"""The app's Sleep-drain fixture IS the server's wire (the `projects-demo.json` pattern).

Every Swift test of the Sleep page's drain (decode, the sentence tail, the stop rungs, the
strip) reads `app/CicadaApp/Tests/fixtures/sleep-status-drain.json`. This test drives four
person-started runs through the real pipeline (LLM boundaries faked, everything else real)
and fails on any byte of drift between what `GET /sleep/status` says and the file: mid-run,
finished, stopped at a plan's limit and cancelled. Clock-dependent fields (`debt`, `startedAt`
and the engine's reason) are pinned to constants — the app never joins on them here.
Synthetic ids only.

After a deliberate wire change: `CICADA_WRITE_APP_FIXTURE=1 python -m pytest <this file>`.
"""
import asyncio
import json
import os
from pathlib import Path

import pytest

from drain_harness import episode_ids, install, seed_bank, settings

from api.routers import sleep as sleep_router
from api.services import agent_engine, sleep_cycle

FIXTURE = Path(__file__).resolve().parents[2] / "app" / "CicadaApp" / "Tests" / "fixtures" / "sleep-status-drain.json"
SENTENCE = "Your Claude plan hit its 5-hour limit — Sleep paused. Try again after 14:00."
DEBT = {"unprocessedCount": 0, "oldestUnprocessedAgeHours": None, "hoursSinceLastCycle": 0.5,
        "hasRunBefore": True, "volumePct": 0, "agePct": 0, "restedPct": 100}


@pytest.fixture(autouse=True)
def _idle_state():
    s = sleep_cycle.get_sleep_state()
    s.status, s.drain, s.drain_run, s.cancel_requested = "idle", None, False, False
    yield
    s.status, s.drain, s.drain_run, s.cancel_requested = "idle", None, False, False


def _body(cfg, *, detail=None):
    body = asyncio.run(sleep_router.sleep_status(settings=cfg)).model_dump(by_alias=True)
    return _pin(body, detail)


def _pin(body, detail=None):
    body["debt"] = dict(DEBT)
    body["startedAt"] = "2026-09-29T10:15:00"
    body["engineDetail"] = detail
    if body.get("drain"):
        body["drain"]["elapsedMs"] = 0   # a measured clock: pinned, the app never joins on it here
    if body.get("paused"):
        body["paused"]["pausedAt"] = "2026-09-29T10:20:00+00:00"
    return body


async def _body_async(cfg, detail=None):
    return _pin((await sleep_router.sleep_status(settings=cfg)).model_dump(by_alias=True), detail)


def _scenario(tmp_path, monkeypatch, kind):
    ids = episode_ids(7)
    memory = seed_bank(tmp_path, ids)
    rig = install(monkeypatch, engine_label="claude-cli")
    cfg = settings(memory, sleep_max_episodes_per_cycle=3)
    cid = "sleep_2026-09-29_101500"
    grabbed = {}

    async def hook(batch_no, episodes):
        if kind == "running" and batch_no == 2:
            grabbed["body"] = await _body_async(cfg)
        if kind == "plan_limit" and batch_no == 3:
            agent_engine.trip_breaker(SENTENCE, resets_at=1790000000)
            return [e["id"] for e in episodes]
        if kind == "cancelled" and batch_no == 2:
            sleep_cycle.request_cancel()

    rig.on_extract = hook
    asyncio.run(sleep_cycle.run(cfg, cid, user_triggered=True, drain=True))
    if kind == "running":
        return grabbed["body"]
    return _body(cfg, detail=SENTENCE if kind == "plan_limit" else None)


def _wire(tmp_path, monkeypatch):
    out = {}
    for kind in ("running", "finished", "plan_limit", "cancelled"):
        sub = tmp_path / kind
        sub.mkdir()
        out[kind] = _scenario(sub, monkeypatch, kind)
    return out


def test_the_app_fixture_is_the_servers_wire(tmp_path, monkeypatch):
    wire = _wire(tmp_path, monkeypatch)
    if os.environ.get("CICADA_WRITE_APP_FIXTURE"):
        FIXTURE.write_text(json.dumps(wire, indent=2, sort_keys=True) + "\n")
    assert json.loads(FIXTURE.read_text()) == json.loads(json.dumps(wire, sort_keys=True))


def test_the_scenarios_say_what_the_app_will_read(tmp_path, monkeypatch):
    wire = _wire(tmp_path, monkeypatch)
    run = wire["running"]
    assert run["status"] == "running" and run["drain"]["batch"] == 2 and run["drain"]["filed"] == 3
    assert run["progress"].startswith("Batch 2 of 3 · Stage 1/5")
    assert wire["finished"]["drain"]["finished"] is True and wire["finished"]["drain"]["filed"] == 7
    stop = wire["plan_limit"]["drain"]["stop"]
    assert stop == {"reason": "plan_limit", "sentence": SENTENCE, "resetsAt": 1790000000, "limit": "unknown"}
    assert wire["plan_limit"]["error"] is None and wire["plan_limit"]["drain"]["filed"] == 6
    assert wire["cancelled"]["cancelled"] is True and wire["cancelled"]["drain"]["stop"]["reason"] == "cancelled"
