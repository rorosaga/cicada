"""G74(a) Task 5 — the abort is no longer upside-down, and the engine is honest.

The old ordering meant a non-empty queue with no engine did LESS work than an
empty one: `return` at sleep_cycle.py:261 skipped the logo warm-up, the
connector poll and the question refresh — all three of which need no LLM.
"""
from __future__ import annotations

import asyncio

import pytest

from api.config import Settings
from api.services import agent_engine, git_service, markdown_parser, predicates, sleep_cycle


def _seed(tmp_path, *, unprocessed: int):
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    (memory / "episodes").mkdir(parents=True)
    (memory / "inbox").mkdir(parents=True)
    predicates.install_predicate_map(memory)
    for i in range(unprocessed):
        markdown_parser.write(
            memory / "episodes" / f"ep_2026-09-01_{i:03d}.md",
            {"id": f"ep_2026-09-01_{i:03d}", "processed": False, "source": "mcp",
             "timestamp": f"2026-09-01T10:0{i}:00"},
            "Episode body about project X and tool Y.",
        )
    return memory


@pytest.fixture
def tail_spy(monkeypatch):
    """Record which engine-independent steps ran, in order."""
    ran: list[str] = []

    async def _logos(memory_path):
        ran.append("logos")

    async def _connectors(memory_path):
        ran.append("connectors")

    async def _questions(memory_path, settings):
        ran.append("questions")

    monkeypatch.setattr(sleep_cycle, "_warm_logos_safely", _logos)
    monkeypatch.setattr(sleep_cycle, "_poll_connectors_safely", _connectors)
    monkeypatch.setattr(sleep_cycle, "_refresh_questions_safely", _questions)
    return ran


def _no_engine(monkeypatch):
    """Stage 1 returns nothing for every episode — the total-failure case."""
    async def extract(episodes, settings):
        return []

    monkeypatch.setattr("api.services.entity_extractor.extract", extract)


# --------------------------------------------------------------------------- #
# The abort ordering fix (spec §1)
# --------------------------------------------------------------------------- #

def test_a_dead_engine_still_runs_logos_connectors_and_questions(tmp_path, monkeypatch, tail_spy):
    memory = _seed(tmp_path, unprocessed=3)
    monkeypatch.setattr(Settings, "memory_path", property(lambda self: memory))
    _no_engine(monkeypatch)

    asyncio.run(sleep_cycle.run(Settings(), "sleep_test"))

    assert set(tail_spy) == {"logos", "connectors", "questions"}
    assert sleep_cycle.get_sleep_state().error


def test_an_idle_cycle_still_runs_all_three(tmp_path, monkeypatch, tail_spy):
    memory = _seed(tmp_path, unprocessed=0)
    monkeypatch.setattr(Settings, "memory_path", property(lambda self: memory))

    asyncio.run(sleep_cycle.run(Settings(), "sleep_test"))

    assert set(tail_spy) == {"logos", "connectors", "questions"}


def test_a_raised_exception_mid_pipeline_still_runs_the_tail(tmp_path, monkeypatch, tail_spy):
    memory = _seed(tmp_path, unprocessed=2)
    monkeypatch.setattr(Settings, "memory_path", property(lambda self: memory))

    async def boom(episodes, settings):
        raise RuntimeError("stage 1 exploded")

    monkeypatch.setattr("api.services.entity_extractor.extract", boom)

    asyncio.run(sleep_cycle.run(Settings(), "sleep_test"))

    assert set(tail_spy) == {"logos", "connectors", "questions"}
    assert "stage 1 exploded" in (sleep_cycle.get_sleep_state().error or "")


def test_the_queue_is_untouched_when_the_engine_is_dead(tmp_path, monkeypatch, tail_spy):
    memory = _seed(tmp_path, unprocessed=3)
    monkeypatch.setattr(Settings, "memory_path", property(lambda self: memory))
    _no_engine(monkeypatch)

    asyncio.run(sleep_cycle.run(Settings(), "sleep_test"))

    assert len(sleep_cycle._get_unprocessed_episodes(memory)) == 3


def test_the_connector_poll_is_skipped_when_the_tree_is_dirty(tmp_path, monkeypatch, tail_spy):
    """H1 protection: the connectors' own `git add -A` must never absorb a
    failed cycle's uncommitted entity writes into a media commit."""
    memory = _seed(tmp_path, unprocessed=1)
    monkeypatch.setattr(Settings, "memory_path", property(lambda self: memory))

    async def dirty(_path):
        return " M entities/x.md\n"

    monkeypatch.setattr(git_service, "porcelain_status", dirty)
    _no_engine(monkeypatch)

    asyncio.run(sleep_cycle.run(Settings(), "sleep_test"))

    assert "connectors" not in tail_spy
    assert {"logos", "questions"} <= set(tail_spy)


# --------------------------------------------------------------------------- #
# Honest engine copy + state
# --------------------------------------------------------------------------- #

def test_the_stage1_failure_message_no_longer_says_api_credits_on_a_plan():
    msg = sleep_cycle._stage1_failure_message("claude-cli")
    assert "API credits" not in msg
    assert "claude auth status" in msg


def test_the_byok_failure_message_still_names_credits():
    msg = sleep_cycle._stage1_failure_message("litellm")
    assert "credit" in msg.lower()


def test_engine_label_maps_the_mode(monkeypatch):
    assert sleep_cycle._engine_label(Settings(llm_mode="agent")) == "claude-cli"
    assert sleep_cycle._engine_label(Settings(llm_mode="local")) == "ollama"
    assert sleep_cycle._engine_label(Settings(llm_mode="byok")) == "litellm"


def test_the_preflight_probe_aborts_before_stage_1_with_the_fix(tmp_path, monkeypatch, tail_spy):
    memory = _seed(tmp_path, unprocessed=2)
    monkeypatch.setattr(Settings, "memory_path", property(lambda self: memory))
    monkeypatch.setattr(agent_engine, "probe",
                        lambda **kw: (False, "Claude Code is signed out — run `claude auth login`."))

    called = {"extract": False}

    async def extract(episodes, settings):
        called["extract"] = True
        return []

    monkeypatch.setattr("api.services.entity_extractor.extract", extract)

    asyncio.run(sleep_cycle.run(Settings(llm_mode="agent"), "sleep_test"))

    state = sleep_cycle.get_sleep_state()
    assert called["extract"] is False               # never spent a spawn
    assert "claude auth login" in (state.error or "")
    assert state.last_engine == "claude-cli"
    assert set(tail_spy) == {"logos", "connectors", "questions"}


def test_the_probe_is_not_run_on_an_idle_cycle(tmp_path, monkeypatch, tail_spy):
    memory = _seed(tmp_path, unprocessed=0)
    monkeypatch.setattr(Settings, "memory_path", property(lambda self: memory))

    def _boom(**kw):
        raise AssertionError("probed an idle cycle")

    monkeypatch.setattr(agent_engine, "probe", _boom)
    asyncio.run(sleep_cycle.run(Settings(llm_mode="agent"), "sleep_test"))


def test_the_breaker_is_reset_at_the_top_of_every_cycle(tmp_path, monkeypatch, tail_spy):
    memory = _seed(tmp_path, unprocessed=0)
    monkeypatch.setattr(Settings, "memory_path", property(lambda self: memory))
    agent_engine.trip_breaker("left over from the last cycle")
    asyncio.run(sleep_cycle.run(Settings(), "sleep_test"))
    assert agent_engine.breaker_reason() is None


def test_sleep_status_exposes_the_engine():
    from fastapi.testclient import TestClient

    from api import main

    sleep_cycle.get_sleep_state().last_engine = "claude-cli"
    sleep_cycle.get_sleep_state().engine_detail = "Claude Code signed in on this Mac."
    body = TestClient(main.app).get("/sleep/status").json()
    assert body["lastEngine"] == "claude-cli"
    assert body["engineDetail"] == "Claude Code signed in on this Mac."
