"""When book episodes become pages (G233): right after a door stages them, and again on Sleep's tail.

A door (a scan, an Apple Books sync, a Goodreads import) stages its episodes — Awake capture, no admission — and
commits them. Then :func:`resolve_and_apply` asks about the scans' ISBNs (``book_lookup``, only while
``CICADA_ALLOW_CONNECTOR_FETCH`` allows it — a lookup is never a model call and never holds admission) and applies
every pending book episode (``books.apply_pending``) inside the bank's write admission, committing its own paths. If
Sleep holds the pages, nothing is applied: the episodes stay pending and Sleep's tail applies them
(``sleep_cycle._resolve_books_safely``), so nothing waits on a process staying up.

One run per bank at a time in this process: a second request while one runs asks it to go round once more.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from loguru import logger

from api.services import book_lookup, books, folder_source, write_admission

CHANNEL = "books"
_RUNNING: dict[str, asyncio.Task] = {}
_AGAIN: set[str] = set()


class _Busy(Exception):
    pass


async def apply_admitted(memory_path: Path, *, author: str, trigger: str) -> dict:
    """Apply pending book episodes and commit what moved, inside the bank's admission; ``{"deferred": True}`` when
    Sleep holds the pages (the tail applies them)."""
    memory_path = Path(memory_path)

    async def body():
        out = await asyncio.to_thread(books.apply_pending, memory_path, defer_renames=True)
        if out["paths"]:
            await folder_source.commit_paths_for(memory_path, out["paths"], subject="Books", trigger=trigger,
                                                 author=author, channel=CHANNEL)
        if out["cicada_paths"]:
            # Cicada's own rewrites (placeholders, lookups, cover stamps) are never the person's scan or sync.
            await folder_source.commit_paths_for(memory_path, out["cicada_paths"], subject="Books", trigger="books/enrich",
                                                 author="cicada", channel=CHANNEL)
        if out.get("renames"):
            # ROR-122: after the person's own commit, so a source's new title is Cicada's own, alone.
            moved = await asyncio.to_thread(books.apply_renames, memory_path, out["renames"])
            if moved:
                await folder_source.commit_paths_for(memory_path, moved, subject="Books", trigger="books/rename",
                                                     author="cicada", channel=CHANNEL)
        return out

    try:
        return await write_admission.run_admitted(memory_path, body, refuse=_Busy)
    except _Busy:
        return {"deferred": True}


async def lookup_waiting(memory_path: Path, *, fetch=None) -> dict | None:
    """Ask about the ISBNs that wait, when the gate allows; None when it does not or nothing waits."""
    from api.services.connectors.base import network_allowed

    isbns = await asyncio.to_thread(books.waiting_isbns, Path(memory_path))
    if not isbns:
        return None
    if not network_allowed():
        from api.services import sync_state

        sync_state.record_skip(Path(memory_path), CHANNEL, "network fetch disabled")
        return None
    return await book_lookup.resolve(isbns, fetch=fetch)


async def resolve_and_apply(memory_path: Path, *, author: str, trigger: str, fetch=None) -> dict:
    report: dict = {}
    try:
        looked = await lookup_waiting(memory_path, fetch=fetch)
        if looked:
            report["lookup"] = looked
        report["apply"] = await apply_admitted(memory_path, author=author, trigger=trigger)
    except Exception as exc:  # noqa: BLE001 — a background job never raises; the episodes stay pending
        from api.services import tool_contract

        logger.warning(f"books: resolve and apply failed: {tool_contract.where(exc)}")
    return report


def schedule(memory_path: Path, *, author: str, trigger: str) -> None:
    """Run :func:`resolve_and_apply` in the background (a scan's answer never waits on a lookup)."""
    key = str(Path(memory_path).resolve())
    running = _RUNNING.get(key)
    if running is not None and not running.done():
        _AGAIN.add(key)
        return

    async def run():
        while True:
            _AGAIN.discard(key)
            await resolve_and_apply(memory_path, author=author, trigger=trigger)
            if key not in _AGAIN:
                break

    task = asyncio.get_running_loop().create_task(run())
    _RUNNING[key] = task
    task.add_done_callback(lambda t: _RUNNING.pop(key, None) if _RUNNING.get(key) is t else None)
