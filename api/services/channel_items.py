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
  (``sources/bookmark_seen.json``) joined to the saved-URL index, then the
  links Cicada kept after they left the browser, each with ``left`` (G191 v4);
  a bank synced before that file existed falls back to the browser's media pages.
* ``safari-tabs``, the connectors, ``rss``, ``files`` — the media pages stamped
  with the channel's origins (``source_overview.CATALOG``); ``files`` also takes
  the pages written before writers stamped an origin, as its card does.
* the chat exports, ``wispr-flow``, ``telegram`` — the episodes of the origin;
  an episode that saved a link is listed as its media page.
* ``folder:<id>`` — one row per file of the folder (its episodes by
  ``folder_id``; a long file's sections are one row), by the file's own name.

* ``youtube-history`` / ``tiktok-history`` — the watched days, one episode
  each (captured, never a save; indexed only, ruling 30), each with
  ``videos``, how many were watched that day; the month summaries are not
  listed (they are counted from these days). A day opens to its videos through
  :func:`watched_day` (Sources v4, owner 2026-10-19: "what I watched in one
  day: a dropdown and you see all the videos I watched that day").
* ``imessage`` — one row per chat (``kind: chat``), titled by **who the chat is
  with** (its sittings' ``correspondent`` record), dated by its newest sitting,
  with ``sittings`` and ``chat``: the app's conversation hash, that name, and
  the stored photo's hash when the chat shares one (Sources v4). A chat opens to
  its sittings through :func:`chat_sittings`.
* the saved sources with no channel (``instagram``, ``youtube``, ``linkedin``,
  ``tiktok``: one-shot imports, ``source_overview.CATALOG``) — listed by their
  Sources row id, as the media pages stamped with the row's origins.

A saved link's row (``kind: media``) also carries, for Sources v3 (owner
2026-10-19: "in two clicks … I can see all the things that I've saved in
Chrome"): ``host``, the bare host of the URL the person saved (``www.``
dropped; never the URL, its path or query), ``site``, the key its mark is
asked under (:func:`_site`), and ``why``,
the newest answer the person gave to "What made you save this?"
(``saved_why`` on the link's episode: the reasons' labels and their own
words), when there is one.

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
    episode_ids,
    episode_time,
    contacts_local,
    reminders_local,
    episode_scrub,
    fact_sources,
    folder_source,
    history_index,
    media_ingestor,
    media_preview,
    messages_source,
    notes_sync,
    reading_hosts,
    saved_why,
    source_overview,
    tab_groups,
    watch_history,
    wispr_flow,
)
from api.services.channel_registry import CHANNEL_IDS

#: Folded into the route's ETag: bump it when the body changes for the same bank files.
#: `g161-2`: a bookmark channel also lists the links that left the browser, with `left` (G191 v4).
#: `g161-3`: a saved link's row carries `site` and `why`; channel-less saved sources list by their row id (Sources v3).
#: `g161-4`: Sources v4 — a title says its day once; Messages lists one row per chat (`kind: chat`, `sittings`, `chat`);
#: a watched day carries `videos` and the month summaries are not listed.
#: `g161-6`: marks-2 — a saved YouTube video's row carries `video` (its still is asked by the page's id), and a saved
#: link still waiting for Sleep (an episode row) carries `host`/`site` (its icon is asked by the episode's id).
#: `g161-7`: ruling 39 — a row whose item came in days after its own date carries `received` (that day).
#: `g161-8`: ruling 47 tier 2 — the Readwise and live Notion rows list their episodes.
SHAPE = "g161-8"
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
    "imessage": ("imessage",),
    "notion": ("notion-export",),
    # Ruling 47 tier 2: what the person's own connection brought in (a Readwise document with a page lists as it).
    "notion-api": ("notion-api",),
    "readwise": ("readwise",),
}
#: A channel whose items are media pages, by the origins its catalog row owns.
_MEDIA_CHANNELS = ("safari-tabs", "pinterest", "reddit", "x", "rss", "files")
#: Sources v3 — a saved source with no channel (a one-shot import): listed by its Sources row id, by its origins.
_SAVED_SOURCE_ROWS = {spec.id: spec.origins for spec in source_overview.CATALOG
                      if spec.channel is None and spec.id in source_overview.SAVED_SOURCES}
#: Sources v3 (re-review of #347) — a watch-history row (captured, never a save) lists its days: one episode per day
#: watched, by its own title, opening in the Reader. Indexed, never read by a model (ruling 30); titles only, as ever.
_HISTORY_ROWS = {spec.id: spec.origins for spec in source_overview.CATALOG
                 if spec.channel is None and spec.id.endswith("-history")}
#: The why's own words on a row: one line, at most this many characters (the full answer is on the item's page).
WHY_CAP = 160


def _catalog_origins(channel_id: str) -> tuple[str, ...]:
    for spec in source_overview.CATALOG:
        if spec.channel == channel_id:
            return spec.origins
    return ()


def known(memory_path: Path, channel_id: str) -> bool:
    """A channel id this bank can list: every fixed row, the always-listed local
    sources, each browser's bookmarks and tab groups, and every registered folder."""
    if (channel_id in CHANNEL_IDS or channel_id in _ORIGIN_CHANNELS or channel_id in _SAVED_SOURCE_ROWS
            or channel_id in _HISTORY_ROWS):
        return True
    if channel_id in (calendar_local.CHANNEL_ID, contacts_local.CHANNEL_ID, reminders_local.CHANNEL_ID):
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


def _with_received(row: dict, received: str | None) -> dict:
    """Ruling 39: a row whose item Cicada received days after its own date says that day too (``received``, the
    Sources page's day rule) — a feed's back catalogue, an old bookmark; absent otherwise, so the common row says its
    one day once."""
    day = _day(received) if received else None
    if day:
        row["received"] = day
    return row


def _without_day(title: str, day: str | None) -> str:
    """Sources v4 (owner 2026-10-19: "avoid repetition") — a title that ends with the row's own day (a Messages
    sitting's "… · 2026-10-19", a watched day's) drops it: the row already shows that day, once, on its right."""
    if day:
        for sep in (" · ", " - ", " — "):
            if title.endswith(sep + day) and len(title) > len(sep + day):
                return title[: -len(sep + day)].rstrip()
    return title


def _episode_row(fm: dict, stem: str, *, when_key: str | None = None) -> dict:
    """An episode by its own title. The day is `when_key`'s value when given (an event's start), else the
    day the source dated it (`original_date`), else the day Cicada captured it."""
    own = fm.get(when_key) if when_key else None
    when = own or fm.get("original_date") or fm.get("timestamp")
    # An event's day is its own calendar day as written (`2026-10-01T09:00:00-05:00` is Oct 1), never shifted to UTC.
    day = _day(str(own)[:10]) if own and len(str(own)) >= 10 else _day(when)
    row = _row("episode", str(fm.get("id") or stem), _without_day(_title(fm.get("title")), day), day,
               _instant(when) or _instant(fm.get("timestamp")))
    return _with_received(row, episode_time.received_after(when, fm.get(episode_ids.RECEIVED_KEY)))


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
        own = entry.get("content_saved_at") or entry.get(episode_time.PUBLISHED_KEY)
        saved = own or entry.get("saved_at") or fm.get("created")
        title = entry.get("title") or fm.get("name") or entry.get("url") or entity_id
        row = _row("media", entity_id, _title(title), _day(saved), _instant(saved))
        # Ruling 39: the url index's `saved_at` is when Cicada took the link in; shown only beside an own date.
        _with_received(row, episode_time.received_after(own, entry.get("saved_at")) if own else None)
        # Read only for the page served (`items`): the site and the why are per-row file reads at thousands of rows.
        row["_url"] = entry.get("url") or fm.get("url")
        row["_episode"] = entry.get("episode_id")
        return row

    def by_origins(self, origins: tuple[str, ...], *, unstamped: bool = False) -> list[dict]:
        wanted = set(origins)
        rows = []
        for entity_id, fm in self.pages.items():
            origin = str(fm.get("origin") or "").strip()
            if (origin in wanted) or (unstamped and not origin):
                if (row := self.row(entity_id)) is not None:
                    rows.append(row)
        return rows


def _site(url) -> dict:
    """Where a saved URL lives, as a row may name it — never the URL itself: ``host``, its bare host (``www.``
    dropped, sanitized), and ``site``, the key a site's mark is asked under (``reading_hosts.site_of``: a walled
    family's name, else the registrable domain). The app asks ``GET /reading/sites/{site}/icon``, which serves only
    a site the reading list already holds and looks nothing else up, then draws a bundled family mark or a monogram."""
    raw = str(url or "")
    host = reading_hosts.display_host(reading_hosts.host_of(raw))
    if not host:
        return {}
    out = {"host": host}
    if site := reading_hosts.mark_key(raw):
        out["site"] = site
    return out


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
        row = _episode_row(fm, f.stem, when_key=when_key)
        # marks-2 — a saved link Sleep has not made a page of yet still names its site, so its row asks that site's
        # icon by the episode's id (`GET /sources/saved/episodes/{id}/site-icon`) instead of drawing a letter.
        if url := saved_episode_url(fm):
            row["_url"] = url
        rows.append(row)
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
    """The links in the browser at the last sync, then (G191 v4) the ones Cicada kept after they left it, each with
    ``left`` — the sync instant that first saw it gone — so the list says "No longer in Chrome"."""
    entry = bookmark_seen.read_seen(memory_path).get(channel_id)
    origin = channel_id[: -len("s")] if channel_id.endswith("-bookmarks") else channel_id
    if not isinstance(entry, dict):
        return media.by_origins((origin,))
    rows, seen = [], set()
    left = bookmark_seen.left_of(entry)
    for h, gone_at in [(h, None) for h in entry.get("hashes") or []] + sorted(left.items()):
        indexed = media.by_hash.get(str(h))
        if not isinstance(indexed, dict):
            continue
        entity_id = str(indexed.get("media_entity_id") or "")
        if entity_id and entity_id not in seen and (row := media.row(entity_id)) is not None:
            seen.add(entity_id)
            if gone_at:
                row["left"] = gone_at
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
    if channel_id == reminders_local.CHANNEL_ID:
        return _episodes(memory_path,
                         lambda fm: str(fm.get("source_id") or "").startswith(reminders_local.SOURCE_PREFIX))
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
    if channel_id in _SAVED_SOURCE_ROWS:
        return media.by_origins(tuple(_SAVED_SOURCE_ROWS[channel_id]))
    if channel_id in _HISTORY_ROWS:
        return _watched_days(memory_path, set(_HISTORY_ROWS[channel_id]))
    if channel_id == messages_source.ORIGIN:
        return _chat_rows(memory_path)
    if channel_id in _ORIGIN_CHANNELS:
        origins = set(_ORIGIN_CHANNELS[channel_id])
        return _episodes(memory_path, lambda fm: str(fm.get("origin") or "") in origins, media=media)
    if channel_id.startswith(folder_source.CHANNEL_PREFIX):
        return _folder(memory_path, channel_id[len(folder_source.CHANNEL_PREFIX):])
    return []


def _watched_days(memory_path: Path, origins: set[str]) -> list[dict]:
    """One row per watched day (never the month summaries, which are counted from these days), with `videos`."""
    rows = []
    for f in bank_index.files(memory_path, "episodes"):
        fm = f.frontmatter or {}
        if str(fm.get("origin") or "") not in origins or not _live(fm) or history_index.kind(fm) == "month":
            continue
        row = _episode_row(fm, f.stem)
        try:
            row["videos"] = max(0, int(fm.get("videos") or len(fm.get("watched") or [])))
        except (TypeError, ValueError):
            row["videos"] = 0
        rows.append(row)
    return rows


def _chat_rows(memory_path: Path) -> list[dict]:
    """Messages — one row per chat (review of #358: "one row per chat, newest day, N sittings"), titled by who it is
    with, its day the newest sitting's, carrying the chat and how many sittings it holds; a sitting with no chat hash
    (never written today) stays its own episode row."""
    photos = source_overview._chat_photos(memory_path)
    chats: dict[str, dict] = {}
    rows = []
    for f in bank_index.files(memory_path, "episodes"):
        fm = f.frontmatter or {}
        if fm.get("origin") != messages_source.ORIGIN or not _live(fm):
            continue
        row = _episode_row(fm, f.stem)
        cid = str(fm.get("conversation") or "")
        if not messages_source.CONVERSATION_ID_RE.match(cid):
            rows.append(row)
            continue
        record = fm.get("correspondent") if isinstance(fm.get("correspondent"), dict) else {}
        name = _title(record.get("name"), fallback="")
        held = chats.get(cid)
        if held is None:
            chats[cid] = held = {**_row("chat", cid, name or row["title"], row["day"], None), "sittings": 0}
            held["_sort"] = row["_sort"]
        held["sittings"] += 1
        if row["_sort"] >= held["_sort"]:
            held["_sort"], held["day"] = row["_sort"], row["day"]
            if name:
                held["title"] = name
    for cid, held in chats.items():
        held["chat"] = {"id": cid, "label": held["title"], "photo": photos.get(cid)}
        rows.append(held)
    return rows


def chat_sittings(memory_path: Path, conversation: str) -> dict | None:
    """One chat's sittings, newest first — what its row opens to: each sitting's episode (it opens in the Reader), its
    day and how many messages it holds. Titles are not repeated: the row above already names the chat. None for an id
    that is not a chat hash or has no live sitting."""
    if not messages_source.CONVERSATION_ID_RE.match(str(conversation or "")):
        return None
    out = []
    for f in bank_index.files(Path(memory_path), "episodes"):
        fm = f.frontmatter or {}
        if (fm.get("origin") != messages_source.ORIGIN or not _live(fm)
                or str(fm.get("conversation") or "") != conversation):
            continue
        row = _episode_row(fm, f.stem)
        try:
            messages = max(0, int(fm.get("message_count") or 0))
        except (TypeError, ValueError):
            messages = 0
        out.append({"id": row["id"], "day": row["day"], "messages": messages or None, "_sort": row["_sort"]})
    if not out:
        return None
    out.sort(key=lambda r: (-r["_sort"], r["id"]))
    return {"conversation": conversation, "sittings": [{k: v for k, v in r.items() if k != "_sort"} for r in out]}


#: A watched day's videos on the wire: at most this many (a day keeps at most `watch_history.MAX_PER_DAY`).
DAY_VIDEOS_MAX = 400


def watched_day(memory_path: Path, episode_id: str) -> dict | None:
    """Sources v4 — one watched day's videos, in the order they were watched: each one's title, channel, the times it
    was watched, its URL (the provider's own watch page) and, for YouTube, its video id (the key its thumbnail is asked
    under, :func:`day_has_video`) and the saved page when the person also saved it (`media_entity_id`, so a click
    lands where a saved item opens). Read from the day's own record; nothing is fetched and no model reads it (ruling
    30). None for an id that is not a live watched day."""
    from api.services import video_urls

    f = bank_index.file(Path(memory_path), "episodes", f"{episode_id}.md")
    fm = (f.frontmatter or {}) if f is not None else {}
    if (str(fm.get("origin") or "") not in watch_history.HISTORY_ORIGINS or not _live(fm)
            or history_index.kind(fm) == "month"):
        return None
    media = _Media(Path(memory_path))
    videos = []
    for r in (fm.get("watched") or [])[:DAY_VIDEOS_MAX]:
        if not isinstance(r, dict) or not watch_history.watch_url(str(r.get("url") or "")):
            continue
        url = str(r["url"])
        ref = video_urls.resolve(url)
        indexed = media.by_hash.get(media_ingestor.url_hash(url))
        page = str(indexed.get("media_entity_id") or "") if isinstance(indexed, dict) else ""
        videos.append({
            "url": url,
            "title": _title(r.get("title"), fallback="Untitled video"),
            "channel": _title(r.get("channel"), fallback="") or None,
            "times": [str(t) for t in (r.get("times") or []) if t][: watch_history.MAX_TIMES],
            "video_id": ref.video_id if ref is not None and ref.provider == "youtube" else None,
            "media_entity_id": page if page and media.row(page) is not None else None,
        })
    return {"episode": str(fm.get("id") or episode_id), "day": str(fm.get("watched_on") or fm.get("original_date") or ""),
            "platform": str(fm.get("platform") or ""), "videos": videos}


def day_has_video(memory_path: Path, episode_id: str, video_id: str) -> bool:
    """Whether ``video_id`` is a YouTube video the watched day ``episode_id`` records — the only ids whose still the
    backend asks YouTube's own thumbnail host for (owner 2026-10-19), and only for a day the person opened (the route
    is keyed by the day). One file read, never a walk of the bank; never an id a request merely names."""
    from api.services import video_urls

    if not media_preview.youtube_id_ok(video_id):
        return False
    f = bank_index.file(Path(memory_path), "episodes", f"{episode_id}.md")
    fm = (f.frontmatter or {}) if f is not None else {}
    if str(fm.get("origin") or "") != watch_history.ORIGINS["youtube"] or not _live(fm):
        return False
    for r in (fm.get("watched") or [])[:DAY_VIDEOS_MAX]:
        if isinstance(r, dict) and video_id in str(r.get("url") or ""):
            ref = video_urls.resolve(str(r["url"]))
            if ref is not None and ref.provider == "youtube" and ref.video_id == video_id:
                return True
    return False


def saved_faces(memory_path: Path, list_id: str, *, limit: int = 3) -> tuple[list[dict], int]:
    """A saved source's faces, from the same set its list lists (review of #358: a row never says "Nothing saved"
    beside faces): the sites of its live saved pages — never a bookmark that left the browser — those whose own icon is
    already cached first, then the rest, each newest first, one face per site (`{id, label, site}`: the newest page of
    that site, its bare host, its site key), and how many more sites there are."""
    from api.services import logo_service

    rows = [r for r in _collect(Path(memory_path), list_id) if r.get("kind") == "media" and not r.get("left")]
    rows.sort(key=lambda r: (-r["_sort"], r["title"].casefold(), r["id"]))
    seen: dict[str, dict] = {}
    known: set[str] = set()
    hits = logo_service.own_site_hits(memory_path)
    for r in rows:
        where = _site(r.get("_url"))
        if where.get("site") and where["site"] not in seen:
            seen[where["site"]] = {"id": r["id"], "label": where["host"], "site": where["site"]}
            if logo_service.own_site_domain(str(r.get("_url") or "")) in hits:
                known.add(where["site"])
    # marks-2 (owner 2026-10-20: a letter where the site has its own picture) — the newest sites whose icon is already
    # cached come first, then the rest, newest first; the app asks those as they show (`SiteIconStore`).
    faces = sorted(seen.values(), key=lambda f: f["site"] not in known)
    return faces[:limit], max(0, len(faces) - limit)


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


def _why(memory_path: Path, episode_id) -> dict | None:
    """The newest answer to "What made you save this?" on the link's episode (`saved_why`, G191), as the row shows it:
    the reasons' labels (a stored project as "For <name>") and the person's own words, one line. None without one."""
    episode_id = str(episode_id or "").strip()
    if not episode_id:
        return None
    f = bank_index.file(memory_path, "episodes", f"{episode_id}.md")
    records = saved_why.records_of((f.frontmatter or {}) if f is not None else {})
    if not records:
        return None
    newest = saved_why.wire(records[-1], added_at=None) or {}
    labels = list(newest.get("labels") or [])
    if project := newest.get("project"):
        labels.append(f"For {saved_why._name_of(memory_path, project)}")
    text = " ".join(str(newest.get("text") or "").split())
    if text:
        text, _ = episode_scrub.scrub(text)
        text = text if len(text) <= WHY_CAP else text[: WHY_CAP - 1].rstrip() + "…"
    if not labels and not text:
        return None
    return {"labels": labels, "text": text or None}


def _enrich(memory_path: Path, row: dict) -> dict:
    """A served saved-link row gains its `site` and its `why`; every private key is dropped."""
    out = {k: v for k, v in row.items() if not k.startswith("_")}
    if row.get("kind") == "episode" and row.get("_url"):
        out.update(_site(row["_url"]))
    if row.get("kind") == "media":
        out.update(_site(row.get("_url")))
        # marks-2 (owner 2026-10-20: "none of the YouTube stuff shows thumbnails") — a saved YouTube video's row draws
        # its still, asked by the page's id (`GET /sources/saved/{id}/still`); the id itself never rides the wire.
        if media_preview.youtube_video_id(str(row.get("_url") or "")):
            out["video"] = True
        if why := _why(memory_path, row.get("_episode")):
            out["why"] = why
    return out


def items(memory_path: Path, channel_id: str, *, offset: int = 0, limit: int = LIMIT_DEFAULT) -> dict | None:
    """One page of what `channel_id` brought in, newest first — or None for a channel this bank does not know."""
    memory_path = Path(memory_path)
    if not known(memory_path, channel_id):
        return None
    offset = max(0, int(offset))
    limit = max(1, min(int(limit), LIMIT_MAX))
    rows = _collect(memory_path, channel_id)
    rows.sort(key=lambda r: (-r["_sort"], r["title"].casefold(), r["id"]))
    page = [_enrich(memory_path, r) for r in rows[offset:offset + limit]]
    return {"channel": channel_id, "total": len(rows), "offset": offset, "limit": limit, "items": page}


def saved_episode_site(memory_path: Path, episode_id: str) -> str | None:
    """The one site a saved link's own icon may be asked of BEFORE Sleep made its page (owner 2026-10-20): a Waiting
    row of a bookmark or a saved post is an episode, with no media id yet. Same rule as :func:`saved_link_site`, read
    from the episode's own record: a live episode of a saved source (``intent_of`` its source key is ``saved``) whose
    frontmatter names the link (``url``) — the registrable domain of THAT URL (``logo_service.own_site_domain``), else
    None and nothing is asked. A conversation, a captured page, a tab group or a watched day never qualifies; the
    caller never supplies the site."""
    from api.services import episode_ids, logo_service

    if not episode_ids.EPISODE_ID_RE.fullmatch(episode_id or ""):
        return None
    f = bank_index.file(Path(memory_path), "episodes", f"{episode_id}.md")
    url = saved_episode_url((f.frontmatter or {}) if f is not None else {})
    return logo_service.own_site_domain(url) if url else None


def saved_episode_url(fm: dict) -> str | None:
    """The link a saved-source episode names (its frontmatter ``url``), for a live episode of a saved source that is
    not a conversation — else None. One predicate for the Waiting row's site key and its icon door."""
    if not fm or not _live(fm) or fm.get("session_id"):
        return None
    if source_overview.intent_of(source_overview.source_key(fm)) != "saved":
        return None
    return str(fm.get("url") or "").strip() or None


def is_saved_link_page(fm: dict) -> bool:
    """A live media page a `saved` source owns (an origin a `saved` row owns, or none, as Files & links takes) — the one
    predicate behind the media icon route and every row's ``siteKey`` (review of #372: a key on a page the route refuses
    would record a miss for the whole site)."""
    if not fm or fm.get("type") != "media" or source_overview.is_hidden(fm):
        return False
    origin = str(fm.get("origin") or "").strip()
    owner = source_overview.source_key({"origin": origin}) if origin else "files"
    return source_overview.intent_of(owner) == "saved"


def media_video_id(memory_path: Path, media_entity_id: str) -> str | None:
    """The YouTube video a saved link's page is (marks-2, owner direction 2026-10-19/20): the id `video_urls` resolves
    from THIS page's own URL (the url index's entry, else its frontmatter), only for a live media page a saved source
    owns (`is_saved_link_page`, the site-icon route's predicate) — else None and nothing is asked. Never an id the caller supplies; the still is keyed by it so a video watched and
    saved is asked once (`media_preview.ensure_video_still`)."""
    memory_path = Path(memory_path)
    f = bank_index.file(memory_path, "entities", f"{media_entity_id}.md")
    fm = (f.frontmatter or {}) if f is not None else {}
    if not is_saved_link_page(fm):   # security review of #387: a saved link's page, the media icon route's predicate
        return None
    try:
        index = media_ingestor.load_url_index(memory_path)
    except Exception:
        index = {}
    media = fm.get("media") if isinstance(fm.get("media"), dict) else {}
    url = next((str(e.get("url") or "") for e in (index.values() if isinstance(index, dict) else [])
                if isinstance(e, dict) and str(e.get("media_entity_id") or "") == media_entity_id
                and not e.get("alias_of")), "") or str(fm.get("url") or media.get("url") or "")
    return media_preview.youtube_video_id(url) if url else None


def saved_link_site(memory_path: Path, media_entity_id: str) -> str | None:
    """The one site a saved link's own icon may be asked of (owner ruling 2026-10-19): the registrable domain of THIS
    link's own URL (`logo_service.own_site_domain`), only for a live media page a saved source lists (a bookmark, a
    saved post, a pasted link — an origin a `saved` row owns, or none, as Files & links takes) — else None, and the
    route answers 404 with nothing asked. Never a name the caller supplies: the site comes from the bank's record."""
    from api.services import logo_service

    memory_path = Path(memory_path)
    f = bank_index.file(memory_path, "entities", f"{media_entity_id}.md")
    if not is_saved_link_page((f.frontmatter or {}) if f is not None else {}):
        return None
    fm = f.frontmatter
    try:
        index = media_ingestor.load_url_index(memory_path)
    except Exception:
        return None
    url = next((str(e.get("url") or "") for e in (index.values() if isinstance(index, dict) else [])
                if isinstance(e, dict) and str(e.get("media_entity_id") or "") == media_entity_id
                and not e.get("alias_of")), "") or str(fm.get("url") or "")
    return logo_service.own_site_domain(url) if url else None
