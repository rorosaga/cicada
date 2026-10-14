"""Review of fix/merge-edges: a writer that still loses edges. Synthetic data only."""
from pathlib import Path

import yaml

from api.services import graph_builder, markdown_parser
from api.services.claims import Claim, write_claims
from api.services.inbox_generator import _write_graph_edges


def _bank(tmp_path: Path) -> Path:
    mem = tmp_path / "memory"
    (mem / "entities").mkdir(parents=True)
    for eid in ("gamma", "delta"):
        markdown_parser.write(mem / "entities" / f"{eid}.md", {"type": "person", "name": eid, "status": "active"},
                              "## Summary\nA page.")
    markdown_parser.write(
        mem / "entities" / "bob-example.md", {"type": "person", "name": "Bob Example", "status": "active"},
        write_claims("## Summary\nA person.", [Claim(id="c-1", text="x", subject="bob-example",
                                                      predicate="works-at", object="gamma", valid_from="2026-01-02")]))
    good = yaml.safe_dump({"edges": [
        {"source": "gamma", "target": "delta", "label": "employs"},
        {"source": "delta", "target": "gamma", "label": "mentions"},
        {"source": "bob-example", "target": "gamma", "label": "works-at", "observer": "agent",
         "context": "general", "claim_id": "c-1", "valid_from": "2026-01-02"},
    ]}, sort_keys=False)
    # Unreadable: e.g. a non-atomic write cut short, or a hand edit.
    (mem / "graph_edges.yaml").write_text(good + "  - {source: [unclosed\n", encoding="utf-8")
    return mem


def test_a_sleep_pass_never_overwrites_an_unreadable_edges_file(tmp_path):
    """Stage 5 now refuses an unreadable file (this branch); Stage 5.7 runs next in the same Sleep and must too."""
    mem = _bank(tmp_path)
    before = (mem / "graph_edges.yaml").read_bytes()
    _write_graph_edges(mem, [{"source": "gamma", "target": "bob-example", "label": "knows"}])   # Stage 5
    assert (mem / "graph_edges.yaml").read_bytes() == before                                   # refused: passes
    graph_builder.regenerate_edges_from_claims(mem)                                            # Stage 5.7
    assert (mem / "graph_edges.yaml").read_bytes() == before, \
        "Stage 5.7 replaced an unreadable graph_edges.yaml with the claim rows alone; every bare edge is gone"
