"""One idle tick per bank, shared by every SSE subscriber (audit 2026-10-02 A10).

`GET /sync/events` used to run `sync_service.version` (a stat walk of the bank)
and `sleep_debt.compute` (another walk of `episodes/`) once a second in EVERY
connected stream, the debt half on the event loop: N clients, N walks. Here one
`current()` call computes the pair at most once per `max_age` per bank, and
concurrent subscribers await that one computation.

The filesystem half runs in worker threads under `bank_index.shared_scans()`,
so `episodes/` is listed once per tick. Nothing is skipped: every tick is the
same full scan, so an external edit (an editor writing a page in place) is seen
on the next tick exactly as before. `/sync/version` and `/sleep/status` stay
exact per request and never read this cache.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path

from api.services import bank_index, sleep_debt, sync_service
from api.services.sleep_cycle import get_sleep_state


@dataclass(frozen=True)
class Tick:
    info: sync_service.VersionInfo
    debt: sleep_debt.SleepDebt
    at: float


_ticks: dict[str, Tick] = {}
# Keyed by (event loop, bank): an `asyncio.Lock` belongs to the loop it is first awaited on, and the suite runs
# several loops in one process.
_locks: dict[tuple[int, str], asyncio.Lock] = {}


def reset() -> None:
    """Forget every shared tick (tests; a bank that was deleted)."""
    _ticks.clear()
    _locks.clear()


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
        with bank_index.shared_scans():
            info = await asyncio.to_thread(sync_service.version, memory_path, get_sleep_state())
            debt = await sleep_debt.compute(memory_path, settings)
        tick = Tick(info=info, debt=debt, at=time.monotonic())
        _ticks[key] = tick
        return tick
