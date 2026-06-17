"""Provider factory — one seam for resolving LLM + embedding backends.

Cicada talks to LLMs through **litellm**, which already routes by the model-id
prefix (``openrouter/<id>``, ``openai/...``, ``anthropic/...``, ``gemini/...``)
reading the matching ``*_API_KEY`` from the environment. So "add a provider"
mostly means "point a model id at it" — OpenRouter needs **zero** special
casing on the LLM side beyond optional attribution headers.

This module is the *preferred* seam going forward (the model-comparison harness
uses it, and services may opt in later), but it is **additive**: the existing
services still call ``litellm.[a]completion`` inline on ``settings.litellm_model``
and the index still records ``{model, dim}`` exactly as before, so the default
path — and the unit-test suite — is byte-identical.

Everything here is hermetically testable: ``resolve_llm_fn`` takes an injectable
``completion`` and ``resolve_embed_fn`` takes injectable transports/factories, so
**no unit test touches the network**.
"""

from __future__ import annotations

import os
from typing import Any, Callable

import numpy as np
from loguru import logger

from api.config import Settings

# ``embed_fn(texts, *, is_query=False) -> np.ndarray`` (float32, 2-D). The same
# contract the sqlite-vec index has always expected.
EmbedFn = Callable[..., np.ndarray]
LlmFn = Callable[..., Any]

OPENROUTER_EMBEDDINGS_URL = "https://openrouter.ai/api/v1/embeddings"
_EMBED_BATCH = 100


# --------------------------------------------------------------------------- #
# LLM factory
# --------------------------------------------------------------------------- #


def _openrouter_headers(settings: Settings) -> dict[str, str] | None:
    """Optional OpenRouter attribution headers, or ``None`` when unconfigured."""
    headers: dict[str, str] = {}
    referer = (settings.openrouter_referer or "").strip()
    title = (settings.openrouter_title or "").strip()
    if referer:
        headers["HTTP-Referer"] = referer
    if title:
        headers["X-OpenRouter-Title"] = title
    return headers or None


def resolve_llm_fn(
    settings: Settings,
    *,
    model: str | None = None,
    completion: LlmFn | None = None,
) -> LlmFn:
    """Resolve a model spec -> a callable bound to that model.

    Args:
        settings: source of the default model (``litellm_model``) and the
            optional OpenRouter attribution config.
        model: explicit model id; defaults to ``settings.litellm_model``. Pass
            ``settings.effective_consolidation_model`` to target the
            consolidation override, or any ``openrouter/<id>`` to route through
            OpenRouter (litellm handles the routing from the prefix).
        completion: the underlying completion callable; defaults to
            ``litellm.completion``. Injected as a fake in tests so no network
            is touched.

    Returns:
        ``fn(messages, *, response_format=None, **kw)`` forwarding to
        ``completion`` with ``model=`` bound and — only for ``openrouter/`` models
        with attribution configured — ``extra_headers`` attached.
    """
    resolved_model = (model or settings.litellm_model).strip()
    if completion is None:
        import litellm

        completion = litellm.completion

    is_openrouter = resolved_model.startswith("openrouter/")
    headers = _openrouter_headers(settings) if is_openrouter else None

    def _call(*, messages, response_format=None, **kw):
        call_kw: dict[str, Any] = {"model": resolved_model, "messages": messages, **kw}
        if response_format is not None:
            call_kw["response_format"] = response_format
        if headers is not None and "extra_headers" not in call_kw:
            call_kw["extra_headers"] = headers
        return completion(**call_kw)

    return _call


# --------------------------------------------------------------------------- #
# Embedding factory
# --------------------------------------------------------------------------- #


def _openrouter_embed_fn(
    settings: Settings,
    *,
    transport: Callable[..., Any] | None = None,
) -> tuple[EmbedFn, str]:
    """Build an OpenRouter /embeddings embed_fn (symmetric; is_query ignored)."""
    model = settings.embedding_model_openrouter
    api_key = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
    if transport is None:
        import requests

        transport = requests.post

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    # Best-effort attribution (harmless if unset).
    attribution = _openrouter_headers(settings)
    if attribution:
        headers.update(attribution)

    def _embed(texts: list[str], *, is_query: bool = False) -> np.ndarray:
        out: list[list[float]] = []
        for start in range(0, len(texts), _EMBED_BATCH):
            batch = texts[start : start + _EMBED_BATCH]
            resp = transport(
                OPENROUTER_EMBEDDINGS_URL,
                headers=headers,
                json={"model": model, "input": batch},
            )
            resp.raise_for_status()
            data = resp.json().get("data", [])
            out.extend(d["embedding"] for d in data)
        return np.asarray(out, dtype=np.float32)

    return _embed, model


def resolve_embed_fn(
    settings: Settings | None = None,
    *,
    transport: Callable[..., Any] | None = None,
    openai_client_factory: Callable[..., Any] | None = None,
    sentence_transformer_factory: Callable[..., Any] | None = None,
) -> tuple[EmbedFn, str]:
    """Build the production embedding fn + its model name from Settings.

    Returns ``(embed_fn, model_name)`` where
    ``embed_fn(texts, *, is_query=False) -> np.ndarray`` (float32, 2-D).

    Modes (after ``resolved_embedding_mode`` auto-degrade):
      - ``openai``     -> OpenAI ``embeddings.create`` (symmetric, is_query ignored).
      - ``openrouter`` -> POST ``/embeddings`` with ``google/gemini-embedding-2``;
                          dim is whatever the response returns (recorded live by
                          the index). Symmetric.
      - ``local``      -> sentence-transformers asymmetric encode_query/document.

    The injectable factories/transport keep this hermetic in tests; production
    uses the real OpenAI client / ``requests.post`` / SentenceTransformer.
    """
    if settings is None:
        from api.config import get_settings

        settings = get_settings()
    settings.warn_if_degraded()
    mode = settings.resolved_embedding_mode
    model = settings.resolved_embedding_model

    if mode == "openrouter":
        return _openrouter_embed_fn(settings, transport=transport)

    if mode == "openai":
        if openai_client_factory is None:
            from openai import OpenAI

            openai_client_factory = OpenAI
        client = openai_client_factory()

        def _openai_embed(texts: list[str], *, is_query: bool = False) -> np.ndarray:
            out: list[list[float]] = []
            for start in range(0, len(texts), _EMBED_BATCH):
                batch = texts[start : start + _EMBED_BATCH]
                resp = client.embeddings.create(model=model, input=batch)
                out.extend(d.embedding for d in resp.data)
            return np.asarray(out, dtype=np.float32)

        return _openai_embed, model

    # Local sentence-transformers (default: google/embeddinggemma-300m).
    if sentence_transformer_factory is None:
        from sentence_transformers import SentenceTransformer

        sentence_transformer_factory = SentenceTransformer
    st_model = sentence_transformer_factory(model)

    def _local_embed(texts: list[str], *, is_query: bool = False) -> np.ndarray:
        encode = st_model.encode_query if is_query else st_model.encode_document
        return np.asarray(encode(texts), dtype=np.float32)

    return _local_embed, model
