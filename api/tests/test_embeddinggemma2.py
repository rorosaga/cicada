"""EmbeddingGemma 2 on the Neural Engine (owner 2026-10-09): the registry, the runtime, the download, the
model rules and the background re-embed. Core ML itself is faked (a pooling stand-in with the real input
shapes), so nothing is downloaded and the suite runs on any Mac; the real model's numbers are in the PR.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from api.config import Settings, get_settings
from api.services import (coreml_embedder, embedding_health, embedding_models as em, markdown_parser, model_fetch,
                          onnx_embedder, providers)
from api.services.claims import Claim, write_claims
from api.services.vector_index import IndexSyncStopped, SqliteVecIndexer

GEMMA = onnx_embedder.PREFERRED_ID
E5 = onnx_embedder.DEFAULT_ID
WORDS = ["alpha", "project", "bob", "example", "planning", "robot", "lidar", "drift", "pan", "receta", "sourdough"]


# --------------------------------------------------------------------------- fixtures

def _tokenizer_json(path: Path) -> None:
    from tokenizers import Tokenizer, models, pre_tokenizers

    vocab = {"<pad>": 0, "<eos>": 1, "<bos>": 2, "<unk>": 3}
    for w in WORDS + ["title:", "none", "|", "text:", "task:", "search", "result", "query:"]:
        vocab.setdefault(w, len(vocab))
    tok = Tokenizer(models.WordLevel(vocab, unk_token="<unk>"))
    tok.pre_tokenizer = pre_tokenizers.WhitespaceSplit()
    tok.save(str(path))


def _gemma_folder(models: Path, *, widths=(768, 512, 256, 128)) -> Path:
    d = models / "embeddinggemma-2"
    (d / coreml_embedder.COMPILED).mkdir(parents=True)
    _tokenizer_json(d / "tokenizer.json")
    rng = np.random.default_rng(0)
    table = rng.standard_normal((64, coreml_embedder.HIDDEN)).astype(np.float32) * 0.05
    (table.view(np.uint32) >> 16).astype(np.uint16).tofile(d / coreml_embedder.TABLE)
    (d / "config.json").write_text(json.dumps({"bos_token_id": 2, "eos_token_id": 1, "pad_token_id": 0}))
    (d / onnx_embedder.MANIFEST).write_text(json.dumps({
        "id": onnx_embedder.PREFERRED_BASE, "runtime": "coreml", "dimensions": 768, "widths": list(widths),
        "max_tokens": 512, "query_prefix": "task: search result | query: ", "document_prefix": "title: none | text: ",
        "revision": "r1"}))
    return d


def _e5_folder(models: Path) -> Path:
    d = models / "multilingual-e5-small"
    d.mkdir(parents=True)
    (d / "model.onnx").write_bytes(b"onnx")
    (d / "tokenizer.json").write_text("{}")
    (d / onnx_embedder.MANIFEST).write_text(json.dumps({"id": E5, "dimensions": 384, "pooling": "mean"}))
    return d


class _FakeModel:
    """Core ML's stand-in: mean-pools the token rows it is given (the real inputs, the real shapes)."""
    loads: list[str] = []

    def __init__(self, path, compute_units=None, function_name=""):
        self.name = function_name
        _FakeModel.loads.append(function_name)

    def predict(self, feed):
        emb = np.asarray(feed["inputs_embeds"], dtype=np.float32)[0]
        if self.name == "pack_256":
            pooled = np.asarray(feed["pool"], dtype=np.float32) @ emb
        else:
            mask = np.asarray(feed["attention_mask"], dtype=np.float32)[0]
            pooled = (mask[:, None] * emb).sum(0, keepdims=True) / mask.sum()
        return {"embedding": np.concatenate([pooled, pooled[:, :256]], axis=1)}


def _fake_ct():
    return SimpleNamespace(ComputeUnit=SimpleNamespace(CPU_AND_NE="ane"),
                           models=SimpleNamespace(CompiledMLModel=_FakeModel))


@pytest.fixture
def mac15(tmp_path, monkeypatch):
    """A Mac that runs the model, with nothing set explicitly; the home holds what the test puts there."""
    for k in ("CICADA_EMBEDDING_MODE", "CICADA_EMBEDDING_MODEL", "CICADA_EMBEDDING_MODEL_LOCAL",
              "CICADA_BUNDLED_MODELS", "CICADA_DISTRIBUTION", "CICADA_COREML_DISABLED"):
        monkeypatch.delenv(k, raising=False)
    home = tmp_path / "home"
    monkeypatch.setenv("CICADA_HOME", str(home))
    monkeypatch.setattr(coreml_embedder, "supported", lambda: True)
    monkeypatch.setattr(coreml_embedder, "import_coremltools", _fake_ct)
    _FakeModel.loads = []
    providers.clear_embed_cache()
    get_settings.cache_clear()
    yield home
    providers.clear_embed_cache()
    get_settings.cache_clear()


def _vectors(texts, dim, salt=""):
    rows = []
    for t in texts:
        h = int(hashlib.sha256((salt + t).encode()).hexdigest()[:8], 16)
        v = np.random.default_rng(h).standard_normal(dim).astype(np.float32)
        rows.append(v / np.linalg.norm(v))
    return np.vstack(rows) if rows else np.zeros((0, dim), np.float32)


@pytest.fixture
def two_models(mac15, monkeypatch):
    """Both on-device models present, their arithmetic faked (and counted)."""
    _e5_folder(mac15 / "models")
    _gemma_folder(mac15 / "models")
    calls = {"e5": 0, "gemma": 0}

    def e5(self, texts, *, is_query=False):
        calls["e5"] += len(texts)
        return _vectors(texts, 384, "e5")

    def gemma(self, texts, *, is_query=False):
        calls["gemma"] += len(texts)
        return _vectors(texts, self.width, "g")

    monkeypatch.setattr(onnx_embedder.OnnxEmbedder, "__call__", e5)
    monkeypatch.setattr(coreml_embedder.CoreMLEmbedder, "__call__", gemma)
    return calls


def _bank(tmp_path, n_pages=3) -> Path:
    bank = tmp_path / "bank"
    (bank / "entities").mkdir(parents=True)
    (bank / "episodes").mkdir(parents=True)
    for n in range(1, 4):
        markdown_parser.write(bank / "episodes" / f"ep_2026-06-01_{n:03d}.md",
                              {"id": f"ep_2026-06-01_{n:03d}", "processed": True, "source": "mcp",
                               "timestamp": "2026-06-01T10:00:00"}, f"alpha-project planning, part {n}")
    for i in range(n_pages):
        claims = [Claim(id=f"clm_{i}", text=f"alpha-project {i} works with bob-example", subject="alpha-project",
                        predicate="related_to", object="bob-example", valid_from="2026-06-01")]
        markdown_parser.write(bank / "entities" / f"page-{i}.md", {"name": f"Page {i}", "type": "project",
                                                                    "status": "active", "confidence": 0.8},
                              write_claims(f"A synthetic page {i}.", claims))
    return bank


def _meta(bank) -> dict:
    conn = sqlite3.connect(bank / "vector_index.db")
    try:
        return dict(conn.execute("SELECT key, value FROM index_meta").fetchall())
    finally:
        conn.close()


def _build_with(bank, model, dim):
    idx = SqliteVecIndexer(bank, embed_fn=lambda texts, *, is_query=False: _vectors(texts, dim, model),
                           model_name=model)
    idx.index_entities(), idx.index_claims(), idx.index_episodes()


# --------------------------------------------------------------------------- the registry

def test_a_downloaded_folder_is_found_with_its_width_in_the_id(mac15):
    _gemma_folder(mac15 / "models")
    spec = onnx_embedder.find(GEMMA)
    assert spec and spec.runtime == "coreml" and spec.id == GEMMA and spec.dimensions == 768
    narrow = onnx_embedder.find("google/embeddinggemma-2:256")
    assert narrow and narrow.dimensions == 256 and narrow.id == "google/embeddinggemma-2:256"
    assert onnx_embedder.find("google/embeddinggemma-2:300") is None, "only a width the manifest lists"
    assert isinstance(onnx_embedder.embedder_for(spec), coreml_embedder.CoreMLEmbedder)
    assert onnx_embedder.default_model().id == GEMMA, "a fresh bank is built with it where it runs"
    assert Settings().resolved_embedding_model == GEMMA


def test_where_it_cannot_run_it_is_invisible_and_the_small_model_answers(mac15, monkeypatch):
    _e5_folder(mac15 / "models")
    _gemma_folder(mac15 / "models")
    monkeypatch.setattr(coreml_embedder, "supported", lambda: False)   # macOS 14, or no Core ML bindings
    assert onnx_embedder.find(GEMMA) is None and not em.is_available(GEMMA)
    assert [s.id for s in onnx_embedder.installed()] == [GEMMA, E5], "still on disk"
    assert Settings().resolved_embedding_model == E5
    with pytest.raises(coreml_embedder.EmbedderUnavailable):
        providers.resolve_embed_fn_for_model(GEMMA, Settings(), _skip_cache=True)
    try:
        providers.resolve_embed_fn_for_model(GEMMA, Settings(), _skip_cache=True)
    except coreml_embedder.EmbedderUnavailable as exc:
        assert embedding_health.classify(exc) == "model_missing"


def test_an_incomplete_folder_never_counts(mac15):
    d = _gemma_folder(mac15 / "models")
    (d / coreml_embedder.TABLE).unlink()
    assert onnx_embedder.find(GEMMA) is None


def test_a_release_reads_downloads_from_the_home_but_onnx_only_from_its_bundle(mac15, monkeypatch, tmp_path):
    _gemma_folder(mac15 / "models")
    _e5_folder(mac15 / "models")
    bundle = tmp_path / "app-models"
    bundle.mkdir()
    monkeypatch.setenv("CICADA_BUNDLED_MODELS", str(bundle))
    assert [s.id for s in onnx_embedder.available()] == [GEMMA]
    _e5_folder(bundle)
    assert [s.id for s in onnx_embedder.available()] == [E5, GEMMA]
    assert onnx_embedder.find(E5).path == bundle / "multilingual-e5-small"


def test_coreml_is_imported_without_its_converter_frameworks():
    import sys

    sentinel = object()
    before = sys.modules.get("torch", sentinel)
    try:
        coreml_embedder.import_coremltools()
    except ImportError:
        pytest.skip("coremltools is not installed in this environment")
    assert sys.modules.get("torch", sentinel) is before, "torch is never left hidden or half-imported"


# --------------------------------------------------------------------------- the runtime

def test_documents_pack_like_singles_and_widths_are_renormalised(mac15):
    d = _gemma_folder(mac15 / "models")
    spec = onnx_embedder.find(GEMMA)
    emb = coreml_embedder.CoreMLEmbedder(spec)
    texts = [" ".join(WORDS[i:i + 3]) for i in range(6)] + ["robot " * 300]   # six short texts, one long
    packed = emb(texts)
    assert packed.shape == (7, 768) and np.allclose(np.linalg.norm(packed, axis=1), 1, atol=1e-5)
    assert "pack_256" in emb.loaded() and "embed_512" in emb.loaded()
    singles = np.vstack([emb([t]) for t in texts])
    cos = (packed * singles).sum(1)
    assert cos.min() > 0.999, "the pack's offsets, masks and pooling match one text at a time"
    narrow = coreml_embedder.CoreMLEmbedder(onnx_embedder.find("google/embeddinggemma-2:256"))
    v = narrow(texts[:2])
    assert v.shape == (2, 256) and np.allclose(np.linalg.norm(v, axis=1), 1, atol=1e-5)
    full = packed[:2, :256]
    assert np.allclose(v, full / np.linalg.norm(full, axis=1, keepdims=True), atol=1e-4), "Matryoshka: a prefix"
    assert d.is_dir()


def test_a_query_loads_only_the_function_its_length_needs(mac15):
    _gemma_folder(mac15 / "models")
    emb = coreml_embedder.CoreMLEmbedder(onnx_embedder.find(GEMMA))
    v = emb(["alpha project"], is_query=True)
    assert v.shape == (1, 768) and emb.loaded() == ("embed_32",)
    emb.warm(query_only=True)
    assert set(emb.loaded()) == set(coreml_embedder.QUERY_FUNCTIONS)


def test_a_query_never_waits_out_a_cold_compile(mac15, monkeypatch):
    _gemma_folder(mac15 / "models")
    release = threading.Event()

    class Slow(_FakeModel):
        def __init__(self, *a, **kw):
            release.wait(5)
            super().__init__(*a, **kw)

    monkeypatch.setattr(coreml_embedder, "import_coremltools",
                        lambda: SimpleNamespace(ComputeUnit=SimpleNamespace(CPU_AND_NE="ane"),
                                                models=SimpleNamespace(CompiledMLModel=Slow)))
    monkeypatch.setattr(coreml_embedder, "QUERY_LOAD_WAIT_S", 0.05)
    emb = coreml_embedder.CoreMLEmbedder(onnx_embedder.find(GEMMA))
    with pytest.raises(coreml_embedder.EmbedderWarming):
        emb(["alpha"], is_query=True)
    assert embedding_health.classify(coreml_embedder.EmbedderWarming("x")) is None, "warming is not a failure"
    release.set()
    deadline = time.monotonic() + 5
    while "embed_32" not in emb.loaded() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert emb(["alpha"], is_query=True).shape == (1, 768), "the load finished in the background"


def test_the_recall_hook_never_loads_a_function_inside_its_budget(mac15):
    _gemma_folder(mac15 / "models")
    fn, mid = providers.cached_embed_fn_for_model(GEMMA)
    hook = providers.warm_local_embed_fn(GEMMA)
    started = time.monotonic()
    with pytest.raises(coreml_embedder.EmbedderWarming):
        hook(["alpha project"], is_query=True)
    assert time.monotonic() - started < 0.5, "it answered 'not yet' at once"
    assert _wait(lambda: "embed_32" in fn.loaded()), "the load it asked for runs in the background"
    assert hook(["alpha project"], is_query=True).shape == (1, 768)


def test_a_load_failure_is_one_kind_and_is_retried(mac15, monkeypatch):
    _gemma_folder(mac15 / "models")
    fail = {"on": True}

    class Broken(_FakeModel):
        def __init__(self, *a, **kw):
            if fail["on"]:
                raise RuntimeError("Core ML said no")
            super().__init__(*a, **kw)

    monkeypatch.setattr(coreml_embedder, "import_coremltools",
                        lambda: SimpleNamespace(ComputeUnit=SimpleNamespace(CPU_AND_NE="ane"),
                                                models=SimpleNamespace(CompiledMLModel=Broken)))
    emb = coreml_embedder.CoreMLEmbedder(onnx_embedder.find(GEMMA))
    with pytest.raises(coreml_embedder.EmbedderUnavailable) as caught:
        emb(["alpha"])
    assert embedding_health.classify(caught.value) == "model_missing"
    fail["on"] = False
    assert emb(["alpha"]).shape == (1, 768)


# --------------------------------------------------------------------------- which model a bank is built with

def test_cicadas_old_defaults_move_to_it_and_a_choice_or_setting_stays(two_models, tmp_path, monkeypatch):
    bank = _bank(tmp_path)
    s = Settings()
    _build_with(bank, E5, 384)
    assert em.build_model(bank, s) == GEMMA, "the small model was Cicada's default, not the person's"
    em.set_bank_choice(bank, E5)
    assert em.build_model(bank, s) == E5, "the person's choice is kept"
    em.set_bank_choice(bank, None)
    monkeypatch.setattr(em, "recorded_model", lambda b: em.LARGE_ID)
    monkeypatch.setattr(em, "sentence_transformers_available", lambda: True)
    monkeypatch.setattr(em, "_in_hf_cache", lambda mid: True)
    assert em.build_model(bank, s) == GEMMA, "a checkout's old default too"
    monkeypatch.setattr(em, "recorded_model", lambda b: "text-embedding-3-small")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    assert em.build_model(bank, s) == "text-embedding-3-small", "a model nobody defaulted to is kept"
    monkeypatch.setenv("CICADA_EMBEDDING_MODEL_LOCAL", E5)
    monkeypatch.setattr(em, "recorded_model", lambda b: E5)
    assert em.build_model(bank, Settings()) == E5, "an explicit setting keeps its meaning"


def test_a_gemma_bank_on_a_mac_without_it_keeps_its_vectors(two_models, tmp_path, monkeypatch):
    bank = _bank(tmp_path)
    _build_with(bank, GEMMA, 768)
    monkeypatch.setattr(coreml_embedder, "supported", lambda: False)
    assert em.build_model(bank, Settings()) == GEMMA, "never re-embedded behind the person's back"
    assert em.pending_switch(bank, Settings()) is None, "nothing to re-embed with"
    hits = SqliteVecIndexer(bank).search_entities("alpha")
    assert hits == [], "its vector legs are empty — search answers on words"


# --------------------------------------------------------------------------- Sleep defers, the job switches

def test_sleep_keeps_each_tables_model_and_leaves_the_switch_to_the_job(two_models, tmp_path, monkeypatch):
    from api.services import sleep_cycle

    monkeypatch.setenv("CICADA_BACKGROUND_REINDEX", "on")
    bank = _bank(tmp_path)
    _build_with(bank, E5, 384)
    markdown_parser.write(bank / "entities" / "page-new.md", {"name": "New", "type": "concept"}, "A new page.")
    two_models.update(e5=0, gemma=0)
    assert sleep_cycle._sync_vector_indexes(bank) == []
    meta = _meta(bank)
    assert {meta[f"model:{k}"] for k in ("entities", "claims", "episodes")} == {E5}
    assert two_models == {"e5": 1, "gemma": 0}, "only the new page, with the table's own model"
    assert em.pending_switch(bank, Settings()) == (GEMMA, ["entities", "claims", "episodes"])


def test_with_the_job_off_sleep_switches_as_before(two_models, tmp_path):
    from api.services import sleep_cycle

    bank = _bank(tmp_path)
    _build_with(bank, E5, 384)
    sleep_cycle._sync_vector_indexes(bank)
    meta = _meta(bank)
    assert {meta[f"model:{k}"] for k in ("entities", "claims", "episodes")} == {GEMMA}
    assert {meta[f"dim:{k}"] for k in ("entities", "claims", "episodes")} == {"768"}


def _wait(predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.01)
    return predicate()


def test_the_job_re_embeds_every_table_and_recall_answers_throughout(two_models, tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_BACKGROUND_REINDEX", "on")
    bank = _bank(tmp_path, n_pages=5)
    _build_with(bank, E5, 384)
    gate = threading.Event()
    seen: list[dict] = []
    real = coreml_embedder.CoreMLEmbedder.__call__

    def slow_gemma(self, texts, *, is_query=False):
        if not is_query:
            gate.wait(5)
        return real(self, texts, is_query=is_query)

    monkeypatch.setattr(coreml_embedder.CoreMLEmbedder, "__call__", slow_gemma)
    em.REINDEX._set(state="idle")
    assert em.start_reindex_if_needed(bank, Settings())
    assert em.status(bank, Settings())["reindex"]["state"] == "running"
    # Mid-embed: every leg still answers, from the old tables and the old model they record.
    out = SqliteVecIndexer(bank).search_kinds("alpha project", {"entities": 3, "claims": 3, "episodes": 2})
    assert all(out.values())
    seen.append(SqliteVecIndexer(bank).table_models())
    gate.set()
    assert _wait(lambda: em.REINDEX.snapshot()["state"] == "done")
    meta = _meta(bank)
    assert {meta[f"model:{k}"] for k in ("entities", "claims", "episodes")} == {GEMMA}
    assert {meta[f"dim:{k}"] for k in ("entities", "claims", "episodes")} == {"768"}
    assert seen[0] == {"entities": E5, "claims": E5, "episodes": E5}
    out = SqliteVecIndexer(bank).search_kinds("alpha project", {"entities": 3, "claims": 3, "episodes": 2})
    assert all(out.values()), "and after, with the new model"
    assert em.status(bank, Settings())["reindex"] == {"state": "done", "model": GEMMA, "done": 3, "total": 3,
                                                       "error": ""}
    assert em.start_reindex_if_needed(bank, Settings()) is False, "nothing left to do"


def test_the_job_never_starts_during_sleep_and_gives_way_when_it_starts(two_models, tmp_path, monkeypatch):
    from api.services import sleep_cycle

    monkeypatch.setenv("CICADA_BACKGROUND_REINDEX", "on")
    bank = _bank(tmp_path, n_pages=80)        # more than one stoppable chunk of claims and pages
    _build_with(bank, E5, 384)
    before = _meta(bank)
    state = sleep_cycle.get_sleep_state()
    monkeypatch.setattr(state, "status", "running")
    em.REINDEX._set(state="idle")
    assert em.start_reindex_if_needed(bank, Settings()) is False
    assert em.REINDEX.snapshot()["state"] == "waiting"
    monkeypatch.setattr(state, "status", "idle")
    calls = {"n": 0}
    real = coreml_embedder.CoreMLEmbedder.__call__

    def sleep_starts_after_one_chunk(self, texts, *, is_query=False):
        calls["n"] += 1
        if calls["n"] == 1:
            state.status = "running"
        return real(self, texts, is_query=is_query)

    monkeypatch.setattr(coreml_embedder.CoreMLEmbedder, "__call__", sleep_starts_after_one_chunk)
    assert em.start_reindex_if_needed(bank, Settings())
    assert _wait(lambda: em.REINDEX.snapshot()["state"] == "waiting")
    assert _meta(bank) == before, "it gave way before writing: every table as it was"
    state.status = "idle"


def test_a_kind_with_nothing_left_drops_its_old_model_table(two_models, tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_BACKGROUND_REINDEX", "on")
    bank = _bank(tmp_path)
    _build_with(bank, E5, 384)
    for page in (bank / "entities").glob("*.md"):   # every claim gone: nothing left to index as claims
        fm = markdown_parser.parse(page).frontmatter
        markdown_parser.write(page, fm, "A page with no claims.")
    em.REINDEX._set(state="idle")
    assert em.start_reindex_if_needed(bank, Settings())
    assert _wait(lambda: em.REINDEX.snapshot()["state"] == "done")
    assert "claims" not in SqliteVecIndexer(bank).table_models()
    assert em.pending_switch(bank, Settings()) is None, "nothing left that reads as a switch to do"


def test_a_stoppable_sync_writes_nothing(two_models, tmp_path):
    bank = _bank(tmp_path)
    _build_with(bank, E5, 384)
    before = _meta(bank)
    idx = SqliteVecIndexer(bank, embed_fn=lambda texts, *, is_query=False: _vectors(texts, 768),
                           model_name=GEMMA, should_stop=lambda: True)
    with pytest.raises(IndexSyncStopped):
        idx.index_entities()
    assert _meta(bank) == before


def test_a_failed_rebuild_leaves_the_old_table_readable(two_models, tmp_path, monkeypatch):
    import sqlite_vec

    bank = _bank(tmp_path)
    _build_with(bank, E5, 384)
    idx = SqliteVecIndexer(bank, embed_fn=lambda texts, *, is_query=False: _vectors(texts, 768), model_name=GEMMA)
    real = sqlite_vec.serialize_float32
    count = {"n": 0}

    def fail_on_second(v):
        count["n"] += 1
        if count["n"] == 2:
            raise RuntimeError("disk full")
        return real(v)

    monkeypatch.setattr(sqlite_vec, "serialize_float32", fail_on_second)
    with pytest.raises(RuntimeError):
        idx.index_entities()
    monkeypatch.setattr(sqlite_vec, "serialize_float32", real)
    assert _meta(bank)["model:entities"] == E5
    conn = sqlite3.connect(bank / "vector_index.db")
    try:
        assert conn.execute("SELECT count(*) FROM meta_entities").fetchone()[0] == 3, "the DROP rolled back too"
    finally:
        conn.close()
    assert SqliteVecIndexer(bank).search_entities("alpha"), "and it still answers"


def test_an_empty_pending_store_leaves_no_table(two_models, tmp_path):
    from api.services.pending_store import PendingEntity

    bank = _bank(tmp_path)
    idx = SqliteVecIndexer(bank, embed_fn=lambda texts, *, is_query=False: _vectors(texts, 384), model_name=E5)
    idx.index_pending_entity(PendingEntity(name="bob-example", type="person", description="someone",
                                           source_episode="ep_2026-06-01_001", confidence=0.5, tags=[],
                                           history_entries=[]))
    idx.rebuild_pending_index()
    assert "pending" in idx.table_models()
    idx.promote_from_pending("bob-example")
    assert "pending" not in idx.table_models(), "a promoted name is no longer searchable as pending"


# --------------------------------------------------------------------------- the download

def _fake_pins(tmp_path, monkeypatch, files: dict[str, bytes]) -> dict:
    pins = {"id": onnx_embedder.PREFERRED_BASE, "dir_name": "embeddinggemma-2", "repo": "example/repo",
            "revision": "abc123", "base_model": "example/base", "license": "Apache-2.0", "dimensions": 768,
            "widths": [768, 512, 256, 128], "max_tokens": 512,
            "files": [{"path": p, "size": len(b), "sha256": hashlib.sha256(b).hexdigest()} for p, b in files.items()]}
    path = tmp_path / "pins.json"
    path.write_text(json.dumps(pins))
    monkeypatch.setattr(model_fetch, "PINS", path)
    return pins


class _Client:
    def __init__(self, files: dict[str, bytes]):
        self.files, self.urls = files, []

    def stream(self, method, url):
        self.urls.append(url)
        body = self.files[url.split("/resolve/abc123/", 1)[1]]
        client = self

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def raise_for_status(self):
                return None

            def iter_bytes(self, n):
                for i in range(0, len(body), 7):
                    yield body[i:i + 7]

        assert client is self
        return _Resp()


def _payload(tmp_path) -> dict[str, bytes]:
    src = _gemma_folder(tmp_path / "src")
    cfg = json.dumps({"bos_token_id": 2, "eos_token_id": 1, "pad_token_id": 0,
                      "prompts": {"search_query": "task: search result | query: ",
                                  "document": "title: none | text: "}}).encode()
    return {"config.json": cfg, "README.md": b"card", "tokenizer.json": (src / "tokenizer.json").read_bytes(),
            "embeddings.bf16": (src / coreml_embedder.TABLE).read_bytes(),
            "EmbeddingGemma2Text.mlpackage/Manifest.json": b"{}",
            "EmbeddingGemma2Text.mlpackage/Data/com.apple.CoreML/model.mlmodel": b"mil"}


def _fake_compile(stage: Path) -> None:
    import shutil

    (stage / coreml_embedder.COMPILED).mkdir()
    shutil.rmtree(stage / coreml_embedder.PACKAGE)


def test_the_download_verifies_compiles_and_swaps_in_whole(mac15, tmp_path, monkeypatch):
    files = _payload(tmp_path)
    _fake_pins(tmp_path, monkeypatch, files)
    client = _Client(files)
    phases = []
    out = model_fetch.install(mac15 / "models", client=client, compile_fn=_fake_compile,
                              progress=lambda phase, done, total: phases.append(phase))
    assert out == mac15 / "models" / "embeddinggemma-2"
    assert all(u.startswith("https://huggingface.co/example/repo/resolve/abc123/") for u in client.urls)
    meta = json.loads((out / onnx_embedder.MANIFEST).read_text())
    assert meta["runtime"] == "coreml" and meta["revision"] == "abc123" and meta["widths"] == [768, 512, 256, 128]
    assert meta["query_prefix"] == "task: search result | query: " and meta["document_prefix"] == "title: none | text: "
    assert "Prohibited Use Policy" in (out / "NOTICE.txt").read_text()
    assert not (out / coreml_embedder.PACKAGE).exists(), "the runtime reads the compiled model only"
    assert not any(p.name.startswith(".") for p in (mac15 / "models").iterdir()), "no staging left behind"
    assert {"download", "prepare", "warm"} <= set(phases)
    assert onnx_embedder.find(GEMMA).path == out
    assert set(_FakeModel.loads) >= {"embed_32", "embed_512", "pack_256"}, "warmed from its final path"
    again = _Client(files)
    model_fetch.install(mac15 / "models", client=again, compile_fn=_fake_compile)
    assert again.urls == [], "a folder at the pinned revision is never fetched again"


def test_a_checksum_mismatch_installs_nothing(mac15, tmp_path, monkeypatch):
    files = _payload(tmp_path)
    _fake_pins(tmp_path, monkeypatch, files)
    tampered = dict(files, **{"embeddings.bf16": files["embeddings.bf16"][:-1] + b"\x00"})
    with pytest.raises(model_fetch.FetchError):
        model_fetch.install(mac15 / "models", client=_Client(tampered), compile_fn=_fake_compile)
    assert not (mac15 / "models").exists() or not any((mac15 / "models").iterdir())


def test_the_real_pins_name_only_the_text_encoder_at_one_revision():
    pins = model_fetch.pins()
    assert len(pins["revision"]) == 40 and pins["dir_name"] == "embeddinggemma-2"
    paths = [f["path"] for f in pins["files"]]
    assert not any("Audio" in p or "Vision" in p or "position_embeddings" in p for p in paths)
    assert all(len(f["sha256"]) == 64 and int(f["size"]) > 0 for f in pins["files"])
    assert 550e6 < model_fetch.total_bytes(pins) < 620e6
    assert f"{pins['id']}:{pins['dimensions']}" == GEMMA


# --------------------------------------------------------------------------- the API

def test_settings_offers_the_download_without_a_token(two_models, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from api import config, main

    import shutil

    bank = _bank(tmp_path)
    shutil.rmtree(tmp_path / "home" / "models" / "embeddinggemma-2")   # this Mac runs it; not downloaded yet
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    config.get_settings.cache_clear()
    started = []
    monkeypatch.setattr(em, "start_download", lambda b, s: started.append(b) or True)
    try:
        with TestClient(main.app) as client:
            status = client.get("/embeddings").json()
            assert status["recommended"] == GEMMA
            option = next(m for m in status["models"] if m["id"] == GEMMA)
            assert option["needsDownload"] and not option["needsToken"] and not option["available"]
            assert em.LARGE_ID not in {m["id"] for m in status["models"]}, "the torch download isn't offered here"
            assert status["reindex"]["state"] in ("idle", "done")
            r = client.post("/embeddings/install", json={"model": GEMMA})
            assert r.status_code == 202 and started == [bank]
            monkeypatch.setattr(coreml_embedder, "supported", lambda: False)
            r = client.post("/embeddings/install", json={"model": GEMMA})
            assert r.status_code == 409 and "macOS 15" in r.json()["detail"]
            assert client.post("/embeddings/install", json={"model": "other/model"}).status_code == 400
    finally:
        config.get_settings.cache_clear()
