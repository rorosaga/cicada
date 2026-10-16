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


def _count_parses(monkeypatch) -> list:
    calls: list = []
    real = markdown_parser.load_yaml
    monkeypatch.setattr(markdown_parser, "load_yaml", lambda text: calls.append(1) or real(text))
    return calls


ODD = {"edges": [
    {"source": "é-ü", "target": "x", "label": "2026-10-08", "n": 1.5, "flag": True, "when": datetime.date(2026, 10, 8),
     "quote": "a: 'b' \"c\"", "none": None, "emoji": "\U0001F389", "yes": "yes", "num": "0012", "empty": ""},
    {"source": "alpha-project", "target": "beta-tool", "label": "uses", "claim_id": "clm_1", "valid_from": "2026-01-02"},
]}


def test_a_read_after_a_write_is_a_copy_of_what_was_written_not_a_parse(tmp_path, monkeypatch):
    """2026-10-16 perf: a Sleep batch read `graph_edges.yaml` ~5 times (~1.1 s a parse at 36k edges), each read but
    the first straight after another step's write. The writer now leaves what it wrote for the next reader."""
    path = tmp_path / "graph_edges.yaml"
    markdown_parser.write_yaml(path, ODD)
    parses = _count_parses(monkeypatch)

    served = markdown_parser.load_yaml_file(path)

    assert parses == []
    assert served == ODD == yaml.safe_load(path.read_text(encoding="utf-8"))   # exactly what a parse returns
    served["edges"].append({"source": "x", "target": "y", "label": "z"})       # a caller's edit stays its own
    assert markdown_parser.load_yaml_file(path) == ODD
    assert parses == []


def test_a_file_changed_by_anyone_else_is_parsed_again(tmp_path, monkeypatch):
    path = tmp_path / "graph_edges.yaml"
    markdown_parser.write_yaml(path, EDGES)
    parses = _count_parses(monkeypatch)
    path.write_text(yaml.safe_dump({"edges": EDGES["edges"][:2]}), encoding="utf-8")   # an in-place rewrite

    assert markdown_parser.load_yaml_file(path) == {"edges": EDGES["edges"][:2]}
    assert parses == [1]
    assert markdown_parser.load_yaml_file(path) == {"edges": EDGES["edges"][:2]}   # and then served from memory
    assert parses == [1]

    path.write_text("edges: [unterminated", encoding="utf-8")
    with pytest.raises(yaml.YAMLError):
        markdown_parser.load_yaml_file(path)
    path.unlink()
    with pytest.raises(OSError):
        markdown_parser.load_yaml_file(path)


def test_one_sleep_write_pass_parses_the_edges_file_at_most_once(tmp_path, monkeypatch):
    bank = _bank(tmp_path)
    markdown_parser.write_yaml(bank / "graph_edges.yaml", EDGES)
    parses = _count_parses(monkeypatch)

    conflict_resolver.apply_changes([_update("alpha-project")], bank)
    inbox_generator._write_graph_edges(bank, [{"source": "beta-tool", "target": "gamma-person", "label": "helps"}])
    graph_builder.regenerate_edges_from_claims(bank)
    conflict_resolver.apply_changes([_update("beta-tool")], bank)

    assert parses == []
    on_disk = yaml.safe_load((bank / "graph_edges.yaml").read_text(encoding="utf-8"))
    assert markdown_parser.load_yaml_file(bank / "graph_edges.yaml") == on_disk
    assert {"source": "beta-tool", "target": "gamma-person", "label": "helps"} in on_disk["edges"]


def test_a_write_never_leaves_its_data_under_another_writers_file(tmp_path, monkeypatch):
    """Another process can replace the file between this write's rename and any later stat of the path. What this
    write left for the next reader is keyed on its own file, so the other writer's file is parsed, not masked."""
    path = tmp_path / "graph_edges.yaml"
    foreign = {"edges": EDGES["edges"][:1]}
    real_replace = markdown_parser._replace

    def replace_then_another_writer(filepath, data):
        stamp = real_replace(filepath, data)
        other = tmp_path / ".other.tmp"
        other.write_text(yaml.safe_dump(foreign), encoding="utf-8")
        import os
        os.replace(other, filepath)
        return stamp

    monkeypatch.setattr(markdown_parser, "_replace", replace_then_another_writer)
    markdown_parser.write_yaml(path, EDGES)

    assert markdown_parser.load_yaml_file(path) == foreign
