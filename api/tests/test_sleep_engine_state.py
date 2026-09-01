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


def test_the_connector_poll_stays_unconditional_after_a_stage1_abort_even_with_a_dirty_tree(
    tmp_path, monkeypatch, tail_spy,
):
    """Fix round 1, M3: a total Stage-1 failure never wrote anything to disk
    (Stages 1-4 only compute `changes` in memory) — an UNRELATED dirty file
    in the bank (a direct Obsidian edit, a workflow this repo explicitly
    supports) must not silently stop connectors from polling on a failed
    cycle, exactly as it never stopped them on the old idle branch."""
    memory = _seed(tmp_path, unprocessed=1)
    monkeypatch.setattr(Settings, "memory_path", property(lambda self: memory))

    async def dirty(_path):
        return " M entities/unrelated-obsidian-edit.md\n"

    monkeypatch.setattr(git_service, "porcelain_status", dirty)
    _no_engine(monkeypatch)

    asyncio.run(sleep_cycle.run(Settings(), "sleep_test"))

    assert set(tail_spy) == {"logos", "connectors", "questions"}


def test_the_connector_poll_is_skipped_once_the_cycle_has_written_and_not_committed(
    monkeypatch, tail_spy,
):
    """H1 protection, preserved for the ACTUAL risk window: once Stage 5 has
    started writing entity/inbox pages and the cycle never reached
    `_finalize`'s commit, the connectors' own `git add -A` must never absorb
    those uncommitted writes into a session-less media commit.

    Exercised directly against `_run_engine_independent_tail` (unit-level,
    not a full `run()`): the only realistic way to reach `write_started=True`
    with `committed=False` is a raised exception between Stage 5's write and
    `_finalize`'s commit, which is exactly what `_state.write_started` exists
    to remember across — `_run_stages` never gets to `return` a
    `_StageOutcome` on that path, so the outcome object itself can't carry
    the signal.
    """
    from pathlib import Path

    sleep_cycle._state.write_started = True
    try:
        async def dirty(_path):
            return " M entities/x.md\n"

        monkeypatch.setattr(git_service, "porcelain_status", dirty)

        asyncio.run(sleep_cycle._run_engine_independent_tail(
            Path("/nonexistent"), Settings(), sleep_cycle._StageOutcome(committed=False),
        ))

        assert "connectors" not in tail_spy
        assert {"logos", "questions"} <= set(tail_spy)
    finally:
        sleep_cycle._state.write_started = False


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


def test_the_stage1_failure_message_prefers_the_throttle_sentence(monkeypatch):
    """L1: `_stage1_failure_message` keys on `breaker_reason()` FIRST — the
    only throttle signal left at the Stage-1-abort boundary, since Stage 1
    swallows `EngineThrottled` per episode so the breaker can fail every
    remaining call fast without spawning. Breaker state is reset around
    every test by conftest's autouse `_reset_agent_engine_state`, so this
    (and the two message tests above) can never silently flip on leaked
    state from a prior test."""
    assert agent_engine.breaker_reason() is None  # conftest's guarantee, made explicit
    sleep_cycle._state.episodes_total = 4
    try:
        agent_engine.trip_breaker("rate limit exceeded, please retry later")
        msg = sleep_cycle._stage1_failure_message("claude-cli")
        assert "Claude plan throttled" in msg
        assert "4 episode(s) left queued" in msg
        assert "rate limit exceeded, please retry later" in msg
    finally:
        sleep_cycle._state.episodes_total = 0


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


def test_the_preflight_prefers_a_warm_registry_cache_over_a_spawn(tmp_path, monkeypatch, tail_spy):
    """Fix round 1, M1: `Registry.cached_statuses()` NEVER probes — a status
    already warmed by `GET /connections`/`GET /status` (30 s TTL) answers the
    pre-flight for free. `agent_engine.probe` is booby-trapped to prove no
    spawn happens at all when the cache is warm."""
    import time as time_module

    from api.models.schemas import ConnectionKind, ConnectionStatus
    from api.services.connections import registry as connections_registry

    memory = _seed(tmp_path, unprocessed=2)
    monkeypatch.setattr(Settings, "memory_path", property(lambda self: memory))

    def _boom(**kw):
        raise AssertionError("spawned `claude` despite a warm registry cache")

    monkeypatch.setattr(agent_engine, "probe", _boom)

    settings = Settings(llm_mode="agent")
    reg = connections_registry.get_registry(settings)
    reg._cache["claude-plan"] = (time_module.monotonic(), ConnectionStatus(
        id="claude-plan", label="Claude plan", kind=ConnectionKind.subscription,
        available=True, connected=True, how="Claude Code signed in on this Mac.",
    ))

    # `_no_engine` (Stage 1 fails) is enough to prove the pre-flight resolved
    # WITHOUT spawning and let the pipeline proceed to Stage 1 — whether
    # Stage 1 itself then succeeds is a different concern (covered above).
    called = {"extract": False}

    async def extract(episodes, settings):
        called["extract"] = True
        return []

    monkeypatch.setattr("api.services.entity_extractor.extract", extract)

    asyncio.run(sleep_cycle.run(settings, "sleep_test"))

    state = sleep_cycle.get_sleep_state()
    assert called["extract"] is True   # reached Stage 1 — the cache answered the pre-flight
    assert state.engine_detail == "Claude Code signed in on this Mac."


def test_the_preflight_falls_back_to_a_short_timeout_spawn_when_the_cache_is_cold(
    tmp_path, monkeypatch, tail_spy,
):
    """Fix round 1, M1: a cold registry cache (nothing has probed
    Connections/Status recently in this process) still needs a real spawn —
    but capped at 5 s, not the original 20 s, since it is now a rare
    fallback rather than the primary path."""
    memory = _seed(tmp_path, unprocessed=1)
    monkeypatch.setattr(Settings, "memory_path", property(lambda self: memory))

    seen: dict = {}

    def fake_probe(**kw):
        seen.update(kw)
        return True, "Claude Code signed in on this Mac."

    monkeypatch.setattr(agent_engine, "probe", fake_probe)
    _no_engine(monkeypatch)

    asyncio.run(sleep_cycle.run(Settings(llm_mode="agent"), "sleep_test"))

    assert seen.get("timeout") == 5.0


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
