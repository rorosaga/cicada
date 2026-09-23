"""F1 (R-FX9) — a claim's text as a Summary sentence: deterministic, no LLM."""
from __future__ import annotations

from api.services.claims import Claim
from api.services.entity_body import summary_from_claims, summary_line


def test_a_claim_reads_as_a_sentence():
    assert summary_line("alpha-project depends-on sqlite-vec", predicate="depends-on") == \
        "Alpha-project depends on sqlite-vec."
    assert summary_line("Bob Example works with Grace Example.", predicate="works-with") == \
        "Bob Example works with Grace Example."
    assert summary_line("iOS app  uses\nSwift", predicate="uses") == "iOS app uses Swift."
    assert summary_line("Is alpha-project shipping?") == "Is alpha-project shipping?"
    assert summary_line("   ") == ""


def test_a_hyphenated_predicate_is_only_humanised_as_a_whole_token():
    assert summary_line("gamma-project re-depends-on x", predicate="depends-on") == "Gamma-project re-depends-on x."


def test_open_claims_in_page_order_deduplicated_and_capped():
    claims = [
        Claim(id="a", text="alpha-project depends-on sqlite-vec", predicate="depends-on"),
        Claim(id="b", text="alpha-project uses postgres", predicate="uses", valid_to="2026-05-01"),
        Claim(id="c", text="Alpha-project depends on sqlite-vec.", predicate="depends-on"),
        Claim(id="d", text="Alpha Project ships a macOS app", predicate="ships"),
        Claim(id="e", text="Alpha Project has a logo", predicate="has"),
        Claim(id="f", text="Alpha Project is open source", predicate="is"),
    ]
    assert summary_from_claims(claims) == (
        "Alpha-project depends on sqlite-vec. Alpha Project ships a macOS app. Alpha Project has a logo.")
    assert summary_from_claims([]) == ""
    long = [Claim(id=str(i), text="word " * 30, predicate="p") for i in range(3)]
    out = summary_from_claims(long, max_chars=60)
    assert len(out) <= 60 and out.endswith("…")
