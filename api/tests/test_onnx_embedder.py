"""G182 — the bundled ONNX model: found by its manifest, the default for a fresh bank
only when bundled, and the query path for a bank that recorded it."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from api.config import Settings
from api.services import onnx_embedder, providers


def _model(root: Path, name: str = "multilingual-e5-small", model_id: str = onnx_embedder.DEFAULT_ID) -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / "model.onnx").write_bytes(b"onnx")
    (d / "tokenizer.json").write_text("{}")
    (d / onnx_embedder.MANIFEST).write_text(json.dumps({"id": model_id, "dimensions": 384, "pooling": "mean",
                                                         "normalize": True, "query_prefix": "Q: ",
                                                         "document_prefix": "D: "}))
    return d


def test_no_bundled_models_in_a_checkout(monkeypatch):
    monkeypatch.delenv("CICADA_BUNDLED_MODELS", raising=False)
    assert onnx_embedder.available() == [] and onnx_embedder.default_model() is None


def test_a_bundled_model_is_found_by_its_manifest(monkeypatch, tmp_path):
    _model(tmp_path)
    (tmp_path / "incomplete").mkdir()
    monkeypatch.setenv("CICADA_BUNDLED_MODELS", str(tmp_path))
    spec = onnx_embedder.find("INTFLOAT/Multilingual-E5-small")
    assert spec and spec.dimensions == 384 and spec.query_prefix == "Q: " and spec.document_prefix == "D: "
    assert [s.id for s in onnx_embedder.available()] == [onnx_embedder.DEFAULT_ID]


def test_a_fresh_bank_uses_the_bundled_model_unless_one_is_named(monkeypatch, tmp_path):
    monkeypatch.delenv("CICADA_EMBEDDING_MODEL_LOCAL", raising=False)
    monkeypatch.setenv("CICADA_EMBEDDING_MODE", "local")
    monkeypatch.delenv("CICADA_BUNDLED_MODELS", raising=False)
    assert Settings().resolved_embedding_model == "google/embeddinggemma-300m", "a checkout is unchanged"
    _model(tmp_path)
    monkeypatch.setenv("CICADA_BUNDLED_MODELS", str(tmp_path))
    assert Settings().resolved_embedding_model == onnx_embedder.DEFAULT_ID
    monkeypatch.setenv("CICADA_EMBEDDING_MODEL_LOCAL", "google/embeddinggemma-300m")
    assert Settings().resolved_embedding_model == "google/embeddinggemma-300m", "an explicit choice wins"


def test_providers_route_a_bundled_id_to_onnx(monkeypatch, tmp_path):
    _model(tmp_path)
    monkeypatch.setenv("CICADA_BUNDLED_MODELS", str(tmp_path))
    fn, mid = providers.resolve_embed_fn_for_model(onnx_embedder.DEFAULT_ID, Settings(), _skip_cache=True)
    assert isinstance(fn, onnx_embedder.OnnxEmbedder) and mid == onnx_embedder.DEFAULT_ID


class _Enc:
    def __init__(self, n):
        self.ids, self.attention_mask, self.type_ids = [1] * n, [1] * n, [0] * n


def test_pooling_normalises_and_prefixes_queries(tmp_path):
    spec = onnx_embedder.ModelSpec(id="m", path=tmp_path, dimensions=2, pooling="cls", normalize=True,
                                   max_tokens=8, query_prefix="Q: ")
    emb = onnx_embedder.OnnxEmbedder(spec)
    seen = []

    class Tok:
        def encode_batch(self, batch):
            seen.extend(batch)
            return [_Enc(3) for _ in batch]

    class Sess:
        def run(self, _out, feed):
            assert set(feed) == {"input_ids", "attention_mask"}
            b = feed["input_ids"].shape[0]
            return [np.tile(np.array([[[3.0, 4.0], [0.0, 0.0], [0.0, 0.0]]], dtype=np.float32), (b, 1, 1))]

    emb._tokenizer, emb._session, emb._inputs = Tok(), Sess(), {"input_ids", "attention_mask"}
    out = emb(["a", "b"], is_query=True)
    assert seen == ["Q: a", "Q: b"]
    assert out.shape == (2, 2) and np.allclose(out[0], [0.6, 0.8])
    assert emb([], is_query=False).shape == (0, 2)


def test_documents_carry_their_own_instruction_and_mean_pooling_ignores_padding(tmp_path):
    """e5 (the bundled multilingual model, owner 2026-10-06) reads "query: " / "passage: " and mean-pools."""
    spec = onnx_embedder.ModelSpec(id="m", path=tmp_path, dimensions=2, pooling="mean", normalize=False,
                                   max_tokens=8, query_prefix="query: ", document_prefix="passage: ")
    emb = onnx_embedder.OnnxEmbedder(spec)
    seen = []

    class Enc:
        ids, attention_mask, type_ids = [1, 1, 0], [1, 1, 0], [0, 0, 0]

    class Tok:
        def encode_batch(self, batch):
            seen.extend(batch)
            return [Enc() for _ in batch]

    class Sess:
        def run(self, _out, feed):
            b = feed["input_ids"].shape[0]
            return [np.tile(np.array([[[2.0, 4.0], [4.0, 0.0], [100.0, 100.0]]], dtype=np.float32), (b, 1, 1))]

    emb._tokenizer, emb._session, emb._inputs = Tok(), Sess(), {"input_ids", "attention_mask"}
    out = emb(["a note"])
    assert seen == ["passage: a note"]
    assert np.allclose(out[0], [3.0, 2.0]), "the padded position never enters the mean"
    emb(["a question"], is_query=True)
    assert seen[-1] == "query: a question"


def test_the_cached_query_embedder_never_imports_sentence_transformers(monkeypatch, tmp_path):
    """G182 phase 3 fix: `cached_embed_fn_for_model` always passes a factory, and a release app has no torch."""
    import sys

    _model(tmp_path)
    monkeypatch.setenv("CICADA_BUNDLED_MODELS", str(tmp_path))
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)  # any import attempt raises
    providers.clear_embed_cache()
    try:
        fn, mid = providers.cached_embed_fn_for_model(onnx_embedder.DEFAULT_ID, Settings())
        assert isinstance(fn, onnx_embedder.OnnxEmbedder) and mid == onnx_embedder.DEFAULT_ID
    finally:
        providers.clear_embed_cache()


# --- A developer checkout runs the same small model (fix/dev-embeddings) ------------------------------------

def test_a_checkout_finds_the_model_fetched_into_its_home(monkeypatch, tmp_path):
    """`make embedding-model` puts the release's pinned files under $CICADA_HOME/models; with no
    CICADA_BUNDLED_MODELS (a checkout), that folder is where the model is found."""
    monkeypatch.delenv("CICADA_BUNDLED_MODELS", raising=False)
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    assert onnx_embedder.available() == [], "nothing fetched yet: nothing found"
    _model(tmp_path / "home" / "models")
    (tmp_path / "home" / "models" / "google--embeddinggemma-300m").mkdir()  # the larger model's download: no manifest
    assert [s.id for s in onnx_embedder.available()] == [onnx_embedder.DEFAULT_ID]
    assert onnx_embedder.default_model().path == tmp_path / "home" / "models" / "multilingual-e5-small"


def test_a_release_looks_only_where_its_launchers_point(monkeypatch, tmp_path):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    _model(tmp_path / "home" / "models")
    monkeypatch.setenv("CICADA_BUNDLED_MODELS", str(tmp_path / "app-models"))
    assert onnx_embedder.available() == [], "the app's own folder, never a copy under the home"


def test_a_checkout_with_the_model_builds_fresh_banks_with_it(monkeypatch, tmp_path):
    monkeypatch.delenv("CICADA_BUNDLED_MODELS", raising=False)
    monkeypatch.delenv("CICADA_EMBEDDING_MODEL_LOCAL", raising=False)
    monkeypatch.setenv("CICADA_EMBEDDING_MODE", "local")
    monkeypatch.setenv("CICADA_HOME", str(tmp_path))
    _model(tmp_path / "models")
    assert Settings().resolved_embedding_model == onnx_embedder.DEFAULT_ID


def test_texts_are_run_one_at_a_time_so_padding_never_inflates_memory(tmp_path):
    """Measured on an M4 Pro, 2,500 synthetic pages with e5-small: one text per run embeds as fast as 32 per run
    (63.8 vs 63.7 pages/s) at half the peak memory (785 vs 1,737 MB) — a batch pads every text to its longest."""
    spec = onnx_embedder.ModelSpec(id="m", path=tmp_path, dimensions=2, pooling="cls", normalize=True,
                                   max_tokens=8, query_prefix="")
    emb = onnx_embedder.OnnxEmbedder(spec)
    sizes = []

    class Tok:
        def encode_batch(self, batch):
            sizes.append(len(batch))
            return [_Enc(3) for _ in batch]

    class Sess:
        def run(self, _out, feed):
            return [np.ones((feed["input_ids"].shape[0], 3, 2), dtype=np.float32)]

    emb._tokenizer, emb._session = Tok(), Sess()
    assert emb(["a", "b", "c"]).shape == (3, 2)
    assert sizes == [1, 1, 1]
