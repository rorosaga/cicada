"""G227 follow-up: the per-sentence plan for a page carrying sentences about a different thing with its name. A plan
only — nothing is written. Synthetic pages; the judge is a fake (no engine)."""
from __future__ import annotations

import asyncio

from api.services import bank_index, same_name, same_name_split
from api.tests.test_same_name import _page


def _bank(tmp_path):
    bank_index.invalidate()
    same_name.invalidate()
    _page(tmp_path, "alpha", "Alpha", "tool", "Alpha is an AI-powered IDE built for pair programming.\n\n"
          "## Article\n\nThe person refactored alpha-project in Alpha's agent mode last week.\n"
          "- The person applied to Alpha's spring cohort and has an interview with its partners.\n"
          "- [a link](https://example.com)\n\nShort.\n\n```claims\n[]\n```\n")
    _page(tmp_path, "alpha-program", "Alpha", "project", "Alpha is an accelerator program for early teams.")
    _page(tmp_path, "media-alpha", "Alpha", "media", "A saved page.")
    _page(tmp_path, "beta", "Beta", "tool", "Beta is a library the person uses for charts every week.")
    return tmp_path


def test_sentences_are_the_pages_prose_only(tmp_path):
    bank = _bank(tmp_path)
    found = same_name_split.sentences(bank_index.file(bank, "entities", "alpha.md").body())
    assert [s.text for s in found] == [
        "Alpha is an AI-powered IDE built for pair programming.",
        "The person refactored alpha-project in Alpha's agent mode last week.",
        "The person applied to Alpha's spring cohort and has an interview with its partners."]
    assert [s.n for s in found] == [1, 2, 3] and found[2].section == "Article"


def test_targets_are_the_shared_names_pages_and_the_ids_asked_for(tmp_path):
    bank = _bank(tmp_path)
    got = dict(same_name_split.targets(bank, extra_ids=["beta"]))
    assert set(got) == {"alpha", "alpha-program", "beta"}, "a saved link is never read; an asked-for page is"
    assert set(got["alpha"]) == {"alpha-program", "media-alpha"} and got["beta"] == []


def test_a_plan_keeps_only_listed_sentences_and_listed_targets_and_writes_nothing(tmp_path):
    bank = _bank(tmp_path)
    before = (bank / "entities" / "alpha.md").read_bytes()
    prompts = []

    async def judge(prompt):
        prompts.append(prompt)
        return {"moves": [{"n": 3, "target": "alpha-program", "reason": "About the program's cohort."},
                          {"n": 2, "target": "somewhere-else", "reason": "not a listed page"},
                          {"n": 99, "target": "new", "reason": "no such sentence"},
                          {"n": 1, "target": "alpha", "reason": "its own page"}]}

    moves = asyncio.run(same_name_split.plan_page(bank, "alpha", ["alpha-program", "media-alpha"], judge))
    assert [(m.n, m.target) for m in moves] == [(3, "alpha-program")]
    assert "accelerator program" in prompts[0] and "3. The person applied" in prompts[0]
    assert (bank / "entities" / "alpha.md").read_bytes() == before
