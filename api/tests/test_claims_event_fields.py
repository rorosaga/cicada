"""G141 §4.1 — the four event fields on `Claim`, and `is_event`.

Legacy fences must round-trip byte-identical (R7's reason: re-rendering a page
must never diff every legacy claim for a field it lacks), and a hand-edited
participant list is cleaned, never fatal.
"""
from api.services.claims import (Claim, clean_participants, event_cardinality, is_event, parse_claims,
                                 write_claims)

# The demo bank's `bob-example` fence (synthetic), as `write_claims` renders it.
LEGACY_FENCE = """```claims
- id: clm_bob-example_works-on_c3b8881d
  text: bob-example works-on Alpha Project
  subject: bob-example
  predicate: works-on
  object: Alpha Project
  object_kind: node
  observer: owner
  context: general
  epistemic: explicit
  source_trust: user_stated
  confidence: 0.75
  valid_from: '2026-09-14'
  valid_to: null
  superseded_by: null
  supersedes: null
  recorded_at: '2026-09-23'
  source_episodes:
  - ep_2026-09-14_001
  premises: []
  authored_by: user
  origin: manual_edit
  session_id: null
  session_ids: []
  decayed_through: null
  evidence:
  - episode: ep_2026-09-14_001
    start: 6
    end: 114
    kind: user
    hash: cb996f31888f
- id: clm_bob-example_works-on_ad0d598c
  text: Bob Example works on Rover Arm Project
  subject: bob-example
  predicate: works-on
  object: rover-arm-project
  object_kind: node
  observer: agent
  context: general
  epistemic: explicit
  source_trust: agent_extracted
  confidence: 0.75
  valid_from: '2026-07-15'
  valid_to: null
  superseded_by: null
  supersedes: null
  recorded_at: '2026-09-23'
  source_episodes:
  - ep_2026-07-15_001
  premises: []
  authored_by: mcp-agentic-write
  origin: mcp
  session_id: null
  session_ids: []
  decayed_through: null
  evidence:
  - episode: ep_2026-07-15_001
    start: 6
    end: 41
    kind: user
    hash: 3bc0bed0cbd5
```"""


def test_a_legacy_fence_round_trips_byte_identical():
    body = "# Bob Example\n\nSome prose.\n\n" + LEGACY_FENCE + "\n"
    claims = parse_claims(body, strict=True)
    assert len(claims) == 2
    assert write_claims(body, claims) == body


def test_event_fields_round_trip_and_junk_is_dropped():
    c = Claim(id="clm_alpha-project_happened_abcd1234_2026-09-22", text="Bob got the guide from Hana Example",
              subject="alpha-project", predicate="happened", object="bob got the guide from hana example",
              object_kind="literal", valid_from="2026-09-22", valid_to="2026-09-22",
              status="done", target="2026-10-01",
              participants=[{"role": "from", "surface": "Hana Example", "entity": "hana-example", "junk": 1},
                            {"role": "boss"}],
              date_basis="stated")
    body = write_claims("# Alpha\n", [c])
    back = parse_claims(body, strict=True)[0]
    assert back.status == "done" and back.target == "2026-10-01" and back.date_basis == "stated"
    assert back.participants == [{"role": "from", "surface": "Hana Example", "entity": "hana-example"}]
    assert "junk" not in body and "boss" not in body


def test_to_dict_omits_the_four_fields_when_empty():
    d = Claim(id="c1", text="t").to_dict()
    for key in ("status", "target", "participants", "date_basis"):
        assert key not in d


def test_is_event_and_event_cardinality():
    assert is_event(Claim(id="a", text="", predicate="happened"))
    assert is_event(Claim(id="b", text="", predicate="milestone"))
    assert not is_event(Claim(id="c", text="", predicate="due"))
    assert not is_event(Claim(id="d", text="", predicate="retracts"))
    assert event_cardinality("happened") == "multi"
    assert event_cardinality("uses") is None


def test_clean_participants_is_forgiving():
    assert clean_participants(None) == []
    assert clean_participants(["x", {"role": "with", "surface": ""}, {"role": "document", "url": "https://example.com"}]) \
        == [{"role": "with"}, {"role": "document", "url": "https://example.com"}]
