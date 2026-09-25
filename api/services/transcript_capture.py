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

Each turn's own time rides in G118's sidecar ``turns: [{offset, ts, speaker}]``
(G141 PJ-4, R-PJ16), written by ``episode_staging.stamps_for`` — the body here
is that module's line shape byte for byte — outside the hash, the last key,
head-stable at 500. The episode ``timestamp`` stays the session's start, so a
session resumed over three days keeps one id while its day-3 turns read day 3.
Round 4 (C1): an agent turn's entry also carries `model`/`effort` when the
transcript (or, for the last reply, the Stop hook) recorded them.
"""

from __future__ import annotations

import hashlib
import re
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from loguru import logger

from api.services import agent_turns, demo_guard, episode_ids, episode_staging, markdown_parser, session_stats, telemetry
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
    reason: str | None = None  # a TranscriptRefused enum, or "demo_bank" (G141 capture-side track)


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


def _turn_sidecar(conv: Conversation, body: str) -> list[dict]:
    """G141 PJ-4 (R-PJ16, R-CS6): the per-turn ``[{offset, ts, speaker}]``
    sidecar, in the ONE shape ``evidence.turn_stamps`` reads.

    :func:`_body` renders ``"{role}: {text}"`` lines joined by ``\\n`` — byte
    for byte ``episode_staging._line`` — so the stager's own ``stamps_for``
    builds it: one writer of the shape, its head-stable 500 cap, aware-UTC
    times, and ``[]`` rather than offsets into text the body does not hold.
    Before this the hook wrote ``turns: <count>`` and every Claude Code turn
    dated to the session's first day."""
    draft = episode_staging.EpisodeDraft(turns=[
        episode_staging.Turn(text=t.text, speaker=t.role, ts=t.ts, model=t.model, effort=t.effort)
        for t in conv.turns])
    return episode_staging.stamps_for(draft, body)


def _place_turns(fm: dict, sidecar: list[dict]) -> None:
    """The sidecar is the LAST key (R-PB4), replaced whole on every rewrite; a
    body with no timed turn drops the key rather than keep stale offsets — the
    stager's ``_apply_common`` rule. Never in ``content_hash``: a time never
    re-queues a session."""
    fm.pop("turns", None)
    if sidecar:
        fm["turns"] = sidecar


def _last_offset(conv: Conversation, body: str) -> int | None:
    """Where the body's LAST turn starts — `_body` joins `"{role}: {text}"`
    chunks with `\\n`, so it is the body's length minus that chunk's."""
    if not conv.turns:
        return None
    last = conv.turns[-1]
    return len(body) - len(f"{last.role}: {last.text}")


def _agent_fields(sidecar: list[dict], previous, effort: str | None, last_offset: int | None) -> list[dict]:
    """Round 4 C1 (R4B-3): what the transcript did not say about an agent turn.

    1. An agent entry the new read left without a `model`/`effort` keeps what the
       previous sidecar held at the SAME offset — offsets are head-stable (R6), so
       a hook-supplied effort survives the next Stop.
    2. The Stop hook's `effort.level` fills the LAST body turn only, only when it
       is the agent's and the transcript gave it none: the transcript wins, and a
       reply not yet flushed leaves the hook's value with no turn to land on
       rather than labelling the previous reply.
    Keys stay in `TURN_STAMP_KEYS` order."""
    before: dict[int, dict] = {}
    if isinstance(previous, list):
        for e in previous:
            if isinstance(e, dict) and e.get("speaker") == "assistant":
                try:
                    before.setdefault(int(e.get("offset")), e)
                except (TypeError, ValueError):
                    continue
    for entry in sidecar:
        if entry.get("speaker") != "assistant":
            continue
        was = before.get(entry["offset"], {})
        if "model" not in entry and (model := agent_turns.clean_model(was.get("model"))):
            entry["model"] = model
        if "effort" not in entry and (kept := agent_turns.clean_effort(was.get("effort"))):
            entry["effort"] = kept
    hook = agent_turns.clean_effort(effort)
    if hook and sidecar and last_offset is not None:
        tail = sidecar[-1]
        if tail.get("offset") == last_offset and tail.get("speaker") == "assistant" and "effort" not in tail:
            tail["effort"] = hook
    return [{k: e[k] for k in episode_staging.TURN_STAMP_KEYS if k in e} for e in sidecar]


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
    that is never rewritten here.

    Final review (G141 PJ-4): the raw-text check comes first. PJ-4 made a
    Stop-hook episode carry up to 500 ``turns`` stamps instead of one
    integer, so YAML-parsing every episode on a cache miss (every new
    session's first Stop, every session after a restart) went from 0.06 s to
    0.86 s at 1000 episodes x 80 turns — under ``_lock``, against the hook's
    3 s timeout. A session id is a UUID, so "not in the bytes" is an exact
    miss and only the one real candidate pays for a parse."""
    try:
        if session_id not in fp.read_text(encoding="utf-8", errors="replace"):
            return False
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
    effort: str | None = None,
) -> CaptureResult:
    """Validate (R2), extract, and write or update the session's one episode (R3).

    ``status``: ``refused`` (nothing read, nothing written — an unsafe path,
    or a demo bank, reason ``demo_bank``), ``empty`` (read,
    nothing worth keeping, nothing written), ``created``, ``updated`` (body
    changed — re-queued for Sleep), ``unchanged`` (same hash — no write, so
    a Stop that fires after every reply costs no git noise).

    ``effort``: the Stop hook's ``effort.level`` for the reply it fired after
    (round 4 C1, R4B-3).
    """
    if demo_guard.is_demo(memory_path):
        # G141 capture-side track (R-CS12): a demo bank holds only made-up
        # examples, so a real session is never written into it — refused
        # before the transcript is even validated, and recorded like every
        # other refusal. The router sends the session to a real bank first;
        # this is the guard for any caller that does not.
        _record(harness, session_id, "refused", None, bank, "demo_bank")
        return CaptureResult("refused", None, 0, 0, {}, reason="demo_bank")
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
            }
            if cwd:
                fm["project_dir"] = cwd
            _place_turns(fm, _agent_fields(_turn_sidecar(conv, body), None, effort, _last_offset(conv, body)))
            path_out = episodes_dir / f"{episode_id}.md"
            markdown_parser.write(path_out, fm, body)
            _episode_cache[(str(episodes_dir.resolve()), harness, session_id)] = path_out
            _record(harness, session_id, "created", conv, bank)
            logger.info(f"capture: created {episode_id} from {harness} session ({len(conv.turns)} turns)")
            return CaptureResult("created", episode_id, kept["user"], kept["assistant"], conv.summary)

        fm = dict(markdown_parser.parse(existing).frontmatter)
        previous = fm.get("turns")
        episode_id = str(fm.get("id") or existing.stem)
        if fm.get("content_hash") == content_hash:
            _record(harness, session_id, "unchanged", conv, bank)
            return CaptureResult("unchanged", episode_id, kept["user"], kept["assistant"], conv.summary)

        # R3: same file, same id, same original timestamp; new body, re-queued,
        # and the whole per-turn sidecar rewritten (G141 PJ-4, R-PJ16).
        # `processed_by` is written only beside `processed: true` (G114 R6),
        # so a re-queued episode must not carry a stale "sleep" stamp.
        fm["title"] = _title(conv, harness)
        fm["content_hash"] = content_hash
        fm["captured_at"] = now
        fm["processed"] = False
        fm.pop("processed_by", None)
        if cwd and not fm.get("project_dir"):
            fm["project_dir"] = cwd
        _place_turns(fm, _agent_fields(_turn_sidecar(conv, body), previous, effort, _last_offset(conv, body)))
        markdown_parser.write(existing, fm, body)
        _record(harness, session_id, "updated", conv, bank)
        logger.info(f"capture: updated {episode_id} from {harness} session ({len(conv.turns)} turns), re-queued")
        return CaptureResult("updated", episode_id, kept["user"], kept["assistant"], conv.summary)
