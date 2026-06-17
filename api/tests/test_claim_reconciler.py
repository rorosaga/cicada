"""Tests for M5e Stage-3 trust-reconciliation (``claim_reconciler``).

Implements the decision tables in ``docs/goals/m5-prep/sleep-trust-reconciliation.md``
exactly. The core invariant under test: **no agent/external claim ever supersedes
a human (``user_stated`` + manual/clarification origin) claim** — it COEXIST-flags
(soft divergence) or becomes a CONFLICT nudge; only a *newer human* claim closes a
human claim. Agent-over-agent on a single-valued predicate is the mechanical
invalidate-and-supersede path (``valid_to`` / ``superseded_by`` / ``supersedes``);
multi-valued predicates coexist. Nothing is ever deleted.

Hermetic: cardinality is resolved against a seeded ``_predicates.yaml`` in a tmp
workspace; no LLM, no network. The reconciler's single-vs-multi judgment is
injected via a ``cardinality_fn`` seam so the mechanical path makes zero LLM calls.
"""

from __future__ import annotations

from api.services import predicates
from api.services.claim_reconciler import reconcile_stage3
from api.services.claims import Claim


def _claim(
    cid,
    subject="rodrigo",
    predicate="works-at",
    obj="acme",
    *,
    observer="agent",
    context="career",
    source_trust="agent_extracted",
    origin="claude-code",
    valid_from="2026-01-01",
    valid_to=None,
    confidence=0.8,
    epistemic="explicit",
):
    return Claim(
        id=cid,
        text=f"{subject} {predicate} {obj}",
        subject=subject,
        predicate=predicate,
        object=obj,
        observer=observer,
        context=context,
        source_trust=source_trust,
        origin=origin,
        valid_from=valid_from,
        valid_to=valid_to,
        confidence=confidence,
        epistemic=epistemic,
    )


def _human(cid, **kw):
    kw.setdefault("source_trust", "user_stated")
    kw.setdefault("origin", "clarification")
    return _claim(cid, **kw)


def _single_card(_pred):
    return True


def _multi_card(_pred):
    return False


def _by_subject(claims):
    out: dict[str, list[Claim]] = {}
    for c in claims:
        out.setdefault(c.subject, []).append(c)
    return out


# --------------------------------------------------------------------------- #
# C0 — first belief in a slot just lands
# --------------------------------------------------------------------------- #


def test_c0_first_claim_in_slot_is_added(tmp_path):
    predicates.install_predicate_map(tmp_path)
    new = _claim("clm_new", obj="acme")
    reconciled, nudges, audit = reconcile_stage3(
        [new], {}, _settings(tmp_path), cardinality_fn=_single_card
    )
    assert [c.id for c in reconciled["rodrigo"]] == ["clm_new"]
    assert nudges == []


# --------------------------------------------------------------------------- #
# C8 — agent-over-agent, newer => mechanical SUPERSEDE
# --------------------------------------------------------------------------- #


def test_c8_agent_over_agent_newer_supersedes(tmp_path):
    predicates.install_predicate_map(tmp_path)
    old = _claim("clm_old", obj="postgres", valid_from="2026-01-15")
    new = _claim("clm_new", obj="sqlite-vec", valid_from="2026-05-05")
    reconciled, nudges, audit = reconcile_stage3(
        [new], _by_subject([old]), _settings(tmp_path), cardinality_fn=_single_card
    )
    by_id = {c.id: c for c in reconciled["rodrigo"]}
    # old claim is CLOSED, not deleted
    assert by_id["clm_old"].valid_to == "2026-05-05"
    assert by_id["clm_old"].superseded_by == "clm_new"
    # new claim is open and records the supersede link
    assert by_id["clm_new"].valid_to is None
    assert by_id["clm_new"].supersedes == "clm_old"
    # nothing deleted
    assert set(by_id) == {"clm_old", "clm_new"}


def test_c8_agent_over_agent_no_date_cue_becomes_conflict_nudge(tmp_path):
    predicates.install_predicate_map(tmp_path)
    old = _claim("clm_old", obj="postgres", valid_from="2026-01-15")
    new = _claim("clm_new", obj="sqlite-vec", valid_from="2026-01-15")  # same date
    reconciled, nudges, audit = reconcile_stage3(
        [new], _by_subject([old]), _settings(tmp_path), cardinality_fn=_single_card
    )
    # ambiguous recency => do NOT supersede; ask
    by_id = {c.id: c for c in reconciled["rodrigo"]}
    assert by_id["clm_old"].valid_to is None, "must not close on ambiguous recency"
    assert any(n.get("action") == "conflict_nudge" for n in nudges)


# --------------------------------------------------------------------------- #
# THE CORE: agent can never supersede a human (C5/C6)
# --------------------------------------------------------------------------- #


def test_agent_cannot_supersede_human_coexist_flag(tmp_path):
    predicates.install_predicate_map(tmp_path)
    human = _human("clm_human", obj="acme", valid_from="2026-01-01")
    agent = _claim("clm_agent", obj="globex", valid_from="2026-05-05")  # newer!
    reconciled, nudges, audit = reconcile_stage3(
        [agent], _by_subject([human]), _settings(tmp_path), cardinality_fn=_single_card
    )
    by_id = {c.id: c for c in reconciled["rodrigo"]}
    # human claim stays OPEN and authoritative — never closed by the agent
    assert by_id["clm_human"].valid_to is None
    assert by_id["clm_human"].superseded_by is None
    # agent claim IS recorded (so retrieval can see it) but flagged shadowed
    assert "clm_agent" in by_id
    # a soft divergence nudge is emitted
    assert any(n.get("action") == "divergence_nudge" for n in nudges)


def test_external_cannot_supersede_human_coexist_flag(tmp_path):
    predicates.install_predicate_map(tmp_path)
    human = _human("clm_human", obj="acme", valid_from="2026-01-01")
    ext = _claim(
        "clm_ext", obj="globex", valid_from="2026-05-05", source_trust="external",
        origin="rss",
    )
    reconciled, nudges, audit = reconcile_stage3(
        [ext], _by_subject([human]), _settings(tmp_path), cardinality_fn=_single_card
    )
    by_id = {c.id: c for c in reconciled["rodrigo"]}
    assert by_id["clm_human"].valid_to is None
    assert any(n.get("action") == "divergence_nudge" for n in nudges)


# --------------------------------------------------------------------------- #
# C7 — human corrects agent => SUPERSEDE allowed
# --------------------------------------------------------------------------- #


def test_c7_human_supersedes_agent(tmp_path):
    predicates.install_predicate_map(tmp_path)
    agent = _claim("clm_agent", obj="acme", valid_from="2026-01-01")
    human = _human("clm_human", obj="globex", valid_from="2026-05-05")
    reconciled, nudges, audit = reconcile_stage3(
        [human], _by_subject([agent]), _settings(tmp_path), cardinality_fn=_single_card
    )
    by_id = {c.id: c for c in reconciled["rodrigo"]}
    assert by_id["clm_agent"].valid_to == "2026-05-05"
    assert by_id["clm_agent"].superseded_by == "clm_human"
    assert by_id["clm_human"].supersedes == "clm_agent"


# --------------------------------------------------------------------------- #
# C4 — human over human: newer supersedes; equal date => conflict nudge
# --------------------------------------------------------------------------- #


def test_c4_human_over_human_newer_supersedes(tmp_path):
    predicates.install_predicate_map(tmp_path)
    old = _human("clm_h1", obj="acme", valid_from="2026-01-01")
    new = _human("clm_h2", obj="globex", valid_from="2026-05-05")
    reconciled, nudges, audit = reconcile_stage3(
        [new], _by_subject([old]), _settings(tmp_path), cardinality_fn=_single_card
    )
    by_id = {c.id: c for c in reconciled["rodrigo"]}
    assert by_id["clm_h1"].valid_to == "2026-05-05"
    assert by_id["clm_h1"].superseded_by == "clm_h2"


def test_c4_human_over_human_equal_date_is_conflict_nudge(tmp_path):
    predicates.install_predicate_map(tmp_path)
    old = _human("clm_h1", obj="acme", valid_from="2026-05-05")
    new = _human("clm_h2", obj="globex", valid_from="2026-05-05")
    reconciled, nudges, audit = reconcile_stage3(
        [new], _by_subject([old]), _settings(tmp_path), cardinality_fn=_single_card
    )
    by_id = {c.id: c for c in reconciled["rodrigo"]}
    assert by_id["clm_h1"].valid_to is None, "equal date must not auto-close a human claim"
    assert any(n.get("action") == "conflict_nudge" for n in nudges)


# --------------------------------------------------------------------------- #
# §6 — degenerate user_stated-but-agent-origin is treated as agent
# --------------------------------------------------------------------------- #


def test_user_stated_but_agent_origin_is_not_protected(tmp_path):
    predicates.install_predicate_map(tmp_path)
    # source_trust user_stated, but origin is a logged harness (agent extracted it)
    spoof = _claim(
        "clm_spoof", obj="acme", source_trust="user_stated", origin="claude-code",
        valid_from="2026-01-01",
    )
    newer_agent = _claim("clm_agent", obj="globex", valid_from="2026-05-05")
    reconciled, nudges, audit = reconcile_stage3(
        [newer_agent], _by_subject([spoof]), _settings(tmp_path),
        cardinality_fn=_single_card,
    )
    by_id = {c.id: c for c in reconciled["rodrigo"]}
    # because the existing claim is NOT origin-protected, a newer agent claim
    # supersedes it (treated as agent-over-agent), not coexist-flagged
    assert by_id["clm_spoof"].valid_to == "2026-05-05"
    assert by_id["clm_spoof"].superseded_by == "clm_agent"


# --------------------------------------------------------------------------- #
# C13/C14 — perspectival escape hatch: different observer/context never collide
# --------------------------------------------------------------------------- #


def test_c13_different_observer_keep_both(tmp_path):
    predicates.install_predicate_map(tmp_path)
    a = _claim("clm_a", obj="postgres", observer="agent", valid_from="2026-01-01")
    b = _claim("clm_b", obj="sqlite-vec", observer="rodrigo", valid_from="2026-05-05")
    reconciled, nudges, audit = reconcile_stage3(
        [b], _by_subject([a]), _settings(tmp_path), cardinality_fn=_single_card
    )
    by_id = {c.id: c for c in reconciled["rodrigo"]}
    # different observer => different slot => no supersede, no conflict
    assert by_id["clm_a"].valid_to is None
    assert by_id["clm_b"].valid_to is None
    assert not any(n.get("action") in ("conflict_nudge", "divergence_nudge") for n in nudges)


def test_c14_different_context_keep_both(tmp_path):
    predicates.install_predicate_map(tmp_path)
    eng = _claim("clm_eng", predicate="values", obj="speed", context="engineering",
                 valid_from="2026-01-01")
    fam = _claim("clm_fam", predicate="values", obj="presence", context="family",
                 valid_from="2026-05-05")
    reconciled, nudges, audit = reconcile_stage3(
        [fam], _by_subject([eng]), _settings(tmp_path), cardinality_fn=_single_card
    )
    by_id = {c.id: c for c in reconciled["rodrigo"]}
    assert by_id["clm_eng"].valid_to is None
    assert by_id["clm_fam"].valid_to is None


# --------------------------------------------------------------------------- #
# Multi-valued predicates coexist (C1/C2)
# --------------------------------------------------------------------------- #


def test_multi_valued_predicate_coexists(tmp_path):
    predicates.install_predicate_map(tmp_path)
    a = _claim("clm_a", predicate="uses", obj="postgres", valid_from="2026-01-01")
    b = _claim("clm_b", predicate="uses", obj="sqlite-vec", valid_from="2026-05-05")
    reconciled, nudges, audit = reconcile_stage3(
        [b], _by_subject([a]), _settings(tmp_path), cardinality_fn=_multi_card
    )
    by_id = {c.id: c for c in reconciled["rodrigo"]}
    # both stay open — multi-valued never supersedes
    assert by_id["clm_a"].valid_to is None
    assert by_id["clm_b"].valid_to is None
    assert "clm_a" in by_id and "clm_b" in by_id


def test_multi_valued_duplicate_reinforces_not_duplicates(tmp_path):
    predicates.install_predicate_map(tmp_path)
    a = _claim("clm_a", predicate="uses", obj="postgres", valid_from="2026-01-01",
               confidence=0.5)
    dup = _claim("clm_dup", predicate="uses", obj="postgres", valid_from="2026-05-05",
                 confidence=0.9)
    reconciled, nudges, audit = reconcile_stage3(
        [dup], _by_subject([a]), _settings(tmp_path), cardinality_fn=_multi_card
    )
    ids = [c.id for c in reconciled["rodrigo"]]
    # the duplicate object did NOT create a second claim; it reinforced the first
    assert ids == ["clm_a"]


# --------------------------------------------------------------------------- #
# Single-valued reaffirmation (C3): same object => reinforce, no new claim
# --------------------------------------------------------------------------- #


def test_single_valued_same_object_reaffirms(tmp_path):
    predicates.install_predicate_map(tmp_path)
    a = _claim("clm_a", obj="acme", valid_from="2026-01-01", confidence=0.5)
    again = _claim("clm_again", obj="acme", valid_from="2026-05-05", confidence=0.9)
    reconciled, nudges, audit = reconcile_stage3(
        [again], _by_subject([a]), _settings(tmp_path), cardinality_fn=_single_card
    )
    ids = [c.id for c in reconciled["rodrigo"]]
    assert ids == ["clm_a"], "reaffirmation must not open a second claim"


# --------------------------------------------------------------------------- #
# C9 — agent_reflected may not close agent_extracted (REJECT, audited)
# --------------------------------------------------------------------------- #


def test_c9_reflected_cannot_supersede_extracted(tmp_path):
    predicates.install_predicate_map(tmp_path)
    extracted = _claim("clm_obs", obj="acme", source_trust="agent_extracted",
                       valid_from="2026-01-01")
    reflected = _claim("clm_guess", obj="globex", source_trust="agent_reflected",
                       valid_from="2026-05-05")
    reconciled, nudges, audit = reconcile_stage3(
        [reflected], _by_subject([extracted]), _settings(tmp_path),
        cardinality_fn=_single_card,
    )
    by_id = {c.id: c for c in reconciled["rodrigo"]}
    # observation is NOT closed by a guess
    assert by_id["clm_obs"].valid_to is None
    # the reflected claim is rejected (not added as superseding) and audited
    assert "clm_guess" not in by_id
    assert any(a.get("action") == "rejected" for a in audit)


# --------------------------------------------------------------------------- #
# Normalization-audit nudge on auto-folded predicates
# --------------------------------------------------------------------------- #


def test_normalization_audit_nudge_emitted_on_fold(tmp_path):
    predicates.install_predicate_map(tmp_path)
    # "built with" folds to "uses" — that fold must be audited
    new = _claim("clm_new", predicate="uses", obj="fastapi", valid_from="2026-01-01")
    new.predicate_raw = "built with"  # the pre-normalization label
    reconciled, nudges, audit = reconcile_stage3(
        [new], {}, _settings(tmp_path), cardinality_fn=_multi_card
    )
    assert any(n.get("action") == "normalization_audit" for n in nudges)


# --------------------------------------------------------------------------- #
# Decay (per-epistemic × source_trust) runs inside Stage 3
# --------------------------------------------------------------------------- #


def test_decay_lowers_confidence_but_never_closes_human(tmp_path):
    predicates.install_predicate_map(tmp_path)
    # a human claim NOT referenced this cycle decays slowly and never closes
    human = _human("clm_human", obj="acme", valid_from="2025-01-01", confidence=0.9)
    human.epistemic = "explicit"
    settings = _settings(tmp_path)
    reconciled, nudges, audit = reconcile_stage3(
        [], _by_subject([human]), settings, cardinality_fn=_single_card,
        now_date="2026-06-17",
    )
    c = reconciled["rodrigo"][0]
    assert c.valid_to is None, "decay must never close a human claim"
    assert c.confidence < 0.9, "unreferenced claim should have decayed"


def test_decay_user_stated_slower_than_agent(tmp_path):
    predicates.install_predicate_map(tmp_path)
    human = _human("clm_h", obj="a", valid_from="2025-01-01", confidence=0.9)
    agent = _claim("clm_a", subject="cicada", obj="b", valid_from="2025-01-01",
                   confidence=0.9)
    settings = _settings(tmp_path)
    reconciled, _, _ = reconcile_stage3(
        [], _by_subject([human, agent]), settings, cardinality_fn=_single_card,
        now_date="2026-06-17",
    )
    h = reconciled["rodrigo"][0]
    a = reconciled["cicada"][0]
    # user_stated decays at 0.3x => higher remaining confidence than agent_extracted
    assert h.confidence > a.confidence


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


class _FakeSettings:
    def __init__(self, memory_path):
        self.memory_path = memory_path
        self.litellm_model = "test-model"
        self.archive_threshold = 0.2
        self.decay_nudge_threshold = 0.4


def _settings(memory_path):
    return _FakeSettings(memory_path)
