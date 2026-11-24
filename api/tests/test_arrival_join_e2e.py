"""The arrival join through the real tail (`benchmarks/consolidation/arrival_join_e2e.py`): a scratch bank and home, a synthetic
directory and Contacts card, git, the tail's own steps in the tail's own order with `LIVE` forced on in this test only. No
model. Names invented."""
from __future__ import annotations

import inspect

from api.services import sleep_cycle
from benchmarks.consolidation import arrival_join_e2e as e2e


def test_the_whole_story_holds_through_the_real_tail(tmp_path):
    result = e2e.story(tmp_path)
    assert result["ok"], {k: v for k, v in result["checks"].items() if not v}


def test_the_join_steps_stand_where_the_plan_puts_them_in_the_tail():
    source = inspect.getsource(sleep_cycle._run_engine_independent_tail)
    order = [source.index(name) for name in ("_arrival_refusals_safely(", "_same_name_review_safely(", "_full_name_join_safely(",
                                             "_arrival_join_safely(", "_catchup_questions_safely(", "_rematch_linkedin_safely(",
                                             "_rematch_contacts_safely(", "_arrival_record_safely(", "_where_to_check_safely(")]
    assert order == sorted(order)      # refusals, 74a, 74b, the join, the catch-up, the rematches, the record


def test_it_ships_report_only_and_the_tail_step_cannot_write_while_it_does(tmp_path, monkeypatch):
    from api.services import arrival_join

    assert arrival_join.LIVE is False
    source = inspect.getsource(sleep_cycle._arrival_join_safely)
    assert "report.joins" in source and "apply_join" in source        # the only write, behind what run_tail hands back
