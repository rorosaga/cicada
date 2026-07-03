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
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from loguru import logger

from api.services import markdown_parser
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
    if from_bookmark_file:
        return "bookmark"
    return "url"


def _site_of(url: str) -> str | None:
    host = (urlparse(url if "://" in url else "https://" + url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else (host or None)


def _fallback_title(url: str) -> str:
    parsed = urlparse(url if "://" in url else "https://" + url)
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
        folder = a.find_previous("h3")
        if folder and folder.get_text(strip=True):
            tags.append(folder.get_text(strip=True))
        items.append(RawItem(
            url=href,
            title=(a.get_text(strip=True) or None),
            tags=tags,
            added=a.get("add_date"),
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
        (``javascript:``, ``mailto:``, etc.) are skipped too.
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

    def walk(node) -> None:
        if not isinstance(node, dict):
            return
        if node.get("WebBookmarkType") == "WebBookmarkTypeLeaf":
            url = node.get("URLString")
            if isinstance(url, str) and url.startswith(("http://", "https://")):
                uri_dict = node.get("URIDictionary")
                title = uri_dict.get("title") if isinstance(uri_dict, dict) else None
                items.append(RawItem(url=url, title=title or None))
            return
        for child in node.get("Children", []) or []:
            walk(child)

    walk(root)
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
    """Chrome ``Bookmarks`` JSON — recurse the roots tree, type=='url'."""
    items: list[RawItem] = []

    def walk(node):
        if not isinstance(node, dict):
            return
        if node.get("type") == "url" and node.get("url"):
            items.append(RawItem(
                url=node["url"],
                title=node.get("name") or None,
                added=node.get("date_added"),
            ))
        for child in node.get("children", []) or []:
            walk(child)

    roots = data.get("roots", {})
    if isinstance(roots, dict):
        for root in roots.values():
            walk(root)
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


def parse_upload(content: bytes, filename: str) -> tuple[list[RawItem], str, bool]:
    """Route an uploaded file to the right parser by extension + sniff.

    Returns ``(items, source_label, from_bookmark_file)``.
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
        text = content.decode("utf-8", errors="replace")
        if "Video ID" in text or "Video Id" in text:
            return parse_youtube_takeout(content, name), "YouTube Takeout", False
        return parse_csv_url_list(text), "URL List", False
    if name.endswith(".txt"):
        return parse_url_list(content.decode("utf-8", errors="replace")), "URL List", False
    raise ValueError(
        "Unsupported file format. Use .html, .json, .csv, .txt, .plist, or .xml/.rss/.atom"
    )


# --- Relevance metric (§3.4, feed sorting) ---------------------------------


def compute_relevance(fm: dict, *, now: datetime | None = None) -> float:
    """Compose a [0,1] relevance score for a saved media item from its frontmatter.

    ``relevance = confidence x recency_decay x personal_weight`` then clamped to
    [0,1]. Mirrors the temporal-decay model used elsewhere in the graph:

    - ``confidence`` (default 0.7) — the save-time/Sleep-adjusted confidence;
    - ``recency_decay = exp(-decay_rate * weeks_since_last_referenced)`` — fresh
      items score near 1.0, stale items fade; ``decay_rate`` defaults to 0.03/wk;
    - ``personal_relevance_weight`` (default 1.0) — an optional manual boost
      surfaced by §3.2 (read-if-present, neutral otherwise).

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

    try:
        decay_rate = float(fm.get("decay_rate", 0.03))
    except (TypeError, ValueError):
        decay_rate = 0.03
    decay_rate = max(0.0, decay_rate)

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


def _episode_body(meta: MediaMeta, url: str, saved_date: str, note: str | None) -> str:
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
    lines.append(f"**Saved:** {saved_date}")
    if meta.description:
        lines += ["", "## Description", meta.description]
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

    body = _episode_body(meta, item.url, saved_date, item.note)
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
    }
    markdown_parser.write(episodes_dir / f"{episode_id}.md", frontmatter, body)
    return episode_id


def _media_entity_id(meta: MediaMeta, item: RawItem) -> str:
    slug = sanitize_id(meta.title) if meta.title else ""
    if not slug or slug == "unnamed":
        slug = sanitize_id(_fallback_title(item.url))
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
    tags = sorted(set([meta.media_type] + (item.tags or [])))

    frontmatter = {
        "name": meta.title,
        "type": "media",
        "status": "active",
        "confidence": 0.7,
        "created": today.strftime("%Y-%m-%d"),
        "last_referenced": today.strftime("%Y-%m-%d"),
        "decay_rate": 0.03,
        "source_episodes": [episode_id],
        "tags": tags,
        "related": [],
        "version": 1,
        "media": {
            "url": item.url,
            "media_type": meta.media_type,
            "site": meta.site,
            "channel": meta.channel,
            "thumbnail": meta.thumbnail,
            "saved_at": today.isoformat() + "Z",
            "url_hash": url_hash(item.url),
        },
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

        await asyncio.gather(*(worker(it) for it in fresh))

    save_url_index(memory_path, idx)

    if commit and created:
        try:
            await _commit_media(memory_path, created)
        except Exception as e:
            logger.warning(f"Media commit failed: {type(e).__name__}: {e}")

    return created, len(items) - len(fresh)


async def _commit_media(memory_path: Path, count: int) -> None:
    from api.services import git_service

    date_str = datetime.now().strftime("%Y-%m-%d")
    message = git_service.build_commit_message(
        f"Sources ingest {date_str}",
        [
            "memory/sources/url_index.json: updated (trigger: user/media_save)",
            f"{count} media item(s) saved (trigger: user/media_save)",
        ],
        authors=["user"],
    )
    await git_service.commit_changes(memory_path, message)


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
