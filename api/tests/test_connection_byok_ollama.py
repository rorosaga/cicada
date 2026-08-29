from __future__ import annotations

import asyncio
import os

import pytest

from api.config import Settings
from api.services.connections import byok, ollama


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path))
    for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    return tmp_path


def test_byok_ids_and_labels():
    ids = {byok.ByokAdapter(p).id for p in byok.BYOK_PROVIDERS}
    assert ids == {"byok-openai", "byok-anthropic", "byok-openrouter", "byok-gemini"}
    assert byok.ByokAdapter("openai").label == "OpenAI API key"


def test_byok_disconnected_then_connected(home):
    a = byok.ByokAdapter("openai")
    s = asyncio.run(a.status())
    assert s.available and not s.connected and s.billing == "usage" and s.login.mode == "key"
    a.set_key("sk-live")
    s = asyncio.run(a.status())
    assert s.connected and s.engine_role == "byok" and s.price_usd_month is None
    assert os.environ["OPENAI_API_KEY"] == "sk-live"
    a.remove_key()
    assert not asyncio.run(a.status()).connected


def test_byok_logout_removes_key(home):
    a = byok.ByokAdapter("anthropic")
    a.set_key("sk-ant")
    asyncio.run(a.logout())
    assert "ANTHROPIC_API_KEY" not in os.environ


def test_byok_unknown_provider():
    with pytest.raises(ValueError):
        byok.ByokAdapter("mystery")


def test_ollama_connected_when_model_present():
    async def tags(_url):
        return ["qwen3:8b", "llama3.1:latest"]

    a = ollama.OllamaAdapter(Settings(ollama_model="qwen3:8b"), fetch_tags=tags)
    s = asyncio.run(a.status())
    assert s.available and s.connected and s.billing == "free" and s.plan_label == "qwen3:8b"


def test_ollama_model_missing():
    async def tags(_url):
        return ["llama3.1:latest"]

    s = asyncio.run(ollama.OllamaAdapter(Settings(ollama_model="qwen3:8b"), fetch_tags=tags).status())
    assert s.available and not s.connected and "ollama pull qwen3:8b" in s.detail


def test_ollama_unreachable():
    async def tags(_url):
        raise ConnectionError("refused")

    s = asyncio.run(ollama.OllamaAdapter(Settings(), fetch_tags=tags).status())
    assert not s.available and not s.connected
