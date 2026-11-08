"""ROR-134 — `GET /graph/meaning`: nearest pages by meaning, distance only (never a link, ruling 56)."""

from __future__ import annotations

import numpy as np
import pytest

from api.services import markdown_parser, meaning_neighbors
from api.services.vector_index import SqliteVecIndexer

# Two subjects on two axes, one page between them, one page on neither.
_DIRECTIONS = {
    "superhero-film": [1.0, 0.1, 0.0, 0.0],
    "superhero-comic": [0.95, 0.2, 0.0, 0.0],
    "cooking-notes": [0.0, 0.0, 1.0, 0.1],
    "pasta-recipe": [0.0, 0.1, 0.95, 0.2],
    "unrelated": [0.0, 0.0, 0.0, 1.0],
}


def _embed(texts: list[str], *, is_query: bool = False) -> np.ndarray:
    out = []
    for t in texts:
        name = next((k for k in _DIRECTIONS if k.replace("-", " ") in t.lower()), "unrelated")
        out.append(_DIRECTIONS[name])
    return np.array(out, dtype=np.float32)


@pytest.fixture
def bank(tmp_path):
    (tmp_path / "entities").mkdir()
    for stem in _DIRECTIONS:
        markdown_parser.write(
            tmp_path / "entities" / f"{stem}.md",
            {"name": stem.replace("-", " "), "type": "concept", "status": "active", "confidence": 0.5},
            f"About the {stem.replace('-', ' ')}.",
        )
    SqliteVecIndexer(tmp_path, embed_fn=_embed).index_entities()
    meaning_neighbors._cache.clear()
    return tmp_path


def test_same_subject_pairs_and_no_cross_subject_pair(bank):
    out = meaning_neighbors.neighbors(bank)
    pairs = {(a, b) for a, b, _ in out["pairs"]}
    assert ("superhero-comic", "superhero-film") in pairs
    assert ("cooking-notes", "pasta-recipe") in pairs
    assert not any("unrelated" in p for p in pairs)           # nothing near it: the floor keeps it unpulled
    assert not any({a, b} == {"superhero-film", "pasta-recipe"} for a, b in pairs)
    assert out["embedded"] == 5 and all(a < b for a, b, _ in out["pairs"])


def test_deterministic_and_cached_on_the_index_signature(bank):
    first = meaning_neighbors.neighbors(bank)
    assert meaning_neighbors.neighbors(bank) is first
    meaning_neighbors._cache.clear()
    assert meaning_neighbors.neighbors(bank)["pairs"] == first["pairs"]


def test_chunking_matches_one_block(monkeypatch):
    rng = np.random.default_rng(0)
    mat = rng.normal(size=(60, 8)).astype(np.float32)
    mat /= np.linalg.norm(mat, axis=1, keepdims=True)
    ids = [f"p{i:02d}" for i in range(60)]
    whole = meaning_neighbors.nearest_pairs(ids, mat, floor=-1.0)
    monkeypatch.setattr(meaning_neighbors, "_CHUNK", 7)
    assert meaning_neighbors.nearest_pairs(ids, mat, floor=-1.0) == whole


def test_no_index_is_empty_not_an_error(tmp_path):
    assert meaning_neighbors.neighbors(tmp_path) == {"model": None, "k": 5, "embedded": 0, "pairs": []}


def test_route_serves_pairs_and_304s(bank):
    from fastapi.testclient import TestClient

    from api.config import get_settings
    from api.main import app

    class _S:
        memory_path = bank

    app.dependency_overrides[get_settings] = lambda: _S()
    try:
        with TestClient(app) as client:
            r = client.get("/graph/meaning")
            assert r.status_code == 200 and r.json()["pairs"]
            again = client.get("/graph/meaning", headers={"If-None-Match": r.headers["ETag"]})
            assert again.status_code == 304
    finally:
        app.dependency_overrides.pop(get_settings, None)
