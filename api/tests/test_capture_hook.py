"""G105 R8/R14: the Stop hook never blocks the harness, never reads the
transcript, never prints to stdout, and never fires from Cicada's own CLI
spawns. Everything is injected; no network, no real home dir."""
from __future__ import annotations

import io
import json
from pathlib import Path

from api.hooks import capture as hook
from api.services.connections import base

SID = "11111111-2222-4333-8444-555555555555"
PAYLOAD = {"session_id": SID, "transcript_path": "/home/example/.claude/projects/x/" + SID + ".jsonl",
           "cwd": "/home/example/alpha-project", "hook_event_name": "Stop"}


def _run(tmp_path, payload, *, environ=None, post=None, argv=("--harness", "claude-code")):
    token = tmp_path / "api_token"
    token.write_text("tok-123")
    log = tmp_path / "logs" / "capture.log"
    calls = []

    def default_post(url, body, tok, timeout):
        calls.append((url, json.loads(body), tok, timeout))
        return 200, '{"status":"created"}'

    rc = hook.main(list(argv), stdin=io.StringIO(json.dumps(payload) if isinstance(payload, dict) else payload),
                   environ=environ or {}, post=post or default_post, log_path=log, token_path=token)
    return rc, calls, log


def test_posts_the_harness_fields_with_bearer_and_3s_timeout(tmp_path, capsys):
    rc, calls, log = _run(tmp_path, PAYLOAD, environ={"CICADA_PORT": "8123"})
    assert rc == 0
    url, body, tok, timeout = calls[0]
    assert url == "http://127.0.0.1:8123/capture/transcript"
    assert body == {"harness": "claude-code", "session_id": SID, "transcript_path": PAYLOAD["transcript_path"],
                    "cwd": PAYLOAD["cwd"], "hook_event": "Stop"}
    assert tok == "tok-123" and timeout == 3.0
    assert capsys.readouterr().out == ""  # a Stop hook's stdout is parsed by the harness
    line = log.read_text().strip().splitlines()[-1]
    assert "claude-code" in line and SID[:8] in line and "created" in line
    assert PAYLOAD["transcript_path"] not in line  # the log names sessions, never paths


def test_exits_zero_and_logs_when_capture_is_off(tmp_path):
    rc, calls, log = _run(tmp_path, PAYLOAD, environ={"CICADA_CAPTURE": "off"})
    assert rc == 0 and calls == []
    assert "CICADA_CAPTURE=off" in log.read_text()


def test_exits_zero_on_bad_stdin_missing_fields_missing_token_and_post_failure(tmp_path):
    assert _run(tmp_path, "{not json")[0] == 0
    rc, calls, log = _run(tmp_path, {"session_id": SID})
    assert rc == 0 and calls == [] and "no transcript_path" in log.read_text()

    def boom(*a):
        raise OSError("connection refused")

    rc, _, log = _run(tmp_path, PAYLOAD, post=boom)
    assert rc == 0 and "connection refused" in log.read_text()
    (tmp_path / "api_token").unlink()
    rc = hook.main(["--harness", "codex"], stdin=io.StringIO(json.dumps(PAYLOAD)), environ={},
                   post=lambda *a: (200, ""), log_path=tmp_path / "l.log", token_path=tmp_path / "api_token")
    assert rc == 0 and "no api_token" in (tmp_path / "l.log").read_text()


def test_harness_arg_is_forwarded(tmp_path):
    _, calls, _ = _run(tmp_path, PAYLOAD, argv=("--harness", "codex"))
    assert calls[0][1]["harness"] == "codex"


def test_log_is_private_and_rotates(tmp_path):
    log = tmp_path / "logs" / "capture.log"
    log.parent.mkdir()
    log.write_text("x" * (hook.LOG_MAX_BYTES + 1))
    _run(tmp_path, PAYLOAD)
    assert (tmp_path / "logs" / "capture.log.1").exists()
    assert oct(log.stat().st_mode & 0o777) == "0o600"


def test_cicada_cli_spawns_carry_capture_off(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    env = base.scrubbed_env()
    assert env["CICADA_CAPTURE"] == "off" and "ANTHROPIC_API_KEY" not in env


def test_hook_module_imports_nothing_from_api(tmp_path):
    src = Path(hook.__file__).read_text()
    assert "from api" not in src and "import api" not in src
