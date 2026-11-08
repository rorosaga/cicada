"""ROR-139 — the signed-in plan account never comes back out of a child `claude -p` run (reply or tool input).

Placeholder address only; no CLI is spawned (the runner is injected, the account reader is swapped)."""
from __future__ import annotations

import json

import pytest

from api.services import agent_engine, engine_errors, engine_identity
from api.services.connections.base import CliResult

ACCOUNT = "anna.may77@example.com"


@pytest.fixture(autouse=True)
def _account(monkeypatch):
    monkeypatch.setattr(engine_identity, "reader", lambda: frozenset({ACCOUNT}))
    engine_identity.clear()
    yield
    engine_identity.clear()


def _runner(result_text: str, search_query: str | None = None):
    def run(argv, **kw):
        lines = []
        if search_query is not None:
            lines.append({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "WebSearch", "input": {"query": search_query}}]}})
        lines.append({"type": "result", "subtype": "success", "is_error": False, "result": result_text,
                      "usage": {}, "modelUsage": {}})
        return CliResult(0, "\n".join(json.dumps(x) for x in lines), "")
    return run


def _call(runner, text="What is the capital of France?", **kw):
    return agent_engine.complete(messages=[{"role": "user", "content": text}], model="haiku", runner=runner, **kw)


def test_a_reply_naming_the_account_is_discarded():
    with pytest.raises(engine_errors.EngineProtocolError):
        _call(_runner("The user is Anna May."))
    with pytest.raises(engine_errors.EngineProtocolError):
        _call(_runner(f"Contact {ACCOUNT}."))


def test_a_search_query_naming_the_account_voids_the_call():
    with pytest.raises(engine_errors.EngineProtocolError):
        _call(_runner("Paris.", search_query="anna may profile"), policy=agent_engine.CallPolicy(web_search=True))


def test_a_clean_reply_and_query_pass():
    env = _call(_runner("Paris.", search_query="capital of France"), policy=agent_engine.CallPolicy(web_search=True))
    assert env["result"] == "Paris."


def test_a_name_the_request_itself_says_is_kept():
    env = _call(_runner("Anna May wrote it."), text="Who wrote the note? Anna May did.")
    assert env["result"] == "Anna May wrote it."


def test_no_account_read_means_no_check():
    engine_identity.reader = lambda: frozenset()
    engine_identity.clear()
    assert _call(_runner("The user is Anna May."))["result"]


def test_a_given_name_alone_read_out_of_the_address_voids_the_call():
    with pytest.raises(engine_errors.EngineProtocolError):
        _call(_runner("Hi Anna, the capital is Paris."))
    with pytest.raises(engine_errors.EngineProtocolError):
        _call(_runner("Paris.", search_query="Anna capital of France"), policy=agent_engine.CallPolicy(web_search=True))


def test_a_given_name_the_request_says_is_kept_and_a_longer_word_is_not_it():
    assert _call(_runner("Anna wrote it."), text="Who wrote the note? Anna did.")["result"]
    assert _call(_runner("Annabelle wrote it."))["result"]


def test_a_child_run_keeps_every_lock_and_the_plan(fake_cli, claude_stream, monkeypatch):
    """A real subprocess through the one door: no user or project context, no MCP, no tools, no hooks of Cicada's own
    capture or recall, and no key (so the call stays on the person's plan)."""
    read_seen = fake_cli("claude", claude_stream("success"),
                         watch=("CICADA_CAPTURE", "CICADA_RECALL", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "leak")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "leak")
    agent_engine.complete(messages=[{"role": "user", "content": "hello"}], model="haiku")
    [seen] = read_seen()
    argv = seen["argv"]
    assert "--safe-mode" in argv and "--strict-mcp-config" in argv and "--no-session-persistence" in argv
    assert argv[argv.index("--setting-sources") + 1] == "" and argv[argv.index("--tools") + 1] == ""
    assert not any(a in argv for a in ("--bare", "--mcp-config", "--add-dir", "--append-system-prompt"))
    assert any(a.startswith("--system-prompt=") for a in argv)
    assert seen["env"] == {"CICADA_CAPTURE": "off", "CICADA_RECALL": "off",
                           "ANTHROPIC_API_KEY": None, "ANTHROPIC_AUTH_TOKEN": None}
