"""Age counts from when it was said (owner ruling 2026-10-09, amending G170's "an import is not silence").

A page or claim fades from the day it was last said. The silence between that day and the day Cicada read it is
proven by the conversations themselves, so the decay pass of the run that read it charges it in full, once; only the
time after that is ruling 1's capped, live silence. Nothing is charged mid-drain, so the order conversations are read
in and where batches break never change the result. Synthetic pages only.
"""

from __future__ import annotations

import asyncio
import math
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from api.models.schemas import DecayClass
from api.services import conflict_resolver, decay_policy, markdown_parser
from api.services.claim_reconciler import reconcile_stage3
from api.services.claims import Claim

TODAY = datetime(2026, 10, 9, 3, 0)


class _Settings:
    archive_threshold = 0.2
    decay_nudge_threshold = 0.4

    def __init__(self, memory_path: Path):
        self.memory_path = memory_path


def _bank(tmp_path: Path) -> Path:
    (tmp_path / "entities").mkdir(parents=True, exist_ok=True)
    (tmp_path / "episodes").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _change(entity_id: str, action: str, *days: str, confidence: float = 0.9, kind: str = "concept",
            untimed: bool = False) -> dict:
    episodes = [f"ep_{d}_001" for d in days]
    entity = {"name": entity_id.replace("-", " ").title(), "type": kind}
    if action == "create":
        entity.update({"summary": "A synthetic thing.", "confidence": confidence})
    return {
        "id": entity_id, "action": action, "entity": entity,
        "source_episode": episodes[-1], "source_episodes": episodes,
        "source_episode_timestamps": [f"{d}T10:00:00+00:00" for d in days],
        "trigger": "sleep/extraction", **({"untimed": True} if untimed else {}),
    }


def _batch(bank: Path, resolved: list[dict], *, decay: bool, now: datetime = TODAY) -> list[dict]:
    """One Sleep batch: Stage 3 over what is on disk, then the writes. Returns Stage 3's changes."""
    existing = []
    for f in sorted((bank / "entities").glob("*.md")):
        parsed = markdown_parser.parse(f)
        existing.append({"id": f.stem, "frontmatter": parsed.frontmatter, "body": parsed.body})
    changes = asyncio.run(conflict_resolver.resolve_and_prune(
        resolved, existing, _Settings(bank), now=now, decay=decay, tuning={}))
    conflict_resolver.apply_changes(changes, bank)
    return changes


def _drain(bank: Path, batches: list[list[dict]], *, now: datetime = TODAY) -> list[dict]:
    """A drain: decay only in the batch that empties the queue (TODO ruling 1 / ruling 13)."""
    out: list[dict] = []
    for i, resolved in enumerate(batches):
        out = _batch(bank, resolved, decay=i == len(batches) - 1, now=now)
    return out


def _fm(bank: Path, entity_id: str) -> dict:
    return markdown_parser.parse(bank / "entities" / f"{entity_id}.md").frontmatter


def _weeks(a: str, b: str) -> float:
    return (datetime.fromisoformat(b) - datetime.fromisoformat(a)).days / 7.0


def _f(weeks: int) -> float:
    return decay_policy.stability(weeks)


# --- pages -------------------------------------------------------------------


def test_a_one_conversation_page_from_2024_is_archived_on_the_day_it_is_read(tmp_path):
    bank = _bank(tmp_path)
    changes = _drain(bank, [
        [_change("old-script", "create", "2024-03-05")],
        [_change("fresh-topic", "create", "2026-10-08")],
        [],   # the batch that empties the queue: decay runs once, here
    ])
    fm = _fm(bank, "old-script")
    assert fm["status"] == "archived" and fm["confidence"] < 0.2
    assert str(fm["last_referenced"]) == "2024-03-05" and str(fm["learned_on"]) == "2026-10-09"
    # Still a page: archived pages stay in entities/ and recall finds them, ranked last.
    assert (bank / "entities" / "old-script.md").exists()
    # Heard late: archived without a question.
    assert not any(c.get("action") == "decay_nudge" for c in changes)
    # The fresh one is untouched by age.
    assert _fm(bank, "fresh-topic")["status"] == "active"


def test_a_plain_cycle_that_reads_an_old_conversation_settles_it_the_same_day(tmp_path):
    bank = _bank(tmp_path)
    _batch(bank, [_change("old-script", "create", "2024-03-05")], decay=True)
    fm = _fm(bank, "old-script")
    assert fm["status"] == "archived" and str(fm["decayed_through"]) == "2026-10-09"


def test_a_three_month_old_one_off_fades_into_decaying_without_a_question(tmp_path):
    bank = _bank(tmp_path)
    changes = _drain(bank, [[_change("quarter-old", "create", "2026-07-17")], []])
    fm = _fm(bank, "quarter-old")
    expected = 0.9 - 0.05 * _weeks("2026-07-17", "2026-10-09")
    assert 0.2 <= expected < 0.4
    assert math.isclose(fm["confidence"], expected, abs_tol=1e-9) and fm["status"] == "decaying"
    assert not any(c.get("action") == "decay_nudge" for c in changes)


@pytest.mark.parametrize("layout", ["old_first", "new_first", "same_batch", "new_in_last_batch"])
def test_said_in_2024_and_again_in_2026_ends_the_drain_alive_whatever_the_order(tmp_path, layout):
    bank = _bank(tmp_path)
    old, new = "2024-05-14", "2026-09-20"
    batches = {
        "old_first": [[_change("topic", "create", old)], [_change("topic", "update", new)], []],
        "new_first": [[_change("topic", "create", new)], [_change("topic", "update", old)], []],
        "same_batch": [[_change("topic", "create", old, new)]],
        "new_in_last_batch": [[_change("topic", "create", old)], [], [_change("topic", "update", new)]],
    }[layout]
    _drain(bank, batches)
    fm = _fm(bank, "topic")
    # Two weeks it came up in; silent since the 2026 mention, charged in full and nothing more.
    expected = 0.9 - 0.05 * _f(2) * _weeks(new, "2026-10-09")
    assert fm["status"] == "active"
    assert math.isclose(fm["confidence"], expected, abs_tol=1e-9)
    assert str(fm["last_referenced"]) == new and str(fm["decayed_through"]) == "2026-10-09"


def test_twelve_weeks_of_mentions_fade_slower_than_one(tmp_path):
    bank = _bank(tmp_path)
    weekly = [f"2025-{m:02d}-{d:02d}" for m, d in [(9, 8), (9, 15), (9, 22), (9, 29), (10, 6), (10, 13), (10, 20),
                                                  (10, 27), (11, 3), (11, 10), (11, 17), (11, 24)]]
    now = datetime(2026, 4, 13, 3, 0)   # twenty weeks after the last mention
    _drain(bank, [[_change("spaced", "create", *weekly), _change("once", "create", weekly[-1])], []], now=now)
    spaced, once = _fm(bank, "spaced"), _fm(bank, "once")
    weeks = _weeks(weekly[-1], "2026-04-13")
    assert math.isclose(spaced["confidence"], 0.9 - 0.05 * _f(12) * weeks, abs_tol=1e-9)
    assert spaced["status"] == "active"
    assert once["status"] == "archived"


def test_an_evergreen_page_never_fades(tmp_path):
    bank = _bank(tmp_path)
    _drain(bank, [[_change("saved-article", "create", "2024-03-05", kind="media")], []])
    fm = _fm(bank, "saved-article")
    assert fm["decay_class"] == DecayClass.evergreen.value
    assert fm["confidence"] == 0.9 and fm["status"] == "active"


def test_the_owners_page_is_unaffected(tmp_path):
    bank = _bank(tmp_path)
    markdown_parser.write(bank / "entities" / "owner-example.md", {
        "name": "Owner Example", "type": "person", "owner": True, "status": "active", "confidence": 1.0,
        "created": "2026-10-01", "last_referenced": "2026-10-01", "decayed_through": "2026-10-01",
        **decay_policy.frontmatter_fields(DecayClass.evergreen), "source_episodes": [],
    }, "## Summary\n\nThe person this bank belongs to.\n")
    before = _fm(bank, "owner-example")
    _drain(bank, [[_change("owner-example", "update", "2024-03-05")], [], []])
    after = _fm(bank, "owner-example")
    assert after["confidence"] == 1.0 and after["status"] == "active"
    assert str(after["last_referenced"]) == str(before["last_referenced"])   # an older mention moves nothing


def test_a_memory_export_only_page_keeps_its_rule(tmp_path):
    bank = _bank(tmp_path)
    markdown_parser.write(bank / "episodes" / "ep_2024-05-01_001.md",
                          {"id": "ep_2024-05-01_001", "source": "claude_memory", "processed": True}, "Facts.\n")
    _drain(bank, [[_change("export-fact", "create", "2024-05-01", untimed=True)], []])
    fm = _fm(bank, "export-fact")
    # No mention, so no last mention and no age: the clock starts the day Cicada learned it.
    assert "last_referenced" not in fm and "learned_on" not in fm
    assert fm["confidence"] == 0.9 and str(fm["decayed_through"]) == "2026-10-09"
    # A month later: ruling 1's one week, nothing more.
    _batch(bank, [], decay=True, now=datetime(2026, 11, 9, 3, 0))
    fm = _fm(bank, "export-fact")
    assert math.isclose(fm["confidence"], 0.9 - 0.05, abs_tol=1e-9)
    assert str(fm["decayed_through"]) == "2026-10-16"


def test_a_live_page_is_still_charged_at_most_a_week_per_cycle(tmp_path):
    bank = _bank(tmp_path)
    _batch(bank, [_change("live", "create", "2026-09-01")], decay=True, now=datetime(2026, 9, 1, 3, 0))
    fm = _fm(bank, "live")
    assert fm["confidence"] == 0.9 and str(fm["decayed_through"]) == "2026-09-01"
    # A month with no cycle (an outage): one week charged, the rest worked off later (TODO ruling 1).
    _batch(bank, [], decay=True, now=datetime(2026, 10, 1, 3, 0))
    fm = _fm(bank, "live")
    assert math.isclose(fm["confidence"], 0.85, abs_tol=1e-9) and str(fm["decayed_through"]) == "2026-09-08"


def test_a_live_page_that_goes_quiet_is_still_asked_about(tmp_path):
    bank = _bank(tmp_path)
    _batch(bank, [_change("live", "create", "2026-09-01", confidence=0.42)], decay=True,
           now=datetime(2026, 9, 1, 3, 0))
    changes = _batch(bank, [], decay=True, now=datetime(2026, 9, 8, 3, 0))
    assert [c["action"] for c in changes if c["id"] == "live"] == ["decay_nudge"]


def test_a_later_mention_revives_and_an_old_one_fades_back(tmp_path):
    bank = _bank(tmp_path)
    _drain(bank, [[_change("revived", "create", "2024-03-05"), _change("not-revived", "create", "2024-03-05")], []])
    assert _fm(bank, "revived")["status"] == "archived" and _fm(bank, "not-revived")["status"] == "archived"
    _drain(bank, [[_change("revived", "update", "2026-10-09"), _change("not-revived", "update", "2024-06-11")], []])
    revived = _fm(bank, "revived")
    assert revived["status"] == "active" and revived["confidence"] == 0.6
    # An old conversation read late never revives — but it makes the one-off a repeat: the repeat floor, dimmed.
    old_again = _fm(bank, "not-revived")
    assert old_again["status"] == "decaying" and math.isclose(old_again["confidence"], 0.39, abs_tol=1e-9)


# --- claims ------------------------------------------------------------------


class _ClaimSettings:
    memory_path = None
    litellm_model = "test-model"
    archive_threshold = 0.2
    decay_nudge_threshold = 0.4


def _claim(cid: str, day: str, subject: str = "topic", conf: float = 0.9) -> Claim:
    return Claim(
        id=cid, text=f"{subject} uses postgres", subject=subject, predicate="uses", object="postgres",
        observer="agent", context="general", epistemic="explicit", source_trust="agent_extracted",
        confidence=conf, valid_from=day, source_episodes=[f"ep_{day}_001"],
    )


def _reconcile(state, incoming, *, decay: bool, today: str = "2026-10-09"):
    return reconcile_stage3(
        incoming, state, _ClaimSettings(), cardinality_fn=lambda _p: False, now_date=today,
        decay_class_fn=lambda _sid: DecayClass.active, decay=decay,
    )


def test_a_claim_said_in_2024_fades_by_its_age_in_the_drain_that_reads_it_without_a_question():
    state, _, _ = _reconcile({}, [_claim("clm_a", "2024-03-05")], decay=False)
    state, nudges, _ = _reconcile(state, [], decay=True)
    (claim,) = state["topic"]
    assert claim.confidence == 0.0 and claim.decayed_through == "2026-10-09"
    assert not [n for n in nudges if n.get("action") == "decay_nudge"]


def test_a_claim_read_in_the_last_batch_is_settled_too():
    state, _, _ = _reconcile({}, [_claim("clm_a", "2026-07-03")], decay=True)
    (claim,) = state["topic"]
    expected = 0.9 - 0.02 * _weeks("2026-07-03", "2026-10-09")
    assert math.isclose(claim.confidence, expected, abs_tol=1e-9)


@pytest.mark.parametrize("order", ["old_first", "new_first"])
def test_a_claim_restated_in_2026_ends_the_drain_the_same_whatever_the_order(order):
    old, new = _claim("clm_old", "2024-05-14"), _claim("clm_new", "2026-09-20")
    first, second = (old, new) if order == "old_first" else (new, old)
    state, _, _ = _reconcile({}, [first], decay=False)
    state, _, _ = _reconcile(state, [second], decay=False)
    state, _, _ = _reconcile(state, [], decay=True)
    (claim,) = state["topic"]
    expected = 0.9 - 0.02 * _f(2) * _weeks("2026-09-20", "2026-10-09")
    assert math.isclose(claim.confidence, expected, abs_tol=1e-9)
    assert claim.decayed_through == "2026-10-09"


def test_a_claim_said_today_is_not_charged():
    state, _, _ = _reconcile({}, [_claim("clm_live", "2026-10-09")], decay=True)
    assert state["topic"][0].confidence == 0.9


def test_an_old_restatement_read_late_lets_a_faded_claim_fade_back_but_a_live_write_revives_it():
    state, _, _ = _reconcile({}, [_claim("clm_a", "2024-03-05", conf=0.5)], decay=True)
    assert state["topic"][0].confidence == 0.0
    # An older conversation read today never revives it — but it makes it a repeat: the repeat floor.
    old_again, _, _ = _reconcile({k: [*v] for k, v in state.items()}, [_claim("clm_b", "2024-02-01")], decay=True)
    assert math.isclose(old_again["topic"][0].confidence, 0.39, abs_tol=1e-9)
    # An agent's live write (no conversation id) is said now: the raise stands.
    live = _claim("clm_c", "2026-10-09")
    live.source_episodes = []
    revived, _, _ = _reconcile(state, [live], decay=True)
    assert revived["topic"][0].confidence == 0.9



# --- owner 2026-10-09: one-offs archive, repeats fade --------------------------


def _live_passes(bank, page_id, start, days):
    """Daily decay passes; returns (the actions raised for the page, the day it archived or None)."""
    actions, archived, day = [], None, start
    for _ in range(days):
        changes = _batch(bank, [], decay=True, now=day)
        actions += [c["action"] for c in changes if c["id"] == page_id]
        if archived is None and _fm(bank, page_id)["status"] == "archived":
            archived = day
        day += timedelta(days=1)
    return actions, archived


def test_a_page_from_two_old_conversations_fades_dimmed_and_archives_only_by_live_silence(tmp_path):
    bank = _bank(tmp_path)
    _drain(bank, [[_change("repeat", "create", "2024-03-05")], [_change("repeat", "update", "2024-04-02")], []])
    fm = _fm(bank, "repeat")
    floor = decay_policy.proven_floor(0.4)
    assert floor == pytest.approx(0.39)
    assert fm["status"] == "decaying" and math.isclose(fm["confidence"], floor, abs_tol=1e-9)
    # Stays on the graph, dimmed, through real silence; archives at the normal live pace — never asked.
    actions, archived = _live_passes(bank, "repeat", datetime(2026, 10, 10, 3, 0), 60)
    assert archived is not None
    expected_days = (floor - 0.2) / (0.05 * _f(2)) * 7
    assert abs((archived - TODAY).days - expected_days) <= 1.5
    assert "decay_nudge" not in actions


def test_a_one_off_faded_by_its_age_is_never_asked_as_live_silence_continues(tmp_path):
    bank = _bank(tmp_path)
    _drain(bank, [[_change("quarter-old", "create", "2026-07-17")], []])
    assert _fm(bank, "quarter-old")["status"] == "decaying"
    actions, archived = _live_passes(bank, "quarter-old", datetime(2026, 10, 10, 3, 0), 40)
    assert archived is not None and "decay_nudge" not in actions


def test_a_page_revived_after_fading_by_age_is_asked_when_it_crosses_again(tmp_path):
    bank = _bank(tmp_path)
    _drain(bank, [[_change("quarter-old", "create", "2026-07-17")], []])
    _drain(bank, [[_change("quarter-old", "update", "2026-10-10")]], now=datetime(2026, 10, 10, 3, 0))
    assert _fm(bank, "quarter-old")["confidence"] == 0.6
    actions, _ = _live_passes(bank, "quarter-old", datetime(2026, 10, 11, 3, 0), 40)
    assert "decay_nudge" in actions


def test_a_memory_export_entry_is_not_a_second_conversation(tmp_path):
    bank = _bank(tmp_path)
    markdown_parser.write(bank / "episodes" / "ep_2024-05-01_001.md",
                          {"id": "ep_2024-05-01_001", "source": "claude_memory", "processed": True}, "Facts.\n")
    _drain(bank, [[_change("one-off", "create", "2024-03-05")],
                  [_change("one-off", "update", "2024-05-01", untimed=True)], []])
    assert _fm(bank, "one-off")["status"] == "archived"


def test_a_claim_restated_in_two_old_conversations_floors_where_a_page_would():
    a, b = _claim("clm_a", "2024-03-05"), _claim("clm_b", "2024-04-02")
    state, _, _ = _reconcile({}, [a], decay=False)
    state, _, _ = _reconcile(state, [b], decay=True)
    assert math.isclose(state["topic"][0].confidence, decay_policy.proven_floor(0.4), abs_tol=1e-9)
    single, _, _ = _reconcile({}, [_claim("clm_c", "2024-03-05", subject="other")], decay=True)
    assert single["other"][0].confidence == 0.0


# --- blocker 1: heard late is quiet only in the pass its age is charged -------


def test_a_page_read_late_is_still_asked_about_when_live_silence_takes_it_below_0_4(tmp_path):
    bank = _bank(tmp_path)
    _batch(bank, [_change("alpha-project", "create", "2026-08-01")], decay=True, now=datetime(2026, 8, 12, 3, 0))
    day, asked = datetime(2026, 8, 13, 3, 0), None
    while day < datetime(2027, 3, 1) and asked is None:
        changes = _batch(bank, [], decay=True, now=day)
        if any(c["id"] == "alpha-project" and c["action"] == "decay_nudge" for c in changes):
            asked = day
        assert _fm(bank, "alpha-project")["status"] != "archived" or asked, "archived without ever asking"
        day += timedelta(days=1)
    assert asked is not None and asked.date().isoformat() < "2026-10-20"


def test_a_claim_read_late_is_still_asked_about_when_live_silence_takes_it_below_0_4():
    state, _, _ = _reconcile({}, [_claim("clm_a", "2026-08-01")], decay=True, today="2026-08-12")
    day, asked = datetime(2026, 8, 13), False
    while day < datetime(2027, 6, 1) and not asked:
        state, nudges, _ = _reconcile(state, [], decay=True, today=day.date().isoformat())
        asked = any(n.get("action") == "decay_nudge" for n in nudges)
        day += timedelta(days=1)
    assert asked


# --- blocker 2: a mention never lowers a page or claim ------------------------


def _decaying_bob(bank):
    _batch(bank, [_change("bob-example", "create", "2026-06-01")], decay=True, now=datetime(2026, 6, 1, 3, 0))
    day = datetime(2026, 6, 2, 3, 0)
    while day <= datetime(2026, 8, 12, 3, 0):
        _batch(bank, [], decay=True, now=day)
        day += timedelta(days=1)
    fm = _fm(bank, "bob-example")
    assert fm["status"] == "decaying" and fm["confidence"] < 0.4
    return fm


@pytest.mark.parametrize("said", ["2026-06-01", "2026-06-02"])
@pytest.mark.parametrize("mid_drain", [False, True])
def test_an_old_re_mention_never_lowers_a_decaying_page(tmp_path, said, mid_drain):
    bank = _bank(tmp_path)
    before = _decaying_bob(bank)
    now = datetime(2026, 8, 12, 3, 0)
    batches = [[_change("bob-example", "update", said)], []] if mid_drain else [[_change("bob-example", "update", said)]]
    _drain(bank, batches, now=now)
    after = _fm(bank, "bob-example")
    assert after["confidence"] >= before["confidence"] and after["status"] in ("decaying", "active")


def test_a_new_mention_revives_a_decaying_page(tmp_path):
    bank = _bank(tmp_path)
    _decaying_bob(bank)
    _drain(bank, [[_change("bob-example", "update", "2026-08-12")], []], now=datetime(2026, 8, 12, 3, 0))
    fm = _fm(bank, "bob-example")
    assert fm["status"] == "active" and fm["confidence"] == 0.6


@pytest.mark.parametrize("said", ["2026-06-01", "2026-06-02"])
def test_an_old_restatement_never_lowers_a_claim(said):
    state, _, _ = _reconcile({}, [_claim("clm_a", "2026-06-01", conf=0.45)], decay=True, today="2026-06-01")
    day = datetime(2026, 6, 2)
    while day <= datetime(2026, 8, 12):
        state, _, _ = _reconcile(state, [], decay=True, today=day.date().isoformat())
        day += timedelta(days=1)
    before = state["topic"][0].confidence
    state, _, _ = _reconcile(state, [_claim("clm_b", said, conf=0.5)], decay=False, today="2026-08-12")
    state, _, _ = _reconcile(state, [], decay=True, today="2026-08-12")
    assert state["topic"][0].confidence >= before


def test_a_claim_faded_by_its_age_is_never_asked_as_live_silence_continues():
    state, nudges, _ = _reconcile({}, [_claim("clm_a", "2026-03-15")], decay=True)
    assert 0.2 < state["topic"][0].confidence < 0.4 and not nudges
    day, asked = datetime(2026, 10, 10), False
    while day < datetime(2027, 6, 1):
        state, nudges, _ = _reconcile(state, [], decay=True, today=day.date().isoformat())
        asked = asked or any(n.get("action") == "decay_nudge" for n in nudges)
        day += timedelta(days=1)
    assert not asked


# --- the floor holds however imports split across runs -------------------------


def _same_and_split_pages(tmp_path):
    same, split = _bank(tmp_path / "same"), _bank(tmp_path / "split")
    _drain(same, [[_change("alpha-project", "create", "2024-03-05")],
                  [_change("alpha-project", "update", "2024-04-02")], []])
    _batch(split, [_change("alpha-project", "create", "2024-03-05")], decay=True)
    assert _fm(split, "alpha-project")["status"] == "archived"
    _batch(split, [_change("alpha-project", "update", "2024-04-02")], decay=True, now=datetime(2026, 10, 10, 3, 0))
    return same, split


def test_a_second_old_conversation_in_a_later_run_lifts_a_one_off_to_the_repeat_floor(tmp_path):
    same, split = _same_and_split_pages(tmp_path)
    lifted = _fm(split, "alpha-project")
    # The floor less the one live day since its age was settled.
    assert lifted["status"] == "decaying"
    assert math.isclose(lifted["confidence"], 0.39 - 0.05 * _f(2) / 7, abs_tol=1e-9)
    assert len(lifted["source_episodes"]) == 2
    _daily(same, datetime(2026, 10, 10, 3, 0), datetime(2026, 10, 20, 3, 0))
    _daily(split, datetime(2026, 10, 11, 3, 0), datetime(2026, 10, 20, 3, 0))
    a, b = _fm(same, "alpha-project"), _fm(split, "alpha-project")
    assert math.isclose(a["confidence"], b["confidence"], abs_tol=1e-9) and a["status"] == b["status"] == "decaying"
    assert str(a["decayed_through"]) == str(b["decayed_through"])


def test_a_second_old_restatement_in_a_later_run_lifts_a_claim_to_the_repeat_floor():
    same, _, _ = _reconcile({}, [_claim("clm_a", "2024-03-05")], decay=False)
    same, _, _ = _reconcile(same, [_claim("clm_b", "2024-04-02")], decay=True)
    split, _, _ = _reconcile({}, [_claim("clm_a", "2024-03-05")], decay=True)
    assert split["topic"][0].confidence == 0.0
    split, _, _ = _reconcile(split, [_claim("clm_b", "2024-04-02")], decay=True, today="2026-10-10")
    assert math.isclose(split["topic"][0].confidence, 0.39 - 0.02 * _f(2) / 7, abs_tol=1e-9)
    same, _, _ = _reconcile(same, [], decay=True, today="2026-10-10")
    for n in range(11, 21):
        same, _, _ = _reconcile(same, [], decay=True, today=f"2026-10-{n}")
        split, _, _ = _reconcile(split, [], decay=True, today=f"2026-10-{n}")
    assert math.isclose(same["topic"][0].confidence, split["topic"][0].confidence, abs_tol=1e-9)


# --- a capture read late, after the last charge, is charged its gap once ------


def _live_page(bank, confidence=0.9):
    _batch(bank, [_change("live", "create", "2026-07-01", confidence=confidence)], decay=True,
           now=datetime(2026, 7, 1, 3, 0))
    day = datetime(2026, 7, 2, 3, 0)
    while day <= datetime(2026, 7, 10, 3, 0):
        _batch(bank, [], decay=True, now=day)
        day += timedelta(days=1)
    return _fm(bank, "live")


def test_a_capture_read_late_after_the_last_charge_never_lowers_an_active_page(tmp_path):
    bank = _bank(tmp_path)
    before = _live_page(bank, confidence=0.5)
    assert before["status"] == "active" and str(before["decayed_through"]) == "2026-07-10"
    _drain(bank, [[_change("live", "update", "2026-07-15")], []])
    fm = _fm(bank, "live")
    # Its clock restarts when it was said; the gap until it was read never takes it below where it stood.
    assert math.isclose(fm["confidence"], before["confidence"], abs_tol=1e-9) and fm["status"] == "active"
    assert str(fm["decayed_through"]) == "2026-10-09" and str(fm["last_referenced"]) == "2026-07-15"
    assert "confidence_before_mention" not in fm
    _batch(bank, [], decay=True, now=datetime(2026, 10, 10, 3, 0))   # the gap is settled: one live day next
    expected = before["confidence"] - 0.05 * _f(2) / 7
    assert math.isclose(_fm(bank, "live")["confidence"], expected, abs_tol=1e-9)


def test_a_late_capture_on_an_evergreen_page_leaves_no_mention_floor(tmp_path):
    bank = _bank(tmp_path)
    _batch(bank, [_change("saved", "create", "2026-07-01", kind="media")], decay=True, now=datetime(2026, 7, 1, 3, 0))
    _batch(bank, [], decay=True, now=datetime(2026, 7, 10, 3, 0))
    _drain(bank, [[_change("saved", "update", "2026-07-15")], []])
    assert "confidence_before_mention" not in _fm(bank, "saved")


def test_a_late_capture_that_revives_a_page_never_leaves_it_below_where_it_stood(tmp_path):
    bank = _bank(tmp_path)
    before = _live_page(bank, confidence=0.45)
    day = datetime(2026, 7, 11, 3, 0)
    while _fm(bank, "live")["status"] != "decaying":
        _batch(bank, [], decay=True, now=day)
        day += timedelta(days=1)
    before = _fm(bank, "live")
    _drain(bank, [[_change("live", "update", (day - timedelta(days=1)).date().isoformat())], []],
           now=datetime(2026, 12, 20, 3, 0))
    after = _fm(bank, "live")
    assert after["confidence"] >= before["confidence"] and after["status"] != "archived"


def _daily(bank, start, end):
    day = start
    while day <= end:
        _batch(bank, [], decay=True, now=day)
        day += timedelta(days=1)


@pytest.mark.parametrize("second_read", ["2026-10-23", "2026-12-01"])
def test_a_second_old_conversation_weeks_later_lands_where_one_run_would_have(tmp_path, second_read):
    same, split = _bank(tmp_path / "same"), _bank(tmp_path / "split")
    read = datetime.fromisoformat(second_read + "T03:00:00")
    _drain(same, [[_change("alpha-project", "create", "2024-03-05")],
                  [_change("alpha-project", "update", "2024-04-02")], []])
    _daily(same, datetime(2026, 10, 10, 3, 0), read)
    _batch(split, [_change("alpha-project", "create", "2024-03-05")], decay=True)
    _daily(split, datetime(2026, 10, 10, 3, 0), read - timedelta(days=1))
    _batch(split, [_change("alpha-project", "update", "2024-04-02")], decay=True, now=read)
    a, b = _fm(same, "alpha-project"), _fm(split, "alpha-project")
    assert a["status"] == b["status"]
    if a["status"] != "archived":
        assert math.isclose(a["confidence"], b["confidence"], abs_tol=1e-9)
    else:
        assert b["confidence"] < 0.2


def test_a_second_old_restatement_weeks_later_lands_a_claim_where_one_run_would_have():
    same, _, _ = _reconcile({}, [_claim("clm_a", "2024-03-05")], decay=False)
    same, _, _ = _reconcile(same, [_claim("clm_b", "2024-04-02")], decay=True)
    split, _, _ = _reconcile({}, [_claim("clm_a", "2024-03-05")], decay=True)
    day = datetime(2026, 10, 10)
    while day < datetime(2026, 12, 1):
        same, _, _ = _reconcile(same, [], decay=True, today=day.date().isoformat())
        split, _, _ = _reconcile(split, [], decay=True, today=day.date().isoformat())
        day += timedelta(days=1)
    same, _, _ = _reconcile(same, [], decay=True, today="2026-12-01")
    split, _, _ = _reconcile(split, [_claim("clm_b", "2024-04-02")], decay=True, today="2026-12-01")
    assert math.isclose(same["topic"][0].confidence, split["topic"][0].confidence, abs_tol=1e-9)
    assert same["topic"][0].confidence < 0.39
