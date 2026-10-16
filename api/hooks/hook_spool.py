"""The client's capture spool (G181 phase 2): what a hook could not deliver, kept under ``$CICADA_HOME`` until the
server answers again.

``$CICADA_HOME/spool/capture/`` (0700), one JSON file per post (0600, written atomically): the route, the full body,
and — for a session — its key and its transcript's path. A session's posts are cumulative (each Stop re-reads the
whole session), so a session keeps ONE entry, the newest (``s-<hash of the key>.json``): a server away for a day
holds one entry per session, not one per reply, and a resend never carries a snapshot older than one already sent.
A per-turn post (Cursor, Gemini CLI) is not cumulative: each is its own entry, flushed in order, and a new turn waits
behind any already waiting so the episode's turn order holds.

A flush sends oldest first while the hook's budget lasts and stops at the first post that does not land because the
server is away or refuses this device; a post the server answered but did not take (a 5xx, a 409) waits on its own —
a session is skipped, a turn holds the turns behind it. A session's resend first re-reads its transcript's SIZE (never its bytes) so the server can tell a
stale snapshot from a replaced file. Bounded: past :data:`MAX_ENTRIES` or :data:`MAX_BYTES` the oldest entries are
dropped and counted in the log — never their content. Nothing here holds a token; the body is the same scrubbed,
capped payload the hook would have sent.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import secrets
import time
from pathlib import Path
from typing import Callable

MAX_ENTRIES = 2000
MAX_BYTES = 128 * 1024 * 1024
#: Leave this much of the budget unspent: the log line and the process exit come after the last send.
MARGIN_S = 0.3


def spool_dir(home: Path) -> Path:
    path = Path(home) / "spool" / "capture"
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    return path


def _name(key: str | None) -> str:
    if key:
        return "s-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:24] + ".json"
    return f"t-{time.time_ns():020d}-{secrets.token_hex(3)}.json"


def put(home: Path, route: str, body: dict, *, key: str | None = None, transcript_path: str | None = None) -> int:
    """Keep one post for later; returns how many old entries the bounds dropped."""
    folder = spool_dir(home)
    entry = {"v": 1, "route": route, "body": body, "key": key, "transcript_path": transcript_path,
             "queued_at": time.time()}
    data = json.dumps(entry).encode("utf-8")
    target = folder / _name(key)
    tmp = folder / f".{target.name}.{secrets.token_hex(4)}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    os.replace(tmp, target)
    return _trim(folder, keep=target.name)


def drop(home: Path, key: str) -> None:
    """A session's newer post landed: the waiting older one is obsolete."""
    try:
        (spool_dir(home) / _name(key)).unlink()
    except OSError:
        pass


def entries(home: Path) -> list[Path]:
    folder = spool_dir(home)
    found = []
    for p in folder.glob("*.json"):
        try:
            found.append((p.stat().st_mtime_ns, p.name, p))
        except OSError:
            continue
    return [p for _, _, p in sorted(found)]


def pending(home: Path) -> int:
    try:
        return len(entries(home))
    except OSError:
        return 0


def has_turns(home: Path) -> bool:
    return any(p.name.startswith("t-") for p in entries(home))


def _trim(folder: Path, *, keep: str) -> int:
    found = []
    total = 0
    for p in folder.glob("*.json"):
        try:
            st = p.stat()
        except OSError:
            continue
        found.append((st.st_mtime_ns, p.name, p, st.st_size))
        total += st.st_size
    found.sort()
    dropped = 0
    while found and (len(found) > MAX_ENTRIES or total > MAX_BYTES):
        _, name, p, size = found.pop(0)
        if name == keep:
            continue
        try:
            p.unlink()
            dropped += 1
            total -= size
        except OSError:
            pass
    return dropped


def flush(home: Path, send: Callable[[str, dict], int | None], *, deadline: float,
          keep: Callable[[int | None], bool], size_of: Callable[[str | None, int], int]) -> tuple[int, int, int]:
    """Send waiting posts oldest first until one does not land or the budget ends. ``send(route, body)`` returns the
    HTTP status or None. ``(sent, dropped_as_final, left)``. One flusher at a time (a non-blocking ``flock``): a
    second hook firing meanwhile leaves the queue to the first."""
    sent = final = 0
    folder = spool_dir(home)
    try:
        lock_fd = os.open(folder / ".flush.lock", os.O_WRONLY | os.O_CREAT, 0o600)
    except OSError:
        return 0, 0, pending(home)
    try:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return 0, 0, pending(home)
        return _flush_locked(home, send, deadline=deadline, keep=keep, size_of=size_of)
    finally:
        os.close(lock_fd)


#: Answers that say the SERVER is away or refuses this device — every later post would get the same, so a flush stops.
#: Any other answer that is not final (a 5xx, a 409) is about one post: a session's entry is skipped and kept, so one
#: stuck session never holds back every turn queued behind it (backend hunt, 2026-10-16); a turn waits, and so do
#: the turns behind it, so an episode's turn order holds.
_STOP_ALL = (None, 401, 403)


def _flush_locked(home, send, *, deadline, keep, size_of) -> tuple[int, int, int]:
    sent = final = 0
    turns_waiting = False
    for path in entries(home):
        if time.monotonic() + MARGIN_S >= deadline:
            break
        is_turn = not path.name.startswith("s-")
        if is_turn and turns_waiting:
            continue
        try:
            stamp = path.stat().st_mtime_ns
            entry = json.loads(path.read_text(encoding="utf-8"))
            route, body = entry["route"], entry["body"]
        except (OSError, ValueError, KeyError, TypeError):
            try:
                path.unlink()      # an entry nobody can read is never resent
            except OSError:
                pass
            continue
        if entry.get("key") and isinstance(body, dict) and "transcript_bytes" in body:
            body["transcript_size"] = size_of(entry.get("transcript_path"), int(body.get("transcript_bytes") or 0))
        status = send(route, body)
        if status is not None and 200 <= status < 300:
            sent += 1
        elif keep(status):
            if status in _STOP_ALL:
                break
            turns_waiting = turns_waiting or is_turn
            continue
        else:
            final += 1
        try:
            if path.stat().st_mtime_ns == stamp:   # a newer post for the same session replaced it meanwhile: keep that
                path.unlink()
        except OSError:
            pass
    return sent, final, pending(home)
