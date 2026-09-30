"""G166 (owner 2026-09-30, G178 generalises it) — "How your agent reads": a selection stored on this Mac,
passed to the person's own agent as an instruction and never as authority.

Default `auto` says nothing new; `own` says "don't load a separate skill"; a skill says "the person chose
<skill>: use it, and if it isn't installed for you, say so and stop". Remote connections and clients that
are not a catalog agent get no skill clause. Every string is neutral (test_provider_neutral_copy.py)."""
from __future__ import annotations

import json
import stat

import pytest

from _reading_fixtures import PUBLIC, ask, enable, reading  # noqa: F401
from _stdio_server import stdio_server
from _synthetic_bank import _bank, _ok_repo, _settings
from api.remote import catalog
from api.remote.runtime import RemoteRuntime
from api.services import agent_methods, handshake, reading_prompt, reading_settings, skill_catalog, state_dictionary
from test_handshake_r12 import _check


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))


def _queue(server):
    return server.handle_tool("cicada_reading_queue", {})


def test_default_is_auto_and_the_default_text_names_no_tool():
    assert agent_methods.choice("reading") == agent_methods.AUTO
    assert agent_methods.prompt_clause("reading") is None and agent_methods.reply_clause("reading", variant="claude-code") is None
    assert agent_methods.capability_line("reading", "claude-code") is None
    assert agent_methods.tool_phrase("reading") == "your browser tools"
    prompt = reading_prompt.queue_prompt()
    assert "with your browser tools in my own signed-in session" in prompt and "I chose" not in prompt
    assert prompt.endswith(reading_prompt.RULES)
    assert not agent_methods.path().exists(), "reading a choice never creates the file"


def test_set_choice_validates_job_and_choice_and_a_removed_id_reads_as_auto():
    assert agent_methods.set_choice("reading", "browser-harness") == "browser-harness"
    assert agent_methods.choice("reading") == "browser-harness"
    for job, chosen in (("nonsense", "auto"), ("reading", "watch"), ("reading", "pdf"), ("reading", "no-such-skill")):
        with pytest.raises(agent_methods.MethodError) as err:
            agent_methods.set_choice(job, chosen)
        assert err.value.args[0].endswith(".") and "isn't" in err.value.args[0]
    assert agent_methods.choice("reading") == "browser-harness", "a refused choice changes nothing"
    # a catalog that no longer lists the skill for the job reads as auto
    empty = {"skills": [], "version": 1}
    assert agent_methods.choice("reading", empty) == agent_methods.AUTO
    assert agent_methods.set_choice("reading", "own") == "own" and agent_methods.choice("reading") == "own"
    assert agent_methods.set_choice("reading", "auto") == "auto" and agent_methods.choice("reading") == "auto"
    assert json.loads(agent_methods.path().read_text())["choices"] == {}


def test_file_is_0600_atomic_and_read_on_every_call():
    agent_methods.set_choice("reading", "own")
    assert stat.S_IMODE(agent_methods.path().stat().st_mode) == 0o600
    assert not list(agent_methods.path().parent.glob(".methods-*.tmp"))
    # another process (the stdio MCP server) changes the file: this one sees it at once, nothing is cached
    data = json.loads(agent_methods.path().read_text())
    data["choices"]["reading"] = "macos-harness"
    agent_methods.path().write_text(json.dumps(data))
    assert agent_methods.choice("reading") == "macos-harness"
    agent_methods.path().write_text("{not json")
    assert agent_methods.choice("reading") == agent_methods.AUTO


def test_no_op_choice_writes_nothing():
    agent_methods.set_choice("reading", "own")
    before = agent_methods.path().stat().st_mtime_ns
    agent_methods.set_choice("reading", "own")
    assert agent_methods.path().stat().st_mtime_ns == before


def test_skill_choice_gives_the_owners_sentence_in_both_voices():
    agent_methods.set_choice("reading", "browser-harness")
    person = agent_methods.prompt_clause("reading")
    assert person == ("I chose the `browser-harness` skill for this. If you run on this Mac and can load skills, "
                      "use it, and set `via` to \"browser-harness\"; if it is not installed for you, say so and "
                      "stop. If you cannot load skills where you run (an app connected from anywhere, say), use "
                      "your own browser tools instead.")
    reply = agent_methods.reply_clause("reading", variant="claude-code")
    assert reply.startswith("The person chose the `browser-harness` skill for this: use it")
    assert reply.endswith("If it is not installed for you, say so and stop.")
    prompt = reading_prompt.queue_prompt()
    assert "with the tool I chose in my own signed-in session" in prompt and person in prompt
    assert prompt.index(person) < prompt.index(reading_prompt.RULES)
    assert "with your browser tools" not in prompt, "the default words give way to a pointer"
    assert reading_prompt.ask_prompt("https://blog.example.net/a").startswith("Start with https://blog.example.net/a. ")


def test_own_choice_names_no_product():
    agent_methods.set_choice("reading", "own")
    clause = agent_methods.prompt_clause("reading")
    assert clause == "I chose your own built-in tools for this; don't load a separate skill for it."
    assert agent_methods.reply_clause("reading", variant="generic").startswith("The person chose your own built-in tools")
    assert "skill for this: use it" not in clause


def test_options_are_data_driven_and_carry_install_state_and_the_terms(tmp_path):
    home = tmp_path / "h"
    (home / ".claude" / "skills" / "browser-harness").mkdir(parents=True)
    (home / ".claude" / "skills" / "browser-harness" / "SKILL.md").write_text("---\nname: x\n---\n")
    options = agent_methods.options("reading", home=home)
    assert [o["id"] for o in options] == ["auto", "own", "browser-harness", "macos-harness"]
    assert [o["kind"] for o in options] == ["auto", "own", "skill", "skill"]
    bh, mh = options[2], options[3]
    assert bh["state"] == {"claude-code": "installed", "codex": "not_installed"} and mh["state"]["claude-code"] == "not_installed"
    assert bh["reach"] and mh["reach"] and "Mac" in mh["reach"] and "Accessibility" in mh["reach"]
    assert bh["install"]["claude-code"]["runnable"] is False and bh["install"]["claude-code"]["prompt"]
    assert bh["title"] == "browser-harness" and bh["detail"] == bh["summary"]


def test_remote_callers_get_no_clause(reading):
    server, memory = reading
    agent_methods.set_choice("reading", "browser-harness")
    ask(memory, PUBLIC)
    assert agent_methods.reply_clause("reading", variant="claude-code", remote=True) is None
    runtime = RemoteRuntime(memory_path=lambda: memory, post=lambda p, d: {}, sleep_running=lambda: False)
    connector = catalog.Connector(id="aaaaaaaa", label="Phone", app="chatgpt", scopes=frozenset({"read", "record"}),
                                  created_at="2026-09-01T00:00:00+00:00")
    text, status = runtime.call(connector, "cicada_reading_queue", {})
    assert status == "ok" and "browser-harness" not in text and "I chose" not in text and "person chose" not in text
    assert "with your browser tools" in text


def test_the_stdio_queue_reply_carries_the_clause_for_a_catalog_agent_only(reading, monkeypatch):
    server, memory = reading
    ask(memory, PUBLIC)
    assert "person chose" not in _queue(server) and "with your browser tools" in _queue(server)
    agent_methods.set_choice("reading", "browser-harness")
    monkeypatch.setattr(server, "CLIENT_INFO", {"name": "claude-code", "version": "1"}, raising=False)
    from api.services import mcp_tools

    out = mcp_tools.reading_queue(mcp_tools.ToolContext(
        memory_path=lambda: memory, session_id="s", harness="claude-code", client_name="claude-code"))
    assert "The person chose the `browser-harness` skill for this" in out and "with the tool the person chose" in out
    generic = mcp_tools.reading_queue(mcp_tools.ToolContext(
        memory_path=lambda: memory, session_id="s", harness="cursor", client_name="cursor"))
    assert "browser-harness" not in generic and "with your browser tools" in generic, "a client that cannot have the skill"
    agent_methods.set_choice("reading", "own")
    own = mcp_tools.reading_queue(mcp_tools.ToolContext(
        memory_path=lambda: memory, session_id="s", harness="cursor", client_name="cursor"))
    assert "your own built-in tools for this" in own


def _schemas():
    return {t["name"]: set(t["inputSchema"].get("properties", {})) for t in stdio_server().TOOLS}


def test_capability_line_needs_reading_on_and_names_only_real_tools_and_arguments():
    agent_methods.set_choice("reading", "browser-harness")
    assert agent_methods.capability_line("reading", "claude-code") is None, "reading is off: no line"
    reading_settings.update(agent_enabled_=True, acknowledge=True)
    line = agent_methods.capability_line("reading", "claude-code")
    assert line.startswith("- Reading pages: the person chose the `browser-harness` skill for it.")
    assert "If it is not installed for you, say so and stop." in line
    _check(line, _schemas())  # R12: cicada_reading_queue(limit) and cicada_record_read(url, outcome, ...) are real
    agent_methods.set_choice("reading", "own")
    assert "your own built-in browser or computer tools" in agent_methods.capability_line("reading", "codex")


def test_generic_variant_gets_no_skill_clause_but_may_hear_about_its_own_tools():
    reading_settings.update(agent_enabled_=True, acknowledge=True)
    agent_methods.set_choice("reading", "browser-harness")
    assert agent_methods.capability_line("reading", "generic") is None
    assert agent_methods.method_lines("generic") == ()
    agent_methods.set_choice("reading", "own")
    assert agent_methods.capability_line("reading", "generic") is not None


def test_primer_with_three_bridges_item_9_and_both_method_lines_fits_with_room_for_state():
    bridges = tuple(skill_catalog.BRIDGE_TEXT[k].format(names="`x` is") for k in ("papers", "video", "meetings"))
    methods = ("- Reading pages: the person chose the `browser-harness` skill for it. When links are waiting "
               "(`cicada_reading_queue(limit)`), read them with it, then record each with "
               "`cicada_record_read(url, outcome, summary, excerpts=[{quote}], via)`. If it is not installed for "
               "you, say so and stop.",
               "- Watching: the person chose something for it.")
    text = handshake.build(None, variant="claude-code", bank="memory", tz="Europe/Madrid",
                           bridges=bridges, reading=True, methods=methods)
    # 1,500 before G162 named `basis` and the video queue in item 3; 1,525 leaves the state block 275 of the 1,800.
    assert len(text) // 4 <= 1525, "the fixed part leaves room for the state block"
    for line in methods + bridges:
        assert line in text
    # methods live in the fixed part with their own cap, not sliced by the bridge cap
    extra = handshake.build(None, variant="claude-code", bank="memory", bridges=bridges, methods=methods + ("- x",))
    assert "- x" not in extra and methods[1] in extra


def test_handshake_cache_key_moves_with_the_choice(tmp_path):
    memory = _bank(tmp_path)
    state_dictionary.refresh(memory, _settings(memory), force=True, repo_resolver=_ok_repo)
    reading_settings.update(agent_enabled_=True, acknowledge=True)
    cache = tmp_path / "cache"
    first, _ = handshake.load_or_build(memory, "claude-code", variant="claude-code", cache_dir=cache)
    assert "the person chose" not in first and "with your browser tools" in first
    agent_methods.set_choice("reading", "browser-harness")
    second, meta = handshake.load_or_build(memory, "claude-code", variant="claude-code", cache_dir=cache)
    assert meta["cached"] is False and "the person chose the `browser-harness` skill for it" in second
    assert "your browser tools" not in second, "item 9 must not contradict the method line that follows it"
    assert "with the tool the person chose" in second
    _check(second, _schemas())
    agent_methods.set_choice("reading", "auto")
    third, _ = handshake.load_or_build(memory, "claude-code", variant="claude-code", cache_dir=cache)
    assert third == first
    # a remote primer never gets a method line
    remote, _ = handshake.load_or_build(memory, variant="remote", tools=catalog.tool_names_for(catalog.DEFAULT_SCOPES),
                                        cache_dir=cache)
    assert "browser-harness" not in remote


def test_item_9_never_says_your_browser_tools_beside_a_chosen_method(tmp_path):
    """R12-style: for every choice and variant, the primer says one thing about what opens pages."""
    memory = _bank(tmp_path)
    state_dictionary.refresh(memory, _settings(memory), force=True, repo_resolver=_ok_repo)
    reading_settings.update(agent_enabled_=True, acknowledge=True)
    for chosen in ("browser-harness", "own", "auto"):
        agent_methods.set_choice("reading", chosen)
        for variant in ("claude-code", "codex", "generic"):
            text, _ = handshake.load_or_build(memory, variant, variant=variant, cache_dir=tmp_path / f"c-{chosen}-{variant}")
            has_method_line = "- Reading pages:" in text
            if has_method_line:
                assert "your browser tools" not in text, (chosen, variant)
            else:
                assert "with your browser tools" in text, (chosen, variant)
    agent_methods.set_choice("reading", "auto")


def test_the_ask_reply_prompt_carries_the_choice(reading):
    server, memory = reading
    agent_methods.set_choice("reading", "macos-harness")
    out = ask(memory, PUBLIC)
    assert "I chose the `macos-harness` skill for this" in out["prompt"]
