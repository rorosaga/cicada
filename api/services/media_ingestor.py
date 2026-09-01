"""Media / bookmark ingestion (sources pipeline).

A saved URL (a bookmark, a YouTube video, a pasted link) is a deliberate
signal, so it skips the promotion gate and is written to two places at once:

1. an episode in ``memory/episodes/`` (``source: bookmark|youtube|instagram|url``)
   that the Sleep cycle extracts other entities from, unchanged;
2. a first-class ``media`` entity in ``memory/entities/`` that is a graph node
   from the moment it is saved.

Network enrichment (Open Graph tags via httpx+bs4, YouTube via the keyless
oEmbed endpoint) is best-effort: any failure degrades to URL-only metadata and
never raises to the caller.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from loguru import logger

from api.services import decay_policy, markdown_parser
from api.services.id_utils import sanitize_id

USER_AGENT = "Mozilla/5.0 (CicadaBot)"
_TIMEOUT = 5.0
_MAX_READ = 1_500_000  # 1.5 MB cap on a fetched page body
MAX_BATCH = 2000
_INLINE_ENRICH_LIMIT = 10  # small batches enrich inline so saves feel instant

# Tracking params stripped during URL normalization.
_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "igshid", "si", "ref", "ref_src",
}


# --- Data shapes ---


@dataclass
class RawItem:
    url: str
    title: str | None = None
    tags: list[str] = field(default_factory=list)
    channel: str | None = None
    added: str | None = None
    note: str | None = None
    # Human-readable source folder/category path, e.g. "Bookmarks Bar/AI/Papers"
    # (Chrome/Safari folder tree) or a single enclosing folder name (Netscape
    # HTML export). Provenance only — never part of dedup identity.
    folder: str | None = None
    # Explicit capture-provenance tag (G9 ``origin``), set by the caller when
    # known — e.g. ``bookmark_sync._tag_origin`` sets ``"chrome-bookmark"`` /
    # ``"safari-bookmark"``. Threaded straight through to the episode + media
    # entity frontmatter by ``write_media_episode``/``write_media_entity``
    # rather than derived from ``tags`` (which also carries arbitrary bookmark
    # folder names and must not be mistaken for provenance). ``None`` when the
    # caller has no origin to report — those writes simply omit the field, same
    # as before this was added.
    origin: str | None = None
    # G48 conversation provenance, threaded from a live MCP client through
    # `POST /sources/save`. Same contract as `origin` above: written to the
    # episode ONLY when the caller supplies it, so every non-MCP capture path
    # (bookmarks, RSS, the app's paste field) produces byte-identical
    # frontmatter to before.
    session_id: str | None = None
    harness: str | None = None
    project_dir: str | None = None
    # G71 §1 — why the user saved this, in their own words (the text around the
    # URL in a Telegram `/save`). Rendered verbatim on the episode body as a
    # `## Saved because` section so Stage 1 extraction can pull concepts out of
    # it exactly as it would from conversation text, and written separately as a
    # `saved-because` claim by the caller that has one.
    reason: str | None = None


@dataclass
class MediaMeta:
    title: str
    description: str = ""
    site: str | None = None
    channel: str | None = None
    thumbnail: str | None = None
    media_type: str = "url"  # bookmark | youtube | instagram | url


@dataclass
class IngestResult:
    status: str  # created | duplicate
    media_entity_id: str
    episode_id: str
    title: str
    media_type: str
    thumbnail: str | None = None
    url: str = ""


# --- URL normalization & hashing ---


def _youtube_video_id(parsed) -> str | None:
    host = (parsed.hostname or "").lower()
    if host.endswith("youtu.be"):
        seg = parsed.path.strip("/").split("/")[0]
        return seg or None
    if "youtube.com" in host:
        if parsed.path == "/watch":
            vid = parse_qs(parsed.query).get("v", [None])[0]
            return vid
        # /shorts/<id>, /embed/<id>, /v/<id>
        m = re.match(r"^/(shorts|embed|v)/([^/?&]+)", parsed.path)
        if m:
            return m.group(2)
    return None


def normalize_url(url: str) -> str:
    """Lowercase scheme+host, strip fragment + tracking params, collapse trailing slash.

    YouTube links canonicalize to ``https://www.youtube.com/watch?v=<id>`` so
    ``youtu.be/<id>``, ``/shorts/<id>`` and ``&t=``/``&list=`` variants dedup
    against each other.
    """
    raw = (url or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    try:
        parsed = urlparse(raw)
    except Exception:
        return raw.lower()

    host = (parsed.hostname or "").lower()

    vid = _youtube_video_id(parsed)
    if vid:
        return f"https://www.youtube.com/watch?v={vid}"

    # Strip tracking params, keep the rest sorted for stable hashing.
    kept = []
    for k, v in parse_qs(parsed.query, keep_blank_values=True).items():
        if k.lower() in _TRACKING_PARAMS:
            continue
        for value in v:
            kept.append((k, value))
    kept.sort()
    query = "&".join(f"{k}={v}" if v else k for k, v in kept)

    path = parsed.path.rstrip("/") or ""
    scheme = (parsed.scheme or "https").lower()
    out = f"{scheme}://{host}{path}"
    if query:
        out += f"?{query}"
    return out


def url_hash(url: str) -> str:
    return hashlib.sha256(normalize_url(url).encode()).hexdigest()[:12]


def _classify(url: str, from_bookmark_file: bool = False) -> str:
    host = (urlparse(url if "://" in url else "https://" + url).hostname or "").lower()
    if "youtube.com" in host or host.endswith("youtu.be"):
        return "youtube"
    if "instagram.com" in host:
        return "instagram"
    if "linkedin.com" in host:
        return "linkedin"
    if from_bookmark_file:
        return "bookmark"
    return "url"


def _site_of(url: str) -> str | None:
    host = (urlparse(url if "://" in url else "https://" + url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else (host or None)


def _fallback_title(url: str) -> str:
    parsed = urlparse(url if "://" in url else "https://" + url)
    # A ``/watch?v=<id>`` URL carries its identity in the query string, not
    # the path (``parsed.path`` is just ``"/watch"`` for every video) — fall
    # back to the video id so two different unenriched videos never collide
    # on the same fallback title (and, downstream, the same entity filename).
    vid = _youtube_video_id(parsed)
    if vid:
        return vid
    seg = parsed.path.strip("/").split("/")[-1] if parsed.path.strip("/") else ""
    seg = seg.replace("-", " ").replace("_", " ").strip()
    return seg or (parsed.hostname or url)


# --- Enrichment (async, graceful offline fallback) ---


async def enrich(url: str, client, from_bookmark_file: bool = False) -> MediaMeta:
    """Best-effort metadata. ANY network/parse failure -> URL-only fallback."""
    media_type = _classify(url, from_bookmark_file=from_bookmark_file)
    site = _site_of(url)
    fallback = MediaMeta(
        title=_fallback_title(url), description="", site=site, media_type=media_type
    )

    try:
        if media_type == "youtube":
            return await _enrich_youtube(url, client, fallback)
        if media_type == "instagram":
            # Login-walled — never attempt scraping; URL-only by design.
            return fallback
        if media_type == "linkedin":
            # ToS-walled (G69: §8.2 bans fetching the post body) — never
            # attempt scraping; URL-only by design, same as Instagram above.
            # This is what makes ``parse_linkedin_saved``'s "thin by design"
            # claim actually true once an item is STAGED, not just previewed.
            return fallback
        return await _enrich_opengraph(url, client, fallback)
    except Exception as e:
        logger.debug(f"Enrichment failed for {url}: {type(e).__name__}: {e}")
        return fallback


async def _enrich_youtube(url: str, client, fallback: MediaMeta) -> MediaMeta:
    oembed = f"https://www.youtube.com/oembed?url={url}&format=json"
    resp = await client.get(oembed, timeout=_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    return MediaMeta(
        title=data.get("title") or fallback.title,
        description="",
        site="youtube.com",
        channel=data.get("author_name") or None,
        thumbnail=data.get("thumbnail_url") or None,
        media_type="youtube",
    )


async def _enrich_opengraph(url: str, client, fallback: MediaMeta) -> MediaMeta:
    resp = await client.get(
        url,
        timeout=_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    )
    resp.raise_for_status()
    html = resp.text[:_MAX_READ]

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")

    def meta(*selectors: tuple[str, str]) -> str | None:
        for attr, value in selectors:
            tag = soup.find("meta", attrs={attr: value})
            if tag and tag.get("content"):
                return tag["content"].strip()
        return None

    title = meta(("property", "og:title"), ("name", "twitter:title"))
    if not title and soup.title and soup.title.string:
        title = soup.title.string.strip()
    description = meta(
        ("property", "og:description"), ("name", "description"),
        ("name", "twitter:description"),
    )
    site_name = meta(("property", "og:site_name"))
    thumbnail = meta(("property", "og:image"), ("name", "twitter:image"))

    return MediaMeta(
        title=title or fallback.title,
        description=description or "",
        site=fallback.site or (site_name.lower() if site_name else None),
        channel=None,
        thumbnail=thumbnail,
        media_type=fallback.media_type,
    )


# --- Parsers ---


def parse_netscape_bookmarks(html: str) -> list[RawItem]:
    """Netscape Bookmark File Format (Safari/Chrome/Firefox export)."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    items: list[RawItem] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith("javascript:") or href.startswith("place:"):
            continue
        tags = [t.strip() for t in (a.get("tags", "") or "").split(",") if t.strip()]
        # Nearest enclosing folder <H3> name -> a tag for nested links.
        # Netscape's loose/unclosed-tag HTML doesn't expose a clean DL/DT
        # nesting to reconstruct a full folder *path* (that would mean
        # rewriting this parser around real DOM ancestry); we carry the single
        # nearest-enclosing folder name only, same depth this parser already
        # sees for the tag above.
        folder_tag = a.find_previous("h3")
        folder_name = folder_tag.get_text(strip=True) if folder_tag else None
        if folder_name:
            tags.append(folder_name)
        items.append(RawItem(
            url=href,
            title=(a.get_text(strip=True) or None),
            tags=tags,
            added=a.get("add_date"),
            folder=folder_name or None,
        ))
    return items


def parse_safari_bookmarks(data: bytes) -> list[RawItem]:
    """Safari bookmarks in either shape Safari can hand you.

    (a) ``~/Library/Safari/Bookmarks.plist`` — a binary or XML property list.
        Walked via stdlib ``plistlib.loads`` (auto-detects binary vs XML);
        nested ``Children`` folders (``WebBookmarkTypeList``/``...Proxy``) are
        recursed, and each ``WebBookmarkTypeLeaf`` yields a ``RawItem`` from
        ``URLString`` + ``URIDictionary["title"]``. Folders themselves are
        skipped (never emitted as items); leaves with a non-http(s) URL
        (``javascript:``, ``mailto:``, etc.) are skipped too. Each folder's
        ``Title`` is threaded down as a ``/``-joined path (e.g. ``"Favorites/
        AI/Papers"``) and stamped on every leaf beneath it as ``folder``; the
        root list's own ``Title`` is normally ``""`` and contributes nothing.
    (b) A Safari-exported bookmarks HTML file — Safari exports the same
        Netscape Bookmark File Format Chrome/Firefox do, so on plist-parse
        failure we decode the bytes as text and delegate straight to
        ``parse_netscape_bookmarks``.

    Malformed input of either shape degrades to ``[]`` — never raises.
    """
    import plistlib

    try:
        root = plistlib.loads(data)
    except Exception:
        try:
            text = data.decode("utf-8", errors="replace")
        except Exception:
            return []
        return parse_netscape_bookmarks(text)

    items: list[RawItem] = []

    def walk(node, path: tuple[str, ...]) -> None:
        if not isinstance(node, dict):
            return
        if node.get("WebBookmarkType") == "WebBookmarkTypeLeaf":
            url = node.get("URLString")
            if isinstance(url, str) and url.startswith(("http://", "https://")):
                uri_dict = node.get("URIDictionary")
                title = uri_dict.get("title") if isinstance(uri_dict, dict) else None
                folder = "/".join(path) if path else None
                items.append(RawItem(url=url, title=title or None, folder=folder))
            return
        title = node.get("Title")
        new_path = path + (title,) if title else path
        for child in node.get("Children", []) or []:
            walk(child, new_path)

    walk(root, ())
    return items


def read_live_safari_bookmarks() -> list[RawItem]:
    """Read the current user's real ``~/Library/Safari/Bookmarks.plist``, if present.

    Convenience for a future "Import from Safari" button — not exercised by
    tests (hermetic tests never touch the live filesystem). Missing file or
    any read/parse error degrades to ``[]``, same as ``parse_safari_bookmarks``.
    """
    from pathlib import Path as _Path

    plist_path = _Path.home() / "Library" / "Safari" / "Bookmarks.plist"
    try:
        data = plist_path.read_bytes()
    except OSError:
        return []
    return parse_safari_bookmarks(data)


def parse_chrome_bookmarks_json(data: dict) -> list[RawItem]:
    """Chrome ``Bookmarks`` JSON — recurse the roots tree, type=='url'.

    Each root (``bookmark_bar``, ``other``, ``synced``) and every nested
    ``type == "folder"`` node carries a display ``name`` (e.g. "Bookmarks
    bar", "Reading"); that name is threaded down the recursion as a
    ``/``-joined path (e.g. ``"Bookmarks bar/Reading"``) and stamped on every
    ``type == "url"`` leaf beneath it as ``folder``. Folders themselves are
    still never emitted as items — only their name flows onto descendant
    leaves.
    """
    items: list[RawItem] = []

    def walk(node, path: tuple[str, ...]) -> None:
        if not isinstance(node, dict):
            return
        if node.get("type") == "url" and node.get("url"):
            items.append(RawItem(
                url=node["url"],
                title=node.get("name") or None,
                added=node.get("date_added"),
                folder="/".join(path) if path else None,
            ))
            return
        name = node.get("name")
        new_path = path + (name,) if name else path
        for child in node.get("children", []) or []:
            walk(child, new_path)

    roots = data.get("roots", {})
    if isinstance(roots, dict):
        for root in roots.values():
            walk(root, ())
    return items


def parse_youtube_takeout(content: bytes, filename: str) -> list[RawItem]:
    """Google Takeout watch-later/history — JSON or CSV."""
    items: list[RawItem] = []
    if filename.endswith(".csv"):
        import csv
        import io

        text = content.decode("utf-8", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            vid = (row.get("Video ID") or row.get("Video Id") or "").strip()
            if vid:
                items.append(RawItem(
                    url=f"https://www.youtube.com/watch?v={vid}",
                ))
        return items

    data = json.loads(content)
    if not isinstance(data, list):
        return items
    for entry in data:
        if not isinstance(entry, dict):
            continue
        url = entry.get("titleUrl") or entry.get("url")
        if not url:
            continue
        channel = None
        subs = entry.get("subtitles") or []
        if isinstance(subs, list) and subs and isinstance(subs[0], dict):
            channel = subs[0].get("name")
        items.append(RawItem(
            url=url,
            title=entry.get("title") or None,
            channel=channel,
            added=entry.get("time"),
        ))
    return items


def parse_instagram_saved(data: dict) -> list[RawItem]:
    """Meta "Download your information" saved-posts export.

    Canonical shape: a top-level dict with ``saved_saved_media`` holding a list
    of records like::

        {"title": "<account name>",
         "string_map_data": {"Saved on": {"href": "https://instagram.com/reel/...",
                                            "timestamp": 1699000000}}}

    Also tolerates a **collections** variant where saves are grouped under
    collection names — either ``saved_saved_media`` itself is a
    ``{collection_name: [record, ...]}`` dict, or a record carries a nested
    ``name`` + ``sources``/``media`` list (a collection wrapper). The
    collection name becomes ``RawItem.folder``; ungrouped saves default to
    folder ``"Saved"``.

    Parses defensively — any unknown/missing key is tolerated, malformed
    input degrades to ``[]`` rather than raising.
    """
    items: list[RawItem] = []
    if not isinstance(data, dict):
        return items

    media = data.get("saved_saved_media")
    if media is None:
        # Tolerate any other "saved_*" top-level key carrying the payload.
        for key, value in data.items():
            if isinstance(key, str) and key.startswith("saved_") and value:
                media = value
                break
    if media is None:
        return items

    def item_from_record(record, folder: str | None) -> None:
        if not isinstance(record, dict):
            return
        title = record.get("title")
        href = None
        smd = record.get("string_map_data")
        if isinstance(smd, dict):
            saved_on = smd.get("Saved on")
            if isinstance(saved_on, dict):
                href = saved_on.get("href")
            if not href:
                for v in smd.values():
                    if isinstance(v, dict) and v.get("href"):
                        href = v["href"]
                        break
        if not href:
            href = record.get("href") or record.get("url")
        if not href or not isinstance(href, str):
            return
        items.append(RawItem(
            url=href,
            title=title if isinstance(title, str) else None,
            folder=folder or "Saved",
            origin="instagram-saved",
        ))

    if isinstance(media, list):
        for record in media:
            # A collections wrapper nests a "name" + "sources"/"media" list
            # instead of a leaf record's "string_map_data".
            if isinstance(record, dict) and "string_map_data" not in record and (
                "sources" in record or "media" in record
            ):
                coll_name = record.get("name") if isinstance(record.get("name"), str) else None
                sub_records = record.get("sources") or record.get("media") or []
                if isinstance(sub_records, list):
                    for sub in sub_records:
                        item_from_record(sub, coll_name)
                    continue
            item_from_record(record, None)
    elif isinstance(media, dict):
        # {collection_name: [record, ...]}
        for coll_name, records in media.items():
            if isinstance(records, list):
                for record in records:
                    item_from_record(record, coll_name if isinstance(coll_name, str) else None)

    return items


def _is_instagram_saved_json(data) -> bool:
    """Sniff rule: a ``.json`` whose top-level dict has a ``saved_*`` key."""
    return isinstance(data, dict) and any(
        isinstance(k, str) and k.startswith("saved_") for k in data.keys()
    )


# TikTok's "Download your data" JSON, one row per section:
# (activity-section key, the list key inside it, the folder name, is_history).
_TIKTOK_SECTIONS = (
    ("Favorite Videos", "FavoriteVideoList", "Favorites", False),
    ("Like List", "ItemFavoriteList", "Likes", False),
    ("Video Browsing History", "VideoList", "Browsing History", True),
)


def _tiktok_activity(data) -> dict | None:
    """The activity dict, under either the old ``Activity`` key or the newer
    ``Your Activity`` one."""
    if not isinstance(data, dict):
        return None
    for key in ("Activity", "Your Activity"):
        section = data.get(key)
        if isinstance(section, dict):
            return section
    return None


def _is_tiktok_export_json(data) -> bool:
    """Sniff rule: an activity wrapper holding at least one known section."""
    activity = _tiktok_activity(data)
    return isinstance(activity, dict) and any(
        name in activity for name, _list_key, _folder, _hist in _TIKTOK_SECTIONS
    )


def parse_tiktok_export(data, *, include_history: bool = False) -> list[RawItem]:
    """TikTok "Download your data" ``user_data.json`` (G71 §3).

    Favourites and Likes are intentional saves and are always parsed.
    Browsing History is ambient exhaust (G69: high noise) and is parsed only
    when the caller opts in; even then it keeps a distinct ``tiktok-history``
    origin so ``/origins`` — and anyone reading the graph later — can tell a
    save from a scroll.

    Entry shape is ``{"Date": "...", "Link": "https://..."}``; older exports
    lowercase ``link``. Malformed input degrades to ``[]`` rather than raising.
    """
    activity = _tiktok_activity(data)
    if not isinstance(activity, dict):
        return []

    items: list[RawItem] = []
    for section_name, list_key, folder, is_history in _TIKTOK_SECTIONS:
        if is_history and not include_history:
            continue
        section = activity.get(section_name)
        if not isinstance(section, dict):
            continue
        rows = section.get(list_key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            url = row.get("Link") or row.get("link") or row.get("URL") or row.get("url")
            if not isinstance(url, str) or not url.strip():
                continue
            date = row.get("Date") or row.get("date")
            items.append(RawItem(
                url=url.strip(),
                added=date if isinstance(date, str) else None,
                folder=folder,
                origin="tiktok-history" if is_history else "tiktok-saved",
            ))
    return items


def _playlist_name_from_filename(filename: str) -> str:
    """``"Watch later-videos.csv"`` -> ``"Watch later"``; ``"<Name>-videos.csv"`` -> ``"<Name>"``."""
    stem = Path(filename).stem  # strips ".csv"
    if stem.lower().endswith("-videos"):
        stem = stem[: -len("-videos")]
    stem = stem.strip()
    return stem or "Playlist"


def _sniff_youtube_video_id_column(fieldnames: list[str] | None) -> str | None:
    for name in fieldnames or []:
        if name and name.strip() in ("Video ID", "Video Id"):
            return name
    return None


def parse_youtube_playlist_csv(content: bytes, filename: str) -> list[RawItem]:
    """A single Google Takeout per-playlist video CSV.

    Takeout ships one CSV per playlist under ``Playlists/``, with the playlist
    name baked into the filename (e.g. ``"Watch later-videos.csv"``,
    ``"<Name>-videos.csv"``). Columns include a video-id column
    (``"Video ID"`` or ``"Video Id"``) and a timestamp; there is no title
    column — titles are filled in later by the youtube oEmbed enrichment path.

    An unrecognized CSV (no video-id column) yields ``[]`` — never raises.
    """
    import csv
    import io

    try:
        text = content.decode("utf-8", errors="replace")
    except Exception:
        return []

    try:
        reader = csv.DictReader(io.StringIO(text))
        vid_col = _sniff_youtube_video_id_column(reader.fieldnames)
    except Exception:
        return []
    if vid_col is None:
        return []

    playlist_name = _playlist_name_from_filename(filename)
    items: list[RawItem] = []
    for row in reader:
        vid = (row.get(vid_col) or "").strip()
        if not vid:
            continue
        items.append(RawItem(
            url=f"https://www.youtube.com/watch?v={vid}",
            title=None,
            folder=playlist_name,
            origin="youtube-playlist",
        ))
    return items


# --- Shared CSV header sniffing (LinkedIn + Reddit exports) ------------------


def _norm_header(name: str | None) -> str:
    """Lowercased, BOM- and whitespace-stripped column name for comparison."""
    return (name or "").strip().lstrip("﻿").lower()


def _pick_column(fieldnames: list[str] | None, candidates: tuple[str, ...]) -> str | None:
    """The first real column name whose normalized form is in ``candidates``."""
    for name in fieldnames or []:
        if _norm_header(name) in candidates:
            return name
    return None


# LinkedIn has renamed this column across export generations, so match a set
# rather than one string. The SPECIFIC names are safe to match anywhere; the
# GENERIC ones (``url``, ``link``) are only trusted when the filename already
# says LinkedIn, or every plain URL CSV in the world would be claimed here.
_LINKEDIN_SPECIFIC_URL_FIELDS = ("saveditem", "saved item", "saveditemurl", "saved item url")
_LINKEDIN_GENERIC_URL_FIELDS = ("url", "link", "itemurl", "item url")
_LINKEDIN_DATE_FIELDS = (
    "savedat", "saved at", "saveddate", "saved date", "createdtime", "created time", "date",
)


def _is_linkedin_saved_filename(filename: str) -> bool:
    stem = Path(filename or "").stem.lower().replace("_", " ").replace("-", " ")
    return "saved item" in stem


def parse_linkedin_saved(content: bytes, filename: str) -> list[RawItem]:
    """LinkedIn "Get a copy of your data" — the Saved Items file.

    Thin by design (G69): the export carries a URL and a saved date and nothing
    else — no post text, no author. LinkedIn §8.2 bans fetching the post body,
    so these stay thin nodes whose only edges come from the folder tag, and the
    UI says so. Never invents a title.

    An unrecognized CSV yields ``[]`` — never raises.
    """
    import csv
    import io

    try:
        text = content.decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        fieldnames = reader.fieldnames
    except Exception:
        return []

    url_col = _pick_column(fieldnames, _LINKEDIN_SPECIFIC_URL_FIELDS)
    if url_col is None and _is_linkedin_saved_filename(filename):
        url_col = _pick_column(fieldnames, _LINKEDIN_GENERIC_URL_FIELDS)
    if url_col is None:
        return []
    date_col = _pick_column(fieldnames, _LINKEDIN_DATE_FIELDS)

    items: list[RawItem] = []
    for row in reader:
        url = (row.get(url_col) or "").strip()
        if not url.startswith(("http://", "https://")):
            continue
        added = None
        if date_col:
            added = (row.get(date_col) or "").strip() or None
        items.append(RawItem(
            url=url,
            added=added,
            folder="Saved Items",
            origin="linkedin-saved",
        ))
    return items


_REDDIT_PERMALINK_FIELDS = ("permalink",)
_REDDIT_FALLBACK_URL_FIELDS = ("permalink url", "url", "link")
REDDIT_BASE_URL = "https://www.reddit.com"


def _is_reddit_saved_filename(filename: str) -> bool:
    stem = Path(filename or "").stem.lower().replace("-", "_")
    return stem.startswith("saved_posts") or stem.startswith("saved_comments")


def parse_reddit_saved_csv(content: bytes, filename: str) -> list[RawItem]:
    """Reddit GDPR export ``saved_posts.csv`` / ``saved_comments.csv`` (G71 §2).

    Rows are ``id,permalink`` and nothing else. The export exists to backfill
    past the API's ~1,000-item listing cap (G69) — it is not the primary route.
    No Reddit-specific hydration call is needed: ``ingest_one`` already runs
    every URL through the OpenGraph enrichment path and reddit.com serves OG
    tags, so an online install gets a real title and an offline one degrades to
    the permalink slug, exactly like every other save.

    Permalinks may be relative (``/r/x/comments/...``); they are absolutized
    against ``https://www.reddit.com`` so ``normalize_url``/``url_hash`` dedup
    them against the same items pulled by the API connector.

    An unrecognized CSV yields ``[]`` — never raises.
    """
    import csv
    import io

    try:
        text = content.decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        fieldnames = reader.fieldnames
    except Exception:
        return []

    url_col = _pick_column(fieldnames, _REDDIT_PERMALINK_FIELDS)
    if url_col is None and _is_reddit_saved_filename(filename):
        url_col = _pick_column(fieldnames, _REDDIT_FALLBACK_URL_FIELDS)
    if url_col is None:
        return []

    stem = Path(filename or "").stem.lower()
    folder = "Saved comments" if "comment" in stem else "Saved posts"

    items: list[RawItem] = []
    for row in reader:
        raw = (row.get(url_col) or "").strip()
        if not raw:
            continue
        if raw.startswith("/"):
            raw = REDDIT_BASE_URL + raw
        if not raw.startswith(("http://", "https://")):
            continue
        items.append(RawItem(url=raw, folder=folder, origin="reddit-saved"))
    return items


# Cap on the number of members walked inside an uploaded zip archive — a
# saved-content export zip has at most a handful of playlist CSVs + one
# watch-history.json; this just bounds a maliciously/accidentally huge zip.
_MAX_ZIP_MEMBERS = 5000


def parse_youtube_takeout_zip(content: bytes, warnings: list[str] | None = None) -> list[RawItem]:
    """Walk a whole Google Takeout zip: ``playlists/*.csv`` + ``watch-history.json``.

    Lets a user drop one Takeout export zip in a single upload instead of
    hunting for individual files. Unrecognized members (anything that isn't a
    ``playlists/*.csv`` or a ``watch-history.json``) are skipped. Any read
    error on an individual member is skipped rather than raised — a partially
    corrupt zip still yields whatever is parseable. A non-zip or unreadable
    archive degrades to ``[]``. ``warnings`` (G71 §4.3), when given, is
    appended to with a summary of anything skipped, so a preview caller can
    surface it instead of only the debug log.
    """
    import zipfile

    items: list[RawItem] = []
    skipped = 0
    try:
        zf = zipfile.ZipFile(BytesIO(content))
    except Exception:
        if warnings is not None:
            warnings.append("This file is not a readable zip archive.")
        return []

    with zf:
        names = zf.namelist()[:_MAX_ZIP_MEMBERS]
        for name in names:
            lower = name.lower()
            # Match case-insensitively, but pass the *original*-cased base
            # filename down to the parsers — the playlist name is derived
            # from it and must keep its real casing.
            base = name.rsplit("/", 1)[-1]
            try:
                if lower.endswith(".csv") and "playlists/" in lower:
                    member_bytes = zf.read(name)
                    items.extend(parse_youtube_playlist_csv(member_bytes, base))
                elif base.lower() == "watch-history.json":
                    member_bytes = zf.read(name)
                    items.extend(parse_youtube_takeout(member_bytes, base))
            except Exception as e:
                logger.debug(f"Skipping unreadable zip member {name}: {type(e).__name__}: {e}")
                skipped += 1
                continue

    if warnings is not None and skipped:
        warnings.append(f"Skipped {skipped} unreadable file(s) inside the archive.")

    return items


def parse_url_list(text: str) -> list[RawItem]:
    """``.txt`` one URL per line (skip blanks / ``#`` comments)."""
    items: list[RawItem] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "." not in line and "://" not in line:
            continue
        items.append(RawItem(url=line))
    return items


def parse_csv_url_list(text: str) -> list[RawItem]:
    """``.csv`` with a url/link column header, else first column."""
    import csv
    import io

    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return []
    header = [h.strip().lower() for h in rows[0]]
    url_col = 0
    has_header = False
    for i, h in enumerate(header):
        if h in ("url", "link", "href"):
            url_col = i
            has_header = True
            break
    items: list[RawItem] = []
    body = rows[1:] if has_header else rows
    for row in body:
        if url_col >= len(row):
            continue
        val = row[url_col].strip()
        if val and ("://" in val or "." in val):
            items.append(RawItem(url=val))
    return items


def parse_rss(xml: str) -> list[RawItem]:
    """Parse an RSS 2.0 or Atom feed into ``RawItem``s (stdlib, namespace-tolerant).

    A feed is just another producer of ``RawItem``s; it flows through the exact
    same ``_dedup_items`` -> ``ingest_batch`` -> url_index/episode/entity path as
    bookmarks. No new consolidation code. We deliberately avoid ``feedparser`` to
    stay dependency-free and offline.

    Handles both shapes:
    - RSS:  ``channel/item`` with ``<link>``, ``<title>``, ``<description>`` or
      ``content:encoded`` (-> ``note``), ``<category>`` (-> ``tags``).
    - Atom: ``<entry>`` with ``<link href=... rel="alternate">`` (alternate
      preferred, else first link), ``<title>``, ``<summary>``, ``<category term>``.

    Tags are namespace-stripped (``{ns}tag`` -> ``tag``). Entries with no usable
    link are skipped. A malformed document yields ``[]`` (never raises) so a bad
    paste degrades gracefully.
    """
    import xml.etree.ElementTree as ET

    text = (xml or "").strip()
    if not text:
        return []
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []

    def local(tag: str) -> str:
        # Strip a leading ``{namespace}`` from an element/attr tag.
        return tag.rsplit("}", 1)[-1] if "}" in tag else tag

    def first_child_text(node, name: str) -> str | None:
        for child in node:
            if local(child.tag) == name and (child.text or "").strip():
                return child.text.strip()
        return None

    def atom_link(node) -> str | None:
        # Prefer rel="alternate" (or no rel); fall back to the first href.
        fallback = None
        for child in node:
            if local(child.tag) != "link":
                continue
            href = child.get("href")
            if not href:
                continue
            rel = child.get("rel")
            if rel in (None, "", "alternate"):
                return href.strip()
            if fallback is None:
                fallback = href.strip()
        return fallback

    items: list[RawItem] = []
    # An <item> is RSS, an <entry> is Atom — search the whole tree so a
    # namespaced or nested channel still matches.
    entries = [el for el in root.iter() if local(el.tag) in ("item", "entry")]
    for entry in entries:
        is_atom = local(entry.tag) == "entry"
        link = atom_link(entry) if is_atom else first_child_text(entry, "link")
        if not link:
            continue
        title = first_child_text(entry, "title")
        # Body: content:encoded (RSS) > description (RSS) > summary (Atom).
        note = (
            first_child_text(entry, "encoded")
            or first_child_text(entry, "description")
            or first_child_text(entry, "summary")
        )
        tags: list[str] = []
        for child in entry:
            if local(child.tag) == "category":
                term = child.get("term") or (child.text or "").strip()
                if term:
                    tags.append(term.strip())
        items.append(RawItem(
            url=link.strip(),
            title=title or None,
            tags=tags,
            note=note or None,
        ))
    return items


async def ingest_feed(
    xml: str,
    memory_path: Path,
    *,
    commit: bool = True,
) -> tuple[int, int]:
    """Parse a feed and push its items through the standard ingest path.

    Thin convenience over ``parse_rss`` + ``ingest_batch``; returns the same
    ``(created, duplicates)`` envelope. ``from_bookmark_file=False`` so the
    ``_classify`` fallback keeps youtube/url media types (no ``rss`` type — that
    would ripple into graph colors).
    """
    items = parse_rss(xml)
    if not items:
        return 0, 0
    return await ingest_batch(items, memory_path, from_bookmark_file=False, commit=commit)


def parse_upload(
    content: bytes,
    filename: str,
    *,
    include_history: bool = False,
    warnings: list[str] | None = None,
) -> tuple[list[RawItem], str, bool]:
    """Route an uploaded file to the right parser by extension + sniff.

    Returns ``(items, source_label, from_bookmark_file)``.

    ``include_history`` (G71 §3) opts a TikTok export's Browsing History in —
    default off, because ambient watch/browse exhaust is noise, not a save.
    ``warnings`` is an optional sink a caller (the preview endpoint) passes so
    partial-parse detail reaches the user instead of only the debug log; every
    existing positional caller is unaffected.
    """
    name = (filename or "").lower()
    if name.endswith(".xml") or name.endswith(".rss") or name.endswith(".atom"):
        return parse_rss(content.decode("utf-8", errors="replace")), "RSS Feed", False
    if name.endswith(".html") or name.endswith(".htm"):
        # parse_safari_bookmarks falls through to parse_netscape_bookmarks for
        # non-plist bytes, so this is byte-for-byte the same output as before
        # for Chrome/Firefox exports too — Safari's HTML export is Netscape
        # format anyway.
        return parse_safari_bookmarks(content), "Bookmarks", True
    if name.endswith(".plist"):
        return parse_safari_bookmarks(content), "Safari Bookmarks", True
    if name.endswith(".json"):
        data = json.loads(content)
        if isinstance(data, dict) and "roots" in data:
            return parse_chrome_bookmarks_json(data), "Chrome Bookmarks", True
        # Instagram "Download your information" saved-posts export — sniffed
        # BEFORE the generic-JSON fallback below (and before the Takeout list
        # check, which only ever matches a list, never a dict, so ordering
        # between the two doesn't matter).
        if _is_instagram_saved_json(data):
            return parse_instagram_saved(data), "Instagram Saved", False
        # TikTok's export nests everything under an activity wrapper, so it can
        # never collide with the Instagram (`saved_*`) or Takeout (list) sniffs.
        if _is_tiktok_export_json(data):
            items = parse_tiktok_export(data, include_history=include_history)
            if not include_history and warnings is not None:
                # Browsing History was intentionally dropped by the
                # ``include_history`` opt-in above — a preview caller must
                # still be told it exists, or "recognized" silently hides
                # data the export actually contains (G71 §3 fix round: the
                # Task 4 brief under-specified this). Re-run with history
                # included just to size the gap; cheap in-memory JSON walk,
                # no I/O.
                excluded = len(parse_tiktok_export(data, include_history=True)) - len(items)
                if excluded > 0:
                    warnings.append(
                        f"Browsing history ({excluded} item"
                        f"{'s' if excluded != 1 else ''}) excluded by default — "
                        "enable it when importing."
                    )
            return items, "TikTok Export", False
        # Takeout JSON is a list of watch entries; otherwise a generic URL list.
        if isinstance(data, list) and data and isinstance(data[0], dict) and (
            "titleUrl" in data[0] or "subtitles" in data[0]
        ):
            return parse_youtube_takeout(content, name), "YouTube Takeout", False
        # Generic JSON URL list: list[str] or list[{url}].
        items: list[RawItem] = []
        if isinstance(data, list):
            for entry in data:
                if isinstance(entry, str):
                    items.append(RawItem(url=entry))
                elif isinstance(entry, dict) and entry.get("url"):
                    items.append(RawItem(url=entry["url"], title=entry.get("title")))
        return items, "URL List", False
    if name.endswith(".csv"):
        # A per-playlist Takeout CSV is sniffed by header (a real video-id
        # column), not a fragile "in text" substring check — an unrecognized
        # CSV (no such column) falls through to the plain URL-list parser.
        # Pass the *original* filename (not the lowercased ``name``) so the
        # derived playlist folder keeps its real casing.
        playlist_items = parse_youtube_playlist_csv(content, filename or name)
        if playlist_items:
            return playlist_items, "YouTube Playlist", False
        reddit_items = parse_reddit_saved_csv(content, filename or name)
        if reddit_items:
            return reddit_items, "Reddit Saved Export", False
        linkedin_items = parse_linkedin_saved(content, filename or name)
        if linkedin_items:
            return linkedin_items, "LinkedIn Saved", False
        return parse_csv_url_list(content.decode("utf-8", errors="replace")), "URL List", False
    if name.endswith(".zip"):
        # L4 (final review): a zip is sniffed by extension alone, but
        # `parse_youtube_takeout_zip` only recognizes `playlists/*.csv` /
        # `watch-history.json` members — a non-Takeout archive (an Instagram
        # or TikTok export, say) reads as an empty zip to it and previously
        # still carried the "YouTube Takeout (zip)" label into the preview's
        # "found no saved links" warning, naming the wrong platform. Only
        # claim the specific label when it actually found Takeout-shaped
        # content; otherwise a generic one, same "unzip it and drop the
        # individual file" guidance either way (via the caller's `total == 0`
        # warning below).
        zip_items = parse_youtube_takeout_zip(content, warnings)
        zip_label = "YouTube Takeout (zip)" if zip_items else "ZIP archive"
        return zip_items, zip_label, False
    if name.endswith(".txt"):
        return parse_url_list(content.decode("utf-8", errors="replace")), "URL List", False
    raise ValueError(
        "Unsupported file format. Use .html, .json, .csv, .txt, .plist, .zip, or .xml/.rss/.atom"
    )


# --- Import preview (G71 §4.3) ----------------------------------------------

# `parse_upload` source label -> stable lowercase platform id. The id is never
# user-facing: the companion app owns every display name (Copy.swift). Tasks
# that add a parser add their label here.
PLATFORM_BY_LABEL = {
    "Instagram Saved": "instagram",
    "YouTube Takeout": "youtube",
    "YouTube Takeout (zip)": "youtube",
    "YouTube Playlist": "youtube",
    "Bookmarks": "bookmarks",
    "Safari Bookmarks": "bookmarks",
    "Chrome Bookmarks": "bookmarks",
    "RSS Feed": "rss",
    "URL List": "urls",
    "LinkedIn Saved": "linkedin",
    "TikTok Export": "tiktok",
    "Reddit Saved Export": "reddit",
}

# What ONE grouping is called on each platform, so the overlay can say
# "6 collections" / "6 boards" instead of a generic word.
COLLECTION_KIND_BY_PLATFORM = {
    "instagram": "collection",
    "youtube": "playlist",
    "pinterest": "board",
    "bookmarks": "folder",
    "rss": "feed",
    "urls": "list",
    "linkedin": "saved",
    "tiktok": "list",
    "reddit": "saved",
    "unknown": "list",
}

DEFAULT_COLLECTION_NAME = "Ungrouped"


@dataclass
class UploadPreview:
    """What a dropped export CONTAINS — computed without staging any of it."""

    recognized: bool
    platform: str
    total: int
    collections: list[dict]  # [{"name": str, "kind": str, "count": int}]
    warnings: list[str]


def preview_upload(
    content: bytes, filename: str, *, include_history: bool = False
) -> UploadPreview:
    """Parse an upload WITHOUT staging anything (G71 §4.3).

    Pure and side-effect free: no episode, no entity, no ``url_index`` write,
    no commit, no network — it runs the same sniff/parse ``parse_upload`` does
    and then only *counts*. ``recognized`` is ``total > 0``: a format we can
    name but from which nothing parses is not a usable export, and saying
    "recognized" about it would be a lie the overlay then repeats.
    """
    warnings: list[str] = []
    try:
        items, label, _ = parse_upload(
            content, filename, include_history=include_history, warnings=warnings
        )
    except ValueError as e:
        # `parse_upload`'s own "Unsupported file format" message already names
        # what's wrong without a filename; every OTHER ValueError bubbling up
        # from a parser (e.g. a `json.JSONDecodeError`, itself a ValueError)
        # needs the filename stitched in or the warning is anonymous.
        msg = str(e)
        if not msg.startswith("Unsupported file format"):
            msg = f"Could not parse {filename or 'this file'}: {msg}"
        return UploadPreview(False, "unknown", 0, [], [msg])
    except Exception as e:
        return UploadPreview(
            False, "unknown", 0, [],
            [f"Could not parse {filename or 'this file'}: {type(e).__name__}: {e}"],
        )

    platform = PLATFORM_BY_LABEL.get(label, "unknown")
    kind = COLLECTION_KIND_BY_PLATFORM.get(platform, "list")

    counts: dict[str, int] = {}
    for item in items:
        if not item.url:
            continue
        name = (item.folder or "").strip() or DEFAULT_COLLECTION_NAME
        counts[name] = counts.get(name, 0) + 1

    total = sum(counts.values())
    if total == 0:
        warnings.append(
            f"Read this as {label} but found no saved links in it — if you dropped "
            "an archive, unzip it and drop the individual export file instead."
        )
    # M3 (final review): mirror the SAME check `POST /sources/upload`'s
    # confirm path enforces (`len(items) > MAX_BATCH` -> 413), on the SAME
    # basis (`items`, before the URL-filtering `counts` above) — the preview
    # promising an import Confirm then refuses is the bug being fixed, so the
    # two checks must agree exactly. Deliberately a warning only: Confirm
    # still hard-rejects rather than silently importing a truncated first
    # slice, so this preview must not claim partial success either.
    if len(items) > MAX_BATCH:
        warnings.append(
            f"{len(items):,} items exceeds the {MAX_BATCH:,}-item batch cap — "
            "Confirm will reject this import; split the export into smaller "
            "files first."
        )

    collections = [
        {"name": n, "kind": kind, "count": counts[n]}
        for n in sorted(counts, key=lambda n: (-counts[n], n))
    ]
    return UploadPreview(total > 0, platform, total, collections, warnings)


# --- Relevance metric (§3.4, feed sorting) ---------------------------------


def compute_relevance(fm: dict, *, now: datetime | None = None) -> float:
    """Compose a [0,1] relevance score for a saved media item from its frontmatter.

    ``relevance = confidence x recency_decay x personal_weight`` then clamped to
    [0,1]. Mirrors the temporal-decay model used elsewhere in the graph:

    - ``confidence`` (default 0.7) — the save-time/Sleep-adjusted confidence;
    - ``recency_decay = exp(-decay_rate * weeks_since_last_referenced)`` — fresh
      items score near 1.0, stale items fade;
    - ``personal_relevance_weight`` (default 1.0) — an optional manual boost
      surfaced by §3.2 (read-if-present, neutral otherwise).

    The rate comes from :func:`decay_policy.resolve`, NOT from a raw
    ``decay_rate:`` read (G66 §1.9). That matters for a page written before the
    class vocabulary existed and not yet touched by the backfill: a legacy
    ``type: media`` page still carrying ``decay_rate: 0.03`` resolves to
    ``evergreen``/0.0, so the Feed agrees with the graph, the entity engine and
    the claim engine instead of being the one consumer that still fades a
    bookmark. An explicit numeric on a decaying class still wins, per the
    resolver's own precedence.

    Pure + side-effect-free so it is directly unit-testable. Any malformed field
    degrades to its default rather than raising.
    """
    import math

    now = now or datetime.now()

    try:
        confidence = float(fm.get("confidence", 0.7))
    except (TypeError, ValueError):
        confidence = 0.7
    confidence = max(0.0, min(1.0, confidence))

    decay_rate = decay_policy.resolve(fm)[1]  # already clamped to >= 0

    # Age in weeks since last reference (or save). Default: treat as fresh.
    weeks = 0.0
    ref = fm.get("last_referenced")
    ref_dt = None
    if isinstance(ref, str) and ref:
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
            try:
                ref_dt = datetime.strptime(ref[: len(fmt) + 2], fmt)
                break
            except ValueError:
                continue
    if ref_dt is not None:
        weeks = max(0.0, (now - ref_dt).total_seconds() / (7 * 86400))

    recency_decay = math.exp(-decay_rate * weeks)

    try:
        weight = float(fm.get("personal_relevance_weight", 1.0))
    except (TypeError, ValueError):
        weight = 1.0
    weight = max(0.0, weight)

    score = confidence * recency_decay * weight
    return max(0.0, min(1.0, score))


# --- Episode ID generation (shared, collision-safe) ---


def _next_episode_id(episodes_dir: Path, ep_date: str) -> str:
    """Next ``ep_<date>_NNN`` id = max existing seq for that date + 1.

    Max-based (not ``len(glob)+1``) so deletions never cause a collision.
    """
    max_num = 0
    for filepath in episodes_dir.glob(f"ep_{ep_date}_*.md"):
        try:
            max_num = max(max_num, int(filepath.stem.split("_")[-1]))
        except ValueError:
            continue
    return f"ep_{ep_date}_{max_num + 1:03d}"


# --- Writers ---


def _episode_body(
    meta: MediaMeta,
    url: str,
    saved_date: str,
    note: str | None,
    folder: str | None = None,
    reason: str | None = None,
) -> str:
    lines = [
        f"# {meta.title}",
        "",
        f"**Source:** {meta.media_type}",
        f"**URL:** {url}",
    ]
    if meta.site:
        lines.append(f"**Site:** {meta.site}")
    if meta.channel:
        lines.append(f"**Channel:** {meta.channel}")
    if folder:
        lines.append(f"**Folder:** {folder}")
    lines.append(f"**Saved:** {saved_date}")
    if meta.description:
        lines += ["", "## Description", meta.description]
    if reason:
        lines += ["", "## Saved because", reason]
    if note:
        lines += ["", "## User note", note]
    return "\n".join(lines)


def _entity_body(meta: MediaMeta, note: str | None) -> str:
    summary = f"Saved {meta.media_type} — {meta.title}."
    lines = ["## Summary", summary]
    if meta.description:
        lines += ["", "## Description", meta.description]
    if note:
        lines += ["", "## Notes", note]
    return "\n".join(lines)


def write_media_episode(
    episodes_dir: Path, item: RawItem, meta: MediaMeta, media_entity_id: str
) -> str:
    episodes_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    ep_date = now.strftime("%Y-%m-%d")
    episode_id = _next_episode_id(episodes_dir, ep_date)
    timestamp = now.isoformat() + "Z"
    saved_date = ep_date

    body = _episode_body(
        meta, item.url, saved_date, item.note, folder=item.folder, reason=item.reason
    )
    content_hash = hashlib.sha256(normalize_url(item.url).encode()).hexdigest()[:12]

    frontmatter = {
        "id": episode_id,
        "timestamp": timestamp,
        "source": meta.media_type,
        "title": meta.title,
        "processed": False,
        "content_hash": content_hash,
        "url": item.url,
        "media_entity_id": media_entity_id,
        "folder": item.folder or None,
    }
    if item.origin:
        frontmatter["origin"] = item.origin
    if item.session_id:
        frontmatter["session_id"] = item.session_id
        if item.harness and item.harness != "unknown":
            frontmatter["harness"] = item.harness
        if item.project_dir:
            frontmatter["project_dir"] = item.project_dir
    markdown_parser.write(episodes_dir / f"{episode_id}.md", frontmatter, body)
    return episode_id


# Byte budget for the slug portion of a media entity id. macOS/APFS (and most
# filesystems) cap a filename at 255 *bytes*, not characters — a long OG title
# heavy on multi-byte emoji/CJK can blow past that in far fewer than 255
# characters. "media-" (6 bytes) + slug + an optional "-<8 hex>" hash suffix
# (9 bytes) + ".md" (3 bytes) must stay comfortably under 255; 120 leaves a
# wide margin.
_MAX_SLUG_BYTES = 120


def _truncate_utf8(s: str, max_bytes: int) -> tuple[str, bool]:
    """Truncate ``s`` to at most ``max_bytes`` UTF-8 bytes without splitting a
    multi-byte character. Returns ``(truncated, was_truncated)``.
    """
    encoded = s.encode("utf-8")
    if len(encoded) <= max_bytes:
        return s, False
    chunk = encoded[:max_bytes]
    # Back off one byte at a time until the tail decodes cleanly (a multi-byte
    # UTF-8 character split mid-sequence raises UnicodeDecodeError).
    while chunk:
        try:
            return chunk.decode("utf-8"), True
        except UnicodeDecodeError:
            chunk = chunk[:-1]
    return "", True


def _media_entity_id(meta: MediaMeta, item: RawItem) -> str:
    slug = sanitize_id(meta.title) if meta.title else ""
    if not slug or slug == "unnamed":
        slug = sanitize_id(_fallback_title(item.url))

    slug, truncated = _truncate_utf8(slug, _MAX_SLUG_BYTES)
    slug = slug.strip("-") or "unnamed"
    if truncated:
        # A stable suffix derived from the URL so two different long titles
        # that truncate to the same prefix never collide on the same filename.
        suffix = hashlib.sha256(normalize_url(item.url).encode("utf-8")).hexdigest()[:8]
        slug = f"{slug}-{suffix}"
    return f"media-{slug}"


def write_media_entity(
    entities_dir: Path,
    entity_id: str,
    item: RawItem,
    meta: MediaMeta,
    episode_id: str,
) -> None:
    entities_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now()
    tag_set = set([meta.media_type] + (item.tags or []))
    # Sanitized folder-slug tag mirrors notes_sync stamping its Apple Notes
    # folder onto the episode: raw human path lives in frontmatter (below),
    # a filesystem-/graph-safe slug also lands in tags so folder/category is
    # filterable the same way any other tag is.
    if item.folder:
        tag_set.add(sanitize_id(item.folder))
    tags = sorted(tag_set)

    frontmatter = {
        "name": meta.title,
        "type": "media",
        "status": "active",
        "confidence": 0.7,
        "created": today.strftime("%Y-%m-%d"),
        "last_referenced": today.strftime("%Y-%m-%d"),
        **decay_policy.frontmatter_fields(
            decay_policy.default_class_for("media", source="media")
        ),
        "source_episodes": [episode_id],
        "tags": tags,
        "related": [],
        "version": 1,
        "folder": item.folder or None,
    }
    if item.origin:
        frontmatter["origin"] = item.origin
    frontmatter["media"] = {
        "url": item.url,
        "media_type": meta.media_type,
        "site": meta.site,
        "channel": meta.channel,
        "thumbnail": meta.thumbnail,
        "saved_at": today.isoformat() + "Z",
        "url_hash": url_hash(item.url),
    }
    body = _entity_body(meta, item.note)
    markdown_parser.write(entities_dir / f"{entity_id}.md", frontmatter, body)


# --- Dedup index ---


def load_url_index(memory_path: Path) -> dict:
    idx_file = memory_path / "sources" / "url_index.json"
    if not idx_file.exists():
        return {}
    try:
        return json.loads(idx_file.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def save_url_index(memory_path: Path, idx: dict) -> None:
    sources_dir = memory_path / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)
    (sources_dir / "url_index.json").write_text(
        json.dumps(idx, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# --- Single-item ingest + batch ---


async def ingest_one(
    item: RawItem, memory_path: Path, client, idx: dict, from_bookmark_file: bool = False
) -> IngestResult:
    h = url_hash(item.url)
    if h in idx:
        existing = idx[h]
        return IngestResult(
            status="duplicate",
            media_entity_id=existing.get("media_entity_id", ""),
            episode_id=existing.get("episode_id", ""),
            title=existing.get("title", item.title or _fallback_title(item.url)),
            media_type=existing.get("media_type", _classify(item.url, from_bookmark_file)),
            thumbnail=existing.get("thumbnail"),
            url=item.url,
        )

    meta = await enrich(item.url, client, from_bookmark_file=from_bookmark_file)
    # Prefer an explicit title from the parser (Takeout/bookmark name) when
    # enrichment fell back to a URL slug.
    if item.title and meta.title == _fallback_title(item.url):
        meta.title = item.title
    if item.channel and not meta.channel:
        meta.channel = item.channel

    entity_id = _media_entity_id(meta, item)
    episode_id = write_media_episode(
        memory_path / "episodes", item, meta, entity_id
    )
    write_media_entity(memory_path / "entities", entity_id, item, meta, episode_id)

    idx[h] = {
        "media_entity_id": entity_id,
        "episode_id": episode_id,
        "url": item.url,
        "title": meta.title,
        "media_type": meta.media_type,
        "thumbnail": meta.thumbnail,
        "saved_at": datetime.now().isoformat() + "Z",
    }
    return IngestResult(
        status="created",
        media_entity_id=entity_id,
        episode_id=episode_id,
        title=meta.title,
        media_type=meta.media_type,
        thumbnail=meta.thumbnail,
        url=item.url,
    )


def _dedup_items(items: list[RawItem], idx: dict) -> tuple[list[RawItem], int]:
    """Drop items already in the url_index and collapse in-batch dup URLs."""
    seen: set[str] = set()
    fresh: list[RawItem] = []
    skipped = 0
    for item in items:
        if not item.url:
            continue
        h = url_hash(item.url)
        if h in idx or h in seen:
            skipped += 1
            continue
        seen.add(h)
        fresh.append(item)
    return fresh, skipped


async def ingest_batch(
    items: list[RawItem],
    memory_path: Path,
    from_bookmark_file: bool = False,
    *,
    commit: bool = True,
) -> tuple[int, int]:
    """Enrich + write a batch with bounded concurrency. Returns (created, dup_in_idx).

    Re-checks the on-disk index at call time so a background job is idempotent
    even if the same file is uploaded twice.
    """
    import httpx

    idx = load_url_index(memory_path)
    fresh, _ = _dedup_items(items, idx)
    if not fresh:
        return 0, len(items)

    sem = asyncio.Semaphore(8)
    lock = asyncio.Lock()
    created = 0
    # Devin PR #25 round 1, finding 3: `_commit_media` used to `git add -A`,
    # which absorbs any PRE-EXISTING dirty edit in the bank (a hand-edit in
    # Obsidian, say) into a media/connector commit under false `user`
    # provenance. Track exactly the paths THIS batch wrote — the same
    # `commit_paths` mechanism the decay-watermark/decay-only commits use —
    # so the commit stages only its own outputs regardless of what else is
    # sitting dirty in the working tree.
    created_paths: list[str] = []

    async with httpx.AsyncClient() as client:
        async def worker(item: RawItem) -> None:
            nonlocal created
            async with sem:
                try:
                    result = await ingest_one(
                        item, memory_path, client, idx,
                        from_bookmark_file=from_bookmark_file,
                    )
                except Exception as e:
                    logger.warning(f"ingest_one failed for {item.url}: {type(e).__name__}: {e}")
                    return
            if result.status == "created":
                async with lock:
                    created += 1
                    created_paths.append(f"entities/{result.media_entity_id}.md")
                    created_paths.append(f"episodes/{result.episode_id}.md")

        await asyncio.gather(*(worker(it) for it in fresh))

    save_url_index(memory_path, idx)

    if commit and created:
        try:
            await _commit_media(memory_path, created, ["sources/url_index.json", *created_paths])
        except Exception as e:
            logger.warning(f"Media commit failed: {type(e).__name__}: {e}")

    return created, len(items) - len(fresh)


async def _commit_media(memory_path: Path, count: int, paths: list[str]) -> None:
    """Commit scoped to exactly ``paths`` — never ``git add -A`` (finding 3
    above). ``paths`` is memory-relative: ``sources/url_index.json`` plus one
    ``entities/<id>.md`` + ``episodes/<id>.md`` pair per item this batch
    actually created.
    """
    from api.services import git_service

    date_str = datetime.now().strftime("%Y-%m-%d")
    message = git_service.build_commit_message(
        f"Sources ingest {date_str}",
        [
            "sources/url_index.json: updated (trigger: user/media_save)",
            f"{count} media item(s) saved (trigger: user/media_save)",
        ],
        authors=["user"],
    )
    await git_service.commit_paths(memory_path, message, paths)


# --- Sleep-cycle media edge injection (CRITIC FIX) ---


def inject_media_edges(memory_path: Path, changes: list[dict]) -> int:
    """Wire ``media —about→ existing-entity`` edges, bypassing the promotion gate.

    For every ``media`` entity, join its ``source_episodes`` against the entities
    resolved this cycle (``changes``) that map to real entity files, and write an
    ``about`` edge. Reuses ``_write_graph_edges`` (dedup helper) and
    ``resolve_entity_file``/``build_name_index`` — no competing resolution logic.

    Returns the number of new edges submitted.
    """
    from api.services.id_utils import build_name_index, resolve_entity_id
    from api.services.inbox_generator import _write_graph_edges

    entities_dir = memory_path / "entities"
    if not entities_dir.exists():
        return 0

    # episode_id -> set of entity ids resolved (to real files) this cycle.
    name_index = build_name_index(entities_dir)
    episode_to_entities: dict[str, set[str]] = {}
    for change in changes:
        if not isinstance(change, dict):
            continue
        entity_id = change.get("id")
        resolved = resolve_entity_id(entities_dir, entity_id or "", name_index)
        if not resolved:
            continue
        eps = set(change.get("source_episodes") or [])
        single = change.get("source_episode")
        if single:
            eps.add(single)
        for ep in eps:
            if ep:
                episode_to_entities.setdefault(ep, set()).add(resolved)

    if not episode_to_entities:
        return 0

    new_edges: list[dict] = []
    for filepath in entities_dir.glob("media-*.md"):
        parsed = markdown_parser.parse(filepath)
        fm = parsed.frontmatter or {}
        if fm.get("type") != "media":
            continue
        media_id = filepath.stem
        for ep in fm.get("source_episodes") or []:
            for target_id in episode_to_entities.get(ep, set()):
                if target_id == media_id:
                    continue
                new_edges.append({
                    "source": media_id,
                    "target": target_id,
                    "label": "about",
                })

    if not new_edges:
        return 0

    _write_graph_edges(memory_path, new_edges)
    return len(new_edges)
