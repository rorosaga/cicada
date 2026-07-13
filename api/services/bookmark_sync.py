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
2. an ``origin`` tag (``chrome-bookmark`` / ``safari-bookmark``) so synced
   items are distinguishable from a manual save or a one-off file upload;
3. a thin summary shape (``{new, skipped, sources}``) for the endpoint/cron.

Nothing here reads a real file path unless ``sync_from_local_files`` is
called explicitly, and that function is best-effort/offline-safe: a missing
or unreadable bookmark file is silently excluded, never raised.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Awaitable, Callable

from loguru import logger

from api.services import media_ingestor
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
    return items


async def sync_bookmarks(
    memory_path: Path,
    *,
    chrome_data: bytes | None = None,
    safari_data: bytes | None = None,
    ingest_fn: IngestFn | None = None,
) -> dict[str, Any]:
    """Parse whichever bookmark data is provided and ingest only the new URLs.

    The diff/dedup is entirely the existing url-hash index: each provided
    source's items are tagged with their origin and handed to ``ingest_fn``
    (default ``media_ingestor.ingest_batch``), which re-checks
    ``url_index.json`` and only writes episodes/media entities for URLs not
    already present. Nothing is parsed or ingested for a source whose data
    was not supplied (``chrome_data=None`` / ``safari_data=None`` skips it).

    Returns ``{"new": <total newly-ingested>, "skipped": <total already
    present>, "sources": [{"origin", "found", "new", "skipped"}, ...]}``.
    """
    fn: IngestFn = ingest_fn or media_ingestor.ingest_batch
    memory_path = Path(memory_path)

    batches: list[tuple[str, list[RawItem]]] = []
    if chrome_data is not None:
        batches.append(("chrome-bookmark", _tag_origin(read_chrome_bookmarks(chrome_data), "chrome-bookmark")))
    if safari_data is not None:
        batches.append((
            "safari-bookmark",
            _tag_origin(media_ingestor.parse_safari_bookmarks(safari_data), "safari-bookmark"),
        ))

    sources: list[dict[str, Any]] = []
    total_new = 0
    total_skipped = 0

    for origin, items in batches:
        if not items:
            sources.append({"origin": origin, "found": 0, "new": 0, "skipped": 0})
            continue
        created, duplicates = await fn(items, memory_path, from_bookmark_file=True)
        total_new += created
        total_skipped += duplicates
        sources.append({
            "origin": origin,
            "found": len(items),
            "new": created,
            "skipped": duplicates,
        })

    return {"new": total_new, "skipped": total_skipped, "sources": sources}


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
