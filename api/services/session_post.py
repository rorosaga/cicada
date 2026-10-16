"""A harness session read on the machine where it lives, posted as turns (G181 phase 2, owner ruling 2, 2026-10-16).

The transcript rail, amended: a Claude Code or Codex session is read **on the machine it lives on, by Cicada's own
extractor** (``transcript_extract``), and only what the extractor keeps crosses the wire — scrubbed, code stripped,
capped (16k for the first person message, 2k for every other turn, the session cap with its head, tail and marker).
The server never opens a path a remote client names; it re-checks what arrived (:func:`from_wire`) and writes it with
the same writer, under the same locks, as a session it read itself (``transcript_capture.capture_posted``), so ids are
minted on the server and one session stays one episode (G104).

Two halves, one shape:

* :func:`read_local` — the client's half, run by the Stop hook when ``CICADA_API_BASE`` names a server: the same path
  rules as the backend's own read (``transcript_capture.validate_transcript_path``: under the harness root, a
  ``.jsonl`` regular file, ``<session_id>.jsonl`` for Claude Code, within the size cap), the same extractor, and the
  transcript's extent (the bytes read) for the superseded rule.
* :func:`from_wire` — the server's half: every field re-validated, every turn cleaned again (fences stripped, secrets
  scrubbed: idempotent on what Cicada's extractor sent), the per-turn caps enforced (a turn over its cap is refused,
  never trimmed into something the extractor did not keep), and the session cap re-applied (``transcript_extract
  .window``). Counts are recomputed from the turns; only the extractor's drop counters, integers, are taken as sent.
"""
from __future__ import annotations

from pathlib import Path

from api.services import agent_turns
from api.services.episode_scrub import scrub
from api.services.transcript_extract import (
    _NOTE_LINE_RE, FIRST_USER_CAP_CHARS, SESSION_CAP_CHARS, TURN_CAP_CHARS, Conversation, Gap, Turn,
    strip_code_fences, window,
)

#: The most turns one post may carry: the session cap is 100k characters, so this is a bound, never a budget.
MAX_TURNS = 5000
_STAMP_MAX = 64
#: The extractor's drop counters (ints, or maps of ints): the only counts taken as sent, for the ledger.
_COUNTER_KEYS = ("dropped_blocks", "dropped_messages")
_INT_KEYS = ("truncated_turns", "scrubbed")


class PostRefused(ValueError):
    """What arrived is not what Cicada's extractor sends. ``reason`` is an enum for the 400 body and the ledger."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


# --- the client's half ---------------------------------------------------------------------------------------------

def to_wire(conv: Conversation) -> dict:
    """What the extractor kept, as JSON: the kept turns (``kept`` — never ``turns``, the episode sidecar's one
    meaning), the dropped middle, the latest time seen and the counts."""
    turns = []
    for t in conv.turns:
        entry: dict = {"role": t.role, "text": t.text}
        if t.ts:
            entry["ts"] = t.ts
        if t.model:
            entry["model"] = t.model
        if t.effort:
            entry["effort"] = t.effort
        if t.reply_gap:
            entry["reply_gap"] = dict(t.reply_gap)
        turns.append(entry)
    gap = None
    if conv.gap is not None:
        gap = {"after": conv.gap.after, "dropped": conv.gap.dropped, "first_at": conv.gap.first_at,
               "last_at": conv.gap.last_at}
    return {"kept": turns, "gap": gap, "last_seen_at": conv.last_seen_at, "summary": dict(conv.summary)}


def read_local(harness: str, session_id: str, transcript_path: str) -> tuple[dict, int]:
    """Read this machine's transcript the way the backend reads its own: ``(conversation wire, bytes read)``.
    ``transcript_capture.TranscriptRefused`` (an enum reason) when the path is not the harness's own file for this
    session — nothing is read then. The agent's replies are always kept here; the server drops them when its
    owner turned them off (``capture_assistant_replies``)."""
    from api.services.transcript_capture import validate_transcript_path
    from api.services.transcript_extract import extract

    path = validate_transcript_path(harness, session_id, transcript_path)
    read_bytes = 0
    with path.open("rb") as fh:
        def lines():
            nonlocal read_bytes
            for raw in fh:
                read_bytes += len(raw)
                yield raw.decode("utf-8", "replace")
        conv = extract(harness, lines(), keep_assistant=True)
    return to_wire(conv), read_bytes


def current_size(transcript_path: str | None, fallback: int) -> int:
    """The transcript's size now (a resend after an outage says how far the file has grown since its read, so the
    server can tell a stale snapshot from a file that was replaced); ``fallback`` when it is gone."""
    try:
        return Path(transcript_path or "").stat().st_size
    except (OSError, ValueError):
        return fallback


# --- the server's half ---------------------------------------------------------------------------------------------

def _stamp(value) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > _STAMP_MAX:
        raise PostRefused("bad_stamp")
    return value or None


def _count(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PostRefused("bad_count")
    return value


def _turn(raw, *, first_user: bool) -> tuple[Turn | None, int]:
    if not isinstance(raw, dict):
        raise PostRefused("bad_turn")
    role, text = raw.get("role"), raw.get("text")
    if role not in ("user", "assistant") or not isinstance(text, str):
        raise PostRefused("bad_turn")
    cap = FIRST_USER_CAP_CHARS if (role == "user" and first_user) else TURN_CAP_CHARS
    if len(text) > cap:
        raise PostRefused("turn_over_cap")
    cleaned, n = scrub(strip_code_fences(text))
    cleaned = cleaned.strip()
    if not cleaned:
        return None, n
    reply_gap = raw.get("reply_gap")
    if reply_gap is not None:
        if role != "assistant" or not isinstance(reply_gap, dict):
            raise PostRefused("bad_turn")
        reply_gap = {"offset": _count(reply_gap.get("offset")), "omitted_chars": _count(reply_gap.get("omitted_chars"))}
        if cleaned != text or reply_gap["offset"] > len(cleaned):
            reply_gap = None          # the text moved under the recorded gap: the marker line still says it
    model = agent_turns.clean_model(raw.get("model")) if role == "assistant" else None
    effort = agent_turns.clean_effort(raw.get("effort")) if role == "assistant" else None
    return Turn(role=role, text=cleaned, ts=_stamp(raw.get("ts")), model=model, effort=effort,
                reply_gap=reply_gap), n


def from_wire(data, *, harness: str, session_id: str, cwd: str | None, keep_assistant: bool = True) -> Conversation:
    """Rebuild the extractor's ``Conversation`` from a post, checking everything (see the module doc)."""
    if not isinstance(data, dict):
        raise PostRefused("bad_conversation")
    raw_turns = data.get("kept")
    if not isinstance(raw_turns, list) or len(raw_turns) > MAX_TURNS:
        raise PostRefused("bad_conversation")
    raw_gap = data.get("gap")
    gap = None
    if raw_gap is not None:
        if not isinstance(raw_gap, dict):
            raise PostRefused("bad_gap")
        after = _count(raw_gap.get("after"))
        if after > len(raw_turns):
            raise PostRefused("bad_gap")
        gap = Gap(after=after, dropped=_count(raw_gap.get("dropped")), first_at=_stamp(raw_gap.get("first_at")),
                  last_at=_stamp(raw_gap.get("last_at")))
    turns: list[Turn] = []
    scrubbed = 0
    seen_user = False
    kept_before_gap = 0
    for i, raw in enumerate(raw_turns):
        turn, n = _turn(raw, first_user=not seen_user)
        scrubbed += n
        if isinstance(raw, dict) and raw.get("role") == "user":
            seen_user = True
        if turn is None or (turn.role == "assistant" and not keep_assistant):
            continue
        if gap is not None and i < gap.after:
            kept_before_gap += 1
        turns.append(turn)
    if gap is not None:
        gap = Gap(after=kept_before_gap, dropped=gap.dropped, first_at=gap.first_at, last_at=gap.last_at)
    if sum(len(t.text) for t in turns) > SESSION_CAP_CHARS:
        turns, gap = window(turns, gap)

    raw_summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    summary: dict = {}
    for key in _COUNTER_KEYS:
        value = raw_summary.get(key)
        summary[key] = ({str(k)[:32]: _count(v) for k, v in list(value.items())[:64]}
                        if isinstance(value, dict) else {})
    for key in _INT_KEYS:
        summary[key] = _count(raw_summary.get(key, 0))
    summary["scrubbed"] += scrubbed
    summary["first_request_clipped"] = raw_summary.get("first_request_clipped") is True
    started_at = ended_at = None
    kept = {"user": 0, "assistant": 0}
    note_like = 0
    for t in turns:
        kept[t.role] += 1
        if t.role == "user" and _NOTE_LINE_RE.search(t.text):
            note_like += 1
        if t.ts:
            started_at = started_at or t.ts
            ended_at = t.ts
    summary.update({"kept": kept, "session_cap_hit": gap is not None, "refused_turns": gap.dropped if gap else 0,
                    "note_like_turns": note_like})
    last_seen = _stamp(data.get("last_seen_at")) or ended_at
    return Conversation(harness=harness, session_id=session_id, cwd=cwd, started_at=started_at, ended_at=ended_at,
                        turns=turns, summary=summary, last_seen_at=last_seen, gap=gap)
