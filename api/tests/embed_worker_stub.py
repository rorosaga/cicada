"""The embedder ``embed_worker``'s child builds in the tests (``embed_worker.FACTORY`` points here).

The same deterministic vectors as ``test_embeddinggemma2``'s in-process fake (salted per model family), so a table
written partly here and partly in-process reads the same either way. ``EMBED_STUB_PIDFILE`` records the process
that embedded; ``EMBED_STUB_HOLD_MS`` holds the GIL for that long per call, as Core ML's predict does (a ``PyDLL``
call never releases it); a text ``"fail:missing"`` raises the error Core ML raises for a model it cannot load.
"""
from __future__ import annotations

import ctypes
import hashlib
import os

import numpy as np


def vectors(texts, dim, salt=""):
    rows = []
    for t in texts:
        h = int(hashlib.sha256((salt + t).encode()).hexdigest()[:8], 16)
        v = np.random.default_rng(h).standard_normal(dim).astype(np.float32)
        rows.append(v / np.linalg.norm(v))
    return np.vstack(rows) if rows else np.zeros((0, dim), np.float32)


def hold_gil(ms: float) -> None:
    usleep = ctypes.PyDLL(None).usleep
    usleep.argtypes = [ctypes.c_uint]
    usleep(int(ms * 1000))


def make(model_id: str):
    salt, dim = ("e5", 384) if "e5" in model_id.lower() else ("g", 768)

    def embed(texts, *, is_query=False):
        pidfile = os.environ.get("EMBED_STUB_PIDFILE")
        if pidfile:
            with open(pidfile, "a", encoding="utf-8") as fh:
                fh.write(f"{os.getpid()} {len(texts)}\n")
        if "fail:missing" in texts:
            from api.services.coreml_embedder import EmbedderUnavailable

            raise EmbedderUnavailable("Core ML could not load embed_32: RuntimeError")
        hold = float(os.environ.get("EMBED_STUB_HOLD_MS") or 0)
        if hold:
            hold_gil(hold)
        return vectors(texts, dim, salt)

    return embed
