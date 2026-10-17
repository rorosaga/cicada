"""Stated values (2026-10-17): a value that changes lands as a claim a later value supersedes.

LongMemEval knowledge-update, 2026-10-17 (G148): a count said as three and later as four, and a personal-best time
said twice, both stayed as two lines of page prose — Stage 1 emitted only entity-to-entity relationships, so there was
no claim for the newer value to close. ``values[]`` in the extraction becomes a literal ``value-of-<attribute>`` claim,
single-valued by its shape. Synthetic names only; no model, no network.
"""
from __future__ import annotations

from api.services import predicates
from api.services.claim_reconciler import reconcile_stage3
from api.services.claims import Claim, is_value_claim, same_value_attribute, value_key, value_predicate
from api.services.entity_extractor import entities_to_claims


class _Settings:
    def __init__(self, memory_path):
        self.memory_path = memory_path
        self.litellm_model = "test-model"
        self.archive_threshold = 0.2
        self.decay_nudge_threshold = 0.4


def _value(cid, attribute, value, valid_from, subject="alice-example"):
    return Claim(id=cid, text=f"{subject} {attribute}: {value}", subject=subject,
                 predicate=value_predicate(attribute), object=value, object_kind="literal",
                 valid_from=valid_from, source_trust="agent_extracted", origin="benchmark")


def _reconcile(tmp_path, incoming, existing):
    predicates.install_predicate_map(tmp_path)
    out: dict[str, list[Claim]] = {}
    for c in existing:
        out.setdefault(c.subject, []).append(c)
    # The bank's vocabulary says nothing about value predicates: the shape alone makes them single-valued.
    return reconcile_stage3(incoming, out, _Settings(tmp_path), cardinality_fn=lambda _p: False,
                            now_date="2023-06-01", decay=False)


def test_the_extraction_projects_a_value_as_a_literal_claim():
    extracted = [{"episode_id": "ep_2023-05-27_001", "origin": "benchmark", "relationships": [], "values": [
        {"entity": "Alice Example", "attribute": "Personal best 5K time", "value": " 25:50 ",
         "source_episode": "ep_2023-05-27_001", "source_episode_timestamp": "2023-05-27T10:00:00+00:00",
         "evidence": [{"episode": "ep_2023-05-27_001", "start": 10, "end": 30, "kind": "user", "hash": "abc"}]},
        {"entity": "Alice Example", "attribute": "", "value": "7"},          # names nothing: dropped
    ]}]
    [claim] = entities_to_claims(extracted, None)
    assert claim.predicate == "value-of-personal-best-5k-time" and claim.object == "25:50"
    assert claim.object_kind == "literal" and is_value_claim(claim)
    assert claim.subject == "alice-example" and claim.valid_from == "2023-05-27"
    assert claim.evidence and claim.evidence[0].kind == "user"


def test_a_newer_value_supersedes_the_older_one_named_in_other_words(tmp_path):
    old = _value("clm_old", "personal best 5k time", "27:12", "2023-05-25")
    new = _value("clm_new", "5K personal best", "25:50", "2023-05-27")
    reconciled, nudges, _ = _reconcile(tmp_path, [new], [old])
    by_id = {c.id: c for c in reconciled["alice-example"]}
    assert by_id["clm_old"].valid_to == "2023-05-27" and by_id["clm_old"].superseded_by == "clm_new"
    assert by_id["clm_new"].valid_to is None and by_id["clm_new"].predicate == old.predicate
    assert nudges == []


def test_an_older_value_read_after_the_newer_is_kept_as_history(tmp_path):
    newer = _value("clm_newer", "korean restaurants tried", "4", "2023-09-30")
    older = _value("clm_older", "number of korean restaurants tried", "3", "2023-08-11")
    reconciled, nudges, audit = _reconcile(tmp_path, [older], [newer])
    by_id = {c.id: c for c in reconciled["alice-example"]}
    assert by_id["clm_newer"].valid_to is None
    assert by_id["clm_older"].valid_to == "2023-09-30" and by_id["clm_older"].superseded_by == "clm_newer"
    assert nudges == [] and any(a["action"] == "superseded_on_arrival" for a in audit)


def test_two_values_on_the_same_day_ask(tmp_path):
    a = _value("clm_a", "korean restaurants tried", "3", "2023-08-11")
    b = _value("clm_b", "korean restaurants tried", "4", "2023-08-11")
    reconciled, nudges, _ = _reconcile(tmp_path, [b], [a])
    assert {c.id for c in reconciled["alice-example"]} == {"clm_a"}
    assert any(n.get("action") == "conflict_nudge" for n in nudges)


def test_a_one_word_attribute_never_meets_a_longer_one():
    assert not same_value_attribute(value_predicate("age"), value_predicate("dog age"))
    assert same_value_attribute(value_predicate("Number of Korean restaurants tried"),
                                value_predicate("korean restaurant tried"))
    assert value_key(value_predicate("the current count of bikes")) == frozenset({"bike"})


def test_value_predicates_are_single_valued_and_other_literals_are_not(tmp_path):
    assert predicates.cardinality(tmp_path, "value-of-monthly-rent") == "single"
    plain = Claim(id="clm_p", text="t", subject="s", predicate="uses", object="python", object_kind="literal")
    assert not is_value_claim(plain)
    node = Claim(id="clm_n", text="t", subject="s", predicate="value-of-x", object="y", object_kind="node")
    assert not is_value_claim(node)
