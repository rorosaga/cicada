"""Lean reads (2026-10-27, G140/G148/G149): recall costs what it is worth, every episode id Cicada prints reads
through a tool the agent already holds, and an answer names who was on the other side of a conversation.

The evidence (local, values redacted): one recall was 14,400 characters — 7 pages, 5 off-topic, the one relevant
page saying its facts three times — and Ask said "the assistant" where the episode recorded a Claude Code session
with its resumable id. Synthetic banks, placeholders only.
"""
from __future__ import annotations

import re

import pytest

from _stdio_server import stdio_server
from _synthetic_bank import _bank, _entity
from api.remote import catalog
from api.remote.runtime import DENIED_TEXT, RemoteRuntime
from api.services import ask_sources, entity_body, episode_actor, markdown_parser, mcp_tools, search_index, \
    tool_door, vector_index

mcp = stdio_server()


# --------------------------------------------------------------------------- the floor and the budget


def _v(eid, score):
    return {"entity_id": eid, "source": "vector", "score": score}


def _k(eid, score):
    return {"entity_id": eid, "source": "lexical", "score": score}


def test_the_floor_keeps_pages_near_a_legs_best_and_drops_the_tail():
    semantic = [_v("alpha-project", 0.80), _v("beta-project", 0.78), _v("noise-a", 0.70), _v("noise-b", 0.69)]
    keyword = [_k("alpha-project", 9.0), _k("bob-example", 6.0), _k("noise-c", 3.0)]
    merged = mcp_tools._rrf_fuse(semantic, keyword, [])
    shown = [h["entity_id"] for h in mcp_tools._above_floor(merged, semantic, keyword, [])]
    # alpha: both legs; beta: 0.02 below the best cosine; bob: 2/3 of the best word score.
    assert set(shown) == {"alpha-project", "beta-project", "bob-example"}
    assert shown[0] == "alpha-project"


def test_the_floor_never_shows_more_than_its_cap_and_never_fewer_than_the_top_one():
    semantic = [_v(f"page-{i}", 0.80 - i * 0.001) for i in range(3)]
    keyword = [_k(f"word-{i}", 5.0) for i in range(3)]
    claims = [{"entity_id": f"claim-{i}", "source": "claim"} for i in range(3)]
    merged = mcp_tools._rrf_fuse(semantic, keyword, claims)
    assert len(mcp_tools._above_floor(merged, semantic, keyword, claims)) == mcp_tools.RECALL_PAGES_SHOWN
    # A top hit no leg puts near its best (a leg-less fused hit) is still shown, alone.
    lonely = [{"entity_id": "only-one"}]
    assert [h["entity_id"] for h in mcp_tools._above_floor(lonely, [], [], [])] == ["only-one"]


def test_the_claim_leg_passes_by_rank_alone():
    claims = [{"entity_id": "c1", "source": "claim", "score": 0.0}, {"entity_id": "c2", "source": "claim"}]
    merged = mcp_tools._rrf_fuse([], [], claims)
    assert [h["entity_id"] for h in mcp_tools._above_floor(merged, [], [], claims)] == ["c1", "c2"]


@pytest.fixture
def bank(tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox", "hubs"):
        (memory / sub).mkdir(parents=True)

    class _NoIndex:
        def __init__(self, *a, **k):
            raise RuntimeError("no vector index in this bank")

    monkeypatch.setattr(vector_index, "SqliteVecIndexer", _NoIndex)
    monkeypatch.setattr(mcp, "get_memory_path", lambda: memory)
    monkeypatch.setattr(mcp, "_STATE_HINT_SENT", False)
    monkeypatch.setattr(mcp.mcp_tools, "_relevant_inbox", lambda memory_path, query, **_: [])
    return memory


def _long_page(memory, eid, *, word="zephyr"):
    facts = "\n".join(f"- {eid} {word} fact {i} on 2026-0{1 + i % 9}-1{i % 9} with a realistic long tail of words."
                      for i in range(60))
    body = (f"## Summary\n{eid} is a {word} page.\n\n## Key Facts\n{facts}\n\n## Article\n" + ("prose " * 800)
            + "\n\n## History\n" + "\n".join(f"- 2026-02-0{1 + i % 9}: {word} event {i}" for i in range(40)) + "\n")
    markdown_parser.write(memory / "entities" / f"{eid}.md",
                          {"name": eid, "type": "project", "status": "active", "confidence": 0.6, "aliases": [],
                           "tags": [], "related": []}, body)


def test_a_recall_over_many_long_matching_pages_stays_inside_the_lean_budget(bank):
    for i in range(9):
        _long_page(bank, f"zephyr-page-{i}")
    search_index.ensure_fresh(bank, wait=True)
    reply = mcp.handle_recall("zephyr")
    pages = re.findall(r"^### zephyr-page-\d", reply, re.M)
    assert 1 <= len(pages) <= mcp_tools.RECALL_PAGES_SHOWN
    # The best page's body is RECALL_TOP_BODY, the others RECALL_OTHER_BODY, plus a heading and a hints block each.
    ceiling = mcp_tools.RECALL_TOP_BODY + (len(pages) - 1) * mcp_tools.RECALL_OTHER_BODY + 400 * len(pages) + 1_200
    assert len(reply) <= ceiling, (len(reply), ceiling)
    assert "more on the full page" in reply   # a cut is said in words, never silent


# --------------------------------------------------------------------------- collapsing repeated facts


def test_collapse_folds_only_bullets_whose_words_and_anchors_are_already_shown():
    summary = "Alpha Project is an application with a draft ready, open on a rolling review since 2026-09-19."
    facts = ["- The application draft was ready.",                               # repeats the summary
             "- A draft was ready for the application.",                          # repeats it again
             "- The application draft was ready on 2026-09-20.",                  # a new date: kept
             "- Bob Example reviewed the application draft.",                     # a new name: kept
             "- The form takes 20-40 minutes.",                                   # new words: kept
             "- See https://alpha.example/apply for the draft."]                  # a new link: kept
    kept, folded = entity_body.collapse_repeats(facts, summary)
    assert folded == 2
    assert kept == facts[2:]


def test_collapse_never_drops_a_distinct_fact_however_many_repeats_surround_it():
    summary = "Gamma runs nightly."
    facts = ["- Gamma runs nightly."] * 10 + ["- Gamma moved to the Lisbon cluster."] + ["- Gamma runs nightly."] * 5
    kept, folded = entity_body.collapse_repeats(facts, summary)
    assert "- Gamma moved to the Lisbon cluster." in kept and folded == 15


def test_collapse_keeps_prose_lines_and_the_page_is_never_edited(bank):
    body = ("## Summary\nDelta is a tool.\n\n## Key Facts\n- Delta is a tool.\n- Delta is a tool.\n"
            "- Delta costs 5 euros.\nnot a bullet\n")
    path = bank / "entities" / "delta.md"
    markdown_parser.write(path, {"name": "Delta", "type": "tool", "status": "active"}, body)
    before = path.read_text()
    out = mcp_tools._type_aware_truncate(markdown_parser.parse(path).body, "tool", max_chars=1_800, collapse=True)
    assert "- Delta costs 5 euros." in out and "not a bullet" in out
    assert out.count("- Delta is a tool.") == 0
    assert "2 more line(s) here repeat the facts above" in out
    assert path.read_text() == before
    # Without `collapse` (every other caller) the old rendering holds.
    assert entity_body.summarize_for_recall(body).count("- Delta is a tool.") == 2


# --------------------------------------------------------------------------- the actor line


def _episode(memory, eid, fm, body="user: hello\nassistant: hi there\n"):
    markdown_parser.write(memory / "episodes" / f"{eid}.md",
                          {"id": eid, "timestamp": f"{eid[3:13]}T10:00:00+00:00", "processed": True, **fm}, body)


@pytest.mark.parametrize("fm, expected", [
    ({"harness": "claude-code", "session_id": "ses-a1", "source": "claude-code",
      "turns": [{"offset": 0, "speaker": "user"}, {"offset": 9, "speaker": "assistant", "model": "model-x"}]},
     "a Claude Code session (id ses-a1, resumable, model model-x)"),
    ({"harness": "codex", "session_id": "ses-b2", "source": "codex"}, "a Codex session (id ses-b2, resumable)"),
    ({"harness": "cursor", "session_id": "ses-c3", "source": "cursor"}, "a Cursor session (id ses-c3)"),
    ({"harness": "claude-code", "session_id": "ses-d4", "source": "mcp"},
     "an agent's saved note from a Claude Code session (id ses-d4)"),
    ({"harness": "claude-web", "session_id": "rc_x", "relay": {"app": "claude", "channel": "remote"}},
     "Claude, relayed through the remote connector"),
    ({"origin": "imessage", "service": "iMessage", "correspondent": {"name": "Agent-example", "kind": "agent"}},
     "Agent-example (an AI agent), over Messages"),
    ({"origin": "imessage", "service": "SMS", "correspondent": {"name": "Bob Example", "kind": "person"}},
     "Bob Example, over Messages"),
    ({"origin": "chatgpt-export"}, "ChatGPT, from the person's exported conversations"),
    ({"origin": "wispr-flow"}, None),   # the person alone: nobody else to name
    ({}, None),
])
def test_the_actor_comes_from_the_episodes_own_fields(fm, expected):
    assert episode_actor.actor(fm) == expected


def test_the_short_actor_drops_the_id_for_asks_speaker_labels():
    fm = {"harness": "claude-code", "session_id": "ses-a1", "source": "claude-code"}
    assert episode_actor.actor(fm, ids=False) == "a Claude Code session"


def test_asks_speaker_label_names_the_agent_and_keeps_the_old_words_when_the_record_names_nobody():
    class Turn:
        role, marker = "assistant", None

    assert ask_sources._who(Turn, {"harness": "claude-code", "session_id": "s", "source": "claude-code"}, "Owner") \
        == "a Claude Code session — the assistant, not the person"
    texted = {"correspondent": {"name": "Agent-example", "kind": "agent"}, "service": "iMessage"}
    assert ask_sources._who(Turn, texted, None).startswith("Agent-example (an AI agent), over Messages")
    # An imported or benchmark conversation names nobody: the prompt's words are byte for byte what they were.
    assert ask_sources._who(Turn, {"source": "import"}, None) == "the assistant (an AI agent, not the person)"


def test_asks_reply_names_who_spoke_in_listed_and_cited_conversations(tmp_path):
    memory = _bank(tmp_path)
    _episode(memory, "ep_2026-10-21_004", {"harness": "claude-code", "session_id": "ses-form", "source": "claude-code"})
    _episode(memory, "ep_2026-10-10_001", {"origin": "imessage", "service": "iMessage",
                                           "correspondent": {"name": "Agent-example", "kind": "agent"}})
    _episode(memory, "ep_2026-10-11_001", {"origin": "wispr-flow"})
    result = {"answer": "The form was filled in by an agent.", "confidence": 0.7, "gaps": [],
              "citations": [{"entity_name": "Alpha Project",
                             "source_episodes": ["ep_2026-10-10_001", "ep_2026-10-11_001"]}],
              "conversations": [{"episode_id": "ep_2026-10-21_004", "title": "form", "day": "2026-10-21"}]}
    stdio = mcp_tools.ToolContext(memory_path=lambda: memory, session_id="s", harness="claude-code")
    text = mcp_tools._render_ask(result, stdio)
    assert "- ep_2026-10-21_004 · 2026-10-21 · form · with a Claude Code session (id ses-form, resumable)" in text
    assert "- ep_2026-10-10_001 · with Agent-example (an AI agent), over Messages" in text
    assert "ep_2026-10-11_001 · with" not in text   # the person alone: no label, never a guess
    assert 'cicada_sources(entity_id="<episode id>")' in text
    # A remote connection without the sources scope is never pointed at a tool it lacks (R12).
    remote = mcp_tools.ToolContext(memory_path=lambda: memory, session_id="s", harness="claude-web",
                                   connector_id="ab12cd34", available=catalog.tool_names_for({"ask"}))
    assert "cicada_sources" not in mcp_tools._render_ask(result, remote)
    # Without a context (an old caller) the reply is what it was.
    assert "with a Claude Code" not in mcp_tools._render_ask(result)


# --------------------------------------------------------------------------- the episode read, on every door


def _seed_episode(memory):
    _episode(memory, "ep_2026-10-21_004",
             {"harness": "claude-code", "session_id": "ses-form", "source": "claude-code", "title": "Fill the form"},
             body="user: please fill the application form\nassistant: " + ("filled field. " * 400)
             + "\nassistant: Left the submit button to you.\n")


def test_stdio_reads_an_episode_id_with_its_actor_and_the_fence(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    _seed_episode(memory)
    monkeypatch.setattr(mcp, "get_memory_path", lambda: memory)
    result = mcp.call_tool("cicada_sources", {"entity_id": "ep_2026-10-21_004"})
    text = result["content"][0]["text"]
    assert "cicada-reference" in text   # fenced as reference data, like every read
    assert "**Conversation `ep_2026-10-21_004`** · 2026-10-21 · Fill the form" in text
    assert "With: a Claude Code session (id ses-form, resumable)." in text
    assert "please fill the application form" in text and "Left the submit button to you." in text


def test_a_long_episode_is_cut_with_the_cut_and_the_next_read_said(tmp_path):
    memory = _bank(tmp_path)
    _episode(memory, "ep_2026-10-21_005", {"harness": "claude-code", "session_id": "s", "source": "claude-code"},
             body="user: go\n" + "\n".join(f"assistant: line {i} " + "x" * 80 for i in range(400)))
    stdio = mcp_tools.ToolContext(memory_path=lambda: memory, session_id="s", harness="claude-code")
    text = str(mcp_tools.sources(stdio, "ep_2026-10-21_005"))
    assert len(text) <= mcp_tools.EPISODE_READ_MAX + 600
    assert '`cicada_continue(session="ep_2026-10-21_005")` pages the rest by turn.' in text


def test_a_page_named_like_an_episode_id_still_reads_as_the_page_and_a_missing_id_is_not_found(tmp_path):
    memory = _bank(tmp_path)
    stdio = mcp_tools.ToolContext(memory_path=lambda: memory, session_id="s", harness="claude-code")
    missing = mcp_tools.sources(stdio, "ep_2026-01-01_999")
    assert getattr(missing, "code", None) == "not_found"
    assert getattr(mcp_tools.sources(stdio, "ep_../../etc"), "code", None) != "error"


def test_the_remote_door_reads_an_episode_only_with_the_sources_scope_and_at_its_cap(tmp_path, monkeypatch):
    from api import config

    memory = _bank(tmp_path)
    _seed_episode(memory)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    try:
        runtime = RemoteRuntime(post=lambda p, d: {}, sleep_running=lambda: False)
        conn = lambda scopes: catalog.Connector(id="ab12cd34", label="Phone", app="claude",  # noqa: E731
                                                scopes=frozenset(scopes), created_at="2026-09-01T00:00:00+00:00",
                                                last_client="claude-ai")
        denied = runtime.call(conn(catalog.DEFAULT_SCOPES), "cicada_sources", {"entity_id": "ep_2026-10-21_004"})
        assert denied == (DENIED_TEXT, "denied")
        text, status = runtime.call(conn({"sources"}), "cicada_sources", {"entity_id": "ep_2026-10-21_004"})
        assert status == "ok"
        assert "With: a Claude Code session (id ses-form, resumable)." in text
        assert "please fill the application form" in text
        assert "Left the submit button to you." not in text       # R-R28: 1,000 characters remotely
        assert "cicada_continue" not in text                       # a stdio-only tool is never named remotely
    finally:
        config.get_settings.cache_clear()


def test_the_device_door_reads_an_episode_as_stdio_would(tmp_path):
    memory = _bank(tmp_path)
    _seed_episode(memory)
    state = tool_door.SessionState()
    ctx = tool_door.context(memory_path=memory, bank_name="default",
                            caller=tool_door.Caller(session_id="ses_x", harness="claude-code"), state=state,
                            surface="mcp", device_id="ab12cd34", backend_url="http://127.0.0.1:9",
                            headers=lambda: {}, post=lambda p, d: {})
    answer = tool_door.run("cicada_sources", {"entity_id": "ep_2026-10-21_004"}, ctx=ctx, state=state,
                           surface="mcp", options={}, root=memory, bank_name="default")
    assert answer.error is None and "Left the submit button to you." in answer.text


def test_recall_excerpts_name_the_actor_and_how_to_read_the_conversation(bank, monkeypatch):
    _entity(bank, "alpha-project", type="project", body="## Summary\nAlpha project zephyr.\n")
    _episode(bank, "ep_2026-10-21_004", {"harness": "claude-code", "session_id": "ses-form", "source": "claude-code"})
    hit = {"text": "user: zephyr form\nassistant: done", "metadata": {"episode_id": "ep_2026-10-21_004"}}
    monkeypatch.setattr(mcp_tools, "_leann_search_episodes", lambda *a, **k: [hit, hit, hit])
    monkeypatch.setattr(mcp_tools, "_lexical_search_episodes", lambda *a, **k: [])
    search_index.ensure_fresh(bank, wait=True)
    reply = mcp.handle_recall("zephyr")
    assert reply.count("[ep_2026-10-21_004]") == 1   # one passage per conversation
    assert "[ep_2026-10-21_004] with a Claude Code session (id ses-form, resumable):" in reply
    assert 'cicada_sources(entity_id="<episode id>")' in reply
