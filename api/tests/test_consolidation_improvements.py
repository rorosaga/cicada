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


def test_dropping_a_thing_closes_its_relationship_and_a_value_naming_it(tmp_path):
    """U3, key runs 2026-11-23: "written in Python" and "implementation language: Python" both outlived "dropped
    Python"; one an unlisted spelling, the other a value. A value whose whole literal is something else stays."""
    from api.services import claim_pipeline
    from api.tests.test_new_user_endings import PROJECT, _bank, _claims, _settings

    memory = _bank(tmp_path)
    day1, day2 = "2026-09-24", "2026-11-08"
    extracted = [{"episode_id": f"ep_{day1}_001", "episode_timestamp": f"{day1}T10:00:00", "origin": "chatgpt",
                  "entities": [{"name": "alpha-project", "type": "project", "source_episode": f"ep_{day1}_001",
                                "values": []}],
                  "relationships": [{"source": "alpha-project", "target": "Python", "label": "is written in",
                                     "source_episode": f"ep_{day1}_001",
                                     "source_episode_timestamp": f"{day1}T10:00:00"}],
                  "values": [{"entity": "alpha-project", "attribute": "implementation language", "value": "Python",
                              "source_episode": f"ep_{day1}_001", "source_episode_timestamp": f"{day1}T10:00:00"},
                             {"entity": "alpha-project", "attribute": "license", "value": "MIT",
                              "source_episode": f"ep_{day1}_001", "source_episode_timestamp": f"{day1}T10:00:00"}]}]
    claim_pipeline.run_claim_pipeline(extracted, [], memory, _settings(memory), now_date=day1)
    later = [{"episode_id": f"ep_{day2}_001", "episode_timestamp": f"{day2}T10:00:00", "origin": "chatgpt",
              "entities": [], "relationships": [{"source": "alpha-project", "target": "Python", "label": "dropped",
                                                 "source_episode": f"ep_{day2}_001",
                                                 "source_episode_timestamp": f"{day2}T10:00:00"}]}]
    claim_pipeline.run_claim_pipeline(later, [], memory, _settings(memory), now_date=day2)
    written = _claims(memory, PROJECT, "is-written-in")
    language = _claims(memory, PROJECT, "value-of-implementation-language")
    licence = _claims(memory, PROJECT, "value-of-license")
    assert written and all(c.valid_to for c in written), "the unlisted spelling ends with the drop"
    assert language and all(c.valid_to for c in language), "a value naming the dropped thing ends with it"
    assert licence and not licence[0].valid_to, "a value naming something else stays"
