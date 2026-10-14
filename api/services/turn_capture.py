"""Capture for a harness whose hooks post each turn's text (capture-everywhere).

Claude Code and Codex hand their Stop hook a transcript path, and
``transcript_capture`` re-reads the whole session on every firing. Cursor and
Gemini CLI document no transcript format, but their hooks carry the words
themselves:

* **Cursor** — ``beforeSubmitPrompt`` carries ``prompt`` (the person's turn) and
  ``afterAgentResponse`` carries ``text`` (the agent's reply), each with the
  conversation's ``conversation_id`` and the run's ``generation_id``.
* **Gemini CLI** — ``AfterAgent`` carries ``prompt`` and ``prompt_response``
  (one whole exchange) with ``session_id``, and ``stop_hook_active`` when the
  turn is a retry of the same prompt.

The hook (``api/hooks/cursor.py``, ``api/hooks/capture.py --harness
gemini-cli``) posts those strings and nothing else; this module is the only
place they become an episode. The backend never opens a path for them.

The episode is the state. A posted turn is cleaned exactly like a transcript
turn (``transcript_extract.clean_turn``: code fences stripped, secrets scrubbed,
16k for the first person message, 2k for every other turn), merged into the
turns the session's ONE episode already holds (G104), windowed by the same
session cap (``transcript_extract.window``: the head stays, the tail slides, the
middle is counted and marked), and written by ``transcript_capture.write_session``
— the same body, hash, sidecar and G110 metadata as a Stop-hook episode
(``capture_kind: transcript``). The kept turns' boundaries ride in ``hook_turns``
(offset, speaker, the hook's turn id, its time, the agent's model, a clipped
reply's gap) so the next firing can split the body back into turns exactly; a
body that does not re-render byte for byte from them is never rewritten
(``state_mismatch``).

Idempotent: a re-fired turn with the same id and the same cleaned text changes
nothing (``unchanged``); a later reply for the same Cursor ``generation_id``
replaces the earlier one, so only the run's final reply is kept (the G105 rule,
unverified against an installed Cursor: one ``afterAgentResponse`` per run is
equally fine). No LLM anywhere.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from api.services import continuity_sessions, demo_guard, episode_ids, markdown_parser
from api.services import transcript_capture as tc
from api.services.transcript_extract import (
    _NOTE_LINE_RE, Conversation, Gap, Turn, clean_turn, window,
)

#: Harnesses whose hooks post turns. Each must also be in ``episode_title.PRODUCT``.
HARNESSES = ("cursor", "gemini-cli")
STATE_KEY = "hook_turns"
#: A hook-supplied turn id (Cursor's ``generation_id``): an opaque token, bounded.
_TURN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
SPEAKERS = ("user", "assistant")
#: The most a hook posts for one turn (it trims to this). Far above what the
#: cleaned turn keeps (16k / 2k), so code stripped before the cap still leaves
#: the words; a bound on the request, not a budget.
TEXT_MAX_CHARS = 256 * 1024


@dataclass
class Posted:
    speaker: str
    text: str


def _refuse(harness: str, session_id: str, bank, reason: str, event) -> tc.CaptureResult:
    tc._record(harness, session_id, "refused", None, bank, reason, event=event)
    return tc.CaptureResult("refused", None, 0, 0, {}, reason=reason)


def _load(stored) -> tuple[list[Turn], list[str | None], Gap | None, bool] | None:
    """The kept turns, their hook ids and the gap, read back from the episode.
    ``None`` when the episode does not re-render byte for byte from its own
    ``hook_turns`` — hand-edited, or written by another writer — so a firing
    never rewrites a body it cannot account for."""
    fm, body = stored.frontmatter, stored.body
    entries = fm.get(STATE_KEY)
    if not isinstance(entries, list) or not entries:
        return None
    gap = None
    gap_meta = fm.get("capture_gap")
    gap_at = None
    if isinstance(gap_meta, dict):
        try:
            gap_at = int(gap_meta.get("offset"))
            dropped = int(gap_meta.get("dropped_turns"))
        except (TypeError, ValueError):
            return None
    try:
        offsets = [int(e["offset"]) for e in entries]
    except (TypeError, KeyError, ValueError):
        return None
    bounds = sorted(set(offsets + ([gap_at] if gap_at is not None else [])))
    turns: list[Turn] = []
    ids: list[str | None] = []
    for e, at in zip(entries, offsets):
        speaker = e.get("speaker")
        prefix = f"{speaker}: "
        if speaker not in SPEAKERS or not body.startswith(prefix, at):
            return None
        later = [b for b in bounds if b > at]
        end = later[0] - 1 if later else len(body)
        gap_info = e.get("reply_gap") if isinstance(e.get("reply_gap"), dict) else None
        turns.append(Turn(role=speaker, text=body[at + len(prefix):end], ts=e.get("at"),
                          model=e.get("model"), reply_gap=dict(gap_info) if gap_info else None))
        ids.append(e.get("id"))
    if gap_at is not None:
        after = sum(1 for at in offsets if at < gap_at)
        gap = Gap(after=after, dropped=dropped, first_at=gap_meta.get("first_dropped_at"),
                  last_at=gap_meta.get("last_dropped_at"))
    probe = Conversation(harness="", session_id=None, cwd=None, started_at=None, ended_at=None,
                         turns=turns, gap=gap)
    if tc._body(probe) != body:
        return None
    clipped = bool((fm.get("capture_flags") or {}).get("first_request_clipped")) \
        if isinstance(fm.get("capture_flags"), dict) else False
    return turns, ids, gap, clipped


def _merge(turns: list[Turn], ids: list[str | None], posted: list[Posted], *, turn_id: str | None, retry: bool,
           now: str, model: str | None, counts: dict) -> bool:
    """Fold the posted turns into ``turns``/``ids`` in place; True when anything moved.

    Keyed (Cursor): a turn with the same id and speaker is replaced when its
    cleaned text differs, else left alone; a new reply lands right after its own
    prompt (a queued follow-up never splits a prompt from its answer), anything
    else is appended. Unkeyed (Gemini CLI, one whole exchange per firing): the
    same exchange again is a no-op, a retry of the last prompt replaces its
    reply, anything else is appended."""
    def cleaned(p: Posted, first: bool) -> Turn | None:
        turn, c = clean_turn(p.speaker, p.text, first=first, ts=now,
                             model=model if p.speaker == "assistant" else None)
        counts["scrubbed"] += c["scrubbed"]
        counts["truncated_turns"] += c["truncated_turns"]
        if turn is not None and c["first_request_clipped"]:
            counts["first_request_clipped"] = True
        return turn

    def has_user(seq) -> bool:
        return any(t.role == "user" for t in seq)

    changed = False
    if turn_id is not None:
        for p in posted:
            idx = next((i for i, (t, k) in enumerate(zip(turns, ids)) if k == turn_id and t.role == p.speaker), None)
            first = p.speaker == "user" and not has_user(turns[:idx] if idx is not None else turns)
            turn = cleaned(p, first)
            if turn is None:
                continue
            if idx is not None:
                if turns[idx].text == turn.text:
                    continue
                turns[idx] = turn
            elif p.speaker == "assistant" and (j := next((i for i, (t, k) in enumerate(zip(turns, ids))
                                                          if k == turn_id and t.role == "user"), None)) is not None:
                turns.insert(j + 1, turn)
                ids.insert(j + 1, turn_id)
            else:
                turns.append(turn)
                ids.append(turn_id)
            changed = True
        return changed

    new: list[Turn] = []
    for p in posted:
        turn = cleaned(p, p.speaker == "user" and not has_user(turns) and not has_user(new))
        if turn is not None:
            new.append(turn)
    if not new:
        return False
    tail = turns[-len(new):]
    if len(tail) == len(new) and all(a.role == b.role and a.text == b.text for a, b in zip(tail, new)):
        return False
    user = next((t for t in new if t.role == "user"), None)
    reply = next((t for t in new if t.role == "assistant"), None)
    if retry and user is not None and reply is not None:
        last_user = max((i for i, t in enumerate(turns) if t.role == "user"), default=None)
        if last_user is not None and turns[last_user].text == user.text:
            del turns[last_user + 1:]
            del ids[last_user + 1:]
            turns.append(reply)
            ids.append(None)
            return True
    turns.extend(new)
    ids.extend([None] * len(new))
    return True


def _entries(conv: Conversation, ids: list[str | None]) -> list[dict]:
    out = []
    for at, turn, key in zip(tc._turn_offsets(conv), conv.turns, ids):
        entry: dict = {"offset": at, "speaker": turn.role}
        if key:
            entry["id"] = key
        if turn.ts:
            entry["at"] = turn.ts
        if turn.model:
            entry["model"] = turn.model
        if turn.reply_gap:
            entry["reply_gap"] = dict(turn.reply_gap)
        out.append(entry)
    return out


def capture_turns(
    memory_path: Path,
    *,
    harness: str,
    session_id: str,
    turns: list[Posted],
    turn_id: str | None = None,
    retry: bool = False,
    model: str | None = None,
    cwd: str | None = None,
    keep_assistant: bool = True,
    bank: str | None = None,
    bank_paths: tuple | None = None,
    hook_event: str | None = None,
) -> tc.CaptureResult:
    """Merge the posted turns into the session's one episode and write it.

    ``status`` is ``transcript_capture``'s vocabulary: ``refused`` (a demo bank,
    a bad harness, session or turn id, or ``state_mismatch``; nothing written),
    ``empty`` (nothing survived cleaning and there is no episode yet),
    ``created``, ``updated`` (re-queued for Sleep), ``unchanged``, ``metadata``."""
    if demo_guard.is_demo(memory_path):
        return _refuse(harness, session_id, bank, "demo_bank", hook_event)
    if harness not in HARNESSES:
        return _refuse(harness, session_id, bank, "bad_harness", hook_event)
    sid = (session_id or "").strip()
    if not tc._SESSION_ID_RE.match(sid):
        return _refuse(harness, session_id, bank, "bad_session_id", hook_event)
    if turn_id is not None and not _TURN_ID_RE.match(turn_id):
        return _refuse(harness, sid, bank, "bad_turn_id", hook_event)
    posted = [p for p in turns if p.speaker in SPEAKERS and (keep_assistant or p.speaker == "user")]
    use_registry = bank_paths is not None and harness in continuity_sessions.HARNESSES
    registry_workspace = None
    if use_registry:
        row = continuity_sessions.get(memory_path, harness, sid, bank_paths=bank_paths) or {}
        registry_workspace = row.get("workspace_identity") or {}

    episodes_dir = memory_path / "episodes"
    with tc._lock, episode_ids.episode_lock(episodes_dir):
        existing = tc._find_session_episode(episodes_dir, harness, sid)
        stored = markdown_parser.parse(existing) if existing is not None else None
        if stored is not None:
            state = _load(stored)
            if state is None:
                return _refuse(harness, sid, bank, "state_mismatch", hook_event)
            kept, ids, gap, clipped = state
        else:
            kept, ids, gap, clipped = [], [], None, False
        counts = {"scrubbed": 0, "truncated_turns": 0, "first_request_clipped": clipped}
        now = episode_ids.utc_now_iso()
        _merge(kept, ids, posted, turn_id=turn_id, retry=retry, now=now, model=model, counts=counts)
        key = {id(t): k for t, k in zip(kept, ids)}
        kept, gap = window(kept, gap)
        ids = [key[id(t)] for t in kept]
        stamps = [t.ts for t in kept if t.ts]
        users = sum(1 for t in kept if t.role == "user")
        conv = Conversation(
            harness=harness, session_id=sid, cwd=cwd,
            started_at=stamps[0] if stamps else None, ended_at=stamps[-1] if stamps else None,
            turns=kept, last_seen_at=stamps[-1] if stamps else None, gap=gap,
            summary={
                "kept": {"user": users, "assistant": len(kept) - users},
                "dropped_blocks": {}, "dropped_messages": {},
                "truncated_turns": counts["truncated_turns"], "scrubbed": counts["scrubbed"],
                "session_cap_hit": gap is not None, "refused_turns": gap.dropped if gap else 0,
                "note_like_turns": sum(1 for t in kept if t.role == "user" and _NOTE_LINE_RE.search(t.text)),
                "first_request_clipped": counts["first_request_clipped"],
            },
        )
        return tc.write_session(memory_path, harness=harness, session_id=sid, conv=conv, existing=existing,
                                cwd=cwd, bank=bank, effort=None, bank_paths=bank_paths if use_registry else None,
                                hook_event=hook_event, registry_workspace=registry_workspace,
                                extra={STATE_KEY: _entries(conv, ids)}, stored=stored)
