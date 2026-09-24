"""R-AG10 — OpenRouter sign-in: PKCE S256, the nonce in the callback path,
single use, 10 minutes, the key only in secrets.env. Fake HTTP only."""
from __future__ import annotations

import base64
import hashlib
import stat
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import auth
from api.services.connections import openrouter, registry as reg_mod, secrets


@pytest.fixture(autouse=True)
def clean(tmp_path, monkeypatch):
    import os

    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    openrouter._pending.clear()
    reg_mod.reset_registry()
    yield
    openrouter._pending.clear()
    # `secrets.set_secret` also exports the key into os.environ, which monkeypatch
    # does not know about — never leak a signed-in OpenRouter into the next test.
    os.environ.pop("OPENROUTER_API_KEY", None)
    reg_mod.reset_registry()


def test_begin_puts_a_nonce_in_the_callback_path_and_an_s256_challenge():
    nonce, url = openrouter.begin("http://127.0.0.1:8000")
    parsed = urlparse(url)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == openrouter.AUTH_URL
    q = {k: v[0] for k, v in parse_qs(parsed.query).items()}
    assert q["callback_url"] == f"http://127.0.0.1:8000/connections/byok-openrouter/callback/{nonce}"
    assert openrouter.NONCE_RE.match(nonce)
    verifier = openrouter._pending[nonce][0]
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert (q["code_challenge"], q["code_challenge_method"], q["key_label"]) == (expected, "S256", "Cicada")


def test_complete_exchanges_once_and_keeps_the_key_only_in_secrets(tmp_path):
    calls = []

    async def fake_post(url, body):
        calls.append((url, body))
        return {"key": "sk-or-v1-EXAMPLE"}

    nonce, _ = openrouter.begin()
    verifier = openrouter._pending[nonce][0]
    import asyncio
    asyncio.run(openrouter.complete(nonce, "code-1", post=fake_post))
    assert calls == [(openrouter.KEYS_URL, {"code": "code-1", "code_verifier": verifier,
                                            "code_challenge_method": "S256"})]
    assert secrets._read()["OPENROUTER_API_KEY"] == "sk-or-v1-EXAMPLE"
    assert stat.S_IMODE(secrets.secrets_path().stat().st_mode) == 0o600
    with pytest.raises(openrouter.InvalidState):
        asyncio.run(openrouter.complete(nonce, "code-1", post=fake_post))   # single use
    assert len(calls) == 1


def test_an_expired_or_codeless_callback_exchanges_nothing():
    import asyncio

    async def never(url, body):
        raise AssertionError("no exchange")

    nonce, _ = openrouter.begin(now=0)
    with pytest.raises(openrouter.InvalidState):
        asyncio.run(openrouter.complete(nonce, "c", post=never, now=openrouter.TTL_SECONDS + 1))
    nonce, _ = openrouter.begin()
    with pytest.raises(openrouter.InvalidState):
        asyncio.run(openrouter.complete(nonce, "", post=never))
    assert nonce not in openrouter._pending, "a codeless callback still spends its nonce"


def test_a_failed_exchange_never_echoes_what_came_back():
    import asyncio

    async def boom(url, body):
        raise RuntimeError("upstream said: sk-or-v1-LEAKED")

    nonce, _ = openrouter.begin()
    with pytest.raises(openrouter.ExchangeError) as err:
        asyncio.run(openrouter.complete(nonce, "c", post=boom))
    assert "LEAKED" not in str(err.value) and err.value.__cause__ is None
    assert "OPENROUTER_API_KEY" not in secrets._read()


@pytest.mark.parametrize("path,open_", [
    ("/connections/byok-openrouter/callback/" + "a" * 32, True),
    ("/connections/byok-openrouter/callback/short", False),
    ("/connections/byok-openai/callback/" + "a" * 32, False),
    ("/connections/byok-openrouter/login", False),
    ("/connections", False),
])
def test_only_the_oauth_callback_path_is_open(path, open_):
    assert auth._is_oauth_callback_path(path) is open_


def test_the_routes_sign_in_end_to_end(monkeypatch, tmp_path):
    from api.services.connections import base
    from api.services.connections.base import CliResult

    monkeypatch.setenv("CICADA_API_AUTH", "on")
    monkeypatch.setenv("CICADA_API_TOKEN", "t")
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path / "memory"))
    (tmp_path / "memory").mkdir()

    async def fake_post(url, body):
        return {"key": "sk-or-v1-EXAMPLE"}

    # `status_with_powers` probes the whole registry once: never a real `claude`/`codex`
    # CLI or a local Ollama from a test (the `test_connections_api.py` fixture's fakes).
    async def fake_run(argv):
        return CliResult(1, "", "not signed in")

    async def no_tags(_url):
        raise ConnectionError("no ollama in tests")

    monkeypatch.setattr(base, "run_cli", fake_run)
    monkeypatch.setattr(reg_mod.shutil, "which", lambda name: f"/usr/local/bin/{name}")
    monkeypatch.setattr(reg_mod, "_ollama_fetch_tags", no_tags)
    monkeypatch.setattr(openrouter, "_default_post", fake_post)
    config.get_settings.cache_clear()
    try:
        client = TestClient(main.app)
        assert client.post("/connections/byok-openrouter/login").status_code == 401
        session = client.post("/connections/byok-openrouter/login", headers={"Authorization": "Bearer t"}).json()
        assert session["mode"] == "oauth" and session["url"].startswith(openrouter.AUTH_URL)
        nonce = parse_qs(urlparse(session["url"]).query)["callback_url"][0].rsplit("/", 1)[1]
        page = client.get(f"/connections/byok-openrouter/callback/{nonce}?code=c1")      # no bearer: the browser
        assert page.status_code == 200 and "OpenRouter connected" in page.text
        assert client.get(f"/connections/byok-openrouter/callback/{nonce}?code=c1").status_code == 400
        card = client.get("/connections/byok-openrouter?fresh=true", headers={"Authorization": "Bearer t"}).json()
        assert card["connected"] is True and card["login"]["mode"] == "oauth"
        assert "sk-or-v1" not in page.text and "sk-or-v1" not in str(card)
    finally:
        config.get_settings.cache_clear()
