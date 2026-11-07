"""A screenshot as one EmbeddingGemma 2 vector, in the same space as Cicada's text vectors (design taste, 2026-10-14).

The Core ML export (``FluidInference/embeddinggemma-2-coreml``, Apache 2.0) ships an image encoder beside the text one:
a Gemma 4 ViT whose ``vision_70`` / ``vision_140`` / ``vision_280`` functions turn an image's 16 px patches into 70 /
140 / 280 tokens already projected into the text model's input space. The text model then embeds
``<bos> <|image> [image tokens] <image|> <eos>`` exactly as it embeds a sentence, so a picture and the words
"dark minimal dashboard with serif headings" are compared by one cosine. The export's card gives the recipe this
module follows: resize keeping the aspect ratio so both sides are multiples of 48 px and the image has at most
9 × budget patches; scale RGB to [0, 1]; cut row-major 16 × 16 patches (each ``[16 rows][16 cols][RGB]``); position
embeddings ``table[0][x] + table[1][y]`` from ``position_embeddings.f16``; a ``pool`` matrix averaging each 3 × 3
group; padding marked ``valid = 0`` and position −1.

**The budget is 70 tokens** (``BUDGET``): the card's zero-shot figure is 87.0 % against 89.5 % at 280, at about 15 ms
an image on the GPU against 64–177 ms — a board of saved screenshots is a few hundred images, re-embedded whole when
the model changes. **The GPU, not the Neural Engine** (``CPU_AND_GPU``, as the card's ``compute_units`` says): full
attention over every patch grows with the square of the count, so the GPU is faster at every budget.

**What runs where.** Only where ``coreml_embedder.supported()`` and the image encoder sits beside a complete text
encoder (``model_fetch.vision_installed``) — which only the person's click puts there. Elsewhere :func:`get` is None
and the design board searches by words. The decode is ``image_decode`` (a child process; no image library here).
"""
from __future__ import annotations

import json
import math
import threading
from pathlib import Path

import numpy as np

from api.services import coreml_embedder

PATCH = 16
GROUP = 3                       # the pooling kernel: 3 × 3 patches make one token
SIDE_STEP = PATCH * GROUP       # 48 px
BUDGET = 70
FUNCTIONS = {70: 630, 140: 1260, 280: 2520}   # tokens → patch slots
POSITION_ROWS = 1024
BOS, EOS = 2, 1
BOI, EOI = 255999, 258882       # <|image>, <image|> (the export's config.json)
COMPILED = "EmbeddingGemma2Vision.mlmodelc"
POSITIONS = "position_embeddings.f16"

_DTYPES = {"float16": np.float16, "float32": np.float32, "double": np.float64, "float64": np.float64,
           "int32": np.int32, "int64": np.int64}


def plan_size(width: int, height: int, tokens: int = BUDGET) -> tuple[int, int]:
    """``(width, height)`` in px for an image of ``width`` × ``height``: aspect kept, both sides multiples of 48 px,
    at most ``tokens`` 3 × 3 groups (9 × ``tokens`` patches), never zero."""
    width, height = max(1, int(width)), max(1, int(height))
    scale = math.sqrt(tokens * SIDE_STEP * SIDE_STEP / (width * height))
    gw = max(1, int(width * scale // SIDE_STEP))
    gh = max(1, int(height * scale // SIDE_STEP))
    while gw * gh > tokens:
        if gw >= gh:
            gw -= 1
        else:
            gh -= 1
    cap = POSITION_ROWS // GROUP
    return min(gw, cap) * SIDE_STEP, min(gh, cap) * SIDE_STEP


def inputs(rgb: np.ndarray, table: np.ndarray, tokens: int = BUDGET) -> tuple[dict[str, np.ndarray], int]:
    """The vision function's feed for ``rgb`` (``uint8 [h, w, 3]``, already at :func:`plan_size`) and the number of
    real tokens it yields. ``table`` is the ``[2, 1024, 768]`` position table."""
    slots = FUNCTIONS[tokens]
    h, w = rgb.shape[:2]
    if h % SIDE_STEP or w % SIDE_STEP:
        raise ValueError("the image isn't at a planned size")
    ph, pw = h // PATCH, w // PATCH
    n = ph * pw
    if n > slots:
        raise ValueError("the image has more patches than the function holds")
    pixels = rgb.astype(np.float32) / 255.0
    patches = pixels.reshape(ph, PATCH, pw, PATCH, 3).transpose(0, 2, 1, 3, 4).reshape(n, PATCH * PATCH * 3)
    ys, xs = np.divmod(np.arange(n), pw)
    feed_patches = np.zeros((1, slots, PATCH * PATCH * 3), dtype=np.float32)
    feed_patches[0, :n] = patches
    positions = np.full((1, slots, 2), -1, dtype=np.float32)
    positions[0, :n, 0], positions[0, :n, 1] = xs, ys
    pos_emb = np.zeros((1, slots, table.shape[-1]), dtype=np.float32)
    pos_emb[0, :n] = np.asarray(table[0][xs], dtype=np.float32) + np.asarray(table[1][ys], dtype=np.float32)
    valid = np.zeros((1, slots), dtype=np.float32)
    valid[0, :n] = 1
    gw = pw // GROUP
    groups = (ys // GROUP) * gw + (xs // GROUP)
    real = int(groups.max()) + 1 if n else 0
    pool = np.zeros((tokens, slots), dtype=np.float32)
    pool[groups, np.arange(n)] = 1.0 / (GROUP * GROUP)
    return ({"patches": feed_patches, "positions": positions, "position_embeddings": pos_emb, "valid": valid,
             "pool": pool}, real)


# --- the preprocessing's fingerprint (vision item 3, 2026-10-28) ---------------------------------------------------
#
# A stored image vector is only comparable with a new one when both went through the SAME preprocessing: the recipe
# above AND the decoder that resizes the bytes (`image_decode`, macOS's `sips` — its resampling can change with an OS
# update, and nothing in Cicada would notice). So a vector is stamped with the model id plus a fingerprint of the
# preprocessing, measured: one built-in reference picture (`reference_png`) is decoded through the real decoder at its
# planned size and cut into the vision function's feed, and the feed's bytes are hashed together with the recipe. An
# unchanged pipeline gives the same stamp and nothing re-embeds; a changed recipe or a decoder that now draws other
# pixels gives a new stamp, and the design index re-embeds every picture once (`design_index.refresh`).

#: The reference picture's size: not a multiple of 48, so the decoder's resampling is exercised on every axis.
REFERENCE_SIZE = (150, 100)
#: The fingerprint of the pipeline every image vector stored before stamps existed was made with (this recipe, macOS
#: 27's `sips`, measured 2026-10-28). A row stamped with the bare model id is current only while the pipeline still
#: measures this — so adding the stamp re-embeds nothing.
LEGACY_FINGERPRINT = "0fe2d32892e5"


def recipe() -> dict:
    """Every constant the feed depends on, beside the code that uses them."""
    return {"patch": PATCH, "group": GROUP, "budget": BUDGET, "slots": FUNCTIONS[BUDGET], "positions": POSITION_ROWS,
            "specials": [BOS, BOI, EOI, EOS], "scale": "rgb/255", "flatten": "alpha over white", "version": 1}


def reference_rgb() -> np.ndarray:
    """``uint8 [100, 150, 3]``: a deterministic picture with edges, gradients and flat areas (no randomness)."""
    w, h = REFERENCE_SIZE
    y, x = np.mgrid[0:h, 0:w]
    rgb = np.stack([(x * 255) // (w - 1), (y * 255) // (h - 1), ((x // 10 + y // 10) % 2) * 255], axis=-1)
    rgb[30:60, 40:90] = (200, 40, 40)
    return rgb.astype(np.uint8)


def reference_png() -> bytes:
    """:func:`reference_rgb` as a PNG, built here (no image library): the bytes the decoder is fingerprinted on."""
    import struct
    import zlib

    rgb = reference_rgb()
    h, w = rgb.shape[:2]
    raw = b"".join(b"\x00" + rgb[row].tobytes() for row in range(h))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def feed_digest(rgb: np.ndarray, tokens: int = BUDGET) -> str:
    """sha256 of the feed :func:`inputs` cuts from ``rgb`` (a zero position table: positions are the recipe's, the
    table is the model's)."""
    import hashlib

    table = np.zeros((2, POSITION_ROWS, 8), dtype=np.float16)
    feed, real = inputs(rgb, table, tokens)
    digest = hashlib.sha256(str(real).encode())
    for key in sorted(feed):
        digest.update(key.encode())
        digest.update(np.ascontiguousarray(feed[key], dtype=np.float32).tobytes())
    return digest.hexdigest()


_FINGERPRINTS: dict[int, str] = {}


def fingerprint(decode=None, tokens: int = BUDGET) -> str:
    """The preprocessing's fingerprint (12 hex): the recipe plus the feed of :func:`reference_png` decoded by the real
    decoder (or ``decode``, for tests). Measured once per process; a decoder that cannot run raises ``DecodeError``."""
    import hashlib

    from api.services import image_decode

    key = id(decode) if decode is not None else 0
    if key in _FINGERPRINTS and decode is None:
        return _FINGERPRINTS[key]
    data = reference_png()
    size = plan_size(*REFERENCE_SIZE, tokens=tokens)
    rgb = (decode or image_decode.decode)(data, size=size)
    text = json.dumps(recipe(), sort_keys=True) + feed_digest(np.asarray(rgb, dtype=np.uint8), tokens)
    out = hashlib.sha256(text.encode()).hexdigest()[:12]
    if decode is None:
        _FINGERPRINTS[key] = out
    return out


def stamp_for(model_id: str, fp: str) -> str:
    """What an image vector is stamped with: the model and the preprocessing that fed it."""
    return f"{model_id}#pre-{fp}"


def stamp_current(stored: str, model_id: str, fp: str) -> bool:
    """Whether a stored vector's stamp still matches: the full stamp, or — for a vector stored before stamps — the
    bare model id while the pipeline still measures :data:`LEGACY_FINGERPRINT`."""
    return stored == stamp_for(model_id, fp) or (stored == model_id and fp == LEGACY_FINGERPRINT)


def sequence_rows(text_embedder, image_tokens: np.ndarray) -> np.ndarray:
    """``<bos> <|image> tokens <image|> <eos>`` as rows of the text model's input (the specials from its table)."""
    head = text_embedder.token_rows([BOS, BOI])
    tail = text_embedder.token_rows([EOI, EOS])
    return np.concatenate([head, np.asarray(image_tokens, dtype=np.float16), tail], axis=0)


class VisionEmbedder:
    """``embed(bytes) -> float32 [width]`` (L2-normalised), and ``embed_text(texts)`` for queries in the same space.
    Lazy and thread-safe; one predict at a time."""

    def __init__(self, folder: Path, text_embedder, *, tokens: int = BUDGET, decode=None):
        self.folder = Path(folder)
        self.text = text_embedder
        self.tokens = tokens
        self.model_id = getattr(getattr(text_embedder, "spec", None), "id", "") or ""
        self._decode = decode
        self._lock = threading.Lock()
        self._model = None
        self._table = None
        self._dtypes: dict[str, type] = {}

    def _load(self):
        with self._lock:
            if self._model is not None:
                return self._model
            ct = coreml_embedder.import_coremltools()
            path = self.folder / COMPILED
            try:
                model = ct.models.CompiledMLModel(str(path), compute_units=ct.ComputeUnit.CPU_AND_GPU,
                                                  function_name=f"vision_{self.tokens}")
            except Exception as exc:  # noqa: BLE001 — one kind for the caller
                raise coreml_embedder.EmbedderUnavailable(f"Core ML could not load the image model: "
                                                          f"{type(exc).__name__}") from exc
            raw = np.memmap(self.folder / POSITIONS, dtype=np.float16, mode="r")
            self._table = raw.reshape(2, POSITION_ROWS, -1)
            self._dtypes = _input_dtypes(path, f"vision_{self.tokens}")
            self._model = model
            return model

    def embed(self, data: bytes) -> np.ndarray:
        from api.services import image_decode

        model = self._load()
        decode = self._decode or image_decode.decode
        size = image_decode.dimensions(data)
        if size is None:
            raise image_decode.DecodeError("no size")
        width, height = plan_size(*size, tokens=self.tokens)
        rgb = decode(data, size=(width, height))
        feed, real = inputs(rgb, self._table, self.tokens)
        feed = {k: v.astype(self._dtypes.get(k, np.float16)) for k, v in feed.items()}
        with self._lock:
            out = model.predict(feed)
        tokens = np.asarray(out["image_tokens"], dtype=np.float32).reshape(self.tokens, -1)[:real]
        return self.text.embed_rows(sequence_rows(self.text, tokens))

    def embed_text(self, texts: list[str], *, is_query: bool = True) -> np.ndarray:
        return self.text(texts, is_query=is_query)

    @property
    def stamp(self) -> str:
        """The stamp every vector this embedder makes carries (:func:`stamp_for`); the fingerprint is measured once."""
        return stamp_for(self.model_id, fingerprint(self._decode, self.tokens))


def _input_dtypes(compiled: Path, function: str) -> dict[str, type]:
    """The input types the compiled model declares (its ``metadata.json``), so each array is handed over as the
    graph expects; anything unreadable is fp16, the export's precision."""
    try:
        meta = json.loads((compiled / "metadata.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    entries = meta if isinstance(meta, list) else [meta]
    found: dict[str, type] = {}
    for entry in entries:
        schemas = [entry.get("inputSchema") or []]
        for fn in (entry.get("functions") or []):
            if isinstance(fn, dict) and fn.get("name") == function:
                schemas.insert(0, fn.get("inputSchema") or [])
        for schema in schemas:
            for item in schema:
                name = str(item.get("name") or "")
                kind = str(item.get("dataType") or "").lower()
                if name and kind in _DTYPES and name not in found:
                    found[name] = _DTYPES[kind]
    return found


_CACHE: dict[str, VisionEmbedder] = {}
_CACHE_LOCK = threading.Lock()


def folder(environ=None) -> Path | None:
    """EmbeddingGemma 2's folder when the image encoder is installed there and this Mac runs it, else None."""
    import os

    from api.services import model_fetch, runtime_layout

    if not coreml_embedder.supported():
        return None
    try:
        p = model_fetch.pins()
        out = model_fetch.destination(runtime_layout.cicada_home(environ or os.environ) / "models", p)
    except model_fetch.FetchError:
        return None
    return out if model_fetch.vision_installed(out, p) else None


def get(environ=None) -> VisionEmbedder | None:
    """The process's one image embedder, or None where search by image can't run (see the module docstring)."""
    from api.services import onnx_embedder, providers

    where = folder(environ)
    if where is None:
        return None
    key = str(where)
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
    if hit is not None:
        return hit
    try:
        text, _ = providers.cached_embed_fn_for_model(onnx_embedder.PREFERRED_ID)
    except Exception:  # noqa: BLE001 — no text model, no image vectors
        return None
    if not hasattr(text, "embed_rows"):
        return None
    made = VisionEmbedder(where, text)
    with _CACHE_LOCK:
        return _CACHE.setdefault(key, made)


def clear_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()
