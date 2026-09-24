"""G149 R-H6/R-H10/R-H15 — the recall hook never blocks or erases a prompt,
prints only the one JSON object both harnesses parse, and never writes the
prompt anywhere. Everything is injected; no network, no real home dir."""
from __future__ import annotations

import io
import json
from pathlib import Path

from api.hooks import recall as hook

SID = "11111111-2222-4333-8444-555555555555"
PROMPT = "How is the Alpha Project going?"
UPS = {"session_id": SID, "hook_event_name": "UserPromptSubmit", "cwd": "/home/example/alpha-project",
       "transcript_path": f"/home/example/.claude/projects/x/{SID}.jsonl", "prompt": PROMPT}
START = {"session_id": SID, "hook_event_name": "SessionStart", "source": "startup", "model": "claude-example-1"}
NOTE = "From Cicada (the person's memory; added by Cicada's hook, not typed by them) — …"


def _run(tmp_path, payload, *, environ=None, post=None, argv=("--harness", "claude-code"), reply=None):
    token = tmp_path / "api_token"
    token.write_text("tok-123")
    log = tmp_path / "logs" / "recall.log"
    out = io.StringIO()
    calls = []

    def default_post(url, body, tok, timeout):
        calls.append((url, json.loads(body), tok, timeout))
        return 200, json.dumps(reply if reply is not None else
                               {"additionalContext": NOTE, "injected": ["alpha-project"], "reason": "injected",
                                "latencyMs": 12})

    stdin = io.StringIO(json.dumps(payload) if isinstance(payload, (dict, list)) else payload)
    rc = hook.main(list(argv), stdin=stdin, stdout=out, environ=environ or {}, post=post or default_post,
                   log_path=log, token_path=token)
    return rc, calls, out.getvalue(), log


def test_a_prompt_travels_as_a_json_body_and_the_note_prints_in_the_shared_shape(tmp_path):
    rc, calls, out, log = _run(tmp_path, UPS, environ={"CICADA_PORT": "8123"})
    assert rc == 0
    url, body, tok, timeout = calls[0]
    assert url == "http://127.0.0.1:8123/capture/hook-context"
    assert body == {"event": "user_prompt_submit", "harness": "claude-code", "session_id": SID,
                    "cwd": UPS["cwd"], "model": None, "prompt": PROMPT}
    assert tok == "tok-123" and timeout == hook.TIMEOUT_S and hook.TIMEOUT_S <= 0.9
    assert json.loads(out) == {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": NOTE}}
    line = log.read_text()
    assert "user_prompt_submit" in line and "injected" in line and "pages=1" in line and "ms" in line
    assert "Alpha" not in line and "alpha-project" not in line and UPS["cwd"] not in line


def test_session_start_sends_no_prompt_and_forwards_the_model(tmp_path):
    _, calls, out, _ = _run(tmp_path, START)
    assert calls[0][1] == {"event": "session_start", "harness": "claude-code", "session_id": SID, "cwd": None,
                           "model": "claude-example-1", "prompt": None}
    assert json.loads(out)["hookSpecificOutput"]["hookEventName"] == "SessionStart"


def test_nothing_to_say_prints_nothing(tmp_path):
    rc, _, out, log = _run(tmp_path, UPS, reply={"additionalContext": None, "injected": [], "reason": "no_match",
                                                 "latencyMs": 3})
    assert (rc, out) == (0, "") and "no_match" in log.read_text()


def test_capture_off_and_recall_off_exit_before_any_request(tmp_path):
    for env, why in (({"CICADA_CAPTURE": "off"}, "CICADA_CAPTURE=off"), ({"CICADA_RECALL": "OFF"}, "CICADA_RECALL=off")):
        rc, calls, out, log = _run(tmp_path, UPS, environ=env)
        assert (rc, calls, out) == (0, [], "") and why in log.read_text()


def test_a_codex_sub_agent_prompt_is_skipped(tmp_path):
    rc, calls, out, log = _run(tmp_path, {**UPS, "agent_id": "a1", "agent_type": "explorer"},
                               argv=("--harness", "codex"))
    assert (rc, calls, out) == (0, [], "") and "sub-agent" in log.read_text()


def test_every_failure_exits_zero_prints_nothing_and_logs_no_words(tmp_path):
    for payload in ("{not json", [1, 2], {**UPS, "hook_event_name": "Stop"}, {**UPS, "session_id": ""}):
        rc, calls, out, _ = _run(tmp_path, payload)
        assert (rc, calls, out) == (0, [], "")

    def boom(url, body, tok, timeout):
        raise OSError(f"connection refused while sending {PROMPT}")

    rc, _, out, log = _run(tmp_path, UPS, post=boom)
    assert (rc, out) == (0, "") and "error: OSError" in log.read_text() and PROMPT not in log.read_text()
    rc, _, out, log = _run(tmp_path, UPS, post=lambda *a: (422, json.dumps({"detail": [{"input": PROMPT}]})))
    assert (rc, out) == (0, "") and "http 422" in log.read_text() and PROMPT not in log.read_text()
    rc, _, out, _ = _run(tmp_path, UPS, post=lambda *a: (200, "not json"))
    assert (rc, out) == (0, "")
    (tmp_path / "api_token").unlink()
    rc = hook.main(["--harness", "codex"], stdin=io.StringIO(json.dumps(UPS)), stdout=io.StringIO(), environ={},
                   post=lambda *a: (200, "{}"), log_path=tmp_path / "l.log", token_path=tmp_path / "api_token")
    assert rc == 0 and "no api_token" in (tmp_path / "l.log").read_text()


def test_the_env_token_wins_over_the_file(tmp_path):
    _, calls, _, _ = _run(tmp_path, UPS, environ={"CICADA_API_TOKEN": "env-tok"})
    assert calls[0][2] == "env-tok"


def test_a_long_prompt_is_windowed_before_it_leaves(tmp_path):
    long = "lorem " * 5000 + "so how is the alpha project?"
    _, calls, _, _ = _run(tmp_path, {**UPS, "prompt": long})
    sent = calls[0][1]["prompt"]
    assert len(sent) == hook.HEAD_CHARS + 1 + hook.TAIL_CHARS and sent.endswith("alpha project?")


def test_a_codex_payload_forwards_its_model(tmp_path):
    payload = {**UPS, "turn_id": "t1", "model": "gpt-example", "permission_mode": "default"}
    _, calls, _, _ = _run(tmp_path, payload, argv=("--harness", "codex"))
    assert calls[0][1]["harness"] == "codex" and calls[0][1]["model"] == "gpt-example"


def test_a_reason_that_is_not_an_enum_is_not_logged(tmp_path):
    _, _, _, log = _run(tmp_path, UPS, reply={"additionalContext": None, "injected": [], "reason": PROMPT})
    assert PROMPT not in log.read_text() and "other" in log.read_text()


def test_log_is_private_and_rotates(tmp_path):
    log = tmp_path / "logs" / "recall.log"
    log.parent.mkdir()
    log.write_text("x" * (hook.LOG_MAX_BYTES + 1))
    _run(tmp_path, UPS)
    assert (tmp_path / "logs" / "recall.log.1").exists()
    assert oct(log.stat().st_mode & 0o777) == "0o600"


def test_the_hook_imports_nothing_from_api():
    src = Path(hook.__file__).read_text()
    assert "from api" not in src and "import api" not in src
