"""Ask: a request for advice is tailored to what the person's own words show, never declined for want of a stated taste
(2026-11-06, G148). LongMemEval_S preference, nothing slept, haiku: 12.5 → 75.0 of 8 questions. Synthetic bank (alice-
example; the word index alone, no network; the model is a stub that records its prompt)."""
from __future__ import annotations

import json

import pytest

from api.services import ask_service, ask_sources, bank_index, evidence, markdown_parser, search_index


@pytest.mark.parametrize("question", [
    "Can you suggest a hotel for my upcoming trip to Lisbon?",
    "Can you recommend a show or movie for me to watch tonight?",
    "My kitchen's becoming a bit of a mess again. Any tips for keeping it clean?",
    "What should I cook this weekend?",
    "¿Me puedes recomendar un libro?",
    "¿Qué me sugieres para la cena?",
])
def test_a_request_for_advice_is_told_apart(question):
    assert ask_sources.asks_advice(question)


@pytest.mark.parametrize("question", [
    "How many hotels did I stay at in Lisbon?",
    "What did you recommend last time?",
    "Which database was chosen for alpha-project?",
    "When did I last watch a movie?",
    "¿Cuántos libros leí este año?",
])
def test_a_question_of_fact_is_not_advice(question):
    assert not ask_sources.asks_advice(question)


@pytest.fixture
def bank(tmp_path):
    memory = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (memory / sub).mkdir(parents=True)
    said = {"ep_2024-02-03_001": "user: I edit all my videos in alpha-editor these days, tutorials included.\n"
                                 "assistant: Good choice.\n"}
    said |= {f"ep_2023-{i:02d}-01_001": f"user: Can you help me plan the weekly errands list number {i}?\n"
                                        f"assistant: Sure, errands list {i}: groceries, laundry, bank.\n"
             for i in range(1, 13)}
    for ep, body in said.items():
        markdown_parser.write(memory / "episodes" / f"{ep}.md",
                              {"id": ep, "timestamp": f"{ep[3:13]}T10:00:00+00:00", "processed": False,
                               "source": "import", "content_hash": evidence.body_hash(body)}, body)
    assert search_index.ensure_fresh(memory, wait=True, max_age_s=0) == "ready"
    bank_index.invalidate()
    yield memory
    bank_index.invalidate()


def _prompt(bank, question: str) -> str:
    seen: list[str] = []

    def model(prompt: str) -> str:
        seen.append(prompt)
        return json.dumps({"answer": "stub", "confidence": 0.5, "used_entities": [], "gaps": []})

    ask_service.answer_query(bank, question, retrieve_fn=lambda q, k: [], llm_fn=model, no_engine=False)
    return seen[0] if seen else ""


def test_advice_gets_its_note_and_the_persons_words(bank):
    prompt = _prompt(bank, "Can you recommend some videos tutorials about editing?")
    assert "ASKS FOR A RECOMMENDATION OR ADVICE" in prompt
    assert "alpha-editor" in prompt


def test_a_question_of_fact_gets_no_such_note(bank):
    prompt = _prompt(bank, "Which editor do I use for my videos?")
    assert "ASKS FOR A RECOMMENDATION OR ADVICE" not in prompt
