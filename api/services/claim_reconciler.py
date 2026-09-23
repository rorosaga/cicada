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

import re
from datetime import date, datetime, timedelta
from typing import Callable

from loguru import logger

from api.models.schemas import DecayClass
from api.services import decay_policy, inbox_questions, predicates
from api.services.claims import HAPPENED, MILESTONE, Claim, Evidence, event_cardinality, is_event, is_record

# A cardinality oracle: predicate -> True (single-valued) | False (multi-valued).
CardinalityFn = Callable[[str], bool]

# A decay-class oracle: subject entity id -> the subject's DecayClass. Injected
# so this module stays pure trust/temporal logic with no filesystem dependency.
DecayClassFn = Callable[[str], DecayClass]

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


def _reinforce(existing: Claim, incoming: Claim) -> None:
    """Reaffirmation/duplicate: bump confidence + merge episodes; no new claim."""
    existing.confidence = max(existing.confidence, incoming.confidence)
    for ep in incoming.source_episodes or []:
        if ep and ep not in existing.source_episodes:
            existing.source_episodes.append(ep)
    if incoming.recorded_at:
        existing.recorded_at = incoming.recorded_at
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


def _normalization_audit_nudge(raw_label: str, canonical: str, claim: Claim) -> dict:
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


def reconcile_stage3(
    incoming_claims: list[Claim],
    existing_claims_by_subject: dict[str, list[Claim]],
    settings,
    *,
    cardinality_fn: CardinalityFn | None = None,
    now_date: str | None = None,
    decay_class_fn: DecayClassFn | None = None,
) -> tuple[dict[str, list[Claim]], list[dict], list[dict]]:
    """Trust-gated invalidate-and-supersede over claims. Nothing deleted.

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
        now_date: decay reference date (ISO); defaults to today.
        decay_class_fn: ``subject_id -> DecayClass``, multiplying each claim's
            decay by its subject entity's class (G66). Defaults to the
            filesystem lookup for ``settings.memory_path``; an evergreen subject
            means its claims never decay.

    Returns ``(reconciled_by_subject, nudges, audit)``. ``nudges`` carries
    ``conflict_nudge`` / ``divergence_nudge`` / ``normalization_audit`` records in
    the inbox-generator change shape; ``audit`` carries ``supersede`` / ``rejected``
    bookkeeping (never user-facing, surfaced in the commit/logs).
    """
    today = now_date or str(date.today())
    if cardinality_fn is None:
        cardinality_fn = _default_cardinality_fn(settings)
    if decay_class_fn is None:
        decay_class_fn = decay_policy.class_lookup(getattr(settings, "memory_path", "."))

    reconciled: dict[str, list[Claim]] = {
        sub: list(claims) for sub, claims in existing_claims_by_subject.items()
    }
    nudges: list[dict] = []
    audit: list[dict] = []
    referenced_subjects: set[str] = set()
    audited_folds: set[tuple[str, str]] = set()
    # G141 rule 1: an existing happening absorbs at most one incoming claim per
    # pass, so two distinct happenings quoting one sentence never collapse.
    absorbed: set[str] = set()

    for new in incoming_claims:
        sub = new.subject
        referenced_subjects.add(sub)
        slot = reconciled.setdefault(sub, [])

        if is_event(new):
            # G141 §5.1: an event has its own rules (span identity, the
            # milestone slot, settles) — the K table would read two milestones
            # of one project as a conflict.
            reconcile_events(new, slot, settings, today=today, nudges=nudges, audit=audit, absorbed=absorbed)
            continue

        # Mandatory normalization-audit nudge on any auto-folded predicate.
        raw_label = getattr(new, "predicate_raw", None)
        if raw_label:
            raw_norm = re.sub(r"\s+", " ", str(raw_label).strip().lower())
            canonical = new.predicate
            if raw_norm and raw_norm != canonical:
                fold_key = (raw_norm, canonical)
                if fold_key not in audited_folds:
                    audited_folds.add(fold_key)
                    nudges.append(_normalization_audit_nudge(str(raw_label), canonical, new))

        same_key_open = [c for c in slot if open_(c) and K(c) == K(new)]

        if not same_key_open:
            slot.append(_stamp_new(new, settings, today=today))
            continue

        single = cardinality_fn(new.predicate)

        if not single:
            # Multi-valued: coexist unless an exact-object duplicate exists.
            dup = next((c for c in same_key_open if same_object(c, new)), None)
            if dup is None:
                slot.append(_stamp_new(new, settings, today=today))
            else:
                _reinforce(dup, new)
            continue

        # Single-valued: ≤1 open per slot.
        existing = same_key_open[0]
        if same_object(existing, new):
            _reinforce(existing, new)
            continue

        action = trust_decision(new, existing)
        if action == "SUPERSEDE":
            _close(existing, by=_stamp_new(new, settings, today=today))
            slot.append(new)
            audit.append({"action": "supersede", "closed": existing.id, "by": new.id})
        elif action == "COEXIST_FLAG":
            slot.append(_stamp_new(new, settings, today=today, status_note="shadowed_by_human"))
            nudges.append(_divergence_nudge(existing, new))
        elif action == "CONFLICT_NUDGE":
            nudges.append(_conflict_nudge(existing, new, today))
        elif action == "REJECT":
            audit.append({"action": "rejected", "kept": existing.id, "dropped": new.id})
        elif action == "KEEP_BOTH":
            slot.append(_stamp_new(new, settings, today=today))

    _decay_claims(reconciled, referenced_subjects, settings, nudges, today, decay_class_fn)
    return reconciled, nudges, audit


# --------------------------------------------------------------------------- #
# decay (§7) — per-epistemic × source_trust; lowers confidence only
# --------------------------------------------------------------------------- #


def _days_since(ref: str | None, today: str) -> int:
    try:
        a = datetime.fromisoformat(today[:10]).date()
        b = datetime.fromisoformat((ref or today)[:10]).date()
    except ValueError:
        return 0
    return max(0, (a - b).days)


def _max_date(left: str | None, right: str | None) -> str | None:
    """The later of two ISO date/date-time strings; either may be missing."""
    candidates = [str(c)[:10] for c in (left, right) if c]
    return max(candidates) if candidates else None


def _decay_claims(
    reconciled: dict[str, list[Claim]],
    referenced_subjects: set[str],
    settings,
    nudges: list[dict],
    today: str,
    decay_class_fn: DecayClassFn,
) -> None:
    archive_threshold = float(getattr(settings, "archive_threshold", 0.2) or 0.2)
    nudge_threshold = float(getattr(settings, "decay_nudge_threshold", 0.4) or 0.4)

    for subject, claims in reconciled.items():
        if subject in referenced_subjects:
            continue
        # One lookup per subject, not per claim.
        multiplier = decay_policy.claim_multiplier(decay_class_fn(subject))
        if multiplier <= 0:
            continue  # evergreen subject: its claims are artifacts, they don't fade
        for c in claims:
            if not open_(c) or is_event(c):
                # Closed claims are history; events are asked about (the G141
                # follow-up), never faded (R-PJ12).
                continue
            base = _DECAY_BASE.get(c.epistemic, 0.02)
            factor = _DECAY_FACTOR.get(c.source_trust, 1.0)
            # G85 §2 / Wave-1 1.1: `recorded_at`/`valid_from` never move, so
            # anchoring decay to them alone re-charges the SAME elapsed span
            # on every Sleep run. `decayed_through` is the watermark this pass
            # itself stamps below; anchor to whichever is more recent so an
            # interval is charged exactly once.
            anchor = _max_date(c.decayed_through, c.recorded_at or c.valid_from)
            raw_days = _days_since(anchor, today)
            # Wave-1 1.8: cap the charge at MAX_DECAY_DAYS_PER_CYCLE and
            # advance the watermark by only that capped amount (not to
            # `today`) — a long gap works off gradually over several cycles
            # instead of charging the whole span as one cliff.
            charged_days = min(raw_days, MAX_DECAY_DAYS_PER_CYCLE)
            amount = base * factor * multiplier * (charged_days / 7.0)
            today_date = date.fromisoformat(today[:10])
            try:
                anchor_date = date.fromisoformat((anchor or today)[:10])
                new_watermark = min(today_date, anchor_date + timedelta(days=charged_days))
            except ValueError:
                new_watermark = today_date
            if amount > 0:
                new_conf = max(0.0, c.confidence - amount)
                if new_conf != c.confidence:
                    c.confidence = new_conf
                    # Decay never closes a claim and never touches a human
                    # claim's validity — it only lowers the retrieval weight
                    # + may nudge.
                    if new_conf < archive_threshold:
                        nudges.append({
                            "id": subject,
                            "action": "decay_nudge",
                            "entity": {"name": _entity_name(c)},
                            "new_confidence": new_conf,
                            "claim_id": c.id,
                            "source_episode": (c.source_episodes or [None])[-1],
                            "trigger": "sleep/decay",
                        })
                    elif new_conf < nudge_threshold:
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
            c.decayed_through = new_watermark.isoformat()


# --------------------------------------------------------------------------- #
# cardinality oracle (§5) — _predicates.yaml first, conservative default
# --------------------------------------------------------------------------- #


def _default_cardinality_fn(settings) -> CardinalityFn:
    memory_path = getattr(settings, "memory_path", None)
    base = predicates.build_cardinality_fn(memory_path)
    # G141 R-PJ5: event cardinality lives in code — a bank's stale
    # `_predicates.yaml` must never make `happened` single-valued.
    return lambda p: False if event_cardinality(p) else base(p)
