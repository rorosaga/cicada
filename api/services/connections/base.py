"""Shared pieces for provider connection adapters.

An adapter *probes* a vendor CLI's login state and can start/stop that CLI's
own login flow. It never holds a vendor token. Every subprocess runs with an
environment built here (``scrubbed_env``): the provider keys Cicada manages
are stripped, and so is every variable that would move a ``claude`` or
``codex`` child off the person's plan (R-E1/R-E3), so a child never inherits
a credential it should not see — and ``claude auth status`` / ``codex login
status`` report the plan, not an override.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Protocol

from api.models.schemas import ConnectionKind, ConnectionStatus, LoginSession
from api.services.auth import cicada_home

#: Provider keys Cicada itself manages (hot-loaded from ``secrets.env`` for
#: the BYOK rung). A CLI child must never inherit them: ``claude -p`` "always"
#: uses ``ANTHROPIC_API_KEY`` when present, and Codex lets an env key outrank
#: its ChatGPT sign-in — either turns a plan call into metered billing.
#: Every key Cicada stores for BYOK belongs here (R-AG11 added xAI, Groq and
#: Mistral; ``test_byok_providers`` fails for a provider missing from it).
MANAGED_KEY_ENV = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "GEMINI_API_KEY",
                   "XAI_API_KEY", "GROQ_API_KEY", "MISTRAL_API_KEY")

#: Variables Cicada never sets that would move a ``claude`` child off the
#: person's plan: each outranks the ``/login`` subscription in Claude Code's
#: auth precedence or reroutes its traffic (code.claude.com/docs/en/
#: authentication and /env-vars, fetched 2026-09-23), and ``claude auth
#: status`` cannot see any of them (it still reports ``claude.ai``). R-E1.
CLAUDE_PLAN_OVERRIDE_ENV = (
    "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
    "ANTHROPIC_FOUNDRY_API_KEY", "ANTHROPIC_FOUNDRY_AUTH_TOKEN", "ANTHROPIC_AWS_API_KEY",
    "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
    "CLAUDE_CODE_USE_MANTLE", "CLAUDE_CODE_USE_ANTHROPIC_AWS",
)

#: The Codex twins. An env key "takes precedence over any other auth method"
#: on the exec path (codex-rs login/auth/manager.rs, R2 §1.4), and a base-URL
#: override sends the call somewhere other than the ChatGPT plan. R-E3.
CODEX_PLAN_OVERRIDE_ENV = ("CODEX_API_KEY", "CODEX_ACCESS_TOKEN", "OPENAI_BASE_URL")

#: Stripped from every child, never worth a warning: the retry watchdog
#: retries a plan 429 indefinitely (defeating the capped retries that make a
#: throttle visible, R-E1), and an inherited ``CODEX_HOME`` would point
#: Cicada back at the person's own ~/.codex (spec Decision 2) — Cicada sets
#: its own below.
_ALSO_STRIPPED = ("CLAUDE_CODE_RETRY_WATCHDOG", "CODEX_HOME")

#: R-E5: one list for every child. Cicada only ever spawns ``claude`` and
#: ``codex``, so stripping the union is safe for both.
SCRUBBED_ENV_KEYS = MANAGED_KEY_ENV + CLAUDE_PLAN_OVERRIDE_ENV + CODEX_PLAN_OVERRIDE_ENV + _ALSO_STRIPPED


@dataclass
class CliResult:
    rc: int
    stdout: str
    stderr: str


Runner = Callable[[list[str]], Awaitable[CliResult]]


#: Where a vendor CLI lives when the process env has no useful PATH. The
#: backend runs under launchd, whose PATH is the bare
#: ``/usr/bin:/bin:/usr/sbin:/sbin`` — so ``shutil.which("claude")`` fails for
#: a CLI installed the normal way (npm global, Homebrew, the native installer
#: into ``~/.local/bin``) even though the same user's terminal finds it. Seen
#: for real on 2026-09-02: ``claude auth status`` said logged in, the Claude
#: plan connection said "install Claude Code", and every Sleep silently fell
#: back to a paid key. The order is the order a person would install them.
_CLI_FALLBACK_DIRS: tuple[str, ...] = (
    "~/.local/bin",
    "/opt/homebrew/bin",
    "/usr/local/bin",
    "~/.npm-global/bin",
    "~/.claude/local",
    "~/.codex/bin",
)


def resolve_binary(name: str) -> str | None:
    """Absolute path of a vendor CLI, or ``None`` if it is nowhere we look.

    A ``name`` that already contains a path separator is returned as-is when
    it exists. ``CICADA_<NAME>_CLI`` (e.g. ``CICADA_CLAUDE_CLI``) overrides
    everything, for a non-standard install. Then ``PATH``, then
    :data:`_CLI_FALLBACK_DIRS`. Never raises.
    """
    if not name:
        return None
    override = os.environ.get(f"CICADA_{name.upper().replace('-', '_')}_CLI")
    if override and os.path.isfile(os.path.expanduser(override)):
        return os.path.expanduser(override)
    if os.sep in name:
        return name if os.path.exists(name) else None
    found = shutil.which(name)
    if found:
        return found
    for d in _CLI_FALLBACK_DIRS:
        candidate = os.path.join(os.path.expanduser(d), name)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def _resolve_argv(argv: list[str]) -> list[str] | None:
    """``argv`` with ``argv[0]`` replaced by its resolved path, or ``None``."""
    path = resolve_binary(argv[0])
    if path is None:
        return None
    return [path, *argv[1:]]


def codex_home() -> Path:
    """Cicada's own Codex home (``$CICADA_HOME/codex``, 0700) — spec Decision 2.

    Signing in here instead of the person's ~/.codex keeps their skills and
    ``AGENTS.md`` (7.7k–11.6k tokens of hidden context per call, measured in
    R2 §2.3) out of every Sleep call and gives Cicada its own refresh chain,
    so two processes never race one refresh token. ``CICADA_HOME`` is its only
    override (R-E7) — no knob points it back at ~/.codex.
    """
    path = cicada_home() / "codex"
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def plan_overrides_present(kind: str) -> list[str]:
    """Names (never values) of the plan-override variables set in THIS
    process's environment. ``kind`` is ``"claude"`` or ``"codex"``."""
    names = CLAUDE_PLAN_OVERRIDE_ENV if kind == "claude" else CODEX_PLAN_OVERRIDE_ENV
    return [name for name in names if (os.environ.get(name) or "").strip()]


def override_note(kind: str) -> str | None:
    """R-E6: why the plan WOULD be bypassed outside Cicada, and that Cicada
    removes it for its own calls — one sentence the connection card and the
    Sleep pre-flight append, or ``None``. Names only: a base URL can carry a
    secret path, a token is a token."""
    names = plan_overrides_present(kind)
    if not names:
        return None
    tool, plan = ("Claude Code", "Claude plan") if kind == "claude" else ("Codex", "ChatGPT plan")
    them = "it" if len(names) == 1 else "them"
    return (
        f"This Mac's environment sets {', '.join(names)}, which would take {tool} off "
        f"your {plan} — Cicada removes {them} for its own calls, so Sleep stays on your plan."
    )


def scrubbed_env(name: str | None = None) -> dict[str, str]:
    """The environment every CLI Cicada spawns runs under (R-E5).

    ``SCRUBBED_ENV_KEYS`` stripped, and ``CICADA_CAPTURE=off`` set: the G105
    Stop hook exits on that variable — otherwise Sleep's own prompts would be
    captured back into the bank as episodes (R8). ``name`` is the binary's
    logical name (``argv[0]`` before resolution); a ``codex`` child also gets
    ``CODEX_HOME`` = Cicada's own home, so no call site can forget it.
    """
    env = {k: v for k, v in os.environ.items() if k not in SCRUBBED_ENV_KEYS}
    env["CICADA_CAPTURE"] = "off"
    if name and os.path.basename(name) == "codex":
        env["CODEX_HOME"] = str(codex_home())
    return env


async def run_cli(
    argv: list[str],
    *,
    timeout: float = 15.0,
    stdin: str | None = None,
    cwd: str | None = None,
    env_overrides: dict[str, str] | None = None,
) -> CliResult:
    """Run ``argv`` with a scrubbed env. Never raises: missing binary -> rc 127,
    timeout -> rc 124, so adapters can degrade to ``available=False``.

    ``stdin`` (G74(a)): text piped to the child. ``None`` (the default, and
    what every connection adapter passes) keeps the historical
    ``stdin=DEVNULL``. ``cwd``: the child's working directory — the agent
    engine runs in a scratch dir under ``$CICADA_HOME``, never a bank and
    never the repo. ``env_overrides``: per-call variables layered on the
    scrubbed env — the Claude rung's ``CLAUDE_CODE_MAX_RETRIES`` (R-E1).
    """
    if not argv:
        return CliResult(127, "", "empty argv")
    # Built from the LOGICAL name, before argv[0] becomes a resolved path, so
    # a `codex` child always lands in Cicada's own home (R-E5/R-E7).
    env = scrubbed_env(argv[0])
    if env_overrides:
        env.update(env_overrides)
    resolved = _resolve_argv(argv)
    if resolved is None:
        return CliResult(127, "", f"{argv[0]}: not found")
    argv = resolved
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
            env=env,
            cwd=cwd,
        )
    except OSError as exc:
        return CliResult(127, "", str(exc))
    payload = stdin.encode("utf-8") if stdin is not None else None
    try:
        out, err = await asyncio.wait_for(proc.communicate(payload), timeout=timeout)
    except asyncio.TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(proc.wait(), timeout=5)
        return CliResult(124, "", f"{argv[0]} timed out after {timeout}s")
    return CliResult(proc.returncode or 0, out.decode("utf-8", "replace"), err.decode("utf-8", "replace"))


def run_cli_sync(
    argv: list[str],
    *,
    timeout: float = 15.0,
    stdin: str | None = None,
    cwd: str | None = None,
    env_overrides: dict[str, str] | None = None,
) -> CliResult:
    """Blocking twin of :func:`run_cli`, with the identical rc contract.

    The Sleep engine needs ONE implementation callable from both a sync call
    site (``dedup_sweep``, ``source_rewrite``, ``ask_service``) and an async
    one (``entity_extractor``, ``entity_resolver``). ``asyncio.run`` cannot be
    used from inside a running loop, so the core is synchronous and the async
    seam wraps it in ``asyncio.to_thread`` instead. ``env_overrides`` as in
    :func:`run_cli`.
    """
    if not argv:
        return CliResult(127, "", "empty argv")
    env = scrubbed_env(argv[0])
    if env_overrides:
        env.update(env_overrides)
    resolved = _resolve_argv(argv)
    if resolved is None:
        return CliResult(127, "", f"{argv[0]}: not found")
    argv = resolved
    kwargs: dict = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "env": env,
        "cwd": cwd,
        "timeout": timeout,
    }
    if stdin is None:
        kwargs["stdin"] = subprocess.DEVNULL
    else:
        kwargs["input"] = stdin.encode("utf-8")
    try:
        proc = subprocess.run(argv, **kwargs)  # noqa: S603 - argv is built, never shell
    except subprocess.TimeoutExpired as exc:
        # R-E9: keep what the child printed before the clock ran out — a
        # `system/api_retry` line there is what distinguishes "throttled
        # while retrying" from "slow" (R1 gap B). POSIX `subprocess.run`
        # populates `exc.stdout` with the output read so far.
        partial = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else ""
        return CliResult(124, partial, f"{argv[0]} timed out after {timeout}s")
    except OSError as exc:
        return CliResult(127, "", str(exc))
    return CliResult(
        proc.returncode or 0,
        proc.stdout.decode("utf-8", "replace"),
        proc.stderr.decode("utf-8", "replace"),
    )


class ConnectionAdapter(Protocol):
    id: str
    label: str
    kind: ConnectionKind

    def available(self) -> bool: ...
    async def status(self) -> ConnectionStatus: ...
    async def begin_login(self) -> LoginSession: ...
    async def logout(self) -> None: ...
