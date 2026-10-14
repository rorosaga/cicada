"""Search the design board by words, by meaning or by an example picture (design taste, 2026-10-14).

**Derived and disposable, outside every bank** (``$CICADA_HOME/design-index/<bank-id>.sqlite``, the continuity
index's precedent): one row per reference and kind — ``image`` (the screenshot's EmbeddingGemma 2 vector,
``vision_embedder``) and ``note`` (the vector of what the person said plus the look's words, the same model's text
encoder) — each stamped with the model and the hash of what was embedded, so a changed note, a new screenshot or a
new model re-embeds exactly that row. Deleting the file costs a re-embed and never a reference; it is never in git.

**One space.** EmbeddingGemma 2 puts an image's vector and a sentence's vector in one 768-wide space, so a text query
is embedded once (the query prompt) and compared with the screenshots *and* the notes; an example picture is compared
with the screenshots. Where the image encoder isn't here (not downloaded, an older Mac) the picture leg is absent and
the board searches by the notes' meaning and by words; with no EmbeddingGemma 2 at all, by words alone — never an
error. The legs are fused by reciprocal rank (k = 60, recall's own fusion), so a cosine between a picture and a
sentence (≈ 0.2–0.35) never has to be compared with one between two sentences (≈ 0.5–0.8).

**Words** read each reference's title, site, link, note, the palette's words (``dark``, ``muted``, ``blue``…), its
tags, fonts and colours. A whole-word hit outranks a prefix, and the query's exact phrase in the note or title earns a
boost (DigUp's exact-word boost, github.com/ARahim3/DigUp, MIT — the idea, not the code).

**When it embeds.** On a search (what is missing, at most ``REFRESH_LIMIT`` pictures a call) and after a save, in the
background — never by Sleep and, in the background, never while Sleep runs. **The query is never logged** and never
stored; a picture searched with is decoded in memory and dropped.
"""
from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
from loguru import logger

from api.services import design_refs

INDEX_DIR = "design-index"
SCHEMA = "1"
REFRESH_LIMIT = 64
RRF_K = 60
#: A meaning leg's hit counts only when its cosine is at least this share of the leg's best (``_close``).
RELATIVE_FLOOR = 0.8
_WORD = re.compile(r"[a-z0-9#][a-z0-9#._-]*")


@dataclass
class Embedders:
    """What this process can embed with. ``image(bytes) -> [d]``; ``text(texts, is_query) -> [n, d]``."""
    model: str
    image: Callable[[bytes], np.ndarray] | None = None
    text: Callable[[list[str], bool], np.ndarray] | None = None


def default_embedders(environ=None) -> Embedders | None:
    """EmbeddingGemma 2 with its image encoder when both are here; its text encoder alone when only that is; else
    None (words only). Never downloads anything."""
    from api.services import onnx_embedder, providers, vision_embedder

    environ = os.environ if environ is None else environ
    vision = vision_embedder.get(environ)
    if vision is not None:
        return Embedders(model=vision.model_id or onnx_embedder.PREFERRED_ID, image=vision.embed,
                         text=lambda texts, q: vision.embed_text(texts, is_query=q))
    if onnx_embedder.find(onnx_embedder.PREFERRED_ID, environ) is None:
        return None
    try:
        fn, model = providers.cached_embed_fn_for_model(onnx_embedder.PREFERRED_ID)
    except Exception:  # noqa: BLE001 — no model, words only
        return None
    return Embedders(model=model, text=lambda texts, q: fn(texts, is_query=q))


# --------------------------------------------------------------------------- the file


def index_path(memory_path, environ=None) -> Path:
    from api.services import continuity_sessions, runtime_layout

    home = runtime_layout.cicada_home(os.environ if environ is None else environ)
    return home / INDEX_DIR / f"{continuity_sessions.bank_file_id(Path(memory_path))}.sqlite"


_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock(path: Path) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(str(path), threading.Lock())


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5)
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
        got = conn.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
        if got is None or got[0] != SCHEMA:
            conn.execute("DROP TABLE IF EXISTS vectors")
            conn.execute("INSERT OR REPLACE INTO meta VALUES ('schema', ?)", (SCHEMA,))
        conn.execute("CREATE TABLE IF NOT EXISTS vectors (ref TEXT, kind TEXT, hash TEXT, model TEXT, dim INTEGER, "
                     "vec BLOB, PRIMARY KEY (ref, kind))")
        conn.commit()
    except sqlite3.DatabaseError:
        conn.close()
        path.unlink(missing_ok=True)   # damaged: disposable, rebuilt
        conn = sqlite3.connect(path, timeout=5)
        conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO meta VALUES ('schema', ?)", (SCHEMA,))
        conn.execute("CREATE TABLE vectors (ref TEXT, kind TEXT, hash TEXT, model TEXT, dim INTEGER, vec BLOB, "
                     "PRIMARY KEY (ref, kind))")
        conn.commit()
    return conn


def _rows(conn: sqlite3.Connection) -> dict[tuple[str, str], tuple[str, str, np.ndarray]]:
    out = {}
    for ref, kind, h, model, dim, blob in conn.execute("SELECT ref, kind, hash, model, dim, vec FROM vectors"):
        out[(ref, kind)] = (h, model, np.frombuffer(blob, dtype=np.float32, count=int(dim)))
    return out


def _unit(v) -> np.ndarray:
    v = np.asarray(v, dtype=np.float32).reshape(-1)
    return v / max(float(np.linalg.norm(v)), 1e-12)


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def refresh(memory_path, emb: Embedders | None, *, refs=None, limit: int | None = REFRESH_LIMIT) -> dict:
    """Bring the index up to the board: embed what is missing or stale (at most ``limit`` pictures), drop rows of
    references that are gone. ``{"images": n, "notes": n, "failed": n}``; never raises on a picture or a model."""
    refs = design_refs.list_refs(memory_path) if refs is None else refs
    path = index_path(memory_path)
    counts = {"images": 0, "notes": 0, "failed": 0}
    with _lock(path):
        conn = _connect(path)
        try:
            have = _rows(conn)
            live = {r.id for r in refs}
            gone = [key for key in have if key[0] not in live]
            conn.executemany("DELETE FROM vectors WHERE ref=? AND kind=?", gone)
            if emb is None:
                conn.commit()
                return counts
            if emb.image is not None:
                for ref in refs:
                    if limit is not None and counts["images"] + counts["failed"] >= limit:
                        break
                    sha = (ref.image or {}).get("sha256") or ""
                    old = have.get((ref.id, "image"))
                    if not sha or (old and old[0] == sha and old[1] == emb.model):
                        continue
                    found = design_refs.image_file(memory_path, ref)
                    if found is None:
                        continue
                    try:
                        vec = _unit(emb.image(found[0].read_bytes()))
                    except Exception as exc:  # noqa: BLE001 — one bad picture never stops the rest
                        counts["failed"] += 1
                        logger.debug(f"design_index: a picture didn't embed ({type(exc).__name__})")
                        continue
                    conn.execute("INSERT OR REPLACE INTO vectors VALUES (?, 'image', ?, ?, ?, ?)",
                                 (ref.id, sha, emb.model, int(vec.size), vec.tobytes()))
                    counts["images"] += 1
            if emb.text is not None:
                todo = []
                for ref in refs:
                    text = design_refs.describe_for_embedding(ref)
                    old = have.get((ref.id, "note"))
                    if text and not (old and old[0] == _text_hash(text) and old[1] == emb.model):
                        todo.append((ref.id, text))
                if todo:
                    try:
                        vecs = np.asarray(emb.text([t for _, t in todo], False), dtype=np.float32)
                    except Exception as exc:  # noqa: BLE001 — the notes wait for the next call
                        counts["failed"] += len(todo)
                        logger.debug(f"design_index: notes didn't embed ({type(exc).__name__})")
                        vecs = None
                    if vecs is not None:
                        for (rid, text), v in zip(todo, vecs):
                            v = _unit(v)
                            conn.execute("INSERT OR REPLACE INTO vectors VALUES (?, 'note', ?, ?, ?, ?)",
                                         (rid, _text_hash(text), emb.model, int(v.size), v.tobytes()))
                            counts["notes"] += 1
            conn.commit()
        finally:
            conn.close()
    return counts


_BG: dict[str, threading.Thread] = {}


def refresh_in_background(memory_path, *, embedders: Callable[[], Embedders | None] = None) -> bool:
    """After a save: embed the new reference off the request, one run per bank at a time; never while Sleep runs
    (the next search catches up)."""
    from api.services import sleep_cycle

    if sleep_cycle.get_sleep_state().status == "running":
        return False
    key = str(Path(memory_path).resolve())
    with _LOCKS_GUARD:
        running = _BG.get(key)
        if running is not None and running.is_alive():
            return False

        def run() -> None:
            try:
                refresh(memory_path, (embedders or default_embedders)())
            except Exception as exc:  # noqa: BLE001 — the next search tries again
                logger.debug(f"design_index: background refresh skipped ({type(exc).__name__})")

        thread = threading.Thread(target=run, name="cicada-design-index", daemon=True)
        _BG[key] = thread
    thread.start()
    return True


def status(memory_path) -> dict:
    """How many references have each kind of vector (for the board's footnote)."""
    path = index_path(memory_path)
    if not path.is_file():
        return {"images": 0, "notes": 0}
    try:
        conn = sqlite3.connect(path, timeout=5)
        try:
            rows = dict(conn.execute("SELECT kind, COUNT(*) FROM vectors GROUP BY kind").fetchall())
        finally:
            conn.close()
    except sqlite3.DatabaseError:
        return {"images": 0, "notes": 0}
    return {"images": int(rows.get("image", 0)), "notes": int(rows.get("note", 0))}


# --------------------------------------------------------------------------- search


def _tokens(text: str) -> list[str]:
    return [t for t in _WORD.findall((text or "").lower()) if len(t) >= 2]


def word_scores(refs, query: str) -> dict[str, float]:
    """Whole word 2, prefix 1, per query word; the exact phrase in the title or note adds 3."""
    terms = _tokens(query)
    phrase = " ".join((query or "").lower().split())
    scores: dict[str, float] = {}
    for ref in refs:
        hay = design_refs.words(ref)
        words = set(_tokens(hay))
        score = 0.0
        for t in terms:
            if t in words:
                score += 2
            elif any(w.startswith(t) for w in words):
                score += 1
        if score and len(terms) > 1 and phrase and phrase in f"{ref.title} {ref.note}".lower():
            score += 3
        if score:
            scores[ref.id] = score
    return scores


def _ranked(vectors: dict[str, np.ndarray], query: np.ndarray) -> list[tuple[str, float]]:
    if not vectors:
        return []
    ids = list(vectors)
    mat = np.vstack([vectors[i] for i in ids])
    if mat.shape[1] != query.size:
        return []
    sims = mat @ query
    order = np.argsort(-sims, kind="stable")
    return [(ids[i], float(sims[i])) for i in order]


def _close(ranking: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """A meaning leg keeps only the hits within ``RELATIVE_FLOOR`` of its best cosine: a model's similarities sit in
    a band that depends on the pair (text–image ≈ 0.2–0.35, text–text ≈ 0.5–0.8), so an absolute floor would be a
    guess per model; "nearly as close as the closest" is not."""
    if not ranking:
        return ranking
    best = ranking[0][1]
    if best <= 0:
        return ranking[:1]
    return [(rid, sim) for rid, sim in ranking if sim >= best * RELATIVE_FLOOR]


def search(memory_path, *, query: str | None = None, image: bytes | None = None, limit: int = 24,
           emb: Embedders | None | str = "default", embed: bool = True) -> dict:
    """``{"results": [{"id", "score", "legs"}], "mode", "missing"}``. ``mode`` names the legs that ran; ``missing``
    says why a leg didn't (``image_model`` — the image encoder isn't here; ``model`` — no EmbeddingGemma 2).

    **Order (review 2026-10-14):** a text query's results are tiered — every reference the words found comes first,
    in fused order, then the references only a meaning leg found — and a meaning leg keeps only hits close to its best
    (``_close``), so a word search never returns the whole board. ``embed=False`` (Sleep is running) answers from the
    vectors already stored and embeds nothing new for the board."""
    refs = design_refs.list_refs(memory_path)
    if emb == "default":
        emb = default_embedders()
    query = (query or "").strip()
    legs: dict[str, list[tuple[str, float]]] = {}
    missing: list[str] = []
    if query:
        words = word_scores(refs, query)
        if words:
            legs["words"] = sorted(words.items(), key=lambda kv: (-kv[1], kv[0]))
    if emb is not None:
        if embed:
            refresh(memory_path, emb, refs=refs)
        conn = _connect(index_path(memory_path))
        try:
            have = _rows(conn)
        finally:
            conn.close()
        images = {r: v for (r, k), (_, m, v) in have.items() if k == "image" and m == emb.model}
        notes = {r: v for (r, k), (_, m, v) in have.items() if k == "note" and m == emb.model}
        if query and emb.text is not None:
            try:
                q = _unit(np.asarray(emb.text([query], True))[0])
            except Exception as exc:  # noqa: BLE001 — the word leg still answers
                logger.debug(f"design_index: the query didn't embed ({type(exc).__name__})")
                q = None
            if q is not None:
                if images:
                    legs["picture"] = _close(_ranked(images, q))
                if notes:
                    legs["note"] = _close(_ranked(notes, q))
        if image is not None:
            if emb.image is None:
                missing.append("image_model")
            else:
                try:
                    v = _unit(emb.image(image))
                except Exception as exc:  # noqa: BLE001 — said, not raised
                    logger.debug(f"design_index: the example picture didn't embed ({type(exc).__name__})")
                    v = None
                if v is not None and images:
                    legs["picture"] = _close(_ranked(images, v))
        if emb.image is None and "image_model" not in missing:
            missing.append("image_model")
    else:
        missing.append("model")
        if image is not None:
            missing.append("image_model")
    fused: dict[str, float] = {}
    hits: dict[str, list[str]] = {}
    for leg, ranking in legs.items():
        for rank, (rid, _score) in enumerate(ranking):
            fused[rid] = fused.get(rid, 0.0) + 1.0 / (RRF_K + rank + 1)
            hits.setdefault(rid, []).append(leg)
    if not query and image is None:
        results = [{"id": r.id, "score": 0.0, "legs": []} for r in refs[:limit]]
    else:
        worded = set(dict(legs.get("words", [])))
        order = sorted(fused, key=lambda rid: (rid not in worded, -fused[rid], rid))[:limit]
        results = [{"id": rid, "score": round(fused[rid], 6), "legs": hits[rid]} for rid in order]
    return {"results": results, "mode": "+".join(sorted(legs)) or "none", "missing": missing}
