"""G74(a) — the Claude Code CLI as a Sleep engine.

One `claude -p` process per LLM call, on the user's own subscription, with
zero API credits. This module owns everything subprocess-shaped: the pinned
argv, stdin marshalling from OpenAI-shaped messages, the envelope parse and
its failure classification, the dual-access response shim, per-stage model and
schema selection, the throttle circuit breaker, and the pre-flight probe.

Three invariants, all load-bearing:

1. **The spawned engine can never write back into memory.** ``--safe-mode``
   disables CLAUDE.md, skills, plugins, hooks and MCP servers;
   ``--strict-mcp-config`` with no ``--mcp-config`` is the independent second
   lock. Together they guarantee the engine cannot call Cicada's own MCP tools
   and consolidate its own consolidation turns.
2. **Never ``--bare``.** It forces ``ANTHROPIC_API_KEY``/``apiKeyHelper`` and
   never reads OAuth — the exact wrong mode for a subscription. The env is
   scrubbed of provider keys (``base.scrubbed_env``) for the same reason.
3. **Prefix-ordered prompts.** Prompt caching persists across separate ``-p``
   processes (spec §4, verified 5.4x on a 58 KB prompt, 1-hour TTL), so the
   stable system text goes to ``--system-prompt`` (argv, constant for a whole
   cycle) and ``marshal_prompt`` NEVER reorders the caller's messages.

The core is synchronous. The async seam wraps it in ``asyncio.to_thread``
rather than the other way around, because sync call sites (``dedup_sweep``,
``source_rewrite``, ``ask_service``) may already be inside a running loop,
where ``asyncio.run`` raises.
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any, Callable

from loguru import logger

from api.services import engine_errors
from api.services.auth import cicada_home
from api.services.connections.base import CliResult

#: ``runner(argv, *, stdin=None, timeout=None, cwd=None) -> CliResult``.
Runner = Callable[..., CliResult]

#: Every flag verified present and accepted together against `claude` 2.1.252
#: (spec §3/§9 V1). ``--tools ""`` is a flag/value pair, hence the empty string.
PINNED_FLAGS: tuple[str, ...] = (
    "-p", "--output-format", "json", "--safe-mode",
    "--strict-mcp-config", "--tools", "", "--no-session-persistence",
)

DEFAULT_AGENT_MODEL = "sonnet"
#: Matches ``entity_extractor.EXTRACTION_TIMEOUT_S`` — the only wall-clock
#: guard Stage 1 has. Call sites that pass ``timeout=`` always win.
DEFAULT_TIMEOUT_S = 300.0

JSON_ONLY_SUFFIX = (
    "Respond with a single JSON object and nothing else — no prose, "
    "no explanation, no markdown fences."
)

#: Per-stage ``--json-schema`` payloads. ONLY stages whose output shape is
#: fully specifiable ship one: a structured-output mode that drops unlisted
#: keys would silently gut entity extraction, and V1b verified the flag only
#: against a trivial schema. Every other stage gets ``JSON_ONLY_SUFFIX`` plus
#: the shared lenient parser (``json_parse``), which is belt-and-braces the
#: spec asks for regardless. Widen this map once a live cycle proves no
#: field-stripping.
SCHEMA_BY_STAGE: dict[str, dict] = {
    "disambiguation": {
        "type": "object",
        "properties": {
            "decision": {"type": "string", "enum": ["same", "different", "unsure"]},
            "reason": {"type": "string"},
        },
        "required": ["decision"],
    },
}

_RATE_LIMIT_MARKERS = ("rate limit", "rate_limit", "too many requests", "overloaded", "429")
_LOGGED_OUT_MARKERS = (
    "not logged in", "not authenticated", "claude auth login",
    "invalid api key", "oauth token has expired", "session expired",
)
_NOT_FOUND_MARKERS = ("model not found", "unknown model", "no such model")

_STATE_LOCK = threading.Lock()
_BREAKER: dict[str, str | None] = {"reason": None}
_MODELS_USED: set[str] = set()


# --------------------------------------------------------------------------- #
# Dual-access response shim (spec §3.1 non-negotiable 1)
# --------------------------------------------------------------------------- #


class _D(dict):
    """A dict whose values are reachable by attribute AND by key.

    Seven Sleep call sites read ``resp.choices[0].message.content``; two
    (``dedup_sweep.py:120``, ``source_rewrite.py:57``) read
    ``resp["choices"][0]["message"]["content"]``. A ``SimpleNamespace`` breaks
    the second; a bare dict breaks the first.
    """

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:  # so getattr(resp, "_hidden_params", None) works
            raise AttributeError(name) from exc


def _wrap(value: Any) -> Any:
    if isinstance(value, dict):
        return _D({k: _wrap(v) for k, v in value.items()})
    if isinstance(value, list):
        return [_wrap(v) for v in value]
    return value


def _bare_model(model: str) -> str:
    return (model or "").strip().split("/")[-1].lower()


def model_from_envelope(envelope: dict, requested_model: str) -> str:
    """The model that actually did the work.

    ``modelUsage`` is multi-model (V1d: one call reported ``claude-haiku-4-5``
    for an internal side-call *and* the requested ``claude-sonnet-5``), so
    never assume one key. Prefer the entry whose ``canonicalModel`` matches
    what we asked for; when we asked by alias ("sonnet"), fall back to the
    entry that emitted the most output tokens.

    Why the heaviest-output-tokens fallback specifically (review nit 3): when
    the request named an alias, nothing in ``modelUsage`` identifies *which*
    key answered that alias — the envelope carries no "this is the one you
    asked for" flag, only a bag of ``{canonical_model: usage}`` entries. Most
    output tokens is the best available proxy (the requested main-model turn
    is normally the substantive one; a side-call is normally a short internal
    check), and it is exactly correct for the real recorded V1d shape (sonnet:
    57 output tokens, haiku side-call: 8). It is still a heuristic, not exact
    matching: a verbose internal side-call could in principle out-output a
    terse main-model turn and get mis-attributed — pinned as a known,
    accepted limitation by
    ``test_model_from_envelope_alias_heuristic_can_misattribute_a_verbose_side_call``.
    """
    per_model = envelope.get("modelUsage")
    if not isinstance(per_model, dict) or not per_model:
        return requested_model
    want = _bare_model(requested_model)
    for key, info in per_model.items():
        canonical = (info or {}).get("canonicalModel") or key
        if want and (_bare_model(canonical) == want or _bare_model(key) == want):
            return key
    return max(
        per_model.items(),
        key=lambda kv: int((kv[1] or {}).get("outputTokens") or 0),
    )[0]


def equiv_cost_from_envelope(envelope: dict) -> float | None:
    """List-price metering for this call, summed across every model it used.

    ``costBasis: "list"`` says this is metering, not money charged — which is
    exactly why it lands in ``equiv_cost_usd`` and never in ``cost_usd``.
    """
    total = envelope.get("total_cost_usd")
    if isinstance(total, (int, float)) and not isinstance(total, bool):
        return float(total)
    per_model = envelope.get("modelUsage")
    if not isinstance(per_model, dict):
        return None
    costs = [
        float(v["costUSD"]) for v in per_model.values()
        if isinstance(v, dict) and isinstance(v.get("costUSD"), (int, float))
        and not isinstance(v.get("costUSD"), bool)
    ]
    return round(sum(costs), 6) if costs else None


def response_shim(envelope: dict, requested_model: str) -> _D:
    """The envelope, wearing an OpenAI response's clothes.

    ``prompt_tokens`` is the GROSS prompt with the cache counters carried
    alongside as a breakdown of it — the contract
    ``telemetry.usage_from_response`` documents and ``pricing.estimate_cost``
    depends on. Verified necessary: a 58 KB prompt reported ``input_tokens: 2``
    with ``cache_creation_input_tokens: 19631``, so reading ``input_tokens``
    alone would record a 20k-token prompt as 2 (V2b).
    """
    usage = envelope.get("usage") or {}
    cache_read = int(usage.get("cache_read_input_tokens") or 0)
    cache_write = int(usage.get("cache_creation_input_tokens") or 0)
    raw_input = int(usage.get("input_tokens") or 0)
    output = int(usage.get("output_tokens") or 0)

    content = envelope.get("result")
    if content is None and envelope.get("structured_output") is not None:
        content = json.dumps(envelope["structured_output"], ensure_ascii=False)

    return _wrap({
        "choices": [{
            "message": {"role": "assistant", "content": content or ""},
            "finish_reason": envelope.get("stop_reason"),
        }],
        "model": model_from_envelope(envelope, requested_model),
        "usage": {
            "prompt_tokens": raw_input + cache_read + cache_write,
            "completion_tokens": output,
            "cache_read_input_tokens": cache_read,
            "cache_creation_input_tokens": cache_write,
            "prompt_tokens_details": {"cached_tokens": cache_read},
        },
    })


# --------------------------------------------------------------------------- #
# argv + prompt
# --------------------------------------------------------------------------- #

#: Conservative charset for a `--model` value: alphanumerics, dash, dot,
#: slash, colon — and NEVER a leading `-` (review fix round 1, M1). A model
#: id/alias is always drawn from a small known set (an alias like "sonnet" or
#: a canonical id like "claude-sonnet-5"); nothing legitimate needs any other
#: character, so a value that fails this is rejected here, before any
#: subprocess spawns, rather than shipped as a raw argv token.
_MODEL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:-]*$")


def build_argv(
    *,
    model: str,
    system_prompt: str,
    json_schema: dict | None = None,
    binary: str = "claude",
) -> list[str]:
    """The pinned invocation. Never grows a ``--bare``, never a ``--mcp-config``.

    Argv hardening (review fix round 1, M1): a `--model`/`--system-prompt`
    value beginning with ``-`` would otherwise be appended as a bare argv
    token right after its flag, with no ``--`` end-of-options sentinel and no
    validation — not shell injection (list-form ``subprocess.run``/
    ``create_subprocess_exec``, never a shell), but a value that could be
    misread as a flag by the CLI's own parser. Two different fixes, chosen
    per field:

    - ``model`` is validated against :data:`_MODEL_ID_RE` and rejected with
      :class:`engine_errors.EngineModelNotFound` before any subprocess spawns.
      A model id is always drawn from a small known set, so this never fires
      on a legitimate value.
    - ``system_prompt`` is joined into a single ``--system-prompt=<value>``
      token instead of two. Verified live against `claude` 2.1.252:
      ``--flag=value`` is accepted as one token, and a leading ``-`` in
      ``value`` is never read as a new option — confirmed with
      ``--model=-oops --output-format bogus``, which failed on the *forced*
      ``--output-format`` error and never on ``-oops``. This makes the whole
      prompt structurally safe regardless of its first character, with no
      content rejected (the system prompt is free-form template text, not a
      value from a small known set, so validate-and-reject would be the wrong
      tool here).
    """
    if model and not _MODEL_ID_RE.match(model):
        raise engine_errors.EngineModelNotFound(
            f"invalid model id/alias: {model!r} — expected alphanumerics, "
            "'.', '-', '/', ':' only, and never a leading '-'"
        )
    argv = [binary, *PINNED_FLAGS]
    if model:
        argv += ["--model", model]
    if system_prompt:
        argv += [f"--system-prompt={system_prompt}"]
    if json_schema is not None:
        argv += ["--json-schema", json.dumps(json_schema, separators=(",", ":"))]
    return argv


def marshal_prompt(messages: list[dict] | None) -> tuple[str, str]:
    """Split OpenAI-shaped messages into ``(--system-prompt text, stdin body)``.

    Order is PRESERVED and never rewritten. Prompt-cache affinity (spec §4)
    depends on the caller putting stable content first; reordering here would
    break that contract *and* change meaning.
    """
    system_parts: list[str] = []
    turns: list[tuple[str, str]] = []
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "user").strip().lower()
        content = message.get("content")
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        if not content.strip():
            continue
        if role == "system":
            system_parts.append(content)
        else:
            turns.append((role, content))
    if len(turns) <= 1:
        body = turns[0][1] if turns else ""
    else:
        body = "\n\n".join(f"{role.upper()}: {text}" for role, text in turns)
    return "\n\n".join(system_parts), body


def scratch_dir() -> Path:
    """The engine's cwd: a scratch dir under ``$CICADA_HOME``.

    Never a memory bank (a stray write must not land in versioned memory) and
    never the repo (``--safe-mode`` already disables CLAUDE.md, but running
    somewhere with nothing to read is the belt).
    """
    path = cicada_home() / "engine-scratch"
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def model_for_stage(settings, stage: str | None) -> str:
    """The Claude model id/alias for a stage — mirrors the litellm main/judge split."""
    if (stage or "") == "disambiguation":
        return (getattr(settings, "agent_disambiguation_model", "") or "").strip() or DEFAULT_AGENT_MODEL
    return (getattr(settings, "agent_model", "") or "").strip() or DEFAULT_AGENT_MODEL


# --------------------------------------------------------------------------- #
# Envelope parsing + classification (spec §5 detection order)
# --------------------------------------------------------------------------- #


def _classify_error(envelope: dict, result: CliResult) -> engine_errors.EngineError:
    reason = str(envelope.get("terminal_reason") or envelope.get("subtype") or "").strip().lower()
    detail = " ".join(
        str(envelope.get(key) or "") for key in ("result", "error", "message")
    ).strip()
    blob = f"{detail} {result.stderr or ''}".lower()
    status = envelope.get("api_error_status")
    # The exact shape of a real 429/quota envelope could not be produced on
    # demand (spec §9). Log the whole envelope on every failure so the first
    # real one captured in the wild can tighten the markers below. The
    # envelope carries no credential — argv, stdin and env are never logged.
    logger.warning(f"claude engine error envelope: {json.dumps(envelope, default=str)[:2000]}")

    if reason == "budget_exhausted":
        return engine_errors.EngineExhausted(
            "Claude plan budget is exhausted for this window — Sleep stopped with the queue intact."
        )
    if any(marker in blob for marker in _LOGGED_OUT_MARKERS):
        return engine_errors.EngineUnavailable(
            "Claude Code is signed out — run `claude auth login`, then trigger Sleep again."
        )
    if status == 404 or any(marker in blob for marker in _NOT_FOUND_MARKERS):
        return engine_errors.EngineModelNotFound(
            f"the Claude CLI rejected the model id: {detail[:200]}"
        )
    if status == 429 or any(marker in blob for marker in _RATE_LIMIT_MARKERS):
        return engine_errors.EngineThrottled(f"Claude plan throttled: {detail[:200]}")
    return engine_errors.EngineFailed(
        f"`claude -p` failed ({reason or 'unknown reason'}): {detail[:200]}"
    )


def parse_envelope(result: CliResult) -> dict:
    """``CliResult`` -> the parsed envelope, or the right ``EngineError``.

    Detection order (spec §5): rc 127 -> binary missing; rc 124 -> timeout;
    non-JSON stdout -> unavailable; ``is_error`` -> classify.
    """
    if result.rc == 127:
        return _raise(engine_errors.EngineUnavailable(
            "Claude Code is not installed — install it (npm i -g @anthropic-ai/claude-code) "
            "and run `claude` once to sign in."
        ))
    if result.rc == 124:
        return _raise(engine_errors.EngineTimeout(
            f"`claude -p` timed out: {(result.stderr or '').strip()[:200]}"
        ))
    text = (result.stdout or "").strip()
    if not text:
        return _raise(engine_errors.EngineUnavailable(
            f"`claude -p` produced no output (rc {result.rc}): "
            f"{(result.stderr or '').strip()[:200] or 'no stderr'}"
        ))
    try:
        envelope = json.loads(text)
    except ValueError:
        return _raise(engine_errors.EngineUnavailable(
            f"`claude -p` did not return the JSON envelope (rc {result.rc}): {text[:200]}"
        ))
    if not isinstance(envelope, dict):
        return _raise(engine_errors.EngineProtocolError(
            f"envelope is not a JSON object: {text[:200]}"
        ))
    if envelope.get("is_error"):
        return _raise(_classify_error(envelope, result))
    if envelope.get("result") is None and envelope.get("structured_output") is None:
        return _raise(engine_errors.EngineProtocolError(
            f"envelope carries neither result nor structured_output: {text[:300]}"
        ))
    return envelope


def _raise(exc: engine_errors.EngineError):
    raise exc


# --------------------------------------------------------------------------- #
# Circuit breaker + models-used ledger (process-global, reset per Sleep cycle)
# --------------------------------------------------------------------------- #


def trip_breaker(reason: str) -> bool:
    """Trip the throttle breaker. Returns ``True`` only for the call that tripped it.

    Stage 1 fans out per-episode with no batch abort, so one throttle would be
    re-hit once per remaining episode. After the first, every subsequent call
    fails fast WITHOUT spawning and the cycle stops cleanly, leaving
    ``processed: false`` to do the rest.
    """
    with _STATE_LOCK:
        if _BREAKER["reason"]:
            return False
        _BREAKER["reason"] = reason or "Claude plan throttled"
        return True


def breaker_reason() -> str | None:
    with _STATE_LOCK:
        return _BREAKER["reason"]


def reset_breaker() -> None:
    with _STATE_LOCK:
        _BREAKER["reason"] = None


def record_model_used(model: str | None) -> None:
    """Remember a model the engine actually reported, for the commit trailers."""
    if not model:
        return
    with _STATE_LOCK:
        _MODELS_USED.add(str(model))


def models_used() -> list[str]:
    with _STATE_LOCK:
        return sorted(_MODELS_USED)


def reset_models_used() -> None:
    with _STATE_LOCK:
        _MODELS_USED.clear()


# --------------------------------------------------------------------------- #
# The call
# --------------------------------------------------------------------------- #


def _default_runner() -> Runner:
    from api.services.connections import base

    return base.run_cli_sync


def complete(
    *,
    messages: list[dict],
    model: str,
    stage: str | None = None,
    want_json: bool = False,
    timeout: float = DEFAULT_TIMEOUT_S,
    runner: Runner | None = None,
    binary: str = "claude",
) -> dict:
    """One `claude -p` call. Returns the parsed envelope; raises ``EngineError``.

    Synchronous by design — see the module docstring.
    """
    tripped = breaker_reason()
    if tripped:
        raise engine_errors.EngineThrottled(tripped)

    system_prompt, body = marshal_prompt(messages)
    schema = SCHEMA_BY_STAGE.get(stage or "") if want_json else None
    if want_json and schema is None:
        system_prompt = f"{system_prompt}\n\n{JSON_ONLY_SUFFIX}" if system_prompt else JSON_ONLY_SUFFIX

    argv = build_argv(model=model, system_prompt=system_prompt, json_schema=schema, binary=binary)
    run = runner or _default_runner()
    result = run(argv, stdin=body, timeout=timeout, cwd=str(scratch_dir()))
    return parse_envelope(result)


def probe(*, runner: Runner | None = None, binary: str = "claude", timeout: float = 20.0) -> tuple[bool, str]:
    """Pre-flight: is the agent rung usable right now? Returns ``(ok, sentence)``.

    The sentence is what the Sleep page shows, so it always names the fix.
    """
    run = runner or _default_runner()
    result = run([binary, "auth", "status", "--json"], stdin=None, timeout=timeout, cwd=None)
    if result.rc == 127:
        return False, (
            "Claude Code is not installed — install it (npm i -g @anthropic-ai/claude-code) "
            "and run `claude` once to sign in."
        )
    try:
        info = json.loads((result.stdout or "").strip() or "{}")
    except ValueError:
        return False, "Could not read `claude auth status` — run `claude` once in a terminal."
    if not isinstance(info, dict) or not info.get("loggedIn"):
        return False, "Claude Code is signed out — run `claude auth login`, then trigger Sleep again."
    if info.get("authMethod") not in (None, "claude.ai"):
        return False, (
            "Claude Code is signed in with an API key, not your plan — unset ANTHROPIC_API_KEY "
            "so Sleep runs on the subscription."
        )
    email = info.get("email")
    return True, f"Claude Code signed in as {email}." if email else "Claude Code signed in on this Mac."
