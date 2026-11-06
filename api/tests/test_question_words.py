"""Questions a person can answer: the words (``inbox_wording.present_options``, the voice, the decay answers).

Every fixture here is synthetic: invented pages (``alpha-project``, ``bob-example``), invented episode ids and dates.
Nothing is read from a bank and nothing is written to one by the wording (it is worded at read)."""
from __future__ import annotations

import json
from datetime import date

import pytest

from api.services import (bank_index, inbox_catchup, inbox_questions, inbox_service, inbox_wording, markdown_parser,
                          mcp_tools)
from api.services.claims import Claim, write_claims

TODAY = "2026-11-06"
OWNER = "owner-example"


def claim(cid, obj, *, episodes=(), recorded_at="2026-10-01", valid_from=None, predicate="value-of-team-size"):
    return Claim(id=cid, text=f"alpha-project {predicate} {obj}", subject="alpha-project", predicate=predicate,
                 object=obj, valid_from=valid_from, recorded_at=recorded_at, source_episodes=list(episodes))


def conflict(options, *, predicate="description", question="", **extra):
    return {"kind": "conflict", "entity_id": "alpha-project", "entity_name": "Alpha Project", "predicate": predicate,
            "question": question, "options": options, **extra}


def side(key, label, *, claim_id=None, desc=None, observed=None, last=None, **extra):
    o = {"key": key, "label": label, "claim_id": claim_id, "description": desc, "observed_at": observed,
         "last_referenced": last}
    o.update(extra)
    return {k: v for k, v in o.items() if v is not None or k in ("claim_id",)}


BOTH = {"key": "both", "label": "Both are true (different contexts)"}


# --------------------------------------------------------------------------- A1: a bare value says what it is of

def test_a_bare_value_question_names_what_the_values_are_of():
    fm = conflict([side("a", "6"), side("b", "10"), BOTH], predicate="value-of-team-size",
                  question="Which is true about Alpha Project (value-of-team-size)?")
    other = inbox_wording.spoken(fm, TODAY, page_fm={"type": "project"})
    assert other.question == "Which is right for Alpha Project's team size: 6 or 10?"
    own = inbox_wording.spoken({**fm, "entity_id": OWNER}, TODAY, owner_id=OWNER, page_fm={"type": "person"})
    assert own.question == "Which is right for your team size: 6 or 10?"


def test_a_name_ending_in_s_takes_the_apostrophe_alone():
    fm = conflict([side("a", "6"), side("b", "10")], predicate="value-of-shelf-height",
                  question="Which is true about Marker Adapters (value-of-shelf-height)?", entity_name="Marker Adapters")
    assert inbox_wording.spoken(fm, TODAY).question == "Which is right for Marker Adapters' shelf height: 6 or 10?"


def test_another_generic_predicate_keeps_the_old_question():
    fm = conflict([side("a", "red"), side("b", "blue")], predicate="likes",
                  question="Which is true about Alpha Project (likes)?")
    assert inbox_wording.spoken(fm, TODAY).question == "Which is right about Alpha Project: red or blue?"


# --------------------------------------------------------------------------- A2 / A5: a description conflict

def test_a_description_conflict_has_no_date_it_never_had():
    fm = conflict([
        side("a", "Still in beta", desc="Existing description, last mentioned in March: still being tested.",
             observed="2026-11-05", last="2026-11-05"),
        side("b", "Shipped", desc="New record: shipped to production.", observed="2026-11-05", last="2026-11-05"),
        BOTH])
    shown = inbox_wording.present_options(fm, TODAY)
    assert [(o["observed_at"], o["last_referenced"]) for o in shown[:2]] == [(None, None), (None, None)]
    assert shown[0]["description"] == "Last mentioned in March: still being tested."
    assert shown[1]["description"] == "Shipped to production."
    said = inbox_wording.spoken(fm, TODAY, page_fm={"type": "project"})
    assert said.reason == "Two things I have about Alpha Project disagree, and I can't tell which is right."
    assert "yesterday" not in said.reason and "ago" not in said.reason


@pytest.mark.parametrize("stored, expected", [
    ("Existing undated note, kept: works on the parser", "Kept: works on the parser"),
    ("From the existing article: a draft", "A draft"),
    ("Newer summary: ships in May", "Ships in May"),
    ("Current claim, said twice: it is a CLI", "Said twice: it is a CLI"),
    ("Described on the page as of 2026-11-05", None),
    ("Existing description from March says it is a draft", "From March says it is a draft"),
    ("New undated record: shipped", "Shipped"),
    ("From the existing description", None),
    ("From the new description on May 3, 2026", "On May 3, 2026"),
    ("Existing record stating attendance in May", "Stating attendance in May"),
    ("Existing note recorded as of 2026-10-06, up from 70.", "Recorded as of 2026-10-06, up from 70."),
    ("New ideas came up later", "New ideas came up later"),
    ("Just a plain clause", "Just a plain clause"),
])
def test_the_checks_own_working_words_are_dropped_from_a_description(stored, expected):
    fm = conflict([side("a", "x", desc=stored), side("b", "y")])
    assert inbox_wording.present_options(fm, TODAY)[0].get("description") == expected


def test_a_label_that_says_the_existing_claim_is_left_alone():
    fm = conflict([side("a", "the existing claim"), side("b", "the new claim")])
    assert [o["label"] for o in inbox_wording.present_options(fm, TODAY)] == ["the existing claim", "the new claim"]


# --------------------------------------------------------------------------- A3 / A4: a claim-backed side

def test_a_side_is_dated_by_when_it_was_said_not_when_it_was_read():
    c = claim("clm_a", "6", episodes=["ep_2026-03-02_001"], recorded_at="2026-11-05")
    fm = conflict([side("a", "6", claim_id="clm_a", desc="Last mentioned 2026-11-05 · yesterday · extracted from "
                                                         "ep_2026-03-02_001", observed="2026-11-05",
                        last="2026-11-05"), side("b", "10"), BOTH], predicate="value-of-team-size")
    shown = inbox_wording.present_options(fm, TODAY, claims=[c])
    assert shown[0]["observed_at"] == shown[0]["last_referenced"] == "2026-03-02"
    assert shown[0]["description"] == "Last mentioned 2026-03-02 · 8 months ago"
    assert "ep_" not in json.dumps([o.get("description") for o in shown])


def test_the_second_value_off_the_page_is_dated_by_its_conversation():
    fm = conflict([side("a", "6", claim_id="clm_gone", desc="Last mentioned 2026-11-05 · yesterday · extracted from "
                                                            "ep_2026-09-10_002", observed="2026-11-05",
                        last="2026-11-05"), side("b", "10"), BOTH], predicate="value-of-team-size")
    shown = inbox_wording.present_options(fm, TODAY, claims=[])
    assert shown[0]["last_referenced"] == "2026-09-10"
    assert shown[0]["description"] == "Last mentioned 2026-09-10 · 8 weeks ago"
    assert shown[0]["source_episode"] == "ep_2026-09-10_002"      # kept readable after the words were rewritten


def test_a_side_with_no_conversation_is_undated_not_dated_by_the_raise_day():
    fm = conflict([side("a", "6", claim_id="clm_gone", desc="Last mentioned 2026-11-05 · yesterday",
                        observed="2026-11-05", last="2026-11-05"), side("b", "10"), BOTH],
                  predicate="value-of-team-size")
    shown = inbox_wording.present_options(fm, TODAY, claims=[])
    assert shown[0]["observed_at"] is None and shown[0]["last_referenced"] is None
    assert shown[0]["description"] == "Last mention unknown"


def test_another_writers_prose_on_a_claim_backed_side_stays():
    fm = conflict([side("a", "6", claim_id="clm_a", desc="Said in the planning call"), side("b", "10")],
                  predicate="value-of-team-size")
    assert inbox_wording.present_options(fm, TODAY, claims=[])[0]["description"] == "Said in the planning call"


def test_a_merged_option_keeps_its_words_and_loses_the_raise_date():
    # `merge_options_into` adopts the incoming claim id on an open prose answer and bumps its date to the raise day.
    fm = conflict([side("a", "Shipped", claim_id="clm_adopted", desc="Existing description, shipped to production",
                        observed="2026-10-01", last="2026-11-05"), side("b", "Still testing"), BOTH])
    shown = inbox_wording.present_options(fm, TODAY, claims=[])
    assert shown[0]["claim_id"] == "clm_adopted" and shown[0]["key"] == "a"
    assert shown[0]["last_referenced"] is None
    assert shown[0]["description"] == "Shipped to production"


# --------------------------------------------------------------------------- the reasons

def _two(ep_a, ep_b, rec_a="2026-10-01", rec_b="2026-10-02"):
    claims = [claim("clm_a", "6", episodes=ep_a, recorded_at=rec_a), claim("clm_b", "10", episodes=ep_b, recorded_at=rec_b)]
    fm = conflict([side("a", "6", claim_id="clm_a", desc="Last mentioned x · y"),
                   side("b", "10", claim_id="clm_b", desc="Last mentioned x · y"), BOTH],
                  predicate="value-of-team-size")
    return fm, claims


def test_two_values_from_one_conversation_say_so():
    fm, claims = _two(["ep_2026-09-10_001"], ["ep_2026-09-10_001"])
    said = inbox_wording.spoken(fm, TODAY, claims=claims)
    assert said.reason == "Both came up in the same conversation, so I can't tell whether one replaces the other."


def test_two_values_said_the_same_day_say_so():
    fm, claims = _two(["ep_2026-09-10_001"], ["ep_2026-09-10_002"])
    said = inbox_wording.spoken(fm, TODAY, claims=claims)
    assert said.reason == "Both were said the same day (about 8 weeks ago), so I can't tell which is current."


def test_a_side_with_two_conversations_is_not_one_conversation():
    fm, claims = _two(["ep_2026-09-10_001", "ep_2026-09-11_001"], ["ep_2026-09-10_001"])
    said = inbox_wording.spoken(fm, TODAY, claims=claims)
    assert "same conversation" not in said.reason


def test_a_side_with_no_date_is_never_the_same_day():
    fm, claims = _two([], ["ep_2026-09-10_001"], rec_a="", rec_b="")
    claims[0].recorded_at = None
    said = inbox_wording.spoken(fm, TODAY, claims=claims)
    assert "same day" not in said.reason and "same conversation" not in said.reason
    assert said.reason.startswith("I have both 6 and 10 (about 8 weeks ago)") or "6" in said.reason


def test_ordinary_two_sided_reason_names_both_ages():
    fm, claims = _two(["ep_2026-03-02_001"], ["ep_2026-09-10_001"])
    said = inbox_wording.spoken(fm, TODAY, claims=claims)
    assert said.reason == ("I have both 6 (about 8 months ago) and 10 (about 8 weeks ago), and I can't tell which "
                           "is current.")


def test_three_answers_are_counted_with_the_latest():
    claims = [claim("clm_a", "6", episodes=["ep_2026-03-02_001"]), claim("clm_b", "10", episodes=["ep_2026-09-10_001"]),
              claim("clm_c", "12", episodes=["ep_2026-05-01_001"])]
    fm = conflict([side("a", "6", claim_id="clm_a"), side("b", "10", claim_id="clm_b"),
                   side("c", "12", claim_id="clm_c"), BOTH], predicate="value-of-team-size")
    said = inbox_wording.spoken(fm, TODAY, claims=claims)
    assert said.reason == "I have 3 different answers, the latest about 8 weeks ago, and I can't tell which is current."


def test_a_third_answer_with_no_date_stops_the_same_conversation_and_same_day_reasons():
    claims = [claim("clm_a", "6", episodes=["ep_2026-09-10_001"]), claim("clm_b", "10", episodes=["ep_2026-09-10_001"])]
    fm = conflict([side("a", "6", claim_id="clm_a"), side("b", "10", claim_id="clm_b"), side("c", "12"), BOTH],
                  predicate="value-of-team-size")
    said = inbox_wording.spoken(fm, TODAY, claims=claims)
    assert "same conversation" not in said.reason and "same day" not in said.reason
    other_day = [claim("clm_a", "6", episodes=["ep_2026-09-10_001"]), claim("clm_b", "10", episodes=["ep_2026-09-10_002"])]
    said = inbox_wording.spoken(fm, TODAY, claims=other_day)
    assert "same conversation" not in said.reason and "same day" not in said.reason


def test_a_count_of_things_is_true_of_the_answers_offered():
    two = conflict([side("a", "x"), side("b", "y"), BOTH])
    assert inbox_wording.spoken(two, TODAY).reason.startswith("Two things I have")
    three = conflict([side("a", "x"), side("b", "y"), side("c", "z"), BOTH])
    assert inbox_wording.spoken(three, TODAY).reason.startswith("Several things I have")


# --------------------------------------------------------------------------- idempotence

def test_presenting_twice_is_presenting_once():
    claims = [claim("clm_a", "6", episodes=["ep_2026-03-02_001"])]
    fm = conflict([side("a", "6", claim_id="clm_a", desc="Last mentioned 2026-11-05 · yesterday · extracted from "
                                                         "ep_2026-03-02_001", observed="2026-11-05",
                        last="2026-11-05"),
                   side("b", "Existing description: ten", desc="Existing description: ten"), BOTH],
                  predicate="value-of-team-size")
    once = inbox_wording.present_options(fm, TODAY, claims=claims)
    twice = inbox_wording.present_options({**fm, "options": once}, TODAY, claims=claims)
    assert once == twice
    again = inbox_wording.present_options({**fm, "options": once}, TODAY)      # even with no claims at hand
    assert again == once


def test_presenting_never_touches_the_stored_options_or_keys():
    fm = conflict([side("a", "x", claim_id="clm_a", desc="Existing description, x", observed="2026-11-05",
                        last="2026-11-05"), side("b", "y"), BOTH])
    before = json.dumps(fm, sort_keys=True)
    shown = inbox_wording.present_options(fm, TODAY, claims=[])
    assert json.dumps(fm, sort_keys=True) == before
    assert [o["key"] for o in shown] == ["a", "b", "both"] and [o.get("claim_id") for o in shown][:1] == ["clm_a"]


def test_only_a_conflict_is_presented():
    fm = {"kind": "decay", "options": [side("keep", "Yes", desc="Existing description, x", observed="2026-11-05")]}
    assert inbox_wording.present_options(fm, TODAY) == fm["options"]


# --------------------------------------------------------------------------- A11: a page id as an answer

def test_a_relation_answer_that_is_a_page_id_is_the_pages_name():
    names = {"bob-example": "Bob Example"}
    fm = conflict([side("a", "bob-example", claim_id="clm_a"), side("b", "carol", claim_id="clm_b"), BOTH],
                  predicate="reports-to")
    shown = inbox_wording.present_options(fm, TODAY, claims=[], page_name=names.get)
    assert [o["label"] for o in shown] == ["Bob Example", "carol", "Both are true (different contexts)"]
    assert [o["key"] for o in shown] == ["a", "b", "both"]
    still = {**fm, "asks": "still", "options": [side("a", "bob-example", claim_id="clm_a"), BOTH]}
    said = inbox_wording.spoken(still, TODAY, page_fm={"type": "person"}, owner_id=OWNER, page_name=names.get)
    assert "Bob Example" in said.question or "bob-example" not in said.question


def test_a_value_answer_is_never_turned_into_a_page_name():
    fm = conflict([side("a", "bob-example", claim_id="clm_a"), side("b", "x", claim_id="clm_b")],
                  predicate="value-of-nickname")
    shown = inbox_wording.present_options(fm, TODAY, claims=[], page_name={"bob-example": "Bob Example"}.get)
    assert shown[0]["label"] == "bob-example"


# --------------------------------------------------------------------------- A6: the voice of a stored question

@pytest.mark.parametrize("stored, expected", [
    ("Have I moved to the new office?", "Have you moved to the new office?"),
    ("Am I still on the platform team?", "Are you still on the platform team?"),
    ("Was I told about my review?", "Were you told about your review?"),
    ("I'm unsure: is it mine or the team's?", "I'm unsure: is it mine or the team's?"),
])
def test_a_first_person_question_is_said_to_the_person(stored, expected):
    assert inbox_wording.stored_in_your_voice(stored) == expected


@pytest.mark.parametrize("stored", ["Did Phase I end in March?", "Is Series I the one you meant?", "Whose is the mine in Peru?",
                                    "Is that mine or the team's?"])
def test_a_numeral_or_the_word_mine_leaves_the_question_as_written(stored):
    assert inbox_wording.stored_in_your_voice(stored) == stored


def test_a_spanish_question_keeps_its_own_me():
    assert inbox_wording.stored_in_your_voice("¿Se me olvidó pagar la matrícula?") == "¿Se me olvidó pagar la matrícula?"


def test_a_contraction_after_a_name_is_never_a_numeral():
    assert inbox_wording.stored_in_your_voice("Is the Mac I'm using a laptop?") == "Is the Mac you're using a laptop?"


def test_a_capitalised_question_word_before_i_still_turns():
    assert inbox_wording.stored_in_your_voice("When I moved, was it May?") == "When you moved, was it May?"
    assert inbox_wording.stored_in_your_voice("My review was in May, right?") == "Your review was in May, right?"


def test_a_question_that_already_says_you_is_left_alone():
    q = "Have I got it right that you moved?"
    assert inbox_wording.stored_in_your_voice(q) == q


def test_a_quoted_first_person_word_leaves_the_whole_question():
    q = 'Did the note say "I will move" or something else?'
    assert inbox_wording.stored_in_your_voice(q) == q


def test_the_owner_named_in_a_safe_frame_is_you():
    names = ["Owner Example", "Owner", "the owner", "the user"]
    assert inbox_wording.stored_in_your_voice("Did Owner Example change teams?", owner_names=names) \
        == "Did you change teams?"
    assert inbox_wording.stored_in_your_voice("Does the owner still work at Alpha Corp?", owner_names=names) \
        == "Do you still work at Alpha Corp?"
    assert inbox_wording.stored_in_your_voice("Is Owner Example's role still engineer?", owner_names=names) \
        == "Is your role still engineer?"
    assert inbox_wording.stored_in_your_voice("Has Owner moved?", owner_names=names) == "Have you moved?"


def test_the_owner_named_anywhere_else_leaves_the_question_as_written():
    q = "Which of Owner Example and Bob Example works here?"
    assert inbox_wording.stored_in_your_voice(q, owner_names=["Owner Example"]) == q


@pytest.mark.parametrize("stored", ["Did Owner already attend Beta Con, or is he applying again?",
                                    "Did Owner save this, or is his link to it only a mention?",
                                    "Did Owner see it before, or is this the first time she's seen it?"])
def test_a_second_clause_still_about_them_leaves_the_question_as_written(stored):
    assert inbox_wording.stored_in_your_voice(stored, owner_names=["Owner"]) == stored


def test_a_stored_conflict_question_is_said_to_the_owner_about_their_own_page():
    fm = conflict([side("a", "x", claim_id="c1"), side("b", "y", claim_id="c2")], predicate="is-reading",
                  question="Does the owner read x or y?", entity_id=OWNER, entity_name="Owner Example")
    said = inbox_wording.spoken(fm, TODAY, page_fm={"type": "person"}, owner_id=OWNER, owner_name="Owner Example")
    assert said.question == "Do you read x or y?"


def test_another_persons_page_never_turns_the_owner_names():
    fm = conflict([side("a", "x", claim_id="c1"), side("b", "y", claim_id="c2")], predicate="is-reading",
                  question="Does Owner Example know whether Bob Example reads x or y?", entity_id="bob-example",
                  entity_name="Bob Example")
    said = inbox_wording.spoken(fm, TODAY, page_fm={"type": "person"}, owner_id=OWNER, owner_name="Owner Example")
    assert said.question == "Does Owner Example know whether Bob Example reads x or y?"


def test_a_page_that_is_not_a_person_turns_the_owner_by_the_banks_own_name():
    fm = conflict([side("a", "x", claim_id="c1"), side("b", "y", claim_id="c2")], predicate="is-reading",
                  question="Will Owner Example ship x or y?")
    said = inbox_wording.spoken(fm, TODAY, page_fm={"type": "project"}, owner_id=OWNER, owner_name="Owner Example")
    assert said.question == "Will you ship x or y?"
    nameless = inbox_wording.spoken(fm, TODAY, page_fm={"type": "project"}, owner_id=OWNER)
    assert nameless.question == "Will Owner Example ship x or y?"


# --------------------------------------------------------------------------- C2: "you mentioned" only where true

def test_a_pair_or_a_name_is_said_to_have_come_up_not_to_have_been_mentioned_by_you():
    pair = inbox_wording.spoken({"kind": "merge_suggestion", "entity_id": "alpha-project", "entity_name": "Alpha Project",
                                 "source_episode_timestamp": "2026-09-10T10:00:00+00:00",
                                 "merge_target_hint": "alpha-two"}, TODAY,
                                page_fm={"type": "project"}, other_fm={"type": "project", "name": "Alpha Two"})
    assert pair.reason.startswith("Alpha Project came up about 8 weeks ago, and it may be Alpha Two")
    assert "You mentioned" not in pair.reason
    named = inbox_wording.spoken({"kind": "clarification", "entity_id": "bob-example", "entity_name": "Bob",
                                  "asks": "name"}, TODAY, page_fm={"type": "person"})
    assert named.reason == "They've come up, but never by name."
    who = inbox_wording.spoken({"kind": "clarification", "entity_id": "bob-example", "entity_name": "Bob",
                                "suggested_classification": "person",
                                "source_episode_timestamp": "2026-09-10T10:00:00+00:00"}, TODAY,
                               page_fm={"type": "person"})
    assert who.reason == "Bob came up about 8 weeks ago, but not how you know them."
    shared = inbox_wording.spoken(
        {"kind": "merge_suggestion", "entity_id": "x", "entity_name": "Delta", "merge_target_hint": "delta-tool"},
        TODAY, other_fm={"name": "Delta", "type": "tool"}, same={"delta-tool": "tool"},
        titled=[{"id": "delta-tool", "name": "Delta", "type": "tool", "qualifier": "tool"}])
    assert shared.reason.startswith("Delta came up") and "You mentioned" not in shared.reason


def test_a_relation_named_page_starts_the_sentence_with_a_capital():
    said = inbox_wording.spoken({"kind": "clarification", "entity_id": "p", "entity_name": "Partner",
                                 "suggested_classification": "person"}, TODAY,
                                page_fm={"type": "person", "unnamed": True, "owner_roles": ["partner"]})
    assert said.reason == "Your partner came up, but not how you know them."


def test_a_name_in_lower_case_keeps_its_own_capitals_after_came_up():
    said = inbox_wording.spoken({"kind": "clarification", "entity_id": "p", "entity_name": "iPhone",
                                 "source_episode_timestamp": "2026-09-10T10:00:00+00:00"}, TODAY, page_fm={"type": "tool"})
    assert said.reason == "iPhone came up about 8 weeks ago, and I couldn't tell who or what it is."


# --------------------------------------------------------------------------- D2: a decay answer answers the question

def test_a_decay_answer_says_yes_or_no_to_the_question_it_follows():
    q = inbox_questions.decay_question("Alpha Project", "2026-03-02", TODAY)
    assert q["question"] == "Still tracking Alpha Project?"
    assert [(o["key"], o["label"]) for o in q["options"]] == [("keep", "Yes, keep it"), ("archive", "No, archive it")]
    assert inbox_questions.validate_question(q["question"], q["options"]) == []
    assert inbox_questions.DECAY_OPTION_KEYS == ("archive", "keep")


# --------------------------------------------------------------------------- E1: an alias edit said as a question

def _alias_edit(**over):
    fm = {"kind": "page_edit", "entity_id": "python", "entity_name": "Python", "origin": "wrong_alias",
          "question": "Cicada suggests a change to Python: “Flask” is the name of another thing, not of Python: it "
                      "is a web framework.",
          "reason": "“Flask” is the name of another thing, not of Python: it is a web framework.",
          "edit": {"remove_aliases": ["Flask"]}}
    fm.update(over)
    return fm


def test_a_wrong_alias_proposal_is_asked_as_a_question_with_its_why():
    said = inbox_wording.spoken(_alias_edit(), TODAY, page_fm={"type": "tool", "name": "Python"})
    assert said.question == "Should “Flask” stop being another name for Python?"
    assert said.reason == "it is a web framework."


@pytest.mark.parametrize("over", [
    {"origin": None}, {"edit": {"remove_aliases": ["Flask", "Django"]}}, {"edit": {"set_prose": "x"}},
    {"reason": "Tidy the page."},
])
def test_every_other_page_edit_keeps_its_stored_words(over):
    said = inbox_wording.spoken(_alias_edit(**over), TODAY, page_fm={"type": "tool", "name": "Python"})
    assert (said.question, said.reason) == ("", "")


def test_a_page_edit_is_served_with_the_alias_words_and_the_stored_question_otherwise(tmp_path):
    memory = tmp_path / "memory"
    for sub in ("entities", "inbox", "episodes"):
        (memory / sub).mkdir(parents=True)
    markdown_parser.write(memory / "entities" / "python.md", {"name": "Python", "type": "tool", "status": "active",
                                                              "confidence": 0.7}, "# Python\n")
    base = {"status": "pending", "created_date": "2026-11-01", "priority": 0.4}
    markdown_parser.write(memory / "inbox" / "inbox-001.md", {**base, **_alias_edit(), "required_input": "choice",
                          "options": [{"key": "apply", "label": "Remove it"}, {"key": "dismiss", "label": "Keep it"}]}, "b")
    markdown_parser.write(memory / "inbox" / "inbox-002.md", {**base, **_alias_edit(origin=None),
                          "question": "An agent suggests a change to Python: x", "required_input": "choice",
                          "options": [{"key": "apply", "label": "Apply"}, {"key": "dismiss", "label": "Leave it"}]}, "b")
    bank_index.invalidate()
    items = {i.id: i for i in inbox_service.load_inbox(memory, include_deferred=True)}
    assert items["inbox-001"].spoken_question == "Should “Flask” stop being another name for Python?"
    assert items["inbox-001"].spoken_reason == "it is a web framework."
    assert items["inbox-002"].spoken_question is None and items["inbox-002"].spoken_reason is None
    assert items["inbox-002"].question == "An agent suggests a change to Python: x"


# --------------------------------------------------------------------------- the three doors

def _bank(tmp_path):
    memory = tmp_path / "memory"
    for sub in ("entities", "inbox", "episodes"):
        (memory / sub).mkdir(parents=True)
    markdown_parser.write(memory / "_state.md", {"type": "state", "owner_id": OWNER}, "")
    markdown_parser.write(memory / "entities" / f"{OWNER}.md", {"name": "Owner Example", "type": "person",
                          "status": "active", "confidence": 0.9}, "# Owner\n")
    body = write_claims("# Alpha Project\n", [
        claim("clm_a", "6", episodes=["ep_2026-03-02_001"], recorded_at="2026-11-05"),
        claim("clm_b", "10", episodes=["ep_2026-09-10_001"], recorded_at="2026-09-12")])
    markdown_parser.write(memory / "entities" / "alpha-project.md",
                          {"name": "Alpha Project", "type": "project", "status": "active", "confidence": 0.7}, body)
    markdown_parser.write(memory / "inbox" / "inbox-001.md", {
        "kind": "conflict", "status": "pending", "priority": 0.5, "created_date": "2026-11-05",
        "required_input": "choice", "entity_id": "alpha-project", "entity_name": "Alpha Project",
        "predicate": "value-of-team-size", "question": "Which is true about Alpha Project (value-of-team-size)?",
        "options": [
            {"key": "a", "label": "6", "claim_id": "clm_a", "observed_at": "2026-11-05",
             "last_referenced": "2026-11-05", "description": "Last mentioned 2026-11-05 · yesterday · extracted from "
                                                             "ep_2026-03-02_001"},
            {"key": "b", "label": "10", "claim_id": "clm_b", "observed_at": "2026-09-12",
             "last_referenced": "2026-09-12", "description": "Last mentioned 2026-09-12 · 2 months ago"},
            BOTH]}, "b")
    bank_index.invalidate()
    return memory


def test_the_app_is_served_the_said_day_not_the_read_day(tmp_path):
    memory = _bank(tmp_path)
    item = inbox_service.load_inbox(memory)[0]
    by_key = {o.key: o for o in item.options}
    assert by_key["a"].last_referenced == by_key["a"].observed_at == "2026-03-02"
    assert by_key["a"].description == f"Last mentioned 2026-03-02 · {inbox_questions.humanize_age('2026-03-02', str(date.today()))}"
    assert by_key["a"].age_days > by_key["b"].age_days
    assert item.spoken_question == "Which is right for Alpha Project's team size: 6 or 10?"
    assert item.spoken_reason.startswith("I have both 6 (about ") and " and 10 (about " in item.spoken_reason
    stored = markdown_parser.parse(memory / "inbox" / "inbox-001.md").frontmatter["options"]
    assert stored[0]["last_referenced"] == "2026-11-05"          # worded at read, never written
    assert stored[0]["description"].endswith("extracted from ep_2026-03-02_001")


def test_the_agent_doors_say_the_same(tmp_path):
    memory = _bank(tmp_path)
    fm = markdown_parser.parse(memory / "inbox" / "inbox-001.md").frontmatter
    said = inbox_catchup.spoken_for(memory, inbox_catchup.Entry(ids=[], rank=0.0, use=0.0, fm=fm, created=""), fm, TODAY)
    assert said.question == "Which is right for Alpha Project's team size: 6 or 10?"
    seen, _cause, _rec = mcp_tools._agent_question(memory, fm, TODAY)
    listing = mcp_tools.render_question(seen, "", TODAY)
    assert "a) 6 — 8 months ago" in listing and "b) 10 — 8 weeks ago" in listing
    assert "yesterday" not in listing
    # the catch-up door gets options that were presented already, and says the same words
    again = inbox_catchup.spoken_for(memory, inbox_catchup.Entry(ids=[], rank=0.0, use=0.0, fm=seen, created=""),
                                     seen, TODAY)
    assert again == said


# --------------------------------------------------------------------------- the bump: when it was said, not read

def _open_question(memory, item_id="inbox-001"):
    inbox = memory / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    markdown_parser.write(inbox / f"{item_id}.md", {
        "kind": "conflict", "status": "pending", "entity_id": "alpha-project", "entity_name": "Alpha Project",
        "predicate": "value-of-team-size", "created_date": "2026-01-01", "question": "Which is right?",
        "options": [{"key": "a", "label": "6", "claim_id": "clm_a", "observed_at": "2026-03-02",
                     "last_referenced": "2026-03-02"},
                    {"key": "b", "label": "10", "claim_id": "clm_b", "observed_at": "2026-02-01",
                     "last_referenced": "2026-02-01"}]}, "b")
    return inbox / f"{item_id}.md"


def test_a_late_read_of_an_old_conversation_does_not_bump_but_a_later_saying_does(tmp_path):
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    for ep in ("ep_2026-03-02_001", "ep_2026-05-01_001"):
        markdown_parser.write(memory / "episodes" / f"{ep}.md", {"id": ep, "timestamp": f"{ep[3:13]}T10:00:00+00:00"}, "x")
    path = _open_question(memory)
    # clm_a: read late (recorded in November) but said on the day it already shows. clm_b: said again in May.
    claims = {"alpha-project": [claim("clm_a", "6", episodes=["ep_2026-03-02_001"], recorded_at="2026-11-04"),
                                claim("clm_b", "10", episodes=["ep_2026-02-01_001", "ep_2026-05-01_001"],
                                      recorded_at="2026-11-04")]}
    result = inbox_questions.refresh_open_questions(memory, claims, "2026-11-06", stale_after_days=9999)
    opts = {o["key"]: o for o in markdown_parser.parse(path).frontmatter["options"]}
    assert result["bumped"] == 1
    assert opts["a"]["last_referenced"] == "2026-03-02"            # the late read did not make it fresh
    assert opts["b"]["last_referenced"] == "2026-05-01"            # a later re-saying did
