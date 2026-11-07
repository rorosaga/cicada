"""G207 (ROR-29): an agent can look into what Sleep has not consolidated yet.

Ask reads enough of an unread conversation or note to answer from it (whole when short, the matching passages when
long, inside one fixed budget), cites only the pages its answer rests on, and ``cicada_pending`` can be pointed at a
topic. Retrieval, not belief: nothing here writes a page or a claim. Synthetic banks only; the model is a stub that
records its prompt; no embedding, no network.
"""
from __future__ import annotations

import json

import pytest

from api.services import (agentic_write, ask_service, ask_sources, bank_index, evidence, history_index,
                          markdown_parser, search_index)


def _episode(memory, ep_id: str, turns: list[str], *, processed: bool = False, **fm) -> None:
    body = "\n".join(turns) + "\n"
    meta = {"id": ep_id, "timestamp": f"{ep_id[3:13]}T10:00:00+00:00", "processed": processed, "source": "mcp",
            "content_hash": evidence.body_hash(body), **fm}
    markdown_parser.write(memory / "episodes" / f"{ep_id}.md", meta, body)


def _page(memory, page_id: str, name: str, summary: str) -> None:
    markdown_parser.write(memory / "entities" / f"{page_id}.md",
                          {"name": name, "type": "concept", "status": "active"}, f"## Summary\n{summary}\n")


IDEAS = [f"Idea {i}: build the {w} tool for the garden, so that the weekly work is easier and quicker" for i, w in
         enumerate("compost seed water prune trellis shed bench hose label journal".split(), 1)]
NOTE = "Ideas for the garden project, the full list:\n" + "\n".join(IDEAS)
QUESTION = "What ideas does the note list for the garden project?"


@pytest.fixture
def bank(tmp_path):
    memory = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (memory / sub).mkdir(parents=True)
    # Pages that are retrieved but have nothing to do with the answer.
    for i in range(3):
        _page(memory, f"unrelated-{i}", f"Unrelated {i}", f"A page about topic number {i}.")
    yield memory
    bank_index.invalidate()


def _reindex(memory) -> None:
    search_index.ensure_fresh(memory, wait=True, max_age_s=0)
    bank_index.invalidate()


def _hit(entity_id: str) -> dict:
    return {"score": 0.9, "text": "", "metadata": {"entity_id": entity_id, "entity_name": entity_id, "type": "concept",
                                                    "status": "active", "file_path": ""}}


class _Model:
    def __init__(self, reply: dict | None = None):
        self.prompts: list[str] = []
        self.reply = reply or {"answer": "stub", "confidence": 0.8, "used_entities": [], "gaps": []}

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return json.dumps(self.reply)


def _ask(memory, question: str, *, pages=("unrelated-0",), model=None, **kw):
    model = model or _Model()
    result = ask_service.answer_query(memory, question, retrieve_fn=lambda q, k: [_hit(p) for p in pages],
                                      llm_fn=model, no_engine=False, **kw)
    return result, model


def _other(prompt: str) -> str:
    return prompt.split("OTHER CONVERSATIONS", 1)[1]


# --- gap 1: Ask reads enough of what is unread ------------------------------------------------------------------

def test_a_short_unread_note_reaches_the_model_whole(bank):
    assert len(NOTE) > ask_sources.EXCERPT_CHARS, "the fixture must be longer than the usual excerpt"
    _episode(bank, "ep_2026-11-01_001", [NOTE], title="Garden ideas")
    _reindex(bank)
    _, model = _ask(bank, QUESTION)
    other = _other(model.prompts[0])
    assert IDEAS[0].split(":")[1].strip() in other and IDEAS[-1].split(":")[1].strip() in other, "the whole list"
    assert "[ep_2026-11-01_001], not yet read by Sleep" in other
    assert "12. A line of OTHER CONVERSATIONS marked" in ask_service.ASK_SYSTEM_PROMPT


def test_the_same_note_read_by_sleep_keeps_the_usual_excerpt(bank):
    _episode(bank, "ep_2026-11-01_001", [NOTE], title="Garden ideas", processed=True)
    _reindex(bank)
    _, model = _ask(bank, QUESTION)
    other = _other(model.prompts[0])
    assert IDEAS[-1].split(":")[1].strip() not in other, "only the unread are read past the excerpt"
    assert "not yet read by Sleep" not in other


def test_a_long_unread_note_shows_its_matching_passages_only(bank):
    filler = "Nothing about plants here, only an unrelated paragraph on the weekly shopping errands. " * 30
    long_note = (f"Garden ideas, first: build the compost bin. {filler}"
                 f"Garden ideas, second: build the trellis. {filler}"
                 f"Garden ideas, third: build the shed bench. {filler}"
                 f"Garden ideas, fourth: a rain barrel. {filler}")
    assert len(long_note) > 4 * ask_sources.UNREAD_WHOLE_CHARS
    _episode(bank, "ep_2026-11-01_001", [long_note], title="Long notes")
    _reindex(bank)
    _, model = _ask(bank, "What garden ideas does the note list?")
    other = _other(model.prompts[0])
    assert "compost bin" in other and "trellis" in other, "the matching passages"
    assert len(other) < len(long_note) // 2, "not the whole note"
    assert "…" in other, "an ellipsis marks where text was left out"


def test_everything_read_past_the_excerpt_stays_inside_one_budget(bank):
    for n in range(1, 6):
        _episode(bank, f"ep_2026-11-0{n}_001",
                 [f"Garden ideas list {n}: " + " ".join(f"build the tool {w} {n}" for w in range(120))],
                 title=f"Garden {n}")
    _reindex(bank)
    found = ask_sources.search(bank, QUESTION)
    shown = ask_sources.gather_search(bank, QUESTION, found)
    assert shown
    usual = ask_sources.SEARCH_CHARS + ask_sources.UNREAD_EXTRA_CHARS
    assert sum(len(e.text) for e in shown) <= usual + 6 * 40, "the usual budget plus the one unread budget"


def test_the_remote_door_without_the_sources_scope_gets_nothing_new(bank):
    _episode(bank, "ep_2026-11-01_001", [NOTE], title="Garden ideas")
    _reindex(bank)
    _, model = _ask(bank, QUESTION, source_words=False)
    assert "OTHER CONVERSATIONS" not in model.prompts[0] and IDEAS[-1] not in model.prompts[0]


def test_an_index_only_save_is_found_but_never_read_by_the_model(bank):
    """Ruling 62: a save with no reason is indexed; its body reaches no model for a retrieval hit."""
    body = ("A saved link about the garden project ideas.\n" + "Distinctive-body-sentence-zebra " * 40)
    _episode(bank, "ep_2026-11-02_001", [body], title="Garden saved link", source="chrome",
             origin="chrome-bookmark", url="https://example.com/garden")
    assert history_index.is_index_only(markdown_parser.parse(bank / "episodes" / "ep_2026-11-02_001.md").frontmatter)
    _reindex(bank)
    found = ask_sources.search(bank, QUESTION)
    assert "ep_2026-11-02_001" not in found.episodes
    found.episodes.append("ep_2026-11-02_001")
    assert not ask_sources.gather_search(bank, QUESTION, found), "handed to the reader, still never read"
    _, model = _ask(bank, "What garden saved link do I have?")
    assert model.prompts, "the model is called, on the save's title and link only"
    assert all("Distinctive-body-sentence-zebra" not in p for p in model.prompts)
    assert "Garden saved link" in model.prompts[0], "found: the title is a line the model sees"


def test_a_retired_locked_note_never_appears(bank):
    """G234: the locked note is out of ``episodes/``; one that somehow carries the mark is still never read."""
    _episode(bank, "ep_2026-11-03_001", ["Locked garden ideas about quartzmarker " * 10], title="Locked",
             **{evidence.LOCKED_NOTE_KEY: True})
    _reindex(bank)
    found = ask_sources.search(bank, QUESTION)
    found.episodes.append("ep_2026-11-03_001")
    assert not ask_sources.gather_search(bank, QUESTION, found)
    _, model = _ask(bank, "What locked garden ideas do I have?")
    assert all("quartzmarker" not in p for p in model.prompts)


def test_reading_more_writes_nothing(bank):
    _episode(bank, "ep_2026-11-01_001", [NOTE], title="Garden ideas")
    _reindex(bank)
    before = {p: p.read_bytes() for p in (bank / "episodes").iterdir()} | {
        p: p.read_bytes() for p in (bank / "entities").iterdir()}
    _ask(bank, QUESTION)
    after = {p: p.read_bytes() for p in (bank / "episodes").iterdir()} | {
        p: p.read_bytes() for p in (bank / "entities").iterdir()}
    assert before == after


# --- gap 2: citations are what the answer rests on --------------------------------------------------------------

def test_an_answer_resting_on_a_conversation_cites_no_retrieved_page(bank):
    _episode(bank, "ep_2026-11-01_001", [NOTE], title="Garden ideas")
    _reindex(bank)
    reply = {"answer": "Ten ideas (not yet confirmed by Sleep).", "confidence": 0.8, "used_entities": [],
             "used_conversations": ["ep_2026-11-01_001"], "gaps": []}
    result, _ = _ask(bank, QUESTION, pages=("unrelated-0", "unrelated-1", "unrelated-2"), model=_Model(reply))
    assert result["citations"] == [] and result["used_entities"] == []
    assert [c["episode_id"] for c in result["conversations"]] == ["ep_2026-11-01_001"]


def test_the_pages_the_model_lists_are_the_citations(bank):
    reply = {"answer": "x", "confidence": 0.8, "used_entities": ["unrelated-1"], "gaps": []}
    result, _ = _ask(bank, "What is topic number 1?", pages=("unrelated-0", "unrelated-1", "unrelated-2"),
                     model=_Model(reply))
    assert [c["entity_id"] for c in result["citations"]] == ["unrelated-1"]


def test_with_no_list_the_pages_the_answer_names_are_cited(bank):
    reply = {"answer": "The Unrelated 2 page says it is about topic number 2.", "confidence": 0.8, "gaps": []}
    result, _ = _ask(bank, "What is topic number 2?", pages=("unrelated-0", "unrelated-1", "unrelated-2"),
                     model=_Model(reply))
    assert [c["entity_id"] for c in result["citations"]] == ["unrelated-2"]
    assert result["used_entities"] == ["unrelated-2"]


def test_with_no_list_and_no_page_named_nothing_is_cited(bank):
    reply = {"answer": "Memory holds nothing on it.", "confidence": 0.2, "gaps": ["nothing"]}
    result, _ = _ask(bank, "What is topic number 2?", pages=("unrelated-0", "unrelated-1"), model=_Model(reply))
    assert result["citations"] == []


# --- gap 3: cicada_pending can be pointed at a topic ------------------------------------------------------------

def _pending_bank(bank):
    _episode(bank, "ep_2026-10-01_001", ["Notes on the harbour regatta schedule and the boat repairs."], title="Regatta")
    _episode(bank, "ep_2026-10-05_001", ["Notes on the kitchen renovation budget and tiles."], title="Kitchen")
    _episode(bank, "ep_2026-10-09_001", ["Another regatta note: sail numbers for the harbour race."], title="Race")
    _episode(bank, "ep_2026-10-12_001", ["A regatta conversation Sleep already read."], title="Done", processed=True)
    _episode(bank, "ep_2026-10-15_001", ["Saved regatta link " * 10], title="Bare save", source="chrome",
             origin="chrome-bookmark", url="https://example.com/regatta")
    _reindex(bank)


def _ids(text: str) -> list[str]:
    return [line.split("`")[1] for line in text.splitlines() if line.startswith("- `")]


def test_pending_leads_with_the_newest_without_a_query(bank):
    _pending_bank(bank)
    ids = _ids(agentic_write.pending_text(bank, None, {}))
    assert ids[:2] == ["ep_2026-10-15_001", "ep_2026-10-09_001"]
    assert "ep_2026-10-12_001" not in ids, "a conversation Sleep read is not waiting"


def test_pending_with_a_query_lists_only_the_waiting_ones_about_it(bank):
    _pending_bank(bank)
    listed: dict = {}
    ids = _ids(agentic_write.pending_text(bank, None, listed, "harbour regatta"))
    assert set(ids) == {"ep_2026-10-01_001", "ep_2026-10-09_001"}, "unread and about it; no kitchen, no read one"
    assert "ep_2026-10-15_001" not in ids, "a bare save is no conversation (ruling 62)"
    assert set(listed) == set(ids), "each listed one carries the rev its mark must match"


def test_pending_with_a_query_that_matches_nothing_says_so(bank):
    _pending_bank(bank)
    assert agentic_write.pending_text(bank, None, {}, "quantum zeppelin") == "No unprocessed episodes match that query."


def test_the_query_is_never_logged(bank, monkeypatch):
    _pending_bank(bank)
    from loguru import logger

    seen: list[str] = []
    sink = logger.add(lambda m: seen.append(str(m)), level="DEBUG")
    try:
        agentic_write.pending_text(bank, None, {}, "harbour regatta")
    finally:
        logger.remove(sink)
    assert not any("harbour regatta" in m for m in seen)


def test_pending_schema_names_query_and_every_door_agrees():
    import importlib.util
    from pathlib import Path

    from api.services import cli_map

    spec = importlib.util.spec_from_file_location("cicada_mcp_server_ror29",
                                                  Path(__file__).resolve().parents[2] / "mcp" / "server.py")
    server = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server)
    tool = next(t for t in server.TOOLS if t["name"] == "cicada_pending")
    assert set(tool["inputSchema"]["properties"]) == {"limit", "query"}
    assert "newest first" in tool["description"] and "query" in tool["description"]
    row = next(r for r in cli_map.ROWS if r.tool == "cicada_pending")
    assert {a.prop for a in row.args} == {"limit", "query"}


# --- ROR-29: a list question over an unread note ----------------------------------------------------------------

SPREAD = ("Ideas for the garden project, the full list:\n"
          + "\n".join(f"Idea {i}: build the {w} tool for the garden. " + "It helps the weekly work, and I want it soon. " * 5
                      for i, w in enumerate("compost seed water prune trellis shed bench hose".split(), 1)))
_LIST = dict(breadth=True, max_episodes=ask_sources.ENUM_EPISODES, max_excerpts=ask_sources.BREADTH_EXCERPTS,
             total_chars=ask_sources.BREADTH_CHARS)


def test_a_list_over_one_unread_note_of_two_thousand_characters_reaches_the_model_whole(bank):
    assert 2200 < len(SPREAD) <= ask_sources.UNREAD_WHOLE_CHARS
    _episode(bank, "ep_2026-11-01_001", [SPREAD], title="Garden ideas")
    _reindex(bank)
    _, model = _ask(bank, QUESTION)
    other = _other(model.prompts[0])
    assert "build the hose tool" in other, "the last item, near the end of the note"
    assert "build the compost tool" in other


def test_the_page_leg_of_a_list_reads_an_unread_note_past_its_line_too(bank):
    _episode(bank, "ep_2026-11-01_001", [SPREAD], title="Garden ideas")
    found = [ask_sources.Pointer(episode="ep_2026-11-01_001", weight=1, terms={"garden", "ideas"})]
    shown = ask_sources.gather(bank, QUESTION, found, deep={"left": ask_sources.UNREAD_EXTRA_CHARS}, **_LIST)
    assert "build the hose tool" in " ".join(e.text for e in shown)


def test_the_page_leg_keeps_a_read_note_at_its_short_line(bank):
    _episode(bank, "ep_2026-11-01_001", [SPREAD], title="Garden ideas", processed=True)
    found = [ask_sources.Pointer(episode="ep_2026-11-01_001", weight=1, terms={"garden", "ideas"})]
    shown = ask_sources.gather(bank, QUESTION, found, **_LIST)
    assert all(len(e.text) <= ask_sources.BREADTH_EXCERPT_CHARS + 2 for e in shown)


def test_both_legs_of_an_ask_draw_on_one_budget(bank, monkeypatch):
    _episode(bank, "ep_2026-11-01_001", [SPREAD], title="Garden ideas")
    _reindex(bank)
    seen: dict[str, dict] = {}
    for name in ("gather", "gather_search"):
        real = getattr(ask_sources, name)

        def spy(*a, _real=real, _name=name, **kw):
            seen[_name] = kw.get("deep")
            return _real(*a, **kw)

        monkeypatch.setattr(ask_sources, name, spy)
    _ask(bank, QUESTION)
    assert seen.get("gather_search") is not None
    assert seen.get("gather") is None or seen["gather"] is seen["gather_search"]


def test_a_list_reads_an_unread_note_among_the_further_conversations_too(bank):
    for n in range(1, 13):
        _episode(bank, f"ep_2026-10-{n:02d}_001", [f"Garden ideas, number {n}: the garden project list needs a tool."],
                 title=f"Garden {n}", processed=True)
    _episode(bank, "ep_2026-11-01_001", [SPREAD], title="Garden ideas")
    _reindex(bank)
    found = ask_sources.search(bank, QUESTION)
    assert "ep_2026-11-01_001" in found.more or "ep_2026-11-01_001" in found.episodes
    shown = ask_sources.gather_search(bank, QUESTION, found)
    text = " ".join(e.text for e in shown if e.episode == "ep_2026-11-01_001")
    assert "build the hose tool" in text, "the last item, near the end of the note"


def test_a_wide_list_still_gets_a_line_from_every_conversation_inside_one_budget(bank):
    eps = [f"ep_2026-11-{n:02d}_001" for n in range(1, 9)]
    for n, ep in enumerate(eps, 1):
        _episode(bank, ep, [SPREAD.replace("Idea 1", f"Idea {n}x")], title=f"Garden {n}")
    found = [ask_sources.Pointer(episode=ep, weight=1, terms={"garden", "ideas"}) for ep in eps]
    deep = {"left": ask_sources.UNREAD_EXTRA_CHARS}
    shown = ask_sources.gather(bank, QUESTION, found, deep=deep, **_LIST)
    assert {e.episode for e in shown} == set(eps), "one line from every conversation"
    assert all(e.unread for e in shown)
    assert sum(len(e.text) for e in shown) <= len(eps) * (ask_sources.BREADTH_EXCERPT_CHARS + 2) \
        + ask_sources.UNREAD_EXTRA_CHARS, "the short lines plus the one unread budget"
    assert deep["left"] >= 0
    assert "A line of WHAT WAS SAID carries the same mark" in ask_service.ASK_SYSTEM_PROMPT
    assert "not yet read by Sleep" in ask_sources.render(shown)


def test_recall_quotes_no_index_only_save_and_no_locked_note_as_a_conversation(bank):
    """Ruling 62 and G234 hold on recall's turn leg: it reads through the same check Ask does."""
    from api.services import mcp_tools

    _episode(bank, "ep_2026-11-02_001", ["A saved link about the garden project ideas.\n"
                                         + "Distinctive-body-sentence-zebra " * 40],
             title="Garden saved link", source="chrome", origin="chrome-bookmark", url="https://example.com/garden")
    _episode(bank, "ep_2026-11-03_001", [NOTE])
    _reindex(bank)
    ctx = mcp_tools.ToolContext(memory_path=lambda: bank, session_id="s", harness="test")
    out = mcp_tools.recall(ctx, QUESTION)
    assert "Distinctive-body-sentence-zebra" not in out
    assert "ep_2026-11-03_001" in out and "not yet read by Sleep" in out

    remote = mcp_tools.ToolContext(memory_path=lambda: bank, session_id="s", harness="test", raw_excerpts=False)
    assert "Idea 1: build the compost" not in mcp_tools.recall(remote, QUESTION), "no `sources` scope, no words"
