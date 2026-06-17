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
