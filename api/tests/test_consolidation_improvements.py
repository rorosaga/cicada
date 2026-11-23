"""G148, 2026-11-23: what the consolidation benchmark found every model getting wrong, fixed where Cicada decides.

- U2: a value said about a thing on the person's page ("half marathon goal time") never replaced the same value on the
  thing's page ("goal finish time"): it moves there when it names the thing and the attribute matches.
- U3: "dropped Python" never closed "written in Python": the seed's `uses` endings now reach the language predicates.
Synthetic data only.
"""
from __future__ import annotations

from api.services import claims as claims_module, predicates
from api.services.claims import Claim


def _value(cid, subject, attribute, value):
    return Claim(id=cid, text=f"{subject} {attribute}: {value}", subject=subject,
                 predicate=claims_module.value_predicate(attribute), object=value, object_kind="literal")


def test_a_value_naming_another_pages_thing_moves_to_that_page():
    old = _value("c_old", "douro-valley-half-marathon", "goal finish time", "under 1:50")
    new = _value("c_new", "ines-varga", "half marathon goal time", "under 1:45")
    existing = {"douro-valley-half-marathon": [old], "ines-varga": []}
    moved = claims_module.route_values_to_their_thing([new], existing)
    assert moved == [("c_new", "ines-varga", "douro-valley-half-marathon")]
    assert new.subject == "douro-valley-half-marathon" and new.predicate == old.predicate


def test_a_value_about_the_person_stays_on_the_person():
    """Words beyond the matching attribute that are not the other page's id: nothing moves."""
    old = _value("c_old", "douro-valley-half-marathon", "goal finish time", "under 1:50")
    new = _value("c_new", "ines-varga", "savings goal time", "June")
    claims_module.route_values_to_their_thing([new], {"douro-valley-half-marathon": [old]})
    assert new.subject == "ines-varga"


def test_two_pages_that_could_take_it_move_nothing():
    a = _value("c_a", "spring-half-marathon", "goal time", "under 2:00")
    b = _value("c_b", "autumn-half-marathon", "goal time", "under 1:50")
    new = _value("c_new", "ines-varga", "half marathon goal time", "under 1:45")
    moved = claims_module.route_values_to_their_thing([new], {"spring-half-marathon": [a], "autumn-half-marathon": [b]})
    assert moved == [] and new.subject == "ines-varga"


def test_a_closed_value_is_never_a_target():
    old = _value("c_old", "douro-valley-half-marathon", "goal time", "under 1:50")
    old.valid_to = "2026-11-01"
    new = _value("c_new", "ines-varga", "half marathon goal time", "under 1:45")
    assert claims_module.route_values_to_their_thing([new], {"douro-valley-half-marathon": [old]}) == []


def test_dropped_ends_what_a_project_was_written_in():
    ending = predicates.build_endings_fn(None)
    assert ending("dropped").canonical == "uses"
    for predicate in ("written-in", "implemented-in", "coded-in"):
        assert ending.ended_by(predicate) == "uses", predicate
