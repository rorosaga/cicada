"""Hermetic tests for /sources/connectors (G71 §2).

No network: the OAuth exchange is monkeypatched. No real credential: every
value below is a placeholder, and the suite asserts that no value is ever
readable back through the API.

Covers both peer connectors — ``ADAPTERS``/``LOGIN_MODES`` are dicts keyed by
``CHANNEL_ID``, so Pinterest (``oauth``) and Reddit (``credentials``) share
every generic route below; only the OAuth-specific routes are Pinterest-only.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.routers import connectors as connectors_router
from api.services import sync_service
from api.services.connections import secrets
from api.services.connectors import pinterest, reddit


@pytest.fixture
def client(tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    for sub in ("episodes", "entities", "sources"):
        (memory / sub).mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    for name in (pinterest.APP_ID_ENV, pinterest.APP_SECRET_ENV, pinterest.TOKEN_ENV,
                 reddit.CLIENT_ID_ENV, reddit.CLIENT_SECRET_ENV,
                 reddit.USERNAME_ENV, reddit.PASSWORD_ENV):
        monkeypatch.delenv(name, raising=False)
    # Another suite's connections test may have leaked this via
    # secrets.set_secret() (which exports straight into os.environ, outside
    # monkeypatch's revert). Defensive, same convention test_connections_api.py
    # uses for its own env, so test_unknown_field_names_are_rejected's "was
    # never set" assertion is order-independent.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    connectors_router._pending_states.clear()
    config.get_settings.cache_clear()
    yield TestClient(main.app), memory
    connectors_router._pending_states.clear()
    config.get_settings.cache_clear()
    # secrets.set_secret exports straight into os.environ; monkeypatch never
    # made that write so it cannot revert it (see test_connector_pinterest.py).
    for name in (pinterest.APP_ID_ENV, pinterest.APP_SECRET_ENV, pinterest.TOKEN_ENV,
                 reddit.CLIENT_ID_ENV, reddit.CLIENT_SECRET_ENV,
                 reddit.USERNAME_ENV, reddit.PASSWORD_ENV):
        os.environ.pop(name, None)


def test_list_connectors_reports_fields_without_values(client):
    c, _ = client
    body = c.get("/sources/connectors").json()
    ids = [x["id"] for x in body["connectors"]]
    assert ids == ["pinterest", "reddit"]
    pin = body["connectors"][0]
    assert pin["connected"] is False
    assert [f["name"] for f in pin["fields"]] == [pinterest.APP_ID_ENV, pinterest.APP_SECRET_ENV]
    assert all("value" not in f for f in pin["fields"])
    red = body["connectors"][1]
    assert red["loginMode"] == "credentials"
    assert [f["name"] for f in red["fields"]] == [
        reddit.CLIENT_ID_ENV, reddit.CLIENT_SECRET_ENV, reddit.USERNAME_ENV, reddit.PASSWORD_ENV]


def test_saving_credentials_marks_fields_present_but_never_echoes_them(client):
    c, _ = client
    resp = c.put(
        "/sources/connectors/pinterest/credentials",
        json={"fields": {
            pinterest.APP_ID_ENV: "client-id-placeholder",
            pinterest.APP_SECRET_ENV: "client-secret-placeholder",
        }},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["connected"] is False  # app id/secret alone != a token
    assert all(f["present"] for f in body["fields"])
    assert "client-secret-placeholder" not in resp.text


def test_saving_all_reddit_fields_marks_it_connected(client):
    """Reddit has no OAuth token step — filling every declared field IS being
    connected, unlike Pinterest where app id/secret alone is not enough."""
    c, _ = client
    resp = c.put(
        "/sources/connectors/reddit/credentials",
        json={"fields": {
            reddit.CLIENT_ID_ENV: "client-id-placeholder",
            reddit.CLIENT_SECRET_ENV: "client-secret-placeholder",
            reddit.USERNAME_ENV: "example_user",
            reddit.PASSWORD_ENV: "password-placeholder",
        }},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["connected"] is True
    assert all(f["present"] for f in body["fields"])
    assert "password-placeholder" not in resp.text


def test_credentials_land_in_secrets_env_with_0600(client):
    c, _ = client
    c.put("/sources/connectors/pinterest/credentials",
          json={"fields": {pinterest.APP_ID_ENV: "client-id-placeholder"}})
    path = secrets.secrets_path()
    assert path.exists()
    assert oct(path.stat().st_mode)[-3:] == "600"


def test_unknown_field_names_are_rejected(client):
    c, _ = client
    resp = c.put("/sources/connectors/pinterest/credentials",
                 json={"fields": {"OPENAI_API_KEY": "nope"}})
    assert resp.status_code == 422
    assert not secrets.has_secret("OPENAI_API_KEY")


def test_unknown_connector_is_404(client):
    c, _ = client
    assert c.get("/sources/connectors/spotify").status_code == 404
    assert c.post("/sources/connectors/spotify/sync").status_code == 404


def test_authorize_returns_a_url_and_arms_a_single_use_state(client):
    c, _ = client
    c.put("/sources/connectors/pinterest/credentials",
          json={"fields": {pinterest.APP_ID_ENV: "client-id-placeholder",
                           pinterest.APP_SECRET_ENV: "client-secret-placeholder"}})
    body = c.post("/sources/connectors/pinterest/authorize").json()
    assert body["authorizeUrl"].startswith(pinterest.AUTH_URL)
    assert len(connectors_router._pending_states) == 1


def test_authorize_requires_credentials_first(client):
    c, _ = client
    resp = c.post("/sources/connectors/pinterest/authorize")
    assert resp.status_code == 422


def test_authorize_rejects_a_credentials_style_connector(client):
    c, _ = client
    resp = c.post("/sources/connectors/reddit/authorize")
    assert resp.status_code == 400
    assert "credentials" in resp.json()["detail"]


def test_callback_rejects_an_unknown_state_without_exchanging(client, monkeypatch):
    c, _ = client
    called = []

    async def fake_exchange(code, **kwargs):
        called.append(code)

    monkeypatch.setattr(pinterest, "exchange_code", fake_exchange)
    resp = c.get("/sources/connectors/pinterest/callback?code=abc&state=forged")
    assert resp.status_code == 400
    assert called == []


def test_callback_exchanges_once_and_burns_the_state(client, monkeypatch):
    c, _ = client
    c.put("/sources/connectors/pinterest/credentials",
          json={"fields": {pinterest.APP_ID_ENV: "client-id-placeholder",
                           pinterest.APP_SECRET_ENV: "client-secret-placeholder"}})
    state = c.post("/sources/connectors/pinterest/authorize").json()["state"]

    called = []

    async def fake_exchange(code, **kwargs):
        called.append(code)
        secrets.set_secret(pinterest.TOKEN_ENV, "tok-abc")

    monkeypatch.setattr(pinterest, "exchange_code", fake_exchange)
    first = c.get(f"/sources/connectors/pinterest/callback?code=abc&state={state}")
    assert first.status_code == 200
    assert "close this tab" in first.text.lower()
    assert called == ["abc"]

    replay = c.get(f"/sources/connectors/pinterest/callback?code=abc&state={state}")
    assert replay.status_code == 400, "a state is single-use"
    assert called == ["abc"]


def test_callback_is_reachable_without_a_bearer_token():
    """The browser cannot send the API token, so this one route is open —
    which is exactly why it is nonce-gated."""
    from api.services import auth

    assert "/sources/connectors/pinterest/callback" in auth._OPEN_PATHS


def test_sync_now_runs_the_adapter_and_reports_counts(client, monkeypatch):
    c, _ = client

    async def fake_sync(memory_path, **kwargs):
        return {"status": "ok", "reason": None, "new": 3, "seen": 5,
                "boards": 2, "error": None}

    monkeypatch.setattr(pinterest, "sync", fake_sync)
    body = c.post("/sources/connectors/pinterest/sync").json()
    assert body["status"] == "ok"
    assert body["new"] == 3
    assert body["seen"] == 5


def test_reddit_sync_now_runs_the_adapter_and_reports_counts(client, monkeypatch):
    c, _ = client

    async def fake_sync(memory_path, **kwargs):
        return {"status": "ok", "reason": None, "new": 2, "seen": 3, "error": None}

    monkeypatch.setattr(reddit, "sync", fake_sync)
    body = c.post("/sources/connectors/reddit/sync").json()
    assert body["status"] == "ok"
    assert body["new"] == 2
    assert body["seen"] == 3


def test_reddit_disconnect_removes_every_credential(client):
    c, _ = client
    c.put("/sources/connectors/reddit/credentials",
          json={"fields": {reddit.CLIENT_ID_ENV: "client-id-placeholder",
                           reddit.USERNAME_ENV: "example_user"}})
    body = c.delete("/sources/connectors/reddit/credentials").json()
    assert body["connected"] is False
    assert all(f["present"] is False for f in body["fields"])


def test_disconnect_removes_every_credential(client):
    c, _ = client
    c.put("/sources/connectors/pinterest/credentials",
          json={"fields": {pinterest.APP_ID_ENV: "client-id-placeholder"}})
    body = c.delete("/sources/connectors/pinterest/credentials").json()
    assert body["connected"] is False
    assert all(f["present"] is False for f in body["fields"])


# --- fix round 1, M2: credential mutations must reach the SSE version vector ---
#
# Saving/forgetting credentials and Pinterest's token exchange write only to
# secrets.env, entirely outside memory_path, so `sync_service.components()`
# never saw them change — the "sources" component (and therefore the whole
# SSE version vector) stayed identical forever, not just until the next poll
# tick. `sync_state.record_credentials_changed` fixes that by touching
# `sync_state.json`, which the "sources" component already watches.


def test_saving_credentials_bumps_the_sources_sync_component(client):
    c, memory = client
    before = sync_service.components(memory)["sources"]
    resp = c.put("/sources/connectors/pinterest/credentials",
                 json={"fields": {pinterest.APP_ID_ENV: "client-id-placeholder"}})
    assert resp.status_code == 200, resp.text
    after = sync_service.components(memory)["sources"]
    assert after != before


def test_forgetting_credentials_bumps_the_sources_sync_component(client):
    c, memory = client
    c.put("/sources/connectors/pinterest/credentials",
          json={"fields": {pinterest.APP_ID_ENV: "client-id-placeholder"}})
    before = sync_service.components(memory)["sources"]
    resp = c.delete("/sources/connectors/pinterest/credentials")
    assert resp.status_code == 200, resp.text
    after = sync_service.components(memory)["sources"]
    assert after != before


def test_pinterest_token_exchange_bumps_the_sources_sync_component(client, monkeypatch):
    c, memory = client
    c.put("/sources/connectors/pinterest/credentials",
          json={"fields": {pinterest.APP_ID_ENV: "client-id-placeholder",
                           pinterest.APP_SECRET_ENV: "client-secret-placeholder"}})
    state = c.post("/sources/connectors/pinterest/authorize").json()["state"]

    async def fake_exchange(code, **kwargs):
        secrets.set_secret(pinterest.TOKEN_ENV, "tok-abc")

    monkeypatch.setattr(pinterest, "exchange_code", fake_exchange)
    before = sync_service.components(memory)["sources"]
    resp = c.get(f"/sources/connectors/pinterest/callback?code=abc&state={state}")
    assert resp.status_code == 200, resp.text
    after = sync_service.components(memory)["sources"]
    assert after != before
