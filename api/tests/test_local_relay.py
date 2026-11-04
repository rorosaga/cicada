"""Ruling 57 — capture for apps with no hook defaults to the tool their model calls as they talk: the Claude desktop
app's local connection is offered and asked for `cicada_capture_turns`, by exact client name, stored as relayed, and a
hook-captured harness never is, whatever it calls itself. Ruling 58 — an export stays a one-time import that upgrades a
relayed conversation in place, from either provider's shape."""
from __future__ import annotations

import json
import re
import time
from datetime import date

import pytest

from _intake_fixtures import _zip
from _stdio_server import stdio_server
from _synthetic_bank import _bank
from api import config
from api.remote import catalog
from api.remote.runtime import RemoteRuntime
from api.routers import conversations as conv
from api.routers import intake
from api.services import (
    demo_guard, episode_actor, evidence, handshake, markdown_parser, mcp_tools, promotion, relay_capture,
    state_dictionary, tool_door, turn_capture,
)

CC_ID = "11111111-2222-3333-4444-555555555555"
FIRST = "Help me plan the alpha-project launch for next week, starting with the checklist."
REPLY = "Here is a checklist for the alpha-project launch: scope, owners, dates."
SECOND = "Add a rollback step after the dates please."


@pytest.fixture
def memory(tmp_path, monkeypatch):
    bank = _bank(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    for name in ("CLAUDE_CODE_SESSION_ID", "CICADA_SESSION_ID", "CICADA_SESSION_HARNESS", "CICADA_CAPTURE",
                 "CICADA_API_BASE", "CICADA_ENGINE_SPAWN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CICADA_PORT", "1")     # no backend here: the stdio door's own write
    config.get_settings.cache_clear()
    yield bank
    config.get_settings.cache_clear()


@pytest.fixture
def server(memory, monkeypatch):
    module = stdio_server()
    monkeypatch.setattr(module, "get_memory_path", lambda: memory)
    monkeypatch.setattr(module, "SESSION", module.SessionIdentity("ses_2026-11-04_abcd1234", "unknown", None))
    monkeypatch.setattr(module, "CLIENT_INFO", {})
    return module


def _connect(module, name):
    module.CLIENT_INFO.clear()
    if name is not None:
        module.CLIENT_INFO.update({"name": name, "version": "1"})
    return {t["name"] for t in module.tools_for_client()}


def _ctx(memory, *, client="claude-ai", harness="unknown"):
    return mcp_tools.ToolContext(memory_path=lambda: memory, session_id="ses_2026-11-04_abcd1234", harness=harness,
                                 project_dir=None, client_name=client, client_version="1", skipped_inbox_ids=set(),
                                 state_hint_sent=False, post=lambda p, d: {}, headers=dict, backend_url="")


def _relayed(memory):
    return [p for p in sorted((memory / "episodes").glob("ep_*.md"))
            if isinstance(markdown_parser.parse(p).frontmatter.get("relay"), dict)]


# --- telling a client apart -------------------------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["claude-ai", "claude-desktop", "Claude AI", "claude_desktop"])
def test_the_desktop_app_by_its_exact_name_is_offered_the_tool(server, name):
    assert "cicada_capture_turns" in _connect(server, name)


@pytest.mark.parametrize("name", ["claude-code", "codex", "codex-mcp-client", "cursor", "gemini-cli", "windsurf", "",
                                  "claude", "claude-ai-next", "my claude-ai client", None])
def test_a_named_harness_an_unknown_or_an_unnamed_client_is_not(server, name):
    assert "cicada_capture_turns" not in _connect(server, name)


def test_nothing_is_offered_before_initialize_names_the_client(server):
    assert "cicada_capture_turns" not in {t["name"] for t in server.tools_for_client()}


def test_claude_code_calling_itself_the_desktop_app_is_still_not_offered_it(server, monkeypatch):
    """A client's name is its own word; the session id Claude Code injects is not."""
    monkeypatch.setattr(server, "SESSION", server.SessionIdentity(CC_ID, "claude-code", None))
    assert "cicada_capture_turns" not in _connect(server, "claude-ai")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", CC_ID)
    assert relay_capture.local_relay_allowed("claude-ai", "unknown") is False


@pytest.mark.parametrize("env", [{"CLAUDE_CODE_SESSION_ID": CC_ID}, {"CICADA_SESSION_ID": "s-12345678"},
                                 {"CICADA_SESSION_HARNESS": "cursor"}, {"CICADA_CAPTURE": "off"},
                                 {"CICADA_CAPTURE": "OFF"}])
def test_a_named_session_or_the_capture_switch_turns_it_off(env):
    assert relay_capture.local_relay_allowed("claude-ai", "unknown", env=env) is False
    assert relay_capture.local_relay_allowed("claude-ai", "unknown", env={}) is True


def test_no_double_capture_a_claude_code_call_writes_nothing_and_answers_unknown_tool(server, memory, monkeypatch):
    monkeypatch.setattr(server, "SESSION", server.SessionIdentity(CC_ID, "claude-code", None))
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", CC_ID)
    for name in ("claude-code", "claude-ai"):
        _connect(server, name)
        before = sorted((memory / "episodes").glob("*"))
        result = server.call_tool("cicada_capture_turns", {"message": FIRST, "conversation": "new"})
        assert result["isError"] is True and "Unknown tool" in result["content"][0]["text"]
        assert sorted((memory / "episodes").glob("*")) == before


def test_an_engine_spawn_is_offered_nothing_whatever_it_is_called(server, monkeypatch):
    monkeypatch.setenv("CICADA_ENGINE_SPAWN", "1")
    assert _connect(server, "claude-ai") == set()


# --- the primer -------------------------------------------------------------------------------------------------------

def _primer(memory, **kw):
    return handshake.build(state_dictionary.read_state(memory), bank="memory", **kw)


def test_only_a_client_offered_the_tool_is_asked_for_it(memory):
    assert "cicada_capture_turns" in _primer(memory, variant="desktop", relay=True)
    assert "cicada_capture_turns" not in _primer(memory, variant="desktop")
    for variant in ("claude-code", "codex", "generic"):
        assert "cicada_capture_turns" not in _primer(memory, variant=variant, relay=True)


def test_the_stdio_primer_matches_the_tool_list_for_every_client(server, memory, monkeypatch, tmp_path):
    """R12 in both directions, through the real door: named in the primer exactly when listed."""
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    for name, offered in (("claude-ai", True), ("claude-code", False), ("cursor", False), (None, False)):
        listed = "cicada_capture_turns" in _connect(server, name)
        assert listed is offered
        assert ("cicada_capture_turns" in server._handshake_text(delivery="tool")) is offered
    monkeypatch.setenv("CICADA_CAPTURE", "off")   # a real desktop app with the switch off is told nothing of it
    assert "cicada_capture_turns" not in _connect(server, "claude-ai")
    text = server._handshake_text(delivery="tool")
    assert "cicada_capture_turns" not in text and "## Desktop app" in text


def test_a_route_with_no_tool_to_hold_never_asks(memory, tmp_path):
    text, meta = handshake.load_or_build(memory, "claude-ai", cache_dir=tmp_path / "c")
    assert meta["variant"] == "desktop" and "cicada_capture_turns" not in text


def test_the_primer_and_its_cached_copy_are_keyed_on_the_ask(memory, tmp_path):
    cache = tmp_path / "c"
    asked, _ = handshake.load_or_build(memory, "claude-ai", cache_dir=cache, relay=True)
    plain, _ = handshake.load_or_build(memory, "claude-ai", cache_dir=cache)
    again, meta = handshake.load_or_build(memory, "claude-ai", cache_dir=cache, relay=True)
    assert asked == again and meta["cached"] and "cicada_capture_turns" not in plain


def test_every_argument_the_primer_names_is_in_the_schema(server, memory):
    schema = next(t for t in server.TOOLS if t["name"] == "cicada_capture_turns")["inputSchema"]
    text = _primer(memory, variant="desktop", relay=True)
    [args] = re.findall(r"`cicada_capture_turns\(([^`]*)\)`", text)
    assert {a.strip() for a in args.split(",")} <= set(schema["properties"])
    assert set(schema["required"]) <= {a.strip() for a in args.split(",")}


def test_the_ask_fits_the_budget(memory):
    """R10's basis, chars/4: the line is fixed text the state trims around, with reading on and a state over budget."""
    from _synthetic_bank import _settings

    state_dictionary.refresh(memory, _settings(memory), force=True)
    state = dict(state_dictionary.read_state(memory))
    state["people"] = [{"id": f"person-{i}", "name": f"Person {i}", "line": "x" * 200} for i in range(40)]
    state["standing"] = [{"id": f"page-{i}", "name": f"Page {i}", "line": "y" * 200} for i in range(40)]
    fixed = handshake.build(None, variant="desktop", bank="memory", relay=True, reading=True)
    full = handshake.build(state, variant="desktop", bank="memory", relay=True, reading=True)
    assert len(handshake._LOCAL_RELAY_LINE) // 4 < 90 and len(fixed) // 4 < handshake.MAX_TOKENS
    assert len(full) // 4 <= handshake.MAX_TOKENS and "cicada_capture_turns" in full


# --- stored as relayed ------------------------------------------------------------------------------------------------

def _turn(server, message, conversation, previous=None):
    args = {"message": message, "conversation": conversation}
    if previous:
        args["previous_reply"] = previous
    return server.call_tool("cicada_capture_turns", args)


def test_one_chat_is_one_relayed_episode_and_two_chats_two_in_one_process(server, memory):
    _connect(server, "claude-ai")
    first = _turn(server, FIRST, "new")
    assert "isError" not in first
    text = first["content"][0]["text"]
    assert "Cicada memory" in text        # said once, in words the person sees
    handle = re.search(r'conversation="(lc_[^"]+)"', text).group(1)
    assert "Cicada memory" not in _turn(server, SECOND, handle, REPLY)["content"][0]["text"]
    assert _turn(server, SECOND, handle, REPLY)["content"][0]["text"] == "Already captured."
    [path] = _relayed(memory)
    stored = markdown_parser.parse(path)
    fm = stored.frontmatter
    assert stored.body == f"user: {FIRST}\nassistant: {REPLY}\nuser: {SECOND}"
    assert fm["session_id"] == handle and fm["harness"] == "claude-desktop" and fm["processed"] is False
    assert fm["evidence_kind"] == "assistant"
    assert fm["relay"]["app"] == "claude" and fm["relay"]["channel"] == "local" and fm["relay"]["first"]
    assert "connector" not in fm["relay"]
    _turn(server, "A different chat about the beta-project budget for the winter quarter.", "new")
    assert len(_relayed(memory)) == 2


def test_a_replica_with_no_backend_never_writes_its_copy(server, memory, monkeypatch):
    monkeypatch.setattr(server.runtime_layout, "is_replica", lambda *a, **k: True)
    _connect(server, "claude-ai")
    result = _turn(server, FIRST, "new")
    assert result["isError"] is True and not _relayed(memory)


def test_a_relayed_chat_is_never_the_persons_own_words(server, memory):
    _connect(server, "claude-ai")
    _turn(server, FIRST, "new")
    [path] = _relayed(memory)
    stored = markdown_parser.parse(path)
    kind = stored.frontmatter["evidence_kind"]
    assert {t.role for t in evidence.turns(stored.body, override=kind)} == {"assistant"}
    assert all(person == "" for person, _ in promotion.exchanges(stored.body, override=kind))
    assert promotion.measure({"name": "alpha-project"}, promotion.exchanges(stored.body, override=kind))[1] is False
    assert episode_actor.actor(stored.frontmatter) == "Claude Desktop, relayed by its model"


def test_the_writer_scrubs_a_relayed_secret(server, memory):
    _connect(server, "claude-ai")
    _turn(server, "Use sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789 for the alpha-project launch please.", "new")
    [path] = _relayed(memory)
    assert "abcdefghijklmnopqrstuvwxyz0123456789" not in path.read_text()


def test_a_demo_bank_refuses_it_like_every_other_write(tmp_path):
    from test_demo_capture import _loose_demo

    bank = _loose_demo(tmp_path)
    reply = relay_capture.capture_local(_ctx(bank), FIRST, conversation="new", queue_index=False)
    assert str(reply) == demo_guard.AGENT_REFUSAL and getattr(reply, "code", None) == "demo_bank"
    assert not list((bank / "episodes").glob("ep_*.md"))


@pytest.mark.parametrize("bad", [None, "", "rc_ab12cd34_2026-11-04_abcd1234", "lc_../../etc", "../x", 12])
def test_a_handle_this_tool_did_not_give_is_refused(memory, bad):
    reply = relay_capture.capture_local(_ctx(memory), FIRST, conversation=bad, queue_index=False)
    assert getattr(reply, "code", None) == "invalid_arguments" and not _relayed(memory)


def test_a_chat_outlives_its_process(memory):
    handle = relay_capture.capture_local(_ctx(memory), FIRST, conversation="new", queue_index=False).data["conversation"]
    reply = relay_capture.capture_local(_ctx(memory), SECOND, REPLY, handle, queue_index=False)
    assert reply.data["status"] == "updated" and len(_relayed(memory)) == 1


# --- both doors in one app --------------------------------------------------------------------------------------------

def _connector():
    return catalog.Connector(id="ab12cd34", label="Claude", app="claude", scopes=frozenset(catalog.DEFAULT_SCOPES),
                             created_at="2026-09-01T00:00:00+00:00", auth="oauth")


def test_the_apps_other_door_never_makes_a_second_copy_of_the_same_turn(memory):
    """A connector added on claude.ai shows in the desktop app beside its local connection, and both primers ask."""
    relayed = relay_capture.capture_local(_ctx(memory), FIRST, conversation="new", queue_index=False)
    runtime = RemoteRuntime(post=lambda p, d: {"status": "resolved"}, sleep_running=lambda: False)
    text, status = runtime.call(_connector(), "cicada_capture_turns", {"message": FIRST})
    assert status == "ok" and "other Cicada connection" in text and len(_relayed(memory)) == 1
    assert "Stop calling" in text and relayed.data["status"] == "created"


def test_and_the_local_door_second_is_told_the_same(memory):
    runtime = RemoteRuntime(post=lambda p, d: {"status": "resolved"}, sleep_running=lambda: False)
    runtime.call(_connector(), "cicada_capture_turns", {"message": FIRST})
    reply = relay_capture.capture_local(_ctx(memory), FIRST, conversation="new", queue_index=False)
    assert reply.data["status"] == "elsewhere" and "conversation" not in reply.data and len(_relayed(memory)) == 1


def test_a_different_chat_or_a_short_message_is_not_the_other_doors(memory):
    runtime = RemoteRuntime(post=lambda p, d: {"status": "resolved"}, sleep_running=lambda: False)
    runtime.call(_connector(), "cicada_capture_turns", {"message": FIRST})
    relay_capture.capture_local(_ctx(memory), "Another chat entirely about the winter budget.", conversation="new",
                                queue_index=False)
    relay_capture.capture_local(_ctx(memory), "Hello there", conversation="new", queue_index=False)
    # Too short to tell apart: the other door's day bucket takes it anyway, and no turn is dropped.
    assert runtime.call(_connector(), "cicada_capture_turns", {"message": "Hello there"})[1] == "ok"
    bodies = [markdown_parser.parse(p).body for p in _relayed(memory)]
    assert len(bodies) == 3 and sum("Hello there" in b for b in bodies) == 2


def test_an_old_identical_first_message_is_a_new_chat(memory, monkeypatch):
    runtime = RemoteRuntime(post=lambda p, d: {"status": "resolved"}, sleep_running=lambda: False)
    runtime.call(_connector(), "cicada_capture_turns", {"message": FIRST})
    monkeypatch.setattr(turn_capture, "ELSEWHERE_WINDOW_S", -1)
    assert relay_capture.capture_local(_ctx(memory), FIRST, conversation="new",
                                       queue_index=False).data["status"] == "created"


# --- the door ---------------------------------------------------------------------------------------------------------

def _door(memory, *, client, harness="unknown", args=None):
    state = tool_door.SessionState(skipped_inbox_ids=set(), state_hint_sent=False, listed_revisions={})
    ctx = tool_door.context(memory_path=memory, bank_name=None,
                            caller=tool_door.Caller(session_id="ses_2026-11-04_abcd1234", harness=harness,
                                                    project_dir=None, client_name=client, client_version="1"),
                            state=state, surface="mcp", device_id="dev12345", backend_url="", headers=dict)
    return tool_door.run("cicada_capture_turns", args or {"message": FIRST, "conversation": "new"}, ctx=ctx,
                         state=state, surface="mcp", options={}, root=memory.parent, bank_name=None)


def test_a_client_machines_desktop_app_relays_through_the_door_and_says_which_device(memory):
    answer = _door(memory, client="claude-ai")
    assert answer.data["status"] == "created"
    [path] = _relayed(memory)
    assert markdown_parser.parse(path).frontmatter["relay"]["device"] == "dev12345"


@pytest.mark.parametrize("client,harness", [("claude-code", "claude-code"), ("claude-ai", "claude-code"),
                                            ("cursor", "unknown"), (None, "unknown")])
def test_the_door_asks_the_same_question(memory, client, harness):
    answer = _door(memory, client=client, harness=harness)
    assert answer.code == "invalid_arguments" and "Unknown tool" in answer.text and not _relayed(memory)


def test_the_command_line_never_relays(memory):
    state = tool_door.SessionState(skipped_inbox_ids=set(), state_hint_sent=False, listed_revisions={})
    ctx = tool_door.context(memory_path=memory, bank_name=None,
                            caller=tool_door.Caller(session_id="s-12345678", harness="unknown", project_dir=None,
                                                    client_name="claude-ai", client_version="1"),
                            state=state, surface="cli", device_id=None, backend_url="", headers=dict)
    with pytest.raises(tool_door.DoorError):
        tool_door.run("cicada_capture_turns", {"message": FIRST, "conversation": "new"}, ctx=ctx, state=state,
                      surface="cli", options={}, root=memory.parent, bank_name=None)


def test_a_door_primer_asks_only_when_the_stdio_side_offered_it(memory, tmp_path, monkeypatch):
    """An older client machine's stdio server lists no such tool and sends no flag: its primer must not ask."""
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    state = tool_door.SessionState(skipped_inbox_ids=set(), state_hint_sent=False, listed_revisions={})
    ctx = tool_door.context(memory_path=memory, bank_name=None,
                            caller=tool_door.Caller(session_id="s-12345678", harness="unknown", project_dir=None,
                                                    client_name="claude-ai", client_version="1"),
                            state=state, surface="mcp", device_id=None, backend_url="", headers=dict)
    for options, asks in (({}, False), ({"relay": True}, True), ({"relay": "yes"}, False)):
        answer = tool_door.run("cicada_handshake", {}, ctx=ctx, state=state, surface="mcp", options=options,
                               root=memory.parent, bank_name=None)
        assert ("cicada_capture_turns" in answer.text) is asks


# --- ruling 58: a one-time export upgrades it in place, either provider's shape --------------------------------------

def _claude_export_zip():
    stamp = f"{date.today().isoformat()}T10:00:00.000000Z"
    return _zip({"users.json": "[]", "conversations.json": json.dumps([{
        "uuid": "conv-claude-1", "name": "Launch plan", "created_at": stamp, "updated_at": stamp,
        "chat_messages": [
            {"uuid": "m0", "sender": "human", "text": FIRST, "content": [], "created_at": stamp},
            {"uuid": "m1", "sender": "assistant", "text": REPLY + " (full)", "content": [], "created_at": stamp},
            {"uuid": "m2", "sender": "human", "text": SECOND, "content": [], "created_at": stamp}]}])})


def _chatgpt_export_zip():
    at = time.time()

    def node(role, text, when):
        return {"message": {"author": {"role": role}, "content": {"parts": [text]}, "create_time": when}}

    return _zip({"user.json": "{}", "conversations.json": json.dumps([{
        "conversation_id": "conv-gpt-1", "title": "Launch plan", "create_time": at, "update_time": at + 60,
        "mapping": {"a": node("user", FIRST, at), "b": node("assistant", REPLY + " (full)", at + 30),
                    "c": node("user", SECOND, at + 40)}}])})


def _import(memory, content):
    parsed = intake.parse_export(content, "export.zip")
    return conv._stage_export(parsed.episodes, memory / "episodes")


def _upgraded(memory, content, relay_first):
    relay_first()
    [path] = _relayed(memory)
    assert markdown_parser.parse(path).frontmatter["evidence_kind"] == "assistant"
    staged = _import(memory, content)
    assert (staged.updated, staged.created) == (1, 0)
    assert [p.name for p in _relayed(memory)] == [path.name]      # the same file, the same id
    stored = markdown_parser.parse(path)
    assert "evidence_kind" not in stored.frontmatter and stored.frontmatter["relay"]["upgraded_at"]
    assert "(full)" in stored.body
    assert _import(memory, content).skipped == 1                  # one-time: a repeat changes nothing
    return stored


def test_an_anthropic_export_upgrades_a_desktop_relay_in_place(memory):
    stored = _upgraded(memory, _claude_export_zip(),
                       lambda: relay_capture.capture_local(_ctx(memory), FIRST, conversation="new", queue_index=False))
    assert stored.frontmatter["harness"] == "claude-desktop" and stored.frontmatter["relay"]["upgraded_by"] == "claude"


def test_an_anthropic_export_upgrades_a_remote_relay_in_place(memory):
    runtime = RemoteRuntime(post=lambda p, d: {"status": "resolved"}, sleep_running=lambda: False)
    _upgraded(memory, _claude_export_zip(), lambda: runtime.call(_connector(), "cicada_capture_turns", {"message": FIRST}))


def test_an_openai_export_upgrades_a_remote_relay_in_place(memory):
    runtime = RemoteRuntime(post=lambda p, d: {"status": "resolved"}, sleep_running=lambda: False)
    connector = catalog.Connector(id="cd34ef56", label="ChatGPT", app="chatgpt", auth="oauth",
                                  scopes=frozenset(catalog.DEFAULT_SCOPES), created_at="2026-09-01T00:00:00+00:00")
    stored = _upgraded(memory, _chatgpt_export_zip(),
                       lambda: runtime.call(connector, "cicada_capture_turns", {"message": FIRST}))
    assert stored.frontmatter["relay"]["upgraded_by"] == "chatgpt"


@pytest.mark.parametrize("content", [_claude_export_zip, _chatgpt_export_zip], ids=["anthropic", "openai"])
def test_a_new_bank_imports_either_export_with_nothing_relayed_first(memory, content):
    staged = _import(memory, content())
    assert (staged.created, staged.updated) == (1, 0) and not _relayed(memory)
    [path] = [p for p in (memory / "episodes").glob("ep_*.md")
              if markdown_parser.parse(p).frontmatter.get("source_id") in ("conv-claude-1", "conv-gpt-1")]
    assert FIRST in path.read_text()
