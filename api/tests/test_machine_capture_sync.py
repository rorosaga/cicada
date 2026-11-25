"""Track B3: a conversation captured on a second machine reaches the HOME's consolidation queue, reliably and
attributably (owner: "make sure the consolidation queues are being correctly synced through all machines").

Real app objects on tmp homes, loopback only: a HOME (publishing) and two other machines, one that keeps a copy (replica
mode, its own backend running) and one plain client (``CICADA_API_BASE``, no backend). The hook runs as the harness runs
it, a subprocess with that machine's environment; every assertion is on the HOME: one waiting episode, ``device`` the
capturing machine's id, exactly once. Synthetic data and placeholder names only."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from test_headless_two_machines import PY, REPO, SID, SID2, _base_env, _hook, _line
from test_replica_two_machines import Machine, _caught_up, _wait

from api.services import markdown_parser


def _episodes(home: Machine, session_id: str) -> list[Path]:
    return home.episodes(session_id)


def _unsent_of(home: Machine, device_id: str):
    """``unsent`` on the home's ``GET /devices/status`` row of that device (None: it never reported)."""
    _s, body = home.call("GET", "/devices/status")
    rows = [r for r in (body or {}).get("devices", []) if r.get("id") == device_id]
    return rows[0].get("unsent") if rows else "no row"


def _device_of(path: Path):
    return markdown_parser.parse(path).frontmatter.get("device")


@pytest.fixture
def trio(tmp_path):
    """A home, a computer that keeps a copy, and a plain client; each with its own device token from the home."""
    home = Machine(tmp_path, "home", CICADA_SYNC_PUBLISH="on")
    replica = Machine(tmp_path, "replica")
    try:
        home.start()
        _s, copy_dev = home.call("POST", "/devices", {"name": "copy-box"})
        _s, client_dev = home.call("POST", "/devices", {"name": "client-box"})
        replica.extra = {"CICADA_REPLICA_OF": home.url}
        (replica.cicada_home / "device_token").write_text(copy_dev["token"] + "\n")
        (replica.cicada_home / "replica_of").write_text(home.url + "\n")
        client_home = tmp_path / "client-home"
        client_cicada = tmp_path / "client-cicada"
        for d in (client_home, client_cicada):
            d.mkdir()
        (client_cicada / "device_token").write_text(client_dev["token"] + "\n")
        os.chmod(client_cicada / "device_token", 0o600)
        projects = replica.home / ".claude" / "projects" / "-home-example-alpha"
        projects.mkdir(parents=True)
        cprojects = client_home / ".claude" / "projects" / "-home-example-alpha"
        cprojects.mkdir(parents=True)
        replica.start()
        assert _caught_up(home, replica), replica.log.read_text()[-2000:]
        yield {
            "home": home, "replica": replica,
            "replica_env": {**_base_env(replica.home, replica.cicada_home), "CICADA_PORT": str(replica.port)},
            "replica_projects": projects, "replica_device": copy_dev["device"]["id"],
            "client_env": {**_base_env(client_home, client_cicada), "CICADA_API_BASE": home.url,
                           "CICADA_SPOOL_RETRY_FIRST_S": "2", "CICADA_SPOOL_RETRY_LIFETIME_S": "240"},
            "client_projects": cprojects, "client_device": client_dev["device"]["id"],
            "client_cicada": client_cicada,
        }
    finally:
        replica.stop()
        home.stop()


def _session(projects: Path, sid: str, text: str) -> Path:
    path = projects / f"{sid}.jsonl"
    path.write_text(_line("user", text, sid=sid) + _line("assistant", [{"type": "text", "text": "noted"}], sid=sid))
    return path


MACHINES = [("replica_env", "replica_projects", "replica_device"), ("client_env", "client_projects", "client_device")]


@pytest.mark.slow
@pytest.mark.parametrize("env_key,projects_key,device_key", MACHINES)
def test_a_session_ends_on_a_second_machine_and_waits_once_at_the_home(trio, env_key, projects_key, device_key):
    home = trio["home"]
    transcript = _session(trio[projects_key], SID, "plan alpha-project with bob-example")
    line = _hook(trio[env_key], transcript)
    assert "http 20" in line, line
    _hook(trio[env_key], transcript)                              # the next Stop: idempotent
    eps = _episodes(home, SID)
    assert len(eps) == 1, line
    assert _device_of(eps[0]) == trio[device_key]
    assert "processed: false" in eps[0].read_text()               # waiting in the home's queue
    # The machine says it holds nothing unsent (a client with the capture it posted, a copy in its announcement).
    assert _wait(lambda: _unsent_of(home, trio[device_key]) == 0, 120), _unsent_of(home, trio[device_key])


@pytest.mark.slow
@pytest.mark.parametrize("env_key,projects_key,device_key", MACHINES)
def test_a_home_that_was_away_at_capture_gets_it_with_no_further_firing(trio, env_key, projects_key, device_key):
    """(a) The home is unreachable when the session ends and comes back; nothing fires on the capturing machine again."""
    home = trio["home"]
    transcript = _session(trio[projects_key], SID2, "decided the beta-example budget")
    home.stop()
    try:
        line = _hook(trio[env_key], transcript, sid=SID2)
        assert "spooled" in line, line
    finally:
        home.start()
    got = _wait(lambda: _episodes(home, SID2), 360)
    assert len(got) == 1, "the home never received the session the machine had spooled"
    assert _device_of(got[0]) == trio[device_key]
    assert _wait(lambda: _unsent_of(home, trio[device_key]) == 0, 120), _unsent_of(home, trio[device_key])


def _long_session(projects: Path, sid: str) -> Path:
    """A transcript past the hook's 16 MB read bound: the hook hands it to a detached child."""
    path = projects / f"{sid}.jsonl"
    padding = "x" * 8192
    with path.open("w") as out:
        out.write(_line("user", "plan the gamma-example launch with bob-example", sid=sid))
        for _ in range((capture.DETACH_BYTES // (len(padding) + 300)) + 40):
            out.write(json.dumps({"type": "system", "uuid": "p", "timestamp": "2026-10-16T10:00:01.000Z",
                                  "sessionId": sid, "cwd": "/home/example/alpha", "content": padding}) + "\n")
        out.write(_line("assistant", [{"type": "text", "text": "noted"}], sid=sid))
    assert path.stat().st_size > capture.DETACH_BYTES
    return path


@pytest.mark.slow
def test_a_long_session_read_by_the_detached_child_still_gets_a_retrier(trio):
    """Reviewer blocker (B3): the child that reads a transcript over 16 MB carries ``CICADA_HOOK_DETACHED``; that used
    to be the marker that also forbade a retrier, so a post of a long session that did not land waited for the next
    firing on that machine. The home is away when the long session ends and comes back; nothing fires again."""
    home = trio["home"]
    sid = "77777777-8888-4999-8aaa-bbbbbbbbbbbb"
    transcript = _long_session(trio["client_projects"], sid)
    env = trio["client_env"]
    home.stop()
    try:
        line = _hook(env, transcript, sid=sid)
        assert "in the background" in line, line
        spool_dir = Path(env["CICADA_HOME"]) / "spool" / "capture"
        assert _wait(lambda: any(spool_dir.glob("s-*.json")), 240), "the detached child never spooled the session"
    finally:
        home.start()
    got = _wait(lambda: _episodes(home, sid), 360)
    assert len(got) == 1, "the home never received the long session the machine had spooled"
    assert _device_of(got[0]) == trio["client_device"]
    assert _wait(lambda: not list(spool_dir.glob("s-*.json")), 120)


def test_the_retrier_marker_is_not_the_detached_marker(tmp_path, monkeypatch):
    """The long-session child (``DETACHED_ENV``) may start the retrier; the retrier (``RETRIER_ENV``) starts none."""
    home = tmp_path / "h"
    (home / "spool").mkdir(parents=True)
    started = []

    class Popen:
        def __init__(self, argv, **kw):
            started.append((argv, kw["env"]))

    monkeypatch.setattr(subprocess, "Popen", Popen)
    base = {"CICADA_HOME": str(home), "CICADA_API_BASE": "http://127.0.0.1:1", "CICADA_API_TOKEN": "t"}
    assert capture._retry_later(capture._client_send, {**base, capture.DETACHED_ENV: "1"}, home, "claude-code")
    argv, child_env = started[-1]
    assert capture.RETRY_ARG in argv and child_env[capture.RETRIER_ENV] == "1"
    assert capture.DETACHED_ENV not in child_env
    assert not capture._retry_later(capture._client_send, {**base, capture.RETRIER_ENV: "1"}, home, "claude-code")
    assert len(started) == 1


@pytest.mark.slow
def test_a_hook_that_does_not_know_it_runs_on_a_copy_is_not_refused(trio, tmp_path):
    """The hook's ``$CICADA_HOME`` is not where the backend keeps ``replica_of`` (or the copy was set in the backend's
    own environment only): it posts the old way, a path, to its own backend. That used to answer 409 and the session was
    let go with no word; now the copy's backend reads the transcript itself and keeps the session for the home."""
    home, replica = trio["home"], trio["replica"]
    other_home = tmp_path / "hook-elsewhere"
    other_home.mkdir()
    (other_home / "api_token").write_text((replica.cicada_home / "api_token").read_text())
    env = {**_base_env(replica.home, other_home), "CICADA_PORT": str(replica.port)}
    assert "replica" not in " ".join(env)                      # the hook sees a plain local machine
    transcript = _session(trio["replica_projects"], "55555555-6666-4777-8888-999999999999", "ship the alpha-project plan")
    line = _hook(env, transcript, sid="55555555-6666-4777-8888-999999999999")
    assert "http 200 queued" in line, line
    got = _wait(lambda: _episodes(home, "55555555-6666-4777-8888-999999999999"), 240)
    assert len(got) == 1 and _device_of(got[0]) == trio["replica_device"]
    _hook(env, transcript, sid="55555555-6666-4777-8888-999999999999")
    time.sleep(3)
    assert len(_episodes(home, "55555555-6666-4777-8888-999999999999")) == 1


# --- the home answers 202 and then does not write (b, c), in one process ----------------------------------------------

import io  # noqa: E402
import threading  # noqa: E402

from api.hooks import capture, hook_spool  # noqa: E402
from api.routers import capture as capture_router  # noqa: E402
from api.tests.test_capture_survives_a_stall import server  # noqa: E402,F401
from api.tests.test_continuity_acceptance import A, A_TURNS, env  # noqa: E402,F401
from api.tests.test_capture_survives_a_stall import _episodes as _bank_episodes, _stop  # noqa: E402


def _client(tmp_path, port, *, base: bool = True):
    home = tmp_path / "hook-home"
    home.mkdir(exist_ok=True)
    (home / "api_token").write_text("scratch-token", encoding="utf-8")
    environ = {"CICADA_HOME": str(home), "CICADA_PORT": str(port), "PATH": "/usr/bin:/bin",
               "CICADA_SPOOL_RETRY": "off"}
    if base:
        environ.update({"CICADA_API_BASE": f"http://127.0.0.1:{port}", "CICADA_API_TOKEN": "scratch-token"})
    return home, environ


def _fire(environ, home, payload) -> str:
    log = home / "capture.log"
    capture.main(["--harness", "claude-code"], stdin=io.StringIO(json.dumps(payload)), environ=environ, log_path=log,
                 token_path=home / "api_token", memory_spawn=lambda *_a, **_k: None)
    return log.read_text(encoding="utf-8").splitlines()[-1]


@pytest.fixture
def slow_failing_write(monkeypatch):
    """The writer outlives the 2 s answer (here 50 ms) and then fails — or its process is gone before it finishes."""
    monkeypatch.setattr(capture_router, "CAPTURE_ANSWER_S", 0.05)
    state = {"fail": True}

    def wrap(real):
        def writer(*args, **kwargs):
            if state["fail"]:
                time.sleep(0.3)
                raise RuntimeError("the write failed after the 202")
            return real(*args, **kwargs)
        return writer

    monkeypatch.setattr(capture_router, "capture_posted", wrap(capture_router.capture_posted))
    monkeypatch.setattr(capture_router, "capture_transcript", wrap(capture_router.capture_transcript))
    return state


def test_a_202_then_a_failed_write_is_kept_until_the_write_is_confirmed(env, tmp_path, server, slow_failing_write,
                                                                         monkeypatch):  # noqa: F811
    """(b) The client's hook hears 202 and must not drop its post: the write then fails, nothing is in the home."""
    home, environ = _client(tmp_path, server["port"])
    line = _fire(environ, home, _stop(env, A, A_TURNS))
    assert "http 202" in line and "kept until the write is confirmed" in line, line
    time.sleep(0.6)                                                  # the late write has failed by now
    assert _bank_episodes(env) == []
    assert hook_spool.pending(home) == 1                             # still held: that is the whole fix
    # The writer works again; the retrier (the timer a plain client otherwise lacks) confirms it: once.
    slow_failing_write["fail"] = False
    monkeypatch.setattr(capture_router, "CAPTURE_ANSWER_S", 2.0)
    monkeypatch.setattr(capture.spool, "ACCEPT_CONFIRM_S", 0.0)
    landed = capture.retry_spool(environ, home=home, sleep=lambda _s: None, lifetime=30)
    assert landed == 1 and len(_bank_episodes(env)) == 1
    assert hook_spool.pending(home) == 0
    # A second confirmation (the first one's answer lost) writes nothing new.
    capture.retry_spool(environ, home=home, sleep=lambda _s: None, lifetime=5)
    assert len(_bank_episodes(env)) == 1


def test_a_server_restarting_between_the_202_and_the_write_loses_nothing(env, tmp_path, server, slow_failing_write,
                                                                          monkeypatch):  # noqa: F811
    """(c) After the 202 the server's process is gone (the write never lands) and is away when the first confirmation
    tries; it comes back and the next one lands the session exactly once."""
    home, environ = _client(tmp_path, server["port"])
    assert "http 202" in _fire(environ, home, _stop(env, A, A_TURNS))
    time.sleep(0.6)
    assert _bank_episodes(env) == []
    slow_failing_write["fail"] = False
    monkeypatch.setattr(capture_router, "CAPTURE_ANSWER_S", 2.0)
    monkeypatch.setattr(capture.spool, "ACCEPT_CONFIRM_S", 0.0)
    calls = {"n": 0}

    def post(url, body, token, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            return None, ""                                          # the server is down: restarting
        return capture._client_send(url, body, token, timeout)

    capture.retry_spool(environ, home=home, post=post, sleep=lambda _s: None, lifetime=30)
    assert calls["n"] >= 2 and len(_bank_episodes(env)) == 1 and hook_spool.pending(home) == 0


def test_a_202_on_the_machines_own_backend_is_kept_too(env, tmp_path, server, slow_failing_write,
                                                        monkeypatch):  # noqa: F811
    """The same on the home itself (the hook's loopback path): 202, then the write fails; the session's next firing
    sends it again (the accepted entry is due after ``ACCEPT_CONFIRM_S``) and nothing doubles."""
    home, environ = _client(tmp_path, server["port"], base=False)
    line = _fire(environ, home, _stop(env, A, A_TURNS))
    assert "http 202" in line and "kept until the write is confirmed" in line, line
    time.sleep(0.6)
    assert _bank_episodes(env) == [] and hook_spool.pending(home) == 1
    slow_failing_write["fail"] = False
    monkeypatch.setattr(capture_router, "CAPTURE_ANSWER_S", 2.0)
    monkeypatch.setattr(capture.spool, "ACCEPT_CONFIRM_S", 0.0)
    other = "bbbbbbbb-2222-4333-8444-555555555555"
    _fire(environ, home, _stop(env, other, A_TURNS[:2]))             # another session ends; it flushes the waiting one
    assert hook_spool.pending(home) == 0
    assert len(_bank_episodes(env)) == 2


# --- the spool and what a machine says it holds -------------------------------------------------------------------------

def _put(home: Path, key: str, *, accepted: bool = False, route: str = "/capture/session"):
    body = {"harness": "claude-code", "session_id": key, "conversation": {"kept": []}, "transcript_bytes": 1,
            "transcript_size": 1}
    hook_spool.put(home, route, body, key=f"claude-code:{key}", target={"base": "https://home.example", "bank_id": None},
                   accepted=accepted)


def test_the_spool_counts_what_it_holds_and_what_it_dropped(tmp_path, monkeypatch):
    home = tmp_path / "h"
    assert hook_spool.counts(home) == {"waiting": 0, "held": 0, "rejected": 0}
    _put(home, "s1")
    _put(home, "s2", accepted=True)
    assert hook_spool.counts(home) == {"waiting": 2, "held": 0, "rejected": 0}
    assert hook_spool.counts(home, other_than="claude-code:s1")["waiting"] == 1   # the one being sent is not counted
    monkeypatch.setattr(hook_spool, "MAX_ENTRIES", 2)
    _put(home, "s3")                                                          # the oldest is dropped: said, not silent
    assert hook_spool.counts(home) == {"waiting": 2, "held": 0, "rejected": 1}


def test_a_copys_follower_sends_the_hook_spool_through_its_own_transport(tmp_path, monkeypatch):
    """The hook's one direct request cannot reach a home the copy reaches by its door or relay; the follower can, and
    does not wait for another session to end on this computer."""
    from api.services import replica

    home = tmp_path / "cicada"
    monkeypatch.setenv("CICADA_HOME", str(home))
    _put(home, "s1")
    _put(home, "s2")
    hook_spool.put(home, "/capture/transcript", {"transcript_path": "/x"}, key="claude-code:local",
                   target={"base": "http://127.0.0.1:8000", "bank_id": None})   # a path only this computer could read
    sent: list = []

    def request(method, path, *, body=None, headers=None, timeout=0, **_kw):
        payload = json.loads(body)
        sent.append((path, payload))
        return 200, {}, {"status": "created", "bankId": "bank-1"}

    monkeypatch.setattr(replica, "request", request)
    replica._flush_hook_spool()
    assert sorted(p["session_id"] for _path, p in sent) == ["s1", "s2"]
    assert {path for path, _p in sent} == {"/capture/session"}
    assert all(p["unsent"]["waiting"] <= 2 and "held" in p["unsent"] for _path, p in sent)
    left = [e.name for e in hook_spool.entries(home)]
    assert len(left) == 1 and hook_spool._read(hook_spool.entries(home)[0])["route"] == "/capture/transcript"


def test_a_copy_that_cannot_reach_the_home_keeps_everything_and_a_202_stays(tmp_path, monkeypatch):
    from api.services import replica

    home = tmp_path / "cicada"
    monkeypatch.setenv("CICADA_HOME", str(home))
    _put(home, "s1")
    monkeypatch.setattr(replica, "request", lambda *a, **k: (None, {}, None))
    replica._flush_hook_spool()
    assert hook_spool.pending(home) == 1
    monkeypatch.setattr(replica, "request", lambda *a, **k: (202, {}, {"status": "accepted"}))
    replica._flush_hook_spool()
    assert hook_spool.pending(home) == 1                      # accepted is not written: it stays
    entry = hook_spool._read(hook_spool.entries(home)[0])
    assert entry["accepted_at"] > 0
    monkeypatch.setattr(replica, "request", lambda *a, **k: (200, {}, {"status": "unchanged"}))
    monkeypatch.setattr(capture.spool, "ACCEPT_CONFIRM_S", 0.0)    # the module the hooks and the follower share
    replica._flush_hook_spool()
    assert hook_spool.pending(home) == 0
