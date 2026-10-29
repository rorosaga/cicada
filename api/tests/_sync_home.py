"""Shared fixtures for the G132 phase 1 tests (the home publishes its log) — never collected (underscore prefix).

A synthetic bank (``_synthetic_bank._bank``: placeholder names only), its own ``CICADA_HOME``, auth on, and a helper
that commits by hand the way a person's terminal would. Nothing reaches the network."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from _synthetic_bank import _bank


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True).stdout


def hand_commit(bank: Path, rel: str, text: str, subject: str = "hand edit") -> str:
    path = bank / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    git(bank, "add", "--", rel)
    git(bank, "commit", "-q", "-m", subject)
    return git(bank, "rev-parse", "HEAD").strip()


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def home(tmp_path, monkeypatch):
    """``(client, master token, bank path)`` for a backend with publishing ON."""
    from api import config
    from api.main import app
    from api.services import capture_commit

    bank = _bank(tmp_path)
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    monkeypatch.setenv("CICADA_API_AUTH", "on")
    monkeypatch.setenv("CICADA_SYNC_PUBLISH", "on")
    monkeypatch.delenv("CICADA_API_TOKEN", raising=False)
    monkeypatch.setattr(capture_commit, "AUTOSTART", False)
    config.get_settings.cache_clear()
    from api.services.auth import get_token

    master = get_token()
    with TestClient(app) as client:
        yield client, master, bank
    config.get_settings.cache_clear()


def device_token(client, master: str, name: str = "laptop", *, kind: str = "full") -> str:
    token = client.post("/devices", json={"name": name}, headers=auth(master)).json()["token"]
    if kind != "full":
        from api.services import device_tokens

        with device_tokens.store()._db() as db:   # noqa: SLF001 — a capture-only device, as pairing narrows one
            db.execute("UPDATE devices SET kind=? WHERE id=?", (kind, token.split("_")[2]))
    return token
