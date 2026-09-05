"""G125 (4) — schedule modes: manual · daily · every N hours · after imports.

`mode` is the truth; `enabled` is derived for older readers (R6). "After
imports" is a settle probe, not a writer hook (R7): every 5 min, run iff idle,
queue non-empty, newest unprocessed ≥ 10 min old. Every scheduled path stays
`user_triggered=False` (TODO.md ruling 4).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
import yaml

from api.models.schemas import ScheduleConfig
from api.services import sleep_cycle, sleep_scheduler


def test_mode_derives_enabled_and_old_payloads_still_load():
    assert ScheduleConfig(mode="manual", hour=3, minute=0).enabled is False
    assert ScheduleConfig(mode="interval", hour=3, minute=0, interval_hours=4).enabled is True
    old = ScheduleConfig(enabled=True, hour=3, minute=0)           # no `mode` — an older client
    assert old.mode == "daily"
    assert ScheduleConfig(enabled=False, hour=3, minute=0).mode == "manual"
    with pytest.raises(ValueError):
        ScheduleConfig(mode="interval", hour=3, minute=0, interval_hours=0)


def test_yaml_round_trip_and_legacy_yaml(tmp_path):
    cfg = ScheduleConfig(mode="interval", hour=3, minute=0, interval_hours=8)
    sleep_scheduler.save_schedule(tmp_path, cfg)
    assert sleep_scheduler.load_schedule(tmp_path) == cfg
    (tmp_path / sleep_scheduler.SCHEDULE_FILE).write_text(yaml.safe_dump({"enabled": True, "hour": 4, "minute": 30}))
    legacy = sleep_scheduler.load_schedule(tmp_path)
    assert (legacy.mode, legacy.hour, legacy.minute, legacy.enabled) == ("daily", 4, 30, True)


def test_next_run_at_per_mode(tmp_path):
    now = datetime(2026, 9, 5, 12, 0, 0)
    sleep_scheduler.save_schedule(tmp_path, ScheduleConfig(mode="manual", hour=3, minute=0))
    assert sleep_scheduler.next_run_at(tmp_path, now) is None
    sleep_scheduler.save_schedule(tmp_path, ScheduleConfig(mode="daily", hour=3, minute=0))
    assert sleep_scheduler.next_run_at(tmp_path, now) == "2026-09-06T03:00:00"
    sleep_scheduler.save_schedule(tmp_path, ScheduleConfig(mode="interval", hour=3, minute=0, interval_hours=6))
    assert sleep_scheduler.next_run_at(tmp_path, now, last_cycle_at=now - timedelta(hours=2)) == "2026-09-05T16:00:00"
    assert sleep_scheduler.next_run_at(tmp_path, now, last_cycle_at=None) == "2026-09-05T18:00:00"
    sleep_scheduler.save_schedule(tmp_path, ScheduleConfig(mode="after_import", hour=3, minute=0))
    assert sleep_scheduler.next_run_at(tmp_path, now, newest_unprocessed_at=now - timedelta(minutes=3)) == "2026-09-05T12:07:00"
    assert sleep_scheduler.next_run_at(tmp_path, now, newest_unprocessed_at=None) is None


def _probe(monkeypatch, *, status, unprocessed, newest_age_min):
    calls = []

    async def fake_run(settings, cycle_id, *, user_triggered=True):
        calls.append(user_triggered)

    async def fake_compute(memory_path, settings=None):
        newest = None if newest_age_min is None else datetime.now() - timedelta(minutes=newest_age_min)
        return SimpleNamespace(unprocessed_count=unprocessed, newest_unprocessed_at=newest)

    monkeypatch.setattr(sleep_cycle, "run", fake_run)
    monkeypatch.setattr("api.services.sleep_debt.compute", fake_compute)
    sleep_cycle.get_sleep_state().status = status
    try:
        asyncio.run(sleep_scheduler._run_after_intake_if_settled(SimpleNamespace(memory_path="/tmp/x")))
    finally:
        sleep_cycle.get_sleep_state().status = "idle"
    return calls


def test_after_import_probe_runs_only_when_settled_idle_and_nonempty(monkeypatch):
    assert _probe(monkeypatch, status="idle", unprocessed=3, newest_age_min=12) == [False]
    assert _probe(monkeypatch, status="idle", unprocessed=3, newest_age_min=4) == []
    assert _probe(monkeypatch, status="idle", unprocessed=0, newest_age_min=None) == []
    assert _probe(monkeypatch, status="running", unprocessed=3, newest_age_min=30) == []


def test_register_job_installs_the_right_trigger(monkeypatch):
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger

    sched = AsyncIOScheduler()
    s = SimpleNamespace(memory_path="/tmp/x")
    sleep_scheduler.register_job(sched, s, ScheduleConfig(mode="daily", hour=3, minute=0))
    assert isinstance(sched.get_job(sleep_scheduler.JOB_ID).trigger, CronTrigger)
    sleep_scheduler.register_job(sched, s, ScheduleConfig(mode="interval", hour=3, minute=0, interval_hours=2))
    assert isinstance(sched.get_job(sleep_scheduler.JOB_ID).trigger, IntervalTrigger)
    sleep_scheduler.register_job(sched, s, ScheduleConfig(mode="after_import", hour=3, minute=0))
    job = sched.get_job(sleep_scheduler.JOB_ID)
    assert isinstance(job.trigger, IntervalTrigger) and job.func is sleep_scheduler._run_after_intake_if_settled
    sleep_scheduler.register_job(sched, s, ScheduleConfig(mode="manual", hour=3, minute=0))
    assert sched.get_job(sleep_scheduler.JOB_ID) is None


def test_put_schedule_accepts_an_old_client_payload(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from api import config, main
    from api.services import bank_index

    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path))
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    try:
        with TestClient(main.app) as client:
            r = client.put("/sleep/schedule", json={"enabled": True, "hour": 2, "minute": 15}).json()
            assert (r["mode"], r["enabled"], r["intervalHours"]) == ("daily", True, 6)
            r = client.put("/sleep/schedule", json={"mode": "after_import", "hour": 2, "minute": 15}).json()
            assert r["enabled"] is True
            assert client.get("/sleep/schedule").json()["mode"] == "after_import"
    finally:
        config.get_settings.cache_clear()
