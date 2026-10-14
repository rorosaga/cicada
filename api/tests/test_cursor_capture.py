"""Capture-everywhere, hook side: Cursor's beforeSubmitPrompt/afterAgentResponse and
Gemini CLI's AfterAgent, from synthetic payloads in the documented shapes (Cursor
docs/hooks v1; Gemini CLI hooks reference; both checked 2026-10-14). No installed
Cursor or Gemini CLI was run: what each really sends is unverified, and the log
line is the signal the person's acting lead reads in the real app."""
from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.hooks import cursor_registry
from api.services import markdown_parser
from api.services import transcript_capture as tc

FIX = Path(__file__).parent / "fixtures"
PROMPT = json.loads((FIX / "cursor/before-submit-prompt-v1.json").read_text())
REPLY = json.loads((FIX / "cursor/after-agent-response-v1.json").read_text())
GEMINI = json.loads((FIX / "gemini/after-agent-v1.json").read_text())
PRIVATE = ("sentinel@", "must-not-open", "SECRET_ATTACHMENT")


def _load(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def cursor():
    return _load("cursor_capture_test_hook", "api/hooks/cursor.py")


def gemini():
    return _load("gemini_capture_test_hook", "api/hooks/capture.py")


def fire(tmp_path, payload, *, post=None, env=None, raw=None):
    sent = []

    def transport(url, body, token, timeout):
        sent.append((url, json.loads(body), timeout))
        return post(url, body, token, timeout) if post else (200, '{"status":"created"}')

    environ = {"HOME": str(tmp_path), "CICADA_HOME": str(tmp_path / "cicada"), "CICADA_API_TOKEN": "synthetic-token",
               "CICADA_PORT": "49178", **(env or {})}
    out = io.StringIO()
    rc = cursor().main(stdin=io.StringIO(raw if raw is not None else json.dumps(payload)), stdout=out,
                       environ=environ, post=transport)
    assert rc == 0
    return json.loads(out.getvalue()), sent


def _log(tmp_path) -> str:
    path = tmp_path / "cicada/logs/capture.log"
    return path.read_text() if path.exists() else ""


def test_the_prompt_hook_posts_only_the_turn_and_always_continues(tmp_path):
    out, [(url, body, timeout)] = fire(tmp_path, PROMPT)
    assert out == {"continue": True}
    assert url == "http://127.0.0.1:49178/capture/turn" and timeout < 2  # it holds the person's message
    assert body == {"harness": "cursor", "session_id": "cursor-synthetic-0001", "hook_event": "beforeSubmitPrompt",
                    "messages": [{"speaker": "user", "text": "Should alpha-project ship on Friday?"}],
                    "turn_id": "generation-synthetic-0001", "cwd": "/synthetic/alpha-project"}
    line = _log(tmp_path)
    assert "cursor cursor-s beforeSubmitPrompt http 200 created" in line
    assert not any(s in line + json.dumps(body) for s in PRIVATE) and "alpha-project ship" not in line


def test_the_reply_hook_posts_the_reply_and_its_model(tmp_path):
    out, [(_, body, _)] = fire(tmp_path, REPLY)
    assert out == {"continue": True}   # every output carries it; Cursor ignores it here
    assert body["messages"] == [{"speaker": "assistant", "text": "Yes, once the migration lands."}]
    assert body["model"] == "synthetic-model" and "transcript_path" not in body


@pytest.mark.parametrize("env", [{"CICADA_CAPTURE": "off"}, {"CURSOR_CODE_REMOTE": "true"}])
def test_capture_off_or_a_remote_session_posts_nothing(tmp_path, env):
    out, sent = fire(tmp_path, PROMPT, env=env)
    assert out == {"continue": True} and sent == []
    assert "skipped" in _log(tmp_path)


@pytest.mark.parametrize("change", [{"prompt": ""}, {"prompt": None}, {"conversation_id": "bad\nid"},
                                    {"conversation_id": None}])
def test_a_payload_without_words_or_a_safe_session_posts_nothing(tmp_path, change):
    out, sent = fire(tmp_path, {**PROMPT, **change})
    assert out == {"continue": True} and sent == []


def test_an_oversized_payload_posts_nothing_and_still_continues(tmp_path):
    raw = json.dumps({**PROMPT, "prompt": "plain words " * 100_000})
    assert len(raw) > 1024 * 1024
    out, sent = fire(tmp_path, None, raw=raw)
    assert out == {"continue": True} and sent == []
    line = _log(tmp_path)
    assert "payload too large" in line and "plain words" not in line


def test_a_prompt_first_payload_over_the_cap_still_continues(tmp_path):
    """Cursor may put the prompt before hook_event_name: past 1 MiB the event is
    never found, and the answer must still let the message through."""
    raw = '{"prompt": "' + "plain words " * 100_000 + '", "hook_event_name": "beforeSubmitPrompt"}'
    assert len(raw) > 1024 * 1024 and raw.index("hook_event_name") > 1024 * 1024
    out, sent = fire(tmp_path, None, raw=raw)
    assert out == {"continue": True} and sent == []


@pytest.mark.parametrize("raw", [b'{"hook_event_name": "beforeSubmitPrompt", "prompt": "caf\xff"}', b"\xff\xfe",
                                 b"[]", b"not json"])
def test_an_unreadable_payload_still_continues(tmp_path, raw):
    def forbidden(*a, **k):
        pytest.fail("an unreadable payload must not post")
    out = io.StringIO()
    stdin = io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8")   # strict, like Python's own stdin
    assert cursor().main(stdin=stdin, stdout=out, environ={"CICADA_HOME": str(tmp_path / "cicada")},
                         post=forbidden) == 0
    assert json.loads(out.getvalue()) == {"continue": True}


def test_a_long_turn_is_trimmed_before_it_is_posted(tmp_path):
    hook = cursor()
    _, [(_, body, _)] = fire(tmp_path, {**PROMPT, "prompt": "plain words " * 30_000})
    assert len(body["messages"][0]["text"]) == hook.TEXT_MAX_CHARS


def test_a_backend_that_is_down_fails_open_without_logging_content(tmp_path):
    def down(*a):
        raise OSError("PRIVATE_SENTINEL refused")
    out, _ = fire(tmp_path, PROMPT, post=down)
    assert out == {"continue": True}
    assert "error: OSError" in _log(tmp_path) and "PRIVATE_SENTINEL" not in _log(tmp_path)


def test_a_validation_error_never_puts_the_turn_in_the_log(tmp_path):
    echo = json.dumps({"detail": [{"input": "Should alpha-project ship on Friday?"}]})
    fire(tmp_path, PROMPT, post=lambda *a: (422, echo))
    assert "http 422" in _log(tmp_path) and "alpha-project" not in _log(tmp_path)


def test_hook_to_route_a_conversation_is_one_episode_and_a_refire_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(tc, "_episode_cache", {})
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.delenv("CICADA_MEMORY_PATH", raising=False)
    monkeypatch.setenv("CICADA_MEMORY_ROOT", str(root))
    config.get_settings.cache_clear()
    client = TestClient(main.app)

    def post(url, body, token, timeout):
        r = client.post("/capture/turn", content=body, headers={"Content-Type": "application/json"})
        return r.status_code, r.text

    try:
        second = {"generation_id": "generation-synthetic-0002"}
        for payload in (PROMPT, REPLY, {**PROMPT, **second, "prompt": "And the review?"},
                        {**REPLY, **second, "text": "It is the last blocker."}):
            fire(tmp_path, payload, post=post)
        (path,) = sorted((root / "episodes").glob("ep_*.md"))
        before = path.read_bytes()
        fire(tmp_path, REPLY, post=post)           # a re-fire of an earlier reply
        assert path.read_bytes() == before
        ep = markdown_parser.parse(path)
        assert ep.body == ("user: Should alpha-project ship on Friday?\nassistant: Yes, once the migration lands.\n"
                           "user: And the review?\nassistant: It is the last blocker.")
        assert ep.frontmatter["harness"] == "cursor" and ep.frontmatter["session_id"] == "cursor-synthetic-0001"
        assert not any(s in path.read_text() for s in PRIVATE)
        assert _log(tmp_path).count("http 200") == 5 and "unchanged" in _log(tmp_path)
    finally:
        config.get_settings.cache_clear()


# --- registration ---------------------------------------------------------------------

CMD = "'/synthetic/python' '/synthetic/cicada/api/hooks/cursor.py'"


def test_capture_install_and_uninstall_keep_every_other_tools_hooks(tmp_path):
    p = tmp_path / ".cursor/hooks.json"
    p.parent.mkdir()
    foreign = {"version": 1, "custom": {"keep": True}, "hooks": {
        "beforeSubmitPrompt": [{"command": "/opt/other-tool/hook prompt", "timeout": 10}],
        "afterAgentResponse": [{"command": "/opt/other-tool/hook reply"}],
        "stop": [{"command": "/opt/other-tool/hook stop"}]}}
    p.write_text(json.dumps(foreign))
    assert cursor_registry.install(p, command=CMD, hook="capture") == "added"
    assert cursor_registry.install(p, command=CMD, hook="capture") == "present"
    assert cursor_registry.install(p, command=CMD) == "added"   # startup is its own switch
    data = json.loads(p.read_text())
    assert data["hooks"]["beforeSubmitPrompt"] == [foreign["hooks"]["beforeSubmitPrompt"][0], {"command": CMD, "timeout": 2}]
    assert data["hooks"]["afterAgentResponse"] == [foreign["hooks"]["afterAgentResponse"][0], {"command": CMD, "timeout": 5}]
    assert data["hooks"]["stop"] == foreign["hooks"]["stop"]  # never a stop hook of ours
    assert cursor_registry.status(p, command=CMD, hook="capture") == "present"
    assert cursor_registry.uninstall(p, hook="startup") == 1
    assert cursor_registry.status(p, command=CMD, hook="capture") == "present"
    assert cursor_registry.uninstall(p, hook="capture") == 2
    assert json.loads(p.read_text()) == foreign


def test_a_moved_checkout_reads_stale_and_updates_in_place(tmp_path):
    p = tmp_path / "hooks.json"
    cursor_registry.install(p, command=CMD, hook="capture")
    moved = "'/elsewhere/python' '/elsewhere/cicada/api/hooks/cursor.py'"
    assert cursor_registry.status(p, command=moved, hook="capture") == "stale"
    assert cursor_registry.install(p, command=moved, hook="capture") == "updated"
    hooks = json.loads(p.read_text())["hooks"]
    assert [e["command"] for e in hooks["beforeSubmitPrompt"] + hooks["afterAgentResponse"]] == [moved, moved]
    assert cursor_registry.uninstall(p) == 2 and not p.read_text().count("cursor.py")


def test_the_registry_cli_takes_the_hook_group(tmp_path, capsys):
    p = tmp_path / "hooks.json"
    assert cursor_registry.main(["install", "--settings", str(p), "--command", CMD, "--hook", "capture"]) == 0
    assert cursor_registry.main(["status", "--settings", str(p), "--command", CMD, "--hook", "capture"]) == 0
    assert cursor_registry.main(["status", "--settings", str(p), "--command", CMD]) == 1  # startup still off
    assert cursor_registry.main(["uninstall", "--settings", str(p), "--hook", "capture"]) == 0
    assert "removed 2" in capsys.readouterr().out


# --- Gemini CLI -------------------------------------------------------------------------


def gfire(tmp_path, payload=None, *, raw=None, env=None, harness="gemini-cli"):
    sent = []
    token = tmp_path / "api_token"
    token.write_text("synthetic-token")
    out = io.StringIO()
    rc = gemini().main(["--harness", harness], stdin=io.StringIO(raw if raw is not None else json.dumps(payload)),
                       stdout=out, environ={"CICADA_PORT": "49178", **(env or {})},
                       post=lambda url, body, tok, timeout: (sent.append((url, json.loads(body))) or
                                                              (200, '{"status":"created"}')),
                       log_path=tmp_path / "capture.log", token_path=token)
    assert rc == 0
    return out.getvalue(), sent, (tmp_path / "capture.log").read_text()


def test_gemini_after_agent_posts_the_exchange_and_prints_json(tmp_path):
    out, [(url, body)], log = gfire(tmp_path, GEMINI)
    assert json.loads(out) == {} and url == "http://127.0.0.1:49178/capture/turn"
    assert body == {"harness": "gemini-cli", "session_id": "gemini-synthetic-0001",
                    "messages": [{"speaker": "user", "text": "Summarise alpha-project"},
                              {"speaker": "assistant", "text": "It ships on Friday."}],
                    "retry": False, "cwd": "/synthetic/alpha-project", "hook_event": "AfterAgent"}
    assert "gemini-cli gemini-s AfterAgent http 200 created" in log and "must-not-open" not in log + json.dumps(body)


@pytest.mark.parametrize("payload,env,why", [
    (GEMINI, {"CICADA_CAPTURE": "off"}, "CICADA_CAPTURE=off"),
    ({**GEMINI, "hook_event_name": "BeforeAgent"}, {}, "not an AfterAgent payload"),
    ({**GEMINI, "prompt": "", "prompt_response": ""}, {}, "no prompt"),
])
def test_gemini_posts_nothing_when_off_or_not_an_exchange(tmp_path, payload, env, why):
    out, sent, log = gfire(tmp_path, payload, env=env)
    assert json.loads(out) == {} and sent == [] and why in log


def test_gemini_oversized_payload_posts_nothing(tmp_path):
    raw = json.dumps({**GEMINI, "prompt": "plain words " * 100_000})
    out, sent, log = gfire(tmp_path, raw=raw)
    assert json.loads(out) == {} and sent == [] and "payload too large" in log and "plain words" not in log


def test_the_claude_code_stop_hook_still_prints_nothing(tmp_path):
    out, sent, _ = gfire(tmp_path, {"session_id": "claude-synthetic-0001", "hook_event_name": "Stop"},
                         harness="claude-code")
    assert out == "" and sent == []
