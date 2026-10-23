"""Stage 3 — trust-gated claim reconciliation (M5e, THE CORE).

Implements ``docs/goals/m5-prep/sleep-trust-reconciliation.md`` exactly. The
mechanical key ``K = (subject, predicate, context, observer)`` decides *which
belief slot* a claim lands in; **trust decides who may close whom**; recency only
breaks ties *within the same trust tier*; **nothing is ever deleted** (superseded
claims are stamped ``valid_to`` / ``superseded_by`` and stay in the list for the
timeline + ``git blame``).

The load-bearing protection (D2 ADDENDUM rule 3a/3b):

- **No ``agent_extracted`` / ``agent_reflected`` / ``external`` claim may close a
  human (``user_stated`` *and* origin ∈ {manual_edit, clarification}) claim.** It
  COEXISTs (recorded but flagged ``shadowed_by_human`` + a soft *divergence* nudge)
  or becomes a CONFLICT nudge.
- **Only a newer human-sourced claim supersedes a human claim** — the human edits
  their own memory via clarification/conversation, the preferred path.
- Agent-over-agent on a single-valued predicate = mechanical invalidate-and-
  supersede; multi-valued predicates coexist.

Per-epistemic × source_trust decay runs here (lowers ``confidence`` only — never
closes a claim, never touches a human claim's validity).

This module is pure trust/temporal logic. The single-vs-multi-valued cardinality
judgment is injected via ``cardinality_fn`` (default: the ``_predicates.yaml``
map). Stage 3 makes **zero LLM calls in the common mechanical path** by design —
the human-protection rule must be deterministic and auditable.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Callable

from loguru import logger

from api.models.schemas import DecayClass
from api.services import decay_policy, episode_time, inbox_questions, predicates
from api.services.claims import (HAPPENED, MILESTONE, Claim, Evidence, event_cardinality, is_event, is_record,
                                 is_value_claim, same_value_attribute)

# A cardinality oracle: predicate -> True (single-valued) | False (multi-valued).
CardinalityFn = Callable[[str], bool]

# A decay-class oracle: subject entity id -> the subject's DecayClass. Injected
# so this module stays pure trust/temporal logic with no filesystem dependency.
DecayClassFn = Callable[[str], DecayClass]

# A subject oracle (G147): the subject page's class, type, kept weeks and the
# per-type pace, read once per subject (`decay_policy.subject_lookup`).
SubjectFn = Callable[[str], "decay_policy.SubjectDecay"]

# Decay lookup (D2 table): base rate per cycle by epistemic class.
_DECAY_BASE = {"explicit": 0.02, "deductive": 0.05, "inductive": 0.10, "abductive": 0.20}
# source_trust multiplier — user_stated fades ~3x slower than routine extraction.
_DECAY_FACTOR = {
    "user_stated": 0.3,
    "agent_extracted": 1.0,
    "agent_reflected": 1.5,
    "external": 1.0,
}
# A THIRD factor (G66): the SUBJECT entity's decay class. An evergreen subject
# multiplies to 0.0 — its claims never decay — while a volatile subject's fade
# twice as fast. See ``schemas.CLAIM_DECAY_MULTIPLIERS``.

# G141 R-PJ18: `companion_app` is the app's writes (`routers/projects.py`) —
# without it an agent or Sleep claim could supersede the person's milestone or
# Log entry. Only that router (and the synthetic demo) ever sets it; no MCP tool
# accepts an `origin` (`test_human_origin_pin.py`).
_HUMAN_ORIGINS = {"manual_edit", "clarification", "companion_app"}

# G85 §2 / Wave-1 1.8: mirrors conflict_resolver.MAX_DECAY_DAYS_PER_CYCLE — a
# single decay pass never charges more than one week's worth, regardless of
# the actual elapsed gap. Independent safety rail from the one-shot
# `decayed_through` backfill migration: a future outage/paused-schedule gap
# degrades gradually over several cycles instead of one cliff.
MAX_DECAY_DAYS_PER_CYCLE = 7


# --------------------------------------------------------------------------- #
# trust predicates (§ Definitions + §6 degenerate case)
# --------------------------------------------------------------------------- #


def is_human(c: Claim) -> bool:
    """Full human protection requires BOTH user_stated AND a human origin (§6).

    A ``user_stated`` claim whose ``origin`` is a logged harness (the agent
    extracted a first-person statement) is NOT overwrite-protected — protection
    is anchored to ``origin``, which only the manual-edit / clarification /
    companion-app (G141's Projects writes, R-PJ18) paths may set. This closes the spoofing hole where routine extraction could
    self-label its way into immunity.
    """
    return c.source_trust == "user_stated" and (c.origin or "") in _HUMAN_ORIGINS


def is_external(c: Claim) -> bool:
    return c.source_trust == "external"


def K(c: Claim) -> tuple[str, str, str, str]:
    """The mechanical belief-slot key: (subject, predicate, context, observer)."""
    return (c.subject, c.predicate, c.context, c.observer)


def open_(c: Claim) -> bool:
    return c.valid_to is None


def _norm_object(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def same_object(a: Claim, b: Claim) -> bool:
    return _norm_object(a.object) == _norm_object(b.object)


def _date_key(value: str | None) -> str:
    """A sortable date string; missing/blank sorts as empty (oldest)."""
    return (value or "").strip()


# --------------------------------------------------------------------------- #
# stamping helpers — _stamp_new / _close / _reinforce
# --------------------------------------------------------------------------- #


def _stamp_new(claim: Claim, settings, *, today: str, status_note: str | None = None) -> Claim:
    if not claim.recorded_at:
        claim.recorded_at = today
    if not claim.valid_from:
        claim.valid_from = today
    if not claim.authored_by:
        from api.services import engine_select

        # R-E22: on a plan cycle `litellm_model` never ran — stamp the plan's model.
        claim.authored_by = "user" if is_human(claim) else engine_select.author_model(settings)
    if status_note:
        # An out-of-band marker the renderer/app can read; carried on the dataclass
        # without breaking the claims YAML round-trip (it is not a Claim field, so
        # write_claims ignores it — it only matters within this in-memory pass + nudges).
        setattr(claim, "_status_note", status_note)
    return claim


def _close(old: Claim, *, by: Claim) -> None:
    old.valid_to = by.valid_from
    old.superseded_by = by.id
    by.supersedes = old.id


def _merge_episodes(existing: Claim, incoming: Claim) -> None:
    for ep in incoming.source_episodes or []:
        if ep and ep not in existing.source_episodes:
            existing.source_episodes.append(ep)


def _said_refs(claim: Claim) -> list[str]:
    """A claim's conversations: its ``source_episodes`` and the ``ep_*`` documents its evidence cites."""
    refs = list(claim.source_episodes or [])
    for ev in claim.evidence or []:
        doc = str(getattr(ev, "episode", "") or "")
        if doc.startswith("ep_") and doc not in refs:
            refs.append(doc)
    return refs


def _said(claim: Claim, untimed=frozenset()) -> str | None:
    """The day a claim was last said: its latest dated conversation (:func:`_said_refs`), never a memory export
    entry (``episode_time``) or a session id. ``valid_from`` is when the fact became true in the world, not when it
    was said, so it never counts here."""
    return decay_policy.latest_said(_said_refs(claim), untimed=untimed)


def _reinforce(existing: Claim, incoming: Claim, *, today: str | None = None, untimed=frozenset()) -> None:
    """Reaffirmation/duplicate: bump confidence + merge episodes; no new claim.

    With ``today`` (the Stage-3 pass; events pass none), age counts from when it was said, and a restatement never
    leaves a claim lower than it stood:

    * a claim not yet settled (minted or restated earlier in this run, or in one that stopped — proven silence
      still owed) keeps the higher confidence and its watermark follows the latest mention; the decay pass that
      settles it charges from there;
    * a settled claim restated in a conversation no charge has covered yet (said on or after its watermark — an
      agent's live write, with no dated conversation, is said today) is restored: the higher confidence, the
      watermark and ``recorded_at`` at today. Said before today (a capture read late), the restored confidence is
      placed on the day it was said and charged the proven silence since, never below where the claim stood — as a
      page is (``_place_on_time``, once the pass knows the subject's pace);
    * a settled claim restated in a conversation it does not already credit, said before its watermark and read
      late, counts as if read the day it was said (owner 2026-10-16): restored that day and charged the silence since
      (``_place_on_time``), never lowered — a restatement from long ago leaves it where its age puts it;
    * a memory export entry alone, or a conversation the claim already credits, gains the source only.
    """
    if today is None:
        existing.confidence = max(existing.confidence, incoming.confidence)
        _merge_episodes(existing, incoming)
        if incoming.recorded_at:
            existing.recorded_at = incoming.recorded_at
        existing.decayed_through = _max_date(existing.decayed_through, incoming.decayed_through)
    else:
        said_before = _said(existing, untimed)
        unsettled = decay_policy.owed(said_before, existing.decayed_through, existing.recorded_at)
        heard = _said(incoming, untimed)
        refs = list(incoming.source_episodes or [])
        if heard is None and not (refs and all(r in untimed for r in refs)):
            heard = today   # no dated conversation and not a memory entry: an agent's live write, said now
        known = set(_said_refs(existing))
        fresh_day = decay_policy.latest_said([r for r in _said_refs(incoming) if r not in known], untimed=untimed)
        _merge_episodes(existing, incoming)
        if unsettled:
            existing.confidence = max(existing.confidence, incoming.confidence)
            existing.decayed_through = _max_date(existing.decayed_through, heard)
            if heard is not None and (said_before is None or heard > said_before):
                existing.recorded_at = today
        elif heard is not None and (not existing.decayed_through or heard >= str(existing.decayed_through)[:10]):
            if heard >= str(today)[:10]:
                existing.confidence = max(existing.confidence, incoming.confidence)
                existing.faded_by_age = None   # said again: asked like any claim
            else:
                # Said before today, read now: placed on its day by the decay pass (`_place_on_time`), which also
                # decides the faded mark, as a page's settle does.
                _defer_on_time(existing, heard, incoming.confidence)
            existing.decayed_through = _max_date(existing.decayed_through, today)
            existing.recorded_at = today
        else:
            if fresh_day is not None:
                # Said before the watermark, read late: as if read the day it was said (`_place_on_time`).
                _defer_on_time(existing, fresh_day, incoming.confidence)
            if existing.faded_by_age:
                # An older conversation that may make a one-off its age faded a repeat: the repeat floor is checked
                # once the pass knows the subject's pace (`_lift_to_repeat_floor`).
                setattr(existing, "_lift_check", True)
    # PR #20 round-2 review fix — "repeated facts lose later conversations":
    # a scalar `session_id` can only ever remember the FIRST writer, so a
    # later conversation restating the same fact would silently vanish from
    # that conversation's `GET /conversations` entity list. Merge every
    # session either claim has ever carried (first-writer scalar included)
    # into `existing.session_ids`, additive and deduped, so aggregation
    # (`session_stats._group`) credits both conversations.
    merged_sessions = existing.all_session_ids()
    for sid in incoming.all_session_ids():
        if sid not in merged_sessions:
            merged_sessions.append(sid)
    existing.session_ids = merged_sessions
    # G118 R8: a later conversation restating the fact adds its span; a
    # `reasoning` placeholder for a document the claim already cites is noise
    # (the earlier entry — span or not — already stands for that document).
    cited = {ev.episode for ev in existing.evidence}
    for ev in incoming.evidence or []:
        if ev in existing.evidence:
            continue
        if not ev.is_span() and ev.episode in cited:
            continue
        existing.evidence.append(ev)
        cited.add(ev.episode)
    # G140 Q-R6: a restatement that names an end is the newer statement of it;
    # one that names none leaves the known end alone.
    if incoming.expected_end:
        existing.expected_end = incoming.expected_end


# --------------------------------------------------------------------------- #
# the trust decision table (§3)
# --------------------------------------------------------------------------- #


def trust_decision(new: Claim, existing: Claim) -> str:
    """Return one of SUPERSEDE | COEXIST_FLAG | CONFLICT_NUDGE | REJECT | KEEP_BOTH.

    Reached only on: same key K, both open, single-valued predicate, differing
    object. Reads ``new.source_trust`` × ``existing.source_trust`` using the
    origin-gated human predicate (§6).
    """
    new_human = is_human(new)
    old_human = is_human(existing)

    # Treat a user_stated-but-agent-origin claim as agent_extracted for the table
    # (it keeps user_stated source_trust for retrieval weight, but is not
    # overwrite-protected and cannot supersede a real human, either).
    def tier(c: Claim, human: bool) -> str:
        if human:
            return "user_stated"
        if c.source_trust == "external":
            return "external"
        if c.source_trust == "agent_reflected":
            return "agent_reflected"
        # agent_extracted OR user_stated-but-not-human
        return "agent_extracted"

    new_t = tier(new, new_human)
    old_t = tier(existing, old_human)
    newer = _date_key(new.valid_from) > _date_key(existing.valid_from)

    # ----- existing is a protected human claim -----
    if old_t == "user_stated":
        if new_t == "user_stated":
            # human over human: newer supersedes; equal/ambiguous date => ask.
            return "SUPERSEDE" if newer else "CONFLICT_NUDGE"
        # agent / external can NEVER close a human => coexist + soft divergence.
        return "COEXIST_FLAG"

    # ----- new is a (real) human claim correcting a machine claim -----
    if new_t == "user_stated":
        return "SUPERSEDE"  # human corrects agent/external

    # ----- agent_extracted (new) -----
    if new_t == "agent_extracted":
        if old_t == "agent_extracted":
            return "SUPERSEDE" if newer else "CONFLICT_NUDGE"
        if old_t == "agent_reflected":
            return "SUPERSEDE"  # extraction > reflection
        if old_t == "external":
            return "SUPERSEDE" if newer else "CONFLICT_NUDGE"

    # ----- agent_reflected (new) -----
    if new_t == "agent_reflected":
        if old_t == "agent_extracted":
            return "REJECT"  # a guess must not close an observation
        if old_t == "agent_reflected":
            return "SUPERSEDE" if newer else "KEEP_BOTH"
        if old_t == "external":
            return "COEXIST_FLAG"

    # ----- external (new) -----
    if new_t == "external":
        if old_t == "agent_extracted":
            return "CONFLICT_NUDGE"
        if old_t == "agent_reflected":
            return "SUPERSEDE"
        if old_t == "external":
            return "SUPERSEDE" if newer else "KEEP_BOTH"

    return "KEEP_BOTH"


# --------------------------------------------------------------------------- #
# nudge / audit records
# --------------------------------------------------------------------------- #


def _entity_name(claim: Claim) -> str:
    return claim.subject.replace("-", " ").title()


def _claim_option(key: str, claim: Claim, today: str) -> dict:
    """One question option backed by a claim, description led by its age."""
    observed = claim.valid_from or claim.recorded_at
    parts = [f"Last mentioned {observed or 'unknown'}", inbox_questions.humanize_age(observed, today)]
    episode = (claim.source_episodes or [""])[0]
    if episode:
        parts.append(f"extracted from {episode}")
    return {
        "key": key,
        "label": claim.object,
        "description": " · ".join(parts),
        "claim_id": claim.id,
        "observed_at": observed,
        "last_referenced": observed,
    }


def _conflict_nudge(existing: Claim, new: Claim, today: str) -> dict:
    """A conflict nudge carrying the G60 question object.

    ``today`` is the reconciliation reference date, so the age phrases in each
    option's description are computed once at generation time (``age_days`` is
    re-derived at read time by ``inbox_service``).
    """
    name = _entity_name(new)
    return {
        "id": new.subject,
        "action": "conflict_nudge",
        "entity": {"name": name},
        "predicate": new.predicate,
        # G97/G115: the conversation that raised the question. The freshest
        # (new) claim's last episode — what `inbox_context` would pick anyway,
        # persisted so the item stays answerable if the claim is later closed.
        # G61 phase 2 S0: this is the only source_episode key — a second,
        # older literal ([0]) used to override it.
        "source_episode": (new.source_episodes or [None])[-1],
        "question": predicates.predicate_question(new.predicate, name),
        "allow_other": True,
        "allow_defer": True,
        "conflict_context": (
            f"Conflicting beliefs about {name} "
            f"({new.predicate}): '{existing.object}' vs '{new.object}'."
        ),
        "options": [
            _claim_option("a", existing, today),
            _claim_option("b", new, today),
            {
                "key": "both",
                "label": "Both are true (different contexts)",
                "description": "Keep both claims, each tagged with its context",
                "claim_id": None,
            },
        ],
        "trigger": "sleep/conflict_resolution",
        "claim_id": new.id,
        "existing_claim_id": existing.id,
    }


def _divergence_nudge(existing: Claim, new: Claim) -> dict:
    return {
        "id": new.subject,
        "action": "divergence_nudge",
        "entity": {"name": _entity_name(new)},
        "conflict_context": (
            f"You said {_entity_name(new)} {new.predicate} '{existing.object}'; "
            f"I'm now reading '{new.object}'. Keep your statement?"
        ),
        "options": [
            f"Keep my statement ({existing.object})",
            f"Update to {new.object}",
            "Both true — different context",
        ],
        "source_episode": (new.source_episodes or [""])[0],
        "trigger": "sleep/conflict_resolution",
        "claim_id": new.id,
        "existing_claim_id": existing.id,
    }


def _normalization_audit_nudge(raw_label: str, canonical: str, claim: Claim,
                               covered: list[Claim] | None = None) -> dict:
    """One fold question for a pair: ``claim`` opens it, ``covered`` are the
    other claims the pass kept under the same fold (``covered_claims``, the
    refs a "wrong fold" answer repoints)."""
    return {
        "id": claim.subject,
        "action": "normalization_audit",
        "entity": {"name": _entity_name(claim)},
        "conflict_context": (
            f"Predicate '{raw_label}' was auto-folded to canonical '{canonical}'. "
            f"Confirm this fold is correct."
        ),
        "options": ["Correct fold", "Wrong fold — keep separate"],
        "source_episode": (claim.source_episodes or [""])[0],
        "trigger": "sleep/conflict_resolution",
        "claim_id": claim.id,
        # G113 slice 3: persisted so `_resolve_normalization` can un-merge the
        # raw label from `_predicates.yaml` on a "wrong fold" answer without
        # re-deriving it from the (already-folded) claim on disk.
        "raw_predicate": raw_label,
        "canonical_predicate": canonical,
        "covered_claims": [{"entity_id": c.subject, "claim_id": c.id} for c in covered or []
                           if (c.subject, c.id) != (claim.subject, claim.id)],
    }


# --------------------------------------------------------------------------- #
# events (G141 §5.1) — happenings and milestones never reach the K table
# --------------------------------------------------------------------------- #

# R-PJ4 §5.1 rule 3: an equal-date tie in a milestone slot is broken by
# lifecycle rank, never by `trust_decision`'s date test (which would turn a
# same-day "create, then mark done" into a conflict).
_LIFECYCLE_RANK = {"planned": 0, "ongoing": 0, "done": 1, "missed": 1, "dropped": 1}


def _stamp_event(claim: Claim, settings, *, today: str) -> Claim:
    """`_stamp_new`, then R-PJ3: a done or dropped happening is born closed."""
    _stamp_new(claim, settings, today=today)
    if claim.predicate == HAPPENED and claim.status in ("done", "dropped"):
        claim.valid_to = claim.valid_from
    return claim


def _close_event(old: Claim, *, by: Claim) -> None:
    """`_close`, never earlier than `old` opened (R-PJB27): a backdated `on`
    must not write a window that closes before it opens — the
    `claim_expiry.closing_date` rule."""
    _close(old, by=by)
    if old.valid_from and _date_key(old.valid_to) < _date_key(old.valid_from):
        old.valid_to = old.valid_from


def _span_list(c: Claim) -> list[Evidence]:
    return [e for e in c.evidence if e.is_span()]


def _overlap(a: Evidence, b: Evidence) -> int:
    if a.episode != b.episode:
        return 0
    return max(0, min(a.end, b.end) - max(a.start, b.start))


def _withdrawn(c: Claim, slot: list[Claim]) -> bool:
    return bool(c.superseded_by) and any(r.id == c.superseded_by and is_record(r) for r in slot)


def _reread_twin(new: Claim, slot: list[Claim], *, ending: bool = False) -> Claim | None:
    """The closed claim ``new`` is a re-read of (G104): a closed, non-withdrawn claim every conversation ``new`` was
    heard in already cites, with ``new``'s id — or, failing that, the same slot (``K``) and object.

    Why the content match and not only the id: a claim id hashes its ``valid_from``, and ruling 34 (2026-10-22) moved a
    conversation's day from its UTC stamp to the person's local day, so re-reading a conversation said between local and
    UTC midnight (a resumed session, a Messages or folder edit, an export upgrading a relay) mints a different id for
    the same belief. Matching on what the claim says, gated on its own conversations, holds for any future change to
    how a day is read too; an alias for the old UTC-day id would need the episode's stamp here and the old rule kept
    alive. ``ending`` (an ending record, born closed on its own day) prefers a record whose ``valid_to`` is its
    ``valid_from`` over a claim the ending closed."""
    heard = set(new.source_episodes or [])
    if not heard:
        return None

    def reread(c: Claim) -> bool:
        return not open_(c) and not _withdrawn(c, slot) and heard <= set(_said_refs(c))

    by_id = next((c for c in slot if c.id == new.id and reread(c)), None)
    if by_id is not None:
        return by_id
    same = [c for c in slot if K(c) == K(new) and same_object(c, new) and reread(c)]
    if ending:
        same.sort(key=lambda c: (str(c.valid_to or "")[:10] != str(c.valid_from or "")[:10], not c.supersedes))
    return same[0] if same else None


def _auto_settle_target(new: Claim, slot: list[Claim]) -> str | None:
    """R-PJ19 (R-PJB25): Sleep may settle only conservatively — a done happening
    closes an OLDER open ongoing one on the same subject when they share at
    least two linked non-owner participants. No production caller until PJ-7."""
    mine = {p.get("entity") for p in new.participants if p.get("entity") and p.get("role") != "owner"}
    hits = [c.id for c in slot
            if c.predicate == HAPPENED and c.status == "ongoing" and open_(c)
            and _date_key(c.valid_from) < _date_key(new.valid_from)
            and len(mine & {p.get("entity") for p in c.participants if p.get("entity") and p.get("role") != "owner"}) >= 2]
    return hits[0] if len(hits) == 1 else None


def reconcile_events(new: Claim, slot: list[Claim], settings, *, today: str, nudges: list[dict],
                     audit: list[dict], absorbed: set[str]) -> None:
    """The event branch of `reconcile_stage3` (G141 §5.1). The general `K`
    table is never reached for an event: two milestones of one project share `K`
    and would read as a conflict. Mutates `slot`; nothing is deleted."""
    if new.predicate == HAPPENED:
        _reconcile_happening(new, slot, settings, today=today, audit=audit, absorbed=absorbed)
    else:
        _reconcile_milestone(new, slot, settings, today=today, nudges=nudges, audit=audit)


def _reconcile_happening(new, slot, settings, *, today, audit, absorbed) -> None:
    # A reinforce moves `recorded_at` only when the incoming claim carries one
    # (`_reinforce`); Sleep-shaped claims arrive without it, and rule 2's
    # "the quiet clock resets" must hold for them too.
    new.recorded_at = new.recorded_at or today
    winner = None
    # 1. Span identity, same status: a G104 re-read that rewords the same
    #    happening, or an agent's live write and that night's Sleep, fold into one.
    best, best_ov = None, 0
    for c in slot:
        if c.predicate != HAPPENED or c.status != new.status or c.id in absorbed or _withdrawn(c, slot):
            continue
        ov = max((_overlap(a, b) for a in _span_list(c) for b in _span_list(new)), default=0)
        if ov > best_ov:
            best, best_ov = c, ov
    if best is not None:
        _reinforce(best, new)
        absorbed.add(best.id)
        winner = best
    else:
        # 2. Same day and words; an ongoing restatement whatever its day.
        for c in slot:
            if c.predicate == HAPPENED and c.status == new.status and same_object(c, new) \
                    and not _withdrawn(c, slot) \
                    and (c.valid_from == new.valid_from or (new.status == "ongoing" and open_(c))):
                _reinforce(c, new)
                winner = c
                break
    if winner is not None:
        setattr(new, "_folded_into", winner.id)
    else:
        winner = _stamp_event(new, settings, today=today)
        slot.append(winner)
    # 4. Settles — also when `new` folded into an existing done/dropped claim
    #    (R-PJB29): that claim is then the closer.
    target = getattr(new, "_settles", None)
    if not target and winner is new and getattr(settings, "auto_settle", False):
        target = _auto_settle_target(new, slot)
    if not target or winner.status not in ("done", "dropped"):
        return
    thread = next((c for c in slot if c.id == target and c.predicate == HAPPENED and c.status == "ongoing"
                   and open_(c)), None)
    if thread is None:
        setattr(new, "_settle_result", "missing")
    elif is_human(thread) and not is_human(new):
        setattr(new, "_settle_result", "refused")          # R-PJB14
    else:
        _close_event(thread, by=winner)
        setattr(new, "_settle_result", "closed")
        audit.append({"action": "supersede", "closed": thread.id, "by": winner.id})


def _reconcile_milestone(new, slot, settings, *, today, nudges, audit) -> None:
    new.recorded_at = new.recorded_at or today
    # 3. One slot per (subject, milestone, slug) ACROSS observers (R-PJ4).
    head = next((c for c in slot if c.predicate == MILESTONE and open_(c) and same_object(c, new)), None)
    if head is None:
        slot.append(_stamp_event(new, settings, today=today))
        return
    if head.status == new.status and (head.target or None) == (new.target or None) \
            and (head.text or "").strip() == (new.text or "").strip():
        _reinforce(head, new)
        setattr(new, "_folded_into", head.id)
        return
    if is_human(head) and not is_human(new):
        # An agent never closes the person's milestone: coexist + a divergence
        # item — a G113 verdict for free (§5.1 rule 3).
        slot.append(_stamp_event(new, settings, today=today))
        setattr(new, "_status_note", "shadowed_by_human")
        nudges.append({**_divergence_nudge(head, new),
                       "conflict_context": (f"You set {head.text} as {head.status}"
                                            + (f" for {head.target}" if head.target else "")
                                            + f"; I'm now reading {new.status}"
                                            + (f" for {new.target}" if new.target else "") + ". Keep your statement?"),
                       "options": [f"Keep my statement ({head.status})", f"Update to {new.status}",
                                   "Both true — different context"]})
        return
    newer = _date_key(new.valid_from) > _date_key(head.valid_from)
    same_day = _date_key(new.valid_from) == _date_key(head.valid_from)
    # R-PJB27: the person's own edit always stands — over an agent head (as
    # `trust_decision`'s "human corrects agent") and over their own earlier
    # head, whatever `on` says; agent-over-agent is ordered by date, then rank.
    if is_human(new) or newer or (same_day and _LIFECYCLE_RANK.get(new.status, 0)
                                  >= _LIFECYCLE_RANK.get(head.status, 0)):
        _close_event(head, by=_stamp_event(new, settings, today=today))
        slot.append(new)
        audit.append({"action": "supersede", "closed": head.id, "by": new.id})
        return
    audit.append({"action": "rejected", "kept": head.id, "dropped": new.id})


# --------------------------------------------------------------------------- #
# the algorithm (§2)
# --------------------------------------------------------------------------- #


def _departed_on(new: Claim, slot: list[Claim], over: set[str], untimed=frozenset(),
                 canonical: str | None = None) -> str | None:
    """The latest day a departure from ``new``'s place was said on this page, or ``None`` (2026-10-14 review).

    A departure is a claim on the same subject and object whose predicate is an ``over`` label ("left", kept under
    its own label when nothing was open) or whose own words are one ("Bob previously worked at Acme", an ending
    record) — so the order claims are read in never decides the belief: a re-read of the older conversation, an
    older mention read after the departure, or "left" listed before "works at" in one extraction."""
    days = []
    for c in slot:
        if c is new or c.subject != new.subject or not same_object(c, new) or is_event(c) or is_record(c):
            continue
        said_label = predicates._slugify_predicate(c.predicate) in over or (
            c.predicate in (new.predicate, canonical) and c.valid_to is not None and _says_any(c.text, over))
        if said_label:
            days.append(_said(c, untimed) or c.valid_from)
    days = [str(d)[:10] for d in days if d]
    return max(days) if days else None


def _says_any(text: str, labels: set[str]) -> bool:
    words = "-" + predicates._slugify_predicate(text or "") + "-"
    return any(f"-{label}-" in words for label in labels)


def _place_claim(new: Claim, slot: list[Claim], settings, today: str, cardinality_fn: CardinalityFn,
                 nudges: list[dict], audit: list[dict], untimed=frozenset(), over: set[str] = frozenset(),
                 canonical: str | None = None) -> Claim | None:
    """One non-event incoming claim against its subject's slot (the K table).
    Returns the claim the page keeps for it — ``new``, or the existing claim a
    restatement reinforced — or ``None`` when it is not stored (a conflict to
    ask about, or rejected).

    ``over`` — the labels that end ``new``'s predicate: a mention said on or before a departure already on the page
    is kept as closed history, never reopened (2026-10-14 review). A claim whose id the page already holds closed, read
    again from a conversation that claim already cites (G104), stays closed: a re-read never undoes a close, and never
    doubles an id. A withdrawn claim restated is a fresh assertion (``cicada_retract_claim``'s rule), as before."""
    twin = _reread_twin(new, slot)
    if twin is not None:
        _merge_episodes(twin, new)
        return twin
    if over and not is_human(new):
        departed = _departed_on(new, slot, over, untimed, canonical)
        said = str(_said(new, untimed) or new.valid_from or today)[:10]
        if departed is not None and said <= departed:
            _stamp_new(new, settings, today=today)
            new.valid_to = max(departed, str(new.valid_from or departed)[:10])
            slot.append(new)
            audit.append({"action": "after_departure", "kept_closed": new.id})
            return new
    value = is_value_claim(new)
    if value:
        _adopt_value_attribute(new, slot)
    same_key_open = [c for c in slot if open_(c) and K(c) == K(new)]

    if not same_key_open:
        slot.append(_stamp_new(new, settings, today=today))
        return new

    single = value or cardinality_fn(new.predicate)

    if not single:
        # Multi-valued: coexist unless an exact-object duplicate exists.
        dup = next((c for c in same_key_open if same_object(c, new)), None)
        if dup is None:
            slot.append(_stamp_new(new, settings, today=today))
            return new
        _reinforce(dup, new, today=today, untimed=untimed)
        return dup

    # Single-valued: ≤1 open per slot.
    existing = same_key_open[0]
    if same_object(existing, new):
        _reinforce(existing, new, today=today, untimed=untimed)
        return existing

    action = trust_decision(new, existing)
    if value and action in ("SUPERSEDE", "CONFLICT_NUDGE"):
        # The owner's-words rail (`inbox_tend.may_close`, review 2026-10-17): a value resting only on the assistant's or
        # another speaker's words never closes one resting on the person's own — in either order. Ask instead.
        from api.services.inbox_tend import may_close

        older = _date_key(new.valid_from) < _date_key(existing.valid_from)
        winner, loser = (existing, new) if older else (new, existing)
        if not may_close(winner, [loser]):
            nudges.append(_conflict_nudge(existing, new, today))
            audit.append({"action": "value_kept_for_persons_words", "kept": existing.id, "asked": new.id})
            return None
    if value and action == "CONFLICT_NUDGE" and _date_key(new.valid_from) < _date_key(existing.valid_from):
        # A value said BEFORE the one the page holds (a drain reads conversations in any order): it is history,
        # closed by the first value said after it — never a question, never lost, and never overlapping another
        # closed value of the same attribute.
        _stamp_new(new, settings, today=today)
        after = min((c for c in slot if K(c) == K(new) and is_value_claim(c)
                     and _date_key(c.valid_from) > _date_key(new.valid_from)),
                    key=lambda c: _date_key(c.valid_from), default=existing)
        new.valid_to = after.valid_from
        new.superseded_by = after.id
        slot.append(new)
        audit.append({"action": "superseded_on_arrival", "kept": existing.id, "closed": new.id})
        return new
    if action == "SUPERSEDE":
        _close(existing, by=_stamp_new(new, settings, today=today))
        slot.append(new)
        audit.append({"action": "supersede", "closed": existing.id, "by": new.id})
        return new
    if action == "COEXIST_FLAG":
        slot.append(_stamp_new(new, settings, today=today, status_note="shadowed_by_human"))
        nudges.append(_divergence_nudge(existing, new))
        return new
    if action == "CONFLICT_NUDGE":
        nudges.append(_conflict_nudge(existing, new, today))
    elif action == "REJECT":
        audit.append({"action": "rejected", "kept": existing.id, "dropped": new.id})
    elif action == "KEEP_BOTH":
        slot.append(_stamp_new(new, settings, today=today))
        return new
    return None


def _adopt_value_attribute(new: Claim, slot: list[Claim]) -> None:
    """A stated value takes the predicate of the open value on its slot that names the same attribute in other words
    (``claims.same_value_attribute``) — the extractor reads each conversation alone, so "korean restaurants tried"
    and "number of korean restaurants tried" are one belief, and only one key lets the newer close the older."""
    if any(open_(c) and K(c) == K(new) for c in slot):
        return
    match = next((c for c in slot if open_(c) and is_value_claim(c) and c.subject == new.subject
                  and c.context == new.context and c.observer == new.observer
                  and same_value_attribute(c.predicate, new.predicate)), None)
    if match is not None:
        new.predicate = match.predicate


def _place_ending(new: Claim, ending: "predicates.Ending", slot: list[Claim], settings, today: str,
                  audit: list[dict], untimed=frozenset(),
                  ended_by: "Callable[[str], str | None] | None" = None) -> "Claim | bool":
    """A claim whose label says a belief stopped being true (``predicates.build_endings_fn``; 2026-10-14).

    A multi-valued place ends only on evidence that it ended — this, a stated end (``claim_expiry``) or the
    person's own edit — never because another place was mentioned. Returns ``False`` when the label does not
    apply here (``left`` with no open place of that name: kept under its own label, so "left Lisbon" never
    becomes a job), else the claim the page keeps for it.

    * ``over`` — every open belief with the canonical predicate on this subject and object, in any context or
      observer, closes, dated when it was said and never before it opened (``_close_event``'s rule); an
      agent's word never closes the person's own (``is_human``), and an ending said before the belief was last
      said closes nothing (left, then went back) — both stay open, counted. The ending itself is kept as closed
      history (``valid_to = valid_from``) under the canonical predicate.
    * ``past`` — "worked at": an open belief on the same object is reinforced, never closed; with none open
      the claim is kept as closed history, never a current place.

    ``ended_by`` (``EndingFn.ended_by``, 2026-10-23): an ``over`` label also closes the open beliefs whose predicate
    the seed's ``also_ends`` ties to the canonical, or that qualify either with more words — "dropped Supabase" ends
    "uses for auth and data Supabase" and "depends on Supabase" too, under the same guards. Each keeps its own
    predicate. ``past`` reinforces only the canonical itself.

    No fold question is raised for either: the endings list is curated, not a guess.
    """
    canonical = ending.canonical

    def ends(c: Claim) -> bool:
        if c.predicate == canonical:
            return True
        return ending.mode == predicates.ENDING_OVER and ended_by is not None and ended_by(c.predicate) == canonical

    targets = [c for c in slot if open_(c) and c.subject == new.subject and ends(c)
               and same_object(c, new) and not is_event(c) and not is_record(c)]
    if not targets and not (ending.synonym or new.predicate == canonical):
        return False
    if ending.mode == predicates.ENDING_PAST and targets:
        _reinforce(targets[0], new, today=today, untimed=untimed)
        return targets[0]
    new.predicate = canonical
    dup = next((c for c in slot if c.id == new.id), None) or _reread_twin(new, slot, ending=True)
    if dup is not None:
        # The same ending read again (a G104 re-read): one record, its sources merged.
        _merge_episodes(dup, new)
        return dup
    _stamp_new(new, settings, today=today)
    said = _said(new, untimed) or new.valid_from
    for t in targets:
        if is_human(t) and not is_human(new):
            audit.append({"action": "ending_shadowed_by_human", "kept": t.id, "by": new.id})
            continue
        if _date_key(said) < _date_key(_max_date(t.valid_from, _said(t, untimed))):
            audit.append({"action": "ending_older", "kept": t.id, "by": new.id})
            continue
        _close_event(t, by=new)
        audit.append({"action": "ended", "closed": t.id, "by": new.id})
    new.valid_to = new.valid_from
    slot.append(new)
    return new


def reconcile_stage3(
    incoming_claims: list[Claim],
    existing_claims_by_subject: dict[str, list[Claim]],
    settings,
    *,
    cardinality_fn: CardinalityFn | None = None,
    endings_fn: "predicates.EndingFn | None" = None,
    now_date: str | None = None,
    decay_class_fn: DecayClassFn | None = None,
    subject_fn: SubjectFn | None = None,
    decay: bool = True,
) -> tuple[dict[str, list[Claim]], list[dict], list[dict]]:
    """Trust-gated invalidate-and-supersede over claims. Nothing deleted.

    ``decay=False`` skips ``_decay_claims`` only (a drain's batches before the
    last; see ``sleep_drain``).

    Args:
        incoming_claims: Stage 1+2 output — fully routed (subject-id, normalized
            predicate). Each claim may carry a ``predicate_raw`` attribute (the
            pre-normalization label) so an auto-fold emits the mandatory audit nudge.
        existing_claims_by_subject: parsed from each page's ``claims`` block.
        settings: carries ``memory_path`` (for the cardinality map),
            ``litellm_model`` (authored_by), ``archive_threshold`` /
            ``decay_nudge_threshold``.
        cardinality_fn: ``predicate -> is_single_valued``. Defaults to the
            ``_predicates.yaml`` cardinality oracle for ``settings.memory_path``.
        endings_fn: ``label -> (canonical, over|past) | None`` — the labels
            that say a belief stopped being true (:func:`_place_ending`).
            Defaults to ``predicates.build_endings_fn`` for the bank.
        now_date: decay reference date (ISO); defaults to today.
        decay_class_fn: ``subject_id -> DecayClass``, multiplying each claim's
            decay by its subject entity's class (G66). Defaults to the
            filesystem lookup for ``settings.memory_path``; an evergreen subject
            means its claims never decay.
        subject_fn: ``subject_id -> SubjectDecay`` (G147) — the subject's
            per-type pace and kept weeks; defaults to
            ``decay_policy.subject_lookup`` for ``settings.memory_path``, or
            ``NEUTRAL_SUBJECT`` for every subject when there is no bank path.

    Returns ``(reconciled_by_subject, nudges, audit)``. ``nudges`` carries
    ``conflict_nudge`` / ``divergence_nudge`` / ``normalization_audit`` records in
    the inbox-generator change shape; ``audit`` carries ``supersede`` / ``rejected``
    bookkeeping (never user-facing, surfaced in the commit/logs).
    """
    today = now_date or str(date.today())
    if cardinality_fn is None:
        cardinality_fn = _default_cardinality_fn(settings)
    memory_path = getattr(settings, "memory_path", None)
    if endings_fn is None:
        endings_fn = predicates.build_endings_fn(memory_path)
    if subject_fn is None:
        # No bank path, no page to read: every subject is neutral. Never "." —
        # this module does not resolve a bank from the process's cwd (R-FD13).
        subject_fn = (decay_policy.subject_lookup(memory_path) if memory_path
                      else (lambda _sid: decay_policy.NEUTRAL_SUBJECT))
    if decay_class_fn is None:
        # One parse per subject: the class is the subject reader's own column.
        decay_class_fn = lambda sid: subject_fn(sid).decay_class  # noqa: E731

    reconciled: dict[str, list[Claim]] = {
        sub: list(claims) for sub, claims in existing_claims_by_subject.items()
    }
    nudges: list[dict] = []
    audit: list[dict] = []
    referenced_subjects: set[str] = set()
    # (raw_slug, canonical) -> the raw label first seen and every claim kept for it
    folds: dict[tuple[str, str], dict] = {}
    # G141 rule 1: an existing happening absorbs at most one incoming claim per
    # pass, so two distinct happenings quoting one sentence never collapse.
    absorbed: set[str] = set()

    # A memory export entry says nothing about when (`episode_time`): read once for the pass.
    untimed = episode_time.untimed_ids(memory_path)
    for new in incoming_claims:
        sub = new.subject
        referenced_subjects.add(sub)
        # Age counts from when it was said (owner ruling 2026-10-09; mirrors the
        # entity engine in `conflict_resolver.resolve_and_prune`): a claim minted
        # from a dated conversation is charged nothing before it was said, and the
        # decay pass charges the silence between then and `recorded_at` — the day
        # Cicada read it — in full. Without a dated conversation (an agent's live
        # write, a memory export entry) its clock starts today, as before. Set
        # before any branch, so every path that stores `new` carries it.
        new.decayed_through = _max_date(new.decayed_through, _said(new, untimed) or today)
        slot = reconciled.setdefault(sub, [])

        if is_event(new):
            # G141 §5.1: an event has its own rules (span identity, the
            # milestone slot, settles) — the K table would read two milestones
            # of one project as a conflict.
            reconcile_events(new, slot, settings, today=today, nudges=nudges, audit=audit, absorbed=absorbed)
            continue

        # Mandatory normalization-audit nudge on any auto-folded predicate.
        # G98/G115: a fold is a label mapped onto a DIFFERENT predicate. The
        # label's own slug is the normalizer's keep-as-is fallback ("uses
        # dataset" -> "uses-dataset"), a formatting change, never a question.
        # One question per pair, raised after the pass so it names every claim
        # the pages keep for it — a reinforced restatement keeps the OLD id.
        raw_label = getattr(new, "predicate_raw", None)
        ending = endings_fn(str(raw_label or new.predicate))
        ended_by = getattr(endings_fn, "ended_by", None)
        if ending is not None and _place_ending(new, ending, slot, settings, today, audit, untimed,
                                                ended_by) is not False:
            continue
        # A predicate an ending also ends (`also_ends`, or a qualified label) reads that canonical's departures.
        canonical = (ended_by(new.predicate) if ended_by else None) or new.predicate
        over = getattr(endings_fn, "over", {}).get(canonical, frozenset())
        kept = _place_claim(new, slot, settings, today, cardinality_fn, nudges, audit, untimed, over, canonical)
        if raw_label:
            raw_slug = predicates._slugify_predicate(str(raw_label))
            if raw_slug and raw_slug != new.predicate:
                entry = folds.setdefault((raw_slug, new.predicate), {"raw": str(raw_label), "kept": []})
                if kept is not None and all(k is not kept for k in entry["kept"]):
                    entry["kept"].append(kept)

    for sub, slot in reconciled.items():
        for c in slot:
            if decay and c.read_late:
                # Restatements read late, in this batch or an earlier one of the drain: placed now, at the final pace.
                pending, c.read_late = c.read_late, None
                _place_on_time(c, sub, pending, settings, decay_class_fn, subject_fn, untimed, today)
            if getattr(c, "_lift_check", False):
                delattr(c, "_lift_check")
                if c.faded_by_age:
                    _lift_to_repeat_floor(c, sub, settings, decay_class_fn, subject_fn, untimed, today)

    for (_raw_slug, canonical), entry in folds.items():
        if entry["kept"]:   # nothing stored under the fold (rejected, or a conflict asked) — nothing to ask
            nudges.append(_normalization_audit_nudge(entry["raw"], canonical, entry["kept"][0], entry["kept"][1:]))

    if decay:
        _decay_claims(reconciled, referenced_subjects, settings, nudges, today, decay_class_fn, subject_fn,
                      untimed=untimed)
    return reconciled, nudges, audit


# --------------------------------------------------------------------------- #
# decay (§7) — per-epistemic × source_trust; lowers confidence only
# --------------------------------------------------------------------------- #


def _max_date(left: str | None, right: str | None) -> str | None:
    """The later of two ISO date/date-time strings; either may be missing."""
    candidates = [str(c)[:10] for c in (left, right) if c]
    return max(candidates) if candidates else None


def _defer_on_time(c: Claim, said: str, confidence: float) -> None:
    """Note a restatement said on ``said`` and read late (``Claim.read_late``): the decay pass places it
    (:func:`_place_on_time`) at the drain's final pace — nothing is charged mid-drain."""
    entry = [str(said)[:10], float(confidence)]
    pending = list(c.read_late or [])
    if entry not in pending:
        pending.append(entry)
    c.read_late = pending


def _place_on_time(c: Claim, subject: str, pending, settings, decay_class_fn, subject_fn, untimed,
                   today: str) -> None:
    """A restatement read late counts as if Cicada had read it the day it was said (owner 2026-10-16, mirrors a
    page's ``conflict_resolver._revive_on_time`` and its settle): the restatement's confidence on that day, less the
    silence since (``decay_policy.on_time``: proven silence floored for a repeat, live silence in full), through the
    claim's watermark plus at most one pass of live silence. Only raises. A claim the restatement leaves below the
    question line, heard late, is ``faded_by_age`` — never asked; one it takes back above the line is asked like any
    claim."""
    multiplier = max(0.0, decay_policy.claim_multiplier(decay_class_fn(subject)))
    alpha, floor = decay_policy.spacing_params(settings)
    rate = claim_rate(c, subject_fn(subject), multiplier, untimed=untimed, alpha=alpha, floor=floor)
    nudge = float(getattr(settings, "decay_nudge_threshold", 0.4) or 0.4)
    heard_in = decay_policy.conversations(_said_refs(c), untimed=untimed)
    day = str(today)[:10]
    # The watermark plus at most one pass of live silence (ruling 1) — what a pass would charge from here.
    through = decay_policy.through_day(c.decayed_through, day, MAX_DECAY_DAYS_PER_CYCLE).isoformat()
    best, best_said = None, None
    for said, confidence in pending:
        lifted = decay_policy.on_time(confidence, rate, said, c.recorded_at, through,
                                      conversations=heard_in, nudge_threshold=nudge)
        if lifted is not None and (best is None or lifted > best):
            best, best_said = lifted, said
    if best is not None and best > c.confidence:
        c.confidence = best
        c.decayed_through = through
        setattr(c, "_placed", True)   # this pass's live silence is in it (ruling 1): not charged again
        if best >= nudge:
            c.faded_by_age = None   # back above the line on the person's words: asked like any claim
        elif decay_policy.heard_late(best_said, day) and not c.faded_by_age:
            c.faded_by_age = day   # its age carried it below the line: fades quietly


def _lift_to_repeat_floor(c: Claim, subject: str, settings, decay_class_fn, subject_fn, untimed, today: str) -> None:
    """A claim its age faded (``faded_by_age``) that an older restatement, read in a later run, makes a repeat:
    where both read in one run would have left it — the repeat floor less the live silence charged since its age
    was settled — when that is higher. Only raises."""
    if decay_policy.conversations(_said_refs(c), untimed=untimed) < 2:
        return
    multiplier = decay_policy.claim_multiplier(decay_class_fn(subject))
    if multiplier <= 0:
        return
    alpha, floor = decay_policy.spacing_params(settings)
    rate = claim_rate(c, subject_fn(subject), multiplier, untimed=untimed, alpha=alpha, floor=floor)
    try:
        since = date.fromisoformat(str(c.faded_by_age)[:10])
        day = date.fromisoformat(str(today)[:10])
    except ValueError:
        return
    nudge = float(getattr(settings, "decay_nudge_threshold", 0.4) or 0.4)
    # Live silence from the day its age was settled to today, as for a page.
    lifted = decay_policy.proven_floor(nudge) - rate * max(0, (day - since).days) / 7.0
    if lifted > c.confidence:
        c.confidence = lifted
        c.decayed_through = day.isoformat()


def claim_rate(c: Claim, about, multiplier: float, *, untimed=frozenset(),
               alpha: float = decay_policy.SPACING_ALPHA, floor: float = decay_policy.SPACING_FLOOR) -> float:
    """A claim's weekly fade: per-epistemic base x source trust x the subject's class (G66) x the subject's
    per-type pace x spacing over the weeks it was said in (G147, R-FD4)."""
    base = _DECAY_BASE.get(c.epistemic, 0.02)
    factor = _DECAY_FACTOR.get(c.source_trust, 1.0)
    spacing = decay_policy.stability(
        decay_policy.claim_mention_weeks(c, about.kept_on, untimed=untimed), alpha=alpha, floor=floor
    )
    return base * factor * multiplier * about.type_multiplier * spacing


def claim_silence(c: Claim, today: date, cap_days: int, *, untimed=frozenset()) -> decay_policy.Silence | None:
    """The silence one pass charges a claim (``decay_policy.silence``): from the later of when it was last said and
    its watermark; proven silence up to ``recorded_at`` (the day Cicada read it) in full, live silence capped.
    A claim with no dated conversation keeps its old anchor — ``recorded_at``, else ``valid_from`` — live only."""
    said = _said(c, untimed)
    if said is None:
        return decay_policy.silence(c.recorded_at or c.valid_from, c.decayed_through, None, today, cap_days)
    return decay_policy.silence(said, c.decayed_through, c.recorded_at, today, cap_days)


def _decay_claims(
    reconciled: dict[str, list[Claim]],
    referenced_subjects: set[str],
    settings,
    nudges: list[dict],
    today: str,
    decay_class_fn: DecayClassFn,
    subject_fn: SubjectFn,
    *,
    untimed=None,
) -> None:
    nudge_threshold = float(getattr(settings, "decay_nudge_threshold", 0.4) or 0.4)
    alpha, floor = decay_policy.spacing_params(settings)
    # A memory export entry restates a claim without the claim coming up (`episode_time`).
    if untimed is None:
        untimed = episode_time.untimed_ids(getattr(settings, "memory_path", None))
    today_date = date.fromisoformat(today[:10])

    for subject, claims in reconciled.items():
        # A subject this pass read is not silent: its claims are charged only the
        # silence their own conversations prove (last said -> the day Cicada read
        # it), never live silence — the clock starts today.
        cap = 0 if subject in referenced_subjects else MAX_DECAY_DAYS_PER_CYCLE
        # One lookup per subject, not per claim.
        multiplier = decay_policy.claim_multiplier(decay_class_fn(subject))
        if multiplier <= 0:
            continue  # evergreen subject: its claims are artifacts, they don't fade
        # G147: the subject's per-type pace (the person's choice, R-FD5) and its
        # "keep" weeks — read once per subject, like the class above.
        about = subject_fn(subject)
        for c in claims:
            if not open_(c) or is_event(c):
                # Closed claims are history; events are asked about (the G141
                # follow-up), never faded (R-PJ12).
                continue
            if getattr(c, "_placed", False):
                delattr(c, "_placed")
                continue   # placed on its day this pass, its live silence included
            # G85 §2 / Wave-1 1.1 + 1.8: charged from the watermark, so an interval
            # is charged exactly once; live silence capped at MAX_DECAY_DAYS_PER_CYCLE
            # with the watermark advancing only by what was charged (TODO ruling 1).
            owed = claim_silence(c, today_date, cap, untimed=untimed)
            if owed is None:
                owed = decay_policy.Silence(0, 0, today_date)
            if cap == 0 and owed.days == 0:
                continue  # read this pass, nothing proven: untouched, as before
            rate = claim_rate(c, about, multiplier, untimed=untimed, alpha=alpha, floor=floor)
            if rate > 0 and owed.days > 0:
                # One-offs fall freely; a claim restated across 2+ conversations floors where a page would
                # (owner 2026-10-09) — proven silence alone never takes it under the archive line.
                new_conf = decay_policy.charge(
                    c.confidence, rate, owed, nudge_threshold=nudge_threshold,
                    conversations=decay_policy.conversations(_said_refs(c), untimed=untimed))
                # Faded by its age (heard late, and this pass's proven silence took it below the question
                # line): marked, it fades quietly from here. A question fires only when live silence carries
                # a claim across 0.4 (`decay_policy.asks`).
                newly = (not c.faded_by_age and owed.proven_days > 0 and new_conf < nudge_threshold
                         and decay_policy.heard_late(_said(c, untimed), c.recorded_at))
                asks = not newly and decay_policy.asks(c.confidence, new_conf, nudge_threshold,
                                                       faded_by_age=c.faded_by_age)
                if newly:
                    c.faded_by_age = owed.watermark.isoformat()
                if new_conf != c.confidence:
                    c.confidence = new_conf
                    # Decay never closes a claim and never touches a human
                    # claim's validity — it only lowers the retrieval weight
                    # + may nudge.
                    if asks:
                        nudges.append({
                            "id": subject,
                            "action": "decay_nudge",
                            "entity": {"name": _entity_name(c)},
                            "new_confidence": new_conf,
                            "claim_id": c.id,
                            "source_episode": (c.source_episodes or [None])[-1],
                            "trigger": "sleep/decay",
                        })
            # Stamp the watermark regardless of whether `amount` moved
            # anything this pass — the next pass must measure from here.
            c.decayed_through = owed.watermark.isoformat()


# --------------------------------------------------------------------------- #
# cardinality oracle (§5) — _predicates.yaml first, conservative default
# --------------------------------------------------------------------------- #


def _default_cardinality_fn(settings) -> CardinalityFn:
    memory_path = getattr(settings, "memory_path", None)
    base = predicates.build_cardinality_fn(memory_path)
    # G141 R-PJ5: event cardinality lives in code — a bank's stale
    # `_predicates.yaml` must never make `happened` single-valued.
    return lambda p: False if event_cardinality(p) else base(p)
