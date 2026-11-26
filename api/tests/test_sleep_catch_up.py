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
    sleep_scheduler.save_schedule(rig.memory, cfg)       # the active bank's own schedule — what the probe reads
    sleep_catch_up.note_schedule(rig.memory, cfg, now=since)
    if handled:
        sleep_catch_up.note_handled(rig.memory, now=handled)
    if last_run:
        sleep_catch_up.note_run_started(rig.memory, now=last_run)


def _probe(rig):
    asyncio.run(sleep_catch_up.probe(rig.settings))


def _settle_and_probe(rig):
    """The first probe notices; the next one, five minutes on, runs."""
    _probe(rig)
    rig.clock.advance(minutes=sleep_catch_up.PROBE_MINUTES)
    _probe(rig)


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


def test_nothing_readable_runs_the_engine_free_tail_only_and_a_later_capture_does_not_turn_it_into_a_run(rig):
    rig.readable["n"] = 0          # only parked or index-only conversations wait
    _seed(rig, since=_local(2026, 10, 1, 12), handled=_local(2026, 10, 18, 3))
    _settle_and_probe(rig)
    # G245: the polls and the upkeep run (the tail), reading nothing, starting no engine, recording no run
    assert len(rig.calls) == 1
    assert rig.calls[0]["tail_only"] is True and rig.calls[0]["engine_free"] is True
    assert rig.calls[0]["user_triggered"] is False and "drain" not in rig.calls[0]
    assert "catch_up_for" not in rig.calls[0]
    rig.readable["n"] = 2          # something arrives at 10:00: it waits for tomorrow's 03:00, as on any day
    rig.clock.advance(hours=2)
    _settle_and_probe(rig)
    assert len(rig.calls) == 1


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
    sleep_scheduler.save_schedule(memory, DAILY)
    sleep_catch_up.note_schedule(memory, DAILY, now=_local(2026, 10, 1, 12))
    sleep_catch_up.note_handled(memory, now=_local(2026, 10, 18, 3))
    try:
        asyncio.run(sleep_catch_up.probe(cfg))
        clock.advance(minutes=sleep_catch_up.PROBE_MINUTES)
        asyncio.run(sleep_catch_up.probe(cfg))
        ds = sleep_cycle.get_sleep_state().drain
        assert ds is not None and ds.started_by == "schedule" and ds.finished
        summary = sleep_runs.get(memory, ds.drain_id)
        assert datetime.fromisoformat(summary["catch_up_for"]) == _local(2026, 10, 19, 3)
        assert sleep_runs.to_run_ref(summary)["catch_up_for"] == summary["catch_up_for"]
    finally:
        state.status, state.drain, state.drain_run, state.cancel_requested = "idle", None, False, False
        registry_module.reset_registry()
        sleep_catch_up.reset_for_tests()


def test_the_probe_reads_the_active_banks_own_schedule_never_the_registered_one(rig, tmp_path):
    """Review B1: jobs are registered with the start bank's schedule and a bank switch does not re-register them.
    A bank set to `manual` (or `after_import`) is never caught up on another bank's 03:00, however much waits."""
    import os

    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    sched = AsyncIOScheduler()
    sleep_scheduler.register_job(sched, SimpleNamespace(memory_path=tmp_path / "bank-a"), DAILY)   # bank A: daily
    job = sched.get_job(sleep_catch_up.JOB_ID)
    assert list(job.args) == [job.args[0]], "the probe is handed no schedule of its own"
    for mode in ("manual", "after_import"):
        sleep_catch_up.reset_for_tests()
        sleep_scheduler.save_schedule(rig.memory, ScheduleConfig(mode=mode, hour=3, minute=0))
        two_days_ago = _local(2026, 10, 17, 12).timestamp()
        os.utime(rig.memory / sleep_scheduler.SCHEDULE_FILE, (two_days_ago, two_days_ago))
        _settle_and_probe(rig)
        _settle_and_probe(rig)
        assert rig.calls == [], f"bank B is {mode}: nothing scheduled to catch up"


def test_a_switched_to_daily_bank_catches_up_its_own_time(rig):
    # Registered with 03:00 elsewhere; this bank's own schedule is 05:30.
    own = ScheduleConfig(mode="daily", hour=5, minute=30)
    _seed(rig, since=_local(2026, 10, 1, 12), handled=_local(2026, 10, 18, 6), cfg=own)
    _settle_and_probe(rig)
    assert len(rig.calls) == 1
    assert datetime.fromisoformat(rig.calls[0]["catch_up_for"]) == _local(2026, 10, 19, 5, 30)


def test_a_demo_bank_is_never_caught_up(rig):
    from api.services import demo_guard

    demo_guard.write_manifest(rig.memory)
    _seed(rig, since=_local(2026, 10, 1, 12), handled=_local(2026, 10, 18, 3))
    _settle_and_probe(rig)
    assert rig.calls == []


def test_a_run_that_starts_while_the_queue_is_counted_is_not_stacked_on(rig, monkeypatch):
    real_compute = __import__("api.services.sleep_debt", fromlist=["compute"]).compute

    async def compute_then_a_run_starts(memory_path, settings=None):
        out = await real_compute(memory_path, settings)
        sleep_cycle.get_sleep_state().status = "running"     # the person pressed Consolidate meanwhile
        return out

    monkeypatch.setattr("api.services.sleep_debt.compute", compute_then_a_run_starts)
    _seed(rig, since=_local(2026, 10, 1, 12), handled=_local(2026, 10, 18, 3))
    _settle_and_probe(rig)
    assert rig.calls == []


# --- 2026-11-25: a scheduled run refused before it read is tried again the same night -----------------------------
#
# The night this was written for: the machine was slow, the 03:00 job fired 2 min 36 s late, the catch-up took it, and a
# write still held the bank for the whole wait (`write_admission.WAIT_MAX_S`). Nothing was read, spent or recorded — and
# both stamps said the night was taken, so nothing tried again.


class _Night:
    """A real git bank with unprocessed conversations, the LLM boundaries faked (`drain_harness`), a writer that can be
    held on the bank, and the clock the probe reads. Probes are five minutes apart, as the scheduler runs them."""

    def __init__(self, tmp_path, monkeypatch):
        from drain_harness import episode_ids, install, seed_bank, settings

        from api.services import write_admission
        from api.services.connections import registry as registry_module

        registry_module.reset_registry()
        self.state = sleep_cycle.get_sleep_state()
        self.state.status, self.state.drain, self.state.drain_run = "idle", None, False
        self.state.cancel_requested, self.state.error = False, None
        self.memory = seed_bank(tmp_path, episode_ids(3))
        self.rig = install(monkeypatch)
        monkeypatch.setattr(write_admission, "WAIT_MAX_S", 0.2)
        sleep_catch_up.reset_for_tests()
        self.clock = Clock(_local(2026, 11, 24, 3, 2))
        monkeypatch.setattr(sleep_catch_up, "_now", self.clock)
        self.cfg = settings(self.memory, sleep_max_episodes_per_cycle=3)
        sleep_scheduler.save_schedule(self.memory, DAILY)
        sleep_catch_up.note_schedule(self.memory, DAILY, now=_local(2026, 11, 1, 12))
        sleep_catch_up.note_handled(self.memory, now=_local(2026, 11, 23, 3))   # last night ran
        self.held = None

    def hold_writer(self):
        import threading

        from api.services import write_admission

        held, release = threading.Event(), threading.Event()

        def writer():
            with write_admission.shared(self.memory):
                held.set()
                release.wait(30)

        thread = threading.Thread(target=writer)
        thread.start()
        assert held.wait(10)
        self.held = (release, thread)

    def release_writer(self):
        if self.held:
            self.held[0].set()
            self.held[1].join(10)
            self.held = None

    def probe(self):
        asyncio.run(sleep_catch_up.probe(self.cfg))

    def close(self):
        from api.services.connections import registry as registry_module

        self.release_writer()
        self.state.status, self.state.drain, self.state.drain_run, self.state.error = "idle", None, False, None
        registry_module.reset_registry()
        sleep_catch_up.reset_for_tests()


@pytest.fixture
def night(tmp_path, monkeypatch):
    n = _Night(tmp_path, monkeypatch)
    # Count every attempt the probe makes, read or refused: a `run` wrapper that watches the window's answer.
    real_run = sleep_cycle.run
    attempts: list[dict] = []

    async def watched_run(settings, cycle_id, **kw):
        attempts.append({"at": n.clock.at, **kw})
        await real_run(settings, cycle_id, **kw)

    monkeypatch.setattr(sleep_cycle, "run", watched_run)
    n.attempts = attempts
    yield n
    n.close()


def _first_missed_probe_runs(n):
    """03:02 fire missed (the machine was busy): the probe notices at 03:05 and runs at 03:10 — into a held bank."""
    n.clock.at = _local(2026, 11, 24, 3, 5)
    n.probe()                                  # noticed: the settle
    n.clock.advance(minutes=sleep_catch_up.PROBE_MINUTES)
    n.probe()                                  # runs, refused at the write window


def test_a_night_whose_run_a_writer_refused_is_tried_again_and_reads(night):
    n = night
    n.hold_writer()
    _first_missed_probe_runs(n)
    assert len(n.attempts) == 1 and n.rig.extract_batches == [], "refused: nothing was read"
    assert n.state.status == "idle"
    # Today the stamps (handled_at, last_run_at) would now say the night was taken, and nothing would try again.
    n.release_writer()
    n.clock.at = _local(2026, 11, 24, 3, 12)
    n.probe()
    assert len(n.attempts) == 1, "not before the first spacing (10 minutes after the refusal)"
    for _ in range(4):
        n.clock.advance(minutes=sleep_catch_up.PROBE_MINUTES)
        n.probe()
    assert len(n.attempts) == 2, "one more try, through the same settle: one run, not a stack"
    retry = n.attempts[1]
    assert retry["user_triggered"] is False, "a retry is a scheduled run (ruling 4)"
    assert datetime.fromisoformat(retry["catch_up_for"]) == _local(2026, 11, 24, 3, 0), "naming the time it serves"
    from drain_harness import episode_ids, waiting

    assert n.rig.extract_batches == [episode_ids(3)] and waiting(n.memory) == [], "it read what waited"
    assert sleep_catch_up.refusal_notice(n.memory) is None and sleep_catch_up._refusal(n.memory) is None, \
        "a run that read ends the retries"
    for _ in range(40):                        # the rest of the night: nothing more
        n.clock.advance(minutes=sleep_catch_up.PROBE_MINUTES)
        n.probe()
    assert len(n.attempts) == 2


def test_the_tries_are_four_spaced_and_end_in_a_plain_sentence(night):
    n = night
    n.hold_writer()                            # the writer never lets go
    _first_missed_probe_runs(n)
    first_refusal = n.clock.at
    for _ in range(60):                        # five hours of probes
        n.clock.advance(minutes=sleep_catch_up.PROBE_MINUTES)
        n.probe()
    times = [a["at"] for a in n.attempts]
    assert len(times) == sleep_catch_up.MAX_TRIES == 4, "the run and three retries, then it stops"
    gaps = [b - a for a, b in zip(times, times[1:])]
    spacing = sleep_catch_up.RETRY_AFTER
    assert all(g >= s for g, s in zip(gaps, spacing)), f"each try waits out its spacing: {gaps}"
    assert times[-1] - first_refusal <= sleep_catch_up.RETRY_WINDOW, "one night"
    assert n.rig.extract_batches == [], "never read past a holder"
    notice = sleep_catch_up.refusal_notice(n.memory)
    assert notice is not None and "did not start" in notice and "still writing" in notice
    assert "tried 4 times" in notice and "next scheduled time" in notice and "start it yourself" in notice
    assert n.state.error is None, "a refused night is a notice, never the run's error"
    assert n.state.progress == notice, "the run's own progress line carries the full sentence"
    from api.routers import sleep as sleep_router

    # A restart forgets the in-memory state; the record does not.
    wire = sleep_router._remembered_refusal(n.state, SimpleNamespace(memory_path=n.memory))
    assert wire["detail"] == notice and wire["gave_up"] is True and wire["retry_at"] is None
    assert wire["tries"] == wire["max_tries"] == 4
    assert wire["text"] == "Last night's 03:00 run didn't start. It runs again at 03:00."
    assert len(wire["text"]) <= 90


def test_while_tries_remain_the_sentence_says_when_the_next_one_is(night):
    n = night
    n.hold_writer()
    _first_missed_probe_runs(n)
    notice = sleep_catch_up.refusal_notice(n.memory)
    assert "something was still writing" in notice and "read nothing" in notice
    assert f"It will try again after {(n.clock.at + sleep_catch_up.RETRY_AFTER[0]).strftime('%H:%M')} (try 2 of 4)" \
        in notice
    assert n.state.error is None, "nothing was read or broken: not an error"
    assert n.state.progress == notice
    wire = sleep_catch_up.refusal(n.memory)
    assert wire["kind"] == "scheduled_run_refused" and wire["detail"] == notice and wire["gave_up"] is False
    assert wire["text"] == (f"Last night's 03:00 run hasn't started yet. Next try after "
                            f"{(n.clock.at + sleep_catch_up.RETRY_AFTER[0]).strftime('%H:%M')}.")
    assert len(wire["text"]) <= 90 and wire["tries"] == 1 and wire["max_tries"] == 4
    assert datetime.fromisoformat(wire["retry_at"]) == n.clock.at + sleep_catch_up.RETRY_AFTER[0]


def test_a_retry_never_stacks_never_reads_over_a_pause_and_never_outlives_the_night(night, monkeypatch):
    n = night
    n.hold_writer()
    _first_missed_probe_runs(n)
    n.release_writer()
    # A cycle is running when the retry falls due: it is never stacked on.
    n.clock.at = _local(2026, 11, 24, 3, 40)
    n.state.status = "running"
    n.probe()
    n.clock.advance(minutes=5)
    n.probe()
    assert len(n.attempts) == 1
    n.state.status = "idle"
    # A paused run waits for the person: upkeep only, and nothing stays owed afterwards.
    monkeypatch.setattr(sleep_scheduler, "_paused_for_the_person", lambda mp: True)
    n.clock.advance(minutes=5)
    n.probe()
    n.clock.advance(minutes=5)
    n.probe()
    assert [a.get("tail_only") for a in n.attempts[1:]] == [True], "one upkeep run, never a read"
    assert sleep_catch_up._refusal(n.memory) is None
    monkeypatch.setattr(sleep_scheduler, "_paused_for_the_person", lambda mp: False)
    n.clock.advance(minutes=30)
    n.probe()
    n.clock.advance(minutes=5)
    n.probe()
    assert len(n.attempts) == 2 and n.rig.extract_batches == []


def test_a_refusal_past_the_night_is_not_retried(night):
    n = night
    n.hold_writer()
    _first_missed_probe_runs(n)
    n.release_writer()
    n.clock.at = n.clock.at + sleep_catch_up.RETRY_WINDOW + timedelta(minutes=1)
    assert sleep_catch_up.retry_due(n.memory, n.clock.at) is None


def test_a_persons_own_run_that_the_window_refused_is_unchanged(night):
    n = night
    n.hold_writer()
    asyncio.run(sleep_cycle.run(n.cfg, "sleep_manual_refused", user_triggered=True, drain=True))
    assert n.state.error == sleep_cycle.WINDOW_BUSY and n.state.progress == f"Paused: {sleep_cycle.WINDOW_BUSY}"
    assert sleep_catch_up._refusal(n.memory) is None, "a click is the person's: it is never retried for them"
    n.release_writer()
    n.clock.at = _local(2026, 11, 24, 9, 0)
    assert sleep_catch_up.retry_due(n.memory, n.clock.at) is None


def test_a_run_that_started_reading_and_failed_keeps_the_tried_once_rule(night, monkeypatch):
    n = night
    from drain_harness import episode_ids

    n.rig.fail_exc = {i: RuntimeError("engine away") for i in episode_ids(3)}
    n.clock.at = _local(2026, 11, 24, 3, 5)
    n.probe()
    n.clock.advance(minutes=sleep_catch_up.PROBE_MINUTES)
    n.probe()
    assert len(n.attempts) == 1 and len(n.rig.extract_batches) == 1, "it read (and spent): that was its try"
    assert sleep_catch_up._refusal(n.memory) is None
    for _ in range(40):
        n.clock.advance(minutes=sleep_catch_up.PROBE_MINUTES)
        n.probe()
    assert len(n.attempts) == 1, "not repeated on every wake"


def test_the_on_time_cron_refused_by_a_writer_is_retried_by_the_probe(night):
    n = night
    n.hold_writer()
    n.clock.at = _local(2026, 11, 24, 3, 0)
    asyncio.run(sleep_scheduler._run_if_idle(n.cfg))      # the cron fires on time into a held bank
    assert n.rig.extract_batches == [] and sleep_catch_up._refusal(n.memory) is not None
    n.release_writer()
    n.clock.at = _local(2026, 11, 24, 3, 11)
    n.probe()                                             # noticed
    n.clock.advance(minutes=sleep_catch_up.PROBE_MINUTES)
    n.probe()
    assert len(n.rig.extract_batches) == 1, "the cron's refused night is read by the probe"


def test_a_wait_the_thread_pool_never_starts_is_a_refusal_not_a_hang(tmp_path, monkeypatch):
    """Where the 22 minutes can go: the wait is bounded from the moment its thread runs, not from the call."""
    import threading

    from api.services import write_admission

    monkeypatch.setattr(write_admission, "WAIT_MAX_S", 0.05)
    monkeypatch.setattr(sleep_cycle, "WINDOW_START_SLACK_S", 0.05)
    gate = threading.Event()
    monkeypatch.setattr(write_admission, "wait_for_writers", lambda mp, **kw: gate.wait(10) or True)
    async def timed() -> tuple[bool, float]:
        t0 = datetime.now()
        answer = await sleep_cycle._open_window(tmp_path)
        return answer, (datetime.now() - t0).total_seconds()   # (asyncio.run itself then waits for the thread)

    try:
        answer, seconds = asyncio.run(timed())
        assert answer is False and seconds < 2, "bounded in wall-clock terms, answered as a refusal"
    finally:
        gate.set()
        sleep_cycle.get_sleep_state().writing = False


def test_the_notice_names_the_run_by_when_it_was_and_never_says_last_night_for_an_old_one(night):
    n = night
    n.hold_writer()
    _first_missed_probe_runs(n)
    due = _local(2026, 11, 24, 3, 0)
    cases = [
        (due + timedelta(hours=5), "Last night's 03:00 run"),
        (due + timedelta(hours=11), "Last night's 03:00 run"),
        (due + timedelta(hours=19), "Today's 03:00 run"),
        (due + timedelta(days=1, hours=5), "Yesterday's 03:00 run"),
        (due + timedelta(days=3, hours=5), "The Nov 24 03:00 run"),
    ]
    for now, lead in cases:
        wire = sleep_catch_up.refusal(n.memory, now=now)
        assert wire["text"].startswith(lead + " "), (now, wire["text"])
        assert len(wire["text"]) <= 90


def test_a_run_that_starts_or_a_cleared_record_takes_the_notice_away(night):
    n = night
    n.hold_writer()
    _first_missed_probe_runs(n)
    assert sleep_catch_up.refusal(n.memory) is not None
    sleep_catch_up.clear_refused(n.memory)
    assert sleep_catch_up.refusal(n.memory) is None and sleep_catch_up.refusal_notice(n.memory) is None
