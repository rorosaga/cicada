"""ROR-134 — the graph's "closeness by meaning": each page's nearest pages by what they say.

Distance only. The pairs this module returns are never links: they draw no edge, create no relation and imply none
(ruling 56 — a link needs a recorded fact or a stated reason). The app uses them as a weak pull in its layout, behind a
switch that is off by default.

The vectors are the entity index's own (``vec_entities``, the same ones search uses), read from the derived
``vector_index.db`` on this Mac. Nothing is embedded here and nothing is stored: the neighbours are computed from the
index and held in memory, keyed by the index file's signature, so a Sleep that moves a vector recomputes them once and
every other request is a lookup. All pairs are never sent to a client — each page keeps its ``k`` nearest, above a floor,
and the pair list is the union of those (at most ``MAX_PAIRS_PER_PAGE`` per page, not n²).
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import numpy as np
from loguru import logger

from api.services.vector_index import INDEX_DB_FILE, SqliteVecIndexer

#: Neighbours kept per page.
NEIGHBORS_K = 5
#: Cosine similarity below which two pages are not "about the same thing" however near they rank (a small memory has
#: few neighbours; an unrelated one must not be pulled in because it was the closest left).
MIN_SIMILARITY = 0.45
#: Most pairs one page may sit in. A page that is "near" to everything (a generic overview) would otherwise pull a
#: couple of hundred pages into one clump; past this its weakest pairs are left out (the strongest are kept first).
MAX_PAIRS_PER_PAGE = 10
#: Rows of the similarity matrix computed at a time: 1,024 × 9,000 float32 is 37 MB, never all pairs at once.
_CHUNK = 1024

_lock = threading.Lock()
_cache: dict[str, tuple[tuple, dict]] = {}


def signature(memory_path: Path) -> tuple:
    """Changes whenever the index file does (its WAL included): the cache key and the route's ETag."""
    db = Path(memory_path) / INDEX_DB_FILE
    parts: list[int] = []
    for p in (db, db.with_name(db.name + "-wal")):
        try:
            st = p.stat()
            parts += [st.st_mtime_ns, st.st_size]
        except OSError:
            parts += [0, 0]
    return (NEIGHBORS_K, MIN_SIMILARITY, *parts)


def _read_vectors(memory_path: Path) -> tuple[list[str], np.ndarray, str | None]:
    """``(page ids, unit-length float32 matrix, model)``; empty when the index is unbuilt or has no entity table."""
    db = Path(memory_path) / INDEX_DB_FILE
    if not db.exists():
        return [], np.zeros((0, 0), dtype=np.float32), None
    indexer = SqliteVecIndexer(memory_path)
    model = indexer.kind_model("entities")
    conn = indexer._connect()
    try:
        rows = conn.execute(
            "SELECT m.key, v.embedding FROM vec_entities v JOIN meta_entities m ON m.rowid = v.rowid ORDER BY m.rowid"
        ).fetchall()
    except sqlite3.OperationalError:
        return [], np.zeros((0, 0), dtype=np.float32), model
    finally:
        conn.close()
    ids = [str(k) for k, _ in rows]
    if not ids:
        return [], np.zeros((0, 0), dtype=np.float32), model
    mat = np.stack([np.frombuffer(b, dtype=np.float32) for _, b in rows]).astype(np.float32, copy=True)
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return ids, mat / norms, model


def nearest_pairs(ids: list[str], mat: np.ndarray, *, k: int = NEIGHBORS_K,
                  floor: float = MIN_SIMILARITY) -> list[list]:
    """The union of every page's ``k`` nearest others above ``floor``, as ``[a, b, weight]`` with ``a < b`` and weight the pair's rank among the pairs, 0..1.

    Chunked matrix products and a partial sort, so the cost is n²·d multiply-adds with O(chunk·n) memory. Ties break
    by position, so the same index gives the same pairs every time (a layout built on them does not jitter)."""
    n = len(ids)
    if n < 2:
        return []
    k = min(k, n - 1)
    best: dict[tuple[int, int], float] = {}
    for start in range(0, n, _CHUNK):
        block = mat[start:start + _CHUNK]
        sims = block @ mat.T
        rows = np.arange(block.shape[0])
        sims[rows, start + rows] = -2.0                      # never itself
        top = np.argpartition(-sims, k - 1, axis=1)[:, :k]
        for r in range(block.shape[0]):
            i = start + r
            for j in top[r]:
                s = float(sims[r, j])
                if s < floor:
                    continue
                key = (i, int(j)) if i < j else (int(j), i)
                best[key] = s
    taken: list[tuple[int, int, float]] = []
    degree: dict[int, int] = {}
    for (a, b), s in sorted(best.items(), key=lambda kv: (-kv[1], kv[0])):
        if degree.get(a, 0) >= MAX_PAIRS_PER_PAGE or degree.get(b, 0) >= MAX_PAIRS_PER_PAGE:
            continue
        degree[a] = degree.get(a, 0) + 1
        degree[b] = degree.get(b, 0) + 1
        taken.append((a, b, s))
    taken.sort()
    # The weight is the pair's rank among the pairs (0..1), not its raw similarity: a model's cosines sit in its own
    # band (0.77-0.92 on the small on-device one), so a client reading the raw number would need to know the model.
    order = np.argsort(np.argsort([s for _, _, s in taken], kind="stable"), kind="stable")
    top = max(len(taken) - 1, 1)
    return [[ids[a], ids[b], round(float(order[i]) / top, 2)] for i, (a, b, _) in enumerate(taken)]


def neighbors(memory_path: Path) -> dict:
    """``{"model", "k", "embedded", "pairs"}`` for the bank at ``memory_path`` (cached on the index's signature)."""
    memory_path = Path(memory_path)
    sig = signature(memory_path)
    key = str(memory_path.resolve())
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] == sig:
            return hit[1]
        ids, mat, model = _read_vectors(memory_path)
        result = {"model": model, "k": NEIGHBORS_K, "embedded": len(ids),
                  "pairs": nearest_pairs(ids, mat) if ids else []}
        _cache[key] = (sig, result)
    logger.debug(f"meaning neighbours: {len(ids)} pages, {len(result['pairs'])} pairs")
    return result
