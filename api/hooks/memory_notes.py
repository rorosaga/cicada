#!/usr/bin/env python3
"""Cicada's reader of an agent's own memory notes (owner ruling 43, 2026-10-27).

Claude Code keeps auto-memory notes per project under ``~/.claude/projects/<project>/memory/`` — one ``*.md`` per note
and a ``MEMORY.md`` index. This script, run by the capture hook on the machine where they live, reads every project's
notes and posts their bytes to ``POST /capture/agent-memory``; the backend parses them (``agent_memory_notes``) and
never opens a path for this source. It reads ONLY ``memory/*.md`` regular files — never a transcript (``*.jsonl``),
never a symlink, never anything outside the root — so the transcript rail is untouched.

When it runs: the capture hook calls :func:`maybe_start` after a Claude Code ``Stop`` or ``PreCompact`` (never on
``SessionEnd``, whose time is the person's exit). That is a stat of every note — milliseconds — compared with the
fingerprint of the last post that landed; only when a note changed, appeared or went away, when the last post was for
another server, or :data:`REPOST_AFTER_S` after it (a bank switch, the switch turned back on), it starts this script
as a detached child (``--sweep``) so the harness never waits on it. The first firing after install has no fingerprint,
so it back-fills every note once; every later post is idempotent (the stager skips an unchanged note).

The post is a full snapshot (``complete: true``), so a deleted note is tombstoned server-side. A root that is missing
or unreadable posts nothing; a snapshot past :data:`MAX_POST_BYTES` or :data:`MAX_NOTES`, or with any note skipped rather
than read (a symlink, over the cap, unreadable), is sent incomplete (newest
first) and tombstones nothing. A post that does not land is not spooled: the fingerprint stays, so the next firing
sends the snapshot again.

Stdlib only, run by path (the hook's rule). On a client of a server elsewhere (``CICADA_API_BASE``) it posts there
with this device's token, so each machine files its own notes; otherwise to the loopback backend with
``$CICADA_HOME/api_token``. One line per sweep in ``capture.log``: counts and an outcome, never a name or a word.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import hook_client as remote_client  # stdlib sibling

HARNESS = "claude-code"
ROUTE = "/capture/agent-memory"
NOTES_DIR = "memory"
SUFFIX = ".md"
#: A note past this is skipped (the largest seen is ~50 KB); the backend's own cap is 256k characters.
MAX_NOTE_BYTES = 256 * 1024
MAX_NOTES = 2000
MAX_POST_BYTES = 8 * 1024 * 1024
#: Re-post an unchanged snapshot after this long, so a bank switch or the switch turned back on catches up.
REPOST_AFTER_S = 3600
STATE_FILE = "agent-memory-notes.json"
LOCK_FILE = "agent-memory-notes.lock"
EVENTS = ("Stop", "PreCompact")
SWEEP_TIMEOUT_S = 30.0
DETACHED_ENV = "CICADA_MEMORY_NOTES_SWEEP"


def _user_home(environ) -> Path | None:
    """``$HOME``, or the process's home only for the real environment: a bare dict that names neither never reaches
    the person's home (``hook_client.raw_base``'s rule)."""
    home = str(environ.get("HOME") or "").strip()
    if home:
        return Path(home)
    return Path.home() if environ is os.environ else None


def projects_root(environ) -> Path | None:
    """Claude Code's projects folder: ``$CLAUDE_CONFIG_DIR/projects`` when the harness set one, else
    ``~/.claude/projects``."""
    config = str(environ.get("CLAUDE_CONFIG_DIR") or "").strip()
    if config:
        return Path(config).expanduser() / "projects"
    home = _user_home(environ)
    return home / ".claude" / "projects" if home is not None else None


def scan(root: Path | None) -> list[tuple[str, str, Path | None, int, int]] | None:
    """Every note: ``(project, file, path, mtime_ns, size)``, newest first. ``None`` when the root is not a readable
    folder (nothing is posted then). Only ``<project>/memory/*.md`` regular files, no symlink followed at any level.

    A note that is there but will not be read — a symlink, over :data:`MAX_NOTE_BYTES`, one that cannot be stat'ed,
    or a memory folder that cannot be listed — is kept with ``path`` ``None``: :func:`build` then sends the post
    incomplete, so the server never tombstones it as deleted."""
    if root is None:
        return None
    try:
        if root.is_symlink() or not root.is_dir():
            return None
        projects = list(os.scandir(root))
    except OSError:
        return None
    out: list[tuple[str, str, Path, int, int]] = []
    for project in projects:
        try:
            if not project.is_dir(follow_symlinks=False):
                continue
            notes_dir = Path(project.path) / NOTES_DIR
            if notes_dir.is_symlink():
                out.append((project.name, "", None, 0, 0))   # not followed, not read: the post is incomplete
                continue
            if not notes_dir.is_dir():
                continue
            entries = list(os.scandir(notes_dir))
        except OSError:
            out.append((project.name, "", None, 0, 0))
            continue
        for entry in entries:
            if not entry.name.endswith(SUFFIX) or entry.name.startswith("."):
                continue
            try:
                if entry.is_symlink():
                    out.append((project.name, entry.name, None, 0, 0))
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                st = entry.stat(follow_symlinks=False)
            except OSError:
                out.append((project.name, entry.name, None, 0, 0))
                continue
            if st.st_size > MAX_NOTE_BYTES:
                out.append((project.name, entry.name, None, st.st_mtime_ns, st.st_size))
                continue
            out.append((project.name, entry.name, Path(entry.path), st.st_mtime_ns, st.st_size))
    out.sort(key=lambda n: (-n[3], n[0], n[1]))
    return out


def fingerprint(notes) -> str:
    digest = hashlib.sha256()
    for project, file, _path, mtime_ns, size in sorted(notes, key=lambda n: (n[0], n[1])):
        digest.update(f"{project}/{file}:{mtime_ns}:{size}\n".encode("utf-8", "surrogateescape"))
    return digest.hexdigest()


def _home(environ) -> Path | None:
    """``$CICADA_HOME``, else ``~/.cicada`` — ``None`` for a bare dict that names no home at all."""
    if str(environ.get("CICADA_HOME") or "").strip():
        return Path(environ["CICADA_HOME"]).expanduser()
    home = _user_home(environ)
    return home / ".cicada" if home is not None else None


def _state_path(home: Path) -> Path:
    return home / "state" / STATE_FILE


def load_state(home: Path | None) -> dict:
    if home is None:
        return {}
    try:
        data = json.loads(_state_path(home).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_state(home: Path | None, state: dict) -> None:
    if home is None:
        return
    path = _state_path(home)
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass


def destination(environ) -> tuple[str | None, str, str | None]:
    """``(base, token, problem)`` — the server elsewhere with this device's token, or the loopback backend."""
    if remote_client.is_client(environ):
        return remote_client.target(environ)
    home = _home(environ)
    if home is None:
        return None, "", "no Cicada home"
    try:
        token = (home / "api_token").read_text(encoding="utf-8").strip()
    except OSError:
        token = ""
    base = f"http://127.0.0.1:{str(environ.get('CICADA_PORT') or '8000')}"
    return base, token, (None if token else "no api_token")


def due(state: dict, fp: str, base: str | None, now: float) -> bool:
    if state.get("fingerprint") != fp or state.get("base") != base:
        return True
    try:
        return now - float(state.get("at") or 0) >= REPOST_AFTER_S
    except (TypeError, ValueError):
        return True


def build(notes) -> tuple[list[dict], bool]:
    """The post's notes and whether they are the whole root (newest first until :data:`MAX_POST_BYTES`)."""
    out: list[dict] = []
    total = 0
    complete = len(notes) <= MAX_NOTES
    for project, file, path, mtime_ns, _size in notes[:MAX_NOTES]:
        if path is None:
            complete = False   # there but skipped (scan): never read as deleted
            continue
        try:
            if path.is_symlink():
                complete = False
                continue
            raw = path.read_bytes()
        except OSError:
            complete = False   # a note that could not be read must not read as deleted
            continue
        if len(raw) > MAX_NOTE_BYTES:
            complete = False
            continue
        if total + len(raw) > MAX_POST_BYTES:
            complete = False
            break
        total += len(raw)
        modified = datetime.fromtimestamp(mtime_ns / 1e9, timezone.utc).isoformat(timespec="seconds")
        out.append({"project": project, "file": file, "text": raw.decode("utf-8", "replace"),
                    "modified_at": modified})
    return out, complete


def sweep(environ, *, post=None, log=None, now: float | None = None) -> str:
    """Read every note and post the snapshot; the outcome as a short log phrase (counts, never names)."""
    post = post or remote_client.send
    home = _home(environ)
    now = time.time() if now is None else now
    notes = scan(projects_root(environ))
    if notes is None:
        return "skipped: no projects folder"
    if not any(n[2] is not None for n in notes):
        return "skipped: no notes"
    base, token, problem = destination(environ)
    if problem:
        return f"skipped: {problem}"
    fp = fingerprint(notes)
    payload, complete = build(notes)
    body = json.dumps({"harness": HARNESS, "notes": payload, "complete": complete}).encode("utf-8")
    status, text = post(base + ROUTE, body, token, SWEEP_TIMEOUT_S)
    if status is None or not 200 <= status < 300:
        return f"not sent: {remote_client.why(status) if status is not None else 'no answer'}"
    try:
        answer = json.loads(text)
    except ValueError:
        answer = {}
    save_state(home, {"fingerprint": fp, "base": base, "at": now})
    if answer.get("status") == "off":
        return "off for this memory"
    return ("posted {n} notes: {c} new, {u} updated, {t} tombstoned, {k} linked".format(
        n=len(payload), c=answer.get("created", 0), u=answer.get("updated", 0), t=answer.get("tombstoned", 0),
        k=answer.get("linked", 0)) + ("" if complete else " (partial)"))


def maybe_start(environ, *, harness: str, event: str, spawn=None, now: float | None = None) -> str | None:
    """From the capture hook: start a detached sweep when one is due. Returns what was done, or ``None``."""
    if harness != HARNESS or event not in EVENTS or str(environ.get(DETACHED_ENV) or "") == "1":
        return None
    notes = scan(projects_root(environ))
    if not notes or not any(n[2] is not None for n in notes):   # no folder, or no note it would read: nothing to send (an empty snapshot tombstones nothing anyway)
        return None
    base, _token, problem = destination(environ)
    if problem:
        return None
    if not due(load_state(_home(environ)), fingerprint(notes), base, time.time() if now is None else now):
        return None
    (spawn or _spawn)(environ)
    return "memory notes: sweep started"


def _spawn(environ) -> None:
    try:
        subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--sweep"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         env={**environ, DETACHED_ENV: "1"}, start_new_session=True, close_fds=True)
    except (OSError, ValueError):
        pass


def _log(environ, message: str) -> None:
    home = _home(environ)
    if home is None:
        return
    path = home / "logs" / "capture.log"
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {HARNESS} memory-notes {message}\n".encode())
        finally:
            os.close(fd)
    except OSError:
        pass


def main(argv=None, environ=None) -> int:
    """``--sweep``: one sweep under a lock (two sessions stopping together send one snapshot). Always exits 0."""
    argv = list(sys.argv[1:] if argv is None else argv)
    environ = os.environ if environ is None else environ
    if "--sweep" not in argv:
        return 0
    if str(environ.get("CICADA_CAPTURE", "")).strip().lower() == "off":
        return 0
    import fcntl

    home = _home(environ)
    if home is None:
        return 0
    lock_path = home / "state" / LOCK_FILE
    try:
        lock_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT, 0o600)
    except OSError:
        return 0
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return 0   # another sweep is running; it reads the same notes
        _log(environ, sweep(environ))
    except Exception as exc:  # noqa: BLE001 - a hook's child never fails loudly
        _log(environ, f"error: {type(exc).__name__}")
    finally:
        os.close(fd)
    return 0


if __name__ == "__main__":
    sys.exit(main())
