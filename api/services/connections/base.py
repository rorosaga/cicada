"""Shared pieces for provider connection adapters.

An adapter *probes* a vendor CLI's login state and can start/stop that CLI's
own login flow. It never holds a vendor token. All subprocesses run with the
provider API keys stripped from the environment so ``claude`` reports its
OAuth state rather than an API-key override, and so a child can never inherit
a key it should not see.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Awaitable, Callable, Protocol

from api.models.schemas import ConnectionKind, ConnectionStatus, LoginSession

SCRUBBED_ENV_KEYS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "GEMINI_API_KEY")


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


def scrubbed_env() -> dict[str, str]:
    """Provider keys stripped, and ``CICADA_CAPTURE=off`` set: every CLI
    Cicada spawns runs under this, and the G105 Stop hook exits on that
    variable — otherwise Sleep's own ``claude -p`` extraction prompts would
    be captured back into the bank as episodes (R8)."""
    env = {k: v for k, v in os.environ.items() if k not in SCRUBBED_ENV_KEYS}
    env["CICADA_CAPTURE"] = "off"
    return env


async def run_cli(
    argv: list[str],
    *,
    timeout: float = 15.0,
    stdin: str | None = None,
    cwd: str | None = None,
) -> CliResult:
    """Run ``argv`` with a scrubbed env. Never raises: missing binary -> rc 127,
    timeout -> rc 124, so adapters can degrade to ``available=False``.

    ``stdin`` (G74(a)): text piped to the child. ``None`` (the default, and
    what every connection adapter passes) keeps the historical
    ``stdin=DEVNULL``. ``cwd``: the child's working directory — the agent
    engine runs in a scratch dir under ``$CICADA_HOME``, never a bank and
    never the repo.
    """
    if not argv:
        return CliResult(127, "", "empty argv")
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
            env=scrubbed_env(),
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
) -> CliResult:
    """Blocking twin of :func:`run_cli`, with the identical rc contract.

    The Sleep engine needs ONE implementation callable from both a sync call
    site (``dedup_sweep``, ``source_rewrite``, ``ask_service``) and an async
    one (``entity_extractor``, ``entity_resolver``). ``asyncio.run`` cannot be
    used from inside a running loop, so the core is synchronous and the async
    seam wraps it in ``asyncio.to_thread`` instead.
    """
    if not argv:
        return CliResult(127, "", "empty argv")
    resolved = _resolve_argv(argv)
    if resolved is None:
        return CliResult(127, "", f"{argv[0]}: not found")
    argv = resolved
    kwargs: dict = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "env": scrubbed_env(),
        "cwd": cwd,
        "timeout": timeout,
    }
    if stdin is None:
        kwargs["stdin"] = subprocess.DEVNULL
    else:
        kwargs["input"] = stdin.encode("utf-8")
    try:
        proc = subprocess.run(argv, **kwargs)  # noqa: S603 - argv is built, never shell
    except subprocess.TimeoutExpired:
        return CliResult(124, "", f"{argv[0]} timed out after {timeout}s")
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
