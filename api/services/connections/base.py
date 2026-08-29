"""Shared pieces for provider connection adapters.

An adapter *probes* a vendor CLI's login state and can start/stop that CLI's
own login flow. It never holds a vendor token. All subprocesses run with the
provider API keys stripped from the environment so ``claude`` reports its
OAuth state rather than an API-key override, and so a child can never inherit
a key it should not see.
"""
from __future__ import annotations

import asyncio
import os
import shutil
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


async def run_cli(argv: list[str], *, timeout: float = 15.0) -> CliResult:
    """Run ``argv`` with a scrubbed env. Never raises: missing binary -> rc 127,
    timeout -> rc 124, so adapters can degrade to ``available=False``."""
    if shutil.which(argv[0]) is None and not os.path.exists(argv[0]):
        return CliResult(127, "", f"{argv[0]}: not found")
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.DEVNULL,
            env=scrubbed_env(),
        )
    except OSError as exc:
        return CliResult(127, "", str(exc))
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return CliResult(124, "", f"{argv[0]} timed out after {timeout}s")
    return CliResult(proc.returncode or 0, out.decode("utf-8", "replace"), err.decode("utf-8", "replace"))


class ConnectionAdapter(Protocol):
    id: str
    label: str
    kind: ConnectionKind

    def available(self) -> bool: ...
    async def status(self) -> ConnectionStatus: ...
    async def begin_login(self) -> LoginSession: ...
    async def logout(self) -> None: ...
