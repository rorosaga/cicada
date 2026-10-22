"""The 2026-10-22 Hyrum audit's MCP hygiene slice (G199 integrity cases, G200 A8/A10/A11, ruling 34's episode-id day).

- A3: ``cicada_write_claim`` refuses an ``observer`` outside its pattern and ``cicada_save_episode`` refuses empty
  ``content`` — a refusal, nothing written — on every door that reaches the bodies (stdio, ``/tools/call``, remote,
  and the command line, which calls the same body or the door).
- A11: no advertised schema names the legacy observer value; the body still accepts it.
- A10: ``ping`` answers ``{}``, unparseable JSON ``-32700`` with a null id, ``tools/call`` with no name ``-32602``;
  stdio read tools carry ``readOnlyHint`` from the remote ``READ_TOOLS``.
- Ruling 34: a hook capture's id carries the conversation's local day (or the client's posted offset); an id once
  minted is never renamed; ``ask_sources`` reads the day a conversation was said from its timestamp.

Synthetic throughout: scratch banks under ``tmp_path``, no backend, no network.
"""
from __future__ import annotations

import io
import json
import os
import sys
import time
from pathlib import Path

import pytest

from _stdio_server import stdio_server
from api.cli_types import REFUSAL_CODES
from api.remote import catalog
from api.remote import runtime as remote_runtime
from api.services import ask_sources, episode_ids, markdown_parser, mcp_tools, owner_identity, tool_door
from api.services import transcript_capture as tc

SID = "11111111-2222-4333-8444-555555555555"


@pytest.fixture
def bank(tmp_path):
    memory = tmp_path / "memory"
    for sub in ("entities", "episodes"):
        (memory / sub).mkdir(parents=True)
    return memory


def _ctx(memory) -> mcp_tools.ToolContext:
    return mcp_tools.ToolContext(memory_path=lambda: memory, session_id="ses_hygiene", harness="claude-code")


def _written(memory) -> list[str]:
    return sorted(p.name for sub in ("entities", "episodes") for p in (memory / sub).iterdir())


# --- A3: the two integrity refusals, on every door ---------------------------------------------------------------

def _doors(memory, monkeypatch):
    """Each door's own dispatch for one tool call: the stdio server's ``handle_tool``, the ``/tools/call`` door's
    table (the command line's client path too) and the remote connector's table."""
    server = stdio_server()
    monkeypatch.setattr(server, "get_memory_path", lambda: memory)
    monkeypatch.setattr(server.runtime_layout, "is_client", lambda *a, **k: False)
    return {
        "stdio": lambda name, args: server.handle_tool(name, args),
        "tools/call": lambda name, args: tool_door.DISPATCH[name](_ctx(memory), args),
        "remote": lambda name, args: remote_runtime._DISPATCH[name](_ctx(memory), args),
    }


@pytest.mark.parametrize("door", ["stdio", "tools/call", "remote"])
def test_an_observer_outside_the_pattern_is_refused_and_nothing_is_written(bank, monkeypatch, door):
    call = _doors(bank, monkeypatch)[door]
    out = call("cicada_write_claim", {"subject": "alpha-project", "predicate": "uses", "object": "sqlite-vec",
                                      "observer": "martian"})
    assert out.startswith("Could not write claim: observer 'martian' is not one of"), out
    assert "nothing was written" in out and getattr(out, "code", None) == "refused"
    assert owner_identity.LEGACY_OBSERVER not in out.lower(), "the refusal never advertises the legacy value"
    assert _written(bank) == []


@pytest.mark.parametrize("door", ["stdio", "tools/call", "remote"])
@pytest.mark.parametrize("args", [{}, {"content": ""}, {"content": "   \n "}, {"content": None}])
def test_an_empty_or_missing_episode_is_refused_and_nothing_is_saved(bank, monkeypatch, door, args):
    out = _doors(bank, monkeypatch)[door]("cicada_save_episode", {"title": "t", **args})
    assert out == "Nothing saved: `content` must be the text to keep, and it was empty."
    assert getattr(out, "code", None) == "refused" and _written(bank) == []


def test_the_command_lines_refusal_is_a_refusal():
    """`cicada save` calls the same body (or the door); its envelope maps the body's code — exit 1, not ok."""
    assert "refused" in REFUSAL_CODES


def test_the_accepted_observers_still_write(bank):
    for observer in ("agent", "external", "external:bob-example", None, ""):
        out = mcp_tools.write_claim(_ctx(bank), "alpha-project", "uses", f"tool-{observer or 'default'}", observer,
                                    None, None, None)
        assert not out.startswith("Could not write claim"), (observer, out)
    assert mcp_tools.observer_accepted("owner") and mcp_tools.observer_accepted(owner_identity.LEGACY_OBSERVER)
    for bad in ("martian", "Owner", "external:", "external:Bob Example", 7, ["agent"]):
        assert not mcp_tools.observer_accepted(bad), bad


# --- A11: nothing advertised names the legacy value ---------------------------------------------------------------

def test_no_advertised_schema_names_the_legacy_observer_value():
    server = stdio_server()
    from api.remote.tools import REMOTE_TOOLS

    assert owner_identity.LEGACY_OBSERVER not in json.dumps(server.TOOLS).lower()
    assert owner_identity.LEGACY_OBSERVER not in json.dumps(REMOTE_TOOLS).lower()


# --- A10: JSON-RPC basics and read annotations --------------------------------------------------------------------

def _run_stdio(monkeypatch, lines: list[str]) -> list[dict]:
    server = stdio_server()
    monkeypatch.setattr(server, "_warn_if_transcript_missing", lambda: None)
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdin", io.StringIO("\n".join(lines) + "\n"))
    monkeypatch.setattr(sys, "stdout", out)
    server.main()
    return [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]


def test_ping_parse_error_and_a_nameless_call_answer_per_json_rpc(monkeypatch):
    answers = _run_stdio(monkeypatch, [
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}),
        json.dumps({"jsonrpc": "2.0", "method": "ping"}),           # a notification: no answer
        "{not json",
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"arguments": {}}}),
        json.dumps({"jsonrpc": "2.0", "id": 3, "method": "no/such"}),
    ])
    assert answers[0] == {"jsonrpc": "2.0", "id": 1, "result": {}}
    assert answers[1] == {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
    assert answers[2]["id"] == 2 and answers[2]["error"]["code"] == -32602
    assert answers[3]["id"] == 3 and answers[3]["error"]["code"] == -32601
    assert len(answers) == 4


def test_every_stdio_read_tool_says_it_only_reads():
    tools = {t["name"]: t for t in stdio_server().TOOLS}
    for name in catalog.READ_TOOLS & set(tools):
        assert tools[name]["annotations"]["readOnlyHint"] is True, name
    assert "annotations" not in tools["cicada_write_claim"]


# --- ruling 34: the id's day is the person's ----------------------------------------------------------------------

@pytest.fixture
def madrid(monkeypatch):
    """The person's zone: 2026-10-22 00:27 there is 2026-10-21 22:27 UTC (CEST, +02:00)."""
    monkeypatch.setenv("TZ", "Europe/Madrid")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def _wire(stamp: str) -> dict:
    return {"kept": [{"role": "user", "text": "plan alpha", "ts": stamp},
                     {"role": "assistant", "text": "done", "ts": stamp}], "gap": None, "summary": {}}


def _post(memory, wire, **kw):
    return tc.capture_posted(memory, harness="claude-code", session_id=SID, conversation=wire, transcript_bytes=100,
                             transcript_size=100, cwd=None, keep_assistant=True, **kw)


def test_a_conversation_just_after_local_midnight_gets_the_local_day(bank, madrid):
    result = _post(bank, _wire("2026-10-21T22:27:00Z"))
    assert result.status == "created" and result.episode_id == "ep_2026-10-22_001"
    fm = markdown_parser.parse(bank / "episodes" / f"{result.episode_id}.md").frontmatter
    assert str(fm["timestamp"]).startswith("2026-10-21T22:27:00"), "the stamp stays aware UTC (R2)"


def test_a_client_posts_its_own_offset_and_the_server_zone_does_not_decide(bank, madrid):
    """A server elsewhere (here Madrid) mints the id for a client five hours behind UTC: the client's day wins."""
    result = _post(bank, _wire("2026-10-22T02:30:00Z"), utc_offset_minutes=-300)
    assert result.episode_id == "ep_2026-10-21_001"


def test_an_existing_id_is_never_renamed(bank, madrid):
    episodes = bank / "episodes"
    old = {"id": "ep_2026-10-21_001", "timestamp": "2026-10-21T22:27:00+00:00", "source": "claude-code",
           "origin": "claude-code", "processed": False, "session_id": SID, "harness": "claude-code",
           "capture_kind": tc.CAPTURE_KIND, "content_hash": "0" * 12}
    markdown_parser.write(episodes / "ep_2026-10-21_001.md", old, "**user:** plan alpha\n")
    tc._episode_cache.clear()
    result = _post(bank, _wire("2026-10-21T22:27:00Z"))
    assert result.episode_id == "ep_2026-10-21_001"
    assert sorted(p.name for p in episodes.iterdir()) == ["ep_2026-10-21_001.md"]


def test_telegram_mints_the_local_day_too(bank, madrid):
    from api.services import telegram_capture

    out = telegram_capture._default_save_episode(bank, "a note", captured_at="2026-10-21T22:27:00+00:00")
    assert out["episode_id"] == "ep_2026-10-22_001"


def test_the_id_day_rule(madrid):
    assert episode_ids.id_day("2026-10-21T22:27:00Z") == "2026-10-22"
    assert episode_ids.id_day("2026-10-21T22:27:00+00:00", utc_offset_minutes=0) == "2026-10-21"
    assert episode_ids.id_day("2026-10-21T22:27:00Z", utc_offset_minutes=10_000) == "2026-10-22", "out of range"
    assert episode_ids.id_day("2026-10-22T00:27:00") == "2026-10-22", "a naive stamp is this machine's time"


def test_ask_reads_the_day_said_not_the_day_in_an_old_id(bank, madrid):
    """An id a hook minted before ruling 34 carries the UTC day; the reader takes the local day from the stamp."""
    markdown_parser.write(bank / "episodes" / "ep_2026-10-21_007.md",
                          {"id": "ep_2026-10-21_007", "timestamp": "2026-10-21T22:27:00+00:00"}, "**user:** hi\n")
    assert ask_sources.episode_day("ep_2026-10-21_007") == "2026-10-21"
    assert ask_sources.said_day(bank, "ep_2026-10-21_007") == "2026-10-22"
    assert ask_sources.said_day(bank, "ep_2026-10-20_001") == "2026-10-20", "no file: the id's day"
    assert ask_sources._episodes_on(bank, ["2026-10-22"]) == ["ep_2026-10-21_007"]
    assert ask_sources._episodes_on(bank, ["2026-10-21"]) == []


@pytest.mark.skipif(os.name != "posix", reason="time.tzset is POSIX")
def test_the_hook_sends_this_machines_offset():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks"))
    import hook_client

    offset = hook_client.utc_offset_minutes("2026-10-21T22:27:00Z")
    assert isinstance(offset, int) and abs(offset) <= episode_ids.MAX_UTC_OFFSET_MINUTES
    assert hook_client.first_stamp(_wire("2026-10-21T22:27:00Z")) == "2026-10-21T22:27:00Z"
    assert hook_client.first_stamp({"kept": []}) is None
