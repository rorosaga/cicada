"""The same-name replay stories (`benchmarks/consolidation/same_name_stories.py`): the stories are labelled consistently and
the simulated bank applies the decisions the way the resolver and the tail do. No model: fake judges stand in."""
from __future__ import annotations

import asyncio
import re

from benchmarks.consolidation import same_name_stories as st

SHAPES = {"two-new", "established-first", "joined-then-clarified", "never-told-apart", "doubt-resolved",
          "one-many-settings", "one-life-moves", "one-thin-first", "one-established-reread"}


def _letters(prompt):
    return re.findall(r"(?m)^\s*\(([A-Z])\) ", prompt)


async def _one_person(system, prompt):
    if "NEW CONVERSATIONS" in prompt or "[person 1]" in prompt or "CONVERSATIONS" in prompt:
        return {"people": [{"conversations": _letters(prompt), "reason": "same"}]}
    return {"verdict": "same", "here": "", "there": ""}   # an unlocated link: a doubt stays a doubt


def test_the_stories_are_labelled_consistently_and_cover_every_shape_in_three_languages():
    stories = st.load_stories()
    assert len({s["id"] for s in stories}) == len(stories)
    assert {s["shape"] for s in stories} == SHAPES
    for s in stories:
        labels = {c["who"] for b in s["batches"] for c in b} | {c["who"] for p in s.get("seed", []) for c in p["convs"]}
        assert (len(labels) >= 2) == s["two"], s["id"]
        assert s["lang"] in ("en", "es", "fr") and s["name"] and s["batches"]
        assert len(s["q"]) == 2 and s["q"][0] <= s["q"][1]
    assert {s["lang"] for s in stories} == {"en", "es", "fr"}
    shapes = {}
    for s in stories:
        shapes[s["shape"]] = shapes.get(s["shape"], 0) + 1
    assert min(shapes.values()) >= 2


def test_every_description_is_what_the_resolver_hands_the_judge():
    from api.services import same_name_people as snp

    story = st.load_stories()[0]
    text = st.text_of(story["batches"][0][0])
    assert text.startswith("(2026-") and "Facts: " in text and snp.words(text) >= 10


def test_a_judge_that_says_one_person_leaves_one_person_and_no_question():
    story = next(s for s in st.load_stories() if s["id"] == "settings-en")
    out = asyncio.run(st.replay(story, _one_person, _one_person))
    assert out["ok"] and out["persons"] == 1 and out["questions"] == 0 and not out["blend"] and not out["cut"]


def test_a_judge_that_always_joins_blends_a_story_of_two_people_and_the_score_says_so():
    story = next(s for s in st.load_stories() if s["id"] == "never-cousin-neighbour-en")
    out = asyncio.run(st.replay(story, _one_person, _one_person))
    assert out["blend"] and not out["ok"] and out["persons"] == 1


def test_a_doubt_nothing_settles_is_one_question_and_two_people_in_the_simulated_bank():
    story = next(s for s in st.load_stories() if s["id"] == "never-cousin-neighbour-en")

    async def doubt(system, prompt):
        if "PERSON 1" in prompt:
            return {"verdict": "cannot_tell"}
        entries = re.findall(r"(?m)^\s*\(([A-Z])\) \((\d{4}-\d{2}-\d{2})\) (.+)$", prompt)
        kin = [l for l, _d, t in entries if "cousin" in t]
        other = [l for l, _d, t in entries if "cousin" not in t]
        if not kin or not other:
            return {"people": [{"conversations": [l for l, *_ in entries], "reason": "one"}]}
        here = next(t for l, _d, t in entries if l == kin[0])
        there = next(t for l, _d, t in entries if l == other[0])
        return {"people": [{"conversations": kin, "reason": "a"}, {"conversations": other, "reason": "b"}],
                "pairs": [{"people": [1, 2], "verdict": "cannot_tell", "here": here[:40], "there": there[:40], "reason": "r"}]}

    out = asyncio.run(st.replay(story, doubt, doubt))
    assert out["questions"] == 1 and out["persons"] == 2 and not out["blend"] and out["ok"]
