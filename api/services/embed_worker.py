"""A long document embed runs in a child process, so it never holds the backend's GIL (2026-10-09).

**Why.** ``coremltools``' ``CompiledMLModel.predict`` holds the GIL for the whole prediction (measured: a 712 ms
Neural Engine predict left a pure-Python thread 0.55 % of its throughput, its longest wait 738 ms). A background
re-embed of an owner-sized bank is minutes of back-to-back predicts — 16 ms for a pack of short texts, ~29 ms for
a 512-token passage — so in-process every other thread of the backend, the event loop included, got the GIL only
between two of them. A request that gives the GIL up and takes it back hundreds of times (a directory listing,
sqlite, the socket) waited up to one predict each time: ``/healthz`` and the capture hook's POST took over 10 s on
the owner's bank. Sleep's own index syncs embed through the same code, so a large sync did the same.

**What runs where.** The parent keeps everything that decides and writes — the diff, the per-file write lock, the
one-transaction swap, the stop check between chunks (``vector_index``). The child only turns texts into vectors:
the same model id, resolved the same way (``providers.cached_embed_fn_for_model``), the same arithmetic, so a
table is never a mix of two processes' vectors of different models. While the child works the parent waits on a
pipe, which releases the GIL.

**Which embeds.** Documents only, for an on-device model (a folder ``onnx_embedder`` finds: the bundled small model,
EmbeddingGemma 2), in batches of at least ``MIN_TEXTS``; a query, a handful of documents, a hosted model (network
bound, releases the GIL) or an injected test embedder stays in-process. ``CICADA_EMBED_WORKER=off`` keeps every
embed in-process (the suite runs with it off; its own tests turn it on).

**Lifetime.** One child per model, started on first use and reused; it exits on its own after ``IDLE_S`` without
work, and at once when the backend goes away (its stdin closes). A child that died is replaced once per call; a
second death is an error the caller handles like any failed embed (the old tables stay as they were).

**Pictures too (vision item 3, 2026-10-28).** ``coremltools`` holds the GIL for an image predict exactly as for a text
one, and the image encoder loads ~300 MB beside the text model, so every picture vector — the meaning index's
background refresh (``image_index``) and the design board's (``design_index``) — is made in a child of its own
(:func:`images`, ``VISION_FACTORY``), never in the backend. That child runs at a lower priority (``NICE``) with its
math libraries held to ``THREADS`` cores, and has a **memory ceiling** (``VISION_MEMORY_MB``): after any request that
leaves its peak resident size above it, it answers and exits, and the next request starts a fresh one. macOS
enforces no address-space limit a process can set on itself, so the ceiling is the child's own check, not the
kernel's. A picture that fails comes back as a row of NaN — one bad file never fails the batch.
"""
from __future__ import annotations

import os
import pickle
import select
import subprocess
import sys
import threading
from pathlib import Path

import numpy as np
from loguru import logger

ENV = "CICADA_EMBED_WORKER"
#: Fewer texts than this embed in-process: a few predicts cost less than a round trip, and far less than a start.
MIN_TEXTS = 16
#: Texts per request to the child: bounds one message (a passage is ≤ 4,000 characters) and its reply.
BATCH = 256
#: A child with nothing to do for this long exits; the next long embed starts another.
IDLE_S = 90.0
#: How the child builds its embedder: ``"module:attr"``, called with the model id, returning an embed function.
#: The default is the backend's own resolution; the tests point it at a stand-in.
FACTORY = "api.services.embed_worker:_resolve"
#: How a picture child builds its embedder: called with the model id, returning ``fn(list[bytes]) -> [n, d]``.
VISION_FACTORY = "api.services.embed_worker:_resolve_vision"
#: Pictures per request: a preview is at most 512 KB, a capture thumbnail far less, so one message stays a few MB.
IMAGE_BATCH = 16
#: A picture child that has peaked above this many MB answers and exits; the next request starts another.
VISION_MEMORY_MB = 2048
#: A picture child's priority and its math libraries' threads (the owner's ≤ 4 cores for background embedding).
NICE = 10
THREADS = 4


class WorkerStopped(RuntimeError):
    """The embedding child exited mid-request twice in a row."""


def enabled(environ=os.environ) -> bool:
    return (environ.get(ENV) or "").strip().lower() not in ("off", "0", "false", "no")


def eligible(model_id: str | None, environ=os.environ) -> bool:
    """Whether a long document embed with ``model_id`` goes to a child: an on-device model folder that runs here."""
    if not model_id or not enabled(environ):
        return False
    from api.services import onnx_embedder

    return onnx_embedder.find(model_id, environ) is not None


def documents(model_id: str, fallback):
    """An embed function for ``model_id``'s documents: long batches in the child, the rest through ``fallback``
    (the in-process embedder for the same model)."""
    def embed(texts: list[str], *, is_query: bool = False) -> np.ndarray:
        if is_query or len(texts) < MIN_TEXTS:
            return fallback(texts, is_query=is_query)
        worker = _worker(model_id)
        parts = [worker.embed(list(texts[i : i + BATCH])) for i in range(0, len(texts), BATCH)]
        return np.concatenate(parts, axis=0)

    return embed


def images(model_id: str):
    """An embed function for pictures with ``model_id``'s image encoder, in the picture child: ``fn(list[bytes]) ->
    float32 [n, d]``, a NaN row for a picture that could not be read or embedded."""
    def embed(blobs: list[bytes]) -> np.ndarray:
        worker = _worker(model_id, VISION_FACTORY)
        parts = [worker.request("images", list(blobs[i : i + IMAGE_BATCH]))
                 for i in range(0, len(blobs), IMAGE_BATCH)]
        return np.concatenate(parts, axis=0) if parts else np.zeros((0, 0), dtype=np.float32)

    return embed


# --------------------------------------------------------------------------- the parent's side

_WORKERS: dict[tuple[str, str], _Worker] = {}
_WORKERS_GUARD = threading.Lock()


def _worker(model_id: str, factory: str | None = None) -> _Worker:
    factory = factory or FACTORY
    key = (factory, model_id)
    with _WORKERS_GUARD:
        worker = _WORKERS.get(key)
        if worker is None:
            worker = _WORKERS[key] = _Worker(model_id, factory)
        return worker


def shutdown() -> None:
    """Stop every child now (tests; a child also exits by itself when idle or when this process ends)."""
    with _WORKERS_GUARD:
        workers = list(_WORKERS.values())
        _WORKERS.clear()
    for worker in workers:
        worker.stop()


class _Worker:
    def __init__(self, model_id: str, factory: str):
        self.model_id = model_id
        self.factory = factory
        self._lock = threading.Lock()     # one request at a time per child
        self._proc: subprocess.Popen | None = None

    @property
    def pid(self) -> int | None:
        return self._proc.pid if self._proc is not None else None

    def _start(self) -> subprocess.Popen:
        env = dict(os.environ)
        # `api` resolves in the child exactly as here: this checkout (or the release's bundle) first.
        root = str(Path(__file__).resolve().parents[2])
        env["PYTHONPATH"] = os.pathsep.join(p for p in (root, env.get("PYTHONPATH", "")) if p)
        argv = [sys.executable, "-m", "api.services.embed_worker", self.model_id, self.factory]
        if self.factory == VISION_FACTORY:
            for name in ("OMP_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
                env[name] = str(THREADS)
            argv += ["--nice", str(NICE), "--ceiling-mb", str(VISION_MEMORY_MB)]
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env, close_fds=True)
        logger.debug(f"embed_worker: started a child for {self.model_id} (pid {proc.pid})")
        return proc

    def stop(self) -> None:
        with self._lock:
            self._kill()

    def _kill(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        for stream in (proc.stdin, proc.stdout):
            try:
                stream.close()
            except OSError:
                pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

    def embed(self, texts: list[str]) -> np.ndarray:
        return self.request("embed", texts)

    def request(self, kind: str, items: list) -> np.ndarray:
        """One request of ``kind`` (``embed`` — texts; ``images`` — picture bytes) and its ``[len(items), d]``."""
        with self._lock:
            for attempt in (1, 2):
                if self._proc is None or self._proc.poll() is not None:
                    self._kill()
                    self._proc = self._start()
                try:
                    pickle.dump((kind, items), self._proc.stdin, protocol=pickle.HIGHEST_PROTOCOL)
                    self._proc.stdin.flush()
                    status, payload = pickle.load(self._proc.stdout)
                except (BrokenPipeError, EOFError, OSError, pickle.UnpicklingError):
                    # It exited between two requests (idle) or died: one fresh start, then it is the caller's error.
                    self._kill()
                    if attempt == 2:
                        raise WorkerStopped("the search model's worker stopped") from None
                    continue
                if status == "ok":
                    vectors = np.asarray(payload, dtype=np.float32)
                    if vectors.ndim != 2 or vectors.shape[0] != len(items):
                        raise ValueError(f"embed worker returned shape {vectors.shape} for {len(items)} items")
                    return vectors
                raise payload
        raise WorkerStopped("the search model's worker stopped")   # pragma: no cover — the loop always returns


# --------------------------------------------------------------------------- the child's side

def _resolve(model_id: str):
    from api.services import providers

    embed_fn, _model = providers.cached_embed_fn_for_model(model_id)
    return embed_fn


def _resolve_vision(model_id: str):
    """The picture child's embedder: EmbeddingGemma 2's image encoder where it is installed (``vision_embedder``),
    one picture at a time, a NaN row for one that fails. ``model_id`` is the text model the table records; the image
    encoder sits beside exactly that one."""
    from api.services import vision_embedder

    vision = vision_embedder.get()
    if vision is None:
        raise RuntimeError("the image model isn't installed here")
    return picture_rows(vision.embed)


def picture_rows(embed_one):
    """``fn(list[bytes]) -> [n, d]`` from a one-picture embedder: a NaN row for a picture that raises."""
    def embed(blobs: list[bytes]) -> np.ndarray:
        rows = []
        for data in blobs:
            try:
                rows.append(np.asarray(embed_one(bytes(data)), dtype=np.float32).reshape(-1))
            except Exception:  # noqa: BLE001 — one bad picture is one NaN row, never the batch
                rows.append(None)
        width = next((r.size for r in rows if r is not None), 0)
        if not width:
            return np.full((len(blobs), 1), np.nan, dtype=np.float32)
        return np.stack([r if r is not None else np.full(width, np.nan, dtype=np.float32) for r in rows])

    return embed


def peak_mb() -> float:
    """This process's peak resident size in MB (``ru_maxrss`` is bytes on macOS, KB on Linux)."""
    import resource

    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / (1024 * 1024) if sys.platform == "darwin" else peak / 1024


def _load(factory: str):
    import importlib

    module, _, attr = factory.partition(":")
    return getattr(importlib.import_module(module), attr)


def _portable(exc: BaseException) -> BaseException:
    """The error as the parent can unpickle it; else its class name only (K9: a message can echo its input)."""
    try:
        pickle.loads(pickle.dumps(exc))
        return exc
    except Exception:  # noqa: BLE001
        return RuntimeError(f"the embedder failed: {type(exc).__name__}")


def serve(model_id: str, factory: str, inp, out, idle_s: float = IDLE_S, ceiling_mb: float | None = None) -> int:
    embed_fn = None
    while True:
        ready, _, _ = select.select([inp], [], [], idle_s)
        if not ready:
            return 0          # idle: the parent starts another when it needs one
        try:
            kind, items = pickle.load(inp)
        except EOFError:
            return 0          # the backend went away
        try:
            if embed_fn is None:
                embed_fn = _load(factory)(model_id)
            raw = embed_fn(items) if kind == "images" else embed_fn(items, is_query=False)
            reply = ("ok", np.asarray(raw, dtype=np.float32))
        except Exception as exc:  # noqa: BLE001 — every failure goes back to the caller as itself
            reply = ("error", _portable(exc))
        pickle.dump(reply, out, protocol=pickle.HIGHEST_PROTOCOL)
        out.flush()
        if ceiling_mb is not None and peak_mb() > ceiling_mb:
            logger.info(f"embed_worker: a picture child passed its {ceiling_mb:.0f} MB ceiling and exits")
            return 0          # the memory ceiling: the next request starts a fresh child


def warm_in_child(folder: Path, timeout_s: float = 30 * 60) -> None:
    """Load (and, the first time, compile for the Neural Engine) every function of the Core ML model in ``folder``
    in a child process. The load holds the GIL as long as the compile takes — about 90 s the first time — and the
    compile is cached by macOS for every process that later loads the model from that path, this one included.
    Raises ``RuntimeError`` when the child could not load it."""
    root = str(Path(__file__).resolve().parents[2])
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(p for p in (root, env.get("PYTHONPATH", "")) if p)
    done = subprocess.run([sys.executable, "-m", "api.services.embed_worker", "--warm", str(folder)],
                          stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, env=env, timeout=timeout_s,
                          check=False)
    if done.returncode != 0:
        raise RuntimeError(f"the model could not be loaded (exit {done.returncode})")


def _warm(folder: str) -> int:
    from api.services import coreml_embedder, onnx_embedder

    spec = onnx_embedder._read_spec(Path(folder))
    if spec is None:
        return 2
    coreml_embedder.CoreMLEmbedder(spec).warm()
    return 0


def main(argv: list[str]) -> int:
    if argv[1:2] == ["--warm"]:
        return _warm(argv[2])
    model_id, factory = argv[1], argv[2]
    rest = argv[3:]
    ceiling = None
    if "--nice" in rest:
        try:
            os.nice(int(rest[rest.index("--nice") + 1]))
        except (OSError, ValueError, IndexError):
            pass
    if "--ceiling-mb" in rest:
        try:
            ceiling = float(rest[rest.index("--ceiling-mb") + 1])
        except (ValueError, IndexError):
            ceiling = None
    # The protocol owns fd 1; anything a library prints goes to stderr (the backend's log) instead.
    out = os.fdopen(os.dup(1), "wb")
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    return serve(model_id, factory, sys.stdin.buffer, out, ceiling_mb=ceiling)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
