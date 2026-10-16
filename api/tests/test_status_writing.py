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
