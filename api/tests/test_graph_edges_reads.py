"""`graph_edges.yaml` is read once per Stage-5 write and through the libyaml loader.

Measured on a 2,000-page synthetic bank (benchmarks/scale): the file grows with the claims (3.7 MB, 35k edges), one
pure-Python `yaml.safe_load` of it costs ~3.8 s, and `_reconcile_related` paid that once per merged entity — 86 s of
a 148 s Sleep batch. These tests pin the read count and the loader, and that the `## Related` blocks they build are
unchanged.
"""
from __future__ import annotations

import datetime
from pathlib import Path

import pytest
import yaml

from api.services import conflict_resolver, graph_builder, hub_builder, inbox_generator, markdown_parser

EDGES = {"edges": [
    {"source": "alpha-project", "target": "beta-tool", "label": "uses"},
    {"source": "gamma-person", "target": "alpha-project", "label": "works on"},
    {"source": "beta-tool", "target": "delta-concept", "label": "implements"},
    {"source": "alpha-project", "target": "alpha-project", "label": "self"},
    {"source": "alpha-project", "target": "missing-page", "label": "cites"},
    {"source": "delta-concept", "target": "beta-tool", "label": "explains", "claim_id": "clm_x"},
]}
PAGES = {
    "alpha-project": ("Alpha Project", "project", ["gamma-person", "delta-concept"]),
    "beta-tool": ("Beta Tool", "tool", []),
    "gamma-person": ("Gamma Person", "person", ["alpha-project"]),
    "delta-concept": ("Delta Concept", "concept", []),
}


def _bank(tmp_path: Path, edges=EDGES) -> Path:
    bank = tmp_path / "bank"
    (bank / "entities").mkdir(parents=True)
    for eid, (name, kind, related) in PAGES.items():
        markdown_parser.write(bank / "entities" / f"{eid}.md",
                              {"id": eid, "name": name, "type": kind, "confidence": 0.8, "related": related},
                              "## Summary\nSynthetic page.\n")
    if edges is not None:
        (bank / "graph_edges.yaml").write_text(yaml.dump(edges, sort_keys=False), encoding="utf-8")
    return bank


def _update(eid: str) -> dict:
    name, kind, _ = PAGES[eid]
    return {"id": eid, "action": "update", "entity": {"name": name, "type": kind, "confidence": 0.8}}


def _related(bank: Path, eid: str) -> str:
    body = markdown_parser.parse(bank / "entities" / f"{eid}.md").body
    return body.partition("## Related")[2].strip()


# The blocks the per-entity reads built before the change (captured from dev ef4d571c).
GOLDEN = {
    "alpha-project": "- [[Beta Tool]] — uses\n- [[Gamma Person]] — works on\n- [[Alpha Project]] — self\n- [[Delta Concept]]",
    "beta-tool": "- [[Alpha Project]] — uses\n- [[Delta Concept]] — implements",
    "gamma-person": "- [[Alpha Project]] — works on",
    "delta-concept": "- [[Beta Tool]] — implements",
}


def test_apply_changes_reads_the_edges_file_once_and_related_blocks_are_unchanged(tmp_path, monkeypatch):
    bank = _bank(tmp_path)
    reads = []
    original = Path.read_text

    def counting(self, *args, **kwargs):
        if self.name == "graph_edges.yaml":
            reads.append(self)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counting)
    conflict_resolver.apply_changes([_update(eid) for eid in PAGES], bank)
    assert len(reads) == 1
    assert {eid: _related(bank, eid) for eid in PAGES} == GOLDEN


def test_apply_changes_without_an_edges_file_or_with_a_broken_one_keeps_related_slugs(tmp_path):
    for edges in (None, "edges: [unterminated"):
        bank = _bank(tmp_path / str(edges is None), edges=None)
        if edges is not None:
            (bank / "graph_edges.yaml").write_text(edges, encoding="utf-8")
        conflict_resolver.apply_changes([_update("alpha-project")], bank)
        assert _related(bank, "alpha-project") == "- [[Gamma Person]]\n- [[Delta Concept]]", edges


def test_apply_changes_with_no_update_never_reads_the_edges_file(tmp_path, monkeypatch):
    bank = _bank(tmp_path)
    monkeypatch.setattr(markdown_parser, "load_yaml", lambda text: pytest.fail("read without an update"))
    conflict_resolver.apply_changes([], bank)


def test_load_yaml_is_safe_load():
    text = yaml.dump({"edges": [{"source": "é-ü", "target": "x", "label": "2026-10-08", "n": 1.5, "flag": True,
                                 "when": datetime.date(2026, 10, 8), "quote": "a: 'b' \"c\"", "none": None}]},
                     allow_unicode=True)
    assert markdown_parser.load_yaml(text) == yaml.safe_load(text)
    assert markdown_parser.load_yaml("") is None
    with pytest.raises(yaml.YAMLError):
        markdown_parser.load_yaml("edges: [unterminated")


def test_no_edges_reader_uses_the_pure_python_loader(tmp_path, monkeypatch):
    bank = _bank(tmp_path)
    monkeypatch.setattr(yaml, "safe_load", lambda *a, **k: pytest.fail("pure-Python safe_load on graph_edges.yaml"))
    assert len(graph_builder._load_edges(bank)) == 6
    assert hub_builder._count_edges(bank) == 6
    conflict_resolver.apply_changes([_update("alpha-project")], bank)
    inbox_generator._write_graph_edges(bank, [{"source": "beta-tool", "target": "gamma-person", "label": "helps"}])
    assert hub_builder._count_edges(bank) == 7
    graph_builder.regenerate_edges_from_claims(bank)
    graph_builder.upsert_claim_edges(bank, ["alpha-project"])
