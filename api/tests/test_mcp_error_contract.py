"""G199 / G200 A7, A9 / Hyrum audit A1, A4, A6: the MCP tool-call contract, on both doors.

A refusal says so (`isError: true` with `structuredContent`), a bad argument is refused with its field named, an
exception never carries Python's message, a digit string still reads as an integer for one release (with a note),
a read reply is reference data on both doors, and the handshake picks its variant by exact client name.
"""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from _stdio_server import stdio_server
from _synthetic_bank import _bank
from api import config
from api.cli_types import EXIT_CODES, REFUSAL_CODES, Result
from api.remote import app as remote_app
from api.remote import catalog, store
from api.remote import tools as remote_tools
from api.remote.runtime import RemoteRuntime
from api.services import handshake, mcp_tools, tool_contract, tool_door

H = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json",
     "Mcp-Protocol-Version": "2025-11-25"}


@pytest.fixture
def memory(tmp_path, monkeypatch):
    bank = _bank(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    config.get_settings.cache_clear()
    yield bank
    config.get_settings.cache_clear()


@pytest.fixture
def srv(memory, monkeypatch):
    server = stdio_server()
    monkeypatch.setattr(server, "get_memory_path", lambda: memory)
    monkeypatch.setattr(server, "_STATE_HINT_SENT", False)
    monkeypatch.setattr(server, "_backend_post", lambda path, payload: {"status": "resolved"})
    return server


def _remote(memory):
    return RemoteRuntime(post=lambda p, d: {"status": "resolved"}, sleep_running=lambda: False)


def _connector(scopes=catalog.SCOPES):
    return catalog.Connector(id="ab12cd34", label="Phone", app="claude", scopes=frozenset(scopes),
                             created_at="2026-09-01T00:00:00+00:00", last_client="claude-ai")


def _text(result: dict) -> str:
    return result["content"][0]["text"]


# --- the argument check --------------------------------------------------------------------------------------------

def test_each_kind_of_bad_argument_is_named():
    schema = {"type": "object", "required": ["query"], "properties": {
        "query": {"type": "string"}, "top_k": {"type": "integer"}, "mode": {"type": "string", "enum": ["ask", "list"]},
        "ids": {"type": "array", "items": {"type": "string"}, "maxItems": 2}, "skip": {"type": "boolean"}}}
    got = tool_contract.check("t", schema, {"top_k": "lots", "mode": "all", "ids": ["a", 3, "c"], "skip": 1})
    assert got.error == ("Invalid arguments: `top_k` must be an integer (got the string \"lots\"); `mode` must be one "
                         "of `ask`, `list` (got the string \"all\"); `ids` holds at most 2 items (got 3); `ids[1]` must "
                         "be a string (got 3); `skip` must be true or false (got 1); `query` is required.")


def test_the_one_release_leniency_reads_digits_and_says_so():
    schema = {"type": "object", "properties": {"top_k": {"type": "integer"}, "skip": {"type": "boolean"},
                                               "since": {"type": "string"}}}
    got = tool_contract.check("t", schema, {"top_k": " 5 ", "skip": "false", "since": None, "conversation": "rc_x"})
    assert got.error is None and got.arguments == {"top_k": 5, "skip": False}
    assert [w.split(" ")[0] for w in got.warnings] == ["`top_k`", "`skip`", "`conversation`"]
    assert "refused from the next release" in got.warnings[0] and "not used" in got.warnings[2]


def test_the_leniency_lasts_one_release():
    from api.version import read_version

    assert read_version() == tool_contract.LENIENT_RELEASE, (
        "G199: the release after 0.6.0 refuses a digit or true/false string where the schema says integer or boolean. "
        "Remove the two lenient branches in tool_contract._value and this test, and the TODO.md line that dates them.")


def test_an_unlisted_alias_reaches_its_argument():
    schema = {"type": "object", "properties": {"id": {"type": "string"}}}
    got = tool_contract.check("cicada_resolve_inbox", schema, {"item_id": "inbox-001"})
    assert got.arguments == {"id": "inbox-001"} and not got.warnings and got.error is None


@pytest.mark.parametrize("since, ok", [("7", True), ("7d", True), (30, True), ("2026-09-01", True),
                                       ("last tuesday", False), ("yesterday", False)])
def test_since_is_a_date_or_a_number_of_days(since, ok):
    got = tool_contract.check("cicada_timeline", {"type": "object", "properties": {"since": tool_contract.SINCE_SCHEMA}},
                              {"since": since})
    assert (got.error is None) is ok


def _shared_scalar_args():
    stdio = {t["name"]: t["inputSchema"] for t in stdio_server().TOOLS}
    for name, tool in remote_tools.REMOTE_TOOLS.items():
        for prop, spec in (tool["inputSchema"].get("properties") or {}).items():
            other = (stdio.get(name, {}).get("properties") or {}).get(prop)
            if other is not None and spec.get("type") in ("integer", "boolean"):
                yield name, prop, spec["type"], stdio[name], tool["inputSchema"]


@pytest.mark.parametrize("name, prop, kind, stdio_schema, remote_schema", list(_shared_scalar_args()))
def test_both_doors_refuse_the_same_bad_value(name, prop, kind, stdio_schema, remote_schema):
    bad = {"integer": "lots", "boolean": "maybe"}[kind]
    for schema in (stdio_schema, remote_schema):
        got = tool_contract.check(name, schema, {prop: bad})
        assert f"`{prop}` must be" in (got.error or ""), (name, prop)


# --- the stdio door ------------------------------------------------------------------------------------------------

def test_a_refusal_is_flagged_with_its_code(srv):
    result = srv.call_tool("cicada_recall_detail", {"entity_id": "nobody-here"})
    assert result["isError"] is True and _text(result) == "Entity 'nobody-here' not found."
    assert result["structuredContent"] == {"code": "not_found", "data": None, "message": _text(result)}


def test_an_answer_carries_no_error_flag_and_is_fenced_as_reference(srv):
    result = srv.call_tool("cicada_recall_detail", {"entity_id": "alpha-project"})
    assert "isError" not in result and "structuredContent" not in result
    text = _text(result)
    assert text.startswith(tool_contract.REFERENCE_HEADER + "\n" + tool_contract.FENCE_OPEN + "\n")
    assert text.endswith(tool_contract.FENCE_CLOSE)


def test_invalid_arguments_name_the_field_and_run_nothing(srv, monkeypatch):
    ran = []
    monkeypatch.setattr(srv, "handle_tool", lambda *a: ran.append(a) or "ran")
    result = srv.call_tool("cicada_ask", {"query": "alpha", "top_k": "lots"})
    assert result["isError"] is True and ran == []
    assert _text(result) == 'Invalid arguments: `top_k` must be an integer (got the string "lots").'
    assert result["structuredContent"]["code"] == "invalid_arguments"


def test_a_digit_string_is_read_with_a_note_outside_the_reference_block(srv, monkeypatch):
    seen = []
    monkeypatch.setattr(srv, "handle_tool", lambda name, args: seen.append(args) or "an answer")
    result = srv.call_tool("cicada_ask", {"query": "alpha", "top_k": "3"})
    assert seen == [{"query": "alpha", "top_k": 3}] and "isError" not in result
    text = _text(result)
    assert text.index(tool_contract.FENCE_CLOSE) < text.index("Note: `top_k` was sent as a string")


def test_an_exception_never_carries_its_message(srv, monkeypatch):
    def boom(name, args):
        raise ValueError("/Users/someone/secret/path and the caller's own words")
    monkeypatch.setattr(srv, "handle_tool", boom)
    result = srv.call_tool("cicada_recall", {"query": "alpha"})
    assert result["isError"] is True and _text(result) == "Error: that didn't work (ValueError)."
    assert result["structuredContent"]["code"] == "error"


def test_an_unknown_tool_is_refused_as_one(srv):
    result = srv.call_tool("cicada_nothing", {})
    assert result["isError"] is True and _text(result) == "Error: Unknown tool: cicada_nothing"


# --- the remote door -----------------------------------------------------------------------------------------------

def test_the_remote_door_refuses_the_same_input_in_the_same_words(memory, srv):
    text, status = _remote(memory).call(_connector(), "cicada_ask", {"query": "alpha", "top_k": "lots"})
    assert status == "invalid" and str(text) == _text(srv.call_tool("cicada_ask", {"query": "alpha", "top_k": "lots"}))


def test_a_remote_refusal_is_flagged_with_its_code_over_http(memory, tmp_path):
    db = store.ConnectorStore(tmp_path / "remote" / "connectors.db")
    _, token = db.create(app="claude", label="", scopes=["read"], expires_in_days=30)
    call = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "cicada_recall_detail", "arguments": {"entity_id": "nobody-here"}}}
    with TestClient(remote_app.build_app(db, runtime=_remote(memory))) as c:
        result = c.post(f"/c/{token}/mcp", json=call, headers=H).json()["result"]
    assert result["isError"] is True and result["content"][0]["text"] == "Entity 'nobody-here' not found."
    assert result["structuredContent"]["code"] == "not_found"


# --- the tool door and the command line agree with the MCP doors ---------------------------------------------------

def test_the_tool_door_names_the_class_never_the_message(memory, monkeypatch):
    def boom(c, a):
        raise ValueError("/Users/someone/secret")
    monkeypatch.setitem(tool_door.DISPATCH, "cicada_recall", boom)
    state = tool_door.SessionState()
    ctx = tool_door.context(memory_path=memory, bank_name=None, caller=tool_door.Caller(), state=state, surface="mcp",
                            device_id=None, backend_url="http://127.0.0.1:9", headers=dict)
    answer = tool_door.run("cicada_recall", {"query": "x"}, ctx=ctx, state=state, surface="mcp", options={},
                           root=memory.parent, bank_name=None)
    assert answer.error == "that didn't work (ValueError)."


def test_every_code_that_flags_an_error_is_a_command_line_refusal_with_an_exit_code():
    for code in REFUSAL_CODES:
        assert tool_contract.is_error(code) and code in EXIT_CODES and not Result("", None, code=code).ok
    assert not tool_contract.is_error("duplicate") and not tool_contract.is_error(None)


# --- the handshake (A7) --------------------------------------------------------------------------------------------

@pytest.mark.parametrize("client, variant, resume", [("claude-code", "claude-code", True), ("claude-ai", "desktop", False),
                                                     ("codex-mcp-client", "codex", False), ("cursor-vscode", "generic", False)])
def test_the_primer_is_chosen_by_exact_name_and_names_no_route(client, variant, resume, memory, tmp_path):
    text, meta = handshake.load_or_build(memory, client, cache_dir=tmp_path / "cache")
    assert meta["variant"] == variant and ("`claude --resume <id>`.\n" in text) is resume
    assert "POST /" not in text and "GET /" not in text and len(text) // 4 <= handshake.MAX_TOKENS


# --- recall and recall_detail (A1, A6) -----------------------------------------------------------------------------

def test_recall_detail_leaves_sleeps_bookkeeping_out(memory, srv):
    page = memory / "entities" / "alpha-project.md"
    raw = page.read_text(encoding="utf-8")
    page.write_text(raw.replace("---\n", "---\ndecay_rate: 0.05\nlayout_version: 2\nsection_provenance:\n"
                                         "  summary: ep_x\nlearned_on: '2026-01-01'\n", 1), encoding="utf-8")
    text = str(mcp_tools.recall_detail(srv._ctx(), "alpha-project"))
    for key in ("decay_rate", "layout_version", "section_provenance", "summary: ep_x", "learned_on"):
        assert key not in text
    assert text.startswith("---\n") and "\n---\n" in text


def test_a_part_ends_before_a_fence_it_would_cut(srv, monkeypatch):
    lines = [f"line {i}\n" for i in range(5)] + ["```claims\n"] + ["x" * 50 + "\n"] * 3 + ["```\n", "after\n"]
    monkeypatch.setattr(mcp_tools, "RECALL_DETAIL_BUDGET", len("".join(lines[:7])))
    part = str(mcp_tools._page_part(srv._ctx(), "alpha-project", "".join(lines), 1))
    assert "```claims" not in part and "lines 1–5 of 11; the rest:" in part


def test_a_fence_longer_than_a_part_is_cut_and_the_footer_says_so(srv, monkeypatch):
    lines = ["```claims\n"] + ["x" * 50 + "\n"] * 6 + ["```\n"]
    monkeypatch.setattr(mcp_tools, "RECALL_DETAIL_BUDGET", 160)
    part = str(mcp_tools._page_part(srv._ctx(), "alpha-project", "".join(lines), 1))
    assert "(inside its `claims` block, which goes on); the rest:" in part
