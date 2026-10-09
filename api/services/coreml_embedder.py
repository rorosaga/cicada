"""EmbeddingGemma 2 on the Neural Engine, through Core ML (macOS 15 and later; owner 2026-10-09).

The model is the Core ML export of ``google/embeddinggemma-2`` (``FluidInference/embeddinggemma-2-coreml``,
Apache 2.0): seven fixed-shape functions sharing one set of fp16 weights (``embed_32`` … ``embed_512`` for one
text, ``pack_256`` for up to eight short ones), a bf16 token table looked up here and scaled by √512, and the
original Gemma tokenizer. Fixed shapes are what keep the graph on the Neural Engine. Measured on an M4 Pro: a
query 2.8 ms (p50); 500 short texts/s packed; 34 texts/s at 256–512 tokens; parity with the reference
sentence-transformers model cosine ≥ 0.9998.

**What runs where.** ``supported()`` is the whole gate: Apple silicon, macOS 15 or later, ``coremltools``
importable. Elsewhere this module is never asked to embed (``onnx_embedder.available`` hides the model) and
search keeps the bundled small model.

**Loading is per function and lazy.** A query loads only the function its length needs (a short query:
``embed_32``, about 1 s warm), a build loads what its texts need. The first load of a function after the model
lands (or after macOS clears its cache) compiles it for the Neural Engine — about 90 s for all seven, cached by
macOS against the ``.mlmodelc`` path, which is why the model lives at one stable path under
``$CICADA_HOME/models`` and is warmed once by the install (``model_fetch``). A query never waits that out: past
``QUERY_LOAD_WAIT_S`` it raises :class:`EmbedderWarming` and search answers on words while the load finishes in
the background; a build waits.

**One predict at a time per process.** Core ML serialises Neural Engine work anyway; the lock only keeps two
threads from sharing one model object.
"""
from __future__ import annotations

import functools
import json
import os
import platform
import threading
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeout
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:  # pragma: no cover
    from api.services.onnx_embedder import ModelSpec

LENGTHS = (32, 48, 64, 128, 256, 512)
HIDDEN = 512
FULL_DIM = 768
PACK_LEN = 256
PACK_SLOTS = 8
SCALE = float(np.sqrt(512.0))
COMPILED = "EmbeddingGemma2Text.mlmodelc"
PACKAGE = "EmbeddingGemma2Text.mlpackage"
TABLE = "embeddings.bf16"
#: How long a SEARCH waits for a function that is still loading before it answers on words instead.
#: A warm load is about 1 s; a cold one (the Neural Engine compile) about 90 s.
QUERY_LOAD_WAIT_S = 8.0
#: The functions a query can need (a query is short); what ``warm(query_only=True)`` loads.
QUERY_FUNCTIONS = ("embed_32", "embed_48", "embed_64")
MIN_MACOS = (15, 0)


class EmbedderWarming(RuntimeError):
    """The model is still loading for the Neural Engine; this query answers on words."""


class EmbedderUnavailable(RuntimeError):
    """The model's files are here but Core ML could not load them."""


def _macos_version() -> tuple[int, int]:
    raw = platform.mac_ver()[0] or "0"
    parts = (raw.split(".") + ["0"])[:2]
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return 0, 0


def supported() -> bool:
    """Whether this Mac can run the model at all: Apple silicon, macOS 15+, and the Core ML bindings.
    ``CICADA_COREML_DISABLED=1`` turns it off (the bundled small model answers)."""
    if os.environ.get("CICADA_COREML_DISABLED", "").strip() == "1":
        return False
    return _platform_supports()


@functools.lru_cache(maxsize=1)
def _platform_supports() -> bool:
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        return False
    if _macos_version() < MIN_MACOS:
        return False
    import importlib.util

    return importlib.util.find_spec("coremltools") is not None


#: Frameworks ``coremltools`` imports at its own import only to offer their converters. This runtime loads
#: compiled models and never converts, so they are hidden for that one import: in a checkout (which has torch)
#: it saves about 2 s of every process's first search; a later ``import torch`` elsewhere is unaffected.
_CONVERTER_FRAMEWORKS = ("torch", "torchvision", "torchaudio", "torchao", "executorch", "tensorflow", "sklearn",
                         "xgboost", "libsvm", "transformers")


def import_coremltools():
    """``coremltools``, quickly and quietly (it logs a line for every converter framework version it doesn't
    know — noise for a runtime that only loads compiled models)."""
    import logging
    import sys
    import warnings

    if "coremltools" in sys.modules:
        return sys.modules["coremltools"]
    logging.getLogger("coremltools").setLevel(logging.ERROR)
    hidden = [name for name in _CONVERTER_FRAMEWORKS if name not in sys.modules]
    for name in hidden:
        sys.modules[name] = None  # type: ignore[assignment] — `import name` raises ImportError meanwhile
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            import coremltools
    finally:
        for name in hidden:
            if sys.modules.get(name, 0) is None:
                del sys.modules[name]
    return coremltools


def files_complete(directory: Path) -> bool:
    """The files the runtime reads (the compiled model, not the package it was compiled from)."""
    return ((directory / COMPILED).is_dir() and (directory / TABLE).is_file()
            and (directory / "tokenizer.json").is_file())


class CoreMLEmbedder:
    """Lazy, thread-safe; ``__call__(texts, *, is_query=False) -> float32 [n, width]``, L2-normalised."""

    def __init__(self, spec: "ModelSpec"):
        self.spec = spec
        self.width = int(spec.dimensions or FULL_DIM)
        self._lock = threading.Lock()
        self._predict_lock = threading.Lock()
        self._models: dict[str, object] = {}
        self._loading: dict[str, Future] = {}
        self._tokenizer = None
        self._table = None

    # ---- loading -------------------------------------------------------------------------------
    def _base(self) -> None:
        with self._lock:
            if self._tokenizer is not None:
                return
            from tokenizers import Tokenizer

            raw = np.memmap(self.spec.path / TABLE, dtype=np.uint16, mode="r")
            self._table = raw.reshape(-1, HIDDEN)
            self._tokenizer = Tokenizer.from_file(str(self.spec.path / "tokenizer.json"))

    def _load_function(self, name: str) -> object:
        ct = import_coremltools()

        try:
            model = ct.models.CompiledMLModel(str(self.spec.path / COMPILED),
                                              compute_units=ct.ComputeUnit.CPU_AND_NE, function_name=name)
        except Exception as exc:  # noqa: BLE001 — every Core ML failure is one kind for the caller
            raise EmbedderUnavailable(f"Core ML could not load {name}: {type(exc).__name__}") from exc
        with self._lock:
            self._models[name] = model
        return model

    def _function(self, name: str, *, wait: float | None) -> object:
        with self._lock:
            model = self._models.get(name)
            if model is not None:
                return model
            future = self._loading.get(name)
            if future is None:
                future = Future()
                self._loading[name] = future
                # A daemon thread, not an executor: a short-lived process (the CLI) that gave up waiting must be
                # able to exit without sitting out a cold compile it no longer needs.
                threading.Thread(target=self._run_load, args=(name, future), name=f"cicada-coreml-{name}",
                                 daemon=True).start()
        try:
            return future.result(timeout=wait)
        except FutureTimeout as exc:
            raise EmbedderWarming("the search model is still loading") from exc

    def _run_load(self, name: str, future: Future) -> None:
        try:
            model, error = self._load_function(name), None
        except BaseException as exc:  # noqa: BLE001 — handed to whoever waits; a later call retries
            model, error = None, exc
        # Forgotten BEFORE the waiters wake: a call right after a failure must start a fresh load, never
        # find this finished one still listed.
        with self._lock:
            self._loading.pop(name, None)
        if error is not None:
            future.set_exception(error)
        else:
            future.set_result(model)

    def loaded(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._models)

    def warm(self, *, query_only: bool = False) -> None:
        """Load (and, the first time on this path, compile) the functions now — the install does it once
        so nobody's first search pays the Neural Engine compile."""
        self._base()
        names = QUERY_FUNCTIONS if query_only else tuple(f"embed_{n}" for n in LENGTHS) + ("pack_256",)
        for name in names:
            self._function(name, wait=None)

    # ---- tokens --------------------------------------------------------------------------------
    def _meta(self) -> dict:
        cached = self.__dict__.get("_cfg")
        if cached is None:
            try:
                cached = json.loads((self.spec.path / "config.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                cached = {}
            self.__dict__["_cfg"] = cached
        return cached

    def _ids(self, text: str) -> list[int]:
        cfg = self._meta()
        bos, eos = int(cfg.get("bos_token_id", 2)), int(cfg.get("eos_token_id", 1))
        ids = self._tokenizer.encode(text, add_special_tokens=False).ids
        cap = max(int(self.spec.max_tokens or 512), 2)
        return [bos] + ids[: cap - 2] + [eos]

    def _rows(self, ids) -> np.ndarray:
        bf = np.asarray(self._table[np.asarray(ids, dtype=np.int64)], dtype=np.uint32) << 16
        return (bf.view(np.float32) * SCALE).astype(np.float16)

    def _pad_id(self) -> int:
        return int(self._meta().get("pad_token_id", 0))

    # ---- model calls ---------------------------------------------------------------------------
    def _single(self, ids: list[int], wait: float | None) -> np.ndarray:
        n = len(ids)
        size = next(s for s in LENGTHS if s >= n)
        model = self._function(f"embed_{size}", wait=wait)
        emb = np.zeros((1, size, HIDDEN), dtype=np.float16)
        emb[0, :n] = self._rows(ids)
        if size > n:
            emb[0, n:] = self._rows([self._pad_id()] * (size - n))
        mask = np.zeros((1, size), dtype=np.float16)
        mask[0, :n] = 1
        with self._predict_lock:
            out = model.predict({"inputs_embeds": emb, "attention_mask": mask})["embedding"]
        return np.asarray(out, dtype=np.float32).reshape(-1)[:FULL_DIM]

    def _packed(self, seqs: list[list[int]]) -> list[np.ndarray]:
        model = self._function("pack_256", wait=None)
        emb = np.zeros((1, PACK_LEN, HIDDEN), dtype=np.float16)
        bias = np.full((1, 1, PACK_LEN, PACK_LEN), -10000, dtype=np.float16)
        pos = np.zeros((PACK_LEN, 1), dtype=np.float16)
        pool = np.zeros((PACK_SLOTS, PACK_LEN), dtype=np.float16)
        off = 0
        for slot, ids in enumerate(seqs):
            n = len(ids)
            emb[0, off:off + n] = self._rows(ids)
            bias[0, 0, off:off + n, off:off + n] = 0
            pos[off:off + n, 0] = np.arange(n)
            pool[slot, off:off + n] = 1.0 / n
            off += n
        if off < PACK_LEN:
            emb[0, off:] = self._rows([self._pad_id()] * (PACK_LEN - off))
            idx = np.arange(off, PACK_LEN)
            bias[0, 0, idx, idx] = 0
        with self._predict_lock:
            out = model.predict({"inputs_embeds": emb, "attention_bias": bias, "positions": pos,
                                 "pool": pool})["embedding"]
        out = np.asarray(out, dtype=np.float32).reshape(PACK_SLOTS, FULL_DIM)
        return [out[i] for i in range(len(seqs))]

    def _documents(self, tokenized: list[list[int]]) -> np.ndarray:
        """Short texts share ``pack_256`` calls (eight at most, 256 tokens in all); longer ones run alone."""
        result = np.zeros((len(tokenized), FULL_DIM), dtype=np.float32)
        bins: list[list[int]] = []
        current: list[int] = []
        used = 0
        for i, ids in enumerate(tokenized):
            if len(ids) > PACK_LEN:
                result[i] = self._single(ids, None)
                continue
            if used + len(ids) > PACK_LEN or len(current) == PACK_SLOTS:
                bins.append(current)
                current, used = [], 0
            current.append(i)
            used += len(ids)
        if current:
            bins.append(current)
        for group in bins:
            if len(group) == 1:  # one text: its own smallest function is cheaper than a 256 pack
                result[group[0]] = self._single(tokenized[group[0]], None)
                continue
            for i, vec in zip(group, self._packed([tokenized[i] for i in group])):
                result[i] = vec
        return result

    def loaded_only(self):
        """This embedder for a caller with a budget of milliseconds (the per-prompt recall hook, G149 R-H4): a
        query whose function isn't loaded yet raises :class:`EmbedderWarming` at once instead of loading it."""
        def embed(texts: list[str], *, is_query: bool = False) -> np.ndarray:
            return self(texts, is_query=is_query, _query_wait=0.0)

        return embed

    def __call__(self, texts: list[str], *, is_query: bool = False, _query_wait: float | None = None) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.width), dtype=np.float32)
        self._base()
        prefix = self.spec.query_prefix if is_query else self.spec.document_prefix
        tokenized = [self._ids(prefix + (t or "")) for t in texts]
        if is_query:
            wait = QUERY_LOAD_WAIT_S if _query_wait is None else _query_wait
            vectors = np.vstack([self._single(ids, wait) for ids in tokenized])
        else:
            vectors = self._documents(tokenized)
        vectors = vectors[:, : self.width]  # Matryoshka: the first N values, re-normalised
        return (vectors / np.clip(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12, None)).astype(np.float32)
