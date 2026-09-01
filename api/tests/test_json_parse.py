"""G74(a) Task 2 — one lenient JSON parser, used by every LLM JSON call site.

Three sites called bare ``json.loads`` (skill_extractor:89,
conflict_resolver:729, entity_resolver:706) and three carved a substring by
hand (dedup_sweep, source_rewrite, ask_service). A single preambled answer
therefore made Stage 4 return [], Stage 3 skip, and Stage 2 answer "unsure" —
which *creates a clarification and splits the entity page*.
"""
from __future__ import annotations

import json

import pytest

from api.services import json_parse


PREAMBLED = 'Let me think about this.\n```json\n{"decision": "same"}\n```\nHope that helps!'


def test_parses_plain_json():
    assert json_parse.parse_json_object('{"a": 1}') == {"a": 1}


def test_parses_fenced_json():
    assert json_parse.parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}


def test_parses_reasoning_preamble_and_trailing_prose():
    assert json_parse.parse_json_object(PREAMBLED) == {"decision": "same"}


def test_parses_a_nested_object_without_stopping_at_the_first_brace():
    raw = 'thinking...\n{"outer": {"inner": {"deep": true}}, "n": 2}\ndone'
    assert json_parse.parse_json_object(raw)["outer"]["inner"]["deep"] is True


def test_braces_inside_strings_do_not_confuse_the_scanner():
    raw = 'x {"body": "a } brace \\" and more {", "ok": true} y'
    assert json_parse.parse_json_object(raw)["ok"] is True


@pytest.mark.parametrize("bad", ["", "   ", None])
def test_empty_raises_value_error(bad):
    with pytest.raises(ValueError):
        json_parse.parse_json_object(bad)


def test_garbage_raises_value_error():
    with pytest.raises(ValueError):
        json_parse.parse_json_object("there is no json object in this text at all")


def test_or_variant_returns_the_default_instead_of_raising():
    assert json_parse.parse_json_object_or("nope", {"verdict": "unsure"}) == {"verdict": "unsure"}


def test_extractor_alias_still_exists_for_the_existing_suite():
    from api.services import entity_extractor

    assert entity_extractor._parse_json_lenient('{"entities": []}') == {"entities": []}


# --------------------------------------------------------------------------- #
# The six re-routed call sites now survive a preambled answer.
# --------------------------------------------------------------------------- #


def _resp(text):
    """A response object satisfying BOTH access styles the call sites use."""
    from api.services.agent_engine import _wrap

    return _wrap({"choices": [{"message": {"content": text}}]})


def test_entity_resolver_judge_survives_a_preambled_answer(monkeypatch):
    import asyncio

    from api.config import Settings
    from api.services import entity_resolver

    async def fake(**kw):
        return _resp(PREAMBLED)

    monkeypatch.setattr(entity_resolver.litellm, "acompletion", fake)
    out = asyncio.run(entity_resolver._llm_judge_same_entity(
        "A", "person", "d", "A.", "person", "b", Settings()))
    assert out == "same"


def test_skill_extractor_survives_a_preambled_answer(monkeypatch):
    import asyncio

    from api.config import Settings
    from api.services import skill_extractor

    async def fake(**kw):
        return _resp('Sure!\n{"skills": [{"name": "Prefers terse summaries"}]}')

    monkeypatch.setattr(skill_extractor.litellm, "acompletion", fake)
    skills = asyncio.run(skill_extractor.detect_patterns(
        [{"id": "x", "action": "create", "name": "X"}], [], Settings()))
    assert skills == [{"name": "Prefers terse summaries"}]


def test_dedup_judge_survives_a_preambled_answer(monkeypatch):
    from api.config import Settings
    from api.services import dedup_sweep, providers

    monkeypatch.setattr(
        providers, "resolve_llm_fn",
        lambda *a, **kw: (lambda **kwargs: _resp('ok:\n{"verdict":"same","confidence":0.9,"winner":"a"}')),
    )
    judge = dedup_sweep._default_judge_fn(Settings())
    assert judge("A body", "B body", "a", "b")["verdict"] == "same"


def test_ask_synthesis_survives_a_preambled_answer():
    from api.services import ask_service

    assert json_parse.parse_json_object(
        '```json\n{"answer": "yes", "confidence": 0.8}\n```'
    )["answer"] == "yes"
    assert ask_service.json_parse is json_parse  # the module is wired in, not re-implemented


# --------------------------------------------------------------------------- #
# Ruling 1 pin: the brace-carving scan is a FALLBACK, tried only after the
# whole-text ``json.loads`` fails. Nothing above isolates the ordering — a
# refactor could route well-formed input through the lenient scanner first
# and silently change results for edge-case-but-valid JSON. These three tests
# prove it directly.
# --------------------------------------------------------------------------- #


def test_strict_json_loads_runs_first_and_wins_for_well_formed_input(monkeypatch):
    """Spy on ``json.loads`` to prove the fast whole-text path is attempted,
    and that for well-formed input it succeeds in exactly one call — the
    carve-and-retry branch (which would issue a SECOND ``json.loads`` on a
    hand-extracted substring) is never reached."""
    calls: list[str] = []
    real_loads = json.loads

    def spy(*a, **kw):
        calls.append(a[0])
        return real_loads(*a, **kw)

    monkeypatch.setattr(json_parse.json, "loads", spy)
    raw = '{"a": 1, "b": {"c": 2}}'

    result = json_parse.parse_json_object(raw)

    assert result == {"a": 1, "b": {"c": 2}}
    assert calls == [raw]  # exactly one call, on the whole text — never carved


def test_lenient_carving_only_engages_after_the_strict_call_fails(monkeypatch):
    """Companion to the above: a preambled answer DOES need the fallback, and
    it costs a second ``json.loads`` call — the first, on the whole noisy
    text, raises (caught internally) and is what triggers the carve; the
    second, on the carved substring, succeeds."""
    calls: list[str] = []
    real_loads = json.loads

    def spy(*a, **kw):
        calls.append(a[0])
        return real_loads(*a, **kw)

    monkeypatch.setattr(json_parse.json, "loads", spy)

    result = json_parse.parse_json_object(PREAMBLED)

    assert result == {"decision": "same"}
    assert len(calls) == 2
    assert calls[0] == PREAMBLED  # first call: the whole noisy text, and it fails
    assert calls[1] == '{"decision": "same"}'  # second call: the carved substring


def test_strict_parse_wins_on_a_top_level_scalar_carving_cannot_handle():
    """A bare JSON string or number has no top-level ``{`` at all — only the
    strict fast-path ``json.loads`` can parse it. Brace-carving alone
    (``text.find("{")`` -> -1) would raise on both, so a correct result here
    is only possible because the strict call runs first and its success is
    respected outright, never overridden by a later carve attempt."""
    assert json_parse.parse_json_object('"hello world"') == "hello world"
    assert json_parse.parse_json_object("42") == 42
