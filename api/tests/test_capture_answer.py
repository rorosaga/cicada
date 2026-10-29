"""2026-10-29 (capture post latency): a session capture answers inside the hook's budget whatever the write costs,
finding a session's episode never reads every episode again, and the Stop hook says "no answer" — and keeps the
request for a later firing — instead of logging an error for a capture that may well have landed. Synthetic data
only; no network, no real home directory."""
from __future__ import annotations

import io
import json
import socket
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.hooks import capture as hook
from api.routers import capture as capture_router
from api.services import markdown_parser, transcript_capture as tc

SID = "11111111-2222-4333-8444-555555555555"
OTHER = "99999999-2222-4333-8444-555555555555"


def _transcript(text: str) -> str:
    return json.dumps({"type": "user", "uuid": "u", "timestamp": "2026-09-03T10:00:00.000Z", "sessionId": SID,
                       "cwd": "/home/example/alpha-project", "message": {"role": "user", "content": text}}) + "\n"


@pytest.fixture(autouse=True)
def _fresh_index(monkeypatch):
    monkeypatch.setattr(tc, "_episode_cache", {})


@pytest.fixture
def roots(tmp_path, monkeypatch):
    claude = tmp_path / "claude-projects" / "-home-example-alpha-project"
    claude.mkdir(parents=True)
    monkeypatch.setattr(tc, "harness_root", lambda h: claude.parent)
    return claude


@pytest.fixture
def memory(tmp_path):
    m = tmp_path / "memory"
    (m / "episodes").mkdir(parents=True)
    return m


@pytest.fixture
def client(memory, monkeypatch):
    from api import config, main

    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    with TestClient(main.app) as c:
        yield c
    config.get_settings.cache_clear()


# --- the route answers inside the budget --------------------------------------------------------------------------


def test_a_slow_write_answers_accepted_and_still_lands(client, roots, memory, monkeypatch):
    path = roots / f"{SID}.jsonl"
    path.write_text(_transcript("plan the alpha-project release"))
    real = capture_router.capture_transcript

    def slow(*a, **kw):
        time.sleep(0.6)
        return real(*a, **kw)

    after: list[tuple] = []
    monkeypatch.setattr(capture_router, "capture_transcript", slow)
    monkeypatch.setattr(capture_router, "CAPTURE_ANSWER_S", 0.05)
    monkeypatch.setattr(capture_router.awake_read, "after_capture",
                        lambda mp, ep, **kw: after.append((ep, kw.get("status"))))
    started = time.monotonic()
    r = client.post("/capture/transcript", json={"harness": "claude-code", "session_id": SID,
                                                 "transcript_path": str(path), "hook_event": "Stop"})
    assert time.monotonic() - started < 0.5          # the answer did not wait for the write
    assert r.status_code == 202, r.text
    assert r.json()["status"] == "accepted" and r.json()["episodeId"] is None
    assert r.json()["bank"]                         # where it is being written is known before it is written
    deadline = time.monotonic() + 5
    while not after and time.monotonic() < deadline:
        time.sleep(0.05)
    # The write finished on its own, once, and the step after a write ran for it.
    assert [p.name for p in (memory / "episodes").glob("ep_*.md")] == ["ep_2026-09-03_001.md"]
    assert after == [("ep_2026-09-03_001", "created")]
    # A later firing finds the same one episode (G104) and answers as before.
    monkeypatch.setattr(capture_router, "CAPTURE_ANSWER_S", 5.0)
    again = client.post("/capture/transcript", json={"harness": "claude-code", "session_id": SID,
                                                     "transcript_path": str(path)})
    assert again.status_code == 200 and again.json()["status"] == "unchanged"


def test_a_fast_refusal_is_still_answered_as_a_refusal(client, roots):
    bad = client.post("/capture/transcript", json={"harness": "claude-code", "session_id": SID,
                                                   "transcript_path": "/etc/passwd"})
    assert bad.status_code == 400


# --- finding a session's episode -----------------------------------------------------------------------------------


def _episode(eps: Path, n: int, sid: str, kind: str | None = tc.CAPTURE_KIND) -> Path:
    fm = {"id": f"ep_2026-09-03_{n:03d}", "session_id": sid, **({"capture_kind": kind} if kind else {})}
    path = eps / f"ep_2026-09-03_{n:03d}.md"
    markdown_parser.write(path, fm, "user: hi\n")
    return path


def test_a_new_session_reads_only_what_changed_since_the_last_lookup(tmp_path, monkeypatch):
    eps = tmp_path / "episodes"
    eps.mkdir()
    for n in range(1, 41):
        _episode(eps, n, f"{n:08d}-2222-4333-8444-555555555555")
    assert tc._find_session_episode(eps, "claude-code", SID) is None     # builds the index: reads every file once
    read: list[str] = []
    real = tc._head_session
    monkeypatch.setattr(tc, "_head_session", lambda fp: read.append(fp.name) or real(fp))
    assert tc._find_session_episode(eps, "claude-code", OTHER) is None    # another new session: nothing read
    assert read == []
    made = _episode(eps, 41, SID)                                         # another writer made one since
    assert tc._find_session_episode(eps, "claude-code", SID) == made
    assert read == ["ep_2026-09-03_041.md"]


def test_only_a_transcript_episode_of_that_session_is_found(tmp_path):
    eps = tmp_path / "episodes"
    eps.mkdir()
    _episode(eps, 1, SID, kind=None)          # cicada_save_episode from the same session: never rewritten here
    assert tc._find_session_episode(eps, "claude-code", SID) is None
    path = _episode(eps, 2, SID)
    assert tc._find_session_episode(eps, "claude-code", SID) == path
    path.unlink()                             # a stale hit is never handed out
    assert tc._find_session_episode(eps, "claude-code", SID) is None


def test_an_episode_rewritten_into_a_session_s_transcript_is_seen(tmp_path):
    eps = tmp_path / "episodes"
    eps.mkdir()
    path = _episode(eps, 1, OTHER)
    assert tc._find_session_episode(eps, "claude-code", SID) is None
    markdown_parser.write(path, {"id": "ep_2026-09-03_001", "session_id": SID, "capture_kind": tc.CAPTURE_KIND,
                                 "title": "a longer title so the size moves"}, "user: hi\n")
    assert tc._find_session_episode(eps, "claude-code", SID) == path


# --- the hook: "no answer", spooled, sent by a later firing --------------------------------------------------------

PAYLOAD = {"session_id": SID, "transcript_path": "/home/example/.claude/projects/x/" + SID + ".jsonl",
           "cwd": "/home/example/alpha-project", "hook_event_name": "Stop"}


def _fire(tmp_path, payload, post, notes=None):
    token = tmp_path / "api_token"
    token.write_text("tok-123")
    log = tmp_path / "logs" / "capture.log"
    env = {"HOME": str(tmp_path), "CICADA_HOME": str(tmp_path / "hook-home"), "CICADA_PORT": "8123"}
    hook.main(["--harness", "claude-code"], stdin=io.StringIO(json.dumps(payload)), environ=env, post=post,
              log_path=log, token_path=token, memory_spawn=notes)
    return log.read_text().strip().splitlines()[-1], tmp_path / "hook-home"


def test_a_timeout_is_no_answer_and_waits_for_a_later_firing(tmp_path, monkeypatch):
    def timed_out(url, body, tok, timeout):
        raise socket.timeout("timed out")

    started: list[str] = []
    monkeypatch.setattr(hook.memory_notes, "maybe_start", lambda env, **kw: started.append(kw["event"]) or None)
    line, home = _fire(tmp_path, PAYLOAD, timed_out)
    assert "error" not in line and "no answer (timed out at 3s)" in line and "spooled" in line
    assert started == ["Stop"]                # the notes sweep is not skipped by a slow answer
    waiting = list((home / "spool" / "capture").glob("s-*.json"))
    assert len(waiting) == 1
    entry = json.loads(waiting[0].read_text())
    assert entry["route"] == "/capture/transcript" and entry["body"]["session_id"] == SID
    assert "user:" not in waiting[0].read_text()      # a path waits, never the session's words

    sent: list[dict] = []

    def answers(url, body, tok, timeout):
        sent.append({"url": url, **json.loads(body)})
        return 200, '{"status":"updated"}'

    line, _ = _fire(tmp_path, {**PAYLOAD, "session_id": OTHER,
                               "transcript_path": PAYLOAD["transcript_path"].replace(SID, OTHER)}, answers)
    assert [s["session_id"] for s in sent] == [OTHER, SID]       # the live one first, then the waiting one
    assert sent[1]["url"] == "http://127.0.0.1:8123/capture/transcript"
    assert "http 200 updated in" in line and "spool: sent 1, 0 waiting" in line
    assert list((home / "spool" / "capture").glob("s-*.json")) == []


def test_the_session_s_own_landed_firing_drops_its_waiting_entry(tmp_path):
    def refused(url, body, tok, timeout):
        raise ConnectionRefusedError("Connection refused")

    line, home = _fire(tmp_path, PAYLOAD, refused)
    assert "no answer (ConnectionRefusedError: Connection refused)" in line
    sent: list[str] = []
    _fire(tmp_path, PAYLOAD, lambda url, body, tok, t: sent.append(json.loads(body)["session_id"]) or (202, '{"status":"accepted"}'))
    assert sent == [SID]                      # the newer firing replaced the waiting one: sent once
    assert list((home / "spool" / "capture").glob("s-*.json")) == []


def test_a_landed_capture_makes_no_spool_folder(tmp_path):
    line, home = _fire(tmp_path, PAYLOAD, lambda *a: (200, '{"status":"created"}'))
    assert "http 200 created in" in line and "spool" not in line
    assert not (home / "spool").exists()


def test_a_waiting_client_entry_is_never_sent_to_the_local_backend(tmp_path):
    from api.hooks import hook_spool

    home = tmp_path / "hook-home"
    hook_spool.put(home, "/capture/session", {"session_id": OTHER}, key=f"claude-code:{OTHER}",
                   target={"base": "http://server.example:8000", "bank_id": None})
    sent: list[str] = []
    _fire(tmp_path, PAYLOAD, lambda url, body, tok, t: sent.append(url) or (200, '{"status":"updated"}'))
    assert sent == ["http://127.0.0.1:8123/capture/transcript"]
    assert len(list((home / "spool" / "capture").glob("s-*.json"))) == 1
