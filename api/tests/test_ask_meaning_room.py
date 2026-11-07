"""G148: Ask's meaning leg in every language, filling only the room the prompt has. Unslept LoCoMo 123 → 138 of 200,
slept 159 → 159, the wrong person's memory 15 → 15. Recall stays on the words: these lines cost it 128 → 114."""
from __future__ import annotations

from api.services import ask_service, ask_sources
from test_ask_infer_es import _Indexer, _prompt, bank  # noqa: F401 — the fixture

ENGLISH = "When did Alice go to the support group?"


def _found(**kw):
    return ask_sources.Searched(episodes=[], weights={}, **kw)


def test_the_budget_is_what_the_prompt_has_left():
    budget = ask_sources._meaning_budget
    assert budget(ENGLISH, _found(), 6000, 0) == (6, ask_sources.MEANING_FILL_CHARS)
    assert budget(ENGLISH, _found(), 6000, 4500) == (3, 1500)


def test_a_full_prompt_adds_nothing_to_an_english_question():
    assert ask_sources._meaning_budget(ENGLISH, _found(), 6000, 6000) == (0, 0)
    assert ask_sources._meaning_budget(ENGLISH, _found(), -9000, 0) == (0, 0), "a memory Sleep has read fills it with pages"


def test_another_language_keeps_its_few_lines_when_the_prompt_is_full():
    fixed = (ask_sources.MEANING_EXTRA_EXCERPTS, ask_sources.MEANING_EXTRA_CHARS)
    assert ask_sources._meaning_budget("¿Cuándo fue Alice al grupo?", _found(), -9000, 0) == fixed


def test_a_request_for_advice_keeps_its_own_budget():
    found = _found(advice=True)
    assert ask_sources._meaning_budget(ENGLISH, found, 0, 0) == (ask_sources.ADVICE_EXTRA_EXCERPTS,
                                                                 ask_sources.ADVICE_EXTRA_CHARS)


def test_a_caller_with_no_room_stays_on_the_fixed_lines():
    fixed = (ask_sources.MEANING_EXTRA_EXCERPTS, ask_sources.MEANING_EXTRA_CHARS)
    assert ask_sources._meaning_budget(ENGLISH, _found(), None, 0) == fixed


def test_only_ask_asks_for_an_english_question_by_meaning(bank):
    assert not ask_sources.search(bank, ENGLISH, indexer=_Indexer(bank)).adds, "recall's call, the default, is unchanged"
    found = ask_sources.search(bank, ENGLISH, indexer=_Indexer(bank), any_language=True)
    assert found.adds and not found.meaning, "the words lead, meaning adds"


def test_ask_calls_the_search_with_any_language(bank, monkeypatch):
    seen = {}
    real = ask_sources.search

    def spy(*a, **kw):
        seen.update(kw)
        return real(*a, **kw)

    monkeypatch.setattr(ask_sources, "search", spy)
    ask_service.answer_query(bank, ENGLISH, top_k=6, llm_fn=lambda p: '{"answer": "x", "confidence": 0.5}', no_engine=False)
    assert seen.get("any_language") is True
