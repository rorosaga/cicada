"""F1 (R-FX1 … R-FX3) — what a claim context may be, and which ones the graph shows.

The owner's live graph served two satellites per annotated paper, named after a
raw folder id and `general`, and the legend listed the raw id as a context. The
table is shared with the app (`ClaimContextTests.swift`), so a rule changed on
one side only turns the other red."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from api.services import bank_index, claim_contexts, markdown_parser
from api.services.claims import Claim, write_claims
from api.services.graph_builder import build_graph

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "claim_contexts.json").read_text(encoding="utf-8"))["cases"]


@pytest.fixture(autouse=True)
def _fresh_index():
    bank_index.invalidate()
    yield
    bank_index.invalidate()


def test_the_fixture_is_not_vacuous():
    assert len(FIXTURE) >= 12


@pytest.mark.parametrize("case", FIXTURE, ids=lambda c: c["context"] or "<empty>")
def test_the_shared_table(case):
    assert claim_contexts.is_valid(case["context"]) is case["valid"]
    assert claim_contexts.is_facet(case["context"]) is case["facet"]
    if case["display"] is not None:
        assert claim_contexts.display_name(case["context"]) == case["display"]


def _entity(memory_path, stem, contexts, *, type_="concept"):
    entities = memory_path / "entities"
    entities.mkdir(parents=True, exist_ok=True)
    claims = [Claim(id=f"{stem}-c{i}", text=f"fact {i}", subject=stem, predicate="notes",
                    object=f"o{i}", object_kind="literal", context=ctx) for i, ctx in enumerate(contexts)]
    markdown_parser.write(entities / f"{stem}.md", {"name": stem.replace("-", " ").title(), "type": type_},
                          write_claims("## Summary\nA page.", claims))


def test_general_is_never_a_facet_dimension(tmp_path):
    _entity(tmp_path, "alpha-project", ["engineering", "general"])
    assert [n.id for n in build_graph(tmp_path).nodes if n.is_facet] == []


def test_two_real_contexts_still_split_and_general_stays_on_the_parent(tmp_path):
    _entity(tmp_path, "bob-example", ["engineering", "family", "general"])
    graph = build_graph(tmp_path)
    facets = {n.id: n for n in graph.nodes if n.is_facet}
    assert sorted(facets) == ["bob-example#engineering", "bob-example#family"]
    assert facets["bob-example#engineering"].name == "Engineering"
    assert facets["bob-example#engineering"].context == "engineering"
    parent = next(n for n in graph.nodes if n.id == "bob-example")
    assert parent.contexts == ["engineering", "family", "general"]


def test_a_value_that_is_not_a_context_never_reaches_the_graph(tmp_path):
    _entity(tmp_path, "media-arxiv-2401-00001", ["folder:f0a1b2:reading-list", "general"], type_="media")
    # G60's "both" answer writes `as of <date>` to keep two claims apart — still
    # a key, never a satellite.
    _entity(tmp_path, "gamma-project", ["as of 2026-05-01", "as of 2026-06-01"])
    graph = build_graph(tmp_path)
    assert [n.id for n in graph.nodes if n.is_facet] == []
    assert not any(n.name.startswith("folder:") for n in graph.nodes)
    by_id = {n.id: n for n in graph.nodes}
    assert by_id["media-arxiv-2401-00001"].contexts == ["general"]
    assert by_id["gamma-project"].contexts == []


def test_an_edge_whose_claim_has_no_real_context_carries_none(tmp_path):
    entities = tmp_path / "entities"
    entities.mkdir(parents=True)
    claim = Claim(id="c1", text="Cited in Alpha Project.", subject="media-arxiv-2401-00001",
                  predicate="cited-in", object="alpha-project", context="folder:f0a1b2:reading-list")
    markdown_parser.write(entities / "media-arxiv-2401-00001.md", {"name": "Paper Alpha", "type": "media"},
                          write_claims("## Summary\nSaved paper — Paper Alpha.", [claim]))
    markdown_parser.write(entities / "alpha-project.md", {"name": "Alpha Project", "type": "project"},
                          "## Summary\nA project.")
    (tmp_path / "graph_edges.yaml").write_text(yaml.dump({"edges": [
        {"source": "media-arxiv-2401-00001", "target": "alpha-project", "label": "cited-in"}]}),
        encoding="utf-8")
    (link,) = [l for l in build_graph(tmp_path).links if l.label == "cited-in"]
    assert link.claim_id == "c1" and link.context is None
