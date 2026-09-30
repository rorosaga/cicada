"""The app's Sleep page v5 fixtures ARE the server's wire (the `projects-demo.json` pattern).

The Swift decode tests for the paused states, the run detail, the reading options and the queue
rows read these files, so a wire drift fails on one side or the other: this test drives the real
backend (LLM boundaries faked, everything else real) and fails on any byte of difference. Clock
fields are pinned; ids are synthetic; no conversation title or text is ever in a fixture.

After a deliberate wire change: `CICADA_WRITE_APP_FIXTURE=1 python -m pytest <this file>`."""
from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from drain_harness import episode_ids, install, seed_bank, settings

from test_sleep_run_detail import _paused_run, _state as _run_detail_state  # noqa: F401  (fixture reused)

from api import main
from api.config import get_settings
from api.services import agent_engine, engine_errors, sleep_cycle, sleep_drain, sleep_paused, sleep_parked, sleep_run_prefs
from api.services import sleep_autocontinue
from api.services.connections import registry as registry_module

FIXTURES = Path(__file__).resolve().parents[2] / "app" / "CicadaApp" / "Tests" / "fixtures"
DEBT = {"unprocessedCount": 0, "oldestUnprocessedAgeHours": None, "hoursSinceLastCycle": 0.5, "hasRunBefore": True,
        "volumePct": 0, "agePct": 0, "restedPct": 100, "parkedCount": 0, "readableCount": 0}
PIN_TS = "2026-09-30T10:20:00+00:00"
PIN_RESET = 1_790_003_600   # what the fixture shows; the run itself uses a reset two hours from now (never in the past)


def _write_or_compare(name: str, wire) -> None:
    path = FIXTURES / name
    text = json.dumps(wire, indent=2, sort_keys=True) + "\n"
    if os.environ.get("CICADA_WRITE_APP_FIXTURE"):
        path.write_text(text)
    assert json.loads(path.read_text()) == json.loads(text), name


def _live_reset() -> int:
    return int(time.time()) + 7200


def _pin_times(node, reset: int):
    """The reset is real (it must be ahead for the guards); the fixture shows a constant."""
    if isinstance(node, dict):
        return {k: _pin_times(v, reset) for k, v in node.items()}
    if isinstance(node, list):
        return [_pin_times(v, reset) for v in node]
    if node == reset:
        return PIN_RESET
    if node == reset + 60:
        return PIN_RESET + 60
    return node


def _pin_status(body: dict, reset: int | None = None) -> dict:
    body["debt"] = dict(DEBT)
    body["startedAt"] = "2026-09-30T10:15:00"
    body["engineDetail"] = None
    if body.get("drain"):
        body["drain"]["elapsedMs"] = 0
    if body.get("paused"):
        body["paused"]["pausedAt"] = PIN_TS
    return _pin_times(body, reset) if reset else body


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    s = sleep_cycle.get_sleep_state()
    s.status, s.drain, s.drain_run, s.cancel_requested = "idle", None, False, False
    registry_module.reset_registry()
    sched = type("S", (), {"jobs": {}, "add_job": lambda self, func, trigger, id=None, **kw: self.jobs.update({id: 1}),
                           "remove_job": lambda self, id: self.jobs.pop(id, None)})()
    sleep_autocontinue.bind(sched)
    yield
    sleep_autocontinue.bind(None)
    s.status, s.drain, s.drain_run, s.cancel_requested = "idle", None, False, False
    registry_module.reset_registry()
    main.app.dependency_overrides.clear()


def _status(cfg, reset: int | None = None) -> dict:
    main.app.dependency_overrides[get_settings] = lambda: cfg
    return _pin_status(TestClient(main.app).get("/sleep/status").json(), reset)


def _scenario(tmp_path, monkeypatch, kind: str) -> dict:
    ids = episode_ids(9)
    memory = seed_bank(tmp_path, ids)
    reset = _live_reset()
    rig = install(monkeypatch, engine_label="claude-cli" if kind in ("reserve", "plan_window") else None)
    if kind == "plan_window":
        sleep_run_prefs.write(registry_module.get_registry(settings(None)), continue_after_reset=True)
    if kind == "reserve":
        sleep_run_prefs.write(registry_module.get_registry(settings(None)), reserve_pct=10)

    async def hook(batch_no, episodes):
        if batch_no != 2:
            return None
        if kind == "user":
            sleep_cycle.request_cancel()
        elif kind == "plan_window":
            agent_engine.trip_breaker("Your plan's 5-hour window is full.", resets_at=reset, kind="five_hour")
            return [e["id"] for e in episodes]
        elif kind == "engine":
            for e in episodes:
                rig.fail_exc[e["id"]] = engine_errors.EngineUnavailable("The engine you chose is signed out.")
        return None

    rig.on_extract = hook
    if kind == "reserve":
        def report(ep):
            if ep["id"] == ids[3]:
                from api.services.agent_stream import RateLimitSignal

                sleep_cycle.get_sleep_state().drain.guard.observe_signals(
                    [RateLimitSignal(status="allowed", limit_type="five_hour", utilization=0.93, resets_at=reset)])

        rig.after_read = report
    cfg = settings(memory, sleep_max_episodes_per_cycle=3)
    asyncio.run(sleep_cycle.run(cfg, "sleep_2026-09-30_101500", user_triggered=True, drain=True))
    if kind == "restart":
        rec = sleep_paused.get_paused(memory) or {}
        assert not rec, "a cancel was not requested: the run finished"
    return _status(cfg, reset)


def _restart_body(tmp_path, monkeypatch) -> dict:
    ids = episode_ids(9)
    memory = seed_bank(tmp_path, ids)
    install(monkeypatch)
    ds = sleep_drain.DrainState(drain_id="sleep_2026-09-30_101500", frozen_ids=ids, batch_size=3, batch=1, batches=3,
                                filed=3, committed_batches=1, calls=40)
    ds.started_mono = time.monotonic()
    sleep_paused.save(memory, sleep_paused.build(ds, phase="running", engine_label="claude-cli"))
    sleep_paused.recover_after_restart(memory)
    return _status(settings(memory, sleep_max_episodes_per_cycle=3))


def _wire(tmp_path, monkeypatch) -> dict:
    out = {}
    for kind in ("user", "plan_window", "reserve", "engine"):
        sub = tmp_path / kind
        sub.mkdir()
        out[kind] = _scenario(sub, monkeypatch, kind)
        sleep_paused.clear(Path(sub / "memory"))
    sub = tmp_path / "restart"
    sub.mkdir()
    out["restart"] = _restart_body(sub, monkeypatch)
    return out


def test_the_paused_status_fixture_is_the_servers_wire(tmp_path, monkeypatch):
    wire = _wire(tmp_path, monkeypatch)
    _write_or_compare("sleep-status-paused.json", wire)


def test_the_paused_scenarios_say_what_the_app_will_read(tmp_path, monkeypatch):
    wire = _wire(tmp_path, monkeypatch)
    for kind, body in wire.items():
        assert body["status"] == "idle" and body["writing"] is False, kind
        assert body["paused"]["canContinue"] is True and body["paused"]["frozen"] == 9, kind
    assert wire["user"]["paused"]["reason"] == "user" and wire["user"]["paused"]["filed"] == 3
    p = wire["plan_window"]["paused"]
    assert (p["reason"], p["limit"], p["resetsAt"]) == ("plan_window", "five_hour", PIN_RESET)
    assert p["autoContinue"] == {"armed": True, "at": PIN_RESET + 60, "left": 2, "blocked": None}
    r = wire["reserve"]["paused"]
    assert (r["reason"], r["sentence"], r["limit"]) == ("reserve", "Paused to leave room in your plan.", "five_hour")
    assert wire["engine"]["paused"]["reason"] == "engine"
    assert wire["restart"]["paused"]["reason"] == "restart" and wire["restart"]["paused"]["sentence"] is None
    assert wire["reserve"]["drain"]["reserve"]["pct"] == 10


def test_the_run_detail_fixture_is_the_servers_wire(tmp_path, monkeypatch):
    memory, cfg, ids = _paused_run(tmp_path, monkeypatch)
    main.app.dependency_overrides[get_settings] = lambda: cfg
    body = TestClient(main.app).get("/sleep/runs/sleep_leg1").json()
    body["startedAt"], body["finishedAt"] = "2026-09-30T10:14:00+00:00", "2026-09-30T17:05:00+00:00"
    body["readMs"], body["pausedMs"] = 8_040_000, 16_620_000
    for b in body["batches"]:
        b["ts"], b["tookMs"], b["commit"] = "2026-09-30T10:30:00.000Z", 660_000, "0" * 40
    for p in body["pauses"]:
        p["startedAt"], p["endedAt"] = "2026-09-30T11:04:00+00:00", "2026-09-30T15:41:00+00:00"
    body["pages"]["first"] = [f"page-{i}" for i in range(len(body["pages"]["first"]))]
    _write_or_compare("sleep-run-detail.json", body)


def test_the_reading_options_fixture_is_the_servers_wire(tmp_path):
    memory = seed_bank(tmp_path, episode_ids(3))
    main.app.dependency_overrides[get_settings] = lambda: settings(memory, sleep_max_episodes_per_cycle=25)
    client = TestClient(main.app)
    defaults = client.get("/sleep/run-options").json()
    custom = client.put("/sleep/run-options", json={"batchSize": 10, "continueAfterReset": True, "reservePct": 20}).json()
    assert defaults["continueAfterReset"] is False and defaults["reservePct"] is None
    _write_or_compare("sleep-run-options.json", {"defaults": defaults, "custom": custom})


def test_the_queue_fixture_is_the_servers_wire(tmp_path, monkeypatch):
    ids = episode_ids(6)
    memory = seed_bank(tmp_path, ids)
    sleep_parked.park(memory, ids[5], "timed_out", 2)
    ds = sleep_drain.DrainState(drain_id="sleep_q", frozen_ids=ids[:5], batch_size=25, batch=1, batches=1)
    ds.origin_of = {i: "claude-code" for i in ids}
    ds.filed_ids, ds.batch_counted = {ids[0]}, False
    ds.live = sleep_drain.BatchLive(index=1, total=4, ids=ids[1:5])
    ds.live.started |= {ids[1], ids[2], ids[3]}
    ds.live.read.add(ids[1])
    ds.live.failed[ids[2]] = "empty_answer"
    ds.attempts[ids[2]] = 1
    ds.memory_path = memory
    sleep_cycle.get_sleep_state().drain = ds
    main.app.dependency_overrides[get_settings] = lambda: settings(memory, sleep_max_episodes_per_cycle=25)
    body = TestClient(main.app).get("/sleep/queue").json()
    for item in body["items"]:
        item["timestamp"] = "2026-09-01T10:00:00"
    _write_or_compare("sleep-queue.json", body)
