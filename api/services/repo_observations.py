"""The last thing the app saw in each declared repo — ``$CICADA_HOME/repos/<bank>.json``.

The backend never runs git in a person's folder (``repo_context``'s docstring
says why). The app runs it when a card opens and posts the outputs to ``POST
/entities/{id}/repos/observed``; that route keeps only the summary here, so
``_state.md`` can name a project's branch without a probe of its own.

What is kept, per ``(path, device)``: ``branch``, ``dirty``, ``ahead``,
``behind``, ``status`` and ``observed_at`` — never a remote, a commit, a
worktree or anything git printed beyond those. It is a machine-global cache
beside the logos and Contacts pictures, **never inside a bank**: an
observation is a fact about this Mac right now, not versioned memory, and a
file in the bank would dirty the tree for the next ``git add -A`` writer.

Reading never creates the folder (``contacts_local.photo_path``'s rule); a
write is atomic (a temp file and ``os.replace``) under one process lock.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from loguru import logger

from api.services import local_refs, logo_service, repo_context

#: An observation older than this renders ``state: stale`` in ``_state.md``.
STALE_AFTER = timedelta(days=7)
#: A branch name git would accept is far shorter; anything longer is not one.
MAX_BRANCH = 255
#: Oldest observations go first past this many, so the file never grows unbounded.
MAX_ENTRIES = 500
_VERSION = 1

_lock = threading.Lock()


def _root() -> Path:
    """``$CICADA_HOME/repos`` read from the environment — never created here (``auth.cicada_home`` mkdirs)."""
    return Path(os.environ.get("CICADA_HOME") or str(Path.home() / ".cicada")).expanduser() / "repos"


def path_for(memory_path: Path) -> Path | None:
    """The bank's cache file, or ``None`` for a bank name that would leave the folder."""
    name = logo_service.bank_name(Path(memory_path))
    if not name or name in {".", ".."} or "/" in name or "\x00" in name:
        return None
    return _root() / f"{name}.json"


def _clean_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _clean_branch(value: Any) -> str | None:
    if not isinstance(value, str) or not value or len(value) > MAX_BRANCH:
        return None
    if "\n" in value or "\r" in value or "\x00" in value:
        return None
    return value


def summarize(ctx: dict[str, Any], observed_at: datetime) -> dict[str, Any] | None:
    """The kept subset of one parsed context, validated; ``None`` when there is nothing to keep."""
    status = ctx.get("status")
    if status not in repo_context.STATUSES or status == "other_device":
        return None
    path = ctx.get("path")
    device = ctx.get("device")
    if not isinstance(path, str) or not path or not isinstance(device, str) or not device:
        return None
    return {
        "path": path,
        "device": device,
        "status": status,
        "branch": _clean_branch(ctx.get("current_branch")),
        "dirty": _clean_int(ctx.get("dirty_files")),
        "ahead": _clean_int(ctx.get("ahead")),
        "behind": _clean_int(ctx.get("behind")),
        "observed_at": observed_at.astimezone(timezone.utc).isoformat(),
    }


def read(memory_path: Path) -> list[dict[str, Any]]:
    """Every kept observation for this bank; ``[]`` when there is no file or it is unreadable."""
    target = path_for(memory_path)
    if target is None:
        return []
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rows = data.get("observations") if isinstance(data, dict) else None
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def record(memory_path: Path, contexts: list[dict[str, Any]], *, now: datetime | None = None) -> int:
    """Upsert each context's summary by ``(path, device)``; returns how many were kept. Never raises."""
    now = now or datetime.now(timezone.utc)
    fresh = [s for s in (summarize(c, now) for c in contexts) if s is not None]
    target = path_for(memory_path)
    if not fresh or target is None:
        return 0
    try:
        from api.services.auth import cicada_home

        cicada_home()  # the machine-global root, 0700, created on the write side only
        with _lock:
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            keep = {(r.get("path"), r.get("device")): r for r in read(memory_path)}
            for s in fresh:
                keep[(s["path"], s["device"])] = s
            rows = sorted(keep.values(), key=lambda r: str(r.get("observed_at") or ""))[-MAX_ENTRIES:]
            fd, tmp = tempfile.mkstemp(prefix=".repos-", suffix=".json", dir=str(target.parent))
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump({"version": _VERSION, "observations": rows}, fh, indent=1, sort_keys=True)
                os.replace(tmp, target)
            except BaseException:
                with contextlib.suppress(OSError):
                    os.unlink(tmp)
                raise
    except OSError as exc:
        logger.warning(f"repo observations not kept: {type(exc).__name__}")
        return 0
    return len(fresh)


def _parse_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def resolver(memory_path: Path) -> Callable[..., dict]:
    """``state_dictionary``'s default ``repo_resolver``: the last observation, never git.

    Returns a callable ``(decl, **_) -> dict`` in the shape ``_repo_blocks``
    reads (``status``, ``current_branch``, ``dirty_files``, ``ahead``,
    ``behind``) plus ``observed_at``. A repo on another device is
    ``other_device`` from the declaration alone; one never observed is
    ``unavailable``.
    """
    this_device = local_refs.current_device_id()
    rows = {(r.get("path"), r.get("device")): r for r in read(memory_path)}

    def lookup(decl: dict, **_: Any) -> dict:
        path = str(decl.get("path") or "")
        if repo_context.is_other_device(decl, this_device):
            return {"path": path, "status": "other_device"}
        device = repo_context.declared_device(decl) or this_device
        row = rows.get((path, device))
        if row is None or _parse_time(row.get("observed_at")) is None:
            return {"path": path, "status": "unavailable"}
        return {
            "path": path,
            "status": row.get("status") if row.get("status") in repo_context.STATUSES else "unavailable",
            "current_branch": _clean_branch(row.get("branch")),
            "dirty_files": _clean_int(row.get("dirty")),
            "ahead": _clean_int(row.get("ahead")),
            "behind": _clean_int(row.get("behind")),
            "observed_at": _parse_time(row.get("observed_at")),
        }

    return lookup
