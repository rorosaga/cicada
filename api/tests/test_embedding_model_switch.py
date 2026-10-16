"""Switching a bank's embedding model rebuilds its index; vectors of two models never mix.

A checkout that runs ``make embedding-model`` gains the small ONNX model. A FRESH bank is
built with it; a bank already built with EmbeddingGemma keeps that model until the person
picks another (Settings → Memory → Search model), and then every table is rebuilt at the new
model's width — the index is derived and disposable, so a switch costs one re-embed, never a
fact. Production resolution throughout (no injected embedder on the rebuild); only the two
models' arithmetic is faked, so nothing is downloaded.
"""
from __future__ import annotations

import json
import sqlite3

import numpy as np
import pytest

from api.config import get_settings
from api.services import embedding_models, markdown_parser, onnx_embedder, providers
from api.services.claims import Claim, write_claims
from api.services.vector_index import SqliteVecIndexer

GEMMA = "google/embeddinggemma-300m"
E5 = onnx_embedder.DEFAULT_ID


def _vectors(texts, dim):
    rows = []
    for t in texts:
        rng = np.random.default_rng(abs(hash(t)) % (2**32))
        v = rng.standard_normal(dim).astype(np.float32)
        rows.append(v / np.linalg.norm(v))
    return np.vstack(rows) if rows else np.zeros((0, dim), np.float32)


@pytest.fixture
def dev_home(tmp_path, monkeypatch):
    """A checkout's home after `make embedding-model` (manifest + placeholder files)."""
    monkeypatch.delenv("CICADA_BUNDLED_MODELS", raising=False)
    # Nothing set explicitly: the default (local) mode, so a bank keeps the model it records.
    for key in ("CICADA_EMBEDDING_MODE", "CICADA_EMBEDDING_MODEL_LOCAL", "CICADA_EMBEDDING_MODEL",
                "CICADA_EMBEDDING_MODEL_OPENROUTER"):
        monkeypatch.delenv(key, raising=False)
    home = tmp_path / "home"
    model = home / "models" / "multilingual-e5-small"
    model.mkdir(parents=True)
    (model / "model.onnx").write_bytes(b"onnx")
    (model / "tokenizer.json").write_text("{}")
    (model / onnx_embedder.MANIFEST).write_text(json.dumps(
        {"id": E5, "dimensions": 384, "pooling": "mean", "query_prefix": "query: ", "document_prefix": "passage: "}))
    monkeypatch.setenv("CICADA_HOME", str(home))
    monkeypatch.setattr(onnx_embedder.OnnxEmbedder, "__call__",
                        lambda self, texts, *, is_query=False: _vectors(texts, 384))
    providers.clear_embed_cache()
    get_settings.cache_clear()
    yield home
    get_settings.cache_clear()


def _bank(tmp_path):
    bank = tmp_path / "bank"
    (bank / "entities").mkdir(parents=True)
    (bank / "episodes").mkdir(parents=True)
    for n in range(1, 4):
        markdown_parser.write(bank / "episodes" / f"ep_2026-06-01_{n:03d}.md",
                              {"id": f"ep_2026-06-01_{n:03d}", "processed": True, "source": "mcp",
                               "timestamp": "2026-06-01T10:00:00"}, f"alpha-project planning, part {n}")
    page = bank / "entities" / "alpha-project.md"
    claims = [Claim(id="clm_alpha_0", text="alpha-project works with bob-example", subject="alpha-project",
                    predicate="related_to", object="bob-example", valid_from="2026-06-01")]
    markdown_parser.write(page, {"name": "Alpha Project", "type": "project", "status": "active",
                                 "confidence": 0.8}, write_claims("A synthetic project.", claims))
    return bank


def _widths(bank) -> dict[str, int]:
    conn = sqlite3.connect(bank / "vector_index.db")
    try:
        meta = dict(conn.execute("SELECT key, value FROM index_meta").fetchall())
    finally:
        conn.close()
    return {k: meta[k] for k in meta if k.startswith(("model:", "dim:"))}


def _index_all(idx):
    idx.index_entities(), idx.index_episodes(), idx.index_claims()


def test_a_fresh_bank_in_a_checkout_is_built_with_the_small_model(dev_home, tmp_path):
    bank = _bank(tmp_path)
    idx = SqliteVecIndexer(bank)
    _index_all(idx)
    meta = _widths(bank)
    assert {meta[f"model:{k}"] for k in ("entities", "episodes", "claims")} == {E5}
    assert {meta[f"dim:{k}"] for k in ("entities", "episodes", "claims")} == {"384"}


def test_picking_the_small_model_for_a_gemma_bank_rebuilds_every_table(dev_home, tmp_path):
    bank = _bank(tmp_path)
    gemma = SqliteVecIndexer(bank, embed_fn=lambda texts, *, is_query=False: _vectors(texts, 768), model_name=GEMMA)
    _index_all(gemma)
    assert set(_widths(bank)[f"dim:{k}"] for k in ("entities", "episodes", "claims")) == {"768"}

    # The bank keeps the model it was built with until the person picks another …
    assert embedding_models.build_model(bank, get_settings()) == GEMMA
    embedding_models.set_bank_choice(bank, E5)
    assert embedding_models.build_model(bank, get_settings()) == E5

    switched = SqliteVecIndexer(bank)
    _index_all(switched)
    meta = _widths(bank)
    for kind in ("entities", "episodes", "claims"):
        assert meta[f"model:{kind}"] == E5 and meta[f"dim:{kind}"] == "384", kind
        assert switched.last_sync[kind]["rebuilt"] == 1, f"{kind}: rebuilt, not mixed"
    # … and every query now runs in the new model's space, with results.
    assert switched.search_episodes("alpha-project", top_k=5)
    assert switched.search_entities("alpha-project", top_k=5)


def test_an_explicit_embedding_setting_moves_every_bank_and_still_rebuilds(dev_home, tmp_path, monkeypatch):
    """An explicit CICADA_EMBEDDING_* (install.sh writes CICADA_EMBEDDING_MODE=local) keeps its old meaning:
    every bank follows the configured default — here the small model — and is rebuilt, never mixed."""
    bank = _bank(tmp_path)
    _index_all(SqliteVecIndexer(bank, embed_fn=lambda texts, *, is_query=False: _vectors(texts, 768),
                                model_name=GEMMA))
    monkeypatch.setenv("CICADA_EMBEDDING_MODE", "local")
    get_settings.cache_clear()
    assert embedding_models.build_model(bank, get_settings()) == E5
    switched = SqliteVecIndexer(bank)
    _index_all(switched)
    assert {v for k, v in _widths(bank).items() if k.startswith("dim:")} == {"384"}
