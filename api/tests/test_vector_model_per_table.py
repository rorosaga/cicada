"""Audit 2026-10-05 P2-4/5/8 — the vector index's query side.

4. Each kind records the model its vectors were built with (`model:<kind>`),
   but a query was embedded with the bank-wide `model` stamp — whichever kind
   was rebuilt LAST. After a partial model switch (entities re-embedded with a
   new model, claims not yet), a claim query was embedded with the wrong model
   and ranked nonsense.
5. A dropped page (the person's "never resurface") still came back from
   semantic recall: the vector filter's tiers only knew `archived`, and the
   stored metadata is as old as the last sync.
8. MCP recall embedded the same query twice (the entity leg and the episode leg).

Fakes only: two deterministic embedders that disagree, no model download.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pytest

from api.services import markdown_parser, mcp_tools, providers, vector_index
from api.services.claims import Claim, write_claims
from api.services.vector_index import SqliteVecIndexer

VOCAB = ["alpha", "beta", "gamma", "delta", "rust", "python", "garden", "music"]


def _embedder(name: str, calls: list):
    """A bag-of-words embedder; model "b" permutes the axes, so a query
    embedded by the wrong model points somewhere else entirely."""
    order = list(range(len(VOCAB))) if name == "model-a" else list(reversed(range(len(VOCAB))))

    def embed(texts, *, is_query: bool = False):
        if is_query:
            calls.append((name, tuple(texts)))
        rows = []
        for t in texts:
            toks = set(re.findall(r"[a-z]+", t.lower()))
            v = np.array([1.0 if VOCAB[order[i]] in toks else 0.0 for i in range(len(VOCAB))], dtype=np.float32)
            n = float(np.linalg.norm(v))
            rows.append(v / n if n else np.ones(len(VOCAB), dtype=np.float32) / np.sqrt(len(VOCAB)))
        return np.vstack(rows).astype(np.float32)

    return embed


@pytest.fixture
def calls(monkeypatch):
    seen: list = []
    fns = {"model-a": _embedder("model-a", seen), "model-b": _embedder("model-b", seen)}
    monkeypatch.setattr(providers, "resolve_embed_fn_for_model", lambda mid, *a, **k: (fns[mid], mid))
    vector_index.clear_query_cache()
    return seen


def _page(bank: Path, eid: str, prose: str, *, status: str = "active", claims=()):
    body = f"## Summary\n{prose}\n"
    if claims:
        body = write_claims(body, list(claims))
    markdown_parser.write(bank / "entities" / f"{eid}.md",
                          {"name": eid, "type": "project", "status": status, "confidence": 0.5}, body)


def _bank(tmp_path: Path) -> Path:
    bank = tmp_path / "bank"
    (bank / "entities").mkdir(parents=True)
    _page(bank, "alpha-project", "alpha rust",
          claims=[Claim(id="c1", text="alpha uses rust", subject="alpha-project", predicate="uses", object="rust")])
    _page(bank, "beta-project", "beta python",
          claims=[Claim(id="c2", text="beta uses python", subject="beta-project", predicate="uses", object="python")])
    _page(bank, "gamma-garden", "gamma garden music")
    return bank


def _partial_switch(bank: Path) -> None:
    """Claims built with model-a; then the configured model became model-b and
    only the entity kind was re-synced (Sleep reindexes kind by kind)."""
    sink: list = []
    SqliteVecIndexer(bank, embed_fn=_embedder("model-a", sink), model_name="model-a").index_claims()
    SqliteVecIndexer(bank, embed_fn=_embedder("model-b", sink), model_name="model-b").index_entities()


def test_a_query_is_embedded_with_the_model_its_table_was_built_with(tmp_path, calls):
    bank = _bank(tmp_path)
    _partial_switch(bank)
    idx = SqliteVecIndexer(bank)
    hits = idx.search_claims("python", top_k=1)
    assert [c[0] for c in calls] == ["model-a"]
    assert hits and hits[0]["metadata"]["claim_id"] == "c2"
    calls.clear()
    ents = idx.search_entities("python", top_k=1)
    assert [c[0] for c in calls] == ["model-b"]
    assert ents and ents[0]["metadata"]["entity_id"] == "beta-project"


def test_a_multi_kind_search_embeds_once_per_model(tmp_path, calls):
    bank = _bank(tmp_path)
    _partial_switch(bank)
    legs = SqliteVecIndexer(bank).search_kinds("rust", {"entities": 2, "claims": 2})
    assert sorted(c[0] for c in calls) == ["model-a", "model-b"]
    assert legs["claims"][0]["metadata"]["claim_id"] == "c1"
    assert legs["entities"][0]["metadata"]["entity_id"] == "alpha-project"


def test_an_injected_embedder_for_one_model_is_not_used_on_another_models_table(tmp_path, calls):
    bank = _bank(tmp_path)
    _partial_switch(bank)
    mine: list = []
    idx = SqliteVecIndexer(bank, embed_fn=_embedder("model-b", mine), model_name="model-b")
    hits = idx.search_claims("python", top_k=1)
    assert [c[0] for c in calls] == ["model-a"] and not mine
    assert hits[0]["metadata"]["claim_id"] == "c2"


def test_a_page_dropped_since_the_last_sync_never_comes_back(tmp_path, calls):
    bank = _bank(tmp_path)
    SqliteVecIndexer(bank, embed_fn=_embedder("model-a", []), model_name="model-a").index_entities()
    _page(bank, "gamma-garden", "gamma garden music", status="dropped")   # after the sync
    _page(bank, "beta-project", "beta python", status="archived")
    idx = SqliteVecIndexer(bank)
    ids = [h["metadata"]["entity_id"] for h in idx.search_entities("gamma garden music", top_k=3)]
    assert "gamma-garden" not in ids
    raw = [h["metadata"]["entity_id"] for h in idx.search_entities("gamma garden", top_k=3, include_archived=True)]
    assert "gamma-garden" not in raw
    # The archived tier reads the page as it is now, not as it was synced.
    tiers = idx.search_entities("beta python alpha", top_k=3)
    assert [h["metadata"]["entity_id"] for h in tiers][-1] == "beta-project"
    assert tiers[-1]["metadata"]["status"] == "archived"


def test_recall_never_renders_or_suggests_a_dropped_page(tmp_path, calls, monkeypatch):
    bank = _bank(tmp_path)
    SqliteVecIndexer(bank, embed_fn=_embedder("model-a", []), model_name="model-a").index_entities()
    _page(bank, "gamma-garden", "gamma garden music", status="dropped")
    # The lexical and claim legs are search_service's (they read FTS meta);
    # here the semantic leg alone must not bring the page back.
    monkeypatch.setattr(mcp_tools, "_keyword_search_entities", lambda *a, **k: [])
    monkeypatch.setattr(mcp_tools, "_claim_subject_search", lambda *a, **k: [
        {"entity_id": "gamma-garden", "source": "claim", "score": 1.0}])
    ctx = mcp_tools.ToolContext(memory_path=lambda: bank, session_id="s", harness="codex")
    out = mcp_tools.recall(ctx, "gamma garden music")
    assert "gamma-garden" not in out and "gamma garden music" not in out


def test_recall_embeds_its_query_once(tmp_path, calls, monkeypatch):
    bank = _bank(tmp_path)
    (bank / "episodes").mkdir()
    markdown_parser.write(bank / "episodes" / "ep_2026-10-01_001.md",
                          {"id": "ep_2026-10-01_001", "timestamp": "2026-10-01T09:00:00+00:00"},
                          "user: we chose rust for alpha")
    idx = SqliteVecIndexer(bank, embed_fn=_embedder("model-a", []), model_name="model-a")
    idx.index_entities()
    idx.index_episodes()
    monkeypatch.setattr(mcp_tools, "_keyword_search_entities", lambda *a, **k: [])
    monkeypatch.setattr(mcp_tools, "_claim_subject_search", lambda *a, **k: [])
    ctx = mcp_tools.ToolContext(memory_path=lambda: bank, session_id="s", harness="codex")
    out = mcp_tools.recall(ctx, "alpha rust")
    assert "ep_2026-10-01_001" in out and "alpha-project" in out.lower()
    assert calls == [("model-a", ("alpha rust",))]


def test_a_table_rebuilt_at_another_width_is_never_queried_with_a_cached_vector(tmp_path, calls, monkeypatch):
    bank = _bank(tmp_path)
    SqliteVecIndexer(bank, embed_fn=_embedder("model-a", []), model_name="model-a").index_entities()
    assert SqliteVecIndexer(bank).search_entities("python", top_k=1)      # caches the 8-wide query vector

    def wide(texts, *, is_query=False):
        base = _embedder("model-a", calls)(texts, is_query=is_query)
        return np.hstack([base, base]).astype(np.float32)                  # same model id, twice the width

    monkeypatch.setattr(providers, "resolve_embed_fn_for_model", lambda mid, *a, **k: (wide, mid))
    _page(bank, "gamma-garden", "gamma garden music python")       # an edit: the sync embeds, sees the new width
    idx = SqliteVecIndexer(bank, embed_fn=wide, model_name="model-a")
    idx.index_entities()
    assert idx.last_sync["entities"]["rebuilt"] == 1 and idx.index_info("entities")["dim"] == 16
    hits = SqliteVecIndexer(bank).search_entities("python", top_k=1)
    assert hits and hits[0]["metadata"]["entity_id"] == "beta-project"
