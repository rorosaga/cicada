"""G183 — one write admission per bank, shared by guarded writers and exclusive for Sleep's flip.

A guarded writer holds admission across its `is_writing()` check, its page writes and its commit; Sleep sets its flag
first and then waits for every holder to finish before it reads a page. The barriers here are events, not sleeps —
the only timed waits are the bound's own (a small `give_up_after`).
"""
from __future__ import annotations

import logging
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

from api.services import sleep_cycle, write_admission


@pytest.fixture
def bank(tmp_path) -> Path:
    b = tmp_path / "bank"
    (b / "entities").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(b)], check=True)
    return b


@pytest.fixture
def window(monkeypatch):
    """Sleep's flag, as `is_writing` reads it."""
    state = {"writing": False}
    monkeypatch.setattr(sleep_cycle, "is_writing", lambda: state["writing"])
    return state


def _flip(bank, window, **kw) -> bool:
    """Sleep's order: the flag first, then the wait."""
    window["writing"] = True
    return write_admission.wait_for_writers(bank, **kw)


def test_a_writer_admitted_before_the_flip_finishes_before_sleep_proceeds(bank, window):
    admitted, release, flipped = threading.Event(), threading.Event(), threading.Event()
    order: list[str] = []

    def writer():
        with write_admission.admitted(bank):
            admitted.set()
            release.wait(5)
            (bank / "entities" / "a.md").write_text("written\n")
            order.append("write")

    def sleep():
        _flip(bank, window)
        order.append("sleep reads")
        flipped.set()

    w = threading.Thread(target=writer)
    w.start()
    assert admitted.wait(5)
    s = threading.Thread(target=sleep)
    s.start()
    assert not flipped.wait(0.2), "Sleep must not read while an admitted writer is mid-write"
    release.set()
    w.join(5)
    s.join(5)
    assert order == ["write", "sleep reads"]
    assert (bank / "entities" / "a.md").read_text() == "written\n"


def test_a_writer_arriving_after_the_flip_is_refused_and_writes_nothing(bank, window):
    assert _flip(bank, window) is True
    with pytest.raises(write_admission.SleepHolding):
        with write_admission.admitted(bank):
            (bank / "entities" / "a.md").write_text("never\n")
    assert not (bank / "entities" / "a.md").exists()


def test_the_refusal_is_the_callers_own(bank, window):
    window["writing"] = True

    class Busy(Exception):
        pass

    with pytest.raises(Busy):
        with write_admission.admitted(bank, refuse=lambda: Busy("try again")):
            pass
    assert write_admission.holders(bank) == 0, "a refused writer releases its hold"


def test_shared_admission_is_reentrant_and_counted(bank, window):
    with write_admission.admitted(bank):
        with write_admission.admitted(bank):
            assert write_admission.holders(bank) == 2
        assert write_admission.holders(bank) == 1
    assert write_admission.holders(bank) == 0


def test_a_hold_is_not_owned_by_a_thread(bank, window):
    """An async route may hold admission across its own awaits; the hold is counted, never thread-owned, so a
    worker thread under it can take it again and Sleep still waits for the outer hold."""
    with write_admission.admitted(bank):
        inner = []
        t = threading.Thread(target=lambda: inner.append(write_admission.holders(bank)))
        t.start()
        t.join(5)
        assert inner == [1]


def test_the_flip_waits_and_logs_past_the_threshold(bank, window, caplog):
    held, release = threading.Event(), threading.Event()

    def writer():
        with write_admission.shared(bank):
            held.set()
            release.wait(5)

    w = threading.Thread(target=writer)
    w.start()
    assert held.wait(5)
    timer = threading.Timer(0.3, release.set)
    timer.start()
    with caplog.at_level(logging.INFO, logger="api.services.write_admission"):
        assert _flip(bank, window, log_after=0.05, give_up_after=10) is True
    w.join(5)
    assert any("waiting for 1 write" in r.getMessage() for r in caplog.records)


def test_a_stuck_writer_is_never_reported_as_a_free_bank(bank, window, caplog):
    """Bounded and honest (fix round 1, finding 1): past `give_up_after` the wait answers False and says Sleep will
    not read — the caller pauses; nothing treats a timed-out wait as an open window."""
    held, release = threading.Event(), threading.Event()

    def writer():
        with write_admission.shared(bank):
            held.set()
            release.wait(5)

    w = threading.Thread(target=writer)
    w.start()
    assert held.wait(5)
    try:
        with caplog.at_level(logging.WARNING, logger="api.services.write_admission"):
            t0 = time.monotonic()
            assert _flip(bank, window, log_after=0.05, give_up_after=0.2) is False
            assert time.monotonic() - t0 < 2
        assert any("will not read" in r.getMessage() for r in caplog.records)
    finally:
        release.set()
        w.join(5)


def test_no_holder_means_no_wait(bank, window):
    t0 = time.monotonic()
    assert _flip(bank, window) is True
    assert time.monotonic() - t0 < 0.5


def test_a_bank_without_git_or_that_does_not_exist_is_still_counted(tmp_path, window):
    plain = tmp_path / "plain"
    plain.mkdir()
    with write_admission.admitted(plain):
        assert write_admission.holders(plain) == 1
    assert write_admission.wait_for_writers(tmp_path / "missing") is True
    assert not (tmp_path / "missing").exists(), "a lock never creates a bank"


def test_one_bank_by_its_resolved_path(bank, window, tmp_path):
    link = tmp_path / "link"
    link.symlink_to(bank)
    with write_admission.shared(link):
        assert write_admission.holders(bank) == 1


_HOLDER = textwrap.dedent("""
    import sys, time
    sys.path.insert(0, sys.argv[2])
    from api.services import write_admission
    with write_admission.shared(sys.argv[1]):
        print("held", flush=True)
        sys.stdin.readline()
""")


def test_a_writer_in_another_process_delays_the_flip(bank, window):
    """The stdio MCP server is another process: its admission is the `flock` on the bank's `.git`."""
    root = str(Path(__file__).resolve().parents[2])
    proc = subprocess.Popen([sys.executable, "-c", _HOLDER, str(bank), root],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert proc.stdout.readline().strip() == "held"
        assert _flip(bank, window, log_after=10, give_up_after=0.2) is False, "the other process's hold is seen"
        done = threading.Event()
        result: list[bool] = []

        def sleep():
            result.append(write_admission.wait_for_writers(bank, give_up_after=10))
            done.set()

        s = threading.Thread(target=sleep)
        s.start()
        assert not done.wait(0.2)
        proc.stdin.write("go\n")
        proc.stdin.flush()
        assert done.wait(5)
        assert result == [True]
    finally:
        proc.kill()
        proc.wait(5)


# --- Fix round 1, finding 5: a bank with no .git still coordinates across processes; an unusable lock fails closed --


def test_a_writer_in_another_process_delays_the_flip_on_a_bank_without_git(tmp_path, window):
    plain = tmp_path / "plain"
    (plain / "entities").mkdir(parents=True)
    root = str(Path(__file__).resolve().parents[2])
    proc = subprocess.Popen([sys.executable, "-c", _HOLDER, str(plain), root],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert proc.stdout.readline().strip() == "held"
        assert _flip(plain, window, log_after=10, give_up_after=0.2) is False, "the other process's hold is seen"
        assert not list(plain.rglob("*.lock")), "nothing is created inside the bank"
    finally:
        proc.kill()
        proc.wait(5)


def test_a_lock_that_cannot_be_opened_fails_closed(bank, window):
    (bank / ".git").chmod(0)
    try:
        with pytest.raises(write_admission.AdmissionUnavailable):
            with write_admission.admitted(bank):
                pass
        assert write_admission.holders(bank) == 0
        assert write_admission.wait_for_writers(bank, give_up_after=0.2) is False, "Sleep cannot confirm: no window"
    finally:
        (bank / ".git").chmod(0o755)
