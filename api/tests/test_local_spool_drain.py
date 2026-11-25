"""A session the hook kept for this computer's OWN backend is sent by that backend once it is up (B3, 2026-11-25).

The stuck state, measured on a second computer: four entries of ``/capture/transcript`` (``v`` 2, target the machine's
own loopback address, a path and a few fields each) kept while the backend was down; their hooks never fired again, so
``capture._flush_local`` never ran, and the machine reported ``unsent: 4`` for weeks. Three transcripts still existed,
one was an empty file. Here: the same entries, a backend that starts (``local_spool.start``, what the lifespan does),
no hook firing — they leave, the empty one counted as rejected; on a copy they reach the home's queue the way a session
that ends today does. Synthetic names; nothing leaves the process."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from api.hooks import capture, hook_client
from api.services import local_spool, replica, runtime_layout
from api.tests.test_continuity_acceptance import A, A_TURNS, _transcript, env  # noqa: F401

spool = capture.spool
PORT = "8713"
OWN = f"http://127.0.0.1:{PORT}"
HOME_URL = "https://home.example"


@pytest.fixture(autouse=True)
def _own_port(monkeypatch):
    monkeypatch.setenv("CICADA_PORT", PORT)
    monkeypatch.delenv("CICADA_REPLICA_OF", raising=False)
    monkeypatch.delenv("CICADA_API_BASE", raising=False)
    local_spool.stop()
    yield
    local_spool.stop()


def _sid(n: int) -> str:
    return f"1111111{n}-2222-4333-8444-55555555555{n}"


def _keep(home: Path, env, sid: str, *, text: str | None = "plan alpha-project with bob-example", base: str = OWN,
          empty: bool = False, gone: bool = False) -> Path:
    """What the hook keeps when its post to the backend got no answer: the request's fields, never the transcript."""
    path = env["claude"] / f"{sid}.jsonl"
    if empty:
        path.write_text("")
    elif not gone:
        path.write_text(_transcript(sid, [("user", text, "2026-10-16T10:00:00.000Z"),
                                          ("assistant", "noted", "2026-10-16T10:00:05.000Z")]), encoding="utf-8")
    fields = {"harness": "claude-code", "session_id": sid, "transcript_path": str(path),
              "cwd": "/home/example/alpha-project", "hook_event": "SessionEnd"}
    capture._spool_local(home, fields, key=f"claude-code:{sid}", base=base)
    return next(p for p in spool.entries(home) if (spool.read(p) or {}).get("key") == f"claude-code:{sid}")


def _stuck(home: Path, env) -> list[str]:
    """The measured state: three sessions with a transcript and one whose file is empty."""
    sids = [_sid(n) for n in range(4)]
    for sid in sids[:3]:
        _keep(home, env, sid)
    _keep(home, env, sids[3], empty=True)
    return sids


def _episodes(env):
    return sorted((env["memory"] / "episodes").glob("*.md"))


def _wait(predicate, timeout=20.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.05)
    return bool(predicate())


def _rejected(home: Path) -> int:
    return spool.counts(home)["rejected"]


# --- the home or a single computer: it lands in its own bank ----------------------------------------------------------

def test_a_backend_that_starts_sends_the_sessions_its_hooks_kept_with_no_hook_firing(env, tmp_path):
    home = runtime_layout.cicada_home()
    sids = _stuck(home, env)
    assert spool.counts(home)["waiting"] == 4                  # what the home would read as "unsent": 4

    assert local_spool.start(first_pass_s=0.05, interval_s=0.2)    # the backend came up; nothing else happens
    assert _wait(lambda: spool.pending(home) == 0), spool.counts(home)

    assert len(_episodes(env)) == 3                            # one episode per session, the empty one writes none
    assert spool.counts(home) == {"waiting": 0, "held": 0, "rejected": 1}    # the empty one counted, as a refusal is
    for sid in sids[:3]:
        assert any(sid in p.read_text() for p in _episodes(env))


def test_a_pass_takes_a_few_and_the_rest_wait_for_the_next(env):
    home = runtime_layout.cicada_home()
    _stuck(home, env)
    out = local_spool.drain_once(limit=2)
    assert out["done"] == 2 and out["waiting"] == 2 and spool.pending(home) == 2
    out = local_spool.drain_once(limit=2)
    assert out["done"] == 1 and out["finished"] == 1 and spool.pending(home) == 0


def test_the_hook_and_the_backend_may_try_the_same_entry_at_once(env, monkeypatch):
    """Both write the one episode (idempotent by content hash); each removes only the file it sent."""
    home = runtime_layout.cicada_home()
    sid = _sid(1)
    path = _keep(home, env, sid)
    entry = spool.read(path)
    posts: list = []

    def post(url, body, token, timeout):
        # the hook's resend arrives while the backend is mid-way: it is the same route, answered by the same writer
        posts.append(url)
        out = local_spool.drain_once()
        return 200, json.dumps({"status": "created"}) if out["done"] else (200, "{}")

    status = capture._flush_local(home, post, "scratch-token", base=OWN, key="claude-code:other", event="Stop",
                                  started=time.monotonic())
    assert posts and not spool.pending(home)
    assert len(_episodes(env)) == 1
    assert "sent 1" in status
    assert entry["route"] == hook_client.LOCAL_ROUTE
    assert local_spool.drain_once() == {"done": 0, "finished": 0, "waiting": 0}     # nothing left to take twice


def test_a_newer_snapshot_kept_during_the_send_is_never_removed(env, monkeypatch):
    home = runtime_layout.cicada_home()
    sid = _sid(2)
    _keep(home, env, sid)
    real = local_spool._deliver

    def deliver(fields, **kw):
        out = real(fields, **kw)
        _keep(home, env, sid, text="a later turn")                # a later firing replaced the entry meanwhile
        return out

    monkeypatch.setattr(local_spool, "_deliver", deliver)
    local_spool.drain_once()
    assert spool.pending(home) == 1                               # the newer one waits for the next pass
    monkeypatch.setattr(local_spool, "_deliver", real)
    local_spool.drain_once()
    assert spool.pending(home) == 0
    assert len(_episodes(env)) == 1


def test_a_transcript_that_is_gone_finishes_counted_never_waiting(env):
    home = runtime_layout.cicada_home()
    _keep(home, env, _sid(1), gone=True)
    out = local_spool.drain_once()
    assert out == {"done": 0, "finished": 1, "waiting": 0}
    assert spool.pending(home) == 0 and _rejected(home) == 1
    assert local_spool.drain_once()["finished"] == 0              # never retried in a loop


def test_a_path_outside_the_harness_root_is_refused_never_opened(env, tmp_path):
    home = runtime_layout.cicada_home()
    sid = _sid(3)
    outside = tmp_path / "elsewhere" / f"{sid}.jsonl"
    outside.parent.mkdir()
    outside.write_text(_transcript(sid, [("user", "secret words", "2026-10-16T10:00:00.000Z")]), encoding="utf-8")
    capture._spool_local(home, {"harness": "claude-code", "session_id": sid, "transcript_path": str(outside)},
                         key=f"claude-code:{sid}", base=OWN)
    local_spool.drain_once()
    assert spool.pending(home) == 0 and _rejected(home) == 1 and not _episodes(env)


def test_an_entry_kept_for_another_address_or_port_is_not_taken(env):
    home = runtime_layout.cicada_home()
    _keep(home, env, _sid(1), base="http://127.0.0.1:9999")
    _keep(home, env, _sid(2), base="https://another-server.example")
    assert local_spool.drain_once() == {"done": 0, "finished": 0, "waiting": 0}
    assert spool.pending(home) == 2 and not _episodes(env)


def test_a_session_post_for_a_home_is_never_read_here(env):
    """A client's ``/capture/session`` entry is the follower's, not this thread's."""
    home = runtime_layout.cicada_home()
    spool.put(home, "/capture/session", {"harness": "claude-code", "session_id": _sid(1), "conversation": {"kept": []},
                                         "transcript_bytes": 1, "transcript_size": 1},
              key=f"claude-code:{_sid(1)}", target={"base": OWN, "bank_id": None})
    assert local_spool.drain_once() == {"done": 0, "finished": 0, "waiting": 0}
    assert spool.pending(home) == 1


def test_an_entry_the_backend_accepted_but_did_not_write_is_taken_once_it_is_due(env, monkeypatch):
    home = runtime_layout.cicada_home()
    path = _keep(home, env, _sid(1))
    spool.accept(path, spool.read(path), spool.signature(path))      # the hook was told 202, then the backend restarted
    assert local_spool.drain_once()["waiting"] == 1                  # a write may still be finishing: not yet
    monkeypatch.setattr(spool, "ACCEPT_CONFIRM_S", 0.0)
    assert local_spool.drain_once()["done"] == 1 and spool.pending(home) == 0 and len(_episodes(env)) == 1


def test_with_only_the_demo_open_the_entry_waits_and_nothing_is_written(env, monkeypatch):
    from api.services import bank_registry

    home = runtime_layout.cicada_home()
    _keep(home, env, _sid(1))
    monkeypatch.setattr(bank_registry, "capture_bank", lambda root: None)
    assert local_spool.drain_once() == {"done": 0, "finished": 0, "waiting": 1}
    assert spool.pending(home) == 1 and not _episodes(env) and _rejected(home) == 0


def test_a_failure_is_logged_by_class_and_the_entry_stays(env, monkeypatch, caplog):
    from api.routers import capture as capture_router

    home = runtime_layout.cicada_home()
    _keep(home, env, _sid(1))

    def boom(*a, **k):
        raise RuntimeError("a secret path /home/example/alpha")

    monkeypatch.setattr(capture_router, "capture_transcript", boom)
    with caplog.at_level("INFO"):
        assert local_spool.drain_once()["waiting"] == 1
    assert spool.pending(home) == 1
    assert "RuntimeError" in caplog.text and "secret path" not in caplog.text


def test_the_thread_starts_once_and_stops(env):
    assert local_spool.start(first_pass_s=30, interval_s=30)
    assert not local_spool.start(first_pass_s=30, interval_s=30)
    local_spool.stop()
    assert not any(t.is_alive() for t in local_spool._THREAD)
    assert local_spool.start(first_pass_s=30, interval_s=30)


# --- a computer that keeps a copy: it reaches the home's queue as a session that ends today does ----------------------

@pytest.fixture
def copy(env, monkeypatch):
    monkeypatch.setenv("CICADA_REPLICA_OF", HOME_URL)
    woke: list = []
    monkeypatch.setattr(replica, "wake", lambda: woke.append(1))
    return woke


def test_on_a_copy_the_stuck_entries_reach_the_follower_queue_and_the_unsent_count_falls(env, copy, monkeypatch):
    home = runtime_layout.cicada_home()
    sids = _stuck(home, env)
    assert replica._unsent()["waiting"] == 4                        # what the machine said it held

    first, second = local_spool.drain_once(), local_spool.drain_once()
    assert (first["done"], second["done"]) == (3, 0) and (first["finished"], second["finished"]) == (0, 1)
    assert not _episodes(env)                                       # a copy never writes a bank
    assert copy                                                     # the follower was woken to send and say what is left
    routes = sorted((spool.read(p)["route"], spool.read(p)["body"]["session_id"]) for p in spool.entries(home))
    assert routes == sorted(("/capture/session", sid) for sid in sids[:3])     # the local entries are gone, the home's wait
    assert replica._unsent() == {"waiting": 3, "held": 0, "rejected": 1}

    sent: list = []

    def request(method, path, **kw):
        sent.append((method, path, json.loads(kw["body"])["session_id"]))
        return 200, {}, {"status": "created", "bankId": "bank-1"}

    monkeypatch.setattr(replica, "request", request)
    monkeypatch.setattr(replica._STATE, "bank_id", "bank-1")
    replica._flush_hook_spool()
    assert sorted(s[2] for s in sent) == sorted(sids[:3]) and {s[1] for s in sent} == {"/capture/session"}
    assert replica._unsent() == {"waiting": 0, "held": 0, "rejected": 1}      # the chip's light clears by itself


def test_on_a_copy_an_entry_for_another_port_is_not_taken(env, copy):
    home = runtime_layout.cicada_home()
    _keep(home, env, _sid(1), base="http://127.0.0.1:9999")
    assert local_spool.drain_once()["done"] == 0
    assert [spool.read(p)["route"] for p in spool.entries(home)] == [hook_client.LOCAL_ROUTE]


def test_on_a_copy_an_empty_transcript_is_finished_not_queued_for_the_home(env, copy):
    home = runtime_layout.cicada_home()
    _keep(home, env, _sid(1), empty=True)
    assert local_spool.drain_once() == {"done": 0, "finished": 1, "waiting": 0}
    assert spool.pending(home) == 0 and _rejected(home) == 1


def test_the_pass_runs_off_the_event_loop_in_its_own_thread(env, monkeypatch):
    seen: list = []
    real = local_spool.drain_once
    monkeypatch.setattr(local_spool, "drain_once",
                        lambda **k: (seen.append(threading.current_thread().name), real(**k))[1])
    _keep(runtime_layout.cicada_home(), env, _sid(1))
    local_spool.start(first_pass_s=0.01, interval_s=0.1)
    assert _wait(lambda: seen)
    assert seen[0] == "cicada-local-spool"
