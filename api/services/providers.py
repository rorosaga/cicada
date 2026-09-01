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

import asyncio
import inspect
import os
import threading
import time
from typing import Any, Callable

import numpy as np
from loguru import logger

from api.config import Settings
from api.services import engine_errors, pricing, telemetry

# ``embed_fn(texts, *, is_query=False) -> np.ndarray`` (float32, 2-D). The same
# contract the sqlite-vec index has always expected.
EmbedFn = Callable[..., np.ndarray]
LlmFn = Callable[..., Any]

OPENROUTER_EMBEDDINGS_URL = "https://openrouter.ai/api/v1/embeddings"
_EMBED_BATCH = 100

# Memoised (embed_fn, model_id) per recorded model id — the query-time path
# (``resolve_embed_fn_for_model`` with no injected factories) used to
# construct a fresh SentenceTransformer (a multi-second model load, not
# inference) on every call. Loaded once per process and reused.
_EMBED_CACHE: dict[str, tuple[EmbedFn, str]] = {}
_EMBED_LOCK = threading.Lock()
# Per-model in-flight build guard: while one thread is constructing the model
# for a given id, any other caller waits on its Event instead of racing it
# into building (and paying for) a second SentenceTransformer load.
_EMBED_INFLIGHT: dict[str, threading.Event] = {}


def _default_sentence_transformer_factory():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer


def clear_embed_cache() -> None:
    with _EMBED_LOCK:
        _EMBED_CACHE.clear()
        _EMBED_INFLIGHT.clear()


def cached_embed_fn_for_model(model_id: str, settings: Settings | None = None) -> tuple[EmbedFn, str]:
    """Memoised :func:`resolve_embed_fn_for_model` — the model is loaded once per process.

    Concurrent misses for the same ``model_id`` (e.g. the lifespan warm-up
    thread racing the first live query) don't each build their own model:
    the first caller becomes the builder, every other caller waits on that
    build's :class:`threading.Event` and then re-checks the cache.
    """
    mid = (model_id or "").strip()
    while True:
        with _EMBED_LOCK:
            hit = _EMBED_CACHE.get(mid)
            if hit is not None:
                return hit
            event = _EMBED_INFLIGHT.get(mid)
            if event is None:
                event = threading.Event()
                _EMBED_INFLIGHT[mid] = event
                own_build = True
            else:
                own_build = False

        if not own_build:
            event.wait()
            continue  # loop back around: check the cache the builder filled

        try:
            built = resolve_embed_fn_for_model(
                mid, settings, sentence_transformer_factory=_default_sentence_transformer_factory(), _skip_cache=True
            )
            with _EMBED_LOCK:
                _EMBED_CACHE[mid] = built
            return built
        finally:
            with _EMBED_LOCK:
                _EMBED_INFLIGHT.pop(mid, None)
            event.set()


def warm_query_embedder(memory_path) -> None:
    """Preload the query embedder recorded in the bank's index (background, best effort)."""
    try:
        from api.services.vector_index import SqliteVecIndexer

        recorded = (SqliteVecIndexer(memory_path).index_info() or {}).get("model")
        if recorded and recorded != "unknown":
            cached_embed_fn_for_model(recorded)
            logger.info(f"Warmed query embedder: {recorded}")
    except Exception as exc:  # never fatal
        logger.warning(f"embedder warm-up skipped: {exc}")


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


#: Wall-clock default for an agent call when the caller passes no ``timeout``.
#: Matches ``entity_extractor.EXTRACTION_TIMEOUT_S`` — the only guard Stage 1 has.
AGENT_DEFAULT_TIMEOUT_S = 300.0

# One process-wide cap on concurrent `claude -p` subprocesses. Stage 1 fans out
# at MAX_CONCURRENCY (10) and Stage 2 is sequential, so without this the rung
# would put 10 CLI processes on the machine at once and walk straight into the
# plan's own rate limit. Two flavors, one per call path (fix round 1, L1): a
# ``threading.BoundedSemaphore`` for the genuinely-sync branch, and an
# ``asyncio.Semaphore`` for the async branch, acquired BEFORE the work is
# dispatched to ``asyncio.to_thread`` so a caller blocked on the cap parks on
# the event loop instead of occupying (and starving) one of the default
# executor's threads for up to ``timeout`` seconds. Both are keyed by the
# requested limit (fix round 1, L2) rather than rebuilt in place, so a caller
# passing a different ``agent_max_concurrency`` gets its own persistent
# semaphore instead of replacing the shared one out from under a caller that
# already holds a permit on it.
_AGENT_SEM_LOCK = threading.Lock()
_AGENT_SEMS: dict[int, threading.BoundedSemaphore] = {}
_AGENT_ASYNC_SEM_LOCK = threading.Lock()
_AGENT_ASYNC_SEMS: dict[tuple[int, int], asyncio.Semaphore] = {}


def _agent_semaphore(limit: int) -> threading.BoundedSemaphore:
    limit = max(1, int(limit or 1))
    with _AGENT_SEM_LOCK:
        sem = _AGENT_SEMS.get(limit)
        if sem is None:
            sem = threading.BoundedSemaphore(limit)
            _AGENT_SEMS[limit] = sem
        return sem


def _agent_async_semaphore(limit: int) -> asyncio.Semaphore:
    """Async-branch twin of :func:`_agent_semaphore` (fix round 1, L1).

    Created lazily per RUNNING loop — never at import — so it can't bind to a
    loop that has since gone away: ``asyncio.Semaphore`` binds to whichever
    loop is running the first time it's awaited, and a module-level instance
    built at import time (or bound to one process's first loop) would raise
    on every later ``asyncio.run()`` in a different loop, exactly the trap
    that keeps this lazy and keyed by ``(loop id, limit)``.
    """
    limit = max(1, int(limit or 1))
    key = (id(asyncio.get_running_loop()), limit)
    with _AGENT_ASYNC_SEM_LOCK:
        sem = _AGENT_ASYNC_SEMS.get(key)
        if sem is None:
            sem = asyncio.Semaphore(limit)
            _AGENT_ASYNC_SEMS[key] = sem
        return sem


def resolve_llm_fn(
    settings: Settings,
    *,
    model: str | None = None,
    completion: LlmFn | None = None,
    stage: str | None = None,
    sink: Callable[[telemetry.UsageEvent], None] | None = None,
    bank: str | None = None,
    is_async: bool | None = None,
    runner: Callable[..., Any] | None = None,
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
        stage: label recorded on every emitted ``UsageEvent`` (e.g. ``"ask"``,
            ``"extraction"``); defaults to ``"unknown"`` when not supplied.
        sink: ``Callable[[UsageEvent], None]`` receiving one event per call;
            defaults to ``telemetry.record`` (the on-disk ledger).
        bank: label recorded on the event; defaults to
            ``telemetry.bank_name(settings)``.
        is_async: force the AGENT rung's returned callable to be awaitable
            (``True``) or blocking (``False``). Outside ``llm_mode="agent"``
            this is a no-op (fix round 1, L4) — the byok/local ``_call``
            always branches on ``inspect.isawaitable(completion(...))`` at
            call time, exactly as before this parameter existed. Defaults to
            ``inspect.iscoroutinefunction(completion)``: verified sound
            (``litellm.acompletion`` is a coroutine function,
            ``litellm.completion`` is not), but in ``llm_mode="agent"`` the
            injected ``completion`` is never called, so the override exists
            for callers that pass neither.
        runner: injected subprocess runner for ``llm_mode="agent"``
            (``runner(argv, *, stdin, timeout, cwd) -> CliResult``). Tests
            always pass one; production leaves it ``None`` and gets
            ``connections.base.run_cli_sync``.

    Returns:
        ``fn(messages, *, response_format=None, **kw)`` forwarding to
        ``completion`` with ``model=`` bound and — only for ``openrouter/`` models
        with attribution configured — ``extra_headers`` attached. When
        ``settings.llm_mode == "local"`` (or the resolved model already starts
        with ``ollama/``), the model is bound to ``ollama/<settings.ollama_model>``
        (litellm's Ollama routing prefix) and ``api_base`` is set to
        ``settings.ollama_base_url`` — no API key required. This leaves the
        byok/openrouter path byte-identical when ``llm_mode != "local"``.
        When ``settings.llm_mode == "agent"``, the call is routed through
        ``agent_engine.complete`` (a ``claude -p`` subprocess on the user's own
        subscription) instead — see the module docstring for the seam contract.

        Every call is timed and reported as one ``UsageEvent`` to ``sink``
        (default: the telemetry ledger) tagged with ``stage`` — the single
        interception point for the consumption dashboard.
    """
    resolved_model = (model or settings.litellm_model).strip()
    # "auto" is resolved ONCE per Sleep cycle by ``engine_select`` (it has to
    # probe the connections registry, which is async and shells out). An
    # unresolved "auto" reaching this synchronous seam degrades to byok rather
    # than blocking a request thread on a subprocess probe.
    mode = (settings.llm_mode or "byok").strip().lower()
    is_agent = mode == "agent"
    if completion is None and not is_agent:
        # Fix round 1, N2: never imported on the agent rung — a multi-second
        # import for a callable that branch is built specifically to avoid
        # calling. `iscoroutinefunction(None)` below is False, same as
        # `iscoroutinefunction(litellm.completion)` would have been, so
        # leaving `completion` unset here changes no inferred behavior.
        import litellm

        completion = litellm.completion
    if sink is None:
        sink = telemetry.record
    bank_label = bank or telemetry.bank_name(settings)

    if is_async is None:
        is_async = inspect.iscoroutinefunction(completion)

    is_local = (not is_agent) and (mode == "local" or resolved_model.startswith("ollama/"))
    if is_local and not resolved_model.startswith("ollama/"):
        resolved_model = f"ollama/{settings.ollama_model}"

    is_openrouter = resolved_model.startswith("openrouter/")
    headers = _openrouter_headers(settings) if is_openrouter else None

    if is_agent:
        from api.services import agent_engine

        # A plan call is not money and does not belong to the disconnected
        # BYOK API-key card. `connection` must EQUAL the adapter id —
        # consumption_stats.per_connection joins strictly on it.
        engine_label, connection, billing = "claude-cli", "claude-plan", "subscription"
        # `litellm_model` ids mean nothing to `claude --model`; the rung has
        # its own model pair (settings.agent_model / agent_disambiguation_model).
        argv_model = agent_engine.model_for_stage(settings, stage)
    else:
        engine_label = "litellm"
        connection, billing = telemetry.connection_for_model(resolved_model)
        argv_model = resolved_model

    def _emit(resp, started: float, ok: bool, *, model_used: str | None = None,
              equiv_override: float | None = None) -> None:
        try:
            usage = telemetry.usage_from_response(resp) if ok else telemetry.usage_from_response(None)
            event_model = model_used or (argv_model if is_agent else resolved_model)
            if is_agent:
                # `costBasis: "list"` says the envelope's figure is metering,
                # not money charged — so it is an equivalent, never a spend.
                cost = None
                equiv = equiv_override
                if equiv is None:
                    equiv = pricing.estimate_cost(
                        event_model, usage["input_tokens"], usage["output_tokens"],
                        usage["cache_read_tokens"], usage["cache_write_tokens"])
            else:
                cost = None if billing == "free" else usage["cost_usd"]
                equiv = pricing.estimate_cost(
                    resolved_model, usage["input_tokens"], usage["output_tokens"],
                    usage["cache_read_tokens"], usage["cache_write_tokens"])
                if equiv is None:
                    equiv = cost
            sink(telemetry.UsageEvent(
                kind="llm_call", stage=stage or "unknown", connection=connection,
                engine=engine_label, model=event_model, bank=bank_label, billing=billing,
                input_tokens=usage["input_tokens"], output_tokens=usage["output_tokens"],
                cache_read_tokens=usage["cache_read_tokens"],
                cache_write_tokens=usage["cache_write_tokens"],
                cost_usd=cost, equiv_cost_usd=equiv,
                duration_ms=int((time.perf_counter() - started) * 1000), ok=ok,
            ))
        except Exception as exc:  # a sink must never break an LLM call
            logger.warning(f"telemetry sink failed: {exc}")

    def _emit_throttle(exc: Exception) -> None:
        """The first ``kind="throttle"`` event this codebase has ever written.

        ``telemetry.KINDS`` has listed it and ``consumption_stats:249`` has
        counted ``throttle_events`` since G51; nothing produced one.
        """
        try:
            sink(telemetry.UsageEvent(
                kind="throttle", stage=stage or "unknown", connection=connection,
                engine=engine_label, model=argv_model, bank=bank_label, billing=billing,
                invocations=0, throttled=True, ok=False, refs={"detail": str(exc)[:300]},
            ))
        except Exception as sink_exc:
            logger.warning(f"telemetry sink failed: {sink_exc}")

    def _agent_invoke(messages, response_format, timeout: float):
        """One `claude -p` call, the response shim, and telemetry.

        Fix round 1, M1: the shim and cost extraction now sit INSIDE the
        guarded region, and the catch is widened from
        ``engine_errors.EngineError`` to ``Exception`` — a bare runner
        exception, or a ``response_shim``/``equiv_cost_from_envelope``
        failure, must still emit exactly one event rather than vanishing on
        the one path whose entire job is making failures visible.

        Callers own their own concurrency gate — the threading semaphore for
        the sync branch, the asyncio semaphore for the async branch (L1) —
        so this function never acquires one itself.
        """
        started = time.perf_counter()
        try:
            envelope = agent_engine.complete(
                messages=messages, model=argv_model, stage=stage,
                want_json=response_format is not None, timeout=timeout, runner=runner,
            )
            resp = agent_engine.response_shim(envelope, argv_model)
            used = resp["model"]
            agent_engine.record_model_used(used)
            equiv = agent_engine.equiv_cost_from_envelope(envelope)
        except engine_errors.EngineThrottled as exc:
            # Trip BEFORE emitting so a concurrent caller cannot also trip.
            newly_tripped = agent_engine.trip_breaker(str(exc))
            _emit(None, started, ok=False)
            if newly_tripped:
                _emit_throttle(exc)
            raise
        except Exception:
            _emit(None, started, ok=False)
            raise
        _emit(resp, started, ok=True, model_used=used, equiv_override=equiv)
        return resp

    def _agent_invoke_sync(messages, response_format, timeout: float):
        with _agent_semaphore(getattr(settings, "agent_max_concurrency", 3)):
            return _agent_invoke(messages, response_format, timeout)

    async def _agent_invoke_async(messages, response_format, timeout: float):
        # Fix round 1, L1: gate BEFORE dispatching to the thread pool, so a
        # caller blocked on the cap parks on the event loop rather than
        # occupying (and starving) one of the default executor's threads for
        # up to `timeout` seconds.
        async with _agent_async_semaphore(getattr(settings, "agent_max_concurrency", 3)):
            return await asyncio.to_thread(_agent_invoke, messages, response_format, timeout)

    def _agent_call(*, messages, response_format=None, **kw):
        # Accept-and-drop every unknown kwarg (`extra_body`, `temperature`,
        # `max_tokens`, `api_base`, ...) — none of them have an argv form.
        # `timeout` is the exception: it is the only wall-clock guard Stage 1
        # has (entity_extractor.py:138). Coerced defensively (fix round 1,
        # L3): a non-numeric or non-positive value falls back to the default
        # rather than raising out of the seam before any telemetry is
        # emitted for the call.
        timeout = AGENT_DEFAULT_TIMEOUT_S
        raw_timeout = kw.get("timeout")
        if raw_timeout is not None:
            try:
                parsed = float(raw_timeout)
            except (TypeError, ValueError):
                parsed = None
            if parsed is not None and parsed > 0:
                timeout = parsed
        if is_async:
            return _agent_invoke_async(messages, response_format, timeout)
        return _agent_invoke_sync(messages, response_format, timeout)

    if is_agent:
        return _agent_call

    def _call(*, messages, response_format=None, **kw):
        call_kw: dict[str, Any] = {"model": resolved_model, "messages": messages, **kw}
        if response_format is not None:
            call_kw["response_format"] = response_format
        if headers is not None and "extra_headers" not in call_kw:
            call_kw["extra_headers"] = headers
        if is_local and "api_base" not in call_kw:
            call_kw["api_base"] = settings.ollama_base_url
        started = time.perf_counter()
        try:
            result = completion(**call_kw)
        except Exception:
            _emit(None, started, ok=False)
            raise
        if inspect.isawaitable(result):
            async def _awaited():
                try:
                    resp = await result
                except Exception:
                    _emit(None, started, ok=False)
                    raise
                _emit(resp, started, ok=True)
                return resp

            return _awaited()
        _emit(result, started, ok=True)
        return result

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


# --------------------------------------------------------------------------- #
# Per-bank embedding resolution (query-time)
# --------------------------------------------------------------------------- #
#
# A memory bank records the embedding model it was BUILT with in its sqlite
# ``index_meta`` table. The query path must embed with THAT model — not the
# global ``Settings`` mode — so two banks built with different embedders
# (e.g. ``original-v1`` on embeddinggemma-300m/768 and ``claude-chats`` on
# gemini-embedding-2/3072) each query correctly at the same time. The build
# path still uses the global configured model, so a *fresh* bank indexes with
# whatever ``CICADA_EMBEDDING_MODE`` says.

# Recorded model ids that map to the OpenRouter ``/embeddings`` route. Gemini
# embedding models are served via OpenRouter in Cicada.
_OPENROUTER_EMBED_MODELS = ("gemini",)


def _model_is_openai(model_id: str) -> bool:
    m = model_id.lower()
    return m.startswith("text-embedding-") or m.startswith("openai/")


def _model_is_openrouter(model_id: str) -> bool:
    m = model_id.lower()
    if m.startswith("openrouter/"):
        return True
    return any(tok in m for tok in _OPENROUTER_EMBED_MODELS)


def resolve_embed_fn_for_model(
    model_id: str,
    settings: Settings | None = None,
    *,
    transport: Callable[..., Any] | None = None,
    openai_client_factory: Callable[..., Any] | None = None,
    sentence_transformer_factory: Callable[..., Any] | None = None,
    _skip_cache: bool = False,
) -> tuple[EmbedFn, str]:
    """Build an embed_fn for a SPECIFIC recorded model id (query-time path).

    Unlike :func:`resolve_embed_fn` (which reads the global mode from Settings),
    this maps a concrete recorded ``model_id`` back to the right provider so a
    bank queries with the model it was built with:

      - ``text-embedding-*`` / ``openai/*``       -> OpenAI ``embeddings.create``
      - ids containing ``gemini`` (or ``openrouter/*``) -> OpenRouter ``/embeddings``
      - anything else (e.g. ``google/embeddinggemma-300m``) -> local
        sentence-transformers, asymmetric query/document encode.

    Returns ``(embed_fn, model_id)``. Injectable factories/transport keep this
    hermetic; production uses the real OpenAI client / ``requests.post`` /
    SentenceTransformer. Callers fall back to the global :func:`resolve_embed_fn`
    when the bank's index is unbuilt (no recorded model).
    """
    if (
        not _skip_cache
        and transport is None
        and openai_client_factory is None
        and sentence_transformer_factory is None
    ):
        return cached_embed_fn_for_model(model_id, settings)

    if settings is None:
        from api.config import get_settings

        settings = get_settings()

    mid = (model_id or "").strip()

    if _model_is_openai(mid):
        openai_model = mid.removeprefix("openai/")
        if openai_client_factory is None:
            from openai import OpenAI

            openai_client_factory = OpenAI
        client = openai_client_factory()

        def _openai_embed(texts: list[str], *, is_query: bool = False) -> np.ndarray:
            out: list[list[float]] = []
            for start in range(0, len(texts), _EMBED_BATCH):
                batch = texts[start : start + _EMBED_BATCH]
                resp = client.embeddings.create(model=openai_model, input=batch)
                out.extend(d.embedding for d in resp.data)
            return np.asarray(out, dtype=np.float32)

        return _openai_embed, mid

    if _model_is_openrouter(mid):
        api_key = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
        if transport is None:
            import requests

            transport = requests.post
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        attribution = _openrouter_headers(settings)
        if attribution:
            headers.update(attribution)

        def _or_embed(texts: list[str], *, is_query: bool = False) -> np.ndarray:
            out: list[list[float]] = []
            for start in range(0, len(texts), _EMBED_BATCH):
                batch = texts[start : start + _EMBED_BATCH]
                resp = transport(
                    OPENROUTER_EMBEDDINGS_URL,
                    headers=headers,
                    json={"model": mid, "input": batch},
                )
                resp.raise_for_status()
                data = resp.json().get("data", [])
                out.extend(d["embedding"] for d in data)
            return np.asarray(out, dtype=np.float32)

        return _or_embed, mid

    # Local sentence-transformers (the recorded id is the ST model name).
    if sentence_transformer_factory is None:
        from sentence_transformers import SentenceTransformer

        sentence_transformer_factory = SentenceTransformer
    st_model = sentence_transformer_factory(mid)

    def _local_for_model(texts: list[str], *, is_query: bool = False) -> np.ndarray:
        encode = st_model.encode_query if is_query else st_model.encode_document
        return np.asarray(encode(texts), dtype=np.float32)

    return _local_for_model, mid
