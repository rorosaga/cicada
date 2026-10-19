"""Capture for a harness whose hooks post each turn's text (capture-everywhere).

Claude Code and Codex hand their Stop hook a transcript path, and
``transcript_capture`` re-reads the whole session on every firing. Cursor and
Gemini CLI hand their hooks a ``transcript_path`` too, but neither documents the
file's format, a confined root or the order its final message lands in — and
Cursor's may be null — so nothing proves which bytes are the person's and which
the final reply. Their hooks carry the words themselves, so those are used and
the transcript is never opened:

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

import hashlib
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
#: Ruling 31: a turn relayed by a hookless app's model through the remote connector. The episode records the
#: channel under this key, and declares ``evidence_kind: assistant`` — the person's words reached Cicada through a
#: model that may paraphrase, so they are never counted as the person's own (promotion, ruling-29 settling) until an
#: export of the same conversation upgrades the episode (``episode_staging``).
RELAY_KEY = "relay"
#: The shortest first message an export may be matched on: below this, two conversations could share it.
RELAY_MATCH_MIN = 24


def relay_match_key(text: str | None) -> str | None:
    """What a relayed conversation and its export are matched on: the cleaned first person message, case-folded,
    letters and digits only, its first 400 — a model relaying "verbatim" may still move spaces or punctuation. ``None``
    for a message too short to tell two conversations apart."""
    folded = re.sub(r"[\W_]+", "", (text or "").casefold())[:400]
    if len(folded) < RELAY_MATCH_MIN:
        return None
    return hashlib.sha256(folded.encode("utf-8")).hexdigest()[:16]


@dataclass
class Posted:
    speaker: str
    text: str


def _refuse(harness: str, session_id: str, bank, reason: str, event) -> tc.CaptureResult:
    tc._record(harness, session_id, "refused", None, bank, reason, event=event)
    return tc.CaptureResult("refused", None, 0, 0, {}, reason=reason)


def _int(value) -> int:
    """A stored offset or count: a real non-negative integer, else ``ValueError``
    (a hand-written ``.inf``, a float, a bool or a string never becomes one)."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("not an offset")
    return value


def _load(stored) -> tuple[list[Turn], list[str | None], Gap | None, bool] | None:
    """The kept turns, their hook ids and the gap, read back from the episode.
    ``None`` when the episode does not re-render byte for byte from its own
    ``hook_turns`` — hand-edited, hand-poisoned, or written by another writer — so
    a firing never rewrites a body it cannot account for and never answers 500."""
    try:
        return _load_strict(stored)
    except (KeyError, TypeError, ValueError, OverflowError, AttributeError):
        return None


def _load_strict(stored):
    fm, body = stored.frontmatter, stored.body
    entries = fm.get(STATE_KEY)
    if not isinstance(entries, list) or not entries or not all(isinstance(e, dict) for e in entries):
        return None
    gap = None
    gap_meta = fm.get("capture_gap")
    gap_at = dropped = None
    if gap_meta is not None:
        gap_at = _int(gap_meta["offset"])
        dropped = _int(gap_meta["dropped_turns"])
    offsets = [_int(e["offset"]) for e in entries]
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
        gap_info = e.get("reply_gap")
        if gap_info is not None:
            # capture_meta reads both keys; a poisoned entry is a mismatch, not a 500.
            gap_info = {"offset": _int(gap_info["offset"]), "omitted_chars": _int(gap_info["omitted_chars"])}
        turn_id = e.get("id")
        if turn_id is not None and not (isinstance(turn_id, str) and _TURN_ID_RE.match(turn_id)):
            return None
        turns.append(Turn(role=speaker, text=body[at + len(prefix):end],
                          ts=e.get("at") if isinstance(e.get("at"), str) else None,
                          model=e.get("model") if isinstance(e.get("model"), str) else None, reply_gap=gap_info))
        ids.append(turn_id)
    if gap_at is not None:
        after = sum(1 for at in offsets if at < gap_at)
        gap = Gap(after=after, dropped=dropped, first_at=gap_meta.get("first_dropped_at"),
                  last_at=gap_meta.get("last_dropped_at"))
    probe = Conversation(harness="", session_id=None, cwd=None, started_at=None, ended_at=None,
                         turns=turns, gap=gap)
    if tc._body(probe) != body:
        return None
    flags = fm.get("capture_flags")
    clipped = bool(flags.get("first_request_clipped")) if isinstance(flags, dict) else False
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
    relay: dict | None = None,
) -> tc.CaptureResult:
    """Merge the posted turns into the session's one episode and write it.

    ``relay`` (ruling 31) marks turns a hookless app's model relayed through the remote connector: ``{app,
    connector, channel}``. Any catalog harness is then accepted, the episode carries the channel and
    ``evidence_kind: assistant``, and an episode an export already upgraded is left alone (``upgraded``).

    ``status`` is ``transcript_capture``'s vocabulary: ``refused`` (a demo bank,
    a bad harness, session or turn id, or ``state_mismatch``; nothing written),
    ``empty`` (nothing survived cleaning and there is no episode yet),
    ``created``, ``updated`` (re-queued for Sleep), ``unchanged``, ``metadata``."""
    if demo_guard.is_demo(memory_path):
        return _refuse(harness, session_id, bank, "demo_bank", hook_event)
    if harness not in HARNESSES and relay is None:
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
        if relay is not None and stored is not None and isinstance(stored.frontmatter.get(RELAY_KEY), dict) \
                and stored.frontmatter[RELAY_KEY].get("upgraded_at"):
            return tc.CaptureResult("upgraded", str(stored.frontmatter.get("id") or existing.stem), 0, 0, {})
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
        extra: dict = {STATE_KEY: _entries(conv, ids)}
        if relay is not None:
            first = next((t.text for t in kept if t.role == "user"), None)
            extra = {"evidence_kind": "assistant",
                     RELAY_KEY: {**{k: v for k, v in relay.items() if v is not None},
                                 "first": relay_match_key(first)},
                     **extra}
        return tc.write_session(memory_path, harness=harness, session_id=sid, conv=conv, existing=existing,
                                cwd=cwd, bank=bank, effort=None, bank_paths=bank_paths if use_registry else None,
                                hook_event=hook_event, registry_workspace=registry_workspace,
                                extra=extra, stored=stored)
