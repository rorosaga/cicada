"""Tests for M5e Stage-5 section-aware merge preserving human prose (rule 3c).

Per ``sleep-trust-reconciliation.md`` §8: an agent Sleep pass merges new fields
into a page's agent-owned sections, but **never rewrites or removes a human-
authored line**. The additive-only guard fires when a page is human-edited
(``human_edited: true`` frontmatter) or carries non-canonical hand-added sections.
``write_claims`` separately owns the machine ``claims`` block and must preserve all
surrounding prose verbatim (M5a invariant, re-asserted here in the Stage-5 path).
"""

from __future__ import annotations

from api.services import entity_body
from api.services.claims import Claim, parse_claims, write_claims


def test_merge_preserves_non_canonical_human_section(tmp_path):
    # A hand-added "## My Notes" section is non-canonical — it must survive an
    # agent merge untouched.
    existing = {
        "Summary": "A project.",
        "My Notes": "- Rodrigo's private note: ship by Friday.",
    }
    merged = entity_body.merge_sections_human_safe(
        existing,
        {"summary": "A project for the thesis.", "key_facts": ["Uses FastAPI."]},
        human_edited=True,
    )
    # human section preserved verbatim
    assert merged["My Notes"] == "- Rodrigo's private note: ship by Friday."
    # agent could still ADD a new fact
    assert "Uses FastAPI." in merged.get("Key Facts", "")


def test_human_edited_summary_is_not_rewritten_only_appended(tmp_path):
    existing = {"Summary": "Rodrigo's own words about the project."}
    merged = entity_body.merge_sections_human_safe(
        existing,
        {"summary": "An entirely different agent summary."},
        human_edited=True,
    )
    # the human sentence is still present (additive — never replaced/removed)
    assert "Rodrigo's own words about the project." in merged["Summary"]


def test_non_human_page_merges_normally(tmp_path):
    existing = {"Summary": "Old summary.", "Key Facts": "- Fact A."}
    merged = entity_body.merge_sections_human_safe(
        existing,
        {"key_facts": ["Fact B."]},
        human_edited=False,
    )
    assert "Fact A." in merged["Key Facts"]
    assert "Fact B." in merged["Key Facts"]


def test_write_claims_preserves_prose_in_stage5_path(tmp_path):
    body = (
        "# Cicada\n\nCicada is a memory system.\n\n"
        "## My Notes\n- Hand-written note.\n"
    )
    claims = [
        Claim(id="clm_1", text="Cicada uses sqlite-vec.", subject="cicada",
              predicate="uses", object="sqlite-vec")
    ]
    new_body = write_claims(body, claims)
    # all human prose preserved verbatim
    assert "# Cicada" in new_body
    assert "Cicada is a memory system." in new_body
    assert "## My Notes" in new_body
    assert "- Hand-written note." in new_body
    # the machine block round-trips
    assert parse_claims(new_body)[0].object == "sqlite-vec"


def test_superseded_claims_stay_in_block_for_timeline(tmp_path):
    body = "Cicada page."
    closed = Claim(id="clm_old", text="Used Postgres.", subject="cicada",
                   predicate="uses", object="postgres",
                   valid_to="2026-05-05", superseded_by="clm_new")
    open_ = Claim(id="clm_new", text="Uses sqlite-vec.", subject="cicada",
                  predicate="uses", object="sqlite-vec", supersedes="clm_old")
    new_body = write_claims(body, [closed, open_])
    parsed = parse_claims(new_body)
    ids = {c.id for c in parsed}
    # nothing deleted — the closed claim survives for the belief timeline
    assert ids == {"clm_old", "clm_new"}
    by_id = {c.id: c for c in parsed}
    assert by_id["clm_old"].valid_to == "2026-05-05"
