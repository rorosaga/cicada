"""`cicada_ask` reads what the pages say item by item, and the conversations' own words behind them (2026-10-17, G148).

LoCoMo conv-26 through Cicada (2026-10-17): 17 of 19 wrong answers said memory lacked a detail that was (a) on the page,
past a 600-character cut of its one-paragraph ``## Key Facts`` list, or (b) in the conversation a shown claim's evidence
span points at, which Ask never read. Synthetic bank only (alice-example, bob-example); retrieval and the model are
injected — no embedding, no network. The model is a stub that records the prompt it was shown.
"""
from __future__ import annotations

import hashlib
import json

import pytest

from api.services import ask_service, bank_index, evidence, markdown_parser, mcp_tools, section_provenance
from api.services.claims import Claim, Evidence, write_claims

EPISODE = "ep_2023-06-27_001"
TURNS = [
    "user: Hey Bob! Look at this necklace.",
    "speaker:bob-example: Love it, any special meaning to it?",
    "user: It was a gift from my grandma, and it stands for love, faith and strength.",
    "speaker:bob-example: How long have you had it?",
    "user: Since I was ten.",
    "assistant: A summary nobody asked for about jewellery care.",
]


def _episode(memory, body: str) -> str:
    markdown_parser.write(memory / "episodes" / f"{EPISODE}.md",
                          {"id": EPISODE, "timestamp": "2023-06-27T10:00:00+00:00", "processed": True,
                           "content_hash": evidence.body_hash(body),
                           "correspondent": {"name": "Bob Example", "kind": "person", "decided_by": "person"}},
                          body)
    return body


@pytest.fixture
def bank(tmp_path):
    memory = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (memory / sub).mkdir(parents=True)
    _episode(memory, "\n".join(TURNS) + "\n")
    body = evidence.source_text(memory, EPISODE)     # offsets and hash are taken on the text as stored
    # The claim's quote is the sentence that says what the necklace is — it does not repeat the word "necklace".
    quote = "It was a gift from my grandma, and it stands for love, faith and strength."
    span_at = body.index(quote)
    span = Evidence(episode=EPISODE, start=span_at, end=span_at + len(quote), kind="user", hash=evidence.body_hash(body))
    filler = [f"Alice Example noted ordinary fact number {i} about the weekly schedule and errands." for i in range(14)]
    facts = filler + ["Alice Example moved from her home country four years ago."]
    page_body = ("## Summary\nAlice Example is the person this memory belongs to.\n\n## Key Facts\n"
                 + "".join(f"- {f}\n" for f in facts)
                 + "\n## Open Questions\n- Which home country she moved from is not stated\n")
    page_body = write_claims(page_body, [Claim(
        id="clm_2023-06-27_neck", text="Alice Example treasures her necklace", subject="alice-example",
        predicate="treasures", object="alices-necklace", valid_from="2023-06-27", recorded_at="2023-06-27",
        source_episodes=[EPISODE], evidence=[span])])
    fm = {"name": "Alice Example", "type": "person", "status": "active", "owner": True,
          "source_episodes": [EPISODE]}
    # The page's lines point at the conversation they came from, as Stage 1 records them.
    records = {"key_facts": {}}
    for item in section_provenance.scan(page_body)["key_facts"]:
        records["key_facts"][item.key] = (item.text_hash, [evidence.reasoning(EPISODE, hash=span.hash)])
    fm[section_provenance.FIELD] = section_provenance.encode(records)
    markdown_parser.write(memory / "entities" / "alice-example.md", fm, page_body)
    bank_index.invalidate()
    yield memory
    bank_index.invalidate()


def _hit(entity_id: str) -> dict:
    return {"score": 0.9, "text": "", "metadata": {"entity_id": entity_id, "entity_name": entity_id, "type": "person",
                                                    "status": "active", "file_path": ""}}


class _Model:
    def __init__(self):
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return json.dumps({"answer": "stub", "confidence": 0.8, "used_entities": ["alice-example"], "gaps": []})


def _ask(bank, question: str, **kw) -> str:
    model = _Model()
    ask_service.answer_query(bank, question, retrieve_fn=lambda q, k: [_hit("alice-example")], llm_fn=model, **kw)
    [prompt] = model.prompts
    return prompt


def _tree(memory) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in memory.rglob("*") if p.is_file()):
        digest.update(path.relative_to(memory).as_posix().encode() + path.read_bytes())
    return digest.hexdigest()


def test_the_cited_conversation_words_reach_the_model_with_who_said_them(bank):
    before = _tree(bank)
    prompt = _ask(bank, "What does Alice's necklace symbolize?")
    said = prompt.split("WHAT WAS SAID", 1)[1]
    assert "it stands for love, faith and strength" in said
    assert "2023-06-27, Alice Example (the person this memory belongs to)" in said
    assert "Bob Example (another person" in said, "the other side's words are labelled as theirs"
    assert _tree(bank) == before, "the words are read at answer time, never written anywhere"


def test_without_the_sources_scope_no_conversation_words_are_shown(bank):
    prompt = _ask(bank, "What does Alice's necklace symbolize?", source_words=False)
    assert "WHAT WAS SAID" not in prompt and "love, faith and strength" not in prompt


def test_a_fact_deep_in_key_facts_is_chosen_by_the_question_and_dated(bank):
    prompt = _ask(bank, "Where did Alice move from four years ago?")
    assert "- [said 2023-06-27] Alice Example moved from her home country four years ago." in prompt


def test_open_questions_are_not_read_as_memory(bank):
    prompt = _ask(bank, "Which home country did Alice move from?")
    assert "is not stated" not in prompt


def test_a_stale_span_never_highlights_other_words(bank):
    # The conversation was rewritten after Sleep: the claim's offsets now land on other words. A stale span points
    # at nothing (never fuzzy, G118 R5); the episode is still read by the question's own words.
    _episode(bank, "user: Completely different opening words here, about the weather and nothing else.\n"
             + "\n".join(TURNS) + "\n")
    prompt = _ask(bank, "What does Alice's necklace symbolize?")
    # The old offsets now fall in Bob's question; a stale span selects nothing, so neither his turn nor the
    # detail (which shares no word with the question) is shown.
    assert "any special meaning" not in prompt and "love, faith and strength" not in prompt
    assert "Look at this necklace" in prompt


def test_the_remote_door_without_sources_asks_without_conversation_words(bank, monkeypatch):
    seen: dict = {}

    def fake_answer(memory_path, query, top_k=6, **kw):
        seen.update(kw)
        return {"answer": "a", "confidence": 0.5, "citations": [], "gaps": [], "used_entities": []}

    monkeypatch.setattr(ask_service, "answer_query", fake_answer)
    ctx = mcp_tools.ToolContext(memory_path=lambda: bank, session_id="s", harness="claude-code",
                                backend_url="http://127.0.0.1:9", connector_id="rc_x", raw_excerpts=False)
    mcp_tools.ask(ctx, "What does Alice's necklace symbolize?")
    assert seen.get("source_words") is False


def test_an_agents_saved_note_is_never_shown_as_the_person_speaking(bank):
    """An episode an agent saved through a tool door has no turn markers; its words are the agent's note."""
    body = "Alice Example's necklace stands for love, faith and strength, the agent noted."
    markdown_parser.write(bank / "episodes" / f"{EPISODE}.md",
                          {"id": EPISODE, "timestamp": "2023-06-27T10:00:00+00:00", "source": "mcp", "origin": "mcp",
                           "processed": True, "content_hash": evidence.body_hash(body)}, body)
    prompt = _ask(bank, "What does Alice's necklace symbolize?")
    said = prompt.split("WHAT WAS SAID", 1)[1]
    assert "an agent's saved note (not the person's own words)" in said
    assert "the person this memory belongs to" not in said
