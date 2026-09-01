"""G66 — both decay engines honor the class, and re-mention restores.

Hermetic: `resolve_and_prune` is driven with an EMPTY `resolved` list so the
synthesis/contradiction LLM path is never entered (it iterates only over
`action == "update"` changes). No network, no model.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from pathlib import Path

from api.models.schemas import DecayClass
from api.services import conflict_resolver, markdown_parser


class _FakeSettings:
    memory_path = None
    archive_threshold = 0.2
    decay_nudge_threshold = 0.4


def run(coro):
    return asyncio.run(coro)


def _existing(entity_id: str, days_ago: int = 35, **fm) -> dict:
    """One unreferenced existing entity. 35 days = 5 weeks by default, chosen so
    volatile floors to 0.0 while active and durable both stay above zero — the
    three classes are then distinguishable in one assertion."""
    base = {
        "name": entity_id.replace("-", " ").title(),
        "type": "concept",
        "status": "active",
        "confidence": 0.7,
        "last_referenced": str(date.today() - timedelta(days=days_ago)),
    }
    base.update(fm)
    return {"id": entity_id, "frontmatter": base, "body": "Body."}


def _by_id(changes: list[dict]) -> dict[str, dict]:
    return {c["id"]: c for c in changes if c.get("action") != "conflict_nudge"}


# --- evergreen is skipped outright -----------------------------------------


def test_evergreen_entity_produces_no_decay_change_at_all():
    changes = run(
        conflict_resolver.resolve_and_prune(
            [], [_existing("media-a-post", type="media")], _FakeSettings()
        )
    )
    assert changes == [], "an evergreen entity must not decay, nudge or archive"


def test_evergreen_by_explicit_class_is_skipped_even_for_a_normal_type():
    changes = run(
        conflict_resolver.resolve_and_prune(
            [], [_existing("pinned", type="concept", decay_class="evergreen")],
            _FakeSettings(),
        )
    )
    assert changes == []


# --- the other three classes decay at their own rates -----------------------


def test_volatile_decays_faster_than_active_which_decays_faster_than_durable():
    existing = [
        _existing("vol", decay_class="volatile"),
        _existing("act", decay_class="active"),
        _existing("dur", decay_class="durable"),
    ]
    changes = _by_id(run(conflict_resolver.resolve_and_prune([], existing, _FakeSettings())))

    vol = changes["vol"]["new_confidence"]
    act = changes["act"]["new_confidence"]
    dur = changes["dur"]["new_confidence"]
    assert vol < act < dur
    # 35 days = 5 weeks from 0.7: volatile (0.15/wk) drops 0.75 and floors at
    # 0.0 -> archived; active drops 0.25; durable drops 0.10 and barely moves.
    assert vol == 0.0
    assert changes["vol"]["action"] == "archive"
    assert changes["act"]["action"] == "decay"
    assert changes["dur"]["action"] == "decay"


def test_an_explicit_numeric_rate_still_wins_for_a_decaying_class():
    changes = _by_id(
        run(
            conflict_resolver.resolve_and_prune(
                [], [_existing("slow", decay_class="active", decay_rate=0.0)],
                _FakeSettings(),
            )
        )
    )
    assert changes["slow"]["new_confidence"] == 0.7, "a 0.0 rate never moves confidence"


def test_a_legacy_page_with_no_class_decays_exactly_as_before():
    changes = _by_id(
        run(
            conflict_resolver.resolve_and_prune(
                [], [_existing("legacy", days_ago=140, decay_rate=0.05)], _FakeSettings()
            )
        )
    )
    # 140 days = 20 weeks * 0.05 = 1.0 drop -> floored at 0.0 -> archived,
    # exactly what the pre-G66 engine did for this page.
    assert changes["legacy"]["action"] == "archive"
    assert changes["legacy"]["new_confidence"] == 0.0


def test_archived_and_dropped_entities_are_still_skipped():
    existing = [
        _existing("gone", status="archived"),
        _existing("nope", status="dropped"),
    ]
    assert run(conflict_resolver.resolve_and_prune([], existing, _FakeSettings())) == []


# --- recovery on re-mention -------------------------------------------------


def _page(memory: Path, entity_id: str, **fm) -> Path:
    ents = memory / "entities"
    ents.mkdir(parents=True, exist_ok=True)
    base = {
        "name": entity_id.title(),
        "type": "concept",
        "status": "active",
        "confidence": 0.5,
        "created": "2026-01-01",
        "last_referenced": "2026-01-01",
        "decay_rate": 0.05,
        "source_episodes": [],
        "tags": [],
        "related": [],
        "version": 1,
    }
    base.update(fm)
    path = ents / f"{entity_id}.md"
    markdown_parser.write(path, base, "## Summary\n\nA thing.")
    return path


def _update(entity_id: str) -> dict:
    return {
        "id": entity_id,
        "action": "update",
        "entity": {"name": entity_id.title(), "type": "concept"},
        "source_episode": "ep_2026-08-31_001",
    }


def test_a_decaying_entity_is_promoted_back_on_re_mention(tmp_path):
    path = _page(tmp_path, "salesforce", status="decaying", confidence=0.32)
    conflict_resolver.apply_changes([_update("salesforce")], tmp_path)
    fm = markdown_parser.parse(path).frontmatter
    assert fm["status"] == "active"
    assert fm["confidence"] == 0.6


def test_an_archived_entity_is_promoted_back_on_re_mention(tmp_path):
    path = _page(tmp_path, "postgres", status="archived", confidence=0.05)
    conflict_resolver.apply_changes([_update("postgres")], tmp_path)
    fm = markdown_parser.parse(path).frontmatter
    assert fm["status"] == "active"
    assert fm["confidence"] == 0.6


def test_recovery_never_lowers_a_confidence_that_is_already_higher(tmp_path):
    path = _page(tmp_path, "cicada", status="decaying", confidence=0.85)
    conflict_resolver.apply_changes([_update("cicada")], tmp_path)
    fm = markdown_parser.parse(path).frontmatter
    assert fm["status"] == "active"
    assert fm["confidence"] == 0.85


def test_a_dropped_entity_is_never_resurrected(tmp_path):
    path = _page(tmp_path, "banished", status="dropped", confidence=0.1)
    conflict_resolver.apply_changes([_update("banished")], tmp_path)
    fm = markdown_parser.parse(path).frontmatter
    assert fm["status"] == "dropped", "user-dismissed means never resurfaced"
    assert fm["confidence"] == 0.1


def test_an_active_entity_keeps_its_confidence_on_re_mention(tmp_path):
    path = _page(tmp_path, "steady", status="active", confidence=0.45)
    conflict_resolver.apply_changes([_update("steady")], tmp_path)
    fm = markdown_parser.parse(path).frontmatter
    assert fm["status"] == "active"
    assert fm["confidence"] == 0.45, "recovery only fires for decaying/archived pages"


# --------------------------------------------------------------------------- #
# Claim engine — the subject's class multiplies the per-claim decay rate
# --------------------------------------------------------------------------- #

from api.services import predicates  # noqa: E402
from api.services.claim_reconciler import reconcile_stage3  # noqa: E402
from api.services.claims import Claim  # noqa: E402


class _ClaimSettings:
    def __init__(self, memory_path):
        self.memory_path = memory_path
        self.litellm_model = "test-model"
        self.archive_threshold = 0.2
        self.decay_nudge_threshold = 0.4


def _open_claim(subject: str, cid: str) -> Claim:
    return Claim(
        id=cid,
        text=f"{subject} uses postgres",
        subject=subject,
        predicate="uses",
        object="postgres",
        observer="agent",
        context="general",
        epistemic="explicit",          # _DECAY_BASE 0.02
        source_trust="agent_extracted",  # _DECAY_FACTOR 1.0
        confidence=0.9,
        valid_from="2026-01-01",
        recorded_at="2026-01-01",
    )


def _decayed_confidence(tmp_path, cls_value: str) -> float:
    predicates.install_predicate_map(tmp_path)
    claim = _open_claim("subj", "clm_1")
    reconciled, _nudges, _audit = reconcile_stage3(
        [],
        {"subj": [claim]},
        _ClaimSettings(tmp_path),
        cardinality_fn=lambda _p: True,
        now_date="2026-04-01",  # 90 days ~ 12.857 weeks
        decay_class_fn=lambda _sid: DecayClass(cls_value),
    )
    return reconciled["subj"][0].confidence


def test_an_evergreen_subjects_claims_never_decay(tmp_path):
    assert _decayed_confidence(tmp_path, "evergreen") == 0.9


def test_a_volatile_subjects_claims_decay_twice_as_fast_as_an_active_one(tmp_path):
    active_drop = 0.9 - _decayed_confidence(tmp_path, "active")
    volatile_drop = 0.9 - _decayed_confidence(tmp_path, "volatile")
    durable_drop = 0.9 - _decayed_confidence(tmp_path, "durable")

    assert active_drop > 0
    assert abs(volatile_drop - 2 * active_drop) < 1e-9
    assert abs(durable_drop - 0.5 * active_drop) < 1e-9


def test_the_default_lookup_reads_the_subjects_page_when_none_is_injected(tmp_path):
    predicates.install_predicate_map(tmp_path)
    _page(tmp_path, "bookmarked", type="media")

    reconciled, _n, _a = reconcile_stage3(
        [],
        {"bookmarked": [_open_claim("bookmarked", "clm_2")]},
        _ClaimSettings(tmp_path),
        cardinality_fn=lambda _p: True,
        now_date="2026-04-01",
    )
    assert reconciled["bookmarked"][0].confidence == 0.9, (
        "the media page resolves to evergreen, so its claims must not decay"
    )


def test_a_subject_with_no_page_decays_at_the_neutral_active_rate(tmp_path):
    predicates.install_predicate_map(tmp_path)
    reconciled, _n, _a = reconcile_stage3(
        [],
        {"ghost": [_open_claim("ghost", "clm_3")]},
        _ClaimSettings(tmp_path),
        cardinality_fn=lambda _p: True,
        now_date="2026-04-01",
    )
    assert reconciled["ghost"][0].confidence == _decayed_confidence(tmp_path, "active")


# --------------------------------------------------------------------------- #
# G85 §2 / Wave-1 1.1 — decay must be charged ONCE per elapsed interval, not
# re-charged from the same anchor on every Sleep run. Entity engine first,
# claim engine second — both prove: (a) rerunning at the SAME reference time
# subtracts exactly zero the second time, and (b) a single run after N
# simulated days charges exactly N days' worth, not more.
# --------------------------------------------------------------------------- #


def test_entity_decay_rerun_at_the_same_instant_subtracts_zero(tmp_path):
    path = _page(
        tmp_path, "octo",
        status="active", confidence=0.85, decay_class="active",
        last_referenced="2026-06-01",  # 17 days before `now` below
    )
    now = datetime(2026, 6, 18, 15, 0, 0)

    existing = [{"id": "octo", "frontmatter": markdown_parser.parse(path).frontmatter, "body": "Body."}]
    changes = run(conflict_resolver.resolve_and_prune([], existing, _FakeSettings(), now=now))
    conflict_resolver.apply_changes(changes, tmp_path)
    fm_after_first = markdown_parser.parse(path).frontmatter
    conf_after_first = fm_after_first["confidence"]
    assert conf_after_first < 0.85, "some decay should have been charged for the elapsed gap"

    # Rerun at the EXACT same instant (the historical bug: zero elapsed time
    # between two Sleep cycles on 2026-06-18 still subtracted 0.378571... twice).
    existing_2 = [{"id": "octo", "frontmatter": fm_after_first, "body": "Body."}]
    changes_2 = run(conflict_resolver.resolve_and_prune([], existing_2, _FakeSettings(), now=now))
    conflict_resolver.apply_changes(changes_2, tmp_path)
    fm_after_second = markdown_parser.parse(path).frontmatter
    assert fm_after_second["confidence"] == conf_after_first, (
        "re-running decay with zero elapsed time must subtract zero the second time"
    )


def test_entity_decay_after_n_simulated_days_charges_exactly_n_days_once(tmp_path):
    path = _page(
        tmp_path, "steady-decay",
        status="active", confidence=0.85, decay_class="active",  # 0.05/wk
        last_referenced="2026-06-01",
    )
    day0 = datetime(2026, 6, 1)

    # Day 0: no time elapsed since last_referenced -> zero decay, but the
    # watermark still gets stamped to day0.
    existing = [{"id": "steady-decay", "frontmatter": markdown_parser.parse(path).frontmatter, "body": "Body."}]
    changes = run(conflict_resolver.resolve_and_prune([], existing, _FakeSettings(), now=day0))
    conflict_resolver.apply_changes(changes, tmp_path)
    fm_day0 = markdown_parser.parse(path).frontmatter
    assert fm_day0["confidence"] == 0.85
    assert fm_day0["decayed_through"] == "2026-06-01"

    # Day 14 (2 weeks later): should charge exactly 14 days = 2 weeks * 0.05 = 0.10,
    # NOT re-charge from `last_referenced` on top of an already-decayed value.
    day14 = datetime(2026, 6, 15)
    existing_2 = [{"id": "steady-decay", "frontmatter": fm_day0, "body": "Body."}]
    changes_2 = run(conflict_resolver.resolve_and_prune([], existing_2, _FakeSettings(), now=day14))
    conflict_resolver.apply_changes(changes_2, tmp_path)
    fm_day14 = markdown_parser.parse(path).frontmatter
    assert fm_day14["confidence"] == round(0.85 - 0.10, 10)


def test_claim_decay_rerun_at_the_same_instant_subtracts_zero(tmp_path):
    predicates.install_predicate_map(tmp_path)
    claim = _open_claim("subj2", "clm_10")
    claim.recorded_at = "2026-01-01"
    claim.valid_from = "2026-01-01"

    reconciled, _n, _a = reconcile_stage3(
        [], {"subj2": [claim]}, _ClaimSettings(tmp_path),
        cardinality_fn=lambda _p: True, now_date="2026-04-01",
        decay_class_fn=lambda _sid: DecayClass("active"),
    )
    conf_after_first = reconciled["subj2"][0].confidence
    assert conf_after_first < 0.9

    # Rerun at the SAME now_date over the output of the first run — the
    # historical bug re-anchored to `recorded_at` and subtracted the same
    # ~90-day span again.
    reconciled_2, _n2, _a2 = reconcile_stage3(
        [], {"subj2": reconciled["subj2"]}, _ClaimSettings(tmp_path),
        cardinality_fn=lambda _p: True, now_date="2026-04-01",
        decay_class_fn=lambda _sid: DecayClass("active"),
    )
    assert reconciled_2["subj2"][0].confidence == conf_after_first, (
        "re-running claim decay with zero elapsed time must subtract zero the second time"
    )


def test_claim_decay_after_n_simulated_days_charges_exactly_n_days_once(tmp_path):
    predicates.install_predicate_map(tmp_path)
    claim = _open_claim("subj3", "clm_11")
    claim.recorded_at = "2026-01-01"
    claim.valid_from = "2026-01-01"

    # Day 0: zero elapsed since recorded_at -> zero decay, watermark stamped.
    reconciled, _n, _a = reconcile_stage3(
        [], {"subj3": [claim]}, _ClaimSettings(tmp_path),
        cardinality_fn=lambda _p: True, now_date="2026-01-01",
        decay_class_fn=lambda _sid: DecayClass("active"),
    )
    day0_claim = reconciled["subj3"][0]
    assert day0_claim.confidence == 0.9
    assert day0_claim.decayed_through == "2026-01-01"

    # 7 days later: explicit epistemic (0.02 base) * agent_extracted (1.0) *
    # active multiplier (1.0) * (7/7) = 0.02 charged exactly once.
    reconciled_2, _n2, _a2 = reconcile_stage3(
        [], {"subj3": [day0_claim]}, _ClaimSettings(tmp_path),
        cardinality_fn=lambda _p: True, now_date="2026-01-08",
        decay_class_fn=lambda _sid: DecayClass("active"),
    )
    assert abs(reconciled_2["subj3"][0].confidence - (0.9 - 0.02)) < 1e-9
