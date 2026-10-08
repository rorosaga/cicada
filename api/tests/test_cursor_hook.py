"""Cursor docs/hooks v1, checked 2026-10-08. Synthetic; no installed Cursor.

Nullable transcript_path proves neither confinement nor final-message format.
Only local interactive sessionStart is supported; stop must never capture.
"""
import importlib.util
import io
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from _continuity_fixtures import write_session
from api import config, main
from api.services import continuity, continuity_sessions, hook_recall
from test_continuity import A_TURNS

FIXTURE = Path(__file__).parent / "fixtures/cursor/session-start-v1.json"


def hook():
    spec = importlib.util.spec_from_file_location("cursor_test_hook", "api/hooks/cursor.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fire(tmp_path, monkeypatch, payload=None, post=None, extra_env=None):
    mod = hook()
    observed = []
    monkeypatch.setattr(mod, "observe_if_needed", lambda cwd, **kw: observed.append(cwd))
    sent = []
    def transport(url, body, token, timeout):
        sent.append((url, json.loads(body), token, timeout))
        if post:
            return post(url, body, token, timeout)
        return 200, json.dumps({"additionalContext": "light pointer", "reason": "primer", "injected": []})
    env = {"HOME": str(tmp_path), "CICADA_HOME": str(tmp_path / "cicada"),
           "CICADA_API_TOKEN": "synthetic-token", "CICADA_PORT": "49178", "PATH": "",
           **(extra_env or {})}
    out = io.StringIO()
    rc = mod.main(stdin=io.StringIO(json.dumps(payload if payload is not None else json.loads(FIXTURE.read_text()))),
                  stdout=out, environ=env, post=transport)
    assert rc == 0
    return json.loads(out.getvalue()), sent, observed


def test_documented_startup_schema_allowlists_values(tmp_path, monkeypatch):
    payload = json.loads(FIXTURE.read_text())
    payload.update(transcript_path="/outside/must-not-open.jsonl", arbitrary="SECRET_EXTRA", cwd="/wrong-hook-cwd")
    out, sent, observed = fire(tmp_path, monkeypatch, payload,
                               extra_env={"CURSOR_USER_EMAIL": "environment@example.invalid"})
    assert out == {"additional_context": "light pointer"}
    [(url, body, token, timeout)] = sent
    assert url == "http://127.0.0.1:49178/capture/hook-context" and timeout <= 0.9
    assert body == {"event": "session_start", "harness": "cursor", "session_id": payload["conversation_id"],
                    "cwd": "/synthetic/alpha-project", "source": "startup"}
    assert observed == [body["cwd"]]
    assert token == "synthetic-token"
    logs = "".join(p.read_text() for p in (tmp_path / "cicada/logs").glob("*"))
    assert not any(s in logs + json.dumps(body) for s in ("sentinel@", "environment@", "SECRET_EXTRA", "must-not-open", "synthetic-model"))


@pytest.mark.parametrize("change", [{"hook_event_name": "stop"}, {"hook_event_name": "afterAgentResponse"},
    {"hook_event_name": "beforeSubmitPrompt"}, {"is_background_agent": True},
    {"is_background_agent": "false"}, {"session_id": "different-session"}, {"conversation_id": "bad\nvalue"}])
def test_unsupported_events_and_unsafe_sessions_never_post(tmp_path, monkeypatch, change):
    payload = {**json.loads(FIXTURE.read_text()), **change, "transcript_path": "/outside/unreadable.jsonl"}
    out, sent, observed = fire(tmp_path, monkeypatch, payload)
    assert out == {} and sent == [] and observed == []


@pytest.mark.parametrize("key", ["CICADA_CAPTURE", "CICADA_RECALL", "CURSOR_CODE_REMOTE"])
def test_disabled_or_remote_never_post(tmp_path, monkeypatch, key):
    out, sent, observed = fire(tmp_path, monkeypatch, extra_env={key: "true" if key == "CURSOR_CODE_REMOTE" else "off"})
    assert out == {} and sent == [] and observed == []


@pytest.mark.parametrize("roots", [[], ["/synthetic/a", "/synthetic/b"], ["relative"], ["/bad\nroot"]])
def test_no_single_valid_workspace_gets_primer_without_guessing_cwd(tmp_path, monkeypatch, roots):
    out, sent, observed = fire(tmp_path, monkeypatch, {**json.loads(FIXTURE.read_text()), "workspace_roots": roots})
    assert out == {"additional_context": "light pointer"}
    assert sent[0][1]["cwd"] is None and observed == []


@pytest.mark.parametrize("status,text", [(401, '{"echo":"sentinel@example.invalid"}'), (200, "not json"),
                                      (200, '{"additionalContext":null}')])
def test_empty_error_or_invalid_response_is_empty_output(tmp_path, monkeypatch, status, text):
    out, _, _ = fire(tmp_path, monkeypatch, post=lambda *a: (status, text))
    assert out == {}


@pytest.mark.parametrize("raw", ["not json", "[]", "x" * (64 * 1024 + 1)])
def test_malformed_or_oversized_input_fails_open(tmp_path, raw):
    out = io.StringIO()
    def forbidden(*a, **k):
        pytest.fail("invalid payload must not post")
    assert hook().main(stdin=io.StringIO(raw), stdout=out, environ={"CICADA_HOME":str(tmp_path)}, post=forbidden) == 0
    assert json.loads(out.getvalue()) == {}


def test_timeout_does_not_print_private_exception_text(tmp_path, monkeypatch):
    def timeout(*a):
        raise TimeoutError("PRIVATE_SENTINEL")
    out, _, _ = fire(tmp_path, monkeypatch, post=timeout)
    assert out == {}
    assert "PRIVATE_SENTINEL" not in (tmp_path / "cicada/logs/recall.log").read_text()


@pytest.mark.parametrize("source_harness", ["claude-code", "codex"])
def test_real_hook_route_light_pointer_and_registry_only(tmp_path, monkeypatch, source_harness):
    memory = tmp_path / "bank"
    (memory / "episodes").mkdir(parents=True)
    write_session(memory, 1, A_TURNS, harness=source_harness, cwd="/synthetic/alpha-project")
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "cicada"))
    config.get_settings.cache_clear()
    continuity.reset(); hook_recall.reset()
    client = TestClient(main.app)
    def post(url, body, token, timeout):
        r = client.post("/capture/hook-context", content=body, headers={"Content-Type": "application/json"})
        return r.status_code, r.text
    try:
        out, _, _ = fire(tmp_path, monkeypatch, post=post)
        text = out["additional_context"]
        assert 'cicada_continue(session="ep_' in text and len(text) // 4 <= 1800
        assert A_TURNS[0][1] not in text
        row = continuity_sessions.get(memory, "cursor", "cursor-synthetic-0001", bank_paths=(memory,))
        assert row["continues"].startswith("ep_") and row["started_at"] and row["cwd_hash"]
        from _stdio_server import stdio_server
        server = stdio_server()
        monkeypatch.setattr(server, "SESSION", server.SessionIdentity(harness="generic", session_id="synthetic-mcp-session",
                                                                      project_dir="/synthetic/unknown-gui-cwd"))
        episode = re.search(r'cicada_continue\(session="([^"]+)"\)', text).group(1)
        history = server.handle_tool("cicada_continue", {"session": episode})
        assert A_TURNS[0][1] in history and "quoted as history" in history
        assert "test_alpha_roundtrip" in history and episode in history
        assert len(list((memory / "episodes").glob("ep_*"))) == 1
        r = client.post("/capture/transcript", json={"harness": "cursor", "session_id": "cursor-synthetic-0001",
                                                  "transcript_path": "/outside/unreadable.jsonl"})
        assert r.status_code == 422, "startup support must not open capture ingress"
    finally:
        config.get_settings.cache_clear(); continuity.reset(); hook_recall.reset()
