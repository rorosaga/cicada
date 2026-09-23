"""G135 — the loopback management API the app drives: status (with reach
detection injected), settings with a live toggle, connectors shown once."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from _synthetic_bank import _bank
from api import config, main
from api.remote import reach, store
from api.routers import remote as remote_router

FUNNEL_ON = {
    "TCP": {"443": {"HTTPS": True}},
    "Web": {"mac.example-tailnet.ts.net:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8765"}}}},
    "AllowFunnel": {"mac.example-tailnet.ts.net:443": True},
}


class _FakeListener:
    def __init__(self):
        self.up, self.error, self.calls = False, None, []

    async def start(self, **kwargs):
        self.calls.append("start")
        self.up = True
        return True

    async def stop(self):
        self.calls.append("stop")
        self.up = False


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(_bank(tmp_path)))
    monkeypatch.delenv("CICADA_REMOTE_PORT", raising=False)  # the port assertions below mean the default
    config.get_settings.cache_clear()
    fake = _FakeListener()
    monkeypatch.setattr(remote_router, "LISTENER", fake)
    monkeypatch.setattr(reach, "detect", lambda port, **k: reach.Reach("funnel-on", "https://mac.example-tailnet.ts.net", False))
    probes = []
    monkeypatch.setattr(reach, "probe", lambda url, **k: probes.append(url) or True)
    yield TestClient(main.app), fake, probes
    config.get_settings.cache_clear()


def test_status_is_off_by_default_and_probes_only_when_asked(client):
    c, _, probes = client
    body = c.get("/remote/status").json()
    assert body["enabled"] is False and body["port"] == 8765 and body["reachable"] is None
    assert body["effectiveUrl"] == "https://mac.example-tailnet.ts.net" and body["tailscale"] == "funnel-on"
    assert body["funnelCommand"] == "tailscale funnel --bg 8765"
    assert body["ngrokCommand"] == "ngrok http 8765 --inspect=false"
    assert probes == []
    assert c.get("/remote/status?probe=true").json()["reachable"] is True and len(probes) == 1


def test_the_switch_starts_and_stops_the_listener_live(client):
    c, fake, _ = client
    assert c.put("/remote/settings", json={"enabled": True}).json()["enabled"] is True
    assert c.put("/remote/settings", json={"enabled": False}).json()["enabled"] is False
    assert fake.calls == ["start", "stop"] and store.load_settings().enabled is False


def test_a_public_url_is_validated_and_can_be_cleared(client):
    c, _, _ = client
    assert c.put("/remote/settings", json={"publicBaseUrl": "http://plain.example"}).status_code == 400
    ok = c.put("/remote/settings", json={"publicBaseUrl": "https://own.example/"}).json()
    assert ok["publicBaseUrl"] == "https://own.example" and ok["effectiveUrl"] == "https://own.example"
    cleared = c.put("/remote/settings", json={"publicBaseUrl": ""}).json()
    assert cleared["publicBaseUrl"] is None


def test_a_connector_is_shown_once_and_never_again(client):
    c, _, _ = client
    created = c.post("/remote/connectors", json={"app": "claude", "label": "Phone",
                                                  "scopes": ["search", "read", "record"], "expiresInDays": 30}).json()
    token = created["token"]
    assert created["link"] == f"https://mac.example-tailnet.ts.net/c/{token}/mcp"
    assert created["mcpUrl"] == "https://mac.example-tailnet.ts.net/mcp"
    listed = c.get("/remote/connectors").json()
    assert set(listed[0]) == {"id", "label", "app", "scopes", "createdAt", "expiresAt", "revokedAt",
                              "lastUsedAt", "lastClient", "state"}
    assert token not in json.dumps(listed)


def test_no_expiry_is_an_explicit_null(client):
    c, _, _ = client
    body = c.post("/remote/connectors", json={"app": "cursor", "scopes": ["search"], "expiresInDays": None}).json()
    assert body["connector"]["expiresAt"] is None


def test_bad_requests_are_400_unknown_ids_404_dead_connectors_409(client):
    c, _, _ = client
    assert c.post("/remote/connectors", json={"app": "claude", "scopes": []}).status_code == 400
    assert c.post("/remote/connectors", json={"app": "claude", "scopes": ["search"], "expiresInDays": 365}).status_code == 400
    assert c.post("/remote/connectors/zzzzzzzz/rotate").status_code == 404
    assert c.delete("/remote/connectors/zzzzzzzz").status_code == 404
    made = c.post("/remote/connectors", json={"app": "claude", "scopes": ["search"]}).json()["connector"]
    assert c.delete(f"/remote/connectors/{made['id']}").json()["state"] == "revoked"
    assert c.post(f"/remote/connectors/{made['id']}/rotate").status_code == 409


def test_rotation_hands_out_a_new_token(client):
    c, _, _ = client
    first = c.post("/remote/connectors", json={"app": "claude", "scopes": ["search"]}).json()
    second = c.post(f"/remote/connectors/{first['connector']['id']}/rotate").json()
    assert second["token"] != first["token"] and second["connector"]["id"] == first["connector"]["id"]


def test_the_ledger_records_connector_lifecycle_as_ids(client, tmp_path, monkeypatch):
    c, _, _ = client
    monkeypatch.setenv("CICADA_TELEMETRY", "on")
    made = c.post("/remote/connectors", json={"app": "claude", "scopes": ["search"]}).json()
    c.post(f"/remote/connectors/{made['connector']['id']}/rotate")
    c.delete(f"/remote/connectors/{made['connector']['id']}")
    from api.services import telemetry

    events = [e.refs["event"] for e in telemetry.read_events() if e.kind == "connector_auth"]
    assert events == ["created", "rotated", "revoked"]
    raw = "".join(p.read_text() for p in telemetry.telemetry_dir().glob("*.jsonl"))
    assert made["token"] not in raw


@pytest.mark.parametrize("status,want", [
    (FUNNEL_ON, "https://mac.example-tailnet.ts.net"),
    ({**FUNNEL_ON, "AllowFunnel": {}}, None),
    ({**FUNNEL_ON, "Web": {"mac.example-tailnet.ts.net:8443": {"Handlers": {"/": {"Proxy": "http://localhost:8765"}}}},
      "AllowFunnel": {"mac.example-tailnet.ts.net:8443": True}}, "https://mac.example-tailnet.ts.net:8443"),
    ({**FUNNEL_ON, "Web": {"mac.example-tailnet.ts.net:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8000"}}}}}, None),
    ({**FUNNEL_ON, "Web": {"mac.example-tailnet.ts.net:443": {"Handlers": {"/api": {"Proxy": "http://127.0.0.1:8765"}}}}}, None),
    ({"Foreground": {"abc": FUNNEL_ON}}, "https://mac.example-tailnet.ts.net"),
    ({}, None),
])
def test_funnel_status_is_read_for_our_port_only(status, want):
    assert reach.funnel_url_for_port(status, 8765) == want


def test_detect_never_changes_a_tunnel():
    seen = []

    def run(cmd, **kwargs):
        seen.append(cmd)

        class Done:
            returncode, stdout = 0, json.dumps(FUNNEL_ON)

        return Done()

    found = reach.detect(8765, which=lambda name: f"/usr/local/bin/{name}", run=run, exists=lambda p: False)
    assert found == reach.Reach("funnel-on", "https://mac.example-tailnet.ts.net", True)
    assert seen == [["/usr/local/bin/tailscale", "funnel", "status", "--json"]]
    assert reach.detect(8765, which=lambda n: None, run=run, exists=lambda p: False).tailscale == "missing"


def test_the_probe_checks_it_is_really_cicada():
    good = lambda url, timeout: (200, json.dumps({"resource": "https://x.example/mcp", "resource_name": "Cicada"}))
    other = lambda url, timeout: (200, json.dumps({"resource": "https://x.example/mcp", "resource_name": "Else"}))
    assert reach.probe("https://x.example", fetch=good) is True
    assert reach.probe("https://x.example", fetch=other) is False
    assert reach.probe("https://x.example", fetch=lambda u, t: (_ for _ in ()).throw(OSError())) is False
