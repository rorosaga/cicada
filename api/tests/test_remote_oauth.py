"""Ruling 31 — sign-in for the remote connector, over real HTTP in process (no network, no tunnel): discovery,
registration (DCR and CIMD), consent in the app only, PKCE, single-use codes, rotating refresh tokens, revocation,
rate limits, the Origin rule, the audience check, nothing in the clear at rest and nothing in a log."""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest
from loguru import logger
from starlette.testclient import TestClient

from _synthetic_bank import _bank
from api import config
from api.remote import app as remote_app
from api.remote import oauth, store
from api.remote.runtime import RemoteRuntime

BASE = "https://testserver"
CLAUDE_CB = "https://claude.ai/api/mcp/auth_callback"
H = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json",
     "Mcp-Protocol-Version": "2025-11-25"}
FORM = {"Content-Type": "application/x-www-form-urlencoded"}


def _pkce():
    verifier = secrets.token_urlsafe(48)
    return verifier, oauth.pkce_challenge(verifier)


class Clock:
    def __init__(self):
        self.now = datetime.now(timezone.utc)

    def __call__(self):
        return self.now


@pytest.fixture
def world(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    db = store.ConnectorStore(tmp_path / "remote" / "connectors.db")
    clock = Clock()
    docs: dict[str, bytes] = {}

    async def fetcher(url):
        return docs.get(url)

    server = oauth.OAuthServer(db.path, connectors=db, fetcher=fetcher, clock=clock)
    runtime = RemoteRuntime(post=lambda p, d: {"status": "resolved"}, sleep_running=lambda: False)
    yield db, server, runtime, clock, docs
    config.get_settings.cache_clear()


def _client(world, limits=None):
    db, server, runtime, _, _ = world
    app = remote_app.build_app(db, runtime=runtime, limits=limits, oauth=server)
    return TestClient(app, base_url=BASE, follow_redirects=False)


def _register(c, **extra):
    body = {"redirect_uris": [CLAUDE_CB], "token_endpoint_auth_method": "none", "client_name": "Claude",
            "grant_types": ["authorization_code", "refresh_token"], **extra}
    resp = c.post("/register", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _authorize(c, client_id, challenge, *, redirect=CLAUDE_CB, state="st-123", headers=None, **extra):
    params = {"response_type": "code", "client_id": client_id, "redirect_uri": redirect,
              "code_challenge": challenge, "code_challenge_method": "S256", "state": state,
              "resource": f"{BASE}/mcp", "scope": "search read record offline_access", **extra}
    return c.get("/authorize", params=params, headers=headers)


def _handle(page) -> str:
    return re.search(r"url=/authorize/wait\?r=([A-Za-z0-9_-]+)", page.text).group(1)


def _code(page) -> str:
    """The code the person reads on their own browser's page — the only thing that approves a sign-in."""
    return re.search(r'<div class="code">([A-Z0-9]{4}-[A-Z0-9]{4})</div>', page.text).group(1)


def _signed_in(world, c, *, scopes=("search", "read", "record"), state="st-123", client=None):
    """The whole happy path: register, authorize, the person approves in the app, collect, exchange."""
    _, server, _, _, _ = world
    client = client or _register(c)
    verifier, challenge = _pkce()
    page = _authorize(c, client["client_id"], challenge, state=state)
    assert page.status_code == 200
    connector = server.approve(_code(page), scopes=list(scopes), expires_in_days=30)
    back = c.get("/authorize/wait", params={"r": _handle(page)})
    assert back.status_code == 302
    query = parse_qs(urlparse(back.headers["location"]).query)
    tokens = c.post("/token", headers=FORM, data={
        "grant_type": "authorization_code", "code": query["code"][0], "redirect_uri": CLAUDE_CB,
        "client_id": client["client_id"], "code_verifier": verifier, "resource": f"{BASE}/mcp"}).json()
    return client, connector, tokens, query


def _tools(c, token):
    resp = c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
                  headers={**H, "Authorization": f"Bearer {token}"})
    return resp


# ── discovery ───────────────────────────────────────────────────────────────

def test_discovery_names_this_listener_as_the_authorization_server(world):
    with _client(world) as c:
        prm = c.get("/.well-known/oauth-protected-resource/mcp").json()
        meta = c.get("/.well-known/oauth-authorization-server").json()
        challenge = c.post("/mcp", json={}, headers=H).headers["www-authenticate"]
    assert prm["resource"] == f"{BASE}/mcp" and prm["authorization_servers"] == [BASE]
    assert meta["issuer"] == BASE and meta["code_challenge_methods_supported"] == ["S256"]
    assert meta["client_id_metadata_document_supported"] is True and "none" in meta["token_endpoint_auth_methods_supported"]
    assert meta["authorization_response_iss_parameter_supported"] is True
    assert meta["registration_endpoint"] == f"{BASE}/register" and "offline_access" in meta["scopes_supported"]
    assert f'resource_metadata="{BASE}/.well-known/oauth-protected-resource/mcp"' in challenge


def test_the_listener_still_serves_only_mcp_and_sign_in(world):
    with _client(world) as c:
        for path in ("/", "/docs", "/remote/status", "/healthz", "/graph", "/authorize/other", "/.well-known/x"):
            assert c.get(path).status_code == 404, path
        assert c.get("/token").status_code == 405


# ── the whole flow ──────────────────────────────────────────────────────────

def test_sign_in_end_to_end_reaches_the_tools_the_person_chose(world):
    db, server, _, _, _ = world
    with _client(world) as c:
        client, connector, tokens, query = _signed_in(world, c, scopes=("search",))
        assert query["state"] == ["st-123"] and query["iss"] == [BASE]
        assert tokens["token_type"] == "Bearer" and tokens["expires_in"] <= oauth.ACCESS_TTL_S
        assert tokens["access_token"].startswith("cic_at_") and tokens["refresh_token"].startswith("cic_rt_")
        assert tokens["scope"] == "search"
        listed = _tools(c, tokens["access_token"])
    assert listed.status_code == 200
    assert sorted(t["name"] for t in listed.json()["result"]["tools"]) == [
        "cicada_handshake", "cicada_open_hub", "cicada_recall"]
    row = db.get(connector.id)
    # A registered client is never named or branded by what it claims or where it returns (review of #359).
    assert row.auth == "oauth" and row.app == "other" and row.label == "Unverified app" and row.use_count == 1


def test_the_public_page_only_shows_a_code_and_waits(world):
    _, server, _, _, _ = world
    with _client(world) as c:
        client = _register(c)
        _, challenge = _pkce()
        page = _authorize(c, client["client_id"], challenge)
        code = _code(page)
        assert "claude.ai" in page.text and "Claude" not in page.text  # a registered client's name is its own claim
        assert "<form" not in page.text and "password" not in page.text.lower()
        assert page.headers["x-frame-options"] == "DENY" and "default-src 'none'" in page.headers["content-security-policy"]
        again = c.get("/authorize/wait", params={"r": _handle(page)})
    assert again.status_code == 200 and code in again.text  # still waiting: nothing approved it
    [waiting] = server.waiting()
    assert set(vars(waiting)) == {"ref", "created_at", "expires_at"}  # the app's list carries no code and no name
    found = server.match(code.lower().replace("-", " "))  # typed loosely
    assert found.ref == waiting.ref and not found.verified and found.client_name is None and found.app == "other"
    assert found.redirect_host == "claude.ai" and found.client_registered_at and found.scopes_asked == [
        "search", "read", "record"]
    assert server.match("ZZZZ-ZZZZ") is None and server.match("nonsense") is None


def test_a_denial_goes_back_with_access_denied_state_and_iss(world):
    _, server, _, _, _ = world
    with _client(world) as c:
        client = _register(c)
        _, challenge = _pkce()
        page = _authorize(c, client["client_id"], challenge, state="keep-me")
        server.deny(server.waiting()[0].ref)
        back = c.get("/authorize/wait", params={"r": _handle(page)})
        q = parse_qs(urlparse(back.headers["location"]).query)
        assert back.headers["location"].startswith(CLAUDE_CB + "?")
        assert q["error"] == ["access_denied"] and q["state"] == ["keep-me"] and q["iss"] == [BASE]
        assert c.get("/authorize/wait", params={"r": _handle(page)}).status_code == 400  # once only


# ── redirect URIs and the open-redirect rule ────────────────────────────────

def test_an_unregistered_redirect_is_a_page_never_a_redirect(world):
    with _client(world) as c:
        client = _register(c)
        _, challenge = _pkce()
        for bad in ("https://evil.example/cb", CLAUDE_CB + "/x", CLAUDE_CB + "?x=1", "https://claude.ai.evil.example/api/mcp/auth_callback"):
            resp = _authorize(c, client["client_id"], challenge, redirect=bad)
            assert resp.status_code == 400 and "location" not in resp.headers, bad
        unknown = _authorize(c, "cic_client_nobody", challenge)
    assert unknown.status_code == 400 and "location" not in unknown.headers


def test_loopback_redirects_match_on_any_port_only(world):
    assert oauth.redirect_matches(["http://localhost/callback"], "http://localhost:3118/callback")
    assert oauth.redirect_matches(["http://127.0.0.1/callback"], "http://127.0.0.1:9/callback")
    assert not oauth.redirect_matches(["http://localhost/callback"], "http://localhost:3118/other")
    assert not oauth.redirect_matches(["http://localhost/callback"], "http://127.0.0.1:3118/callback")
    assert not oauth.redirect_matches(["https://app.example/cb"], "https://app.example:444/cb")
    assert not oauth.redirect_matches(["http://localhost/callback"], "http://localhost.evil.example/callback")


def test_registration_refuses_unsafe_redirects_and_methods(world):
    with _client(world) as c:
        for body in ({"redirect_uris": ["http://example.com/cb"]}, {"redirect_uris": ["https://a.example/cb#x"]},
                     {"redirect_uris": []}, {"redirect_uris": ["https://user:pw@a.example/cb"]},
                     {"redirect_uris": [CLAUDE_CB], "token_endpoint_auth_method": "private_key_jwt"},
                     {"redirect_uris": [CLAUDE_CB], "grant_types": ["client_credentials"]}):
            assert c.post("/register", json=body).status_code == 400, body


# ── PKCE and the code ───────────────────────────────────────────────────────

def test_pkce_s256_is_required_and_verified(world):
    _, server, _, _, _ = world
    with _client(world) as c:
        client = _register(c)
        verifier, challenge = _pkce()
        for extra in ({"code_challenge_method": "plain"}, {"code_challenge": ""}):
            resp = _authorize(c, client["client_id"], challenge, **extra)
            q = parse_qs(urlparse(resp.headers["location"]).query)
            assert q["error"] == ["invalid_request"] and q["iss"] == [BASE]
        page = _authorize(c, client["client_id"], challenge)
        server.approve(_code(page), scopes=["search"], expires_in_days=7)
        code = parse_qs(urlparse(c.get("/authorize/wait", params={"r": _handle(page)}).headers["location"]).query)["code"][0]
        wrong = c.post("/token", headers=FORM, data={"grant_type": "authorization_code", "code": code,
                                                     "redirect_uri": CLAUDE_CB, "client_id": client["client_id"],
                                                     "code_verifier": secrets.token_urlsafe(48)})
    assert wrong.status_code == 400 and wrong.json()["error"] == "invalid_grant"


def test_a_code_is_single_use_and_a_replay_revokes_what_it_issued(world):
    with _client(world) as c:
        client, _, tokens, query = _signed_in(world, c)
        verifier_guess = "x" * 43
        replay = c.post("/token", headers=FORM, data={
            "grant_type": "authorization_code", "code": query["code"][0], "redirect_uri": CLAUDE_CB,
            "client_id": client["client_id"], "code_verifier": verifier_guess})
        assert replay.status_code == 400 and replay.json()["error"] == "invalid_grant"
        assert _tools(c, tokens["access_token"]).status_code == 401
        refreshed = c.post("/token", headers=FORM, data={"grant_type": "refresh_token",
                                                         "refresh_token": tokens["refresh_token"],
                                                         "client_id": client["client_id"]})
    assert refreshed.json()["error"] == "invalid_grant"


def test_a_code_expires_and_is_bound_to_its_client_and_redirect(world):
    _, server, _, clock, _ = world
    with _client(world) as c:
        client, other = _register(c), _register(c)
        codes = []
        for _ in range(3):
            verifier, challenge = _pkce()
            page = _authorize(c, client["client_id"], challenge)
            server.approve(_code(page), scopes=["search"], expires_in_days=7)
            loc = c.get("/authorize/wait", params={"r": _handle(page)}).headers["location"]
            codes.append((parse_qs(urlparse(loc).query)["code"][0], verifier))

        def exchange(code, verifier, **over):
            data = {"grant_type": "authorization_code", "code": code, "redirect_uri": CLAUDE_CB,
                    "client_id": client["client_id"], "code_verifier": verifier, **over}
            return c.post("/token", headers=FORM, data=data).json()

        assert exchange(*codes[0], client_id=other["client_id"])["error"] == "invalid_grant"
        assert exchange(*codes[1], redirect_uri=CLAUDE_CB + "/")["error"] == "invalid_grant"
        clock.now += timedelta(seconds=oauth.CODE_TTL_S + 1)
        assert exchange(*codes[2])["error"] == "invalid_grant"


def test_the_waiting_page_is_bound_to_its_browser(world):
    _, server, _, _, _ = world
    with _client(world) as c:
        client = _register(c)
        _, challenge = _pkce()
        page = _authorize(c, client["client_id"], challenge)
        server.approve(_code(page), scopes=["search"], expires_in_days=7)
        handle = _handle(page)
    with _client(world) as stranger:  # the request id alone, without the browser's cookie
        assert stranger.get("/authorize/wait", params={"r": handle}).status_code == 400
        stranger.cookies.set(oauth.COOKIE, "forged")
        assert stranger.get("/authorize/wait", params={"r": handle}).status_code == 400


def test_a_request_nobody_approves_expires(world):
    _, server, _, clock, _ = world
    with _client(world) as c:
        client = _register(c)
        _, challenge = _pkce()
        page = _authorize(c, client["client_id"], challenge)
        clock.now += timedelta(seconds=oauth.REQUEST_TTL_S + 1)
        assert server.waiting() == []
        with pytest.raises(KeyError):
            server.approve(_code(page), scopes=["search"], expires_in_days=7)
        assert "expired" in c.get("/authorize/wait", params={"r": _handle(page)}).text


# ── refresh, revocation, audience ───────────────────────────────────────────

def test_refresh_tokens_rotate_and_a_reused_one_ends_the_grant(world):
    _, _, _, clock, _ = world
    with _client(world) as c:
        client, _, first, _ = _signed_in(world, c)

        def refresh(token):
            return c.post("/token", headers=FORM, data={"grant_type": "refresh_token", "refresh_token": token,
                                                        "client_id": client["client_id"]})

        second = refresh(first["refresh_token"]).json()
        assert second["refresh_token"] != first["refresh_token"] and _tools(c, second["access_token"]).status_code == 200
        clock.now += timedelta(seconds=oauth.REFRESH_REUSE_GRACE_S + 1)
        stolen = refresh(first["refresh_token"])
        assert stolen.status_code == 400 and stolen.json()["error"] == "invalid_grant"
        assert refresh(second["refresh_token"]).json()["error"] == "invalid_grant"  # the whole grant ended
        assert _tools(c, second["access_token"]).status_code == 401


def test_revoking_in_settings_ends_access_and_refresh(world):
    db, _, _, _, _ = world
    with _client(world) as c:
        client, connector, tokens, _ = _signed_in(world, c)
        db.revoke(connector.id)
        assert _tools(c, tokens["access_token"]).status_code == 401
        assert c.post("/token", headers=FORM, data={"grant_type": "refresh_token", "client_id": client["client_id"],
                                                    "refresh_token": tokens["refresh_token"]}).json()["error"] == "invalid_grant"


def test_rfc7009_revocation_by_the_app(world):
    with _client(world) as c:
        client, _, tokens, _ = _signed_in(world, c)
        assert c.post("/revoke", headers=FORM, data={"token": tokens["refresh_token"],
                                                     "client_id": client["client_id"]}).status_code == 200
        assert _tools(c, tokens["access_token"]).status_code == 401


def test_an_access_token_is_only_good_for_this_resource(world):
    with _client(world) as c:
        _, _, tokens, _ = _signed_in(world, c)
        elsewhere = c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
                           headers={**H, "Authorization": f"Bearer {tokens['access_token']}",
                                    "Host": "other.example.ts.net"})
        client = _register(c)
        _, challenge = _pkce()
        target = _authorize(c, client["client_id"], challenge, resource="https://other.example/mcp")
    assert elsewhere.status_code == 401
    assert parse_qs(urlparse(target.headers["location"]).query)["error"] == ["invalid_target"]


def test_an_expired_access_token_is_refused(world):
    _, server, _, clock, _ = world
    with _client(world) as c:
        _, _, tokens, _ = _signed_in(world, c)
        clock.now += timedelta(seconds=oauth.ACCESS_TTL_S + 1)
        resp = _tools(c, tokens["access_token"])
    assert resp.status_code == 401 and 'error="invalid_token"' in resp.headers["www-authenticate"]


# ── confidential clients ────────────────────────────────────────────────────

def test_a_confidential_client_must_authenticate_the_way_it_registered(world):
    with _client(world) as c:
        client = _register(c, token_endpoint_auth_method="client_secret_basic")
        assert client["client_secret"]
        basic = base64.b64encode(f"{client['client_id']}:wrong".encode()).decode()
        bad = c.post("/token", headers={**FORM, "Authorization": f"Basic {basic}"},
                     data={"grant_type": "refresh_token", "refresh_token": "x"})
        posted = c.post("/token", headers=FORM, data={"grant_type": "refresh_token", "refresh_token": "x",
                                                      "client_id": client["client_id"],
                                                      "client_secret": client["client_secret"]})
        none = c.post("/token", headers=FORM, data={"grant_type": "refresh_token", "refresh_token": "x",
                                                    "client_id": client["client_id"]})
    assert bad.status_code == 401 and bad.json()["error"] == "invalid_client"
    assert posted.status_code == 401  # registered for basic: a posted secret is another method
    assert none.status_code == 401


# ── CIMD ────────────────────────────────────────────────────────────────────

def test_a_client_id_metadata_document_is_fetched_checked_and_cached(world):
    _, server, _, _, docs = world
    url = "https://claude.ai/oauth/claude-code-client-metadata"
    docs[url] = json.dumps({"client_id": url, "client_name": "Claude Code",
                            "redirect_uris": ["http://localhost/callback", "http://127.0.0.1/callback"],
                            "token_endpoint_auth_method": "none"}).encode()
    with _client(world) as c:
        verifier, challenge = _pkce()
        page = _authorize(c, url, challenge, redirect="http://localhost:3118/callback")
        assert page.status_code == 200
        found = server.match(_code(page))
        assert found.app == "claude-code" and found.loopback and found.client_host == "claude.ai" and found.verified
        assert found.client_name == "Claude Code"
        del docs[url]  # cached: the second sign-in does not fetch again
        assert _authorize(c, url, challenge, redirect="http://127.0.0.1:5/callback").status_code == 200


@pytest.mark.parametrize("doc", [
    {"client_id": "https://app.example/other", "redirect_uris": [CLAUDE_CB]},
    {"client_id": "https://app.example/meta", "redirect_uris": ["http://app.example/cb"]},
    {"client_id": "https://app.example/meta", "redirect_uris": [CLAUDE_CB],
     "token_endpoint_auth_methods_supported": ["private_key_jwt"]},
])
def test_a_bad_metadata_document_is_an_unknown_client(world, doc):
    _, _, _, _, docs = world
    docs["https://app.example/meta"] = json.dumps(doc).encode()
    with _client(world) as c:
        _, challenge = _pkce()
        resp = _authorize(c, "https://app.example/meta", challenge)
    assert resp.status_code == 400 and "location" not in resp.headers


def test_the_real_document_fetch_goes_through_net_guard():
    import asyncio

    for url in ("https://127.0.0.1/meta", "https://10.0.0.5/meta", "https://[::1]/meta", "https://100.100.1.1/meta"):
        assert asyncio.run(oauth.fetch_metadata_document(url)) is None, url


# ── rate limits and the Origin rule ─────────────────────────────────────────

def test_registration_and_authorization_are_limited_without_sending_the_person_to_approve(world):
    _, server, _, _, _ = world
    with _client(world) as c:
        codes = [c.post("/register", json={"redirect_uris": [CLAUDE_CB]}).status_code for _ in range(12)]
        assert codes.count(201) == 10 and codes[-1] == 429
    server.limits = oauth.OAuthLimits.default()
    with _client(world) as c:
        client = _register(c)
        _, challenge = _pkce()
        one_source = [_authorize(c, client["client_id"], challenge).status_code for _ in range(11)]
        assert one_source[:10] == [200] * 10 and one_source[-1] == 429
        refused = _authorize(c, client["client_id"], challenge)
        assert "approve" not in refused.text.lower() and "waiting" not in refused.text.lower()
        other = _authorize(c, client["client_id"], challenge, headers={"X-Forwarded-For": "198.51.100.7"})
    assert other.status_code == 200  # another source is not locked out by the first one's flood


def test_a_full_queue_evicts_the_flooders_requests_not_the_persons(world, monkeypatch):
    _, server, _, _, _ = world
    monkeypatch.setattr(oauth, "MAX_PENDING", 6)
    with _client(world) as c:
        client = _register(c)
        _, challenge = _pkce()
        owner = _authorize(c, client["client_id"], challenge, headers={"X-Forwarded-For": "203.0.113.9"})
        flood = [_authorize(c, client["client_id"], challenge, headers={"X-Forwarded-For": "192.0.2.1"})
                 for _ in range(9)]
        assert all(f.status_code == 200 for f in flood) and len(server.waiting()) == 6
        assert server.match(_code(owner)) is not None  # the person's one request survived the flood
        assert server._request_by_handle(_handle(flood[0]))["status"] == "evicted"  # the flood's own went
        assert server._request_by_handle(_handle(owner))["status"] == "pending"


def test_the_review_probe_a_stranger_cannot_get_a_sign_in_approved(world):
    """Security review of #359, the probe kept as a regression test: a stranger registers an app called "Claude"
    returning to claude.ai, floods the queue, and waits for the person to approve the look-alike. The person sees no
    clickable look-alike, approves by the code on their own page, and the stranger never obtains a code or a token."""
    _, server, _, _, _ = world
    with _client(world) as attacker:
        evil = _register(attacker)  # client_name "Claude", claude.ai's callback — anyone may register this
        flows = []
        for i in range(oauth.MAX_PENDING):
            verifier, challenge = _pkce()
            page = _authorize(attacker, evil["client_id"], challenge, headers={"X-Forwarded-For": f"192.0.2.{i % 9}"})
            assert page.status_code == 200
            flows.append((verifier, _handle(page)))
        with _client(world) as owner:
            real = _register(owner)
            verifier, challenge = _pkce()
            mine = _authorize(owner, real["client_id"], challenge, headers={"X-Forwarded-For": "203.0.113.9"})
            assert mine.status_code == 200  # never locked out, never told to approve what waits
            listed = server.waiting()
            assert all(set(vars(w)) == {"ref", "created_at", "expires_at"} for w in listed)
            with pytest.raises(KeyError):
                server.approve("", scopes=["search"], expires_in_days=7)
            server.approve(_code(mine), scopes=["search"], expires_in_days=7)  # the person types their own code
            back = owner.get("/authorize/wait", params={"r": _handle(mine)})
            assert back.status_code == 302 and "code=" in back.headers["location"]
        for verifier, handle in flows:
            resp = attacker.get("/authorize/wait", params={"r": handle})
            assert "location" not in resp.headers  # still waiting or evicted: no code ever reaches the stranger
        assert server.match(_code(mine)) is None  # the person's code is spent


def test_a_spent_token_bucket_still_lets_a_valid_refresh_through(world, monkeypatch):
    monkeypatch.setattr(oauth, "TOKEN_PER_CLIENT_PER_MINUTE", 2)
    with _client(world) as c:
        client, _, tokens, _ = _signed_in(world, c)  # the exchange took one
        spam = [c.post("/token", headers=FORM, data={"grant_type": "refresh_token", "client_id": client["client_id"],
                                                     "refresh_token": "cic_rt_bogus"}).status_code for _ in range(3)]
        assert spam[-1] == 429
        ok = c.post("/token", headers=FORM, data={"grant_type": "refresh_token", "client_id": client["client_id"],
                                                  "refresh_token": tokens["refresh_token"]})
        other = _register(c)
        fresh = c.post("/token", headers=FORM, data={"grant_type": "refresh_token", "client_id": other["client_id"],
                                                     "refresh_token": "cic_rt_bogus"})
    assert ok.status_code == 200 and ok.json()["access_token"].startswith("cic_at_")
    assert fresh.status_code == 400  # another client's bucket is its own


def test_a_full_client_table_drops_the_oldest_grantless_client(world, monkeypatch):
    _, server, _, _, _ = world
    monkeypatch.setattr(oauth, "MAX_CLIENTS", 3)
    server.limits = oauth.OAuthLimits.default()
    with _client(world) as c:
        client, _, _, _ = _signed_in(world, c)  # has a grant: never dropped
        first = _register(c)
        ids = [_register(c)["client_id"] for _ in range(4)]
    assert server.get_client(client["client_id"]) is not None
    assert server.get_client(first["client_id"]) is None and server.get_client(ids[-1]) is not None


@pytest.mark.parametrize("bad", [CLAUDE_CB.replace("/api/", "\\api/"), "https://claude.ai:99999/cb",
                                 "https://claude.ai:x/cb", CLAUDE_CB + "\x01", CLAUDE_CB + "\x7f"])
def test_a_presented_redirect_with_odd_characters_is_refused(world, bad):
    assert not oauth.redirect_matches([bad, CLAUDE_CB], bad)  # refused even if it were registered
    with _client(world) as c:
        client = _register(c)
        _, challenge = _pkce()
        resp = _authorize(c, client["client_id"], challenge, redirect=bad)
    assert resp.status_code == 400 and "location" not in resp.headers


def test_refresh_reuse_also_revokes_the_connector_so_settings_shows_it(world):
    db, _, _, clock, _ = world
    with _client(world) as c:
        client, connector, first, _ = _signed_in(world, c)
        c.post("/token", headers=FORM, data={"grant_type": "refresh_token", "client_id": client["client_id"],
                                             "refresh_token": first["refresh_token"]})
        clock.now += timedelta(seconds=oauth.REFRESH_REUSE_GRACE_S + 1)
        c.post("/token", headers=FORM, data={"grant_type": "refresh_token", "client_id": client["client_id"],
                                             "refresh_token": first["refresh_token"]})
    assert db.get(connector.id).state() == "revoked"


def test_the_metadata_fetch_has_one_overall_deadline(world, monkeypatch):
    import asyncio

    _, server, _, _, _ = world
    monkeypatch.setattr(oauth, "CIMD_TIMEOUT_S", 0.2)

    async def slow(url):
        await asyncio.sleep(5)
        return b"{}"

    server.fetcher = slow
    started = datetime.now()
    assert asyncio.run(server.resolve_client("https://slow.example/meta")) is None
    assert (datetime.now() - started).total_seconds() < 2


def test_origin_is_refused_everywhere_but_the_sign_in_pages(world):
    with _client(world) as c:
        evil = {"Origin": "https://evil.example"}
        assert c.post("/register", json={"redirect_uris": [CLAUDE_CB]}, headers=evil).status_code == 403
        assert c.post("/token", headers={**FORM, **evil}, data={"grant_type": "refresh_token"}).status_code == 403
        client = _register(c)
        _, challenge = _pkce()
        params = {"response_type": "code", "client_id": client["client_id"], "redirect_uri": CLAUDE_CB,
                  "code_challenge": challenge, "code_challenge_method": "S256"}
        assert c.get("/authorize", params=params, headers=evil).status_code == 200


def test_the_token_endpoint_takes_only_a_form(world):
    with _client(world) as c:
        resp = c.post("/token", json={"grant_type": "refresh_token"})
    assert resp.status_code == 400 and resp.json()["error"] == "invalid_request"


# ── nothing in the clear ────────────────────────────────────────────────────

def test_tokens_codes_and_secrets_are_hashed_at_rest_and_never_logged(world, caplog):
    db, _, _, _, _ = world
    seen: list[str] = []
    sink = logger.add(lambda m: seen.append(str(m)), level="DEBUG")
    caplog.set_level(logging.DEBUG)
    try:
        with _client(world) as c:
            confidential = _register(c, token_endpoint_auth_method="client_secret_post")
            client, _, tokens, query = _signed_in(world, c, state="opaque-state-value")
            refreshed = c.post("/token", headers=FORM, data={"grant_type": "refresh_token", "client_id": client["client_id"],
                                                             "refresh_token": tokens["refresh_token"]}).json()
            _tools(c, refreshed["access_token"])
    finally:
        logger.remove(sink)
    secrets_seen = [tokens["access_token"], tokens["refresh_token"], refreshed["access_token"],
                    refreshed["refresh_token"], query["code"][0], confidential["client_secret"]]
    raw = b"".join(p.read_bytes() for p in db.path.parent.iterdir() if p.is_file())
    logs = "\n".join(seen) + "\n".join(r.getMessage() for r in caplog.records)
    for value in secrets_seen:
        assert value.encode() not in raw and value not in logs
    assert hashlib.sha256(tokens["access_token"].encode()).hexdigest().encode() in raw
    assert b"opaque-state-value" not in raw  # the client's state is dropped once the code is used


# ── the app's side ──────────────────────────────────────────────────────────

def test_the_app_approves_and_denies_through_the_loopback_api(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient as ApiClient

    from api import main
    from api.routers import remote as remote_router

    home = tmp_path / "home"
    monkeypatch.setenv("CICADA_HOME", str(home))
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(_bank(tmp_path)))
    config.get_settings.cache_clear()
    db = store.ConnectorStore()
    server = oauth.OAuthServer(db.path, connectors=db)
    client = server.register({"redirect_uris": ["https://chatgpt.com/connector_platform_oauth_redirect"],
                              "token_endpoint_auth_method": "none", "client_name": "ChatGPT"})
    found = server.get_client(client["client_id"])
    first = server.start_request(client=found, redirect_uri=found.redirect_uris[0], code_challenge="a" * 43,
                                 state=None, resource="https://x.example/mcp", scopes_asked=["search"])
    server.start_request(client=found, redirect_uri=found.redirect_uris[0], code_challenge="a" * 43,
                         state=None, resource="https://x.example/mcp", scopes_asked=[])
    third = server.start_request(client=found, redirect_uri=found.redirect_uris[0], code_challenge="a" * 43,
                                 state=None, resource="https://x.example/mcp", scopes_asked=[])
    api = ApiClient(main.app)
    listed = api.get("/remote/oauth/requests").json()
    assert len(listed) == 3 and all(set(r) == {"ref", "createdAt", "expiresAt"} for r in listed)  # no code, no name
    matched = api.post("/remote/oauth/match", json={"userCode": first[2].lower()}).json()
    assert matched["verified"] is False and matched["clientName"] is None and matched["app"] == "other"
    assert matched["redirectHost"] == "chatgpt.com" and matched["clientRegisteredAt"] and "userCode" not in matched
    assert api.post("/remote/oauth/match", json={"userCode": "ZZZZ-ZZZZ"}).status_code == 404
    made = api.post("/remote/oauth/approve", json={"userCode": first[2], "scopes": ["search", "record"],
                                                   "expiresInDays": 7}).json()
    assert made["auth"] == "oauth" and made["app"] == "other" and made["scopes"] == ["record", "search"]
    assert made["label"] == "Unverified app"
    assert api.post("/remote/oauth/approve", json={"userCode": first[2], "scopes": ["search"],
                                                   "expiresInDays": 7}).status_code == 404  # answered already
    assert api.post("/remote/oauth/approve", json={"userCode": third[2], "scopes": ["search"],
                                                   "expiresInDays": 365}).status_code == 400  # every connector expires
    waiting = api.get("/remote/oauth/requests").json()
    assert api.post(f"/remote/oauth/requests/{waiting[0]['ref']}/deny").status_code == 200
    assert api.post("/remote/oauth/requests/deny-all").json()["count"] == 1
    assert api.get("/remote/oauth/requests").json() == []
    monkeypatch.setattr(remote_router, "_base_or_409", lambda: _async("https://x.example"))
    assert api.post(f"/remote/connectors/{made['id']}/rotate").status_code == 409  # no link to rotate
    config.get_settings.cache_clear()


async def _async(value):
    return value


# ── re-review of #359: availability and look-alikes ─────────────────────────

def test_one_ipv6_block_is_one_source_and_cannot_evict_the_person(world):
    """The re-review's probe: rotating addresses inside one /64 buys nothing."""
    _, server, _, _, _ = world
    assert oauth.source_key("2001:db8::1") == oauth.source_key("2001:db8::ffff:1") == "2001:db8::/64"
    assert oauth.source_key("::ffff:198.51.100.7") == "198.51.100.7"
    with _client(world) as owner:
        real = _register(owner)
        _, challenge = _pkce()
        mine = _authorize(owner, real["client_id"], challenge, headers={"X-Forwarded-For": "198.51.100.7"})
    with _client(world) as attacker:
        evil = _register(attacker)
        statuses = []
        for i in range(70):
            _, challenge = _pkce()
            statuses.append(_authorize(attacker, evil["client_id"], challenge,
                                       headers={"X-Forwarded-For": f"2001:db8::{i:x}"}).status_code)
    assert statuses.count(200) == 10 and statuses.count(429) == 60
    assert server.match(_code(mine)) is not None
    with _client(world) as owner:
        _, challenge = _pkce()
        again = _authorize(owner, real["client_id"], challenge, headers={"X-Forwarded-For": "198.51.100.7"})
    assert again.status_code == 200  # no global ceiling for a flood to spend


def test_junk_client_ids_spend_nothing_and_a_live_code_passes_a_spent_bucket(world, monkeypatch):
    """The re-review's token-drain probe, plus a real client's own bucket spent by someone spamming its id."""
    _, server, _, _, _ = world
    monkeypatch.setattr(oauth, "TOKEN_PER_CLIENT_PER_MINUTE", 2)
    with _client(world) as c:
        client = _register(c)
        verifier, challenge = _pkce()
        page = _authorize(c, client["client_id"], challenge)
        server.approve(_code(page), scopes=["search"], expires_in_days=30)
        back = c.get("/authorize/wait", params={"r": _handle(page)})
        code = parse_qs(urlparse(back.headers["location"]).query)["code"][0]
        junk = [c.post("/token", headers=FORM, data={"grant_type": "authorization_code", "code": "x",
                                                     "client_id": f"junk{i}", "code_verifier": "y"}).status_code
                for i in range(320)]
        assert 429 not in junk and set(junk) == {401}
        spam = [c.post("/token", headers=FORM, data={"grant_type": "authorization_code", "code": "nope",
                                                     "client_id": client["client_id"], "code_verifier": "y"}
                       ).status_code for _ in range(3)]
        assert spam[-1] == 429
        mine = c.post("/token", headers=FORM, data={"grant_type": "authorization_code", "code": code,
                                                    "redirect_uri": CLAUDE_CB, "client_id": client["client_id"],
                                                    "code_verifier": verifier})
    assert mine.status_code == 200 and mine.json()["access_token"].startswith("cic_at_")


@pytest.mark.parametrize("client_id", [
    "https://claude.ai．evil.example/meta",   # full-width dot
    "https://claude.ai。evil.example/meta",   # ideographic full stop
    "https://xn--clude-0ra.ai/meta" if False else "https://cläude.ai/meta",  # an IDN
    "https://claude.ai\\@evil.example/meta",
    "https://claude.ai%2eevil.example/meta",
])
def test_a_look_alike_metadata_host_is_refused_before_any_fetch(world, client_id):
    _, server, _, _, docs = world
    fetched = []

    async def fetcher(url):
        fetched.append(url)
        return json.dumps({"client_id": url, "redirect_uris": [CLAUDE_CB]}).encode()

    server.fetcher = fetcher
    with _client(world) as c:
        _, challenge = _pkce()
        resp = _authorize(c, client_id, challenge)
    assert resp.status_code == 400 and fetched == []
    assert oauth.fetched_host("https://claude.ai/oauth/meta") == "claude.ai"


@pytest.mark.parametrize("raw,shown", [
    ("Claude Code", "Claude Code"),
    ("Claude (published by claude.ai)", None),
    ("Official Claude", None),
    ("Verified ChatGPT", None),
    ("Claude, by Anthropic", None),
    ("claude.ai", "claudeai"),
    ("Tab\tName\n", "Tab Name"),
])
def test_a_documents_name_cannot_claim_a_status_or_a_host(raw, shown):
    assert oauth.clean_name(raw) == shown


def test_the_binding_cookie_is_host_only(world):
    with _client(world) as c:
        client = _register(c)
        _, challenge = _pkce()
        page = _authorize(c, client["client_id"], challenge)
    cookie = page.headers["set-cookie"]
    assert cookie.startswith("__Host-cicada_signin=") and "Path=/;" in cookie + ";" and "Domain" not in cookie
    assert "Secure" in cookie and "HttpOnly" in cookie


def test_metadata_document_clients_are_pruned_like_registered_ones(world):
    _, server, _, clock, docs = world
    url = "https://app.example/meta"
    docs[url] = json.dumps({"client_id": url, "redirect_uris": [CLAUDE_CB]}).encode()
    import asyncio

    assert asyncio.run(server.resolve_client(url)) is not None
    clock.now += timedelta(days=2)
    server._prune_clients(clock.now)
    assert server.get_client(url) is None
