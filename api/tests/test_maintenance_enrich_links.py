"""Router tests for POST /maintenance/enrich-links (G102 cheap slice).
Hermetic: `link_enrichment.backfill` is monkeypatched to a spy so the router
contract (query params, engine resolution, 409 guard, response shape) is what
is under test — the driver has its own suite."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import link_enrichment, sleep_cycle


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    """`engine_select.resolve_settings` reads the connections registry under
    `cicada_home()` (prefs only, for byok) — never the developer's real one."""
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))


def _client(tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    return TestClient(main.app), memory


def _spy(monkeypatch, report=None):
    calls = []

    async def fake_backfill(memory_path, settings, **kwargs):
        calls.append((memory_path, settings, kwargs))
        r = link_enrichment.BackfillReport(selected=3, reused=2, summarized=1, fetched=1, remaining=7)
        r.commit = "abc123"
        return r

    monkeypatch.setattr(link_enrichment, "backfill", fake_backfill)
    return calls


def test_endpoint_runs_backfill_with_the_live_seams_and_reports(tmp_path, monkeypatch):
    client, memory = _client(tmp_path, monkeypatch)
    calls = _spy(monkeypatch)
    resp = client.post("/maintenance/enrich-links?limit=50&recon_limit=10")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["selected"], body["reused"], body["summarized"], body["fetched"], body["remaining"]) == (3, 2, 1, 1, 7)
    assert body["commit"] == "abc123" and body["engine"] == "litellm" and body["engineDetail"]
    (path, settings, kwargs), = calls
    assert path == memory and kwargs["limit"] == 50 and kwargs["recon_limit"] == 10
    # User-initiated: the LIVE fetch + summarize seams are passed, never gated (R10).
    assert kwargs["fetch_fn"] is link_enrichment.default_fetch
    assert kwargs["summarize_fn"] is link_enrichment._summarize_excerpt
    assert kwargs["engine"] == "litellm"
    config.get_settings.cache_clear()


def test_limit_defaults_to_the_per_cycle_setting_and_is_bounded(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    calls = _spy(monkeypatch)
    assert client.post("/maintenance/enrich-links").status_code == 200
    assert calls[-1][2]["limit"] == config.get_settings().link_enrich_backfill_per_cycle
    assert client.post("/maintenance/enrich-links?limit=0").status_code == 422
    assert client.post("/maintenance/enrich-links?limit=501").status_code == 422
    config.get_settings.cache_clear()


def test_409_while_a_sleep_cycle_is_running(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    calls = _spy(monkeypatch)
    monkeypatch.setattr(sleep_cycle, "get_sleep_state", lambda: SimpleNamespace(status="running"))
    resp = client.post("/maintenance/enrich-links?limit=5")
    assert resp.status_code == 409 and calls == []
    config.get_settings.cache_clear()


def test_kill_switch_short_circuits_before_engine_resolution(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    calls = _spy(monkeypatch)
    monkeypatch.setenv("CICADA_LINK_ENRICH_ENABLED", "0")
    config.get_settings.cache_clear()

    async def boom(*a, **k):
        raise AssertionError("engine must not be resolved when the feature is off")

    monkeypatch.setattr("api.services.engine_select.resolve_settings", boom)
    resp = client.post("/maintenance/enrich-links?limit=5")
    assert resp.status_code == 200 and resp.json()["selected"] == 0 and calls == []
    config.get_settings.cache_clear()
