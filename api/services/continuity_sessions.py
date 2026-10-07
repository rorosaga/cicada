"""The continuity session registry (G110 slice 1a, plan C3).

A session starts before it has an episode, and a prompt that never reached a
Stop leaves no trace in the bank. This small file outside every bank is how
the next session learns either: one row per harness session with

* ``harness`` — the harness enum (set once);
* ``cwd_hash`` — ``sha256(cwd)[:16]``, never the path (first value kept);
* ``started_at`` — when a SessionStart arrived (the EARLIEST kept);
* ``last_prompt_at`` — when an accepted prompt arrived, including one whose
  answer timed out (the LATEST kept);
* ``continues`` — the one episode id Cicada pointed this session at (the
  first write wins; it is never rewritten).

Ids, a hash and times only — never a path, a title or a prompt. Merges are
monotone, so a request that finishes after a newer one can never move a time
backwards (critique finding 35).

**Never inside a bank.** ``continuity_home`` refuses a ``CICADA_HOME`` that
resolves (symlinks followed) inside the memory root or any configured bank;
then every write answers ``unavailable`` and nothing is created. The derived
index's lock (``continuity.py``) uses the same guard.

**Bounded.** ``apply`` is one read-modify-write under a non-blocking
``fcntl.flock`` tried until the caller's deadline (``busy`` past it,
``skipped`` when no time was left at all); the file is capped at
``MAX_BYTES`` and ``MAX_ROWS``; rows expire after ``EXPIRES_AFTER_DAYS``,
applied in memory on every read. Errors are an enum; the exception's class is
logged, never its message (it can carry a path). It never raises.
"""
from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import os
import re
import secrets
import stat
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from loguru import logger

from api.services import episode_ids

EXPIRES_AFTER_DAYS = 30
MAX_ROWS = 1000
MAX_BYTES = 1_048_576
#: How long a call with no deadline waits for the lock (the capture path).
UNBOUNDED_WAIT_S = 1.0
HARNESSES = ("claude-code", "codex")
STATUSES = ("ok", "busy", "skipped", "error", "unavailable")

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{7,127}$")   # transcript_capture's rule
_HASH_RE = re.compile(r"^[0-9a-f]{16}$")
_SLUG_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")
_TIME_KEYS = ("started_at", "last_prompt_at")


# --- paths -------------------------------------------------------------------


def cwd_hash(cwd: str) -> str:
    """The registry's only trace of a folder."""
    return hashlib.sha256(str(cwd).encode("utf-8", "surrogateescape")).hexdigest()[:16]


def bank_paths_for(root: Path) -> tuple[Path, ...]:
    """The memory root and every configured bank's directory — what
    ``continuity_home`` must stay out of. Resolved once per operation."""
    from api.services import bank_registry

    root = Path(root)
    paths = [root]
    try:
        for name in (bank_registry.load_registry(root).get("banks") or {}):
            paths.append(bank_registry.bank_dir(root, str(name)))
    except Exception as exc:  # noqa: BLE001 — an unreadable registry still guards the root
        logger.debug(f"continuity: bank list unreadable ({type(exc).__name__})")
    return tuple(paths)


def _inside(child: str, parent: str) -> bool:
    return child == parent or child.startswith(parent.rstrip(os.sep) + os.sep)


def continuity_home(bank_paths) -> Path | None:
    """``$CICADA_HOME/continuity``, created 0700 — or ``None`` when it would
    sit inside any configured bank (or the memory root), symlink aliases
    included. Nothing is created when it is refused."""
    raw = os.environ.get("CICADA_HOME") or str(Path.home() / ".cicada")
    home = Path(raw).expanduser() / "continuity"
    real_home = os.path.realpath(home)
    for p in bank_paths or ():
        if _inside(real_home, os.path.realpath(p)):
            return None
    try:
        home.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(home, 0o700)
    except OSError as exc:
        logger.debug(f"continuity: home unavailable ({type(exc).__name__})")
        return None
    return home


def bank_file_id(memory_path: Path) -> str:
    """``<slug>-<sha256(realpath)[:8]>``: two banks with one name in two roots
    never share a file, and a crafted name can never reach another path."""
    slug = _SLUG_UNSAFE.sub("-", Path(memory_path).name)[:40].strip(".-") or "bank"
    digest = hashlib.sha256(os.path.realpath(memory_path).encode("utf-8", "surrogateescape")).hexdigest()[:8]
    return f"{slug}-{digest}"


# --- rows --------------------------------------------------------------------


def _canonical_time(value) -> str | None:
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    if moment.tzinfo is None:
        return None
    return episode_ids.to_utc_iso(moment)


def _clean_row(harness: str, raw) -> dict | None:
    """The exact allowlist, validated value by value (read AND write)."""
    if not isinstance(raw, dict) or harness not in HARNESSES:
        return None
    row: dict = {"harness": harness}
    if isinstance(raw.get("cwd_hash"), str) and _HASH_RE.match(raw["cwd_hash"]):
        row["cwd_hash"] = raw["cwd_hash"]
    for key in _TIME_KEYS:
        stamp = _canonical_time(raw.get(key))
        if stamp:
            row[key] = stamp
    if isinstance(raw.get("continues"), str) and episode_ids.EPISODE_ID_RE.match(raw["continues"]):
        row["continues"] = raw["continues"]
    return row


def _activity(row: dict) -> str:
    return max(row.get("started_at") or "", row.get("last_prompt_at") or "")


def _alive(row: dict, now: datetime) -> bool:
    stamp = _activity(row)
    if not stamp:
        return False
    return now - datetime.fromisoformat(stamp) < timedelta(days=EXPIRES_AFTER_DAYS)


def _split_key(key) -> tuple[str, str] | None:
    if not isinstance(key, str) or ":" not in key:
        return None
    harness, sid = key.split(":", 1)
    if harness not in HARNESSES or not _SESSION_ID_RE.match(sid):
        return None
    return harness, sid


def _parse(data: bytes, now: datetime) -> dict[str, dict]:
    if len(data) > MAX_BYTES:
        return {}
    try:
        doc = json.loads(data.decode("utf-8")) if data else {}
    except (ValueError, UnicodeDecodeError):
        return {}
    rows_in = doc.get("rows") if isinstance(doc, dict) else None
    out: dict[str, dict] = {}
    if not isinstance(rows_in, dict):
        return out
    for key, raw in rows_in.items():
        parts = _split_key(key)
        if parts is None:
            continue
        row = _clean_row(parts[0], raw)
        if row is not None and _alive(row, now):
            out[key] = row
    return out


def _merge(row: dict, events: dict) -> dict:
    new = _clean_row(row["harness"], events) or {}
    if "cwd_hash" in new and "cwd_hash" not in row:
        row["cwd_hash"] = new["cwd_hash"]
    if "started_at" in new:
        row["started_at"] = min(filter(None, (row.get("started_at"), new["started_at"])))
    if "last_prompt_at" in new:
        row["last_prompt_at"] = max(filter(None, (row.get("last_prompt_at"), new["last_prompt_at"])))
    if "continues" in new and "continues" not in row:
        row["continues"] = new["continues"]
    return row


def _bounded(rows: dict[str, dict]) -> dict[str, dict]:
    if len(rows) <= MAX_ROWS:
        return rows
    keep = sorted(rows, key=lambda k: _activity(rows[k]))[-MAX_ROWS:]
    return {k: rows[k] for k in keep}


# --- I/O ---------------------------------------------------------------------


def _paths(memory_path: Path, bank_paths) -> tuple[Path, Path] | None:
    home = continuity_home(bank_paths)
    if home is None:
        return None
    fid = bank_file_id(memory_path)
    return home / f"{fid}.json", home / f"{fid}.lock"


def open_regular(path: Path, flags: int, mode: int = 0o600) -> int:
    """Open ``path`` without following a symlink in its final component and
    refuse anything but a regular file (G110 fix round 1, review finding 3): a
    planted ``<id>.lock`` or ``<id>.json`` symlink pointing into a bank is never
    read, written or chmodded through, and a FIFO never blocks the open."""
    fd = os.open(path, flags | os.O_NOFOLLOW | os.O_NONBLOCK, mode)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError(errno.EINVAL, "not a regular file")
    except BaseException:
        os.close(fd)
        raise
    return fd


def read_regular(path: Path, limit: int) -> bytes:
    """Up to ``limit + 1`` bytes of a regular, non-symlinked file; ``b""`` when
    it does not exist. Anything unsafe raises ``OSError``."""
    try:
        fd = open_regular(path, os.O_RDONLY)
    except FileNotFoundError:
        return b""
    try:
        chunks, size = [], 0
        while size <= limit:
            chunk = os.read(fd, min(1 << 20, limit + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def open_lock(path: Path) -> int:
    """A lock file's descriptor: created 0600 if absent, never through a symlink."""
    fd = open_regular(path, os.O_RDWR | os.O_CREAT)
    try:
        os.fchmod(fd, 0o600)
    except BaseException:
        os.close(fd)
        raise
    return fd


def _read(path: Path) -> bytes:
    return read_regular(path, MAX_BYTES)


def _write(path: Path, rows: dict[str, dict]) -> None:
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"schema": 1, "rows": rows}, fh, sort_keys=True)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _lock(lock_path: Path, deadline: float | None) -> int | None:
    fd = open_lock(lock_path)
    until = deadline if deadline is not None else time.monotonic() + UNBOUNDED_WAIT_S
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except BlockingIOError:
            if time.monotonic() >= until:
                os.close(fd)
                return None
            time.sleep(0.005)


def apply(memory_path: Path, *, bank_paths, harness: str, session_id: str, events: dict,
          deadline: float | None, now: datetime | None = None) -> str:
    """One bounded read-modify-write merging ``events`` into the session's row.
    Returns a status from :data:`STATUSES`; never raises. ``deadline`` is a
    ``time.monotonic()`` value; ``None`` waits at most ``UNBOUNDED_WAIT_S``."""
    if deadline is not None and time.monotonic() >= deadline:
        return "skipped"
    if harness not in HARNESSES or not _SESSION_ID_RE.match(str(session_id or "")):
        return "error"
    try:
        paths = _paths(Path(memory_path), bank_paths)
        if paths is None:
            return "unavailable"
        path, lock_path = paths
        fd = _lock(lock_path, deadline)
        if fd is None:
            return "busy"
        try:
            now = now or datetime.now(timezone.utc)
            rows = _parse(_read(path), now)
            key = f"{harness}:{session_id}"
            rows[key] = _merge(rows.get(key) or {"harness": harness}, events or {})
            _write(path, _bounded(rows))
        finally:
            os.close(fd)
        return "ok"
    except Exception as exc:  # noqa: BLE001 — a registry failure never costs a prompt
        logger.debug(f"continuity: registry write failed ({type(exc).__name__})")
        return "error"


def all_rows(memory_path: Path, *, bank_paths, now: datetime | None = None) -> dict[str, dict]:
    """Every live row, validated. No lock: writes are whole-file replaces."""
    try:
        paths = _paths(Path(memory_path), bank_paths)
        if paths is None:
            return {}
        return _parse(_read(paths[0]), now or datetime.now(timezone.utc))
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"continuity: registry read failed ({type(exc).__name__})")
        return {}


def get(memory_path: Path, harness: str, session_id: str, *, bank_paths, now: datetime | None = None) -> dict | None:
    return all_rows(memory_path, bank_paths=bank_paths, now=now).get(f"{harness}:{session_id}")


def rows_for_cwd(memory_path: Path, cwd_hash_value: str, *, bank_paths, now: datetime | None = None) -> list[dict]:
    """Sessions started in this folder, each with ``session_id`` added."""
    out = []
    for key, row in all_rows(memory_path, bank_paths=bank_paths, now=now).items():
        if row.get("cwd_hash") == cwd_hash_value:
            out.append({**row, "session_id": key.split(":", 1)[1]})
    return out
