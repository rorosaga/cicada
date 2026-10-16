"""A saved link's, video's or paper's own picture — fetched once, stored outside every bank, served from then on.

Before this module the backend never held a thumbnail: ``entity_picture.resolve`` handed the provider's URL to the
app, which fetched it itself (so a relative ``og:image`` showed nothing, a dead link blanked the card, and a web
client would have had to reach every provider). Now one place decides a media page's preview, one place fetches it,
and ``GET /entities/{id}/preview`` serves the stored copy.

**Where a preview comes from** (:func:`source_for`, pure — the wire's ``?v=`` is derived from it):

1. the page's own stored image — ``media.thumbnail``: the saved page's ``og:image`` / ``twitter:image`` (made
   absolute against the page's URL, so a relative tag finally counts) or a provider's oEmbed ``thumbnail_url``;
2. a YouTube video with none stored (oEmbed refuses a video whose embedding is off): the video's standard still,
   ``i.ytimg.com/vi/<id>/hqdefault.jpg``, built from the id ``video_urls.resolve`` already validated. It is a still
   image on Cicada's own pin, not the video and not a stream (the G162 rail: never download a video, never derive a
   stream), and nothing a provider returned is used to build it;
3. a PDF the person saved as a direct link (not an arXiv or DOI paper — G133 never fetches one — and not a walled
   host): page 1, rendered in the backend (``pdf_page``); a saved direct image link is its own picture.

A ``person`` page never has one (it is not a ``media`` page), and a paper keyed by arXiv/DOI has none of the three:
its picture is the person's own PDF (``POST /entities/{id}/picture/pdf``, rung 1) or its monogram.

**The cache** is ``$CICADA_HOME/previews/<bank>/<id>.<ext>`` with a ``<id>.json`` sidecar — machine-global, never
inside a bank, like logos (a preview is a derived artifact of the outside world). One file per page, so no shared
index and no cross-process merge. A hit is kept for good while the page's source is unchanged: it is never re-fetched,
and a source that changes but cannot be fetched keeps the stored copy, so **a dead original link never breaks the
card**. A miss is remembered per source: a definite one (a 404, a wall, not an image, too big) for ``MISS_TTL``, a
transient one (a timeout, a 5xx) for ``RETRY_TTL``.

**The fetch** is the ToS rail's: ``net_guard`` on the first request and every redirect hop (at most
``MAX_REDIRECTS``), ``TIMEOUT_S``, at most ``MAX_BYTES`` read, no cookies, one fixed User-Agent, and a wall
(401/403/407/451, or a redirect onto a login host) is a miss never retried with different headers. Raster only:
PNG, JPEG, GIF or WebP by their magic bytes, whatever the header says; an SVG is refused (``logo_service``'s reason).

**The gates.** ``GET /entities/{id}/preview`` is the app asking to draw a card, exactly like ``GET /logo``: it
fetches only while ``CICADA_ALLOW_LOGO_FETCH`` is on (the picture-fetch gate; the suite runs with it off). A caller
that runs unattended (``unattended=True``; nothing does yet — no Sleep step warms previews) also needs
``CICADA_ALLOW_CONNECTOR_FETCH``. A gated-off request is never recorded as a miss. The person's own PDF upload
fetches nothing and is not gated.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Awaitable, Callable
from urllib.parse import quote, urljoin, urlparse

from loguru import logger

from api.services import logo_service, markdown_parser, net_guard

CACHE_DIR_NAME = "previews"
MISS_TTL = timedelta(days=7)
RETRY_TTL = timedelta(hours=1)
MAX_BYTES = 512 * 1024
TIMEOUT_S = 4.0
MAX_REDIRECTS = 3
MIN_PIXELS = 16
USER_AGENT = logo_service.USER_AGENT
MAX_URL = 2048
#: YouTube's standard still for a video id: present for every public video, embeddable or not.
YOUTUBE_STILL = "https://i.ytimg.com/vi/{id}/hqdefault.jpg"
_YOUTUBE_ID_RE = re.compile(r"[A-Za-z0-9_-]{6,20}")
#: `papers.KIND` (spelled here so this module stays light for the graph builder; a test pins the two equal).
PAPER_KIND = "paper"
WALL_STATUSES = frozenset({401, 403, 407, 451})
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
MEDIA_TYPES = {"png": "image/png", "jpg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}
EXTS = tuple(MEDIA_TYPES)
_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp")


@dataclass(frozen=True)
class Source:
    """Where one page's preview comes from: ``image`` (fetched as is) or ``pdf`` (fetched, then page 1 rendered)."""

    kind: str
    url: str

    @property
    def key(self) -> str:
        """sha256[:12] of the source — the wire's ``?v=``: a new source is a new key, so no cache is ever stale."""
        return hashlib.sha256(f"{self.kind}:{self.url}".encode()).hexdigest()[:12]


@dataclass
class Fetched:
    """One HTTP answer, as much of it as the rail lets through."""

    status: int
    body: bytes
    content_type: str = ""
    location: str | None = None


Fetcher = Callable[[str], Awaitable[Fetched]]
Renderer = Callable[[bytes], "bytes | None"]


# --- the source (pure) --------------------------------------------------------------------------------------------


def _usable(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return (parsed.scheme in ("http", "https") and bool(parsed.hostname) and len(url) <= MAX_URL
            and not any(ch.isspace() for ch in url))


def _walled(url: str) -> bool:
    from api.services import reading_hosts   # light, but keep the graph builder's import path minimal

    return reading_hosts.is_walled(url)


def _youtube_id(url: str) -> str | None:
    from api.services import video_urls

    ref = video_urls.resolve(url)
    if ref is None or ref.provider != "youtube" or not ref.video_id:
        return None
    return ref.video_id if _YOUTUBE_ID_RE.fullmatch(ref.video_id) else None


def _never_scraped(url: str) -> bool:
    from api.services.papers import never_scraped   # lazy: papers imports the graph builder

    return never_scraped(url)


def source_for(fm: dict) -> Source | None:
    """A ``media`` page's preview source, from its frontmatter alone (no I/O). None for every other page."""
    fm = fm or {}
    if str(fm.get("type") or "").strip().lower() != "media":
        return None
    media = fm.get("media")
    if not isinstance(media, dict) or media.get("kind") == PAPER_KIND:
        return None
    page_url = media.get("url") if isinstance(media.get("url"), str) else ""
    page_url = page_url.strip()
    thumb = media.get("thumbnail")
    if isinstance(thumb, str) and thumb.strip():
        try:
            absolute = urljoin(page_url, thumb.strip()) if page_url else thumb.strip()
        except ValueError:
            absolute = ""
        if _usable(absolute) and not _walled(absolute):
            return Source("image", absolute)
    if not page_url:
        return None
    vid = _youtube_id(page_url)
    if vid:
        return Source("image", YOUTUBE_STILL.format(id=vid))
    try:
        path = urlparse(page_url).path.lower()
    except ValueError:
        return None
    if not _usable(page_url) or _walled(page_url) or _never_scraped(page_url):
        return None
    if path.endswith(".pdf"):
        return Source("pdf", page_url)
    if path.endswith(_IMAGE_SUFFIXES):
        return Source("image", page_url)   # a saved image is its own picture
    return None


def key_for(fm: dict) -> str | None:
    source = source_for(fm)
    return source.key if source else None


def preview_path(entity_id: str, fm: dict) -> str | None:
    """The API path the app loads the stored copy from (``/entities/<id>/preview?v=<key>``), or None."""
    key = key_for(fm)
    return f"/entities/{quote(entity_id, safe='')}/preview?v={key}" if key else None


# --- the cache -----------------------------------------------------------------------------------------------------


def _root(bank: str) -> Path:
    """``$CICADA_HOME/previews/<bank>/`` without creating anything (a read must not conjure a folder)."""
    raw = os.environ.get("CICADA_HOME") or str(Path.home() / ".cicada")
    return Path(raw).expanduser() / CACHE_DIR_NAME / (bank or "default")


def _inside(base: Path, name: str) -> Path | None:
    path = (base / name).resolve()
    return path if path.parent == base.resolve() else None


def _meta_path(bank: str, entity_id: str) -> Path | None:
    return _inside(_root(bank), f"{entity_id}.json")


def read_meta(bank: str, entity_id: str) -> dict:
    path = _meta_path(bank, entity_id)
    if path is None:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _write_meta(bank: str, entity_id: str, meta: dict) -> None:
    path = _meta_path(bank, entity_id)
    if path is None:
        return
    try:
        _write_atomic(path, (json.dumps(meta, indent=2, sort_keys=True) + "\n").encode())
    except OSError as exc:
        logger.warning(f"preview meta not written: {type(exc).__name__}")


def stored_file(bank: str, entity_id: str) -> Path | None:
    """The stored copy, whatever source it came from — what the endpoint serves, so a dead link keeps its card."""
    hit = read_meta(bank, entity_id).get("hit")
    if not isinstance(hit, dict) or hit.get("ext") not in EXTS:
        return None
    path = _inside(_root(bank), f"{entity_id}.{hit['ext']}")
    return path if path is not None and path.is_file() else None


def _stamp(raw) -> datetime | None:
    try:
        stamp = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def fresh_miss(meta: dict, key: str, *, now: datetime | None = None) -> bool:
    """True while a remembered miss for THIS source still holds (``MISS_TTL``, or ``RETRY_TTL`` when transient)."""
    miss = (meta or {}).get("miss")
    if not isinstance(miss, dict) or miss.get("key") != key:
        return False
    at = _stamp(miss.get("at"))
    if at is None:
        return False
    ttl = RETRY_TTL if miss.get("transient") else MISS_TTL
    return (now or datetime.now(timezone.utc)) - at < ttl


# --- the fetch -----------------------------------------------------------------------------------------------------


def sniff(data: bytes) -> str | None:
    """The raster format from the magic bytes — the only thing trusted, never the Content-Type."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def accept_image(data: bytes) -> str | None:
    """The extension to store ``data`` under, or None: raster only, within the bound, not a tracking pixel."""
    if not data or len(data) > MAX_BYTES or logo_service.looks_like_svg(data):
        return None
    ext = sniff(data)
    if ext is None:
        return None
    smallest = logo_service.min_dimension(data)
    if smallest is not None and smallest < MIN_PIXELS:
        return None
    return ext


async def _http_get(url: str) -> Fetched:
    """One hop, bounded, keyless: no redirects followed (the caller checks each hop), no cookie jar, the body read
    only up to the bound."""
    import httpx

    async with httpx.AsyncClient(follow_redirects=False, timeout=TIMEOUT_S, cookies=None) as client:
        async with client.stream("GET", url, headers={"User-Agent": USER_AGENT}) as resp:
            body = bytearray()
            async for chunk in resp.aiter_bytes():
                body.extend(chunk)
                if len(body) > MAX_BYTES:
                    break
            return Fetched(status=resp.status_code, body=bytes(body),
                           content_type=resp.headers.get("content-type", ""), location=resp.headers.get("location"))


class _Miss(Exception):
    def __init__(self, reason: str, *, transient: bool = False):
        super().__init__(reason)
        self.reason = reason
        self.transient = transient


async def _get(url: str, fetcher: Fetcher) -> Fetched:
    """The rail's one GET: ``net_guard`` before every hop, a wall stops it, nothing is retried."""
    from api.services import link_enrichment   # lazy: it imports media_ingestor's neighbours

    current = url
    for _ in range(MAX_REDIRECTS + 1):
        if _walled(current):
            raise _Miss("walled")
        if not await net_guard.is_fetchable_url_async(current):
            raise _Miss("unsafe")
        try:
            got = await fetcher(current)
        except Exception as exc:  # noqa: BLE001 — a dead host is a miss, never an error
            raise _Miss(type(exc).__name__, transient=True) from exc
        if got.status in REDIRECT_STATUSES and got.location:
            nxt = urljoin(current, got.location)
            if link_enrichment._redirected_to_wall(url, nxt):
                raise _Miss("walled")
            current = nxt
            continue
        if got.status in WALL_STATUSES:
            raise _Miss("blocked")
        if got.status == 429 or got.status >= 500:
            raise _Miss(f"http {got.status}", transient=True)
        if got.status != 200:
            raise _Miss(f"http {got.status}")
        if len(got.body) > MAX_BYTES:
            raise _Miss("too large")
        return got
    raise _Miss("redirects")


async def _produce(source: Source, fetcher: Fetcher, renderer: Renderer) -> tuple[bytes, str]:
    got = await _get(source.url, fetcher)
    if source.kind == "pdf":
        from api.services import pdf_page

        if not pdf_page.looks_like_pdf(got.body):
            raise _Miss("not a pdf")
        png = await asyncio.to_thread(renderer, got.body)
        if not png or accept_image(png) != "png":
            raise _Miss("render")
        return png, "png"
    ext = accept_image(got.body)
    if ext is None:
        raise _Miss("not an image")
    return got.body, ext


# --- ensure --------------------------------------------------------------------------------------------------------

_locks: dict[str, asyncio.Lock] = {}
_lock_loop: asyncio.AbstractEventLoop | None = None


def _lock(name: str) -> asyncio.Lock:
    """One fetch per page at a time (the card and the Feed row ask together); per running loop, like logos."""
    global _lock_loop
    loop = asyncio.get_running_loop()
    if loop is not _lock_loop:
        _lock_loop = loop
        _locks.clear()
    return _locks.setdefault(name, asyncio.Lock())


def fetch_allowed(*, unattended: bool = False) -> bool:
    if not logo_service.fetch_allowed():
        return False
    if unattended:
        from api.services.connectors.base import network_allowed

        return network_allowed()
    return True


def _default_renderer(data: bytes) -> bytes | None:
    from api.services import pdf_page

    return pdf_page.render_first_page(data)


async def ensure_preview(memory_path, entity_id: str, *, fetcher: Fetcher | None = None,
                         renderer: Renderer | None = None, unattended: bool = False,
                         now: datetime | None = None) -> Path | None:
    """Resolve → stored copy → fetch once → store. Returns the file to serve, or None for "no preview".

    An injected ``fetcher`` always runs (the caller chose the mechanism); the default one obeys the gates."""
    memory_path = Path(memory_path)
    bank = logo_service.bank_name(memory_path)
    async with _lock(f"{bank}/{entity_id}"):
        page = memory_path / "entities" / f"{entity_id}.md"
        if _meta_path(bank, entity_id) is None or not page.is_file():
            return None
        try:
            fm = markdown_parser.parse(page).frontmatter or {}
        except Exception:  # noqa: BLE001 — an unreadable page keeps whatever is stored
            return stored_file(bank, entity_id)
        source = source_for(fm)
        if source is None:
            return None
        meta = read_meta(bank, entity_id)
        stored = stored_file(bank, entity_id)
        hit = meta.get("hit") if isinstance(meta.get("hit"), dict) else None
        if stored is not None and hit and hit.get("key") == source.key:
            return stored
        if fresh_miss(meta, source.key, now=now):
            return stored
        if fetcher is None:
            if not fetch_allowed(unattended=unattended):
                return stored   # never asked: not a miss
            fetcher = _http_get
        at = (now or datetime.now(timezone.utc)).isoformat()
        try:
            body, ext = await _produce(source, fetcher, renderer or _default_renderer)
        except _Miss as miss:
            logger.debug(f"preview miss for a {source.kind} source: {miss.reason}")
            meta["miss"] = {"key": source.key, "at": at, "reason": miss.reason, "transient": miss.transient}
            await asyncio.to_thread(_write_meta, bank, entity_id, meta)
            return stored   # a dead link keeps the copy already stored
        target = _inside(_root(bank), f"{entity_id}.{ext}")
        if target is None:
            return stored
        try:
            await asyncio.to_thread(_write_atomic, target, body)
        except OSError as exc:
            logger.warning(f"preview not stored: {type(exc).__name__}")
            return stored
        for other in EXTS:
            if other != ext and (old := _inside(_root(bank), f"{entity_id}.{other}")) is not None:
                try:
                    old.unlink()
                except OSError:
                    pass
        await asyncio.to_thread(_write_meta, bank, entity_id,
                                {"hit": {"key": source.key, "ext": ext, "at": at, "kind": source.kind}})
        return target
