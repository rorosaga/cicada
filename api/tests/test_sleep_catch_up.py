"""A scheduled run the Mac slept or was off through runs once, soon after it is back (owner 2026-10-19).

`sleep_catch_up.probe` is the job; the clock is injected through `_now`, the run through `sleep_cycle.run`. Every
scheduled path stays `user_triggered=False` (ruling 4/4b)."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from api.models.schemas import ScheduleConfig
from api.services import sleep_catch_up, sleep_cycle, sleep_runs, sleep_scheduler

DAILY = ScheduleConfig(mode="daily", hour=3, minute=0)


def _local(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi).astimezone()


class Clock:
    def __init__(self, at):
        self.at = at

    def __call__(self):
        return self.at

    def advance(self, **kw):
        self.at = self.at + timedelta(**kw)


@pytest.fixture
def rig(tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    sleep_catch_up.reset_for_tests()
    clock = Clock(_local(2026, 10, 19, 8, 12))
    monkeypatch.setattr(sleep_catch_up, "_now", clock)
    calls: list[dict] = []

    async def fake_run(settings, cycle_id, **kw):
        calls.append(kw)

    readable = {"n": 4}

    async def fake_compute(memory_path, settings=None):
        return SimpleNamespace(unprocessed_count=readable["n"] + 1, readable_count=readable["n"])

    monkeypatch.setattr(sleep_cycle, "run", fake_run)
    monkeypatch.setattr("api.services.sleep_debt.compute", fake_compute)
    monkeypatch.setattr(sleep_scheduler, "_paused_for_the_person", lambda mp: False)
    sleep_cycle.get_sleep_state().status = "idle"
    yield SimpleNamespace(memory=memory, settings=SimpleNamespace(memory_path=memory), clock=clock, calls=calls,
                          readable=readable)
    sleep_cycle.get_sleep_state().status = "idle"
    sleep_catch_up.reset_for_tests()


def _seed(rig, *, since, handled=None, last_run=None, cfg=DAILY):
    sleep_catch_up.note_schedule(rig.memory, cfg, now=since)
    if handled:
        sleep_catch_up.note_handled(rig.memory, now=handled)
    if last_run:
        sleep_catch_up.note_run_started(rig.memory, now=last_run)


def _probe(rig, cfg=DAILY):
    asyncio.run(sleep_catch_up.probe(rig.settings, cfg))


def _settle_and_probe(rig, cfg=DAILY):
    """The first probe notices; the next one, five minutes on, runs."""
    _probe(rig, cfg)
    rig.clock.advance(minutes=sleep_catch_up.PROBE_MINUTES)
    _probe(rig, cfg)


def test_asleep_at_the_due_time_the_late_wake_runs_it_once_after_a_settle_and_unattended(rig):
    # Last night's 03:00 fired (handled); tonight's came while the lid was shut; the Mac wakes at 08:12.
    _seed(rig, since=_local(2026, 10, 1, 12), handled=_local(2026, 10, 18, 3))
    _probe(rig)
    assert rig.calls == [], "noticed, not run on the moment of waking"
    rig.clock.advance(minutes=sleep_catch_up.PROBE_MINUTES)
    _probe(rig)
    assert len(rig.calls) == 1
    kw = rig.calls[0]
    assert kw["user_triggered"] is False, "a catch-up is a scheduled run (ruling 4/4b)"
    assert kw.get("tail_only") is not True
    assert datetime.fromisoformat(kw["catch_up_for"]) == _local(2026, 10, 19, 3)
    rig.clock.advance(minutes=sleep_catch_up.PROBE_MINUTES)
    _probe(rig)
    assert len(rig.calls) == 1, "once"


def test_off_at_the_due_time_a_start_after_it_catches_up_from_the_recorded_runs(rig):
    # The first start after an upgrade: no stamp file yet; the schedule was saved weeks ago and the last run
    # (runs.json, the record that predates the stamps) began yesterday at 03:00.
    import os

    sleep_scheduler.save_schedule(rig.memory, DAILY)
    weeks_ago = _local(2026, 9, 20, 12).timestamp()
    os.utime(rig.memory / sleep_scheduler.SCHEDULE_FILE, (weeks_ago, weeks_ago))
    from api.services import sleep_local

    sleep_local.write_json(sleep_runs._path(rig.memory, create=True), {
        "runs": {"sleep_a": {"id": "sleep_a", "started_by": "schedule",
                             "started_at": _local(2026, 10, 18, 3).isoformat()}},
        "order": ["sleep_a"]})
    _settle_and_probe(rig)
    assert len(rig.calls) == 1 and rig.calls[0]["user_triggered"] is False
    assert datetime.fromisoformat(rig.calls[0]["catch_up_for"]) == _local(2026, 10, 19, 3)


def test_many_nights_missed_run_once_naming_the_latest(rig):
    _seed(rig, since=_local(2026, 10, 1, 12), handled=_local(2026, 10, 14, 3))
    _settle_and_probe(rig)
    assert len(rig.calls) == 1
    assert datetime.fromisoformat(rig.calls[0]["catch_up_for"]) == _local(2026, 10, 19, 3)
    # Another wake later the same day: nothing more is owed until tomorrow's 03:00.
    rig.clock.advance(hours=3)
    _settle_and_probe(rig)
    assert len(rig.calls) == 1


def test_interval_mode_missed_steps_run_once():
    cfg = ScheduleConfig(mode="interval", hour=3, minute=0, interval_hours=6)
    anchor = _local(2026, 10, 18, 2)
    now = _local(2026, 10, 19, 8, 12)
    due = sleep_catch_up.due_before(cfg, now, anchor)
    assert due == anchor + timedelta(hours=30), "one time comes back — the latest step, never a backlog"
    assert sleep_catch_up.due_before(cfg, anchor + timedelta(hours=5), anchor) is None


def test_a_run_since_the_due_time_owes_nothing(rig):
    _seed(rig, since=_local(2026, 10, 1, 12), handled=_local(2026, 10, 18, 3), last_run=_local(2026, 10, 19, 7))
    _settle_and_probe(rig)
    assert rig.calls == []


def test_a_schedule_set_after_the_time_does_not_catch_up_a_time_before_it(rig):
    _seed(rig, since=_local(2026, 10, 19, 7))     # "daily at 03:00", saved at 07:00 today
    _settle_and_probe(rig)
    assert rig.calls == []


def test_a_paused_run_gets_upkeep_only(rig, monkeypatch):
    monkeypatch.setattr(sleep_scheduler, "_paused_for_the_person", lambda mp: True)
    _seed(rig, since=_local(2026, 10, 1, 12), handled=_local(2026, 10, 18, 3))
    _settle_and_probe(rig)
    assert len(rig.calls) == 1
    assert rig.calls[0]["tail_only"] is True and rig.calls[0]["user_triggered"] is False
    assert "catch_up_for" not in rig.calls[0]
    rig.clock.advance(minutes=sleep_catch_up.PROBE_MINUTES * 3)
    _settle_and_probe(rig)
    assert len(rig.calls) == 1, "the upkeep took the missed time's turn"


def test_nothing_readable_runs_nothing_and_a_later_capture_does_not_turn_it_into_a_run(rig):
    rig.readable["n"] = 0          # only parked or index-only conversations wait
    _seed(rig, since=_local(2026, 10, 1, 12), handled=_local(2026, 10, 18, 3))
    _settle_and_probe(rig)
    assert rig.calls == []
    rig.readable["n"] = 2          # something arrives at 10:00: it waits for tomorrow's 03:00, as on any day
    rig.clock.advance(hours=2)
    _settle_and_probe(rig)
    assert rig.calls == []


def test_a_running_cycle_is_never_stacked_on(rig):
    _seed(rig, since=_local(2026, 10, 1, 12), handled=_local(2026, 10, 18, 3))
    sleep_cycle.get_sleep_state().status = "running"
    _settle_and_probe(rig)
    assert rig.calls == []
    sleep_cycle.get_sleep_state().status = "idle"
    rig.clock.advance(minutes=sleep_catch_up.PROBE_MINUTES)
    _probe(rig)
    assert len(rig.calls) == 1, "still owed once the cycle is done (it started before the due time)"


def test_a_catch_up_that_fails_is_tried_once_not_on_every_wake(rig, monkeypatch):
    # A plan engine with "Scheduled runs may use my plan" off fails the same way the 03:00 run does — once.
    async def failing_run(settings, cycle_id, **kw):
        rig.calls.append(kw)
        sleep_cycle.get_sleep_state().error = "the scheduled engine refused"

    monkeypatch.setattr(sleep_cycle, "run", failing_run)
    _seed(rig, since=_local(2026, 10, 1, 12), handled=_local(2026, 10, 18, 3))
    _settle_and_probe(rig)
    for _ in range(3):             # three more wakes the same day
        rig.clock.advance(hours=1)
        _settle_and_probe(rig)
    assert len(rig.calls) == 1
    sleep_cycle.get_sleep_state().error = None


def test_a_wake_between_noticing_and_running_restarts_the_settle(rig):
    _seed(rig, since=_local(2026, 10, 1, 12), handled=_local(2026, 10, 18, 3))
    _probe(rig)                                   # noticed
    rig.clock.advance(hours=1)                    # the lid closed again for an hour
    _probe(rig)
    assert rig.calls == [], "a long gap is a wake: settle again"
    rig.clock.advance(minutes=sleep_catch_up.PROBE_MINUTES)
    _probe(rig)
    assert len(rig.calls) == 1


def test_the_on_time_fire_stamps_its_turn_so_the_probe_never_repeats_it(rig, monkeypatch):
    async def fake_run(settings, cycle_id, *, user_triggered=True, drain=False):
        rig.calls.append({"user_triggered": user_triggered, "cron": True})

    monkeypatch.setattr(sleep_cycle, "run", fake_run)
    _seed(rig, since=_local(2026, 10, 1, 12), handled=_local(2026, 10, 18, 3))
    rig.clock.at = _local(2026, 10, 19, 3)       # the cron fires on time
    asyncio.run(sleep_scheduler._run_if_idle(rig.settings))
    rig.clock.advance(minutes=30)
    _settle_and_probe(rig)
    assert rig.calls == [{"user_triggered": False, "cron": True}]


def test_register_job_adds_the_catch_up_probe_only_beside_daily_and_interval(tmp_path):
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger

    sched = AsyncIOScheduler()
    s = SimpleNamespace(memory_path=tmp_path / "memory")
    sleep_scheduler.register_job(sched, s, DAILY)
    cron = sched.get_job(sleep_scheduler.JOB_ID)
    assert isinstance(cron.trigger, CronTrigger)
    assert cron.misfire_grace_time == sleep_catch_up.ON_TIME_GRACE_S and cron.coalesce is True
    probe = sched.get_job(sleep_catch_up.JOB_ID)
    assert probe is not None and probe.func is sleep_catch_up.probe and probe.coalesce is True
    sleep_scheduler.register_job(sched, s, ScheduleConfig(mode="interval", hour=3, minute=0, interval_hours=4))
    assert sched.get_job(sleep_catch_up.JOB_ID) is not None
    for mode in ("after_import", "manual"):
        sleep_scheduler.register_job(sched, s, ScheduleConfig(mode=mode, hour=3, minute=0))
        assert sched.get_job(sleep_catch_up.JOB_ID) is None, f"{mode} is unchanged: no catch-up"


def test_a_changed_schedule_starts_its_own_since(tmp_path):
    memory = tmp_path / "memory"
    memory.mkdir()
    sleep_catch_up.note_schedule(memory, DAILY, now=_local(2026, 10, 1, 12))
    sleep_catch_up.note_schedule(memory, DAILY, now=_local(2026, 10, 5, 12))      # re-saved, same schedule
    assert datetime.fromisoformat(sleep_catch_up.load(memory)["since"]) == _local(2026, 10, 1, 12)
    sleep_catch_up.note_schedule(memory, ScheduleConfig(mode="daily", hour=4, minute=30), now=_local(2026, 10, 6, 9))
    assert datetime.fromisoformat(sleep_catch_up.load(memory)["since"]) == _local(2026, 10, 6, 9)


def test_the_catch_up_run_says_so_in_its_summary(tmp_path, monkeypatch):
    """A real drain over a real git bank: the run summary and its history ref carry the missed time."""
    from drain_harness import episode_ids, install, seed_bank, settings

    from api.services.connections import registry as registry_module

    registry_module.reset_registry()
    state = sleep_cycle.get_sleep_state()
    state.status, state.drain, state.drain_run, state.cancel_requested = "idle", None, False, False
    memory = seed_bank(tmp_path, episode_ids(3))
    install(monkeypatch)
    sleep_catch_up.reset_for_tests()
    clock = Clock(_local(2026, 10, 19, 8, 12))
    monkeypatch.setattr(sleep_catch_up, "_now", clock)
    cfg = settings(memory, sleep_max_episodes_per_cycle=2)
    sleep_catch_up.note_schedule(memory, DAILY, now=_local(2026, 10, 1, 12))
    sleep_catch_up.note_handled(memory, now=_local(2026, 10, 18, 3))
    try:
        asyncio.run(sleep_catch_up.probe(cfg, DAILY))
        clock.advance(minutes=sleep_catch_up.PROBE_MINUTES)
        asyncio.run(sleep_catch_up.probe(cfg, DAILY))
        ds = sleep_cycle.get_sleep_state().drain
        assert ds is not None and ds.started_by == "schedule" and ds.finished
        summary = sleep_runs.get(memory, ds.drain_id)
        assert datetime.fromisoformat(summary["catch_up_for"]) == _local(2026, 10, 19, 3)
        assert sleep_runs.to_run_ref(summary)["catch_up_for"] == summary["catch_up_for"]
    finally:
        state.status, state.drain, state.drain_run, state.cancel_requested = "idle", None, False, False
        registry_module.reset_registry()
        sleep_catch_up.reset_for_tests()
