"""Recordings and videos the person adds, found by meaning (meaning index 2; G195 stage 2; owner via the coordinator,
2026-10-28: "go with the recommendation" — on-device transcription, no audio model; frames from picked local files).

**The app reads, the backend parses bytes.** The person picks or drops an audio or video file in the app. The app —
never the backend — opens it: it transcribes the speech on the Mac with Apple's own on-device recogniser and, for a
video, samples a frame every 3 s and keeps one per shot (an 8 × 8 average hash that moved more than 4 bits). It posts
only those derivatives: the words with their times, and ≤ 640 × 400 JPEG frames with theirs. The backend never sees
the file's path or its bytes, never downloads anything, and never derives a stream of anything (G162).

**Where it lives — outside every bank** (``$CICADA_HOME/files/<bank>/<file-id>/``): ``meta.json`` (the file's name,
kind, size, length, its sha256, when it was added), ``transcript.json`` (the scrubbed words, each segment with its
start and end in seconds) and ``frames/<ms>.jpg`` with ``frames.json``. Like site captures' full images it is never in
git and never exported with the bank. Deleting a file's folder removes it from search at the next refresh.

**What the words are — attribution.** A transcript is **the recording's words**, not the person's own: whoever
spoke in a podcast, a meeting or a voice memo is unknown to Cicada. So the words never become an episode, never count
as the person's words for promotion, are never read by Sleep (G195: "Sleep never reads the index"), and every hit
says where it came from ("the recording's words, at 12:34"). A file becomes memory only when the person or an agent
uses it in a conversation (G195's "promoted on use"), and then the conversation is the evidence.

**In the one meaning index.** The words are the ``files`` text kind of ``vector_index.db`` (passages of about
1,600 characters with their start and end times, embedded by the bank's text model through ``vector_index``'s own
diffing sync, so a model switch rebuilds it in one transaction); the frames are pictures of the ``images`` kind
(``source: frame``, with their time). Both are embedded only by the background refresher (``image_index``), outside
Sleep, never on a search. A search scores a passage by its lift over the query's mean cosine across every passage
(``image_index``'s measured reasoning) and shows it only at ``TEXT_LIFT_MIN``.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np
from loguru import logger

ROOT_DIR = "files"
KINDS = ("audio", "video")
TEXT_KIND = "files"
FILE_ID_RE = re.compile(r"^[0-9a-f]{16}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_NAME = 200
MAX_SEGMENTS = 20_000
MAX_SEGMENT_CHARS = 4_000
MAX_TEXT_CHARS = 2_000_000          # ~ 40 h of speech
MAX_SECONDS = 48 * 3600.0
MAX_FRAMES = 1_200                  # DigUp's cap: 1 h at one frame every 3 s
MAX_FRAMES_PER_CALL = 64
MAX_FRAME_BYTES = 200 * 1024
FRAME_W, FRAME_H = 640, 400
PASSAGE_CHARS = 1_600               # vector_index.EPISODE_CHUNK_CHARS: what the search models read
#: A passage is a hit only this far above the query's mean cosine over every passage. Calibrated on the real text
#: model (``benchmarks.perf.media_index_build``): a topic said lifts its best passage ≥ 0.18, a topic never said ≤ 0.04.
TEXT_LIFT_MIN = 0.12
SCRUB_WRITER = "media-files"


class FileRefused(ValueError):
    """What was posted is not something this store keeps (said in words; nothing written)."""


# --------------------------------------------------------------------------- the store


def root(memory_path) -> Path:
    """``$CICADA_HOME/files/<bank>/`` — outside every bank and git repo."""
    from api.services import video_queue
    from api.services.auth import cicada_home

    return cicada_home() / ROOT_DIR / video_queue.bank_slug(Path(memory_path))


def _folder(memory_path, file_id: str) -> Path | None:
    if not FILE_ID_RE.match(str(file_id or "")):
        return None
    return root(memory_path) / file_id


def file_id_for(sha256: str) -> str:
    return str(sha256)[:16]


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _json(path: Path) -> dict | list | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _seconds(value, field: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        raise FileRefused(f"{field} isn't a number of seconds") from None
    if not math.isfinite(out) or out < 0 or out > MAX_SECONDS:
        raise FileRefused(f"{field} is out of range")
    return round(out, 3)


def record_media(memory_path, *, name: str, kind: str, sha256: str, size: int = 0, duration_s=None,
                 language: str | None = None, segments: list | None = None) -> dict:
    """Keep one added file's description and its words. The same file (by sha256) posted again replaces its words
    and keeps its frames. ``{"action": "added" | "updated", "id"}``; raises :class:`FileRefused` and writes nothing for
    anything out of shape."""
    from api.services import episode_scrub

    kind = str(kind or "").strip().lower()
    if kind not in KINDS:
        raise FileRefused("only audio and video files are kept here")
    sha = str(sha256 or "").strip().lower()
    if not SHA_RE.match(sha):
        raise FileRefused("the file's sha256 is missing")
    clean_name = " ".join(str(name or "").replace("/", " ").split())[:MAX_NAME] or f"A {kind} file"
    segs = list(segments or [])
    if len(segs) > MAX_SEGMENTS:
        raise FileRefused("too many transcript segments")
    kept, total, scrubbed = [], 0, 0
    for seg in segs:
        if not isinstance(seg, dict):
            raise FileRefused("a transcript segment isn't an object")
        text = " ".join(str(seg.get("text") or "").split())[:MAX_SEGMENT_CHARS]
        if not text:
            continue
        text, n = episode_scrub.scrub(text)
        scrubbed += n
        start = _seconds(seg.get("start", 0), "start")
        end = max(start, _seconds(seg.get("end", start), "end"))
        total += len(text)
        if total > MAX_TEXT_CHARS:
            raise FileRefused("the transcript is too long")
        kept.append({"start": start, "end": end, "text": text})
    kept.sort(key=lambda s: s["start"])
    fid = file_id_for(sha)
    folder = _folder(memory_path, fid)
    old = _json(folder / "meta.json") if folder.is_dir() else None
    meta = {
        "id": fid, "sha256": sha, "name": clean_name, "kind": kind,
        "size": max(0, int(size or 0)),
        "duration_s": _seconds(duration_s, "duration") if duration_s is not None else None,
        "language": str(language or "")[:20] or None,
        "added_at": (old or {}).get("added_at") or _now(),
        "updated_at": _now(),
        "segments": len(kept),
        "words_by": "the recording",   # attribution: never the person's own words
    }
    _write_atomic(folder / "transcript.json", json.dumps(kept, ensure_ascii=False).encode())
    _write_atomic(folder / "meta.json", (json.dumps(meta, indent=2, ensure_ascii=False) + "\n").encode())
    episode_scrub.record(SCRUB_WRITER, scrubbed)
    return {"action": "updated" if old else "added", "id": fid}


def record_frames(memory_path, file_id: str, frames: list[tuple[float, bytes]]) -> dict:
    """Keep a video's kept frames (``[(seconds, jpeg)]``), each ≤ 640 × 400 and ≤ 200 KB, at most ``MAX_FRAMES`` a
    file. A frame at a time already kept replaces it. ``{"kept", "total"}``."""
    from api.services import image_decode

    folder = _folder(memory_path, file_id)
    if folder is None or not (folder / "meta.json").is_file():
        raise FileRefused("add the file before its frames")
    if (_json(folder / "meta.json") or {}).get("kind") != "video":
        raise FileRefused("only a video has frames")
    if len(frames) > MAX_FRAMES_PER_CALL:
        raise FileRefused(f"at most {MAX_FRAMES_PER_CALL} frames a call")
    index = {int(r["ms"]): r for r in (_json(folder / "frames.json") or []) if isinstance(r, dict) and "ms" in r}
    checked = []
    for t, data in frames:
        at = _seconds(t, "a frame's time")
        data = bytes(data or b"")
        if not data or len(data) > MAX_FRAME_BYTES or image_decode.sniff(data) != "jpg":
            raise FileRefused("a frame must be a JPEG of at most 200 KB")
        size = image_decode.dimensions(data)
        if size is None or size[0] > FRAME_W or size[1] > FRAME_H:
            raise FileRefused("a frame must be at most 640 × 400")
        checked.append((int(round(at * 1000)), data))
    if len(set(index) | {ms for ms, _ in checked}) > MAX_FRAMES:
        raise FileRefused(f"at most {MAX_FRAMES} frames a file")
    for ms, data in checked:
        _write_atomic(folder / "frames" / f"{ms}.jpg", data)
        index[ms] = {"ms": ms, "sha256": hashlib.sha256(data).hexdigest()}
    rows = [index[k] for k in sorted(index)]
    _write_atomic(folder / "frames.json", json.dumps(rows).encode())
    return {"kept": len(checked), "total": len(rows)}


def list_files(memory_path) -> list[dict]:
    """Every added file's description, newest first, with how many frames it keeps."""
    base = root(memory_path)
    if not base.is_dir():
        return []
    out = []
    for folder in base.iterdir():
        meta = _json(folder / "meta.json") if FILE_ID_RE.match(folder.name) else None
        if isinstance(meta, dict):
            frames = _json(folder / "frames.json") or []
            out.append({**meta, "frames": len(frames) if isinstance(frames, list) else 0})
    return sorted(out, key=lambda m: str(m.get("added_at") or ""), reverse=True)


def any_files(memory_path) -> bool:
    base = root(memory_path)
    return base.is_dir() and any(FILE_ID_RE.match(p.name) for p in base.iterdir())


def get(memory_path, file_id: str) -> dict | None:
    folder = _folder(memory_path, file_id)
    meta = _json(folder / "meta.json") if folder is not None else None
    return meta if isinstance(meta, dict) else None


def frame_file(memory_path, file_id: str, ms: int) -> Path | None:
    """A kept frame, only one ``frames.json`` lists — never a path a request names."""
    folder = _folder(memory_path, file_id)
    if folder is None:
        return None
    rows = _json(folder / "frames.json") or []
    if not any(isinstance(r, dict) and r.get("ms") == int(ms) for r in rows):
        return None
    path = folder / "frames" / f"{int(ms)}.jpg"
    return path if path.is_file() else None


def delete(memory_path, file_id: str) -> bool:
    folder = _folder(memory_path, file_id)
    if folder is None or not folder.is_dir():
        return False
    shutil.rmtree(folder)
    return True


# --------------------------------------------------------------------------- into the meaning index


def clock(seconds) -> str:
    """``12:34`` or ``1:02:03``."""
    s = int(max(0, float(seconds or 0)))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def passages(meta: dict, segments: list[dict]) -> list[tuple[str, str, dict]]:
    """``(key, text, metadata)`` for ``vector_index``'s sync: whole segments packed to about ``PASSAGE_CHARS``, each
    passage keeping the start of its first segment and the end of its last."""
    out, buf, start, end = [], [], None, 0.0
    fid = str(meta.get("id"))

    def flush():
        nonlocal buf, start
        if buf:
            i = len(out)
            out.append((f"{fid}#{i}", " ".join(buf),
                        {"file_id": fid, "name": meta.get("name"), "kind": meta.get("kind"), "start": start,
                         "end": end, "words_by": "the recording"}))
        buf, start = [], None

    size = 0
    for seg in segments:
        text = str(seg.get("text") or "")
        if buf and size + len(text) + 1 > PASSAGE_CHARS:
            flush()
            size = 0
        if start is None:
            start = float(seg.get("start") or 0)
        buf.append(text)
        size += len(text) + 1
        end = float(seg.get("end") or seg.get("start") or 0)
    flush()
    return out


def staged(memory_path) -> list[tuple[str, str, dict]]:
    rows = []
    base = root(memory_path)
    if not base.is_dir():
        return rows
    for folder in sorted(base.iterdir()):
        meta = _json(folder / "meta.json") if FILE_ID_RE.match(folder.name) else None
        segs = _json(folder / "transcript.json") if isinstance(meta, dict) else None
        if isinstance(segs, list) and segs:
            rows += passages(meta, segs)
    return rows


def pictures(memory_path) -> list:
    """Every kept frame as a picture for ``image_index`` (``source: frame``, its file and time)."""
    from api.services import image_index

    base = root(memory_path)
    if not base.is_dir():
        return []
    out = []
    for folder in sorted(base.iterdir()):
        meta = _json(folder / "meta.json") if FILE_ID_RE.match(folder.name) else None
        if not isinstance(meta, dict):
            continue
        for row in _json(folder / "frames.json") or []:
            if not isinstance(row, dict) or "ms" not in row:
                continue
            path = folder / "frames" / f"{int(row['ms'])}.jpg"
            if not path.is_file():
                continue
            at = int(row["ms"]) / 1000.0
            out.append(image_index.Picture(
                f"frame:{folder.name}@{int(row['ms'])}", "frame", path,
                title=f"{meta.get('name') or 'A video'} at {clock(at)}", file_id=folder.name, at=at,
                day=str(meta.get("added_at") or "")[:10] or None,
                thumb=f"/files/{folder.name}/frames/{int(row['ms'])}", sha=str(row.get("sha256") or "") or None))
    return out


def refresh_text(memory_path, *, embed_fn=None, should_stop: Callable[[], bool] | None = None) -> dict:
    """Sync the ``files`` text kind with the transcripts on this Mac (``vector_index``'s diffing sync: only new or
    changed passages embed, long batches in the embed child; a model change rebuilds in one transaction) and write
    the kind's mean for the lift. Raises ``vector_index.IndexSyncStopped`` when Sleep starts (nothing written)."""
    from api.services.vector_index import SqliteVecIndexer, _write_lock

    rows = staged(memory_path)
    indexer = SqliteVecIndexer(Path(memory_path), embed_fn=embed_fn, should_stop=should_stop)
    conn = indexer._connect()
    try:
        present = indexer._has_table(conn, TEXT_KIND)
    finally:
        conn.close()
    if not rows and not present:
        return {"embedded": 0, "reused": 0, "removed": 0, "rebuilt": 0}
    stats = indexer._sync_kind(TEXT_KIND, rows)
    conn = indexer._connect()
    try:
        with _write_lock(indexer.db_path):
            conn.execute(f"CREATE TABLE IF NOT EXISTS stats_{TEXT_KIND} (name TEXT PRIMARY KEY, value BLOB)")
            blobs = [b for (b,) in conn.execute(f"SELECT embedding FROM vec_{TEXT_KIND}")] \
                if indexer._has_table(conn, TEXT_KIND) else []
            if blobs:
                mu = np.stack([np.frombuffer(b, dtype=np.float32) for b in blobs]).astype(np.float64).mean(axis=0)
                conn.executemany(f"INSERT OR REPLACE INTO stats_{TEXT_KIND}(name, value) VALUES (?, ?)",
                                 [("n", str(len(blobs)).encode()), ("mean", mu.astype(np.float32).tobytes())])
            else:
                conn.execute(f"DELETE FROM stats_{TEXT_KIND}")
            conn.commit()
    finally:
        conn.close()
    return stats


def search_text(memory_path, query: str, *, top_k: int = 8, embed_fn=None) -> list[dict]:
    """Passages of added recordings for ``query``, best first: ``[{"key", "score" (lift), "cosine", "text",
    "metadata"}]``, only at ``lift ≥ TEXT_LIFT_MIN``. ``[]`` with no ``files`` table — never an error, never the
    query in a log."""
    from api.services.vector_index import INDEX_DB_FILE, SqliteVecIndexer

    query = (query or "").strip()
    if not query or not (Path(memory_path) / INDEX_DB_FILE).exists():
        return []
    indexer = SqliteVecIndexer(Path(memory_path), embed_fn=embed_fn) if embed_fn else SqliteVecIndexer(Path(memory_path))
    try:
        conn = indexer._connect()
    except Exception:  # noqa: BLE001
        return []
    try:
        if not indexer._has_table(conn, TEXT_KIND):
            return []
        got = dict(conn.execute(f"SELECT name, value FROM stats_{TEXT_KIND}").fetchall())
        if "mean" not in got:
            return []
        mu = np.frombuffer(got["mean"], dtype=np.float32)
        try:
            qvec = np.asarray(indexer._query_vector(query, TEXT_KIND), dtype=np.float32).reshape(-1)
        except Exception as exc:  # noqa: BLE001 — the class only (K9)
            logger.debug(f"media_files: the query didn't embed ({type(exc).__name__})")
            return []
        if qvec.size != mu.size:
            return []
        qvec = qvec / max(float(np.linalg.norm(qvec)), 1e-12)
        mean = float(qvec @ mu)
        hits = indexer._knn(conn, TEXT_KIND, query, int(max(1, top_k)), qvec=qvec)
    except sqlite3.DatabaseError as exc:
        logger.debug(f"media_files: search failed ({type(exc).__name__})")
        return []
    finally:
        conn.close()
    out = []
    for h in hits:
        lift = float(h["score"]) - mean
        if lift < TEXT_LIFT_MIN:
            break
        out.append({"key": (h.get("metadata") or {}).get("file_id", ""), "score": round(lift, 4),
                    "cosine": round(float(h["score"]), 4), "text": h.get("text") or "",
                    "metadata": h.get("metadata") or {}})
    return out
