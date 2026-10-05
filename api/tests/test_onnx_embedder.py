"""G182 — the bundled ONNX model: found by its manifest, the default for a fresh bank
only when bundled, and the query path for a bank that recorded it."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from api.config import Settings
from api.services import onnx_embedder, providers


def _model(root: Path, name: str = "bge-small-en-v1.5", model_id: str = onnx_embedder.DEFAULT_ID) -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / "model.onnx").write_bytes(b"onnx")
    (d / "tokenizer.json").write_text("{}")
    (d / onnx_embedder.MANIFEST).write_text(json.dumps({"id": model_id, "dimensions": 384, "pooling": "cls",
                                                         "normalize": True, "query_prefix": "Q: "}))
    return d


def test_no_bundled_models_in_a_checkout(monkeypatch):
    monkeypatch.delenv("CICADA_BUNDLED_MODELS", raising=False)
    assert onnx_embedder.available() == [] and onnx_embedder.default_model() is None


def test_a_bundled_model_is_found_by_its_manifest(monkeypatch, tmp_path):
    _model(tmp_path)
    (tmp_path / "incomplete").mkdir()
    monkeypatch.setenv("CICADA_BUNDLED_MODELS", str(tmp_path))
    spec = onnx_embedder.find("baai/BGE-small-en-v1.5")
    assert spec and spec.dimensions == 384 and spec.query_prefix == "Q: "
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
