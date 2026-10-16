"""Reviewer reproductions for fix/placeholder-people (synthetic data only). Each test asserts the SAFE behaviour,
so a failure is the blocker reproduced."""
from __future__ import annotations

from pathlib import Path

from api.services import markdown_parser, role_people
from api.services.claims import parse_claims
from api.services.clarification_manager import ClarificationManager
from api.tests.test_role_people import (
    EP_A, OWNER_FM, OWNER_ID, TS_A, _claim, _git, _git_bank, _page, _person, _resolve,
)


# --- B1: the repair's evidence reader takes a qualified relation for the bare one ----------------------------------


def _father_bank(memory: Path, predicate: str) -> None:
    (memory / "entities").mkdir(parents=True, exist_ok=True)
    _page(memory, OWNER_ID, {**OWNER_FM}, "The owner.")
    _page(memory, "alpha-owner's-father", {"name": "Alpha Owner's father"}, "## Summary\nA retired engineer.",
          [_claim("c-father-1", "alpha-owner's-father", "retired-from", "Engineering", object_kind="literal")])
    _page(memory, "carl-example", {"name": "Carl Example"}, "## Summary\nThe owner's spouse's dad.",
          [_claim("c-carl-1", "carl-example", predicate, OWNER_ID)])


def test_b1_a_father_in_law_is_not_the_owners_father(tmp_path):
    memory = tmp_path / "memory"
    _father_bank(memory, "father-in-law-of")
    plan = role_people.survey(memory)
    assert plan.merges == [], f"would merge the father placeholder into the father-in-law: {plan.merges}"


def test_b1_a_business_partner_is_not_the_owners_partner(tmp_path):
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    _page(memory, OWNER_ID, {**OWNER_FM}, "The owner.",
          [_claim("c-owner-1", OWNER_ID, "business-partner-of", "dana-example")])
    _page(memory, "alpha-owner's-partner", {"name": "Alpha Owner's partner"}, "## Summary\nLives with the owner.")
    _page(memory, "dana-example", {"name": "Dana Example"}, "## Summary\nCo-founded a company with the owner.")
    plan = role_people.survey(memory)
    assert plan.merges == [], f"would merge the partner placeholder into the business partner: {plan.merges}"


def test_b1_apply_folds_the_father_page_into_the_father_in_law(tmp_path):
    memory = _git_bank(tmp_path)
    _father_bank(memory, "father-in-law-of")
    _git(memory, "add", "-A")
    _git(memory, "commit", "-q", "-m", "seed")
    role_people.apply(memory, sleep_running=lambda: False)
    carl = markdown_parser.parse(memory / "entities" / "carl-example.md")
    assert "father" not in (carl.frontmatter.get("owner_roles") or []), "Carl now holds 'father' on the record"
    assert "c-father-1" not in {c.id for c in parse_claims(carl.body)}, "the father's claims moved onto Carl"


# --- B2: a common given name is read as a relation ----------------------------------------------------------------


def test_b2_a_person_named_tia_is_a_name():
    assert role_people.parse("Tia", role_people.owner_names(OWNER_FM)) is None


def test_b2_an_aunt_mention_never_lands_on_a_friend_named_tia():
    existing = [{"id": OWNER_ID, "frontmatter": OWNER_FM},
                {"id": "tia", "frontmatter": {"name": "Tia", "type": "person", "status": "active"}}]
    extracted = [{"episode_id": EP_A, "entities": [_person("mi tia", EP_A, TS_A)], "relationships": []}]
    role_people.canonicalize(extracted, existing, OWNER_FM)
    assert extracted[0]["entities"][0]["name"] != "Tia", "the aunt's mention was renamed onto the friend's page"


def test_b2_the_repair_leaves_a_named_tia_alone(tmp_path):
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    _page(memory, OWNER_ID, {**OWNER_FM}, "The owner.")
    _page(memory, "tia", {"name": "Tia"}, "## Summary\nA friend from the climbing gym.")
    plan = role_people.survey(memory)
    assert plan.placeholders == 0 and plan.asked == 0, \
        f"the repair marks Tia unnamed and asks 'What's the name of your tia?': {plan.counts()}"


# --- B3: legacy possible-duplicate items now fold whole pages -----------------------------------------------------


def test_b3_an_old_duplicate_question_about_a_mention_does_not_fold_a_page_promoted_since(tmp_path):
    memory = _git_bank(tmp_path)
    _page(memory, OWNER_ID, {**OWNER_FM}, "The owner.")
    _page(memory, "sam-example", {"name": "Sam Example"}, "## Summary\nA colleague.")
    # Stage 2, conversation A: "Sam" might be Sam Example -> a possible-duplicate question about the MENTION.
    item = ClarificationManager(memory).create(
        entity_name="Sam", source_episode=EP_A, uncertainty_type="Possible duplicate of Sam Example",
        suggested_classification="person", suggested_confidence=0.6, source_context="Sam helped with the move.")
    assert item
    # Later conversations: a page "Sam" is promoted, with what they said about that Sam.
    _page(memory, "sam", {"name": "Sam", "source_episodes": ["ep_2026-09-25_001", "ep_2026-09-26_001"]},
          "## Summary\nA neighbour's child who plays violin.",
          [_claim("c-sam-1", "sam", "plays", "Violin", object_kind="literal")])
    _git(memory, "add", "-A")
    _git(memory, "commit", "-q", "-m", "seed")
    # The person answers the old question about conversation A's mention.
    _resolve(memory, item, action="merge", merge_target="sam-example")
    assert (memory / "entities" / "sam.md").exists(), "the whole later 'Sam' page was folded into Sam Example"
