"""Bearer-token auth on the local API (G49 P0 launch blocker)."""
from __future__ import annotations

import os
import stat

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import auth


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path / "memory"))
    monkeypatch.delenv("CICADA_API_TOKEN", raising=False)
    monkeypatch.setenv("CICADA_API_AUTH", "on")
    config.get_settings.cache_clear()
    yield tmp_path / "home"
    config.get_settings.cache_clear()


def test_cicada_home_is_created_private(home):
    path = auth.cicada_home()
    assert path == home
    assert path.is_dir()
    assert stat.S_IMODE(path.stat().st_mode) == 0o700


def test_get_token_generates_once_and_persists(home):
    first = auth.get_token()
    second = auth.get_token()
    assert first == second and len(first) >= 32
    token_file = home / auth.TOKEN_FILE_NAME
    assert token_file.read_text().strip() == first
    assert stat.S_IMODE(token_file.stat().st_mode) == 0o600


def test_env_token_overrides_file(home, monkeypatch):
    monkeypatch.setenv("CICADA_API_TOKEN", "from-env")
    assert auth.get_token() == "from-env"


def test_healthz_is_open_but_status_requires_token(home):
    with TestClient(main.app) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/status").status_code == 401
        ok = client.get("/status", headers={"Authorization": f"Bearer {auth.get_token()}"})
        assert ok.status_code == 200, ok.text


def test_wrong_token_rejected(home):
    with TestClient(main.app) as client:
        resp = client.get("/status", headers={"Authorization": "Bearer nope"})
        assert resp.status_code == 401


def test_non_ascii_bearer_token_is_rejected_not_500(home):
    with TestClient(main.app) as client:
        # httpx/starlette require header values as raw bytes when they aren't
        # pure ASCII (a plain `str` there hits httpx's own ascii-encode step
        # before the request is even sent) — this is "é" UTF-8-encoded, as a
        # real non-ASCII bearer token would arrive on the wire.
        resp = client.get("/status", headers={"Authorization": b"Bearer \xc3\xa9"})
        assert resp.status_code == 401


def test_auth_off_switch_disables_check(home, monkeypatch):
    monkeypatch.setenv("CICADA_API_AUTH", "off")
    with TestClient(main.app) as client:
        assert client.get("/status").status_code == 200


def test_cors_allows_loopback_origins_only(home):
    """A local-only backend has no business echoing `*`: any page the user has
    open could otherwise script requests at localhost:8000 (provider keys,
    logout, memory writes). Native clients send no Origin and are unaffected."""
    with TestClient(main.app) as client:
        for origin in ("http://localhost:5173", "http://127.0.0.1:8000", "https://localhost"):
            resp = client.get("/healthz", headers={"Origin": origin})
            assert resp.headers.get("access-control-allow-origin") == origin, origin

        for origin in ("https://evil.example", "http://localhost.evil.example",
                       "http://notlocalhost:8000"):
            resp = client.get("/healthz", headers={"Origin": origin})
            assert "access-control-allow-origin" not in resp.headers, origin


def test_cors_preflight_still_allows_the_bearer_header_from_loopback(home):
    with TestClient(main.app) as client:
        resp = client.options("/status", headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        })
        assert resp.status_code == 200
        assert resp.headers["access-control-allow-origin"] == "http://localhost:5173"
        assert "authorization" in resp.headers["access-control-allow-headers"].lower()


def test_capture_telegram_is_exempt_from_bearer_check(home):
    """Telegram's servers POST this webhook through a public tunnel and cannot
    send our bearer header, so it's in ``_OPEN_PATHS`` — gated only by its own
    ``CICADA_TELEGRAM_BOT_TOKEN`` check in api/routers/capture.py, never by
    ``require_token``."""
    with TestClient(main.app) as client:
        resp = client.post("/capture/telegram", json={})
        assert resp.json() != {"detail": "missing or invalid bearer token"}
