"""R-E2 — the ChatGPT plan as an engine: one ``codex exec`` per LLM call.

Mirror of ``agent_engine`` for OpenAI's own CLI, so everything above the seam
is reused: ``providers`` owns the shared semaphore, telemetry and the
throttle breaker (R-E19); this module owns what is subprocess-shaped — the
pinned argv, the per-call instructions/schema files, the JSONL reader and
its failure classification, and the OpenAI-shaped response shim.

Why ``codex exec`` and never a token (spec Decision 2): Cicada holds no
vendor credential. The person signs in once in Cicada's own Codex home
(``base.codex_home``) and every child runs there
(``base.scrubbed_env("codex")``). Calling ``chatgpt.com/backend-api`` with
Codex's client id is ruled out (R2 §3.4, transport C).

Invariants, each verified against codex-cli 0.154.0 (R2 §2, 2026-09-23):

1. **The engine can never write into memory or read the person's Codex
   setup.** ``--ignore-user-config`` loads no ``config.toml`` (so none of the
   person's MCP servers — Cicada's own included — and no plugins); the
   isolated home carries none of the person's skills, ``AGENTS.md`` or
   hooks; ``--disable hooks`` plus ``CICADA_CAPTURE=off`` are two locks on
   the G105 Stop hook; ``--disable memories`` keeps Codex's memory from
   learning the person's episodes; ``-s read-only`` and ``--disable
   shell_tool|unified_exec`` in an empty scratch cwd leave nothing to run
   and nowhere to write.
   **Not the same as no hidden context** (final review M4, measured
   2026-09-23 by pointing a signed-out 0.154.0 run at a local capture
   server, synthetic prompt): Codex unpacks its OWN bundled system skills
   into ``<home>/skills/.system`` on first run and lists them in every
   request (~10.8k chars) — turned off with ``skills.include_instructions=
   false`` (plus ``include_permissions_instructions`` and
   ``include_collaboration_mode_instructions`` for the notes that then take
   its place). What still rides every call and has no working switch here:
   the code-mode/collaboration tool namespace (~15k chars: ``exec``,
   ``spawn_agent``… despite ``--disable multi_agent``), a
   ``multi_agent_role`` note (~3.4k) and ``environment_context`` (~1k,
   kept: it carries the date). Request body 31.8k → 21.0k bytes; the
   signed-in token count is owed to the live check (G49).
2. **``--ephemeral``** writes no rollout file and no history line (60→60
   session files, 260→260 history lines), so Cicada's own Codex capture can
   never ingest Sleep's prompts.
3. **Cicada's prompt, not Codex's** (R-E15). ``model_instructions_file``
   replaces Codex's base coding-agent instructions; a stage with no system
   prompt gets ``DEFAULT_INSTRUCTIONS``. The file is written per call (0600)
   and deleted after — it can carry bank-derived text.
4. **Only a turn that never completes is a failure** (R-E16). ``item.type ==
   "error"`` items are warnings on a successful run, and a top-level
   ``error`` line is a transport retry notice ("Reconnecting... 2/5 (…)") when
   the turn still completes — seen on a real signed-out run 2026-09-23.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

from api.services import agent_engine, engine_errors, engine_schemas
from api.services.connections.base import CliResult

CODEX_PINNED: tuple[str, ...] = (
    "exec", "--ephemeral", "--ignore-user-config", "--ignore-rules", "--skip-git-repo-check",
    "-s", "read-only", "--json",
    "-c", 'web_search="disabled"',
    # Final review M4: the isolated home still ships Codex's bundled system
    # skills, and their listing rode every call (~10.8k chars); the sandbox
    # and collaboration-mode notes that surface in its place (~2k, ~1.7k)
    # are moot with no shell and no agents. All three measured off.
    "-c", "skills.include_instructions=false", "-c", "include_permissions_instructions=false",
    "-c", "include_collaboration_mode_instructions=false",
    "--disable", "memories", "--disable", "hooks", "--disable", "plugins", "--disable", "apps",
    "--disable", "multi_agent", "--disable", "shell_tool", "--disable", "unified_exec",
    "--disable", "image_generation", "--disable", "view_image",
)
DEFAULT_TIMEOUT_S = agent_engine.DEFAULT_TIMEOUT_S
DEFAULT_INSTRUCTIONS = (
    "Answer the request directly and completely. Do not run commands, read files or change anything."
)
INSTALL_HINT = (
    "Install Codex CLI (npm i -g @openai/codex), then sign in with ChatGPT on Settings → Plans & keys."
)
SIGNED_OUT = (
    "ChatGPT isn't signed in for Cicada — sign in with ChatGPT on Settings → Plans & keys, "
    "then run Sleep again."
)
API_KEY_ACCOUNT = (
    "Codex is signed in to Cicada with an API key, not a ChatGPT plan — that bills per token. "
    "Sign out and sign in with ChatGPT on Settings → Plans & keys."
)
#: R-E15: strict schemas for the two stages whose shape is fully specifiable.
SCHEMA_BY_STAGE: dict[str, dict] = {
    "extraction": engine_schemas.extraction_schema(strict=True),
    "disambiguation": engine_schemas.disambiguation_schema(strict=True),
}
_EFFORT_RE = re.compile(r"^[a-z]+$")
_LOGGED_OUT_MARKERS = (
    "401 unauthorized", "missing bearer", "not logged in", "sign in again", "log in again",
    "refresh token was already used", "refresh token was revoked", "refresh_token_expired",
    "refresh_token_reused", "refresh_token_invalidated",
)
_NOT_FOUND_MARKERS = ("model_not_found", "model not found", "does not exist", "is not supported",
                      "unknown model")
_SCHEMA_MARKERS = ("invalid_json_schema", "invalid schema")
_LIMIT_MARKERS = ("usage limit", "rate limit", "rate_limit", "too many requests", "429", "limit reached")


@dataclass
class ExecResult:
    text: str | None = None
    usage: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    failure: str | None = None
    completed: bool = False
    json_lines: int = 0


def scratch_dir() -> Path:
    path = agent_engine.scratch_dir() / "codex"
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def model_for_stage(settings, stage: str | None) -> str:
    """``""`` = no ``-m`` (R-E17). Disambiguation falls back to the main model."""
    main = str(getattr(settings, "codex_model", "") or "").strip()
    if (stage or "") == "disambiguation":
        return str(getattr(settings, "codex_disambiguation_model", "") or "").strip() or main
    return main


def effort_for(settings) -> str:
    return str(getattr(settings, "codex_reasoning_effort", "low") or "").strip()


def build_argv(*, model: str, effort: str, instructions_path: Path, cwd: Path,
               schema_path: Path | None = None, binary: str = "codex") -> list[str]:
    """The pinned invocation. Never a ``--dangerously-*`` flag, never a
    writable sandbox. ``model``/``effort`` are validated before any spawn
    (the ``agent_engine`` M1 rule: a leading ``-`` must never become a flag)."""
    if model and not agent_engine.is_valid_model_id(model):
        raise engine_errors.EngineModelNotFound(
            f"invalid model id: {model!r} — expected alphanumerics, '.', '-', '/', ':' only")
    if effort and not _EFFORT_RE.match(effort):
        raise engine_errors.EngineModelNotFound(
            f"invalid reasoning effort: {effort!r} — expected a lowercase word such as 'low'")
    argv = [binary, *CODEX_PINNED, "-C", str(cwd)]
    if model:
        argv += ["-m", model]
    if effort:
        argv += ["-c", f'model_reasoning_effort="{effort}"']
    # json.dumps is a valid TOML basic string for a path (Codex parses `-c`
    # values as TOML); a file keeps TOML quoting away from the prompt itself.
    argv += ["-c", f"model_instructions_file={json.dumps(str(instructions_path))}"]
    if schema_path is not None:
        argv += ["--output-schema", str(schema_path)]
    argv.append("-")
    return argv


def parse_events(stdout: str | None) -> ExecResult:
    """``codex exec --json`` JSONL → the answer, usage, warnings and — only
    if the turn never completed — the failure (R-E16)."""
    out = ExecResult()
    last_error: str | None = None
    for raw in (stdout or "").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            event = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        out.json_lines += 1
        kind = event.get("type")
        if kind == "item.completed":
            item = event.get("item") or {}
            if item.get("type") == "agent_message" and isinstance(item.get("text"), str):
                out.text = item["text"]
            elif item.get("type") == "error":
                out.warnings.append(str(item.get("message") or "")[:300])
        elif kind == "turn.completed":
            out.completed = True
            out.usage = event.get("usage") or {}
        elif kind == "turn.failed":
            out.failure = str((event.get("error") or {}).get("message") or "turn failed")
        elif kind == "error":
            last_error = str(event.get("message") or "error")
            out.warnings.append(last_error[:300])
    if out.failure is None and not out.completed and last_error is not None:
        out.failure = last_error
    return out


def check(result: CliResult, parsed: ExecResult) -> None:
    """Raise the ``EngineError`` a failed call means; return on success."""
    if result.rc == 127:
        raise engine_errors.EngineUnavailable(INSTALL_HINT)
    if result.rc == 124:
        raise engine_errors.EngineTimeout(f"`codex exec` timed out: {(result.stderr or '').strip()[:200]}")
    if result.rc == 0 and parsed.completed and parsed.failure is None and parsed.text is not None:
        for warning in parsed.warnings:
            logger.info(f"codex engine warning: {warning}")
        return
    if parsed.json_lines == 0:
        raise engine_errors.EngineUnavailable(
            f"`codex exec` produced no events (rc {result.rc}): "
            f"{(result.stderr or '').strip()[:200] or 'no stderr'}")
    reason = parsed.failure or ""
    # Log the whole failure message the first time any shape is seen — the
    # agent_engine stance for failures that could not be produced on demand.
    logger.warning(f"codex engine failure (rc {result.rc}): {reason[:500]}")
    blob = f"{reason} {result.stderr or ''}".lower()
    if any(m in blob for m in _LOGGED_OUT_MARKERS):
        raise engine_errors.EngineUnavailable(SIGNED_OUT)
    if any(m in blob for m in _NOT_FOUND_MARKERS):
        raise engine_errors.EngineModelNotFound(f"the ChatGPT plan rejected the model: {reason[:200]}")
    if any(m in blob for m in _SCHEMA_MARKERS):
        raise engine_errors.EngineProtocolError(f"Codex rejected the output schema: {reason[:200]}")
    if any(m in blob for m in _LIMIT_MARKERS):
        raise engine_errors.EngineThrottled(f"ChatGPT plan limit reached: {reason[:200]}")
    if parsed.failure is None:
        raise engine_errors.EngineProtocolError("`codex exec` finished without a reply")
    raise engine_errors.EngineFailed(f"`codex exec` failed: {reason[:200]}")


def _write_private(directory: Path, suffix: str, text: str) -> Path:
    fd, name = tempfile.mkstemp(prefix="call-", suffix=suffix, dir=directory)   # 0600
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
    return Path(name)


def complete(*, messages: list[dict], model: str, stage: str | None = None, want_json: bool = False,
             timeout: float = DEFAULT_TIMEOUT_S, runner=None, binary: str = "codex",
             scope: str | None = None, effort: str = "low") -> ExecResult:
    """One ``codex exec`` call; raises ``EngineError``. Synchronous by design,
    like ``agent_engine.complete`` (the seam wraps it in ``to_thread``)."""
    scope = scope or agent_engine.current_scope()
    tripped = agent_engine.breaker_reason(scope=scope)
    if tripped:
        exc = engine_errors.EngineThrottled(tripped)
        exc.spawned = False
        raise exc
    system_prompt, body = agent_engine.marshal_prompt(messages)
    schema = SCHEMA_BY_STAGE.get(stage or "") if want_json else None
    if want_json and schema is None:
        suffix = agent_engine.JSON_ONLY_SUFFIX
        system_prompt = f"{system_prompt}\n\n{suffix}" if system_prompt else suffix
    workdir = scratch_dir()
    cwd = workdir / "cwd"
    cwd.mkdir(mode=0o700, exist_ok=True)
    written: list[Path] = []
    try:
        instructions = _write_private(workdir, ".md", system_prompt or DEFAULT_INSTRUCTIONS)
        written.append(instructions)
        schema_path = None
        if schema is not None:
            schema_path = _write_private(workdir, ".json", json.dumps(schema, separators=(",", ":")))
            written.append(schema_path)
        argv = build_argv(model=model, effort=effort, instructions_path=instructions, cwd=cwd,
                          schema_path=schema_path, binary=binary)
        run = runner or agent_engine._default_runner()
        result = run(argv, stdin=body, timeout=timeout, cwd=str(cwd))
    finally:
        for path in written:
            with suppress(OSError):
                path.unlink()
    parsed = parse_events(result.stdout)
    check(result, parsed)
    return parsed


def response_shim(parsed: ExecResult, requested_model: str):
    """OpenAI clothes on the Codex answer. ``input_tokens`` is already gross
    (cached tokens are a subset under OpenAI's semantics), which is exactly
    the ledger's rule (``telemetry.usage_from_response``). exec does not echo
    the served model, so the model is the one requested (R2 §4.3)."""
    usage = parsed.usage or {}
    prompt = int(usage.get("input_tokens") or 0)
    cached = int(usage.get("cached_input_tokens") or 0)
    return agent_engine._wrap({
        "choices": [{"message": {"role": "assistant", "content": parsed.text or ""},
                     "finish_reason": "stop"}],
        "model": requested_model or "",
        "usage": {"prompt_tokens": prompt, "completion_tokens": int(usage.get("output_tokens") or 0),
                  "cache_read_input_tokens": cached, "cache_creation_input_tokens": 0,
                  "prompt_tokens_details": {"cached_tokens": cached}},
    })


def probe(*, runner=None, timeout: float = 5.0) -> tuple[bool, str]:
    """``codex login status`` (≈0.01 s) — the cheap fallback when the
    app-server is unavailable. Never the app-server itself."""
    run = runner or agent_engine._default_runner()
    result = run(["codex", "login", "status"], stdin=None, timeout=timeout, cwd=None)
    if result.rc == 127:
        return False, INSTALL_HINT
    if result.rc != 0:
        return False, SIGNED_OUT
    return True, "Signed in to ChatGPT."


async def preflight(*, snapshot_fn=None, probe_fn=None, now=None) -> tuple[bool, str, str | None]:
    """R-E18: before a cycle's first spawn — signed in? on the plan (not an
    API key)? limit already reached? — and the plan's current default model
    (R-E17). Returns ``(ok, sentence, default_model)``."""
    from api.services import codex_app_server, plan_limits, pricing

    snap = await (snapshot_fn or codex_app_server.snapshot)(fresh=True)
    if snap is None:
        ok, detail = await asyncio.to_thread(probe_fn or probe)
        return ok, ("Signed in to ChatGPT (plan details unavailable right now)." if ok else detail), None
    if not snap.signed_in:
        return False, SIGNED_OUT, None
    # Final review M3: a signed-in reply with no ``type`` is not proof of an
    # API key — treating it as one aborted every ChatGPT-plan cycle while the
    # card (``codex_cli.status``, same tolerance) read Connected. Only a type
    # that is present and not ``chatgpt`` is refused.
    if snap.account_type not in (None, "chatgpt"):
        return False, API_KEY_ACCOUNT, None
    stop = plan_limits.codex_stop(snap, now=now)
    if stop:
        return False, stop, None
    label = pricing.plan_label("chatgpt-plan", snap.plan, None) or "your ChatGPT plan"
    return True, f"Signed in to {label}.", snap.default_model
