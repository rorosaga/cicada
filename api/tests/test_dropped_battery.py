"""The passing-fact replay battery (`benchmarks/consolidation/dropped_battery.py`): its cases are well formed and its
judge tells a fact written as a claim from one written as prose only, one only on the book rails, and one dropped;
and a counter-case's plan or doubt is not the person's act. No model: a fake Stage 1 stands in. Also: Stage 1's prompt
asks for the person's own act on a named thing as a relationship, once, in the paragraph about relationships."""
from __future__ import annotations

from datetime import date

from api.services import entity_extractor
from benchmarks.consolidation import dropped_battery as battery

CLOCK = date(2026, 11, 23)


def case(case_id: str) -> dict:
    return next(c for c in battery.load_cases() if c["id"] == case_id)


def rel(source: str, label: str, target: str, starts: str | None = None) -> dict:
    return {"source": source, "label": label, "target": target, "starts": starts}


def ent(name: str, *facts: str, history: list | None = None) -> dict:
    return {"name": name, "type": "concept", "summary": "", "key_facts": list(facts), "history_entries": history or []}


def test_every_case_is_complete_and_the_fixture_one_resolves():
    cases = battery.load_cases()
    assert len({c["id"] for c in cases}) == len(cases)
    assert {c["polarity"] for c in cases} == {"said", "counter"}
    assert {c["lang"] for c in cases} >= {"en", "es", "fr"}
    assert {c["kind"] for c in cases} >= {"book", "film", "place", "course", "purchase", "race", "doctor", "decision"}
    for c in cases:
        assert c["thing"] and c["owner"], c["id"]
        if c["polarity"] == "counter":
            assert c["wrong"], c["id"]
        _, turns, _ = battery.conversation_of(c, CLOCK)
        assert turns and turns[0], c["id"]
        assert battery.episode_of(c, CLOCK, 1)["content"].startswith("user: ")
        # the person's own line says it: some line of theirs holds a token of the thing
        own = " ".join(battery.norm(t) for t in turns[0::2])
        assert battery._has(c["thing"] + c.get("also", []), own) or c["polarity"] == "counter", c["id"]
    assert "Everyday Things" in battery.episode_of(case("fx-book-recs"), CLOCK, 1)["content"]


def test_a_relationship_from_the_owner_to_the_thing_is_a_claim_and_it_is_dated():
    c = case("en-book")
    result = {"entities": [], "relationships": [rel("Priya Anand", "finished", "The Quiet Ledger", "2026-11-14")], "values": []}
    judged = battery.judge_extraction(c, result, CLOCK)
    assert judged["level"] == "claim" and judged["dated"] is True
    result["relationships"][0]["starts"] = "2026-11-10"
    assert battery.judge_extraction(c, result, CLOCK)["dated"] is False


def test_the_fact_in_key_facts_only_is_prose_not_a_claim():
    c = case("fx-book-recs")
    result = {"entities": [ent("The Design of Everyday Things", "Ines Varga read The Design of Everyday Things and loved it.")],
              "relationships": [rel("Don Norman", "wrote", "The Design of Everyday Things")], "values": []}
    assert battery.judge_extraction(c, result)["level"] == "prose"
    result["book_said"] = [{"name": "The Design of Everyday Things", "status": "finished", "stated": True}]
    assert battery.judge_extraction(c, result)["level"] == "status"
    result["relationships"].append(rel("Ines Varga", "read", "The Design of Everyday Things"))
    assert battery.judge_extraction(c, result)["level"] == "claim"
    assert battery.judge_extraction(c, {"entities": [ent("Don Norman")], "relationships": [], "values": []})["level"] == "dropped"


def test_a_value_on_the_thing_that_rests_on_the_line_is_a_claim():
    c = case("en-race")
    result = {"entities": [], "relationships": [],
              "values": [{"entity": "Harbourside 10k", "attribute": "finish time", "value": "52:10", "evidence_quote": None}]}
    assert battery.judge_extraction(c, result)["level"] == "claim"


def test_a_counter_case_is_wrong_only_when_the_label_says_the_act_was_done():
    c = case("es-place-plan")
    plan = {"entities": [], "relationships": [rel("Mateo Quiroga", "plans to visit", "Lisboa")], "values": []}
    assert battery.judge_extraction(c, plan)["wrong"] is False
    done = {"entities": [], "relationships": [rel("Mateo Quiroga", "visited", "Lisboa")], "values": []}
    assert battery.judge_extraction(c, done)["wrong"] is True
    other = {"entities": [], "relationships": [rel("Hermana (sin nombre)", "visited", "Lisboa")], "values": []}
    assert battery.judge_extraction(c, other)["wrong"] is False   # someone else's act is not the owner's


def test_the_prompt_asks_for_the_persons_own_act_as_a_relationship_once():
    prompt = " ".join(entity_extractor.EXTRACTION_SYSTEM_PROMPT.split())
    assert prompt.count("said in passing in a conversation about something else") == 1
    assert "never only a key_fact" in prompt
