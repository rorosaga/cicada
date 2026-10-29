"""One idle tick per bank, shared by every SSE subscriber (audit 2026-10-02 A10).

`GET /sync/events` used to run `sync_service.version` (a stat walk of the bank)
and `sleep_debt.compute` (another walk of `episodes/`) once a second in EVERY
connected stream, the debt half on the event loop: N clients, N walks. Here one
`current()` call computes the pair at most once per `max_age` per bank, and
concurrent subscribers await that one computation.

The filesystem half runs in worker threads under `bank_index.shared_scans()`,
so `episodes/` is listed once per tick. `/sync/version` and `/sleep/status` stay
exact per request and never read this cache; a request's ETag and read may reuse the last walk's listings only
through :func:`reusable_listings`' gate (speed 2026-10-29).

File-change events (2026-10-16 perf, owner decision 2): with the bank's watcher
running (`bank_watch`), a tick walks the bank only when the OS reported a change
since the last walk, or when that walk is `bank_watch.FALLBACK_S` (10 s) old.
Between, a tick answers from the last walk's directory listings (and its two
stamps walked outside `bank_index`), and recomputes everything else — git HEAD,
the files outside the bank, the TTL expiries, the Sleep state, the clock — as
before. An editor's in-place write is an event like any other; one the OS never
reported is seen by the next fallback walk. No watcher: every tick walks.
"""
from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from api.services import bank_index, bank_watch, local_writes, sleep_debt, sync_service
from api.services.sleep_cycle import get_sleep_state


@dataclass(frozen=True)
class Tick:
    info: sync_service.VersionInfo
    debt: sleep_debt.SleepDebt
    at: float
    #: When the bank was last walked (equal to ``at`` for a full tick), the watcher's count read BEFORE that walk began
    #: (``None`` without a watcher), and that walk's listings of the bank's directories.
    walked_at: float = 0.0
    seq: int | None = None
    #: Which watcher ``seq`` was read from (``BankWatch.generation``): a count is comparable only within one watcher.
    watch_gen: int | None = None
    listings: dict | None = field(default=None, repr=False, compare=False)
    #: ``local_writes.current()`` read BEFORE that walk began: this process's own writes since move it.
    local_gen: int | None = None


_ticks: dict[str, Tick] = {}
# Keyed by (event loop, bank): an `asyncio.Lock` belongs to the loop it is first awaited on, and the suite runs
# several loops in one process.
_locks: dict[tuple[int, str], asyncio.Lock] = {}


def reset() -> None:
    """Forget every shared tick and stop the watchers (tests; a bank that was deleted)."""
    _ticks.clear()
    _locks.clear()
    bank_watch.stop_all()


def next_poll_delay(tick: Tick, poll_seconds: float) -> float:
    """How long a stream waits before asking again: until the tick it was handed is ``poll_seconds`` old, so a
    stream that joined mid-interval shares the next computation instead of trailing it by up to ``max_age``."""
    age = time.monotonic() - tick.at
    return min(poll_seconds, max(0.05, poll_seconds - age))


async def current(memory_path: Path, settings, *, max_age: float) -> Tick:
    """The bank's tick, recomputed when older than ``max_age`` seconds."""
    key = str(memory_path)
    loop_key = (id(asyncio.get_running_loop()), key)
    lock = _locks.get(loop_key)
    if lock is None:
        lock = _locks[loop_key] = asyncio.Lock()
    async with lock:
        tick = _ticks.get(key)
        if tick is not None and time.monotonic() - tick.at < max_age:
            return tick
        watch = await asyncio.to_thread(bank_watch.for_bank, memory_path)
        now = time.monotonic()
        if (watch is not None and tick is not None and tick.seq is not None and tick.listings is not None
                and watch.generation == tick.watch_gen and watch.seq == tick.seq
                and local_writes.current() == tick.local_gen   # this process wrote: walk now, never wait for the OS
                and now - tick.walked_at < bank_watch.FALLBACK_S):
            # Nothing in the bank moved since the last walk: its listings answer, everything else is read now.
            reuse = {k: tick.info.components[k] for k in sync_service.WALKED_OUTSIDE_INDEX
                     if k in tick.info.components}
            with bank_index.shared_scans(seed=tick.listings):
                info = await asyncio.to_thread(sync_service.version, memory_path, get_sleep_state(), reuse=reuse)
                debt = await sleep_debt.compute(memory_path, settings)
            tick = Tick(info=info, debt=debt, at=time.monotonic(), walked_at=tick.walked_at, seq=tick.seq,
                        watch_gen=tick.watch_gen, listings=tick.listings, local_gen=tick.local_gen)
        else:
            seq = watch.seq if watch is not None else None   # read BEFORE the walk: a change during it walks again
            gen = watch.generation if watch is not None else None
            local_gen = local_writes.current()
            with bank_index.shared_scans() as memo:
                info = await asyncio.to_thread(sync_service.version, memory_path, get_sleep_state())
                debt = await sleep_debt.compute(memory_path, settings)
            prefix = os.path.join(str(memory_path), "")
            listings = {d: listing for d, listing in (memo or {}).items() if d.startswith(prefix)}
            at = time.monotonic()
            tick = Tick(info=info, debt=debt, at=at, walked_at=at, seq=seq, watch_gen=gen, listings=listings,
                        local_gen=local_gen)
        _ticks[key] = tick
        return tick


def reusable_listings(memory_path: Path) -> dict | None:
    """The last walk's directory listings, for a REQUEST's ETag and read (speed 2026-10-29, item (e)), or ``None``.

    Only while all of these hold: the stream's tick walked this bank under its running watcher; that watcher (the same
    one) has reported no change since before the walk began; this process wrote nothing since then either
    (``local_writes``: every page write, and every request that is not a read — so the person's own answer is never
    served from before it); no Sleep run is under way; and the walk is younger than ``bank_watch.FALLBACK_S``. A
    change another process made reaches the watcher within its debounce; until then a request may see the bank as the
    walk did — the same view the stream itself serves. Without a stream (the app closed) there is no tick: every
    request walks, as before."""
    key = str(memory_path)
    tick = _ticks.get(key)
    if tick is None or tick.listings is None or tick.seq is None or tick.local_gen is None:
        return None
    if time.monotonic() - tick.walked_at >= bank_watch.FALLBACK_S:
        return None
    watch = bank_watch.running(memory_path)
    if watch is None or watch.generation != tick.watch_gen or watch.seq != tick.seq:
        return None
    if local_writes.current() != tick.local_gen:
        return None
    if getattr(get_sleep_state(), "status", "idle") == "running":
        return None
    return tick.listings


def request_scans(memory_path: Path):
    """``bank_index.shared_scans`` for one request: seeded with :func:`reusable_listings` when they may answer, else
    listing each directory once, as every request did."""
    return bank_index.shared_scans(seed=reusable_listings(memory_path))
