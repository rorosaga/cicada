"""G75 on the MCP surface: `initialize` returns `instructions`, the
`cicada_handshake` tool returns the same text, recall's hints carry the
now-view once per process, and `cicada_check_nudges` accepts `entity_ids`
(R12). Loads mcp/server.py the way test_mcp_inbox_questions.py does."""
from __future__ import annotations

import importlib.util
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from _synthetic_bank import _bank, _ok_repo, _settings

from api.services import markdown_parser, state_dictionary

REPO_ROOT = Path(__file__).resolve().parents[2]
TODAY = date(2026, 9, 3)
NOW = datetime(2026, 9, 3, 10, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def server():
    spec = importlib.util.spec_from_file_location("cicada_mcp_server_g75", REPO_ROOT / "mcp" / "server.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["cicada_mcp_server_g75"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def bank(tmp_path, monkeypatch, server):
    memory = _bank(tmp_path)
    state_dictionary.refresh(memory, _settings(memory), force=True, today=TODAY, now=NOW, repo_resolver=_ok_repo)
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_TELEMETRY", "off")
    monkeypatch.setattr(server, "get_memory_path", lambda: memory)
    monkeypatch.setattr(server, "_STATE_HINT_SENT", False)
    server.CLIENT_INFO.clear()
    return memory


def test_initialize_returns_instructions_and_captures_client_info(server, bank):
    result = server.initialize_result({"clientInfo": {"name": "claude-code", "version": "2.1"}})
    assert result["protocolVersion"] == "2024-11-05"
    assert result["serverInfo"]["name"] == "cicada-bookworm"
    assert server.CLIENT_INFO == {"name": "claude-code", "version": "2.1"}
    text = result["instructions"]
    assert text.startswith("# Cicada") and "## Claude Code" in text
    assert "`alpha-project`" in text and "cicada_check_nudges(entity_ids=" in text
    assert len(text) // 4 <= 1800


def test_initialize_without_client_info_is_generic(server, bank):
    result = server.initialize_result({})
    assert "## Your harness" in result["instructions"]


def test_initialize_with_no_state_file_still_answers(server, bank):
    (bank / "_state.md").unlink()
    result = server.initialize_result({"clientInfo": {"name": "codex-cli"}})
    assert "## Contract" in result["instructions"] and "no `_state.md` yet" in result["instructions"]


def test_handshake_tool_returns_the_same_text(server, bank):
    server.initialize_result({"clientInfo": {"name": "codex-cli"}})
    via_init = server.initialize_result({"clientInfo": {"name": "codex-cli"}})["instructions"]
    assert server.handle_tool("cicada_handshake", {}) == via_init
    tools = {t["name"]: t for t in server.TOOLS}
    assert "cicada_handshake" in tools and "instructions" in tools["cicada_handshake"]["description"]


def test_recall_hints_carry_the_state_once_per_process(server, bank, monkeypatch):
    monkeypatch.setattr(server, "_leann_search_entities", lambda *a, **k: [])
    monkeypatch.setattr(server, "_leann_search_episodes", lambda *a, **k: [])
    first = server.handle_recall("alpha project")
    assert "`" * 3 + "cicada-hints" in first
    assert '"state"' in first and '"alpha-project"' in first and '"pending": 1' in first
    second = server.handle_recall("alpha project")
    assert '"state"' not in second, "the cursor rides once per conversation"


def test_recall_with_nothing_to_suggest_emits_no_hints_block(server, bank, monkeypatch):
    monkeypatch.setattr(server, "_leann_search_entities", lambda *a, **k: [])
    monkeypatch.setattr(server, "_leann_search_episodes", lambda *a, **k: [])
    out = server.handle_recall("zzzz-nothing-matches-this")
    assert "`" * 3 + "cicada-hints" not in out
    assert server._STATE_HINT_SENT is False, "an unsent cursor is not consumed"


def test_check_nudges_accepts_entity_ids(server, bank):
    markdown_parser.write(bank / "inbox" / "inbox-003.md",
                          {"kind": "decay", "status": "pending", "entity_id": "bob-example",
                           "entity_name": "Bob Example", "title": "Still in touch with Bob?", "created_date": "2026-08-01"}, "c")
    out = server.handle_tool("cicada_check_nudges", {"entity_ids": ["bob-example"]})
    assert "inbox-003" in out and "inbox-001" not in out
    schema = {t["name"]: t for t in server.TOOLS}["cicada_check_nudges"]["inputSchema"]
    assert schema["properties"]["entity_ids"]["type"] == "array"
    both = server.handle_tool("cicada_check_nudges", {})
    assert "inbox-001" in both and "inbox-003" in both
