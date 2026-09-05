"""G122 — GET/PUT /sleep/engine: the engine & model picker's business logic.

Hermetic in exactly the shape `test_connections_api.py`/`test_engine_select.py`'s
own `api_client` fixture already established: a fake `run_cli` so no real
`claude`/`codex` CLI is ever spawned, and a patched `_ollama_fetch_tags` so no
real HTTP call reaches a local Ollama daemon. Ruling 4 (a scheduled cycle
never spends plan quota) and the G124 no-price/no-token rail are both
regression-tested here, not just asserted in prose.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services.connections import base, registry as reg_mod
from api.services.connections.base import CliResult


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path / "memory"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    config.get_settings.cache_clear()
    reg_mod.reset_registry()

    async def fake_run(argv):
        if argv[:3] == ["claude", "auth", "status"]:
            return CliResult(0, json.dumps({"loggedIn": True, "authMethod": "claude.ai",
                                            "email": "r@example.com", "subscriptionType": "max"}), "")
        if argv[:3] == ["codex", "login", "status"]:
            return CliResult(1, "", "Not logged in")
        return CliResult(0, "", "")

    monkeypatch.setattr(base, "run_cli", fake_run)
    monkeypatch.setattr(reg_mod.shutil, "which", lambda name: f"/usr/local/bin/{name}")

    async def no_tags(_url):
        raise ConnectionError("no ollama in tests")

    monkeypatch.setattr(reg_mod, "_ollama_fetch_tags", no_tags)
    test_client = TestClient(main.app)
    yield test_client
    reg_mod.reset_registry()
    config.get_settings.cache_clear()


def test_get_default_shape(client):
    resp = client.get("/sleep/engine")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["mode"] == "byok"
    assert body["source"] == "default"
    ids = {c["id"] for c in body["candidates"]}
    assert ids == {"auto", "agent", "codex", "local", "byok"}
    codex = next(c for c in body["candidates"] if c["id"] == "codex")
    assert codex["available"] is False
    assert codex["detail"]  # explains Sleep can't run on it yet
    assert "manual" in body["preview"] and "scheduled" in body["preview"]
    assert body["preview"]["manual"]["why"]
    assert body["preview"]["scheduled"]["why"]


def test_put_writes_prefs_and_get_reflects_them(client):
    resp = client.put("/sleep/engine", json={"mode": "local", "model": "llama3.1"})
    assert resp.status_code == 200, resp.text
    body = client.get("/sleep/engine").json()
    assert body["mode"] == "local"
    assert body["source"] == "prefs"
    assert body["model"] == "llama3.1"


def test_put_rejects_codex_and_bogus_mode(client):
    assert client.put("/sleep/engine", json={"mode": "codex"}).status_code == 422
    assert client.put("/sleep/engine", json={"mode": "sonnet"}).status_code == 422


def test_put_rejects_an_invalid_agent_model(client):
    resp = client.put("/sleep/engine", json={"mode": "agent", "model": "-oops"})
    assert resp.status_code == 422


def test_put_accepts_any_nonempty_ollama_tag(client):
    resp = client.put("/sleep/engine", json={"mode": "local", "model": "custom:latest"})
    assert resp.status_code == 200, resp.text


def test_switching_mode_clears_the_previous_modes_stale_model(client):
    client.put("/sleep/engine", json={"mode": "local", "model": "llama3.1"})
    resp = client.put("/sleep/engine", json={"mode": "agent"})
    assert resp.status_code == 200, resp.text
    body = client.get("/sleep/engine").json()
    # A Local-mode Ollama tag must never survive a mode switch and get
    # misread as an Agent-mode Claude alias — falls back to the
    # `agent_model` default ("sonnet") instead.
    assert body["model"] != "llama3.1"
    assert body["model"] == "sonnet"


def test_scheduled_preview_never_shows_the_plan_when_only_prefs_chose_it(client):
    # Claude probes connected in this fixture's fake_run (see module docstring).
    resp = client.put("/sleep/engine", json={"mode": "agent"})
    assert resp.status_code == 200, resp.text
    body = client.get("/sleep/engine").json()
    assert body["preview"]["manual"]["engine"] == "claude-cli"
    assert body["preview"]["scheduled"]["engine"] == "litellm"


def test_prefs_file_is_0600(client, tmp_path):
    resp = client.put("/sleep/engine", json={"mode": "local", "model": "llama3.1"})
    assert resp.status_code == 200, resp.text
    path = tmp_path / "home" / "connections.json"
    assert oct(path.stat().st_mode)[-3:] == "600"


def test_get_never_returns_a_price_or_token_field(client):
    resp = client.get("/sleep/engine")
    assert resp.status_code == 200
    text = resp.text.lower()
    assert "price" not in text
    assert "token" not in text
