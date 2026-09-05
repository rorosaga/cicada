from __future__ import annotations

import json
import subprocess
import time

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import bank_index, sync_service


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path))
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    with TestClient(main.app) as c:
        yield c, tmp_path
    config.get_settings.cache_clear()


def test_git_head_reads_ref_without_subprocess(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "x"], cwd=tmp_path, check=True)
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True).stdout.strip()
    assert sync_service.git_head(tmp_path) == sha
    assert sync_service.git_head(tmp_path / "nope") == ""


def test_version_stable_then_changes(client):
    c, mem = client
    v1 = c.get("/sync/version").json()
    v2 = c.get("/sync/version").json()
    assert v1["version"] == v2["version"] and set(v1["components"]) >= {"entities", "inbox", "episodes", "git_head", "bank", "sleep"}
    time.sleep(0.01)
    (mem / "entities" / "new.md").write_text("---\ntype: concept\n---\nx\n")
    v3 = c.get("/sync/version").json()
    assert v3["version"] != v1["version"] and v3["components"]["entities"] != v1["components"]["entities"]


def test_etag_304_on_graph_and_inbox(client):
    c, _ = client
    for path in ("/graph", "/inbox", "/contributors", "/banks", "/sources", "/origins"):
        r1 = c.get(path)
        assert r1.status_code == 200 and r1.headers.get("etag"), path
        r2 = c.get(path, headers={"If-None-Match": r1.headers["etag"]})
        assert r2.status_code == 304, path


def test_banks_etag_changes_when_bank_entity_count_changes(client):
    """The /banks ETag must cover the entity_count/episode_count it reports for
    every bank -- not just banks.yaml's own mtime -- or a 304 would hide a
    changed count (a real body diff) behind a stale ETag."""
    c, mem = client

    r1 = c.get("/banks")
    assert r1.status_code == 200 and r1.headers.get("etag")
    etag1 = r1.headers["etag"]

    time.sleep(0.01)
    (mem / "entities" / "brand-new.md").write_text("---\ntype: concept\n---\nx\n")

    r2 = c.get("/banks", headers={"If-None-Match": etag1})
    assert r2.status_code == 200, "entity_count changed -- must not 304"
    etag2 = r2.headers["etag"]
    assert etag2 != etag1

    r3 = c.get("/banks", headers={"If-None-Match": etag2})
    assert r3.status_code == 304, "unchanged since etag2 -- should 304 now"


def test_graph_etag_varies_with_query_params(client):
    c, _ = client
    e1 = c.get("/graph").headers["etag"]
    e2 = c.get("/graph?hubs_only=true").headers["etag"]
    assert e1 != e2


def test_inbox_etag_varies_with_kind_filter(client):
    c, _ = client
    e1 = c.get("/inbox").headers["etag"]
    e2 = c.get("/inbox?kind=decay").headers["etag"]
    assert e1 != e2


def test_sse_first_event_is_version(client):
    # NOTE: this repo's starlette/httpx versions make TestClient's `.stream()`
    # run the ASGI app to full completion (via a *blocking* portal.call, see
    # starlette/testclient.py::_TestClientTransport.handle_request) before
    # returning any bytes at all -- so `with c.stream(...)` never returns for
    # a never-ending SSE generator, and would hang the test suite forever.
    # Drive the router's async generator directly instead: pull one event,
    # then aclose() it (exercising the same cancellation path a real client
    # disconnect would trigger) and assert that raises nothing.
    import asyncio

    from api.config import get_settings
    from api.routers import sync as sync_router

    async def _drive():
        settings = get_settings()
        resp = await sync_router.events(settings=settings)
        assert resp.media_type == "text/event-stream"
        gen = resp.body_iterator
        first = await gen.__anext__()
        await gen.aclose()
        return first

    first = asyncio.run(_drive())
    lines = first.splitlines()
    assert lines[0] == "event: version"
    data = json.loads(lines[1].split(":", 1)[1])
    assert "version" in data


def test_sse_sleep_event_carries_debt_and_progress(client):
    """G106 amendment: Rested %/Progress % are SSE-driven, not just on
    `/sleep/status` — the `sleep` event (which fires right alongside
    `version` on the very first tick, since `last_sleep` starts as `None`)
    must carry the same debt fields the REST endpoint does."""
    import asyncio

    from api.config import get_settings
    from api.routers import sync as sync_router

    async def _drive():
        settings = get_settings()
        resp = await sync_router.events(settings=settings)
        gen = resp.body_iterator
        await gen.__anext__()          # "version" — first on every tick
        sleep_raw = await gen.__anext__()  # "sleep" — fires alongside it
        await gen.aclose()
        return sleep_raw

    raw = asyncio.run(_drive())
    lines = raw.splitlines()
    assert lines[0] == "event: sleep"
    data = json.loads(lines[1].split(":", 1)[1])
    for key in ("restedPct", "volumePct", "agePct", "unprocessedCount",
                "hasRunBefore", "hoursSinceLastCycle", "progressPct"):
        assert key in data, f"sleep event missing {key}"


def test_sse_sleep_event_carries_per_origin_counts_and_moves_per_episode(client):
    """G125 R3: the study list counts down per episode, so the change key
    must include `stage1_progress` — `progressPct` alone is an integer
    percent that stays put for many episodes on a big queue."""
    import asyncio

    from api.config import get_settings
    from api.routers import sync as sync_router
    from api.services import sleep_cycle

    state = sleep_cycle.get_sleep_state()
    state.status, state.stage, state.episodes_total = "running", 0, 300
    state.queue_by_origin = {"safari-tab": 300}
    state.read_by_origin, state.stage1_progress = {}, 0

    async def _drive():
        resp = await sync_router.events(settings=get_settings())
        gen = resp.body_iterator
        await gen.__anext__()                      # version
        first = await gen.__anext__()              # sleep
        state.read_by_origin, state.stage1_progress = {"safari-tab": 1}, 1   # 1/300 → still 0 %
        second = await gen.__anext__()             # must be a NEW sleep event, not a ping
        await gen.aclose()
        return first, second

    try:
        first, second = asyncio.run(_drive())
    finally:
        state.status, state.stage, state.episodes_total = "idle", 0, 0
        state.queue_by_origin, state.read_by_origin, state.stage1_progress = {}, {}, 0
    d1 = json.loads(first.splitlines()[1].split(":", 1)[1])
    assert d1["queueByOrigin"] == {"safari-tab": 300} and d1["readByOrigin"] == {}
    assert second.splitlines()[0] == "event: sleep"
    d2 = json.loads(second.splitlines()[1].split(":", 1)[1])
    assert d2["readByOrigin"] == {"safari-tab": 1}


def test_sse_sleep_event_fires_when_age_pct_changes_even_though_rested_pct_does_not(
    client, monkeypatch,
):
    """Devin PR #27 round 1, finding 4: `rested_pct = 100 - max(volume_pct,
    age_pct)` — when volume dominates, `age_pct` can move (or the oldest
    episode can cross a UI threshold via `hours_since_last_cycle`) with
    `rested_pct` staying exactly where it was. The old `sleep_key` only
    tracked `rested_pct`, so a connected client held stale `agePct`/
    `hoursSinceLastCycle` indefinitely whenever that happened — and could
    miss the Swift side's 48h "hungry" threshold entirely. Drives two real
    poll ticks with `sleep_debt.compute` faked to return exactly that shape
    (volume 80 dominates throughout; age moves 10 -> 30; rested pinned at
    20) and asserts a SECOND `sleep` event still fires."""
    import asyncio

    from api.config import get_settings
    from api.routers import sync as sync_router
    from api.services import sleep_debt

    calls = {"n": 0}

    async def fake_compute(memory_path, settings):
        calls["n"] += 1
        age = 10 if calls["n"] == 1 else 30
        return sleep_debt.SleepDebt(
            unprocessed_count=5,
            oldest_unprocessed_age_hours=7.0,
            hours_since_last_cycle=1.0,
            has_run_before=True,
            volume_pct=80,
            age_pct=age,
            rested_pct=20,   # unchanged across both ticks — volume dominates
        )

    monkeypatch.setattr(sleep_debt, "compute", fake_compute)

    async def _drive():
        settings = get_settings()
        resp = await sync_router.events(settings=settings)
        gen = resp.body_iterator
        await gen.__anext__()                    # "version" — tick 1
        first_sleep = await gen.__anext__()       # "sleep" — tick 1 (age=10)
        # `version` does not fire again (nothing on disk changed) — the
        # next yield is tick 2's "sleep" event, if the fix works.
        second_sleep = await asyncio.wait_for(gen.__anext__(), timeout=5)
        await gen.aclose()
        return first_sleep, second_sleep

    first_raw, second_raw = asyncio.run(_drive())

    def _agePct(raw: str) -> int:
        lines = raw.splitlines()
        assert lines[0] == "event: sleep"
        return json.loads(lines[1].split(":", 1)[1])["agePct"]

    assert _agePct(first_raw) == 10
    assert _agePct(second_raw) == 30, (
        "a second sleep event must fire even though restedPct never changed"
    )


def test_status_does_not_spawn_git_twice_when_head_unchanged(client, monkeypatch):
    c, _ = client
    from api.services import git_service

    calls = {"n": 0}
    orig = git_service._run_git

    async def counting(*args, **kwargs):
        calls["n"] += 1
        return await orig(*args, **kwargs)

    monkeypatch.setattr(git_service, "_run_git", counting)

    r1 = c.get("/status")
    after_first = calls["n"]
    r2 = c.get("/status")
    assert r1.status_code == 200 and r2.status_code == 200
    assert calls["n"] == after_first, (
        f"expected no additional git calls on the second /status with HEAD unchanged "
        f"({after_first} -> {calls['n']})"
    )


def test_sources_component_covers_feeds_and_calendars(tmp_path):
    """Subscribing to an RSS feed or an ICS calendar rewrites `feeds.yaml` /
    `calendars.yaml` — neither of which lives under `sources/` — so without them
    in the vector the app's feed/calendar lists never learn they are stale."""
    (tmp_path / "entities").mkdir()
    (tmp_path / "sources").mkdir()

    before = sync_service.components(tmp_path)
    time.sleep(0.01)
    (tmp_path / "feeds.yaml").write_text("feeds:\n  - url: https://example.com/rss\n")
    with_feed = sync_service.components(tmp_path)
    assert with_feed["sources"] != before["sources"]

    time.sleep(0.01)
    (tmp_path / "calendars.yaml").write_text("calendars:\n  - url: https://example.com/c.ics\n")
    with_cal = sync_service.components(tmp_path)
    assert with_cal["sources"] != with_feed["sources"]


def test_inbox_component_varies_daily_once_a_pending_item_is_deferred(tmp_path):
    """G60 fix round 1: `is_deferred` (api/services/inbox_service.py) hides an
    inbox item purely by comparing `remind_after` to `date.today()` -- no file
    mtime changes the day the date passes. Without folding today's date into
    the "inbox" ETag component, a client that cached `/inbox` before the due
    date would keep getting a 304 forever and never learn the item came back.
    """
    from datetime import date as real_date

    (tmp_path / "entities").mkdir()
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "inbox-001.md").write_text(
        "---\nkind: conflict\nstatus: pending\nremind_after: '2099-01-01'\n---\nx\n"
    )

    class _FrozenDate(real_date):
        _today = real_date(2026, 8, 30)

        @classmethod
        def today(cls):
            return cls._today

    import api.services.sync_service as sync_service_module

    monkeypatch_today = _FrozenDate

    orig_date = sync_service_module.date
    try:
        sync_service_module.date = monkeypatch_today
        comps_day1 = sync_service_module.components(tmp_path)

        monkeypatch_today._today = real_date(2026, 8, 31)
        comps_day2 = sync_service_module.components(tmp_path)
    finally:
        sync_service_module.date = orig_date

    assert comps_day1["inbox"] != comps_day2["inbox"]


def test_inbox_component_stable_across_days_with_no_deferred_items(tmp_path):
    """Sanity check: without any `remind_after`, the inbox component must NOT
    vary with the day -- otherwise every /inbox response would re-validate
    daily for no reason."""
    from datetime import date as real_date

    (tmp_path / "entities").mkdir()
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "inbox-001.md").write_text(
        "---\nkind: decay\nstatus: pending\n---\nx\n"
    )

    class _FrozenDate(real_date):
        _today = real_date(2026, 8, 30)

        @classmethod
        def today(cls):
            return cls._today

    import api.services.sync_service as sync_service_module

    orig_date = sync_service_module.date
    try:
        sync_service_module.date = _FrozenDate
        comps_day1 = sync_service_module.components(tmp_path)

        _FrozenDate._today = real_date(2026, 8, 31)
        comps_day2 = sync_service_module.components(tmp_path)
    finally:
        sync_service_module.date = orig_date

    assert comps_day1["inbox"] == comps_day2["inbox"]


def test_pending_defer_scan_is_cached_on_the_inbox_mtime(tmp_path, monkeypatch):
    """H1 — `components()` is polled once a second by the SSE loop and called by
    every ETag check, so the inbox YAML scan must run only when the inbox moves.
    """
    (tmp_path / "entities").mkdir()
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "inbox-001.md").write_text(
        "---\nkind: conflict\nstatus: pending\n---\nx\n"
    )

    sync_service._DEFER_CACHE.clear()
    calls = {"n": 0}
    real_scan = sync_service._scan_inbox_for_pending_defer

    def _counting(mp):
        calls["n"] += 1
        return real_scan(mp)

    monkeypatch.setattr(sync_service, "_scan_inbox_for_pending_defer", _counting)

    for _ in range(5):
        comps = sync_service.components(tmp_path)
    assert calls["n"] == 1, "a quiet inbox must not be re-parsed per call"
    assert ":" not in comps["inbox"]

    # A defer rewrites the file -> the mtime moves -> the cache re-validates.
    time.sleep(0.01)
    (inbox / "inbox-001.md").write_text(
        "---\nkind: conflict\nstatus: pending\nremind_after: '2099-01-01'\n---\nx\n"
    )
    comps2 = sync_service.components(tmp_path)
    assert calls["n"] == 2
    assert ":" in comps2["inbox"], "the daily re-validate marker is back"

    # And an un-defer (file removed / rewritten) invalidates it again.
    time.sleep(0.01)
    (inbox / "inbox-001.md").unlink()
    comps3 = sync_service.components(tmp_path)
    assert calls["n"] == 3
    assert ":" not in comps3["inbox"]


def _logo_meta(tmp_path, monkeypatch, entries):
    from api.services import logo_service

    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    bank = logo_service.bank_name(tmp_path)
    logo_service.write_meta(bank, entries)
    return logo_service, bank


def test_logos_component_moves_when_an_entry_ages_past_its_ttl(tmp_path, monkeypatch):
    """PR14 review: the `logos` component was `meta.json`'s mtime alone, but a
    TTL expiry writes NOTHING — `is_fresh` just starts returning False at read
    time, so `/graph`'s `has_logo` flips true->false behind an ETag that never
    moved and the app 304s into a permanently wrong graph."""
    import os
    from datetime import datetime, timedelta, timezone

    (tmp_path / "entities").mkdir()
    now = datetime.now(timezone.utc)
    logo_service, bank = _logo_meta(tmp_path, monkeypatch, {
        "mongodb": {"fetched_at": now.isoformat(), "miss": False, "ext": "png"},
    })
    sync_service._LOGO_TTL_CACHE.clear()
    before = sync_service.components(tmp_path)["logos"]

    # Same index, same mtime — only the clock moved past the entry's TTL.
    meta_path = logo_service.meta_path(bank)
    stamps = meta_path.stat()
    logo_service.write_meta(bank, {
        "mongodb": {"fetched_at": (now - logo_service.HIT_TTL - timedelta(days=1)).isoformat(),
                    "miss": False, "ext": "png"},
    })
    os.utime(meta_path, (stamps.st_atime, stamps.st_mtime))
    # Standing in for the next-expiry deadline passing, which is what makes
    # `_logos_component` rescan on its own.
    sync_service._LOGO_TTL_CACHE.clear()

    after = sync_service.components(tmp_path)["logos"]
    assert after != before, "an expired logo entry must change the logos component"


def test_logo_expiry_scan_is_memoized_between_polls(tmp_path, monkeypatch):
    """`components()` is polled ~1/s, so the index must not be re-parsed per
    call — the memo is keyed on the mtime plus the next expiry deadline."""
    from datetime import datetime, timezone

    (tmp_path / "entities").mkdir()
    logo_service, _bank = _logo_meta(tmp_path, monkeypatch, {
        "mongodb": {"fetched_at": datetime.now(timezone.utc).isoformat(),
                    "miss": False, "ext": "png"},
    })
    sync_service._LOGO_TTL_CACHE.clear()
    calls = {"n": 0}
    real = logo_service.expiry_state

    def counting(bank, **kw):
        calls["n"] += 1
        return real(bank, **kw)

    monkeypatch.setattr(logo_service, "expiry_state", counting)
    for _ in range(5):
        sync_service.components(tmp_path)
    assert calls["n"] == 1
