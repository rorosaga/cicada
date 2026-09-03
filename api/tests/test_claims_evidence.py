"""G118 slice 1 — `Claim.evidence`: spans (offsets + hash), never copies.

Round-trips through the in-page ```claims block; a legacy claim without the
key parses to an empty list; `to_dict` omits an empty list (R7) so a page
rewrite never touches ~2,300 legacy claims for a field they do not have.
"""
from __future__ import annotations

from api.services.claims import EVIDENCE_KINDS, Claim, Evidence, parse_claims, write_claims


def test_evidence_kinds_are_the_four_the_g118_row_names():
    assert EVIDENCE_KINDS == ("user", "assistant", "page", "reasoning")


def test_claim_defaults_to_no_evidence_and_to_dict_omits_the_key():
    c = Claim(id="clm_x", text="alpha-project uses sqlite-vec")
    assert c.evidence == []
    assert "evidence" not in c.to_dict()
    assert Claim.from_dict(c.to_dict()) == c


def test_evidence_round_trips_through_the_claims_block():
    ev = [
        Evidence(episode="ep_2026-09-01_001", start=12, end=40, kind="user", hash="0123456789ab"),
        Evidence(episode="ep_2026-09-02_003", start=-1, end=-1, kind="reasoning", hash="abcdefabcdef"),
    ]
    c = Claim(id="clm_x", text="alpha-project uses sqlite-vec", subject="alpha-project",
              predicate="uses", object="sqlite-vec", evidence=ev)
    body = write_claims("## Summary\nA project.", [c])
    back = parse_claims(body)
    assert back == [c]
    assert back[0].evidence[0].is_span() is True
    assert back[0].evidence[1].is_span() is False
    assert "start: 12" in body and "hash: 0123456789ab" in body


def test_legacy_claim_without_evidence_parses_to_empty_list():
    body = (
        "```claims\n- id: clm_old\n  text: old belief\n  subject: alpha-project\n"
        "  predicate: uses\n  object: postgres\n```\n"
    )
    (c,) = parse_claims(body)
    assert c.evidence == []


def test_evidence_from_dict_is_forgiving_never_raising():
    # Unknown kind, junk offsets, missing keys: degrade to reasoning, never raise.
    assert Evidence.from_dict({"episode": "ep_x", "start": "a", "end": 5, "kind": "user"}) == Evidence(
        episode="ep_x", start=-1, end=-1, kind="reasoning", hash="")
    assert Evidence.from_dict({"kind": "banana", "start": 1, "end": 4}) == Evidence(
        episode="", start=-1, end=-1, kind="reasoning", hash="")
    assert Evidence.from_dict({"episode": "ep_x", "start": 3, "end": 3, "kind": "user"}).kind == "reasoning"
    assert Evidence.from_dict(None) == Evidence()
    # A non-mapping entry inside a claim's list is skipped, the rest kept.
    c = Claim.from_dict({"id": "clm_x", "text": "t", "evidence": ["junk", {"episode": "ep_y", "start": 0, "end": 2, "kind": "page", "hash": "h"}]})
    assert c.evidence == [Evidence(episode="ep_y", start=0, end=2, kind="page", hash="h")]
