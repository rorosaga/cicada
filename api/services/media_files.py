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
git and never exported with the bank. Deleting a file's folder removes it from search at the next refresh. ``meta.json`` also remembers the file's
page in the bank (``page``, ``media_pages``), which holds everything but the words.

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
KINDS = ("audio", "video", "image")
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
FRAME_TEXT_FILE = "frame_text.json"
MAX_FRAME_TEXT_CHARS = 4_000        # the text read from one picture (a screen full is about 2,000)
MAX_TEXT_ITEMS_PER_CALL = 64
FRAME_W, FRAME_H = 640, 400
PASSAGE_CHARS = 1_600               # vector_index.EPISODE_CHUNK_CHARS: what the search models read
#: A passage is a hit only this far above the query's mean cosine over every passage. Calibrated on the real text
#: model (``benchmarks.perf.media_index_build``): a topic said lifts its best passage ≥ 0.18, a topic never said ≤ 0.04.
TEXT_LIFT_MIN = 0.12
SCRUB_WRITER = "media-files"
#: A store that names its own recordings (G43): an item is keyed by the store's id for it, never by its bytes, so an
#: edit re-stages the same item and a deletion retires it. Only these sources may key themselves.
SOURCES = ("voice_memos",)
SOURCE_KEY_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
MAX_MODEL = 80


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


def source_file_id(source: str, key: str) -> str:
    """The id of an item a store names itself (``voice_memos`` + the store's id for the recording)."""
    return hashlib.sha256(f"{source}:{key}".encode()).hexdigest()[:16]


def _recorded_at(value) -> str:
    """The item's own date as aware UTC ISO (ruling 39); refused when it isn't a date."""
    try:
        when = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        raise FileRefused("recorded_at isn't a date") from None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def record_media(memory_path, *, name: str, kind: str, sha256: str | None = None, size: int = 0, duration_s=None,
                 language: str | None = None, segments: list | None = None, source: str | None = None,
                 source_key: str | None = None, recorded_at=None, transcribed_by: str | None = None) -> dict:
    """Keep one added file's description and its words. The same file (by sha256) posted again replaces its words
    and keeps its frames. With a ``source`` (G43) the item is keyed by the store's id and dated by ``recorded_at``;
    the same bytes posted again are ``unchanged`` and a changed recording re-stages (``updated``).
    ``transcribed_by`` names the model that made the words (the contributor a page will show).
    ``{"action": "added" | "updated" | "unchanged", "id"}``; raises :class:`FileRefused` and writes nothing for
    anything out of shape."""
    from api.services import episode_scrub

    kind = str(kind or "").strip().lower()
    if kind not in KINDS:
        raise FileRefused("only audio, video and picture files are kept here")
    sha = str(sha256 or "").strip().lower()
    when = None
    if source is not None:
        if source not in SOURCES or kind != "audio":
            raise FileRefused("that store isn't one this keeps")
        if not SOURCE_KEY_RE.match(str(source_key or "")):
            raise FileRefused("the recording's id is missing")
        if sha and not SHA_RE.match(sha):
            raise FileRefused("the file's sha256 is malformed")
        when = _recorded_at(recorded_at) if recorded_at else None
    elif not SHA_RE.match(sha):
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
    fid = source_file_id(source, source_key) if source else file_id_for(sha)
    folder = _folder(memory_path, fid)
    old = _json(folder / "meta.json") if folder.is_dir() else None
    if source and old and not old.get("deleted_at") and sha and old.get("sha256") == sha:
        return {"action": "unchanged", "id": fid}
    meta = {
        "id": fid, "sha256": sha, "name": clean_name, "kind": kind,
        "size": max(0, int(size or 0)),
        "duration_s": _seconds(duration_s, "duration") if duration_s is not None else None,
        "language": str(language or "")[:20] or None,
        "added_at": (old or {}).get("added_at") or _now(),
        "updated_at": _now(),
        "segments": len(kept),
        "words_by": "the recording",   # attribution: never the person's own words
        "transcribed_by": " ".join(str(transcribed_by or "").split())[:MAX_MODEL] or None,
    }
    if (old or {}).get("page") and not (old or {}).get("deleted_at"):
        meta["page"] = old["page"]       # the file's page (``media_pages``): the same file keeps it
    if source:
        # A tombstoned item that comes back is a fresh one (``deleted_at`` is not carried over).
        meta.update({"sha256": sha or None, "source": source, "source_key": source_key, "recorded_at": when})
    _write_atomic(folder / "transcript.json", json.dumps(kept, ensure_ascii=False).encode())
    _write_atomic(folder / "meta.json", (json.dumps(meta, indent=2, ensure_ascii=False) + "\n").encode())
    episode_scrub.record(SCRUB_WRITER, scrubbed)
    _reindex(memory_path, fid)
    return {"action": "updated" if old and not old.get("deleted_at") else "added", "id": fid}


def retire_source(memory_path, source: str, present: set[str]) -> int:
    """Tombstone every kept item of ``source`` whose store id is not in ``present`` (the store's complete list): its
    words and frames go, its description stays with ``deleted_at`` (never unlinked), and its vectors leave at the next
    refresh. Returns how many were retired."""
    base = root(memory_path)
    if source not in SOURCES or not base.is_dir():
        return 0
    n = 0
    for folder in base.iterdir():
        meta = _json(folder / "meta.json") if FILE_ID_RE.match(folder.name) else None
        if not isinstance(meta, dict) or meta.get("source") != source or meta.get("deleted_at"):
            continue
        if meta.get("source_key") in present:
            continue
        from api.services import media_pages

        media_pages.queue_retirement(memory_path, [folder.name])      # its page goes with it (the next sync)
        for name in ("transcript.json", "frames.json", FRAME_TEXT_FILE):
            (folder / name).unlink(missing_ok=True)
        shutil.rmtree(folder / "frames", ignore_errors=True)
        meta.update({"deleted_at": _now(), "segments": 0})
        _write_atomic(folder / "meta.json", (json.dumps(meta, indent=2, ensure_ascii=False) + "\n").encode())
        _unindex(memory_path, folder.name)
        n += 1
    return n


def record_frames(memory_path, file_id: str, frames: list[tuple[float, bytes]]) -> dict:
    """Keep a video's kept frames (``[(seconds, jpeg)]``), each ≤ 640 × 400 and ≤ 200 KB, at most ``MAX_FRAMES`` a
    file. A frame at a time already kept replaces it. ``{"kept", "total"}``."""
    from api.services import image_decode

    folder = _folder(memory_path, file_id)
    if folder is None or not (folder / "meta.json").is_file():
        raise FileRefused("add the file before its frames")
    kind = (_json(folder / "meta.json") or {}).get("kind")
    if kind not in ("video", "image"):
        raise FileRefused("only a video or a picture has frames")
    if kind == "image" and len(frames) > 1:
        raise FileRefused("a picture keeps one picture")
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
    if kind == "image":
        index = {}      # a photo keeps one derivative: a new one replaces the old
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
        if isinstance(meta, dict) and not meta.get("deleted_at"):
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


def delete(memory_path, file_id: str, *, by: str = "cicada") -> bool:
    """Remove a file's words and frames now. Its page is queued for retirement first (``media_pages``; ``by`` is who
    asked, for the commit's author) and goes at the next sync."""
    folder = _folder(memory_path, file_id)
    if folder is None or not folder.is_dir():
        return False
    from api.services import media_pages

    media_pages.queue_retirement(memory_path, [file_id], by=by)
    shutil.rmtree(folder)
    _unindex(memory_path, file_id)
    return True


def transcript(memory_path, file_id: str) -> dict | None:
    """A file's words as stored (scrubbed, each with its start and end), for the page that draws them at view time.
    ``None`` for a file that is gone. Never indexed as page text and never in a bank."""
    folder = _folder(memory_path, file_id)
    meta = _json(folder / "meta.json") if folder is not None else None
    if not isinstance(meta, dict) or meta.get("deleted_at"):
        return None
    rows = _json(folder / "transcript.json")
    segments = [{"start": r["start"], "end": r["end"], "text": r["text"]} for r in rows or []
                if isinstance(r, dict) and isinstance(r.get("text"), str)]
    return {"segments": segments, "transcribedBy": meta.get("transcribed_by"), "language": meta.get("language"),
            "durationS": meta.get("duration_s"), "wordsBy": meta.get("words_by") or "the recording"}


# --------------------------------------------------------------------------- into the meaning index


def clock(seconds) -> str:
    """``12:34`` or ``1:02:03``."""
    s = int(max(0, float(seconds or 0)))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def _pack(meta: dict, segments: list[dict]) -> list[dict]:
    """Whole segments packed to about ``PASSAGE_CHARS``: ``{"key", "text", "md", "marks"}`` per passage, each keeping
    the start of its first segment and the end of its last; ``marks`` are ``[character offset, start ms]`` of every
    segment in the passage (what lets a word hit land on its own second)."""
    out, buf, marks, start, end = [], [], [], None, 0.0
    fid = str(meta.get("id"))

    def flush():
        nonlocal buf, marks, start
        if buf:
            i = len(out)
            out.append({"key": f"{fid}#{i}", "text": " ".join(buf), "marks": marks,
                        "md": {"file_id": fid, "name": meta.get("name"), "kind": meta.get("kind"), "start": start,
                               "end": end, "words_by": "the recording", "recorded_at": meta.get("recorded_at")}})
        buf, marks, start = [], [], None

    size = 0
    for seg in segments:
        text = str(seg.get("text") or "")
        if buf and size + len(text) + 1 > PASSAGE_CHARS:
            flush()
            size = 0
        if start is None:
            start = float(seg.get("start") or 0)
        marks.append([size, int(round(float(seg.get("start") or 0) * 1000))])
        buf.append(text)
        size += len(text) + 1
        end = float(seg.get("end") or seg.get("start") or 0)
    flush()
    return out


def passages(meta: dict, segments: list[dict]) -> list[tuple[str, str, dict]]:
    """``(key, text, metadata)`` for ``vector_index``'s sync: whole segments packed to about ``PASSAGE_CHARS``, each
    passage keeping the start of its first segment and the end of its last."""
    return [(p["key"], p["text"], p["md"]) for p in _pack(meta, segments)]


# --------------------------------------------------------------------------- text read from a picture (ROR-117)


def clean_picture_text(text) -> tuple[str, int]:
    """The one cleaning of text an app read from a picture — a kept frame, or a photo item (a door that adds one
    calls :func:`record_frame_text`): whitespace collapsed, at most ``MAX_FRAME_TEXT_CHARS``, and the same scrub as a
    transcript before anything is stored. ``(text, how many secrets it scrubbed)``."""
    from api.services import episode_scrub

    flat = " ".join(str(text or "").split())[:MAX_FRAME_TEXT_CHARS]
    return episode_scrub.scrub(flat) if flat else ("", 0)


def _frame_text_rows(folder: Path) -> list[dict]:
    rows = _json(folder / FRAME_TEXT_FILE)
    if not isinstance(rows, list):
        return []
    return [r for r in rows if isinstance(r, dict) and isinstance(r.get("ms"), int) and r.get("text")]


def record_frame_text(memory_path, file_id: str, items: list[tuple[float, str]]) -> dict:
    """Keep the text an app read from a picture at a time of the item (``[(seconds, text)]``): each kept frame of a
    video, or ``(0, text)`` for a photo item. Read on this Mac by the app (Apple's on-device recogniser) and posted as
    a derivative; it is the picture's words — never the person's, never read by Sleep — searchable by words and by
    meaning, marked as read from the picture. A time already kept is replaced; empty text removes it. Scrubbed like a
    transcript. ``{"kept", "total"}``; raises :class:`FileRefused` and writes nothing for anything out of shape."""
    from api.services import episode_scrub

    folder = _folder(memory_path, file_id)
    if folder is None or not (folder / "meta.json").is_file():
        raise FileRefused("add the file before its picture text")
    if len(items) > MAX_TEXT_ITEMS_PER_CALL:
        raise FileRefused(f"at most {MAX_TEXT_ITEMS_PER_CALL} pictures' text a call")
    index = {int(r["ms"]): str(r["text"]) for r in _frame_text_rows(folder)}
    checked, scrubbed = [], 0
    for t, text in items:
        text, n = clean_picture_text(text)
        scrubbed += n
        checked.append((int(round(_seconds(t, "a picture's time") * 1000)), text))
    for ms, text in checked:
        if text:
            index[ms] = text
        else:
            index.pop(ms, None)
    if len(index) > MAX_FRAMES:
        raise FileRefused(f"at most {MAX_FRAMES} pictures' text a file")
    rows = [{"ms": ms, "text": index[ms]} for ms in sorted(index)]
    if rows:
        _write_atomic(folder / FRAME_TEXT_FILE, json.dumps(rows, ensure_ascii=False).encode())
    else:
        (folder / FRAME_TEXT_FILE).unlink(missing_ok=True)
    episode_scrub.record(SCRUB_WRITER, scrubbed)
    _reindex(memory_path, file_id)
    return {"kept": len([1 for _, text in checked if text]), "total": len(rows)}


def _picture_pack(meta: dict, rows: list[dict]) -> list[dict]:
    """One or more passages per picture's text (a run of the same text over consecutive kept frames is one): the
    same shape as :func:`_pack`, ``md["from"] = "picture"`` and a single mark at the picture's time."""
    out, last, fid = [], None, str(meta.get("id"))
    for row in sorted(rows, key=lambda r: r["ms"]):
        text = " ".join(str(row["text"]).split())
        if not text or text == last:
            continue
        last = text
        ms = int(row["ms"])
        pieces, rest = [], text
        while rest:
            if len(rest) <= PASSAGE_CHARS:
                pieces.append(rest)
                break
            cut = rest.rfind(" ", 0, PASSAGE_CHARS)
            cut = cut if cut > 0 else PASSAGE_CHARS
            pieces.append(rest[:cut])
            rest = rest[cut:].lstrip()
        for j, piece in enumerate(pieces):
            out.append({"key": f"{fid}#t{ms}" + (f".{j}" if j else ""), "text": piece, "marks": [[0, ms]],
                        "md": {"file_id": fid, "name": meta.get("name"), "kind": meta.get("kind"),
                               "start": ms / 1000.0, "end": ms / 1000.0, "words_by": "the recording",
                               "from": "picture", "recorded_at": meta.get("recorded_at")}})
    return out


def _packed(folder: Path, meta: dict) -> list[dict]:
    segs = _json(folder / "transcript.json")
    out = _pack(meta, segs) if isinstance(segs, list) and segs else []
    return out + _picture_pack(meta, _frame_text_rows(folder))


def staged(memory_path) -> list[tuple[str, str, dict]]:
    rows = []
    base = root(memory_path)
    if not base.is_dir():
        return rows
    for folder in sorted(base.iterdir()):
        meta = _json(folder / "meta.json") if FILE_ID_RE.match(folder.name) else None
        if isinstance(meta, dict):
            rows += [(p["key"], p["text"], p["md"]) for p in _packed(folder, meta)]
    return rows


# --------------------------------------------------------------------------- into the lexical index (file_words)

_STAMPED = ("transcript.json", FRAME_TEXT_FILE, "meta.json")


def _stamp(folder: Path) -> str | None:
    """What the store holds for one item, for ``file_words``' diff: ``None`` when it holds no words or text."""
    parts = []
    for name in _STAMPED:
        try:
            st = (folder / name).stat()
            parts.append(f"{st.st_mtime_ns}:{st.st_size}")
        except OSError:
            parts.append("-")
    return None if parts[0] == "-" and parts[1] == "-" else "|".join(parts)


def store_stamps(memory_path) -> dict[str, str]:
    """``{file id: stamp}`` of every item that holds words or picture text."""
    base = root(memory_path)
    if not base.is_dir():
        return {}
    out = {}
    for folder in base.iterdir():
        if FILE_ID_RE.match(folder.name) and (stamp := _stamp(folder)):
            out[folder.name] = stamp
    return out


def lexical_rows(memory_path, file_id: str) -> tuple[str | None, list[dict]]:
    """``(stamp, rows)`` for ``file_words``: the item's passages (the ones the meaning index embeds) as
    ``{"body", "s", "e" (ms), "src", "marks", "name", "kind"}``. ``(None, [])`` for an item taken out."""
    folder = _folder(memory_path, file_id)
    meta = _json(folder / "meta.json") if folder is not None else None
    stamp = _stamp(folder) if folder is not None and isinstance(meta, dict) and not meta.get("deleted_at") else None
    if stamp is None:
        return None, []
    rows = [{"body": p["text"], "s": int(round(float(p["md"]["start"] or 0) * 1000)),
             "e": int(round(float(p["md"]["end"] or p["md"]["start"] or 0) * 1000)),
             "src": p["md"].get("from") or "", "marks": p["marks"], "name": meta.get("name") or "",
             "kind": meta.get("kind") or "audio"} for p in _packed(folder, meta)]
    return stamp, rows


def _reindex(memory_path, file_id: str) -> None:
    from api.services import file_words

    file_words.reindex(memory_path, file_id)


def _unindex(memory_path, file_id: str) -> None:
    from api.services import file_words

    file_words.drop(memory_path, file_id)


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
        photo = meta.get("kind") == "image"
        for row in _json(folder / "frames.json") or []:
            if not isinstance(row, dict) or "ms" not in row:
                continue
            path = folder / "frames" / f"{int(row['ms'])}.jpg"
            if not path.is_file():
                continue
            at = int(row["ms"]) / 1000.0
            if photo:
                # A photo added by the person: its one derivative, named by the file, with no time.
                out.append(image_index.Picture(
                    f"photo:{folder.name}", "photo", path, title=str(meta.get("name") or "A photo"),
                    file_id=folder.name, day=str(meta.get("added_at") or "")[:10] or None,
                    thumb=f"/files/{folder.name}/frames/{int(row['ms'])}", sha=str(row.get("sha256") or "") or None))
                continue
            out.append(image_index.Picture(
                f"frame:{folder.name}@{int(row['ms'])}", "frame", path,
                title=f"{meta.get('name') or 'A video'} at {clock(at)}", file_id=folder.name, at=at,
                day=str(meta.get("recorded_at") or meta.get("added_at") or "")[:10] or None,
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
    from api.services import image_index
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
        n = int(got["n"].decode()) if "n" in got else 0
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
    # A lone passage, or a count the stats don't record (n = 0), is never shown for free (review of #529): its cosine
    # must reach the absolute floor measured for EmbeddingGemma 2, and on any other model it isn't shown at all.
    lone_min = image_index.LONE_TEXT_COSINE_MIN if image_index.calibrated(indexer.kind_model(TEXT_KIND)) else None
    out = []
    for h in hits:
        score = image_index.clears(float(h["score"]), mean, n, lift_min=TEXT_LIFT_MIN, lone_min=lone_min)
        if score is None:
            break
        out.append({"key": (h.get("metadata") or {}).get("file_id", ""), "score": round(score, 4),
                    "cosine": round(float(h["score"]), 4), "text": h.get("text") or "",
                    "metadata": h.get("metadata") or {}})
    return out


def _at_ms(body: str, marks: list, tokens: list[str], default: int) -> int:
    """The second a hit lands on: the start of the segment (or picture) of the passage that holds the most of the
    query's words (a word-start each, the subject words when the query has some), the earliest on a tie; the
    passage's own start (``default``) when no segment holds any."""
    from api.services import text_fold

    subject = [t for t in tokens if text_fold.subject_terms(t)] or tokens
    if not marks or not subject:
        return default
    best, best_n = default, 0
    for i, (offset, ms) in enumerate(marks):
        end = marks[i + 1][0] - 1 if i + 1 < len(marks) else len(body)
        words = text_fold.words(body[offset:end])
        n = sum(1 for t in subject if any(w.startswith(t) for w in words))
        if n > best_n:
            best, best_n = int(ms), n
    return best


def find(memory_path, query: str, *, top_k: int = 8, embed_fn=None, semantic: bool = True,
         plain_words: bool = True) -> list[dict]:
    """Passages of added recordings, videos and the text read from their pictures for ``query``, best first: by
    meaning (:func:`search_text`) and by words (``file_words``), the two lists fused into one hit per passage by
    the one reciprocal-rank fusion (``search_service.rrf_scores``). ``[{"key" (file id), "score", "text",
    "metadata" (file_id, name, kind, start, end, from?), "at" (seconds the hit lands on), "via" ("words" |
    "meaning" | "both")}]``. ``semantic=False`` is the type-as-you-go path: words only, no embedding call.
    ``plain_words`` lets a question in plain words find its rarest word. Never raises; the query is never logged."""
    from api.services import file_words, search_service, text_fold

    query = (query or "").strip()
    top_k = max(1, int(top_k))
    tokens = text_fold.query_tokens(query)
    sem = search_text(memory_path, query, top_k=top_k, embed_fn=embed_fn) if semantic else []
    try:
        lex = file_words.search(memory_path, query, limit=top_k, plain_words=plain_words)
    except Exception as exc:  # noqa: BLE001 — a derived leg fewer, never an error
        logger.debug(f"media_files: the words leg failed ({type(exc).__name__})")
        lex = []

    def sem_key(row):
        md = row.get("metadata") or {}
        return f"{md.get('file_id')}|{int(round(float(md.get('start') or 0) * 1000))}|{md.get('from') or ''}"

    def lex_key(row):
        return f"{row['fid']}|{row['s']}|{row['src']}"

    scores, _ = search_service.rrf_scores([{"id": lex_key(r)} for r in lex], [{"id": sem_key(r)} for r in sem])
    by_lex, by_sem = {lex_key(r): r for r in lex}, {sem_key(r): r for r in sem}
    out = []
    for k in sorted(scores, key=lambda x: -scores[x])[:top_k]:
        lx, sm = by_lex.get(k), by_sem.get(k)
        if lx is not None:
            md = {"file_id": lx["fid"], "name": lx["name"], "kind": lx["kind"], "start": lx["s"] / 1000.0,
                  "end": lx["e"] / 1000.0, "words_by": "the recording"}
            if lx["src"]:
                md["from"] = lx["src"]
            at = _at_ms(lx["body"], lx["marks"], tokens, lx["s"]) / 1000.0
            text = lx["body"]
        else:
            md = dict(sm.get("metadata") or {})
            text = sm.get("text") or ""
            start_ms = int(round(float(md.get("start") or 0) * 1000))
            held = file_words.passage(memory_path, md.get("file_id", ""), start_ms, md.get("from") or "")
            at = (_at_ms(held["body"], held["marks"], tokens, start_ms) if held else start_ms) / 1000.0
        out.append({"key": md.get("file_id", ""), "score": round(scores[k], 4), "text": text, "metadata": md,
                    "at": at, "via": "both" if lx is not None and sm is not None else "words" if lx is not None
                    else "meaning"})
    return out
