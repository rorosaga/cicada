"""Device-scoped live git context for an entity's declared ``repos:`` (backlog G-repo).

An entity's frontmatter can declare that it "has a repo" on disk — e.g. the
capstone `project` entity pointing at ``~/Documents/roros_lab/cicada`` — via a
``repos:`` list (path + optional device/remote/default_branch/worktrees hints,
see the module-level ``RepoContext`` schema in ``api/models/schemas.py`` for the
exact wire shape). This module answers "what does that repo actually look like
right now, on THIS machine?" by shelling out to a small, fixed allowlist of
read-only git plumbing commands.

Mirrors ``api/services/local_refs.py``'s safety posture exactly:

1. **Never read file contents.** Only git plumbing (``rev-parse``, ``status``,
   ``log``, ``worktree list``, ``symbolic-ref``, ``remote get-url``) — the same
   "does it still exist / what does it look like" oracle, not a file server.
2. **Other-device short-circuit.** When a repo declares a ``device`` that isn't
   :func:`local_refs.current_device_id`, we do NOT run git against the path —
   it would be probing an unrelated repo that happens to share a path on this
   machine. ``status`` is ``"other_device"`` and nothing is observed.
3. **Every failure mode degrades to a status value — this module never raises
   to the caller.** Missing path, non-repo directory, no git binary, a hung git
   process (timeout) — each maps to its own ``status`` and the rest of the
   fields fall back to ``None``/``[]`` rather than propagating an exception.

Two entry points:

- :func:`git_repo_snapshot` — the low-level, device-unaware probe: given a path
  already known to belong to this machine, run the fixed command allowlist and
  return a plain live-observation dict. Never looks at declared/frontmatter
  values.
- :func:`resolve_repo_context` — the entry point routers/MCP should call. Takes
  one declared ``repos:`` entry (a dict — ``path``, optional ``device`` /
  ``remote`` / ``default_branch`` / ``worktrees``), applies the other-device
  short-circuit, calls :func:`git_repo_snapshot`, and merges declared metadata
  on top (worktree ``declared`` flags, ``default_branch_declared`` vs
  ``_observed``, ``stale_hint``) to produce the full ``RepoContext`` shape.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from api.services import local_refs

# --- fixed, read-only git command allowlist ---------------------------------
#
# Every subprocess call in this module runs exactly one of these forms (never
# shell=True, never a caller-supplied argv fragment):
#
#   git rev-parse --is-inside-work-tree
#   git rev-parse --abbrev-ref HEAD
#   git rev-parse --git-common-dir
#   git remote get-url origin
#   git status --porcelain=v1 --branch
#   git log -1 --format=<fixed format string>
#   git worktree list --porcelain
#   git symbolic-ref refs/remotes/origin/HEAD
#
# All read-only; none of them can mutate the repo or read a tracked file's
# contents.

_LOG_FORMAT = "%H%x1f%an%x1f%aI%x1f%s"  # hash / author / iso-date / subject
_AHEAD_RE = re.compile(r"ahead (\d+)")
_BEHIND_RE = re.compile(r"behind (\d+)")

# Statuses a snapshot/context can carry. "ok" is the only status with live data.
STATUSES = ("ok", "other_device", "missing", "not_a_repo", "git_unavailable", "timeout")


def _run(args: list[str], cwd: Path, timeout_s: float) -> subprocess.CompletedProcess:
    """Run one read-only git command. Raises TimeoutExpired/FileNotFoundError
    (never anything else via ``check=False``) — callers decide how to degrade."""
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout_s,
        check=False,
    )


def _empty_snapshot(status: str) -> dict[str, Any]:
    return {
        "status": status,
        "exists": status != "missing",
        "is_git_repo": False,
        "remote": None,
        "current_branch": None,
        "default_branch_observed": None,
        "ahead": None,
        "behind": None,
        "dirty_files": None,
        "worktrees": [],
        "last_commit": None,
    }


def git_repo_snapshot(path: str, timeout_s: float = 2.0) -> dict[str, Any]:
    """Live, device-unaware git observation of ``path`` — never raises.

    Assumes the caller has already established that ``path`` belongs to THIS
    machine (the other-device short-circuit lives in
    :func:`resolve_repo_context`, one layer up). Returns a plain dict (no
    Pydantic dependency here, so this stays trivially unit-testable) with keys
    matching the live-observation subset of ``RepoContext``: ``status``,
    ``exists``, ``is_git_repo``, ``remote``, ``current_branch``,
    ``default_branch_observed``, ``ahead``, ``behind``, ``dirty_files``,
    ``worktrees`` (each ``declared: False`` — the caller merges declared info),
    ``last_commit``.
    """
    resolved = Path(path).expanduser()
    if not resolved.exists():
        return _empty_snapshot("missing")

    try:
        proc = _run(["rev-parse", "--is-inside-work-tree"], resolved, timeout_s)
    except subprocess.TimeoutExpired:
        return _empty_snapshot("timeout")
    except FileNotFoundError:
        return _empty_snapshot("git_unavailable")

    if proc.returncode != 0 or proc.stdout.strip() != "true":
        return _empty_snapshot("not_a_repo")

    # Repo confirmed valid from here on — every further probe degrades ONLY
    # its own field on failure; a hiccup on one probe never invalidates the
    # fields other probes already got cleanly.
    return {
        "status": "ok",
        "exists": True,
        "is_git_repo": True,
        "remote": _origin_remote(resolved, timeout_s),
        "current_branch": _current_branch(resolved, timeout_s),
        "default_branch_observed": _observed_default_branch(resolved, timeout_s),
        **_status_counts(resolved, timeout_s),
        "worktrees": _worktrees(resolved, timeout_s),
        "last_commit": _last_commit(resolved, timeout_s),
    }


def _current_branch(resolved: Path, timeout_s: float) -> str | None:
    try:
        proc = _run(["rev-parse", "--abbrev-ref", "HEAD"], resolved, timeout_s)
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    branch = proc.stdout.strip()
    if not branch or branch == "HEAD":  # detached HEAD -> no "current branch"
        return None
    return branch


def _origin_remote(resolved: Path, timeout_s: float) -> str | None:
    try:
        proc = _run(["remote", "get-url", "origin"], resolved, timeout_s)
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    url = proc.stdout.strip()
    return url or None


def _observed_default_branch(resolved: Path, timeout_s: float) -> str | None:
    """Origin's HEAD symref, tolerating absence (no remote / never fetched)."""
    try:
        proc = _run(
            ["symbolic-ref", "refs/remotes/origin/HEAD"], resolved, timeout_s
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    ref = proc.stdout.strip()
    return ref.rsplit("/", 1)[-1] if ref else None


def _status_counts(resolved: Path, timeout_s: float) -> dict[str, int | None]:
    """ahead/behind (None when there's no upstream to compare against) + dirty count."""
    try:
        proc = _run(["status", "--porcelain=v1", "--branch"], resolved, timeout_s)
    except Exception:
        return {"ahead": None, "behind": None, "dirty_files": None}
    if proc.returncode != 0:
        return {"ahead": None, "behind": None, "dirty_files": None}

    lines = proc.stdout.splitlines()
    if not lines or not lines[0].startswith("##"):
        return {"ahead": None, "behind": None, "dirty_files": None}

    header = lines[0]
    dirty = len([ln for ln in lines[1:] if ln.strip()])
    if "..." not in header:
        return {"ahead": None, "behind": None, "dirty_files": dirty}

    ahead = behind = 0
    bracket_start = header.find("[")
    if bracket_start != -1:
        bracket_end = header.find("]", bracket_start)
        info = header[bracket_start + 1 : bracket_end] if bracket_end != -1 else ""
        am = _AHEAD_RE.search(info)
        bm = _BEHIND_RE.search(info)
        ahead = int(am.group(1)) if am else 0
        behind = int(bm.group(1)) if bm else 0
    return {"ahead": ahead, "behind": behind, "dirty_files": dirty}


def _last_commit(resolved: Path, timeout_s: float) -> dict[str, str] | None:
    try:
        proc = _run(["log", "-1", f"--format={_LOG_FORMAT}"], resolved, timeout_s)
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    out = proc.stdout.strip("\n")
    if not out:
        return None  # empty repo, no commits yet
    parts = out.split("\x1f")
    if len(parts) != 4:
        return None
    hash_, author, date_, subject = parts
    return {"hash": hash_, "author": author, "date": date_, "subject": subject}


def _main_worktree_path(resolved: Path, timeout_s: float) -> Path | None:
    """The main worktree's own path, derived from ``--git-common-dir``.

    The common dir is always the main worktree's real ``.git`` directory
    (linked worktrees have their OWN private git-dir under
    ``<common>/worktrees/<name>`` but share the same common-dir) — so its
    parent is the main worktree's path. Bare repos (common-dir not named
    ``.git``) are out of scope; returns ``None`` and every worktree entry then
    degrades ``is_main`` to ``False``.
    """
    try:
        proc = _run(["rev-parse", "--git-common-dir"], resolved, timeout_s)
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    raw = proc.stdout.strip()
    if not raw:
        return None
    common_path = Path(raw)
    if not common_path.is_absolute():
        common_path = resolved / common_path
    try:
        common_path = common_path.resolve()
    except OSError:
        return None
    if common_path.name != ".git":
        return None
    return common_path.parent


def _parse_worktree_porcelain(output: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    current: dict[str, Any] = {}
    for line in output.splitlines():
        if not line:
            if current:
                entries.append(current)
                current = {}
            continue
        if line.startswith("worktree "):
            if current:
                entries.append(current)
            current = {"path": line[len("worktree ") :]}
        elif line.startswith("branch "):
            ref = line[len("branch ") :]
            current["branch"] = ref.rsplit("/", 1)[-1] if ref else None
        elif line == "detached":
            current["branch"] = None
    if current:
        entries.append(current)
    return entries


def _worktrees(resolved: Path, timeout_s: float) -> list[dict[str, Any]]:
    try:
        proc = _run(["worktree", "list", "--porcelain"], resolved, timeout_s)
    except Exception:
        return []
    if proc.returncode != 0:
        return []

    entries = _parse_worktree_porcelain(proc.stdout)
    main_path = _main_worktree_path(resolved, timeout_s)

    out: list[dict[str, Any]] = []
    for entry in entries:
        entry_path = Path(entry["path"])
        is_main = False
        if main_path is not None:
            try:
                is_main = entry_path.resolve() == main_path
            except OSError:
                is_main = str(entry_path) == str(main_path)
        out.append(
            {
                "path": entry["path"],
                "branch": entry.get("branch"),
                "is_main": is_main,
                "is_dirty": None,
                "declared": False,  # merged with declared info by the caller
            }
        )
    return out


# --- declared-repo entry point (device short-circuit + merge) ---------------


def _norm_path(path: str) -> str:
    try:
        return str(Path(path).expanduser().resolve())
    except OSError:
        return str(Path(path).expanduser())


def _declared_worktrees_as_dicts(declared: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for w in declared or []:
        if not isinstance(w, dict) or not w.get("path"):
            continue
        out.append(
            {
                "path": str(w["path"]),
                "branch": w.get("branch"),
                "is_main": bool(w.get("primary", False)),
                "is_dirty": None,
                "declared": True,
            }
        )
    return out


def _merge_worktrees(
    observed: list[dict[str, Any]], declared: list[Any]
) -> list[dict[str, Any]]:
    declared_paths = {
        _norm_path(w["path"]) for w in (declared or []) if isinstance(w, dict) and w.get("path")
    }
    merged: list[dict[str, Any]] = []
    for w in observed:
        merged.append({**w, "declared": _norm_path(w["path"]) in declared_paths})
    return merged


def resolve_repo_context(repo_decl: dict[str, Any], *, timeout_s: float = 2.0) -> dict[str, Any]:
    """Build a full ``RepoContext`` dict for one declared ``repos:`` entry.

    ``repo_decl`` is one entry from an entity's ``repos:`` frontmatter list —
    ``{"path": ..., "device": ..., "remote": ..., "default_branch": ...,
    "worktrees": [...]}`` — everything but ``path`` optional. Never raises;
    every failure mode maps to a ``status`` value (see :data:`STATUSES`) with
    the rest of the fields degraded to ``None``/``[]``.
    """
    path = str(repo_decl.get("path", "") or "")
    device = repo_decl.get("device")
    device = str(device).strip() or None if device else None
    declared_remote = repo_decl.get("remote")
    declared_default_branch = repo_decl.get("default_branch")
    declared_worktrees = repo_decl.get("worktrees") or []
    dbd = str(declared_default_branch).strip() if declared_default_branch else None

    current = local_refs.current_device_id()

    if device and device != current:
        return {
            "path": path,
            "device": device,
            "status": "other_device",
            "exists": False,
            "is_git_repo": False,
            "remote": str(declared_remote) if declared_remote else None,
            "current_branch": None,
            "default_branch_declared": dbd,
            "default_branch_observed": None,
            "ahead": None,
            "behind": None,
            "dirty_files": None,
            "worktrees": _declared_worktrees_as_dicts(declared_worktrees),
            "last_commit": None,
            "stale_hint": None,
        }

    snap = git_repo_snapshot(path, timeout_s=timeout_s)

    if snap["status"] != "ok":
        return {
            "path": path,
            "device": device or current,
            "status": snap["status"],
            "exists": snap["exists"],
            "is_git_repo": False,
            "remote": str(declared_remote) if declared_remote else None,
            "current_branch": None,
            "default_branch_declared": dbd,
            "default_branch_observed": None,
            "ahead": None,
            "behind": None,
            "dirty_files": None,
            "worktrees": _declared_worktrees_as_dicts(declared_worktrees),
            "last_commit": None,
            "stale_hint": None,
        }

    dbo = snap["default_branch_observed"]
    stale_hint = None
    if dbd and dbo and dbd != dbo:
        stale_hint = f"declared default branch '{dbd}' differs from observed '{dbo}'"

    return {
        "path": path,
        "device": device or current,
        "status": "ok",
        "exists": True,
        "is_git_repo": True,
        "remote": snap["remote"] or (str(declared_remote) if declared_remote else None),
        "current_branch": snap["current_branch"],
        "default_branch_declared": dbd,
        "default_branch_observed": dbo,
        "ahead": snap["ahead"],
        "behind": snap["behind"],
        "dirty_files": snap["dirty_files"],
        "worktrees": _merge_worktrees(snap["worktrees"], declared_worktrees),
        "last_commit": snap["last_commit"],
        "stale_hint": stale_hint,
    }
