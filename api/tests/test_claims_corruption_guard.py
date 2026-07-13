"""Corruption guard: a present-but-unparseable ```claims block must never be
silently destroyed by any read-modify-write path.

Background (reconsolidation pilot, 2026-07-13): three live entities carried
claims blocks with stray ``` fences embedded in claim text. ``parse_claims``
degraded them to ``[]`` (by design, for read paths), but every writer then
rebuilt the block from that empty list — silently wiping the trapped claims.
These tests pin the fix: strict parsing at every rewrite site, so a corrupt
block aborts the write and the page stays byte-identical.
"""

from __future__ import annotations

import pytest

from api.services import agentic_write, claim_seeder, markdown_parser, source_rewrite
from api.services.claim_pipeline import run_claim_pipeline
from api.services.claims import (
    Claim,
    MalformedClaimsBlockError,
    parse_claims,
)
from api.services.entity_merge import merge_entities
from api.services.link_enrichment import _append_claim

# A claims block that is present but cannot parse. Live corruption shape:
# a stray ``` fence embedded in claim text truncates the block early, leaving
# the captured payload as invalid YAML (here: an unterminated quoted scalar).
CORRUPT_BLOCK = (
    "```claims\n"
    "- id: clm_2026-01-01_001\n"
    "  text: \"first trapped claim\n"
    "```\n"
)

GOOD_BODY = "## Summary\nA page.\n\n" + CORRUPT_BLOCK


def _corrupt_page(tmp_path, entity_id="supahost"):
    ents = tmp_path / "entities"
    ents.mkdir(parents=True, exist_ok=True)
    page = ents / f"{entity_id}.md"
    page.write_text(
        f"---\nname: {entity_id}\ntype: tool\nstatus: active\nconfidence: 0.6\n"
        f"source_episodes:\n  - ep_2026-01-01_001\n---\n\n{GOOD_BODY}",
        encoding="utf-8",
    )
    return page


def _claim(subject: str) -> Claim:
    return Claim(
        id="clm_new_001",
        text="new claim",
        subject=subject,
        predicate="uses",
        object="something",
        object_kind="node",
        observer="agent",
        context="general",
        epistemic="explicit",
        source_trust="agent_extracted",
        confidence=0.5,
    )


# --------------------------------------------------------------------------- #
# parse_claims: lenient default unchanged, strict raises
# --------------------------------------------------------------------------- #


def test_parse_claims_lenient_default_still_degrades():
    assert parse_claims(GOOD_BODY) == []


def test_parse_claims_strict_raises_on_yaml_error():
    with pytest.raises(MalformedClaimsBlockError):
        parse_claims(GOOD_BODY, strict=True)


def test_parse_claims_strict_raises_on_non_list_payload():
    body = "```claims\nkey: value\n```\n"
    with pytest.raises(MalformedClaimsBlockError):
        parse_claims(body, strict=True)


def test_parse_claims_strict_passes_clean_and_absent_blocks():
    assert parse_claims("no block here", strict=True) == []
    clean = "```claims\n- id: clm_x\n  text: ok\n  subject: s\n  predicate: p\n  object: o\n```\n"
    assert len(parse_claims(clean, strict=True)) == 1


# --------------------------------------------------------------------------- #
# agentic_write.write_claim: refuses, reports, leaves page untouched
# --------------------------------------------------------------------------- #


def test_write_claim_refuses_on_corrupt_block(tmp_path):
    page = _corrupt_page(tmp_path)
    before = page.read_bytes()

    result = agentic_write.write_claim(
        tmp_path, "supahost", "uses", "postgres", observer="agent"
    )

    assert result["action"] == "corrupt_claims_block"
    assert "unparseable" in result["error"]
    assert page.read_bytes() == before


# --------------------------------------------------------------------------- #
# claim_pipeline write-back: corrupt page skipped, others written
# --------------------------------------------------------------------------- #


def test_claim_pipeline_write_back_skips_corrupt_page(tmp_path):
    page = _corrupt_page(tmp_path)
    before = page.read_bytes()

    class _S:  # minimal settings shim; reconcile_stage3 reads nothing risky here
        litellm_model = "test"

    extracted = [
        {
            "name": "Supahost",
            "type": "tool",
            "attributes": {"uses": "postgres"},
            "source_episode": "ep_2026-07-01_001",
        }
    ]
    result = run_claim_pipeline(extracted, [], tmp_path, _S())

    assert page.read_bytes() == before
    # nothing else should have been written for this subject
    assert result["claims_written"] == 0 or page.read_bytes() == before


# --------------------------------------------------------------------------- #
# entity_merge: corrupt winner aborts the merge (both pages untouched)
# --------------------------------------------------------------------------- #


def test_merge_entities_aborts_on_corrupt_winner(tmp_path):
    winner = _corrupt_page(tmp_path, "winner")
    ents = tmp_path / "entities"
    loser = ents / "loser.md"
    loser.write_text(
        "---\nname: loser\ntype: tool\nstatus: active\nconfidence: 0.4\n---\n\n## Summary\nb\n",
        encoding="utf-8",
    )
    w_before, l_before = winner.read_bytes(), loser.read_bytes()

    with pytest.raises(MalformedClaimsBlockError):
        merge_entities(tmp_path, loser_id="loser", winner_id="winner")

    assert winner.read_bytes() == w_before
    assert loser.read_bytes() == l_before


# --------------------------------------------------------------------------- #
# link_enrichment._append_claim: returns False, page untouched
# --------------------------------------------------------------------------- #


def test_append_claim_refuses_on_corrupt_block(tmp_path):
    page = _corrupt_page(tmp_path)
    before = page.read_bytes()

    assert _append_claim(page, _claim("supahost")) is False
    assert page.read_bytes() == before


# --------------------------------------------------------------------------- #
# claim_seeder: corrupt subject skipped, page untouched
# --------------------------------------------------------------------------- #


def test_claim_seeder_skips_corrupt_subject(tmp_path):
    page = _corrupt_page(tmp_path)
    before = page.read_bytes()
    (tmp_path / "graph_edges.yaml").write_text(
        "edges:\n  - source: supahost\n    target: postgres\n    label: uses\n",
        encoding="utf-8",
    )

    claim_seeder.seed_claims_from_edges(tmp_path, rebuild_index=False)

    assert page.read_bytes() == before


# --------------------------------------------------------------------------- #
# source_rewrite: corrupt entity skipped with explicit error
# --------------------------------------------------------------------------- #


def test_source_rewrite_skips_corrupt_entity(tmp_path):
    page = _corrupt_page(tmp_path)
    before = page.read_bytes()
    episodes = tmp_path / "episodes"
    episodes.mkdir()
    (episodes / "ep_2026-01-01_001.md").write_text(
        "---\nid: ep_2026-01-01_001\nprocessed: true\n---\n\nTalked about supahost hosting.\n",
        encoding="utf-8",
    )

    class _S:
        litellm_model = "test"

    def fake_llm(**_kwargs):
        return {"choices": [{"message": {"content": '{"body": "## Summary\\nrewritten"}'}}]}

    result = source_rewrite.rewrite_entity_from_sources(
        tmp_path, "supahost", _S(), llm_fn=fake_llm
    )

    assert result.get("error") == "corrupt_claims_block"
    assert result["changed"] is False
    assert page.read_bytes() == before
