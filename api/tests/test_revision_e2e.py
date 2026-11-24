"""`benchmarks/consolidation/revision_e2e.py`: the engine-free half (the two story files and the reading of a bank)."""
import json
from datetime import date
from pathlib import Path

import pytest

from benchmarks.consolidation import revision_e2e as e2e

REVIEW = Path(e2e.__file__).with_name("revision_e2e_review_stories.json")
CLOCK = date(2026, 11, 24)


@pytest.mark.parametrize("path", [e2e.STORIES, REVIEW], ids=["stories", "review"])
def test_a_story_file_is_a_two_night_fixture_whose_stories_each_say_what_must_hold(path):
    fixture = json.loads(path.read_text(encoding="utf-8"))
    assert set(fixture) >= {"owner", "conversations", "gold", "expect"}, "the benchmark's leg stages and scores it"
    stories = fixture["expect"]["stories"]
    assert len({s["id"] for s in stories}) == len(stories) >= 10
    for story in stories:
        assert story["shape"] and story["lang"]
        assert story.get("current") or story.get("stale") or story.get("kept"), story["id"]


def _story():
    return {"id": "x1", "shape": "date", "lang": "en", "about": "valencia",
            "current": [["2026-12-13"]], "stale": [["2026-12-06"]]}


def _claim(day, **extra):
    return {"subject": "lia-prueba", "predicate": "moves-to", "object": "valencia", "valid_from": day,
            "text": f"Lia Prueba moves to Valencia {day}", **extra}


@pytest.mark.parametrize("claims, verdict", [
    ([_claim("2026-12-13"), _claim("2026-12-06", valid_to="2026-11-24")], "correct"),
    ([_claim("2026-12-13"), _claim("2026-12-06")], "both_current"),
    ([_claim("2026-12-06")], "stale_only"),
    ([_claim("2026-12-06", superseded_by="clm_x")], "missing"),
])
def test_a_story_is_judged_on_what_is_open_never_on_what_was_closed(claims, verdict):
    got = e2e.judge_story(_story(), claims, [], CLOCK, None)
    assert got["verdict"] == verdict
    assert bool(got["stale_open"]) == (verdict in ("both_current", "stale_only"))
