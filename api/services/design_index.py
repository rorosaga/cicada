"""Search the design board by words, by meaning or by an example picture (design taste, 2026-10-14).

**Derived and disposable, in the one meaning index** (meaning index 2, 2026-10-28: the ``look_vectors`` table of the
bank's ``vector_index.db``, git-ignored and never copied or exported with the bank; the board's own file under
``$CICADA_HOME/design-index/`` is folded in once and deleted, :func:`_migrate`): one row per reference and kind — ``image`` (the screenshot's EmbeddingGemma 2 vector,
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
    #: The image encoder's preprocessing fingerprint (`vision_embedder.fingerprint`): an image row is current only
    #: while its stamp matches the model AND this (vision item 3, 2026-10-28). None: rows are stamped with the model.
    image_fingerprint: str | None = None

    def image_current(self, stored: str) -> bool:
        from api.services import vision_embedder

        if self.image_fingerprint is None:
            return stored == self.model
        return vision_embedder.stamp_current(stored, self.model, self.image_fingerprint)

    @property
    def image_stamp(self) -> str:
        from api.services import vision_embedder

        return self.model if self.image_fingerprint is None else vision_embedder.stamp_for(self.model,
                                                                                           self.image_fingerprint)


def default_embedders(environ=None) -> Embedders | None:
    """EmbeddingGemma 2 with its image encoder when both are here; its text encoder alone when only that is; else
    None (words only). Never downloads anything."""
    from api.services import onnx_embedder, providers, vision_embedder

    environ = os.environ if environ is None else environ
    from api.services import embed_worker

    vision = vision_embedder.get(environ)
    if vision is not None:
        try:
            fp = vision_embedder.fingerprint()
        except Exception:  # noqa: BLE001 — a decoder that cannot run embeds no picture anyway
            fp = None
        image = vision.embed
        if embed_worker.enabled(environ):
            # Vision item 3 (2026-10-28): every picture vector is made in the picture child, never in the backend —
            # a Core ML predict holds the GIL and the image encoder is ~300 MB (``embed_worker`` "Pictures too").
            # Only the image encoder's folder is read here; the text half of `vision` loads only for a query.
            in_child = embed_worker.images(onnx_embedder.PREFERRED_ID)   # one picture child for every caller

            def image(data: bytes) -> np.ndarray:
                row = np.asarray(in_child([data]), dtype=np.float32)[0]
                if not np.all(np.isfinite(row)):
                    raise ValueError("the picture didn't embed")
                return row
        return Embedders(model=vision.model_id or onnx_embedder.PREFERRED_ID, image=image,
                         text=lambda texts, q: vision.embed_text(texts, is_query=q), image_fingerprint=fp)
    if onnx_embedder.find(onnx_embedder.PREFERRED_ID, environ) is None:
        return None
    try:
        fn, model = providers.cached_embed_fn_for_model(onnx_embedder.PREFERRED_ID)
    except Exception:  # noqa: BLE001 — no model, words only
        return None
    return Embedders(model=model, text=lambda texts, q: fn(texts, is_query=q))


# --------------------------------------------------------------------------- the file


def index_path(memory_path, environ=None) -> Path:
    """The one meaning index of the bank (``vector_index.db``): the board's rows are its ``look_vectors`` table
    (meaning index 2, 2026-10-28). Derived and disposable like every vector there — git-ignored, never copied or
    exported with the bank (``bank_registry.DERIVED_ARTIFACTS``)."""
    from api.services.vector_index import INDEX_DB_FILE

    return Path(memory_path) / INDEX_DB_FILE


def legacy_path(memory_path, environ=None) -> Path:
    """Where the board's own file lived before it joined the one index (``$CICADA_HOME/design-index/<bank-id>``);
    read once by :func:`_migrate`, then deleted."""
    from api.services import continuity_sessions, runtime_layout

    home = runtime_layout.cicada_home(os.environ if environ is None else environ)
    return home / INDEX_DIR / f"{continuity_sessions.bank_file_id(Path(memory_path))}.sqlite"


_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()
TABLE = "look_vectors"
SCHEMA_KEY = "schema:looks"
_COLUMNS = "(ref TEXT, kind TEXT, hash TEXT, model TEXT, dim INTEGER, vec BLOB, PRIMARY KEY (ref, kind))"


def _lock(path: Path) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(str(path), threading.Lock())


def _open(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=5)
    conn.execute("CREATE TABLE IF NOT EXISTS index_meta (key TEXT PRIMARY KEY, value TEXT)")
    got = conn.execute("SELECT value FROM index_meta WHERE key = ?", (SCHEMA_KEY,)).fetchone()
    if got is None or got[0] != SCHEMA:
        conn.execute(f"DROP TABLE IF EXISTS {TABLE}")
        conn.execute("INSERT OR REPLACE INTO index_meta(key, value) VALUES (?, ?)", (SCHEMA_KEY, SCHEMA))
    conn.execute(f"CREATE TABLE IF NOT EXISTS {TABLE} {_COLUMNS}")
    conn.commit()
    return conn


def _connect(path: Path, memory_path=None) -> sqlite3.Connection:
    """The board's table in the one index, created on first use, with the old separate file folded in once
    (:func:`_migrate`). A file that is not a database is unusable to every kind: it is removed and rebuilt (every
    vector in it is derived), never an error."""
    from api.services.vector_index import _write_lock

    path.parent.mkdir(parents=True, exist_ok=True)
    with _write_lock(path):
        try:
            conn = _open(path)
        except sqlite3.DatabaseError:
            logger.warning("design_index: the meaning index file was damaged; it is rebuilt")
            for p in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
                p.unlink(missing_ok=True)
            conn = _open(path)
        if memory_path is not None:
            _migrate(conn, memory_path)
    return conn


def _migrate(conn: sqlite3.Connection, memory_path) -> int:
    """Move the rows of the board's old file into the one index, then delete the file (meaning index 2). A row
    already in the index wins; an unreadable old file is simply deleted (its vectors are re-embedded). Returns the
    rows moved. Caller holds the index's write lock."""
    old = legacy_path(memory_path)
    if not old.is_file():
        return 0
    moved = 0
    try:
        src = sqlite3.connect(f"file:{old}?mode=ro", uri=True, timeout=5)
        try:
            schema = src.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
            rows = src.execute("SELECT ref, kind, hash, model, dim, vec FROM vectors").fetchall() \
                if schema and schema[0] == SCHEMA else []
        finally:
            src.close()
        before = conn.total_changes
        conn.executemany(f"INSERT OR IGNORE INTO {TABLE} VALUES (?, ?, ?, ?, ?, ?)", rows)
        conn.commit()
        moved = conn.total_changes - before
    except sqlite3.DatabaseError as exc:
        logger.debug(f"design_index: the old board file was unreadable ({type(exc).__name__}); its rows re-embed")
    for p in (old, Path(f"{old}-wal"), Path(f"{old}-shm")):
        p.unlink(missing_ok=True)
    try:
        old.parent.rmdir()   # the folder goes with its last bank's file
    except OSError:
        pass
    if moved:
        logger.info(f"design_index: {moved} look vector(s) moved into the meaning index")
    return moved


def _rows(conn: sqlite3.Connection) -> dict[tuple[str, str], tuple[str, str, np.ndarray]]:
    out = {}
    for ref, kind, h, model, dim, blob in conn.execute(f"SELECT ref, kind, hash, model, dim, vec FROM {TABLE}"):
        out[(ref, kind)] = (h, model, np.frombuffer(blob, dtype=np.float32, count=int(dim)))
    return out


def read_rows(memory_path) -> dict[tuple[str, str], tuple[str, str, np.ndarray]]:
    """``{(ref, kind): (hash, stamp, vector)}`` of the board's rows, or ``{}`` (for ``image_index``, which reuses a
    look's current picture vector instead of embedding it twice)."""
    path = index_path(memory_path)
    if not path.is_file():
        return {}
    try:
        conn = sqlite3.connect(path, timeout=5)
        try:
            return _rows(conn)
        finally:
            conn.close()
    except sqlite3.DatabaseError:
        return {}


def _unit(v) -> np.ndarray:
    v = np.asarray(v, dtype=np.float32).reshape(-1)
    return v / max(float(np.linalg.norm(v)), 1e-12)


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def refresh(memory_path, emb: Embedders | None, *, refs=None, limit: int | None = REFRESH_LIMIT) -> dict:
    """Bring the index up to the board: embed what is missing or stale (at most ``limit`` pictures), drop rows of
    references that are gone. ``{"images": n, "notes": n, "failed": n}``; never raises on a picture or a model.
    Everything is embedded first and written after, in one short transaction under the index's one write lock —
    the file is shared with the text kinds, so it is never held across an embed."""
    from api.services.vector_index import _write_lock

    refs = design_refs.list_refs(memory_path) if refs is None else refs
    path = index_path(memory_path)
    counts = {"images": 0, "notes": 0, "failed": 0}
    with _lock(path):
        conn = _connect(path, memory_path)
        try:
            have = _rows(conn)
            live = {r.id for r in refs}
            gone = [key for key in have if key[0] not in live]
            writes: list[tuple] = []
            if emb is not None and emb.image is not None:
                for ref in refs:
                    if limit is not None and counts["images"] + counts["failed"] >= limit:
                        break
                    sha = (ref.image or {}).get("sha256") or ""
                    old = have.get((ref.id, "image"))
                    if not sha or (old and old[0] == sha and emb.image_current(old[1])):
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
                    writes.append((ref.id, "image", sha, emb.image_stamp, int(vec.size), vec.tobytes()))
                    counts["images"] += 1
            if emb is not None and emb.text is not None:
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
                            writes.append((rid, "note", _text_hash(text), emb.model, int(v.size), v.tobytes()))
                            counts["notes"] += 1
            if gone or writes:
                with _write_lock(path):
                    conn.executemany(f"DELETE FROM {TABLE} WHERE ref=? AND kind=?", gone)
                    conn.executemany(f"INSERT OR REPLACE INTO {TABLE} VALUES (?, ?, ?, ?, ?, ?)", writes)
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
    if not path.is_file() and not legacy_path(memory_path).is_file():
        return {"images": 0, "notes": 0}
    try:
        conn = _connect(path, memory_path)
        try:
            rows = dict(conn.execute(f"SELECT kind, COUNT(*) FROM {TABLE} GROUP BY kind").fetchall())
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
        conn = _connect(index_path(memory_path), memory_path)
        try:
            have = _rows(conn)
        finally:
            conn.close()
        images = {r: v for (r, k), (_, m, v) in have.items() if k == "image" and emb.image_current(m)}
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


def similar(memory_path, ref_id: str, *, limit: int = 8, emb: Embedders | None | str = "default",
            embed: bool = True) -> dict:
    """Looks like one already saved (owner 2026-10-20: a page's look shows its similar looks) — same answer shape as
    :func:`search`, the look itself left out. The look's own stored picture vector is the query (nothing is embedded
    for it again); without one, its look words, fonts and site are, through the word leg — so a Mac with no search
    model still answers, said in ``missing``."""
    refs = design_refs.list_refs(memory_path)
    me = next((r for r in refs if r.id == ref_id), None)
    if me is None:
        return {"results": [], "mode": "none", "missing": []}
    if emb == "default":
        emb = default_embedders()
    legs: dict[str, list[tuple[str, float]]] = {}
    missing: list[str] = []
    if emb is not None:
        if embed:
            refresh(memory_path, emb, refs=refs)
        conn = _connect(index_path(memory_path), memory_path)
        try:
            have = _rows(conn)
        finally:
            conn.close()
        images = {r: v for (r, k), (_, m, v) in have.items() if k == "image" and emb.image_current(m)}
        mine = images.pop(ref_id, None)
        if mine is not None and images:
            legs["picture"] = _close(_ranked(images, mine))
        if emb.image is None:
            missing.append("image_model")
    else:
        missing.append("model")
    if not legs:
        words = " ".join([*me.look, *design_refs.fonts(me)])
        scores = {rid: s for rid, s in word_scores([r for r in refs if r.id != ref_id], words).items()} if words else {}
        if scores:
            legs["words"] = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    fused: dict[str, float] = {}
    hits: dict[str, list[str]] = {}
    for leg, ranking in legs.items():
        for rank, (rid, _score) in enumerate(ranking):
            if rid == ref_id:
                continue
            fused[rid] = fused.get(rid, 0.0) + 1.0 / (RRF_K + rank + 1)
            hits.setdefault(rid, []).append(leg)
    order = sorted(fused, key=lambda rid: (-fused[rid], rid))[:max(1, int(limit))]
    return {"results": [{"id": rid, "score": round(fused[rid], 6), "legs": hits[rid]} for rid in order],
            "mode": "+".join(sorted(legs)) or "none", "missing": missing}
