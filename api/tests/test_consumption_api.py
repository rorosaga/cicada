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


def test_telemetry_rides_the_sync_version_vector(client):
    before = client.get("/sync/version").json()["components"]["telemetry"]
    tm.record(tm.UsageEvent(kind="llm_call", stage="ask", model="gpt-5.4-mini", connection="byok-openai",
                            input_tokens=1, output_tokens=1, cost_usd=0.001, equiv_cost_usd=0.001))
    after = client.get("/sync/version").json()["components"]["telemetry"]
    assert after != before, "a new telemetry event must change the telemetry sync component"
