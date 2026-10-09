"""The bundled embedding model: an ONNX export run with onnxruntime, no torch (G182).

A release app ships one small, ungated, multilingual model
(``intfloat/multilingual-e5-small``, 384 dimensions; owner 2026-10-06) under ``Contents/Resources/backend/models/<name>/`` and its launchers
point ``CICADA_BUNDLED_MODELS`` there. Each model directory holds ``model.onnx``,
``tokenizer.json`` and a ``cicada-model.json`` manifest naming the model id, its
pooling, whether vectors are normalised and the instructions a query and a document
each carry (e5's ``query: `` / ``passage: ``), so this module needs no per-model code.

A developer checkout has no app bundle (the variable is unset): ``make embedding-model``
fetches the release's same pinned files (``scripts/fetch-embedding-model.sh``, pins in
``scripts/release/inputs.env``) into ``$CICADA_HOME/models``, and the model is found
there. Without that step a checkout keeps EmbeddingGemma through sentence-transformers.
A bank records the model it was built with and is always queried with that model
(``providers.resolve_embed_fn_for_model``); a model change rebuilds its index.

**This module is also the registry of on-device model folders** (owner 2026-10-09): a manifest may name
``"runtime": "coreml"`` — EmbeddingGemma 2 on the Neural Engine (``coreml_embedder``), downloaded once into
``$CICADA_HOME/models`` by ``model_fetch`` on macOS 15 and later, never bundled. Its manifest lists the
Matryoshka ``widths`` the model can be cut to, and its ids carry the width (``google/embeddinggemma-2:768``),
so a table records exactly which vector space it holds. A Core ML folder counts only on a Mac that can run it
(``coreml_embedder.supported``); elsewhere it is invisible and the bundled small model answers.
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np

BUNDLED_MODELS_ENV = "CICADA_BUNDLED_MODELS"
MANIFEST = "cicada-model.json"
#: The id a release app's fresh bank is built with where nothing better runs: the floor, always bundled.
DEFAULT_ID = "intfloat/multilingual-e5-small"
#: The model every bank is built with where this Mac can run it (owner 2026-10-09): EmbeddingGemma 2 on the
#: Neural Engine at its full 768 dimensions (``coreml_embedder``; the width is part of the id).
PREFERRED_BASE = "google/embeddinggemma-2"
PREFERRED_WIDTH = 768
PREFERRED_ID = f"{PREFERRED_BASE}:{PREFERRED_WIDTH}"
#: One text per run: a batch pads every text to its longest. Measured (M4 Pro, 2,500 synthetic pages, e5-small):
#: 63.8 pages/s at 785 MB peak against 63.7 pages/s at 1,737 MB with 32 per run.
_BATCH = 1


@dataclass(frozen=True)
class ModelSpec:
    id: str
    path: Path
    dimensions: int
    pooling: str            # "cls" | "mean"
    normalize: bool
    max_tokens: int
    query_prefix: str
    document_prefix: str = ""
    runtime: str = "onnx"                 # "onnx" | "coreml"
    widths: tuple[int, ...] = ()          # Matryoshka widths a coreml model can be cut to; its id carries one


def _home_models(environ=os.environ) -> Path:
    from api.services import runtime_layout

    return runtime_layout.cicada_home(environ) / "models"


def _roots(environ=os.environ) -> list[tuple[Path, bool]]:
    """Where model folders live, as ``(folder, onnx_allowed)``: ``CICADA_BUNDLED_MODELS`` (set only by a
    release app's launchers), else ``$CICADA_HOME/models`` — where a developer checkout's ``make
    embedding-model`` puts them. Only directories holding a complete manifest count, so the larger model's
    download beside them is never mistaken for one. A release reads ONNX models only from its own bundle (never a copy under the
    home), and downloaded Core ML models only from ``$CICADA_HOME/models`` (a stable path: the Neural Engine's
    compile cache is keyed by it). A checkout reads both from the home."""
    raw = (environ.get(BUNDLED_MODELS_ENV) or "").strip()
    if raw:
        return [(Path(raw), True), (_home_models(environ), False)]
    return [(_home_models(environ), True)]


def _read_spec(directory: Path) -> ModelSpec | None:
    try:
        meta = json.loads((directory / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    runtime = str(meta.get("runtime") or "onnx")
    if runtime == "coreml":
        from api.services import coreml_embedder

        if not coreml_embedder.files_complete(directory):
            return None
    elif runtime != "onnx" or not (directory / "model.onnx").is_file() or not (directory / "tokenizer.json").is_file():
        return None
    model_id = str(meta.get("id") or "").strip()
    if not model_id:
        return None
    dimensions = int(meta.get("dimensions") or 0)
    widths = tuple(int(w) for w in (meta.get("widths") or []) if int(w) > 0)
    if runtime == "coreml":
        widths = widths or ((dimensions,) if dimensions else ())
        if not widths:
            return None
        dimensions = dimensions if dimensions in widths else widths[0]
        model_id = f"{model_id}:{dimensions}"   # a Core ML id always names its width
    return ModelSpec(
        id=model_id,
        path=directory,
        dimensions=dimensions,
        pooling=str(meta.get("pooling") or "cls"),
        normalize=bool(meta.get("normalize", True)),
        max_tokens=int(meta.get("max_tokens") or 512),
        query_prefix=str(meta.get("query_prefix") or ""),
        document_prefix=str(meta.get("document_prefix") or ""),
        runtime=runtime,
        widths=widths,
    )


def base_id(model_id: str) -> str:
    """``google/embeddinggemma-2:256`` → ``google/embeddinggemma-2`` (an id without a width is its own base)."""
    head, sep, tail = (model_id or "").strip().rpartition(":")
    return head if sep and tail.isdigit() else (model_id or "").strip()


def installed(environ=os.environ, *, runnable_only: bool = False) -> list[ModelSpec]:
    """Every complete model folder, in directory order (a Core ML one also where this Mac can't run it)."""
    out: list[ModelSpec] = []
    seen: set[str] = set()
    for root, onnx_allowed in _roots(environ):
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            spec = _read_spec(child) if child.is_dir() and not child.name.startswith(".") else None
            if spec is None or (spec.runtime == "onnx" and not onnx_allowed) or spec.id.lower() in seen:
                continue
            if runnable_only and spec.runtime == "coreml":
                from api.services import coreml_embedder

                if not coreml_embedder.supported():
                    continue
            seen.add(spec.id.lower())
            out.append(spec)
    return out


def available(environ=os.environ) -> list[ModelSpec]:
    """Every complete model this Mac can run, in directory order."""
    return installed(environ, runnable_only=True)


def _match(spec: ModelSpec, wanted: str) -> ModelSpec | None:
    if spec.runtime != "coreml":
        return spec if spec.id.lower() == wanted else None
    base = base_id(spec.id).lower()
    if wanted == base:
        return spec
    head, sep, tail = wanted.rpartition(":")
    if sep and head == base and tail.isdigit() and int(tail) in spec.widths:
        return replace(spec, id=f"{base_id(spec.id)}:{int(tail)}", dimensions=int(tail))
    return None


def find(model_id: str, environ=os.environ, *, runnable_only: bool = True) -> ModelSpec | None:
    """The model with this id (case-insensitively; a Core ML id may name any width its manifest lists), or None.
    By default only a model this Mac can run."""
    wanted = (model_id or "").strip().lower()
    for spec in installed(environ, runnable_only=runnable_only):
        hit = _match(spec, wanted)
        if hit is not None:
            return hit
    return None


def default_model(environ=os.environ) -> ModelSpec | None:
    """The model a fresh bank is built with when one is here: EmbeddingGemma 2 where this Mac runs it
    (``PREFERRED_ID``), else the bundled small model (``DEFAULT_ID``), else the first one found."""
    models = available(environ)
    preferred = find(PREFERRED_ID, environ)
    if preferred is not None:
        return preferred
    return next((s for s in models if s.id == DEFAULT_ID), models[0] if models else None)


def embedder_for(spec: ModelSpec):
    """The embedder object for a model folder: onnxruntime, or Core ML on the Neural Engine."""
    if spec.runtime == "coreml":
        from api.services.coreml_embedder import CoreMLEmbedder

        return CoreMLEmbedder(spec)
    return OnnxEmbedder(spec)


class OnnxEmbedder:
    """Loads lazily; safe to share across threads (onnxruntime sessions are)."""

    def __init__(self, spec: ModelSpec):
        self.spec = spec
        self._lock = threading.Lock()
        self._session = None
        self._tokenizer = None
        self._inputs: set[str] = set()

    def _load(self) -> None:
        with self._lock:
            if self._session is not None:
                return
            import onnxruntime as ort
            from tokenizers import Tokenizer

            tokenizer = Tokenizer.from_file(str(self.spec.path / "tokenizer.json"))
            tokenizer.enable_truncation(max_length=self.spec.max_tokens)
            tokenizer.enable_padding()
            options = ort.SessionOptions()
            options.log_severity_level = 3
            session = ort.InferenceSession(str(self.spec.path / "model.onnx"), sess_options=options,
                                           providers=["CPUExecutionProvider"])
            self._inputs = {i.name for i in session.get_inputs()}
            self._tokenizer, self._session = tokenizer, session

    def __call__(self, texts: list[str], *, is_query: bool = False) -> np.ndarray:
        self._load()
        if not texts:
            return np.zeros((0, self.spec.dimensions or 0), dtype=np.float32)
        prefix = self.spec.query_prefix if is_query else self.spec.document_prefix
        chunks: list[np.ndarray] = []
        for start in range(0, len(texts), _BATCH):
            batch = [prefix + (t or "") for t in texts[start : start + _BATCH]]
            encoded = self._tokenizer.encode_batch(batch)
            ids = np.asarray([e.ids for e in encoded], dtype=np.int64)
            mask = np.asarray([e.attention_mask for e in encoded], dtype=np.int64)
            feed = {"input_ids": ids, "attention_mask": mask}
            if "token_type_ids" in self._inputs:
                feed["token_type_ids"] = np.asarray([e.type_ids for e in encoded], dtype=np.int64)
            hidden = self._session.run(None, feed)[0]
            if self.spec.pooling == "mean":
                weights = mask[..., None].astype(np.float32)
                vectors = (hidden * weights).sum(axis=1) / np.clip(weights.sum(axis=1), 1e-9, None)
            else:
                vectors = hidden[:, 0]
            if self.spec.normalize:
                vectors = vectors / np.clip(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12, None)
            chunks.append(vectors.astype(np.float32))
        return np.concatenate(chunks, axis=0)
