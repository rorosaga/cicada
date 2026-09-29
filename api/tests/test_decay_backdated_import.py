"""A backdated import is not the person going silent (TODO ruling 1's corollary).

A first drain consolidates months-old exports over several cycles. A page a cycle
creates or references from an old episode keeps that date as its content date
(`last_referenced`), but silence is measured from the cycle that learned it —
`decayed_through` — so the following drain cycles charge nothing, while a page that
then really goes unmentioned decays from the cycle it was created.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from api.models.schemas import DecayClass
from api.services import conflict_resolver, markdown_parser, predicates
from api.services.claim_reconciler import reconcile_stage3
from api.services.claims import Claim


class _Settings:
    memory_path = None
    archive_threshold = 0.2
    decay_nudge_threshold = 0.4


def _run(coro):
    return asyncio.run(coro)


def _create(entity_id: str, episode_ts: str) -> dict:
    return {
        "id": entity_id, "action": "create",
        "entity": {"name": entity_id.title(), "type": "concept", "summary": "A thing.", "confidence": 0.7},
        "source_episode": "ep_old_001", "source_episode_timestamp": episode_ts,
        "trigger": "sleep/extraction",
    }


def _cycle(tmp_path, resolved: list[dict], now: datetime) -> None:
    """One Sleep cycle's Stage 3 + write over what is on disk."""
    (tmp_path / "entities").mkdir(exist_ok=True)
    existing = []
    for f in sorted((tmp_path / "entities").glob("*.md")):
        parsed = markdown_parser.parse(f)
        existing.append({"id": f.stem, "frontmatter": parsed.frontmatter, "body": parsed.body})
    changes = _run(conflict_resolver.resolve_and_prune(resolved, existing, _Settings(), now=now))
    conflict_resolver.apply_changes(changes, tmp_path)


def test_a_page_created_from_a_six_month_old_episode_survives_a_multi_cycle_drain(tmp_path):
    day = datetime(2026, 9, 28, 3, 0)
    _cycle(tmp_path, [_create("old-topic", "2026-03-20T10:00:00+00:00")], day)
    fm = markdown_parser.parse(tmp_path / "entities" / "old-topic.md").frontmatter
    # True content date kept for display; silence measured from this cycle.
    assert str(fm["last_referenced"]) == "2026-03-20" and str(fm["decayed_through"]) == "2026-09-28"

    for _ in range(6):  # the drain: back-to-back cycles working through the queue
        _cycle(tmp_path, [], day)
    fm = markdown_parser.parse(tmp_path / "entities" / "old-topic.md").frontmatter
    assert fm["confidence"] == 0.7 and fm["status"] == "active"


def test_a_page_unmentioned_after_creation_decays_from_the_cycle_it_was_created(tmp_path):
    created = datetime(2026, 9, 1, 3, 0)
    _cycle(tmp_path, [_create("quiet-topic", "2026-03-20T10:00:00+00:00")], created)
    # Two weeks later, one cycle at a time: exactly one week charged each (the cap),
    # measured from 2026-09-01 — not from March.
    _cycle(tmp_path, [], datetime(2026, 9, 8, 3, 0))
    fm = markdown_parser.parse(tmp_path / "entities" / "quiet-topic.md").frontmatter
    assert round(fm["confidence"], 10) == round(0.7 - 0.05, 10)
    assert str(fm["decayed_through"]) == "2026-09-08"
    _cycle(tmp_path, [], datetime(2026, 9, 15, 3, 0))
    fm = markdown_parser.parse(tmp_path / "entities" / "quiet-topic.md").frontmatter
    assert round(fm["confidence"], 10) == round(0.7 - 0.10, 10)


def test_a_re_mention_of_old_episodes_restarts_the_clock_and_never_moves_it_back(tmp_path):
    _cycle(tmp_path, [_create("seen-twice", "2026-03-20T10:00:00+00:00")], datetime(2026, 9, 20, 3, 0))
    update = {"id": "seen-twice", "action": "update", "entity": {"name": "Seen Twice", "type": "concept"},
              "source_episode": "ep_old_002", "source_episode_timestamp": "2026-04-02T10:00:00+00:00"}
    # A drain cycle on an earlier reference date than the page's watermark.
    _cycle(tmp_path, [update], datetime(2026, 9, 10, 3, 0))
    fm = markdown_parser.parse(tmp_path / "entities" / "seen-twice.md").frontmatter
    assert str(fm["decayed_through"]) == "2026-09-20"
    _cycle(tmp_path, [update], datetime(2026, 9, 25, 3, 0))
    fm = markdown_parser.parse(tmp_path / "entities" / "seen-twice.md").frontmatter
    assert str(fm["decayed_through"]) == "2026-09-25"


# --- claims ------------------------------------------------------------------


class _ClaimSettings:
    def __init__(self, memory_path):
        self.memory_path = memory_path
        self.litellm_model = "test-model"
        self.archive_threshold = 0.2
        self.decay_nudge_threshold = 0.4


def _stage1_claim(subject: str, cid: str, obj: str = "postgres") -> Claim:
    """A Stage-1 claim from a months-old episode: valid_from old, nothing recorded yet."""
    return Claim(
        id=cid, text=f"{subject} uses {obj}", subject=subject, predicate="uses", object=obj,
        observer="agent", context="general", epistemic="explicit", source_trust="agent_extracted",
        confidence=0.9, valid_from="2026-03-20", source_episodes=["ep_old_001"],
    )


def _reconcile(existing, incoming, today: str):
    return reconcile_stage3(
        incoming, existing, _ClaimSettings(None),
        cardinality_fn=lambda _p: False, now_date=today,
        decay_class_fn=lambda _sid: DecayClass("active"),
    )[0]


def test_a_claim_minted_from_an_old_episode_is_not_charged_by_the_following_drain_cycles():
    today = "2026-09-28"
    state = _reconcile({}, [_stage1_claim("subj", "clm_a")], today)
    (claim,) = state["subj"]
    assert claim.valid_from == "2026-03-20" and claim.decayed_through == today
    for _ in range(5):  # drain cycles that never mention subj again
        state = _reconcile(state, [_stage1_claim("other", "clm_b")], today)
    assert state["subj"][0].confidence == 0.9
    # A week of real silence after that charges from the cycle that learned it.
    state = _reconcile(state, [], "2026-10-05")
    assert abs(state["subj"][0].confidence - (0.9 - 0.02)) < 1e-9


def test_a_superseding_claim_from_an_old_episode_carries_the_watermark_too():
    today = "2026-09-28"
    state = _reconcile({}, [_stage1_claim("subj2", "clm_c", "postgres")], today)
    # Single-valued predicate: a newer claim (later episode) supersedes — the branch
    # that appends the incoming claim without `_stamp_new`.
    newer = _stage1_claim("subj2", "clm_d", "mysql")
    newer.valid_from = "2026-05-01"
    newer.source_trust = "user_stated"
    out = reconcile_stage3(
        [newer], state, _ClaimSettings(None), cardinality_fn=lambda _p: True, now_date=today,
        decay_class_fn=lambda _sid: DecayClass("active"),
    )[0]
    open_claims = [c for c in out["subj2"] if c.valid_to is None]
    assert open_claims and all(c.decayed_through == today for c in open_claims)
