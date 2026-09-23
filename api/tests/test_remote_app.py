"""G135 — the remote door over real HTTP, in process (no network): the 401
shape, the secret link, scoped tool lists, Origin refusal, the rate limit,
both protocol eras, protected-resource metadata, and no token in any log."""
from __future__ import annotations

import logging
import re
import subprocess
from datetime import datetime, timedelta, timezone

import pytest
from loguru import logger
from starlette.testclient import TestClient

from _synthetic_bank import _bank
from api import config
from api.remote import app as remote_app
from api.remote import catalog, store
from api.remote.runtime import DENIED_TEXT, RemoteRuntime

H = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json",
     "Mcp-Protocol-Version": "2025-11-25"}


def _rpc(method, params=None, i=1):
    return {"jsonrpc": "2.0", "id": i, "method": method, "params": params or {}}


@pytest.fixture
def world(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    db = store.ConnectorStore(tmp_path / "remote" / "connectors.db")
    runtime = RemoteRuntime(post=lambda p, d: {"status": "resolved"}, sleep_running=lambda: False)
    yield db, runtime, memory
    config.get_settings.cache_clear()


def _client(db, runtime, limits=None):
    return TestClient(remote_app.build_app(db, runtime=runtime, limits=limits))


def _names(resp):
    return sorted(t["name"] for t in resp.json()["result"]["tools"])


def test_no_token_is_a_401_that_says_how_to_authenticate(world):
    db, runtime, _ = world
    with _client(db, runtime) as c:
        resp = c.post("/mcp", json=_rpc("tools/list"), headers=H)
    assert resp.status_code == 401 and resp.json()["error"] == "invalid_token"
    challenge = resp.headers["www-authenticate"]
    assert challenge.startswith('Bearer realm="cicada", error="invalid_token"')
    assert "resource_metadata" not in challenge


def test_revoked_and_expired_tokens_are_401_with_their_reason(world):
    db, runtime, _ = world
    _, expired = db.create(app="claude", label="", scopes=["search"], expires_in_days=7,
                           now=datetime.now(timezone.utc) - timedelta(days=8))
    gone, revoked = db.create(app="claude", label="", scopes=["search"], expires_in_days=7)
    db.revoke(gone.id)
    with _client(db, runtime) as c:
        for token, reason in ((expired, "expired"), (revoked, "revoked")):
            resp = c.post(f"/c/{token}/mcp", json=_rpc("tools/list"), headers=H)
            assert resp.status_code == 401 and reason in resp.headers["www-authenticate"]


def test_the_secret_link_and_the_bearer_header_reach_the_same_connector(world):
    db, runtime, _ = world
    connector, token = db.create(app="claude", label="", scopes=["search", "read", "record"], expires_in_days=30)
    init = _rpc("initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                               "clientInfo": {"name": "claude-ai", "version": "1"}})
    with _client(db, runtime) as c:
        assert c.post(f"/c/{token}/mcp", json=init, headers=H).status_code == 200
        via_link = _names(c.post(f"/c/{token}/mcp", json=_rpc("tools/list", i=2), headers=H))
        via_header = _names(c.post("/mcp", json=_rpc("tools/list", i=3),
                                   headers={**H, "Authorization": f"Bearer {token}"}))
    assert via_link == via_header == sorted(catalog.tool_names_for(catalog.DEFAULT_SCOPES))
    assert not set(via_link) & catalog.NEVER_REMOTE
    assert db.get(connector.id).last_client == "claude-ai" and db.get(connector.id).use_count == 3


def test_a_search_only_connector_sees_three_tools_and_is_refused_the_rest(world):
    db, runtime, _ = world
    _, token = db.create(app="perplexity", label="", scopes=["search"], expires_in_days=30)
    with _client(db, runtime) as c:
        listed = _names(c.post(f"/c/{token}/mcp", json=_rpc("tools/list"), headers=H))
        call = c.post(f"/c/{token}/mcp", json=_rpc("tools/call", {"name": "cicada_save_episode",
                                                                  "arguments": {"content": "x"}}), headers=H)
    assert listed == ["cicada_handshake", "cicada_open_hub", "cicada_recall"]
    result = call.json()["result"]
    assert result["isError"] is True and result["content"][0]["text"] == DENIED_TEXT


def test_a_browser_origin_is_refused(world):
    db, runtime, _ = world
    _, token = db.create(app="claude", label="", scopes=["search"], expires_in_days=30)
    with _client(db, runtime) as c:
        resp = c.post(f"/c/{token}/mcp", json=_rpc("tools/list"), headers={**H, "Origin": "https://evil.example"})
    assert resp.status_code == 403


def test_the_rate_limit_answers_429_with_retry_after(world):
    db, runtime, _ = world
    _, token = db.create(app="claude", label="", scopes=["search"], expires_in_days=30)
    clock = [1000.0]
    limits = remote_app.Limits(per_minute=2, clock=lambda: clock[0])
    with _client(db, runtime, limits) as c:
        codes = [c.post(f"/c/{token}/mcp", json=_rpc("tools/list", i=n), headers=H).status_code for n in range(3)]
        last = c.post(f"/c/{token}/mcp", json=_rpc("tools/list", i=9), headers=H)
    assert codes == [200, 200, 429] and int(last.headers["retry-after"]) >= 1


def test_an_oversized_body_is_refused(world):
    db, runtime, _ = world
    _, token = db.create(app="claude", label="", scopes=["record"], expires_in_days=30)
    huge = _rpc("tools/call", {"name": "cicada_save_episode", "arguments": {"content": "x" * (remote_app.MAX_BODY_BYTES + 10)}})
    with _client(db, runtime) as c:
        assert c.post(f"/c/{token}/mcp", json=huge, headers=H).status_code == 413


def test_the_2026_07_28_era_is_served_too(world):
    db, runtime, _ = world
    _, token = db.create(app="claude-code", label="", scopes=["search"], expires_in_days=30)
    meta = {"io.modelcontextprotocol/protocolVersion": "2026-07-28",
            "io.modelcontextprotocol/clientInfo": {"name": "claude-code", "version": "3"},
            "io.modelcontextprotocol/clientCapabilities": {}}
    headers = {**H, "Mcp-Protocol-Version": "2026-07-28", "Mcp-Method": "tools/list",
               "Authorization": f"Bearer {token}"}
    with _client(db, runtime) as c:
        resp = c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"_meta": meta}},
                      headers=headers)
    assert resp.status_code == 200
    assert sorted(t["name"] for t in resp.json()["result"]["tools"]) == ["cicada_handshake", "cicada_open_hub",
                                                                           "cicada_recall"]


def test_protected_resource_metadata_is_public_and_names_cicada(world):
    db, runtime, _ = world
    with _client(db, runtime) as c:
        resp = c.get("/.well-known/oauth-protected-resource/mcp", headers={"Host": "mac.example-tailnet.ts.net"})
    body = resp.json()
    assert resp.status_code == 200 and body["resource_name"] == "Cicada"
    assert body["resource"] == "https://mac.example-tailnet.ts.net/mcp" and "authorization_servers" not in body


def test_the_instructions_name_only_the_handshake(world):
    db, runtime, _ = world
    _, token = db.create(app="claude", label="", scopes=["search"], expires_in_days=30)
    # `clientInfo.version` is required by the spec (Implementation); the SDK
    # answers -32602 without it, so the fixture carries one.
    init = _rpc("initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                               "clientInfo": {"name": "x", "version": "1"}})
    with _client(db, runtime) as c:
        text = c.post(f"/c/{token}/mcp", json=init, headers=H).json()["result"]["instructions"]
    assert set(re.findall(r"cicada_[a-z_]+", text)) == {"cicada_handshake"}


def test_a_remote_write_over_http_commits_as_its_app(world):
    db, runtime, memory = world
    _, token = db.create(app="chatgpt", label="", scopes=["record"], expires_in_days=30)
    with _client(db, runtime) as c:
        resp = c.post(f"/c/{token}/mcp", json=_rpc("tools/call", {"name": "cicada_save_episode",
                      "arguments": {"content": "a plan worth keeping", "title": "plan"}}), headers=H)
    assert resp.json()["result"]["isError"] is False
    body = subprocess.run(["git", "-C", str(memory), "log", "-1", "--format=%B"], capture_output=True, text=True).stdout
    assert "Cicada-Author: chatgpt" in body and "trigger: remote/chatgpt" in body


def test_no_token_ever_reaches_a_log(world, caplog):
    db, runtime, _ = world
    _, token = db.create(app="claude", label="", scopes=["search"], expires_in_days=30)
    # The whole 43-char secret, via the one token grammar. Never `rsplit("_")`:
    # base64url secrets contain "_" about half the time, and the tail after the
    # last one can be a single character that any log line contains.
    secret = catalog.TOKEN_RE.match(token).group(2)
    seen: list[str] = []
    sink = logger.add(lambda m: seen.append(str(m)), level="DEBUG")
    caplog.set_level(logging.DEBUG)
    try:
        with _client(db, runtime) as c:
            c.post(f"/c/{token}/mcp", json=_rpc("tools/list"), headers=H)
            c.post(f"/c/{token}x/mcp", json=_rpc("tools/list"), headers=H)
            c.post(f"/c/{token}/mcp", json=_rpc("tools/call", {"name": "cicada_recall", "arguments": {"query": "alpha"}}), headers=H)
    finally:
        logger.remove(sink)
    everything = "\n".join(seen) + "\n".join(r.getMessage() for r in caplog.records)
    assert token not in everything and secret not in everything
