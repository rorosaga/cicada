"""The relationship-direction replay battery (`benchmarks/consolidation/direction_battery.py`): its cases are well formed and
its judge tells a role written the right way round from a reversed one, in three languages, for a role the other side
holds, one the owner holds and a symmetric one. No model: a fake Stage 1 stands in."""
from __future__ import annotations

import json
from datetime import date

import pytest

from benchmarks.consolidation import direction_battery as battery

CLOCK = date(2026, 11, 23)


def case(case_id: str) -> dict:
    return next(c for c in battery.load_cases() if c["id"] == case_id)


def rel(source: str, label: str, target: str) -> dict:
    return {"source": source, "label": label, "target": target}


def test_every_case_is_complete_and_the_fixture_ones_resolve():
    cases = battery.load_cases()
    assert len({c["id"] for c in cases}) == len(cases)
    assert {c["kind"] for c in cases} == {"asymmetric", "owner-held", "symmetric"}
    assert {c["lang"] for c in cases} >= {"en", "es", "fr"}
    for c in cases:
        assert c["holder"] and c["other"] and c["role"] and c["family"], c["id"]
        owner, turns, day = battery.conversation_of(c, CLOCK)
        assert owner and turns and turns[0], c["id"]
        episode = battery.episode_of(c, CLOCK, 1)
        assert episode["content"].startswith("user: ") and episode["id"].startswith(f"ep_{day.isoformat()}_")
    # the ones that are the benchmark's own R1 and R2 conversations
    assert "brother-in-law" in battery.episode_of(case("fx-en-brother-in-law"), CLOCK, 1)["content"]
    assert "beau-frère" in battery.episode_of(case("fx-fr-beau-frere"), CLOCK, 1)["content"]
    assert "landlord" in battery.episode_of(case("fx-en-landlord"), CLOCK, 1)["content"]


@pytest.mark.parametrize("case_id, claim, verdict", [
    # the person's brother-in-law: the holder is the subject of "<role> of", the object of "has <role>"
    ("fx-en-brother-in-law", rel("Marc", "brother-in-law of", "Noor Haddad"), "right"),
    ("fx-en-brother-in-law", rel("Marc", "is the brother-in-law of", "Noor Haddad"), "right"),
    ("fx-en-brother-in-law", rel("Noor Haddad", "has brother-in-law", "Marc"), "right"),
    ("fx-en-brother-in-law", rel("Noor Haddad", "brother-in-law of", "Marc"), "reversed"),
    ("fx-en-brother-in-law", rel("Marc", "has brother-in-law", "Noor Haddad"), "reversed"),
    # the other side's role is as right as the holder's: "<owner> sister-in-law of <holder>" is not what was said
    ("fx-en-brother-in-law", rel("Noor Haddad", "sister-in-law of", "Marc"), "right"),
    ("fx-fr-beau-frere", rel("Marc", "beau-frère de", "Noor Haddad"), "right"),
    ("fx-fr-beau-frere", rel("Noor Haddad", "beau-frère de", "Marc"), "reversed"),
    ("fx-fr-beau-frere", rel("Noor Haddad", "a pour beau-frère", "Marc"), "right"),
    ("es-suegra", rel("Lucía Barrios", "suegra de", "Carmen Ibarra"), "reversed"),
    ("es-suegra", rel("Carmen Ibarra", "suegra de", "Lucía Barrios"), "right"),
    ("es-suegra", rel("Lucía Barrios", "tiene suegra", "Carmen Ibarra"), "right"),
    # a verb said from the report's side: "reports to" makes its object the manager
    ("en-manager", rel("Wen Calloway", "reports to", "Dana Whitlock"), "right"),
    ("en-manager", rel("Dana Whitlock", "reports to", "Wen Calloway"), "reversed"),
    ("en-manager", rel("Dana Whitlock", "manages", "Wen Calloway"), "right"),
    ("en-manager", rel("Wen Calloway", "manages", "Dana Whitlock"), "reversed"),
    ("fr-cheffe", rel("Inès Maillard", "rend compte à", "Camille Perrin"), "right"),
    # a passive makes its object the one who holds the role, even when the label begins with the role's word
    ("fr-mentor", rel("Inès Maillard", "mentored by", "Étienne Roche"), "right"),
    ("fr-mentor", rel("Étienne Roche", "mentored by", "Inès Maillard"), "reversed"),
    ("fr-mentor", rel("Étienne Roche", "mentor of", "Inès Maillard"), "right"),
    ("en-tenant", rel("Aroha Telford", "tenant of", "Wen Calloway"), "right"),
    ("en-tenant", rel("Wen Calloway", "tenant of", "Aroha Telford"), "reversed"),
    ("en-tenant", rel("Wen Calloway", "landlord of", "Aroha Telford"), "right"),
    # the parent: "<child> daughter of <parent>" is the inverse role, held by the other side
    ("es-padre", rel("Lucía Barrios", "hija de", "Joaquín Salas"), "right"),
    ("es-padre", rel("Joaquín Salas", "hija de", "Lucía Barrios"), "reversed"),
])
def test_the_judge_reads_which_side_holds_the_role(case_id, claim, verdict):
    assert battery.judge_relationship(case(case_id), claim) == verdict


def test_a_relationship_about_something_else_or_a_third_party_is_not_a_statement_of_the_role():
    c = case("fx-en-brother-in-law")
    assert battery.judge_relationship(c, rel("Marc", "lives in", "Annecy")) is None
    assert battery.judge_relationship(c, rel("Marc", "helps with", "Noor Haddad")) is None
    assert battery.judge_relationship(c, rel("Marc", "brother-in-law of", "Idris")) is None      # a third person
    assert battery.judge_relationship(c, rel("Noor Haddad", "family", "Noor Haddad")) is None    # the same side twice
    # a role word inside a longer word is not the role ("ami" in "family")
    assert battery.judge_relationship(case("fr-ami"), rel("Baptiste", "family of", "Inès Maillard")) is None


def test_a_role_the_owner_holds_must_stay_the_owners():
    c = case("en-owner-manager")
    assert battery.judge_relationship(c, rel("Wen Calloway", "manages", "Elio Park")) == "right"
    assert battery.judge_relationship(c, rel("Elio Park", "reports to", "Wen Calloway")) == "right"
    assert battery.judge_relationship(c, rel("Elio Park", "manages", "Wen Calloway")) == "reversed"
    assert battery.judge_relationship(c, rel("Wen Calloway", "reports to", "Elio Park")) == "reversed"
    c = case("en-owner-landlord")
    assert battery.judge_relationship(c, rel("Wen Calloway", "landlord of", "Pavel Nowak")) == "right"
    assert battery.judge_relationship(c, rel("Pavel Nowak", "landlord of", "Wen Calloway")) == "reversed"


def test_a_symmetric_relation_is_never_reversed_only_doubled():
    c = case("es-hermana")
    one = battery.judge_extraction(c, [rel("Marisol", "hermana de", "Lucía Barrios")])
    other_way = battery.judge_extraction(c, [rel("Lucía Barrios", "hermana de", "Marisol")])
    both = battery.judge_extraction(c, [rel("Marisol", "hermana de", "Lucía Barrios"), rel("Lucía Barrios", "hermana de", "Marisol")])
    none = battery.judge_extraction(c, [rel("Marisol", "se muda a", "Valencia")])
    assert (one["outcome"], other_way["outcome"], both["outcome"], none["outcome"]) == ("right", "right", "doubled", "none")
    assert one["reversed"] == other_way["reversed"] == both["reversed"] == 0


def test_an_extraction_is_wrong_when_any_relation_is_reversed_even_beside_a_right_one():
    c = case("fx-en-brother-in-law")
    assert battery.judge_extraction(c, [rel("Marc", "brother-in-law of", "Noor Haddad")])["outcome"] == "right"
    assert battery.judge_extraction(c, [rel("Noor Haddad", "brother-in-law of", "Marc")])["outcome"] == "reversed"
    assert battery.judge_extraction(c, [rel("Marc", "brother-in-law of", "Noor Haddad"),
                                        rel("Noor Haddad", "brother-in-law of", "Marc")])["outcome"] == "mixed"
    assert battery.judge_extraction(c, [])["outcome"] == "none"


def test_rows_summarise_by_case_family_language_and_kind_and_a_failed_call_is_not_a_miss(tmp_path):
    cases = {c["id"]: c for c in battery.load_cases()}
    raw = [
        {"case": "fx-en-brother-in-law", "relationships": [rel("Noor Haddad", "brother-in-law of", "Marc")]},
        {"case": "fx-en-brother-in-law", "relationships": [rel("Marc", "brother-in-law of", "Noor Haddad")]},
        {"case": "fx-fr-beau-frere", "relationships": None},
        {"case": "es-hermana", "relationships": [rel("Marisol", "hermana de", "Lucía Barrios")]},
    ]
    (tmp_path / "raw.jsonl").write_text("".join(json.dumps(r) + "\n" for r in raw))
    rows = battery.rows_from_raw(raw, cases)
    s = battery.summarise(rows)
    assert s["total"]["runs"] == 4 and s["total"]["wrong"] == 1 and s["total"]["failed"] == 1
    assert s["family"]["kinship"]["runs"] == 4 and s["lang"]["en"]["wrong"] == 1 and s["kind"]["symmetric"]["wrong"] == 0
    assert "TOTAL reversed 1/4" in battery.report(rows)


def test_the_prompt_states_the_rule_for_any_role_and_names_no_role_of_the_benchmark():
    """The fix is a rule (the role in a label is the source's), shown with examples that are not the benchmark's own."""
    from api.services.entity_extractor import EXTRACTION_SYSTEM_PROMPT

    low = " ".join(EXTRACTION_SYSTEM_PROMPT.split())
    rule = low.split("A ROLE IN A LABEL BELONGS TO THE SOURCE.")[1].split("- \"works at\"")[0]
    assert "must read as a true sentence" in rule and "in any language" in rule
    assert 'source X, label "aunt of", target the user' in rule and 'source the user, label "manager of"' in rule
    # no word fitted to the benchmark's two roles
    for word in ("brother-in-law", "landlord", "beau-fr"):
        assert word not in rule.lower()
    # the owner's own working relationships stay as the earlier rule has them (the user first, "reports to")
    assert '"<user> reports to <manager>"' in low
