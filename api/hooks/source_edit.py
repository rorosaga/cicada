#!/usr/bin/env python3
"""An agent's edit of a watched source file, recorded (G244, ruling 76, owner 2026-11-23).

Claude Code runs this after one of its file tools (``Edit``, ``Write``, ``MultiEdit``, ``NotebookEdit``) succeeds
(``PostToolUse``, matched in the plugin's ``hooks.json``). When the edited file lies inside a folder Cicada watches
(``GET /sources/folders``), the hook hashes the file's bytes and posts ``{folder_id, relpath, sha256, harness,
session_id, transcript_path?, tool, at}`` to ``POST /capture/source-edit``: the agent's own process names the file, the
backend never opens a path (the ``~/Library`` rail), and only the hash leaves — never a word of the file. The backend
matches the hash to the episode the folder sync staged, in either order, and the episode carries the contribution.

A hook, never the agent's memory (G105's rule): the model is never asked to report its own edit. A shell command's edit
is not seen here; the agent declares it with ``cicada source-edit <file>``.

**The fast path** matters: this fires on every edit, most of them nowhere near a watched folder. So the folder list is
cached in ``$CICADA_HOME/state/source-edit-folders.json`` for :data:`TTL_S` seconds, and an edit outside every folder
costs one small file read, one ``realpath`` and the interpreter's start — no HTTP, no log line. A folder added in the
last minute is seen after the cache expires. Nothing is imported from the backend; ``hook_client`` (urllib) is imported
only when a request is actually made.

What is never done: a symlink is not followed (the edited path must not be one, and its resolved path must be a regular
file under a folder's own resolved root; the longest root wins); a file past the app's own 2 MB sync cap is skipped; no
subprocess is spawned and nothing is written to stdout (a PostToolUse hook's stdout is the agent's). The log line is
one per post, an outcome and a count, never a path or a word. ``CICADA_CAPTURE=off`` (Cicada's own spawns) stops it.
Exit 0 always: a hook never blocks an agent's tool.

Stdlib only, run by path. On a client of a server elsewhere (``CICADA_API_BASE``) it posts there with the device token
(``hook_client.target``). A post that does not land is not spooled: the folder sync still stages the revision, just
without the agent named.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HARNESS = "claude-code"
ROUTE = "/capture/source-edit"
FOLDERS_ROUTE = "/sources/folders"
#: Claude Code's file tools. The plugin's matcher says the same; a hook handed another tool does nothing.
TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})
#: The app's own sync cap (``FolderScanner.maxFileBytes``): a larger file is never staged, so never attributed.
MAX_FILE_BYTES = 2_000_000
#: How long the folder list is trusted: a folder added in the last minute waits for the next refresh.
TTL_S = 60.0
#: A refresh that failed (backend down) is retried after this, never on every edit.
FAILED_TTL_S = 15.0
GET_TIMEOUT_S = 1.5
POST_TIMEOUT_S = 2.5
#: A hook's stdin: the tool's whole input (a Write's content included) and result. Past this, nothing is read.
MAX_STDIN_BYTES = 32 * 1024 * 1024
STATE_FILE = "source-edit-folders.json"
LOG_MAX_BYTES = 256 * 1024


# --- environment -----------------------------------------------------------------------------------------------------


def _home(environ) -> Path | None:
    """``$CICADA_HOME``, else ``~/.cicada`` — ``None`` for a bare dict that names no home at all (``memory_notes``'s rule:
    a test's environment never reaches the person's home)."""
    if str(environ.get("CICADA_HOME") or "").strip():
        return Path(environ["CICADA_HOME"]).expanduser()
    home = str(environ.get("HOME") or "").strip()
    if home:
        return Path(home) / ".cicada"
    return Path.home() / ".cicada" if environ is os.environ else None


def _log(environ, message: str) -> None:
    home = _home(environ)
    if home is None:
        return
    path = home / "logs" / "capture.log"
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > LOG_MAX_BYTES * 4:
            os.replace(path, path.with_suffix(".log.1"))
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {HARNESS} source-edit {message}\n".encode())
        finally:
            os.close(fd)
    except OSError:
        pass


# --- the folder list, cached ------------------------------------------------------------------------------------------


def _state_path(home: Path) -> Path:
    return home / "state" / STATE_FILE


def _load_cache(home: Path | None) -> dict:
    if home is None:
        return {}
    try:
        data = json.loads(_state_path(home).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_cache(home: Path | None, data: dict) -> None:
    if home is None:
        return
    path = _state_path(home)
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass


def _fresh(cache: dict, now: float) -> bool:
    try:
        age = now - float(cache.get("at"))
    except (TypeError, ValueError):
        return False
    return -1.0 <= age < (TTL_S if cache.get("ok") else FAILED_TTL_S)


def _slim(folders) -> list[dict]:
    """What a match needs from each folder: its id, root, and include/exclude globs (the wire is camelCase)."""
    out: list[dict] = []
    for f in folders if isinstance(folders, list) else []:
        if not isinstance(f, dict) or not isinstance(f.get("id"), str) or not isinstance(f.get("path"), str):
            continue
        out.append({"id": f["id"], "path": f["path"],
                    "include": [p for p in (f.get("include") or []) if isinstance(p, str)],
                    "exclude": [p for p in (f.get("exclude") or []) if isinstance(p, str)]})
    return out


def _destination(environ):
    """``(base, token, problem)`` — ``memory_notes.destination``'s rule, imported only when a request is made."""
    sys.path.insert(0, str(Path(__file__).parent))
    import memory_notes   # stdlib sibling; pulls hook_client (urllib) in

    return memory_notes.destination(environ)


def _http_get(url: str, token: str, timeout: float) -> tuple[int | None, str]:
    import urllib.error
    import urllib.request

    sys.path.insert(0, str(Path(__file__).parent))
    import hook_client

    req = urllib.request.Request(url, method="GET", headers={"Authorization": f"Bearer {token}"})
    try:
        with hook_client.opener().open(req, timeout=timeout) as resp:  # noqa: S310 - the person's own server
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except (urllib.error.URLError, OSError, ValueError):
        return None, ""


def folders_for(environ, *, get=None, now: float | None = None) -> list[dict]:
    """The watched folders, from the cache while it is fresh, else asked of the backend once. A backend that does not
    answer keeps the last list (stale beats nothing) and is not asked again for :data:`FAILED_TTL_S`."""
    now = time.time() if now is None else now
    home = _home(environ)
    cache = _load_cache(home)
    if _fresh(cache, now):
        return _slim(cache.get("folders"))
    base, token, problem = _destination(environ)
    folders, ok = _slim(cache.get("folders")), False
    if not problem:
        status, text = (get or _http_get)(base + FOLDERS_ROUTE, token, GET_TIMEOUT_S)
        if status is not None and 200 <= status < 300:
            try:
                body = json.loads(text)
                listed = body.get("folders") if isinstance(body, dict) else None
            except ValueError:
                listed = None
            if isinstance(listed, list):
                folders, ok = _slim(listed), True
    _save_cache(home, {"at": now, "ok": ok, "folders": folders})
    return folders


# --- matching the edited file to a folder --------------------------------------------------------------------------


def _glob_re(pattern: str):
    """``folder_source._glob_re``'s grammar: ``**/`` any directories (none included), ``**`` anything, ``*`` anything
    but ``/``, ``?`` one character but ``/``."""
    i, out = 0, []
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out))


def _included(relpath: str, include: list[str], exclude: list[str]) -> bool:
    """A file the folder would never sync is not worth a post. An empty include list says nothing (the backend's own
    default applies there), so it never excludes."""
    if include and not any(_glob_re(p).fullmatch(relpath) for p in include):
        return False
    return not any(_glob_re(p).fullmatch(relpath) for p in exclude)


def _edited_path(payload: dict) -> str | None:
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    for key in ("file_path", "notebook_path"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def locate(raw_path: str, folders: list[dict], *, cwd: str | None = None) -> tuple[dict, str, Path] | None:
    """``(folder, relpath, resolved file)`` for an edited path, or ``None``.

    The path must not be a symlink, its resolved target must be a regular file, and that target must lie under a
    folder's own resolved root; of several roots the longest wins (a folder inside another). ``relpath`` is with ``/``.
    A path that names nothing under a root, or that a folder's globs exclude, is ``None``."""
    try:
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = Path(cwd or os.getcwd()) / path
        path = Path(os.path.abspath(path))
        if path.is_symlink():
            return None
        real = Path(os.path.realpath(path))
        if not stat.S_ISREG(os.lstat(real).st_mode):
            return None
    except (OSError, ValueError):
        return None
    best: tuple[int, dict, str] | None = None
    for folder in folders:
        try:
            root = Path(os.path.realpath(Path(folder["path"]).expanduser()))
            rel = real.relative_to(root)
        except (OSError, ValueError):
            continue
        if not rel.parts:
            continue
        relpath = "/".join(rel.parts)
        if not _included(relpath, folder.get("include") or [], folder.get("exclude") or []):
            continue
        if best is None or len(root.parts) > best[0]:
            best = (len(root.parts), folder, relpath)
    return None if best is None else (best[1], best[2], real)


def hash_file(path: Path) -> str | None:
    """sha256 of the file's bytes (the app's ``FolderScanner.sha256`` of the same bytes), or ``None`` when it cannot be
    read, is not a regular file by the time it is opened, or is over :data:`MAX_FILE_BYTES`."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        data = b""
        with os.fdopen(fd, "rb", closefd=False) as fh:
            data = fh.read(MAX_FILE_BYTES + 1)
    except OSError:
        return None
    finally:
        os.close(fd)
    if len(data) > MAX_FILE_BYTES:
        return None
    return hashlib.sha256(data).hexdigest()


# --- the post --------------------------------------------------------------------------------------------------------


def _send(url: str, body: bytes, token: str, timeout: float) -> tuple[int | None, str]:
    sys.path.insert(0, str(Path(__file__).parent))
    import hook_client

    return hook_client.send(url, body, token, timeout)


def run(payload: dict, *, environ, harness: str = HARNESS, get=None, post=None, now: float | None = None) -> str | None:
    """One PostToolUse event. Returns the log phrase when something was posted or went wrong after a file matched a
    folder; ``None`` for an edit that is nobody's business (outside every folder, another tool, no session)."""
    tool = payload.get("tool_name")
    if tool not in TOOLS:
        return None
    raw_path = _edited_path(payload)
    session_id = payload.get("session_id")
    if raw_path is None or not isinstance(session_id, str) or not session_id.strip():
        return None
    folders = folders_for(environ, get=get, now=now)
    if not folders:
        return None
    cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) else None
    found = locate(raw_path, folders, cwd=cwd)
    if found is None:
        return None
    folder, relpath, real = found
    digest = hash_file(real)
    if digest is None:
        return "skipped: file unreadable or over the size cap"
    base, token, problem = _destination(environ)
    if problem:
        return f"skipped: {problem}"
    body = {"folder_id": folder["id"], "relpath": relpath, "sha256": digest, "harness": harness,
            "session_id": session_id.strip(), "tool": tool,
            "at": datetime.fromtimestamp(time.time() if now is None else now, timezone.utc).isoformat(timespec="seconds")}
    transcript = payload.get("transcript_path")
    if isinstance(transcript, str) and transcript.strip():
        body["transcript_path"] = transcript
    status, text = (post or _send)(base + ROUTE, json.dumps(body).encode("utf-8"), token, POST_TIMEOUT_S)
    if status is None:
        return "not sent: no answer"
    if not 200 <= status < 300:
        return f"not sent: http {status}"
    try:
        answer = json.loads(text)
    except ValueError:
        answer = {}
    if not isinstance(answer, dict):
        answer = {}
    state = answer.get("status")
    state = state if state in ("attached", "held", "refused") else "sent"
    episodes = answer.get("episodes")
    count = len(episodes) if isinstance(episodes, list) else 0
    reason = answer.get("reason")
    suffix = f" ({reason})" if state == "refused" and isinstance(reason, str) and re.fullmatch(r"[a-z_]{1,40}", reason) else ""
    return f"{state}: {count} episode{'' if count == 1 else 's'}{suffix}"


def main(argv=None, *, stdin=None, environ=None, get=None, post=None, now: float | None = None) -> int:
    """The hook: PostToolUse JSON on stdin, nothing on stdout, exit 0 whatever happens."""
    argv = list(sys.argv[1:] if argv is None else argv)
    environ = os.environ if environ is None else environ
    if str(environ.get("CICADA_CAPTURE", "")).strip().lower() == "off":
        return 0
    harness = HARNESS
    if "--harness" in argv and argv.index("--harness") + 1 < len(argv):
        harness = argv[argv.index("--harness") + 1]
    try:
        stream = stdin if stdin is not None else sys.stdin
        raw = stream.read(MAX_STDIN_BYTES)
        payload = json.loads(raw) if raw else {}
        if not isinstance(payload, dict):
            return 0
        outcome = run(payload, environ=environ, harness=harness, get=get, post=post, now=now)
        if outcome:
            _log(environ, outcome)
    except Exception as exc:  # noqa: BLE001 - a hook never fails loudly
        _log(environ, f"error: {type(exc).__name__}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
