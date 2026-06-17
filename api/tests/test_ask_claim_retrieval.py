"""Tests for M5e retrieval swap: claim-first default retrieve_fn + entity fallback.

The default ``ask_service`` retrieval becomes **claim-first**: it searches the
derived ``claims`` index (``search_claims``), expands 1-hop over the graph and
transclusion, and maps each claim hit back to its subject entity so the existing
``answer/confidence/citations/gaps`` contract is preserved. **When the bank has no
claims yet** (un-consolidated / legacy), it falls back to ``search_entities`` so
``/ask`` does not regress.

Hermetic: a fake ``embed_fn`` is injected into the indexer (never a real model);
the LLM is injected via ``llm_fn``. The default ``retrieve_fn`` builder is
exercised directly so the claim→entity mapping is covered.
"""

from __future__ import annotations

import json

import numpy as np

from api.services import ask_service, markdown_parser
from api.services.claims import Claim, write_claims
from api.services.vector_index import SqliteVecIndexer

_VOCAB = ["sqlite", "vec", "index", "fastapi", "backend", "rodrigo", "acme", "company"]


def fake_embed(texts, *, is_query: bool = False):
    rows = []
    for text in texts:
        low = text.lower()
        vec = np.array([float(low.count(w)) for w in _VOCAB], dtype=np.float32)
        norm = float(np.linalg.norm(vec))
        if norm > 0:
            vec = vec / norm
        else:
            vec = np.ones(len(_VOCAB), dtype=np.float32) / np.sqrt(len(_VOCAB))
        rows.append(vec)
    return np.vstack(rows).astype(np.float32)


def _write_entity_with_claims(entities_dir, stem, name, claims, body_prose="A page."):
    body = write_claims(body_prose, claims)
    markdown_parser.write(
        entities_dir / f"{stem}.md",
        {"name": name, "type": "concept", "status": "active", "confidence": 0.8},
        body,
    )


def _claim(cid, subject, text, **kw):
    kw.setdefault("observer", "agent")
    kw.setdefault("context", "general")
    kw.setdefault("valid_from", "2026-01-01")
    return Claim(id=cid, text=text, subject=subject, **kw)


def test_claim_first_retrieval_grounds_on_claims(tmp_path):
    entities_dir = tmp_path / "entities"
    entities_dir.mkdir()
    _write_entity_with_claims(
        entities_dir, "cicada", "Cicada",
        [_claim("clm_1", "cicada", "Cicada uses sqlite-vec for its index.",
                predicate="uses", object="sqlite-vec")],
        body_prose="Cicada is a memory system.",
    )
    indexer = SqliteVecIndexer(tmp_path, embed_fn=fake_embed)
    indexer.index_claims()
    indexer.index_entities()

    retrieve_fn = ask_service.build_claim_first_retrieve_fn(tmp_path, embed_fn=fake_embed)
    llm_fn = _llm({
        "answer": "Cicada uses sqlite-vec.",
        "confidence": 0.8,
        "used_entities": ["cicada"],
        "gaps": [],
    })

    result = ask_service.answer_query(
        tmp_path, "sqlite vec index", top_k=6, retrieve_fn=retrieve_fn, llm_fn=llm_fn
    )
    cited = {c["entity_id"] for c in result["citations"]}
    assert "cicada" in cited
    assert "sqlite-vec" in result["answer"]


def test_retrieval_falls_back_to_entities_when_no_claims(tmp_path):
    """A bank with entities but NO claims must still ground via search_entities."""
    entities_dir = tmp_path / "entities"
    entities_dir.mkdir()
    # entity page with no ```claims block
    markdown_parser.write(
        entities_dir / "fastapi.md",
        {"name": "FastAPI", "type": "tool", "status": "active", "confidence": 0.8},
        "FastAPI is the backend web framework.",
    )
    indexer = SqliteVecIndexer(tmp_path, embed_fn=fake_embed)
    indexer.index_entities()
    # claims index is empty (no claims on any page)
    assert indexer.index_claims() == 0

    retrieve_fn = ask_service.build_claim_first_retrieve_fn(tmp_path, embed_fn=fake_embed)
    llm_fn = _llm({
        "answer": "The backend is FastAPI.",
        "confidence": 0.7,
        "used_entities": ["fastapi"],
        "gaps": [],
    })

    result = ask_service.answer_query(
        tmp_path, "fastapi backend", top_k=6, retrieve_fn=retrieve_fn, llm_fn=llm_fn
    )
    cited = {c["entity_id"] for c in result["citations"]}
    assert cited == {"fastapi"}, "must fall back to entity search when no claims"


def test_claim_hit_maps_to_subject_entity_id(tmp_path):
    """A claim hit must resolve to its subject's entity id for citation."""
    entities_dir = tmp_path / "entities"
    entities_dir.mkdir()
    _write_entity_with_claims(
        entities_dir, "rodrigo", "Rodrigo",
        [_claim("clm_w", "rodrigo", "Rodrigo works at Acme company.",
                predicate="works-at", object="acme", context="career")],
    )
    indexer = SqliteVecIndexer(tmp_path, embed_fn=fake_embed)
    indexer.index_claims()
    indexer.index_entities()

    retrieve_fn = ask_service.build_claim_first_retrieve_fn(tmp_path, embed_fn=fake_embed)
    hits = retrieve_fn("rodrigo acme company", 6)
    assert hits, "claim search should return hits"
    # hits are in the search_entities shape so the ask pipeline is unchanged
    ids = {h["metadata"]["entity_id"] for h in hits}
    assert "rodrigo" in ids
    # citation carries the claim provenance (claim_id + observer + valid window)
    rodrigo_hit = next(h for h in hits if h["metadata"]["entity_id"] == "rodrigo")
    assert rodrigo_hit["metadata"].get("claim_id") == "clm_w"
    assert rodrigo_hit["metadata"].get("observer") == "agent"


def _llm(payload):
    def _call(prompt):
        return json.dumps(payload)
    return _call
