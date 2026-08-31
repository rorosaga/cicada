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


def scrubbed_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in SCRUBBED_ENV_KEYS}


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
    if shutil.which(argv[0]) is None and not os.path.exists(argv[0]):
        return CliResult(127, "", f"{argv[0]}: not found")
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
    if shutil.which(argv[0]) is None and not os.path.exists(argv[0]):
        return CliResult(127, "", f"{argv[0]}: not found")
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
