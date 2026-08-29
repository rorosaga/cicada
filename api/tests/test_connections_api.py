from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services.connections import base, registry
from api.services.connections.base import CliResult


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path / "memory"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    config.get_settings.cache_clear()
    registry.reset_registry()

    calls: list[list[str]] = []

    async def fake_run(argv):
        calls.append(argv)
        if argv[:3] == ["claude", "auth", "status"]:
            return CliResult(0, json.dumps({"loggedIn": True, "authMethod": "claude.ai",
                                            "email": "r@example.com", "subscriptionType": "max"}), "")
        if argv[:3] == ["codex", "login", "status"]:
            return CliResult(1, "", "Not logged in")
        return CliResult(0, "", "")

    fake_run.calls = calls  # type: ignore[attr-defined]
    monkeypatch.setattr(base, "run_cli", fake_run)
    monkeypatch.setattr(registry.shutil, "which", lambda name: f"/usr/local/bin/{name}")

    async def no_tags(_url):
        raise ConnectionError("no ollama in tests")

    monkeypatch.setattr(registry, "_ollama_fetch_tags", no_tags)
    test_client = TestClient(main.app)
    test_client.run_cli_calls = calls  # type: ignore[attr-defined]
    yield test_client
    registry.reset_registry()
    config.get_settings.cache_clear()


def test_list_connections(client):
    body = client.get("/connections").json()
    ids = [c["id"] for c in body["connections"]]
    assert ids[:2] == ["claude-plan", "chatgpt-plan"]
    assert {"byok-openai", "byok-anthropic", "byok-openrouter", "byok-gemini", "ollama-local"} <= set(ids)
    claude = next(c for c in body["connections"] if c["id"] == "claude-plan")
    assert claude["connected"] and claude["plan"] == "max" and claude["priceUsdMonth"] is None


def test_set_tier_pref_prices_the_plan(client, tmp_path):
    resp = client.put("/connections/claude-plan/prefs", json={"tier": "20x"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["priceUsdMonth"] == 200.0 and resp.json()["planLabel"] == "Claude Max 20x"
    prefs = json.loads((tmp_path / "home" / registry.PREFS_FILE_NAME).read_text())
    assert prefs["claude-plan"]["tier"] == "20x"


def test_reject_bad_tier(client):
    assert client.put("/connections/claude-plan/prefs", json={"tier": "99x"}).status_code == 422


def test_byok_key_roundtrip(client, tmp_path):
    resp = client.put("/connections/byok-openai/key", json={"key": "sk-abc"})
    assert resp.status_code == 200 and resp.json()["connected"] is True
    assert "OPENAI_API_KEY=sk-abc" in (tmp_path / "home" / "secrets.env").read_text()
    resp = client.delete("/connections/byok-openai/key")
    assert resp.status_code == 200 and resp.json()["connected"] is False


def test_key_endpoint_rejects_non_byok(client):
    assert client.put("/connections/claude-plan/key", json={"key": "x"}).status_code == 400


def test_login_claude_is_terminal_handoff(client):
    resp = client.post("/connections/claude-plan/login")
    assert resp.status_code == 200
    assert resp.json()["mode"] == "terminal" and resp.json()["command"] == "claude auth login"


def test_logout_claude(client):
    assert client.post("/connections/claude-plan/logout").status_code == 200


def test_unknown_connection_404(client):
    assert client.get("/connections/nope").status_code == 404


def test_status_has_connections_block(client):
    # Warm the cache first — /status is cache-only and never probes itself.
    assert client.get("/connections").status_code == 200
    body = client.get("/status").json()
    assert body["connections"]["connected"] == ["claude-plan"]


def test_status_cold_cache_does_not_probe(client):
    body = client.get("/status").json()
    assert body["connections"]["connected"] == []
    assert body["connections"]["engine"] is None
    assert client.run_cli_calls == []
