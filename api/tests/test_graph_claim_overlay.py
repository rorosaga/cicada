"""Tests for the additive M5b claim overlay on GET /graph (d2 §2).

The overlay is OPTIONAL and additive: a graph with no claims behaves exactly as
before (no observers/contexts/facets, links unchanged), and the new fields only
populate when in-page claims exist. These guards are what let the shipped d3
graph consumer keep working untouched.
"""

from __future__ import annotations

from api.services import markdown_parser
from api.services.claims import Claim, write_claims
from api.services.graph_builder import build_graph


def _write_entity(memory_path, stem, name, claims=None, **fm_extra):
    entities_dir = memory_path / "entities"
    entities_dir.mkdir(parents=True, exist_ok=True)
    fm = {"name": name, "type": "concept", "status": "active", "confidence": 0.8}
    fm.update(fm_extra)
    body = write_claims("A page.", claims or [])
    markdown_parser.write(entities_dir / f"{stem}.md", fm, body)


def _write_edges(memory_path, edges):
    import yaml

    (memory_path / "graph_edges.yaml").write_text(
        yaml.dump({"edges": edges}, sort_keys=False), encoding="utf-8"
    )


def test_graph_without_claims_has_empty_overlay(tmp_path):
    _write_entity(tmp_path, "cicada", "Cicada")
    _write_edges(tmp_path, [])
    resp = build_graph(tmp_path)
    node = next(n for n in resp.nodes if n.id == "cicada")
    assert node.observers == []
    assert node.contexts == []
    assert node.is_facet is False
    assert resp.observers == []


def test_graph_node_gets_observers_and_contexts_from_claims(tmp_path):
    _write_entity(
        tmp_path, "rodrigo", "Rodrigo",
        [
            Claim(id="c1", text="values speed", subject="rodrigo", predicate="values",
                  object="speed", observer="agent", context="engineering"),
            Claim(id="c2", text="values presence", subject="rodrigo", predicate="values",
                  object="presence", observer="rodrigo", context="family"),
        ],
    )
    _write_edges(tmp_path, [])
    resp = build_graph(tmp_path)
    node = next(n for n in resp.nodes if n.id == "rodrigo")
    assert set(node.observers) == {"agent", "rodrigo"}
    assert set(node.contexts) == {"engineering", "family"}
    assert set(resp.observers) == {"agent", "rodrigo"}


def test_graph_emits_facet_subnodes_for_multicontext_subject(tmp_path):
    _write_entity(
        tmp_path, "rodrigo", "Rodrigo",
        [
            Claim(id="c1", text="values speed", subject="rodrigo", context="engineering"),
            Claim(id="c2", text="values presence", subject="rodrigo", context="family"),
        ],
    )
    _write_edges(tmp_path, [])
    resp = build_graph(tmp_path)
    facet_nodes = [n for n in resp.nodes if n.is_facet]
    facet_ids = {n.id for n in facet_nodes}
    assert "rodrigo#engineering" in facet_ids
    assert "rodrigo#family" in facet_ids
    eng = next(n for n in facet_nodes if n.id == "rodrigo#engineering")
    assert eng.parent_id == "rodrigo"
    assert eng.context == "engineering"
    # a facetOf edge links the satellite to its parent
    assert any(
        l.source == "rodrigo#engineering" and l.target == "rodrigo" and l.label == "facetOf"
        for l in resp.links
    )


def test_graph_single_context_subject_has_no_facet_subnodes(tmp_path):
    _write_entity(
        tmp_path, "cicada", "Cicada",
        [
            Claim(id="c1", text="uses sqlite", subject="cicada", context="engineering"),
            Claim(id="c2", text="uses fastapi", subject="cicada", context="engineering"),
        ],
    )
    _write_edges(tmp_path, [])
    resp = build_graph(tmp_path)
    assert not any(n.is_facet for n in resp.nodes)


def test_graph_links_get_context_and_claimid_from_matching_claim(tmp_path):
    _write_entity(
        tmp_path, "cicada", "Cicada",
        [
            Claim(id="clm_uses", text="uses sqlite-vec", subject="cicada",
                  predicate="uses", object="sqlite-vec", context="engineering"),
        ],
    )
    _write_entity(tmp_path, "sqlite-vec", "sqlite-vec")
    _write_edges(tmp_path, [{"source": "cicada", "target": "sqlite-vec", "label": "uses"}])
    resp = build_graph(tmp_path)
    link = next(
        l for l in resp.links if l.source == "cicada" and l.target == "sqlite-vec"
    )
    assert link.context == "engineering"
    assert link.claim_id == "clm_uses"


def test_graph_links_get_context_and_claimid_with_multiword_label(tmp_path):
    """Regression for the raw-vs-normalized predicate mismatch (M5b review #1).

    The edge label in graph_edges.yaml is the RAW multi-word form (``depends on``)
    while the seeded claim carries the NORMALIZED predicate (``depends-on``). The
    overlay must normalize the link label through the same predicate map before
    the lookup, or the context/claim-id tagging silently misses every multi-word
    edge (~70% of the real graph).
    """
    from api.services import predicates

    predicates.install_predicate_map(tmp_path)
    _write_entity(
        tmp_path, "cicada", "Cicada",
        [
            Claim(id="clm_dep", text="depends on leann", subject="cicada",
                  predicate="depends-on", object="leann", context="engineering"),
        ],
    )
    _write_entity(tmp_path, "leann", "LEANN")
    _write_edges(tmp_path, [{"source": "cicada", "target": "leann", "label": "depends on"}])
    resp = build_graph(tmp_path)
    link = next(l for l in resp.links if l.source == "cicada" and l.target == "leann")
    assert link.context == "engineering"
    assert link.claim_id == "clm_dep"


def test_graph_superseded_claims_excluded_from_overlay(tmp_path):
    _write_entity(
        tmp_path, "cicada", "Cicada",
        [
            Claim(id="c_valid", text="uses sqlite", subject="cicada", context="engineering"),
            Claim(id="c_old", text="used postgres", subject="cicada", context="career",
                  valid_to="2026-05-05"),  # closed -> not in overlay
        ],
    )
    _write_edges(tmp_path, [])
    resp = build_graph(tmp_path)
    node = next(n for n in resp.nodes if n.id == "cicada")
    assert node.contexts == ["engineering"]  # career (superseded) excluded
    assert not any(n.is_facet for n in resp.nodes)
