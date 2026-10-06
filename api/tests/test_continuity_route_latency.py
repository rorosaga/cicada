"""G110 slice 1a T4: the WHOLE SessionStart route's latency (critique finding 19).

Drives the real `POST /capture/hook-context` (SessionStart, `source: clear`)
through TestClient over a synthetic bank shaped like the critic's: 1,500
episodes — 300 Stop-hook sessions with 500-entry sidecars, 30 of them with
~3.6 KB folder paths, 50 with heads over 16 KB — with agent reading on and
registry rows present. Reports server-side `latencyMs` (run with `-s`).

* cold — no index file, no in-memory index, no handshake cache: p95 ≤ 600 ms;
* warm — the same call again: p95 ≤ 250 ms;
* near the deadline — assembly slowed to 750 ms and the registry lock held:
  the answer stays within the 800 ms budget (+50 ms) and carries no partial note.

Interpreter start-up and a cold disk are not measured; the OS file cache is
warm after the first read. End-to-end hook latency (the stdlib hook posting
through the same app) is reported separately."""
from __future__ import annotations

import fcntl
import io
import json
import os
import shutil
import statistics
import time

import pytest
from fastapi.testclient import TestClient

from _continuity_fixtures import CWD, sid, write_other_episode, write_session
from _reading_fixtures import enable
from api import config, main
from api.services import continuity, continuity_sessions, hook_recall

URL = "/capture/hook-context"
RUNS = 10


@pytest.fixture(scope="module")
def big(tmp_path_factory):
    root = tmp_path_factory.mktemp("continuity-latency")
    memory = root / "memory"
    (memory / "episodes").mkdir(parents=True)
    long_dir = "/home/example/" + "/".join(["a long folder name with spaces"] * 120)
    turns = [("user" if i % 2 == 0 else "assistant", f"turn {i} about the alpha parser") for i in range(500)]
    for n in range(1, 301):
        cwd = long_dir if n <= 30 else (CWD if n == 300 else f"/home/example/p{n % 40}")
        extra = {"zz_note": "x" * 17_000} if 31 <= n <= 80 else None
        write_session(memory, n, turns, cwd=cwd, start=-1000 + n, step=0.01, extra_meta=extra)
    for i in range(1200):
        write_other_episode(memory, i)
    return {"root": root, "memory": memory, "home": root / "home"}


@pytest.fixture
def client(big, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(big["home"]))
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(big["memory"]))
    config.get_settings.cache_clear()
    enable()
    hook_recall.reset()
    yield TestClient(main.app)
    config.get_settings.cache_clear()
    hook_recall.reset()


def _start(client, i):
    return client.post(URL, json={"event": "session_start", "harness": "claude-code", "session_id": sid(5000 + i),
                                  "cwd": CWD, "source": "clear"}).json()


def _cold(big):
    continuity.reset()
    target = continuity.index_path(big["memory"], (big["memory"],))
    if target is not None:
        target.unlink(missing_ok=True)
    shutil.rmtree(big["home"] / "handshake", ignore_errors=True)


def _p95(xs):
    return statistics.quantiles(xs, n=20)[18]


def test_the_whole_route_cold_and_warm(client, big):
    cold, warm = [], []
    for i in range(RUNS):
        _cold(big)
        data = _start(client, i)
        assert "Where the last session in this folder stopped" in (data["additionalContext"] or ""), data["reason"]
        cold.append(data["latencyMs"])
        warm.append(_start(client, 100 + i)["latencyMs"])
    print(f"\nG110 SessionStart route: cold p50 {statistics.median(cold)} ms p95 {_p95(cold):.0f} ms; "
          f"warm p50 {statistics.median(warm)} ms p95 {_p95(warm):.0f} ms")
    assert _p95(cold) <= 600 and _p95(warm) <= 250


def test_near_the_deadline_with_a_held_lock_there_is_no_partial_note(client, big, monkeypatch):
    real = continuity.assemble

    def slow(*a, **k):
        time.sleep(0.75)
        return real(*a, **k)

    monkeypatch.setattr(continuity, "assemble", slow)
    home = continuity_sessions.continuity_home((big["memory"],))
    lock = home / f"{continuity_sessions.bank_file_id(big['memory'])}.lock"
    fd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        data = _start(client, 900)
    finally:
        os.close(fd)
    assert data["latencyMs"] <= hook_recall.PRIMER_BUDGET_S * 1000 + 50
    assert data["additionalContext"] is None and data["reason"] == "timeout"


def test_end_to_end_hook_latency_is_reported(client, big, tmp_path):
    """The stdlib hook (api/hooks/recall.py), posting through the same app.
    Interpreter start-up is excluded; this is the hook's own work plus the route."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("recall_hook", "api/hooks/recall.py")
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)

    def post(url, body, token, timeout):
        r = client.post(URL, content=body, headers={"Content-Type": "application/json"})
        return r.status_code, r.text

    token = tmp_path / "token"
    token.write_text("t")
    samples = []
    for i in range(5):
        out = io.StringIO()
        payload = json.dumps({"session_id": sid(7000 + i), "hook_event_name": "SessionStart", "cwd": CWD,
                              "source": "clear"})
        t0 = time.perf_counter()
        hook.main(["--harness", "claude-code"], stdin=io.StringIO(payload), stdout=out, environ={},
                  post=post, log_path=tmp_path / "recall.log", token_path=token)
        samples.append((time.perf_counter() - t0) * 1000)
        assert "Where the last session in this folder stopped" in json.loads(out.getvalue())[
            "hookSpecificOutput"]["additionalContext"]
    print(f"\nG110 end-to-end hook (in-process, no interpreter start): median {statistics.median(samples):.0f} ms")
