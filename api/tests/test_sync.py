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
