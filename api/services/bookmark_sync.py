"""Keyless browser-bookmark sync connector.

Accepts the bookmark bytes the companion app read from the browsers' files
(or a test's inline bytes), diffs the parsed URLs against what has already
been ingested, and pushes only the *new* ones into the existing ingest
pipeline.

No new dedup logic here. ``media_ingestor.ingest_batch`` already re-checks
``memory/sources/url_index.json`` (keyed on ``url_hash``) at call time and
drops anything already present — that IS the diff. This module only adds:

1. two more producers of ``RawItem`` (Chrome's ``Bookmarks`` JSON tree, and
   Safari via the existing ``parse_safari_bookmarks``);
2. an ``origin`` tag (``chrome-bookmark`` / ``safari-bookmark``) — stamped
   both into ``RawItem.tags`` (a searchable graph tag) and ``RawItem.origin``
   (the G9 capture-provenance field ``media_ingestor`` writes verbatim into
   the resulting episode + media entity frontmatter) — so synced items are
   distinguishable from a manual save or a one-off file upload;
3. a thin summary shape (``{new, skipped, sources}``) for the endpoint/cron;
4. (2026-09-02 brief, R5) folder selection — ``filter_by_folders`` narrows
   a parsed source to chosen folder-path prefixes, and ``folder_tree`` /
   ``preview_bookmarks`` give the app the tree with leaf counts to choose
   from, without staging anything;
5. (R4) ``CHANNEL_BY_ORIGIN`` — one ``sync_state.json`` key per browser, so
   the catalog's per-browser tiles each have exactly one channel.
6. (G129 slice 2, G191 v4) left the browser — a URL that dropped out of a
   channel's browser file since the previous sync is marked as gone from that
   browser, with the day, in the seen-set's ``left`` map; Cicada keeps it and
   asks nothing (until G191 v4 this was a ``removal`` inbox question, which
   existed because the bookmark sync then had no other way to say a link had
   left the browser; the person's own Remove now lives on the bookmark's page).
   Diffed against ``bookmark_seen.py``'s own per-channel seen-set, NEVER
   against ``url_index.json`` — see that module's docstring for the rails.

Nothing here reads a browser's file: the app reads ``~/Library`` and the
backend parses bytes (the launchd backend has no Full Disk Access).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Awaitable, Callable

from loguru import logger

from api.services import bookmark_forget, bookmark_seen, episode_ids, markdown_parser, media_ingestor, saved_at
from api.services.media_ingestor import RawItem

# (items, memory_path, from_bookmark_file) -> (created, duplicates), matching
# media_ingestor.ingest_batch's signature (commit kwarg has a default there).
IngestFn = Callable[..., Awaitable[tuple[int, int]]]


# --- Parsers ---


def read_chrome_bookmarks(data: bytes) -> list[RawItem]:
    """Parse Chrome's ``Bookmarks`` JSON tree into ``RawItem``s.

    Walks ``roots`` -> recurses ``children``; a node with ``type == "url"``
    yields a ``RawItem(url, title, folder)`` where ``folder`` is the ``/``-
    joined display-name path of every enclosing folder (e.g. "Bookmarks bar/
    Reading"). Folders (``type == "folder"``) are recursed into but never
    emitted themselves — only their name flows onto descendant leaves.
    Delegates to the existing
    ``media_ingestor.parse_chrome_bookmarks_json`` (same tree-walk already
    used by the ``.json`` branch of ``parse_upload``) so there is exactly one
    Chrome-tree-walking implementation. Malformed/non-JSON bytes degrade to
    ``[]`` — never raises.
    """
    try:
        obj = json.loads(data)
    except Exception:
        return []
    if not isinstance(obj, dict):
        return []
    return media_ingestor.parse_chrome_bookmarks_json(obj)


# --- Sync (diff + ingest only what's new) ---


def _tag_origin(items: list[RawItem], origin: str) -> list[RawItem]:
    for item in items:
        item.tags = sorted(set((item.tags or []) + [origin]))
        # ``tags`` also carries arbitrary bookmark-folder names, so it isn't a
        # reliable provenance signal on its own — stamp the explicit ``origin``
        # field too. ``media_ingestor.write_media_episode``/``write_media_entity``
        # thread this straight into episode + media-entity frontmatter (G9
        # origin-provenance; see ``api/services/origin_stats.py``).
        item.origin = origin
    return items


#: Round 4 (C9, R-SR2): the Chromium-family browsers whose default-profile
#: `Bookmarks` JSON the app reads and posts. One parser (`read_chrome_bookmarks`)
#: serves all five — the file is Chromium's, and each browser's bundle id and
#: path were verified from public sources (the round-4 sources plan), never from
#: a real profile. Edge and Opera wait for the same check (G119). Only the
#: default profile is ever read (R-SR1): profile selection is G119's next slice.
CHROMIUM_BROWSERS: dict[str, str] = {
    "chrome": "Chrome", "brave": "Brave", "vivaldi": "Vivaldi", "comet": "Comet", "dia": "Dia",
}
SAFARI_ORIGIN = "safari-bookmark"


def origin_for(browser: str) -> str:
    """``brave`` -> ``brave-bookmark`` — the G9 origin every item of that browser carries."""
    return f"{browser}-bookmark"


def channel_for(browser: str) -> str:
    """``brave`` -> ``brave-bookmarks`` — its one ``sync_state.json`` key and channel row (R4)."""
    return f"{browser}-bookmarks"


# Which `sync_state.json` channel each browser's sync stamps (R4). The old
# combined "bookmarks" key is read back as a legacy fallback by
# `channel_registry._sync_channel` and never written again: the catalog has
# one tile per browser, and a channel must map to exactly one tile.
CHANNEL_BY_ORIGIN = {**{origin_for(b): channel_for(b) for b in CHROMIUM_BROWSERS}, SAFARI_ORIGIN: "safari-bookmarks"}

# Display label per origin — the same origins `_tag_origin` ever stamps — and per channel (G191 v4: "No longer in
# Chrome since …" names the browser by its channel).
_BROWSER_LABEL = {**{origin_for(b): name for b, name in CHROMIUM_BROWSERS.items()}, SAFARI_ORIGIN: "Safari"}
BROWSER_BY_CHANNEL = {CHANNEL_BY_ORIGIN[o]: name for o, name in _BROWSER_LABEL.items()}

#: Round 4 (R-SR13, R-SR14): the counts a Safari sync stamps beside `found`, which
#: `channel_registry` ships as the row's `parts`.
PART_KEYS = ("reading_list", "favorites")
SAFARI_FAVORITES_ROOT = "BookmarksBar"
SAFARI_READING_LIST_ROOT = "com.apple.ReadingList"

# Safari's plist names its top-level folders by internal key; the preview
# shows the names the user sees in Safari while the PATH keeps the raw key
# (R5: the parser's `folder` output is unchanged, so an existing entity's
# `folder:` and a new one's still agree byte for byte).
SAFARI_FOLDER_LABELS = {
    "BookmarksBar": "Favorites",
    "BookmarksMenu": "Bookmarks Menu",
    "com.apple.ReadingList": "Reading List",
}

ROOT_NAME = "All bookmarks"


def display_name(segment: str) -> str:
    """The label a folder-path segment gets in the preview tree (R5). Only
    Safari's three internal top-level keys are mapped; every other segment —
    and every Chrome folder, whose names are already display names — is
    returned verbatim."""
    return SAFARI_FOLDER_LABELS.get(segment, segment)


def folder_tree(items: list[RawItem]) -> dict[str, Any]:
    """Nested ``{name, path, count, children}`` over the items' ``folder`` paths.

    ``count`` is every leaf at or below that folder, so a parent's count is
    the number the user gets by ticking it. Root-level leaves (``folder is
    None``) count on the root only. Children sort by display name. ``path``
    is the raw ``/``-joined key the parser emitted — it is what the app sends
    back as ``folders`` and what ``filter_by_folders`` compares against, so
    it must never be the display name.
    """
    root: dict[str, Any] = {"name": ROOT_NAME, "path": "", "count": 0, "children": {}}
    for item in items:
        if not item.url:
            continue
        root["count"] += 1
        node = root
        segments = [s for s in (item.folder or "").split("/") if s]
        for depth, seg in enumerate(segments):
            path = "/".join(segments[: depth + 1])
            child = node["children"].get(seg)
            if child is None:
                child = node["children"][seg] = {
                    "name": display_name(seg), "path": path, "count": 0, "children": {},
                }
            child["count"] += 1
            node = child

    def freeze(n: dict[str, Any]) -> dict[str, Any]:
        kids = sorted(n["children"].values(), key=lambda c: c["name"].lower())
        return {"name": n["name"], "path": n["path"], "count": n["count"], "children": [freeze(k) for k in kids]}

    return freeze(root)


def filter_by_folders(items: list[RawItem], folders: list[str] | None) -> list[RawItem]:
    """Keep items whose ``folder`` equals a selected path or sits beneath one (R5).

    Segment-boundary prefix match (``"A/B"`` selects ``"A/B"`` and ``"A/B/C"``
    but never ``"A/Bc"``), case-sensitive; ``""`` selects everything (it is
    the tree root's path). ``None``/``[]`` means "no filter" — the
    pre-existing everything-or-nothing behaviour, unchanged.
    """
    if not folders:
        return items
    wanted = list(folders)
    if "" in wanted:
        return items
    out: list[RawItem] = []
    for item in items:
        f = item.folder or ""
        if any(f == w or f.startswith(w + "/") for w in wanted):
            out.append(item)
    return out


def _root(folder: str | None) -> str:
    return (folder or "").split("/", 1)[0]


def safari_parts(items: list[RawItem]) -> dict[str, int]:
    """How many of a Safari sync's items are in the Reading List and under Favorites
    (the `BookmarksBar`, its folders included) — R-SR13's "counts on the wire"."""
    return {
        "reading_list": sum(1 for i in items if _root(i.folder) == SAFARI_READING_LIST_ROOT),
        "favorites": sum(1 for i in items if _root(i.folder) == SAFARI_FAVORITES_ROOT),
    }


def recently_saved_first(items: list[RawItem]) -> list[RawItem]:
    """Dated items newest first, then the undated in file order — stable both ways.

    R-SR13: "recently saved" is not stored anywhere in Safari's plist; it is the
    Reading List sorted by `DateAdded`. Ingesting in that order means the newest
    saves are staged first — the order every later reader of the batch sees.
    It is NOT a stop guarantee: the app's × cancels only its own request, and
    the route runs the whole batch to the end regardless (round 4 phase A final
    review, finding 2); the per-bank lock in the route is what keeps a second
    sync from racing it.
    """
    dated = sorted((i for i in items if i.added), key=lambda i: i.added, reverse=True)
    return dated + [i for i in items if not i.added]


def _batches(
    chrome_data: bytes | None,
    safari_data: bytes | None,
    chromium: list[tuple[str, bytes]] | None = None,
) -> list[tuple[str, list[RawItem]]]:
    """Parse + origin-tag whichever sources were supplied — Chrome's legacy field,
    then each Chromium-family browser in the order sent, then Safari — one parse
    path so a preview can never disagree with the sync. An unknown browser raises
    ``ValueError`` before anything is parsed (the router answers 422 first)."""
    for browser, _ in chromium or []:
        if browser not in CHROMIUM_BROWSERS:
            raise ValueError(f"unknown browser {browser!r}")
    batches: list[tuple[str, list[RawItem]]] = []
    if chrome_data is not None:
        batches.append((origin_for("chrome"), _tag_origin(read_chrome_bookmarks(chrome_data), origin_for("chrome"))))
    for browser, data in chromium or []:
        origin = origin_for(browser)
        batches.append((origin, _tag_origin(read_chrome_bookmarks(data), origin)))
    if safari_data is not None:
        items = recently_saved_first(media_ingestor.parse_safari_bookmarks(safari_data))
        batches.append((SAFARI_ORIGIN, _tag_origin(items, SAFARI_ORIGIN)))
    return batches


def preview_bookmarks(
    *,
    chrome_data: bytes | None = None,
    safari_data: bytes | None = None,
    chromium: list[tuple[str, bytes]] | None = None,
) -> dict[str, Any]:
    """Folder trees per supplied source — parse only, nothing staged (mirrors
    ``media_ingestor.preview_upload``'s contract for ``?preview=true``), so
    the app can show "Favorites · 500" before the user picks a folder.

    Returns ``{"sources": [{"origin", "total", "tree"}, ...]}``.
    """
    return {"sources": [
        {"origin": origin, "total": sum(1 for i in items if i.url), "tree": folder_tree(items)}
        for origin, items in _batches(chrome_data, safari_data, chromium)
    ]}


#: G191 v4 — a read that shares no link with the previous one, when the previous held at least this many, is a different
#: or broken file (another profile's, a half-written one), never the person removing every bookmark one by one: it is
#: compared like a first sync — nothing is marked gone and nothing counts as saved again.
WHOLESALE_MIN = 5


def _not_comparable(prev_entry: dict | None, current_hashes: list[str], folders: list[str] | None) -> str | None:
    """Why this read must not be diffed against the channel's previous one (G129 Rail 1 and G191 v4's guards), or
    ``None`` when it may. ``"first"`` (no previous read — silent, R6), ``"scope"`` (the folder selection changed), ``"empty"``
    (this read holds no bookmark while the last held some), ``"wholesale"`` (no link in common, see
    :data:`WHOLESALE_MIN`)."""
    if prev_entry is None:
        return "first"
    if bookmark_seen._normalize_folders(prev_entry.get("folders")) != bookmark_seen._normalize_folders(folders):
        return "scope"
    prev = set(prev_entry.get("hashes") or [])
    if prev and not current_hashes:
        return "empty"
    if len(prev) >= WHOLESALE_MIN and not (prev & set(current_hashes)):
        return "wholesale"
    return None


_REFUSAL_WORDS = {
    "scope": "folder scope changed since the last sync",
    "empty": "the browser's file held no bookmarks, so nothing was marked as gone",
    "wholesale": "the browser's file shares no bookmark with the last read, so nothing was marked as gone",
}


def _retire_removal_questions(memory_path: Path, channel: str) -> tuple[list[str], dict[str, str]]:
    """G191 v4 — the pending "Still keep …?" questions an earlier sync asked about this channel's bookmarks (G129 slice
    2) are retired: a bookmark leaving the browser is a status now, never a question. Each item's link is marked gone
    from the day that sync saw it (its ``synced_at``); keeping it is what Cicada does anyway, which is the question's
    own first option. Returns ``(item paths removed, {url_hash: at})``. Papers' removal questions are not bookmarks and
    are untouched."""
    inbox_dir = memory_path / "inbox"
    if not inbox_dir.is_dir():
        return [], {}
    removed: list[str] = []
    marks: dict[str, str] = {}
    for path in sorted(inbox_dir.glob("inbox-*.md")):
        try:
            fm = markdown_parser.parse(path).frontmatter or {}
        except Exception:
            continue
        if (str(fm.get("kind") or "") != "removal" or str(fm.get("trigger") or "") != "sync/bookmark_removal"
                or str(fm.get("channel") or "") != channel or str(fm.get("status") or "pending") != "pending"):
            continue
        url = str(fm.get("url") or "")
        if url:
            marks[media_ingestor.url_hash(url)] = str(fm.get("synced_at") or "") or episode_ids.utc_now_iso()
        path.unlink()
        removed.append(f"inbox/{path.name}")
    return removed, marks


async def sync_bookmarks(
    memory_path: Path,
    *,
    chrome_data: bytes | None = None,
    safari_data: bytes | None = None,
    chromium: list[tuple[str, bytes]] | None = None,
    folders: list[str] | None = None,
    ingest_fn: IngestFn | None = None,
    propose_removals: bool = True,
) -> dict[str, Any]:
    """Parse whichever bookmark data is provided and ingest only the new URLs.

    The diff/dedup is entirely the existing url-hash index: each provided
    source's items are tagged with their origin and handed to ``ingest_fn``
    (default ``media_ingestor.ingest_batch``), which re-checks
    ``url_index.json`` and only writes episodes/media entities for URLs not
    already present. Nothing is parsed or ingested for a source whose data
    was not supplied (``chrome_data=None`` / ``safari_data=None`` skips it).
    ``chromium`` (round 4, C9) is ``[(browser, bytes)]`` for the Chromium family;
    each gets its own origin and channel. A Safari source also carries its
    ``reading_list`` / ``favorites`` counts (R-SR13), and its items are ingested
    recently saved first.

    ``folders`` (R5) narrows each source to the selected folder paths before
    ingest; omitted, the behaviour is byte-identical to before the option
    existed. ``found`` then counts the items that survived the filter — the
    number the channel row reports as "N bookmarks".

    ``propose_removals`` (G129 slice 2, default on; the name is kept for its callers) diffs each synced channel's
    CURRENT url-hash set against its PREVIOUS one, read from ``bookmark_seen.py``'s own per-channel seen-set — never
    against ``url_index.json`` (Rail 2). **G191 v4 (owner 2026-10-15):** a link missing from the current set is no
    longer a ``removal`` inbox question: it is marked as gone from that browser, with the day (the seen-set's
    ``left`` map, :func:`bookmark_seen.next_left`), and Cicada keeps the bookmark, its page and its reasons. A link
    present again (the person bookmarked it again) loses the mark on the same sync, and is asked about like any
    re-save. The diff is refused — nothing marked — when the rails say the two reads are not comparable
    (:func:`_not_comparable`: a channel's first read, a folder-scope change, an empty read, a wholesale swap), and
    every refusal but the first read is recorded in ``removals_skipped``. The seen-set then advances to the CURRENT
    hashes (Rail 2's "always advance"), except after an empty read, which keeps the previous set so a half-written file
    never makes every link look new or gone. A pending removal question an earlier version asked about this channel
    is retired into the status (:func:`_retire_removal_questions`).

    Returns ``{"new": <total newly-ingested>, "skipped": <total already
    present>, "sources": [{"origin", "channel", "found", "new", "skipped"},
    ...], "removals_proposed": 0 (G191 v4: never asked any more; kept on the wire for older clients),
    "removals_skipped": <"; "-joined per-channel reasons, or None>,
    "left_marked": <links newly marked as gone from their browser>,
    "fresh": [...], "fresh_total": <int>}`` — ``channel`` is the
    ``sync_state`` key the router stamps (R4). G191 adds ``first_sync`` to
    each source (no seen-set before this pass) and ``fresh``: the bookmarks
    this sync newly saved (``FRESH_CAP`` of them, each with its episode and
    the browser's own ``added_at`` instant when the file records one), so the
    app can ask "what made you save this?" about one bookmark made a moment
    ago — and never after a first sync, a bulk import or a reorganisation
    (moved bookmarks are known URLs, so they are never fresh).

    A touched ``sources/bookmark_seen.json``, the revived pages and the retired questions are committed together at
    the end (``_commit_removals``) — scoped to exactly those paths, never ``git add -A`` (finding 1, G129 slice-2 final
    review).
    """
    fn: IngestFn = ingest_fn or media_ingestor.ingest_batch
    memory_path = Path(memory_path)

    sources: list[dict[str, Any]] = []
    total_new = 0
    total_skipped = 0
    total_left = 0
    removals_skip_reasons: list[str] = []
    retired_paths: list[str] = []
    seen_touched = False

    at = episode_ids.utc_now_iso()
    # G191: read regardless of `propose_removals` — a channel with no seen-set has never been synced, and a first sync
    # is never a moment to ask "what made you save this?".
    prev_seen = bookmark_seen.read_seen(memory_path)
    fresh: list[dict[str, Any]] = []
    revived_paths: list[str] = []

    for origin, items in _batches(chrome_data, safari_data, chromium):
        items = filter_by_folders(items, folders) if folders else items
        channel = CHANNEL_BY_ORIGIN[origin]
        prev_entry = prev_seen.get(channel)
        current_hashes = sorted({media_ingestor.url_hash(i.url) for i in items if i.url})
        refusal = _not_comparable(prev_entry, current_hashes, folders)
        created = duplicates = 0
        if items:
            unseen = _unseen(items, memory_path)
            # G191 v3: read before the ingest (the index after it holds the new links too) and before the seen-set
            # advances below. G191 v4: only against a comparable read.
            resaved = _resaved(items, memory_path, origin=origin, channel=channel,
                               prev_entry=None if refusal else prev_entry, folders=folders, unseen=unseen)
            created, duplicates = await fn(items, memory_path, from_bookmark_file=True)
            total_new += created
            total_skipped += duplicates
            fresh.extend(_fresh(unseen, memory_path, origin=origin, channel=channel))
            fresh.extend(resaved)
            revived_paths.extend(_revive(memory_path, resaved))
        entry = {"origin": origin, "channel": channel, "found": len(items), "new": created, "skipped": duplicates,
                 "first_sync": channel not in prev_seen}
        if origin == SAFARI_ORIGIN:
            entry.update(safari_parts(items))
        sources.append(entry)

        if propose_removals:
            if refusal in _REFUSAL_WORDS:
                removals_skip_reasons.append(f"{channel}: {_REFUSAL_WORDS[refusal]}")
            retired, retired_marks = _retire_removal_questions(memory_path, channel)
            retired_paths.extend(retired)
            if refusal == "empty":
                # A file that held nothing: the previous set stays, so the next real read is compared with it.
                if retired:
                    bookmark_seen.write_channel_seen(
                        memory_path, channel, folders=(prev_entry or {}).get("folders"),
                        hashes=list((prev_entry or {}).get("hashes") or []), at=(prev_entry or {}).get("at"),
                        newest_added=(prev_entry or {}).get("newest_added"),
                        left={**retired_marks, **bookmark_seen.left_of(prev_entry)})
                    seen_touched = True
                continue
            removed = None if refusal else bookmark_seen.diff_removed(
                prev_entry, current_hashes,
                previous_folders=(prev_entry or {}).get("folders"), current_folders=folders)
            idx = media_ingestor.load_url_index(memory_path)
            base = {"left": {**retired_marks, **bookmark_seen.left_of(prev_entry)}}
            left = bookmark_seen.next_left(base, current_hashes, removed, at=at, held=set(idx))
            total_left += len(set(left) - set(base["left"]))
            bookmark_seen.write_channel_seen(memory_path, channel, folders=folders, hashes=current_hashes, at=at,
                                             newest_added=newest_added(items), left=left)
            seen_touched = True

    if retired_paths or seen_touched or revived_paths:
        await _commit_removals(memory_path, retired_paths, seen_touched, revived_paths)

    return {
        "new": total_new,
        "skipped": total_skipped,
        "sources": sources,
        # G191 v4: a bookmark leaving the browser is a status, never a question.
        "removals_proposed": 0,
        "removals_skipped": "; ".join(removals_skip_reasons) or None,
        "left_marked": total_left,
        # G191: what THIS sync newly saved, so the app can ask why about a single bookmark made a moment ago.
        "fresh": fresh[:FRESH_CAP],
        "fresh_total": len(fresh),
    }


def fresh_preview(
    memory_path: Path,
    *,
    chrome_data: bytes | None = None,
    safari_data: bytes | None = None,
    chromium: list[tuple[str, bytes]] | None = None,
) -> dict[str, Any]:
    """G191 — the early look: which bookmarks in these bytes this bank does not hold yet, WITHOUT ingesting anything.

    Measured 2026-10-14: the full sync answered 6-7 s after the browser wrote its file (each new link is enriched by a
    page fetch, then two commits), and the panel waited for it and for the store's reconcile behind it — 18 s in all.
    This is the same parse and the same ``url_index`` check the sync runs first (``_batches`` + ``_unseen``), so the
    app can ask "what made you save this?" a moment after the save while the real sync runs. Read-only: no lock, no
    write, no commit, no fetch. Returns the sync's own shape (``new``/``skipped`` 0, each source's ``first_sync``,
    ``fresh`` without an episode yet) so one policy decides both.
    """
    memory_path = Path(memory_path)
    prev_seen = bookmark_seen.read_seen(memory_path)
    sources: list[dict[str, Any]] = []
    fresh: list[dict[str, Any]] = []
    for origin, items in _batches(chrome_data, safari_data, chromium):
        channel = CHANNEL_BY_ORIGIN[origin]
        sources.append({"origin": origin, "channel": channel, "found": len(items), "new": 0, "skipped": 0,
                        "first_sync": channel not in prev_seen})
        unseen = _unseen(items, memory_path)
        for item in unseen:
            fresh.append({"url": item.url, "title": item.title or "", "origin": origin, "channel": channel,
                          "episode_id": "", "media_entity_id": "",
                          "added_at": saved_at.validate_instant(item.added_at), "resave": False})
        # G191 v3: a link held already but saved again — the early look asks about it like a new one.
        prev_entry = prev_seen.get(channel)
        current = sorted({media_ingestor.url_hash(i.url) for i in items if i.url})
        comparable = _not_comparable(prev_entry, current, None) is None
        fresh.extend(_resaved(items, memory_path, origin=origin, channel=channel,
                              prev_entry=prev_entry if comparable else None, folders=None, unseen=unseen))
    return {"new": 0, "skipped": 0, "sources": sources, "removals_proposed": 0, "removals_skipped": None,
            "left_marked": 0, "fresh": fresh[:FRESH_CAP], "fresh_total": len(fresh)}


#: G191 — how many newly saved bookmarks a sync lists by name. The app asks only when exactly one is new, so a few is
#: plenty to tell one from many; `fresh_total` carries the real count.
FRESH_CAP = 3


def _unseen(items: list[RawItem], memory_path: Path) -> list[RawItem]:
    """The items no ``url_index`` row holds yet, one per URL — what this sync can newly save (G191)."""
    idx = media_ingestor.load_url_index(memory_path)
    out: list[RawItem] = []
    seen: set[str] = set()
    for item in items:
        if not item.url or media_ingestor.existing_hash(item, idx) is not None:
            continue
        h = media_ingestor.url_hash(item.url)
        if h not in seen:
            seen.add(h)
            out.append(item)
    return out


def _fresh(unseen: list[RawItem], memory_path: Path, *, origin: str, channel: str) -> list[dict[str, Any]]:
    """The unseen items the ingest really saved, read back from ``url_index`` (an item the ingest dropped — a junk
    URL, a failed write — has no row and is not listed)."""
    if not unseen:
        return []
    idx = media_ingestor.load_url_index(memory_path)
    out: list[dict[str, Any]] = []
    for item in unseen:
        h = media_ingestor.existing_hash(item, idx)
        row = idx.get(h) if h else None
        if not row or not row.get("episode_id"):
            continue
        out.append({
            "url": item.url,
            "title": str(row.get("title") or item.title or ""),
            "origin": origin,
            "channel": channel,
            "episode_id": str(row.get("episode_id") or ""),
            "media_entity_id": str(row.get("media_entity_id") or ""),
            "added_at": saved_at.validate_instant(item.added_at),
            "resave": False,
        })
    return out


def newest_added(items: list[RawItem]) -> str | None:
    """The newest browser instant among ``items`` (aware UTC ISO), or ``None`` when the file records none (Safari's
    bookmarks) — what the seen-set keeps so the next sync can tell a bookmark made since from one moved since."""
    instants = [v for v in (saved_at.validate_instant(i.added_at) for i in items) if v]
    return max(instants, key=saved_at.sort_instant) if instants else None


def _resaved(items: list[RawItem], memory_path: Path, *, origin: str, channel: str, prev_entry: dict | None,
             folders: list[str] | None, unseen: list[RawItem]) -> list[dict[str, Any]]:
    """G191 v3 — the bookmarks saved AGAIN since this channel's last sync: links the bank already holds (so they are
    not new to Cicada) that this browser's file has newly saved. Owner 2026-10-15: "If I remove the bookmark and
    bookmark it again, the prompt doesn't appear. Is that on purpose?" — it was not; a re-save is a new moment of
    saving.

    **A re-save, not a move.** A bookmark counts as saved again when, on this channel:

    * its URL was absent from the previous sync's seen-set and is present now (removed and saved again, or saved
      here for the first time while another browser already held it), or
    * the browser stamps it (Chrome's ``date_added``) later than the newest instant the previous sync saw — a new
      bookmark node for a link already bookmarked (removed and saved again between two syncs, or a duplicate).

    A move, a rename or a reorganisation keeps both the URL in the seen-set and the node's own ``date_added``, so it
    is never a re-save. Refused, like the removal diff (Rail 1), on a first sync (no seen-set) or when the folder
    scope changed since the last sync. Each is reported in ``fresh`` with ``resave: true`` and the episode the link
    already has, so one policy in the app decides about both."""
    if prev_entry is None:
        return []
    if bookmark_seen._normalize_folders(prev_entry.get("folders")) != bookmark_seen._normalize_folders(folders):
        return []
    prev_hashes = set(prev_entry.get("hashes") or [])
    newest_before = saved_at.validate_instant(prev_entry.get("newest_added")) or saved_at.validate_instant(
        prev_entry.get("at"))
    idx = media_ingestor.load_url_index(memory_path)
    skip = {media_ingestor.url_hash(i.url) for i in unseen if i.url}
    out: list[dict[str, Any]] = []
    for item in items:
        if not item.url:
            continue
        h = media_ingestor.url_hash(item.url)
        if h in skip:
            continue
        held = media_ingestor.existing_hash(item, idx)
        row = idx.get(held) if held else None
        if not row or not row.get("episode_id"):
            continue
        added = saved_at.validate_instant(item.added_at)
        absent = h not in prev_hashes
        later = bool(added and newest_before) and saved_at.sort_instant(added) > saved_at.sort_instant(newest_before)
        if not (absent or later):
            continue
        skip.add(h)
        out.append({
            "url": item.url,
            "title": str(row.get("title") or item.title or ""),
            "origin": origin,
            "channel": channel,
            "episode_id": str(row.get("episode_id") or ""),
            "media_entity_id": str(row.get("media_entity_id") or ""),
            "added_at": added,
            "resave": True,
        })
    return out


def _revive(memory_path: Path, resaved: list[dict[str, Any]]) -> list[str]:
    """A link saved again whose page the person removed (archived by a removal answer or by Remove on its bookmark
    page) comes back: the media page is active again and its episode loses the removal stamp. Returns the
    memory-relative paths written, for the sync's own scoped commit."""
    written: list[str] = []
    for item in resaved:
        entity_id = str(item.get("media_entity_id") or "")
        path = memory_path / "entities" / f"{entity_id}.md"
        if entity_id and path.is_file():
            try:
                parsed = markdown_parser.parse(path)
            except Exception:
                parsed = None
            if parsed is not None and str(parsed.frontmatter.get("status") or "active") == "archived":
                parsed.frontmatter["status"] = "active"
                parsed.frontmatter["last_referenced"] = str(date.today())
                parsed.frontmatter.pop("removed_at", None)
                markdown_parser.write(path, parsed.frontmatter, parsed.body)
                written.append(f"entities/{entity_id}.md")
        episode_id = str(item.get("episode_id") or "")
        ep = memory_path / "episodes" / f"{episode_id}.md"
        if episode_id and ep.is_file() and bookmark_forget.clear_removed(ep):
            written.append(f"episodes/{episode_id}.md")
    return written


async def _commit_removals(memory_path: Path, retired_paths: list[str], seen_touched: bool,
                           revived_paths: list[str] | None = None) -> None:
    """Commit scoped to exactly the files this sync changed — a touched ``sources/bookmark_seen.json`` (G191 v4: the
    links that left a browser ride it), the pages a re-save brought back and the removal questions it retired — never
    ``git add -A`` (finding 1, G129 slice-2 final review), mirroring ``media_ingestor._commit_media``.

    ``Cicada-Author: cicada`` — no LLM ran and no user made a choice; this is pure bookkeeping the browser's file
    proved, exactly like the G85 decay-only commit. Best-effort: a non-git memory dir (most unit tests use a bare
    ``tmp_path``) must not fail the sync itself, so failures are logged and swallowed.
    """
    from api.services import git_service

    revived_paths = revived_paths or []
    # A retired question git never tracked has nothing to stage (`git add` refuses a pathspec that matches nothing).
    retired = [p for p in sorted(retired_paths) if await git_service.is_tracked(memory_path, p)]
    paths = sorted(set(retired) | set(revived_paths)
                   | ({"sources/bookmark_seen.json"} if seen_touched else set()))
    # G191 v3: a removed bookmark saved again is active again — bookkeeping the browser's file proved, no model.
    lines = [f"{p}: updated (trigger: sync/bookmark_resave)" for p in sorted(revived_paths)]
    # G191 v4: a bookmark leaving the browser is a status on the seen-set, not a question.
    lines += [f"{p}: removed (trigger: sync/bookmark_left)" for p in retired]
    if seen_touched:
        lines.append("sources/bookmark_seen.json: updated (trigger: sync/bookmark_left)")
    if not paths:
        return
    message = git_service.build_commit_message(
        f"Bookmark sync {date.today()}", lines, authors=["cicada"],
    )
    try:
        await git_service.commit_paths(memory_path, message, paths)
    except Exception as e:  # pragma: no cover - non-git workspace (most unit tests)
        logger.warning(f"Bookmark sync commit failed: {type(e).__name__}: {e}")
