"""G110 D2: hook-side, stdlib-only git identity observation. Never backend code.

Two fixed plumbing commands, one 100ms deadline, bounded output and no shell.
Hints keep only cwd hash/time; raw git paths travel once in the loopback body.
"""
from __future__ import annotations

import hashlib
import json
import os
import selectors
import secrets
import shutil
import socket
import stat
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

TIMEOUT_S = 0.1
OUTPUT_MAX = 4096
REAP_RESERVE_S = 0.02
COMMANDS = (("common_dir", "--git-common-dir"), ("repo_root", "--show-toplevel"))
MAC_GIT = ("/Library/Developer/CommandLineTools/usr/bin/git",
           "/Applications/Xcode.app/Contents/Developer/usr/bin/git", "/opt/homebrew/bin/git", "/usr/local/bin/git")


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", "surrogateescape")).hexdigest()[:16]


def _executable(environ) -> str | None:
    # /usr/bin/git can pop the developer-tools install dialog on macOS.
    if sys.platform == "darwin":
        bundled = environ.get("CICADA_BACKEND_DIR")
        candidates = MAC_GIT + ((os.path.join(bundled, "git/bin/git"),) if bundled and bundled.startswith("/") else ())
        return next((p for p in candidates if os.access(p, os.X_OK)), None)
    return shutil.which("git", path=environ.get("PATH", os.defpath))


def _environment(environ) -> dict:
    env = {k: environ[k] for k in ("PATH", "HOME", "TMPDIR", "SYSTEMROOT") if k in environ}
    env.update(GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0", GIT_CONFIG_NOSYSTEM="1",
               GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull, LC_ALL="C", LANG="C")
    return env


def _reap_later(proc) -> None:
    try:
        proc.wait(timeout=60)
    except subprocess.TimeoutExpired:
        pass


def _run(argv, cwd, env, deadline) -> bytes | None:
    """Read at most OUTPUT_MAX+1 bytes; kill/reap a failed or late child."""
    proc = None
    try:
        if time.monotonic() >= deadline - REAP_RESERVE_S:
            return None
        proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        chunks, size = [], 0
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stdout, selectors.EVENT_READ)
            while True:
                left = deadline - REAP_RESERVE_S - time.monotonic()
                if left <= 0 or not selector.select(left):
                    return None
                chunk = os.read(proc.stdout.fileno(), OUTPUT_MAX + 1 - size)
                if not chunk:
                    rc = proc.wait(timeout=max(0.001, deadline - time.monotonic()))
                    return b"".join(chunks) if rc == 0 else None
                chunks.append(chunk)
                size += len(chunk)
                if size > OUTPUT_MAX:
                    return None
    except (OSError, subprocess.TimeoutExpired):
        return None
    finally:
        if proc is not None:
            if proc.poll() is None:
                proc.kill()
            # SIGKILL reaping stays in the reserved part of the pair's budget.
            try:
                proc.wait(timeout=max(0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                # Rare kernel-delayed SIGKILL: keep the hook bounded and reap when
                # the child becomes waitable. No workspace work runs on this thread.
                threading.Thread(target=_reap_later, args=(proc,), daemon=True).start()
            proc.stdout.close()


def _path(raw: bytes | None) -> str | None:
    if not isinstance(raw, bytes) or len(raw) > OUTPUT_MAX:
        return None
    try:
        value = raw.decode("utf-8").removesuffix("\n")
    except UnicodeDecodeError:
        return None
    if not value.startswith("/") or any(ord(c) < 32 or ord(c) == 127 for c in value):
        return None
    return value


def observe(cwd: str, *, home: Path, environ, run=None, clock=time.monotonic) -> dict:
    failed = {"cwd_hash": _hash(cwd), "observed_at": datetime.now(timezone.utc).isoformat()}
    executable = _executable(environ)
    if executable is None:
        return failed
    run = run or _run
    deadline = clock() + TIMEOUT_S
    values = {}
    for key, arg in COMMANDS:
        if clock() >= deadline:
            return failed
        raw = run([executable, "-c", "core.fsmonitor=false", "rev-parse", "--path-format=absolute", arg],
                  cwd, _environment(environ), deadline)
        value = _path(raw)
        if value is None or clock() > deadline:
            return failed
        values[key] = value
    scope = _hash(str(home.absolute()) + "\0" + socket.gethostname())
    return {**failed, **values, "scope_hash": scope}


def _hint_path(home: Path, harness: str, session_id: str) -> Path:
    return home / "continuity-hook-hints" / (_hash(harness + ":" + session_id) + ".json")


def _hint_dir(home, environ, *, create=False) -> int | None:
    """No symlinked cache directory; refuse homes inside configured memory roots."""
    directory = home / "continuity-hook-hints"
    real = os.path.realpath(directory)
    for key in ("CICADA_MEMORY_PATH", "CICADA_MEMORY_ROOT"):
        if environ.get(key):
            bank = os.path.realpath(environ[key])
            if real == bank or real.startswith(bank.rstrip(os.sep) + os.sep):
                return None
    try:
        if create:
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        return os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return None


def _hint(home, harness, session_id, environ) -> dict:
    directory = _hint_dir(home, environ)
    if directory is None:
        return {}
    try:
        fd = os.open(_hint_path(home, harness, session_id).name,
                     os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                return {}
            raw = os.read(fd, 1025)
        finally:
            os.close(fd)
        doc = json.loads(raw) if len(raw) <= 1024 else {}
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        return {}
    finally:
        os.close(directory)


def observe_if_needed(cwd, *, home, environ, harness, session_id, startup=False) -> dict | None:
    if not isinstance(cwd, str) or not cwd.startswith("/") or len(cwd) > OUTPUT_MAX:
        return None
    if not startup and _hint(home, harness, session_id, environ).get("cwd_hash") == _hash(cwd):
        return None
    return observe(cwd, home=home, environ=environ)


def remember(home, harness, session_id, observation, *, environ=None) -> None:
    if not isinstance(observation, dict):
        return
    directory = _hint_dir(home, os.environ if environ is None else environ, create=True)
    if directory is None:
        return
    target = _hint_path(home, harness, session_id).name
    tmp = "." + target + "." + secrets.token_hex(4)
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        with os.fdopen(fd, "w") as fh:
            json.dump({k: observation[k] for k in ("cwd_hash", "observed_at")}, fh)
        os.replace(tmp, target, src_dir_fd=directory, dst_dir_fd=directory)
    except (OSError, KeyError):
        pass
    finally:
        try:
            os.unlink(tmp, dir_fd=directory)
        except OSError:
            pass
        os.close(directory)
