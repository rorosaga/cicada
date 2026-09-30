"""Leave room in my plan — the reserve (Sleep page v5, B6; owner 2026-09-30: off by default).

A soft stop, not a tripped breaker: the batch in progress keeps what it read, the rest is never
started and is not an attempt. A line, not a guarantee: what was already running finishes."""
from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from drain_harness import episode_ids, install, is_processed, seed_bank, waiting

from api import main
from api.config import Settings, get_settings
from api.services import (
    agent_engine, cycle_usage, sleep_cycle, sleep_drain, sleep_paused, sleep_reserve, sleep_run_prefs,
)
from api.services.agent_stream import RateLimitSignal
from api.services.connections import registry as registry_module


def _future() -> int:
    return int(time.time()) + 3600


def _signal(util, window="five_hour", reset=None):
    return RateLimitSignal(status="allowed", limit_type=window, utilization=util, resets_at=reset or _future())


@pytest.fixture(autouse=True)
def _idle_state():
    s = sleep_cycle.get_sleep_state()
    s.status, s.drain, s.drain_run, s.cancel_requested = "idle", None, False, False
    registry_module.reset_registry()
    yield
    s.status, s.drain, s.drain_run, s.cancel_requested = "idle", None, False, False
    registry_module.reset_registry()
    main.app.dependency_overrides.clear()


def _cfg(memory, **over):
    # `CICADA_MEMORY_PATH` is the field's validation alias: a `memory_root=` kwarg is silently ignored
    # and would point at the real default bank.
    return Settings(CICADA_MEMORY_PATH=memory, sleep_max_episodes_per_cycle=3, link_enrich_enabled=False, **over)


def _reserve(pct):
    sleep_run_prefs.write(registry_module.get_registry(Settings()), reserve_pct=pct)


def _run(memory, cid="sleep_rsv", **over):
    cfg = _cfg(memory, **over)
    asyncio.run(sleep_cycle.run(cfg, cid, user_triggered=True, drain=True))
    return cfg, sleep_cycle.get_sleep_state()


def test_the_reserve_soft_stop_files_the_partial_batch_and_pauses(tmp_path, monkeypatch):
    ids = episode_ids(9)
    memory = seed_bank(tmp_path, ids)
    rig = install(monkeypatch, engine_label="claude-cli")
    _reserve(10)
    reset = _future()

    def report(ep):
        if ep["id"] == ids[0]:   # the first read's call reports the window at 93% — past the 90% line
            sleep_cycle.get_sleep_state().drain.guard.observe_signals([_signal(0.93, reset=reset)])

    rig.after_read = report
    _cfg_, state = _run(memory)
    ds = state.drain

    assert rig.skipped == [ids[1], ids[2]], "no new read starts once the window is past the line"
    assert [is_processed(memory, i) for i in ids[:3]] == [True, False, False], "what was read is filed, not thrown away"
    assert ds.committed_batches == 1 and ds.filed == 1 and len(rig.extract_batches) == 1
    assert ds.stop.reason == "reserve" and ds.stop.sentence == "Paused to leave room in your plan."
    assert (ds.stop.resets_at, ds.stop.limit) == (reset, "five_hour")
    assert state.error is None, "a pause, not a failure: no breaker tripped and Stage 2 never raised"
    assert ds.attempts == {} and not ds.unread and not ds.parked, "skipped by the reserve is not an attempt"
    assert ids[1] not in ds.settled and ids[2] not in ds.settled, "and not settled: Continue reads them"
    assert set(ds.requeued_ids) >= {ids[1], ids[2]}
    rec = sleep_paused.get_paused(memory)
    assert rec["reason"] == "reserve" and rec["limit"] == "five_hour" and rec["resets_at"] == reset
    assert "links" not in rig.tail, "the tail's link backfill would spend the plan the person is keeping"
    assert waiting(memory) == ids[1:]


def test_a_reserve_reached_before_the_first_read_pauses_at_once_with_no_paid_call(tmp_path, monkeypatch):
    """Continue into a window that is still past the line (the last recorded cycle says so)."""
    memory = seed_bank(tmp_path, episode_ids(6))
    rig = install(monkeypatch, engine_label="claude-cli")
    _reserve(10)
    reset = _future()
    monkeypatch.setattr(cycle_usage, "last_cycles", lambda events=None, bank=None: {
        "claude-plan": {"window": "five_hour", "used_fraction": 0.95, "resets_at": reset, "as_of": "x"}})
    _cfg_, state = _run(memory)
    ds = state.drain
    assert rig.extract_batches == [] and ds.committed_batches == 0, "not one paid call was made"
    assert ds.stop.reason == "reserve" and ds.stop.resets_at == reset
    assert sleep_paused.get_paused(memory)["reason"] == "reserve"
    assert waiting(memory) == episode_ids(6)


def test_a_window_whose_reset_has_passed_is_not_a_reason_to_stop(tmp_path, monkeypatch):
    memory = seed_bank(tmp_path, episode_ids(3))
    rig = install(monkeypatch, engine_label="claude-cli")
    _reserve(10)
    monkeypatch.setattr(cycle_usage, "last_cycles", lambda events=None, bank=None: {
        "claude-plan": {"window": "five_hour", "used_fraction": 0.99, "resets_at": int(time.time()) - 60, "as_of": "x"}})
    _cfg_, state = _run(memory)
    assert rig.extract_batches and state.drain.finished, "the window reset since: that reading is stale"


def test_the_reserve_reached_on_the_last_batch_is_a_finished_run_not_a_pause(tmp_path, monkeypatch):
    ids = episode_ids(3)
    memory = seed_bank(tmp_path, ids)
    rig = install(monkeypatch, engine_label="claude-cli")
    _reserve(10)
    rig.after_read = lambda ep: sleep_cycle.get_sleep_state().drain.guard.observe_signals([_signal(0.99)]) \
        if ep["id"] == ids[2] else None    # after the very last read: nothing is left to protect
    _cfg_, state = _run(memory)
    assert state.drain.stop is None and state.drain.finished and state.drain.filed == 3
    assert sleep_paused.get_paused(memory) is None


def test_off_leaves_the_claude_rungs_own_90_percent_stop_alone(tmp_path, monkeypatch):
    memory = seed_bank(tmp_path, episode_ids(3))
    install(monkeypatch, engine_label="claude-cli")
    seen = []
    real = sleep_cycle._run_batch

    async def spy(settings, batch_id, memory_path, *, user_triggered, batch=None):
        seen.append(getattr(batch.resolved[0], "agent_stop_utilization", None))
        return await real(settings, batch_id, memory_path, user_triggered=user_triggered, batch=batch)

    monkeypatch.setattr(sleep_cycle, "_run_batch", spy)
    _cfg_, state = _run(memory)
    assert seen == [0.9], "no reserve figure set: R-E12's stop is exactly what it was"
    assert state.drain.guard is None and state.drain.reserve_pct is None


def test_a_reserve_lifts_that_stop_for_the_run_or_a_5_percent_line_would_be_pre_empted(tmp_path, monkeypatch):
    memory = seed_bank(tmp_path, episode_ids(3))
    install(monkeypatch, engine_label="claude-cli")
    _reserve(5)
    seen = []
    real = sleep_cycle._run_batch

    async def spy(settings, batch_id, memory_path, *, user_triggered, batch=None):
        seen.append(batch.resolved[0].agent_stop_utilization)
        return await real(settings, batch_id, memory_path, user_triggered=user_triggered, batch=batch)

    monkeypatch.setattr(sleep_cycle, "_run_batch", spy)
    _cfg_, state = _run(memory)
    assert seen == [1.0] and state.drain.guard is not None
    assert Settings().agent_stop_utilization == 0.9, "the shared Settings object is never mutated"


def test_a_reserve_only_applies_to_a_plan_engine(tmp_path, monkeypatch):
    memory = seed_bank(tmp_path, episode_ids(3))
    rig = install(monkeypatch)   # the metered rung: no plan window to keep free
    _reserve(10)
    _cfg_, state = _run(memory)
    assert state.drain.guard is None and state.drain.reserve_pct is None
    assert rig.skipped == [] and state.drain.finished


def test_a_chatgpt_plan_run_never_pauses_on_the_claude_plans_last_window(tmp_path, monkeypatch):
    """Review: the guard is seeded only from the plan the run is on. A full Claude window in the
    ledger must not stop a ChatGPT-plan run, nor show as an enforced window for it."""
    ids = episode_ids(3)
    memory = seed_bank(tmp_path, ids)
    rig = install(monkeypatch, engine_label="codex-cli")
    _reserve(10)
    from api.services import codex_engine

    monkeypatch.setattr(cycle_usage, "last_cycles", lambda events=None, bank=None: {
        "claude-plan": {"window": "five_hour", "used_fraction": 0.99, "resets_at": _future(), "as_of": "x"}})

    async def preflight(**_kw):
        codex_engine._last_snapshot = SimpleNamespace(windows=(("primary", 10, _future()),))
        return True, "Signed in to your plan.", None

    async def begin(_cycle_id):
        return None

    monkeypatch.setattr(codex_engine, "preflight", preflight)
    monkeypatch.setattr(cycle_usage, "begin_codex", begin)
    _cfg_, state = _run(memory)
    ds = state.drain
    assert rig.extract_batches == [ids], "it read"
    assert ds.stop is None and ds.finished and ds.filed == 3
    assert "five_hour" not in ds.guard.windows, "another plan's window is never this run's"
    assert sleep_paused.get_paused(memory) is None


def test_the_chatgpt_plan_is_read_from_the_preflight_snapshot_at_each_batch_boundary(tmp_path, monkeypatch):
    ids = episode_ids(6)
    memory = seed_bank(tmp_path, ids)
    rig = install(monkeypatch, engine_label="codex-cli")
    _reserve(10)
    from api.services import codex_engine

    snapshots = iter([
        SimpleNamespace(windows=(("primary", 40, _future()), ("secondary", 10, _future()))),   # batch 1: room
        SimpleNamespace(windows=(("primary", 40, _future()), ("secondary", 95, _future()))),   # batch 2: past the line
    ])
    probes = []

    async def preflight(**_kw):
        snap = next(snapshots)
        probes.append(snap)
        codex_engine._last_snapshot = snap
        return True, "Signed in to your plan.", None

    async def begin(_cycle_id):
        return None

    monkeypatch.setattr(codex_engine, "preflight", preflight)
    monkeypatch.setattr(cycle_usage, "begin_codex", begin)
    _cfg_, state = _run(memory)
    ds = state.drain

    assert len(probes) == 2, "one read per batch (the pre-flight's own), never a second probe"
    assert len(rig.extract_batches) == 1 and ds.committed_batches == 1
    assert ds.stop.reason == "reserve" and ds.stop.limit == "unknown", "the snapshot's window kind is not assumed"
    assert waiting(memory) == ids[3:]


def test_a_window_the_engine_never_reports_is_named_as_not_enforced_never_promised():
    g = sleep_reserve.ReserveGuard(10, engine="claude-cli")
    assert g.wire() == {"pct": 10, "windows": [{"window": "five_hour", "enforced": None},
                                               {"window": "seven_day", "enforced": None}]}, "before any call: unknown"
    g.observe_signals([_signal(0.2)])
    assert g.wire()["windows"] == [{"window": "five_hour", "enforced": True},
                                   {"window": "seven_day", "enforced": False, "reason": "not_reported"}]
    g.observe_signals([_signal(0.4, "seven_day")])
    assert [w["enforced"] for w in g.wire()["windows"]] == [True, True]
    assert not g.is_reached()
    g.observe_signals([_signal(0.91, "seven_day")])
    assert g.is_reached() and g.stop_values()[1] == "seven_day"
    g2 = sleep_reserve.ReserveGuard(20, engine="claude-cli")
    g2.observe_signals([_signal(0.79)])
    assert not g2.is_reached(), "20% is a line at 80%"
    g2.observe_signals([_signal(0.80)])
    assert g2.is_reached()


def test_the_engine_menu_says_whether_the_reserve_applies_and_which_windows(tmp_path, monkeypatch):
    memory = seed_bank(tmp_path, episode_ids(3))
    main.app.dependency_overrides[get_settings] = lambda: _cfg(memory)
    client = TestClient(main.app)
    client.put("/sleep/run-options", json={"reservePct": 10})
    r = client.get("/sleep/engine").json()["reserve"]
    assert r["pct"] == 10 and r["choices"] == [5, 10, 20, 30]
    assert r["applies"] is False, "the default engine is a key: no plan window to keep free"
    assert r["windows"] == []
