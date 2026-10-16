"""R-AG11 — the key providers, their defaults and the key cards. Offline: the
installed LiteLLM's own bundled catalog is the source of truth for a model id
(``api.pin_litellm`` keeps litellm from fetching a newer one at import)."""
from __future__ import annotations

import os

import litellm
import pytest
from litellm.litellm_core_utils.get_model_cost_map import get_model_cost_map_source_info

from api.config import Settings
from api.services import cycle_usage, pricing, providers, telemetry
from api.services.connections import base, byok


def _known(model: str) -> dict | None:
    return litellm.model_cost.get(model) or litellm.model_cost.get(model.split("/", 1)[-1])


def test_the_price_table_is_the_one_litellm_ships_never_a_fetched_one():
    """The import-time fetch made this file pass or fail on what upstream merged that day (an OpenRouter
    alias vanished from the remote table, then every `openrouter/` row did) and was an ungated request."""
    assert os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] == "True"
    info = get_model_cost_map_source_info()
    assert (info["source"], info["is_env_forced"], info["url"]) == ("local", True, None)


def test_no_settings_file_or_inherited_value_turns_the_fetch_back_on():
    from api import cli, settings_file

    environ = {"LITELLM_LOCAL_MODEL_COST_MAP": "False"}
    cli._force_production(environ)
    assert environ["LITELLM_LOCAL_MODEL_COST_MAP"] == "True"
    assert "LITELLM_LOCAL_MODEL_COST_MAP" in cli.CONTROL_KEYS
    assert "LITELLM_LOCAL_MODEL_COST_MAP" in settings_file.CONTROL_KEYS


def test_every_default_is_a_model_litellm_knows_with_structured_output():
    for p in byok.PROVIDERS:
        info = _known(p.default_model)
        assert info is not None, p.default_model
        assert info.get("mode") == "chat" and info.get("supports_response_schema"), p.default_model
        # Priced, so the engine card's list price and a cycle's cost line have a figure to show.
        assert info.get("input_cost_per_token") and info.get("output_cost_per_token"), p.default_model


def test_a_model_the_table_does_not_list_costs_unknown_end_to_end():
    """Ruling 12: a price shows only with its basis, so an unpriced model never reads as $0. Offline: litellm's
    own `mock_response` runs its real cost path with no request."""
    model = "openrouter/example-lab/not-a-listed-model"
    assert _known(model) is None
    events: list[telemetry.UsageEvent] = []
    fn = providers.resolve_llm_fn(Settings(litellm_model=model), completion=litellm.completion,
                                  stage="extraction", sink=events.append, bank="lab")
    fn(messages=[{"role": "user", "content": "hi"}], mock_response="{}", api_key="sk-example")
    (ev,) = events
    assert ev.connection == "byok-openrouter" and ev.ok and ev.input_tokens > 0
    assert ev.cost_usd is None and ev.equiv_cost_usd is None
    assert pricing.estimate_cost(model, 1000, 100) is None
    cycle_usage._PRICE_CACHE.pop(model, None)
    assert cycle_usage.list_price_per_million(model) == (None, None)
    ev.refs = {"cycle_id": "c"}
    run = telemetry.UsageEvent(kind="sleep_run", engine="litellm", connection="byok-openrouter",
                               refs={"cycle_id": "c", "commit": "abc1234", cycle_usage.TAGGED_REF: True})
    usage = cycle_usage.usage_for(cycle_usage.Ledger.build([run, ev]), "abc1234")
    assert usage.total_cost_usd is None and usage.total_equiv_usd is None
    summary = cycle_usage.summarize(usage)
    assert summary.cost_usd is None and summary.equiv_cost_usd is None


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
    ("xai/grok-4-1-fast-reasoning-latest", "byok-xai"), ("groq/openai/gpt-oss-120b", "byok-groq"),
    ("mistral/mistral-small-latest", "byok-mistral"), ("openrouter/anthropic/claude-x", "byok-openrouter"),
])
def test_a_model_bills_the_key_card_of_its_provider(model, card):
    assert telemetry.connection_for_model(model) == (card, "usage")
    assert telemetry.connection_for_model("ollama/llama3.1") == ("ollama-local", "free")
