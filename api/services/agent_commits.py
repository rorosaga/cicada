"""Commit one agent write on its own (G135 R-R11, R-R13).

Before G135 an MCP claim write changed an entity page and never committed it,
so the next ``git add -A`` writer — usually Sleep's ``_finalize`` — swept it
into its own commit under its own ``Cicada-Author:``: the G85 smear, for every
fact an agent wrote. Now each write commits ONLY the paths it touched
(``git_service.commit_paths``), attributed to the harness that wrote it — a
harness label, because MCP clients do not disclose their model (G49 keeps the
model reserved) — with the conversation as ``Cicada-Session:`` and no
``Cicada-Engine:`` (no engine ran inside Cicada: "omitted rather than guessed").

Three refusals, all silent to the caller. A bank that is not its own git repo
root is never committed (``git -C`` would climb into whatever repo encloses
it — the worktree, in a careless test). A call from inside a running event
loop is refused (the caller is async and owns its own commit). A commit that
fails — a Sleep cycle holding the index lock — leaves the write standing: the
file stays dirty and the next writer's commit picks it up, exactly today's
behaviour. Provenance never blocks memory.
"""
from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path

from loguru import logger


def author_for(harness: str | None) -> str:
    """The ``Cicada-Author:`` for an agent write: the harness label, or
    ``agent`` — the word G114 R6 already uses for ``processed_by`` — when the
    harness never identified itself (G48's ``unknown`` placeholder)."""
    value = (harness or "").strip()
    return value if value and value != "unknown" else "agent"


def commit_write(
    memory_path: Path, *, subject: str, lines: list[str], paths: list[str], author: str,
    session: str | None,
) -> bool:
    memory_path = Path(memory_path)
    if not paths or not (memory_path / ".git").exists():
        return False
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        return False
    from api.services import git_service

    message = git_service.build_commit_message(
        f"{subject} {date.today().isoformat()}", lines, authors=[author],
        sessions=[session] if session else None,
    )
    try:
        asyncio.run(git_service.commit_paths(memory_path, message, paths))
    except Exception as exc:  # noqa: BLE001 — the write already stands
        logger.warning(f"agent commit skipped ({type(exc).__name__}); the write stands uncommitted")
        return False
    return True
