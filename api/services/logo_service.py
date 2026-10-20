"""Entity logos (G59) — keyless resolution, fetch, and an on-disk cache.

The ladder, from a source and never a guess (G61 S3-b):

1. explicit ``logo:`` frontmatter (a URL) — the user said so, stop here;
2. the first TRUSTED ``website`` source in the page's ``sources:`` (the person's, one they took, or one Cicada's own
   read confirmed — ``fact_sources.trusted``);
3. nothing: the page keeps its monogram. No ``## Links`` fallback, no saved link's site, no ``website`` claim, and no
   ``<name>.com`` guess; never for a ``person`` or a ``media`` page.

Fetching is keyless (apple-touch-icon → the homepage's ``<link rel=icon>`` →
DuckDuckGo's icon service) behind an injectable ``fetcher`` so tests never
touch the network, and is gated by ``CICADA_ALLOW_LOGO_FETCH`` (on by default,
off for the whole test suite). Results — hits *and* misses — are cached under
``$CICADA_HOME/logos/<bank>/``, **never inside a memory bank**: a logo is a
derived, disposable artifact of the outside world, not part of the user's
versioned memory.

SSRF guard (G59 round 1): every URL this module ever hands to a fetcher —
the first request for a rung *and* every redirect hop it bounces through —
passes ``_is_safe_url``: only ``http``/``https`` schemes are eligible, and the
host (a literal IP checked directly, a name resolved via an injectable
``resolver``) must not resolve to anything loopback, private (RFC1918),
link-local (incl. the ``169.254.169.254`` cloud metadata address),
unique-local/ULA, unspecified, or multicast. Redirects are never delegated to
the HTTP client's own follow-redirects — each hop is re-checked here, so a
legitimate public host cannot bounce this fetcher into an internal service.

Pillow is deliberately not a dependency. Whatever the site serves is stored
as-is with the right ``Content-Type``; ``min_dimension`` sniffs PNG/GIF/ICO/JPEG
headers directly so a 1×1 tracking pixel is rejected without a decode. Raster
formats only — an SVG is a scriptable document and this module stores nothing
it would have to sanitize, so ``_accept`` refuses ``image/svg+xml`` and any
payload that sniffs as SVG regardless of the header the site sent.
"""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
import ipaddress
import json
import os
import re
import socket
import struct
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Awaitable, Callable
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from loguru import logger

from api.services import markdown_parser, net_guard
from api.services.auth import cicada_home

CACHE_DIR_NAME = "logos"
META_FILENAME = "meta.json"
# Sidecar for the cross-process `flock` (deliberately NOT `meta.json.lock`, so
# it can never be mistaken for one of `write_meta`'s `meta.json.<pid>.tmp`).
LOCK_FILENAME = "meta.lock"
HIT_TTL = timedelta(days=30)
#: The one place an icon is looked up when the site itself must not be contacted.
SERVICE_URL = "https://icons.duckduckgo.com/ip3/{domain}.ico"
#: A bank's site-icon namespace inside its own logo folder (G166): ``logos/<bank>/sites/``, with its
#: own ``meta.json``. Entity ids cannot contain ``/``, so a site key can never collide with an entity id
#: and ``cached_ids`` (which feeds ``/graph``'s ``has_logo``) never sees a site.
SITES_DIR = "sites"
MISS_TTL = timedelta(days=7)
MAX_BYTES = 512 * 1024
TIMEOUT_SECONDS = 4.0
MIN_PIXELS = 16
USER_AGENT = "Mozilla/5.0 (CicadaBot)"
# The page types whose own site draws a brand mark (`entity_picture.LOGO_TYPES` derives from it). Not a licence to
# guess a domain: nothing guesses one any more.
GUESSABLE_TYPES = {"company", "tool"}

_ICON_LINK_RE = re.compile(
    r"""<link\b[^>]*\brel\s*=\s*["']?[^"'>]*\b(?:apple-touch-icon|icon)\b[^"'>]*["']?[^>]*>""",
    re.IGNORECASE,
)
_HREF_RE = re.compile(r"""\bhref\s*=\s*["']([^"']+)["']""", re.IGNORECASE)

# Raster formats only, deliberately. `image/svg+xml` is NOT here: an SVG is a
# document — it can carry <script>, external <image xlink:href>, and CSS — and
# `GET /entities/{id}/logo` serves these bytes straight back with their stored
# media type. Storing an attacker-chosen SVG (any site can serve one for its
# apple-touch-icon) would put arbitrary script on the logo endpoint's origin.
# There is no sanitizer here and one is not worth carrying for a favicon, so
# the answer is "don't accept the format".
_EXT_BY_TYPE = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
    "image/x-icon": "ico",
    "image/vnd.microsoft.icon": "ico",
    "image/ico": "ico",
}
_SVG_SNIFF_BYTES = 1024


@dataclass
class FetchResult:
    status: int
    body: bytes
    content_type: str
    etag: str | None = None
    location: str | None = None  # a 3xx's Location header, for manual redirect-following


Fetcher = Callable[[str], Awaitable[FetchResult]]
Resolver = Callable[[str], list[str]]

_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
MAX_REDIRECTS = 3


def fetch_allowed() -> bool:
    return os.environ.get("CICADA_ALLOW_LOGO_FETCH", "on").strip().lower() not in {"off", "0", "false"}


#: G61 S3-b — the logo RULE. Version 2: a picture is drawn from a trusted ``website`` source and never from a guess. A
#: bank's entity logos cached under an older rule (a name-guessed domain, a ``## Links`` article's site) are purged ONCE;
#: the marker ``logos/<bank>/.rule`` records the rule a bank's cache was written under. The cache is derived and
#: disposable (TODO ruling 3), so this costs a few fetches and never a fact. The ``sites/`` namespace (G166's site
#: icons) is not entity logos and is never touched.
LOGO_RULE = 2
RULE_FILENAME = ".rule"
_ruled: set[str] = set()


def logos_dir(bank: str) -> Path:
    """``$CICADA_HOME/logos/<bank>/`` — machine-global, never inside a bank. A folder made now was made under the
    current rule, so its marker is written with it; one that predates the rule has none and is purged once
    (:func:`ensure_rule`)."""
    path = cicada_home() / CACHE_DIR_NAME / (bank or "default")
    root = cicada_home() / CACHE_DIR_NAME / (bank or "default").split("/")[0]
    fresh = not root.exists()
    path.mkdir(parents=True, exist_ok=True)
    if fresh:
        try:
            (root / RULE_FILENAME).write_text(str(LOGO_RULE), encoding="utf-8")
        except OSError:
            pass
    return path


@contextlib.contextmanager
def _meta_flock(bank: str):
    """The bank's exclusive ``fcntl`` lock on ``meta.lock`` (degrading to no lock where a filesystem has none)."""
    try:
        handle = open(logos_dir(bank) / LOCK_FILENAME, "a+")
    except OSError:
        yield
        return
    with handle:
        locked = True
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except OSError:
            locked = False
        try:
            yield
        finally:
            if locked:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass


def ensure_rule(bank: str) -> int:
    """Purge a bank's entity logos cached under an older rule, once (marker ``.rule``); a no-op afterwards and for the
    rest of the process. Returns how many cached files it removed. Deletes only the bank's own top-level logo files and
    its ``meta.json`` entries — never ``sites/``, never a page in a bank."""
    if bank in _ruled:
        return 0
    directory = logos_dir(bank)
    marker = directory / RULE_FILENAME
    try:
        current = int(marker.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        current = 0
    purged = 0
    if current < LOGO_RULE:
        keep = {META_FILENAME, LOCK_FILENAME, RULE_FILENAME}
        # Under the same cross-process lock `_record_meta_sync` takes, so a fetch finishing in another process cannot
        # write an entry between the purge and the emptied index.
        with _meta_flock(bank):
            for entry in directory.iterdir():
                if entry.is_file() and entry.name not in keep:
                    try:
                        entry.unlink()
                        purged += 1
                    except OSError:
                        pass
            try:
                write_meta(bank, {})
                marker.write_text(str(LOGO_RULE), encoding="utf-8")
            except OSError as exc:
                logger.warning(f"logo rule purge could not finish for {bank}: {type(exc).__name__}")
                return purged
        logger.info(f"logo cache for {bank} moved to rule {LOGO_RULE}: {purged} cached file(s) dropped")
    _ruled.add(bank)
    return purged


def bank_name(memory_path: Path) -> str:
    return Path(memory_path).name or "default"


# --- SSRF guard --------------------------------------------------------------


def _resolve_host(host: str) -> list[str]:
    """Default resolver: every address ``host`` resolves to, via the system
    resolver. An unresolvable host yields ``[]`` (treated as unsafe — a
    fetcher must never proceed on a host it cannot verify)."""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return []
    return sorted({info[4][0] for info in infos})


def _is_public_ip(ip_str: str) -> bool:
    """One rule for the whole backend (G135 R-R10): `net_guard.is_public_ip`,
    which also refuses the tailnet range this copy used to let through."""
    return net_guard.is_public_ip(ip_str)


def _is_safe_url(url: str, *, resolver: Resolver) -> bool:
    """``http``/``https`` only, and every address the host resolves to must be
    public. Checked before the first request for a rung *and* before every
    redirect hop, so neither a crafted ladder value nor a legitimate public
    host's own redirect can steer a fetch at loopback/private/link-local/ULA/
    unspecified/multicast/metadata addresses."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = parsed.hostname
    if not host:
        return False
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        return _is_public_ip(str(literal))
    addresses = resolver(host)
    return bool(addresses) and all(_is_public_ip(addr) for addr in addresses)


# --- domain resolution ------------------------------------------------------


def _host(raw: str | None) -> str | None:
    """Host of a URL, lowercased, ``www.`` stripped. None when unusable."""
    if not raw:
        return None
    candidate = raw.strip()
    if not candidate:
        return None
    if "://" not in candidate:
        candidate = "https://" + candidate
    try:
        host = (urlparse(candidate).hostname or "").lower()
    except ValueError:
        return None
    if host.startswith("www."):
        host = host[4:]
    return host or None


def _trusted_website_host(frontmatter: dict) -> str | None:
    """The host of the FIRST trusted ``website`` source, best first (``fact_sources.rank``) — and nothing else.

    A page's picture is drawn from its own site, and only from one somebody vouched for: the person's own entry, one
    they took ("Use this site"), or one Cicada's own read confirmed (``verified``). A model's proposal is not trusted
    until then (``fact_sources.trusted``), so a wrong guess draws no mark. The role is the ``website`` predicate (or an
    entry the person added with none). A walled or platform host is skipped: a profile page or a code host is not the
    entity's own mark (``site_sources.is_platform``). A hand-edited scalar (``sources: 5``) is no list of sources
    (r4-people final review, finding 2)."""
    from api.services import fact_sources, site_sources

    sources = frontmatter.get("sources")
    if not isinstance(sources, list):
        return None

    def serves(source: dict, _predicate) -> bool:
        who = str(source.get("added_by") or fact_sources.USER).strip() or fact_sources.USER
        wanted = fact_sources.same_predicate(source.get("predicate"), fact_sources.WEBSITE) or (
            not str(source.get("predicate") or "").strip() and who == fact_sources.USER)
        return wanted and str(source.get("kind") or "").strip().lower() == "url"

    # An explicit `website` entry outranks a bare one the person typed (a verified site must not lose to a link with no
    # role), then `rank` orders each group: the person's, one they took, a verified one.
    ranked = fact_sources.rank(sources, fact_sources.WEBSITE, match=serves)
    explicit = [s for s in ranked if fact_sources.same_predicate(s.get("predicate"), fact_sources.WEBSITE)]
    bare = [s for s in ranked if s not in explicit]
    for source in explicit + bare:
        if not fact_sources.trusted(source):
            continue
        ref = source.get("ref")
        if isinstance(ref, str) and ref.strip():
            host = _host(ref)
            if host and not site_sources.is_platform(host):
                return host
    return None


def domain_for(frontmatter: dict, body: str = "") -> str | None:
    """Resolve an entity page to the domain whose icon should represent it — from a source, never from a guess.

    1. an explicit ``logo:`` (the person said so);
    2. the first TRUSTED ``website`` source (:func:`_trusted_website_host`);
    3. nothing.

    Removed with G61 S3-b: the first ``## Links`` URL (an article about a company drew the article site's icon), a saved
    link's ``media.url``, a ``website`` *claim* (a model's word, unverified) and ``<name>.com`` for a single-token name
    (the "stranger's mark": a small company got a stranger's icon and an AI provider a fireworks show's). A page with no
    trusted site keeps its ring monogram (G146). A person (or a media page) never gets a logo at all: no service is sent
    a person's name (G146/G159)."""
    fm = frontmatter or {}
    if str(fm.get("type") or "").strip().lower() in ("person", "media"):
        return None
    explicit = _host(fm.get("logo") if isinstance(fm.get("logo"), str) else None)
    if explicit:
        return explicit
    return _trusted_website_host(fm)


# --- image sniffing ---------------------------------------------------------


def min_dimension(data: bytes) -> int | None:
    """Smaller of width/height, read straight from the header.

    Returns None for a format we don't sniff (WEBP) — "unknown" means
    "accept", because refusing a perfectly good mark would be worse than
    letting a rare oddity through. (SVG never reaches here: ``_accept``
    refuses the format outright, header *and* sniffed body.)
    """
    if len(data) < 8:
        return None
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        width, height = struct.unpack(">II", data[16:24])
        return min(width, height)
    if data[:6] in (b"GIF87a", b"GIF89a") and len(data) >= 10:
        width, height = struct.unpack("<HH", data[6:10])
        return min(width, height)
    if data[:4] == b"\x00\x00\x01\x00" and len(data) >= 8:
        # ICO directory entry: a 0 byte means 256.
        width = data[6] or 256
        height = data[7] or 256
        return min(width, height)
    if data[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                height, width = struct.unpack(">HH", data[i + 5:i + 9])
                return min(width, height)
            segment = struct.unpack(">H", data[i + 2:i + 4])[0]
            i += 2 + segment
        return None
    return None


def ext_for(content_type: str) -> str | None:
    return _EXT_BY_TYPE.get((content_type or "").split(";", 1)[0].strip().lower())


# --- fetching ---------------------------------------------------------------


async def _http_get(url: str, *, transport=None) -> FetchResult:
    """Default fetcher: bounded, keyless, a single hop.

    Redirects are deliberately NOT followed here (``follow_redirects=False``)
    — a 3xx is surfaced via ``location`` and followed by the shared,
    safety-checked loop in ``fetch_logo`` instead, so a redirect target gets
    exactly the same host check as the first request.
    """
    import httpx

    # Streamed and cut at MAX_BYTES + 1 (Sources v3, 2026-10-19): the ToS rail is "≤ 512 KB read", so an oversize body
    # is never pulled in whole only to be refused; one byte over is enough for `_accept` to say no. The cap is on the
    # RAW bytes off the wire (`aiter_raw`) with `Accept-Encoding: identity` asked, so a compressed bomb can never
    # inflate before the cut — a server that compresses anyway sends bytes no image check accepts. A fresh client per
    # hop carries no cookie from anywhere. `transport` is for tests (`httpx.MockTransport`).
    headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "identity"}
    async with httpx.AsyncClient(follow_redirects=False, timeout=TIMEOUT_SECONDS, transport=transport) as client:
        async with client.stream("GET", url, headers=headers) as resp:
            chunks, size = [], 0
            async for chunk in resp.aiter_raw():
                chunks.append(chunk)
                size += len(chunk)
                if size > MAX_BYTES:
                    break
            body = b"".join(chunks)[: MAX_BYTES + 1]
            return FetchResult(
                status=resp.status_code,
                body=body,
                content_type=resp.headers.get("content-type", ""),
                etag=resp.headers.get("etag"),
                location=resp.headers.get("location"),
            )


def looks_like_svg(data: bytes) -> bool:
    """True when the payload is (or opens as) an SVG/XML document.

    The ``Content-Type`` is attacker-controlled, so a refusal keyed only on the
    header is trivially bypassed by serving SVG bytes as ``image/png``. Sniff
    the head of the body too: an SVG starts with ``<svg``, or with an XML
    prolog / doctype / comment that leads to one.
    """
    head = data[:_SVG_SNIFF_BYTES].lstrip(b"\xef\xbb\xbf").lstrip()
    if not head.startswith(b"<"):
        return False
    return b"<svg" in head.lower()


def _accept(result: FetchResult) -> tuple[bytes, str, str | None] | None:
    if result.status != 200 or not result.body:
        return None
    if len(result.body) > MAX_BYTES:
        return None
    ext = ext_for(result.content_type)
    if ext is None:  # includes image/svg+xml — see _EXT_BY_TYPE
        return None
    if looks_like_svg(result.body):
        logger.debug("logo refused: SVG payload behind a raster content-type")
        return None
    smallest = min_dimension(result.body)
    if smallest is not None and smallest < MIN_PIXELS:
        return None
    return result.body, ext, result.etag


def _icon_href(html: bytes, base_url: str) -> str | None:
    text = html.decode("utf-8", "replace")
    for tag in _ICON_LINK_RE.findall(text):
        href = _HREF_RE.search(tag)
        if href:
            return urljoin(base_url, href.group(1).strip())
    return None


async def _get_safely(url: str, *, fetcher: Fetcher, resolver: Resolver) -> FetchResult | None:
    """One logical GET: validates ``url`` (and every redirect hop, up to
    ``MAX_REDIRECTS``) against the SSRF host policy before ever calling
    ``fetcher``. Returns None for an unsafe URL, a fetcher error, or a
    redirect chain that runs too long — never raises."""
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        if not _is_safe_url(current, resolver=resolver):
            logger.debug(f"logo fetch refused unsafe URL: {current}")
            return None
        try:
            result = await fetcher(current)
        except Exception as exc:  # a dead host must never raise into the caller
            logger.debug(f"logo fetch failed for {current}: {type(exc).__name__}: {exc}")
            return None
        if result.status in _REDIRECT_STATUSES and result.location:
            current = urljoin(current, result.location)
            continue
        return result
    logger.debug(f"logo fetch for {url} exceeded {MAX_REDIRECTS} redirects")
    return None


async def fetch_via_icon_service(
    domain: str, *, fetcher: Fetcher | None = None, resolver: Resolver | None = None
) -> tuple[bytes, str, str | None] | None:
    """The last rung on its own: one GET of the icon service for ``domain``, then the
    same accept rules as any logo (a 404 placeholder is a miss; an SVG or an
    oversize file is refused). ``fetch_logo`` and the walled-site icons share
    this one URL builder — the service is the ONLY thing a walled site's icon
    ever asks (R-RW4: the site itself is never contacted)."""
    if fetcher is None:
        if not fetch_allowed():
            return None
        fetcher = _http_get
    resolver = resolver or _resolve_host
    result = await _get_safely(SERVICE_URL.format(domain=domain), fetcher=fetcher, resolver=resolver)
    return _accept(result) if result is not None else None


async def fetch_site_icon(
    domain: str, *, fetcher: Fetcher | None = None, resolver: Resolver | None = None
) -> tuple[bytes, str, str | None] | None:
    """A site's icon from the icon service, retrying once with ``www.`` prepended
    when the bare domain has none (the service answers 404 for a bare
    ``instagram.com`` and 200 for the ``www.`` form). Both requests go to the
    service only; the miss is the caller's to cache once both fail."""
    got = await fetch_via_icon_service(domain, fetcher=fetcher, resolver=resolver)
    if got is None and not domain.startswith("www."):
        got = await fetch_via_icon_service("www." + domain, fetcher=fetcher, resolver=resolver)
    return got


async def fetch_logo(
    domain: str, *, fetcher: Fetcher | None = None, resolver: Resolver | None = None
) -> tuple[bytes, str, str | None] | None:
    """Try the three rungs in order. Returns ``(body, ext, etag)`` or None.

    An injected ``fetcher`` always runs (the caller supplied the mechanism, so
    there is nothing left to gate); the default HTTP one is gated by
    ``CICADA_ALLOW_LOGO_FETCH``. Every request this makes — the first hop of
    each rung and any redirect it follows — passes the SSRF host check in
    ``_get_safely``/``_is_safe_url``; an injected ``resolver`` lets tests
    simulate DNS without touching the network.

    A login-walled host (``reading_hosts.is_walled``, R-RW4) is never contacted:
    its first two rungs (its own ``apple-touch-icon`` and homepage) are skipped
    and only the icon service is asked.
    """
    if fetcher is None:
        if not fetch_allowed():
            return None
        fetcher = _http_get
    resolver = resolver or _resolve_host

    from api.services import reading_hosts

    if not reading_hosts.is_walled(f"https://{domain}/"):
        homepage = f"https://{domain}/"
        candidates = [f"https://{domain}/apple-touch-icon.png"]

        for url in candidates:
            result = await _get_safely(url, fetcher=fetcher, resolver=resolver)
            accepted = _accept(result) if result is not None else None
            if accepted:
                return accepted

        page = await _get_safely(homepage, fetcher=fetcher, resolver=resolver)
        if page is not None and page.status == 200 and page.body:
            href = _icon_href(page.body, homepage)
            if href:
                result = await _get_safely(href, fetcher=fetcher, resolver=resolver)
                accepted = _accept(result) if result is not None else None
                if accepted:
                    return accepted

    return await fetch_via_icon_service(domain, fetcher=fetcher, resolver=resolver)


# --- cache ------------------------------------------------------------------


def meta_path(bank: str) -> Path:
    """This bank's logo index, **without creating anything**.

    ``logos_dir`` mkdirs; this doesn't, because ``sync_service.components``
    stats it on every version poll (~1/s) and must not conjure a cache
    directory for a bank that has never had a logo fetched. Honours the same
    ``$CICADA_HOME`` override ``auth.cicada_home`` uses.
    """
    raw = os.environ.get("CICADA_HOME") or str(Path.home() / ".cicada")
    return Path(raw).expanduser() / CACHE_DIR_NAME / (bank or "default") / META_FILENAME


def read_meta(bank: str) -> dict:
    try:
        data = json.loads(meta_path(bank).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_meta(bank: str, meta: dict) -> None:
    """Replace the index atomically (tmp + ``os.replace``).

    Callers inside this process are serialised by ``_lock("meta")``; the atomic
    rename is for the cross-process case (the CLI sleep cycle and the running
    API server share one cache), so a concurrent reader never sees a half-
    written file.
    """
    path = logos_dir(bank) / META_FILENAME  # mkdirs; the write needs the dir
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        logger.warning(f"Could not write logo meta for {bank}: {type(exc).__name__}: {exc}")
        try:
            tmp.unlink()
        except OSError:
            pass


def is_fresh(entry: dict, *, now: datetime | None = None) -> bool:
    """A hit is good for 30 days, a miss for 7 — a brand mark changes rarely,
    but a site that had no icon last week might have one now."""
    fetched = _fetched_at(entry)
    if fetched is None:
        return False
    ttl = MISS_TTL if (entry or {}).get("miss") else HIT_TTL
    return (now or datetime.now(timezone.utc)) - fetched < ttl


def _fetched_at(entry: dict) -> datetime | None:
    """The entry's ``fetched_at`` as an aware datetime, or None if unusable."""
    raw = (entry or {}).get("fetched_at")
    if not raw:
        return None
    try:
        stamp = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def expiry_state(bank: str, *, now: datetime | None = None) -> tuple[int, float | None]:
    """``(entries past their TTL, epoch of the next expiry)`` for this index.

    Nothing on disk changes when an entry merely *ages* past its TTL, so a
    version component built from ``meta.json``'s mtime alone cannot see it —
    and ``/graph``'s ``has_logo`` (which is computed from
    :func:`cached_ids`, i.e. from :func:`is_fresh` at read time) silently
    flips true→false behind an ETag that never moved. The first number moves
    on every expiry, giving ``sync_service`` something to fold in; the second
    says when it will next move, so the scan runs once per expiry rather than
    once per poll.
    """
    now = now or datetime.now(timezone.utc)
    expired = 0
    soonest: float | None = None
    for entry in read_meta(bank).values():
        if not isinstance(entry, dict):
            continue
        fetched = _fetched_at(entry)
        if fetched is None:
            expired += 1  # an unusable stamp is never fresh
            continue
        due = fetched + (MISS_TTL if entry.get("miss") else HIT_TTL)
        if due <= now:
            expired += 1
        elif soonest is None or due.timestamp() < soonest:
            soonest = due.timestamp()
    return expired, soonest


def page_edited_since_fetch(entity_file: Path, entry: dict) -> bool:
    """True when the entity page was written after its logo was cached.

    The logo domain is *resolved from the page* (``logo:``, a ``sources:``
    URL, the first ``## Links`` URL, ``media.url``, a ``website`` claim). Edit
    any of those and a 30-day-fresh cache entry kept serving the old brand.
    An mtime compare answers it without a parse, let alone a fetch — so
    ``/graph`` (which only reads the index) still touches no network.
    """
    try:
        mtime = entity_file.stat().st_mtime
    except OSError:
        return False  # no page to have been edited
    fetched = _fetched_at(entry)
    if fetched is None:
        return True
    return mtime > fetched.timestamp()


def cached_path(bank: str, entity_id: str) -> Path | None:
    """The cached logo file for this entity, if there is a fresh hit on disk."""
    entry = read_meta(bank).get(entity_id)
    if not entry or entry.get("miss") or not is_fresh(entry):
        return None
    ext = entry.get("ext")
    if not ext:
        return None
    path = logos_dir(bank) / f"{entity_id}.{ext}"
    return path if path.exists() else None


def cached_ids(bank: str) -> set[str]:
    """Every entity id with a fresh cached logo. Read-only, no network — this
    is what ``GET /graph`` uses to fill ``has_logo``."""
    ensure_rule(bank)
    meta = read_meta(bank)
    directory = logos_dir(bank)
    return {
        eid for eid, entry in meta.items()
        if isinstance(entry, dict) and not entry.get("miss") and is_fresh(entry)
        and entry.get("ext") and (directory / f"{eid}.{entry['ext']}").exists()
    }


def missed_ids(bank: str) -> dict[str, float]:
    """Every entity id with a FRESH recorded miss, mapped to when it was recorded (epoch seconds). Read-only, no
    network — the picture precedence's logo rung is "cached, or not yet known to miss" (G146 plan R-PE9), and a page
    edited after its miss is re-resolved exactly as `page_edited_since_fetch` re-resolves it for the logo endpoint."""
    ensure_rule(bank)
    out: dict[str, float] = {}
    for eid, entry in read_meta(bank).items():
        if isinstance(entry, dict) and entry.get("miss") and is_fresh(entry):
            fetched = _fetched_at(entry)
            if fetched is not None:
                out[eid] = fetched.timestamp()
    return out


# --- concurrency -------------------------------------------------------------
#
# `_lock("meta")` serialises the read-modify-write of a bank's `meta.json` so
# a fetch that finishes second can't drop the entry the first one wrote — its
# image would sit on disk unreferenced, silently re-fetched next request while
# `has_logo` flickers. (Within one loop the read and the write are adjacent, so
# the window opens when a second loop or a second process — the CLI sleep cycle
# beside the running server — writes the same index; that case is closed by the
# `fcntl` lock in `_record_meta_sync`, with `write_meta`'s atomic rename keeping
# concurrent *readers* from ever seeing a half-written file.)
#
# `_lock(f"entity:{bank}/{id}")` makes two concurrent requests for the same
# entity run the three-rung fetch ladder once: the loser waits and then finds a
# fresh cache entry. (The inbox row and the detail card for one entity render
# together, so this is the common case, not a corner one.)
#
# Locks are cached per running loop rather than created at import: an
# `asyncio.Lock` binds to the first loop that contends on it, and this process
# runs more than one loop over its life (the CLI sleep cycle, and every
# `asyncio.run` in the test suite). The cache is dropped wholesale when the
# running loop changes, so it holds a strong reference to at most one loop and
# never grows without bound.
_locks: dict[str, asyncio.Lock] = {}
_lock_loop: asyncio.AbstractEventLoop | None = None


def _lock(name: str) -> asyncio.Lock:
    global _lock_loop
    loop = asyncio.get_running_loop()
    if loop is not _lock_loop:
        _lock_loop = loop
        _locks.clear()
    lock = _locks.get(name)
    if lock is None:
        lock = _locks[name] = asyncio.Lock()
    return lock


async def ensure_logo(memory_path: Path, entity_id: str, *, fetcher: Fetcher | None = None) -> Path | None:
    """Resolve → cache-check → fetch → store. Returns the file, or None for a
    page with no resolvable domain, a fetch miss, or a gated-off fetch."""
    memory_path = Path(memory_path)
    bank = bank_name(memory_path)
    async with _lock(f"entity:{bank}/{entity_id}"):
        return await _ensure_logo_locked(memory_path, bank, entity_id, fetcher=fetcher)


async def _ensure_logo_locked(
    memory_path: Path, bank: str, entity_id: str, *, fetcher: Fetcher | None = None
) -> Path | None:
    entity_file = memory_path / "entities" / f"{entity_id}.md"
    ensure_rule(bank)
    entry = read_meta(bank).get(entity_id)
    cached_ok = bool(entry) and is_fresh(entry)
    # An edit to the page can change which domain this entity resolves to, so a
    # fresh entry is only good while the page is older than it.
    if cached_ok and not page_edited_since_fetch(entity_file, entry):
        return cached_path(bank, entity_id)

    if not entity_file.exists():
        return None
    try:
        parsed = markdown_parser.parse(entity_file)
    except Exception:
        # Unreadable page: keep serving whatever is already cached.
        return cached_path(bank, entity_id) if cached_ok else None

    domain = domain_for(parsed.frontmatter or {}, parsed.body or "")

    # The page changed since the last fetch, but re-resolving may still land on
    # the SAME domain (Sleep bumping `last_referenced`/`version` every cycle,
    # say) — that's an unrelated edit, not a rebrand. Refresh the fetch stamp
    # so the mtime compare settles and skip the network ladder entirely,
    # instead of re-running it for every active entity on every Sleep cycle.
    if cached_ok and domain == entry.get("domain"):
        await _record_meta(
            bank, entity_id, {**entry, "fetched_at": datetime.now(timezone.utc).isoformat()},
        )
        return cached_path(bank, entity_id)

    if not domain:
        # No domain resolves (no trusted website source, or the page is not a brand): a cached mark is a mark drawn
        # from something that is no longer there — a stranger's, once a name guess put it there — so it goes, and the
        # miss is recorded (G61 S3-b). The page keeps its monogram until it has a site somebody vouched for.
        if entry and not entry.get("miss"):
            for old in (logos_dir(bank).glob(f"{entity_id}.*")):
                try:
                    old.unlink()
                except OSError:
                    pass
        if not (entry and entry.get("miss") and cached_ok):
            await _record_meta(
                bank, entity_id,
                {"fetched_at": datetime.now(timezone.utc).isoformat(), "domain": None, "miss": True, "etag": None,
                 "ext": None},
            )
        return None

    if fetcher is None and not fetch_allowed():
        # Not a miss: we never asked. Caching one would suppress the real fetch
        # for a week once the gate is turned back on. A page edit alone must not
        # cost the user the logo they already have, so keep serving the cache.
        return cached_path(bank, entity_id) if cached_ok else None

    result = await fetch_logo(domain, fetcher=fetcher)
    now = datetime.now(timezone.utc).isoformat()

    if result is None:
        if cached_ok and not (entry or {}).get("miss"):
            # This was a re-validation (the page changed), not a first fetch: a
            # site being down for a minute must not cost the user a mark we
            # already have. Keep the entry and retry when its own TTL expires.
            logger.debug(f"logo re-validation for {entity_id} failed; keeping the cached mark")
            return cached_path(bank, entity_id)
        await _record_meta(
            bank, entity_id,
            {"fetched_at": now, "domain": domain, "miss": True, "etag": None, "ext": None},
        )
        return None

    body, ext, etag = result
    path = logos_dir(bank) / f"{entity_id}.{ext}"
    try:
        path.write_bytes(body)
    except OSError as exc:
        logger.warning(f"Could not cache logo for {entity_id}: {type(exc).__name__}: {exc}")
        return None
    await _record_meta(
        bank, entity_id,
        {"fetched_at": now, "domain": domain, "miss": False, "etag": etag, "ext": ext},
    )
    return path


def _record_meta_sync(bank: str, entity_id: str, entry: dict) -> None:
    """Read-modify-write one entry under an exclusive ``fcntl`` file lock.

    ``_lock("meta")`` only serialises coroutines in THIS process, and
    ``write_meta``'s tmp+``os.replace`` only buys atomicity — neither makes the
    read-modify-write merge-safe across processes. The CLI sleep cycle warms
    logos beside a running API server, and without this both would load their
    own copy of the index and the second ``os.replace`` would silently drop the
    first's entry (its image left on disk, unreferenced, ``has_logo`` flickering
    until something re-fetched it). ``flock`` on a sidecar lock file closes that
    window; the lock is released with the ``with`` block, and a filesystem that
    cannot lock degrades to the previous behavior rather than failing the fetch.
    """
    lock_path = logos_dir(bank) / LOCK_FILENAME
    try:
        handle = open(lock_path, "a+")
    except OSError as exc:
        logger.warning(f"logo meta lock unavailable for {bank}: {type(exc).__name__}: {exc}")
        meta = read_meta(bank)
        meta[entity_id] = entry
        write_meta(bank, meta)
        return
    with handle:
        locked = True
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except OSError as exc:  # e.g. a filesystem without flock support
            locked = False
            logger.debug(f"flock unsupported for {lock_path}: {type(exc).__name__}: {exc}")
        try:
            meta = read_meta(bank)
            meta[entity_id] = entry
            write_meta(bank, meta)
        finally:
            if locked:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass


async def _record_meta(bank: str, entity_id: str, entry: dict) -> None:
    """Read-modify-write one entry under ``_lock("meta")`` + a file lock.

    The re-read *inside* the lock is the point: the copy this coroutine loaded
    before its ``await``ed fetch is stale by now. The blocking file lock runs
    off the event loop so a second process holding it can't stall the server.
    """
    async with _lock("meta"):
        await asyncio.to_thread(_record_meta_sync, bank, entity_id, entry)


async def warm_logos(memory_path: Path, *, limit: int = 50, fetcher: Fetcher | None = None) -> int:
    """Sleep tail step: fetch missing logos for the busiest company/tool pages
    so the common ones are ready before the user ever opens them.

    Bounded by ``limit`` and never raises — a cycle must not fail because a
    CDN was down.
    """
    from api.services import bank_index

    memory_path = Path(memory_path)
    if fetcher is None and not fetch_allowed():
        return 0
    ensure_rule(bank_name(memory_path))

    candidates: list[tuple[int, str]] = []
    for f in bank_index.files(memory_path, "entities"):
        fm = f.frontmatter or {}
        if str(fm.get("type") or "").lower() not in GUESSABLE_TYPES:
            continue
        related = fm.get("related") or []
        candidates.append((len(related) if isinstance(related, list) else 0, f.stem))
    # Highest degree first; the id breaks ties so a warm run is deterministic.
    candidates.sort(key=lambda pair: (-pair[0], pair[1]))

    warmed = 0
    for _, entity_id in candidates[:limit]:
        try:
            if await ensure_logo(memory_path, entity_id, fetcher=fetcher) is not None:
                warmed += 1
        except Exception as exc:
            logger.debug(f"warm_logos: {entity_id} failed: {type(exc).__name__}: {exc}")
    return warmed


# --- site icons (G166) --------------------------------------------------------------------------------------


def site_bank(bank: str) -> str:
    """The cache namespace of a bank's site icons: ``<bank>/sites`` — the same helpers
    (``logos_dir``, ``read_meta``, ``_record_meta``, the flock, the TTLs) run over it."""
    return f"{bank or 'default'}/{SITES_DIR}"


async def ensure_site_icon(
    memory_path: Path, site: str, domain: str, *, fetcher: Fetcher | None = None
) -> Path | None:
    """Resolve -> cache-check -> ONE icon-service lookup (with the ``www.`` retry) -> store.

    ``site`` is the key (``reading_hosts.site_of``) the cache is filed under;
    ``domain`` is the name the icon service is told (``reading_hosts.icon_host``).
    The site itself is never contacted. Gated by ``CICADA_ALLOW_LOGO_FETCH``
    exactly as ``ensure_logo`` is, and never caches a "never asked" as a miss.
    A hit lasts 30 days, a miss 7."""
    bank = site_bank(bank_name(Path(memory_path)))
    async with _lock(f"site:{bank}/{site}"):
        entry = read_meta(bank).get(site)
        cached_ok = bool(entry) and is_fresh(entry)
        if cached_ok:
            return cached_path(bank, site)
        if fetcher is None and not fetch_allowed():
            return None
        result = await fetch_site_icon(domain, fetcher=fetcher)
        now = datetime.now(timezone.utc).isoformat()
        if result is None:
            await _record_meta(bank, site, {"fetched_at": now, "domain": domain, "miss": True, "etag": None, "ext": None})
            return None
        body, ext, etag = result
        path = logos_dir(bank) / f"{site}.{ext}"
        try:
            path.write_bytes(body)
        except OSError as exc:
            logger.warning(f"Could not cache a site icon: {type(exc).__name__}: {exc}")
            return None
        await _record_meta(bank, site, {"fetched_at": now, "domain": domain, "miss": False, "etag": etag, "ext": ext})
        return path



# --- a saved link's own site (owner ruling 2026-10-19; discovery amended 2026-10-20) ---------------------------------
#
# The owner, 2026-10-19: a saved link's row shows the site's own icon, asked of the site itself — never through a
# third-party service (the icon service is never told what the person saved) — only when the app asks for a list the
# person opened (never from Sleep, never a whole bank), the registrable domain of the saved link's own URL only, through
# the SSRF guard and the ToS rail, behind `CICADA_ALLOW_LOGO_FETCH`, cached outside every bank with misses cached too;
# a failure is a monogram, never an error.
#
# Amended (owner 2026-10-20: "when I open the website I can clearly see a favicon in the Chrome tab"): the two fixed
# paths alone missed every site that declares its icon in its HTML at another path, on a CDN, or behind a same-site
# redirect. Discovery now goes the way a browser does: the homepage (same-registrable-domain redirects only, e.g. → www),
# its `<link rel>` icon declarations (icon, shortcut icon, apple-touch-icon; sizes; light/dark `media`), relative hrefs
# resolved against the page's final URL (or its `<base href>`), the best raster first, then the two fixed paths. A URL
# the page itself declares may live on another host (a CDN) — https only, through the SSRF guard, its redirects kept on
# that host's or the site's registrable domain, and accepted only when the content-type says image AND the bytes sniff
# as a raster. The whole discovery has one 4 s budget per site; every response is cut at 512 KB.
#
# SVG stays a miss: there is no in-process rasteriser here (Pillow is deliberately not a dependency, and a hand-rolled
# SVG renderer is the opposite of safe), and serving SVG to the app as-is would put a scriptable document on the
# backend's origin. A `data:` icon is decoded only when it is base64 raster (PNG/ICO/GIF/JPEG/WebP), its decoded size
# capped and its bytes sniffed like any download; a `data:image/svg+xml` icon is a miss.

#: The cache namespace: `logos/<bank>/sites/own/` — beside, never mixed with, the icon-service icons in `sites/`, so a miss
#: on one path never hides the other.
OWN_SITE_DIR = "own"
OWN_SITE_PATHS = ("/apple-touch-icon.png", "/favicon.ico")
#: The discovery's version, stamped on every own-site cache entry. A miss recorded by an older discovery (the two fixed
#: paths of 2026-10-19) is asked once more with this one; hits stay.
OWN_SITE_DISCOVERY = 2
#: The whole discovery for one site — homepage, declared icons, fixed paths — fits in this many seconds (the ToS rail).
OWN_SITE_BUDGET_SECONDS = TIMEOUT_SECONDS
#: At most this many declared icons are asked, best first, before the fixed paths.
MAX_DECLARED_ICONS = 3
_ICON_RELS = {"icon", "apple-touch-icon", "apple-touch-icon-precomposed"}
#: A site that says no: a miss at once, the next path never tried, nothing retried with other headers (the ToS rail).
_BLOCK_STATUSES = {401, 403, 407, 451}
_MAGIC_EXT = ((b"\x89PNG\r\n\x1a\n", "png"), (b"\x00\x00\x01\x00", "ico"), (b"GIF8", "gif"), (b"\xff\xd8\xff", "jpg"))
#: A response that says it is a document is never an icon, whatever its bytes say.
_DOCUMENT_TYPES = ("text/html", "application/xhtml", "image/svg", "text/xml", "application/xml")
_RASTER_DATA_TYPES = {"image/png", "image/x-icon", "image/vnd.microsoft.icon", "image/ico", "image/gif", "image/jpeg",
                      "image/jpg", "image/webp"}


def own_site_bank(bank: str) -> str:
    return f"{site_bank(bank)}/{OWN_SITE_DIR}"


def own_site_domain(url: str) -> str | None:
    """The one name a saved link's own icon is asked of: the registrable domain of the link's URL
    (`reading_hosts.site_of`), when it is a public-looking domain and not a login-walled family — else None (the row
    keeps its bundled family mark or its monogram, and nothing is asked)."""
    from api.services import reading_hosts

    site = reading_hosts.site_of(url or "")
    if not site or "." not in site or not reading_hosts.valid_site_key(site):
        return None
    if reading_hosts.is_walled(f"https://{site}/") or not reading_hosts.is_public_name(site):
        return None
    return site


def _sniff_ext(body: bytes) -> str | None:
    if body[:4] == b"RIFF" and body[8:12] == b"WEBP":
        return "webp"
    return next((e for magic, e in _MAGIC_EXT if body.startswith(magic)), None)


def _raster(body: bytes, content_type: str, etag: str | None, *, image_type: bool) -> tuple[bytes, str, str | None] | None:
    """An icon only when its BYTES are a raster (PNG/ICO/GIF/JPEG/WebP magic) — never SVG, never over 512 KB, never
    below `MIN_PIXELS`. The content-type may never claim a document (an SPA answering `/favicon.ico` with its HTML);
    with `image_type` it must also say `image/*` (an icon declared on another host). The extension comes from the
    bytes, not the header."""
    if not body or len(body) > MAX_BYTES or looks_like_svg(body):
        return None
    ctype = (content_type or "").split(";", 1)[0].strip().lower()
    if ctype.startswith(_DOCUMENT_TYPES) or (image_type and not ctype.startswith("image/")):
        return None
    ext = _sniff_ext(body)
    if ext is None:
        return None
    smallest = min_dimension(body)
    if smallest is not None and smallest < MIN_PIXELS:
        return None
    return body, ext, etag


def _sniffed(result: FetchResult) -> tuple[bytes, str, str | None] | None:
    """A response from the site itself: a favicon served as `application/octet-stream` or `text/plain` is still an
    icon when its bytes say so; one that says HTML is not."""
    if result.status != 200:
        return None
    return _raster(result.body, result.content_type, result.etag, image_type=False)


@dataclass
class _IconLink:
    url: str
    rel: frozenset
    size: int | None
    dark: bool
    light: bool
    order: int

    def rank(self) -> tuple:
        # The light-scheme (or scheme-less) icon before a dark one; then the largest raster of at least 32 px; then
        # one of unknown size; then a small one; ties in the page's own order.
        size = self.size
        bucket = 0 if size is not None and size >= 32 else (1 if size is None else 2)
        return (self.dark and not self.light, bucket, -(size or 0), self.order)


class _IconLinkParser(HTMLParser):
    """`<link rel>` icon declarations and the first `<base href>`, read with the standard library's tokenizer — no
    script runs, nothing is fetched, entities are only the HTML ones. Stops collecting after 64 links."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.base: str | None = None
        self.links: list[dict] = []

    def handle_starttag(self, tag, attrs):
        if tag == "base" and self.base is None:
            href = dict(attrs).get("href")
            if href:
                self.base = href.strip()
        elif tag == "link" and len(self.links) < 64:
            self.links.append({k.lower(): (v or "") for k, v in attrs})

    handle_startendtag = handle_starttag


def _declared_size(sizes: str) -> int | None:
    best = None
    for token in (sizes or "").lower().split():
        match = re.fullmatch(r"(\d{1,4})x(\d{1,4})", token)
        if match:
            side = min(int(match.group(1)), int(match.group(2)))
            best = side if best is None else max(best, side)
    return best


def declared_icons(html: bytes, page_url: str) -> list[_IconLink]:
    """The raster icons a homepage declares, best first. Skips `mask-icon` and anything typed or named SVG (a miss
    here, see above), a `data:` icon that is not base64 raster, and any href that resolves to something but https."""
    parser = _IconLinkParser()
    try:
        parser.feed(html[:MAX_BYTES].decode("utf-8", "replace"))
        parser.close()
    except Exception:  # a malformed page is a page with no declarations
        pass
    base = urljoin(page_url, parser.base) if parser.base else page_url
    found: dict[str, _IconLink] = {}
    for order, attrs in enumerate(parser.links):
        rel = frozenset(attrs.get("rel", "").lower().split())
        href = attrs.get("href", "").strip()
        if not href or not rel & _ICON_RELS or "mask-icon" in rel:
            continue
        kind = attrs.get("type", "").strip().lower()
        if "svg" in kind:
            continue
        if href.lower().startswith("data:"):
            if _data_icon_type(href) is None:
                continue
            url = href
        else:
            url = urljoin(base, href)
            parsed = urlparse(url)
            if parsed.scheme != "https" or parsed.path.lower().endswith(".svg"):
                continue
        media = attrs.get("media", "").lower().replace(" ", "")
        size = _declared_size(attrs.get("sizes", ""))
        if size is None and rel & {"apple-touch-icon", "apple-touch-icon-precomposed"}:
            size = 180  # Apple's documented size when none is declared
        link = _IconLink(url=url, rel=rel, size=size, dark="prefers-color-scheme:dark" in media,
                         light="prefers-color-scheme:light" in media, order=order)
        if url not in found or link.rank() < found[url].rank():
            found[url] = link
    return sorted(found.values(), key=_IconLink.rank)


def _data_icon_type(uri: str) -> str | None:
    """The media type of a base64 raster `data:` URI, else None (SVG, percent-encoded, unknown)."""
    head, sep, _ = uri.partition(",")
    if not sep:
        return None
    parts = [p.strip().lower() for p in head[5:].split(";")]
    if "base64" not in parts[1:] or parts[0] not in _RASTER_DATA_TYPES:
        return None
    return parts[0]


def _decode_data_icon(uri: str) -> tuple[bytes, str, str | None] | None:
    """A `data:` icon's bytes, the decoded size capped at 512 KB BEFORE decoding (from the encoded length), then the same
    raster rules as a download — the declared type must agree that it is an image and the bytes must sniff as one."""
    import base64
    import binascii

    kind = _data_icon_type(uri)
    if kind is None:
        return None
    payload = "".join(uri.partition(",")[2].split())
    if len(payload) > (MAX_BYTES * 4) // 3 + 4:
        return None
    try:
        body = base64.b64decode(payload, validate=False)
    except (binascii.Error, ValueError):
        return None
    return _raster(body, kind, None, image_type=True)


async def _follow(url: str, allowed: Callable[[str], bool], *, fetcher: Fetcher,
                  resolver: Resolver | None) -> tuple[FetchResult, str] | None:
    """One GET whose every hop (≤ `MAX_REDIRECTS`) passes `allowed`, is no login-walled host and passes the SSRF check
    — a hop anywhere else is a miss, never followed. Returns the response and the URL that answered it."""
    from api.services import reading_hosts

    current = url
    for _ in range(MAX_REDIRECTS + 1):
        if not allowed(current) or reading_hosts.is_walled(current):
            return None
        # The route runs per visible row, so DNS never blocks the event loop: net_guard's async check (off-loop), or
        # an injected resolver (tests).
        safe = (net_guard.is_fetchable_url(current, resolver=resolver) if resolver is not None
                else await net_guard.is_fetchable_url_async(current))
        if not safe:
            return None
        try:
            result = await fetcher(current)
        except Exception as exc:  # a dead host is a monogram, never an error
            logger.debug(f"own-site icon fetch failed: {type(exc).__name__}")
            return None
        if result.status in _REDIRECT_STATUSES and result.location:
            current = urljoin(current, result.location)
            continue
        return result, current
    return None


def _on_site(site: str) -> Callable[[str], bool]:
    from api.services import reading_hosts

    return lambda url: reading_hosts.site_of(url) == site


async def _get_on_site(url: str, site: str, *, fetcher: Fetcher, resolver: Resolver | None) -> FetchResult | None:
    """One GET that never leaves `site` (same registrable domain on every hop)."""
    got = await _follow(url, _on_site(site), fetcher=fetcher, resolver=resolver)
    return got[0] if got else None


class _Blocked(Exception):
    """The site said no (401/403/407/451): the whole discovery stops, nothing else is asked."""


async def _discover(site: str, *, fetcher: Fetcher, resolver: Resolver | None) -> tuple[bytes, str, str | None] | None:
    from api.services import reading_hosts

    tried: set[str] = set()
    asked: list[str] = []

    async def counted(url: str) -> FetchResult:
        asked.append(url)
        return await fetcher(url)

    host = site
    page = await _follow(f"https://{site}/", _on_site(site), fetcher=counted, resolver=resolver)
    if page is None and not asked and not site.startswith("www."):
        # Nothing was asked: the bare registrable domain has no public address of its own (some sites answer only on
        # their www. host). Ask www. once — the same site, its own SSRF check.
        page = await _follow(f"https://www.{site}/", _on_site(site), fetcher=counted, resolver=resolver)
        if asked:  # the www. host answered (even with a redirect off the site): the fixed paths are asked there
            host = f"www.{site}"
    if page is not None:
        result, final_url = page
        host = urlparse(final_url).hostname or host  # on the site: `_follow` checked every hop
        if result.status in _BLOCK_STATUSES:
            raise _Blocked
        ctype = (result.content_type or "").lower()
        if result.status == 200 and result.body and ("html" in ctype or not ctype):
            for link in declared_icons(result.body, final_url)[:MAX_DECLARED_ICONS]:
                if link.url.startswith("data:"):
                    got = _decode_data_icon(link.url)
                    if got:
                        return got
                    continue
                tried.add(link.url)
                declared_site = reading_hosts.site_of(link.url)
                own = declared_site == site
                allowed = (lambda u, d=declared_site: urlparse(u).scheme == "https"
                           and reading_hosts.site_of(u) in (d, site))
                got = await _follow(link.url, allowed, fetcher=fetcher, resolver=resolver)
                if got is None:
                    continue
                answer = got[0]
                if answer.status in _BLOCK_STATUSES and own:
                    raise _Blocked
                if answer.status == 200:
                    icon = _raster(answer.body, answer.content_type, answer.etag, image_type=not own)
                    if icon:
                        return icon
    for path in OWN_SITE_PATHS:
        url = f"https://{host}{path}"
        if url in tried:
            continue
        result = await _get_on_site(url, site, fetcher=fetcher, resolver=resolver)
        if result is None:
            continue
        if result.status in _BLOCK_STATUSES:
            raise _Blocked
        accepted = _sniffed(result)
        if accepted:
            return accepted
    return None


async def fetch_own_site_icon(
    site: str, *, fetcher: Fetcher | None = None, resolver: Resolver | None = None
) -> tuple[bytes, str, str | None] | None:
    """The site's own icon, found the way a browser finds it (see the section note): the homepage's declared icons,
    best first, then `OWN_SITE_PATHS`; the first acceptable raster wins; a block (401/403/407/451) from the site stops
    at once; the whole discovery fits `OWN_SITE_BUDGET_SECONDS`. Never the icon service."""
    if fetcher is None:
        if not fetch_allowed():
            return None
        fetcher = _http_get
    try:
        return await asyncio.wait_for(_discover(site, fetcher=fetcher, resolver=resolver), OWN_SITE_BUDGET_SECONDS)
    except _Blocked:
        return None
    except asyncio.TimeoutError:
        logger.debug("own-site icon discovery ran out of its time budget")
        return None


def _own_entry_current(entry: dict) -> bool:
    """A fresh entry, unless it is a miss an older discovery recorded — that one is asked once more."""
    if not entry or not is_fresh(entry):
        return False
    return not (entry.get("miss") and int(entry.get("v") or 1) < OWN_SITE_DISCOVERY)


async def ensure_own_site_icon(memory_path: Path, site: str, *, fetcher: Fetcher | None = None) -> Path | None:
    """Cache-check -> at most one `fetch_own_site_icon` -> store, under `logos/<bank>/sites/own/`. A hit lasts 30 days,
    a miss 7 (a miss from before `OWN_SITE_DISCOVERY` is retried once); with the gate off (and no injected fetcher)
    nothing is asked and nothing is recorded."""
    bank = own_site_bank(bank_name(Path(memory_path)))
    async with _lock(f"own:{bank}/{site}"):
        entry = read_meta(bank).get(site)
        if _own_entry_current(entry):
            return cached_path(bank, site)
        if fetcher is None and not fetch_allowed():
            return None
        result = await fetch_own_site_icon(site, fetcher=fetcher)
        now = datetime.now(timezone.utc).isoformat()
        if result is None:
            await _record_meta(bank, site, {"fetched_at": now, "miss": True, "etag": None, "ext": None,
                                            "v": OWN_SITE_DISCOVERY})
            return None
        body, ext, etag = result
        path = logos_dir(bank) / f"{site}.{ext}"
        try:
            path.write_bytes(body)
        except OSError as exc:
            logger.warning(f"Could not cache a site icon: {type(exc).__name__}: {exc}")
            return None
        await _record_meta(bank, site, {"fetched_at": now, "miss": False, "etag": etag, "ext": ext,
                                        "v": OWN_SITE_DISCOVERY})
        return path
