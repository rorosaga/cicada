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
from datetime import date, datetime
from typing import Callable

from loguru import logger

from api.services import predicates
from api.services.claims import Claim

# A cardinality oracle: predicate -> True (single-valued) | False (multi-valued).
CardinalityFn = Callable[[str], bool]

# Decay lookup (D2 table): base rate per cycle by epistemic class.
_DECAY_BASE = {"explicit": 0.02, "deductive": 0.05, "inductive": 0.10, "abductive": 0.20}
# source_trust multiplier — user_stated fades ~3x slower than routine extraction.
_DECAY_FACTOR = {
    "user_stated": 0.3,
    "agent_extracted": 1.0,
    "agent_reflected": 1.5,
    "external": 1.0,
}

_HUMAN_ORIGINS = {"manual_edit", "clarification"}


# --------------------------------------------------------------------------- #
# trust predicates (§ Definitions + §6 degenerate case)
# --------------------------------------------------------------------------- #


def is_human(c: Claim) -> bool:
    """Full human protection requires BOTH user_stated AND a human origin (§6).

    A ``user_stated`` claim whose ``origin`` is a logged harness (the agent
    extracted a first-person statement) is NOT overwrite-protected — protection
    is anchored to ``origin``, which only the manual-edit / clarification paths
    may set. This closes the spoofing hole where routine extraction could
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
        claim.authored_by = (
            "user" if is_human(claim) else (getattr(settings, "litellm_model", "") or "unknown")
        )
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


def _conflict_nudge(existing: Claim, new: Claim) -> dict:
    return {
        "id": new.subject,
        "action": "conflict_nudge",
        "entity": {"name": _entity_name(new)},
        "conflict_context": (
            f"Conflicting beliefs about {_entity_name(new)} "
            f"({new.predicate}): '{existing.object}' vs '{new.object}'."
        ),
        "options": [
            f"{existing.object}",
            f"{new.object}",
            "Both are true (different contexts)",
        ],
        "source_episode": (new.source_episodes or [""])[0],
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
    }


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

    Returns ``(reconciled_by_subject, nudges, audit)``. ``nudges`` carries
    ``conflict_nudge`` / ``divergence_nudge`` / ``normalization_audit`` records in
    the inbox-generator change shape; ``audit`` carries ``supersede`` / ``rejected``
    bookkeeping (never user-facing, surfaced in the commit/logs).
    """
    today = now_date or str(date.today())
    if cardinality_fn is None:
        cardinality_fn = _default_cardinality_fn(settings)

    reconciled: dict[str, list[Claim]] = {
        sub: list(claims) for sub, claims in existing_claims_by_subject.items()
    }
    nudges: list[dict] = []
    audit: list[dict] = []
    referenced_subjects: set[str] = set()
    audited_folds: set[tuple[str, str]] = set()

    for new in incoming_claims:
        sub = new.subject
        referenced_subjects.add(sub)
        slot = reconciled.setdefault(sub, [])

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
            nudges.append(_conflict_nudge(existing, new))
        elif action == "REJECT":
            audit.append({"action": "rejected", "kept": existing.id, "dropped": new.id})
        elif action == "KEEP_BOTH":
            slot.append(_stamp_new(new, settings, today=today))

    _decay_claims(reconciled, referenced_subjects, settings, nudges, today)
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


def _decay_claims(
    reconciled: dict[str, list[Claim]],
    referenced_subjects: set[str],
    settings,
    nudges: list[dict],
    today: str,
) -> None:
    archive_threshold = float(getattr(settings, "archive_threshold", 0.2) or 0.2)
    nudge_threshold = float(getattr(settings, "decay_nudge_threshold", 0.4) or 0.4)

    for subject, claims in reconciled.items():
        if subject in referenced_subjects:
            continue
        for c in claims:
            if not open_(c):
                continue  # closed claims don't decay; they're history
            base = _DECAY_BASE.get(c.epistemic, 0.02)
            factor = _DECAY_FACTOR.get(c.source_trust, 1.0)
            ref = c.recorded_at or c.valid_from
            days = _days_since(ref, today)
            amount = base * factor * (days / 7.0)
            if amount <= 0:
                continue
            new_conf = max(0.0, c.confidence - amount)
            if new_conf == c.confidence:
                continue
            c.confidence = new_conf
            # Decay never closes a claim and never touches a human claim's
            # validity — it only lowers the retrieval weight + may nudge.
            if new_conf < archive_threshold:
                nudges.append({
                    "id": subject,
                    "action": "decay_nudge",
                    "entity": {"name": _entity_name(c)},
                    "new_confidence": new_conf,
                    "claim_id": c.id,
                    "trigger": "sleep/decay",
                })
            elif new_conf < nudge_threshold:
                nudges.append({
                    "id": subject,
                    "action": "decay_nudge",
                    "entity": {"name": _entity_name(c)},
                    "new_confidence": new_conf,
                    "claim_id": c.id,
                    "trigger": "sleep/decay",
                })


# --------------------------------------------------------------------------- #
# cardinality oracle (§5) — _predicates.yaml first, conservative default
# --------------------------------------------------------------------------- #


def _default_cardinality_fn(settings) -> CardinalityFn:
    memory_path = getattr(settings, "memory_path", None)
    return predicates.build_cardinality_fn(memory_path)
