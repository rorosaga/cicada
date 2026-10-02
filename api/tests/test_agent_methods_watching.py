"""Ruling 17 / G178 — "How your agent watches": the second job of `agent_methods`. Same mechanism as reading (a selection
saved on this Mac, an instruction to the person's own agent, never authority), offered for the watching job: the video
skill, the browser harness and the Mac harness beside "Let my agent choose" and the agent's own tools. One choice per job;
the choice reaches the video hand-off prompt (within its cap), the stdio claim reply and the primer, never a remote
connection; a picked skill files its graph page and nothing else does."""
from __future__ import annotations

import re

import pytest

from _stdio_server import stdio_server
from _synthetic_bank import _bank, _ok_repo, _settings
from _video_fixtures import bank_with_videos
from api.remote import catalog
from api.remote.runtime import RemoteRuntime
from api.services import agent_methods, handshake, mcp_tools, skill_catalog, state_dictionary, video_prompt, video_queue
from test_handshake_r12 import _check

WATCH_SKILLS = ("watch", "browser-harness", "macos-harness")
BANNED = re.compile(r"\b(gemini|google|claude|codex|chatgpt|openai|anthropic|ollama|openrouter|sonnet|haiku|opus|gpt|"
                    r"grok|mistral|groq|whisper)\b", re.I)


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))


def _schemas():
    return {t["name"]: set(t["inputSchema"].get("properties", {})) for t in stdio_server().TOOLS}


def test_watching_is_a_job_with_its_own_choice_and_the_three_skills_are_offered():
    assert "watching" in agent_methods.JOBS and agent_methods.JOBS["watching"].question == "How your agent watches"
    opts = agent_methods.options("watching")
    assert [o["id"] for o in opts] == ["auto", "own", *WATCH_SKILLS]
    assert [o["title"] for o in opts[:2]] == ["Let my agent choose", "Its own tools for watching"]
    assert agent_methods.options("reading") and "watch" not in [o["id"] for o in agent_methods.options("reading")]
    assert agent_methods.choice("watching") == agent_methods.AUTO
    agent_methods.set_choice("watching", "macos-harness")
    assert agent_methods.choice("watching") == "macos-harness" and agent_methods.choice("reading") == agent_methods.AUTO
    agent_methods.set_choice("reading", "browser-harness")
    assert (agent_methods.choice("reading"), agent_methods.choice("watching")) == ("browser-harness", "macos-harness")
    with pytest.raises(agent_methods.MethodError):
        agent_methods.set_choice("watching", "pdf")
    with pytest.raises(agent_methods.MethodError):
        agent_methods.set_choice("reading", "watch")  # a video skill is not one of the reading choices


def test_the_mac_harness_option_says_plainly_it_controls_the_whole_mac():
    (option,) = [o for o in agent_methods.options("watching") if o["id"] == "macos-harness"]
    assert "any app on your Mac" in option["reach"]


def test_the_prompt_clause_exists_only_when_chosen_and_fits_the_cap_for_every_choice():
    assert agent_methods.prompt_clause("watching") is None
    base = video_prompt.build(3, "auto")
    assert video_prompt.method_clause(None) is None and "chose" not in base
    assert "with your own tools" in base
    for chosen in ("own", *WATCH_SKILLS):
        agent_methods.set_choice("watching", chosen)
        clause = video_prompt.method_clause(None)
        assert clause and not BANNED.search(clause.replace("browser-harness", "x")), clause
        assert len(clause) <= video_prompt.MAX_METHOD_CLAUSE_CHARS, (chosen, len(clause), clause)
        text = video_prompt.build(99, "link", browser_clause=video_prompt.BROWSER_CLAUSE, method_clause=clause)
        assert clause in text and len(text) <= video_prompt.MAX_CHARS, (chosen, len(text))
        assert "with the tool I chose" in text and "with your own tools" not in text
        if chosen != "own":
            assert f'`engine` "{chosen}"' in clause, "the argument named exists on cicada_record_watch"
    assert "engine" in _schemas()["cicada_record_watch"]


def test_the_hand_off_routes_carry_the_clause_only_when_chosen(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from api import config, main

    memory, _keys = bank_with_videos(tmp_path, 1)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    try:
        client = TestClient(main.app)
        off = client.get("/videos/run/prompt", params={"count": 2, "method": "auto"}).json()["prompt"]
        assert "I chose" not in off
        agent_methods.set_choice("watching", "watch")
        on = client.get("/videos/run/prompt", params={"count": 2, "method": "auto"}).json()["prompt"]
        assert "I chose the `watch` skill" in on and len(on) <= video_prompt.MAX_CHARS
        assert "`macos-harness`" not in on, "one choice per job"
    finally:
        config.get_settings.cache_clear()


def _claim(memory, keys, *, client_name, harness="claude-code", remote=False):
    video_queue.path_for(memory).unlink(missing_ok=True)  # the queue file is per bank NAME, shared by these fixtures
    video_queue.put(memory, keys[0], "watch")
    ctx = mcp_tools.ToolContext(memory_path=lambda: memory, session_id="ses_w", harness=harness,
                                client_name=client_name)
    return mcp_tools.video_claim(ctx)


def test_the_claim_reply_carries_the_clause_for_a_catalog_agent_only(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_tools, "_backend_sleep_running", lambda *a, **k: False)
    memory, keys = bank_with_videos(tmp_path, 1)
    out = _claim(memory, keys, client_name="claude-code")
    assert "person chose" not in out and "with your own tools" in out
    agent_methods.set_choice("watching", "browser-harness")
    memory2, keys2 = bank_with_videos(tmp_path / "b", 1)
    out = _claim(memory2, keys2, client_name="claude-code")
    assert 'The person chose the `browser-harness` skill for this' in out and 'set `engine` to "browser-harness"' in out
    assert "with the tool the person chose" in out
    memory3, keys3 = bank_with_videos(tmp_path / "c", 1)
    generic = _claim(memory3, keys3, client_name="cursor", harness="cursor")
    assert "browser-harness" not in generic and "with your own tools" in generic, "a client that cannot have the skill"
    agent_methods.set_choice("watching", "own")
    memory4, keys4 = bank_with_videos(tmp_path / "d", 1)
    own = _claim(memory4, keys4, client_name="cursor", harness="cursor")
    assert "your own built-in tools for this" in own


def test_a_remote_connection_never_hears_the_choice(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_tools, "_backend_sleep_running", lambda *a, **k: False)
    memory, keys = bank_with_videos(tmp_path, 1)
    agent_methods.set_choice("watching", "macos-harness")
    video_queue.put(memory, keys[0], "watch")
    assert video_prompt.method_clause(memory, reply=True, variant="claude-code", remote=True) is None
    runtime = RemoteRuntime(memory_path=lambda: memory, post=lambda p, d: {}, sleep_running=lambda: False)
    connector = catalog.Connector(id="aaaaaaaa", label="Phone", app="chatgpt", scopes=frozenset(catalog.DEFAULT_SCOPES),
                                  created_at="2026-09-01T00:00:00+00:00")
    text, status = runtime.call(connector, "cicada_video_claim", {})
    assert status == "ok" and "macos-harness" not in text and "person chose" not in text
    assert "with your own tools" in text
    remote, _ = handshake.load_or_build(memory, variant="remote", tools=catalog.tool_names_for(catalog.DEFAULT_SCOPES),
                                        cache_dir=tmp_path / "rc")
    assert "macos-harness" not in remote and "Watching videos" not in remote


def test_the_primer_line_is_r12_true_local_only_and_never_moves_the_reading_phrase(tmp_path):
    assert agent_methods.capability_line("watching", "claude-code") is None
    agent_methods.set_choice("watching", "macos-harness")
    line = agent_methods.capability_line("watching", "claude-code")
    assert line.startswith("- Watching videos: the person chose the `macos-harness` skill for it.")
    assert "say so and stop" in line
    _check(line, _schemas())
    assert agent_methods.capability_line("watching", "generic") is None, "a skill only where it can be installed"
    agent_methods.set_choice("watching", "own")
    assert "your own built-in tools" in agent_methods.capability_line("watching", "generic")
    agent_methods.set_choice("watching", "watch")
    memory = _bank(tmp_path)
    state_dictionary.refresh(memory, _settings(memory), force=True, repo_resolver=_ok_repo)
    cache = tmp_path / "cache"
    text, meta = handshake.load_or_build(memory, "claude-code", variant="claude-code", cache_dir=cache)
    assert "- Watching videos: the person chose the `watch` skill for it." in text
    assert "- Reading pages:" not in text
    _check(text, _schemas())
    agent_methods.set_choice("watching", "auto")
    again, meta2 = handshake.load_or_build(memory, "claude-code", variant="claude-code", cache_dir=cache)
    assert meta2["cached"] is False and "Watching videos" not in again, "the choice is part of the cache key"


def test_the_primer_with_every_method_line_and_all_bridges_stays_inside_the_unraised_budget():
    bridges = tuple(skill_catalog.BRIDGE_TEXT[k].format(names="`x` is") for k in ("papers", "video", "meetings"))
    agent_methods.set_choice("reading", "browser-harness")
    agent_methods.set_choice("watching", "macos-harness")
    from api.services import reading_settings

    reading_settings.update(agent_enabled_=True, acknowledge=True)
    methods = agent_methods.method_lines("claude-code")
    assert len(methods) == 2 and methods[0].startswith("- Reading pages:") and methods[1].startswith("- Watching videos:")
    text = handshake.build(None, variant="claude-code", bank="memory", tz="Europe/Madrid", bridges=bridges,
                           reading=True, methods=methods, reading_tools="the tool the person chose")
    assert len(text) // 4 <= 1550, len(text) // 4  # 1,525 on dev; G61 S3-a item 4 (~25 tokens): 1,550 leaves the state block 250


def test_the_page_is_written_only_on_selection(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from api import config, main
    from api.services import markdown_parser

    memory = _bank(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    try:
        client = TestClient(main.app)
        r = client.put("/agent-methods", json={"job": "watching", "choice": "own"})
        assert r.status_code == 200 and r.json()["write"] == {"page": "none"}
        client.put("/agent-methods", json={"job": "watching", "choice": "auto"})
        assert not list((memory / "entities").glob("*harness*")) and not (memory / "entities" / "claude-video.md").exists()
        r = client.put("/agent-methods", json={"job": "watching", "choice": "watch"})
        body = r.json()
        assert r.status_code == 200 and body["job"] == "watching" and body["write"] == {"page": "created"}
        fm = markdown_parser.parse(memory / "entities" / "claude-video.md").frontmatter
        assert fm["type"] == "skill" and "agent-skill" in fm["tags"]
        assert agent_methods.choice("reading") == agent_methods.AUTO, "one choice per job"
        bad = client.put("/agent-methods", json={"job": "watching", "choice": "pdf"})
        assert bad.status_code == 422 and bad.json()["detail"] == "That isn't one of the choices for how your agent watches."
    finally:
        config.get_settings.cache_clear()
