"""G213 — the HTTP agent API, and G212 — pairing a device with a one-time code.

The backend door (`/v1/*` on the backend's own port) and the listener door (the same operations on the G135 listener,
owner 2026-10-22) run the same remote tool bodies through `agent_api.call`. Synthetic bank and placeholder names only;
nothing reaches the network.
"""
from __future__ import annotations

import json
import subprocess

import pytest
from fastapi.testclient import TestClient

from _synthetic_bank import _bank
from api.remote import agent_api, catalog, store as remote_store
from api.services import device_tokens


@pytest.fixture
def server(tmp_path, monkeypatch):
    """A backend with auth ON, one synthetic bank, its own CICADA_HOME, Sleep idle."""
    from api import config
    from api.main import app
    from api.remote import runtime as remote_runtime
    from api.routers import agent_api as agent_router
    from api.remote.app import Limits

    memory = _bank(tmp_path)
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setenv("CICADA_API_AUTH", "on")
    monkeypatch.delenv("CICADA_API_TOKEN", raising=False)
    monkeypatch.setattr(remote_runtime, "_SHARED", None)
    monkeypatch.setattr(agent_router, "LIMITS", Limits())
    config.get_settings.cache_clear()
    from api.services.auth import get_token

    master = get_token()
    with TestClient(app) as client:
        yield client, master, memory
    config.get_settings.cache_clear()


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _agent(client, master, name="Texting Agent", scopes=("search", "read", "record")):
    made = client.post("/agent-api/tokens", json={"name": name, "scopes": list(scopes), "expiresInDays": 30,
                                                  "baseUrl": "https://cicada.example.ts.net"},
                       headers=_auth(master))
    assert made.status_code == 201, made.text
    return made.json()


# --- tokens ----------------------------------------------------------------------------------------------------------

def test_an_agent_token_is_made_by_the_person_shown_once_and_handed_off_in_one_paragraph(server):
    client, master, _ = server
    made = _agent(client, master)
    token = made["token"]
    assert catalog.API_TOKEN_RE.match(token)
    assert made["agent"]["author"] == "api:texting-agent" and made["agent"]["state"] == "active"
    prompt = made["prompt"]
    assert token in prompt and "https://cicada.example.ts.net/v1/llms.txt" in prompt and "\n" not in prompt
    listed = client.get("/agent-api/tokens", headers=_auth(master)).json()["tokens"]
    assert [t["id"] for t in listed] == [made["agent"]["id"]] and token not in json.dumps(listed)
    # Never listed as a G135 connector (it opens /v1 only).
    assert client.get("/remote/connectors", headers=_auth(master)).json() == []


def test_a_device_never_mints_an_agent_token(server):
    client, master, _ = server
    device = client.post("/devices", json={"name": "laptop"}, headers=_auth(master)).json()["token"]
    assert client.post("/agent-api/tokens", json={"name": "x"}, headers=_auth(device)).status_code == 403
    assert client.get("/agent-api/tokens", headers=_auth(device)).status_code == 200


def test_only_a_connector_token_opens_v1(server):
    client, master, _ = server
    device = client.post("/devices", json={"name": "laptop"}, headers=_auth(master)).json()["token"]
    for headers in ({}, _auth(master), _auth(device), _auth("cic_api_abcdefgh_" + "b" * 43)):
        answer = client.post("/v1/recall", json={"query": "alpha"}, headers=headers)
        assert answer.status_code == 401 and answer.json()["code"] == "invalid_token"
        assert answer.json()["isError"] is True


def test_a_revoked_or_expired_agent_token_is_refused_at_once(server):
    client, master, _ = server
    made = _agent(client, master)
    assert client.post("/v1/recall", json={"query": "alpha"}, headers=_auth(made["token"])).status_code == 200
    assert client.delete(f"/agent-api/tokens/{made['agent']['id']}", headers=_auth(master)).status_code == 200
    answer = client.post("/v1/recall", json={"query": "alpha"}, headers=_auth(made["token"]))
    assert answer.status_code == 401 and "revoked" in answer.json()["text"]


def test_an_agent_token_never_opens_mcp_and_a_link_secret_of_its_row_is_no_key(tmp_path):
    db = remote_store.ConnectorStore(tmp_path / "c.db")
    connector, token = db.create(app="other", label="Agent", scopes=["search"], expires_in_days=7, auth="api")
    assert db.verify_agent(token)[1] == "ok"
    assert db.verify(token) == (None, "malformed")
    secret = token.split("_", 3)[3]
    assert db.verify(f"cic_rc_{connector.id}_{secret}") == (None, "unknown")
    with pytest.raises(ValueError):
        db.rotate(connector.id)
    with pytest.raises(ValueError):
        db.create(app="other", label="  ", scopes=["search"], expires_in_days=7, auth="api")


def test_a_link_connector_secret_also_opens_v1(server):
    client, _, _ = server
    _, token = remote_store.ConnectorStore().create(app="grok", label="Grok", scopes=["search"], expires_in_days=7)
    answer = client.post("/v1/recall", json={"query": "alpha"}, headers=_auth(token))
    assert answer.status_code == 200


# --- operations ------------------------------------------------------------------------------------------------------

def test_recall_answers_the_envelope_with_a_fenced_reply(server):
    client, master, _ = server
    token = _agent(client, master)["token"]
    answer = client.post("/v1/recall", json={"query": "alpha project"}, headers=_auth(token))
    assert answer.status_code == 200
    body = answer.json()
    assert set(body) == {"text", "isError", "code", "data"} and body["isError"] is False
    assert "<<<cicada-reference" in body["text"]


def test_a_save_carries_the_agent_s_provenance_and_a_claim_is_never_the_person_s_words(server):
    client, master, memory = server
    made = _agent(client, master)
    token, cid = made["token"], made["agent"]["id"]
    saved = client.post("/v1/save_note", json={"content": "Decided to ship alpha on Friday.", "title": "Ship"},
                        headers=_auth(token))
    assert saved.status_code == 200 and saved.json()["isError"] is False, saved.text
    from api.services import markdown_parser

    episodes = [(markdown_parser.parse(p).frontmatter, None) for p in sorted((memory / "episodes").glob("ep_*.md"))]
    fm = next(fm for fm, _ in episodes if fm.get("connector") == cid)
    assert fm["harness"] == catalog.API_HARNESS
    log = subprocess.run(["git", "-C", str(memory), "log", "-1", "--format=%B"], capture_output=True, text=True).stdout
    assert "Cicada-Author: api:texting-agent" in log
    # The remote schema's observer is agent | external: the person's own words are refused, by field.
    owner = client.post("/v1/write_claim", json={"subject": "alpha-project", "predicate": "uses", "object": "x",
                                                 "observer": "owner"}, headers=_auth(token))
    assert owner.status_code == 400 and owner.json()["code"] == "invalid_arguments" and "observer" in owner.json()["text"]
    claim = client.post("/v1/write_claim", json={"subject": "alpha-project", "predicate": "uses",
                                                 "object": "sqlite-vec"}, headers=_auth(token))
    assert claim.status_code == 200 and claim.json()["isError"] is False, claim.text
    page = (memory / "entities" / "alpha-project.md").read_text()
    assert f"remote:{cid}" in page


def test_scopes_bound_the_operations(server):
    client, master, _ = server
    token = _agent(client, master, scopes=("search",))["token"]
    denied = client.post("/v1/save_note", json={"content": "x"}, headers=_auth(token))
    assert denied.status_code == 403 and denied.json()["code"] == "denied"
    me = client.get("/v1/me", headers=_auth(token)).json()
    assert me["operations"] == ["recall"] and me["scopes"] == ["search"] and me["kind"] == "agent"


def test_refusals_before_a_tool_runs(server):
    client, master, _ = server
    token = _agent(client, master)["token"]
    assert client.post("/v1/nope", json={}, headers=_auth(token)).json()["code"] == "unknown_operation"
    bad = client.post("/v1/recall", content=b"[1]", headers=_auth(token))
    assert bad.status_code == 400 and bad.json()["code"] == "invalid_arguments"
    browser = client.post("/v1/recall", json={"query": "x"}, headers={**_auth(token), "Origin": "https://evil.example"})
    assert browser.status_code == 403 and browser.json()["code"] == "origin"


def test_a_write_while_sleep_holds_the_pages_is_409_with_retry_after(server, monkeypatch):
    client, master, _ = server
    from api.remote import runtime as remote_runtime

    token = _agent(client, master)["token"]
    monkeypatch.setattr(remote_runtime, "_sleep_running", lambda: True)
    monkeypatch.setattr(remote_runtime, "_SHARED", None)
    answer = client.post("/v1/save_note", json={"content": "x"}, headers=_auth(token))
    assert answer.status_code == 409 and answer.json()["code"] == "sleep_writing"
    assert answer.headers["Retry-After"] == str(agent_api.BUSY_RETRY_S)


def test_the_documents_are_open_and_describe_every_operation(server):
    client, _, _ = server
    text = client.get("/llms.txt").text
    assert client.get("/v1/llms.txt").text == text
    for op in agent_api.OPS:
        assert f"/v1/{op}" in text
    doc = client.get("/v1/openapi.json").json()
    assert doc["openapi"] == "3.1.0" and set(doc["paths"]) == {f"/v1/{op}" for op in agent_api.OPS} | {"/v1/me"}
    blob = json.dumps(doc)
    assert "conversation" not in json.dumps([p["post"]["requestBody"] for k, p in doc["paths"].items() if "post" in p])
    assert "cicada_save_episode" not in blob   # tool names are spelled as this door's operations


def test_every_operation_is_a_remote_tool_with_a_scope():
    from api.remote.tools import REMOTE_TOOLS

    for op, tool in agent_api.OPS.items():
        assert tool in REMOTE_TOOLS and catalog.TOOL_SCOPE[tool], op


def test_an_api_author_is_a_harness_contributor():
    from api.services import git_service

    assert git_service._classify_author_kind("api:texting-agent") == git_service.HARNESS_KIND


# --- the listener door (owner 2026-10-22) ------------------------------------------------------------------------------

def test_the_listener_serves_v1_with_the_same_envelope_and_never_mcp_to_an_agent_token(tmp_path, monkeypatch):
    from api import config
    from api.remote.app import build_app
    from api.remote.runtime import RemoteRuntime

    memory = _bank(tmp_path)
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    try:
        db = remote_store.ConnectorStore()
        _, token = db.create(app="other", label="Agent", scopes=["search", "read"], expires_in_days=7, auth="api")
        app = build_app(db, runtime=RemoteRuntime(post=lambda p, d: {}, sleep_running=lambda: False))
        with TestClient(app, base_url="https://cicada.example.ts.net") as client:
            ok = client.post("/v1/recall", json={"query": "alpha"}, headers=_auth(token))
            assert ok.status_code == 200 and set(ok.json()) == {"text", "isError", "code", "data"}
            assert client.get("/v1/me", headers=_auth(token)).json()["operations"] == [
                "recall", "page", "timeline", "project", "inbox"]
            assert client.post("/v1/save_note", json={"content": "x"}, headers=_auth(token)).status_code == 403
            assert "/v1/recall" in client.get("/v1/llms.txt").text
            mcp = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                              headers={**_auth(token), "Accept": "application/json, text/event-stream"})
            assert mcp.status_code == 401
            assert client.post("/v1/recall", json={}, headers=_auth("nope")).status_code == 401
            assert client.post("/v1/recall", json={"query": "x"},
                               headers={**_auth(token), "Origin": "https://evil.example"}).status_code == 403
    finally:
        config.get_settings.cache_clear()


# --- G212: pairing ---------------------------------------------------------------------------------------------------

def test_a_pairing_code_is_shown_once_spent_once_and_mints_a_device(server):
    client, master, _ = server
    made = client.post("/devices/pairing", json={"url": "https://cicada.example.ts.net"}, headers=_auth(master))
    assert made.status_code == 201
    code, qr = made.json()["code"], made.json()["qr"]
    assert qr == {"v": 1, "url": "https://cicada.example.ts.net", "code": code} and len(code) == 9
    pairing_id = made.json()["pairing"]["id"]
    assert client.get(f"/devices/pairing/{pairing_id}", headers=_auth(master)).json()["pairing"]["state"] == "waiting"
    # A phone types it however it likes: lower case, no dash.
    paired = client.post("/pair", json={"code": code.lower().replace("-", ""), "name": "Example Phone"})
    assert paired.status_code == 201
    token, device = paired.json()["token"], paired.json()["device"]
    assert device_tokens.TOKEN_RE.match(token) and device["name"] == "Example Phone"
    assert client.get("/devices", headers=_auth(token)).status_code == 200
    seen = client.get(f"/devices/pairing/{pairing_id}", headers=_auth(master)).json()
    assert seen["pairing"]["state"] == "paired" and seen["device"]["id"] == device["id"]
    again = client.post("/pair", json={"code": code, "name": "Another"})
    assert again.status_code == 404


def test_a_code_is_hashed_at_rest_and_expires(tmp_path):
    from datetime import datetime, timedelta, timezone

    db = device_tokens.DeviceStore(tmp_path / "devices.db")
    then = datetime(2026, 10, 22, 9, 0, tzinfo=timezone.utc)
    pairing, code = db.create_pairing(now=then)
    raw = b"".join(p.read_bytes() for p in tmp_path.glob("devices.db*"))
    assert code.replace("-", "").encode() not in raw
    with pytest.raises(KeyError):
        db.redeem(code, "Phone", now=then + timedelta(seconds=device_tokens.PAIRING_TTL_S + 1))
    assert db.pairing(pairing.id, now=then + timedelta(hours=1)).state == "expired"


def test_a_cancelled_code_pairs_nothing_and_a_device_cannot_make_one(server):
    client, master, _ = server
    made = client.post("/devices/pairing", json={}, headers=_auth(master)).json()
    assert made["qr"]["url"] is None
    assert client.delete(f"/devices/pairing/{made['pairing']['id']}", headers=_auth(master)).status_code == 200
    assert client.post("/pair", json={"code": made["code"], "name": "Phone"}).status_code == 404
    device = client.post("/devices", json={"name": "laptop"}, headers=_auth(master)).json()["token"]
    assert client.post("/devices/pairing", json={}, headers=_auth(device)).status_code == 403
    assert client.post("/devices/pairing", json={"url": "http://cicada.example.ts.net"},
                       headers=_auth(master)).status_code == 400


def test_at_most_five_codes_wait(tmp_path):
    db = device_tokens.DeviceStore(tmp_path / "devices.db")
    for _ in range(device_tokens.MAX_OPEN_PAIRINGS):
        db.create_pairing()
    with pytest.raises(ValueError):
        db.create_pairing()
