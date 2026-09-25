"""URL → video classification. Pure: no network, no I/O, never raises (R2).

Track V / R-V1: the provider is a **pure function of a URL the bank already
stores**, so it is DERIVED at read time rather than written into a bank. That
is what lets every already-saved Vimeo/TikTok/Loom/``.mp4`` item play the
moment the app updates — no whole-bank rewrite commit, and no parallel
``url_index.json`` migration (``GET /sources`` reads ``media_type`` from the
index, not the page, so migrating one and not the other is the split-brain
class this repo already knows). It is also the house rule: ``_state.md`` is a
cursor not a copy, ``age_days`` is derived at read, ``inbox_context``
recomputes offsets on every read.

The same table exists in Swift (``Views/Common/VideoRef.swift``) and both are
pinned by ``api/tests/fixtures/video_urls.json`` (R-V8). Edit the fixture
first; the other side then fails until it is taught too.

What is NOT here, and why (R-V4 — the ToS rail):
  * No stream resolution. No ``yt-dlp``, no ``googlevideo.com``, no ``.m3u8``
    lifted out of a page's HTML or JS, no provider CDN URL. A direct file
    Cicada plays is one the USER saved as a direct URL.
  * No network to classify. ``vm.tiktok.com/<slug>`` hides its id behind a
    redirect, so it stays ``external`` rather than being resolved by a fetch.
  * Twitch is ``external``: its player validates ``parent`` against the real
    embedding origin, and a ``WKWebView`` loading the player as a top-level
    document has none — synthesising one is circumventing an embed
    restriction.
  * X is absent: ``x.com/<user>/status/<id>`` is *any* post, so classifying
    every status as a video would be a lie. Instagram is absent too — it is
    login-walled and never plays in-app.

This module is deliberately a leaf: stdlib only, no imports from the rest of
``api``. ``media_ingestor`` may call it; it never calls anything back.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

# Path extensions AVKit can play directly (R3). Matched case-insensitively
# against the PATH only — an extension in a query string is not a file.
FILE_EXTENSIONS = frozenset({"mp4", "m4v", "mov", "webm", "m3u8"})

# Schemes that are ever classified (R2). Anything else — ``javascript:``,
# ``data:``, ``mailto:`` — is not a video no matter what it ends in.
_SCHEMES = frozenset({"http", "https", "file"})

PROVIDERS = frozenset({"youtube", "vimeo", "tiktok", "loom", "twitch", "direct", "local"})

# Providers with a keyless oEmbed endpoint the ingest path may call. YouTube
# is deliberately absent: ``media_ingestor._enrich_youtube`` already owns it
# and stays untouched (plan R12).
OEMBED_PROVIDERS: tuple[str, ...] = ("vimeo", "tiktok", "loom")

_YOUTUBE_PATH_RE = re.compile(r"^/(?:shorts|embed|v|live)/([^/?&#]+)")
_TIKTOK_VIDEO_RE = re.compile(r"^/@[^/]+/video/(\d+)")
_TIKTOK_EMBED_RE = re.compile(r"^/embed/v\d+/(\d+)")
_LOOM_RE = re.compile(r"^/(?:share|embed)/([0-9a-zA-Z]+)")
_TWITCH_VIDEO_RE = re.compile(r"^/videos/(\d+)")
_VIMEO_HASH_RE = re.compile(r"^[0-9a-zA-Z]{4,}$")


@dataclass(frozen=True)
class VideoRef:
    """One resolved video reference.

    ``kind`` is the *decision*, not just a description:
      * ``embed``    — load ``embed_url`` in the provider's own player.
      * ``file``     — hand ``watch_url`` to AVKit.
      * ``external`` — recognised as a video, deliberately not played in-app;
                       the reason lives in this module's docstring, not in a
                       TODO.
    ``video_id`` is ``None`` for a file and for a YouTube playlist (there is
    no single video; ``embed_url`` carries the list id instead).
    """

    provider: str
    kind: str
    video_id: str | None
    embed_url: str | None
    watch_url: str


def _parsed(url: str):
    raw = (url or "").strip()
    if not raw:
        return None
    try:
        parsed = urlparse(raw)
    except Exception:
        # urlparse is total for str inputs today, but R2 promises totality to
        # a Feed row, not to a CPython version — the guard costs nothing.
        return None
    if (parsed.scheme or "").lower() not in _SCHEMES:
        return None
    return parsed


def _extension(path: str) -> str:
    tail = path.rsplit("/", 1)[-1]
    return tail.rsplit(".", 1)[-1].lower() if "." in tail else ""


def is_direct_file(url: str) -> bool:
    """True for a URL whose PATH ends in a playable video extension (R3)."""
    ref = resolve(url)
    return ref is not None and ref.kind == "file"


def _youtube(parsed, url: str) -> VideoRef | None:
    host = (parsed.hostname or "").lower()
    vid: str | None = None
    if host.endswith("youtu.be"):
        vid = (parsed.path.strip("/").split("/") or [""])[0] or None
    else:
        if parsed.path.rstrip("/") == "/watch":
            vid = (parse_qs(parsed.query).get("v") or [None])[0] or None
        if not vid:
            m = _YOUTUBE_PATH_RE.match(parsed.path)
            if m:
                vid = m.group(1)
        if not vid and parsed.path.rstrip("/") == "/playlist":
            # YouTube's own multi-video player. No single video id exists, so
            # ``video_id`` stays None and the list id lives in the embed url.
            plist = (parse_qs(parsed.query).get("list") or [None])[0]
            if plist:
                return VideoRef(
                    "youtube", "embed", None,
                    f"https://www.youtube-nocookie.com/embed/videoseries?list={plist}",
                    url,
                )
    if not vid:
        return None
    return VideoRef(
        "youtube", "embed", vid,
        f"https://www.youtube-nocookie.com/embed/{vid}", url,
    )


def _vimeo(parsed, url: str) -> VideoRef | None:
    segments = [s for s in parsed.path.split("/") if s]
    for i, seg in enumerate(segments):
        if not seg.isdigit():
            continue
        embed = f"https://player.vimeo.com/video/{seg}"
        # Vimeo's own private-link param: an unlisted video is
        # ``vimeo.com/<id>/<hash>`` and embeds as ``?h=<hash>``.
        nxt = segments[i + 1] if i + 1 < len(segments) else ""
        if nxt and not nxt.isdigit() and _VIMEO_HASH_RE.match(nxt):
            embed = f"{embed}?h={nxt}"
        return VideoRef("vimeo", "embed", seg, embed, url)
    return None


def _tiktok(parsed, url: str) -> VideoRef | None:
    host = (parsed.hostname or "").lower()
    if host.startswith("vm.") or host.startswith("vt."):
        # R4: the id is only behind a redirect; classifying costs no network.
        return VideoRef("tiktok", "external", None, None, url)
    m = _TIKTOK_VIDEO_RE.match(parsed.path) or _TIKTOK_EMBED_RE.match(parsed.path)
    if not m:
        return None
    vid = m.group(1)
    return VideoRef("tiktok", "embed", vid, f"https://www.tiktok.com/embed/v2/{vid}", url)


def _loom(parsed, url: str) -> VideoRef | None:
    m = _LOOM_RE.match(parsed.path)
    if not m:
        return None
    vid = m.group(1)
    return VideoRef("loom", "embed", vid, f"https://www.loom.com/embed/{vid}", url)


def _twitch(parsed, url: str) -> VideoRef | None:
    host = (parsed.hostname or "").lower()
    if host.startswith("clips."):
        slug = (parsed.path.strip("/").split("/") or [""])[0]
        return VideoRef("twitch", "external", slug or None, None, url) if slug else None
    m = _TWITCH_VIDEO_RE.match(parsed.path)
    return VideoRef("twitch", "external", m.group(1), None, url) if m else None


def resolve(url: str) -> VideoRef | None:
    """Classify a URL. ``None`` means "not a video" — never an exception (R2)."""
    parsed = _parsed(url)
    if parsed is None:
        return None
    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").lower()
    path = parsed.path or ""

    if scheme == "file":
        if not path.strip("/"):
            return None
        return VideoRef("local", "file", None, None, url) if _extension(path) in FILE_EXTENSIONS else None

    if not host:
        return None

    # A direct file wins over a host table: nothing in the table serves one.
    if _extension(path) in FILE_EXTENSIONS:
        return VideoRef("direct", "file", None, None, url)

    if host.endswith("youtu.be") or "youtube.com" in host or "youtube-nocookie.com" in host:
        return _youtube(parsed, url)
    if host == "vimeo.com" or host.endswith(".vimeo.com"):
        return _vimeo(parsed, url)
    if "tiktok.com" in host:
        return _tiktok(parsed, url)
    if "loom.com" in host:
        return _loom(parsed, url)
    if "twitch.tv" in host:
        return _twitch(parsed, url)
    return None
