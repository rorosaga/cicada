"""Owner 2026-11-24: someone known only by a description is not asked their name on a first mention, only once they come
up in a second conversation (`role_people.heard_again`, `inbox_tend` rule `name_once`). Invented names throughout."""
import asyncio

import pytest

from api.services import bank_index, inbox_tend, markdown_parser, role_people, web_settle
from test_role_people import OWNER_FM, OWNER_ID, _git, _git_bank, _name_questions, _page

TEACHER = "portuguese-guitar-teacher"


def _bank(tmp_path, episodes, **extra):
    memory = _git_bank(tmp_path)
    _page(memory, OWNER_ID, {**OWNER_FM}, "The owner.")
    _page(memory, TEACHER, {"name": "Portuguese guitar teacher", "unnamed": True, "nickname_title": True,
                            "source_episodes": episodes, **extra}, "## Summary\nTeaches fado on Thursdays.")
    return memory


def _episode(memory, eid, **fm):
    markdown_parser.write(memory / "episodes" / f"{eid}.md", {"timestamp": "2026-11-01T10:00:00+00:00", "processed": True,
                                                              **fm}, "user: Tomas has a teacher.")


def test_a_first_mention_asks_nothing_and_a_second_conversation_asks_once(tmp_path):
    memory = _bank(tmp_path, ["ep_2026-11-01_001"])
    assert role_people.ensure_question(memory, TEACHER, owner_fm=OWNER_FM) is None
    assert _name_questions(memory) == []
    fm = markdown_parser.parse(memory / "entities" / f"{TEACHER}.md")
    markdown_parser.write(memory / "entities" / f"{TEACHER}.md",
                          {**fm.frontmatter, "source_episodes": ["ep_2026-11-01_001", "ep_2026-11-09_001"]}, fm.body)
    path = role_people.ensure_question(memory, TEACHER, owner_fm=OWNER_FM)
    assert path is not None
    assert role_people.ensure_question(memory, TEACHER, owner_fm=OWNER_FM) is None   # once
    assert len(_name_questions(memory)) == 1


def test_two_episodes_of_one_session_are_one_conversation(tmp_path):
    memory = _bank(tmp_path, ["ep_2026-11-01_001", "ep_2026-11-01_002"])
    _episode(memory, "ep_2026-11-01_001", session_id="ses-one-abcdefgh", capture_kind="transcript")
    _episode(memory, "ep_2026-11-01_002", session_id="ses-one-abcdefgh", capture_kind="transcript")
    bank_index.invalidate()
    assert role_people.ensure_question(memory, TEACHER, owner_fm=OWNER_FM) is None


def test_a_page_with_no_recorded_conversation_is_not_asked(tmp_path):
    memory = _bank(tmp_path, [])
    assert role_people.ensure_question(memory, TEACHER, owner_fm=OWNER_FM) is None


def test_a_relation_is_held_to_the_same_rule(tmp_path):
    memory = _git_bank(tmp_path)
    _page(memory, OWNER_ID, {**OWNER_FM}, "The owner.")
    _page(memory, "partner", {"name": "Partner", "unnamed": True, "owner_roles": ["partner"],
                              "source_episodes": ["ep_2026-11-01_001"]}, "Lives nearby.")
    assert role_people.ensure_question(memory, "partner", owner_fm=OWNER_FM) is None
    assert role_people.ask_after_write(memory, [{"id": "partner", "action": "update"}], OWNER_FM) == []


def test_someone_who_declined_stays_unasked_after_a_second_conversation(tmp_path):
    memory = _bank(tmp_path, ["ep_2026-11-01_001", "ep_2026-11-09_001"], name_declined=True)
    assert role_people.ensure_question(memory, TEACHER, owner_fm=OWNER_FM) is None


# --- a question a memory already holds ---------------------------------------------------------


def _asked_bank(tmp_path):
    """A memory holding the question as it was raised before the rule: the page rests on one conversation."""
    memory = _bank(tmp_path, ["ep_2026-11-01_001", "ep_2026-11-09_001"])
    path = role_people.ensure_question(memory, TEACHER, owner_fm=OWNER_FM)
    assert path is not None
    page = memory / "entities" / f"{TEACHER}.md"
    parsed = markdown_parser.parse(page)
    markdown_parser.write(page, {**parsed.frontmatter, "source_episodes": ["ep_2026-11-01_001"]}, parsed.body)
    _git(memory, "add", "-A")
    _git(memory, "commit", "-q", "-m", "seed")
    bank_index.invalidate()
    return memory, path


def _settle(memory, path):
    decision, why = inbox_tend.policy(memory, path, markdown_parser.parse(path).frontmatter)
    if decision is not None:
        decision.fingerprint = path.read_bytes()
    return decision, why


def test_a_question_asked_on_one_mention_is_retired_with_nothing_written_and_comes_back_on_the_second(tmp_path):
    memory, path = _asked_bank(tmp_path)
    page_before = (memory / "entities" / f"{TEACHER}.md").read_bytes()
    decision, _ = _settle(memory, path)
    assert (decision.rule, decision.request) == ("name_once", None)
    assert asyncio.run(inbox_tend.apply(memory, type("S", (), {"memory_path": memory})(), decision))
    assert not path.exists() and _name_questions(memory) == []
    assert (memory / "entities" / f"{TEACHER}.md").read_bytes() == page_before        # the page, its title and claims stay
    assert "name_once" in _git(memory, "log", "-1", "--format=%B")
    rows = [r for r in web_settle.list_settled(memory) if r["rule"] == "name_once"]
    assert rows and rows[0]["group"] == "sleep" and rows[0]["reason"] == inbox_tend.RULES["name_once"]
    # They come up in a second conversation: the question is raised again, once, the normal way.
    page = memory / "entities" / f"{TEACHER}.md"
    parsed = markdown_parser.parse(page)
    markdown_parser.write(page, {**parsed.frontmatter, "source_episodes": ["ep_2026-11-01_001", "ep_2026-11-20_001"]},
                          parsed.body)
    assert role_people.ensure_question(memory, TEACHER, owner_fm=OWNER_FM) is not None
    assert len(_name_questions(memory)) == 1


def test_a_settle_the_person_took_back_is_theirs_and_never_retired_again(tmp_path):
    memory, path = _asked_bank(tmp_path)
    decision, _ = _settle(memory, path)
    asyncio.run(inbox_tend.apply(memory, type("S", (), {"memory_path": memory})(), decision))
    restored, paths, lines, _rec = inbox_tend.undo(memory, path.stem)
    web_settle.commit_sync(memory, web_settle.commit_message("Sleep's settle undone", lines, authors=["user"]), paths)
    bank_index.invalidate()
    again = memory / "inbox" / f"{restored}.md"
    assert again.exists()
    assert _settle(memory, again) == (None, "undone")
    assert role_people.ensure_question(memory, TEACHER, owner_fm=OWNER_FM) is None    # the open one is theirs: no second


def test_a_question_on_a_page_that_came_up_again_or_was_deferred_is_not_retired(tmp_path):
    memory = _bank(tmp_path, ["ep_2026-11-01_001", "ep_2026-11-09_001"])
    path = role_people.ensure_question(memory, TEACHER, owner_fm=OWNER_FM)
    assert _settle(memory, path)[0] is None
    page = memory / "entities" / f"{TEACHER}.md"
    parsed = markdown_parser.parse(page)
    markdown_parser.write(page, {**parsed.frontmatter, "source_episodes": ["ep_2026-11-01_001"]}, parsed.body)
    assert _settle(memory, path)[0].rule == "name_once"      # one conversation now: the rule would retire it …
    item = markdown_parser.parse(path)
    markdown_parser.write(path, {**item.frontmatter, "remind_after": "2999-01-01"}, item.body)
    assert _settle(memory, path) == (None, "deferred")       # … unless the person put it off
