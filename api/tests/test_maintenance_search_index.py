"""G139 — Settings → Memory's search-index row: a status that reads the
derived FTS5 index's freshness, and a rebuild that follows enrich-links' 409
rules (R-O17 keeps the dedup sweep out)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import search_index, sleep_cycle


@pytest.fixture(autouse=True)
def _fresh_index_state():
    """`search_index` keeps per-bank process state, and a status read on a
    bank with no index starts a background build — the same isolation
    `test_search_index.py`'s fixture gives its own tests."""
    search_index.reset()
    yield
    search_index.reset()


def _client(tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    (memory / "entities" / "alpha-project.md").write_text("---\ntype: project\nname: Alpha project\n---\nBody.\n", encoding="utf-8")
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    return TestClient(main.app), memory


def test_status_reports_a_state_and_rebuild_makes_it_ready(tmp_path, monkeypatch):
    client, memory = _client(tmp_path, monkeypatch)
    assert client.get("/maintenance/search-index").json()["state"] in {"ready", "stale", "building", "unavailable"}
    # The read above may have started a background build; let it finish so no
    # worker outlives the test's tmp dir.
    assert search_index.wait_idle(memory, timeout=10)
    body = client.post("/maintenance/search-index/rebuild").json()
    if search_index.fts5_available():
        assert body["state"] == "ready" and body["builtAt"] and body["documents"] >= 1
    config.get_settings.cache_clear()


def test_rebuild_is_refused_while_sleep_runs(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    monkeypatch.setattr(sleep_cycle, "get_sleep_state", lambda: SimpleNamespace(status="running"))
    assert client.post("/maintenance/search-index/rebuild").status_code == 409
    config.get_settings.cache_clear()


def test_a_failed_rebuild_is_a_plain_503(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    def boom(_):
        raise RuntimeError("disk")
    monkeypatch.setattr(search_index, "rebuild", boom)
    resp = client.post("/maintenance/search-index/rebuild")
    assert resp.status_code == 503 and "disk" not in resp.text
    config.get_settings.cache_clear()
