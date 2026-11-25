"""Ruling 83 (owner 2026-11-25): a mention that could be several known pages is ONE question — "Were you talking about your
brother or <Full Name>?" — raised through one door, rewritten from the pairwise form by Sleep's tending, answered through
the existing verbs (a pick is a merge of the held mention, "Someone else" files nothing).

Synthetic banks only (the `test_held_release` fixture: alex, alex-kim, alex-lee, mira-quell, "Alex" held against the page
called Alex); git is real; nothing reaches a network or an engine.
"""
from __future__ import annotations

from datetime import date

import pytest

from api.services import inbox_service, markdown_parser, pending_store, same_name, which_one
from api.tests.test_held_release import (  # noqa: F401 — `bank` is a fixture
    EP1, _answer, _claims, _commit, _held, _line, _line_claims, _page, _question, bank,
)

TODAY = date(2026, 10, 3)


def _roles(bank, pid: str, role: str) -> None:
    parsed = markdown_parser.parse(bank / "entities" / f"{pid}.md")
    markdown_parser.write(bank / "entities" / f"{pid}.md", {**parsed.frontmatter, "owner_roles": [role]}, parsed.body)


@pytest.fixture
def nick(bank):
    """A held nickname ("Nick") that two people answer to — a brother (known by the relation) and a friend named in full —
    asked the old way: one pairwise question per candidate."""
    (bank / "inbox" / "inbox-001.md").unlink()
    for pid, name in (("nick-brother", "Nick Rowe"), ("nick-friend", "Nick Vale")):
        _page(bank, pid, name, "person")
    _roles(bank, "nick-brother", "brother")
    _line(bank, "Nick", "nick-brother", [_held("nick", "mentors", "mira-quell", 1, EP1)])
    for n, (pid, name) in enumerate((("nick-brother", "Nick Rowe"), ("nick-friend", "Nick Vale")), start=1):
        _question(bank, f"inbox-00{n}", "Nick", pid, name)
    _commit(bank, "a nickname two people answer to")
    same_name.invalidate()
    return bank


def _served(bank, item_id):
    return next(i for i in inbox_service.load_inbox(bank) if i.id == item_id)


def test_a_nickname_is_every_page_it_could_be(nick):
    assert which_one.answering(nick, "Nick") == ["nick-brother", "nick-friend"]
    assert which_one.answering(nick, "Nick Vale") == ["nick-friend"]
    assert which_one.answering(nick, "Nobody") == []


def test_a_short_name_inside_two_full_names_is_a_mention_of_both(bank):
    assert which_one.answering(bank, "Alex", exclude={"alex"}) == ["alex-kim", "alex-lee"]


def test_sleeps_tending_rewrites_the_pairs_into_the_one_question(nick):
    report = which_one.tend(nick, TODAY)
    assert (report.rewritten, report.folded) == (1, 1)
    assert sorted(p.name for p in (nick / "inbox").glob("inbox-*.md")) == ["inbox-001.md"], "nothing beside it"
    fm = markdown_parser.parse(nick / "inbox" / "inbox-001.md").frontmatter
    assert fm["same_title"] == ["nick-brother", "nick-friend"] and fm["held_mention"] is True
    assert which_one.tend(nick, TODAY).written == [], "idempotent: nothing to do on the next night"


def test_the_question_is_the_one_a_person_would_ask(nick):
    which_one.tend(nick, TODAY)
    item = _served(nick, "inbox-001")
    assert item.spoken_question == "Were you talking about your brother or Nick Vale?"
    assert [o.label for o in item.options] == ["Your brother", "Nick Vale", "Someone else"]
    assert [o.key for o in item.options] == ["page:nick-brother", "page:nick-friend", "another"], "the keys do not change"
    assert "same as" not in (item.spoken_question or "")
    assert item.same_title == ["nick-brother", "nick-friend"], "served though no two pages share a title"


def test_picking_a_page_files_the_held_lines_there_and_only_there(nick):
    which_one.tend(nick, TODAY)
    _answer(nick, "inbox-001", action="resolve", option_key="page:nick-friend")
    assert ("nick-friend", "mentors", "mira-quell") in _claims(nick, "nick-friend")
    assert _claims(nick, "nick-brother") == []
    assert _line_claims(nick, "Nick") == []
    # No alias is written to the other candidate and the name is never taken from it: nothing for the alias-collision rule.
    fm = markdown_parser.parse(nick / "entities" / "nick-brother.md").frontmatter
    assert "Nick" not in (fm.get("aliases") or [])


def test_someone_else_files_nothing_and_keeps_the_mention_apart(nick):
    which_one.tend(nick, TODAY)
    _answer(nick, "inbox-001", action="resolve", option_key="another")
    assert _claims(nick, "nick-friend") == [] and _claims(nick, "nick-brother") == []
    line = next(e for e in pending_store.load(nick) if e.name == "Nick")
    assert line.apart_pages() == {"nick-brother", "nick-friend"} and line.held_claims, "the line keeps its claims"


def test_one_candidate_is_no_question(nick):
    assert which_one.raise_question(nick, "Nick", EP1, ["nick-brother"]) is None


def test_raise_question_is_the_one_door_and_asks_once(nick):
    for path in (nick / "inbox").glob("inbox-*.md"):
        path.unlink()
    rel = which_one.raise_question(nick, "Nick", EP1, today=TODAY)
    assert rel == "inbox/inbox-001.md"
    fm = markdown_parser.parse(nick / rel).frontmatter
    assert fm["same_title"] == ["nick-brother", "nick-friend"] and fm["source_episode"] == EP1
    assert which_one.raise_question(nick, "Nick", EP1, today=TODAY) is None, "the open question is the question"


def test_a_question_the_person_took_back_is_theirs(nick):
    path = nick / "inbox" / "inbox-001.md"
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, {**parsed.frontmatter, "sleep_settle": "undone"}, parsed.body)
    assert which_one.tend(nick, TODAY).written == []


def test_measure_a_first_name_and_a_short_name_each_become_one_question(bank):
    """The labelled set's other two cases: a first name inside two full names (2 pairwise questions -> 1) and a short name
    shared by a tool and a project (2 -> 1)."""
    _question(bank, "inbox-002", "Alex", "alex-lee", "Alex Lee")
    _page(bank, "foo-studio", "Foo Studio", "tool")
    _page(bank, "foo-app", "Foo", "project")
    _line(bank, "Foo", "foo-app", [_held("foo", "uses", "mira-quell", 3, EP1)])
    _question(bank, "inbox-003", "Foo", "foo-studio", "Foo Studio")
    _question(bank, "inbox-004", "Foo", "foo-app", "Foo")
    _commit(bank, "two more ambiguous mentions")
    before = sorted(p.name for p in (bank / "inbox").glob("inbox-*.md"))
    assert len(before) == 4
    which_one.tend(bank, TODAY)
    left = sorted(p.name for p in (bank / "inbox").glob("inbox-*.md"))
    assert len(left) == 2, "four pairwise questions, two mentions: two questions"
    spoken = {i.entity_name: i.spoken_question for i in inbox_service.load_inbox(bank)}
    assert spoken["Alex"] == "Were you talking about Alex Kim or Alex Lee?"
    assert spoken["Foo"].startswith("Were you talking about Foo Studio or Foo")
