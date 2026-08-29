"""Tests for graph_builder summary/content_hash node enrichment (sync-engine task 4).

Nodes carry a short `summary` (derived from the entity body) and a
`content_hash` (derived from frontmatter + body) so the companion app's
sync engine can detect per-node content changes without diffing full bodies.
"""

from __future__ import annotations


def test_summarize_prefers_summary_section():
    from api.services.graph_builder import summarize

    body = "# Title\n\n## Summary\n\nA person who does robotics.\nMore.\n\n## Key Facts\n- x"
    assert summarize(body) == "A person who does robotics."
    assert summarize("just\nplain text here") == "just plain text here"
    assert summarize("") is None
    assert len(summarize("x" * 500)) == 200


def test_graph_nodes_have_summary_and_hash(tmp_path):
    from api.services import bank_index
    from api.services.graph_builder import build_graph

    bank_index.invalidate()
    (tmp_path / "entities").mkdir()
    (tmp_path / "entities" / "a.md").write_text("---\nname: A\ntype: concept\n---\n## Summary\n\nAbout A.\n")
    g = build_graph(tmp_path)
    node = next(n for n in g.nodes if n.id == "a")
    assert node.summary == "About A." and len(node.content_hash) == 12
    (tmp_path / "entities" / "a.md").write_text("---\nname: A\ntype: concept\n---\n## Summary\n\nAbout A, changed.\n")
    import time; time.sleep(0.01)
    g2 = build_graph(tmp_path)
    assert next(n for n in g2.nodes if n.id == "a").content_hash != node.content_hash
