"""G177 — the app's write controls follow Sleep's write window, not `running`.

`GET /status` and the SSE `sleep` event carry `writing` (`sleep_cycle.is_writing`), and
the sync version's `sleep` component moves when it flips, so the app's `.status` domain
refreshes between a drain's batches instead of holding the controls disabled for hours."""
from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import bank_index, sleep_cycle, sync_service


@pytest.fixture
def client(tmp_path, monkeypatch):
    (tmp_path / "episodes").mkdir()
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path))
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    with TestClient(main.app) as c:
        yield c, tmp_path
    config.get_settings.cache_clear()


def _run(monkeypatch, *, drain: bool, writing: bool, status: str = "running"):
    state = sleep_cycle.get_sleep_state()
    monkeypatch.setattr(state, "status", status)
    monkeypatch.setattr(state, "drain_run", drain)
    monkeypatch.setattr(state, "writing", writing)
    return state


def test_status_says_writing_only_inside_the_window(client, monkeypatch):
    c, _ = client
    assert c.get("/status").json()["sleep"]["writing"] is False, "idle holds nothing"
    _run(monkeypatch, drain=False, writing=False)
    assert c.get("/status").json()["sleep"]["writing"] is True, "a plain cycle holds the bank for its whole run"
    _run(monkeypatch, drain=True, writing=False)
    body = c.get("/status").json()["sleep"]
    assert body["status"] == "running" and body["writing"] is False, "a drain between batches accepts writes"
    _run(monkeypatch, drain=True, writing=True)
    assert c.get("/status").json()["sleep"]["writing"] is True, "a batch's write window"


def test_the_sleep_component_moves_when_the_window_opens(client, monkeypatch):
    _, memory = client
    state = _run(monkeypatch, drain=True, writing=False)
    between = sync_service.components(memory, sleep_state=state)["sleep"]
    monkeypatch.setattr(state, "writing", True)
    inside = sync_service.components(memory, sleep_state=state)["sleep"]
    assert between != inside, "the app maps `sleep` onto `.status`; a window that opens must refresh it"
    monkeypatch.setattr(state, "writing", False)
    assert sync_service.components(memory, sleep_state=state)["sleep"] == between


def test_the_sse_sleep_event_carries_writing_and_fires_when_it_flips(client, monkeypatch):
    from api.config import get_settings
    from api.routers import sync as sync_router

    state = _run(monkeypatch, drain=True, writing=False)

    async def _drive():
        resp = await sync_router.events(settings=get_settings())
        gen = resp.body_iterator
        seen = []
        while len([e for e in seen if e.startswith("event: sleep")]) < 1:
            seen.append(await gen.__anext__())
        state.writing = True
        while len([e for e in seen if e.startswith("event: sleep")]) < 2:
            raw = await gen.__anext__()
            if not raw.startswith("event: ping"):
                seen.append(raw)
        await gen.aclose()
        return [json.loads(e.splitlines()[1].split(":", 1)[1]) for e in seen if e.startswith("event: sleep")]

    # Bounded: before G177 the flip moved nothing in the change key, so no second event ever came.
    first, second = asyncio.run(asyncio.wait_for(_drive(), timeout=10))
    assert first["writing"] is False and second["writing"] is True


def test_status_carries_the_refused_night_as_a_notice_never_an_error(client, monkeypatch):
    """A scheduled run the write window refused is said on `/status` too, not only on `/sleep/status`, as a calm
    `notice`: nothing was read or broken, so `error` stays empty. The in-memory state is gone after a restart, the
    machine-local record is not (`sleep_catch_up.refusal`). A real error wins; a live run carries none."""
    from api.services import sleep_catch_up

    c, memory = client
    seen = []
    wire = {"kind": "scheduled_run_refused", "text": "Last night's 03:00 run didn't start. It runs again at 03:00.",
            "detail": "The scheduled run for Nov 24 at 03:00 did not start: something was still writing.",
            "retry_at": None, "tries": 4, "max_tries": 4, "gave_up": True}

    def notice(memory_path):
        seen.append(str(memory_path))
        return dict(wire)

    monkeypatch.setattr(sleep_catch_up, "refusal", notice)
    state = _run(monkeypatch, drain=False, writing=False, status="idle")
    monkeypatch.setattr(state, "error", None)
    sleep = c.get("/status").json()["sleep"]
    assert sleep["error"] is None, "a refused night is never the error state"
    assert sleep["notice"] == {"kind": "scheduled_run_refused", "text": wire["text"], "detail": wire["detail"],
                               "retryAt": None, "tries": 4, "maxTries": 4, "gaveUp": True}
    assert seen == [str(memory)], "asked of the active bank"
    monkeypatch.setattr(state, "error", "its own error")
    sleep = c.get("/status").json()["sleep"]
    assert sleep["error"] == "its own error" and sleep["notice"] is None, "a real error wins over the notice"
    _run(monkeypatch, drain=False, writing=False, status="running")
    monkeypatch.setattr(state, "error", None)
    sleep = c.get("/status").json()["sleep"]
    assert sleep["error"] is None and sleep["notice"] is None, "never over a running cycle"


def test_sleep_status_carries_the_refused_night_as_a_notice_never_an_error(client, monkeypatch):
    from api.services import sleep_catch_up

    c, _ = client
    wire = {"kind": "scheduled_run_refused", "text": "Last night's 03:00 run hasn't started yet. Next try after 03:12.",
            "detail": "The scheduled run for Nov 24 at 03:00 did not start.", "retry_at": "2026-11-24T03:12:00+00:00",
            "tries": 1, "max_tries": 4, "gave_up": False}
    monkeypatch.setattr(sleep_catch_up, "refusal", lambda memory_path: dict(wire))
    state = _run(monkeypatch, drain=False, writing=False, status="idle")
    monkeypatch.setattr(state, "error", None)
    body = c.get("/sleep/status").json()
    assert body["error"] is None and body["notice"]["text"] == wire["text"]
    assert body["notice"]["retryAt"] == wire["retry_at"] and body["notice"]["gaveUp"] is False
    monkeypatch.setattr(state, "error", "its own error")
    body = c.get("/sleep/status").json()
    assert body["error"] == "its own error" and body["notice"] is None
