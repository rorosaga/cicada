from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import telemetry as tm
from api.services.connections import registry


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path / "memory"))
    monkeypatch.setenv("CICADA_TELEMETRY", "on")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    config.get_settings.cache_clear()
    registry.reset_registry()

    async def statuses(self, fresh=False):
        from api.models.schemas import ConnectionKind, ConnectionStatus
        return [ConnectionStatus(id="byok-openai", label="OpenAI API key", kind=ConnectionKind.usage,
                                 available=True, connected=True, billing="usage")]

    monkeypatch.setattr(registry.Registry, "statuses", statuses)
    tm.record(tm.UsageEvent(kind="llm_call", stage="ask", model="gpt-5.4-mini", connection="byok-openai",
                            input_tokens=10, output_tokens=5, cost_usd=0.01, equiv_cost_usd=0.01))
    yield TestClient(main.app)
    registry.reset_registry()
    config.get_settings.cache_clear()


def test_summary(client):
    body = client.get("/consumption/summary?range=30d").json()
    assert body["costUsd"] == 0.01 and body["invocations"] == 1 and body["range"] == "30d"


def test_calendar_shape(client):
    body = client.get("/consumption/calendar?weeks=4").json()
    assert len(body["days"]) == 28 and {"date", "memoryWrites", "events", "tokens", "level"} <= set(body["days"][0])


def test_stats(client):
    body = client.get("/consumption/stats?range=all").json()
    assert body["byModel"][0]["model"] == "gpt-5.4-mini" and len(body["hourHistogram"]) == 24


def test_connections(client):
    body = client.get("/consumption/connections").json()
    assert body["connections"][0]["id"] == "byok-openai" and body["connections"][0]["costUsd"] == 0.01


def test_harness_is_200_even_when_nothing_exists(client, tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    body = client.get("/consumption/harness").json()
    assert body == {"claudeCode": None, "codex": None}


def test_bad_range_422(client):
    assert client.get("/consumption/summary?range=yesterday").status_code == 422


def test_summary_etag_304_then_200_after_new_event(client):
    first = client.get("/consumption/summary?range=all")
    etag = first.headers["etag"]
    assert client.get("/consumption/summary?range=all", headers={"If-None-Match": etag}).status_code == 304

    tm.record(tm.UsageEvent(kind="llm_call", stage="ask", model="gpt-5.4-mini", connection="byok-openai",
                            input_tokens=1, output_tokens=1, cost_usd=0.001, equiv_cost_usd=0.001))
    again = client.get("/consumption/summary?range=all", headers={"If-None-Match": etag})
    assert again.status_code == 200, "a new ledger event must break the ETag"


def test_calendar_and_stats_also_support_conditional_get(client):
    for path in ("/consumption/calendar?weeks=4", "/consumption/stats?range=all"):
        first = client.get(path)
        etag = first.headers.get("etag")
        assert etag, f"{path} must set an ETag"
        assert client.get(path, headers={"If-None-Match": etag}).status_code == 304


def _local_date_differs_from_utc(tz: str) -> bool:
    import os
    import time as _time
    from datetime import datetime, timezone

    old = os.environ.get("TZ")
    os.environ["TZ"] = tz
    _time.tzset()
    try:
        from datetime import date as _date
        return _date.today() != datetime.now(timezone.utc).date()
    finally:
        if old is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old
        _time.tzset()


# UTC+14 and UTC-11: at every instant of the day at least ONE of these has a
# local date that differs from UTC's, so this pair pins the bug whatever time
# the suite runs at.
@pytest.mark.parametrize("tz", ["Pacific/Kiritimati", "Pacific/Midway"])
def test_day_windows_are_bounded_by_the_utc_day_not_the_machine_day(client, monkeypatch, tz):
    """Every ledger event is stamped in UTC and bucketed by `ts[:10]`, so
    bounding the query with the machine's local day shifted (and, west of UTC,
    dropped) the most recent day of usage."""
    import os
    import time as _time
    from datetime import datetime, timezone

    from api.services import consumption_stats

    captured: dict = {}

    async def fake_summary(memory_path, *, range_, today):
        captured["summary"] = today
        return {"range": range_, "costUsd": 0.0, "invocations": 0}

    async def fake_calendar(memory_path, *, weeks, today):
        captured["calendar"] = today
        return []

    async def fake_stats(memory_path, *, range_, today):
        captured["stats"] = today
        return {"by_model": [], "by_stage": [], "by_connection": [], "by_bank": [],
                "series": [], "hour_histogram": [0] * 24, "favorite_model": None,
                "lifetime_tokens": 0, "range": range_}

    real_read_events = tm.read_events

    def spy_read_events(start=None, end=None):
        captured["connections_end"] = end
        return real_read_events(start=start, end=end)

    monkeypatch.setattr(consumption_stats, "summary", fake_summary)
    monkeypatch.setattr(consumption_stats, "calendar", fake_calendar)
    monkeypatch.setattr(consumption_stats, "stats", fake_stats)
    monkeypatch.setattr(tm, "read_events", spy_read_events)

    old_tz = os.environ.get("TZ")
    os.environ["TZ"] = tz
    _time.tzset()
    try:
        for path in ("/consumption/summary?range=30d", "/consumption/calendar?weeks=4",
                     "/consumption/stats?range=all", "/consumption/connections"):
            assert client.get(path).status_code == 200, path
        utc_today = datetime.now(timezone.utc).date()
    finally:
        if old_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old_tz
        _time.tzset()

    assert captured["summary"] == utc_today
    assert captured["calendar"] == utc_today
    assert captured["stats"] == utc_today
    assert captured["connections_end"] == utc_today


def test_at_least_one_of_the_two_probe_zones_really_differs_from_utc():
    """Guards the test above from silently becoming a no-op."""
    assert (_local_date_differs_from_utc("Pacific/Kiritimati")
            or _local_date_differs_from_utc("Pacific/Midway"))


def test_daily_dashboards_stop_being_cached_across_utc_midnight(client, monkeypatch):
    """Rolling ranges, streaks and calendars all move at UTC midnight with no
    new ledger event to bump the `telemetry` component — so the current UTC
    date is part of the ETag."""
    from datetime import date as _date

    from api.routers import consumption

    tags = {}
    for path in ("/consumption/summary?range=30d", "/consumption/calendar?weeks=4",
                 "/consumption/stats?range=all"):
        tags[path] = client.get(path).headers["etag"]
        assert client.get(path, headers={"If-None-Match": tags[path]}).status_code == 304

    monkeypatch.setattr(consumption, "_utc_today", lambda: _date(2099, 1, 1))
    for path, etag in tags.items():
        resp = client.get(path, headers={"If-None-Match": etag})
        assert resp.status_code == 200, f"{path} 304'd into yesterday's numbers"


def test_telemetry_rides_the_sync_version_vector(client):
    before = client.get("/sync/version").json()["components"]["telemetry"]
    tm.record(tm.UsageEvent(kind="llm_call", stage="ask", model="gpt-5.4-mini", connection="byok-openai",
                            input_tokens=1, output_tokens=1, cost_usd=0.001, equiv_cost_usd=0.001))
    after = client.get("/sync/version").json()["components"]["telemetry"]
    assert after != before, "a new telemetry event must change the telemetry sync component"
