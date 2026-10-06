"""G110 fix round 1, finding 1: the installed recall hook forwards SessionStart's
`source`, and the route fails closed on a missing one.

Runs the REAL stdlib hook (`api/hooks/recall.py`), posting into the real app,
for startup / clear / missing / resume / compact / fork payloads in both
harnesses. Only startup and clear get a continuity block or a `continues`."""
from __future__ import annotations

import importlib.util
import io
import json

import pytest
from fastapi.testclient import TestClient

from _continuity_fixtures import CWD, sid, write_session
from api import config, main
from api.services import continuity, continuity_sessions, hook_recall
from test_continuity import A_TURNS

URL = "/capture/hook-context"


def _hook():
    spec = importlib.util.spec_from_file_location("recall_hook_e2e", "api/hooks/recall.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HOOK = _hook()


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    write_session(memory, 1, A_TURNS)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    hook_recall.reset()
    continuity.reset()
    client = TestClient(main.app)
    token = tmp_path / "token"
    token.write_text("t")
    yield {"memory": memory, "client": client, "token": token, "log": tmp_path / "recall.log"}
    config.get_settings.cache_clear()


def _fire(env, harness, session, source):
    def post(url, body, token, timeout):
        r = env["client"].post(URL, content=body, headers={"Content-Type": "application/json"})
        return r.status_code, r.text

    payload = {"session_id": session, "hook_event_name": "SessionStart", "cwd": CWD}
    if source is not None:
        payload["source"] = source
    out = io.StringIO()
    HOOK.main(["--harness", harness], stdin=io.StringIO(json.dumps(payload)), stdout=out, environ={},
              post=post, log_path=env["log"], token_path=env["token"])
    return json.loads(out.getvalue())["hookSpecificOutput"]["additionalContext"] if out.getvalue() else ""


@pytest.mark.parametrize("harness", ["claude-code", "codex"])
@pytest.mark.parametrize("source, delivered", [("startup", True), ("clear", True), (None, False),
                                               ("resume", False), ("compact", False), ("fork", False)])
def test_only_startup_and_clear_get_the_block_through_the_real_hook(env, harness, source, delivered):
    session = sid(500 + ["claude-code", "codex"].index(harness) * 10
                  + ["startup", "clear", None, "resume", "compact", "fork"].index(source))
    note = _fire(env, harness, session, source)
    assert note, "the primer is always sent"
    assert ("Where the last session in this folder stopped" in note) is delivered
    row = continuity_sessions.get(env["memory"], harness, session, bank_paths=(env["memory"],)) or {}
    assert ("continues" in row) is delivered
    assert row.get("started_at")


def test_the_hook_forwards_source_only_on_session_start():
    sent = {}

    def post(url, body, token, timeout):
        sent.update(json.loads(body))
        return 200, json.dumps({"additionalContext": None, "reason": "no_match", "injected": []})

    import tempfile
    from pathlib import Path

    d = Path(tempfile.mkdtemp())
    (d / "t").write_text("t")
    HOOK.main(["--harness", "codex"], stdin=io.StringIO(json.dumps(
        {"session_id": sid(1), "hook_event_name": "UserPromptSubmit", "prompt": "hi", "source": "startup"})),
        stdout=io.StringIO(), environ={}, post=post, log_path=d / "l", token_path=d / "t")
    assert sent.get("source") is None
    HOOK.main(["--harness", "codex"], stdin=io.StringIO(json.dumps(
        {"session_id": sid(1), "hook_event_name": "SessionStart", "source": ["not", "text"]})),
        stdout=io.StringIO(), environ={}, post=post, log_path=d / "l", token_path=d / "t")
    assert sent.get("source") is None
