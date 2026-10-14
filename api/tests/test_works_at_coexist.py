"""2026-10-14 — a person holds more than one place at once: ``works-at`` coexists, and a place ends only on evidence.

Every bank here is synthetic: `bob-example`, `acme-example`, `lab-example`, made-up episodes. The owner's measured page
(26 ``works-at`` claims, 25 closed, flipping between six places 1-60 days apart) is the case these reproduce in small.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import yaml

from api.services import claim_pipeline, markdown_parser, predicates
from api.services.claim_reconciler import reconcile_stage3
from api.services.claims import Claim, parse_claims, write_claims

PERSON = "bob-example"


def _settings(memory: Path):
    return SimpleNamespace(memory_path=memory, litellm_model="gpt-5.4-mini",
                           litellm_disambiguation_model="gpt-5.4-nano", archive_threshold=0.2,
                           decay_nudge_threshold=0.4)


def _bank(tmp_path: Path, *, stale: bool = False) -> Path:
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    (memory / "episodes").mkdir(parents=True)
    predicates.install_predicate_map(memory)
    if stale:
        # A bank seeded before 2026-10-14: its own map still lists works-at single-valued, and
        # `install_predicate_map` never refreshes a populated map.
        path = memory / predicates.RUNTIME_FILE
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        data["single_valued"] = [*data["single_valued"], "works-at"]
        data["multi_valued"] = [p for p in data["multi_valued"] if p != "works-at"]
        data.pop("endings", None)
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    markdown_parser.write(memory / "entities" / f"{PERSON}.md",
                          {"name": "Bob Example", "type": "person", "status": "active"}, "## Summary\nA person.")
    return memory


def _sleep(memory: Path, day: str, n: int, rels: list[tuple[str, str]]) -> dict:
    """One Sleep-style pass over one conversation on `day`: Stage 1 projection, Stage 3, Stage 5 write."""
    ep = f"ep_{day}_{n:03d}"
    extracted = [{"episode_id": ep, "episode_timestamp": f"{day}T10:00:00", "origin": "claude-code", "entities": [],
                  "relationships": [{"source": "Bob Example", "target": target, "label": label, "source_episode": ep,
                                     "source_episode_timestamp": f"{day}T10:00:00"} for label, target in rels]}]
    return claim_pipeline.run_claim_pipeline(extracted, [], memory, _settings(memory), now_date=day)


def _places(memory: Path) -> tuple[set[str], list[Claim]]:
    claims = parse_claims(markdown_parser.parse(memory / "entities" / f"{PERSON}.md").body, strict=True)
    works = [c for c in claims if c.predicate == "works-at"]
    return {c.object for c in works if c.valid_to is None}, works


# --- the vocabulary ----------------------------------------------------------------------------------------------


def test_works_at_is_multi_valued_and_the_others_stay_single(tmp_path):
    memory = _bank(tmp_path)
    single = predicates.build_cardinality_fn(memory)
    assert single("works-at") is False
    assert predicates.cardinality(memory, "works-at") == "multi"
    for p in ("runs-on", "takes-place-in", "part-of"):
        assert single(p) is True, p


def test_a_stale_bank_map_cannot_make_works_at_single_again(tmp_path):
    memory = _bank(tmp_path, stale=True)
    assert predicates.build_cardinality_fn(memory)("works-at") is False, "the committed seed's multi wins"
    assert predicates.build_cardinality_fn(memory)("part-of") is True
    assert predicates.build_cardinality_fn(tmp_path / "no-map")("part-of") is False, \
        "a bank with no map still coexists everything — the seed's singles are not imported"


def test_ending_labels_compare_slugged_and_an_ambiguous_label_ends_nothing(tmp_path):
    memory = _bank(tmp_path)
    ending = predicates.build_endings_fn(memory)
    assert ending("Previously  Worked At") == predicates.Ending("works-at", "over", True)
    assert ending("left") == predicates.Ending("works-at", "over", False)
    assert ending("worked-at") == predicates.Ending("works-at", "past", True)
    assert ending("works at") is None
    path = memory / predicates.RUNTIME_FILE
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["endings"] = {"lives-in": {"over": ["left"]}}
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    assert predicates.build_endings_fn(memory)("left") is None, "two canonicals claim it: when unsure, nothing closes"


# --- Stage 3 ------------------------------------------------------------------------------------------------------


def test_two_concurrent_jobs_stay_current_through_several_sleeps(tmp_path):
    for stale in (False, True):
        memory = _bank(tmp_path / ("stale" if stale else "fresh"), stale=stale)
        # A→B→A→B, 1-60 days apart: the measured flip-flop, in small.
        for n, (day, place) in enumerate([("2026-06-01", "Acme Example"), ("2026-06-02", "Lab Example"),
                                          ("2026-07-15", "Acme Example"), ("2026-08-30", "Lab Example"),
                                          ("2026-09-01", "Acme Example")], start=1):
            result = _sleep(memory, day, n, [("works at", place)])
            assert not [a for a in result.get("audit", []) if a.get("action") == "supersede"]
        current, works = _places(memory)
        assert current == {"acme-example", "lab-example"}, (stale, current)
        assert all(c.superseded_by is None for c in works), "a mention of one place never closes the other"
        assert len(works) == 2, "a restatement reinforces the open belief, never opens a second"


def test_a_stated_departure_ends_one_place_and_leaves_the_other(tmp_path):
    memory = _bank(tmp_path)
    _sleep(memory, "2026-06-01", 1, [("works at", "Acme Example"), ("works at", "Lab Example")])
    _sleep(memory, "2026-09-10", 2, [("left", "Acme Example")])
    current, works = _places(memory)
    assert current == {"lab-example"}
    acme = next(c for c in works if c.object == "acme-example" and c.valid_from == "2026-06-01")
    record = next(c for c in works if c.id == acme.superseded_by)
    assert acme.valid_to == "2026-09-10", "closed on the day the departure was said"
    assert (record.valid_from, record.valid_to, record.supersedes) == ("2026-09-10", "2026-09-10", acme.id), \
        "the departure is kept as closed history, never a current place"


def test_a_departure_said_before_the_place_was_last_said_ends_nothing(tmp_path):
    memory = _bank(tmp_path)
    _sleep(memory, "2026-03-01", 1, [("works at", "Acme Example")])
    _sleep(memory, "2026-09-01", 2, [("works at", "Acme Example")])
    _sleep(memory, "2026-05-01", 3, [("left", "Acme Example")])     # an older conversation, read late
    assert _places(memory)[0] == {"acme-example"}, "left, then went back: the newer word stands"


def test_past_tense_reinforces_a_current_place_and_otherwise_is_history(tmp_path):
    memory = _bank(tmp_path)
    _sleep(memory, "2026-06-01", 1, [("works at", "Acme Example")])
    _sleep(memory, "2026-06-05", 2, [("worked at", "Acme Example"), ("worked at", "Old Example"),
                                     ("previously worked at", "Older Example")])
    current, works = _places(memory)
    assert current == {"acme-example"}, "a past-tense mention is never a current place"
    closed = {c.object for c in works if c.valid_to}
    assert closed == {"old-example", "older-example"}, "kept as history, not dropped"
    acme = [c for c in works if c.object == "acme-example"]
    assert len(acme) == 1 and "ep_2026-06-05_002" in acme[0].source_episodes, "reinforced, not closed"


def test_left_a_place_that_was_never_a_job_keeps_its_own_label(tmp_path):
    memory = _bank(tmp_path)
    _sleep(memory, "2026-06-01", 1, [("left", "Lisbon Example")])
    claims = parse_claims(markdown_parser.parse(memory / "entities" / f"{PERSON}.md").body, strict=True)
    assert [(c.predicate, c.object, c.valid_to) for c in claims] == [("left", "lisbon-example", None)]


def test_an_agents_departure_never_closes_the_persons_own_statement(tmp_path):
    memory = _bank(tmp_path)
    human = Claim(id="clm_human_001", text="Bob Example works at Acme Example", subject=PERSON, predicate="works-at",
                  object="acme-example", observer="agent", context="general", source_trust="user_stated",
                  origin="clarification", valid_from="2026-06-01", confidence=0.95)
    markdown_parser.write(memory / "entities" / f"{PERSON}.md", {"name": "Bob Example", "type": "person"},
                          write_claims("## Summary\nA person.", [human]))
    _sleep(memory, "2026-09-10", 1, [("left", "Acme Example")])
    current, _ = _places(memory)
    assert current == {"acme-example"}, "only the person ends their own statement"


def test_a_single_valued_predicate_still_supersedes(tmp_path):
    memory = _bank(tmp_path)
    old = Claim(id="clm_a", text="x part-of alpha", subject="x", predicate="part-of", object="alpha",
                valid_from="2026-06-01")
    new = Claim(id="clm_b", text="x part-of beta", subject="x", predicate="part-of", object="beta",
                valid_from="2026-06-02")
    out, _nudges, audit = reconcile_stage3([new], {"x": [old]}, _settings(memory), now_date="2026-06-02")
    assert old.superseded_by == "clm_b" and {"action": "supersede", "closed": "clm_a", "by": "clm_b"} in audit
