"""Hook-driven transcript capture: validate, extract, write one episode per
session (G105 R2, R3, R10, R12, R13).

The hook (``api/hooks/capture.py``) forwards the harness's own stdin JSON;
THIS module is the only place a transcript is opened, and only after the
path has been proven to be the file the harness just named for the session
that just ended: under that harness's known root after symlink resolution,
a ``.jsonl`` regular file, within the size cap, and — for Claude Code —
named exactly ``<session_id>.jsonl`` (the same key the MCP seam's
``isfile()`` resumability check uses, ``session_stats.py:72``). Anything
else is refused with an enum reason and never read. That is the G48 rail
restated: transcripts are not a corpus Cicada mines; the one that just
ended is a stream intake, and what enters the bank is what the extractor
keeps.

Writes mirror the conversation importer byte-for-byte (``conversations.py``
``_stage_episodes`` / ``_update_episode_in_place``): the body is
``role: text`` lines, the hash is ``sha256(body)[:12]``, and a grown session
rewrites the same file with ``processed: false`` so Sleep re-consolidates
exactly one episode (the G104-safe path). Ids and stamps come from
``episode_ids`` (G114). No LLM anywhere.
"""

from __future__ import annotations

import hashlib
import re
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from loguru import logger

from api.services import episode_ids, markdown_parser, session_stats, telemetry
from api.services.transcript_extract import HARNESSES, Conversation, extract

#: 256 MiB. The largest transcript seen on the author's machine during the
#: 2026-09-03 schema peek was 85 MB; the cap is a ceiling against a runaway
#: file, not a budget.
MAX_TRANSCRIPT_BYTES = 256 * 1024 * 1024
TITLE_MAX = 72
CAPTURE_KIND = "transcript"
PRODUCT = {"claude-code": "Claude Code", "codex": "Codex"}

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{7,127}$")
_lock = threading.Lock()
# (episodes_dir, harness, session_id) -> episode path, so a Stop firing on a
# long session does not rescan every episode file. Keyed by the episodes dir
# because the active bank can change under a running backend
# (``POST /banks/{name}/activate``) — a key without it would hand one bank's
# episode path to another bank's capture (plan critic 2026-09-03: the
# un-keyed cache also bled across the test suite's tmp banks). A hit is
# re-verified by parsing the one cached file — it must still be a transcript
# episode for this session, since a bank rename, duplicate or restore can
# leave a stale path behind.
_episode_cache: dict[tuple[str, str, str], Path] = {}


class TranscriptRefused(Exception):
    """A path the endpoint will not open. ``reason`` is one of
    ``bad_harness | bad_session_id | outside_root | not_jsonl | not_a_file |
    too_large | stem_mismatch`` — an enum, so the ledger row and the 400
    body never carry the offending path itself."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def harness_root(harness: str) -> Path:
    """Where each harness keeps its transcripts. A function (not a constant)
    so tests can point it at ``tmp_path``; never derived from a request."""
    if harness == "claude-code":
        return session_stats.transcripts_root()
    if harness == "codex":
        return Path.home() / ".codex" / "sessions"
    raise TranscriptRefused("bad_harness")


def validate_transcript_path(harness: str, session_id: str, raw_path: str) -> Path:
    """R2: prove the path is the harness's own transcript for this session.

    Order matters: ``resolve(strict=True)`` first so a symlink planted inside
    the root that points elsewhere is judged by where it lands, not where it
    sits; the root check before anything that would stat or open the target;
    the size check last because it is the only step that touches the file.
    """
    if harness not in HARNESSES:
        raise TranscriptRefused("bad_harness")
    sid = (session_id or "").strip()
    if not _SESSION_ID_RE.match(sid):
        raise TranscriptRefused("bad_session_id")
    root = harness_root(harness).expanduser().resolve()
    try:
        path = Path(raw_path or "").expanduser().resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        raise TranscriptRefused("not_a_file")
    if not path.is_relative_to(root):
        raise TranscriptRefused("outside_root")
    if path.suffix != ".jsonl":
        raise TranscriptRefused("not_jsonl")
    if not path.is_file():
        raise TranscriptRefused("not_a_file")
    if harness == "claude-code" and path.stem != sid:
        raise TranscriptRefused("stem_mismatch")
    if harness == "codex" and sid not in path.name:
        raise TranscriptRefused("stem_mismatch")
    if path.stat().st_size > MAX_TRANSCRIPT_BYTES:
        raise TranscriptRefused("too_large")
    return path


@dataclass
class CaptureResult:
    status: str  # created | updated | unchanged | empty | refused
    episode_id: str | None
    turns_user: int
    turns_assistant: int
    summary: dict
    reason: str | None = None


def _utc(ts: str | None) -> str:
    """A transcript stamp (``…Z``) → the R2 ``+00:00`` shape; now() when absent."""
    if ts:
        try:
            return episode_ids.to_utc_iso(datetime.fromisoformat(ts.replace("Z", "+00:00")))
        except ValueError:
            pass
    return episode_ids.utc_now_iso()


def _body(conv: Conversation) -> str:
    """The importer's exact body shape (``conversations.py:792``), so G118
    spans and ``evidence.speaker_kind`` read a captured episode unchanged."""
    return "\n".join(f"{t.role}: {t.text}" for t in conv.turns)


def _title(conv: Conversation, harness: str) -> str:
    """R12: the first kept user turn's first line, else ``<Product> session``."""
    for t in conv.turns:
        if t.role == "user":
            first = t.text.strip().splitlines()[0].strip()
            if first:
                return first if len(first) <= TITLE_MAX else first[: TITLE_MAX - 1] + "…"
    return f"{PRODUCT.get(harness, harness)} session"


def _is_session_episode(fp: Path, session_id: str) -> bool:
    """R3: only a ``capture_kind: transcript`` page for this session counts.
    An MCP ``cicada_save_episode`` from the same session carries the same
    ``session_id`` but no ``capture_kind`` — a deliberate, separate episode
    that is never rewritten here."""
    try:
        fm = markdown_parser.parse(fp).frontmatter
    except Exception:  # noqa: BLE001 - one malformed episode must not block capture
        return False
    return fm.get("capture_kind") == CAPTURE_KIND and str(fm.get("session_id") or "") == session_id


def _find_session_episode(episodes_dir: Path, harness: str, session_id: str) -> Path | None:
    key = (str(episodes_dir.resolve()), harness, session_id)
    cached = _episode_cache.get(key)
    if cached is not None and cached.is_file() and _is_session_episode(cached, session_id):
        return cached
    _episode_cache.pop(key, None)
    for fp in sorted(episodes_dir.glob("ep_*.md")):
        if _is_session_episode(fp, session_id):
            _episode_cache[key] = fp
            return fp
    return None


def _record(harness: str, session_id: str, status: str, conv: Conversation | None, bank: str | None,
            reason: str | None = None) -> None:
    """R10: one ``capture`` ledger row — ids, enums and counts only. Never a
    turn's text, a title, or the cwd: the ledger is machine-global and
    outside the bank. ``telemetry.record`` swallows its own failures, so this
    can never raise into the capture path.

    Final review (2026-09-03) F1: ``invocations=0`` and ``stage="capture"``.
    A Stop hook fires after every reply of every session, so with the
    dataclass default ``invocations=1`` and ``stage=<harness>`` the Usage
    page grew a ``claude-code`` stage whose invocation count was the
    person's reply cadence, not a unit of Cicada's LLM work. The harness
    already lives in ``refs`` for anyone reading the ledger row itself.
    ``consumption_stats`` additionally keeps ``capture`` rows out of every
    activity view (``by_stage``/``by_bank``/hour histogram/daily series)."""
    summary = conv.summary if conv else {}
    refs = {
        "harness": harness, "status": status, "session_id": session_id,
        "turns_user": summary.get("kept", {}).get("user", 0),
        "turns_assistant": summary.get("kept", {}).get("assistant", 0),
        "dropped_blocks": summary.get("dropped_blocks", {}),
        "dropped_messages": summary.get("dropped_messages", {}),
        "truncated_turns": summary.get("truncated_turns", 0),
        "scrubbed": summary.get("scrubbed", 0),
        "session_cap_hit": summary.get("session_cap_hit", False),
    }
    if reason:
        refs["reason"] = reason
    telemetry.record(telemetry.UsageEvent(kind="capture", stage="capture", bank=bank, billing="free",
                                          invocations=0, refs=refs, ok=status != "refused"))


def capture_transcript(
    memory_path: Path,
    *,
    harness: str,
    session_id: str,
    transcript_path: str,
    cwd: str | None,
    keep_assistant: bool,
    bank: str | None = None,
) -> CaptureResult:
    """Validate (R2), extract, and write or update the session's one episode (R3).

    ``status``: ``refused`` (nothing read, nothing written), ``empty`` (read,
    nothing worth keeping, nothing written), ``created``, ``updated`` (body
    changed — re-queued for Sleep), ``unchanged`` (same hash — no write, so
    a Stop that fires after every reply costs no git noise).
    """
    try:
        path = validate_transcript_path(harness, session_id, transcript_path)
    except TranscriptRefused as exc:
        _record(harness, session_id, "refused", None, bank, exc.reason)
        return CaptureResult("refused", None, 0, 0, {}, reason=exc.reason)

    with path.open("r", encoding="utf-8", errors="replace") as fh:
        conv = extract(harness, fh, keep_assistant=keep_assistant)
    kept = conv.summary["kept"]

    with _lock:
        episodes_dir = memory_path / "episodes"
        episodes_dir.mkdir(parents=True, exist_ok=True)
        if not conv.turns:
            _record(harness, session_id, "empty", conv, bank)
            return CaptureResult("empty", None, 0, 0, conv.summary)

        body = _body(conv)
        content_hash = hashlib.sha256(body.encode()).hexdigest()[:12]
        existing = _find_session_episode(episodes_dir, harness, session_id)
        now = episode_ids.utc_now_iso()

        if existing is None:
            timestamp = _utc(conv.started_at)
            episode_id = episode_ids.next_episode_id(episodes_dir, timestamp[:10])
            fm = {
                "id": episode_id,
                "timestamp": timestamp,
                "source": harness,
                "origin": harness,
                "title": _title(conv, harness),
                "processed": False,
                "content_hash": content_hash,
                "session_id": session_id,
                "harness": harness,
                "capture_kind": CAPTURE_KIND,
                "captured_at": now,
                "turns": len(conv.turns),
            }
            if cwd:
                fm["project_dir"] = cwd
            path_out = episodes_dir / f"{episode_id}.md"
            markdown_parser.write(path_out, fm, body)
            _episode_cache[(str(episodes_dir.resolve()), harness, session_id)] = path_out
            _record(harness, session_id, "created", conv, bank)
            logger.info(f"capture: created {episode_id} from {harness} session ({len(conv.turns)} turns)")
            return CaptureResult("created", episode_id, kept["user"], kept["assistant"], conv.summary)

        fm = dict(markdown_parser.parse(existing).frontmatter)
        episode_id = str(fm.get("id") or existing.stem)
        if fm.get("content_hash") == content_hash:
            _record(harness, session_id, "unchanged", conv, bank)
            return CaptureResult("unchanged", episode_id, kept["user"], kept["assistant"], conv.summary)

        # R3: same file, same id, same original timestamp; new body, re-queued.
        # `processed_by` is written only beside `processed: true` (G114 R6),
        # so a re-queued episode must not carry a stale "sleep" stamp.
        fm["title"] = _title(conv, harness)
        fm["content_hash"] = content_hash
        fm["captured_at"] = now
        fm["turns"] = len(conv.turns)
        fm["processed"] = False
        fm.pop("processed_by", None)
        if cwd and not fm.get("project_dir"):
            fm["project_dir"] = cwd
        markdown_parser.write(existing, fm, body)
        _record(harness, session_id, "updated", conv, bank)
        logger.info(f"capture: updated {episode_id} from {harness} session ({len(conv.turns)} turns), re-queued")
        return CaptureResult("updated", episode_id, kept["user"], kept["assistant"], conv.summary)
