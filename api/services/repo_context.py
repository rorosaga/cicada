"""Device-scoped git context for an entity's declared ``repos:`` (backlog G-repo).

An entity's frontmatter can declare that it "has a repo" on disk — a
``project`` entity pointing at ``~/src/alpha-project`` — via a ``repos:`` list
(path + optional device/remote/default_branch/worktrees hints; the wire shape is
``RepoContext`` in ``api/models/schemas.py``). This module answers "what does
that repo look like on THIS machine?" from the outputs of a small, fixed list of
read-only git commands, :data:`REPO_COMMANDS`.

**Who runs git.** Never the backend. Under launchd the backend's interpreter is
what macOS names, so a ``git -C ~/Documents/…`` there made the Mac ask whether
"python3.12" may read the person's folder. The app runs the list itself
(``GitRunner``, pinned to the same list by ``api/tests/fixtures/repo_commands.json``)
and posts the raw outputs; the backend only parses them with
:func:`parse_snapshot` — the ``~/Library`` rail: the app reads the Mac, the
backend parses bytes. The one other caller of git here is the MCP tool
``cicada_repo_context`` (:func:`resolve_repo_context`), which runs in the process
the agent harness launched, so macOS attributes it to that harness — honestly.

Rails:

1. **Never read file contents.** Only git plumbing (``rev-parse``, ``status``,
   ``log``, ``worktree list``, ``symbolic-ref``, ``remote get-url``).
2. **Other-device short-circuit.** A repo that declares a ``device`` other than
   :func:`local_refs.current_device_id` is ``other_device`` and nothing is run
   or read — it would be probing an unrelated checkout that shares a path here.
3. **Every failure is a status, never an exception.** ``missing``,
   ``not_a_repo``, ``denied`` (macOS refused the folder), ``git_unavailable``,
   ``timeout`` — each degrades the rest of the fields to ``None``/``[]``.
4. **The parser never touches the filesystem.** No ``resolve``, no ``exists``:
   the main worktree is ``git rev-parse --path-format=absolute
   --git-common-dir`` minus ``/.git``, compared as a string.
"""

from __future__ import annotations

import os
import re
import subprocess
from typing import Any

from api.services import local_refs

# --- the fixed, read-only command list ---------------------------------------
#
# Stable keys: the app posts `{key: {rc, stdout, stderr?}}` under exactly these
# names. Every command runs as `git <GIT_PREFIX> -C <path> <args>` — never a
# shell, never a caller-supplied fragment — with GIT_OPTIONAL_LOCKS=0 (a status
# never rewrites the index) and LC_ALL=C (the refusal classifier reads English).
# `inside` runs first; when it does not answer "true" nothing else runs.

_LOG_FORMAT = "%H%x1f%an%x1f%aI%x1f%s"  # hash / author / iso-date / subject
_AHEAD_RE = re.compile(r"ahead (\d+)")
_BEHIND_RE = re.compile(r"behind (\d+)")

GIT_PREFIX: tuple[str, ...] = ("-c", "core.fsmonitor=false")

REPO_COMMANDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("inside", ("rev-parse", "--is-inside-work-tree")),
    ("remote", ("remote", "get-url", "origin")),
    ("branch", ("rev-parse", "--abbrev-ref", "HEAD")),
    ("origin_head", ("symbolic-ref", "refs/remotes/origin/HEAD")),
    ("status", ("status", "--porcelain=v1", "--branch")),
    ("worktrees", ("worktree", "list", "--porcelain")),
    ("common_dir", ("rev-parse", "--path-format=absolute", "--git-common-dir")),
    ("last_commit", ("log", "-1", f"--format={_LOG_FORMAT}")),
)
COMMAND_KEYS: frozenset[str] = frozenset(k for k, _ in REPO_COMMANDS)

# Statuses a context can carry. "ok" is the only status with live data.
STATUSES = ("ok", "other_device", "missing", "not_a_repo", "denied", "git_unavailable", "timeout")
# What the runner (or the app) reports when git gave no output to parse at all.
RUN_ERRORS = ("git_unavailable", "timeout", "missing")

_DENIED_MARKERS = ("Operation not permitted", "Permission denied")
_MISSING_MARKER = "No such file or directory"


def _is_int_like(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _out(outputs: dict, key: str) -> str | None:
    """A command's stdout when it succeeded, else ``None`` (absent, failed, malformed)."""
    entry = outputs.get(key) if isinstance(outputs, dict) else None
    if not isinstance(entry, dict) or entry.get("rc") != 0:
        return None
    stdout = entry.get("stdout")
    return stdout if isinstance(stdout, str) else None


def _inside_status(outputs: dict) -> str:
    """``ok`` when the first command said this is a work tree, else why not."""
    entry = outputs.get("inside") if isinstance(outputs, dict) else None
    if not isinstance(entry, dict):
        return "not_a_repo"
    if entry.get("rc") == 0 and str(entry.get("stdout") or "").strip() == "true":
        return "ok"
    stderr = str(entry.get("stderr") or "")
    if any(m in stderr for m in _DENIED_MARKERS):
        return "denied"
    if "cannot change to" in stderr and _MISSING_MARKER in stderr:
        return "missing"
    return "not_a_repo"


# --- the parsers (pure) ------------------------------------------------------


def _current_branch(outputs: dict) -> str | None:
    out = _out(outputs, "branch")
    branch = (out or "").strip()
    if not branch or branch == "HEAD" or "\n" in branch:  # detached HEAD -> no "current branch"
        return None
    return branch


def _origin_remote(outputs: dict) -> str | None:
    url = (_out(outputs, "remote") or "").strip()
    return url or None


def _observed_default_branch(outputs: dict) -> str | None:
    """Origin's HEAD symref, tolerating absence (no remote / never fetched)."""
    ref = (_out(outputs, "origin_head") or "").strip()
    return ref.rsplit("/", 1)[-1] if ref else None


def _status_counts(outputs: dict) -> dict[str, int | None]:
    """ahead/behind (None when there's no upstream to compare against) + dirty count."""
    out = _out(outputs, "status")
    if out is None:
        return {"ahead": None, "behind": None, "dirty_files": None}
    lines = out.splitlines()
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


def _last_commit(outputs: dict) -> dict[str, str] | None:
    out = (_out(outputs, "last_commit") or "").strip("\n")
    if not out:
        return None  # empty repo, no commits yet
    parts = out.split("\x1f")
    if len(parts) != 4:
        return None
    hash_, author, date_, subject = parts
    return {"hash": hash_, "author": author, "date": date_, "subject": subject}


def _main_worktree_path(outputs: dict) -> str | None:
    """The main worktree's path: the absolute common dir minus ``/.git``.

    Linked worktrees have a private git-dir under ``<common>/worktrees/<name>``
    but share the common dir, which is the main worktree's ``.git``. Git prints
    both it and ``worktree list``'s main entry through its own realpath, so a
    string compare is exact — no ``resolve()`` here, ever. Bare repos (a common
    dir not named ``.git``) are out of scope: ``None``, and every worktree then
    reads ``is_main: False``.
    """
    raw = (_out(outputs, "common_dir") or "").strip().rstrip("/")
    if not raw.startswith("/") or not raw.endswith("/.git"):
        return None
    return raw[: -len("/.git")] or "/"


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


def _worktrees(outputs: dict) -> list[dict[str, Any]]:
    out = _out(outputs, "worktrees")
    if out is None:
        return []
    main_path = _main_worktree_path(outputs)
    return [
        {
            "path": entry["path"],
            "branch": entry.get("branch"),
            "is_main": main_path is not None and entry["path"].rstrip("/") == main_path,
            "is_dirty": None,
            "declared": False,  # merged with declared info below
        }
        for entry in _parse_worktree_porcelain(out)
    ]


def _norm_path(path: str) -> str:
    """String normalisation only — ``~`` expanded, dots folded. Never ``resolve()``."""
    return os.path.normpath(os.path.expanduser(str(path)))


def _declared_worktrees_as_dicts(declared: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for w in declared or []:
        if not isinstance(w, dict) or not w.get("path"):
            continue
        out.append(
            {
                "path": str(w["path"]),
                "branch": str(w["branch"]) if w.get("branch") else None,
                "is_main": bool(w.get("primary", False)),
                "is_dirty": None,
                "declared": True,
            }
        )
    return out


def _merge_worktrees(observed: list[dict[str, Any]], declared: list[Any]) -> list[dict[str, Any]]:
    declared_paths = {
        _norm_path(w["path"]) for w in (declared or []) if isinstance(w, dict) and w.get("path")
    }
    return [{**w, "declared": _norm_path(w["path"]) in declared_paths} for w in observed]


def declared_device(decl: dict[str, Any]) -> str | None:
    device = decl.get("device") if isinstance(decl, dict) else None
    return (str(device).strip() or None) if device else None


def is_other_device(decl: dict[str, Any], this_device: str | None = None) -> bool:
    return not local_refs.is_this_device(declared_device(decl), this_device)


def parse_snapshot(
    outputs: dict[str, Any],
    decl: dict[str, Any],
    *,
    error: str | None = None,
    this_device: str | None = None,
) -> dict[str, Any]:
    """A full ``RepoContext`` dict from one declaration and the raw command outputs.

    ``outputs`` maps :data:`REPO_COMMANDS` keys to ``{"rc", "stdout", "stderr"?}``;
    a key that is absent or failed degrades only its own field. ``error`` names
    why there is nothing to parse (:data:`RUN_ERRORS`). Pure: no filesystem, no
    subprocess, never raises on malformed input.
    """
    decl = decl if isinstance(decl, dict) else {}
    outputs = outputs if isinstance(outputs, dict) else {}
    path = str(decl.get("path", "") or "")
    device = declared_device(decl)
    declared_remote = decl.get("remote")
    declared_remote = str(declared_remote) if declared_remote else None
    dbd = str(decl.get("default_branch")).strip() if decl.get("default_branch") else None
    declared_worktrees = decl.get("worktrees") if isinstance(decl.get("worktrees"), list) else []
    current = this_device or local_refs.current_device_id()

    def degraded(status: str, *, exists: bool) -> dict[str, Any]:
        return {
            "path": path,
            "device": device if status == "other_device" else (device or current),
            "status": status,
            "exists": exists,
            "is_git_repo": False,
            "remote": declared_remote,
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

    if is_other_device(decl, this_device):
        return degraded("other_device", exists=False)
    if error in RUN_ERRORS:
        return degraded(error, exists=error != "missing")
    status = _inside_status(outputs)
    if status != "ok":
        return degraded(status, exists=status != "missing")

    dbo = _observed_default_branch(outputs)
    stale_hint = None
    if dbd and dbo and dbd != dbo:
        stale_hint = f"declared default branch '{dbd}' differs from observed '{dbo}'"
    return {
        "path": path,
        "device": device or current,
        "status": "ok",
        "exists": True,
        "is_git_repo": True,
        "remote": _origin_remote(outputs) or declared_remote,
        "current_branch": _current_branch(outputs),
        "default_branch_declared": dbd,
        "default_branch_observed": dbo,
        **_status_counts(outputs),
        "worktrees": _merge_worktrees(_worktrees(outputs), declared_worktrees),
        "last_commit": _last_commit(outputs),
        "stale_hint": stale_hint,
    }


# --- the runner: the MCP tool's, never the backend's -------------------------


def run_repo_commands(path: str, *, timeout_s: float = 2.0) -> tuple[dict[str, dict], str | None]:
    """Run :data:`REPO_COMMANDS` against ``path`` and return ``(outputs, error)``.

    Only ``mcp/server.py``'s ``cicada_repo_context`` reaches this (through
    :func:`resolve_repo_context`): it runs in the agent harness's process. The
    backend never calls it — ``test_backend_never_reads_folders`` holds that.
    Never raises; a failure of ``inside`` is the ``error``, a later command's
    only drops its own key.
    """
    target = os.path.expanduser(str(path))
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0", "LC_ALL": "C", "LANG": "C", "CICADA_CAPTURE": "off"}
    outputs: dict[str, dict] = {}
    for key, args in REPO_COMMANDS:
        try:
            proc = subprocess.run(
                ["git", *GIT_PREFIX, "-C", target, *args],
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
                env=env,
            )
        except subprocess.TimeoutExpired:
            if key == "inside":
                return outputs, "timeout"
            continue
        except OSError:  # FileNotFoundError: no git binary on PATH
            if key == "inside":
                return outputs, "git_unavailable"
            continue
        outputs[key] = {"rc": proc.returncode, "stdout": proc.stdout or "", "stderr": proc.stderr or ""}
        if key == "inside" and _inside_status(outputs) != "ok":
            break
    return outputs, None


def resolve_repo_context(repo_decl: dict[str, Any], *, timeout_s: float = 2.0) -> dict[str, Any]:
    """The MCP tool's live probe: the device short-circuit, the runner, the parser.

    ``repo_decl`` is one ``repos:`` entry — ``{"path", "device"?, "remote"?,
    "default_branch"?, "worktrees"?}``. Never raises.
    """
    if is_other_device(repo_decl):
        return parse_snapshot({}, repo_decl)
    outputs, error = run_repo_commands(str(repo_decl.get("path", "") or ""), timeout_s=timeout_s)
    return parse_snapshot(outputs, repo_decl, error=error)
