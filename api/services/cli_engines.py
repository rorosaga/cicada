"""G49 / G50 — the person's own signed-in agent CLIs as Sleep engines: Cursor, OpenCode and Grok.

The mirror of ``codex_engine`` for three more harnesses, so everything above the seam is reused: ``providers`` owns
the shared semaphore, telemetry and the throttle breaker; this module owns what is subprocess-shaped — one spec per
tool (its binary, its pinned argv, its output reader, its failure words), the cached sign-in probe, the live model
list and the pre-flight a cycle runs before its first spawn.

Rails, each one a test in ``test_cli_engines.py``:

1. **The person's own login, never ours.** Cicada spawns the CLI the person installed and signed into. It never reads,
   copies or stores the tool's credential files, never signs in for them and never installs anything; a missing or
   signed-out tool says the exact command the person runs. The key variables that would move a tool off its sign-in
   (``CURSOR_API_KEY``, ``XAI_API_KEY`` …) are stripped from every child (``base.scrubbed_env``).
2. **Plan, not metered.** Cursor runs on the person's Cursor plan (Cursor bills usage past the included amount only if
   the person turned that on in their Cursor account — said in words on the card). OpenCode routes to many providers:
   only the subscription sign-ins (``OPENCODE_PLAN_PROVIDERS``) count as a plan, and a model on any other provider is
   refused before a call, said in words — an API key the person wants is Sleep's API-key engine, not OpenCode. Grok
   prefers its signed-in session over ``XAI_API_KEY`` (which Cicada strips); a reply that carries a charged cost is
   API-key traffic, and the run stops on it.
3. **Headless, structured, no tools.** Every call runs in an empty scratch directory with each tool's own no-tools
   switches: Cursor in ask mode without ``--force`` plus a deny-all ``.cursor/cli.json``; OpenCode with
   ``OPENCODE_PERMISSION={"*":"deny"}`` and no plugins or Claude Code config; Grok with ``dontAsk``, every tool kind
   denied, no web search, no subagents and no plan mode.
4. **Its own runs are never captured.** ``CICADA_CAPTURE=off`` and ``CICADA_RECALL=off`` ride every child; Cicada's
   Cursor and Gemini CLI hooks (and the Claude Code hooks Grok also runs) exit on them.
5. **A plan limit is a pause.** Usage and rate-limit words map to ``EngineThrottled``, which trips the breaker and
   pauses the drain with the tool's own sentence.

Antigravity is not here: Google's own FAQ says wrapping ``agy`` inside another application "is not supported under
consumer plans", and Gemini CLI stopped serving personal Google sign-ins on 2026-06-18 (report, plan-engines).
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import tempfile
import threading
import time
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from loguru import logger

from api.services import agent_engine, engine_errors
from api.services.connections.base import CliResult


@dataclass(frozen=True)
class EngineSpec:
    mode: str                 # the `llm_mode` / picker id
    label: str                # the engine label (`ENGINE_LABELS`, telemetry, the Cicada-Engine trailer)
    connection: str           # the ledger's connection id for this plan
    name: str                 # the tool's own name — shown only where it is the person's choice
    plan_name: str            # how a run on it is named ("Cursor plan")
    binaries: tuple[str, ...]  # tried in order; the first that resolves runs
    install: str              # the exact install line, in words
    sign_in: str              # the exact sign-in command
    default_models: tuple[str, ...] = ()
    billing_note: str = ""    # how a metered path could arise, in words, for the picker
    flag_model: str = "--model"
    #: Always pass an explicit model (review of #494): a tool's own config default could be a key-backed model.
    explicit_model: bool = False


CURSOR = EngineSpec(
    mode="cursor", label="cursor-cli", connection="cursor-plan", name="Cursor", plan_name="Cursor plan",
    binaries=("cursor-agent", "agent"),
    install="Install Cursor's command line (curl https://cursor.com/install -fsS | bash), then run `agent login`.",
    sign_in="agent login",
    # Cursor's own Auto model is part of every plan; the live `agent models` list adds the rest.
    default_models=("auto",),
    billing_note=("Runs on your Cursor plan. Past its included usage Cursor stops, unless you turned on "
                  "usage-based pricing in your Cursor account — then it bills there."),
)
OPENCODE = EngineSpec(
    mode="opencode", label="opencode-cli", connection="opencode-plan", name="OpenCode", plan_name="OpenCode plan",
    binaries=("opencode",),
    install="Install OpenCode (curl -fsSL https://opencode.ai/install | bash), then run `opencode auth login`.",
    sign_in="opencode auth login",
    billing_note=("Only a subscription you signed in to through OpenCode (GitHub Copilot or OpenCode Go). "
                  "A model on an API key is never used here — choose an API key as the engine for that."),
    flag_model="-m", explicit_model=True,
)
GROK = EngineSpec(
    mode="grok", label="grok-cli", connection="grok-plan", name="Grok", plan_name="Grok plan",
    binaries=("grok",),
    install="Install Grok Build (see docs.x.ai/build/cli), then run `grok login`.",
    sign_in="grok login",
    billing_note=("Runs on your signed-in Grok subscription, only on xAI's own Grok models, and only when you "
                  "start a read. A key you set in Grok's own settings for one of those models would still bill "
                  "that key; if Grok reports a charged cost, Sleep stops."),
    flag_model="-m", explicit_model=True,
)
SPECS: dict[str, EngineSpec] = {s.mode: s for s in (CURSOR, OPENCODE, GROK)}
BY_LABEL: dict[str, EngineSpec] = {s.label: s for s in SPECS.values()}
MODES: tuple[str, ...] = tuple(SPECS)

#: OpenCode providers that are a subscription sign-in (opencode.ai/docs/providers): GitHub Copilot and OpenCode Go.
#: Every other provider OpenCode routes to bills an API key or pay-as-you-go credit (rail 2), and the ChatGPT and
#: Claude subscriptions have their own engines here.
OPENCODE_PLAN_PROVIDERS = ("github-copilot", "opencode-go")

DEFAULT_TIMEOUT_S = agent_engine.DEFAULT_TIMEOUT_S
DEFAULT_INSTRUCTIONS = "Answer the request directly and completely, from the text it gives you."
NO_TOOLS_LINE = "Do not run commands, read or write files, browse, or use any tool. Reply with the answer only."

#: The longest prompt one argv string may carry: Linux caps a single argument at 128 KiB (MAX_ARG_STRLEN); macOS
#: caps the whole argv near 1 MiB. Grok and OpenCode take a file instead and are not bound by this.
_ARG_LIMIT = 120_000 if sys.platform.startswith("linux") else 900_000

_SIGNED_OUT = ("not logged in", "not authenticated", "authentication required", "login required", "please log in",
               "please login", "log in first", "sign in", "unauthorized", "no credentials",
               "run `grok login`", "run grok login", "set xai_api_key", "agent login", "auth login")
_LIMIT = ("usage limit", "rate limit", "rate_limit", "ratelimit", "too many requests", "limit reached",
          "quota", "resource_exhausted", "weekly limit", "out of credits", "usage pool", "hit your limit")
#: A bare HTTP status only as its own token (review of #494): never inside a request id, a hash or a longer number.
_STATUS_401 = re.compile(r"(?<![\w.-])401(?![\w.-])")
_STATUS_429 = re.compile(r"(?<![\w.-])429(?![\w.-])")
_NOT_FOUND = ("model not found", "model_not_found", "unknown model", "invalid model", "unsupported model",
              "model is not available", "not a valid model", "no such model", "providermodelnotfound")


@dataclass
class ExecResult:
    text: str | None = None
    usage: dict = field(default_factory=dict)
    model: str | None = None        # the model the tool REPORTED serving, never a guess
    cost_usd: float | None = None   # a charged cost the tool reported (Grok on an API key)
    failure: str | None = None
    events: int = 0


# --------------------------------------------------------------------------- #
# Settings → the call
# --------------------------------------------------------------------------- #


def spec_for(mode_or_label: str | None) -> EngineSpec | None:
    key = (mode_or_label or "").strip().lower()
    return SPECS.get(key) or BY_LABEL.get(key)


def model_for_stage(settings, stage: str | None) -> str:
    """``""`` = no model flag (the tool's own default). Disambiguation falls back to the main model."""
    main = str(getattr(settings, "cli_engine_model", "") or "").strip()
    if (stage or "") == "disambiguation":
        return str(getattr(settings, "cli_engine_disambiguation_model", "") or "").strip() or main
    return main


def opencode_is_plan_model(model: str) -> bool:
    provider = (model or "").split("/", 1)[0].strip().lower()
    return "/" in (model or "") and provider in OPENCODE_PLAN_PROVIDERS


#: xAI's own built-in models (docs: custom models — "By default, Grok uses models hosted by SpaceXAI"). A
#: `config.toml` model with its own `base_url`/`api_key` (OpenAI, Anthropic, Bedrock …) outranks the sign-in, so
#: only these ids are ever offered or passed; Cicada never reads `config.toml` to tell them apart.
_GROK_BUILTIN = re.compile(r"^grok-[a-z0-9][a-z0-9.-]*$")


def grok_is_builtin(model: str) -> bool:
    return bool(_GROK_BUILTIN.match((model or "").strip()))


def plan_model(spec: EngineSpec, model: str) -> bool:
    """A model this tool runs on the person's plan: OpenCode's subscription providers, Grok's built-in ids, any
    Cursor model (Cursor's own plan)."""
    if spec is OPENCODE:
        return opencode_is_plan_model(model)
    if spec is GROK:
        return grok_is_builtin(model)
    return bool(model)


def metered_refusal(spec: EngineSpec, model: str) -> str | None:
    """Why a model is refused before any call because it would bill an API key (rail 2), else ``None``."""
    if spec is OPENCODE and model and not opencode_is_plan_model(model):
        return (f"OpenCode would run {model} on an API key or paid credit, not a subscription — Sleep runs OpenCode "
                f"only on GitHub Copilot or OpenCode Go. Choose one of those models, or choose an API key as "
                f"Sleep's engine in Settings → Intelligence. Nothing was read.")
    if spec is GROK and model and not grok_is_builtin(model):
        return (f"{model} isn't one of xAI's own Grok models, so Grok would run it through a key or another "
                f"provider set in its own settings, not your subscription — Sleep runs Grok only on its grok-… "
                f"models. Choose one of those. Nothing was read.")
    return None


def scratch_dir(spec: EngineSpec) -> Path:
    path = agent_engine.scratch_dir() / spec.mode
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def _empty_cwd(spec: EngineSpec) -> Path:
    """A fresh, empty working directory per call (a stray write lands nowhere that is read again)."""
    return Path(tempfile.mkdtemp(prefix="call-", dir=scratch_dir(spec)))


#: Cursor's project permissions file (cursor.com/docs/cli/reference/permissions): deny wins over allow.
CURSOR_DENY = {"permissions": {"allow": [], "deny": ["Shell(*)", "Read(**)", "Write(**)", "WebFetch(*)", "Mcp(*:*)"]}}
#: OpenCode's inline permission config (opencode.ai/docs/permissions): every tool denied.
OPENCODE_ENV = {
    "OPENCODE_PERMISSION": json.dumps({"*": "deny"}),
    "OPENCODE_DISABLE_CLAUDE_CODE": "1", "OPENCODE_DISABLE_PROJECT_CONFIG": "1",
    "OPENCODE_DISABLE_EXTERNAL_SKILLS": "1", "OPENCODE_DISABLE_AUTOUPDATE": "1", "OPENCODE_DISABLE_LSP_DOWNLOAD": "1",
}
#: Grok's tool kinds (docs: headless mode, permissions and safety): each denied, deny wins over every other rule.
GROK_DENY = ("Bash", "Edit", "Write", "Read", "Grep", "WebFetch", "MCPTool")
#: Review of #494, blocker 1: Grok scans Claude Code's and Cursor's config by default — their MCP servers (Cicada's
#: own among them: its handshake would ride the extraction prompt), hooks, rules, skills and instruction files. Every
#: compatibility cell off (docs: configuration → harness compatibility, config reference `compat.*`; env beats
#: config.toml), and no organisation-managed MCP fetch. `--deny MCPTool` alone blocks calls, never a server's start.
GROK_ENV = {
    **{f"GROK_{vendor}_{cell}_ENABLED": "false"
       for vendor in ("CLAUDE", "CURSOR") for cell in ("MCPS", "HOOKS", "RULES", "SKILLS", "AGENTS")},
    "GROK_MANAGED_MCPS_ENABLED": "false",
}


def _opencode_config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return Path(base) / "opencode"


def opencode_mcp_names() -> list[str]:
    """The MCP server names in the person's own global OpenCode config (``opencode.json[c]``) — names only, never a
    value; it is configuration, not a credential (those live in OpenCode's ``auth.json``, never read). ``cicada`` is
    always among them: Cicada wires itself in under that name (``agent_wiring``)."""
    from api.services import agent_wiring

    names = {"cicada"}
    for filename in ("opencode.json", "opencode.jsonc"):
        path = _opencode_config_dir() / filename
        try:
            data = agent_wiring._loads_jsonc(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        mcp = data.get("mcp") if isinstance(data, dict) else None
        if isinstance(mcp, dict):
            names.update(str(k) for k in mcp if isinstance(k, str) and k)
    return sorted(names)


def opencode_env() -> dict[str, str]:
    """OpenCode's per-call environment: every tool denied, and — review of #494, blocker 1 — every MCP server the
    person's config names turned off through Cicada's own ``OPENCODE_CONFIG_CONTENT`` (the highest config layer, set
    after the scrub strips any the person exported), so no server starts and none of their instructions loads."""
    content = {"$schema": "https://opencode.ai/config.json",
               "mcp": {name: {"enabled": False} for name in opencode_mcp_names()},
               "permission": {"*": "deny"}}
    return {**OPENCODE_ENV, "OPENCODE_CONFIG_CONTENT": json.dumps(content, separators=(",", ":"))}


def full_prompt(messages: list[dict], *, want_json: bool) -> str:
    """One text: Cicada's instructions, the no-tools line, then the request. None of these tools takes a
    replacement system prompt in print mode, so the instructions lead the message."""
    system_prompt, body = agent_engine.marshal_prompt(messages)
    instructions = system_prompt or DEFAULT_INSTRUCTIONS
    if want_json:
        instructions = f"{instructions}\n\n{agent_engine.JSON_ONLY_SUFFIX}"
    return f"{instructions}\n\n{NO_TOOLS_LINE}\n\n---\n\n{body}"


def _check_model(model: str) -> None:
    if model and not agent_engine.is_valid_model_id(model):
        raise engine_errors.EngineModelNotFound(
            f"invalid model id: {model!r} — expected alphanumerics, '.', '-', '/', ':' only")


def build_call(spec: EngineSpec, *, model: str, prompt: str, cwd: Path, binary: str) -> tuple[list[str], dict, str | None]:
    """``(argv, env overrides, stdin)`` for one call — never a ``--force``, ``--yolo``, ``--auto`` or
    always-approve flag. Writes any per-call file into ``cwd`` (deleted with it)."""
    _check_model(model)
    if spec is CURSOR:
        (cwd / ".cursor").mkdir(mode=0o700)
        (cwd / ".cursor" / "cli.json").write_text(json.dumps(CURSOR_DENY), encoding="utf-8")
        if len(prompt.encode("utf-8")) > _ARG_LIMIT:
            raise engine_errors.EngineFailed(
                f"this request is too long for one Cursor command line ({len(prompt)} characters)")
        argv = [binary, "-p", "--output-format", "json", "--mode", "ask", "--trust", "--workspace", str(cwd)]
        if model:
            argv += [spec.flag_model, model]
        argv.append(prompt)
        return argv, {"NO_OPEN_BROWSER": "1"}, None
    if spec is OPENCODE:
        prompt_path = cwd / "request.md"
        prompt_path.write_text(prompt, encoding="utf-8")
        argv = [binary, "run", "--format", "json", "--pure", "--dir", str(cwd)]
        if model:
            argv += [spec.flag_model, model]
        argv += ["--file", str(prompt_path), "Answer the request in the attached file, following its instructions."]
        return argv, opencode_env(), None
    # Grok
    prompt_path = cwd / "request.md"
    prompt_path.write_text(prompt, encoding="utf-8")
    argv = [binary, "--prompt-file", str(prompt_path), "--output-format", "json", "--cwd", str(cwd),
            "--no-auto-update", "--permission-mode", "dontAsk", "--disable-web-search", "--no-subagents",
            "--no-plan", "--disallowed-tools", "Agent", "--max-turns", "4"]
    for kind in GROK_DENY:
        argv += ["--deny", kind]
    if model:
        argv += [spec.flag_model, model]
    return argv, dict(GROK_ENV), None


# --------------------------------------------------------------------------- #
# Output readers
# --------------------------------------------------------------------------- #


def _json_objects(stdout: str | None) -> list[dict]:
    """Every JSON object in ``stdout``: one document, or one per line (NDJSON)."""
    text = (stdout or "").strip()
    if not text:
        return []
    try:
        whole = json.loads(text)
        return [whole] if isinstance(whole, dict) else []
    except ValueError:
        pass
    out: list[dict] = []
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw.startswith("{"):
            continue
        try:
            obj = json.loads(raw)
        except ValueError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def parse_cursor(stdout: str | None) -> ExecResult:
    """``agent -p --output-format json``: one ``{"type":"result","subtype":"success","is_error":false,"result":…}``
    (cursor.com/docs/cli/reference/output-format). A failure prints no JSON and exits non-zero."""
    out = ExecResult()
    for obj in _json_objects(stdout):
        out.events += 1
        if obj.get("type") == "result":
            if obj.get("is_error") or obj.get("subtype") not in (None, "success"):
                out.failure = str(obj.get("result") or obj.get("error") or obj.get("subtype") or "failed")
            elif isinstance(obj.get("result"), str):
                out.text = obj["result"]
        elif obj.get("type") == "system" and obj.get("model"):
            out.model = str(obj["model"])
    return out


def parse_opencode(stdout: str | None) -> ExecResult:
    """``opencode run --format json``: one event per line — ``text`` (``part.text``), ``step_finish``
    (``part.tokens``), ``error`` (``error.message`` or ``error.data.message``)."""
    out = ExecResult()
    texts: list[str] = []
    tokens = {"input": 0, "output": 0, "cache_read": 0}
    for obj in _json_objects(stdout):
        out.events += 1
        kind = obj.get("type")
        part = obj.get("part") if isinstance(obj.get("part"), dict) else {}
        if kind == "text" and isinstance(part.get("text"), str):
            texts.append(part["text"])
        elif kind == "step_finish":
            t = part.get("tokens") if isinstance(part.get("tokens"), dict) else {}
            tokens["input"] += int(t.get("input") or 0)
            tokens["output"] += int(t.get("output") or 0)
            cache = t.get("cache") if isinstance(t.get("cache"), dict) else {}
            tokens["cache_read"] += int(cache.get("read") or 0)
            if part.get("modelID"):
                out.model = f"{part.get('providerID')}/{part['modelID']}" if part.get("providerID") else str(part["modelID"])
        elif kind == "error":
            err = obj.get("error") if isinstance(obj.get("error"), dict) else {}
            data = err.get("data") if isinstance(err.get("data"), dict) else {}
            out.failure = str(data.get("message") or err.get("message") or err.get("name") or "error")
    if texts:
        out.text = "".join(texts).strip()
    out.usage = tokens
    return out


def parse_grok(stdout: str | None) -> ExecResult:
    """``grok --output-format json``: ``{"text", "stopReason", "modelUsage": {model: …}, "usage", "total_cost_usd"?}``,
    or ``{"type":"error","message":…}`` on a failure (xai-org/grok-build docs, headless mode)."""
    out = ExecResult()
    for obj in _json_objects(stdout):
        out.events += 1
        if obj.get("type") == "error":
            out.failure = str(obj.get("message") or "error")
            continue
        if isinstance(obj.get("text"), str):
            out.text = obj["text"]
        usage = obj.get("usage") if isinstance(obj.get("usage"), dict) else {}
        out.usage = {"input": int(usage.get("input_tokens") or 0), "output": int(usage.get("output_tokens") or 0),
                     "cache_read": int(usage.get("cache_read_input_tokens") or 0)}
        models = obj.get("modelUsage") if isinstance(obj.get("modelUsage"), dict) else {}
        if models:
            # The model that made the most calls is the one that answered; a compaction side-call never wins.
            out.model = max(models, key=lambda m: int((models[m] or {}).get("modelCalls") or 0))
        cost = obj.get("total_cost_usd")
        if isinstance(cost, (int, float)) and not isinstance(cost, bool) and cost > 0:
            out.cost_usd = float(cost)
        stop = str(obj.get("stopReason") or "")
        if stop and stop not in ("end_turn", "stop_sequence"):
            out.failure = out.failure or f"stopped: {stop}"
    return out


PARSERS: dict[str, Callable[[str | None], ExecResult]] = {
    "cursor": parse_cursor, "opencode": parse_opencode, "grok": parse_grok,
}


def check(spec: EngineSpec, result: CliResult, parsed: ExecResult) -> None:
    """Raise the ``EngineError`` a failed call means; return on success."""
    if result.rc == 127:
        raise engine_errors.EngineUnavailable(f"{spec.name} isn't installed. {spec.install}")
    if parsed.cost_usd is not None:
        # Rail 2: a charged cost is API-key traffic, not the plan. The answer is kept; nothing after it runs.
        raise engine_errors.EngineOverage(
            f"{spec.name} reported a charged cost for that read, so it ran on an API key, not your plan — Sleep "
            f"stopped. Remove the key from {spec.name}'s own settings, or choose an API key as Sleep's engine.")
    ok = result.rc == 0 and parsed.failure is None and bool((parsed.text or "").strip())
    if ok:
        return
    reason = parsed.failure or ""
    blob = f"{reason} {result.stderr or ''} {result.stdout if parsed.events == 0 else ''}".lower()
    logger.warning(f"{spec.label} engine failure (rc {result.rc}): {reason[:300] or (result.stderr or '')[:300]}")
    if any(m in blob for m in _LIMIT) or _STATUS_429.search(blob):
        raise engine_errors.EngineThrottled(f"Your {spec.plan_name} hit its usage limit — Sleep paused. "
                                            f"({(reason or result.stderr or '').strip()[:160]})")
    if any(m in blob for m in _SIGNED_OUT) or _STATUS_401.search(blob):
        raise engine_errors.EngineUnavailable(f"{spec.name} is signed out — run `{spec.sign_in}`, then Sleep again.")
    if any(m in blob for m in _NOT_FOUND):
        raise engine_errors.EngineModelNotFound(f"{spec.name} rejected the model: {reason[:200] or blob.strip()[:200]}")
    transport = f"{reason} {result.stderr or ''}"
    if result.rc == 124:
        if engine_errors.is_connectivity_error(transport):
            raise engine_errors.EngineConnectionLost(f"{spec.name} lost the connection: {transport.strip()[:300]}")
        raise engine_errors.EngineTimeout(f"{spec.name} timed out: {(result.stderr or '').strip()[:200]}")
    if engine_errors.is_connectivity_error(transport):
        raise engine_errors.EngineConnectionLost(f"{spec.name} lost the connection: {transport.strip()[:300]}")
    if parsed.events == 0:
        raise engine_errors.EngineUnavailable(
            f"{spec.name} printed no answer (rc {result.rc}): {(result.stderr or '').strip()[:200] or 'no output'}")
    if parsed.failure is None:
        raise engine_errors.EngineProtocolError(f"{spec.name} finished without a reply")
    raise engine_errors.EngineFailed(f"{spec.name} failed: {reason[:200]}")


# --------------------------------------------------------------------------- #
# The call
# --------------------------------------------------------------------------- #


def resolve_binary(spec: EngineSpec) -> str | None:
    """The first of the spec's binaries that resolves (``base.resolve_binary``: CICADA_<NAME>_CLI, PATH, the usual
    install folders). ``None`` = not installed."""
    from api.services.connections import base

    for name in spec.binaries:
        path = base.resolve_binary(name)
        if not path:
            continue
        if spec is CURSOR and name == "agent" and not _is_cursor_agent(path):
            continue   # some other tool's `agent` on PATH: never called with a prompt
        return name
    return None


_CURSOR_CHECKED: dict[str, bool] = {}


def _is_cursor_agent(path: str) -> bool:
    """Review of #494: a binary named only ``agent`` is used only once its own help names Cursor (cached per path).
    ``--help`` prints and exits; nothing is sent anywhere."""
    if path in _CURSOR_CHECKED:
        return _CURSOR_CHECKED[path]
    try:
        result = agent_engine._default_runner()([path, "--help"], stdin=None, timeout=5.0, cwd=None)
        ok = result.rc == 0 and "cursor" in f"{result.stdout}\n{result.stderr}".lower()
    except Exception:  # noqa: BLE001 — unreadable reads as not Cursor's
        ok = False
    _CURSOR_CHECKED[path] = ok
    return ok


def complete(spec: EngineSpec, *, messages: list[dict], model: str, stage: str | None = None,
             want_json: bool = False, timeout: float = DEFAULT_TIMEOUT_S, runner=None,
             scope: str | None = None) -> ExecResult:
    """One headless call; raises ``EngineError``. Synchronous by design (the seam wraps it in ``to_thread``)."""
    scope = scope or agent_engine.current_scope()
    tripped = agent_engine.breaker_reason(scope=scope)
    if tripped:
        exc = engine_errors.EngineThrottled(tripped)
        exc.spawned = False
        raise exc
    if spec.explicit_model and not model:
        # Never the tool's own config default (it could be key-backed): the first plan model it lists, else refuse.
        model = next(iter(status(spec).models), "")
        if not model:
            exc = engine_errors.EngineUnavailable(
                f"{spec.name} lists no model Sleep may read with on your plan — choose one in Settings → "
                f"Intelligence. Nothing was read.")
            exc.spawned = False
            raise exc
    refused = metered_refusal(spec, model)
    if refused:
        exc = engine_errors.EngineUnavailable(refused)
        exc.spawned = False
        raise exc
    binary = resolve_binary(spec)
    if binary is None:
        exc = engine_errors.EngineUnavailable(f"{spec.name} isn't installed. {spec.install}")
        exc.spawned = False
        raise exc
    cwd = _empty_cwd(spec)
    try:
        argv, env, stdin = build_call(spec, model=model, prompt=full_prompt(messages, want_json=want_json),
                                      cwd=cwd, binary=binary)
        run = runner or agent_engine._default_runner()
        result = run(argv, stdin=stdin, timeout=timeout, cwd=str(cwd), env_overrides=env)
    finally:
        _remove_tree(cwd)
    parsed = PARSERS[spec.mode](result.stdout)
    check(spec, result, parsed)
    # The model this call was made with, when the tool reported none: an explicit `-m` is what ran.
    parsed.model = parsed.model or model or None
    return parsed


def _remove_tree(path: Path) -> None:
    import shutil

    with suppress(OSError):
        shutil.rmtree(path)


def response_shim(parsed: ExecResult, requested_model: str):
    """OpenAI clothes on the answer. The model is the one the tool reported serving, else the one asked for, else
    empty — never a guess."""
    usage = parsed.usage or {}
    cached = int(usage.get("cache_read") or 0)
    return agent_engine._wrap({
        "choices": [{"message": {"role": "assistant", "content": parsed.text or ""}, "finish_reason": "stop"}],
        "model": parsed.model or requested_model or "",
        "usage": {"prompt_tokens": int(usage.get("input") or 0) + cached,
                  "completion_tokens": int(usage.get("output") or 0),
                  "cache_read_input_tokens": cached, "cache_creation_input_tokens": 0,
                  "prompt_tokens_details": {"cached_tokens": cached}},
    })


# --------------------------------------------------------------------------- #
# Status and models (cached; never a call that spends)
# --------------------------------------------------------------------------- #


@dataclass
class Status:
    available: bool
    connected: bool
    detail: str
    models: list[str] = field(default_factory=list)
    as_of: float = 0.0


_CACHE: dict[str, Status] = {}
_CACHE_LOCK = threading.Lock()
CACHE_TTL_S = 30.0
_MODEL_LINE = re.compile(r"^[\s*>•-]*([A-Za-z0-9][A-Za-z0-9._/:-]*)(?:\s|$)")
_NOT_MODEL_WORDS = frozenset({"available", "models", "model", "current", "default", "id", "name", "no", "loading",
                              "error", "usage", "tip", "note", "warning"})


def parse_model_lines(stdout: str | None) -> list[str]:
    """Model ids from a ``models`` listing: the first id-shaped token of each line, headers and prose skipped."""
    found: list[str] = []
    for raw in (stdout or "").splitlines():
        m = _MODEL_LINE.match(raw)
        if not m:
            continue
        token = m.group(1).rstrip(":")
        if token.lower() in _NOT_MODEL_WORDS or not agent_engine.is_valid_model_id(token):
            continue
        if raw.strip().endswith(":") and " " in raw.strip():
            continue   # "Available models:" style headers
        if token not in found:
            found.append(token)
    return found


def _signed_out(text: str) -> bool:
    low = text.lower()
    return any(m in low for m in ("not logged in", "not authenticated", "logged out", "login required",
                                  "authentication required", "please log in", "please login", "run `agent login`",
                                  "run agent login", "run `grok login`", "run grok login", "set xai_api_key",
                                  "no authenticated"))


#: Review of #494: each status command gets a short budget, so a hung tool costs the picker seconds, never half a
#: minute; the picker itself serves the last known state while a refresh runs (`astatus(stale_ok=True)`).
PROBE_TIMEOUT_S = 8.0


def probe_now(spec: EngineSpec, *, runner=None, timeout: float = PROBE_TIMEOUT_S) -> Status:
    """One status read: is the tool installed, signed in (on a plan), and which plan models it offers.
    Cursor: ``agent status`` and ``agent models``, side by side. OpenCode: ``opencode models`` — signed in to a plan
    when it lists a model on a plan provider. Grok: ``grok models`` (it refuses without a sign-in, with
    ``XAI_API_KEY`` stripped), only xAI's built-in ``grok-…`` ids kept."""
    run = runner or agent_engine._default_runner()
    binary = resolve_binary(spec)
    if binary is None:
        return Status(False, False, f"{spec.name} isn't installed. {spec.install}", as_of=time.time())
    if spec is CURSOR:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=2) as pool:
            status_f = pool.submit(run, [binary, "status"], stdin=None, timeout=timeout, cwd=None)
            models_f = pool.submit(run, [binary, "models"], stdin=None, timeout=timeout, cwd=None)
            status_r, listing = status_f.result(), models_f.result()
        text = f"{status_r.stdout}\n{status_r.stderr}"
        if status_r.rc != 0 or _signed_out(text):
            return Status(True, False, f"Cursor is signed out — run `{spec.sign_in}`.", as_of=time.time())
        models = parse_model_lines(listing.stdout) if listing.rc == 0 else []
        return Status(True, True, "Signed in to Cursor.", models, time.time())
    listing = run([binary, "models"], stdin=None, timeout=timeout, cwd=None,
                  env_overrides=opencode_env() if spec is OPENCODE else dict(GROK_ENV))
    text = f"{listing.stdout}\n{listing.stderr}"
    if spec is OPENCODE:
        models = [m for m in parse_model_lines(listing.stdout) if "/" in m] if listing.rc == 0 else []
        plan = [m for m in models if opencode_is_plan_model(m)]
        if not plan:
            return Status(True, False, "OpenCode has no subscription signed in — run `opencode auth login` and "
                                       "choose GitHub Copilot or OpenCode Go.", as_of=time.time())
        return Status(True, True, "Signed in to a subscription in OpenCode.", plan, time.time())
    if listing.rc != 0 or _signed_out(text):
        return Status(True, False, f"Grok is signed out — run `{spec.sign_in}`.", as_of=time.time())
    builtin = [m for m in parse_model_lines(listing.stdout) if grok_is_builtin(m)]
    if not builtin:
        return Status(True, False, "Grok lists none of xAI's own grok-… models — run `grok login` with your Grok "
                                   "subscription.", as_of=time.time())
    return Status(True, True, "Signed in to Grok.", builtin, time.time())


_REFRESHING: set[str] = set()


def status(spec: EngineSpec, *, fresh: bool = False, runner=None, stale_ok: bool = False) -> Status:
    """``probe_now`` behind a 30 s cache (the picker and a cycle's pre-flight read the same answer). ``stale_ok``
    (the picker): an expired answer is served at once while one background refresh runs; only a tool never read
    before is waited on, at ``PROBE_TIMEOUT_S`` per command."""
    with _CACHE_LOCK:
        cached = _CACHE.get(spec.mode)
    if cached is not None and not fresh and time.time() - cached.as_of < CACHE_TTL_S:
        return cached
    if cached is not None and stale_ok and not fresh:
        with _CACHE_LOCK:
            start = spec.mode not in _REFRESHING
            _REFRESHING.add(spec.mode)
        if start:
            threading.Thread(target=_refresh, args=(spec, runner), daemon=True).start()
        return cached
    return _refresh(spec, runner)


def _refresh(spec: EngineSpec, runner=None) -> Status:
    try:
        st = probe_now(spec, runner=runner)
    except Exception as exc:  # noqa: BLE001 — a probe never fails its caller
        logger.warning(f"{spec.label} status probe failed: {type(exc).__name__}")
        st = Status(True, False, f"Couldn't read {spec.name}'s status right now.", as_of=time.time())
    with _CACHE_LOCK:
        _CACHE[spec.mode] = st
        _REFRESHING.discard(spec.mode)
    return st


def invalidate() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


async def astatus(spec: EngineSpec, *, fresh: bool = False, stale_ok: bool = False) -> Status:
    return await asyncio.to_thread(status, spec, fresh=fresh, stale_ok=stale_ok)


def model_choices(spec: EngineSpec, st: Status | None, saved: str | None) -> list[str]:
    """The picker's list: the tool's live list (else the documented defaults), plus the saved model, which never
    disappears from the list."""
    models = list(st.models) if st and st.models else list(spec.default_models)
    models = [m for m in models if plan_model(spec, m)]
    if saved and saved not in models:
        models.append(saved)
    return models


def stale_model_sentence(spec: EngineSpec, st: Status | None, saved: str | None) -> str | None:
    """A saved model the tool no longer offers, in words — it is never silently swapped."""
    if not saved or st is None or not st.connected or not st.models or saved in st.models:
        return None
    return (f"{spec.name} no longer lists {saved}. Sleep won't read with it until you choose a model it offers "
            f"(or {spec.name} lists it again).")


async def preflight(spec: EngineSpec, settings) -> tuple[bool, str, str | None]:
    """Before a cycle's first spawn: installed? signed in? the saved model still offered and a plan model?
    Returns ``(ok, sentence, model to fill in)`` — OpenCode and Grok always get an explicit model, so an unpicked one
    becomes the first plan model the tool lists (said in the sentence); Cursor runs its own default with no flag."""
    st = await astatus(spec, fresh=True)
    if not st.connected:
        return False, st.detail, None
    saved = model_for_stage(settings, None)
    for model in {saved, model_for_stage(settings, "disambiguation")} - {""}:
        refused = metered_refusal(spec, model)
        if refused:
            return False, refused, None
        stale = stale_model_sentence(spec, st, model)
        if stale:
            return False, stale, None
    if spec.explicit_model and not saved:
        first = st.models[0] if st.models else None
        if first is None:
            return False, f"{spec.name} lists no model Sleep may read with on your plan. Nothing was read.", None
        return True, f"{st.detail} Reading with {first}, the first model it lists.", first
    return True, st.detail, None


def env_note() -> str | None:
    """Names (never values) of the key variables set in this process that Cicada strips from these tools' children."""
    from api.services.connections import base

    names = [n for n in base.CLI_ENGINE_OVERRIDE_ENV if (os.environ.get(n) or "").strip()]
    if not names:
        return None
    return f"This machine's environment sets {', '.join(names)}; Cicada removes it for its own calls."
