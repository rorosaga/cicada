"""Pictures in the one meaning index (vision item 3, 2026-10-28; G195's first image slice).

The owner: "Video, images, articles, websites, audios, etc should be in the same embedding space with the Gemma model
we have for embeddings. All running locally." Text already lives in ``vector_index.db`` (entities, claims, episodes,
pending). This module adds **pictures as one more kind of that same file** — ``vec_images`` / ``meta_images`` beside
the others, stamped ``model:images`` / ``dim:images`` / ``recipe:images`` — embedded by EmbeddingGemma 2's image
encoder, which puts a picture in the text model's 768-wide space, so a text query is compared with pictures by one
cosine.

**Which pictures** (:func:`sources`) — only ones Cicada already holds, never a byte fetched for this:

* ``look`` — a saved look's screenshot (``design_refs``, in the bank);
* ``capture`` — the newest in-bank thumbnail of a saved site's captures (``site_captures``; a capture that showed the
  person's own account keeps its thumbnail outside the bank and is not indexed);
* ``preview`` — a saved link's, video's or paper's stored preview (``media_preview``, outside every bank);
* ``still`` — a YouTube video's stored still, for a saved video page or a watched day (``media_preview``'s
  ``watched/`` store, outside every bank). A still is YouTube's own picture for the id, never a frame: Cicada never
  downloads a video or derives a stream (G162). A watched day's still is indexed, never read by a model that writes
  memory (ruling 30: watch history is "found through the lexical and vector indexes").

**Derived and disposable.** Each row's ``hash`` is the picture's sha256 plus :func:`recipe` (the preprocessing: the
vision function's token budget and the sizing rule), so a changed picture, a new model or a new recipe re-embeds
exactly that row; deleting the file costs a re-embed and never a picture. The query is never logged.

**Scores (measured: ``benchmarks.perf.image_fusion`` on synthetic vectors, ``benchmarks.perf.image_index_build`` on
the real encoder).** A text query's cosine to a matching picture is below its cosine to an unrelated passage (the
modality gap), so a picture is scored against *its own kind*: its **lift**, ``cos − μ``, where μ is the query's exact
mean cosine over every picture — exact, and one dot product with the kind's mean vector (``stats_images``, written
with the table), so no query scans it. A picture is a hit only at ``lift ≥ LIFT_MIN``, so "nothing found" is an
answer. Reciprocal rank (the text kinds' fusion) was rejected: it put a picture in the top five of every
documents-only query. A z-score (lift over the query's own spread, DigUp's recipe) was rejected for the floor: on the
real encoder a query about nothing pictured has a tiny spread, which lifts its best unrelated picture to the z of a
right one; the undivided lift separates them.

**When it embeds.** Only :func:`refresh`, run by the background refresher (:func:`start_refresh`) — after the backend
starts, after a Sleep run ends, after the image encoder is installed, and a little after a new picture is stored —
never by Sleep, never while Sleep runs (it gives way between batches), never on a search. The vectors are made in the
picture child (``embed_worker.images``: lower priority, ≤ 4 cores, a memory ceiling), never in the backend, and only
where the person's click installed the image encoder. A search embeds only the query's words, with the text model
the table records — the image encoder is never loaded to search, so the prompt hook's 300 ms and the palette's prefix
pass never touch it (the prefix pass never reaches this module at all).
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np
from loguru import logger

KIND = "images"
#: A picture is a hit only when its cosine to the query is at least this far above the query's mean cosine over every
#: picture (its *lift*). Calibrated on the real image encoder (``benchmarks.perf.image_index_build``): a picture the
#: query describes lifts 0.10–0.15, a near miss (the right shape, another colour) ≈ 0.08, the best picture for a query
#: about nothing drawn ≤ 0.03.
LIFT_MIN = 0.06
#: Pictures embedded per step of a refresh; the refresh checks for Sleep between steps.
STEP = 16
#: A trigger after a picture is stored waits this long, so a burst of stored previews is one refresh.
SETTLE_S = 30.0
#: The two generations of the picture table. Search reads the one ``serving:images`` names; a model or preprocessing
#: change builds the other and swaps the pointer in one transaction, so search keeps the old pictures until the new
#: set is complete (the vector rail: "recall keeps the old table until the new one commits").
GENERATIONS = (KIND, f"{KIND}_alt")
SERVING_KEY = f"serving:{KIND}"


def recipe() -> str | None:
    """The preprocessing a picture's vector depends on besides its bytes and the model — the ONE stamp both picture
    stores use (``vision_embedder.fingerprint``: the recipe plus a reference picture through the real decoder, so a
    decoder change re-embeds too). None where the decoder cannot run here (then no picture is embedded either)."""
    from api.services import vision_embedder

    try:
        return vision_embedder.fingerprint()
    except Exception:  # noqa: BLE001 — no decoder, no picture vectors; what is stored stays
        return None


# --------------------------------------------------------------------------- what is indexed


@dataclass
class Picture:
    """One picture Cicada holds, and where it came from (all ids, never a path, on the wire)."""
    key: str                       # "<source>:<id>", the row's stable key
    source: str                    # look | capture | preview | still
    path: Path
    title: str = ""
    entity_id: str | None = None
    episode_id: str | None = None
    video_id: str | None = None
    capture_id: str | None = None
    look_id: str | None = None
    day: str | None = None
    thumb: str = ""                # the API path the app (or a local agent) loads it from
    sha: str | None = None         # the content hash when the source already recorded one

    def meta(self) -> dict:
        out = {"source": self.source, "title": self.title, "thumb": self.thumb}
        for name in ("entity_id", "episode_id", "video_id", "capture_id", "look_id", "day"):
            value = getattr(self, name)
            if value:
                out[name] = value
        return out


def _looks(memory_path: Path) -> list[Picture]:
    from api.services import design_refs

    out = []
    for ref in design_refs.list_refs(memory_path):
        found = design_refs.image_file(memory_path, ref)
        if found is None:
            continue
        out.append(Picture(f"look:{ref.id}", "look", found[0], title=ref.title or ref.site or "A look",
                           entity_id=ref.entity or None, look_id=ref.id, day=(ref.captured or "")[:10] or None,
                           thumb=f"/design/{ref.id}/image", sha=(ref.image or {}).get("sha256") or None))
    return out


def _captures(memory_path: Path, names: dict[str, str]) -> list[Picture]:
    from api.services import site_captures

    root = Path(memory_path) / site_captures.CAPTURES_DIR
    if not root.is_dir():
        return []
    out = []
    for folder in sorted(p for p in root.iterdir() if p.is_dir() and site_captures.ENTITY_RE.match(p.name)):
        for cap in site_captures.list_captures(memory_path, folder.name):
            thumb = cap.get("thumb") if isinstance(cap.get("thumb"), dict) else None
            path = site_captures.thumb_file(memory_path, (thumb or {}).get("file")) if thumb else None
            if path is None:
                continue
            out.append(Picture(f"capture:{folder.name}", "capture", path,
                               title=str(cap.get("title") or names.get(folder.name) or folder.name),
                               entity_id=folder.name, capture_id=cap["id"],
                               day=str(cap.get("captured_at") or "")[:10] or None,
                               thumb=f"/explore/captures/{folder.name}/{cap['id']}/thumb",
                               sha=str((thumb or {}).get("sha256") or "") or None))
            break   # the newest look only: an older one is history, not what the site looks like
    return out


def _media(memory_path: Path) -> tuple[list[Picture], dict[str, str]]:
    from api.services import bank_index, channel_items, logo_service, media_preview

    bank = logo_service.bank_name(Path(memory_path))
    out: list[Picture] = []
    names: dict[str, str] = {}
    for f in bank_index.files(Path(memory_path), "entities"):
        fm = f.frontmatter or {}
        names[f.stem] = str(fm.get("name") or f.stem)
        if fm.get("type") != "media" or fm.get("status") == "dropped":
            continue
        title = str(fm.get("name") or f.stem)
        stored = media_preview.stored_file(bank, f.stem)
        if stored is not None:
            out.append(Picture(f"preview:{f.stem}", "preview", stored, title=title, entity_id=f.stem,
                               thumb=media_preview.preview_path(f.stem, fm) or f"/entities/{f.stem}/preview"))
            continue
        media = fm.get("media") if isinstance(fm.get("media"), dict) else {}
        url = str(fm.get("url") or media.get("url") or "")
        vid = media_preview.youtube_video_id(url) if url else None
        if vid and channel_items.is_saved_link_page(fm):
            still = media_preview.stored_still(bank, vid)
            if still is not None:
                out.append(Picture(f"still:{vid}", "still", still, title=title, entity_id=f.stem, video_id=vid,
                                   thumb=f"/sources/saved/{f.stem}/still"))
    return out, names


def _watched(memory_path: Path, have: set[str]) -> list[Picture]:
    """A watched day's videos whose still is already stored (a still is asked for only when the person opened that
    day). One row per video — its latest day — and none for a video a saved page already gave."""
    from api.services import bank_index, channel_items, history_index, logo_service, media_preview, video_urls, \
        watch_history

    bank = logo_service.bank_name(Path(memory_path))
    if not (media_preview._root(bank) / media_preview.WATCHED_DIR).is_dir():
        return []
    best: dict[str, Picture] = {}
    for f in bank_index.files(Path(memory_path), "episodes"):
        fm = f.frontmatter or {}
        if (str(fm.get("origin") or "") != watch_history.ORIGINS["youtube"] or fm.get("source_deleted_at")
                or history_index.kind(fm) == "month"):
            continue
        day = str(fm.get("watched_on") or fm.get("original_date") or "")[:10]
        for row in (fm.get("watched") or [])[:channel_items.DAY_VIDEOS_MAX]:
            if not isinstance(row, dict):
                continue
            ref = video_urls.resolve(str(row.get("url") or ""))
            if ref is None or ref.provider != "youtube" or f"still:{ref.video_id}" in have:
                continue
            seen = best.get(ref.video_id)
            if seen is not None and (seen.day or "") >= day:
                continue
            still = media_preview.stored_still(bank, ref.video_id)
            if still is None:
                continue
            best[ref.video_id] = Picture(
                f"still:{ref.video_id}", "still", still, title=str(row.get("title") or "A video you watched"),
                episode_id=f.stem, video_id=ref.video_id, day=day or None,
                thumb=f"/sources/watch-history/days/{f.stem}/videos/{ref.video_id}/thumbnail")
    return list(best.values())


def sources(memory_path) -> list[Picture]:
    """Every picture this bank's records point at that is on this Mac now, one per key."""
    memory_path = Path(memory_path)
    media, names = _media(memory_path)
    pictures = [*_looks(memory_path), *_captures(memory_path, names), *media]
    pictures += _watched(memory_path, {p.key for p in pictures})
    seen: dict[str, Picture] = {}
    for p in pictures:
        seen.setdefault(p.key, p)
    return list(seen.values())


# --------------------------------------------------------------------------- the table


def _db(memory_path) -> Path:
    from api.services.vector_index import INDEX_DB_FILE

    return Path(memory_path) / INDEX_DB_FILE


def _connect(memory_path) -> sqlite3.Connection:
    from api.services.vector_index import SqliteVecIndexer

    return SqliteVecIndexer(Path(memory_path))._connect()


def _stamps(conn: sqlite3.Connection) -> dict[str, str]:
    try:
        return dict(conn.execute("SELECT key, value FROM index_meta").fetchall())
    except sqlite3.OperationalError:
        return {}


def _has_table(conn: sqlite3.Connection, gen: str = KIND) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (f"meta_{gen}",)).fetchone() is not None


def _serving(conn: sqlite3.Connection, stamps: dict[str, str] | None = None) -> str:
    """The generation search reads: the one ``serving:images`` names, else the first (a table written before
    generations, or none yet)."""
    gen = (stamps if stamps is not None else _stamps(conn)).get(SERVING_KEY) or KIND
    return gen if gen in GENERATIONS else KIND


def _rows(conn: sqlite3.Connection, gen: str = KIND) -> dict[str, tuple[int, str]]:
    if not _has_table(conn, gen):
        return {}
    return {key: (rowid, h) for rowid, key, h in conn.execute(f"SELECT rowid, key, hash FROM meta_{gen}")}


def _drop(conn: sqlite3.Connection, gen: str) -> None:
    for table in (f"vec_{gen}", f"meta_{gen}", f"stats_{gen}"):
        conn.execute(f"DROP TABLE IF EXISTS {table}")
    try:
        conn.executemany("DELETE FROM index_meta WHERE key = ?",
                         [(f"model:{gen}",), (f"dim:{gen}",), (f"recipe:{gen}",)])
    except sqlite3.OperationalError:
        pass


def _sha(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _model_for_images() -> str | None:
    """The text model an image vector belongs to (EmbeddingGemma 2, at its full width), as ``vector_index`` names
    it — so a text query is embedded with the model the table records and shares recall's cached query vector."""
    from api.services import onnx_embedder, providers

    try:
        _fn, model = providers.cached_embed_fn_for_model(onnx_embedder.PREFERRED_ID)
    except Exception:  # noqa: BLE001 — no text model here, no picture vectors
        return None
    return model or None


def default_embedder() -> tuple[Callable[[list[bytes]], np.ndarray], str] | None:
    """``(fn(list[bytes]) -> [n, d], model)`` where the person installed the image encoder, else None. The vectors
    are made in the picture child (``embed_worker.images``); with the child off (the suite) in this process."""
    from api.services import embed_worker, onnx_embedder, vision_embedder

    if vision_embedder.folder() is None:
        return None
    model = _model_for_images()
    if model is None:
        return None
    if embed_worker.enabled():
        return embed_worker.images(onnx_embedder.PREFERRED_ID), model   # one picture child for every caller
    vision = vision_embedder.get()
    if vision is None:
        return None
    return embed_worker.picture_rows(vision.embed), model


class RefreshStopped(RuntimeError):
    """The refresh gave way (Sleep started). What was written stays; the next trigger goes on."""


def refresh(memory_path, embedder: tuple[Callable[[list[bytes]], np.ndarray], str] | None | str = "default", *,
            should_stop: Callable[[], bool] | None = None, limit: int | None = None,
            pictures: list[Picture] | None = None) -> dict:
    """Bring the picture table up to the pictures on this Mac: embed what is new or changed (at most ``limit``),
    drop rows whose picture is gone, rewrite the kind's mean. ``{"embedded", "reused", "removed", "failed", "total",
    "rebuilding"}``. Never raises for a picture; raises :class:`RefreshStopped` when ``should_stop`` says so between
    steps (what was written stays).

    **A new model or preprocessing never empties search.** The serving generation is diffed in place only while its
    stamps match; otherwise the other generation is built (resumed across stops when its stamps match) and, once it
    holds every picture, the ``serving:images`` pointer moves to it and the old one is dropped in one transaction.
    Until then search answers from the old generation (``rebuilding: 1`` says a build is under way)."""
    from api.services.vector_index import _write_lock

    memory_path = Path(memory_path)
    if embedder == "default":
        embedder = default_embedder()
    tag = recipe()
    if tag is None:
        embedder = None   # no decoder here: nothing can be embedded; keep what is stored
    counts = {"embedded": 0, "reused": 0, "removed": 0, "failed": 0, "total": 0, "rebuilding": 0}
    pics = sources(memory_path) if pictures is None else pictures
    wanted: dict[str, tuple[Picture, str]] = {}
    for p in pics:
        sha = p.sha or _sha(p.path)
        if sha:
            wanted[p.key] = (p, sha[:32])
    conn = _connect(memory_path)
    try:
        stamps = _stamps(conn)
        serving = _serving(conn, stamps)
        model = embedder[1] if embedder else None

        def matches(gen: str) -> bool:
            return stamps.get(f"model:{gen}") == model and stamps.get(f"recipe:{gen}") == tag

        target = serving
        if embedder and _has_table(conn, serving) and not matches(serving):
            target = next(g for g in GENERATIONS if g != serving)
            counts["rebuilding"] = 1
            if _has_table(conn, target) and not matches(target):
                with _write_lock(_db(memory_path)):
                    _drop(conn, target)   # a build for an older model: start over
                    conn.commit()
        have = _rows(conn, target)
        gone = [k for k in have if k not in wanted]
        todo = [k for k, (_p, h) in wanted.items() if k not in have or have[k][1] != h]
        counts["reused"] = len(wanted) - len(todo)
        if limit is not None:
            todo = todo[: max(0, int(limit))]
        if not embedder:
            todo = []   # no encoder here: keep what is stored, only drop what is gone
        if target != serving:
            # Review of #506: a picture gone leaves the generation search reads NOW, before any embed (a stop for
            # Sleep, or a new generation that never fills, must not keep a deleted picture's title and path).
            served = _rows(conn, serving)
            stale = [k for k in served if k not in wanted]
            if stale:
                with _write_lock(_db(memory_path)):
                    for k in stale:
                        conn.execute(f"DELETE FROM vec_{serving} WHERE rowid = ?", (served[k][0],))
                        conn.execute(f"DELETE FROM meta_{serving} WHERE rowid = ?", (served[k][0],))
                    conn.commit()
                _write_moments(conn, memory_path, serving)
                counts["removed"] += len(stale)
        _embed_into(conn, memory_path, target, todo, wanted, have, embedder, model, tag, counts, should_stop)
        with _write_lock(_db(memory_path)):
            for k in gone:
                rowid = have[k][0]
                conn.execute(f"DELETE FROM vec_{target} WHERE rowid = ?", (rowid,))
                conn.execute(f"DELETE FROM meta_{target} WHERE rowid = ?", (rowid,))
            if target == serving:
                counts["removed"] += len(gone)
            # Metadata moves without its picture moving (a page renamed): refreshed in place, no embed.
            if _has_table(conn, target):
                for k, (p, h) in wanted.items():
                    if k in have and have[k][1] == h:
                        conn.execute(f"UPDATE meta_{target} SET metadata = ?, text = ? WHERE key = ?",
                                     (json.dumps(p.meta()), p.title, k))
            conn.commit()
        if target != serving:
            # Complete = every picture that can be embedded is in the new generation (one that failed is not waited
            # for; one a ``limit`` left out is).
            # Nothing left to embed (no pictures left, or every one fails under the new decoder) completes it too,
            # so the old generation never outlives what it describes.
            needed = set(wanted) - set(counts.get("_failed_keys", []))
            if not needed or (_has_table(conn, target) and set(_rows(conn, target)) >= needed):
                _swap(conn, memory_path, serving, target)
                counts["rebuilding"] = 0
        elif _has_table(conn, target) and (counts["embedded"] or counts["removed"]):
            _write_moments(conn, memory_path, target)
        live = _serving(conn)
        if _has_table(conn, live):
            counts["total"] = int(conn.execute(f"SELECT count(*) FROM meta_{live}").fetchone()[0])
    finally:
        conn.close()
    counts.pop("_failed_keys", None)
    return counts


def _embed_into(conn, memory_path: Path, gen: str, todo: list[str], wanted, have, embedder, model, tag, counts,
                should_stop) -> None:
    from api.services.vector_index import _blob

    failed: list[str] = counts.setdefault("_failed_keys", [])
    # Pictures with the same bytes under two keys (a still saved and watched) are embedded once.
    by_hash: dict[str, np.ndarray] = {}
    for start in range(0, len(todo), STEP):
        if should_stop is not None and should_stop():
            raise RefreshStopped("Sleep started")
        chunk = todo[start : start + STEP]
        fresh = [k for k in chunk if wanted[k][1] not in by_hash]
        blobs, ok_keys = [], []
        for k in fresh:
            try:
                blobs.append(wanted[k][0].path.read_bytes())
                ok_keys.append(k)
            except OSError:
                counts["failed"] += 1
                failed.append(k)
        if blobs:
            try:
                vecs = np.asarray(embedder[0](blobs), dtype=np.float32)
            except Exception as exc:  # noqa: BLE001 — the step waits for the next refresh
                logger.debug(f"image_index: a step didn't embed ({type(exc).__name__})")
                counts["failed"] += len(blobs)
                failed.extend(ok_keys)
                continue
            for k, v in zip(ok_keys, vecs):
                if v.size < 2 or not np.all(np.isfinite(v)):
                    counts["failed"] += 1
                    failed.append(k)
                    continue
                by_hash[wanted[k][1]] = v / max(float(np.linalg.norm(v)), 1e-12)
        rows = [(k, by_hash[wanted[k][1]]) for k in chunk if wanted[k][1] in by_hash]
        if rows:
            _write(conn, memory_path, gen, rows, wanted, have, model, tag, _blob)
            counts["embedded"] += len(rows)


def _write(conn, memory_path: Path, gen: str, rows, wanted, have, model: str, tag: str, blob) -> None:
    from api.services.vector_index import _write_lock

    dim = int(rows[0][1].size)
    with _write_lock(_db(memory_path)):
        if not _has_table(conn, gen):
            conn.execute(f"CREATE VIRTUAL TABLE vec_{gen} USING vec0(embedding float[{dim}] distance_metric=cosine)")
            conn.execute(f"CREATE TABLE meta_{gen} (rowid INTEGER PRIMARY KEY, text TEXT, metadata TEXT, key TEXT, "
                         f"hash TEXT)")
            conn.execute("CREATE TABLE IF NOT EXISTS index_meta (key TEXT PRIMARY KEY, value TEXT)")
        for key, vec in rows:
            pic, h = wanted[key]
            old = have.pop(key, None)
            if old is not None:
                conn.execute(f"DELETE FROM vec_{gen} WHERE rowid = ?", (old[0],))
                conn.execute(f"DELETE FROM meta_{gen} WHERE rowid = ?", (old[0],))
            cur = conn.execute(f"INSERT INTO meta_{gen}(text, metadata, key, hash) VALUES (?, ?, ?, ?)",
                               (pic.title, json.dumps(pic.meta()), key, h))
            conn.execute(f"INSERT INTO vec_{gen}(rowid, embedding) VALUES (?, ?)", (cur.lastrowid, blob(vec)))
        # Only this kind's own stamps: the bank-wide ``model`` / ``dim`` name the text tables' build model.
        conn.executemany("INSERT OR REPLACE INTO index_meta(key, value) VALUES (?, ?)",
                         [(f"model:{gen}", model), (f"dim:{gen}", str(dim)), (f"recipe:{gen}", tag)])
        if _stamps(conn).get(SERVING_KEY) is None:
            conn.execute("INSERT OR REPLACE INTO index_meta(key, value) VALUES (?, ?)", (SERVING_KEY, gen))
        conn.commit()


def _swap(conn, memory_path: Path, old: str, new: str) -> None:
    """The finished generation becomes the one search reads, and the old one goes — one transaction."""
    from api.services.vector_index import _write_lock

    x = _all_vectors(conn, new)
    with _write_lock(_db(memory_path)):
        conn.execute("BEGIN IMMEDIATE")
        _put_mean(conn, new, x)
        conn.execute("INSERT OR REPLACE INTO index_meta(key, value) VALUES (?, ?)", (SERVING_KEY, new))
        _drop(conn, old)
        conn.commit()
    _MOMENTS.clear()


def _all_vectors(conn: sqlite3.Connection, gen: str = KIND) -> np.ndarray:
    if not _has_table(conn, gen):
        return np.zeros((0, 0), dtype=np.float32)
    blobs = [b for (b,) in conn.execute(f"SELECT embedding FROM vec_{gen}")]
    if not blobs:
        return np.zeros((0, 0), dtype=np.float32)
    return np.stack([np.frombuffer(b, dtype=np.float32) for b in blobs])


def _put_mean(conn: sqlite3.Connection, gen: str, x: np.ndarray) -> None:
    conn.execute(f"CREATE TABLE IF NOT EXISTS stats_{gen} (name TEXT PRIMARY KEY, value BLOB)")
    if x.size:
        # The mean is all a search needs (a query's lift is its cosine minus ``q · mean``). The spread a z-score
        # would need is not stored: measured and rejected as a floor (module docstring).
        mu = np.asarray(x, dtype=np.float64).mean(axis=0).astype(np.float32)
        conn.executemany(f"INSERT OR REPLACE INTO stats_{gen}(name, value) VALUES (?, ?)",
                         [("n", str(x.shape[0]).encode()), ("mean", mu.tobytes())])
    else:
        conn.execute(f"DELETE FROM stats_{gen}")


def _write_moments(conn: sqlite3.Connection, memory_path: Path, gen: str = KIND) -> None:
    from api.services.vector_index import _write_lock

    x = _all_vectors(conn, gen)
    with _write_lock(_db(memory_path)):
        _put_mean(conn, gen, x)
        conn.commit()
    _MOMENTS.clear()


#: ``{(db path, generation): (mtime, n, mean)}`` — read once per write of the file, not once per query.
_MOMENTS: dict[tuple[str, str], tuple[float, int, np.ndarray]] = {}


def _read_moments(conn: sqlite3.Connection, memory_path: Path, gen: str | None = None) -> tuple[int, np.ndarray] | None:
    gen = gen or _serving(conn)
    path = str(_db(memory_path))
    try:
        stamp = os.stat(path).st_mtime
        wal = Path(path + "-wal")
        if wal.exists():
            stamp = max(stamp, wal.stat().st_mtime)
    except OSError:
        return None
    hit = _MOMENTS.get((path, gen))
    if hit is not None and hit[0] == stamp:
        return hit[1], hit[2]
    try:
        got = dict(conn.execute(f"SELECT name, value FROM stats_{gen}").fetchall())
    except sqlite3.OperationalError:
        return None
    if not {"n", "mean"} <= set(got):
        return None
    mu = np.frombuffer(got["mean"], dtype=np.float32)
    n = int(got["n"].decode())
    _MOMENTS[(path, gen)] = (stamp, n, mu)
    return n, mu


# --------------------------------------------------------------------------- search


def search(memory_path, query: str, *, top_k: int = 8, embed_fn=None) -> list[dict]:
    """Pictures for ``query``, best first: ``[{"key", "score" (the lift), "cosine", "metadata"}]``, only those at
    ``lift ≥ LIFT_MIN``, from the serving generation. ``[]`` with no picture table, no stored mean, or no text model
    for its query — never an error, never the image encoder, never the query in a log."""
    memory_path = Path(memory_path)
    query = (query or "").strip()
    if not query or not _db(memory_path).exists():
        return []
    try:
        conn = _connect(memory_path)
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"image_index: no index ({type(exc).__name__})")
        return []
    try:
        stamps = _stamps(conn)
        gen = _serving(conn, stamps)
        if not _has_table(conn, gen):
            return []
        stats = _read_moments(conn, memory_path, gen)
        if stats is None:
            return []
        _n, mu = stats
        model = stamps.get(f"model:{gen}")
        try:
            from api.services.vector_index import _cached_query_vector, _named

            if embed_fn is not None:
                qvec = np.asarray(embed_fn([query], is_query=True), dtype=np.float32)[0]
            elif _named(model):
                from api.services.providers import resolve_embed_fn_for_model

                fn, _m = resolve_embed_fn_for_model(model)
                qvec = _cached_query_vector(model, stamps.get(f"dim:{gen}"), query,
                                            lambda: np.asarray(fn([query], is_query=True), dtype=np.float32)[0])
            else:
                return []
            qvec = np.asarray(qvec, dtype=np.float32).reshape(-1)
        except Exception as exc:  # noqa: BLE001 — the class only (K9)
            logger.debug(f"image_index: the query didn't embed ({type(exc).__name__})")
            return []
        if qvec.size != mu.size:
            return []
        qvec = qvec / max(float(np.linalg.norm(qvec)), 1e-12)
        mean = float(qvec @ mu)
        from api.services.vector_index import _blob

        rows = conn.execute(
            f"SELECT v.distance, m.key, m.metadata FROM vec_{gen} v JOIN meta_{gen} m ON m.rowid = v.rowid "
            f"WHERE v.embedding MATCH ? AND k = ? ORDER BY v.distance", (_blob(qvec), int(max(1, top_k)))).fetchall()
    except sqlite3.DatabaseError as exc:
        logger.debug(f"image_index: search failed ({type(exc).__name__})")
        return []
    finally:
        conn.close()
    out = []
    for distance, key, meta in rows:
        cos = 1.0 - float(distance)
        lift = cos - mean
        if lift < LIFT_MIN:
            break
        out.append({"key": key, "score": round(lift, 4), "cosine": round(cos, 4),
                    "metadata": json.loads(meta) if meta else {}})
    return out


def status(memory_path) -> dict:
    """``{"pictures": n, "model": ...}`` — how many pictures search reads now (0 with no table)."""
    db = _db(memory_path)
    if not db.exists():
        return {"pictures": 0}
    try:
        conn = _connect(memory_path)
        try:
            stamps = _stamps(conn)
            gen = _serving(conn, stamps)
            if not _has_table(conn, gen):
                return {"pictures": 0}
            n = int(conn.execute(f"SELECT count(*) FROM meta_{gen}").fetchone()[0])
            return {"pictures": n, "model": stamps.get(f"model:{gen}")}
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        return {"pictures": 0}


# --------------------------------------------------------------------------- the background refresher


@dataclass
class _Runner:
    thread: threading.Thread | None = None
    again: bool = False
    timer: threading.Timer | None = None
    last: dict = field(default_factory=dict)


_RUNNERS: dict[str, _Runner] = {}
_RUNNERS_GUARD = threading.Lock()


def _sleep_running() -> bool:
    from api.services import sleep_cycle

    return sleep_cycle.get_sleep_state().status == "running"


def start_refresh(memory_path, *, delay_s: float = 0.0) -> bool:
    """Refresh the picture index in the background: one run per bank at a time (a trigger during a run runs once
    more after it), never while Sleep runs (the end of the run triggers it again), and only where the image
    encoder is installed. ``delay_s`` waits first, folding a burst of triggers into one run. Never raises."""
    try:
        from api.services import vision_embedder

        if vision_embedder.folder() is None:
            return False
    except Exception:  # noqa: BLE001
        return False
    key = str(Path(memory_path).resolve())
    with _RUNNERS_GUARD:
        runner = _RUNNERS.setdefault(key, _Runner())
        if runner.thread is not None and runner.thread.is_alive():
            runner.again = True
            return False
        if delay_s > 0:
            if runner.timer is not None and runner.timer.is_alive():
                return False
            runner.timer = threading.Timer(delay_s, start_refresh, args=(memory_path,))
            runner.timer.daemon = True
            runner.timer.start()
            return True
        if _sleep_running():
            return False
        runner.thread = threading.Thread(target=_run, args=(Path(memory_path), runner), name="cicada-image-index",
                                         daemon=True)
        runner.thread.start()
    return True


def _run(memory_path: Path, runner: _Runner) -> None:
    started = time.monotonic()
    while True:
        runner.again = False
        try:
            runner.last = refresh(memory_path, should_stop=_sleep_running)
            if runner.last.get("embedded") or runner.last.get("removed"):
                logger.info(f"image_index: {runner.last['embedded']} picture(s) embedded, "
                            f"{runner.last['removed']} removed, {runner.last['total']} in all "
                            f"({time.monotonic() - started:.0f}s)")
        except RefreshStopped:
            logger.info("image_index: gave way to Sleep; it goes on when the run ends")
            return
        except Exception as exc:  # noqa: BLE001 — the next trigger tries again
            logger.debug(f"image_index: refresh skipped ({type(exc).__name__})")
            return
        if not runner.again or _sleep_running():
            return
