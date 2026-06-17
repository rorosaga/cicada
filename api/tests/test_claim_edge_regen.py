"""Tests for M5e Stage-5 valid-only claim-edge regeneration + origin derivation.

``graph_builder.regenerate_edges_from_claims`` projects currently-valid claims
into ``graph_edges.yaml``, tagging each edge with observer / context / claim_id.
Closed (superseded) claims are excluded; a bank with no claims is left untouched
so seeded/legacy edge graphs are not wiped. Plus the ``sleep_cycle`` legacy
``source`` -> G9 ``origin`` derivation table.
"""

from __future__ import annotations

import yaml

from api.services import markdown_parser, sleep_cycle
from api.services.claims import Claim, write_claims
from api.services.graph_builder import regenerate_edges_from_claims


def _write_subject(memory_path, stem, name, claims):
    entities_dir = memory_path / "entities"
    entities_dir.mkdir(parents=True, exist_ok=True)
    body = write_claims(f"{name} page.", claims)
    markdown_parser.write(
        entities_dir / f"{stem}.md",
        {"name": name, "type": "concept", "status": "active"},
        body,
    )


def test_regenerate_edges_tags_observer_and_context(tmp_path):
    _write_subject(
        tmp_path, "cicada", "Cicada",
        [
            Claim(id="clm_1", text="uses sqlite-vec", subject="cicada",
                  predicate="uses", object="sqlite-vec",
                  observer="agent", context="engineering", valid_from="2026-01-01"),
        ],
    )
    n = regenerate_edges_from_claims(tmp_path)
    assert n == 1
    data = yaml.safe_load((tmp_path / "graph_edges.yaml").read_text())
    edge = data["edges"][0]
    assert edge["source"] == "cicada"
    assert edge["target"] == "sqlite-vec"
    assert edge["label"] == "uses"
    assert edge["observer"] == "agent"
    assert edge["context"] == "engineering"
    assert edge["claim_id"] == "clm_1"


def test_regenerate_edges_excludes_superseded_claims(tmp_path):
    _write_subject(
        tmp_path, "cicada", "Cicada",
        [
            Claim(id="clm_old", text="uses postgres", subject="cicada",
                  predicate="uses", object="postgres",
                  valid_to="2026-05-05", superseded_by="clm_new"),
            Claim(id="clm_new", text="uses sqlite-vec", subject="cicada",
                  predicate="uses", object="sqlite-vec", supersedes="clm_old"),
        ],
    )
    regenerate_edges_from_claims(tmp_path)
    data = yaml.safe_load((tmp_path / "graph_edges.yaml").read_text())
    targets = {e["target"] for e in data["edges"]}
    assert targets == {"sqlite-vec"}, "closed claim must not produce an edge"


def test_regenerate_edges_noop_when_no_claims_preserves_legacy(tmp_path):
    entities_dir = tmp_path / "entities"
    entities_dir.mkdir(parents=True, exist_ok=True)
    # a legacy entity page with NO claims block
    markdown_parser.write(
        entities_dir / "fastapi.md",
        {"name": "FastAPI", "type": "tool", "status": "active"},
        "FastAPI is a framework.",
    )
    # a pre-existing seeded edge graph
    (tmp_path / "graph_edges.yaml").write_text(
        yaml.dump({"edges": [{"source": "cicada", "target": "fastapi", "label": "uses"}]}),
        encoding="utf-8",
    )
    n = regenerate_edges_from_claims(tmp_path)
    assert n == 0, "no claims => leave the existing edge graph untouched"
    data = yaml.safe_load((tmp_path / "graph_edges.yaml").read_text())
    assert data["edges"][0]["source"] == "cicada"  # legacy edge preserved


def test_regenerate_edges_preserves_non_claim_edges_in_mixed_bank(tmp_path):
    """M5e review MUST-FIX: the mixed state (some pages have claims, a populated
    legacy graph_edges.yaml exists) must NOT wipe the non-claim edges.

    This is the real post-M5b-seeding + first-Sleep-cycle state: relationship,
    wikilink-``mentions`` and media-``about`` edges have already been written into
    graph_edges.yaml earlier in the same cycle; Stage 5.7 runs after them and must
    MERGE its claim-derived edges in, not clobber the whole file.
    """
    # One page carries a claim → an edge will be derived from it.
    _write_subject(
        tmp_path, "cicada", "Cicada",
        [
            Claim(id="clm_1", text="uses sqlite-vec", subject="cicada",
                  predicate="uses", object="sqlite-vec",
                  observer="agent", context="engineering", valid_from="2026-01-01"),
        ],
    )
    # A pre-existing edge graph populated earlier in the cycle (relationship +
    # wikilink-mentions + media-about edges) that have NO backing claim.
    (tmp_path / "graph_edges.yaml").write_text(
        yaml.dump({"edges": [
            {"source": "cicada", "target": "fastapi", "label": "uses"},
            {"source": "cicada", "target": "leann-paper", "label": "mentions"},
            {"source": "bookmark-1", "target": "cicada", "label": "about"},
        ]}),
        encoding="utf-8",
    )

    regenerate_edges_from_claims(tmp_path)

    data = yaml.safe_load((tmp_path / "graph_edges.yaml").read_text())
    pairs = {(e["source"], e["target"], e["label"]) for e in data["edges"]}
    # the non-claim edges survive
    assert ("cicada", "fastapi", "uses") in pairs
    assert ("cicada", "leann-paper", "mentions") in pairs
    assert ("bookmark-1", "cicada", "about") in pairs
    # and the claim-derived edge is present too
    assert ("cicada", "sqlite-vec", "uses") in pairs


def test_regenerate_edges_supersedes_stale_claim_edge_on_reconsolidation(tmp_path):
    """A claim-derived edge whose claim was later superseded must not linger.

    When a single-valued claim is closed and replaced, re-running the regen must
    drop the old claim's edge (its object changed) while preserving genuinely
    non-claim edges. Claim-derived edges are identified by their tag, so a stale
    one is replaced rather than accumulating.
    """
    _write_subject(
        tmp_path, "cicada", "Cicada",
        [
            Claim(id="clm_old", text="uses postgres", subject="cicada",
                  predicate="current-stack", object="postgres",
                  observer="agent", context="engineering",
                  valid_to="2026-05-05", superseded_by="clm_new"),
            Claim(id="clm_new", text="uses sqlite-vec", subject="cicada",
                  predicate="current-stack", object="sqlite-vec",
                  observer="agent", context="engineering",
                  supersedes="clm_old", valid_from="2026-05-05"),
        ],
    )
    # A previous cycle had written the now-stale claim edge into the file plus an
    # unrelated non-claim edge.
    (tmp_path / "graph_edges.yaml").write_text(
        yaml.dump({"edges": [
            {"source": "cicada", "target": "postgres", "label": "current-stack",
             "claim_id": "clm_old", "observer": "agent", "context": "engineering"},
            {"source": "cicada", "target": "fastapi", "label": "uses"},
        ]}),
        encoding="utf-8",
    )

    regenerate_edges_from_claims(tmp_path)

    data = yaml.safe_load((tmp_path / "graph_edges.yaml").read_text())
    pairs = {(e["source"], e["target"], e["label"]) for e in data["edges"]}
    assert ("cicada", "postgres", "current-stack") not in pairs, (
        "stale superseded claim edge must be dropped on re-regen"
    )
    assert ("cicada", "sqlite-vec", "current-stack") in pairs
    assert ("cicada", "fastapi", "uses") in pairs, "non-claim edge preserved"


def test_derive_origin_table():
    assert sleep_cycle._derive_origin("mcp") == "claude-code"
    assert sleep_cycle._derive_origin("claude") == "claude-code"
    assert sleep_cycle._derive_origin("claude_project") == "claude-code"
    assert sleep_cycle._derive_origin("telegram") == "telegram"
    assert sleep_cycle._derive_origin("rss") == "rss"
    assert sleep_cycle._derive_origin("") == "unknown"
    assert sleep_cycle._derive_origin(None) == "unknown"
    # an already origin-shaped value passes through
    assert sleep_cycle._derive_origin("codex") == "codex"
