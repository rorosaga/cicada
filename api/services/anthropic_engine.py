"""G237: a Claude API key, served through Anthropic's own SDK.

The owner, 2026-11-04: "having cicada work the same or as good as through Claude code is crucial and priority." This is
the key path's ``agent_engine``: the same prompts (``marshal_prompt``, ``JSON_ONLY_SUFFIX``), the same seam around it
(``providers``' semaphore, breaker, drain retry and ledger), and the same answer shape. What litellm 1.83.4 could not do
for a Claude key, measured with a stub client: it sent ``extra_body`` as a literal top-level field (a 400 on every
extraction and judge call), dropped JSON mode, capped every model its table does not list at 4096 tokens, and carried
``temperature`` (a 400 on every current model).

Invariants:

1. **The key is read only here and only when chosen**, from ``ANTHROPIC_API_KEY`` (``secrets`` projects it), passed
   explicitly. It never falls through to the SDK's own chain (a profile, an auth token) and ``base_url`` is fixed, so an
   inherited ``ANTHROPIC_BASE_URL`` can never send the key elsewhere. No prompt, answer or provider message is logged.
2. **One cache breakpoint: the end of the system prompt.** Cicada's system prompts are the same bytes every call and
   the user message is different every call, so that is the shared prefix; a marker after the conversation would write
   text nothing ever reads. TTL 1 hour: a drain's next batch reaches the same prompt after more than 5 minutes (the
   2× write pays for itself by the second batch), and the plan's own CLI was measured writing 1-hour entries.
3. **The first call on a prefix goes first.** A cache entry is readable only once its response starts streaming, so
   parallel calls all pay to write it (measured on the plan: three at once, zero reads, three full writes). Stage 1 fans
   out, so the rest wait for the first call's first byte, a few seconds at most, and then read.
4. **Every call streams**: a long answer cannot hit an HTTP timeout, and ``timeout`` stays a real wall clock.
5. **A refusal is said in words, and a 429 is a pause.** Every SDK error becomes an ``engine_errors`` class carrying a
   provider-neutral sentence; the provider's text classifies it (``engine_cause``) and goes no further.
"""
from __future__ import annotations

import hashlib
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from loguru import logger

from api.services import agent_engine, anthropic_models, engine_cause, engine_errors

#: The vendor's own API host, never read from the environment (invariant 1).
BASE_URL = "https://api.anthropic.com"
#: The SDK's retries of a 429, 5xx or dropped connection. A key's limits are per-minute buckets and the SDK honours
#: ``retry-after``, so this rides out more than the plan's 2 (`agent_cli_max_retries`) before it pauses the run.
MAX_RETRIES = 4
CONNECT_TIMEOUT_S = 10.0
#: Room for a long answer. A key's output limit counts tokens as they are produced, never ``max_tokens`` (the vendor's
#: rate-limit page), and every call streams, so a high ceiling costs nothing unless it is used.
DEFAULT_MAX_TOKENS = 64_000
#: Thinking counts toward ``max_tokens`` on current models, so a caller's short cap (a link's two sentences at 100) gets
#: room for it; the answer itself stays as short as it was asked to be.
THINKING_ROOM = 2_048
CACHE_TTL = "1h"
#: A rate limit lifting within this long is waited out by a batch's later stages (see ``complete``).
SHORT_LIMIT_S = 120.0
#: A prefix under the API's smallest cacheable size (512 tokens on current models) is not worth waiting for.
GATE_MIN_CHARS = 1_500
GATE_WAIT_S = 30.0
#: A prefix's entry is warm for this long after the last call that reached it.
WARM_S = 55 * 60.0
SEARCH_TOOL_NEW = "web_search_20260209"
SEARCH_TOOL_BASIC = "web_search_20250305"
_NEW_SEARCH_LINES = ("opus", "sonnet")

_client_lock = threading.Lock()
_clients: dict[str, Any] = {}


def _build_client(key: str):
    """The one place the SDK client is made (a test hands in its own HTTP transport here)."""
    import anthropic

    return anthropic.Anthropic(api_key=key, base_url=BASE_URL, max_retries=MAX_RETRIES)


def make_client(*, timeout: float | None = None, max_retries: int | None = None):
    """The SDK client for the key in the environment, one per key, reused for its connection pool. Raises
    ``EngineUnavailable`` with no key or no SDK, in words. The cache is keyed by the key's hash, never the key."""
    key = (os.environ.get(anthropic_models.KEY_ENV) or "").strip()
    if not key:
        raise engine_errors.EngineUnavailable(engine_cause.sentence("auth"))
    slot = hashlib.sha256(key.encode()).hexdigest()
    with _client_lock:
        client = _clients.get(slot)
        if client is None:
            try:
                built = _build_client(key)
            except ImportError as exc:
                raise engine_errors.EngineUnavailable(
                    "This install is missing a part the API key engine needs. Update Cicada (from a checkout: `uv sync` "
                    "in api/), then start the read again.") from exc
            _clients.clear()   # a changed key never keeps the old one's client
            client = built
            _clients[slot] = client
    return client.with_options(max_retries=MAX_RETRIES if max_retries is None else max_retries,
                               **({"timeout": timeout} if timeout is not None else {}))


def reset_clients() -> None:
    with _client_lock:
        _clients.clear()


# --------------------------------------------------------------------------- #
# The first call on a prefix goes first (invariant 3)
# --------------------------------------------------------------------------- #


@dataclass
class _Prefix:
    ready: threading.Event = field(default_factory=threading.Event)
    warm_until: float = 0.0


_prefix_lock = threading.Lock()
_prefixes: dict[str, _Prefix] = {}


def reset_prefixes() -> None:
    with _prefix_lock:
        _prefixes.clear()


def _enter_prefix(key: str) -> _Prefix | None:
    """``None`` when a first call has already opened this prefix (or it is warm); the prefix when this call goes first.
    A call that came after a first call still on its way waits for its first byte, bounded."""
    now = time.monotonic()
    with _prefix_lock:
        for stale in [k for k, p in _prefixes.items() if p.ready.is_set() and p.warm_until <= now]:
            _prefixes.pop(stale, None)
        prefix = _prefixes.get(key)
        if prefix is None:
            prefix = _Prefix()
            _prefixes[key] = prefix
            return prefix
    prefix.ready.wait(GATE_WAIT_S)
    return None


def _open_prefix(prefix: _Prefix | None) -> None:
    if prefix is not None:
        prefix.warm_until = time.monotonic() + WARM_S
        prefix.ready.set()


def _fail_prefix(key: str, prefix: _Prefix | None) -> None:
    """The first call failed before its first byte: the next call goes first."""
    if prefix is None or prefix.ready.is_set():
        return
    with _prefix_lock:
        if _prefixes.get(key) is prefix:
            _prefixes.pop(key, None)
    prefix.ready.set()


def _touch_prefix(key: str) -> None:
    with _prefix_lock:
        prefix = _prefixes.get(key)
        if prefix is not None:
            prefix.warm_until = time.monotonic() + WARM_S


# --------------------------------------------------------------------------- #
# Errors, in words
# --------------------------------------------------------------------------- #

KEY_LIMIT = "key_limit"
OVERLOADED = "The provider is overloaded right now. Continue later; what was read is kept."
TIMED_OUT = "The provider did not answer within Sleep's time limit for the call."
LOST = "The connection to the provider was lost."
SERVICE_FAILED = "The provider's service failed on this call."
REFUSED_REQUEST = "The provider refused this request."
CUT_OFF = "The answer was cut off at its length limit."
NO_ANSWER = "The provider finished without an answer."
MODEL_REFUSED = "The model declined to read this conversation."


_STREAM_ERRORS = {"overloaded_error": 529, "rate_limit_error": 429, "api_error": 500, "timeout_error": 504}


def _resets_at(exc) -> int | None:
    """The provider's own reset time from its headers, when it sent one. Measured, never estimated."""
    headers = getattr(getattr(exc, "response", None), "headers", None)
    if headers is None:
        return None
    retry = headers.get("retry-after")
    try:
        if retry is not None:
            return int(time.time() + float(retry))
    except ValueError:
        pass
    for name in ("anthropic-ratelimit-input-tokens-reset", "anthropic-ratelimit-tokens-reset",
                 "anthropic-ratelimit-requests-reset"):
        value = headers.get(name)
        if value:
            try:
                return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
            except ValueError:
                continue
    return None


def _short_limit_wait(scope: str) -> float | None:
    """How long until a tripped key limit lifts, when it is a rate limit that says so and soon. ``None`` for anything
    else (a spending limit, no reset time, a long wait): those fail fast, nothing sent."""
    if agent_engine.breaker_kind(scope=scope) != KEY_LIMIT:
        return None
    resets = agent_engine.breaker_resets_at(scope=scope)
    if resets is None:
        return None
    wait = float(resets) - time.time()
    return max(0.0, wait) if wait <= SHORT_LIMIT_S else None


def _key_limit(err: engine_errors.EngineError) -> engine_errors.EngineError:
    """Marked so a pause on a key never reads as the person's plan (``agent_engine.limit_kind_of``)."""
    err.limit_type = KEY_LIMIT
    return err


def _translate(exc: Exception) -> engine_errors.EngineError:
    """An SDK failure as the class every layer above already branches on. The log gets its class and status only."""
    import anthropic

    status = getattr(exc, "status_code", None)
    # An error inside an open stream arrives with the stream's own 200: its body says what it really was.
    body = getattr(exc, "body", None)
    kind = (body.get("error") or {}).get("type") if isinstance(body, dict) else None
    status = _STREAM_ERRORS.get(kind, status) if status == 200 or status is None else status
    logger.warning(f"Claude API call failed: {type(exc).__name__} status={status} "
                   f"request={getattr(exc, 'request_id', None)}")
    if isinstance(exc, anthropic.APITimeoutError):
        return engine_errors.EngineTimeout(TIMED_OUT)
    if isinstance(exc, anthropic.APIConnectionError):
        return engine_errors.EngineConnectionLost(LOST)
    cause = engine_cause.classify(exc)
    if cause == "spending_limit" or status == 402:
        return _key_limit(engine_errors.EngineExhausted(engine_cause.sentence("spending_limit")))
    if status in (401, 403) or cause == "auth":
        return engine_errors.EngineUnavailable(engine_cause.sentence("auth"))
    if status == 404 or cause == "model_not_found":
        return engine_errors.EngineModelNotFound(engine_cause.sentence("model_not_found"))
    if status == 429:
        return _key_limit(engine_errors.EngineThrottled(engine_cause.sentence("rate_limited"), resets_at=_resets_at(exc)))
    if status == 529:
        return _key_limit(engine_errors.EngineThrottled(OVERLOADED, resets_at=_resets_at(exc)))
    if isinstance(status, int) and status >= 500:
        return engine_errors.EngineConnectionLost(SERVICE_FAILED)
    return engine_errors.EngineFailed(REFUSED_REQUEST)


# --------------------------------------------------------------------------- #
# The call
# --------------------------------------------------------------------------- #


def _system_blocks(system_text: str) -> list[dict]:
    return [{"type": "text", "text": system_text, "cache_control": {"type": "ephemeral", "ttl": CACHE_TTL}}]


def _search_tool(served: str) -> dict:
    """The newest search the model takes, one search a call. Haiku takes the basic variant only."""
    newer = any(line in served for line in _NEW_SEARCH_LINES)
    return {"type": SEARCH_TOOL_NEW if newer else SEARCH_TOOL_BASIC, "name": "web_search", "max_uses": 1}


def request_params(*, messages: list[dict] | None, served: str, want_json: bool, effort: str | None,
                   max_tokens: int, web_search: bool) -> dict:
    """The request body, a pure function of the call. Nothing in it changes between calls of one stage except the user
    message: the prefix is byte-identical (invariant 2)."""
    system_text, body = agent_engine.marshal_prompt(messages)
    system_text = (system_text or "").strip() or agent_engine.DEFAULT_SYSTEM_PROMPT
    if want_json:
        system_text = f"{system_text}\n\n{agent_engine.JSON_ONLY_SUFFIX}"
    params: dict[str, Any] = {
        "model": served,
        "max_tokens": max_tokens,
        "system": _system_blocks(system_text),
        "messages": [{"role": "user", "content": body or " "}],
    }
    if effort and anthropic_models.takes_effort(served, effort):
        params["output_config"] = {"effort": effort}
    if web_search:
        params["tools"] = [_search_tool(served)]
    return params


def _text_of(message) -> str:
    return "".join(getattr(b, "text", "") or "" for b in message.content if getattr(b, "type", "") == "text")


def _searches_of(message) -> list[list]:
    """The searches a server-side tool made, in the plan stream's shape (``web_lookup.searched_queries``)."""
    out: list[list] = []
    for block in message.content:
        if getattr(block, "type", "") == "server_tool_use" and "search" in str(getattr(block, "name", "")):
            inp = getattr(block, "input", None)
            out.append([str(block.name), dict(inp) if isinstance(inp, dict) else {}])
    return out


@dataclass
class _Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0
    cache_write: int = 0
    cache_write_1h: int = 0
    searches: int = 0

    def add(self, usage) -> None:
        self.input_tokens += int(getattr(usage, "input_tokens", 0) or 0)
        self.output_tokens += int(getattr(usage, "output_tokens", 0) or 0)
        self.cache_read += int(getattr(usage, "cache_read_input_tokens", 0) or 0)
        self.cache_write += int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
        split = getattr(usage, "cache_creation", None)
        self.cache_write_1h += int(getattr(split, "ephemeral_1h_input_tokens", 0) or 0)
        tools = getattr(usage, "server_tool_use", None)
        self.searches += int(getattr(tools, "web_search_requests", 0) or 0)

    @property
    def gross(self) -> int:
        """The whole prompt (``telemetry.usage_from_response``'s rule): the API's ``input_tokens`` is the uncached rest."""
        return self.input_tokens + self.cache_read + self.cache_write


def cost_usd(model: str, usage: _Usage) -> float | None:
    """What the call cost at the vendor's list price (``price_supplement.claude_cost``, each write at its own TTL's
    rate). ``None`` when the model has no price: unknown, never zero."""
    from api.services import price_supplement

    return price_supplement.claude_cost(
        model, input_tokens=usage.input_tokens, output_tokens=usage.output_tokens, cache_read=usage.cache_read,
        cache_write=usage.cache_write, cache_write_1h=usage.cache_write_1h, searches=usage.searches)


def _shim(*, text: str, stop_reason: str | None, served: str, usage: _Usage, searches: list[list] | None) -> Any:
    # The plan's dual-access shape, so every stage reads one answer either way.
    resp: dict[str, Any] = {
        "choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": stop_reason}],
        "model": served,
        "usage": {
            "prompt_tokens": usage.gross,
            "completion_tokens": usage.output_tokens,
            "cache_read_input_tokens": usage.cache_read,
            "cache_creation_input_tokens": usage.cache_write,
            "prompt_tokens_details": {"cached_tokens": usage.cache_read},
        },
        "_hidden_params": {"response_cost": cost_usd(served, usage)},
    }
    if searches is not None:
        resp["tool_uses"] = searches
    return agent_engine._wrap(resp)


def _stream_once(client, params: dict, *, timeout: float, deadline: float, first: _Prefix | None) -> Any:
    """One streamed request. The first byte opens the prefix for the calls waiting on it; the wall clock is checked as
    the answer arrives, so a call never runs past Sleep's budget however fast the bytes come."""
    import anthropic

    sized = client.with_options(timeout=anthropic.Timeout(timeout, connect=CONNECT_TIMEOUT_S))
    with sized.messages.stream(**params) as stream:
        for _event in stream:
            _open_prefix(first)
            if time.monotonic() > deadline:
                raise engine_errors.EngineTimeout(TIMED_OUT)
        return stream.get_final_message()


def complete(
    *,
    messages: list[dict],
    model: str,
    stage: str | None = None,
    want_json: bool = False,
    timeout: float = agent_engine.DEFAULT_TIMEOUT_S,
    scope: str | None = None,
    effort: str | None = None,
    max_tokens: int | None = None,
    web_search: bool = False,
) -> Any:
    """One call. Returns the response shim; raises only ``engine_errors`` (``direct_engines``' contract). A tripped
    breaker fails before anything is sent, tagged ``spawned = False`` so the seam records no phantom call."""
    scope = scope or agent_engine.current_scope()
    tripped = agent_engine.breaker_reason(scope=scope)
    if tripped:
        wait = _short_limit_wait(scope)
        if wait is None:
            exc = engine_errors.EngineThrottled(tripped)
            exc.limit_type = KEY_LIMIT
            exc.spawned = False
            raise exc
        # The batch's reads are already paid for: a later stage waits out a key's minute instead of losing them. The
        # breaker stays tripped, so the run still stops, with the words, once this batch is filed.
        time.sleep(wait)

    client = make_client()
    deadline = time.monotonic() + timeout
    served = anthropic_models.resolve(model)
    limit = anthropic_models.max_output(served.model)
    ask = DEFAULT_MAX_TOKENS if max_tokens is None else max(int(max_tokens), THINKING_ROOM)
    ask = min(ask, limit) if limit else ask
    usage = _Usage()
    moved: str | None = served.note
    if moved:
        logger.warning(f"Claude API: a retired model id moved forward to {served.model}")
    model_id = served.model
    while True:
        params = request_params(messages=messages, served=model_id, want_json=want_json, effort=effort,
                                max_tokens=ask, web_search=web_search)
        system_text = params["system"][0]["text"]
        prefix_key = None
        first = None
        if len(system_text) >= GATE_MIN_CHARS:
            prefix_key = hashlib.sha256(f"{model_id}\0{effort}\0{web_search}\0{system_text}".encode()).hexdigest()
            first = _enter_prefix(prefix_key)
        try:
            message = _stream_once(client, params, timeout=timeout, deadline=deadline, first=first)
        except engine_errors.EngineError:
            _fail_prefix(prefix_key or "", first)
            raise
        except Exception as exc:  # noqa: BLE001 — every SDK failure leaves here as an engine error, in words
            _fail_prefix(prefix_key or "", first)
            translated = _translate(exc)
            if isinstance(translated, engine_errors.EngineModelNotFound) and moved is None:
                forward = anthropic_models.forward_after_refusal(model_id)
                if forward is not None:
                    logger.warning(f"Claude API: the model id was refused, moved forward to {forward.model}")
                    model_id, moved = forward.model, forward.note
                    continue
            raise translated from None
        _open_prefix(first)
        if prefix_key:
            _touch_prefix(prefix_key)
        usage.add(message.usage)
        stop = getattr(message, "stop_reason", None)
        if stop == "refusal":
            category = getattr(getattr(message, "stop_details", None), "category", None)
            logger.warning(f"Claude API: the model declined a call (stage {stage}, category {category})")
            raise engine_errors.EngineRefused(MODEL_REFUSED)
        text = _text_of(message)
        if stop == "max_tokens":
            raise engine_errors.EngineProtocolError(CUT_OFF)
        if not text.strip():
            raise engine_errors.EngineProtocolError(NO_ANSWER)
        served_id = str(getattr(message, "model", "") or model_id)
        return _shim(text=text, stop_reason=stop, served=served_id, usage=usage,
                     searches=_searches_of(message) if web_search else None)
