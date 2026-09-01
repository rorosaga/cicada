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
