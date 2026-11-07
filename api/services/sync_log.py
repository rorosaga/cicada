"""The home's published log: every commit of the bank by its sequence number (G132 phase 1, ruling 51a/e3).

**The sequence number** of a commit is its position on the first-parent chain from the root commit (the root is 1).
It is derived from the history alone — no trailer, nothing written into the bank — so it is the same on every device
that holds the same history, and it only grows: no bank writer rewrites history (no amend, rebase, reset of a ref,
force), and every ref move a writer makes is a fast-forward child (``git_service._commit_kept_apart_sync``).

**The sidecar** ``$CICADA_HOME/sync/<bank key>/log.db`` (sqlite, 0600) maps ``seq → sha, first parent, commit time``.
It is derived and disposable: deleted, it is rebuilt from ``git log --first-parent``. It catches up from its own last
row with one read-only ``git log <last>..<head>`` when HEAD moves (``sync_service.git_head``, a file read, says when).

**A rewritten history freezes publishing (ruling 51e3).** When the sidecar's last published commit is no longer the
first parent of what follows it on HEAD's chain — a hand amend, a reset, a rebase in the bank — the log stops
answering (``HistoryRewritten``: 409 ``history_rewritten``), says so in words, and stays frozen until the person
chooses "publish from here" (:func:`publish_from_here`), after which replicas copy the bank again. Nothing heals on
its own.

**What leaves:** seq, sha, first parent and commit time — never a subject, a path or a title; those travel only inside
the pack (``sync_pack``), to the person's own full devices. Every git call here is a read.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from api.services import sync_publish

DB_FILE = "log.db"
MAX_LIMIT = 1000
DEFAULT_LIMIT = 500
_GIT_TIMEOUT_S = 60
_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS commits (seq INTEGER PRIMARY KEY, sha TEXT NOT NULL UNIQUE, parent TEXT, at INTEGER)",
    "CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS bases (device TEXT PRIMARY KEY, base_seq INTEGER, head_seq INTEGER, at REAL)",
)
FROZEN_DETAIL = ("This memory's history was rewritten on this computer (a commit was amended or reset by hand), so "
                 "publishing to your other devices stopped. Nothing was changed. Choose \"publish from here\" to make "
                 "this history the one your devices copy again.")

_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


class HistoryRewritten(Exception):
    def __init__(self, last_seq: int, last_sha: str):
        super().__init__("history_rewritten")
        self.last_seq = last_seq
        self.last_sha = last_sha

    def body(self) -> dict:
        return {"code": "history_rewritten", "lastSeq": self.last_seq, "lastSha": self.last_sha,
                "detail": FROZEN_DETAIL}


class Unavailable(Exception):
    """The history could not be read just now (git failed); nothing was published or frozen."""


def _exists(memory_path, sha: str) -> bool:
    try:
        return subprocess.run(["git", "cat-file", "-e", f"{sha}^{{commit}}"], cwd=str(memory_path),
                              capture_output=True, timeout=_GIT_TIMEOUT_S).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return True   # unknown: never freeze on a failed probe


@dataclass(frozen=True)
class Head:
    seq: int
    sha: str

    def wire(self) -> dict:
        return {"seq": self.seq, "sha": self.sha}


def _lock(memory_path) -> threading.Lock:
    key = os.path.realpath(os.fspath(memory_path))
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.Lock())


def _db_path(memory_path) -> Path:
    path = sync_publish.bank_dir(memory_path) / DB_FILE
    if not path.exists():
        os.close(os.open(path, os.O_WRONLY | os.O_CREAT, 0o600))
    return path


@contextmanager
def _db(memory_path):
    conn = sqlite3.connect(_db_path(memory_path), timeout=5)
    try:
        for stmt in _SCHEMA:
            conn.execute(stmt)
        yield conn
        conn.commit()
    finally:
        conn.close()


def _git(memory_path, *args: str) -> str:
    """One read-only git command (never a write subcommand: ``test_git_write_lock``'s lint)."""
    proc = subprocess.run(["git", *args], cwd=str(memory_path), capture_output=True, timeout=_GIT_TIMEOUT_S)
    if proc.returncode != 0:
        raise RuntimeError(f"git {args[0]} failed")
    return proc.stdout.decode("utf-8", errors="replace")


def _chain(memory_path, head: str, since: str | None) -> list[tuple[str, str | None, int]]:
    """``(sha, first parent, commit time)`` oldest first, on HEAD's first-parent chain after ``since``."""
    spec = f"{since}..{head}" if since else head
    out = _git(memory_path, "log", "--first-parent", "--reverse", "--format=%H %P %ct", spec, "--")
    rows = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        sha, at = parts[0], parts[-1]
        parents = parts[1:-1]
        rows.append((sha, parents[0] if parents else None, int(at) if at.isdigit() else 0))
    return rows


#: How far back the loose-object walk goes before it hands over to ``git log``.
_LOOSE_WALK_MAX = 64


def _loose_commit(memory_path: Path, sha: str) -> tuple[str | None, int] | None:
    """``(first parent, commit time)`` of a commit git still holds as a loose object, read with zlib — no subprocess.
    A commit a writer just made is loose until git packs it; anything else (packed, a ``.git`` file) is ``None`` and
    the caller asks ``git log``."""
    import zlib

    if len(sha) != 40:
        return None
    try:
        raw = zlib.decompress((memory_path / ".git" / "objects" / sha[:2] / sha[2:]).read_bytes())
    except (OSError, zlib.error):
        return None
    header, _, body = raw.partition(b"\0")
    if not header.startswith(b"commit "):
        return None
    parent, at = None, 0
    for line in body.split(b"\n"):
        if not line:
            break   # the end of the headers
        if line.startswith(b"parent ") and parent is None:
            parent = line[7:47].decode("ascii", "replace")
        elif line.startswith(b"committer "):
            parts = line.rsplit(b" ", 2)
            at = int(parts[-2]) if len(parts) >= 3 and parts[-2].isdigit() else 0
    return parent, at


def _loose_chain(memory_path: Path, head: str, since: str) -> list[tuple[str, str | None, int]] | None:
    """The commits after ``since`` up to ``head`` by first parent, from loose objects alone, oldest first; ``None``
    when the walk cannot finish that way (then ``git log`` answers, and judges a rewrite)."""
    rows = []
    sha = head
    for _ in range(_LOOSE_WALK_MAX):
        got = _loose_commit(memory_path, sha)
        if got is None:
            return None
        parent, at = got
        rows.append((sha, parent, at))
        if parent == since:
            return rows[::-1]
        if parent is None:
            return None
        sha = parent
    return None


def _frozen(db) -> dict | None:
    row = db.execute("SELECT v FROM meta WHERE k='frozen'").fetchone()
    return json.loads(row[0]) if row else None


def update(memory_path) -> Head:
    """Catch the sidecar up to the bank's HEAD and return the published head. Raises :class:`HistoryRewritten` while
    publishing is frozen. ``Head(0, "")`` for a bank with no commit yet."""
    from api.services import sync_service

    mp = Path(memory_path)
    with _lock(mp), _db(mp) as db:
        frozen = _frozen(db)
        if frozen is not None:
            raise HistoryRewritten(int(frozen["lastSeq"]), str(frozen["lastSha"]))
        last = db.execute("SELECT seq, sha FROM commits ORDER BY seq DESC LIMIT 1").fetchone()
        head = sync_service.git_head(mp)
        if not head:
            return Head(int(last[0]), str(last[1])) if last else Head(0, "")
        if last is not None and last[1] == head:
            return Head(int(last[0]), head)
        try:
            rows = (_loose_chain(mp, head, str(last[1])) if last is not None else None) \
                or _chain(mp, head, last[1] if last else None)
        except (RuntimeError, subprocess.SubprocessError, OSError):
            # A failed read is a rewrite only when the last published commit is gone (a rewrite then a prune);
            # anything else is a moment's failure and says so, never a freeze.
            if last is None or _exists(mp, str(last[1])):
                raise Unavailable() from None
            rows = []
        if last is not None and (not rows or rows[0][1] != last[1]):
            # The last commit we published is not the first parent of what follows it: a hand rewrite (or a reset to
            # an older commit, which leaves nothing after it). Freeze; never heal on its own.
            db.execute("INSERT OR REPLACE INTO meta VALUES ('frozen', ?)", (json.dumps(
                {"lastSeq": int(last[0]), "lastSha": str(last[1]), "at": time.time()}),))
            raise HistoryRewritten(int(last[0]), str(last[1]))
        seq = int(last[0]) if last else 0
        for sha, parent, at in rows:
            seq += 1
            db.execute("INSERT INTO commits VALUES (?, ?, ?, ?)", (seq, sha, parent, at))
        return Head(seq, rows[-1][0]) if rows else Head(seq, last[1] if last else "")


def _iso(at: int | None) -> str | None:
    if not at:
        return None
    return datetime.fromtimestamp(int(at), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def since(memory_path, seq: int, limit: int = DEFAULT_LIMIT) -> tuple[Head, list[dict], bool]:
    """``(head, entries after seq, more)``, ``limit`` at most :data:`MAX_LIMIT`."""
    head = update(memory_path)
    limit = max(1, min(int(limit), MAX_LIMIT))
    with _lock(memory_path), _db(memory_path) as db:
        rows = db.execute("SELECT seq, sha, parent, at FROM commits WHERE seq > ? ORDER BY seq LIMIT ?",
                          (max(0, int(seq)), limit + 1)).fetchall()
    more = len(rows) > limit
    entries = [{"seq": int(r[0]), "sha": r[1], "parent": r[2], "at": _iso(r[3])} for r in rows[:limit]]
    return head, entries, more


def seq_of(memory_path, sha: str) -> int | None:
    """The published seq of ``sha`` (full or unique prefix of at least 7), else ``None``."""
    value = (sha or "").strip().lower()
    if len(value) < 7 or len(value) > 64 or any(c not in "0123456789abcdef" for c in value):
        return None
    update(memory_path)
    with _lock(memory_path), _db(memory_path) as db:
        rows = db.execute("SELECT seq FROM commits WHERE sha LIKE ? LIMIT 2", (value + "%",)).fetchall()
    return int(rows[0][0]) if len(rows) == 1 else None


def head_seq(memory_path) -> int | None:
    """The published head's seq for a reply (``/tools/call``), or ``None`` when publishing is off, frozen or fails."""
    if not sync_publish.publishable(memory_path):
        return None
    try:
        return update(memory_path).seq
    except Exception:  # noqa: BLE001 — a reply never fails for its seq
        return None


def note_base(memory_path, device: str, base_seq: int, head: int | None) -> None:
    """Record the seq a device's write was based on beside the head it landed on (51a: recorded, not enforced)."""
    try:
        with _lock(memory_path), _db(memory_path) as db:
            db.execute("INSERT OR REPLACE INTO bases VALUES (?, ?, ?, ?)", (device, int(base_seq), head, time.time()))
    except Exception:  # noqa: BLE001 — a record never fails the write it describes
        pass


def state(memory_path) -> dict:
    """``{"state": "publishing"|"history_rewritten", ...}`` for the status frame, never raising."""
    try:
        head = update(memory_path)
    except HistoryRewritten as exc:
        return {"state": "history_rewritten", **exc.body()}
    except Unavailable:
        return {"state": "unavailable"}
    return {"state": "publishing", **head.wire()}


def publish_from_here(memory_path) -> Head:
    """The person's choice after a rewrite: this history is the one published from now on. The sidecar starts over
    (replicas see a new history and copy the bank again — PR B refuses a non-ancestor)."""
    mp = Path(memory_path)
    with _lock(mp):
        path = sync_publish.bank_dir(mp) / DB_FILE
        for suffix in ("", "-wal", "-shm", "-journal"):
            Path(str(path) + suffix).unlink(missing_ok=True)
    return update(mp)
