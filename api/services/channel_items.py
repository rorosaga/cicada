"""What came in, by name — the items a capture channel brought in (G161).

Every source row says *how many* came in (``sync_state`` → ``channel_registry``
→ the app's count line); this module says *which*: each item's own title and
day, newest first, a page at a time. It reads the same set the row's count
means wherever the bank records it, and says so channel by channel below:

* ``notes`` — ``sources/notes_index.json``: one entry per note, pointing at the
  latest episode written for it (``notes_sync``). The index keeps a note the
  person deleted in Notes, so the list can run longer than the last sync's count.
* ``calendar-local`` / ``calendar`` — the event episodes (``source_id``
  ``calendar-local:…`` / ``origin: calendar``), never a tombstoned one; the day
  is the event's own start. An event that left the synced window stays, as the
  stager keeps it.
* ``<browser>-tab-groups`` — the snapshot episodes keyed ``tab-group:<browser>:…``,
  never a tombstoned one.
* ``contacts-local`` — the ``person`` pages the Contacts sync matched (an
  ``addressbook://`` source Cicada added, or its photo mark): **the page's name
  only**. Never an address, a number, a note or the address-book id.
* ``<browser>-bookmarks`` — the URL hashes the last sync saw in the browser
  (``sources/bookmark_seen.json``) joined to the saved-URL index; a bank synced
  before that file existed falls back to the browser's media pages.
* ``safari-tabs``, the connectors, ``rss``, ``files`` — the media pages stamped
  with the channel's origins (``source_overview.CATALOG``); ``files`` also takes
  the pages written before writers stamped an origin, as its card does.
* the chat exports, ``wispr-flow``, ``telegram`` — the episodes of the origin;
  an episode that saved a link is listed as its media page.
* ``folder:<id>`` — one row per file of the folder (its episodes by
  ``folder_id``; a long file's sections are one row), by the file's own name.

Titles only on the wire (scrubbed, one line, ≤ 120 characters), never a body.
Engine-free, read-only, never outside the bank, and never a Store domain: the
router ETags each page and the app keeps it in memory, like provenance. The
``total`` is this list's own count — it is not promised to equal the row's
number (the drifts above are real and disclosed).
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

from api.services import (
    bank_index,
    bookmark_seen,
    bookmark_sync,
    calendar_local,
    contacts_local,
    episode_scrub,
    fact_sources,
    folder_source,
    media_ingestor,
    notes_sync,
    source_overview,
    tab_groups,
    wispr_flow,
)
from api.services.channel_registry import CHANNEL_IDS

#: Folded into the route's ETag: bump it when the body changes for the same bank files.
SHAPE = "g161-1"
LIMIT_DEFAULT = 50
LIMIT_MAX = 200
TITLE_CAP = 120

#: A chat export's channel id → the origin its episodes carry (`channel_registry._origin_channel`).
_ORIGIN_CHANNELS = {
    "chat-export:claude": ("claude-export",),
    "chat-export:chatgpt": ("chatgpt-export",),
    "chat-export:gemini": ("gemini-export",),
    "wispr-flow": (wispr_flow.ORIGIN,),
    "telegram": ("telegram",),
}
#: A channel whose items are media pages, by the origins its catalog row owns.
_MEDIA_CHANNELS = ("safari-tabs", "pinterest", "reddit", "x", "rss", "files")


def _catalog_origins(channel_id: str) -> tuple[str, ...]:
    for spec in source_overview.CATALOG:
        if spec.channel == channel_id:
            return spec.origins
    return ()


def known(memory_path: Path, channel_id: str) -> bool:
    """A channel id this bank can list: every fixed row, the always-listed local
    sources, each browser's bookmarks and tab groups, and every registered folder."""
    if channel_id in CHANNEL_IDS or channel_id in _ORIGIN_CHANNELS:
        return True
    if channel_id in (calendar_local.CHANNEL_ID, contacts_local.CHANNEL_ID):
        return True
    if channel_id in {bookmark_sync.channel_for(b) for b in bookmark_sync.CHROMIUM_BROWSERS}:
        return True
    if channel_id in {tab_groups.channel_id(b) for b in tab_groups.BROWSERS}:
        return True
    if channel_id.startswith(folder_source.CHANNEL_PREFIX):
        folder_id = channel_id[len(folder_source.CHANNEL_PREFIX):]
        return folder_source.get_folder(memory_path, folder_id) is not None
    return False


# --- small readers -----------------------------------------------------------


def _title(raw, fallback: str = "Untitled") -> str:
    """One line, scrubbed, at most `TITLE_CAP` characters — never a body."""
    text = " ".join(str(raw or "").split())
    if not text:
        return fallback
    text, _ = episode_scrub.scrub(text)
    return text if len(text) <= TITLE_CAP else text[: TITLE_CAP - 1].rstrip() + "…"


def _instant(raw) -> datetime | None:
    """Any of the bank's three timestamp shapes, or a bare date, as an aware UTC instant."""
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        dt = raw
    elif isinstance(raw, date):
        return datetime(raw.year, raw.month, raw.day, tzinfo=timezone.utc)
    else:
        text = str(raw).strip()
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                d = date.fromisoformat(text[:10])
            except ValueError:
                return None
            return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.astimezone()   # a naive stamp is the writer's LOCAL time (source_overview._activity_day)
    return dt.astimezone(timezone.utc)


def _day(raw) -> str | None:
    """A bare date stays that date; an instant is its UTC day (the Sources page's rule)."""
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw.isoformat()
    text = str(raw or "").strip()
    if len(text) == 10:
        try:
            return date.fromisoformat(text).isoformat()
        except ValueError:
            return None
    at = _instant(raw)
    return at.date().isoformat() if at else None


def _row(kind: str, item_id: str, title: str, day: str | None, sort_at: datetime | None) -> dict:
    return {"kind": kind, "id": item_id, "title": title, "day": day,
            "_sort": (sort_at or datetime.min.replace(tzinfo=timezone.utc)).timestamp()}


def _episode_row(fm: dict, stem: str, *, when_key: str | None = None) -> dict:
    """An episode by its own title. The day is `when_key`'s value when given (an event's start), else the
    day the source dated it (`original_date`), else the day Cicada captured it."""
    own = fm.get(when_key) if when_key else None
    when = own or fm.get("original_date") or fm.get("timestamp")
    # An event's day is its own calendar day as written (`2026-10-01T09:00:00-05:00` is Oct 1), never shifted to UTC.
    day = _day(str(own)[:10]) if own and len(str(own)) >= 10 else _day(when)
    return _row("episode", str(fm.get("id") or stem), _title(fm.get("title")), day,
                _instant(when) or _instant(fm.get("timestamp")))


class _Media:
    """The saved-URL index and the media pages, read once per request."""

    def __init__(self, memory_path: Path):
        self.pages = {f.stem: f.frontmatter or {} for f in bank_index.files(memory_path, "entities")
                      if (f.frontmatter or {}).get("type") == "media"}
        try:
            index = media_ingestor.load_url_index(memory_path)
        except Exception:
            index = {}
        self.by_hash = index if isinstance(index, dict) else {}
        self.by_entity: dict[str, dict] = {}
        for entry in self.by_hash.values():
            if isinstance(entry, dict) and entry.get("media_entity_id") and not entry.get("alias_of"):
                self.by_entity.setdefault(str(entry["media_entity_id"]), entry)

    def row(self, entity_id: str) -> dict | None:
        fm = self.pages.get(entity_id)
        if fm is None or source_overview.is_hidden(fm):
            return None   # the Feed hides it too (F6), so a click would land nowhere
        entry = self.by_entity.get(entity_id) or {}
        saved = entry.get("content_saved_at") or entry.get("saved_at") or fm.get("created")
        title = entry.get("title") or fm.get("name") or entry.get("url") or entity_id
        return _row("media", entity_id, _title(title), _day(saved), _instant(saved))

    def by_origins(self, origins: tuple[str, ...], *, unstamped: bool = False) -> list[dict]:
        wanted = set(origins)
        rows = []
        for entity_id, fm in self.pages.items():
            origin = str(fm.get("origin") or "").strip()
            if (origin in wanted) or (unstamped and not origin):
                if (row := self.row(entity_id)) is not None:
                    rows.append(row)
        return rows


def _live(fm: dict) -> bool:
    return not fm.get("source_deleted_at")


# --- one reader per family -----------------------------------------------------


def _notes(memory_path: Path) -> list[dict]:
    path = Path(memory_path) / "sources" / notes_sync.NOTES_INDEX_FILENAME
    try:
        index = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        index = {}
    wanted = {str(v.get("episode_id")) for v in (index.values() if isinstance(index, dict) else [])
              if isinstance(v, dict) and v.get("episode_id")}
    return [_episode_row(f.frontmatter or {}, f.stem) for f in bank_index.files(memory_path, "episodes")
            if str((f.frontmatter or {}).get("id") or f.stem) in wanted]


def _episodes(memory_path: Path, keep, *, when_key: str | None = None, media: _Media | None = None) -> list[dict]:
    rows: list[dict] = []
    seen_media: set[str] = set()
    for f in bank_index.files(memory_path, "episodes"):
        fm = f.frontmatter or {}
        if not _live(fm) or not keep(fm):
            continue
        media_id = str(fm.get("media_entity_id") or "").strip()
        if media_id and media is not None:
            # A saved link is listed as its page, once — the Feed's item, not its capture episode.
            if media_id not in seen_media and (row := media.row(media_id)) is not None:
                seen_media.add(media_id)
                rows.append(row)
            continue
        rows.append(_episode_row(fm, f.stem, when_key=when_key))
    return rows


def _contacts(memory_path: Path) -> list[dict]:
    rows = []
    for f in bank_index.files(memory_path, "entities"):
        fm = f.frontmatter or {}
        if fm.get("type") != "person" or fm.get("status") == "dropped":
            continue
        mine = [s for s in fact_sources.as_sources(fm.get("sources"))
                if str(s.get("ref") or "").startswith(contacts_local.REF_SCHEME)
                and s.get("added_by") == contacts_local.ADDED_BY]
        if not mine and not fm.get(contacts_local.FRONTMATTER_KEY):
            continue
        added = sorted(str(s.get("added_at")) for s in mine if s.get("added_at"))
        day = _day(added[0]) if added else None
        # The page's name and nothing else from the card (G154's rule; the address-book id never travels).
        name = fm.get("name") or f.stem.replace("-", " ").title()
        rows.append(_row("page", f.stem, _title(name), day, _instant(day)))
    return rows


def _bookmarks(memory_path: Path, channel_id: str, media: _Media) -> list[dict]:
    entry = bookmark_seen.read_seen(memory_path).get(channel_id)
    origin = channel_id[: -len("s")] if channel_id.endswith("-bookmarks") else channel_id
    if not isinstance(entry, dict):
        return media.by_origins((origin,))
    rows, seen = [], set()
    for h in entry.get("hashes") or []:
        indexed = media.by_hash.get(str(h))
        if not isinstance(indexed, dict):
            continue
        entity_id = str(indexed.get("media_entity_id") or "")
        if entity_id and entity_id not in seen and (row := media.row(entity_id)) is not None:
            seen.add(entity_id)
            rows.append(row)
    return rows


def _collect(memory_path: Path, channel_id: str) -> list[dict]:
    if channel_id == "notes":
        return _notes(memory_path)
    if channel_id == calendar_local.CHANNEL_ID:
        return _episodes(memory_path,
                         lambda fm: str(fm.get("source_id") or "").startswith(calendar_local.SOURCE_PREFIX),
                         when_key="event_start")
    if channel_id == "calendar":
        return _episodes(memory_path, lambda fm: fm.get("origin") == "calendar", when_key="event_start")
    if channel_id == contacts_local.CHANNEL_ID:
        return _contacts(memory_path)
    for browser in tab_groups.BROWSERS:
        if channel_id == tab_groups.channel_id(browser):
            prefix = f"{tab_groups.SOURCE_PREFIX}{browser}:"
            return _episodes(memory_path, lambda fm: str(fm.get("source_id") or "").startswith(prefix))
    media = _Media(memory_path)
    if channel_id in {bookmark_sync.channel_for(b) for b in bookmark_sync.CHROMIUM_BROWSERS} \
            or channel_id == "safari-bookmarks":
        return _bookmarks(memory_path, channel_id, media)
    if channel_id in _MEDIA_CHANNELS:
        return media.by_origins(_catalog_origins(channel_id), unstamped=channel_id == "files")
    if channel_id in _ORIGIN_CHANNELS:
        origins = set(_ORIGIN_CHANNELS[channel_id])
        return _episodes(memory_path, lambda fm: str(fm.get("origin") or "") in origins, media=media)
    if channel_id.startswith(folder_source.CHANNEL_PREFIX):
        return _folder(memory_path, channel_id[len(folder_source.CHANNEL_PREFIX):])
    return []


def _folder(memory_path: Path, folder_id: str) -> list[dict]:
    """One row per file, as the row counts notes: a long file is staged as one episode per section
    (`folder_source.drafts_for_file`), and the list names the file once, by its own name, opening at its first
    section. The folder's label and the path are not repeated — the row already says which folder (DR-38)."""
    by_file: dict[str, tuple[str, dict, str]] = {}
    for f in bank_index.files(memory_path, "episodes"):
        fm = f.frontmatter or {}
        if fm.get("origin") != folder_source.ORIGIN or str(fm.get("folder_id") or "") != folder_id or not _live(fm):
            continue
        relpath = str(fm.get("relpath") or fm.get("source_id") or f.stem)
        sid = str(fm.get("source_id") or "")
        # The whole file (no `#section`) or its intro first, then the lowest source id: a stable first section.
        rank = "0" if "#" not in sid else ("1" if sid.endswith("#intro") else "2" + sid)
        held = by_file.get(relpath)
        if held is None or rank < held[0]:
            by_file[relpath] = (rank, fm, f.stem)
    rows = []
    for relpath, (_, fm, stem) in by_file.items():
        name = relpath.rsplit("/", 1)[-1]
        stem_name = name.rsplit(".", 1)[0] if "." in name.lstrip(".") else name
        row = _episode_row(fm, stem)
        row["title"] = _title(stem_name, fallback=row["title"])
        rows.append(row)
    return rows


def items(memory_path: Path, channel_id: str, *, offset: int = 0, limit: int = LIMIT_DEFAULT) -> dict | None:
    """One page of what `channel_id` brought in, newest first — or None for a channel this bank does not know."""
    memory_path = Path(memory_path)
    if not known(memory_path, channel_id):
        return None
    offset = max(0, int(offset))
    limit = max(1, min(int(limit), LIMIT_MAX))
    rows = _collect(memory_path, channel_id)
    rows.sort(key=lambda r: (-r["_sort"], r["title"].casefold(), r["id"]))
    page = [{k: v for k, v in r.items() if k != "_sort"} for r in rows[offset:offset + limit]]
    return {"channel": channel_id, "total": len(rows), "offset": offset, "limit": limit, "items": page}
