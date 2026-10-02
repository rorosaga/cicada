"""Track B — Sleep's index step is incremental and off the event loop.

The vector index used to re-embed every episode, entity and claim each cycle
and the FTS index rebuilt in full, both synchronously inside the async cycle.
Now a document is embedded only when its text hash is new or changed, deleted
documents leave the index, a model / schema / dimension change rebuilds the
table, the FTS file is refreshed by its (mtime, size) stamps, and the blocking
work runs through ``asyncio.to_thread``. Both indexes stay derived and
disposable: deleting either file costs a build, never a fact.
"""
from __future__ import annotations

import asyncio
import sqlite3
import time

import numpy as np
import pytest

from api.services import bank_index, markdown_parser, search_index, sleep_cycle
from api.services.claims import Claim, write_claims
from api.services.vector_index import SqliteVecIndexer

_VOCAB = ["python", "web", "guitar", "music", "graph", "memory", "sleep", "cycle"]


class CountingEmbedder:
    """Deterministic bag-of-words embedder that records every text it embeds."""

    def __init__(self, dim_pad: int = 0):
        self.seen: list[str] = []
        self.dim_pad = dim_pad

    def __call__(self, texts, *, is_query: bool = False):
        if not is_query:
            self.seen.extend(texts)
        rows = []
        for text in texts:
            low = text.lower()
            vec = np.array([float(low.count(w)) for w in _VOCAB] + [0.0] * self.dim_pad,
                           dtype=np.float32)
            n = float(np.linalg.norm(vec))
            rows.append(vec / n if n else vec)
        return np.vstack(rows).astype(np.float32)


def _bank(tmp_path):
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    (memory / "episodes").mkdir(parents=True)
    return memory


def _episode(memory, n, body, **fm):
    markdown_parser.write(
        memory / "episodes" / f"ep_2026-06-01_{n:03d}.md",
        {"id": f"ep_2026-06-01_{n:03d}", "processed": True, "source": "mcp",
         "timestamp": "2026-06-01T10:00:00", **fm},
        body,
    )


def _entity(memory, stem, body, **fm):
    markdown_parser.write(
        memory / "entities" / f"{stem}.md",
        {"name": stem.title(), "type": "tool", "status": "active", "confidence": 0.8, **fm},
        body,
    )


def _indexer(memory, embed, model="fake-model"):
    return SqliteVecIndexer(memory, embed_fn=embed, model_name=model)


def _episode_ids(idx, query="python"):
    return sorted({r["metadata"]["episode_id"] for r in idx.search_episodes(query, top_k=50)})


# --- vector index ------------------------------------------------------------


def test_an_unchanged_episode_is_not_re_embedded_and_a_changed_one_is(tmp_path):
    memory = _bank(tmp_path)
    for n in range(1, 5):
        _episode(memory, n, f"python talk number {n}")
    emb = CountingEmbedder()
    idx = _indexer(memory, emb)

    assert idx.index_episodes() == 4
    assert len(emb.seen) == 4 and idx.last_sync["episodes"]["rebuilt"] == 1

    emb.seen.clear()
    assert idx.index_episodes() == 4
    assert emb.seen == [], "nothing changed, nothing embedded"
    assert idx.last_sync["episodes"] == {"embedded": 0, "reused": 4, "removed": 0, "rebuilt": 0}

    _episode(memory, 2, "guitar music instead")
    assert idx.index_episodes() == 4
    assert emb.seen == ["guitar music instead"], "only the edited episode is embedded"
    assert idx.last_sync["episodes"]["reused"] == 3

    hits = idx.search_episodes("guitar music", top_k=1)
    assert hits[0]["metadata"]["episode_id"] == "ep_2026-06-01_002"


def test_a_new_episode_is_added_and_a_deleted_one_leaves_the_index(tmp_path):
    memory = _bank(tmp_path)
    for n in range(1, 4):
        _episode(memory, n, f"python talk number {n}")
    emb = CountingEmbedder()
    idx = _indexer(memory, emb)
    idx.index_episodes()
    emb.seen.clear()

    _episode(memory, 4, "web graph memory")
    (memory / "episodes" / "ep_2026-06-01_001.md").unlink()
    assert idx.index_episodes() == 3
    assert emb.seen == ["web graph memory"]
    assert idx.last_sync["episodes"] == {"embedded": 1, "reused": 2, "removed": 1, "rebuilt": 0}
    assert _episode_ids(idx) == ["ep_2026-06-01_002", "ep_2026-06-01_003", "ep_2026-06-01_004"]


def test_incremental_results_equal_a_fresh_full_build(tmp_path):
    memory = _bank(tmp_path)
    for n in range(1, 7):
        _episode(memory, n, f"python web {'guitar ' * n} note {n}")
    idx = _indexer(memory, CountingEmbedder())
    idx.index_episodes()
    _episode(memory, 3, "memory sleep cycle")
    (memory / "episodes" / "ep_2026-06-01_006.md").unlink()
    _episode(memory, 7, "graph graph python")
    idx.index_episodes()

    fresh_root = tmp_path / "fresh"
    fresh_root.mkdir()
    (fresh_root / "episodes").mkdir()
    for f in (memory / "episodes").glob("*.md"):
        (fresh_root / "episodes" / f.name).write_bytes(f.read_bytes())
    fresh = _indexer(fresh_root, CountingEmbedder())
    fresh.index_episodes()

    for q in ("python", "guitar", "memory sleep", "graph"):
        a = [(r["metadata"]["episode_id"], round(r["score"], 5)) for r in idx.search_episodes(q, 10)]
        b = [(r["metadata"]["episode_id"], round(r["score"], 5)) for r in fresh.search_episodes(q, 10)]
        assert a == b, q


def test_a_grown_long_episode_re_embeds_only_the_passages_that_changed(tmp_path):
    memory = _bank(tmp_path)
    para = "python web memory graph\n" * 200          # ~4.8k chars: two passages
    _episode(memory, 1, para)
    emb = CountingEmbedder()
    idx = _indexer(memory, emb)
    idx.index_episodes()
    first_passages = len(emb.seen)
    assert first_passages >= 2
    emb.seen.clear()

    _episode(memory, 1, para + "sleep cycle tail\n" * 5)
    idx.index_episodes()
    assert 0 < len(emb.seen) < first_passages + 1
    assert idx.last_sync["episodes"]["rebuilt"] == 0


def test_a_metadata_only_change_updates_in_place_without_embedding(tmp_path):
    memory = _bank(tmp_path)
    _entity(memory, "fastapi", "python web framework")
    emb = CountingEmbedder()
    idx = _indexer(memory, emb)
    idx.index_entities()
    emb.seen.clear()

    _entity(memory, "fastapi", "python web framework", status="archived", confidence=0.1)
    idx.index_entities()
    assert emb.seen == []
    (hit,) = idx.search_entities("python web", top_k=1, include_archived=True)
    assert hit["metadata"]["status"] == "archived"
    assert hit["metadata"]["confidence"] == pytest.approx(0.1)


def test_entities_and_claims_are_incremental_too(tmp_path):
    memory = _bank(tmp_path)
    _entity(memory, "alpha", "python graph")
    _entity(memory, "beta", "guitar music")

    def with_claims(stem, texts):
        parsed = markdown_parser.parse(memory / "entities" / f"{stem}.md")
        claims = [Claim(id=f"clm_{stem}_{i}", text=t, subject=stem, predicate="describes",
                        object=t, valid_from="2026-06-01") for i, t in enumerate(texts)]
        markdown_parser.write(memory / "entities" / f"{stem}.md", parsed.frontmatter,
                              write_claims(parsed.body, claims))

    with_claims("alpha", ["alpha likes python", "alpha likes graph"])
    with_claims("beta", ["beta plays guitar"])
    emb = CountingEmbedder()
    idx = _indexer(memory, emb)
    idx.index_entities()
    assert idx.index_claims() == 3
    emb.seen.clear()

    assert idx.index_entities() == 2 and idx.index_claims() == 3
    assert emb.seen == []

    with_claims("beta", ["beta plays guitar", "beta plays music"])
    assert idx.index_claims() == 4
    assert emb.seen == ["beta plays music"]
    # the entity page text moved too (a claims block was appended to its body)
    idx.index_entities()
    assert idx.last_sync["entities"]["embedded"] == 1


def test_a_model_change_forces_a_full_rebuild(tmp_path):
    memory = _bank(tmp_path)
    for n in range(1, 4):
        _episode(memory, n, f"python talk {n}")
    idx = _indexer(memory, CountingEmbedder(), model="model-a")
    idx.index_episodes()

    emb_b = CountingEmbedder()
    other = _indexer(memory, emb_b, model="model-b")
    other.index_episodes()
    assert len(emb_b.seen) == 3, "vectors from another model are never reused"
    assert other.last_sync["episodes"]["rebuilt"] == 1
    assert other.index_info()["model"] == "model-b"


def test_a_dimension_change_under_the_same_model_name_rebuilds(tmp_path):
    memory = _bank(tmp_path)
    for n in range(1, 4):
        _episode(memory, n, f"python talk {n}")
    _indexer(memory, CountingEmbedder()).index_episodes()
    _episode(memory, 2, "guitar music")            # something to embed -> width is seen

    wide = CountingEmbedder(dim_pad=4)
    idx = _indexer(memory, wide)
    idx.index_episodes()
    assert idx.last_sync["episodes"]["rebuilt"] == 1
    assert len(idx.search_episodes("python", top_k=5)) == 3


def test_an_older_schema_table_is_rebuilt_in_full(tmp_path):
    memory = _bank(tmp_path)
    for n in range(1, 4):
        _episode(memory, n, f"python talk {n}")
    idx = _indexer(memory, CountingEmbedder())
    idx.index_episodes()
    conn = sqlite3.connect(idx.db_path)
    conn.execute("ALTER TABLE meta_episodes DROP COLUMN hash")   # what a pre-Track-B file lacks
    conn.commit()
    conn.close()

    emb = CountingEmbedder()
    _indexer(memory, emb).index_episodes()
    assert len(emb.seen) == 3


def test_a_failed_embed_leaves_the_previous_index_untouched(tmp_path):
    memory = _bank(tmp_path)
    for n in range(1, 4):
        _episode(memory, n, f"python talk {n}")
    idx = _indexer(memory, CountingEmbedder())
    idx.index_episodes()
    _episode(memory, 2, "guitar music")
    _episode(memory, 9, "memory new one")
    (memory / "episodes" / "ep_2026-06-01_001.md").unlink()

    def boom(texts, *, is_query=False):
        raise RuntimeError("embedder down")

    broken = _indexer(memory, boom)
    with pytest.raises(RuntimeError):
        broken.index_episodes()
    assert _episode_ids(idx) == ["ep_2026-06-01_001", "ep_2026-06-01_002", "ep_2026-06-01_003"]

    idx.index_episodes()                     # and the next healthy run catches up
    assert _episode_ids(idx) == ["ep_2026-06-01_002", "ep_2026-06-01_003", "ep_2026-06-01_009"]


def test_the_index_file_is_disposable(tmp_path):
    memory = _bank(tmp_path)
    _episode(memory, 1, "python talk")
    idx = _indexer(memory, CountingEmbedder())
    idx.index_episodes()
    idx.db_path.unlink()
    emb = CountingEmbedder()
    _indexer(memory, emb).index_episodes()
    assert emb.seen == ["python talk"]


def test_removing_every_document_empties_the_index(tmp_path):
    memory = _bank(tmp_path)
    _episode(memory, 1, "python talk")
    idx = _indexer(memory, CountingEmbedder())
    idx.index_episodes()
    (memory / "episodes" / "ep_2026-06-01_001.md").unlink()
    assert idx.index_episodes() == 0
    assert idx.search_episodes("python", top_k=5) == []


# --- FTS index ---------------------------------------------------------------


@pytest.fixture()
def fts_state():
    bank_index.invalidate()
    search_index.reset()
    yield
    search_index.reset()
    bank_index.invalidate()


def _count_indexed(monkeypatch):
    seen: list[str] = []
    real = search_index._index_doc

    def spy(conn, doc_key, f):
        seen.append(doc_key)
        return real(conn, doc_key, f)

    monkeypatch.setattr(search_index, "_index_doc", spy)
    return seen


def test_refresh_reindexes_only_the_documents_that_moved(tmp_path, monkeypatch, fts_state):
    memory = _bank(tmp_path)
    for n in range(1, 6):
        _episode(memory, n, f"python talk {n}")
    _entity(memory, "alpha", "python graph")
    search_index.refresh(memory)                       # cold: a full build

    seen = _count_indexed(monkeypatch)
    search_index.refresh(memory)
    assert seen == [], "an idle night re-indexes nothing"

    _episode(memory, 3, "a much longer rewrite of the third talk")
    _episode(memory, 6, "brand new")
    (memory / "episodes" / "ep_2026-06-01_001.md").unlink()
    search_index.refresh(memory)
    assert sorted(seen) == ["episodes/ep_2026-06-01_003.md", "episodes/ep_2026-06-01_006.md"]

    with search_index.Reader(memory) as r:
        assert len(r.ranked("pas", search_index.match_expression(["brand"]), 5)) == 1
        # "python" was in episodes 1-5 (+ the entity page); 1 is gone, 3 was rewritten
        assert len(r.ranked("pas", search_index.match_expression(["python"]), 10)) == 3


def test_refresh_builds_a_missing_file_and_rebuilds_a_schema_mismatch(tmp_path, monkeypatch, fts_state):
    memory = _bank(tmp_path)
    _episode(memory, 1, "python talk")
    search_index.refresh(memory)
    db = search_index.db_path(memory)
    assert db.exists()

    db.unlink()
    for suffix in ("-wal", "-shm"):
        (db.parent / (db.name + suffix)).unlink(missing_ok=True)
    search_index.reset(memory)
    seen = _count_indexed(monkeypatch)
    search_index.refresh(memory)
    assert seen == ["episodes/ep_2026-06-01_001.md"], "a missing file is a full build"

    conn = sqlite3.connect(db)
    conn.execute("UPDATE meta SET value = 'old-schema' WHERE key = 'schema'")
    conn.commit()
    conn.close()
    search_index.reset(memory)
    seen.clear()
    search_index.refresh(memory)
    assert seen == ["episodes/ep_2026-06-01_001.md"], "another schema is a full build"


def test_refresh_replaces_a_corrupt_file(tmp_path, fts_state):
    memory = _bank(tmp_path)
    _episode(memory, 1, "python talk")
    search_index.refresh(memory)
    db = search_index.db_path(memory)
    for suffix in ("-wal", "-shm"):
        (db.parent / (db.name + suffix)).unlink(missing_ok=True)
    db.write_bytes(b"this is not a database" * 100)
    search_index.reset(memory)
    search_index.refresh(memory)
    with search_index.Reader(memory) as r:
        assert len(r.ranked("pas", search_index.match_expression(["python"]), 5)) == 1


# --- the cycle keeps the loop free -------------------------------------------


def test_the_cycle_index_step_does_not_block_the_event_loop(tmp_path, monkeypatch, fts_state):
    from test_sleep_cycle_claims_wired import _patch_boundaries, _seed_bank, _settings

    memory = _seed_bank(tmp_path)
    extracted = [{
        "episode_id": "ep_2026-06-17_001", "episode_timestamp": "2026-06-17T10:00:00",
        "origin": "claude-code", "relationships": [],
        "entities": [{"name": "Cicada", "type": "project", "source_episode": "ep_2026-06-17_001"}],
    }]
    resolved = [{"id": "cicada", "action": "create", "source_episode": "ep_2026-06-17_001",
                 "source_episodes": ["ep_2026-06-17_001"], "trigger": "sleep/extraction",
                 "entity": {"name": "Cicada", "type": "project", "confidence": 0.8, "key_facts": []}}]
    _patch_boundaries(monkeypatch, memory, extracted=extracted, resolved_changes=resolved,
                      resolved_edges=[])

    SLOW_S = 0.4

    class SlowIndexer:
        def __init__(self, *_a, **_k):
            pass

        def index_entities(self):
            time.sleep(SLOW_S)      # a real embed: synchronous CPU the loop must not wait on
            return 0

        def index_episodes(self):
            time.sleep(SLOW_S)
            return 0

        def index_claims(self):
            return 0

    real_refresh = search_index.refresh

    def slow_refresh(path):
        time.sleep(SLOW_S)
        return real_refresh(path)

    monkeypatch.setattr("api.services.vector_index.SqliteVecIndexer", SlowIndexer)
    monkeypatch.setattr(search_index, "refresh", slow_refresh)

    async def scenario():
        worst_gap = 0.0
        running = True

        async def ticker():
            nonlocal worst_gap
            last = time.monotonic()
            while running:
                await asyncio.sleep(0.01)
                now = time.monotonic()
                worst_gap = max(worst_gap, now - last)
                last = now

        task = asyncio.create_task(ticker())
        await asyncio.sleep(0.05)      # the ticker is running before the cycle starts
        started = time.monotonic()
        await sleep_cycle.run(_settings(memory), cycle_id="2026-06-17_loop")
        elapsed = time.monotonic() - started
        running = False
        await task
        return worst_gap, elapsed

    worst_gap, elapsed = asyncio.run(scenario())
    assert elapsed >= 3 * SLOW_S, "the slow index work really ran inside the cycle"
    # Each slow step blocks for 0.4 s; a free loop is never away from the
    # ticker for more than a fraction of that.
    assert worst_gap < SLOW_S / 2, f"the loop stalled for {worst_gap:.2f}s during the cycle"
    assert sleep_cycle._state.index_warning is None
