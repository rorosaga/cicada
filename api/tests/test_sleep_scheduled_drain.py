"""TODO ruling 16 (owner 2026-09-30): a scheduled cycle reads everything waiting too — and ruling 4 is
untouched: it never uses a plan, so it reads on the scheduled engine."""
from __future__ import annotations

import asyncio

import pytest

from drain_harness import episode_ids, install, seed_bank, settings, waiting

from api.services import engine_select, sleep_cycle, sleep_debt, sleep_scheduler
from api.services.connections import registry as registry_module


@pytest.fixture(autouse=True)
def _state():
    s = sleep_cycle.get_sleep_state()
    s.status, s.drain, s.drain_run, s.cancel_requested = "idle", None, False, False
    registry_module.reset_registry()
    yield
    s.status, s.drain, s.drain_run, s.cancel_requested = "idle", None, False, False
    registry_module.reset_registry()


def _sub(memory, cap=3):
    return settings(memory, sleep_max_episodes_per_cycle=cap)


def test_a_scheduled_drain_reads_every_batch_but_never_selects_a_plan(tmp_path, monkeypatch):
    ids = episode_ids(8)
    memory = seed_bank(tmp_path, ids)
    rig = install(monkeypatch)
    # The person's own choice is a plan engine — for a run THEY start.
    registry_module.get_registry(_sub(memory)).set_pref(engine_select.SLEEP_ENGINE_PREF_KEY, "mode", "agent")
    seen = []
    real = engine_select.resolve_settings

    async def spy(settings_, *a, **k):
        out = await real(settings_, *a, **k)
        seen.append((k.get("user_triggered"), engine_select.engine_label(out[0])))
        return out

    monkeypatch.setattr(engine_select, "resolve_settings", spy)
    asyncio.run(sleep_scheduler._run_if_idle(_sub(memory)))

    assert [len(b) for b in rig.extract_batches] == [3, 3, 2], "every batch, not one"
    assert waiting(memory) == []
    assert seen == [(False, "litellm")], "resolved once, unattended, and never a plan (ruling 4)"
    ds = sleep_cycle.get_sleep_state().drain
    assert ds.started_by == "schedule" and ds.finished and ds.committed_batches == 3


def test_the_after_import_probe_drains_too_and_says_who_started_it(tmp_path, monkeypatch):
    from datetime import datetime, timedelta

    ids = episode_ids(5)
    memory = seed_bank(tmp_path, ids)
    rig = install(monkeypatch)

    async def old_queue(memory_path, settings_=None):
        real = await _real_compute(memory_path, settings_)
        real.newest_unprocessed_at = datetime.now() - timedelta(hours=1)
        return real

    _real_compute = sleep_debt.compute
    monkeypatch.setattr(sleep_debt, "compute", old_queue)
    asyncio.run(sleep_scheduler._run_after_intake_if_settled(_sub(memory, cap=2)))
    assert [len(b) for b in rig.extract_batches] == [2, 2, 1]
    wire = sleep_cycle.get_sleep_state().drain
    assert wire.started_by == "schedule"


def test_a_scheduled_drain_holds_the_bank_switch_guard_like_any_run(tmp_path, monkeypatch):
    """Disclosed (R-3): it can run for hours, and the same 409 protects its pinned bank."""
    memory = seed_bank(tmp_path, episode_ids(6))
    rig = install(monkeypatch)
    held = []

    async def look(batch_no, episodes):
        held.append(sleep_cycle.get_sleep_state().drain_run)

    rig.on_extract = look
    asyncio.run(sleep_scheduler._run_if_idle(_sub(memory)))
    assert held == [True, True] and sleep_cycle.get_sleep_state().drain_run is False
