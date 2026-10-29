"""G132 phase 1 — off by default, nothing changes (ruling 51a "Unset/off, nothing changes"): with publishing off the
new routes answer a plain 404, nothing is written under `$CICADA_HOME/sync/`, a capture records nothing and starts no
thread, the tool door's reply is what it was, and the lifespan, the MCP door and client routing never read the switch.
Synthetic banks only."""
from __future__ import annotations

import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from _sync_home import auth
from _synthetic_bank import _bank

REPO = Path(__file__).resolve().parents[2]
SID = "11111111-2222-4333-8444-555555555555"
#: The tool door's reply before G132 phase 1, key for key.
TOOL_REPLY_KEYS = {"text", "code", "data", "error", "segments", "state", "bank", "bankId"}


@pytest.fixture
def off(tmp_path, monkeypatch):
    from api import config
    from api.main import app

    bank = _bank(tmp_path)
    home = tmp_path / "home"
    monkeypatch.setenv("CICADA_HOME", str(home))
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    monkeypatch.setenv("CICADA_API_AUTH", "on")
    monkeypatch.delenv("CICADA_SYNC_PUBLISH", raising=False)
    monkeypatch.delenv("CICADA_API_TOKEN", raising=False)
    config.get_settings.cache_clear()
    from api.services.auth import get_token

    master = get_token()
    with TestClient(app) as client:
        yield client, master, bank, home
    config.get_settings.cache_clear()


def test_off_the_routes_are_absent_and_nothing_is_written(off):
    client, master, bank, home = off
    for method, path in (("GET", "/sync/log"), ("GET", "/sync/pack"), ("GET", "/sync/status"),
                         ("POST", "/sync/publish/from-here")):
        r = client.request(method, path, headers=auth(master))
        assert r.status_code == 404 and r.json() == {"detail": "Not Found"}, path
    assert client.get("/sync/publish", headers=auth(master)).json()["publish"] is False
    # A capture, a tool write and the old sync routes write nothing for publishing.
    conv = {"kept": [{"role": "user", "text": "plan alpha"}], "gap": None, "summary": {}}
    r = client.post("/capture/session", headers=auth(master), json={
        "harness": "claude-code", "session_id": SID, "conversation": conv, "transcript_bytes": 10,
        "transcript_size": 10, "cwd": "/home/example/alpha"})
    assert r.status_code == 200 and r.json()["status"] == "created"
    reply = client.post("/tools/call", headers={**auth(master), "Idempotency-Key": "k1"}, json={
        "tool": "cicada_save_episode", "arguments": {"content": "decided to ship alpha", "title": "Ship"}})
    assert reply.status_code == 200 and set(reply.json()) == TOOL_REPLY_KEYS
    assert client.get("/sync/version", headers=auth(master)).status_code == 200
    assert not (home / "sync").exists()
    assert not any(t.name == "cicada-capture-commit" for t in threading.enumerate())
    # The capture stays uncommitted, as before: Sleep's batch commits it.
    import subprocess

    status = subprocess.run(["git", "status", "--porcelain", "--", "episodes"], cwd=str(bank), capture_output=True,
                            text=True).stdout
    assert "ep_" in status


def test_the_lifespan_the_mcp_door_and_client_routing_never_read_the_switch():
    for rel in ("api/main.py", "mcp/server.py", "api/services/tool_client.py", "api/services/runtime_layout.py",
                "api/services/hook_client.py", "api/cli.py", "api/cli_app.py"):
        path = REPO / rel
        if path.exists():
            text = path.read_text(encoding="utf-8")
            for name in ("sync_publish", "sync_log", "sync_pack", "capture_commit"):
                assert name not in text, f"{rel} reads {name}"


def test_the_environment_closes_a_settings_file_that_says_on(tmp_path, monkeypatch):
    from api.services import sync_publish

    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("CICADA_SYNC_PUBLISH", raising=False)
    assert not sync_publish.enabled() and sync_publish.source() == "default"
    assert not (tmp_path / "home" / "sync").exists()
    sync_publish.set_enabled(True)
    assert sync_publish.enabled() and sync_publish.source() == "settings"
    assert oct((tmp_path / "home" / "sync" / "settings.json").stat().st_mode & 0o777) == "0o600"
    monkeypatch.setenv("CICADA_SYNC_PUBLISH", "off")
    assert not sync_publish.enabled() and sync_publish.source() == "env"


def test_only_the_servers_own_token_turns_publishing_on(off):
    client, master, _bank, home = off
    token = client.post("/devices", json={"name": "laptop"}, headers=auth(master)).json()["token"]
    assert client.put("/sync/publish", json={"publish": True}, headers=auth(token)).status_code == 403
    assert client.get("/sync/publish", headers=auth(token)).json()["publish"] is False
    on = client.put("/sync/publish", json={"publish": True}, headers=auth(master))
    assert on.status_code == 200 and on.json()["publish"] is True and on.json()["log"]["state"] == "publishing"
    assert client.get("/sync/log", headers=auth(token)).status_code == 200


def test_a_demo_bank_is_never_published(off, monkeypatch):
    from api.services import demo_guard

    client, master, bank, _home = off
    monkeypatch.setenv("CICADA_SYNC_PUBLISH", "on")
    (bank / demo_guard.MANIFEST).write_text(f"kind: {demo_guard.DEMO_KIND}\n")
    for path in ("/sync/log", "/sync/pack", "/sync/status"):
        assert client.get(path, headers=auth(master)).status_code == 404
    body = client.get("/sync/publish", headers=auth(master)).json()
    assert body["publish"] is True and body["demo"] is True and body["log"] is None
