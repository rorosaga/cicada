"""Ask reaches what was said in conversations no page points at (2026-10-19, the search leg).

The owner's eval (60 questions about one conversation each): 25 wrong answers, 25 of them about one known source
conversation; that conversation's own words reached the prompt for 5, although plain episode search ranked it in the
top five for 16. Ask was page-first: a conversation's words arrived only through a shown page's evidence or
provenance. The search leg finds the conversations by the question's own words and shows their matching turns as
OTHER CONVERSATIONS. Synthetic banks only (alice-example, bob-example); no embedding, no network — the vector index
is absent, so the word index alone finds conversations here. The model is a stub that records its prompt.
"""
from __future__ import annotations

import hashlib
import json

import pytest

from api.services import ask_service, ask_sources, bank_index, evidence, markdown_parser, search_index


def _episode(memory, ep_id: str, turns: list[str], **fm) -> None:
    body = "\n".join(turns) + "\n"
    meta = {"id": ep_id, "timestamp": f"{ep_id[3:13]}T10:00:00+00:00", "processed": True, "source": "import",
            "content_hash": evidence.body_hash(body), **fm}
    markdown_parser.write(memory / "episodes" / f"{ep_id}.md", meta, body)


def _filler(i: int) -> list[str]:
    return [f"user: Can you help me plan the weekly errands list number {i}?",
            f"assistant: Sure, here is a plan for errands list {i}: groceries, laundry and the bank."]


@pytest.fixture
def bank(tmp_path):
    memory = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (memory / sub).mkdir(parents=True)
    for i in range(1, 9):
        _episode(memory, f"ep_2024-0{i}-01_001", _filler(i))
    # The decision, said once, in the middle of a long multi-topic export that no page cites.
    long_turns = []
    for i in range(40):
        long_turns += [f"user: Another question about the garden irrigation schedule, part {i}.",
                       f"assistant: The irrigation schedule part {i} looks fine; water early in the morning."]
    long_turns[41] = ("user: For alpha-project I decided on Postgres over the document store, because the reports "
                      "need joins.")
    _episode(memory, "ep_2025-03-14_001", long_turns, title="Chat export")
    # The person's page exists but says nothing about the decision.
    markdown_parser.write(memory / "entities" / "alice-example.md",
                          {"name": "Alice Example", "type": "person", "status": "active", "owner": True},
                          "## Summary\nAlice Example is the person this memory belongs to.\n")
    assert search_index.ensure_fresh(memory, wait=True) == "ready"
    bank_index.invalidate()
    yield memory
    bank_index.invalidate()


def _hit(entity_id: str) -> dict:
    return {"score": 0.9, "text": "", "metadata": {"entity_id": entity_id, "entity_name": entity_id, "type": "person",
                                                    "status": "active", "file_path": ""}}


class _Model:
    def __init__(self, reply: dict | None = None):
        self.prompts: list[str] = []
        self.reply = reply or {"answer": "stub", "confidence": 0.8, "used_entities": [], "gaps": []}

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return json.dumps(self.reply)


def _ask(bank, question: str, *, pages=("alice-example",), model=None, **kw):
    model = model or _Model()
    result = ask_service.answer_query(bank, question, retrieve_fn=lambda q, k: [_hit(p) for p in pages],
                                      llm_fn=model, no_engine=False, **kw)
    return result, model


def _tree(memory) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in memory.rglob("*") if p.is_file() and p.name != search_index.DB_FILE
                       and not p.name.startswith(search_index.DB_FILE)):
        digest.update(path.relative_to(memory).as_posix().encode() + path.read_bytes())
    return digest.hexdigest()


def test_a_decision_deep_in_a_long_export_no_page_cites_reaches_the_model(bank):
    before = _tree(bank)
    _, model = _ask(bank, "Which database did I choose for alpha-project?")
    [prompt] = model.prompts
    other = prompt.split("OTHER CONVERSATIONS", 1)[1]
    assert "I decided on Postgres over the document store" in other
    assert "[ep_2025-03-14_001], Alice Example (the person this memory belongs to)" in other, "dated, its conversation and speaker"
    assert "WHAT WAS SAID" not in prompt, "no page pointed there: the words come only from the search leg"
    assert _tree(bank) == before, "Ask never writes to the bank"


def test_without_the_sources_scope_the_leg_never_runs(bank):
    called = []
    _, model = _ask(bank, "Which database did I choose for alpha-project?", source_words=False,
                    search_fn=lambda m, q: called.append(q))
    assert not called
    assert "OTHER CONVERSATIONS" not in model.prompts[0] and "Postgres" not in model.prompts[0]


def test_no_page_but_a_conversation_answers_calls_the_model_and_cites_the_conversation(bank):
    reply = {"answer": "Postgres.", "confidence": 0.8, "used_entities": ["ep_2025-03-14_001"],
             "used_conversations": ["ep_2025-03-14_001", "ep_9999-01-01_001"], "gaps": []}
    result, model = _ask(bank, "Which database was chosen for alpha-project?", pages=(), model=_Model(reply))
    assert len(model.prompts) == 1, "a conversation to ground on is not a gap"
    assert result["answer"] == "Postgres."
    assert result["used_entities"] == [], "an episode id is not an invented entity"
    assert [c["episode_id"] for c in result["conversations"]] == ["ep_2025-03-14_001"], "only ids that were shown"
    assert result["conversations"][0]["title"] == "Chat export"


def test_omitted_used_conversations_falls_back_to_every_one_shown(bank):
    result, _ = _ask(bank, "Which database was chosen for alpha-project?", pages=())
    assert [c["episode_id"] for c in result["conversations"]] == ["ep_2025-03-14_001"]


def test_nothing_found_by_pages_or_words_is_still_the_honest_gap(bank):
    result, model = _ask(bank, "What is the capital of Zanzibarland?", pages=())
    assert model.prompts == [], "the gap fast path never calls the model"
    assert result["confidence"] <= 0.05 and result["conversations"] == []


def test_a_turn_holding_only_common_words_is_never_shown(bank):
    # "errands" and "plan" are in most of the bank's conversations: they rank nothing.
    found = ask_sources.search(bank, "What errands did I plan?")
    assert "errand" not in found.weights and "plan" not in found.weights
    _, model = _ask(bank, "What errands did I plan?")
    assert "OTHER CONVERSATIONS" not in model.prompts[0]


def test_index_only_episodes_are_never_shown(bank):
    from api.services import history_index

    _episode(bank, "ep_2025-05-01_001", ["user: Watched: the alpha-project Postgres talk"],
             source=history_index.HISTORY_SOURCE)
    search_index.ensure_fresh(bank, wait=True, max_age_s=0)
    found = ask_sources.search(bank, "Which Postgres talk about alpha-project?")
    assert "ep_2025-05-01_001" in found.episodes, "the index finds it"
    shown = ask_sources.gather_search(bank, "Which Postgres talk about alpha-project?", found)
    assert "ep_2025-05-01_001" not in {e.episode for e in shown}, "ruling 30: a watched day is a record, not words"


def test_an_agents_saved_note_is_never_the_persons_words(bank):
    _episode(bank, "ep_2025-06-01_001", ["The person prefers Postgres for alpha-project reporting."], source="mcp")
    search_index.ensure_fresh(bank, wait=True, max_age_s=0)
    _, model = _ask(bank, "Does alpha-project reporting use Postgres?")
    other = model.prompts[0].split("OTHER CONVERSATIONS", 1)[1]
    assert "[ep_2025-06-01_001], an agent's saved note (not the person's own words)" in other


def test_the_assistants_words_are_labelled_as_the_assistants(bank):
    _episode(bank, "ep_2025-07-01_001", ["user: What should alpha-project use for queues?",
                                         "assistant: I would suggest a Kafkaesque broker for alpha-project queues."])
    search_index.ensure_fresh(bank, wait=True, max_age_s=0)
    _, model = _ask(bank, "Which broker for alpha-project queues?")
    other = model.prompts[0].split("OTHER CONVERSATIONS", 1)[1]
    assert "the assistant (an AI agent, not the person): \"I would suggest a Kafkaesque broker" in other


def test_a_turn_the_page_leg_showed_is_not_repeated(bank):
    found = ask_sources.search(bank, "Which database did I choose for alpha-project?")
    first = ask_sources.gather_search(bank, "Which database did I choose for alpha-project?", found)
    again = ask_sources.gather_search(bank, "Which database did I choose for alpha-project?", found,
                                      taken=ask_sources.shown_turns(first))
    assert first and not ({(e.episode, e.order[2]) for e in first} & {(e.episode, e.order[2]) for e in again})


def test_the_leg_is_bounded(bank):
    for i in range(30):
        _episode(bank, f"ep_2026-01-{i + 1:02d}_001",
                 [f"user: alpha-project Postgres note {i}: " + "the reporting joins need care " * 30])
    search_index.ensure_fresh(bank, wait=True, max_age_s=0)
    found = ask_sources.search(bank, "alpha-project Postgres reporting joins")
    shown = ask_sources.gather_search(bank, "alpha-project Postgres reporting joins", found)
    assert len({e.episode for e in shown}) <= ask_sources.SEARCH_EPISODES
    assert len(shown) <= ask_sources.SEARCH_EXCERPTS
    assert sum(len(e.text) for e in shown) <= ask_sources.SEARCH_CHARS


def test_the_question_is_never_logged(bank, monkeypatch):
    from loguru import logger

    lines: list[str] = []
    sink = logger.add(lambda m: lines.append(str(m)), level="DEBUG")

    def boom(*a, **k):
        raise RuntimeError("Which database did I choose for alpha-project?")

    monkeypatch.setattr(search_index, "Reader", boom)
    try:
        found = ask_sources.search(bank, "Which database did I choose for alpha-project?")
    finally:
        logger.remove(sink)
    assert found.episodes == []
    assert lines and not any("alpha-project" in line or "database" in line for line in lines)
