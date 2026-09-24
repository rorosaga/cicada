"""R-AG11 — the key providers, their defaults and the key cards. Offline: the
installed LiteLLM's own catalog is the source of truth for a model id."""
from __future__ import annotations

import litellm
import pytest

from api.services import telemetry
from api.services.connections import base, byok


def _known(model: str) -> dict | None:
    return litellm.model_cost.get(model) or litellm.model_cost.get(model.split("/", 1)[-1])


def test_every_default_is_a_model_litellm_knows_with_structured_output():
    for p in byok.PROVIDERS:
        info = _known(p.default_model)
        assert info is not None, p.default_model
        assert info.get("mode") == "chat" and info.get("supports_response_schema"), p.default_model


def test_the_picker_order_and_openrouter_is_its_own_card():
    assert [p.id for p in byok.PICKER] == ["anthropic", "openai", "gemini", "xai", "groq", "mistral"]
    assert byok.provider("openrouter").connection_id == "byok-openrouter"
    assert list(byok.BYOK_PROVIDERS)[:4] == ["openai", "anthropic", "openrouter", "gemini"]   # card order kept


def test_every_provider_key_is_managed_and_scrubbed_from_plan_children():
    for p in byok.PROVIDERS:
        assert p.env in base.MANAGED_KEY_ENV and p.env in base.SCRUBBED_ENV_KEYS, p.env


@pytest.mark.parametrize("model,card", [
    ("gpt-5.4-mini", "byok-openai"), ("anthropic/claude-haiku-4-5", "byok-anthropic"),
    ("claude-sonnet-5", "byok-anthropic"), ("gemini/gemini-flash-latest", "byok-gemini"),
    ("xai/grok-4.5-latest", "byok-xai"), ("groq/openai/gpt-oss-120b", "byok-groq"),
    ("mistral/mistral-small-latest", "byok-mistral"), ("openrouter/anthropic/claude-x", "byok-openrouter"),
])
def test_a_model_bills_the_key_card_of_its_provider(model, card):
    assert telemetry.connection_for_model(model) == (card, "usage")
    assert telemetry.connection_for_model("ollama/llama3.1") == ("ollama-local", "free")
