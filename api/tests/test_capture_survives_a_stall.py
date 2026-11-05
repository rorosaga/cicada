"""What a stalled event loop costs a capture (2026-11-05, the Stage 2 stall): a real uvicorn on a real socket, its loop
blocked for longer than the hook waits, and the real hook posting into it. The socket still accepts, so the hook hears
nothing rather than a refusal. These pin what survives: the words reach the episode exactly once. Synthetic fixtures."""
from __future__ import annotations

import asyncio
import io
import json
import socket
import threading
import time

import pytest
import uvicorn

from api import main
from api.hooks import capture, hook_spool
from api.services import markdown_parser
from api.tests.test_continuity_acceptance import A, A_TURNS, _transcript, _ts, env  # noqa: F401


@pytest.fixture
def server(env):  # noqa: F811
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(main.app, host="127.0.0.1", port=port, lifespan="off", log_level="error"))
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=lambda: loop.run_until_complete(srv.serve()), daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not srv.started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert srv.started
    yield {"port": port, "loop": loop}
    srv.should_exit = True
    thread.join(10)


def _stall(server, seconds: float) -> None:
    server["loop"].call_soon_threadsafe(time.sleep, seconds)
    time.sleep(0.1)


def _environ(env, tmp_path, port):  # noqa: F811
    return {"CICADA_PORT": str(port), "CICADA_HOME": str(tmp_path / "hook-home"), "PATH": "/usr/bin:/bin"}


def _hook(env, tmp_path, port, payload: dict, harness: str = "claude-code") -> str:  # noqa: F811
    home = tmp_path / "hook-home"
    home.mkdir(exist_ok=True)
    log = home / "capture.log"
    (home / "api_token").write_text("scratch-token", encoding="utf-8")
    capture.main(["--harness", harness], stdin=io.StringIO(json.dumps(payload)), environ=_environ(env, tmp_path, port),
                 log_path=log, token_path=home / "api_token", memory_spawn=lambda *_a, **_k: None)
    return log.read_text(encoding="utf-8") if log.exists() else ""


def _stop(env, session, turns, event="Stop") -> dict:  # noqa: F811
    path = env["claude"] / f"{session}.jsonl"
    path.write_text(_transcript(session, turns), encoding="utf-8")
    return {"session_id": session, "transcript_path": str(path), "cwd": "/home/example/alpha-project",
            "hook_event_name": event}


def _episodes(env):  # noqa: F811
    return sorted((env["memory"] / "episodes").glob("*.md"))


def _settle(env, want: int = 1, seconds: float = 8.0):  # noqa: F811
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline and len(_episodes(env)) < want:
        time.sleep(0.05)
    return _episodes(env)


def test_a_stop_during_a_stall_is_spooled_and_lands_once(env, tmp_path, server):  # noqa: F811
    home = tmp_path / "hook-home"
    _stall(server, capture.TIMEOUT_S + 2)
    started = time.monotonic()
    log = _hook(env, tmp_path, server["port"], _stop(env, A, A_TURNS))
    assert time.monotonic() - started < capture.TIMEOUT_S + 1, "the hook waited longer than its own bound"
    assert "no answer" in log and "spooled" in log
    assert hook_spool.pending(home) == 1

    # The loop wakes and serves the request the hook gave up on: its bytes were already in the socket.
    episodes = _settle(env)
    assert len(episodes) == 1, "the post the hook gave up on was never served"

    # The session's next firing sends again: the same episode, nothing doubled, nothing left waiting.
    later = A_TURNS + [("user", "One more question about the alpha parser.", _ts(30))]
    log = _hook(env, tmp_path, server["port"], _stop(env, A, later))
    assert hook_spool.pending(home) == 0, log
    assert len(_episodes(env)) == 1
    body = markdown_parser.parse(_episodes(env)[0]).body
    assert body.count("One more question about the alpha parser.") == 1
    assert body.count(A_TURNS[0][1]) == 1


def test_a_last_stop_during_a_stall_with_no_later_firing_still_lands(env, tmp_path, server):  # noqa: F811
    """The session ends in the stall and never fires again: the served request is the whole of it."""
    _stall(server, capture.TIMEOUT_S + 1.5)
    _hook(env, tmp_path, server["port"], _stop(env, A, A_TURNS, event="SessionEnd"))
    episodes = _settle(env)
    assert len(episodes) == 1
    assert A_TURNS[0][1] in episodes[0].read_text(encoding="utf-8")


def test_a_per_turn_post_during_a_stall_is_kept_once(env, tmp_path, server):  # noqa: F811
    """A harness whose hook carries the turn's words (a post that names no file to read again)."""
    payload = {"session_id": "gem-session-1", "prompt": "The alpha parser question.", "prompt_response": "Its answer.",
               "hook_event_name": "AfterAgent", "cwd": "/home/example/alpha-project"}
    _stall(server, capture.TIMEOUT_S + 2)
    log = _hook(env, tmp_path, server["port"], payload, harness="gemini-cli")
    episodes = _settle(env)
    assert len(episodes) == 1, f"a turn posted into a stall was lost: {log}"
    assert markdown_parser.parse(episodes[0]).body.count("The alpha parser question.") == 1
    # The same exchange again (a retried firing) changes nothing.
    _hook(env, tmp_path, server["port"], payload, harness="gemini-cli")
    assert markdown_parser.parse(_episodes(env)[0]).body.count("The alpha parser question.") == 1
