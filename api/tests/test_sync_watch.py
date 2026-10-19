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
import threading
import time
from pathlib import Path
from types import SimpleNamespace

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


#: How long a test waits for the OS to deliver a marker — a bound on the OS, not the property under test: FSEvents
#: took up to ~2.9 s to report a write with five watchers running and up to ~10 s with five suites beside each other
#: (measured 2026-10-18). Whether a change was *reported* is read from the watcher's count, never from the fallback walk.
EVENT_WAIT_S = 30.0


def _settle(watch: bank_watch.BankWatch, *, within: float = EVENT_WAIT_S) -> bool:
    """Return once the OS has reported every change made before this call, and the watcher has counted it.

    FSEvents also reports writes made just BEFORE a stream started (a test's own setup), late and in no fixed time —
    0.4-1.9 s after the watcher started on a loaded machine, more under contention. A fixed sleep before reading
    ``seq`` is a timing guess that loses under load (the 2026-10-18 flake: the setup's own episode writes bumped
    ``seq`` after a 0.6 s sleep), and so is a fixed wait for a change to be reported. Events arrive in the order they
    happened, so once a marker written now is reported, nothing older is still on its way. The marker is an
    index-database name at the bank's root, which the watcher never counts; every other path meets the real filter.
    Returns whether the marker was reported."""
    marker = os.path.join(str(watch.bank), f"vector_index.db.settle-{time.monotonic_ns()}")
    real = watch._counts
    seen = threading.Event()

    def look(path: str) -> bool:
        if path == marker:
            seen.set()
        return real(path)

    watch._counts = look
    try:
        Path(marker).write_bytes(b"")
        reported = seen.wait(within)
        time.sleep(0.1)   # the batch the marker came in is counted just after its last path is looked at
    finally:
        del watch._counts
    return reported


def test_between_events_a_tick_reads_no_bank_directory_and_answers_the_same(tmp_path, walks):
    bank = _bank(tmp_path)

    async def go():
        await sync_ticker.current(bank, None, max_age=0.0)
        assert await asyncio.to_thread(_settle, bank_watch.for_bank(bank))   # the setup's own writes reported
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
        watch = bank_watch.for_bank(bank)
        assert await asyncio.to_thread(_settle, watch)
        await sync_ticker.current(bank, None, max_age=0.0)
        seq = watch.seq
        _edit_in_place(page, "Body.", "Edited elsewhere.")
        assert await asyncio.to_thread(_settle, watch), "the OS reported the edit"
        after = (await sync_ticker.current(bank, None, max_age=0.0)).info.version
        return seq, watch.seq, before, after

    seq_before, seq_after, before, after = asyncio.run(go())
    assert seq_after > seq_before, "the edit was reported as an event, not found by the fallback walk"
    assert after != before


def test_a_new_episode_moves_the_debt_once_reported(tmp_path):
    bank = _bank(tmp_path)

    async def go():
        first = await sync_ticker.current(bank, None, max_age=0.0)
        watch = bank_watch.for_bank(bank)
        assert await asyncio.to_thread(_settle, watch)
        await sync_ticker.current(bank, None, max_age=0.0)
        seq = watch.seq
        markdown_parser.write(bank / "episodes" / "ep_2026-10-06_001.md",
                              {"id": "ep_2026-10-06_001", "processed": False,
                               "timestamp": "2026-10-06T10:00:00+00:00"}, "Synthetic.")
        assert await asyncio.to_thread(_settle, watch), "the OS reported the new episode"
        return first, await sync_ticker.current(bank, None, max_age=0.0), seq, watch.seq

    first, second, seq_before, seq_after = asyncio.run(go())
    assert seq_after > seq_before
    assert (first.debt.unprocessed_count, second.debt.unprocessed_count) == (2, 3)


def test_a_change_the_os_never_reported_is_seen_by_the_fallback_walk(tmp_path, monkeypatch):
    bank = _bank(tmp_path)
    page = bank / "entities" / "alpha-project.md"
    monkeypatch.setattr(bank_watch.BankWatch, "bump", lambda self: None)   # every event lost
    # The ticker's own clock, so "the last walk is young" and "the walk is FALLBACK_S old" are facts of the test, not
    # of how busy the machine is (a real 0.3 s sleep against a 0.6 s fallback lost under five suites at once).
    clock = [1_000.0]
    monkeypatch.setattr(sync_ticker, "time", SimpleNamespace(monotonic=lambda: clock[0]))

    async def go():
        before = (await sync_ticker.current(bank, None, max_age=0.0)).info.version
        _edit_in_place(page, "Body.", "Lost event.")
        clock[0] += bank_watch.FALLBACK_S / 2
        mid = (await sync_ticker.current(bank, None, max_age=0.0)).info.version
        clock[0] += bank_watch.FALLBACK_S
        after = (await sync_ticker.current(bank, None, max_age=0.0)).info.version
        return before, mid, after

    before, mid, after = asyncio.run(go())
    assert mid == before, "no event and the last walk is young: answered from it"
    assert after != before, "the walk is FALLBACK_S old: the bank is walked again"


def test_what_lives_outside_the_bank_directories_is_read_every_tick(tmp_path):
    bank = _bank(tmp_path)
    (bank / ".git" / "refs" / "heads").mkdir(parents=True)
    (bank / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (bank / ".git" / "refs" / "heads" / "main").write_text("a" * 40 + "\n")

    async def go():
        first = await sync_ticker.current(bank, None, max_age=0.0)
        watch = bank_watch.for_bank(bank)
        assert await asyncio.to_thread(_settle, watch)   # past the notifier's report of the setup above
        await sync_ticker.current(bank, None, max_age=0.0)
        seq = watch.seq
        (bank / ".git" / "refs" / "heads" / "main").write_text("b" * 40 + "\n")   # a commit: git's own files
        second = await sync_ticker.current(bank, None, max_age=0.0)
        reported = await asyncio.to_thread(_settle, watch)
        return first, second, seq, watch.seq, reported

    first, second, seq_before, seq_after, reported = asyncio.run(go())
    assert first.info.components["git_head"] == "a" * 40
    assert second.info.components["git_head"] == "b" * 40
    assert seq_after == seq_before, "git's bookkeeping is not a change to walk for"
    assert reported, "the OS reported the commit before the count was read"


def test_the_index_databases_at_the_root_do_not_count(tmp_path):
    bank = _bank(tmp_path)
    watch = bank_watch.for_bank(bank)
    assert _settle(watch)   # past the notifier's report of the setup above
    seq = watch.seq
    (bank / "vector_index.db").write_bytes(b"x")
    (bank / "search_index.db-wal").write_bytes(b"x")
    reported = _settle(watch)
    assert watch.seq == seq
    assert reported, "the OS reported the index writes before the count was read"
    (bank / "inbox" / "inbox-0001.md").write_text("---\nstatus: pending\n---\n")
    assert _settle(watch), "the OS reported the inbox write"
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


def test_a_new_watcher_never_vouches_for_the_old_watchers_listings(tmp_path, walks):
    """A restarted notifier (or a bank directory made again) starts counting from zero: equal counts across two
    watchers say nothing, so the first tick on the new watcher walks."""
    bank = _bank(tmp_path)

    async def go():
        first = await sync_ticker.current(bank, None, max_age=0.0)
        old = bank_watch.for_bank(bank)
        old.stop()                                   # the notifier died; the next ask starts another
        new = bank_watch.for_bank(bank)
        assert new is not None and new is not old
        new.seq = first.seq                          # the same count, from another watcher
        walks.clear()
        return first, await sync_ticker.current(bank, None, max_age=0.0), new

    first, second, new = asyncio.run(go())
    assert "episodes" in walks, "the new watcher's first tick walked the bank"
    assert second.walked_at > first.walked_at and second.watch_gen == new.generation != first.watch_gen


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
