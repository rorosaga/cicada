"""The full-name join battery (`benchmarks/consolidation/full_name_battery.py`): its cases build real banks, the
engine-free guards answer what each case says they must, and its scoring tells a wrong join from a true one. No model:
a fake judge stands in. Names invented."""
from __future__ import annotations

import asyncio

import pytest

from benchmarks.consolidation import full_name_battery as battery


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()


def _always(verdict):
    async def judge(system, prompt):
        import re

        quote = re.search(r"(?m)^\[1\] \([^)]*\) (.+)$", prompt)
        return {"verdict": verdict, "turn": 1, "quote": quote.group(1) if quote else "", "reason": "r"}
    return judge


def test_the_cases_are_labelled_and_cover_the_kinds_the_brief_names():
    cases = battery.load_cases()
    assert len({c["id"] for c in cases}) == len(cases)
    assert all(c["kind"] in ("one", "two") and c["turn"] and c["full"] and c["short"] for c in cases)
    ids = " ".join(c["id"] for c in cases)
    for kind in ("father-son", "colleagues", "namesake", "list", "surname-elsewhere", "es", "fr", "assistant-only", "quoted"):
        assert kind in ids, kind
    assert sum(c["kind"] == "one" for c in cases) >= 4
    assert sum(c["kind"] == "two" for c in cases) >= 8


def test_every_case_builds_a_bank_whose_guards_say_what_the_case_says():
    for case in battery.load_cases():
        row = asyncio.run(battery.run_case(case, 1, _always("cannot_tell")))
        assert row["guard"] == case.get("guard", "shape"), (case["id"], row["guard"])


def test_a_judge_that_always_says_one_is_caught_by_the_wrong_join_count():
    rows = [asyncio.run(battery.run_case(c, 2, _always("one"))) for c in battery.load_cases()
            if c["id"] in ("true-apposition-lunch", "two-father-son", "two-assistant-only")]
    by = {r["id"]: r for r in rows}
    assert by["true-apposition-lunch"]["joins"] == 2 and by["true-apposition-lunch"]["wrong_joins"] == 0
    # a model that says "one" for a father and a son on the located words is the failure the battery counts
    assert by["two-father-son"]["wrong_joins"] == 2
    # both names only in the assistant's turn: never read, whatever the model would say
    assert by["two-assistant-only"]["wrong_joins"] == 0 and by["two-assistant-only"]["calls"] == 0
    assert "WRONG JOINS (two people joined): 2/" in battery.report(rows)
