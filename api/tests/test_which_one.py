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


# --------------------------------------------------------------------------- review fixes (PR #906)

import asyncio  # noqa: E402

from api.services import bank_index, git_service, merge_rejections, sleep_cycle  # noqa: E402
from api.tests.test_held_release import EP2, _git  # noqa: E402


def _inbox_bytes(bank) -> dict[str, bytes]:
    return {p.relative_to(bank).as_posix(): p.read_bytes() for p in sorted((bank / "inbox").rglob("*.md"))}


def _with_episode(bank, item_id: str, episode: str, **extra) -> None:
    path = bank / "inbox" / f"{item_id}.md"
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, {**parsed.frontmatter, "source_episode": episode, **extra}, parsed.body)


def test_a_failed_commit_puts_every_question_back_as_it_was(nick, monkeypatch):
    """The catch-up step REWRITES a tracked question and moves the others; its undo used to unlink the paths it wrote, so
    after a failed commit the originals were gone from the tree and the deletion rode the next writer's commit."""
    _with_episode(nick, "inbox-002", EP2, why_asked="They share a first name.")
    _commit(nick, "two episodes")
    before = _inbox_bytes(nick)

    async def boom(*_a, **_k):
        raise git_service.GitError("index.lock is held")

    monkeypatch.setattr(git_service, "commit_paths", boom)
    asyncio.run(sleep_cycle._catchup_questions_safely(nick))
    assert _inbox_bytes(nick) == before, "every question is as it was, none is gone and no record is left"
    assert _git(nick, "status", "--porcelain") == ""


def test_a_commit_that_goes_through_leaves_one_question_and_the_folded_one_settled(nick):
    asyncio.run(sleep_cycle._catchup_questions_safely(nick))
    assert _git(nick, "status", "--porcelain") == ""
    assert sorted(_inbox_bytes(nick)) == ["inbox/inbox-001.md", "inbox/settled/inbox-002.md"]
    assert "Cicada-Author: cicada" in _git(nick, "log", "-1", "--format=%B")


def test_folding_carries_every_conversation_and_every_word_and_retires_through_a_settled_record(nick):
    _with_episode(nick, "inbox-002", EP2, why_asked="They share a first name.")
    _commit(nick, "two episodes")
    original = (nick / "inbox" / "inbox-002.md").read_bytes()
    report = which_one.tend(nick, TODAY)
    assert report.folded == 1
    fm = markdown_parser.parse(nick / "inbox" / "inbox-001.md").frontmatter
    assert fm["source_episode"] == EP1 and fm["source_episodes"] == [EP1, EP2]
    assert fm["why_asked"] == "They share a first name.", "a reason the survivor lacked is carried"
    assert which_one.episodes_of(fm) == [EP1, EP2]
    record = markdown_parser.parse(nick / "inbox" / "settled" / "inbox-002.md")
    assert record.frontmatter["source_episode"] == EP2 and record.frontmatter["settled"]["rule"] == which_one.RULE
    assert record.frontmatter["why_asked"] == "They share a first name.", "nothing the folded file stored is lost"
    from api.services import inbox_tend

    assert which_one.RULE in inbox_tend.RULES and which_one.RULE in inbox_tend.ENGINE_FREE
    # The report remembers what it read, so a failed commit can put it back byte for byte.
    assert report.before["inbox/inbox-002.md"] == original and report.before["inbox/settled/inbox-002.md"] is None


def test_taking_back_the_fold_reopens_the_question_through_sleeps_own_undo(nick):
    which_one.tend(nick, TODAY)
    _commit(nick, "Sleep's tending")
    from api.services import inbox_tend

    inbox_tend.undo(nick, "inbox-002")
    assert (nick / "inbox" / "inbox-002.md").exists() and not (nick / "inbox" / "settled" / "inbox-002.md").exists()


def test_a_pick_credits_the_page_with_every_conversation_the_question_came_from(nick):
    _with_episode(nick, "inbox-002", EP2)
    which_one.tend(nick, TODAY)
    _answer(nick, "inbox-001", action="resolve", option_key="page:nick-friend")
    episodes = markdown_parser.parse(nick / "entities" / "nick-friend.md").frontmatter["source_episodes"]
    assert EP1 in episodes and EP2 in episodes


@pytest.mark.parametrize("how", ["raised", "tended"])
def test_someone_else_keeps_the_mention_apart_from_every_candidate_whoever_made_the_question(nick, how):
    """`raise_question` writes no `held_mention`; the answer used to become a name-wide rejection of the first candidate."""
    if how == "raised":
        for path in (nick / "inbox").glob("inbox-*.md"):
            path.unlink()
        assert which_one.raise_question(nick, "Nick", EP1, today=TODAY) == "inbox/inbox-001.md"
        assert "held_mention" not in markdown_parser.parse(nick / "inbox" / "inbox-001.md").frontmatter
    else:
        _with_episode(nick, "inbox-002", EP2)
        which_one.tend(nick, TODAY)
    _answer(nick, "inbox-001", action="resolve", option_key="another")
    line = next(e for e in pending_store.load(nick) if e.name == "Nick")
    assert line.apart_pages() == {"nick-brother", "nick-friend"} and EP1 in line.apart_episodes()
    if how == "tended":
        assert EP2 in line.apart_episodes(), "scoped to every conversation the question came from"
    assert not merge_rejections.is_rejected(nick, "nick", "nick-brother"), "no name is rejected for the future"
    assert not merge_rejections.is_rejected(nick, "nick", "nick-friend")
    assert line.held_claims, "the line keeps what it holds"


def test_two_candidates_with_the_same_relation_are_told_by_their_names(nick):
    _roles(nick, "nick-friend", "brother")
    assert which_one.labels([
        {"id": "a", "name": "Nick Rowe", "type": "person", "roles": ["brother"], "qualifier": None},
        {"id": "b", "name": "Nick Vale", "type": "person", "roles": ["brother"], "qualifier": None}]) == ["Nick Rowe", "Nick Vale"]
    which_one.tend(nick, TODAY)
    item = _served(nick, "inbox-001")
    assert [o.label for o in item.options] == ["Nick Rowe", "Nick Vale", "Someone else"]
    assert item.spoken_question == "Were you talking about Nick Rowe or Nick Vale?"


def test_two_choices_never_show_the_same_words():
    same = [{"id": "x-1", "name": "Pat Doe", "type": "person", "roles": None, "qualifier": None},
            {"id": "x-2", "name": "Pat Doe", "type": "person", "roles": None, "qualifier": None}]
    shown = which_one.labels(same)
    assert len(set(shown)) == 2 and all("Pat Doe" in s for s in shown)
    qualified = [{**same[0], "qualifier": "person, Sep 2026"}, {**same[1], "qualifier": "person, Oct 2026"}]
    assert which_one.labels(qualified) == ["Pat Doe (person, Sep 2026)", "Pat Doe (person, Oct 2026)"]
    assert which_one.labels([{**same[0], "roles": ["brother"]}, {**same[1], "roles": ["friend"]}]) == ["Your brother", "Your friend"]


def test_the_owners_own_page_is_never_a_candidate(nick):
    _page(nick, "nick-owner", "Nick Owner", "person")
    path = nick / "entities" / "nick-owner.md"
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, {**parsed.frontmatter, "owner": True}, parsed.body)
    assert "nick-owner" not in which_one.answering(nick, "Nick")
    assert which_one.usable(nick, "Nick", ["nick-owner", "nick-brother", "nick-friend"]) == ["nick-brother", "nick-friend"]
    assert which_one.raise_question(nick, "Nick", EP1, ["nick-owner", "nick-friend"]) is None, "one candidate is left"


def _people(bank, first: str, surnames: list[str]) -> list[str]:
    ids = []
    for surname in surnames:
        pid = f"{first.lower()}-{surname.lower()}"
        _page(bank, pid, f"{first} {surname}", "person")
        ids.append(pid)
    return ids


def test_a_short_name_needs_three_letters_and_a_common_first_name_pulls_in_no_one(bank):
    _people(bank, "Jo", ["Ames", "Bell"])
    assert which_one.answering(bank, "Jo") == [], "a two-letter word is no one's short name"
    assert which_one.answering(bank, "J") == []
    _people(bank, "Sam", ["Ames", "Bell", "Cole", "Dunn", "Eyre"])
    assert which_one.answering(bank, "Sam") == [], "five people share it: a common name says nothing about which"
    assert which_one.answering(bank, "Sam", pointed={"sam-ames"}) == [f"sam-{s}" for s in ("ames", "bell", "cole", "dunn", "eyre")], \
        "the question already points at a page of that name: its namesakes are real alternatives, up to what the card shows"
    _people(bank, "Sam", ["Fox"])
    assert which_one.answering(bank, "Sam", pointed={"sam-ames"}) == [], "six is more than the card shows well"
    _people(bank, "Ida", ["Ames", "Bell", "Cole"])
    assert len(which_one.answering(bank, "Ida")) == 3, "at most three pages answer to it: all are asked"


def test_tending_never_widens_a_two_button_question_into_a_six_button_one(bank):
    _people(bank, "Sam", ["Ames", "Bell", "Cole", "Dunn", "Eyre", "Fox"])
    _question(bank, "inbox-002", "Sam", "sam-ames", "Sam Ames", entity_id="sam")
    _question(bank, "inbox-003", "Sam", "sam-bell", "Sam Bell", entity_id="sam")
    _commit(bank, "a common first name")
    which_one.tend(bank, TODAY)
    fm = markdown_parser.parse(bank / "inbox" / "inbox-002.md").frontmatter
    assert fm["same_title"] == ["sam-ames", "sam-bell"], "six people share the name: the question keeps the candidates it had"


def test_a_later_pairwise_question_about_the_mention_is_folded_into_the_open_one(nick):
    which_one.tend(nick, TODAY)
    _page(nick, "nick-third", "Nick Third", "person")
    _question(nick, "inbox-003", "Nick", "nick-third", "Nick Third")
    _commit(nick, "a later pairwise question")
    report = which_one.tend(nick, TODAY)
    assert (report.rewritten, report.folded) == (1, 1)
    assert sorted(p.name for p in (nick / "inbox").glob("inbox-*.md")) == ["inbox-001.md"], "never a second which-one question"
    fm = markdown_parser.parse(nick / "inbox" / "inbox-001.md").frontmatter
    assert fm["same_title"] == ["nick-brother", "nick-friend", "nick-third"]
    assert which_one.tend(nick, TODAY).written == []


def test_a_which_one_question_the_person_holds_makes_no_second_one(nick):
    which_one.tend(nick, TODAY)
    path = nick / "inbox" / "inbox-001.md"
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, {**parsed.frontmatter, "sleep_settle": "undone"}, parsed.body)
    _page(nick, "nick-third", "Nick Third", "person")
    _question(nick, "inbox-003", "Nick", "nick-third", "Nick Third")
    _commit(nick, "a later pairwise question")
    assert which_one.tend(nick, TODAY).written == []
    assert (nick / "inbox" / "inbox-003.md").exists()


def test_a_pick_is_that_mentions_answer_and_the_next_mention_is_not_auto_joined(nick):
    """The owner's rule: a later mention is decided by its own context. A pick used to list the name as the picked page's
    alias and leave Stage 2's "the person said so" note on it, so the next "Nick" went there with no look at its conversation."""
    from api.services import entity_resolver as er

    which_one.tend(nick, TODAY)
    _answer(nick, "inbox-001", action="resolve", option_key="page:nick-friend")
    pages = []
    for path in sorted((nick / "entities").glob("*.md")):
        parsed = markdown_parser.parse(path)
        pages.append({"id": path.stem, "frontmatter": parsed.frontmatter, "body": parsed.body})
    by_name = er.existing_by_name(pages)
    aliases = er._alias_index(by_name)
    mention = {"name": "Nick", "type": "person"}
    assert er._answered_match(mention, aliases) is None
    assert er._exact_person_match(mention, by_name, aliases) is None
    assert er._find_direct_candidate_match(mention, by_name, {}, aliases) is None
    friend = markdown_parser.parse(nick / "entities" / "nick-friend.md")
    assert "Nick" not in (friend.frontmatter.get("aliases") or []) and "Resolved ambiguous mention" not in friend.body
    assert ("nick-friend", "mentors", "mira-quell") in _claims(nick, "nick-friend"), "what was held still lands on the pick"
