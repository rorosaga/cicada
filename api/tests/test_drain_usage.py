"""Plan usage stays attributed per batch under one person-started run (PR #138's
`cycle_usage`, TODO ruling 12; owner, 2026-09-29). Each batch is a cycle with its
own id, breaker scope, plan window bracket and clock; the drain adds ids only."""
from __future__ import annotations

import asyncio

import pytest

from drain_harness import episode_ids, install, seed_bank, settings

from api.services import agent_engine, cycle_usage, sleep_cycle, telemetry
from api.services.agent_stream import RateLimitSignal


def _mine(table, prefix):
    """This run's keys only: the accumulators are process-wide and other tests leave theirs."""
    return [k for k in table if prefix in k]


@pytest.fixture(autouse=True)
def _idle_state():
    s = sleep_cycle.get_sleep_state()
    s.status, s.drain, s.drain_run, s.cancel_requested = "idle", None, False, False
    yield
    s.status, s.drain, s.drain_run, s.cancel_requested = "idle", None, False, False


def test_every_batch_brackets_its_own_plan_window_and_names_the_drain(tmp_path, monkeypatch):
    ids = episode_ids(7)
    memory = seed_bank(tmp_path, ids)
    rig = install(monkeypatch, engine_label="claude-cli")
    scopes, events = [], []
    monkeypatch.setattr(telemetry, "record", lambda ev: events.append(ev))

    async def note_usage(batch_no, episodes):
        scope = agent_engine.current_scope()
        scopes.append(scope)
        cycle_usage.note_signals(
            agent_engine.cycle_id_from_scope(scope),
            [RateLimitSignal(status="allowed", limit_type="five_hour", utilization=batch_no / 10, resets_at=1790000000)])

    rig.on_extract = note_usage
    asyncio.run(sleep_cycle.run(
        settings(memory, sleep_max_episodes_per_cycle=3), "sleep_usage", user_triggered=True, drain=True))

    assert scopes == ["sleep:sleep_usage_b001", "sleep:sleep_usage_b002", "sleep:sleep_usage_b003"]
    runs = [e for e in events if e.kind == "sleep_run"]
    assert [r.refs["cycle_id"] for r in runs] == ["sleep_usage_b001", "sleep_usage_b002", "sleep_usage_b003"]
    assert {r.refs["drain_id"] for r in runs} == {"sleep_usage"}
    assert [(r.refs["batch"], r.refs["batches"]) for r in runs] == [(1, 3), (2, 3), (3, 3)]
    # each batch's plan block is its own calls, not the run's cumulative ones
    assert [r.refs["plan"]["windows"][0]["after"] for r in runs] == [0.1, 0.2, 0.3]
    assert [r.refs["episodes_processed"] for r in runs] == [3, 3, 1], "a batch's ledger row is its own"
    assert all(r.refs[cycle_usage.TAGGED_REF] is True for r in runs)
    # bounded: nothing outlives the run
    assert _mine(cycle_usage._CLAUDE, "sleep_usage") == [] and _mine(cycle_usage._CODEX_START, "sleep_usage") == []
    assert _mine(agent_engine._BREAKER, "sleep_usage") == [] == _mine(agent_engine._BREAKER_RESETS, "sleep_usage")


def test_a_batchs_duration_is_its_own_not_the_time_since_the_drain_began(tmp_path, monkeypatch):
    memory = seed_bank(tmp_path, episode_ids(6))
    rig = install(monkeypatch)
    events = []
    monkeypatch.setattr(telemetry, "record", lambda ev: events.append(ev))
    clock = {"t": 1000.0}

    from types import SimpleNamespace

    # A shim for sleep_cycle's own `time` only — asyncio's clock is left alone.
    monkeypatch.setattr(sleep_cycle, "time", SimpleNamespace(monotonic=lambda: clock["t"]))

    async def slow(batch_no, episodes):
        clock["t"] += 50.0   # every batch takes 50 s

    rig.on_extract = slow
    asyncio.run(sleep_cycle.run(
        settings(memory, sleep_max_episodes_per_cycle=3), "sleep_clock", user_triggered=True, drain=True))
    runs = [e for e in events if e.kind == "sleep_run"]
    assert [r.duration_ms for r in runs] == [50000, 50000]


def test_a_plan_stop_leaves_no_breaker_or_window_behind(tmp_path, monkeypatch):
    memory = seed_bank(tmp_path, episode_ids(6))
    rig = install(monkeypatch, engine_label="claude-cli")

    async def trip(batch_no, episodes):
        cycle_usage.note_signals(
            agent_engine.cycle_id_from_scope(agent_engine.current_scope()),
            [RateLimitSignal(status="rejected", limit_type="five_hour", utilization=1.0, resets_at=1790000000)])
        if batch_no == 2:
            agent_engine.trip_breaker("Your Claude plan hit its 5-hour limit — Sleep paused.", resets_at=1790000000)
            return [e["id"] for e in episodes]

    rig.on_extract = trip
    asyncio.run(sleep_cycle.run(
        settings(memory, sleep_max_episodes_per_cycle=3), "sleep_trip", user_triggered=True, drain=True))
    assert sleep_cycle.get_sleep_state().drain.stop.reason == "plan_limit"
    assert _mine(cycle_usage._CLAUDE, "sleep_trip") == [] and _mine(agent_engine._BREAKER, "sleep_trip") == []
    assert _mine(agent_engine._BREAKER_RESETS, "sleep_trip") == []
