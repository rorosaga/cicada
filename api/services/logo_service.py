"""Entity logos (G59) — keyless resolution, fetch, and an on-disk cache.

The ladder, cheapest first, never guessing where a guess would be wrong:

1. explicit ``logo:`` frontmatter (a URL) — the user said so, stop here;
2. the first ``kind: url`` entry in the page's ``sources:`` list (G61);
3. the first URL in the body's ``## Links`` section;
4. ``media.url`` (a saved link's own site);
5. a heuristic, and **only** for ``company``/``tool`` pages: a ``website``
   claim's host if one exists, else ``<slug>.com`` when the name is a single
   token. Never for a ``person`` — "Rodrigo" is not rodrigo.com.

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
headers directly so a 1×1 tracking pixel is rejected without a decode.
"""

from __future__ import annotations

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
from urllib.parse import urljoin, urlparse

from loguru import logger

from api.services import entity_body, markdown_parser
from api.services.auth import cicada_home
from api.services.claims import parse_claims

CACHE_DIR_NAME = "logos"
META_FILENAME = "meta.json"
HIT_TTL = timedelta(days=30)
MISS_TTL = timedelta(days=7)
MAX_BYTES = 512 * 1024
TIMEOUT_SECONDS = 4.0
MIN_PIXELS = 16
USER_AGENT = "Mozilla/5.0 (CicadaBot)"
# Only these page types plausibly have a brand mark worth guessing at.
GUESSABLE_TYPES = {"company", "tool"}

_URL_RE = re.compile(r"https?://[^\s<>\")\]]+")
_ICON_LINK_RE = re.compile(
    r"""<link\b[^>]*\brel\s*=\s*["']?[^"'>]*\b(?:apple-touch-icon|icon)\b[^"'>]*["']?[^>]*>""",
    re.IGNORECASE,
)
_HREF_RE = re.compile(r"""\bhref\s*=\s*["']([^"']+)["']""", re.IGNORECASE)

_EXT_BY_TYPE = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
    "image/svg+xml": "svg",
    "image/x-icon": "ico",
    "image/vnd.microsoft.icon": "ico",
    "image/ico": "ico",
}


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


def logos_dir(bank: str) -> Path:
    """``$CICADA_HOME/logos/<bank>/`` — machine-global, never inside a bank."""
    path = cicada_home() / CACHE_DIR_NAME / (bank or "default")
    path.mkdir(parents=True, exist_ok=True)
    return path


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
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return not (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_unspecified
        or ip.is_multicast
    )


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


def _first_source_url(frontmatter: dict) -> str | None:
    for entry in frontmatter.get("sources") or []:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("kind") or "").strip().lower() != "url":
            continue
        ref = entry.get("ref")
        if isinstance(ref, str) and ref.strip():
            return ref
    return None


def _first_links_url(body: str) -> str | None:
    links = entity_body.parse_sections(body or "").get("Links", "")
    match = _URL_RE.search(links)
    return match.group(0).rstrip(").,") if match else None


def _website_claim_host(body: str) -> str | None:
    try:
        claims = parse_claims(body or "")
    except Exception:
        return None
    for claim in claims:
        if claim.valid_to is not None or claim.superseded_by:
            continue
        if (claim.predicate or "").strip().lower() != "website":
            continue
        host = _host(claim.object)
        if host:
            return host
    return None


def _slug_guess(name: str) -> str | None:
    """``MongoDB`` -> ``mongodb.com``. Only for a single-token name: a
    multi-word name maps to a domain far too unreliably to be worth a fetch."""
    cleaned = (name or "").strip()
    if not cleaned or any(c.isspace() for c in cleaned):
        return None
    slug = re.sub(r"[^a-z0-9-]", "", cleaned.lower())
    return f"{slug}.com" if len(slug) >= 2 else None


def domain_for(frontmatter: dict, body: str) -> str | None:
    """Resolve an entity page to the domain whose icon should represent it."""
    fm = frontmatter or {}

    explicit = _host(fm.get("logo") if isinstance(fm.get("logo"), str) else None)
    if explicit:
        return explicit

    from_source = _host(_first_source_url(fm))
    if from_source:
        return from_source

    from_links = _host(_first_links_url(body))
    if from_links:
        return from_links

    media = fm.get("media")
    if isinstance(media, dict):
        from_media = _host(media.get("url") if isinstance(media.get("url"), str) else None)
        if from_media:
            return from_media

    entity_type = str(fm.get("type") or "").strip().lower()
    if entity_type not in GUESSABLE_TYPES:
        return None

    claimed = _website_claim_host(body)
    if claimed:
        return claimed

    return _slug_guess(str(fm.get("name") or ""))


# --- image sniffing ---------------------------------------------------------


def min_dimension(data: bytes) -> int | None:
    """Smaller of width/height, read straight from the header.

    Returns None for a format we don't sniff (SVG, WEBP) — "unknown" means
    "accept", because refusing a perfectly good vector mark would be worse
    than letting a rare oddity through.
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


async def _http_get(url: str) -> FetchResult:
    """Default fetcher: bounded, keyless, a single hop.

    Redirects are deliberately NOT followed here (``follow_redirects=False``)
    — a 3xx is surfaced via ``location`` and followed by the shared,
    safety-checked loop in ``fetch_logo`` instead, so a redirect target gets
    exactly the same host check as the first request.
    """
    import httpx

    async with httpx.AsyncClient(follow_redirects=False, timeout=TIMEOUT_SECONDS) as client:
        resp = await client.get(url, headers={"User-Agent": USER_AGENT})
        body = resp.content[: MAX_BYTES + 1]
        return FetchResult(
            status=resp.status_code,
            body=body,
            content_type=resp.headers.get("content-type", ""),
            etag=resp.headers.get("etag"),
            location=resp.headers.get("location"),
        )


def _accept(result: FetchResult) -> tuple[bytes, str, str | None] | None:
    if result.status != 200 or not result.body:
        return None
    if len(result.body) > MAX_BYTES:
        return None
    ext = ext_for(result.content_type)
    if ext is None:
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
    """
    if fetcher is None:
        if not fetch_allowed():
            return None
        fetcher = _http_get
    resolver = resolver or _resolve_host

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

    ddg_result = await _get_safely(
        f"https://icons.duckduckgo.com/ip3/{domain}.ico", fetcher=fetcher, resolver=resolver
    )
    return _accept(ddg_result) if ddg_result is not None else None


# --- cache ------------------------------------------------------------------


def _meta_path(bank: str) -> Path:
    return logos_dir(bank) / META_FILENAME


def read_meta(bank: str) -> dict:
    try:
        data = json.loads(_meta_path(bank).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_meta(bank: str, meta: dict) -> None:
    try:
        _meta_path(bank).write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError as exc:
        logger.warning(f"Could not write logo meta for {bank}: {type(exc).__name__}: {exc}")


def is_fresh(entry: dict, *, now: datetime | None = None) -> bool:
    """A hit is good for 30 days, a miss for 7 — a brand mark changes rarely,
    but a site that had no icon last week might have one now."""
    raw = (entry or {}).get("fetched_at")
    if not raw:
        return False
    try:
        fetched = datetime.fromisoformat(str(raw))
    except ValueError:
        return False
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=timezone.utc)
    ttl = MISS_TTL if (entry or {}).get("miss") else HIT_TTL
    return (now or datetime.now(timezone.utc)) - fetched < ttl


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
    meta = read_meta(bank)
    directory = logos_dir(bank)
    return {
        eid for eid, entry in meta.items()
        if isinstance(entry, dict) and not entry.get("miss") and is_fresh(entry)
        and entry.get("ext") and (directory / f"{eid}.{entry['ext']}").exists()
    }


async def ensure_logo(memory_path: Path, entity_id: str, *, fetcher: Fetcher | None = None) -> Path | None:
    """Resolve → cache-check → fetch → store. Returns the file, or None for a
    page with no resolvable domain, a fetch miss, or a gated-off fetch."""
    memory_path = Path(memory_path)
    bank = bank_name(memory_path)

    entry = read_meta(bank).get(entity_id)
    if entry and is_fresh(entry):
        return cached_path(bank, entity_id)

    entity_file = memory_path / "entities" / f"{entity_id}.md"
    if not entity_file.exists():
        return None
    try:
        parsed = markdown_parser.parse(entity_file)
    except Exception:
        return None

    domain = domain_for(parsed.frontmatter or {}, parsed.body or "")
    if not domain:
        return None

    if fetcher is None and not fetch_allowed():
        # Not a miss: we never asked. Caching one would suppress the real fetch
        # for a week once the gate is turned back on.
        return None

    result = await fetch_logo(domain, fetcher=fetcher)
    now = datetime.now(timezone.utc).isoformat()
    meta = read_meta(bank)

    if result is None:
        meta[entity_id] = {"fetched_at": now, "domain": domain, "miss": True, "etag": None, "ext": None}
        write_meta(bank, meta)
        return None

    body, ext, etag = result
    path = logos_dir(bank) / f"{entity_id}.{ext}"
    try:
        path.write_bytes(body)
    except OSError as exc:
        logger.warning(f"Could not cache logo for {entity_id}: {type(exc).__name__}: {exc}")
        return None
    meta[entity_id] = {"fetched_at": now, "domain": domain, "miss": False, "etag": etag, "ext": ext}
    write_meta(bank, meta)
    return path


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
