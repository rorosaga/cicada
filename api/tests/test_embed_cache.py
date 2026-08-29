from __future__ import annotations

import numpy as np

from api.config import Settings
from api.services import providers


class _ST:
    instances = 0

    def __init__(self, name):
        _ST.instances += 1
        self.name = name

    def encode_query(self, texts):
        return np.zeros((len(texts), 4), dtype=np.float32)

    def encode_document(self, texts):
        return np.zeros((len(texts), 4), dtype=np.float32)


def test_cached_embed_fn_builds_model_once(monkeypatch):
    providers.clear_embed_cache()
    _ST.instances = 0
    monkeypatch.setattr(providers, "_default_sentence_transformer_factory", lambda: _ST)
    fn1, m1 = providers.cached_embed_fn_for_model("google/embeddinggemma-300m", Settings())
    fn2, m2 = providers.cached_embed_fn_for_model("google/embeddinggemma-300m", Settings())
    assert fn1 is fn2 and m1 == m2 == "google/embeddinggemma-300m"
    assert _ST.instances == 1
    assert fn1(["q"], is_query=True).shape == (1, 4)


def test_injected_factory_bypasses_cache():
    providers.clear_embed_cache()
    _ST.instances = 0
    providers.resolve_embed_fn_for_model("local-x", Settings(), sentence_transformer_factory=_ST)
    providers.resolve_embed_fn_for_model("local-x", Settings(), sentence_transformer_factory=_ST)
    assert _ST.instances == 2


def test_warm_query_embedder_never_raises(tmp_path):
    providers.clear_embed_cache()
    providers.warm_query_embedder(tmp_path)  # no index on disk -> no-op
