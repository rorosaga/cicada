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
import contextvars
from contextlib import contextmanager
from datetime import date
from pathlib import Path

from loguru import logger

#: What the bank's uncommitted pages held when the agent's call began (owner, 2026-10-16, from the backend hunt):
#: ``(bank path, git_service.snapshot_dirty)``. Set around one mutating tool call by the door that runs it
#: (:func:`setting_apart`); read by :func:`commit_write`, which then commits someone else's edit on a path it takes
#: apart, first, as the inbox routes do — never under the agent's name.
_BEFORE: contextvars.ContextVar[tuple[str, dict] | None] = contextvars.ContextVar("agent_commits_before", default=None)


def _key(memory_path) -> str:
    try:
        return str(Path(memory_path).resolve())
    except OSError:
        return str(memory_path)


@contextmanager
def setting_apart(memory_path):
    """Around one agent write: snapshot the bank's dirty pages first, so the write's commit keeps an edit that was
    already there apart. A tree that cannot be read snapshots nothing (the commit is then as before)."""
    from api.services import git_service

    try:
        snapshot = git_service.snapshot_dirty_sync(memory_path)
    except Exception:  # noqa: BLE001 — a snapshot never blocks a write
        snapshot = None
    token = _BEFORE.set((_key(memory_path), snapshot) if snapshot is not None else None)
    try:
        yield
    finally:
        _BEFORE.reset(token)


def before_for(memory_path) -> dict | None:
    """The snapshot :func:`setting_apart` took for this bank in this call, else ``None``."""
    held = _BEFORE.get()
    if held is None or held[0] != _key(memory_path):
        return None
    return held[1]


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
    before = before_for(memory_path)
    try:
        if before is not None:
            git_service.commit_touched_sync(memory_path, message, paths, before=before,
                                            kept_subject=f"Uncommitted edit kept apart {date.today().isoformat()}",
                                            kept_trigger="agent/kept-apart")
        else:
            asyncio.run(git_service.commit_paths(memory_path, message, paths))
    except Exception as exc:  # noqa: BLE001 — the write already stands
        logger.warning(f"agent commit skipped ({type(exc).__name__}); the write stands uncommitted")
        return False
    return True
