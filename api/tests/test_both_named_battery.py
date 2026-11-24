"""The Stage 1 replay of a conversation that names two people of one first name (`both_named_battery`): the cases are
labelled consistently and the scoring reads shapes and where each person's facts land. No model."""
from __future__ import annotations

from benchmarks.consolidation import both_named_battery as b


def _case(**k):
    return {"id": "x", "kind": "two", "name": "Marc", "people": {"A": ["carpenter"], "B": ["research team"]}, **k}


def _entity(name, text, kind="person"):
    return {"name": name, "type": kind, "summary": text, "key_facts": [], "aliases": []}


def test_every_case_names_two_people_with_their_own_marks_and_two_controls_name_one():
    cases = b.load_cases()
    assert len({c["id"] for c in cases}) == len(cases) >= 8
    assert {c["lang"] for c in cases} >= {"en", "es", "fr", "de"}
    assert sum(c["kind"] == "one" for c in cases) >= 2
    for c in cases:
        assert set(c["people"]) == {"A", "B"} and len(c["turns"]) >= 3 and c["name"] in " ".join(c["turns"])
        assert not set(map(b.norm, c["people"]["A"])) & set(map(b.norm, c["people"]["B"])), c["id"]


def test_a_name_is_bare_parenthesised_or_other():
    assert [b.form_of(n, "Marc") for n in ("Marc", "Marc (cousin)", "Aunt Marc", "Marc Curie", "Mercury (planet)", "Marco")] == \
        ["bare", "paren", "other", "other", None, None]


def test_two_people_on_two_entities_are_clean_and_on_one_are_blended():
    clean = {"entities": [_entity("Marc (cousin)", "a carpenter"), _entity("Marc (colleague)", "on the research team")]}
    blended = {"entities": [_entity("Marc", "a carpenter on the research team")]}
    lost = {"entities": [_entity("Marc (cousin)", "a carpenter"), _entity("Marc (colleague)", "works somewhere")]}
    assert b.judge_extraction(_case(), clean) == {"shape": "paren+paren", "outcome": "clean",
                                                  "names": ["Marc (cousin)", "Marc (colleague)"], "holds": [["A"], ["B"]]}
    assert b.judge_extraction(_case(), blended)["outcome"] == "blended"
    assert b.judge_extraction(_case(), lost)["outcome"] == "lost"


def test_a_control_where_the_two_names_are_one_person_must_stay_one_entity():
    one = _case(kind="one")
    assert b.judge_extraction(one, {"entities": [_entity("Marc", "a carpenter")]})["outcome"] == "one-entity"
    assert b.judge_extraction(one, {"entities": [_entity("Marc", "a"), _entity("Marc (gym)", "b")]})["outcome"] == "split"
