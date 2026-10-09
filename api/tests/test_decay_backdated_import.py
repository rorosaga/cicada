"""A backdated import is charged its age once, by the cycle that reads it — never again (TODO ruling 1).

Owner ruling 2026-10-09 ("let age count") amended G170's "an import is not silence": a page created or referenced
from an old episode keeps that date as its content date (`last_referenced`) and fades from it. The silence between
that date and the day Cicada read it (`learned_on`) is charged in full by the decay pass of the run that read it;
after that, ruling 1's cap holds (at most a week per cycle). Undated claims keep their old anchor. The full rule's
tests are `test_decay_age_counts.py`.
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


def test_a_backdated_page_is_charged_its_age_once_and_never_again_the_same_day(tmp_path):
    day = datetime(2026, 9, 28, 3, 0)
    _cycle(tmp_path, [_create("old-topic", "2026-09-07T10:00:00+00:00")], day)
    fm = markdown_parser.parse(tmp_path / "entities" / "old-topic.md").frontmatter
    # Content date kept; three weeks of silence the episode proves, charged once.
    assert str(fm["last_referenced"]) == "2026-09-07" and str(fm["learned_on"]) == "2026-09-28"
    assert str(fm["decayed_through"]) == "2026-09-28"
    assert round(fm["confidence"], 10) == round(0.7 - 0.05 * 3, 10)

    for _ in range(6):  # more cycles the same day charge nothing more
        _cycle(tmp_path, [], day)
    fm = markdown_parser.parse(tmp_path / "entities" / "old-topic.md").frontmatter
    assert round(fm["confidence"], 10) == round(0.7 - 0.05 * 3, 10) and fm["status"] == "active"


def test_after_its_age_is_charged_a_page_decays_a_week_per_cycle(tmp_path):
    created = datetime(2026, 9, 1, 3, 0)
    _cycle(tmp_path, [_create("quiet-topic", "2026-08-25T10:00:00+00:00")], created)
    fm = markdown_parser.parse(tmp_path / "entities" / "quiet-topic.md").frontmatter
    assert round(fm["confidence"], 10) == round(0.7 - 0.05, 10)
    # Two weeks later, one cycle at a time: exactly one week charged each (the cap).
    _cycle(tmp_path, [], datetime(2026, 9, 8, 3, 0))
    fm = markdown_parser.parse(tmp_path / "entities" / "quiet-topic.md").frontmatter
    assert round(fm["confidence"], 10) == round(0.7 - 0.10, 10)
    assert str(fm["decayed_through"]) == "2026-09-08"
    _cycle(tmp_path, [], datetime(2026, 9, 15, 3, 0))
    fm = markdown_parser.parse(tmp_path / "entities" / "quiet-topic.md").frontmatter
    assert round(fm["confidence"], 10) == round(0.7 - 0.15, 10)


def test_an_older_re_mention_moves_no_clock(tmp_path):
    _cycle(tmp_path, [_create("seen-twice", "2026-09-15T10:00:00+00:00")], datetime(2026, 9, 20, 3, 0))
    update = {"id": "seen-twice", "action": "update", "entity": {"name": "Seen Twice", "type": "concept"},
              "source_episode": "ep_old_002", "source_episode_timestamp": "2026-04-02T10:00:00+00:00"}
    _cycle(tmp_path, [update], datetime(2026, 9, 25, 3, 0))
    fm = markdown_parser.parse(tmp_path / "entities" / "seen-twice.md").frontmatter
    # Age counts from when it was said: the April mention is older than the page's last one.
    assert str(fm["last_referenced"]) == "2026-09-15" and str(fm["learned_on"]) == "2026-09-20"
    assert str(fm["decayed_through"]) == "2026-09-20"


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


def test_an_undated_claim_keeps_its_old_anchor_through_the_following_drain_cycles():
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


def test_a_superseding_undated_claim_carries_the_watermark_too():
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
