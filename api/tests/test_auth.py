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


def test_auth_off_switch_disables_check(home, monkeypatch):
    monkeypatch.setenv("CICADA_API_AUTH", "off")
    with TestClient(main.app) as client:
        assert client.get("/status").status_code == 200


def test_capture_telegram_is_exempt_from_bearer_check(home):
    """Telegram's servers POST this webhook through a public tunnel and cannot
    send our bearer header, so it's in ``_OPEN_PATHS`` — gated only by its own
    ``CICADA_TELEGRAM_BOT_TOKEN`` check in api/routers/capture.py, never by
    ``require_token``."""
    with TestClient(main.app) as client:
        resp = client.post("/capture/telegram", json={})
        assert resp.json() != {"detail": "missing or invalid bearer token"}
