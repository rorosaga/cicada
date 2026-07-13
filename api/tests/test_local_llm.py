"""Hermetic tests for the Ollama "local" consolidation mode.

``resolve_llm_fn`` gains a third routing path (``llm_mode="local"``) that
binds the model to litellm's ``ollama/<model>`` prefix and forwards
``api_base`` — no API key, no network — so the deterministic Sleep cycle can
run fully on-device. Every test injects a fake ``completion``; **no real
Ollama server is ever contacted.**
"""

from __future__ import annotations

from api.config import Settings
from api.services import providers


class _FakeCompletion:
    """Records the kwargs of every call; returns a minimal response object."""

    def __init__(self):
        self.calls: list[dict] = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)

        class _Msg:
            content = '{"ok": true}'

        class _Choice:
            message = _Msg()

        class _Resp:
            choices = [_Choice()]
            usage = {"total_tokens": 7, "cost": 0.0}

        return _Resp()


def test_local_mode_binds_ollama_model_and_api_base():
    settings = Settings(
        llm_mode="local",
        ollama_model="llama3.1",
        ollama_base_url="http://localhost:11434",
    )
    fake = _FakeCompletion()
    fn = providers.resolve_llm_fn(settings, completion=fake)

    fn(messages=[{"role": "user", "content": "hi"}])

    assert len(fake.calls) == 1
    assert fake.calls[0]["model"] == "ollama/llama3.1"
    assert fake.calls[0]["api_base"] == "http://localhost:11434"


def test_local_mode_uses_configured_base_url():
    settings = Settings(
        llm_mode="local",
        ollama_model="mistral",
        ollama_base_url="http://127.0.0.1:9999",
    )
    fake = _FakeCompletion()
    fn = providers.resolve_llm_fn(settings, completion=fake)

    fn(messages=[{"role": "user", "content": "hi"}])

    assert fake.calls[0]["model"] == "ollama/mistral"
    assert fake.calls[0]["api_base"] == "http://127.0.0.1:9999"


def test_explicit_ollama_prefixed_model_routes_local_even_without_llm_mode():
    # An explicit "ollama/<x>" model id should route local (and get api_base)
    # even if llm_mode wasn't set to "local" — the prefix itself is authoritative.
    settings = Settings(llm_mode="byok", ollama_base_url="http://localhost:11434")
    fake = _FakeCompletion()
    fn = providers.resolve_llm_fn(settings, model="ollama/phi3", completion=fake)

    fn(messages=[{"role": "user", "content": "hi"}])

    assert fake.calls[0]["model"] == "ollama/phi3"
    assert fake.calls[0]["api_base"] == "http://localhost:11434"


def test_byok_mode_unchanged_routes_litellm_model_no_ollama():
    settings = Settings(llm_mode="byok", litellm_model="gpt-5.4-mini")
    fake = _FakeCompletion()
    fn = providers.resolve_llm_fn(settings, completion=fake)

    fn(messages=[{"role": "user", "content": "hi"}])

    assert fake.calls[0]["model"] == "gpt-5.4-mini"
    assert "api_base" not in fake.calls[0]


def test_byok_mode_openrouter_model_unaffected_by_ollama_fields():
    settings = Settings(llm_mode="byok")
    fake = _FakeCompletion()
    fn = providers.resolve_llm_fn(
        settings, model="openrouter/z-ai/glm-5.2", completion=fake
    )
    fn(messages=[{"role": "user", "content": "hi"}])

    assert fake.calls[0]["model"] == "openrouter/z-ai/glm-5.2"
    assert "api_base" not in fake.calls[0]


def test_default_llm_mode_is_byok():
    settings = Settings()
    assert settings.llm_mode == "byok"


def test_local_mode_default_ollama_model_and_base_url():
    settings = Settings(llm_mode="local")
    assert settings.ollama_model == "llama3.1"
    assert settings.ollama_base_url == "http://localhost:11434"
