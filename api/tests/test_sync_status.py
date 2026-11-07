"""G132 phase 1 — the home's status frame (ruling 51d): the SSE `sleep` event's keys exactly (built in one place),
plus the schedule and its next run, the waiting and parked conversations by id only, a provider-neutral engine label
and the home's name; and the primer is brought current before a replica reads. Synthetic banks only."""
from __future__ import annotations

import asyncio
import json

from _sync_home import auth, device_token, home  # noqa: F401 — the fixture
from api.services import sleep_parked, state_dictionary


def _sse_sleep_payload(settings) -> dict:
    from api.routers import sync as sync_router

    async def first():
        resp = await sync_router.events(settings=settings)
        it = resp.body_iterator
        try:
            while True:
                chunk = await asyncio.wait_for(it.__anext__(), 5)
                if chunk.startswith("event: sleep"):
                    return json.loads(chunk.split("data: ", 1)[1])
        finally:
            await it.aclose()

    return asyncio.run(first())


def test_the_frame_carries_the_sse_sleep_keys_and_ids_never_titles(home):  # noqa: F811
    from api.config import get_settings

    client, master, bank = home
    sleep_parked.park(bank, "ep_2026-09-01_001", "failed twice", 2)
    r = client.get("/sync/status", headers=auth(device_token(client, master)))
    assert r.status_code == 200, r.text
    frame = r.json()
    assert set(frame["sleep"]) == set(_sse_sleep_payload(get_settings()))
    assert frame["queue"]["waiting"] == ["ep_2026-09-01_001"]
    assert frame["queue"]["parked"] == ["ep_2026-09-01_001"]
    assert "Planning alpha" not in r.text   # the waiting episode's title never travels
    assert frame["engine"]["label"] in {"plan", "key", "local", "auto", "none", "unknown"}
    assert set(frame["schedule"]) == {"mode", "enabled", "hour", "minute", "intervalHours", "nextAt"}
    assert frame["home"]["name"] and frame["seq"] == frame["log"]["seq"] >= 1
    assert frame["log"]["state"] == "publishing"


def test_a_replica_never_reads_an_older_primer_than_the_home(home):  # noqa: F811
    client, master, bank = home
    state_dictionary.state_path(bank).unlink(missing_ok=True)
    assert client.get("/sync/log", headers=auth(master)).status_code == 200
    assert state_dictionary.state_path(bank).exists()
    from _sync_home import git

    # Written and committed alone, before the log was read.
    assert git(bank, "status", "--porcelain", "--", "_state.md") == ""
    assert git(bank, "log", "-1", "--format=%s", "--name-only").split() [-1] == "_state.md"
