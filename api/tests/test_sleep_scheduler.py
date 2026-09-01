"""G74(a) Task 7 fix round 1, H1 — the two `sleep_cycle.run` call sites mark
their trigger source correctly. Spec §7's "user-triggered only" scope (and
`Copy.sleepEngineExplainer`'s literal "never on the nightly schedule" promise)
are only true if `POST /sleep/trigger` and the cron callback disagree on
`user_triggered` — this is the wiring test proving they do.
"""
from __future__ import annotations

import asyncio

from api.config import Settings
from api.services import sleep_cycle, sleep_scheduler


def test_the_scheduled_cron_path_marks_the_cycle_not_user_triggered(monkeypatch):
    calls = []

    async def fake_run(settings, cycle_id, *, user_triggered=True):
        calls.append(user_triggered)

    monkeypatch.setattr(sleep_cycle, "run", fake_run)
    state = sleep_cycle.get_sleep_state()
    state.status = "idle"

    asyncio.run(sleep_scheduler._run_if_idle(Settings()))

    assert calls == [False]


def test_the_scheduled_cron_path_skips_when_a_cycle_is_already_running(monkeypatch):
    calls = []

    async def fake_run(settings, cycle_id, *, user_triggered=True):
        calls.append(user_triggered)

    monkeypatch.setattr(sleep_cycle, "run", fake_run)
    state = sleep_cycle.get_sleep_state()
    state.status = "running"
    try:
        asyncio.run(sleep_scheduler._run_if_idle(Settings()))
    finally:
        state.status = "idle"

    assert calls == []  # never called `run` at all — no trigger source to mislabel


def test_the_manual_trigger_endpoint_marks_the_cycle_user_triggered(monkeypatch):
    from fastapi.testclient import TestClient

    from api import main

    calls = []

    async def fake_run(settings, cycle_id, *, user_triggered=True):
        calls.append(user_triggered)

    # `api/routers/sleep.py` did `from ... import run` — that binds a
    # SEPARATE name in the router module's own namespace, so patching
    # `sleep_cycle.run` (as above) would not intercept this call; the
    # router's own reference has to be patched instead.
    monkeypatch.setattr("api.routers.sleep.run", fake_run)
    sleep_cycle.get_sleep_state().status = "idle"

    client = TestClient(main.app)
    resp = client.post("/sleep/trigger")

    assert resp.status_code == 200
    assert calls == [True]
