"""Registry completeness + callback generalization tests (Task 15).

These pin the shape of ``api.services.connectors.ADAPTERS`` itself — every
entry must expose the full adapter contract the module docstring documents —
and confirm the OAuth callback route generalization (§3): every OAuth
adapter is served by the SAME single route, and a state minted for one
connector 4xx's on another's callback.
"""

from __future__ import annotations

import importlib
import inspect
import os
import pkgutil

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.routers import connectors as connectors_router
from api.services import connectors as connectors_package
from api.services.connectors import ADAPTERS, x

REQUIRED_ATTRS = (
    "CHANNEL_ID", "LABEL", "FIELDS", "LOGIN_MODE", "CHANNEL_NOUN", "SECRET_NAMES",
    "is_connected", "credential_fields", "forget", "sync",
)

# Every secret name any adapter could ever write, for the shared teardown
# below — matches the per-adapter `_isolated_home` convention in
# test_connector_{pinterest,reddit,x}.py, just unioned across all of them
# since this file spans every adapter generically.
_ALL_SECRET_NAMES = {name for adapter in ADAPTERS.values() for name in adapter.SECRET_NAMES}


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    """Credentials go to a throwaway $CICADA_HOME — never the real ~/.cicada
    (fix round 1, Nit 2: was popped inline at the end of one test body, which
    leaks env on a mid-test failure and never ran for any other test in this
    file). Also clears X's PKCE verifier store, the other piece of
    module-global state a connector test can leak across the session.
    """
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    for name in _ALL_SECRET_NAMES:
        monkeypatch.delenv(name, raising=False)
    x._pending_verifiers.clear()
    yield
    for name in _ALL_SECRET_NAMES:
        os.environ.pop(name, None)
    x._pending_verifiers.clear()


def test_every_connector_module_is_registered_in_adapters():
    """Fix round 1, L2: the completeness test below only checks modules
    ALREADY in ``ADAPTERS`` — it would say nothing about a new
    ``connectors/<name>.py`` someone forgets to add to the registry, which
    would then be invisible everywhere with no failing test. Scan the
    package directory itself and require every module except the two
    non-adapter ones to be a registered value in ``ADAPTERS``."""
    package_dir = os.path.dirname(connectors_package.__file__)
    module_names = {
        info.name for info in pkgutil.iter_modules([package_dir])
        if not info.ispkg
    }
    non_adapter_modules = {"base"}
    expected_adapter_modules = module_names - non_adapter_modules

    registered_modules = {
        importlib.import_module(f"api.services.connectors.{name}")
        for name in expected_adapter_modules
    }
    assert registered_modules == set(ADAPTERS.values()), (
        f"connectors/{sorted(expected_adapter_modules)} vs ADAPTERS "
        f"{sorted(a.__name__ for a in ADAPTERS.values())} — a module exists "
        f"on disk that ADAPTERS never registered, or vice versa"
    )


@pytest.mark.parametrize("channel_id", list(ADAPTERS))
def test_every_adapter_exposes_the_full_contract_surface(channel_id):
    adapter = ADAPTERS[channel_id]
    for attr in REQUIRED_ATTRS:
        assert hasattr(adapter, attr), f"{channel_id} is missing `{attr}`"
    assert adapter.CHANNEL_ID == channel_id
    assert isinstance(adapter.LABEL, str) and adapter.LABEL
    assert adapter.LOGIN_MODE in ("oauth", "credentials")
    assert isinstance(adapter.CHANNEL_NOUN, str) and adapter.CHANNEL_NOUN
    assert isinstance(adapter.FIELDS, tuple) and adapter.FIELDS
    assert isinstance(adapter.SECRET_NAMES, tuple) and adapter.SECRET_NAMES
    # Every FIELDS name must be covered by SECRET_NAMES — the whole point of
    # declaring SECRET_NAMES separately is that it's a superset (FIELDS plus
    # any derived token), never a subset that would orphan a credential.
    field_names = {f["name"] for f in adapter.FIELDS}
    assert field_names <= set(adapter.SECRET_NAMES)
    assert inspect.iscoroutinefunction(adapter.sync)


@pytest.mark.parametrize(
    "channel_id", [cid for cid, a in ADAPTERS.items() if a.LOGIN_MODE == "oauth"]
)
def test_every_oauth_adapter_exposes_authorize_url_and_exchange_code(channel_id):
    adapter = ADAPTERS[channel_id]
    assert hasattr(adapter, "authorize_url")
    assert hasattr(adapter, "exchange_code")
    assert inspect.iscoroutinefunction(adapter.exchange_code)
    # Callable with just (state) / (code) — base_url and state default, so
    # every OAuth adapter can be driven identically by the router.
    sig = inspect.signature(adapter.authorize_url)
    sig.bind("some-state")
    exchange_sig = inspect.signature(adapter.exchange_code)
    exchange_sig.bind("some-code")


def test_credentials_only_adapters_have_no_oauth_surface():
    for channel_id, adapter in ADAPTERS.items():
        if adapter.LOGIN_MODE == "credentials":
            assert not hasattr(adapter, "authorize_url"), channel_id
            assert not hasattr(adapter, "exchange_code"), channel_id


def test_only_one_callback_route_exists_for_every_oauth_adapter():
    """Task 15 §3: replaces the previous per-connector
    `/pinterest/callback` + `/x/callback` pair with ONE generalized route."""
    callback_routes = [
        r for r in main.app.routes
        if getattr(r, "path", None) == "/sources/connectors/{connector_id}/callback"
    ]
    assert len(callback_routes) == 1
    assert callback_routes[0].endpoint is connectors_router.connector_callback
    # And no connector-specific literal callback route remains registered.
    literal_callback_paths = {
        getattr(r, "path", None) for r in main.app.routes
    } & {f"/sources/connectors/{cid}/callback" for cid in ADAPTERS}
    assert literal_callback_paths == set()


@pytest.fixture
def client(tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    for sub in ("episodes", "entities", "sources"):
        (memory / sub).mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    connectors_router._pending_states.clear()
    config.get_settings.cache_clear()
    yield TestClient(main.app)
    connectors_router._pending_states.clear()
    config.get_settings.cache_clear()


def test_pinterest_and_x_callbacks_are_served_by_the_same_route_function(client):
    from api.services.connectors import pinterest, x

    client.put("/sources/connectors/pinterest/credentials",
               json={"fields": {pinterest.APP_ID_ENV: "id", pinterest.APP_SECRET_ENV: "secret"}})
    client.put("/sources/connectors/x/credentials",
               json={"fields": {x.CLIENT_ID_ENV: "id"}})
    pinterest_state = client.post("/sources/connectors/pinterest/authorize").json()["state"]
    x_state = client.post("/sources/connectors/x/authorize").json()["state"]

    # Both go through /{connector_id}/callback — no code path is reachable
    # instead of raising 400 (no exchange_code monkeypatch means a live
    # network attempt would occur; the missing `code` short-circuits first).
    pinterest_resp = client.get(f"/sources/connectors/pinterest/callback?state={pinterest_state}")
    x_resp = client.get(f"/sources/connectors/x/callback?state={x_state}")
    assert pinterest_resp.status_code == 400
    assert "No authorization code" in pinterest_resp.json()["detail"]
    assert x_resp.status_code == 400
    assert "No authorization code" in x_resp.json()["detail"]


def test_a_credentials_only_connector_rejects_its_callback_route(client):
    resp = client.get("/sources/connectors/reddit/callback?code=abc&state=whatever")
    assert resp.status_code == 400
    assert "credentials" in resp.json()["detail"]


@pytest.mark.parametrize("channel_id", list(ADAPTERS))
def test_forget_removes_every_secret_name_the_adapter_declares(channel_id):
    """Task 15 §4: the orphan-fix — forget() sweeps exactly SECRET_NAMES."""
    from api.services.connections import secrets

    adapter = ADAPTERS[channel_id]
    for name in adapter.SECRET_NAMES:
        secrets.set_secret(name, "placeholder-value")

    adapter.forget()

    for name in adapter.SECRET_NAMES:
        assert not secrets.has_secret(name), f"{channel_id}: {name} survived forget()"
        raw = secrets.secrets_path().read_text(encoding="utf-8") if secrets.secrets_path().exists() else ""
        assert name not in raw, f"{channel_id}: {name} literally still in secrets.env"
