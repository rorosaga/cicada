"""The batteries' ``--engine key|plan`` option (`benchmarks/consolidation/engines.py`, 2026-11-24): the plan reads no key,
builds the plan's settings with the same tiers, and the tally says how many replies a parser could not use. No model."""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace

import pytest

from api.services import providers
from benchmarks.consolidation import (both_named_battery, direction_battery, dropped_battery, ended_scope_battery, engines,
                                      full_name_battery, same_name_battery, same_name_stories, value_ended_battery,
                                      value_join_battery)


def _reply(text: str):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


def test_the_plan_reads_no_key_and_removes_one_from_the_environment(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-a-key")
    called = []
    engines.arm("plan", lambda: called.append("read"))
    assert called == [] and "ANTHROPIC_API_KEY" not in os.environ


def test_the_key_engine_runs_the_batterys_own_reader():
    called = []
    engines.arm("key", lambda: called.append("read"))
    assert called == ["read"]
    with pytest.raises(ValueError):
        engines.arm("cursor")


def test_settings_are_the_engines_with_the_same_tiers(tmp_path):
    plan = engines.settings("plan", tmp_path, model="sonnet", judge="haiku")
    assert plan.llm_mode == "agent" and plan.agent_model == "sonnet" and plan.agent_disambiguation_model == "haiku"
    key = engines.settings("key", tmp_path, model="sonnet", judge="haiku")
    assert key.llm_mode == "byok" and "sonnet" in key.litellm_model and "haiku" in key.litellm_disambiguation_model


def test_every_battery_takes_the_option_and_a_plan_is_never_the_default():
    for module in (both_named_battery, direction_battery, dropped_battery, same_name_battery, same_name_stories,
                   value_join_battery, ended_scope_battery, value_ended_battery):
        src = open(module.__file__, encoding="utf-8").read()
        assert "engines.add_argument" in src, module.__name__
    import argparse

    p = argparse.ArgumentParser()
    engines.add_argument(p)
    assert p.parse_args([]).engine == "key" and p.parse_args(["--engine", "plan"]).engine == "plan"
    assert full_name_battery.__doc__   # the one battery whose default was already the plan


def test_the_tally_counts_replies_that_are_not_a_json_object_and_keeps_the_keys_it_saw(monkeypatch):
    answers = iter(['{"people": []}', "I think they are the same person.", '{"decision": "same", "reason": "x"}'])

    def fake(settings, **kw):
        def call(*a, **k):
            return _reply(next(answers))
        return call

    monkeypatch.setattr(providers, "resolve_llm_fn", fake)
    with engines.tally() as counted:
        llm = providers.resolve_llm_fn(None, stage="disambiguation")
        for _ in range(3):
            llm(messages=[])
    assert counted.calls["disambiguation"] == 3 and counted.not_json["disambiguation"] == 1
    assert counted.shapes["disambiguation"]["decision,reason"] == 1 and counted.shapes["disambiguation"]["people"] == 1
    assert counted.unusable() == 1


def test_the_tally_wraps_an_awaitable_and_a_raise_and_restores_the_seam(monkeypatch):
    def fake(settings, **kw):
        async def call(*a, **k):
            if k.get("boom"):
                raise RuntimeError("discarded")
            return _reply('{"out_of_date": true}')
        return call

    monkeypatch.setattr(providers, "resolve_llm_fn", fake)
    with engines.tally() as counted:
        llm = providers.resolve_llm_fn(None, stage="value_match")

        async def go():
            await llm(messages=[])
            with pytest.raises(RuntimeError):
                await llm(messages=[], boom=True)

        asyncio.run(go())
    assert providers.resolve_llm_fn is fake
    assert counted.calls["value_match"] == 2 and counted.raised["value_match"]["RuntimeError"] == 1
    assert counted.unusable("value_match") == 1
    assert "value_match" in counted.report() and counted.as_dict()["unusable"] == 1
