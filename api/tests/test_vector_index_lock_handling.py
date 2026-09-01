"""G99a / Wave-1 1.4 — a lock must not read as "the agent has no memory".

Two things were wrong: `_connect` set no PRAGMA at all, so a nightly rebuild
(`_rebuild_table`: DROP + recreate + bulk insert inside one transaction) locks
the whole db file under `journal_mode=delete` against every concurrent API/MCP
reader; and each `except sqlite3.OperationalError: return []` handler degraded
completely silently — indistinguishable from an empty index at the call site.
"""

from __future__ import annotations

import sqlite3

import numpy as np
import pytest
from loguru import logger

from api.services import markdown_parser
from api.services.vector_index import SqliteVecIndexer


def fake_embed(texts: list[str], *, is_query: bool = False) -> np.ndarray:
    return np.ones((len(texts), 4), dtype=np.float32)


@pytest.fixture
def loguru_sink():
    """Capture loguru records emitted during the test (no caplog bridge is
    configured for loguru anywhere in this suite — a temporary sink is the
    standard loguru-native way to assert on a log line)."""
    records: list[str] = []
    sink_id = logger.add(lambda msg: records.append(msg.record["message"]), level="WARNING")
    yield records
    logger.remove(sink_id)


def _seeded_indexer(tmp_path) -> SqliteVecIndexer:
    entities_dir = tmp_path / "entities"
    entities_dir.mkdir()
    markdown_parser.write(
        entities_dir / "x.md",
        {"name": "X", "type": "concept", "status": "active", "confidence": 0.5},
        "Body.",
    )
    indexer = SqliteVecIndexer(tmp_path, embed_fn=fake_embed)
    indexer.index_entities()
    return indexer


def test_connect_sets_wal_and_normal_synchronous(tmp_path):
    indexer = _seeded_indexer(tmp_path)
    conn = indexer._connect()
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        sync = conn.execute("PRAGMA synchronous").fetchone()[0]
    finally:
        conn.close()
    assert mode.lower() == "wal"
    # SQLite reports synchronous as an int: NORMAL == 1 (OFF=0, FULL=2).
    assert sync == 1


class _LockedConn:
    """Wraps a real connection but raises on `.execute` (sqlite3.Connection's
    `execute` is a read-only C attribute — it can't be monkeypatched directly)."""

    def __init__(self, real: sqlite3.Connection):
        self._real = real

    def execute(self, *_a, **_k):
        raise sqlite3.OperationalError("database is locked")

    def close(self):
        self._real.close()


def test_index_info_logs_a_warning_and_degrades_on_lock(tmp_path, monkeypatch, loguru_sink):
    indexer = _seeded_indexer(tmp_path)
    real_connect = indexer._connect
    monkeypatch.setattr(indexer, "_connect", lambda: _LockedConn(real_connect()))

    result = indexer.index_info()

    assert result == {}
    assert any("index_info" in r and "locked" in r for r in loguru_sink), (
        "a lock must be logged, not silently read as an unbuilt index"
    )


def test_search_entities_logs_a_warning_and_degrades_on_lock(tmp_path, monkeypatch, loguru_sink):
    indexer = _seeded_indexer(tmp_path)
    monkeypatch.setattr(
        indexer, "_knn",
        lambda *a, **k: (_ for _ in ()).throw(sqlite3.OperationalError("database is locked")),
    )

    assert indexer.search_entities("anything") == []
    assert any("search_entities" in r and "locked" in r for r in loguru_sink)


def test_search_kind_logs_a_warning_and_degrades_on_lock(tmp_path, monkeypatch, loguru_sink):
    indexer = _seeded_indexer(tmp_path)
    monkeypatch.setattr(
        indexer, "_knn",
        lambda *a, **k: (_ for _ in ()).throw(sqlite3.OperationalError("database is locked")),
    )

    assert indexer._search_kind("episodes", "anything", 5) == []
    assert any("_search_kind" in r and "episodes" in r and "locked" in r for r in loguru_sink)


def test_search_claims_logs_a_warning_and_degrades_on_lock(tmp_path, monkeypatch, loguru_sink):
    indexer = _seeded_indexer(tmp_path)
    monkeypatch.setattr(
        indexer, "_knn",
        lambda *a, **k: (_ for _ in ()).throw(sqlite3.OperationalError("database is locked")),
    )

    assert indexer.search_claims("anything") == []
    assert any("search_claims" in r and "locked" in r for r in loguru_sink)


# --------------------------------------------------------------------------- #
# Devin PR #24 round 1, finding 4 — enabling WAL can itself throw, and it ran
# in _connect() BEFORE the caller's own graceful `except
# sqlite3.OperationalError`, so a lock at connect time raised instead of
# degrading. _try_enable_wal must never propagate.
# --------------------------------------------------------------------------- #


class _PragmaFailsConn:
    """Duck-typed stand-in for a locked connection: every `.execute()` (i.e.
    both PRAGMA statements _try_enable_wal issues) raises."""

    def __init__(self):
        self.executed: list[str] = []

    def execute(self, sql, *_a, **_k):
        self.executed.append(sql)
        raise sqlite3.OperationalError("database is locked")


def _reset_wal_warned_flag(monkeypatch):
    import api.services.vector_index as vi
    monkeypatch.setattr(vi, "_warned_wal_failure", False)


def test_try_enable_wal_never_raises_on_a_locked_connection(monkeypatch):
    from api.services.vector_index import _try_enable_wal

    _reset_wal_warned_flag(monkeypatch)
    conn = _PragmaFailsConn()

    _try_enable_wal(conn)  # must not raise

    # Stops after the FIRST failing PRAGMA — synchronous=NORMAL is never
    # attempted once journal_mode=WAL has already failed.
    assert conn.executed == ["PRAGMA journal_mode=WAL"]


def test_try_enable_wal_logs_the_failure_exactly_once_across_calls(monkeypatch, loguru_sink):
    from api.services.vector_index import _try_enable_wal

    _reset_wal_warned_flag(monkeypatch)

    _try_enable_wal(_PragmaFailsConn())
    _try_enable_wal(_PragmaFailsConn())
    _try_enable_wal(_PragmaFailsConn())

    warnings = [r for r in loguru_sink if "WAL" in r]
    assert len(warnings) == 1, "a persistently-locked file must not warn on every connect"


class _PragmaFlakyRealConn:
    """Wraps a REAL sqlite3.Connection (so `sqlite_vec.load` and normal
    queries still work — `sqlite_vec.load` just calls
    `conn.load_extension(...)`, no isinstance checks) but raises
    OperationalError for the journal_mode PRAGMA specifically, reproducing
    the actual regression path through `_connect()`."""

    def __init__(self, real):
        self._real = real

    def execute(self, sql, *a, **k):
        # Only the SET form (what `_try_enable_wal` issues) fails — a later
        # bare `PRAGMA journal_mode` read (used by this test to verify the
        # mode genuinely didn't change) must still work.
        if isinstance(sql, str) and sql.upper() == "PRAGMA JOURNAL_MODE=WAL":
            raise sqlite3.OperationalError("database is locked")
        return self._real.execute(sql, *a, **k)

    def __getattr__(self, name):
        return getattr(self._real, name)


def test_connect_itself_never_raises_when_the_wal_pragma_is_locked(tmp_path, monkeypatch, loguru_sink):
    """End-to-end reproduction of finding 4: `_connect()` must degrade to a
    working connection on the pre-existing journal mode, not propagate — a
    request must never 500 because the index couldn't switch to WAL."""
    _reset_wal_warned_flag(monkeypatch)
    indexer = _seeded_indexer(tmp_path)

    real_sqlite3_connect = sqlite3.connect

    def wrapping_connect(*a, **k):
        return _PragmaFlakyRealConn(real_sqlite3_connect(*a, **k))

    monkeypatch.setattr("api.services.vector_index.sqlite3.connect", wrapping_connect)

    conn = indexer._connect()  # must not raise
    try:
        # The connection is still fully usable for real queries even though
        # the WAL PRAGMA it attempted raised.
        cur = conn.execute("SELECT 1")
        assert cur.fetchone() == (1,)
    finally:
        conn.close()

    assert any("WAL" in r and "locked" in r for r in loguru_sink)

    # And the ACTUAL search path (the caller-facing regression) still WORKS
    # end to end rather than raising up through the router — the connection
    # is fully usable, just not on WAL.
    results = indexer.search_entities("anything")
    assert results and results[0]["metadata"]["entity_id"] == "x"
