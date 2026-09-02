"""CQA-H3: skill_extractor and conflict_resolver used to call
``litellm.acompletion`` directly, bypassing ``api.services.providers.
resolve_llm_fn`` — the one seam model/provider overrides (llm_mode="local"
-> ollama, consolidation_model) are supposed to apply through. These tests
pin that both modules now route through the factory, that the async call
shape is preserved (``completion=litellm.acompletion`` bound in, still
awaited), and that a ``consolidation_model`` / ``llm_mode="local"`` override
actually reaches the bound ``model=``/``api_base=`` kwargs.

Hermetic: ``litellm.acompletion`` is monkeypatched on each module's own
``litellm`` import (mirrors the existing ``entity_extractor`` pattern in
``test_extractor_robustness.py``) — no network. Uses ``asyncio.run(...)``
rather than ``pytest.mark.asyncio`` — pytest-asyncio isn't a project
dependency (see ``test_sleep_resumable.py`` for the same convention).
"""
from __future__ import annotations

import asyncio
import json

from api.config import Settings
from api.services import conflict_resolver, skill_extractor


class _FakeResp:
    def __init__(self, content: str):
        class _Msg:
            pass

        class _Choice:
            pass

        msg = _Msg()
        msg.content = content
        choice = _Choice()
        choice.message = msg
        self.choices = [choice]


def _fake_acompletion(captured):
    async def _fn(**kw):
        captured.update(kw)
        return _FakeResp(json.dumps({"skills": []}))

    return _fn


# --------------------------------------------------------------------------- #
# skill_extractor.detect_patterns
# --------------------------------------------------------------------------- #


def test_skill_extractor_routes_through_factory_default(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(skill_extractor.litellm, "acompletion", _fake_acompletion(captured))
    settings = Settings(litellm_model="gpt-5.4-mini")

    result = asyncio.run(skill_extractor.detect_patterns([{"id": "e1"}], [], settings))

    assert result == []
    # Byte-identical default: same model as before the factory adoption.
    assert captured["model"] == "gpt-5.4-mini"
    assert captured["response_format"] == {"type": "json_object"}


def test_skill_extractor_respects_consolidation_model_override(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(skill_extractor.litellm, "acompletion", _fake_acompletion(captured))
    settings = Settings(
        litellm_model="gpt-5.4-mini", consolidation_model="openrouter/z-ai/glm-5.2"
    )

    asyncio.run(skill_extractor.detect_patterns([{"id": "e1"}], [], settings))

    assert captured["model"] == "openrouter/z-ai/glm-5.2"


def test_skill_extractor_respects_local_llm_mode(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(skill_extractor.litellm, "acompletion", _fake_acompletion(captured))
    settings = Settings(litellm_model="gpt-5.4-mini", llm_mode="local", ollama_model="llama3.1")

    asyncio.run(skill_extractor.detect_patterns([{"id": "e1"}], [], settings))

    assert captured["model"] == "ollama/llama3.1"
    assert captured["api_base"] == settings.ollama_base_url


# --------------------------------------------------------------------------- #
# conflict_resolver._synthesize_entity_update / _detect_contradiction
# --------------------------------------------------------------------------- #


def test_synthesize_entity_update_routes_through_factory_default(monkeypatch):
    captured: dict = {}

    async def fake_acompletion(**kw):
        captured.update(kw)
        return _FakeResp("Synthesized body.")

    monkeypatch.setattr(conflict_resolver.litellm, "acompletion", fake_acompletion)
    settings = Settings(litellm_model="gpt-5.4-mini")

    body = asyncio.run(conflict_resolver._synthesize_entity_update(
        entity_name="Cicada",
        entity_type="project",
        existing_body="Old body.",
        new_description="New info.",
        new_history_entries=[],
        source_reference_date=None,
        settings=settings,
    ))

    assert body == "Synthesized body."
    assert captured["model"] == "gpt-5.4-mini"


def test_synthesize_entity_update_respects_consolidation_model_override(monkeypatch):
    captured: dict = {}

    async def fake_acompletion(**kw):
        captured.update(kw)
        return _FakeResp("Synthesized body.")

    monkeypatch.setattr(conflict_resolver.litellm, "acompletion", fake_acompletion)
    settings = Settings(
        litellm_model="gpt-5.4-mini", consolidation_model="openrouter/z-ai/glm-5.2"
    )

    asyncio.run(conflict_resolver._synthesize_entity_update(
        entity_name="Cicada",
        entity_type="project",
        existing_body="Old body.",
        new_description="New info.",
        new_history_entries=[],
        source_reference_date=None,
        settings=settings,
    ))

    assert captured["model"] == "openrouter/z-ai/glm-5.2"


def test_detect_contradiction_respects_local_llm_mode(monkeypatch):
    captured: dict = {}

    async def fake_acompletion(**kw):
        captured.update(kw)
        return _FakeResp(json.dumps({"has_unresolvable_contradiction": False, "options": []}))

    monkeypatch.setattr(conflict_resolver.litellm, "acompletion", fake_acompletion)
    settings = Settings(litellm_model="gpt-5.4-mini", llm_mode="local", ollama_model="llama3.1")

    result = asyncio.run(conflict_resolver._detect_contradiction(
        entity_name="Cicada",
        existing_body="Old body.",
        new_description="New info.",
        settings=settings,
    ))

    assert result == {"has_unresolvable_contradiction": False, "options": []}
    assert captured["model"] == "ollama/llama3.1"
    assert captured["api_base"] == settings.ollama_base_url


# --------------------------------------------------------------------------- #
# G51: the four remaining direct callsites now route through the factory.
# --------------------------------------------------------------------------- #

import litellm as _litellm

from api.services import ask_service, entity_extractor, entity_resolver, link_enrichment


def test_entity_extractor_respects_local_llm_mode(monkeypatch):
    captured: dict = {}

    async def fake(**kw):
        captured.update(kw)
        return _FakeResp(json.dumps({"entities": [], "relationships": []}))

    monkeypatch.setattr(entity_extractor.litellm, "acompletion", fake)
    settings = Settings(llm_mode="local", ollama_model="qwen3:8b", ollama_base_url="http://127.0.0.1:11434")
    asyncio.run(entity_extractor._extract_chunk("ep1", "hello", 0, 1, settings))
    assert captured["model"] == "ollama/qwen3:8b" and captured["api_base"] == "http://127.0.0.1:11434"
    assert captured["response_format"] == {"type": "json_object"}


def test_entity_resolver_judge_respects_local_llm_mode(monkeypatch):
    captured: dict = {}

    async def fake(**kw):
        captured.update(kw)
        return _FakeResp(json.dumps({"decision": "same"}))

    monkeypatch.setattr(entity_resolver.litellm, "acompletion", fake)
    settings = Settings(llm_mode="local", ollama_model="qwen3:8b", litellm_disambiguation_model="gpt-5.4-nano")
    out = asyncio.run(entity_resolver._llm_judge_same_entity("A", "person", "d", "A.", "person", "b", settings))
    assert out == "same" and captured["model"] == "ollama/qwen3:8b"


def test_link_enrichment_summarizer_routes_through_factory(monkeypatch):
    captured: dict = {}

    async def fake(**kw):
        captured.update(kw)
        return _FakeResp("A page about knots.")

    monkeypatch.setattr(_litellm, "acompletion", fake)
    settings = Settings(litellm_model="gpt-5.4-mini")
    out = asyncio.run(link_enrichment._summarize_excerpt("Knots", "Long excerpt " * 20, "https://x", settings))
    assert out == "A page about knots." and captured["model"] == "gpt-5.4-mini" and captured["max_tokens"] == 100


def test_ask_default_llm_fn_routes_through_factory(monkeypatch):
    captured: dict = {}

    def fake(**kw):
        captured.update(kw)
        return _FakeResp(json.dumps({"answer": "x"}))

    monkeypatch.setattr(_litellm, "completion", fake)
    monkeypatch.setenv("CICADA_LLM_MODE", "local")
    monkeypatch.setenv("CICADA_OLLAMA_MODEL", "qwen3:8b")
    from api import config
    config.get_settings.cache_clear()
    try:
        fn = ask_service._default_llm_fn()
        assert fn("prompt") == json.dumps({"answer": "x"})
        assert captured["model"] == "ollama/qwen3:8b"
    finally:
        config.get_settings.cache_clear()
