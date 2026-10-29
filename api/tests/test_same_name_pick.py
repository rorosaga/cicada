"""G227 follow-up (owner 2026-10-29): pick the page — a mention said as a title several pages share is asked ONE
question, one option per page plus "none of these"; a pick merges the held mention into that page by id, "none"
keeps it apart from every one so Sleep makes a page of its own (a clean title, a distinct id).

Synthetic banks only (the `test_held_release` fixture: alex, alex-kim, alex-lee, mira-quell, plus a second "Alex",
``alex-2``); git is real; nothing reaches a network or an engine.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from api.services import bank_index, markdown_parser, merge_rejections, same_name, same_name_pick
from api.tests.test_held_release import (  # noqa: F401 — `bank` is a fixture
    EP1, _answer, _claims, _commit, _line_claims, _page, bank,
)


def _pick_question(root, item_id: str = "inbox-002", ids=("alex", "alex-2")) -> None:
    markdown_parser.write(root / "inbox" / f"{item_id}.md", {
        "held_mention": True, "kind": "merge_suggestion", "required_input": "merge", "status": "pending",
        "priority": 0.7, "entity_id": "alex", "entity_name": "Alex", "title": "Which Alex is this?",
        "uncertainty_type": "Possible duplicate of Alex", "suggested_classification": "person — x",
        "suggested_confidence": 0.7, "created_date": "2026-10-02", "source_episode": EP1,
        "merge_target_hint": ids[0], "same_title": list(ids)}, "Could not safely decide.")


@pytest.fixture
def picked_bank(bank):
    (bank / "inbox" / "inbox-001.md").unlink()   # the fixture's own pair question is another test's
    _page(bank, "alex-2", "Alex", "person")
    _pick_question(bank)
    _commit(bank, "a second Alex and a pick question")
    same_name.invalidate()
    return bank


def _served(bank, item_id="inbox-002"):
    from api.services import inbox_service

    return next(i for i in inbox_service.load_inbox(bank) if i.id == item_id)


def test_the_question_is_served_with_one_option_per_page_and_none(picked_bank):
    item = _served(picked_bank)
    assert [o.key for o in item.options] == ["page:alex", "page:alex-2", "none"]
    assert [o.page_id for o in item.options[:2]] == ["alex", "alex-2"]
    assert all(o.page_name == "Alex" and o.qualifier for o in item.options[:2])
    assert item.options[0].qualifier != item.options[1].qualifier, "the qualifier tells them apart"
    assert item.options[0].label == f"Alex ({item.options[0].qualifier})", "the label keeps it in text for agents"
    assert item.options[2].label == same_name_pick.NONE_LABEL
    assert item.question == "Which Alex is this?"
    assert item.spoken_question.startswith("Which Alex is this:")


def test_picking_a_page_merges_the_held_mention_into_that_page_by_id(picked_bank):
    _answer(picked_bank, "inbox-002", action="resolve", option_key="page:alex-2")
    assert ("alex-2", "mentors", "mira-quell") in _claims(picked_bank, "alex-2")
    assert _claims(picked_bank, "alex") == [], "never the other page that shares the name"
    assert _line_claims(picked_bank, "Alex") == []
    assert not (picked_bank / "inbox" / "inbox-002.md").exists()


def _line(bank):
    from api.services import pending_store

    return next(e for e in pending_store.load(bank) if e.name == "Alex")


def test_none_of_these_keeps_this_mention_apart_never_the_name(picked_bank):
    _answer(picked_bank, "inbox-002", action="resolve", option_key="none")
    line = _line(picked_bank)
    assert line.apart_pages() == {"alex", "alex-2"} and EP1 in line.apart_episodes()
    # #546 review: no name→page pair — the mention's slug is the first page's own id, and such a pair kept every later
    # mention of that page from joining it.
    assert not merge_rejections.is_rejected(picked_bank, "alex", "alex")
    assert not merge_rejections.is_rejected(picked_bank, "alex", "alex-2")
    assert _claims(picked_bank, "alex-2") == [] and _line_claims(picked_bank, "Alex"), "held for Sleep to place"


def test_after_none_a_later_mention_of_an_existing_page_still_joins_it_and_the_held_claims_stay(picked_bank):
    from api.services import entity_resolver as er
    from api.services import pending_store

    _answer(picked_bank, "inbox-002", action="resolve", option_key="none")

    class _Indexer:
        def pending_by_name(self, name):
            return next((e for e in pending_store.load(picked_bank) if e.name.lower() == name.lower()), None)

    later = er._apart_here(_Indexer(), "Alex", {"ep_2026-10-20_001"})          # a new conversation
    assert later == frozenset()
    tool = {"name": "Alex", "type": "tool"}
    tool_page = {"id": "alex", "frontmatter": {"name": "Alex", "type": "tool"}, "body": ""}
    hit = er._find_direct_candidate_match(tool, {"alex": tool_page}, {}, same_title={"alex": [tool_page]},
                                          rejected=later)
    assert hit is not None and hit["candidate"]["id"] == "alex", "a later mention still joins the page"
    reread = er._apart_here(_Indexer(), "Alex", {EP1})                        # the same conversation read again
    assert reread == frozenset({("alex", "alex"), ("alex", "alex-2")})
    assert er._find_direct_candidate_match(tool, {"alex": tool_page}, {}, same_title={"alex": [tool_page]},
                                           rejected=reread) is None
    # The later mention joining "alex" never carries the held mention's claims there.
    assert pending_store.ready(picked_bank, lambda _n, _s: "alex", decided=["alex"]) == []


def test_a_key_that_is_not_one_of_its_pages_is_refused(picked_bank):
    for key in ("page:alex-kim", "page:nowhere", "same"):
        with pytest.raises(HTTPException) as err:
            _answer(picked_bank, "inbox-002", action="resolve", option_key=key)
        assert err.value.status_code == 400
    assert (picked_bank / "inbox" / "inbox-002.md").exists(), "nothing written"


def test_the_catch_up_and_the_agent_doors_offer_the_same_keys(picked_bank):
    from api.services import catchup_chat, mcp_tools

    item = _served(picked_bank)
    assert [k["key"] for k in catchup_chat.answer_keys(item)] == ["page:alex", "page:alex-2", "none"]
    fm = markdown_parser.parse(picked_bank / "inbox" / "inbox-002.md").frontmatter
    asked, _cause, _rec = mcp_tools._agent_question(picked_bank, fm, "2026-10-29")
    assert asked["question"] == "Which Alex is this?"
    assert [o["key"] for o in asked["options"]] == ["page:alex", "page:alex-2", "none"]
    assert "page:<id>" in mcp_tools._format_inbox_blurb(fm, "")


def test_one_question_per_mention_never_one_per_pair(picked_bank):
    from api.services.clarification_manager import ClarificationManager

    bank_index.invalidate()
    again = ClarificationManager(picked_bank).create(
        entity_name="Alex", source_episode=EP1, uncertainty_type="Possible duplicate of Alex",
        suggested_classification="person — x", suggested_confidence=0.6, source_context="",
        same_title=["alex", "alex-2"], target_id="alex-2")
    assert again is None, "the open question about this mention is the same question"
    assert len(list((picked_bank / "inbox").glob("inbox-*.md"))) == 1


def test_a_re_read_of_the_answered_conversation_never_brings_back_a_page_it_is_not():
    from api.services import entity_resolver as er

    ide = {"id": "alpha", "frontmatter": {"name": "Alpha", "type": "tool"}, "body": ""}
    prog = {"id": "alpha-program", "frontmatter": {"name": "Alpha", "type": "project"}, "body": ""}
    same = {"alpha": [ide, prog]}
    rejected = frozenset({("alpha", "alpha"), ("alpha", "alpha-program")})
    tool = {"name": "Alpha", "type": "tool"}
    assert er._find_direct_candidate_match(tool, {"alpha": ide}, {}, same_title=same)["candidate"]["id"] == "alpha"
    assert er._find_direct_candidate_match(tool, {"alpha": ide}, {}, same_title=same, rejected=rejected) is None
    calls = []

    async def judge(**kwargs):
        calls.append(kwargs)
        return "unsure"

    er_judge = er._llm_judge_same_entity
    er._llm_judge_same_entity = judge
    try:
        concept = {"name": "Alpha", "type": "company", "description": "x"}
        assert asyncio.run(er._same_title_match(concept, same, {}, settings=None, rejected=rejected)) is None
        assert calls == [], "never judged, never asked again"
        one_left = frozenset({("alpha", "alpha")})
        match = asyncio.run(er._same_title_match(concept, same, {}, settings=None, rejected=one_left))
        assert match["same_title"] == ["alpha-program"]
    finally:
        er._llm_judge_same_entity = er_judge


def test_a_page_of_its_own_keeps_the_clean_title_under_a_distinct_id():
    from api.services import entity_resolver as er

    assert er._another_id("Alpha", {"alpha"}, {}) == "alpha-2"
    assert er._another_id("Alpha", {"alpha", "alpha-2"}, {"alpha-3": {}}) == "alpha-4"
    assert not hasattr(er, "_another_title")
