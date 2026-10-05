"""Audit 2026-10-02 A10 — the SSE loop's idle cost.

Every connected client used to run `sync_service.version` (a stat walk of the
bank) and `sleep_debt.compute` (another walk of `episodes/`) once a second, the
debt half on the event loop. Now: one computation per bank per tick shared by
every subscriber, the filesystem half in a worker thread, and one `scandir` per
directory per tick. External edits are still found by the same full scan.
Synthetic banks under pytest's tmp only.
"""
from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path

import pytest

from api.services import bank_index, markdown_parser, sleep_debt, sync_service, sync_ticker


def _bank(tmp_path: Path, name: str = "bank", episodes: int = 5) -> Path:
    bank = tmp_path / name
    for sub in ("entities", "episodes", "hubs", "inbox"):
        (bank / sub).mkdir(parents=True)
    for i in range(episodes):
        markdown_parser.write(bank / "episodes" / f"ep_2026-10-05_{i + 1:03d}.md",
                              {"id": f"ep_2026-10-05_{i + 1:03d}", "processed": i % 2 == 0,
                               "timestamp": "2026-10-05T10:00:00+00:00"}, "Synthetic.")
    markdown_parser.write(bank / "entities" / "alpha-project.md", {"name": "Alpha", "type": "project"}, "Body.")
    return bank


@pytest.fixture(autouse=True)
def _fresh():
    sync_ticker.reset()
    bank_index.invalidate()
    yield
    sync_ticker.reset()


def _count_versions(monkeypatch) -> dict:
    calls = {"n": 0}
    real = sync_service.version

    def counting(memory_path, sleep_state=None):
        calls["n"] += 1
        return real(memory_path, sleep_state)

    monkeypatch.setattr(sync_service, "version", counting)
    return calls


def test_concurrent_subscribers_share_one_computation(tmp_path, monkeypatch):
    bank = _bank(tmp_path)
    calls = _count_versions(monkeypatch)

    async def five():
        return await asyncio.gather(*(sync_ticker.current(bank, None, max_age=5.0) for _ in range(5)))

    ticks = asyncio.run(five())
    assert calls["n"] == 1
    assert len({t.info.version for t in ticks}) == 1
    assert all(t is ticks[0] for t in ticks)


def test_a_tick_older_than_max_age_is_recomputed(tmp_path, monkeypatch):
    bank = _bank(tmp_path)
    calls = _count_versions(monkeypatch)

    async def twice():
        await sync_ticker.current(bank, None, max_age=0.05)
        await asyncio.sleep(0.1)
        await sync_ticker.current(bank, None, max_age=0.05)

    asyncio.run(twice())
    assert calls["n"] == 2


def test_two_banks_never_share_a_tick(tmp_path):
    a, b = _bank(tmp_path, "a", episodes=2), _bank(tmp_path, "b", episodes=3)

    async def both():
        return await sync_ticker.current(a, None, max_age=5.0), await sync_ticker.current(b, None, max_age=5.0)

    ta, tb = asyncio.run(both())
    assert ta is not tb
    assert ta.info.components["episodes"] != tb.info.components["episodes"]


def test_an_external_in_place_edit_is_seen_on_the_next_tick(tmp_path):
    bank = _bank(tmp_path)
    page = bank / "entities" / "alpha-project.md"

    async def edit_between_ticks():
        first = await sync_ticker.current(bank, None, max_age=0.0)
        # An editor rewriting the file in place (no rename): only the file's own mtime moves.
        with page.open("r+", encoding="utf-8") as fh:
            text = fh.read()
            fh.seek(0)
            fh.write(text.replace("Body.", "Edited elsewhere."))
            fh.truncate()
        later = time.time() + 5
        import os
        os.utime(page, (later, later))
        second = await sync_ticker.current(bank, None, max_age=0.0)
        return first, second

    first, second = asyncio.run(edit_between_ticks())
    assert first.info.version != second.info.version


def test_the_debt_scan_runs_off_the_event_loop_thread(tmp_path, monkeypatch):
    bank = _bank(tmp_path)
    seen: list[int] = []
    real = bank_index.files

    def recording(memory_path, subdir):
        seen.append(threading.get_ident())
        return real(memory_path, subdir)

    monkeypatch.setattr(bank_index, "files", recording)

    async def go():
        loop_thread = threading.get_ident()
        await sleep_debt.compute(bank)
        return loop_thread

    loop_thread = asyncio.run(go())
    assert seen and all(t != loop_thread for t in seen)


def test_one_scandir_of_episodes_per_tick(tmp_path, monkeypatch):
    bank = _bank(tmp_path)
    scans: list[str] = []
    real = bank_index._scan_uncached

    def counting(directory):
        scans.append(Path(directory).name)
        return real(directory)

    monkeypatch.setattr(bank_index, "_scan_uncached", counting)
    asyncio.run(sync_ticker.current(bank, None, max_age=0.0))
    assert scans.count("episodes") == 1


def test_the_shared_tick_equals_the_unshared_computation(tmp_path):
    bank = _bank(tmp_path)

    async def both():
        tick = await sync_ticker.current(bank, None, max_age=0.0)
        info = sync_service.version(bank, None)
        debt = await sleep_debt.compute(bank)
        return tick, info, debt

    tick, info, debt = asyncio.run(both())
    assert tick.info == info
    assert (tick.debt.unprocessed_count, tick.debt.rested_pct, tick.debt.parked_count) == \
        (debt.unprocessed_count, debt.rested_pct, debt.parked_count)


def test_the_sse_loop_uses_the_shared_tick(tmp_path, monkeypatch):
    from api.routers import sync as sync_router
    from api.config import Settings

    bank = _bank(tmp_path)
    calls = _count_versions(monkeypatch)
    settings = Settings(CICADA_MEMORY_PATH=str(bank))

    async def two_clients():
        r1 = await sync_router.events(settings=settings)
        r2 = await sync_router.events(settings=settings)
        g1, g2 = r1.body_iterator, r2.body_iterator
        first = await asyncio.gather(g1.__anext__(), g2.__anext__())
        await g1.aclose()
        await g2.aclose()
        return first

    first = asyncio.run(two_clients())
    assert all(e.startswith("event: version") for e in first)
    assert calls["n"] == 1, "two subscribers, one computation"
