"""Hermetic tests for the provider factory (``api.services.providers``).

The factory is the single seam that resolves a model spec -> an LLM callable
and the embedding mode -> an embed_fn. Every test here injects a fake
transport (a fake ``completion`` / fake POST), so **no network is touched**.

Back-compat invariant: with default settings, ``resolve_llm_fn`` binds
``settings.litellm_model`` and ``resolve_embed_fn`` behaves exactly like the
old ``vector_index._resolve_embed_fn`` (openai/local) — these guarantees keep
the 238-test default path byte-identical.
"""

from __future__ import annotations

import numpy as np
import pytest

from api.config import Settings
from api.services import providers


# --------------------------------------------------------------------------- #
# LLM factory
# --------------------------------------------------------------------------- #


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
            usage = {"total_tokens": 7, "cost": 0.001}

        return _Resp()


def test_resolve_llm_fn_default_binds_litellm_model():
    settings = Settings(litellm_model="gpt-5.4-mini")
    fake = _FakeCompletion()
    fn = providers.resolve_llm_fn(settings, completion=fake)

    fn(messages=[{"role": "user", "content": "hi"}])

    assert len(fake.calls) == 1
    assert fake.calls[0]["model"] == "gpt-5.4-mini"
    # No network: the fake captured the call instead.


def test_resolve_llm_fn_explicit_model_overrides():
    settings = Settings(litellm_model="gpt-5.4-mini")
    fake = _FakeCompletion()
    fn = providers.resolve_llm_fn(
        settings, model="openrouter/z-ai/glm-5.2", completion=fake
    )
    fn(messages=[{"role": "user", "content": "hi"}])
    assert fake.calls[0]["model"] == "openrouter/z-ai/glm-5.2"


def test_resolve_llm_fn_forwards_response_format_and_kwargs():
    settings = Settings()
    fake = _FakeCompletion()
    fn = providers.resolve_llm_fn(settings, completion=fake)
    fn(
        messages=[{"role": "user", "content": "hi"}],
        response_format={"type": "json_object"},
    )
    assert fake.calls[0]["response_format"] == {"type": "json_object"}


def test_resolve_llm_fn_returns_completion_result():
    settings = Settings()
    fake = _FakeCompletion()
    fn = providers.resolve_llm_fn(settings, completion=fake)
    resp = fn(messages=[{"role": "user", "content": "hi"}])
    assert resp.choices[0].message.content == '{"ok": true}'


def test_openrouter_model_adds_attribution_headers():
    settings = Settings(openrouter_referer="https://example.test", openrouter_title="Cicada")
    fake = _FakeCompletion()
    fn = providers.resolve_llm_fn(
        settings, model="openrouter/qwen/qwen3.7-max", completion=fake
    )
    fn(messages=[{"role": "user", "content": "hi"}])
    headers = fake.calls[0].get("extra_headers") or {}
    assert headers.get("HTTP-Referer") == "https://example.test"
    assert headers.get("X-OpenRouter-Title") == "Cicada"


def test_non_openrouter_model_has_no_attribution_headers():
    settings = Settings(openrouter_referer="https://example.test")
    fake = _FakeCompletion()
    fn = providers.resolve_llm_fn(settings, model="gpt-5.4-mini", completion=fake)
    fn(messages=[{"role": "user", "content": "hi"}])
    assert "extra_headers" not in fake.calls[0]


def test_openrouter_no_referer_omits_headers():
    # Without an explicit referer, only the title header would be set; if both
    # are empty no extra_headers dict is attached.
    settings = Settings(openrouter_referer="", openrouter_title="")
    fake = _FakeCompletion()
    fn = providers.resolve_llm_fn(
        settings, model="openrouter/z-ai/glm-5.2", completion=fake
    )
    fn(messages=[{"role": "user", "content": "hi"}])
    assert "extra_headers" not in fake.calls[0]


# --------------------------------------------------------------------------- #
# effective_consolidation_model
# --------------------------------------------------------------------------- #


def test_effective_consolidation_model_empty_falls_back_to_litellm():
    settings = Settings(litellm_model="gpt-5.4-mini", consolidation_model="")
    assert settings.effective_consolidation_model == "gpt-5.4-mini"


def test_effective_consolidation_model_when_set():
    settings = Settings(
        litellm_model="gpt-5.4-mini", consolidation_model="openrouter/minimax/minimax-m3"
    )
    assert settings.effective_consolidation_model == "openrouter/minimax/minimax-m3"


# --------------------------------------------------------------------------- #
# Embedding factory — openai / local (unchanged behavior)
# --------------------------------------------------------------------------- #


def test_resolve_embed_fn_openai(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    class _FakeEmbeddings:
        def create(self, *, model, input):
            class _D:
                def __init__(self, e):
                    self.embedding = e

            class _R:
                data = [_D([0.1, 0.2, 0.3]) for _ in input]

            return _R()

    class _FakeOpenAI:
        def __init__(self, *a, **k):
            self.embeddings = _FakeEmbeddings()

    settings = Settings(embedding_mode="openai", embedding_model="text-embedding-3-small")
    embed_fn, model = providers.resolve_embed_fn(settings, openai_client_factory=_FakeOpenAI)
    assert model == "text-embedding-3-small"
    out = embed_fn(["a", "b"], is_query=False)
    assert out.dtype == np.float32
    assert out.shape == (2, 3)


def test_resolve_embed_fn_local(monkeypatch):
    class _FakeST:
        def __init__(self, name):
            self.name = name

        def encode_query(self, texts):
            return [[1.0, 0.0] for _ in texts]

        def encode_document(self, texts):
            return [[0.0, 1.0] for _ in texts]

    settings = Settings(embedding_mode="local", embedding_model_local="fake/model")
    embed_fn, model = providers.resolve_embed_fn(
        settings, sentence_transformer_factory=_FakeST
    )
    assert model == "fake/model"
    q = embed_fn(["x"], is_query=True)
    d = embed_fn(["x"], is_query=False)
    assert q.tolist() == [[1.0, 0.0]]
    assert d.tolist() == [[0.0, 1.0]]


# --------------------------------------------------------------------------- #
# Embedding factory — OpenRouter (new)
# --------------------------------------------------------------------------- #


class _FakeTransport:
    """A fake POST returning OpenRouter-style ``{data:[{embedding:[...]}]}``."""

    def __init__(self, dim=4):
        self.dim = dim
        self.calls: list[dict] = []

    def __call__(self, url, *, headers, json):  # mirrors requests.post signature
        self.calls.append({"url": url, "headers": headers, "json": json})
        n = len(json["input"])

        class _Resp:
            status_code = 200

            def __init__(self, dim, n):
                self._dim = dim
                self._n = n

            def raise_for_status(self):
                return None

            def json(self_inner):
                return {
                    "data": [
                        {"embedding": [0.5] * self_inner._dim} for _ in range(self_inner._n)
                    ],
                    "usage": {"total_tokens": 3, "cost": 0.0001},
                }

        return _Resp(self.dim, n)


def test_resolve_embed_fn_openrouter(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    transport = _FakeTransport(dim=3072)
    settings = Settings(
        embedding_mode="openrouter",
        embedding_model_openrouter="google/gemini-embedding-2",
    )
    embed_fn, model = providers.resolve_embed_fn(settings, transport=transport)
    assert model == "google/gemini-embedding-2"
    out = embed_fn(["alpha", "beta"], is_query=True)  # is_query accepted-and-ignored
    assert out.dtype == np.float32
    assert out.shape == (2, 3072)
    # Posted to the OpenRouter embeddings endpoint with the bearer key + model.
    call = transport.calls[0]
    assert call["url"].endswith("/embeddings")
    assert call["headers"]["Authorization"] == "Bearer or-test"
    assert call["json"]["model"] == "google/gemini-embedding-2"


def test_resolve_embed_fn_openrouter_missing_key_degrades_to_local(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    class _FakeST:
        def __init__(self, name):
            self.name = name

        def encode_query(self, texts):
            return [[1.0] for _ in texts]

        def encode_document(self, texts):
            return [[2.0] for _ in texts]

    settings = Settings(embedding_mode="openrouter", embedding_model_local="fake/local")
    embed_fn, model = providers.resolve_embed_fn(
        settings, sentence_transformer_factory=_FakeST
    )
    # Degraded to local: model is the local model, not the openrouter one.
    assert model == "fake/local"
    out = embed_fn(["x"], is_query=False)
    assert out.tolist() == [[2.0]]


def test_resolved_embedding_mode_openrouter_with_key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    settings = Settings(embedding_mode="openrouter")
    assert settings.resolved_embedding_mode == "openrouter"
    assert settings.resolved_embedding_model == "google/gemini-embedding-2"


def test_resolved_embedding_mode_openrouter_without_key_degrades(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    settings = Settings(embedding_mode="openrouter")
    assert settings.resolved_embedding_mode == "local"


def test_resolve_embed_fn_openrouter_batches(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    transport = _FakeTransport(dim=2)
    settings = Settings(
        embedding_mode="openrouter", embedding_model_openrouter="google/gemini-embedding-2"
    )
    embed_fn, _ = providers.resolve_embed_fn(settings, transport=transport)
    texts = [f"t{i}" for i in range(250)]  # > 100 -> 3 batches
    out = embed_fn(texts)
    assert out.shape == (250, 2)
    assert len(transport.calls) == 3
