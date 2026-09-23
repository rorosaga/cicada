"""G61 phase 2 S2 — which inbox questions a source could answer, derived at read.

Spec: ``docs/superpowers/specs/2026-09-23-g61-agent-first-clarification-design.md``
§4 (the ceiling by kind, the clamps, targets and rungs; R-AC8, R-AC9) and the
owner's D-AC2 ruling; plan ``docs/superpowers/plans/2026-09-23-g61-s0-s2.md``
(R-AC34 … R-AC41 — the state machine is R-AC34's table).

Pure, engine-free and zero-network, like ``recommended_key`` and ``cause``: the
answer is recomputed on every read from the item, the subject page (its
``sources:``, its ``owner:`` flag, its claims) and the predicate vocabulary, and
it is never stored — a source added a minute ago changes it at once. Nothing
here checks, holds or settles anything: S2 only says what COULD be checked, and
:func:`census` counts it, ids-free, so the owner can see whether S3–S8 are worth
building (spec §13, §15).
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Callable

from api.services import fact_sources, inbox_questions, predicates
from api.services.claim_reconciler import is_human

CHECKABLE = "checkable"
NEEDS_SOURCE = "needs_source"
INFORM_ONLY = "inform_only"
NEVER = "never"
STATES = (CHECKABLE, NEEDS_SOURCE, INFORM_ONLY, NEVER)

RUNG_FETCH = "fetch"              # Cicada's own public read (S4)
RUNG_AGENT = "agent"              # an agent the person runs, any harness (S3)
RUNG_AGENT_LOCAL = "agent_local"  # an agent on this Mac: an app, a file, a repo
RUNGS = (RUNG_FETCH, RUNG_AGENT, RUNG_AGENT_LOCAL)

LOCI = ("world", "artifact", "person", "unknown")

# Every reason `checkability` can give, per state (plan R-AC34).
REASONS: dict[str, tuple[str, ...]] = {
    NEVER: ("not_a_question", "unknown_kind", "informational", "person_locus"),
    INFORM_ONLY: ("merge_suggestion", "only_me", "divergence", "clarification", "refused_host_only"),
    NEEDS_SOURCE: ("no_source", "owner_subject", "unknown_locus"),
    CHECKABLE: ("entity_path", "human_option", "artifact_locus", "owner_subject", "recent_speech",
                "access_unverified", "no_settle_grade_source", "settle_eligible"),
}

RECENT_SPEECH_DAYS = 14   # clamp 4 (plan R-AC38): recent speech outranks a page that may be stale
MAX_TARGETS = 3
ENTITY_PATH_KEY = "description"   # inbox_generator.generate keys every entity-path question on it
_NOT_A_QUESTION = frozenset({"decay", "normalization", "removal"})
_QUESTION_KINDS = frozenset({"conflict", "divergence", "clarification", "merge_suggestion"})
_SYNTHETIC_KEYS = frozenset({"both", "neither"})
_TRUSTED = frozenset({fact_sources.USER, fact_sources.CICADA})


@dataclass(frozen=True)
class Vocab:
    """The two predicate facts checkability needs, read once per inbox read."""

    cardinality: Callable[[str], str]
    locus: Callable[[str], str]


def vocab_for(memory_path: Path | None) -> Vocab:
    """The locus lists are read once; ``cardinality`` is memoised per predicate
    for the life of this Vocab (one inbox read), so an inbox of fifty items
    reads the bank's ``_predicates.yaml`` once per distinct predicate, not once
    per item (``predicates.cardinality`` re-reads the file on every call)."""
    cardinality = lru_cache(maxsize=None)(lambda p: predicates.cardinality(memory_path, p))
    return Vocab(cardinality=cardinality, locus=predicates.build_locus_fn(memory_path))


@dataclass(frozen=True)
class Target:
    """One place the fact could be checked, and by which rungs (spec §4.3)."""

    ref: str
    kind: str
    access: str
    added_by: str
    predicate_matched: bool
    accepted: bool
    rungs: tuple[str, ...]
    own_session_only: bool = False

    def to_wire(self) -> dict:
        return {"ref": self.ref, "kind": self.kind, "access": self.access, "added_by": self.added_by,
                "predicate_matched": self.predicate_matched, "accepted": self.accepted,
                "rungs": list(self.rungs), "own_session_only": self.own_session_only}


@dataclass(frozen=True)
class Checkability:
    state: str
    reason: str
    locus: str = "unknown"
    targets: tuple[Target, ...] = ()
    rungs: tuple[str, ...] = ()
    settle_eligible: bool = False

    def to_wire(self) -> dict:
        return {"state": self.state, "reason": self.reason, "locus": self.locus,
                "targets": [t.to_wire() for t in self.targets], "rungs": list(self.rungs),
                "settle_eligible": self.settle_eligible}


def _kind_ceiling(kind: str) -> Checkability | None:
    """Rows 1–3: the kinds decided before anything is read (spec §4.1)."""
    if kind in _NOT_A_QUESTION:
        return Checkability(NEVER, "not_a_question")          # G121(e): not a question of fact
    if kind == "followup":
        # G141 PJ-6: "how did it go?" is the person's own experience — no page can say it.
        return Checkability(NEVER, "person_locus", "person")
    if kind not in _QUESTION_KINDS:
        return Checkability(NEVER, "unknown_kind")
    if kind == "merge_suggestion":
        return Checkability(INFORM_ONLY, "merge_suggestion")  # G81 / G115 §4: never marked
    return None


def _added_by(source: dict) -> str:
    return str(source.get("added_by") or fact_sources.USER)


def _matches(source: dict, predicate: str | None) -> bool:
    """Predicate match (plan R-AC35): the entity path's ``description`` key also
    takes a source with no predicate — one attached to the page as a whole."""
    if not predicate:
        return False
    if fact_sources.same_predicate(source.get("predicate"), predicate):
        return True
    return predicate == ENTITY_PATH_KEY and not str(source.get("predicate") or "").strip()


def _rank(source: dict) -> int:
    who = _added_by(source)
    return 0 if who == fact_sources.USER else 1 if who == fact_sources.CICADA else 2


def _target(source: dict, matched: bool) -> Target:
    ref = str(source.get("ref") or "").strip()
    kind = str(source.get("kind") or fact_sources.infer_kind(ref))
    access = fact_sources.effective_access(source)
    refused = kind == fact_sources.KIND_URL and fact_sources.is_refused_host(ref)
    if kind == fact_sources.KIND_URL:
        if refused:
            rungs: tuple[str, ...] = (RUNG_AGENT,)   # D-AC2: the person's own open session only
        elif access in (fact_sources.ACCESS_PUBLIC, fact_sources.ACCESS_UNKNOWN):
            rungs = (RUNG_FETCH, RUNG_AGENT)
        else:
            rungs = (RUNG_AGENT,)
    elif kind == fact_sources.KIND_NOTE:
        rungs = (RUNG_AGENT,)                        # the note IS the instruction
    else:
        rungs = (RUNG_AGENT_LOCAL,)
    return Target(ref=ref, kind=kind, access=access, added_by=_added_by(source), predicate_matched=matched,
                  accepted=bool(source.get("accepted")), rungs=rungs, own_session_only=refused)


def targets_for(sources, predicate: str | None, *, person_only: bool) -> tuple[Target, ...]:
    """Ranked targets (spec §4.3): predicate-matched first — the person's, then
    Cicada's, then an agent's, file order within each — capped at
    :data:`MAX_TARGETS`; with no match, the first ``url`` (the hint's own
    fallback). An "Only I know" note is never a target. On the owner's page only
    the person's sources count (R-AC9)."""
    usable = [s for s in fact_sources.as_sources(sources) if not s.get("only_me")]
    if person_only:
        usable = [s for s in usable if _added_by(s) == fact_sources.USER]
    matched = sorted((s for s in usable if _matches(s, predicate)), key=_rank)
    if matched:
        return tuple(_target(s, True) for s in matched[:MAX_TARGETS])
    first_url = next((s for s in usable if str(s.get("kind") or "") == fact_sources.KIND_URL), None)
    return (_target(first_url, False),) if first_url is not None else ()


def _only_me(sources, predicate: str | None) -> bool:
    return any(s.get("only_me") and _added_by(s) == fact_sources.USER and _matches(s, predicate)
               for s in fact_sources.as_sources(sources))


def _rungs(targets: tuple[Target, ...]) -> tuple[str, ...]:
    return tuple(r for r in RUNGS if any(r in t.rungs for t in targets))


def _settle_block(options: list[dict], option_claims: dict, targets: tuple[Target, ...], *, locus: str,
                  owner: bool, entity_path: bool, today: str) -> str:
    """The first reason a checkable conflict may NOT settle, else ``settle_eligible``
    (plan R-AC34; spec §4.2 clamps 1–4, §4.3 eligibility; clamp 5 is S7's, R-AC37)."""
    if entity_path:
        return "entity_path"
    if any(c is not None and c.valid_to is None and is_human(c) for c in option_claims.values()):
        return "human_option"
    if locus == "artifact":
        return "artifact_locus"
    if owner:
        return "owner_subject"
    for option in options:
        if str(option.get("key")) in _SYNTHETIC_KEYS:
            continue
        age = inbox_questions.age_days(option.get("last_referenced") or option.get("observed_at"), today)
        if age is not None and age <= RECENT_SPEECH_DAYS:
            return "recent_speech"
    grade = [t for t in targets if t.predicate_matched and t.kind == fact_sources.KIND_URL
             and not t.own_session_only and (t.added_by in _TRUSTED or t.accepted)]
    if any(t.access == fact_sources.ACCESS_PUBLIC for t in grade):
        return "settle_eligible"
    if any(t.access == fact_sources.ACCESS_UNKNOWN for t in grade):
        return "access_unverified"
    return "no_settle_grade_source"


def checkability(item_fm: dict, *, options: list[dict], option_claims: dict, subject_fm: dict | None,
                 vocab: Vocab, today: str) -> Checkability:
    """Which rung could answer this item, and whether a finding could ever settle
    it (spec §4). The order is plan R-AC34's table; the first row that applies
    decides. ``option_claims`` maps an option key to its claim (absent when the
    claim is not on the page)."""
    kind = str(item_fm.get("kind") or "")
    early = _kind_ceiling(kind)
    if early is not None:
        return early
    raw_predicate = str(item_fm.get("predicate") or "").strip().lower()
    predicate = (raw_predicate or ENTITY_PATH_KEY) if kind == "conflict" else (raw_predicate or None)
    locus = vocab.locus(predicate) if predicate else "unknown"
    if kind == "conflict" and vocab.cardinality(predicate) == "multi":
        return Checkability(NEVER, "informational", locus)    # G98: shown, never asked
    if locus == "person":
        return Checkability(NEVER, "person_locus", locus)     # a page cannot say what someone prefers
    subject_fm = subject_fm or {}
    sources = subject_fm.get("sources")
    if predicate and _only_me(sources, predicate):
        return Checkability(INFORM_ONLY, "only_me", locus)
    owner = subject_fm.get("owner") is True
    targets = targets_for(sources, predicate, person_only=owner)
    rungs = _rungs(targets)
    if not targets:
        reason = "owner_subject" if owner and fact_sources.as_sources(sources) else "no_source"
        return Checkability(NEEDS_SOURCE, reason, locus)
    if kind == "conflict" and locus == "unknown" and not any(
            t.predicate_matched and t.added_by == fact_sources.USER for t in targets):
        return Checkability(NEEDS_SOURCE, "unknown_locus", locus, targets, rungs)
    if kind in ("divergence", "clarification"):
        return Checkability(INFORM_ONLY, kind, locus, targets, rungs)
    if all(t.own_session_only for t in targets):
        return Checkability(INFORM_ONLY, "refused_host_only", locus, targets, rungs)
    reason = _settle_block(options, option_claims, targets, locus=locus, owner=owner,
                           entity_path=not item_fm.get("claim_id"), today=today)
    return Checkability(CHECKABLE, reason, locus, targets, rungs, settle_eligible=reason == "settle_eligible")


def for_item(item_fm: dict, options: list[dict], context) -> Checkability:
    """:func:`checkability` with its inputs from ``inbox_context.InboxContext``'s
    caches — the one call ``load_inbox`` makes per item. A kind decided by its
    ceiling returns before the page is touched, and the page's claims are parsed
    only when an option names a claim — so a decay-heavy inbox costs nothing new
    (the parse budget ``test_inbox_context.py`` pins)."""
    early = _kind_ceiling(str(item_fm.get("kind") or ""))
    if early is not None:
        return early
    entity_id = str(item_fm.get("entity_id") or "")
    page = context.entity(entity_id)
    option_claims: dict = {}
    if any(o.get("claim_id") for o in options):
        by_id = {c.id: c for c in context.claims(entity_id)}
        option_claims = {str(o.get("key")): by_id[str(o["claim_id"])]
                         for o in options if o.get("claim_id") and str(o["claim_id"]) in by_id}
    return checkability(item_fm, options=options, option_claims=option_claims,
                        subject_fm=page.frontmatter if page is not None else None,
                        vocab=context.check_vocab(), today=context.today)


def census(memory_path: Path) -> dict:
    """How much of the pending inbox a source could answer (spec §15's coverage
    gate, plan R-AC41). Counts only: every key is an enum and every value an
    integer (plus the one ``checkable_share`` ratio), so the output can go into
    a PR or a backlog row as it is — never an item id, a page id, a link or a
    host. Deferred items are pending questions
    and count (``deferred`` says how many). Read-only: ``load_inbox`` writes
    nothing."""
    from api.services import inbox_service

    today = str(date.today())
    items = [i for i in inbox_service.load_inbox(Path(memory_path), include_deferred=True) if i.status == "pending"]
    by_state: Counter = Counter()
    by_reason: Counter = Counter()
    by_locus: Counter = Counter()
    by_rung: Counter = Counter()
    by_access: Counter = Counter()
    by_kind: dict[str, Counter] = {}
    settle = deferred = 0
    for item in items:
        check = item.check
        if check is None:
            continue
        by_state[check.state] += 1
        by_reason[f"{check.state}/{check.reason}"] += 1
        by_locus[check.locus] += 1
        by_kind.setdefault(item.kind.value, Counter())[check.state] += 1
        for rung in check.rungs:
            by_rung[rung] += 1
        for target in check.targets:
            by_access[target.access] += 1
        settle += int(check.settle_eligible)
        if item.remind_after and inbox_questions.is_deferred({"remind_after": item.remind_after}, today):
            deferred += 1
    total = len(items)
    return {
        "total": total,
        "deferred": deferred,
        "by_state": {s: by_state.get(s, 0) for s in STATES},
        "by_reason": dict(sorted(by_reason.items())),
        "by_kind": {k: {s: c.get(s, 0) for s in STATES} for k, c in sorted(by_kind.items())},
        "by_locus": {x: by_locus.get(x, 0) for x in LOCI},
        "by_rung": {r: by_rung.get(r, 0) for r in RUNGS},
        "targets_by_access": {a: by_access.get(a, 0) for a in fact_sources.ACCESS_VALUES},
        "settle_eligible": settle,
        "checkable_share": round(by_state.get(CHECKABLE, 0) / total, 3) if total else 0.0,
    }
