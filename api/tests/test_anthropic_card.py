"""G237: the engine's card on a Claude key, resolving one, and what a commit says served it. Hermetic: no key reaches
anything but `anthropic_stub`, no list is read unless a test asks."""
from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("anthropic")

from api.config import Settings
from api.services import anthropic_engine, anthropic_models, direct_engines, engine_select, git_service
from api.tests.anthropic_stub import StubAnthropic
from api.tests.test_sleep_engine_prefs import client  # noqa: F401 — the module's fixture

CLAUDE = "anthropic/claude-sonnet-5-5"


@pytest.fixture
def key(client, monkeypatch):  # noqa: F811
    stub = StubAnthropic()
    stub.install(monkeypatch)
    yield stub
    anthropic_engine.reset_clients()


def _choose(client, model):  # noqa: F811
    return client.put("/sleep/engine", json={"mode": "byok", "model": model})


def test_a_claude_key_lists_its_tiers_with_the_saved_model_first_and_no_read_on_a_get(client, key):  # noqa: F811
    assert _choose(client, CLAUDE).status_code == 200
    body = client.get("/sleep/engine").json()
    card = next(c for c in body["candidates"] if c["id"] == "byok")
    assert card["models"][0] == CLAUDE, "a tap writes the first, and keeps the choice"
    assert {"anthropic/claude-haiku-5-5", "anthropic/claude-opus-5-5"} <= set(card["models"])
    assert card["catalogue"]["source"] == "documented", "before the key's list is read, the floor says so"
    assert not key.headers_seen, "a page view never reads the list"


def test_refresh_reads_the_keys_list_on_the_persons_click_and_prices_carry_their_basis(client, key):  # noqa: F811
    _choose(client, CLAUDE)
    resp = client.post("/sleep/engine/models/refresh", json={"id": "byok"})
    assert resp.status_code == 200, resp.text
    assert len(key.headers_seen) == 1, "one list read"
    card = next(c for c in resp.json()["candidates"] if c["id"] == "byok")
    assert card["catalogue"]["source"] == "your key"
    price = card["modelPrices"][CLAUDE]
    assert price["inputPerMillionUsd"] == 2 and price["outputPerMillionUsd"] == 10
    assert "pricing" in price["basis"] and "2026" in price["basis"]
    assert not key.requests, "nothing here spends"


def test_with_no_key_the_refresh_answers_as_it_did(client, monkeypatch):  # noqa: F811
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert client.post("/sleep/engine/models/refresh", json={"id": "byok"}).status_code == 422


def test_a_retired_saved_model_is_said_on_the_card(client, key):  # noqa: F811
    client.post("/sleep/engine/models/refresh", json={"id": "byok"})
    _choose(client, "anthropic/claude-opus-4-1-20250805")
    card = next(c for c in client.get("/sleep/engine").json()["candidates"] if c["id"] == "byok")
    assert "no longer offered" in card["modelNote"]
    assert card["models"][0] == "anthropic/claude-opus-4-1-20250805", "never dropped from the list"


def test_choosing_claude_pins_the_small_tier_as_judge_as_on_the_plan(client, key):  # noqa: F811
    _choose(client, CLAUDE)
    assert client.get("/sleep/engine").json()["disambiguationModel"] == "anthropic/claude-haiku-5-5"
    _choose(client, "gpt-5.4-mini")
    assert client.get("/sleep/engine").json()["disambiguationModel"] == "gpt-5.4-mini", "any other key: as before"


def test_a_key_reads_every_stage_on_its_own_provider(monkeypatch, tmp_path):
    class Registry:
        def __init__(self, entry):
            self.entry = entry

        def prefs(self):
            return {engine_select.SLEEP_ENGINE_PREF_KEY: self.entry}

    monkeypatch.setenv("CICADA_HOME", str(tmp_path))
    settings = Settings(_env_file=None, llm_mode="auto", consolidation_model="openrouter/z-ai/glm-5.2")
    settings.model_fields_set.discard("llm_mode")
    resolved, _why = asyncio.run(engine_select.resolve_settings(
        settings, Registry({"mode": "byok", "model": CLAUDE})))
    assert resolved.litellm_model == CLAUDE
    assert resolved.effective_consolidation_model == CLAUDE, "a dotfile's other provider never gets the merges"
    assert resolved.litellm_disambiguation_model == "anthropic/claude-haiku-5-5", "the shipped judge is another key's"
    same, _why = asyncio.run(engine_select.resolve_settings(
        Settings(_env_file=None, llm_mode="byok", consolidation_model="anthropic/claude-opus-5-5"),
        Registry({"mode": "byok", "model": CLAUDE})))
    assert same.effective_consolidation_model == "anthropic/claude-opus-5-5", "the same provider's pin stands"


def test_auto_never_reaches_a_claude_key(monkeypatch, tmp_path):
    """Ruling 31: a key in the environment changes nothing until it is chosen."""

    class Registry:
        def prefs(self):
            return {}

        def cached_statuses(self):
            return []

        async def status(self, _id):
            raise RuntimeError("no plan here")

    monkeypatch.setenv("ANTHROPIC_API_KEY", "stub-key-not-real")
    monkeypatch.setenv("CICADA_HOME", str(tmp_path))
    monkeypatch.setattr("api.services.agent_engine.probe", lambda **kw: (False, "signed out"))
    monkeypatch.setattr("api.services.codex_engine.probe", lambda **kw: (False, "signed out"))
    monkeypatch.setattr(engine_select, "_cli_rungs", _no_rungs)
    settings = Settings(_env_file=None, llm_mode="auto", litellm_model=CLAUDE)
    settings.model_fields_set.discard("llm_mode")
    resolved, _why = asyncio.run(engine_select.resolve_settings(settings, Registry()))
    assert engine_select.engine_label(resolved) == engine_select.NO_ENGINE_LABEL
    from api.services import providers

    with pytest.raises(Exception, match="engine"):
        providers.resolve_llm_fn(resolved, stage="extraction", sink=lambda e: None)(messages=[])


async def _no_rungs(*_a, **_kw):
    return None, []


def test_the_trailer_says_what_served_the_commit():
    build = git_service.build_commit_message
    assert "Cicada-Engine: anthropic-api" in build("s", [], authors=["claude-haiku-5-5"], engine="litellm")
    assert "Cicada-Engine: litellm" in build("s", [], authors=["openrouter/anthropic/claude-haiku-4-5"], engine="litellm")
    assert "Cicada-Engine: litellm" in build("s", [], authors=["claude-haiku-5-5", "gpt-5.4-mini"], engine="litellm")
    assert "Cicada-Engine: claude-cli" in build("s", [], authors=["claude-haiku-5-5"], engine="claude-cli")
    assert direct_engines.trailer_engine("litellm", []) == "litellm"


def test_a_default_is_the_lists_small_tier_once_read(client, key):  # noqa: F811
    assert anthropic_models.default_model() == "anthropic/claude-haiku-5-5"
    key.models = [*key.models, {"id": "claude-haiku-6", "line": "haiku", "lifecycle": "active",
                                "created_at": "2026-12-01T00:00:00Z", "display_name": "Claude Haiku 6"}]
    client.post("/sleep/engine/models/refresh", json={"id": "byok"})
    body = client.get("/sleep/engine").json()
    assert next(p for p in body["providers"] if p["id"] == "anthropic")["defaultModel"] == "anthropic/claude-haiku-6"


def test_another_keys_stage_pin_stands_when_the_key_is_not_claude(monkeypatch, tmp_path):
    """Review of #614: the rule is a Claude key's. A person with two keys who pinned merges elsewhere keeps that."""
    from api.services import engine_select

    settings = Settings(_env_file=None, llm_mode="byok", consolidation_model="anthropic/claude-opus-5-5")
    assert engine_select._one_provider_key(settings, {"litellm_model": "openrouter/z-ai/glm-5.2"}) == {}
    assert engine_select._one_provider_key(
        Settings(_env_file=None, llm_mode="byok", consolidation_model="openrouter/z-ai/glm-5.2"),
        {"litellm_model": CLAUDE})["consolidation_model"] == ""
