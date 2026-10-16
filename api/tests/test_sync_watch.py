"""The SSE tick walks the bank only on a file-change event or every 10 s (2026-10-16 perf, owner decision 2).

Measured on the owner-scale synthetic bank (`benchmarks.scale.idle_tick`, ~8,800 files): 33 ms of CPU every second
with the app open, a full stat walk per tick. With the bank's watcher (`bank_watch`: FSEvents / inotify through
`watchfiles`) a tick between events answers from the last walk's listings. These tests pin what must still hold: an
outside editor's in-place write is seen, a change the OS never reported is seen by the fallback walk, what lives
outside the bank is read every tick, and without a working notifier every tick walks as before.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import time
from pathlib import Path

import pytest

from api.services import bank_index, bank_watch, markdown_parser, sync_ticker


def _bank(tmp_path: Path, name: str = "bank") -> Path:
    bank = tmp_path / name
    for sub in ("entities", "episodes", "hubs", "inbox"):
        (bank / sub).mkdir(parents=True)
    for i in range(4):
        markdown_parser.write(bank / "episodes" / f"ep_2026-10-05_{i + 1:03d}.md",
                              {"id": f"ep_2026-10-05_{i + 1:03d}", "processed": i % 2 == 0,
                               "timestamp": "2026-10-05T10:00:00+00:00"}, "Synthetic.")
    markdown_parser.write(bank / "entities" / "alpha-project.md", {"name": "Alpha", "type": "project"}, "Body.")
    return bank.resolve()


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.delenv("CICADA_SYNC_WATCH", raising=False)
    sync_ticker.reset()
    bank_index.invalidate()
    yield
    sync_ticker.reset()


@pytest.fixture
def walks(monkeypatch):
    """Directory listings actually read from disk, by directory name."""
    seen: list[str] = []
    real = bank_index._scan_uncached

    def counting(directory):
        seen.append(Path(directory).name)
        return real(directory)

    monkeypatch.setattr(bank_index, "_scan_uncached", counting)
    return seen


def _edit_in_place(page: Path, old: str, new: str) -> None:
    with page.open("r+", encoding="utf-8") as fh:   # an editor's write: same inode, no rename
        text = fh.read()
        fh.seek(0)
        fh.write(text.replace(old, new))
        fh.truncate()


async def _until_version_moves(bank: Path, before: str, *, within: float) -> float | None:
    started = time.monotonic()
    while time.monotonic() - started < within:
        tick = await sync_ticker.current(bank, None, max_age=0.0)
        if tick.info.version != before:
            return time.monotonic() - started
        await asyncio.sleep(0.05)
    return None


def test_between_events_a_tick_reads_no_bank_directory_and_answers_the_same(tmp_path, walks):
    bank = _bank(tmp_path)

    async def go():
        first = await sync_ticker.current(bank, None, max_age=0.0)
        walks.clear()
        later = [await sync_ticker.current(bank, None, max_age=0.0) for _ in range(5)]
        return first, later

    first, later = asyncio.run(go())
    assert bank_watch.for_bank(bank) is not None, "the notifier runs on this machine"
    assert not {"entities", "episodes", "hubs", "inbox"} & set(walks)
    assert all(t.info == first.info for t in later)
    assert all(t.debt.unprocessed_count == first.debt.unprocessed_count == 2 for t in later)
    assert all(t.walked_at == first.walked_at for t in later)


def test_an_outside_editors_in_place_write_is_seen_once_the_os_reports_it(tmp_path):
    bank = _bank(tmp_path)
    page = bank / "entities" / "alpha-project.md"

    async def go():
        before = (await sync_ticker.current(bank, None, max_age=0.0)).info.version
        await sync_ticker.current(bank, None, max_age=0.0)
        _edit_in_place(page, "Body.", "Edited elsewhere.")
        return await _until_version_moves(bank, before, within=5.0)

    assert asyncio.run(go()) is not None


def test_a_new_episode_moves_the_debt_once_reported(tmp_path):
    bank = _bank(tmp_path)

    async def go():
        first = await sync_ticker.current(bank, None, max_age=0.0)
        markdown_parser.write(bank / "episodes" / "ep_2026-10-06_001.md",
                              {"id": "ep_2026-10-06_001", "processed": False,
                               "timestamp": "2026-10-06T10:00:00+00:00"}, "Synthetic.")
        await _until_version_moves(bank, first.info.version, within=5.0)
        return first, await sync_ticker.current(bank, None, max_age=0.0)

    first, second = asyncio.run(go())
    assert (first.debt.unprocessed_count, second.debt.unprocessed_count) == (2, 3)


def test_a_change_the_os_never_reported_is_seen_by_the_fallback_walk(tmp_path, monkeypatch):
    bank = _bank(tmp_path)
    page = bank / "entities" / "alpha-project.md"
    monkeypatch.setattr(bank_watch.BankWatch, "bump", lambda self: None)   # every event lost
    monkeypatch.setattr(bank_watch, "FALLBACK_S", 0.6)

    async def go():
        before = (await sync_ticker.current(bank, None, max_age=0.0)).info.version
        _edit_in_place(page, "Body.", "Lost event.")
        await asyncio.sleep(0.3)
        mid = (await sync_ticker.current(bank, None, max_age=0.0)).info.version
        took = await _until_version_moves(bank, before, within=3.0)
        return before, mid, took

    before, mid, took = asyncio.run(go())
    assert mid == before, "no event and the last walk is young: answered from it"
    assert took is not None and took < 1.5


def test_what_lives_outside_the_bank_directories_is_read_every_tick(tmp_path):
    bank = _bank(tmp_path)
    (bank / ".git" / "refs" / "heads").mkdir(parents=True)
    (bank / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (bank / ".git" / "refs" / "heads" / "main").write_text("a" * 40 + "\n")

    async def go():
        first = await sync_ticker.current(bank, None, max_age=0.0)
        seq = bank_watch.for_bank(bank).seq
        await asyncio.sleep(0.6)   # past the notifier's report of the setup above
        seq = bank_watch.for_bank(bank).seq
        await sync_ticker.current(bank, None, max_age=0.0)
        (bank / ".git" / "refs" / "heads" / "main").write_text("b" * 40 + "\n")   # a commit: git's own files
        second = await sync_ticker.current(bank, None, max_age=0.0)
        await asyncio.sleep(0.6)
        return first, second, seq, bank_watch.for_bank(bank).seq

    first, second, seq_before, seq_after = asyncio.run(go())
    assert first.info.components["git_head"] == "a" * 40
    assert second.info.components["git_head"] == "b" * 40
    assert seq_after == seq_before, "git's bookkeeping is not a change to walk for"


def test_the_index_databases_at_the_root_do_not_count(tmp_path):
    bank = _bank(tmp_path)
    watch = bank_watch.for_bank(bank)
    time.sleep(0.6)
    seq = watch.seq
    (bank / "vector_index.db").write_bytes(b"x")
    (bank / "search_index.db-wal").write_bytes(b"x")
    time.sleep(0.8)
    assert watch.seq == seq
    (bank / "inbox" / "inbox-0001.md").write_text("---\nstatus: pending\n---\n")
    deadline = time.monotonic() + 5
    while watch.seq == seq and time.monotonic() < deadline:
        time.sleep(0.05)
    assert watch.seq > seq


def test_without_a_notifier_every_tick_walks(tmp_path, monkeypatch, walks):
    bank = _bank(tmp_path)
    import watchfiles._rust_notify as rust

    def broken(*args, **kwargs):
        raise OSError("no notifier here")

    monkeypatch.setattr(rust, "RustNotify", broken)

    async def go():
        for _ in range(3):
            await sync_ticker.current(bank, None, max_age=0.0)

    asyncio.run(go())
    assert bank_watch.for_bank(bank) is None
    assert walks.count("episodes") == 3


def test_turned_off_every_tick_walks(tmp_path, monkeypatch, walks):
    monkeypatch.setenv("CICADA_SYNC_WATCH", "off")
    bank = _bank(tmp_path)

    async def go():
        for _ in range(3):
            await sync_ticker.current(bank, None, max_age=0.0)

    asyncio.run(go())
    assert bank_watch.for_bank(bank) is None
    assert walks.count("episodes") == 3


def test_a_bank_deleted_and_made_again_gets_a_new_watcher(tmp_path):
    bank = _bank(tmp_path)
    first = bank_watch.for_bank(bank)
    shutil.rmtree(bank)
    _bank(tmp_path)
    second = bank_watch.for_bank(bank)
    assert second is not None and second is not first
    assert not first.healthy


def test_a_watcher_nobody_asks_about_is_stopped(tmp_path, monkeypatch):
    a, b = _bank(tmp_path, "a"), _bank(tmp_path, "b")
    wa = bank_watch.for_bank(a)
    monkeypatch.setattr(bank_watch, "IDLE_S", 0.0)
    time.sleep(0.01)
    bank_watch.for_bank(b)
    deadline = time.monotonic() + 5
    while wa._thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not wa.healthy and not wa._thread.is_alive()


def test_stop_all_leaves_no_watcher_thread(tmp_path):
    bank = _bank(tmp_path)
    w = bank_watch.for_bank(bank)
    bank_watch.stop_all()
    w._thread.join(5)
    assert not w._thread.is_alive()
    assert os.path.isdir(bank)
