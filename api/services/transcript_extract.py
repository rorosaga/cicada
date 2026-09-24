"""Deterministic, block-level transcript extraction (G105).

Capture used to be agent judgment: an episode existed only if a model chose
to call ``cicada_save_episode`` (measured: zero MCP tool invocations in 12
days; four episodes from one very long session — TODO.md ruling 6). This
module is the other rung of G80's ladder: a *parser* decides what is
conversation content, and it decides the same way every time.

The RULING (G105, 2026-09-03) is implemented literally:

* keep (a) the person's turns — ``user`` messages whose blocks are ``text``;
  a ``user`` message carrying a ``tool_result`` is tool output wearing the
  user role and is dropped without becoming a turn boundary (R4);
* keep (b) the agent's FINAL reply per turn — the ``text`` blocks after the
  last ``tool_use`` and before the next boundary; interstitial narration,
  every ``tool_use`` / ``tool_result`` / ``thinking`` block and every file
  dump are skipped by construction, not by heuristics;
* from (b)'s lines, exactly two more facts and nothing else of them (round 4
  D1, C1): the model id and the reasoning effort — Claude Code's
  ``message.model`` and top-level ``effort``, Codex's ``turn_context.payload.model``
  and ``.effort`` — cleaned by ``agent_turns`` (unknown values dropped) and
  carried on the agent turn only;
* on what survives: fenced code stripped, secrets scrubbed, a per-turn cap
  and a head-stable session cap (R6);
* ``keep_assistant=False`` drops (b) — the owner's fallback if the assistant
  half proves noisy (R7).

The G48 rail is restated, not removed: tool output, code and secrets never
enter a bank. This module never opens a file — it takes lines — so the
only transcript read stays where R2 puts it (``transcript_capture``).

A note Cicada's own recall hook added (G149) is never the person's words,
whatever shape the harness stores it in (``recall_text.is_injection``,
``_HOOK_OUTPUT_RE``): captured as "the person said", it would hand Sleep its
own memory as new evidence (R-H12).

Pure: no bank state, no LLM, no I/O. ``summary`` carries counts only so it
can go straight into the ledger (R10).
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable

from api.services import recall_text
from api.services.episode_scrub import REDACTED, scrub as _scrub  # R-LS6: one rule set
from api.services.agent_turns import clean_effort, clean_model  # round 4 C1: one vocabulary

HARNESSES = ("claude-code", "codex")

#: ~2,000 chars is the ruling's per-turn cap: enough for a real question or
#: a real answer, small enough that a pasted log cannot become an episode.
TURN_CAP_CHARS = 2000
#: Head-stable session cap (R6): the first turns are kept, later ones
#: dropped and flagged, so an episode's byte offsets — which G118 spans
#: point into — do not move between two hook firings on the same session.
SESSION_CAP_CHARS = 100_000

CODE_OMITTED = "[code omitted]"

# Harness-injected user text, by the tag it opens with (R5). Verified against
# a real transcript's key names on 2026-09-03: these wear the user role but
# are the harness talking to the model, not the person.
CLAUDE_HARNESS_TAGS = frozenset({
    "task-notification", "command-name", "command-message", "command-args",
    "command-stdout", "local-command-stdout", "local-command-caveat",
    "system-reminder", "ide_opened_file", "ide_selection", "ide_diagnostics",
    # G149 R-H12: tag names hook output could arrive under. Unverified here (no
    # transcript is read, R2); a person never types them, so dropping them
    # costs nothing.
    "user-prompt-submit-hook", "session-start-hook",
})
CODEX_HARNESS_TAGS = frozenset({
    "environment_context", "user_instructions", "permissions",
    "apps_instructions", "skills_instructions", "plugins_instructions",
    "turn_aborted", "collaboration_mode",
})

_SYSTEM_REMINDER_RE = re.compile(r"<system-reminder>.*?</system-reminder>", re.DOTALL)
# G149 R-H12: the same tags as a SPAN, stripped wherever it sits in a block,
# like a system reminder. `_first_tag` reads only a block's first tag, so hook
# output a harness appended after the person's prompt would otherwise be kept.
_HOOK_OUTPUT_RE = re.compile(r"<(user-prompt-submit-hook|session-start-hook)>.*?</\1>", re.DOTALL)
_LEADING_TAG_RE = re.compile(r"^\s*<([A-Za-z_][A-Za-z0-9_-]*)")
_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_OPEN_FENCE_RE = re.compile(r"```.*\Z", re.DOTALL)
# Cheap pre-parse gate for Claude Code lines (R6): a user/assistant line
# always contains this; an attachment / file-history-snapshot line usually
# does not, and those are the bulk of a large transcript.
_CLAUDE_PREFILTER = re.compile(r'"type"\s*:\s*"(?:user|assistant)"')

@dataclass
class Turn:
    role: str  # "user" | "assistant"
    text: str
    ts: str | None
    # Round 4 C1: set on an agent turn only — what the harness recorded for the
    # kept reply's line; never inferred (R4B-2).
    model: str | None = None
    effort: str | None = None


@dataclass
class Conversation:
    harness: str
    session_id: str | None
    cwd: str | None
    started_at: str | None
    ended_at: str | None
    turns: list[Turn] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


# --- cleaning ----------------------------------------------------------------


def strip_code_fences(text: str) -> str:
    """Replace every ``` fenced block — and an unterminated trailing one —
    with ``[code omitted]``. Code is memorialised in the repo and its git
    history (G105: "Cicada storing a bash command duplicates git badly");
    what a fence held is also the densest place a secret hides."""
    out = _FENCE_RE.sub(CODE_OMITTED, text)
    out = _OPEN_FENCE_RE.sub(CODE_OMITTED, out)
    return out.strip()


def scrub_secrets(text: str) -> tuple[str, int]:
    """The extractor's name for :func:`api.services.episode_scrub.scrub` (R-LS6).

    The rules moved out so every episode writer — not only this Stop-hook path —
    scrubs with the same list (R-N3); the one-time-code family arrived with the
    move, so a code pasted into a session is now redacted here too."""
    return _scrub(text)


def _first_tag(text: str) -> str | None:
    m = _LEADING_TAG_RE.match(text)
    return m.group(1).lower() if m else None


def _text_blocks(content) -> list[dict]:
    """A string body becomes one text block so both shapes flow through the
    same per-block filter (R5 — filtering is per block, never per message)."""
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        return [b for b in content if isinstance(b, dict)]
    return []


class _Builder:
    """Turn assembly shared by both harnesses: R4's boundary rule, the
    final-reply-per-turn pending buffer, R6's cleaning order and caps."""

    def __init__(self, harness: str, *, keep_assistant: bool, turn_cap: int, session_cap: int):
        self.harness = harness
        self.keep_assistant = keep_assistant
        self.turn_cap = turn_cap
        self.session_cap = session_cap
        self.turns: list[Turn] = []
        self.pending: list[tuple[str, str | None, str | None, str | None]] = []
        self.kept: Counter = Counter()
        self.dropped_blocks: Counter = Counter()
        self.dropped_messages: Counter = Counter()
        self.truncated_turns = 0
        self.scrubbed = 0
        self.session_cap_hit = False
        self.total_chars = 0
        self.started_at: str | None = None
        self.ended_at: str | None = None

    # -- counting -------------------------------------------------------------
    def count_block(self, kind: str, n: int = 1) -> None:
        self.dropped_blocks[kind or "unknown"] += n

    def count_msg(self, kind: str, n: int = 1) -> None:
        self.dropped_messages[kind] += n

    # -- turns ------------------------------------------------------------------
    def user(self, text: str, ts: str | None) -> None:
        self.boundary()
        self._add("user", text, ts)

    def assistant_text(self, text: str, ts: str | None, model=None, effort=None) -> None:
        if text and text.strip():
            self.pending.append((text, ts, clean_model(model), clean_effort(effort)))

    def assistant_tool_call(self) -> None:
        """A tool call means everything the agent said so far this turn was
        narration on the way to the tool, not the reply (R4)."""
        self.count_block("interstitial", len(self.pending))
        self.pending = []

    def boundary(self) -> None:
        if not self.pending:
            return
        joined = "\n\n".join(p[0] for p in self.pending)
        ts = self.pending[-1][1]
        # R4B-2: the last line of the kept reply that names one — the line whose
        # `ts` the turn already takes; narration before a tool was dropped with it.
        model = next((p[2] for p in reversed(self.pending) if p[2]), None)
        effort = next((p[3] for p in reversed(self.pending) if p[3]), None)
        self.pending = []
        if not self.keep_assistant:
            self.count_msg("assistant_by_flag")
            return
        self._add("assistant", joined, ts, model=model, effort=effort)

    def _add(self, role: str, text: str, ts: str | None, *, model=None, effort=None) -> None:
        cleaned = strip_code_fences(text)
        cleaned, n = scrub_secrets(cleaned)
        self.scrubbed += n
        cleaned = cleaned.strip()
        if not cleaned:
            self.count_msg("empty")
            return
        if len(cleaned) > self.turn_cap:
            cleaned = cleaned[: self.turn_cap - 1] + "…"
            self.truncated_turns += 1
        if self.total_chars + len(cleaned) > self.session_cap:
            self.session_cap_hit = True
            return
        self.turns.append(Turn(role=role, text=cleaned, ts=ts, model=model, effort=effort))
        self.total_chars += len(cleaned)
        self.kept[role] += 1
        if ts:
            self.started_at = self.started_at or ts
            self.ended_at = ts

    def finish(self, session_id: str | None, cwd: str | None) -> Conversation:
        self.boundary()
        return Conversation(
            harness=self.harness,
            session_id=session_id,
            cwd=cwd,
            started_at=self.started_at,
            ended_at=self.ended_at,
            turns=self.turns,
            summary={
                "kept": {"user": self.kept["user"], "assistant": self.kept["assistant"]},
                "dropped_blocks": dict(self.dropped_blocks),
                "dropped_messages": dict(self.dropped_messages),
                "truncated_turns": self.truncated_turns,
                "scrubbed": self.scrubbed,
                "session_cap_hit": self.session_cap_hit,
            },
        )


def _parse(raw: str, b: _Builder) -> dict | None:
    try:
        obj = json.loads(raw)
    except ValueError:
        b.count_msg("bad_json")
        return None
    if not isinstance(obj, dict):
        b.count_msg("bad_json")
        return None
    return obj


# --- Claude Code -------------------------------------------------------------


def extract_claude_code(
    lines: Iterable[str],
    *,
    keep_assistant: bool = True,
    turn_cap: int = TURN_CAP_CHARS,
    session_cap: int = SESSION_CAP_CHARS,
) -> Conversation:
    """One Claude Code transcript (JSONL lines) → the ruling's conversation."""
    b = _Builder("claude-code", keep_assistant=keep_assistant, turn_cap=turn_cap, session_cap=session_cap)
    session_id: str | None = None
    cwd: str | None = None
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        if not _CLAUDE_PREFILTER.search(raw):
            b.count_msg("other_type")
            continue
        obj = _parse(raw, b)
        if obj is None:
            continue
        typ = obj.get("type")
        if typ not in ("user", "assistant"):
            b.count_msg("other_type")
            continue
        session_id = session_id or (str(obj.get("sessionId") or "") or None)
        cwd = cwd or (str(obj.get("cwd") or "") or None)
        if obj.get("isSidechain"):
            b.count_msg("sidechain")
            continue
        if obj.get("isCompactSummary"):
            b.count_msg("compact_summary")
            continue
        msg = obj.get("message") if isinstance(obj.get("message"), dict) else {}
        blocks = _text_blocks(msg.get("content"))
        ts = str(obj.get("timestamp") or "") or None

        if typ == "user":
            kinds = Counter(str(bk.get("type") or "") for bk in blocks)
            if kinds.get("tool_result"):
                # Tool output wearing the user role: dropped, and NOT a
                # boundary (R4) — the agent's turn is still in progress.
                b.count_block("tool_result", kinds["tool_result"])
                continue
            b.boundary()
            if obj.get("isMeta"):
                b.count_msg("meta")
                continue
            for k, n in kinds.items():
                if k != "text":
                    b.count_block(k, n)
            kept: list[str] = []
            tagged = 0
            for bk in blocks:
                if bk.get("type") != "text":
                    continue
                text = _HOOK_OUTPUT_RE.sub("", _SYSTEM_REMINDER_RE.sub("", str(bk.get("text") or "")))
                tag = _first_tag(text)
                if tag in CLAUDE_HARNESS_TAGS or recall_text.is_injection(text):
                    tagged += 1
                    continue
                if text.strip():
                    kept.append(text)
            if not kept:
                b.count_msg("harness_tag" if tagged else "empty")
                continue
            b.user("\n".join(kept), ts)
        else:
            if obj.get("isApiErrorMessage"):
                b.count_msg("api_error")
                continue
            # Round 4 D1 (C1): exactly two keys of an agent line — `message.model`
            # and the top-level `effort` (a `{level}` object is read the same way).
            # Thinking, usage and every other key stay unread (G105).
            model = msg.get("model")
            effort = obj.get("effort")
            if isinstance(effort, dict):
                effort = effort.get("level")
            for bk in blocks:
                k = str(bk.get("type") or "")
                if k == "text":
                    b.assistant_text(str(bk.get("text") or ""), ts, model, effort)
                elif k == "tool_use":
                    b.count_block("tool_use")
                    b.assistant_tool_call()
                elif k in ("thinking", "redacted_thinking"):
                    b.count_block("thinking")
                else:
                    b.count_block(k)
    return b.finish(session_id, cwd)


# --- Codex ---------------------------------------------------------------------


def extract_codex(
    lines: Iterable[str],
    *,
    keep_assistant: bool = True,
    turn_cap: int = TURN_CAP_CHARS,
    session_cap: int = SESSION_CAP_CHARS,
) -> Conversation:
    """One Codex rollout (JSONL lines) → the same conversation shape.

    Only ``response_item`` lines carry turns; ``event_msg`` ``user_message`` /
    ``agent_message`` lines duplicate them and are counted as ``other_type``.
    ``function_call`` is Codex's ``tool_use`` (resets the pending reply);
    ``function_call_output`` its ``tool_result``; ``reasoning`` its thinking.
    """
    b = _Builder("codex", keep_assistant=keep_assistant, turn_cap=turn_cap, session_cap=session_cap)
    session_id: str | None = None
    cwd: str | None = None
    ctx_model = ctx_effort = None
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        obj = _parse(raw, b)
        if obj is None:
            continue
        typ = obj.get("type")
        payload = obj.get("payload") if isinstance(obj.get("payload"), dict) else {}
        ts = str(obj.get("timestamp") or "") or None
        if typ == "session_meta":
            session_id = session_id or (str(payload.get("id") or "") or None)
            cwd = cwd or (str(payload.get("cwd") or "") or None)
            continue
        if typ == "turn_context":
            # Round 4 D1 (C1): the model and reasoning effort for the agent turns
            # that follow, until the next turn_context — these two payload keys
            # only; instructions, policies and summaries are never read. Counted
            # as before, so the ledger's counts do not move.
            ctx_model, ctx_effort = payload.get("model"), payload.get("effort")
            b.count_msg("other_type")
            continue
        if typ != "response_item":
            b.count_msg("other_type")
            continue
        ptype = str(payload.get("type") or "")
        if ptype == "message":
            role = str(payload.get("role") or "")
            texts = [
                str(bk.get("text") or "")
                for bk in (payload.get("content") or [])
                if isinstance(bk, dict) and bk.get("type") in ("input_text", "output_text")
            ]
            if role == "user":
                b.boundary()
                kept = [t for t in texts
                        if _first_tag(t) not in CODEX_HARNESS_TAGS and not recall_text.is_injection(t) and t.strip()]
                if not kept:
                    b.count_msg("harness_tag" if texts else "empty")
                    continue
                b.user("\n".join(kept), ts)
            elif role == "assistant":
                b.assistant_text("\n".join(texts), ts, ctx_model, ctx_effort)
            else:
                b.count_msg("developer")
        elif ptype == "function_call":
            b.count_block("function_call")
            b.assistant_tool_call()
        elif ptype == "function_call_output":
            b.count_block("function_call_output")
        elif ptype == "reasoning":
            b.count_block("reasoning")
        else:
            b.count_block(ptype)
    return b.finish(session_id, cwd)


def extract(harness: str, lines: Iterable[str], **kw) -> Conversation:
    if harness == "claude-code":
        return extract_claude_code(lines, **kw)
    if harness == "codex":
        return extract_codex(lines, **kw)
    raise ValueError(f"unknown harness {harness!r} (known: {', '.join(HARNESSES)})")
