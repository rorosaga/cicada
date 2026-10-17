"""A metered engine that refuses every call says why, in plain words, with the fix (2026-10-17).

The scheduled run on the owner's machine ended "every episode failed on the API engine (check the model id, and that
the key still has credit)" while the provider had said, on every call, that the key had reached its own spending
limit. The provider's words now reach the person as one of four causes; the plan switch is named as a fix only for a
scheduled run that ruling 4 kept off the plan, and never flipped.
"""
from __future__ import annotations

import asyncio

import litellm
import pytest

from drain_harness import episode_ids, install, seed_bank, settings, waiting

from api.services import engine_cause, engine_errors, engine_select, sleep_cycle, sleep_paused

KEY_LIMIT = 'OpenrouterException - {"error":{"message":"Key limit exceeded (total limit). Manage it in settings.","code":403}}'


@pytest.fixture(autouse=True)
def _idle_state():
    s = sleep_cycle.get_sleep_state()
    s.status, s.drain, s.drain_run, s.cancel_requested = "idle", None, False, False
    yield
    s.status, s.drain, s.drain_run, s.cancel_requested = "idle", None, False, False


def _api_error(msg: str, status: int = 403):
    return litellm.exceptions.APIError(status, msg, "openrouter", "some/model")


@pytest.mark.parametrize("exc,cause", [
    (_api_error(KEY_LIMIT), "spending_limit"),
    (litellm.exceptions.RateLimitError("You exceeded your current quota, please check your plan and billing details",
                                       "openai", "m"), "spending_limit"),
    (_api_error("Insufficient credits. Add more using the dashboard", 402), "spending_limit"),
    (_api_error("Your credit balance is too low to access the API", 400), "spending_limit"),
    (litellm.exceptions.AuthenticationError("Incorrect API key provided", "openai", "m"), "auth"),
    (litellm.exceptions.AuthenticationError("User not found.", "openrouter", "m"), "auth"),
    (litellm.exceptions.NotFoundError("No endpoints found for some/model.", "m", "openrouter"), "model_not_found"),
    (_api_error("The model `x` does not exist or you do not have access to it", 404), "model_not_found"),
    (litellm.exceptions.RateLimitError("Rate limit exceeded: free-models-per-min", "openrouter", "m"), "rate_limited"),
    (_api_error("Internal server error", 500), None),
    (ConnectionError("connection reset"), None),
])
def test_a_provider_refusal_is_sorted_into_its_cause(exc, cause):
    assert engine_cause.classify(exc) == cause


def test_every_cause_has_a_sentence_and_only_the_metered_ones_name_the_plan_switch():
    for cause in engine_cause.CAUSES:
        plain = engine_cause.sentence(cause)
        assert "Scheduled runs may use my plan" not in plain
        assert "OpenRouter" not in plain and "openrouter" not in plain, "provider-neutral copy"
    hinted = engine_cause.sentence("spending_limit", plan_hint=True)
    assert "spending limit" in hinted and "Raise the key's limit" in hinted
    assert "Scheduled runs may use my plan" in hinted and "Settings → Sleep" in hinted
    assert "Scheduled runs may use my plan" not in engine_cause.sentence("auth", plan_hint=True), \
        "a bad key is fixed by the key, not by a plan"


def _run(memory, *, user_triggered):
    cfg = settings(memory, sleep_max_episodes_per_cycle=3)
    asyncio.run(sleep_cycle.run(cfg, "sleep_cause", user_triggered=user_triggered, drain=True))
    return sleep_cycle.get_sleep_state()


def _every_call_refused(rig, exc):
    async def refuse(batch_no, episodes):
        for e in episodes:
            rig.fail_exc[e["id"]] = exc
    rig.on_extract = refuse


def test_a_scheduled_run_on_a_capped_key_says_the_limit_was_reached_and_names_both_fixes(tmp_path, monkeypatch):
    ids = episode_ids(6)
    memory = seed_bank(tmp_path, ids)
    rig = install(monkeypatch)

    async def degraded(settings_, registry=None, *, user_triggered=True):
        return "byok", engine_select.SCHEDULE_DEGRADED   # ruling 4 kept this scheduled run off the plan

    monkeypatch.setattr(engine_select, "resolve_llm_mode", degraded)
    _every_call_refused(rig, _api_error(KEY_LIMIT))
    state = _run(memory, user_triggered=False)

    stop = state.drain.stop
    assert stop.reason == "engine"
    assert "spending limit" in stop.sentence and "Raise the key's limit or add credit with the provider" in stop.sentence
    assert "Scheduled runs may use my plan" in stop.sentence
    assert "check the model id" not in stop.sentence, "the generic guess no longer hides the provider's own answer"
    assert "Key limit exceeded" not in stop.sentence, "the provider's raw text never reaches the wire"
    rec = sleep_paused.get_paused(memory)
    assert rec["reason"] == "engine" and rec["sentence"] == stop.sentence and rec["can_continue"] is True
    assert waiting(memory) == ids, "the queue is intact"


def test_a_run_the_person_started_names_only_the_providers_fix(tmp_path, monkeypatch):
    memory = seed_bank(tmp_path, episode_ids(3))
    rig = install(monkeypatch)
    _every_call_refused(rig, _api_error(KEY_LIMIT))
    stop = _run(memory, user_triggered=True).drain.stop
    assert "spending limit" in stop.sentence and "Scheduled runs may use my plan" not in stop.sentence


def test_a_refused_key_says_so(tmp_path, monkeypatch):
    memory = seed_bank(tmp_path, episode_ids(3))
    rig = install(monkeypatch)
    _every_call_refused(rig, litellm.exceptions.AuthenticationError("Incorrect API key provided", "openai", "m"))
    stop = _run(memory, user_triggered=True).drain.stop
    assert "refused the API key" in stop.sentence and "Settings → Plans & keys" in stop.sentence
    assert "pick another engine" in stop.sentence, "an install that never chose an engine is told that door too (G117)"


def test_a_failure_the_provider_did_not_explain_keeps_the_generic_sentence(tmp_path, monkeypatch):
    memory = seed_bank(tmp_path, episode_ids(3))
    rig = install(monkeypatch)
    _every_call_refused(rig, _api_error("Internal server error", 500))
    stop = _run(memory, user_triggered=True).drain.stop
    assert stop.reason == "engine" and "Stage 1 extracted nothing" in stop.sentence


def test_a_cli_engine_error_keeps_its_own_words(tmp_path, monkeypatch):
    """Cicada's own engine errors are already in words; the cause sentence is for a provider's refusal only."""
    ids = episode_ids(6)
    memory = seed_bank(tmp_path, ids)
    rig = install(monkeypatch)

    async def batch_two_refused(batch_no, episodes):
        if batch_no == 2:
            for e in episodes:
                rig.fail_exc[e["id"]] = engine_errors.EngineModelNotFound("model alias rejected")

    rig.on_extract = batch_two_refused
    stop = _run(memory, user_triggered=True).drain.stop
    assert stop.reason == "engine" and "Stage 1 extracted nothing" in stop.sentence
    assert "The provider" not in stop.sentence, "no provider cause is read into Cicada's own engine errors"


def test_a_cap_reached_partway_says_the_cause_after_filing_what_was_read(tmp_path, monkeypatch):
    ids = episode_ids(9)
    memory = seed_bank(tmp_path, ids)
    rig = install(monkeypatch)

    async def cap_mid_batch_two(batch_no, episodes):
        if batch_no == 2:
            rig.fail_exc[episodes[-1]["id"]] = _api_error(KEY_LIMIT)

    rig.on_extract = cap_mid_batch_two
    state = _run(memory, user_triggered=True)
    stop = state.drain.stop
    assert stop.reason == "engine" and "spending limit" in stop.sentence
    assert state.drain.filed == 5, "the batch filed what it read before the cap"
