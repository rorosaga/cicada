"""M5f: the claim layer wired LOAD-BEARING into the live Sleep cycle.

These tests exercise ``api.services.claim_pipeline`` — the additive orchestration
seam that ties Stage 1 claim emission (``entities_to_claims``), Stage 3 trust-gated
reconciliation (``reconcile_stage3``) and Stage 5 page-write (``write_claims`` +
human-prose-safe merge) into one live-shaped call invoked from ``sleep_cycle.run``.

Invariants under test (the M5f acceptance bar):

* a live-shaped Stage produces claims into the entity page's ```claims block;
* the trust invariant holds **in the wired path** — an agent extraction can NOT
  overwrite a human ``user_stated`` + clarification claim already on the page; it
  coexists (flagged) + emits a soft divergence nudge;
* human-authored prose sections survive a real pipeline pass (no rewrite/removal);
* claim-derived edges are MERGED into graph_edges.yaml, not wiped;
* the legacy entity path is unaffected (claims are additive on top of it).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import yaml

from api.services import claim_pipeline, markdown_parser, predicates
from api.services.claims import Claim, parse_claims, write_claims


def _settings(memory_path: Path):
    return SimpleNamespace(
        memory_path=memory_path,
        litellm_model="gpt-5.4-mini",
        litellm_disambiguation_model="gpt-5.4-nano",
        archive_threshold=0.2,
        decay_nudge_threshold=0.4,
    )


def _seed_workspace(tmp_path: Path) -> Path:
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    (memory / "episodes").mkdir(parents=True)
    predicates.install_predicate_map(memory)
    return memory


def _write_entity(memory: Path, stem: str, frontmatter: dict, body: str) -> Path:
    fp = memory / "entities" / f"{stem}.md"
    markdown_parser.write(fp, frontmatter, body)
    return fp


def _extracted(rel, *, episode="ep_2026-06-17_001", origin="claude-code", ts="2026-06-17T10:00:00"):
    return [
        {
            "episode_id": episode,
            "episode_timestamp": ts,
            "origin": origin,
            "entities": [],
            "relationships": [
                {**r, "source_episode": episode, "source_episode_timestamp": ts}
                for r in rel
            ],
        }
    ]


# --------------------------------------------------------------------------- #
# 1. live-shaped Stage 1+3+5 produces claims into the page
# --------------------------------------------------------------------------- #


def test_pipeline_writes_claims_into_entity_page(tmp_path):
    memory = _seed_workspace(tmp_path)
    _write_entity(
        memory,
        "cicada",
        {"name": "Cicada", "type": "project", "status": "active"},
        "## Summary\nA memory system.",
    )
    extracted = _extracted([{"source": "Cicada", "target": "sqlite-vec", "label": "uses"}])

    result = claim_pipeline.run_claim_pipeline(
        extracted, [], memory, _settings(memory), now_date="2026-06-17"
    )

    parsed = markdown_parser.parse(memory / "entities" / "cicada.md")
    claims = parse_claims(parsed.body)
    assert any(c.predicate == "uses" and c.object == "sqlite-vec" for c in claims)
    assert "A memory system." in parsed.body  # prose preserved
    assert result["claims_written"] >= 1


# --------------------------------------------------------------------------- #
# 2. the trust invariant in the WIRED path: agent can't overwrite a human claim
# --------------------------------------------------------------------------- #


def test_wired_agent_cannot_supersede_human_claim(tmp_path):
    memory = _seed_workspace(tmp_path)
    human = Claim(
        id="clm_human_001",
        text="Rodrigo works at acme",
        subject="rodrigo",
        predicate="works-at",
        object="acme",
        observer="agent",
        context="general",
        source_trust="user_stated",
        origin="clarification",
        valid_from="2026-06-10",
        confidence=0.9,
    )
    body = write_claims("## Summary\nThe user.", [human])
    _write_entity(memory, "rodrigo", {"name": "Rodrigo", "type": "person"}, body)

    # Agent now extracts a CONTRADICTING single-valued belief (works-at is
    # single-valued in the seeded _predicates.yaml — one primary current employer).
    extracted = _extracted(
        [{"source": "Rodrigo", "target": "globex", "label": "works at"}]
    )
    result = claim_pipeline.run_claim_pipeline(
        extracted, [], memory, _settings(memory), now_date="2026-06-18"
    )

    parsed = markdown_parser.parse(memory / "entities" / "rodrigo.md")
    claims = {c.id: c for c in parse_claims(parsed.body)}
    # The human claim is STILL OPEN — never closed by the agent.
    assert claims["clm_human_001"].valid_to is None
    assert claims["clm_human_001"].superseded_by is None
    # The agent claim is recorded but a soft divergence nudge was emitted.
    nudge_actions = {n.get("action") for n in result["nudges"]}
    assert "divergence_nudge" in nudge_actions


def test_wired_human_over_human_supersedes(tmp_path):
    memory = _seed_workspace(tmp_path)
    old_human = Claim(
        id="clm_old_human",
        text="Rodrigo works at acme",
        subject="rodrigo",
        predicate="works-at",
        object="acme",
        observer="agent",
        context="general",
        source_trust="user_stated",
        origin="manual_edit",
        valid_from="2026-05-01",
        confidence=0.9,
    )
    body = write_claims("## Summary\nThe user.", [old_human])
    _write_entity(memory, "rodrigo", {"name": "Rodrigo", "type": "person"}, body)

    # A NEWER human-sourced claim (origin=clarification) legitimately supersedes.
    new_human = Claim(
        id="clm_new_human",
        text="Rodrigo works at globex",
        subject="rodrigo",
        predicate="works-at",
        object="globex",
        observer="agent",
        context="general",
        source_trust="user_stated",
        origin="clarification",
        valid_from="2026-06-18",
        confidence=0.95,
    )
    result = claim_pipeline.run_claim_pipeline(
        [], [], memory, _settings(memory),
        now_date="2026-06-18",
        extra_claims=[new_human],
    )

    parsed = markdown_parser.parse(memory / "entities" / "rodrigo.md")
    claims = {c.id: c for c in parse_claims(parsed.body)}
    assert claims["clm_old_human"].valid_to == "2026-06-18"
    assert claims["clm_old_human"].superseded_by == "clm_new_human"
    assert claims["clm_new_human"].valid_to is None
    assert result is not None


# --------------------------------------------------------------------------- #
# 3. human prose preserved through a real pipeline pass
# --------------------------------------------------------------------------- #


def test_human_prose_section_survives_pipeline(tmp_path):
    memory = _seed_workspace(tmp_path)
    body = (
        "## Summary\nA project.\n\n"
        "## My Private Notes\nRemember to call the supervisor on Friday.\n"
    )
    _write_entity(
        memory,
        "cicada",
        {"name": "Cicada", "type": "project", "human_edited": True},
        body,
    )
    extracted = _extracted([{"source": "Cicada", "target": "leann", "label": "uses"}])

    claim_pipeline.run_claim_pipeline(
        extracted, [], memory, _settings(memory), now_date="2026-06-18"
    )

    text = (memory / "entities" / "cicada.md").read_text()
    # The hand-authored, non-canonical section is preserved verbatim.
    assert "## My Private Notes" in text
    assert "Remember to call the supervisor on Friday." in text
    # And the claim still landed.
    claims = parse_claims(markdown_parser.parse(memory / "entities" / "cicada.md").body)
    assert any(c.object == "leann" for c in claims)


# --------------------------------------------------------------------------- #
# 4. claim-derived edges are MERGED, not wiped
# --------------------------------------------------------------------------- #


def test_pipeline_merges_claim_edges_preserving_legacy(tmp_path):
    memory = _seed_workspace(tmp_path)
    _write_entity(memory, "cicada", {"name": "Cicada", "type": "project"}, "## Summary\nx")
    # A pre-existing NON-claim edge (e.g. a media `about` edge) must survive.
    (memory / "graph_edges.yaml").write_text(
        yaml.dump({"edges": [{"source": "cicada", "target": "blog-post", "label": "about"}]}),
        encoding="utf-8",
    )
    extracted = _extracted([{"source": "Cicada", "target": "sqlite-vec", "label": "uses"}])

    claim_pipeline.run_claim_pipeline(
        extracted, [], memory, _settings(memory), now_date="2026-06-18"
    )
    # Stage 5.7 (edge regen) is a separate call in the cycle; run it here to mirror.
    from api.services.graph_builder import regenerate_edges_from_claims

    regenerate_edges_from_claims(memory)

    data = yaml.safe_load((memory / "graph_edges.yaml").read_text())
    pairs = {(e["source"], e["target"], e["label"]) for e in data["edges"]}
    assert ("cicada", "blog-post", "about") in pairs  # legacy preserved
    assert ("cicada", "sqlite-vec", "uses") in pairs  # claim edge added


# --------------------------------------------------------------------------- #
# 5. additive: claims never touch the entity frontmatter / legacy fields
# --------------------------------------------------------------------------- #


def test_pipeline_is_additive_to_entity_frontmatter(tmp_path):
    memory = _seed_workspace(tmp_path)
    fm = {
        "name": "Cicada",
        "type": "project",
        "status": "active",
        "confidence": 0.7,
        "version": 4,
    }
    _write_entity(memory, "cicada", fm, "## Summary\nx")
    extracted = _extracted([{"source": "Cicada", "target": "leann", "label": "uses"}])

    claim_pipeline.run_claim_pipeline(
        extracted, [], memory, _settings(memory), now_date="2026-06-18"
    )

    parsed = markdown_parser.parse(memory / "entities" / "cicada.md")
    # Entity-path frontmatter is untouched by the claim writer.
    assert parsed.frontmatter["version"] == 4
    assert parsed.frontmatter["confidence"] == 0.7
    assert parsed.frontmatter["status"] == "active"


def test_pipeline_skips_subjects_without_pages(tmp_path):
    """A claim whose subject has no entity page is not lost — it is staged on a
    new page-less buffer rather than crashing. (Additive: never raise.)"""
    memory = _seed_workspace(tmp_path)
    extracted = _extracted([{"source": "Ghost Entity", "target": "thing", "label": "uses"}])
    # Should not raise even though no `ghost-entity.md` exists.
    result = claim_pipeline.run_claim_pipeline(
        extracted, [], memory, _settings(memory), now_date="2026-06-18"
    )
    assert isinstance(result, dict)
