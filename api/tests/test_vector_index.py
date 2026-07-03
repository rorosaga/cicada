"""Tests for the sqlite-vec derived vector index (LEANN replacement).

The indexer is decoupled from the embedding backend via an injected
``embed_fn`` so these tests run fully offline with a deterministic,
bag-of-words embedder — no OpenAI key, no model download.
"""

from __future__ import annotations

import numpy as np

from api.services import markdown_parser
from api.services.vector_index import PendingEntity, SqliteVecIndexer

# A tiny fixed vocabulary so a hand-rolled embedder produces meaningful
# cosine geometry: texts sharing words land close together.
_VOCAB = ["python", "web", "framework", "api", "database", "music", "guitar", "acoustic"]


def fake_embed(texts: list[str], *, is_query: bool = False) -> np.ndarray:
    """Deterministic normalized bag-of-words embedding over ``_VOCAB``.

    Accepts ``is_query`` (ignored here) to match the asymmetric embedding
    contract: production routes documents and queries through different
    EmbeddingGemma prompts via ``encode_document`` / ``encode_query``.
    """
    rows = []
    for text in texts:
        low = text.lower()
        vec = np.array([float(low.count(word)) for word in _VOCAB], dtype=np.float32)
        norm = float(np.linalg.norm(vec))
        if norm > 0:
            vec = vec / norm
        rows.append(vec)
    return np.vstack(rows).astype(np.float32)


def _make_entity(entities_dir, stem, name, etype, body, **extra_fm):
    fm = {
        "name": name,
        "type": etype,
        "status": "active",
        "confidence": 0.8,
        **extra_fm,
    }
    markdown_parser.write(entities_dir / f"{stem}.md", fm, body)


def test_search_entities_ranks_semantic_match_first(tmp_path):
    entities_dir = tmp_path / "entities"
    entities_dir.mkdir()
    _make_entity(
        entities_dir, "fastapi", "FastAPI", "tool",
        "A python web framework for building an api with async support.",
    )
    _make_entity(
        entities_dir, "guitar-practice", "Guitar Practice", "skill",
        "Daily acoustic guitar music practice routine.",
    )

    indexer = SqliteVecIndexer(tmp_path, embed_fn=fake_embed)
    count = indexer.index_entities()
    assert count == 2

    results = indexer.search_entities("python web framework api", top_k=2)

    assert results, "expected at least one hit"
    top = results[0]
    assert top["metadata"]["entity_id"] == "fastapi"
    assert top["metadata"]["type"] == "tool"
    assert top["metadata"]["status"] == "active"
    assert isinstance(top["score"], float)


def test_search_missing_index_returns_empty(tmp_path):
    """Cold/fresh install: no index file yet -> [] so the caller can degrade."""
    (tmp_path / "entities").mkdir()
    indexer = SqliteVecIndexer(tmp_path, embed_fn=fake_embed)
    assert indexer.search_entities("anything", top_k=5) == []


def test_archived_entities_excluded_by_default(tmp_path):
    entities_dir = tmp_path / "entities"
    entities_dir.mkdir()
    _make_entity(
        entities_dir, "active-api", "Active API", "tool",
        "python web framework api service.", status="active",
    )
    _make_entity(
        entities_dir, "old-api", "Old API", "tool",
        "python web framework api legacy.", status="archived",
    )
    indexer = SqliteVecIndexer(tmp_path, embed_fn=fake_embed)
    indexer.index_entities()

    # with < top_k active hits, archived entities are appended as fallback
    default_hits = indexer.search_entities("python web framework api", top_k=5)
    ids = {h["metadata"]["entity_id"] for h in default_hits}
    assert "active-api" in ids
    assert "old-api" in ids  # archived surfaced as fallback when active set thin

    all_hits = indexer.search_entities(
        "python web framework api", top_k=5, include_archived=True
    )
    assert "old-api" in {h["metadata"]["entity_id"] for h in all_hits}


def test_index_info_records_model_and_dim(tmp_path):
    """Reindex must know what it built: model name + vector dim are persisted."""
    entities_dir = tmp_path / "entities"
    entities_dir.mkdir()
    _make_entity(entities_dir, "fastapi", "FastAPI", "tool", "python web framework api.")

    indexer = SqliteVecIndexer(tmp_path, embed_fn=fake_embed, model_name="fake-test-v1")
    indexer.index_entities()

    info = indexer.index_info()
    assert info["model"] == "fake-test-v1"
    assert info["dim"] == len(_VOCAB)


def test_documents_indexed_as_document_queries_searched_as_query(tmp_path):
    """Asymmetric embedding: index path is_query=False, search path is_query=True."""
    calls: list[bool] = []

    def recording_embed(texts, *, is_query=False):
        calls.append(is_query)
        return fake_embed(texts, is_query=is_query)

    entities_dir = tmp_path / "entities"
    entities_dir.mkdir()
    _make_entity(entities_dir, "fastapi", "FastAPI", "tool", "python web framework api.")

    indexer = SqliteVecIndexer(tmp_path, embed_fn=recording_embed)
    indexer.index_entities()
    assert calls == [False], "indexing must embed documents (is_query=False)"

    indexer.search_entities("python web framework", top_k=1)
    assert calls[-1] is True, "search must embed the query (is_query=True)"


def _make_episode(episodes_dir, stem, body, **fm):
    base = {"id": stem, "source": "test", "timestamp": "2026-06-17T00:00:00", "title": stem}
    base.update(fm)
    markdown_parser.write(episodes_dir / f"{stem}.md", base, body)


def test_index_and_search_episodes(tmp_path):
    episodes_dir = tmp_path / "episodes"
    episodes_dir.mkdir()
    _make_episode(episodes_dir, "ep_001", "We discussed the python web framework api design.")
    _make_episode(episodes_dir, "ep_002", "Notes about acoustic guitar music practice.")

    indexer = SqliteVecIndexer(tmp_path, embed_fn=fake_embed)
    count = indexer.index_episodes()
    assert count == 2

    hits = indexer.search_episodes("python web framework", top_k=2)
    assert hits
    assert hits[0]["metadata"]["episode_id"] == "ep_001"


def test_pending_roundtrip_and_promote(tmp_path):
    (tmp_path / "entities").mkdir()
    indexer = SqliteVecIndexer(tmp_path, embed_fn=fake_embed)

    entity = PendingEntity(
        name="Mongo",
        type="tool",
        description="python database vector store mentioned once.",
        source_episode="ep_001",
        confidence=0.3,
        tags=[],
        history_entries=[],
    )
    indexer.index_pending_entity(entity)
    indexer.rebuild_pending_index()

    assert indexer.pending_by_name("Mongo") is not None
    found = indexer.search_pending("python database", top_k=3)
    assert any(h["metadata"]["entity_name"] == "Mongo" for h in found)

    promoted = indexer.promote_from_pending("Mongo")
    assert promoted is not None and promoted.name == "Mongo"
    assert indexer.pending_by_name("Mongo") is None
