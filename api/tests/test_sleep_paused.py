"""A paused run (Sleep page v5, B5, critic H1/H3/H4): Pause, Continue, End this run, restart.

Paused is a fact about a run, not a state of Sleep: ``status`` stays idle and nothing is held.
The record is a sidecar outside the bank; ids, counts and enums only."""
from __future__ import annotations

import asyncio
import stat

import pytest
from fastapi.testclient import TestClient

from drain_harness import episode_ids, install, is_processed, seed_bank, settings, waiting

from api import main
from api.config import get_settings
from api.services import (
    agent_engine, engine_errors, git_service, sleep_cycle, sleep_drain, sleep_local, sleep_paused, sleep_parked,
    sleep_scheduler, sync_service, telemetry,
)

SENTENCE = "Your Claude plan hit its 5-hour limit — Sleep paused. Try again after 14:00."
RESET = 1790000000


@pytest.fixture(autouse=True)
def _idle_state():
    s = sleep_cycle.get_sleep_state()
    s.status, s.drain, s.drain_run, s.cancel_requested = "idle", None, False, False
    yield
    s.status, s.drain, s.drain_run, s.cancel_requested = "idle", None, False, False
    main.app.dependency_overrides.clear()


def _run(memory, cap=3, cid="sleep_pz", **kw):
    cfg = settings(memory, sleep_max_episodes_per_cycle=cap)
    asyncio.run(sleep_cycle.run(cfg, cid, user_triggered=kw.pop("user_triggered", True), drain=True, **kw))
    return cfg, sleep_cycle.get_sleep_state()


def _pause_by(kind):
    """A hook that stops the run in batch 2 the way ``kind`` does."""
    async def hook(batch_no, episodes):
        if batch_no != 2:
            return None
        if kind == "user":
            sleep_cycle.request_cancel()
            return None
        if kind == "engine":
            return [e["id"] for e in episodes]   # with the failure hook telling why (see rig.fail_exc below)
        agent_engine.trip_breaker(SENTENCE, resets_at=RESET, kind=kind)
        return [e["id"] for e in episodes]
    return hook


@pytest.mark.parametrize("stop_by,reason,limit", [
    ("user", "user", None),
    ("five_hour", "plan_window", "five_hour"),
    ("seven_day", "plan_weekly", "seven_day"),
    ("overage", "overage", "overage"),
    ("unknown", "plan_window", "unknown"),
    ("engine", "engine", None),
])
def test_a_paused_record_is_written_for_each_stop(tmp_path, monkeypatch, stop_by, reason, limit):
    ids = episode_ids(9)
    memory = seed_bank(tmp_path, ids)
    rig = install(monkeypatch)
    rig.on_extract = _pause_by(stop_by)
    if stop_by == "engine":
        rig.fail_exc = {}   # batch 2 fails wholesale below
        async def engine_gone(batch_no, episodes):
            if batch_no == 2:
                for e in episodes:
                    rig.fail_exc[e["id"]] = engine_errors.EngineUnavailable("Claude Code is signed out")
        rig.on_extract = engine_gone
    _cfg, state = _run(memory)

    rec = sleep_paused.get_paused(memory)
    assert rec is not None and rec["phase"] == "paused" and rec["reason"] == reason
    assert rec["run_id"] == "sleep_pz" and rec["frozen"] == 9 and rec["filed"] == 3 and rec["committed_batches"] == 1
    assert rec["limit"] == limit
    if reason.startswith("plan") or reason == "overage":
        assert rec["sentence"] == SENTENCE and rec["resets_at"] == RESET, "the vendor's own words and reset time"
    assert rec["can_continue"] is True
    assert waiting(memory) == ids[3:], "the queue is untouched"
    assert state.status == "idle" and state.drain_run is False, "paused is not a state of Sleep"
    assert sleep_cycle.is_writing() is False, "nothing is held: the app and an agent carry on"


def test_a_moved_bank_and_an_unexpected_error_leave_no_paused_record(tmp_path, monkeypatch):
    memory = seed_bank(tmp_path, episode_ids(9))
    rig = install(monkeypatch)

    async def boom(batch_no, episodes):
        if batch_no == 2:
            raise RuntimeError("something unexpected")

    rig.on_extract = boom
    _cfg, state = _run(memory)
    assert state.drain.stop.reason == "error"
    assert sleep_paused.get_paused(memory) is None and not sleep_local.bank_dir(memory, create=False).joinpath("run.json").exists()


def test_the_status_route_serves_the_paused_block_and_idle_status(tmp_path, monkeypatch):
    ids = episode_ids(9)
    memory = seed_bank(tmp_path, ids)
    rig = install(monkeypatch)
    rig.on_extract = _pause_by("five_hour")
    cfg, _ = _run(memory)
    main.app.dependency_overrides[get_settings] = lambda: cfg
    body = TestClient(main.app).get("/sleep/status").json()
    assert body["status"] == "idle" and body["writing"] is False
    p = body["paused"]
    assert (p["runId"], p["reason"], p["filed"], p["frozen"], p["canContinue"]) == ("sleep_pz", "plan_window", 3, 9, True)
    assert p["sentence"] == SENTENCE and p["resetsAt"] == RESET and p["limit"] == "five_hour"
    assert p["autoContinue"] is None, "the opt-in switch is off by default"
    assert "frozenIds" not in p and "frozen_ids" not in p


def test_continue_carries_the_counters_and_the_run_id_and_keeps_batch_numbering_unique(tmp_path, monkeypatch):
    ids = episode_ids(9)
    memory = seed_bank(tmp_path, ids)
    rig = install(monkeypatch)
    events = []
    monkeypatch.setattr(telemetry, "record", lambda ev: events.append(ev))
    rig.on_extract = _pause_by("user")
    _run(memory, cid="sleep_leg1")
    rec = sleep_paused.get_paused(memory)
    assert rec["committed_batches"] == 1 and waiting(memory) == ids[3:]

    rig.on_extract = None
    rig.extract_batches.clear()
    _cfg, state = _run(memory, cid="sleep_leg2", continue_from=rec)
    ds = state.drain
    assert ds.drain_id == "sleep_leg1", "the same run: Past nights groups both sides of the pause"
    assert ds.resumed and ds.frozen == 9 and ds.filed == 9 and ds.finished and ds.stop is None
    assert rig.extract_batches == [ids[3:6], ids[6:9]], "only what was waiting is read again"
    assert sleep_paused.load(memory) is None, "a finished run leaves no record"

    runs = [e for e in events if e.kind == "sleep_run"]
    keys = [(r.refs["drain_id"], r.refs["batch"]) for r in runs]
    assert keys == [("sleep_leg1", 1), ("sleep_leg1", 2), ("sleep_leg1", 3)] and len(set(keys)) == 3
    assert [r.refs["cycle_id"] for r in runs] == ["sleep_leg1_b001", "sleep_leg2_b002", "sleep_leg2_b003"], \
        "a fresh cycle prefix per leg: the ledger never merges two batches"
    subjects = [s for s in _log(memory) if s.startswith("Sleep cycle")]
    assert any("(batch 2 of 3)" in s for s in subjects) and any("(batch 3 of 3)" in s for s in subjects)


def _log(memory):
    from drain_harness import git

    return git(memory, "log", "--format=%s", "--reverse").splitlines()


def test_a_continue_counts_a_pause_as_paused_time_not_reading_time(tmp_path, monkeypatch):
    memory = seed_bank(tmp_path, episode_ids(9))
    rig = install(monkeypatch)
    rig.on_extract = _pause_by("user")
    _run(memory, cid="sleep_t1")
    rec = dict(sleep_paused.get_paused(memory))
    rec["paused_at_ts"] = int(rec["paused_at_ts"]) - 3600   # it has been paused for an hour
    rec["elapsed_ms"] = 120_000
    rig.on_extract = None
    ds = _run(memory, cid="sleep_t2", continue_from=rec)[1].drain
    assert 3_599_000 <= ds.paused_ms <= 3_700_000
    assert 120_000 <= ds.elapsed_ms() < 180_000, "reading time carries on from where it stopped, the hour excluded"


def test_continue_without_a_record_is_a_fresh_run(tmp_path, monkeypatch):
    ids = episode_ids(4)
    memory = seed_bank(tmp_path, ids)
    install(monkeypatch)
    calls = []

    async def fake_run(settings_, cycle_id, **kw):
        calls.append(kw)

    monkeypatch.setattr("api.routers.sleep.run", fake_run)
    main.app.dependency_overrides[get_settings] = lambda: settings(memory, sleep_max_episodes_per_cycle=3)
    client = TestClient(main.app)
    assert client.post("/sleep/trigger", json={"continue": True}).json()["status"] == "started"
    assert calls == [{"user_triggered": True, "drain": True}], "no paused run: nothing to continue from"


def test_only_a_continue_body_continues_and_a_bare_trigger_clears_the_pause(tmp_path, monkeypatch):
    ids = episode_ids(9)
    memory = seed_bank(tmp_path, ids)
    rig = install(monkeypatch)
    rig.on_extract = _pause_by("user")
    cfg, _ = _run(memory)
    rec = sleep_paused.get_paused(memory)
    calls = []

    async def fake_run(settings_, cycle_id, **kw):
        calls.append(kw)

    monkeypatch.setattr("api.routers.sleep.run", fake_run)
    main.app.dependency_overrides[get_settings] = lambda: cfg
    client = TestClient(main.app)
    assert client.post("/sleep/trigger", json={"continue": True}).json()["message"] == "Sleep run resumed"
    assert calls[-1]["continue_from"]["run_id"] == rec["run_id"]
    sleep_cycle.get_sleep_state().status = "idle"
    client.post("/sleep/trigger")   # the documented curl: no body
    assert "continue_from" not in calls[-1], "a no-body trigger is a fresh run"

    # and the real thing clears the stale record the moment it starts (README's curl stays a fresh Consolidate)
    sleep_cycle.get_sleep_state().status = "idle"
    rig.on_extract = None
    _run(memory, cid="sleep_fresh")
    assert sleep_paused.load(memory) is None and waiting(memory) == []


def test_end_this_run_deletes_the_record_and_leaves_the_queue_alone(tmp_path, monkeypatch):
    ids = episode_ids(9)
    memory = seed_bank(tmp_path, ids)
    rig = install(monkeypatch)
    rig.on_extract = _pause_by("user")
    cfg, _ = _run(memory)
    main.app.dependency_overrides[get_settings] = lambda: cfg
    client = TestClient(main.app)

    sleep_cycle.get_sleep_state().status = "running"
    assert client.post("/sleep/run/end").status_code == 409, "a run that is reading is paused first"
    sleep_cycle.get_sleep_state().status = "idle"
    assert client.post("/sleep/run/end").json()["status"] == "ended"
    assert sleep_paused.get_paused(memory) is None and waiting(memory) == ids[3:]
    assert client.get("/sleep/status").json()["paused"] is None
    assert client.post("/sleep/run/end").json()["status"] == "none", "idempotent"


def test_a_restart_turns_a_running_sidecar_into_a_restart_pause(tmp_path, monkeypatch):
    ids = episode_ids(6)
    memory = seed_bank(tmp_path, ids)
    install(monkeypatch)
    ds = sleep_drain.DrainState(drain_id="sleep_dead", frozen_ids=ids, batch_size=3, batch=1, filed=3,
                                committed_batches=1, calls=40)
    sleep_paused.save(memory, sleep_paused.build(ds, phase="running", engine_label="claude-cli"))
    assert sleep_paused.get_paused(memory) is None, "a run that is still reading is not paused"

    assert sleep_paused.recover_after_restart(memory) == "paused"
    rec = sleep_paused.get_paused(memory)
    assert rec["reason"] == "restart" and rec["filed"] == 3 and rec["calls"] == 40 and rec["run_id"] == "sleep_dead"
    assert rec["sentence"] is None and rec["resets_at"] is None and rec["auto_continue"] is None
    assert sleep_paused.recover_after_restart(memory) is None, "an already paused record is left alone"


def test_a_restart_with_everything_filed_deletes_the_sidecar(tmp_path):
    ids = episode_ids(3)
    memory = seed_bank(tmp_path, ids)
    from api.services import markdown_parser

    for i in ids:
        p = memory / "episodes" / f"{i}.md"
        parsed = markdown_parser.parse(p)
        markdown_parser.write(p, {**parsed.frontmatter, "processed": True}, parsed.body)
    ds = sleep_drain.DrainState(drain_id="sleep_done", frozen_ids=ids, batch_size=3)
    sleep_paused.save(memory, sleep_paused.build(ds, phase="running"))
    assert sleep_paused.recover_after_restart(memory) == "deleted" and sleep_paused.load(memory) is None


def test_a_bank_activation_and_boot_run_the_recovery_without_touching_the_bank(tmp_path):
    from api.services.bank_migrations import run_bank_migrations

    ids = episode_ids(4)
    memory = seed_bank(tmp_path, ids)
    ds = sleep_drain.DrainState(drain_id="sleep_boot", frozen_ids=ids, batch_size=3, filed=1)
    sleep_paused.save(memory, sleep_paused.build(ds, phase="running"))
    head = sync_service.git_head(memory)
    summary = run_bank_migrations(memory)
    assert sleep_paused.get_paused(memory)["reason"] == "restart"
    assert "paused" not in summary and sync_service.git_head(memory) == head, "the bank is untouched"


def test_the_sidecar_is_outside_the_bank_0600_and_holds_ids_only(tmp_path, monkeypatch):
    ids = episode_ids(9)
    memory = seed_bank(tmp_path, ids)
    rig = install(monkeypatch)
    rig.on_extract = _pause_by("user")
    _run(memory)
    path = sleep_local.bank_dir(memory, create=False) / "run.json"
    assert path.is_file() and memory not in path.parents
    assert stat.S_IMODE(path.stat().st_mode) == 0o600 and stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    text = path.read_text()
    assert "Episode" not in text and "project X" not in text, "no text from a conversation"
    from drain_harness import git

    assert git(memory, "status", "--porcelain").strip() == "", "and nothing in the bank changed"


def test_paused_is_scoped_to_the_active_bank(tmp_path, monkeypatch):
    a = seed_bank(tmp_path / "a", episode_ids(9))
    b = seed_bank(tmp_path / "b", episode_ids(3))
    rig = install(monkeypatch)
    rig.on_extract = _pause_by("user")
    cfg_a, _ = _run(a)
    assert sleep_paused.get_paused(a) is not None
    main.app.dependency_overrides[get_settings] = lambda: settings(b, sleep_max_episodes_per_cycle=3)
    body = TestClient(main.app).get("/sleep/status").json()
    assert body["paused"] is None, "bank A's pause is not bank B's"
    assert body["drain"] is None, "and neither is A's lingering drain"
    main.app.dependency_overrides[get_settings] = lambda: cfg_a
    assert TestClient(main.app).get("/sleep/status").json()["paused"]["runId"] == "sleep_pz"


def test_the_sync_version_moves_on_pause_end_and_restart(tmp_path, monkeypatch):
    ids = episode_ids(9)
    memory = seed_bank(tmp_path, ids)
    rig = install(monkeypatch)
    before = sync_service.components(memory)["sleep"]
    rig.on_extract = _pause_by("user")
    _run(memory)
    paused = sync_service.components(memory)["sleep"]
    assert paused != before and "paused:sleep_pz" in paused, "a pause moves the component the app maps onto its status"
    sleep_paused.clear(memory)
    assert sync_service.components(memory)["sleep"] == before, "End this run moves it back"
    ds = sleep_drain.DrainState(drain_id="sleep_r", frozen_ids=ids, batch_size=3)
    sleep_paused.save(memory, sleep_paused.build(ds, phase="running"))
    assert sync_service.components(memory)["sleep"] == before, "a sidecar that is still reading is not a pause"
    sleep_paused.recover_after_restart(memory)
    assert "paused:sleep_r" in sync_service.components(memory)["sleep"]


def test_a_paused_run_holds_nothing_but_a_scheduled_drain_holds_the_bank_like_any_run(tmp_path, monkeypatch):
    """Paused: idle, no bank guard, no write hold. A scheduled drain that is reading pins its bank for
    hours (disclosed, R-3) — the same 409 a person's run has, because it is the same loop."""
    from fastapi import HTTPException

    from api.routers import banks

    memory = seed_bank(tmp_path, episode_ids(9))
    rig = install(monkeypatch)
    rig.on_extract = _pause_by("user")
    _run(memory)
    banks._refuse_switch_during_drain()          # paused and idle: switching is fine
    assert sleep_cycle.is_writing() is False

    seen = {}

    async def while_reading(batch_no, episodes):
        seen["refused"] = False
        try:
            banks._refuse_switch_during_drain()
        except HTTPException as e:
            seen["refused"] = "Cicada is reading" in e.detail

    rig.on_extract = while_reading
    sleep_paused.clear(memory)
    _run(memory, user_triggered=False, cid="sleep_sched")
    assert seen["refused"] is True


# --------------------------------------------------------------------------- #
# H1: the scheduler and a paused run
# --------------------------------------------------------------------------- #


def test_the_scheduler_skips_while_a_run_is_paused_on_both_entry_points(tmp_path, monkeypatch):
    from datetime import datetime, timedelta
    from types import SimpleNamespace

    memory = seed_bank(tmp_path, episode_ids(9))
    rig = install(monkeypatch)
    rig.on_extract = _pause_by("user")
    _run(memory)
    calls = []

    async def fake_run(settings_, cycle_id, **kw):
        calls.append(kw)

    async def fake_debt(memory_path, settings_=None):
        return SimpleNamespace(unprocessed_count=6, readable_count=6, parked_count=0,
                               newest_unprocessed_at=datetime.now() - timedelta(hours=2))

    monkeypatch.setattr(sleep_cycle, "run", fake_run)
    monkeypatch.setattr("api.services.sleep_debt.compute", fake_debt)
    cfg = SimpleNamespace(memory_path=memory)
    sleep_scheduler._paused_upkeep_at.clear()
    asyncio.run(sleep_scheduler._run_if_idle(cfg))
    asyncio.run(sleep_scheduler._run_after_intake_if_settled(cfg))
    asyncio.run(sleep_scheduler._run_after_intake_if_settled(cfg))
    assert calls == [{"user_triggered": False, "tail_only": True}] * 2, (
        "a Pause is undone by nobody but the person: upkeep only, and the probe's at most once a day")
    sleep_paused.clear(memory)
    asyncio.run(sleep_scheduler._run_if_idle(cfg))
    assert len(calls) == 3 and calls[-1] == {"user_triggered": False, "drain": True}


def test_claim_expiry_and_follow_ups_still_run_on_the_cron_while_a_run_is_paused(tmp_path, monkeypatch):
    """Review (must): a pause never switches off the engine-free tail. The cron reads nothing
    over it and leaves the record and the queue as they were."""
    from types import SimpleNamespace

    ids = episode_ids(9)
    memory = seed_bank(tmp_path, ids)
    rig = install(monkeypatch)
    rig.on_extract = _pause_by("user")
    _cfg, state = _run(memory)
    rec = sleep_paused.get_paused(memory)
    assert rec is not None
    paused_drain = state.drain
    left = waiting(memory)
    rig.tail.clear()
    rig.extract_batches.clear()

    cfg = settings(memory, sleep_max_episodes_per_cycle=3)
    asyncio.run(sleep_scheduler._run_if_idle(cfg))

    assert "expiry" in rig.tail and "followups" in rig.tail and "state" in rig.tail
    assert rig.extract_batches == [], "nothing is read over a pause"
    assert waiting(memory) == left
    after = sleep_paused.get_paused(memory)
    assert after is not None and after["run_id"] == rec["run_id"], "the pause is the person's to end"
    s = sleep_cycle.get_sleep_state()
    assert s.status == "idle" and s.drain is paused_drain and not s.tail_only


def test_the_after_import_probe_ignores_a_queue_of_only_parked_conversations(tmp_path, monkeypatch):
    ids = episode_ids(3)
    memory = seed_bank(tmp_path, ids)
    for i in ids:
        sleep_parked.park(memory, i, "empty_answer", 2)
    calls = []

    async def fake_run(settings_, cycle_id, **kw):
        calls.append(kw)

    monkeypatch.setattr(sleep_cycle, "run", fake_run)
    from datetime import datetime, timedelta

    from api.services import sleep_debt

    debt = asyncio.run(sleep_debt.compute(memory, settings(memory)))
    assert (debt.unprocessed_count, debt.parked_count, debt.readable_count) == (3, 3, 0), "waiting, but not readable"
    # Old episodes so the settle window has passed: only the readable count keeps it quiet.
    from types import SimpleNamespace

    asyncio.run(sleep_scheduler._run_after_intake_if_settled(SimpleNamespace(memory_path=memory)))
    assert calls == [], "no empty freeze every five minutes"
    sleep_parked.unpark(memory)
    asyncio.run(sleep_scheduler._run_after_intake_if_settled(SimpleNamespace(memory_path=memory)))
    assert len(calls) == 1


def test_a_scheduled_engine_stop_leaves_a_pause_that_the_next_probe_does_not_restart(tmp_path, monkeypatch):
    ids = episode_ids(6)
    memory = seed_bank(tmp_path, ids)
    rig = install(monkeypatch)

    async def gone(batch_no, episodes):
        for e in episodes:
            rig.fail_exc[e["id"]] = engine_errors.EngineUnavailable("no key for the scheduled engine")

    rig.on_extract = gone
    _cfg, state = _run(memory, user_triggered=False)
    assert state.drain.started_by == "schedule" and state.drain.stop.reason == "engine"
    rec = sleep_paused.get_paused(memory)
    assert rec["reason"] == "engine" and rec["started_by"] == "schedule" and rec["auto_continue"] is None

    from types import SimpleNamespace

    calls = []

    async def fake_run(settings_, cycle_id, **kw):
        calls.append(kw)

    monkeypatch.setattr(sleep_cycle, "run", fake_run)
    asyncio.run(sleep_scheduler._run_if_idle(SimpleNamespace(memory_path=memory)))
    assert calls == [{"user_triggered": False, "tail_only": True}], (
        "it waits for the person (upkeep only): Continue runs on the engine they chose for a run they start")
    assert waiting(memory) == ids


# --------------------------------------------------------------------------- #
# H4: the limit kind
# --------------------------------------------------------------------------- #


def test_the_breaker_records_which_limit_tripped_it():
    with agent_engine.use_scope("sleep:kind_a"):
        assert agent_engine.breaker_kind() is None
        agent_engine.trip_breaker("five-hour", resets_at=RESET, kind="five_hour")
        assert agent_engine.breaker_kind() == "five_hour"
    assert agent_engine.breaker_kind(scope="sleep:kind_a") is None, "purged with the scope"
    with agent_engine.use_scope("sleep:kind_b"):
        agent_engine.trip_breaker("odd")   # no kind given, or a value outside the set
        assert agent_engine.breaker_kind() == "unknown"
    with agent_engine.use_scope("sleep:kind_c"):
        agent_engine.trip_breaker("odd", kind="fortnight")
        assert agent_engine.breaker_kind() == "unknown"


def test_a_limit_kind_comes_from_the_window_or_the_error_never_from_a_sentence():
    assert agent_engine.limit_kind_of(None, "five_hour") == "five_hour"
    assert agent_engine.limit_kind_of(None, "seven_day_opus") == "seven_day"
    assert agent_engine.limit_kind_of(engine_errors.EngineOverage("x")) == "overage"
    assert agent_engine.limit_kind_of(engine_errors.EngineThrottled("Your weekly limit")) == "unknown"
    err = agent_engine._stop_error(agent_engine.plan_limits.PlanStop("rejected", "s", "seven_day", RESET))
    assert isinstance(err, engine_errors.EngineExhausted) and agent_engine.limit_kind_of(err) == "seven_day"


def test_a_drain_stop_carries_the_limit_kind(tmp_path, monkeypatch):
    memory = seed_bank(tmp_path, episode_ids(9))
    rig = install(monkeypatch)
    rig.on_extract = _pause_by("seven_day")
    _cfg, state = _run(memory)
    stop = state.drain.stop
    assert (stop.reason, stop.limit, stop.resets_at) == ("plan_limit", "seven_day", RESET)
    assert stop.to_wire()["limit"] == "seven_day"
    err = engine_errors.EngineExhausted("used up", resets_at=RESET)
    err.limit_type = "seven_day"
    assert sleep_drain.classify(err).limit == "seven_day"
    assert sleep_drain.classify(engine_errors.EngineThrottled("x")).limit == "unknown"


# --------------------------------------------------------------------------- #
# Final review: a scheduled run's pause nobody chose is the schedule's to replace;
# Past nights never keeps a stale 'paused' or 'running' run.
# --------------------------------------------------------------------------- #


def _schedule_calls(monkeypatch):
    calls = []

    async def fake_run(settings_, cycle_id, **kw):
        calls.append(kw)

    monkeypatch.setattr(sleep_cycle, "run", fake_run)
    return calls


@pytest.mark.parametrize("reason,started_by,age_h,replaced", [
    ("restart", "schedule", 0, True),
    ("engine", "schedule", 7, True),
    ("engine", "schedule", 1, False),     # a scheduled engine that is still away: not every five minutes
    ("user", "schedule", 48, False),      # a person's Pause is theirs
    ("plan_window", "schedule", 48, False),
    ("restart", "user", 48, False),       # a run a person started is theirs
])
def test_the_schedule_replaces_only_a_scheduled_pause_nobody_chose(tmp_path, monkeypatch, reason, started_by,
                                                                   age_h, replaced):
    import time
    from types import SimpleNamespace

    from api.services import sleep_runs

    ids = episode_ids(4)
    memory = seed_bank(tmp_path, ids)
    ds = sleep_drain.DrainState(drain_id="sleep_old", frozen_ids=ids, batch_size=3, started_by=started_by)
    sleep_runs.record_leg(memory, ds, state="paused", reason=reason)
    rec = sleep_paused.build(ds, phase="paused", stop=None)
    rec.update({"reason": reason, "paused_at_ts": int(time.time() - age_h * 3600)})
    sleep_paused.save(memory, rec)
    calls = _schedule_calls(monkeypatch)
    asyncio.run(sleep_scheduler._run_if_idle(SimpleNamespace(memory_path=memory)))
    if replaced:
        assert calls == [{"user_triggered": False, "drain": True}] and sleep_paused.load(memory) is None
        assert sleep_runs.get(memory, "sleep_old")["state"] == "ended", "the replaced run is ended in Past nights"
    else:
        assert calls == [{"user_triggered": False, "tail_only": True}]
        assert sleep_paused.get_paused(memory)["run_id"] == "sleep_old"


def test_a_scheduled_run_on_an_env_pinned_plan_reads_one_batch(tmp_path, monkeypatch):
    """Ruling 16's one exception: `CICADA_LLM_MODE=agent|codex` hands a scheduled run a plan, so
    that run reads one batch, never a whole queue unattended on the plan."""
    from api.config import Settings
    from api.services import engine_select

    pinned = Settings(memory_path=tmp_path, llm_mode="agent")
    assert engine_select.scheduled_plan_pin(pinned) is True
    assert engine_select.scheduled_plan_pin(Settings(memory_path=tmp_path, llm_mode="byok")) is False
    assert engine_select.scheduled_plan_pin(Settings(memory_path=tmp_path)) is False, "a prefs choice is not a pin"
    memory = seed_bank(tmp_path / "b", episode_ids(2))
    calls = _schedule_calls(monkeypatch)
    asyncio.run(sleep_scheduler._run_if_idle(Settings(memory_path=memory, llm_mode="codex")))
    assert calls[-1] == {"user_triggered": False, "drain": False}


def test_a_fresh_consolidate_ends_the_replaced_run_in_past_nights(tmp_path, monkeypatch):
    from api.services import sleep_runs

    ids = episode_ids(9)
    memory = seed_bank(tmp_path, ids)
    rig = install(monkeypatch)
    rig.on_extract = _pause_by("user")
    _run(memory)
    assert sleep_runs.get(memory, "sleep_pz")["state"] == "paused"
    rig.on_extract = None
    _run(memory, cid="sleep_fresh")
    old = sleep_runs.get(memory, "sleep_pz")
    assert old["state"] == "ended" and old["pauses"][-1]["to"] is not None, "never 'paused' forever"
    assert sleep_runs.get(memory, "sleep_fresh")["state"] == "finished"


def test_a_restart_pause_is_recorded_in_past_nights_too(tmp_path):
    from api.services import sleep_runs

    ids = episode_ids(6)
    memory = seed_bank(tmp_path, ids)
    ds = sleep_drain.DrainState(drain_id="sleep_dead", frozen_ids=ids, batch_size=3, filed=3)
    sleep_runs.record_leg(memory, ds, state="running")
    sleep_paused.save(memory, sleep_paused.build(ds, phase="running"))
    assert sleep_paused.recover_after_restart(memory) == "paused"
    run = sleep_runs.get(memory, "sleep_dead")
    assert run["state"] == "paused" and len(run["pauses"]) == 1
    assert run["pauses"][0]["reason"] == "restart" and run["pauses"][0]["to"] is None
