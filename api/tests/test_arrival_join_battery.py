"""The arrival join's regression net (`benchmarks/consolidation/arrival_join_battery.py`): every hand-written trap answers what it
says (real scratch banks, the real `gather` and `decide`, no model), nothing joins that must not across 2,000 generated scenes,
and the net itself is checked: the traps cover what the plan's 3.8 names, and a deliberately broken rule fails it. The scenes
measure the rule against its author's picture of the world; the bar before a join writes is the coordinator's reading of a real
bank. Names invented."""
from __future__ import annotations

import pytest

from benchmarks.consolidation import arrival_join_battery as battery


@pytest.mark.slow
def test_every_trap_answers_what_it_says_and_none_joins_that_must_not():
    result = battery.run_traps()
    assert result["failed"] == [], result["failed"]
    assert result["wrong_joins"] == 0 and result["traps"] == result["ok"]


def test_the_traps_cover_what_the_plan_names():
    ids = " ".join(t.id for t in battery.traps())
    for named in ("two-connections", "connection-and-card", "known-full-name", "second-held", "day-7", "day-8", "week-precision",
                  "month-precision", "fuzzy-namesake", "first-mention-untimed", "page-first-said-months-earlier",
                  "old-note-edited", "living-note", "owner-given-name", "relation-titled", "role-word", "same-name-doubt",
                  "split-pair", "undo-then-rerun", "page-names-another-profile", "arrival-already-a-page", "stale-directory",
                  "two-linkless", "non-ascii", "plain-word", "company-conflict", "dormant-old-namesake", "namesake-20-days"):
        assert named in ids, named
    assert len({t.id for t in battery.traps()}) == len(battery.traps())


def test_no_scene_joins_wrongly_and_none_is_missed_across_two_thousand():
    result = battery.run_scenes(2000, seed=7)
    assert result["false_joins"] == 0 and result["missed_joins"] == 0, result["examples"]
    assert result["joined"] > 100 and result["joined"] == result["should_join"]       # the net exercises the joining path too


@pytest.mark.slow
def test_the_net_catches_a_rule_that_was_loosened(monkeypatch):
    """Widen the window to eight days and the day-8 trap, and some scenes, must fail: a net that cannot fail is no net."""
    from api.services import arrival_join as aj

    monkeypatch.setattr(aj, "WINDOW_DAYS", 8)
    assert battery.run_traps()["failed"] or battery.run_scenes(500, seed=3)["false_joins"]
    monkeypatch.setattr(aj, "WINDOW_DAYS", 7)
    monkeypatch.setattr(aj, "BLOCK_DAYS", 10)
    assert battery.run_traps()["failed"] or battery.run_scenes(500, seed=3)["false_joins"]
