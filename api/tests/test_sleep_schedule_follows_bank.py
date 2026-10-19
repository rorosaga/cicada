"""The scheduled Sleep job follows the ACTIVE bank's own schedule (follow-ups 2026-10-19).

Before: `register_job` built the trigger from the schedule loaded when it was registered (startup, or a schedule save),
and `_run_if_idle` never re-read the active bank's mode — so after a bank switch the job kept the old bank's trigger,
and a bank set to `manual` got a scheduled run on the old bank's 03:00. Now the switch routes re-register from the new
bank's schedule (`follow_active_bank`) and a fire whose trigger is not the active bank's re-registers and runs nothing
(`_stale_trigger`, for a switch that did not come through a route).
"""
from __future__ import annotations

import asyncio

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from fastapi.testclient import TestClient

from api import config, main
from api.models.schemas import ScheduleConfig
from api.services import bank_registry, sleep_catch_up, sleep_cycle, sleep_scheduler


@pytest.fixture
def banks(tmp_path, monkeypatch):
    """Synthetic `default` (daily 03:00) and `beta` banks; Sleep's run is an observation stub."""
    root = tmp_path / "bank-root"
    root.mkdir()
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(root))
    config.get_settings.cache_clear()
    bank_registry.scaffold_bank(root)
    bank_registry.create_bank(root, "beta", seed_owner=False)
    sleep_scheduler.save_schedule(root, ScheduleConfig(mode="daily", hour=3, minute=0))
    runs: list = []

    async def observed_run(settings, *args, **kwargs):
        runs.append(settings.memory_path)

    monkeypatch.setattr(sleep_cycle, "run", observed_run)
    monkeypatch.setattr(sleep_scheduler, "_paused_for_the_person", lambda mp: False)
    sleep_cycle.get_sleep_state().status = "idle"
    sleep_catch_up.reset_for_tests()
    yield root, runs
    config.get_settings.cache_clear()


class _Scheduler:
    """An AsyncIOScheduler that is never started: jobs are added and inspected, and a test fires one by hand."""

    def __init__(self):
        self.inner = AsyncIOScheduler()

    def __getattr__(self, name):
        return getattr(self.inner, name)


def _fire(scheduler, job_id=sleep_scheduler.JOB_ID):
    job = scheduler.get_job(job_id)
    assert job is not None, f"no {job_id} job registered"
    asyncio.run(job.func(*job.args, **job.kwargs))


def _cron_fields(job) -> dict:
    assert isinstance(job.trigger, CronTrigger)
    return {f.name: str(f) for f in job.trigger.fields if f.name in ("hour", "minute")}


def _switch(client: TestClient, name: str) -> None:
    resp = client.post(f"/banks/{name}/activate")
    assert resp.status_code == 200, resp.text


@pytest.fixture
def client(banks, monkeypatch):
    scheduler = _Scheduler()
    monkeypatch.setattr(main.app.state, "scheduler", scheduler, raising=False)
    settings = config.get_settings()
    sleep_scheduler.register_job(scheduler, settings, sleep_scheduler.load_schedule(settings.memory_path))
    return TestClient(main.app), scheduler, settings


def test_switching_to_a_manual_bank_removes_the_job_and_nothing_runs(banks, client):
    root, runs = banks
    c, scheduler, settings = client
    assert _cron_fields(scheduler.get_job(sleep_scheduler.JOB_ID)) == {"hour": "3", "minute": "0"}
    _switch(c, "beta")                                   # beta has no schedule file: manual
    assert scheduler.get_job(sleep_scheduler.JOB_ID) is None
    assert scheduler.get_job(sleep_catch_up.JOB_ID) is None
    assert runs == []


def test_a_stale_trigger_firing_for_a_manual_bank_runs_nothing(banks, client):
    """The bug as reported: the switch did not come through the route (the registry changed underneath), the old
    03:00 trigger fires, and the active bank is on `manual` — before the fix `_run_if_idle` ran Sleep on it."""
    root, runs = banks
    c, scheduler, settings = client
    bank_registry.activate_bank(root, "beta")            # no route: the job still holds default's 03:00
    _fire(scheduler)
    assert runs == []
    assert scheduler.get_job(sleep_scheduler.JOB_ID) is None, "the fire re-registered from beta's own schedule"
    assert scheduler.get_job(sleep_catch_up.JOB_ID) is None


def test_switching_to_a_bank_on_05_00_fires_at_05_00_for_that_bank(banks, client):
    root, runs = banks
    c, scheduler, settings = client
    sleep_scheduler.save_schedule(bank_registry.bank_dir(root, "beta"), ScheduleConfig(mode="daily", hour=5, minute=0))
    _switch(c, "beta")
    job = scheduler.get_job(sleep_scheduler.JOB_ID)
    assert _cron_fields(job) == {"hour": "5", "minute": "0"}
    assert job.kwargs["registered"].hour == 5
    _fire(scheduler)
    assert runs == [bank_registry.bank_dir(root, "beta")]


def test_switching_back_restores_the_old_schedule(banks, client):
    root, runs = banks
    c, scheduler, settings = client
    sleep_scheduler.save_schedule(bank_registry.bank_dir(root, "beta"), ScheduleConfig(mode="interval", interval_hours=8))
    _switch(c, "beta")
    job = scheduler.get_job(sleep_scheduler.JOB_ID)
    assert isinstance(job.trigger, IntervalTrigger) and job.trigger.interval.total_seconds() == 8 * 3600
    _switch(c, "default")
    assert _cron_fields(scheduler.get_job(sleep_scheduler.JOB_ID)) == {"hour": "3", "minute": "0"}
    assert scheduler.get_job(sleep_catch_up.JOB_ID) is not None
    _fire(scheduler)
    assert runs == [root]


def test_a_stale_trigger_re_registers_the_active_banks_time_and_skips_the_old_one(banks, client):
    root, runs = banks
    c, scheduler, settings = client
    sleep_scheduler.save_schedule(bank_registry.bank_dir(root, "beta"), ScheduleConfig(mode="daily", hour=5, minute=30))
    bank_registry.activate_bank(root, "beta")            # no route
    _fire(scheduler)                                     # default's 03:00 fires
    assert runs == [], "nothing runs on another bank's time"
    assert _cron_fields(scheduler.get_job(sleep_scheduler.JOB_ID)) == {"hour": "5", "minute": "30"}
    _fire(scheduler)                                     # beta's own 05:30
    assert runs == [bank_registry.bank_dir(root, "beta")]


def test_two_banks_on_the_same_schedule_share_the_trigger_and_run_the_active_one(banks, client):
    root, runs = banks
    c, scheduler, settings = client
    sleep_scheduler.save_schedule(bank_registry.bank_dir(root, "beta"), ScheduleConfig(mode="daily", hour=3, minute=0))
    bank_registry.activate_bank(root, "beta")            # no route, same schedule
    _fire(scheduler)
    assert runs == [bank_registry.bank_dir(root, "beta")]


def test_the_after_import_probe_follows_the_active_bank_too(banks, client):
    root, runs = banks
    c, scheduler, settings = client
    sleep_scheduler.save_schedule(root, ScheduleConfig(mode="after_import"))
    sleep_scheduler.register_job(scheduler, settings, ScheduleConfig(mode="after_import"))
    bank_registry.activate_bank(root, "beta")            # manual, no route
    _fire(scheduler)
    assert runs == []
    assert scheduler.get_job(sleep_scheduler.JOB_ID) is None


def test_the_demo_doors_and_a_bare_app_never_fail_the_switch(banks, monkeypatch):
    """No scheduler on the app (a bare test app): the switch still answers; `follow_active_bank` is a no-op."""
    root, runs = banks
    monkeypatch.setattr(main.app.state, "scheduler", None, raising=False)
    resp = TestClient(main.app).post("/banks/beta/activate")
    assert resp.status_code == 200
    assert sleep_scheduler.follow_active_bank(None, config.get_settings()) is None
