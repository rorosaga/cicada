"""Onboarding v3 (2026-10-24): the Agents step's "<Agent> just called me" reads a tool call, never a connect.

`GET /agents/wiring` runs `claude mcp get cicada`, which spawns the stdio server and sends `initialize` as Claude Code;
an agent starting a session does the same. Both move `lastSeenAt`. Only a `tools/call` (or a call through the tool
door) moves `lastCalledAt`, which is what the step watches.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from _stdio_server import stdio_server
from _synthetic_bank import _bank
from api import config
from api.services import agent_live, agent_seen


@pytest.fixture
def env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    bank = _bank(tmp_path)
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "cicada"))
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    monkeypatch.setenv("CICADA_TELEMETRY", "off")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    config.get_settings.cache_clear()
    agent_seen.reset()
    agent_live._TAIL.reset()
    yield {"home": home, "bank": bank}
    config.get_settings.cache_clear()


def _rows(env):
    return {r["id"]: r for r in agent_live.snapshot(home=env["home"], python="/x", repo=Path("/r"))["agents"]}


def test_a_connect_alone_is_seen_but_never_a_call(env):
    assert agent_seen.stamp_agent("claude-code", via="mcp")
    row = _rows(env)["claude-code"]
    assert row["last_seen_at"] and row["connected"]
    assert row["last_called_at"] is None


def test_a_stdio_tool_call_and_a_tool_door_call_are_calls(env):
    assert agent_seen.stamp_agent("claude-code", via="call")
    assert agent_seen.stamp_agent("codex", via="tool", device="abcd1234")
    rows = _rows(env)
    assert rows["claude-code"]["last_called_at"] and rows["codex"]["last_called_at"]
    assert rows["claude-code"]["via"] == "mcp", "a call is still an MCP sighting"
    assert rows["claude-code"]["last_seen_at"] == rows["claude-code"]["last_called_at"]


def test_a_tier_two_agents_call_lights_another_agent_too(env):
    agent_seen.stamp_agent("zed", via="call")
    rows = _rows(env)
    assert rows["other"]["last_called_at"] == rows["zed"]["last_called_at"]


def test_the_stdio_server_stamps_a_call_on_tools_call_and_never_on_initialize(env, monkeypatch):
    server = stdio_server()
    monkeypatch.setattr(server, "get_memory_path", lambda: env["bank"])
    monkeypatch.setattr(server, "_STATE_HINT_SENT", False)
    monkeypatch.setattr(server, "_backend_post", lambda path, payload: {"status": "resolved"})
    # What `claude mcp get cicada` (the wiring check) does: spawn, initialize as Claude Code, leave.
    server.initialize_result({"clientInfo": {"name": "claude-code", "version": "2.0"}})
    vias = {(r["agent"], r["via"]) for r in agent_seen.agents()}
    assert ("claude-code", "mcp") in vias
    assert not any(via == "call" for _, via in vias), "a wiring probe is never a call"
    assert _rows(env)["claude-code"]["last_called_at"] is None
    # The person's agent asks something.
    server.call_tool("cicada_recall", {"query": "alpha"})
    assert ("claude-code", "call") in {(r["agent"], r["via"]) for r in agent_seen.agents()}
    assert _rows(env)["claude-code"]["last_called_at"]


def test_the_wire_carries_last_called_at_additively(env):
    from api.models.schemas import AgentLiveResponse

    agent_seen.stamp_agent("codex", via="call")
    body = AgentLiveResponse(**agent_live.snapshot(home=env["home"], python="/x", repo=Path("/r"))).model_dump(
        by_alias=True)
    codex = next(a for a in body["agents"] if a["id"] == "codex")
    assert set(codex) == {"id", "connected", "lastSeenAt", "via", "lastCalledAt"}
    assert codex["lastCalledAt"]
