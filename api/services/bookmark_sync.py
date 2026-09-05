"""Keyless browser-bookmark sync connector.

Polls the local Chrome/Safari bookmark files (or accepts inline bytes, e.g.
from the companion app or a test), diffs the parsed URLs against what has
already been ingested, and pushes only the *new* ones into the existing
ingest pipeline.

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
6. (G129 slice 2) removal proposals — a URL that dropped out of a channel's
   browser file since the previous sync becomes one ``removal`` inbox item
   (``keep``/``remove``; ``remove`` archives, never deletes). Diffed against
   ``bookmark_seen.py``'s own per-channel seen-set, NEVER against
   ``url_index.json`` (a kept URL has already left the browser, and a
   memory-based diff would re-propose it forever — see that module's
   docstring for both correctness rails).

Nothing here reads a real file path unless ``sync_from_local_files`` is
called explicitly, and that function is best-effort/offline-safe: a missing
or unreadable bookmark file is silently excluded, never raised.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Awaitable, Callable

from loguru import logger

from api.services import bookmark_seen, episode_ids, inbox_generator, inbox_service, markdown_parser, media_ingestor
from api.services.media_ingestor import RawItem

# (items, memory_path, from_bookmark_file) -> (created, duplicates), matching
# media_ingestor.ingest_batch's signature (commit kwarg has a default there).
IngestFn = Callable[..., Awaitable[tuple[int, int]]]


# --- Standard macOS bookmark file locations ---------------------------------


def chrome_bookmarks_path() -> Path:
    """The standard macOS location of Chrome's default-profile ``Bookmarks`` JSON file."""
    return (
        Path.home()
        / "Library"
        / "Application Support"
        / "Google"
        / "Chrome"
        / "Default"
        / "Bookmarks"
    )


def safari_bookmarks_path() -> Path:
    """The standard macOS location of Safari's ``Bookmarks.plist``."""
    return Path.home() / "Library" / "Safari" / "Bookmarks.plist"


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


# Which `sync_state.json` channel each browser's sync stamps (R4). The old
# combined "bookmarks" key is read back as a legacy fallback by
# `channel_registry._sync_channel` and never written again: the catalog has
# one tile per browser, and a channel must map to exactly one tile.
CHANNEL_BY_ORIGIN = {"chrome-bookmark": "chrome-bookmarks", "safari-bookmark": "safari-bookmarks"}

# Display label for a removal item's question text and its hint (R2) — the
# same two origins `_tag_origin` ever stamps.
_BROWSER_LABEL = {"chrome-bookmark": "Chrome", "safari-bookmark": "Safari"}

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


def _batches(chrome_data: bytes | None, safari_data: bytes | None) -> list[tuple[str, list[RawItem]]]:
    """Parse + origin-tag whichever sources were supplied, in the fixed
    Chrome-then-Safari order both ``sync_bookmarks`` and ``preview_bookmarks``
    report — one parse path so a preview can never disagree with the sync."""
    batches: list[tuple[str, list[RawItem]]] = []
    if chrome_data is not None:
        batches.append(("chrome-bookmark", _tag_origin(read_chrome_bookmarks(chrome_data), "chrome-bookmark")))
    if safari_data is not None:
        batches.append((
            "safari-bookmark",
            _tag_origin(media_ingestor.parse_safari_bookmarks(safari_data), "safari-bookmark"),
        ))
    return batches


def preview_bookmarks(*, chrome_data: bytes | None = None, safari_data: bytes | None = None) -> dict[str, Any]:
    """Folder trees per supplied source — parse only, nothing staged (mirrors
    ``media_ingestor.preview_upload``'s contract for ``?preview=true``), so
    the app can show "Favorites · 500" before the user picks a folder.

    Returns ``{"sources": [{"origin", "total", "tree"}, ...]}``.
    """
    return {"sources": [
        {"origin": origin, "total": sum(1 for i in items if i.url), "tree": folder_tree(items)}
        for origin, items in _batches(chrome_data, safari_data)
    ]}


def _propose_removals(
    memory_path: Path, *, origin: str, channel: str, removed_hashes: list[str], at: str,
) -> list[str]:
    """One ``removal`` inbox item per hash in ``removed_hashes`` that still
    names a live, non-archived media entity and has no open removal item
    already (idempotency — a second sync before the person answers must not
    spawn a second question for the same URL; ``inbox_generator.find_open``'s
    existing ``(entity_id, "")`` dedup key, unchanged, already covers this).

    ``remove`` never deletes the page (G129 row rule) — that happens on
    resolve, not here; this function only ever proposes. Returns the
    memory-relative paths of the inbox items actually written (e.g.
    ``["inbox/inbox-005.md"]``) so the caller can commit exactly those files
    rather than ``git add -A`` (finding 1, G129 slice-2 final review) — a
    dirty unrelated file elsewhere in the bank must never ride along under
    this sync's ``cicada``/``sync/bookmark_removal`` provenance.
    """
    idx = media_ingestor.load_url_index(memory_path)
    inbox_dir = memory_path / "inbox"
    inbox_dir.mkdir(parents=True, exist_ok=True)
    next_num = inbox_service.next_inbox_num(inbox_dir)
    browser = _BROWSER_LABEL.get(origin, origin)
    written: list[str] = []
    for h in removed_hashes:
        entry = idx.get(h)
        entity_id = str((entry or {}).get("media_entity_id") or "")
        if not entity_id:
            continue  # never ingested, or the index entry is gone — nothing to ask about
        entity_path = memory_path / "entities" / f"{entity_id}.md"
        if not entity_path.exists():
            continue
        try:
            efm = markdown_parser.parse(entity_path).frontmatter
        except Exception:
            continue
        if str(efm.get("status", "active") or "active") in ("archived", "dropped"):
            continue  # already gone — nothing left to ask
        if inbox_generator.find_open(memory_path, "removal", entity_id) is not None:
            continue  # already asked, still pending
        entity_name = str(efm.get("name") or entry.get("title") or entity_id)
        # R2: the entity's own first-save origin vs THIS sync's origin — a
        # mismatch means some other path (a manual save, the other browser)
        # is where it actually came from, worth surfacing on the card.
        entity_origin = str(efm.get("origin") or "") or None
        hint = f"Also saved via {entity_origin}" if entity_origin and entity_origin != origin else None
        item_id = f"inbox-{next_num:03d}"
        next_num += 1
        frontmatter = {
            "kind": "removal",
            "required_input": "choice",
            "status": "pending",
            "priority": 0.4,
            "entity_id": entity_id,
            "entity_name": entity_name,
            "title": f"Still keep {entity_name}?",
            "created_date": str(date.today()),
            "question": f"It was removed from {browser}.",
            # R4: keep first — QuestionSelection's documented no-recommendation
            # fallback highlights index 0.
            "options": [
                {"key": "keep", "label": "Keep"},
                {"key": "remove", "label": "Remove"},
            ],
            "allow_other": False,
            "allow_defer": True,
            "channel": channel,
            "browser": browser,
            "url": str(entry.get("url") or ""),
            "synced_at": at,
            "hint": hint,
            "trigger": "sync/bookmark_removal",
        }
        markdown_parser.write(
            inbox_dir / f"{item_id}.md", frontmatter,
            f"{entity_name} was removed from {browser}.",
        )
        written.append(f"inbox/{item_id}.md")
    return written


async def sync_bookmarks(
    memory_path: Path,
    *,
    chrome_data: bytes | None = None,
    safari_data: bytes | None = None,
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

    ``folders`` (R5) narrows each source to the selected folder paths before
    ingest; omitted, the behaviour is byte-identical to before the option
    existed. ``found`` then counts the items that survived the filter — the
    number the channel row reports as "N bookmarks".

    ``propose_removals`` (G129 slice 2, default on) additionally diffs each
    synced channel's CURRENT url-hash set against its PREVIOUS one, read from
    ``bookmark_seen.py``'s own per-channel seen-set — never against
    ``url_index.json`` (Rail 2: a kept URL has already left the browser, and
    a memory-based diff would re-propose it after every subsequent sync
    forever). A URL missing from the current set becomes one ``removal``
    inbox item (``_propose_removals``). The diff is refused (Rail 1) — and
    recorded as a skip reason, never silently guessed — when the current
    sync's folder scope differs from the previous one's, because everything
    outside a changed selection was never looked at this pass and would look
    deleted for the wrong reason; a channel's very first sync (no previous
    seen-set at all) refuses the same way but silently (R6 — that case is
    expected, not an error). The seen-set is then advanced to the CURRENT
    sync's hashes regardless of what was proposed or answered (Rail 2's
    "always advance" half) — this is what makes "a kept URL is never
    re-proposed" hold with no bookkeeping of the person's eventual answer.

    Returns ``{"new": <total newly-ingested>, "skipped": <total already
    present>, "sources": [{"origin", "channel", "found", "new", "skipped"},
    ...], "removals_proposed": <total removal items written>,
    "removals_skipped": <"; "-joined per-channel reasons, or None>}`` —
    ``channel`` is the ``sync_state`` key the router stamps (R4).

    Every ``removal`` item this call wrote, plus a touched
    ``sources/bookmark_seen.json``, are committed together at the end
    (``_commit_removals``) — scoped to exactly those paths, never
    ``git add -A``, mirroring ``media_ingestor._commit_media``'s pattern one
    call earlier in this same path (finding 1, G129 slice-2 final review):
    without it, both files sat dirty until some unrelated later writer's
    broad commit silently absorbed them under the wrong author/trigger.
    """
    fn: IngestFn = ingest_fn or media_ingestor.ingest_batch
    memory_path = Path(memory_path)

    sources: list[dict[str, Any]] = []
    total_new = 0
    total_skipped = 0
    total_removals_proposed = 0
    removals_skip_reasons: list[str] = []
    removal_paths: list[str] = []
    seen_touched = False

    at = episode_ids.utc_now_iso()
    prev_seen = bookmark_seen.read_seen(memory_path) if propose_removals else {}

    for origin, items in _batches(chrome_data, safari_data):
        items = filter_by_folders(items, folders) if folders else items
        channel = CHANNEL_BY_ORIGIN[origin]
        if not items:
            sources.append({"origin": origin, "channel": channel, "found": 0, "new": 0, "skipped": 0})
        else:
            created, duplicates = await fn(items, memory_path, from_bookmark_file=True)
            total_new += created
            total_skipped += duplicates
            sources.append({
                "origin": origin,
                "channel": channel,
                "found": len(items),
                "new": created,
                "skipped": duplicates,
            })

        if propose_removals:
            current_hashes = sorted({media_ingestor.url_hash(i.url) for i in items})
            prev_entry = prev_seen.get(channel)
            removed = bookmark_seen.diff_removed(
                prev_entry, current_hashes,
                previous_folders=(prev_entry or {}).get("folders"),
                current_folders=folders,
            )
            if removed is None:
                if prev_entry is not None:  # R6: silent on a channel's first-ever sync
                    removals_skip_reasons.append(f"{channel}: folder scope changed since the last sync")
            elif removed:
                new_paths = _propose_removals(
                    memory_path, origin=origin, channel=channel, removed_hashes=removed, at=at,
                )
                total_removals_proposed += len(new_paths)
                removal_paths.extend(new_paths)
            bookmark_seen.write_channel_seen(memory_path, channel, folders=folders, hashes=current_hashes, at=at)
            seen_touched = True

    if removal_paths or seen_touched:
        await _commit_removals(memory_path, removal_paths, seen_touched)

    return {
        "new": total_new,
        "skipped": total_skipped,
        "sources": sources,
        "removals_proposed": total_removals_proposed,
        "removals_skipped": "; ".join(removals_skip_reasons) or None,
    }


async def _commit_removals(memory_path: Path, removal_paths: list[str], seen_touched: bool) -> None:
    """Commit scoped to exactly the removal items written this call plus a
    touched ``sources/bookmark_seen.json`` — never ``git add -A`` (finding 1,
    G129 slice-2 final review), mirroring ``media_ingestor._commit_media``.

    ``Cicada-Author: cicada`` — no LLM ran and no user made a choice; this is
    pure bookkeeping (a removal *proposal*, not a resolution) exactly like the
    G85 decay-only commit and the idle inbox-refresh commit
    (``sleep_cycle._run_idle_question_refresh``), both of which use the same
    author for the same reason. Best-effort: a non-git memory dir (most unit
    tests use a bare ``tmp_path``) must not fail the sync itself, so failures
    are logged and swallowed, matching every other scoped-commit call site in
    this codebase (``_commit_media``, the idle refresh above).
    """
    from api.services import git_service

    paths = sorted(set(removal_paths) | ({"sources/bookmark_seen.json"} if seen_touched else set()))
    lines = [f"{p}: created (trigger: sync/bookmark_removal)" for p in sorted(removal_paths)]
    if seen_touched:
        lines.append("sources/bookmark_seen.json: updated (trigger: sync/bookmark_removal)")
    message = git_service.build_commit_message(
        f"Bookmark removal sync {date.today()}", lines, authors=["cicada"],
    )
    try:
        await git_service.commit_paths(memory_path, message, paths)
    except Exception as e:  # pragma: no cover - non-git workspace (most unit tests)
        logger.warning(f"Bookmark removal commit failed: {type(e).__name__}: {e}")


async def sync_from_local_files(memory_path: Path) -> dict[str, Any]:
    """Best-effort, offline-safe sync against the real local bookmark files.

    For a scheduled/triggered sync (cron, "sync now" button) where no inline
    data is supplied. Reads ``chrome_bookmarks_path()`` / ``safari_bookmarks_path()``
    if they exist; a missing file, permission error, or unreadable file is
    swallowed and that source is simply excluded — this function never raises.
    If neither file is present, returns ``{"new": 0, "skipped": 0, "sources": []}``
    without touching ``ingest_batch`` at all. Not exercised against the real
    filesystem in tests.
    """
    chrome_data: bytes | None = None
    try:
        path = chrome_bookmarks_path()
        if path.exists():
            chrome_data = path.read_bytes()
    except OSError as e:
        logger.debug(f"Could not read Chrome bookmarks: {type(e).__name__}: {e}")

    safari_data: bytes | None = None
    try:
        path = safari_bookmarks_path()
        if path.exists():
            safari_data = path.read_bytes()
    except OSError as e:
        logger.debug(f"Could not read Safari bookmarks: {type(e).__name__}: {e}")

    if chrome_data is None and safari_data is None:
        return {"new": 0, "skipped": 0, "sources": []}

    return await sync_bookmarks(memory_path, chrome_data=chrome_data, safari_data=safari_data)
