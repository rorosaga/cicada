"""G148: a recording tool joins the list when Cicada's own words name it, for a client known to re-read the list, and
every other client holds every tool from the start. Nothing is lost: a held-back tool still runs, and R12 holds."""
from __future__ import annotations

import inspect
import io
import json
import re

import pytest

from _stdio_server import stdio_server
from _synthetic_bank import _bank
from api import config
from api.services import handshake, mcp_tools, reading_prompt, recall_text, saved_lists, substack_lists, tool_offer, \
    youtube_lists


@pytest.fixture
def server(tmp_path, monkeypatch):
    bank = _bank(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_PORT", "1")
    for name in ("CLAUDE_CODE_SESSION_ID", "CICADA_SESSION_ID", "CICADA_SESSION_HARNESS", "CICADA_API_BASE",
                 "CICADA_ENGINE_SPAWN"):
        monkeypatch.delenv(name, raising=False)
    config.get_settings.cache_clear()
    module = stdio_server()
    monkeypatch.setattr(module, "get_memory_path", lambda: bank)
    monkeypatch.setattr(module, "CLIENT_INFO", {})
    monkeypatch.setattr(module, "_OPENED", set())
    yield module
    config.get_settings.cache_clear()


def _names(module, client):
    module.CLIENT_INFO.clear()
    if client is not None:
        module.CLIENT_INFO.update({"name": client, "version": "1"})
    return {t["name"] for t in module.tools_for_client()}


def _reply(text):
    return {"content": [{"type": "text", "text": text}]}


@pytest.mark.parametrize("client", ["claude-code", "Visual Studio Code", "gemini-cli-mcp-client"])
def test_a_client_that_re_reads_the_list_starts_without_the_recording_tools(server, client):
    assert not _names(server, client) & tool_offer.OPENED_BY_A_REPLY
    assert server.initialize_result({"clientInfo": {"name": client}})["capabilities"]["tools"] == {"listChanged": True}


@pytest.mark.parametrize("client", ["codex-mcp-client", "claude-ai", "cursor-vscode", "opencode", "something-new", None])
def test_any_other_client_holds_every_tool_and_is_promised_no_change(server, client):
    assert tool_offer.OPENED_BY_A_REPLY <= _names(server, client)
    params = {"clientInfo": {"name": client}} if client else {}
    assert server.initialize_result(params)["capabilities"]["tools"] == {}


def test_a_reply_naming_a_tool_offers_it_and_tells_the_client_once(server, monkeypatch):
    out = io.StringIO()
    monkeypatch.setattr("sys.stdout", out)
    _names(server, "claude-code")
    server._offer_what_was_named(_reply("Nothing here."))
    assert out.getvalue() == ""
    server._offer_what_was_named(_reply("record it with `cicada_record_read(url, outcome)`"))
    assert json.loads(out.getvalue())["method"] == "notifications/tools/list_changed"
    held = _names(server, "claude-code")
    assert "cicada_record_read" in held and "cicada_record_capture" not in held
    out.truncate(0), out.seek(0)
    server._offer_what_was_named(_reply("again `cicada_record_read`"))
    assert out.getvalue() == ""


def test_a_client_holding_everything_is_never_sent_a_notification(server, monkeypatch):
    out = io.StringIO()
    monkeypatch.setattr("sys.stdout", out)
    _names(server, "codex-mcp-client")
    server._offer_what_was_named(_reply("record it with `cicada_record_read(url, outcome)`"))
    assert out.getvalue() == ""


def test_a_held_back_tool_called_by_name_still_runs(server):
    _names(server, "claude-code")
    reply = server.call_tool("cicada_record_read", {"url": "https://bob-example.org/", "outcome": "failed"})
    assert "Unknown tool" not in reply["content"][0]["text"]


def test_a_job_s_first_tool_names_what_records_it():
    """The whole design rests on this: every held-back tool is named by a reply of a tool that stays listed."""
    source = {
        "cicada_record_read": mcp_tools.reading_queue,
        "cicada_record_check": mcp_tools.reading_queue,
        "cicada_record_youtube_list": youtube_lists.queue_lines,
        "cicada_record_saved_list": saved_lists.queue_lines,
        "cicada_record_substack_list": substack_lists.queue_lines,
        "cicada_record_refresh": mcp_tools.refresh_claim,
        "cicada_record_capture": mcp_tools.explore_claim,
    }
    assert set(source) == tool_offer.OPENED_BY_A_REPLY
    for tool, fn in source.items():
        assert tool in inspect.getsource(fn) or any(tool in inspect.getsource(h) for h in _helpers(fn)), tool


def _helpers(fn):
    module = inspect.getmodule(fn)
    called = set(re.findall(r"\b(_[a-z_]+)\(", inspect.getsource(fn)))
    return [getattr(module, name) for name in called if inspect.isfunction(getattr(module, name, None))]


def test_the_primer_of_a_client_that_re_reads_names_no_tool_it_does_not_hold(server, tmp_path, monkeypatch):
    from api.services import reading_settings

    monkeypatch.setattr(reading_settings, "agent_enabled", lambda: True)
    bank = server.get_memory_path()
    for client, kw in (("claude-code", {}), ("Visual Studio Code", {}), (None, {"variant": "claude-code"})):
        text, _ = handshake.load_or_build(bank, client, cache_dir=tmp_path / "cache", **kw)
        assert not tool_offer.named_in(text), client
        assert "cicada_reading_queue" in text
        assert len(text) // 4 <= handshake.MAX_TOKENS
    full, _ = handshake.load_or_build(bank, "codex-mcp-client", cache_dir=tmp_path / "cache")
    assert "cicada_record_read" in full


def test_the_hook_s_lines_name_only_what_stays_listed():
    assert not tool_offer.named_in(recall_text.reading_line(3))
    assert not tool_offer.named_in(recall_text.refresh_line(2))
    assert "cicada_record_read" in recall_text.reading_line(3, record=True)


def test_a_hand_off_prompt_names_the_queue_before_what_records_it():
    source = inspect.getsource(reading_prompt)
    assert source.index("cicada_reading_queue(limit)") < source.index("cicada_record_read(url")
