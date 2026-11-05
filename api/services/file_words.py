"""The words of added recordings and videos, found by the words themselves (ROR-117, G43; ``media_files``).

``media_files.search_text`` finds a passage by meaning. A distinctive word said once — a surname, a product, a number
— is not reliably near its query in meaning, and type-as-you-go needs words, not an embedding call. So the same
passages the meaning index embeds are also kept here as an FTS5 table, read by the find palette's prefix pass, the
app's Search and recall, and fused with the meaning leg by ``media_files.find`` (the one reciprocal-rank fusion).

**Where.** A table ``fil`` inside ``search_index.db`` (the bank's derived FTS5 file: git-ignored, never copied or
exported — ``bank_registry`` lists it), not a table in ``vector_index.db``: that file's mtime is the Sleep sync
cursor and its existence says a model has indexed something, and a words-only index must exist without a model. The
table has its own state (``fil_state``: one stamp per added file), so ``search_index``'s own stamp-diff builds never
touch it. **Disposable:** a missing table, a schema or tokenizer change, or a file that vanished is rebuilt from the
store (``$CICADA_HOME/files/<bank>/``) at the next search or write — from nothing, never an error. A bank with no
added file never gets the table.

**Fresh.** A write (``media_files``: words, frames, frame text) re-indexes that file at once and ``delete`` /
``retire_source`` drop it at once, so a file taken out stops being found on the next keystroke; a search also diffs
the store's stamps (at most every ``CHECK_TTL_S``) so another process's write or a hand-removed folder is caught.

**Rails.** These are the recording's words, never the person's: never an episode, never read by Sleep, stored outside
every bank but this derived table. The query is never logged, nor is a passage.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

from loguru import logger

from api.services import search_index, text_fold

TABLE = "fil"
STATE = "fil_state"
COLUMNS = "body, fid UNINDEXED, s UNINDEXED, e UNINDEXED, src UNINDEXED, marks UNINDEXED, name UNINDEXED, kind UNINDEXED"
#: Bumped when how a passage is cut or stored changes: every bank's table rebuilds once, from the store.
SCHEMA_VERSION = "1"
CHECK_TTL_S = 2.0
#: A file owns the rowids ``slot << SLOT_BITS`` + its passage number, so taking it out is a range delete, never a scan.
SLOT_BITS = 14
MAX_ROWS_PER_FILE = (1 << SLOT_BITS) - 1
#: More files than this out of step is a rebuild: done in the background while the search serves what is there.
INLINE_FILES = 40
#: A word is rare enough to carry a plain-words question when this few passages hold it (the larger of the two).
RARE_MIN_PASSAGES = 3
RARE_SHARE = 20     # ... or one in this many passages

_LOCK = threading.RLock()
_CHECKED: dict[str, float] = {}
_WORKERS: dict[str, threading.Thread] = {}


def _tag() -> str:
    return f"{SCHEMA_VERSION}|{search_index.TOKENIZER}|{search_index.PREFIX}"


def reset(memory_path=None) -> None:
    """Forget the per-bank freshness clock (tests; ``search_index.reset`` calls this)."""
    with _LOCK:
        if memory_path is None:
            _CHECKED.clear()
        else:
            _CHECKED.pop(str(Path(memory_path)), None)


def _connect(memory_path: Path) -> sqlite3.Connection | None:
    """A write-capable connection to the bank's existing ``search_index.db``; ``None`` when there is none (this never
    creates the file: ``search_index`` builds it, and the first search after that builds this table from the store)."""
    db = search_index.db_path(memory_path)
    if not db.exists() or not search_index.fts5_available():
        return None
    conn = search_index._open(db)
    try:
        conn.execute("PRAGMA journal_mode=WAL").fetchone()
    except sqlite3.DatabaseError:
        conn.close()
        raise
    return conn


def _has_state(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (STATE,)).fetchone() is not None


def _ensure_schema(conn: sqlite3.Connection) -> bool:
    """Create the table when it is missing or from another layout. True when it was (re)created empty."""
    try:
        row = conn.execute(f"SELECT stamp FROM {STATE} WHERE fid = '_schema'").fetchone()
    except sqlite3.OperationalError:
        row = None
    if row and row[0] == _tag():
        return False
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(f"DROP TABLE IF EXISTS {TABLE}")
        conn.execute(f"DROP TABLE IF EXISTS {STATE}")
        conn.execute(f"CREATE VIRTUAL TABLE {TABLE} USING fts5({COLUMNS}, tokenize='{search_index.TOKENIZER}', "
                     f"prefix='{search_index.PREFIX}')")
        conn.execute(f"CREATE TABLE {STATE} (fid TEXT PRIMARY KEY, stamp TEXT NOT NULL, slot INTEGER NOT NULL DEFAULT 0)")
        conn.execute(f"INSERT INTO {STATE}(fid, stamp, slot) VALUES ('_schema', ?, 0)", (_tag(),))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return True


def _put(conn: sqlite3.Connection, fid: str, stamp: str | None, rows: list[dict]) -> None:
    """Replace one file's rows (inside the caller's transaction)."""
    row = conn.execute(f"SELECT slot FROM {STATE} WHERE fid = ?", (fid,)).fetchone()
    slot = int(row[0]) if row else 0
    if slot:
        conn.execute(f"DELETE FROM {TABLE} WHERE rowid BETWEEN ? AND ?",
                     (slot << SLOT_BITS, (slot << SLOT_BITS) | MAX_ROWS_PER_FILE))
        conn.execute(f"DELETE FROM {STATE} WHERE fid = ?", (fid,))
    if stamp is None:
        return
    if not slot:
        slot = int(conn.execute(f"SELECT COALESCE(MAX(slot), 0) + 1 FROM {STATE}").fetchone()[0])
    base = slot << SLOT_BITS
    conn.executemany(
        f"INSERT INTO {TABLE}(rowid, body, fid, s, e, src, marks, name, kind) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(base + i, r["body"], fid, int(r["s"]), int(r["e"]), r["src"], json.dumps(r["marks"]), r["name"], r["kind"])
         for i, r in enumerate(rows[:MAX_ROWS_PER_FILE])])
    conn.execute(f"INSERT INTO {STATE}(fid, stamp, slot) VALUES (?, ?, ?)", (fid, stamp, slot))


def _txn(conn: sqlite3.Connection, fn) -> None:
    conn.execute("BEGIN IMMEDIATE")
    try:
        fn()
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def reindex(memory_path, file_id: str) -> None:
    """Re-read one file from the store and replace its rows (a write just changed it). A bank whose index file does
    not exist yet is left alone: the first search builds from the store. Never raises (the index is derived)."""
    from api.services import media_files

    memory_path = Path(memory_path)
    try:
        with _LOCK:
            conn = _connect(memory_path)
            if conn is None:
                return
            try:
                _ensure_schema(conn)
                stamp, rows = media_files.lexical_rows(memory_path, file_id)
                _txn(conn, lambda: _put(conn, file_id, stamp, rows))
            finally:
                conn.close()
    except Exception as exc:  # noqa: BLE001 — class only; a passage must not reach a log
        logger.debug(f"file_words: reindex skipped ({type(exc).__name__})")


def drop(memory_path, file_id: str) -> None:
    """A file was taken out: its words leave the lexical index now."""
    memory_path = Path(memory_path)
    try:
        with _LOCK:
            conn = _connect(memory_path)
            if conn is None:
                return
            try:
                if not _has_state(conn):
                    return   # no table, nothing of it to remove
                _ensure_schema(conn)
                _txn(conn, lambda: _put(conn, file_id, None, []))
            finally:
                conn.close()
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"file_words: drop skipped ({type(exc).__name__})")


def ensure(memory_path, *, force: bool = False) -> bool:
    """Bring the table level with the store: new or changed files indexed, removed ones dropped. At most one diff
    every ``CHECK_TTL_S`` unless ``force``. More than ``INLINE_FILES`` out of step (a first build, a layout change)
    is done by a background thread while the search serves what is there; ``force`` always does it inline. True when
    the table exists. Never raises."""
    from api.services import media_files

    memory_path = Path(memory_path)
    key = str(memory_path)
    now = time.monotonic()
    if not force and now - _CHECKED.get(key, float("-inf")) < CHECK_TTL_S:
        return True
    try:
        with _LOCK:
            disk = media_files.store_stamps(memory_path)
            conn = _connect(memory_path)
            if conn is None:
                return False
            try:
                if not disk and not _has_state(conn):
                    _CHECKED[key] = time.monotonic()
                    return False   # no added file and no table: a bank without recordings never gets one
                fresh = _ensure_schema(conn)
                state = {} if fresh else dict(conn.execute(f"SELECT fid, stamp FROM {STATE} WHERE fid != '_schema'"))
                changed = [fid for fid, stamp in disk.items() if state.get(fid) != stamp]
                gone = [fid for fid in state if fid not in disk]
                if not force and len(changed) + len(gone) > INLINE_FILES:
                    _spawn(memory_path)
                    _CHECKED[key] = time.monotonic()
                    return True
                if changed or gone:
                    def apply():
                        for fid in gone:
                            _put(conn, fid, None, [])
                        for fid in changed:
                            stamp, rows = media_files.lexical_rows(memory_path, fid)
                            _put(conn, fid, stamp, rows)
                    _txn(conn, apply)
            finally:
                conn.close()
            _CHECKED[key] = time.monotonic()
            return True
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"file_words: index not level ({type(exc).__name__})")
        return False


def _spawn(memory_path: Path) -> None:
    key = str(memory_path)
    worker = _WORKERS.get(key)
    if worker is not None and worker.is_alive():
        return
    _WORKERS[key] = threading.Thread(target=ensure, args=(memory_path,), kwargs={"force": True},
                                     name="file-words-sync", daemon=True)
    _WORKERS[key].start()


def wait_idle(memory_path, timeout: float = 60.0) -> bool:
    """Wait for a background sync of this bank (tests and the benchmark)."""
    worker = _WORKERS.get(str(Path(memory_path)))
    if worker is not None:
        worker.join(timeout)
        return not worker.is_alive()
    return True


def rebuild(memory_path) -> int:
    """Throw the table away and index the store again (the repair path and the tests). Returns the passages kept."""
    memory_path = Path(memory_path)
    try:
        with _LOCK:
            conn = _connect(memory_path)
            if conn is not None:
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    conn.execute(f"DROP TABLE IF EXISTS {TABLE}")
                    conn.execute(f"DROP TABLE IF EXISTS {STATE}")
                    conn.execute("COMMIT")
                finally:
                    conn.close()
            _CHECKED.pop(str(memory_path), None)
        ensure(memory_path, force=True)
        return count(memory_path)
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"file_words: rebuild failed ({type(exc).__name__})")
        return 0


def count(memory_path) -> int:
    conn = _reader(Path(memory_path))
    if conn is None:
        return 0
    try:
        return int(conn.execute(f"SELECT count(*) FROM {TABLE}").fetchone()[0])
    except sqlite3.DatabaseError:
        return 0
    finally:
        conn.close()


def _reader(memory_path: Path) -> sqlite3.Connection | None:
    db = search_index.db_path(memory_path)
    if not db.exists():
        return None
    try:
        conn = sqlite3.connect(db.resolve().as_uri() + "?mode=rw", uri=True, timeout=2.0, check_same_thread=False)
        conn.execute("PRAGMA query_only=ON")
        return conn
    except sqlite3.DatabaseError:
        return None


def _expression(terms: list[str], joiner: str) -> str:
    return joiner.join(f'"{t}"*' for t in terms)


def _row(r: tuple) -> dict:
    body, fid, s, e, src, marks, name, kind = r
    try:
        marks = json.loads(marks or "[]")
    except ValueError:
        marks = []
    return {"fid": fid, "body": body, "s": int(s), "e": int(e), "src": src or "", "marks": marks,
            "name": name, "kind": kind}


def passage(memory_path, file_id: str, start_ms: int, src: str = "") -> dict | None:
    """The one indexed passage of a file that starts at ``start_ms`` (a meaning hit's passage, to find its segments);
    ``None`` when there is none. Never raises."""
    conn = _reader(Path(memory_path))
    if conn is None:
        return None
    try:
        row = conn.execute(f"SELECT body, fid, s, e, src, marks, name, kind FROM {TABLE} "
                           f"WHERE fid = ? AND s = ? AND src = ? LIMIT 1", (file_id, int(start_ms), src or "")).fetchone()
        return _row(row) if row else None
    except sqlite3.DatabaseError:
        return None
    finally:
        conn.close()


def search(memory_path, query: str, *, limit: int = 8, plain_words: bool = False) -> list[dict]:
    """Passages whose words hold every word of ``query`` (a prefix each), best first (bm25):
    ``[{"fid", "body", "s", "e" (ms), "src" ("" speech or "picture"), "marks", "name", "kind"}]``. ``plain_words``
    (recall, Ask, hybrid search): when no passage holds every word, the question's *rare* words alone — those few
    passages hold — so "what did they say about <name>?" finds the passage that names it. ``[]`` with no table; never
    an error; the query is never logged."""
    tokens = text_fold.query_tokens(query)
    if not tokens or not search_index.fts5_available():
        return []
    memory_path = Path(memory_path)
    if not ensure(memory_path):
        return []
    conn = _reader(memory_path)
    if conn is None:
        return []
    cols = "body, fid, s, e, src, marks, name, kind"
    limit = max(1, int(limit))
    try:
        sql = f"SELECT {cols} FROM {TABLE} WHERE {TABLE} MATCH ? ORDER BY bm25({TABLE}) LIMIT ?"
        rows = [_row(r) for r in conn.execute(sql, (_expression(tokens, " "), limit))]
        if rows or not plain_words:
            return rows
        total = int(conn.execute(f"SELECT count(*) FROM {TABLE}").fetchone()[0])
        cap = max(RARE_MIN_PASSAGES, total // RARE_SHARE)
        rare = []
        for tok in tokens:
            if not text_fold.subject_terms(tok):
                continue   # a function word carries no subject
            held = conn.execute(f"SELECT count(*) FROM {TABLE} WHERE {TABLE} MATCH ?",
                                (_expression([tok], " "),)).fetchone()[0]
            if 0 < held <= cap:
                rare.append(tok)
        if not rare:
            return []
        return [_row(r) for r in conn.execute(sql, (_expression(rare, " OR "), limit))]
    except sqlite3.DatabaseError as exc:
        logger.debug(f"file_words: search failed ({type(exc).__name__})")
        return []
    finally:
        conn.close()
