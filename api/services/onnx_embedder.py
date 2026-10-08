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
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np

BUNDLED_MODELS_ENV = "CICADA_BUNDLED_MODELS"
MANIFEST = "cicada-model.json"
#: The id a release app's fresh bank is built with.
DEFAULT_ID = "intfloat/multilingual-e5-small"
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


def model_dirs(environ=os.environ) -> list[Path]:
    """Where bundled models live: ``CICADA_BUNDLED_MODELS`` (set only by a release
    app's launchers), else ``$CICADA_HOME/models`` — where a developer checkout's
    ``make embedding-model`` puts them. Only directories holding a manifest count, so
    the larger model's download beside them is never mistaken for one."""
    raw = (environ.get(BUNDLED_MODELS_ENV) or "").strip()
    if raw:
        return [Path(raw)]
    from api.services import runtime_layout

    return [runtime_layout.cicada_home(environ) / "models"]


def _read_spec(directory: Path) -> ModelSpec | None:
    try:
        meta = json.loads((directory / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not (directory / "model.onnx").is_file() or not (directory / "tokenizer.json").is_file():
        return None
    model_id = str(meta.get("id") or "").strip()
    if not model_id:
        return None
    return ModelSpec(
        id=model_id,
        path=directory,
        dimensions=int(meta.get("dimensions") or 0),
        pooling=str(meta.get("pooling") or "cls"),
        normalize=bool(meta.get("normalize", True)),
        max_tokens=int(meta.get("max_tokens") or 512),
        query_prefix=str(meta.get("query_prefix") or ""),
        document_prefix=str(meta.get("document_prefix") or ""),
    )


def available(environ=os.environ) -> list[ModelSpec]:
    """Every complete bundled model, in directory order."""
    out: list[ModelSpec] = []
    for root in model_dirs(environ):
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            spec = _read_spec(child) if child.is_dir() else None
            if spec is not None:
                out.append(spec)
    return out


def find(model_id: str, environ=os.environ) -> ModelSpec | None:
    """The bundled model with this id, case-insensitively, or None."""
    wanted = (model_id or "").strip().lower()
    return next((s for s in available(environ) if s.id.lower() == wanted), None)


def default_model(environ=os.environ) -> ModelSpec | None:
    """The model a fresh bank is built with when one is bundled: ``DEFAULT_ID``
    if present, else the first bundled model."""
    models = available(environ)
    return next((s for s in models if s.id == DEFAULT_ID), models[0] if models else None)


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
