"""Ask: a request for advice is tailored to what the person's own words show, in any language, with no word list (G148,
2026-11-06). Synthetic bank (alice-example; the word index alone, no network)."""
from __future__ import annotations

import numpy as np
import pytest

from api.services import (ask_service, ask_sources, bank_index, evidence, markdown_parser, question_intent,
                          search_index)


class _Index:
    """A search model of one dimension per kind: a question leans the way its marker says, in whatever words."""

    def __init__(self, lean: str | None):
        self.lean = lean

    def nearness(self, question, passages):
        if self.lean is None:
            raise RuntimeError("no model on this machine")
        return {k: np.full(len(v), 0.9 if k == self.lean else 0.5) for k, v in passages.items()}


def test_a_question_leaning_to_the_advice_examples_asks_advice():
    assert question_intent.asks_advice(_Index("advice"), "¿Me recomiendas un libro?")


def test_a_question_of_another_kind_does_not():
    assert not question_intent.asks_advice(_Index("other"), "When did I read it?")
    assert not question_intent.asks_advice(_Index("count"), "How many did I read?")


def test_with_no_model_on_this_machine_it_says_no_and_never_raises():
    assert not question_intent.asks_advice(None, "Can you recommend a book?")
    assert not question_intent.asks_advice(_Index(None), "Can you recommend a book?")


def test_help_or_record_is_the_models_call_in_every_language_never_a_note():
    """The detector found 3 of 90 PersonalizationV4 questions and the rest were declined. With "the ONLY source of truth"
    at the head of the prompt a rule further down reached 3 of 8; at the head, for the record alone, 6 of 8."""
    head = ask_service.ASK_SYSTEM_PROMPT.split("Rules:")[0]
    assert head.index("ON THE RECORD") < head.index("ONLY source of truth") < head.index("REQUEST FOR HELP")
    assert "General knowledge never supplies a fact about the person" in head
    asked = ask_service._build_prompt("what should I cook?", [], searched=ask_sources.Searched(episodes=[], weights={}, advice=True))
    plain = ask_service._build_prompt("what should I cook?", [], searched=ask_sources.Searched(episodes=[], weights={}))
    assert asked == plain, "being read as advice widens the search; it adds nothing to the prompt"


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


def test_more_lines_by_meaning_for_advice(bank, monkeypatch):
    """Asked for advice, the meaning leg may add its larger allowance; the question's own words still find the turn."""
    monkeypatch.setattr(question_intent, "asks_advice", lambda indexer, question: True)
    found = ask_sources.search(bank, "Can you recommend some videos tutorials about editing?")
    shown = ask_sources.gather_search(bank, "Can you recommend some videos tutorials about editing?", found)
    assert any("alpha-editor" in e.text for e in shown)
