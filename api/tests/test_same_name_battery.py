"""The same-name replay battery (`benchmarks/consolidation/same_name_battery.py`): its cases are labelled consistently and
its scoring tells a false split (one person cut in two) from a missed one. No model: a fake judge stands in."""
from __future__ import annotations

import asyncio
import re

from api.services import same_name_people as snp
from benchmarks.consolidation import same_name_battery as battery


def _entries(prompt):
    """Every lettered description the prompt shows, as ``{letter: its words after the date}``."""
    return {m.group(1): m.group(2) for m in re.finditer(r"(?m)^\s*\(([A-Z])\) (?:\(\d{4}-\d{2}-\d{2}\) )?(.+)$", prompt)}


def _every_conversation_its_own_person(system, prompt):
    async def go():
        said = _entries(prompt)
        letters = list(said)
        pairs = [{"people": [a + 1, b + 1], "verdict": "different", "here": said[letters[a]][:30], "there": said[letters[b]][:30],
                  "reason": "r"} for a in range(len(letters)) for b in range(a + 1, len(letters))]
        return {"people": [{"conversations": [x], "reason": "own"} for x in letters], "pairs": pairs}
    return go()


def _everyone_the_same(system, prompt):
    async def go():
        return {"people": [{"conversations": list(_entries(prompt)), "reason": "same"}]}
    return go()


def test_the_cases_are_labelled_and_cover_both_kinds_and_the_real_shapes():
    cases = battery.load_cases()
    assert len({c["id"] for c in cases}) == len(cases)
    for c in cases:
        assert c["kind"] in ("one", "two") and c["mentions"]
        labels = {m["label"] for m in c["mentions"]} | {i["label"] for i in c.get("identities", [])}
        assert (len(labels) == 1) == (c["kind"] == "one"), c["id"]
        assert not any(i["plain"] for i in c.get("identities", [])[1:]), c["id"]
    ids = {c["id"] for c in cases}
    assert {"idris-final-dev", "teo-promoted-real", "marc-like-interleaved"} <= ids
    assert sum(c["kind"] == "one" for c in cases) >= 30


def test_a_judge_that_splits_everything_is_all_false_splits_and_no_missed_ones():
    cases = [c for c in battery.load_cases() if c["id"] in ("partner-job-move", "two-mentions-before-after", "dentist-vs-cousin")]
    rows = asyncio.run(battery.run(cases, 2, _every_conversation_its_own_person))
    by = {r["id"]: r for r in rows}
    # a known page and one new mention, split apart: a false split; two mentions of one person apart too
    assert by["partner-job-move"]["false"] == 2 and by["two-mentions-before-after"]["false"] == 2
    assert by["dentist-vs-cousin"]["missed"] == 0 and by["dentist-vs-cousin"]["false"] == 0


def test_a_judge_that_joins_everything_misses_every_true_split():
    cases = [c for c in battery.load_cases() if c["id"] in ("dentist-vs-cousin", "marc-like-known-family", "partner-job-move")]
    rows = asyncio.run(battery.run(cases, 2, _everyone_the_same))
    by = {r["id"]: r for r in rows}
    assert by["dentist-vs-cousin"]["missed"] == 2 and by["marc-like-known-family"]["missed"] == 2
    assert by["partner-job-move"]["false"] == 0 and by["partner-job-move"]["missed"] == 0
