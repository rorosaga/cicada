"""The queue of captures a second machine keeps for the home, held to three rules (review of the B3 change):

1. a queued session follows its BANK, not the address it was captured for (the home moved, or this computer became
   the home) — and never lands in a memory it was not captured for;
2. marking an entry (accepted, held) or removing it never overwrites a newer snapshot of the session that landed while
   the post was in flight, nor brings back one that was dropped;
3. the same for the single-machine path (``capture._flush_local``).

Unit-level, fake senders, synthetic names; nothing leaves the process."""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import pytest

from api.hooks import capture
from api.services import home_move, replica

spool = capture.spool            # the module the hooks and the follower share (``hook_client.spool_module``)

OLD, NEW = "https://old-home.example", "https://new-home.example"


def _session_body(sid: str, text: str = "v1") -> dict:
    return {"harness": "claude-code", "session_id": sid, "conversation": {"kept": [text]}, "transcript_bytes": 1,
            "transcript_size": 1}


def _put(home: Path, sid: str, *, base: str = OLD, bank: str | None = "bank-1", text: str = "v1",
         route: str = "/capture/session", accepted: bool = False) -> Path:
    spool.put(home, route, _session_body(sid, text), key=f"claude-code:{sid}",
              target={"base": base, "bank_id": bank}, accepted=accepted)
    return next(p for p in spool.entries(home) if (spool._read(p) or {}).get("key") == f"claude-code:{sid}"
                and (spool._read(p) or {}).get("target", {}).get("base") == base)


def _sid(entry_path: Path) -> str:
    return spool._read(entry_path)["body"]["session_id"]


def _left(home: Path) -> set[str]:
    return {_sid(p) for p in spool.entries(home)}


# --- finding 1: a session follows its bank --------------------------------------------------------------------------

def test_a_copy_sends_a_session_kept_for_its_bank_after_the_home_moved(tmp_path, monkeypatch):
    home = tmp_path / "cicada"
    monkeypatch.setenv("CICADA_HOME", str(home))
    monkeypatch.setenv("CICADA_REPLICA_OF", NEW)                    # the copy was re-pointed: the old address is gone
    monkeypatch.setattr(replica._STATE, "bank_id", "bank-1")        # the bank this copy follows
    _put(home, "moved", base=OLD, bank="bank-1")                    # captured for the old home, same memory
    _put(home, "other-bank", base=OLD, bank="bank-2")               # another memory behind the old address
    _put(home, "no-bank", base=OLD, bank=None)                      # never heard which memory: waits for its server
    _put(home, "here", base=NEW, bank=None)                         # the current home's own: as before
    sent: list = []

    def request(method, path, *, body=None, **_kw):
        sent.append(json.loads(body))
        return 200, {}, {"status": "created", "bankId": "bank-1"}

    monkeypatch.setattr(replica, "request", request)
    replica._flush_hook_spool()
    assert sorted(b["session_id"] for b in sent) == ["here", "moved"]
    assert next(b for b in sent if b["session_id"] == "moved")["bank_id"] == "bank-1"   # the home checks the bank
    assert _left(home) == {"other-bank", "no-bank"}


def _become_home(tmp_path, monkeypatch, bank_id: str = "bank-1"):
    home = tmp_path / "cicada"
    home.mkdir(exist_ok=True)
    (home / "device_token").write_text("cic_dev_synthetic\n")
    monkeypatch.setenv("CICADA_HOME", str(home))
    monkeypatch.setattr(home_move, "_settings", lambda: type("S", (), {"memory_root": str(tmp_path / "memory")})())
    from api.services import bank_registry

    monkeypatch.setattr(bank_registry, "_active_record", lambda _root: ("main", tmp_path / "memory", bank_id))
    return home


def test_a_computer_that_became_the_home_drains_its_queued_sessions_into_its_own_bank_once(tmp_path, monkeypatch):
    home = _become_home(tmp_path, monkeypatch)
    _put(home, "queued", base=OLD, bank="bank-1")
    _put(home, "turn", base=OLD, bank="bank-1", route="/capture/turn")
    _put(home, "other-bank", base=OLD, bank="bank-2")               # never filed in a memory it was not captured for
    _put(home, "no-bank", base=OLD, bank=None)
    assert not (home / "spool" / "tx").exists()                     # no transaction outbox at all
    calls: list = []

    def request(method, path, *, body=None, environ=None, **_kw):
        calls.append((path, json.loads(body)["session_id"], dict(environ or {})))
        return 200, {}, {"status": "created", "bankId": "bank-1"}

    monkeypatch.setattr(replica, "request", request)
    home_move.drain_own_spool()
    assert sorted((p, s) for p, s, _e in calls) == [("/capture/session", "queued"), ("/capture/turn", "turn")]
    assert all(e["CICADA_REPLICA_OF"].startswith("http://127.0.0.1:") for _p, _s, e in calls)   # its own backend
    assert _left(home) == {"other-bank", "no-bank"}
    calls.clear()
    home_move.drain_own_spool()                                     # a second drain sends nothing: exactly once
    assert calls == []


def test_a_home_with_no_device_token_of_its_own_keeps_the_queue(tmp_path, monkeypatch):
    home = _become_home(tmp_path, monkeypatch)
    (home / "device_token").unlink()
    _put(home, "queued", base=OLD, bank="bank-1")
    monkeypatch.setattr(replica, "request", lambda *a, **k: pytest.fail("nothing is sent without a token"))
    home_move.drain_own_spool()
    assert _left(home) == {"queued"}


def test_the_home_starts_the_drain_when_only_the_capture_spool_holds_something(tmp_path, monkeypatch):
    home = _become_home(tmp_path, monkeypatch)
    from api.services import admitted_log, sync_publish

    monkeypatch.setattr(sync_publish, "publishable", lambda _p: True)
    monkeypatch.setattr(home_move, "start_peer_watch", lambda _p: None)
    monkeypatch.setattr(home_move, "resume_after_start", lambda _p: None)
    monkeypatch.setattr(admitted_log, "prune", lambda _p: None)
    started: list = []

    class FakeThread:
        def __init__(self, target=None, **_kw):
            started.append(target)

        def start(self):
            pass

    monkeypatch.setattr(home_move.threading, "Thread", FakeThread)
    home_move.at_start(tmp_path / "memory")
    assert started == []                                            # nothing queued: nothing started
    _put(home, "queued", base=OLD, bank="bank-1")
    home_move.at_start(tmp_path / "memory")
    assert started == [home_move._flush_own_outbox]


# --- finding 2: marking never overwrites a newer snapshot ---------------------------------------------------------------

def _bank_mismatch():
    return 409, json.dumps({"code": "bank_mismatch"})


def _flush(home: Path, send):
    return spool.flush(home, send, deadline=time.monotonic() + 20.0, keep=lambda s: s is None or s >= 500,
                       size_of=lambda _p, n: n, base=OLD)


@pytest.mark.parametrize("answer, mark", [((202, ""), "accepted_at"), (None, "held_at")])
def test_a_newer_snapshot_landing_between_the_send_and_the_mark_survives(tmp_path, monkeypatch, answer, mark):
    """The window is the rename itself: the mark re-checks the file under the spool's lock and a ``put`` of a newer
    snapshot waits for that lock, so it lands AFTER the mark, never under it."""
    home = tmp_path / "cicada"
    path = _put(home, "s1", text="old")
    answer = answer or _bank_mismatch()
    real_replace = os.replace
    armed = {"on": True}
    racer: list = []

    def replace(src, dst, *a, **k):
        if armed["on"] and Path(dst) == path and threading.current_thread() is threading.main_thread():
            armed["on"] = False                                     # the newer snapshot arrives as the mark renames
            t = threading.Thread(target=lambda: spool.put(home, "/capture/session", _session_body("s1", "new"),
                                                          key="claude-code:s1", target={"base": OLD, "bank_id": "bank-1"}))
            t.start()
            racer.append(t)
            time.sleep(0.15)                                        # a lock-free put would have landed by now
        return real_replace(src, dst, *a, **k)

    monkeypatch.setattr(os, "replace", replace)
    _flush(home, lambda route, body: answer)
    for t in racer:
        t.join(10)
    entry = spool._read(path)
    assert entry["body"]["conversation"] == {"kept": ["new"]}, "the stale entry overwrote the newer snapshot"
    assert mark not in entry                                        # the newer snapshot was never sent


def test_a_newer_snapshot_put_during_the_send_is_kept_and_a_dropped_entry_stays_dropped(tmp_path):
    home = tmp_path / "cicada"
    path = _put(home, "s1", text="old")

    def newer(route, body):
        _put(home, "s1", text="new")
        return 202, ""

    _flush(home, newer)
    assert spool._read(path)["body"]["conversation"] == {"kept": ["new"]} and "accepted_at" not in spool._read(path)
    for answer in ((202, ""), (200, "{}")):
        def dropped(route, body, answer=answer):
            spool.drop(home, "claude-code:s1", OLD, ("bank-1",))
            return answer

        _put(home, "s1", text="again")
        _flush(home, dropped)
        assert not path.exists()                                   # not resurrected by a late mark or write-back


def test_remove_and_accept_name_the_file_that_was_sent(tmp_path):
    home = tmp_path / "cicada"
    path = _put(home, "s1", text="old")
    stamp = spool.signature(path)
    entry = spool._read(path)
    _put(home, "s1", text="new")
    spool.accept(path, entry, stamp)
    assert spool.remove(path, stamp) is False
    assert spool._read(path)["body"]["conversation"] == {"kept": ["new"]} and "accepted_at" not in spool._read(path)
    assert spool.remove(path, spool.signature(path)) is True and not path.exists()


def test_a_held_lock_never_hangs_a_hook(tmp_path, monkeypatch):
    import fcntl

    home = tmp_path / "cicada"
    path = _put(home, "s1")
    monkeypatch.setattr(spool, "MARK_WAIT_S", 0.1)
    fd = os.open(spool.spool_dir(home) / spool.MARK_LOCK, os.O_WRONLY | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        started = time.monotonic()
        assert spool.remove(path, spool.signature(path)) is False   # skipped: the entry stays, a resend is idempotent
        _put(home, "s2")                                            # a put goes on (its rename is atomic by itself)
        assert time.monotonic() - started < 2.0 and path.exists()
    finally:
        os.close(fd)


# --- finding 3: the single-machine path ----------------------------------------------------------------------------------

LOCAL_BASE = "http://127.0.0.1:8123"


def _local(home: Path, sid: str, text: str) -> Path:
    spool.put(home, capture.LOCAL_ROUTE, {"transcript_path": f"/x/{sid}.jsonl", "text": text},
              key=f"claude-code:{sid}", target={"base": LOCAL_BASE, "bank_id": None})
    return next(p for p in spool.entries(home) if (spool._read(p) or {}).get("key") == f"claude-code:{sid}")


def _flush_local(home: Path, post):
    return capture._flush_local(home, post, "scratch-token", base=LOCAL_BASE, key="claude-code:current", event="Stop",
                                started=time.monotonic())


def test_flush_local_keeps_a_newer_firing_of_a_session_whose_old_entry_was_sent(tmp_path):
    home = tmp_path / "cicada"
    path = _local(home, "s1", "old")
    for status in (202, 200):
        def post(url, data, token, timeout, status=status):
            _local(home, "s1", f"newer-{status}")                   # the session fired again during the ~3 s post
            return status, "{}"

        _flush_local(home, post)
        entry = spool._read(path)
        assert entry and entry["body"]["text"] == f"newer-{status}" and "accepted_at" not in entry


def test_flush_local_does_not_bring_back_an_entry_dropped_during_the_post(tmp_path):
    home = tmp_path / "cicada"
    path = _local(home, "s1", "old")

    def post(url, data, token, timeout):
        spool.drop(home, "claude-code:s1", LOCAL_BASE)              # the session's own firing landed and dropped it
        return 202, "{}"

    _flush_local(home, post)
    assert not path.exists()
