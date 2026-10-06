"""Continue after a plan reset (TODO ruling 15 — a narrow amendment to ruling 4; Sleep page v5, B7).

An opt-in switch, off by default. A run the person started may continue itself once, after its own
plan window resets. It never crosses a weekly reset, never arms from a scheduled run, never changes
engine, and is bounded (twice, 36 hours, a vendor-given reset time)."""
from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from drain_harness import episode_ids, install, seed_bank, settings, waiting

from api import main
from api.config import get_settings
from api.services import (
    agent_engine, sleep_autocontinue as ac, sleep_cycle, sleep_paused, sleep_run_prefs,
)
from api.services.connections import registry as registry_module

NOW = int(time.time())
RESET = NOW + 2 * 3600


class FakeScheduler:
    def __init__(self):
        self.jobs = {}

    def add_job(self, func, trigger, id=None, args=None, replace_existing=False, misfire_grace_time=None, **kw):
        self.jobs[id] = SimpleNamespace(func=func, trigger=trigger, args=args, misfire=misfire_grace_time)

    def remove_job(self, id):
        if id not in self.jobs:
            raise KeyError(id)
        self.jobs.pop(id)


@pytest.fixture(autouse=True)
def _state():
    s = sleep_cycle.get_sleep_state()
    s.status, s.drain, s.drain_run, s.cancel_requested = "idle", None, False, False
    registry_module.reset_registry()
    sched = FakeScheduler()
    ac.bind(sched)
    yield sched
    ac.bind(None)
    s.status, s.drain, s.drain_run, s.cancel_requested = "idle", None, False, False
    registry_module.reset_registry()
    main.app.dependency_overrides.clear()


def _switch(on=True):
    sleep_run_prefs.write(registry_module.get_registry(settings(None)), continue_after_reset=on)


def _pause_five_hour(kind="five_hour", reset=None, batch=2):
    async def hook(batch_no, episodes):
        if batch_no == batch:
            agent_engine.trip_breaker("Your plan's 5-hour window is full.", resets_at=reset or RESET, kind=kind)
            return [e["id"] for e in episodes]
    return hook


def _leg(memory, rig, hook, cid="sleep_ac", user_triggered=True, **kw):
    rig.on_extract = hook
    cfg = settings(memory, sleep_max_episodes_per_cycle=3)
    asyncio.run(sleep_cycle.run(cfg, cid, user_triggered=user_triggered, drain=True, **kw))
    return cfg, sleep_cycle.get_sleep_state()


# --------------------------------------------------------------------------- #
# arming
# --------------------------------------------------------------------------- #


def test_it_is_off_by_default_and_arms_nothing(tmp_path, monkeypatch, _state):
    memory = seed_bank(tmp_path, episode_ids(9))
    rig = install(monkeypatch)
    _leg(memory, rig, _pause_five_hour())
    rec = sleep_paused.get_paused(memory)
    assert rec["reason"] == "plan_window" and rec["auto_continue"] is None
    assert _state.jobs == {}


def test_a_person_started_five_hour_pause_arms_one_job_after_the_reset(tmp_path, monkeypatch, _state):
    memory = seed_bank(tmp_path, episode_ids(9))
    rig = install(monkeypatch)
    _switch()
    _leg(memory, rig, _pause_five_hour())
    rec = sleep_paused.get_paused(memory)
    assert rec["auto_continue"] == {"armed": True, "at": RESET + 60, "left": 2, "used": 0, "blocked": None}
    job = _state.jobs[ac.job_id(memory)]
    assert job.func is ac._fire and job.args == [str(memory), "sleep_ac"]
    assert int(job.trigger.run_date.timestamp()) == RESET + 60, "the vendor's own reset time plus a minute"
    assert job.misfire >= 60, "asleep at the reset: it fires on wake while still inside the window"
    wire = sleep_paused.to_wire(rec)["auto_continue"]
    assert wire == {"armed": True, "at": RESET + 60, "left": 2, "blocked": None}


def test_a_scheduled_run_never_arms_it_even_with_the_switch_on(tmp_path, monkeypatch, _state):
    memory = seed_bank(tmp_path, episode_ids(9))
    rig = install(monkeypatch)
    _switch()
    _cfg, state = _leg(memory, rig, _pause_five_hour(), user_triggered=False)
    assert state.drain.started_by == "schedule" and state.drain.continue_after_reset is False
    assert sleep_paused.get_paused(memory)["auto_continue"] is None and _state.jobs == {}


@pytest.mark.parametrize("stop_by", ["user", "engine"])
def test_a_persons_own_pause_and_an_engine_failure_never_arm_it(tmp_path, monkeypatch, _state, stop_by):
    from api.services import engine_errors

    memory = seed_bank(tmp_path, episode_ids(9))
    rig = install(monkeypatch)
    _switch()

    async def hook(batch_no, episodes):
        if batch_no == 2 and stop_by == "user":
            sleep_cycle.request_cancel()
        if batch_no == 2 and stop_by == "engine":
            for e in episodes:
                rig.fail_exc[e["id"]] = engine_errors.EngineUnavailable("signed out")

    _leg(memory, rig, hook)
    rec = sleep_paused.get_paused(memory)
    assert rec["reason"] == stop_by and rec["auto_continue"]["armed"] is False and _state.jobs == {}


def test_a_weekly_pause_is_never_armed(tmp_path, monkeypatch, _state):
    memory = seed_bank(tmp_path, episode_ids(9))
    rig = install(monkeypatch)
    _switch()
    _leg(memory, rig, _pause_five_hour(kind="seven_day"))
    rec = sleep_paused.get_paused(memory)
    assert rec["reason"] == "plan_weekly"
    assert rec["auto_continue"] == {"armed": False, "at": None, "left": 2, "used": 0, "blocked": "weekly"}
    assert _state.jobs == {}


# --------------------------------------------------------------------------- #
# the bounds, as a table
# --------------------------------------------------------------------------- #

GOOD = {"reason": "plan_window", "limit": "five_hour", "resets_at": RESET, "paused_at_ts": NOW}


@pytest.mark.parametrize("rec,kw,expected", [
    (GOOD, {}, None),
    ({**GOOD, "reason": "reserve"}, {}, None),
    ({**GOOD, "reason": "overage", "limit": "overage"}, {}, None),
    (GOOD, {"used": 1}, None),
    (GOOD, {"used": 2}, "used_twice"),
    (GOOD, {"started_by": "schedule"}, "scheduled"),
    (GOOD, {"switch_on": False}, "off"),
    ({**GOOD, "reason": "user"}, {}, "reason"),
    ({**GOOD, "reason": "engine"}, {}, "reason"),
    ({**GOOD, "reason": "restart"}, {}, "reason"),
    ({**GOOD, "reason": "plan_weekly", "limit": "seven_day"}, {}, "weekly"),
    ({**GOOD, "reason": "reserve", "limit": "seven_day"}, {}, "weekly"),
    ({**GOOD, "limit": "unknown"}, {}, "unknown_limit"),
    ({**GOOD, "limit": None}, {}, "unknown_limit"),
    ({**GOOD, "resets_at": None}, {}, "no_reset_time"),
    ({**GOOD, "resets_at": True}, {}, "no_reset_time"),
    ({**GOOD, "resets_at": NOW + 36 * 3600}, {}, "too_far"),
    ({**GOOD, "resets_at": NOW + 35 * 3600}, {}, None),
])
def test_the_bounds(rec, kw, expected):
    args = {"started_by": "user", "switch_on": True, "used": 0, "now": NOW}
    args.update(kw)
    assert ac.blocked_reason(rec, **args) == expected


# --------------------------------------------------------------------------- #
# firing: every guard is checked again
# --------------------------------------------------------------------------- #


def _armed(tmp_path, monkeypatch, *, cid="sleep_ac"):
    memory = seed_bank(tmp_path, episode_ids(9))
    rig = install(monkeypatch)
    _switch()
    cfg, _ = _leg(memory, rig, _pause_five_hour(), cid=cid)
    return memory, rig, cfg


def _fire(memory, cfg, monkeypatch, run_id="sleep_ac"):
    calls = []

    async def fake_run(settings_, cycle_id, **kw):
        calls.append({"cycle_id": cycle_id, **kw})

    monkeypatch.setattr(sleep_cycle, "run", fake_run)
    monkeypatch.setattr("api.config.get_settings", lambda: cfg)
    asyncio.run(ac._fire(str(memory), run_id))
    return calls


def test_the_job_resumes_the_run_when_every_guard_holds(tmp_path, monkeypatch):
    memory, rig, cfg = _armed(tmp_path, monkeypatch)
    calls = _fire(memory, cfg, monkeypatch)
    assert len(calls) == 1 and calls[0]["user_triggered"] is True and calls[0]["drain"] is True
    assert calls[0]["continue_from"]["run_id"] == "sleep_ac" and calls[0]["continue_from"]["auto_used"] == 1
    assert sleep_cycle.get_sleep_state().status == "running", "the slot was reserved before the run task began"


@pytest.mark.parametrize("mutate,why", [
    (lambda rec: rec.update(paused_at_ts=int(time.time()) - 37 * 3600), "too_far"),
    (lambda rec: rec.update(auto_continue={**rec["auto_continue"], "used": 2}), "used_twice"),
    (lambda rec: rec.update(started_by="schedule"), "scheduled"),
    (lambda rec: rec.update(engine_label="claude-cli"), "engine_changed"),
    (lambda rec: rec.update(engine_model="a-different-model"), "engine_changed"),
])
def test_every_guard_is_checked_again_at_fire_time(tmp_path, monkeypatch, mutate, why):
    memory, rig, cfg = _armed(tmp_path, monkeypatch)
    rec = dict(sleep_paused.get_paused(memory))
    mutate(rec)
    sleep_paused.save(memory, rec)
    assert _fire(memory, cfg, monkeypatch) == []
    assert sleep_paused.get_paused(memory)["auto_continue"]["blocked"] == why
    assert sleep_paused.get_paused(memory)["auto_continue"]["armed"] is False, "still paused, and it says why"


def test_a_running_cycle_a_stale_job_and_a_changed_bank_start_nothing(tmp_path, monkeypatch):
    memory, rig, cfg = _armed(tmp_path, monkeypatch)
    sleep_cycle.get_sleep_state().status = "running"
    assert _fire(memory, cfg, monkeypatch) == []
    assert sleep_paused.get_paused(memory)["auto_continue"]["blocked"] == "busy"
    sleep_cycle.get_sleep_state().status = "idle"
    assert _fire(memory, cfg, monkeypatch, run_id="some_older_run") == [], "a job for a run that is gone"
    other = SimpleNamespace(memory_path=tmp_path / "elsewhere")
    assert _fire(memory, other, monkeypatch) == []
    assert sleep_paused.get_paused(memory)["auto_continue"]["blocked"] == "bank_changed"


def test_turning_the_switch_off_after_the_pause_withdraws_it(tmp_path, monkeypatch):
    memory, rig, cfg = _armed(tmp_path, monkeypatch)
    _switch(False)
    assert _fire(memory, cfg, monkeypatch) == []
    assert sleep_paused.get_paused(memory)["auto_continue"]["blocked"] == "off"


def test_ending_the_run_or_continuing_by_hand_disarms_the_job(tmp_path, monkeypatch, _state):
    memory, rig, cfg = _armed(tmp_path, monkeypatch)
    assert ac.job_id(memory) in _state.jobs
    main.app.dependency_overrides[get_settings] = lambda: cfg
    assert TestClient(main.app).post("/sleep/run/end").json()["status"] == "ended"
    assert ac.job_id(memory) not in _state.jobs
    assert _fire(memory, cfg, monkeypatch) == [], "nothing left to continue"


def test_the_job_is_per_bank_and_end_elsewhere_leaves_it(tmp_path, monkeypatch, _state):
    """Final review: the promise lives in one bank's sidecar, so the job is that bank's. A
    trigger or an End in another bank — even an End with no paused run — never drops it."""
    memory, rig, cfg = _armed(tmp_path, monkeypatch)
    other = seed_bank(tmp_path / "other", episode_ids(2))
    assert ac.job_id(memory) != ac.job_id(other)
    main.app.dependency_overrides[get_settings] = lambda: settings(other)
    assert TestClient(main.app).post("/sleep/run/end").json()["status"] == "none"
    ac.disarm(other)
    assert ac.job_id(memory) in _state.jobs, "bank A's armed continue is untouched"


def test_activating_a_bank_re_arms_its_paused_run(tmp_path, monkeypatch, _state):
    """Final review: boot re-arms only the bank active then; activating another bank later runs
    its migrations, which re-arm its own armed pause."""
    from api.services import bank_migrations

    memory, rig, cfg = _armed(tmp_path, monkeypatch)
    fresh = FakeScheduler()
    ac.bind(fresh)   # a new process that booted into some other bank
    bank_migrations.run_bank_migrations(memory)
    assert ac.job_id(memory) in fresh.jobs


def test_an_armed_pause_survives_a_restart(tmp_path, monkeypatch, _state):
    memory, rig, cfg = _armed(tmp_path, monkeypatch)
    fresh = FakeScheduler()
    ac.bind(fresh)   # a new process: no jobs
    assert ac.rearm_after_restart(memory) is True
    assert int(fresh.jobs[ac.job_id(memory)].trigger.run_date.timestamp()) == RESET + 60, "from the sidecar, not memory"
    # and if the pause has aged past the window meanwhile, it re-arms nothing and says why
    rec = dict(sleep_paused.get_paused(memory))
    rec["paused_at_ts"] = int(time.time()) - 40 * 3600
    sleep_paused.save(memory, rec)
    fresh2 = FakeScheduler()
    ac.bind(fresh2)
    assert ac.rearm_after_restart(memory) is False and fresh2.jobs == {}
    assert sleep_paused.get_paused(memory)["auto_continue"]["blocked"] == "too_far"


def test_two_automatic_continues_and_then_it_stops_asking(tmp_path, monkeypatch, _state):
    """End to end through the real loop: pause, fire, pause, fire, pause — the third is not armed."""
    memory, rig, cfg = _armed(tmp_path, monkeypatch)
    monkeypatch.setattr("api.config.get_settings", lambda: cfg)
    states = [sleep_paused.get_paused(memory)["auto_continue"]]
    for n in (1, 2):
        rig.on_extract = _pause_five_hour(batch=len(rig.extract_batches) + 1)   # each resumed leg trips again at once
        asyncio.run(ac._fire(str(memory), "sleep_ac"))
        rec = sleep_paused.get_paused(memory)
        assert rec is not None and rec["run_id"] == "sleep_ac", "the same run, resumed"
        states.append(rec["auto_continue"])
        sleep_cycle.get_sleep_state().status = "idle"
    assert [(s["armed"], s["left"], s["used"]) for s in states] == [(True, 2, 0), (True, 1, 1), (False, 0, 2)]
    assert states[2]["blocked"] == "used_twice"
    assert waiting(memory) == episode_ids(9)[3:], "the person's own Continue is still there"


def test_the_count_survives_a_restart_and_a_manual_continue(tmp_path, monkeypatch, _state):
    """Review: ruling 15's 'at most twice' is per run. Two automatic continues, then a restart,
    then the person's own Continue, then a plan pause: the third automatic one is not armed."""
    memory, rig, cfg = _armed(tmp_path, monkeypatch)
    monkeypatch.setattr("api.config.get_settings", lambda: cfg)
    for _ in (1, 2):
        rig.on_extract = _pause_five_hour(batch=len(rig.extract_batches) + 1)
        asyncio.run(ac._fire(str(memory), "sleep_ac"))
        sleep_cycle.get_sleep_state().status = "idle"
    rec = sleep_paused.get_paused(memory)
    assert rec["auto_used"] == 2

    # A restart mid-run: the running-phase record carries the count, and so does the restart pause.
    running = dict(rec, phase="running", auto_continue=None)
    sleep_paused.save(memory, running)
    assert sleep_paused.recover_after_restart(memory) == "paused"
    restarted = sleep_paused.get_paused(memory)
    assert restarted["reason"] == "restart" and restarted["auto_used"] == 2

    # The person's own Continue, which pauses on the plan again.
    rig.on_extract = _pause_five_hour(batch=len(rig.extract_batches) + 1)
    asyncio.run(sleep_cycle.run(cfg, "sleep_manual", user_triggered=True, drain=True, continue_from=restarted))
    final = sleep_paused.get_paused(memory)
    assert final["reason"] == "plan_window" and final["auto_used"] == 2
    assert final["auto_continue"]["armed"] is False and final["auto_continue"]["blocked"] == "used_twice"


def test_a_consolidate_during_the_engine_check_wins_and_the_job_starts_nothing(tmp_path, monkeypatch):
    """Review: the fire-time engine check awaits (it may probe for seconds). A person pressing
    Consolidate meanwhile holds the slot; the job then gives up instead of starting a second run."""
    from api.services import engine_select

    memory, rig, cfg = _armed(tmp_path, monkeypatch)
    real = engine_select.resolve_settings

    async def slow_resolve(settings_, user_triggered=True):
        out = await real(settings_, user_triggered=user_triggered)
        sleep_cycle.reserve_cycle("sleep_person", drain=True)   # the person's trigger lands here
        return out

    monkeypatch.setattr(engine_select, "resolve_settings", slow_resolve)
    assert _fire(memory, cfg, monkeypatch) == []
    s = sleep_cycle.get_sleep_state()
    assert s.cycle_id == "sleep_person", "the person's run keeps its slot"


# --------------------------------------------------------------------------- #
# the rail
# --------------------------------------------------------------------------- #


def test_only_the_continue_route_and_this_module_may_pass_continue_from():
    """TODO ruling 15 is a narrow amendment to ruling 4. A third caller — the scheduler above all —
    would quietly widen it, so a new one fails here and must be argued in the ruling first."""
    root = Path(__file__).resolve().parents[1]
    hits = set()
    for path in root.rglob("*.py"):
        rel = path.relative_to(root)
        if rel.parts[0] == "tests" or any(part.startswith(".") or part in {"node_modules", "__pycache__"}
                                           for part in rel.parts):
            continue
        if re.search(r"continue_from\s*=", path.read_text(encoding="utf-8")):
            hits.add(str(rel))
    assert hits == {"routers/sleep.py", "services/sleep_autocontinue.py", "services/sleep_cycle.py"}, hits
    sched = (root / "services" / "sleep_scheduler.py").read_text()
    assert "continue_from" not in sched, "the scheduler never continues a run"
