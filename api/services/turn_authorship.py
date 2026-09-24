"""Which model, at which reasoning effort, wrote a harness claim — joined at
read, never stored (round 4 D1, contracts C3/C4; G49's reservation lifted for
harness writes, TODO ruling 11).

G49 kept a conversation's model reserved because nothing that wrote memory
recorded one. Round 4 records it where it is already known: the Stop-hook
capture keeps each agent turn's `model`/`effort` in the episode's `turns`
sidecar (C1), and every claim written through the MCP seam carries
`recorded_ts` (C2). This module joins the two, per request, from bank files:

* a claim → its first writer's `session_id` → that session's capture episode
  (`capture_kind: transcript`; an MCP episode of the same session never is) →
  the last person's turn at or before `recorded_ts` → the agent turn that
  answered it (the next agent entry before the next person's). No such turn →
  null. No `recorded_ts` (written before C2) → the session's only model, when it
  used exactly one (R4B-6).
* an evidence span of kind `assistant` → the turn its start falls in, by the
  body's own turn starts, unless the span is stale (R4B-7).

Never self-reported: an agent asked for its model can only guess, and a guess
in provenance is worse than a blank (D1). Only author kind `harness` is joined —
a Sleep claim's model is its `Cicada-Author`. Engine-free: `bank_index`'s cached
frontmatter, and at most one body read per cited episode per request, only for
an episode whose sidecar names a model.
"""

from __future__ import annotations

import bisect
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from api.models.schemas import EvidenceModel
from api.services import agent_turns, bank_index, episode_staging, evidence, git_service
from api.services.claims import Claim, Evidence

#: `transcript_capture.CAPTURE_KIND`, spelled here: the read paths must never
#: import the capture writer (`test_the_provenance_module_is_engine_free`).
CAPTURE_KIND = "transcript"

Pair = tuple[str | None, str | None]
NONE: Pair = (None, None)


def _second(value) -> datetime | None:
    """An aware instant floored to the second, or None. `recorded_ts` has second
    precision and a turn's `ts` has milliseconds, so both sides are floored: a
    question asked at 10:05:00.600 and a write stamped 10:05:00 are the same
    second, and the write belongs to that question's turn (R4B-6)."""
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value or "").strip())
        except ValueError:
            return None
    if dt.tzinfo is None:
        return None
    return dt.astimezone(timezone.utc).replace(microsecond=0)


def turn_at(stamps: list[agent_turns.Stamp], recorded_ts) -> Pair:
    """C3's join over one session's sidecar. Pure."""
    moment = _second(recorded_ts)
    if moment is None or not stamps:
        return NONE
    if len(stamps) >= episode_staging.MAX_TURN_STAMPS:
        # Turns past the head-stable cap carry no stamp: a write after the last
        # stamped turn could belong to any of them.
        last = _second(stamps[-1].ts)
        if last is None or moment >= last:
            return NONE
    asked = None
    for i, s in enumerate(stamps):
        if s.speaker != "user":
            continue
        at = _second(s.ts)
        if at is None:
            continue
        if at > moment:
            break
        asked = i
    if asked is None:
        return NONE
    for s in stamps[asked + 1:]:
        if s.speaker == "user":
            return NONE          # that question got no kept reply (tool calls only)
        if s.speaker == "assistant":
            return (s.model, s.effort)
    return NONE                  # the reply is not captured yet — the next Stop adds it


def only_pair(stamps: list[agent_turns.Stamp]) -> Pair:
    """A claim with no `recorded_ts`: the session's model when it used exactly
    one, and its effort by the same rule, independently."""
    models = {s.model for s in stamps if s.speaker == "assistant" and s.model}
    efforts = {s.effort for s in stamps if s.speaker == "assistant" and s.effort}
    return (next(iter(models)) if len(models) == 1 else None,
            next(iter(efforts)) if len(efforts) == 1 else None)


class TurnAuthorship:
    """One request's join. Build one per request and pass it to every
    `claim_to_model` call; `text` shares the caller's body cache (the timeline's
    `episode_text`, provenance's `_Episodes.body`) so a body is read once."""

    def __init__(self, memory_path: Path | None, *, text: Callable[[str], str | None] | None = None,
                 frontmatter: Callable[[str], dict | None] | None = None):
        self._path = Path(memory_path) if memory_path is not None else None
        self._text = text
        # A caller that already holds an episode's frontmatter (`/citations`
        # reads its one document) answers `stamps` from it, so a span join
        # never costs a scan of every episode — that route's parse budget
        # (`test_only_pages_that_name_the_episode_are_parsed`). None falls
        # through to `bank_index`.
        self._frontmatter = frontmatter
        self._files: dict[str, bank_index.IndexedFile] | None = None
        self._by_session: dict[str, str] | None = None
        self._stamps: dict[str, list[agent_turns.Stamp]] = {}
        self._bodies: dict[str, str | None] = {}
        self._starts: dict[str, list[int]] = {}

    def _index(self) -> dict[str, bank_index.IndexedFile]:
        if self._files is None:
            self._files = ({f.stem: f for f in bank_index.files(self._path, "episodes")}
                           if self._path is not None else {})
        return self._files

    def _capture_of(self, session_id: str) -> str | None:
        if self._by_session is None:
            self._by_session = {}
            for stem, f in sorted(self._index().items()):
                fm = f.frontmatter or {}
                sid = str(fm.get("session_id") or "").strip()
                if sid and fm.get("capture_kind") == CAPTURE_KIND:
                    self._by_session.setdefault(sid, stem)
        return self._by_session.get(session_id)

    def stamps(self, episode: str) -> list[agent_turns.Stamp]:
        if episode not in self._stamps:
            fm = self._frontmatter(episode) if self._frontmatter is not None else None
            if fm is None:
                f = self._index().get(episode)
                fm = f.frontmatter if f is not None else None
            self._stamps[episode] = agent_turns.stamps(fm)
        return self._stamps[episode]

    def _body(self, episode: str) -> str | None:
        if episode not in self._bodies:
            if self._text is not None:
                self._bodies[episode] = self._text(episode)
            else:
                f = self._index().get(episode)
                try:
                    self._bodies[episode] = f.body() if f is not None else None
                except Exception:  # noqa: BLE001 — one unreadable episode never fails a read
                    self._bodies[episode] = None
        return self._bodies[episode]

    def for_claim(self, claim: Claim, author_kind: str) -> Pair:
        if author_kind != git_service.HARNESS_KIND:
            return NONE
        sid = (claim.session_id or "").strip()
        episode = self._capture_of(sid) if sid else None
        if episode is None:
            return NONE
        stamps = self.stamps(episode)
        return turn_at(stamps, claim.recorded_ts) if claim.recorded_ts else only_pair(stamps)

    def for_span(self, ev: Evidence) -> Pair:
        if ev.kind != "assistant" or not ev.is_span() or not evidence.is_episode_id(ev.episode):
            return NONE
        stamps = self.stamps(ev.episode)
        if not any(s.model or s.effort for s in stamps):
            return NONE          # nothing to find: no body read
        body = self._body(ev.episode)
        if body is None or ev.end > len(body):
            return NONE
        if evidence.span_status(body, end=ev.end, hash=ev.hash) == evidence.SPAN_STALE:
            return NONE          # stale never answers (§4.9)
        starts = self._starts.setdefault(ev.episode, evidence.turn_starts(body))
        i = bisect.bisect_right(starts, ev.start) - 1
        if i < 0:
            return NONE
        hit = next((s for s in stamps if s.offset == starts[i]), None)
        return (hit.model, hit.effort) if hit is not None and hit.speaker == "assistant" else NONE


def evidence_model(ev: Evidence, turns: TurnAuthorship | None) -> EvidenceModel:
    """One span on the wire (G118) with its turn's model (C3). `turns=None`
    serves the two fields as null — a caller with no bank to read."""
    model, effort = turns.for_span(ev) if turns is not None else NONE
    return EvidenceModel(**ev.to_dict(), model=model, effort=effort)
