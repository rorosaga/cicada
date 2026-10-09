"""The platforms' own "download your data" exports, read for what the person saved.

One path for every platform export, the way chat exports have one intake
(``api/routers/intake.py``). A person asks Instagram, TikTok, Google Takeout,
X, Reddit or LinkedIn for their data, receives a ``.zip``, and drops it on
Cicada — the app, ``POST /sources/upload`` or ``cicada import``. The backend
only ever sees the bytes it was sent: it never opens ``~/Downloads`` or any
path a request names (CLAUDE.md, "the app reads ``~/Library``, the backend
parses bytes"). No hosted social API is involved, so nothing the person saved
passes through a third party, and no model runs here (no LLM at capture).

What this module decides, and nothing more:

* **Which member is which.** A platform archive holds far more than saves —
  messages, contacts, search history, media. A member is read only when its
  NAME says it is a save list this module knows (``like.js``,
  ``saved_posts.json``, ``playlists/*.csv``…). Everything else is counted and
  skipped unread; a media file is never opened. The generic "any CSV with a
  URL column" and "any JSON list of URLs" parsers that a single dropped file
  may fall back to are never used inside an archive: a LinkedIn
  ``Connections.csv`` has a URL column too, and it holds other people.
* **History is not a save.** Watch and browse history (YouTube's
  ``watch-history.json``, TikTok's browsing history) is read only when the
  caller opts in (G69/G71 §3: ambient exhaust, not saves); otherwise its size
  is said in a warning so the preview never hides what the archive contains.
* **One item per saved thing.** The same post can sit in two files of one
  archive (Instagram lists every save in ``saved_posts.json`` and again under
  its collection). Items merge on the same identity ``url_index`` uses
  (``media_ingestor.url_hash``), keeping the person's own collection name over
  a platform default and the first save date found.

Staging, dedup against what is already in memory (the direct connectors
included) and the writes are ``media_ingestor``'s, unchanged: a saved item is
one ``url_index`` row keyed by its normalized URL — the identity every
bookmark, connector, upload and single save already shares — so an export
never forks a link the person saved some other way.
"""

from __future__ import annotations

import json
import re
import zipfile
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import PurePosixPath
from typing import Callable, Iterable

from loguru import logger

from api.services import episode_scrub, media_ingestor, saved_at
from api.services.media_ingestor import RawItem

#: A member larger than this (uncompressed) is skipped with a warning instead of
#: read: no save list comes near it, and a crafted archive must not exhaust memory.
MAX_MEMBER_BYTES = 64 * 1024 * 1024
#: How many members may be READ from one archive (listing is free).
MAX_READ_MEMBERS = 2000

#: The connector's own spelling of a post's URL (``connectors/x.py``), so an
#: archive's like or bookmark and the API's bookmark dedupe on ``url_hash``.
X_STATUS_URL = "https://x.com/i/web/status/{id}"
X_TITLE_MAX = 80
#: Third-party text (a liked post's words) kept as the page's stand-in
#: description, cut like Safari's Reading List excerpt (round 4, R-SR13).
PREVIEW_MAX = 500

#: Platform id -> the ``parse_upload`` label ``PLATFORM_BY_LABEL`` maps back.
LABEL_BY_PLATFORM = {
    "instagram": "Instagram Saved",
    "tiktok": "TikTok Export",
    "youtube": "YouTube Takeout (zip)",
    "reddit": "Reddit Saved Export",
    "linkedin": "LinkedIn Saved",
    "x": "X Archive",
}
MIXED_LABEL = "Saved-content archive"
EMPTY_LABEL = "ZIP archive"

_X_FILE = re.compile(r"^(like|likes|bookmark|bookmarks)(-part\d+)?\.js$")
_X_KIND = {"like": "like", "likes": "like", "bookmark": "bookmark", "bookmarks": "bookmark"}
_INSTAGRAM_FILES = {"saved_posts.json", "saved_collections.json", "liked_posts.json"}
#: TikTok's TXT export, one file per list (``Activity/Like List.txt`` …).
_TIKTOK_TXT = {
    "like list.txt": ("Likes", False),
    "favorite videos.txt": ("Favorites", False),
    "video browsing history.txt": ("Browsing History", True),
    "browsing history.txt": ("Browsing History", True),
    "watch history.txt": ("Browsing History", True),
}
#: Extensions never opened inside an archive.
_UNREAD_EXT = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".mp4", ".mov", ".m4a", ".mp3", ".webm",
               ".srt", ".vtt", ".pdf", ".woff", ".woff2", ".ttf", ".css", ".svg", ".ico")


@dataclass
class ArchiveResult:
    """What one archive (or one folder's files) holds, before anything is staged."""

    items: list[RawItem] = field(default_factory=list)
    platforms: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    #: Members read and recognized, by archive path.
    members: list[str] = field(default_factory=list)
    skipped: int = 0
    history_excluded: int = 0

    @property
    def label(self) -> str:
        if not self.items:
            return EMPTY_LABEL
        if len(self.platforms) == 1:
            return LABEL_BY_PLATFORM[self.platforms[0]]
        return MIXED_LABEL


# --- one member ------------------------------------------------------------


def is_save_list(path: str) -> bool:
    """Whether a member's NAME is one this module reads (the archive walker and
    the app's folder walk ask the same question, so neither reads a file the
    other would skip)."""
    p = PurePosixPath(path.replace("\\", "/"))
    base = p.name.lower()
    low = str(p).lower()
    if _X_FILE.match(base) or base in _INSTAGRAM_FILES or base in _TIKTOK_TXT:
        return True
    if base.startswith("user_data") and base.endswith(".json"):
        return True
    if base == "watch-history.json" or (base.endswith(".csv") and "playlists/" in low):
        return True
    if base.endswith(".csv") and (media_ingestor._is_reddit_saved_filename(base)
                                  or media_ingestor._is_linkedin_saved_filename(base)):
        return True
    return False


def parse_member(path: str, data: bytes, *, include_history: bool = False) -> tuple[list[RawItem], str | None, int]:
    """One archive member -> ``(items, platform, history_excluded)``.

    ``platform`` is ``None`` when the member is not a save list this module
    reads (the caller counts it as skipped). Never raises on bad content: a
    member that will not parse yields ``[]`` for its platform.
    """
    p = PurePosixPath(path.replace("\\", "/"))
    base = p.name.lower()
    low = str(p).lower()

    m = _X_FILE.match(base)
    if m:
        return parse_x_archive_js(data, _X_KIND[m.group(1)]), "x", 0

    if base in _INSTAGRAM_FILES:
        try:
            parsed = json.loads(data)
        except ValueError:
            return [], "instagram", 0
        return media_ingestor.parse_instagram_saved(parsed), "instagram", 0

    if base in _TIKTOK_TXT:
        folder, is_history = _TIKTOK_TXT[base]
        items = parse_tiktok_txt(data, folder=folder, is_history=is_history)
        if is_history and not include_history:
            return [], "tiktok", len(items)
        return items, "tiktok", 0

    if base.startswith("user_data") and base.endswith(".json"):
        try:
            parsed = json.loads(data)
        except ValueError:
            return [], None, 0
        if not media_ingestor._is_tiktok_export_json(parsed):
            return [], None, 0
        items = media_ingestor.parse_tiktok_export(parsed, include_history=include_history)
        excluded = 0
        if not include_history:
            excluded = len(media_ingestor.parse_tiktok_export(parsed, include_history=True)) - len(items)
        return items, "tiktok", excluded

    if base == "watch-history.json":
        try:
            items = media_ingestor.parse_youtube_takeout(data, base)
        except ValueError:
            return [], "youtube", 0
        if not include_history:
            return [], "youtube", len(items)
        return items, "youtube", 0

    if base.endswith(".csv") and "playlists/" in low:
        return media_ingestor.parse_youtube_playlist_csv(data, p.name), "youtube", 0

    if base.endswith(".csv") and media_ingestor._is_reddit_saved_filename(base):
        return media_ingestor.parse_reddit_saved_csv(data, p.name), "reddit", 0

    if base.endswith(".csv") and media_ingestor._is_linkedin_saved_filename(base):
        return media_ingestor.parse_linkedin_saved(data, p.name), "linkedin", 0

    return [], None, 0


# --- the walkers -------------------------------------------------------------


Reader = Callable[[], bytes]


def parse_members(members: Iterable[tuple[str, int, Reader]], *, include_history: bool = False) -> ArchiveResult:
    """Every ``(path, size, read)`` member through :func:`parse_member`.

    A folder the CLI walks and a zip the backend received both arrive here, so
    the two cannot read an export differently. ``read`` is called only for a
    member whose name is a save list and whose size is within the cap.
    """
    out = ArchiveResult()
    merged: dict[str, RawItem] = {}
    read = 0
    oversized = 0
    for path, size, reader in members:
        parts = PurePosixPath(path.replace("\\", "/")).parts
        base = parts[-1] if parts else ""
        if not base or base.startswith(".") or "__MACOSX" in parts:
            continue
        if base.lower().endswith(_UNREAD_EXT) or not is_save_list(path):
            out.skipped += 1
            continue
        if size > MAX_MEMBER_BYTES:
            oversized += 1
            continue
        if read >= MAX_READ_MEMBERS:
            out.skipped += 1
            continue
        read += 1
        try:
            data = reader()
            items, platform, excluded = parse_member(path, data, include_history=include_history)
        except Exception as exc:  # noqa: BLE001 - one bad member never sinks the archive
            # The class only: a message could quote the member's own text.
            logger.warning(f"Saved export: skipped an unreadable member ({type(exc).__name__})")
            out.skipped += 1
            continue
        if platform is None:
            out.skipped += 1
            continue
        out.history_excluded += excluded
        if items or excluded:
            out.members.append(path)
        if items and platform not in out.platforms:
            out.platforms.append(platform)
        for item in items:
            _merge(merged, item)
    out.items = list(merged.values())
    if oversized:
        out.warnings.append(f"Skipped {oversized} file(s) over {MAX_MEMBER_BYTES // (1024 * 1024)} MB inside the archive.")
    if out.history_excluded:
        n = out.history_excluded
        out.warnings.append(f"Watch and browsing history ({n} item{'s' if n != 1 else ''}) excluded by default — "
                            "enable it when importing.")
    return out


def parse_archive(content: bytes, *, include_history: bool = False) -> ArchiveResult:
    """A whole export ``.zip``. An unreadable archive is an empty result with a warning."""
    try:
        zf = zipfile.ZipFile(BytesIO(content))
    except Exception:  # noqa: BLE001 - BadZipFile, a truncated upload, an empty body
        return ArchiveResult(warnings=["This file is not a readable zip archive."])
    with zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        return parse_members(((i.filename, i.file_size, (lambda i=i: zf.read(i))) for i in infos),
                             include_history=include_history)


def _merge(merged: dict[str, RawItem], item: RawItem) -> None:
    key = media_ingestor.url_hash(item.url)
    have = merged.get(key)
    if have is None:
        merged[key] = item
        return
    if _is_default_folder(have.folder) and not _is_default_folder(item.folder):
        have.folder = item.folder
    if not have.added and item.added:
        have.added = item.added
    if not have.title and item.title:
        have.title = item.title


def _is_default_folder(folder: str | None) -> bool:
    return not folder or folder == "Saved"


# --- X (Twitter) archive -----------------------------------------------------


def parse_x_archive_js(data: bytes, kind: str) -> list[RawItem]:
    """X's archive ``data/like.js`` (and ``bookmark.js`` should an archive carry one).

    Each file is ``window.YTD.<name>.part<N> = [ {"like": {"tweetId", "fullText",
    "expandedUrl"}} … ]``. The URL is built from the post id in the connector's
    own spelling, so a like and an API bookmark of one post are one page. The
    archive gives no like date, so none is recorded (never guessed). The post's
    words are its author's, not the person's: they become the title and the
    page's stand-in description (``preview``), scrubbed here, and never a
    ``note`` (which the episode renders as the person's own). ``defer_enrich``:
    the words are already in hand, and a post page is script-rendered and often
    walled — the import asks nothing of the network for it.
    """
    try:
        text = data.decode("utf-8-sig", errors="replace")
    except Exception:  # noqa: BLE001
        return []
    start = text.find("[")
    if start < 0:
        return []
    body = text[start:].strip().rstrip(";")
    try:
        rows = json.loads(body)
    except ValueError:
        return []
    if not isinstance(rows, list):
        return []
    origin = "x-likes" if kind == "like" else "x-bookmarks"
    folder = "Likes" if kind == "like" else "Bookmarks"
    items: list[RawItem] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        rec = row.get(kind) or row.get(kind + "s") or (next(iter(row.values()), None) if len(row) == 1 else None)
        if not isinstance(rec, dict):
            continue
        tweet_id = str(rec.get("tweetId") or rec.get("tweet_id") or "").strip()
        if not tweet_id.isdigit():
            continue
        words, _ = episode_scrub.scrub(" ".join(str(rec.get("fullText") or "").split()))
        title = None
        if words:
            title = (words[:X_TITLE_MAX].rstrip() + "…") if len(words) > X_TITLE_MAX else words
        items.append(RawItem(
            url=X_STATUS_URL.format(id=tweet_id),
            title=title,
            preview=(words[:PREVIEW_MAX] or None),
            folder=folder,
            origin=origin,
            defer_enrich=True,
        ))
    return items


# --- TikTok TXT export -------------------------------------------------------


def parse_tiktok_txt(data: bytes, *, folder: str, is_history: bool) -> list[RawItem]:
    """TikTok's TXT export: blocks of ``Date: …`` / ``Link: …`` lines."""
    text = data.decode("utf-8-sig", errors="replace")
    items: list[RawItem] = []
    date: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        key, sep, value = line.partition(":")
        if not sep:
            continue
        key = key.strip().lower()
        value = value.strip()
        if key == "date":
            date = value
        elif key in ("link", "video link", "url"):
            if value.startswith(("http://", "https://")):
                items.append(RawItem(
                    url=value,
                    added=saved_at.from_tiktok(date),
                    folder=folder,
                    origin="tiktok-history" if is_history else "tiktok-saved",
                ))
            date = None
    return items


__all__ = ["ArchiveResult", "LABEL_BY_PLATFORM", "MAX_MEMBER_BYTES", "is_save_list", "parse_archive",
           "parse_member", "parse_members", "parse_tiktok_txt", "parse_x_archive_js"]
