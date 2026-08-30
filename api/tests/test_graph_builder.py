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


def test_synthetic_hub_and_repo_nodes_have_stable_hashes(tmp_path):
    """hub:* / repo:* nodes must carry a real content_hash.

    They have no file behind them, so they used to ship ``content_hash=""``.
    The companion app's delta diff treats an empty hash as "assume changed",
    which re-pushed every synthetic node in every delta (126 of them in the
    live bank). The hash must be deterministic across rebuilds and must move
    only when the node's defining fields move.
    """
    import time

    from api.services import bank_index
    from api.services.graph_builder import build_graph

    bank_index.invalidate()
    (tmp_path / "entities").mkdir()
    (tmp_path / "entities" / "a.md").write_text(
        "---\nname: A\ntype: project\n"
        "repos:\n  - path: ~/code/alpha\n---\nbody\n"
    )
    (tmp_path / "hubs").mkdir()
    (tmp_path / "hubs" / "h.md").write_text(
        "---\nname: H\ntype: hub\nhub_kind: type\nmember_count: 1\n"
        "members:\n  - id: a\n---\n"
    )

    g1 = build_graph(tmp_path)
    hub = next(n for n in g1.nodes if n.id == "hub:h")
    repo = next(n for n in g1.nodes if n.id.startswith("repo:"))
    assert len(hub.content_hash) == 12
    assert len(repo.content_hash) == 12
    assert hub.content_hash != repo.content_hash

    # Stable across an unrelated rebuild (cache-busted by an entity edit).
    (tmp_path / "entities" / "b.md").write_text("---\nname: B\ntype: concept\n---\nb\n")
    time.sleep(0.01)
    bank_index.invalidate()
    g2 = build_graph(tmp_path)
    assert next(n for n in g2.nodes if n.id == "hub:h").content_hash == hub.content_hash
    assert next(n for n in g2.nodes if n.id == repo.id).content_hash == repo.content_hash

    # Changing a defining field moves the hash.
    (tmp_path / "hubs" / "h.md").write_text(
        "---\nname: H renamed\ntype: hub\nhub_kind: type\nmember_count: 1\n"
        "members:\n  - id: a\n---\n"
    )
    time.sleep(0.01)
    bank_index.invalidate()
    g3 = build_graph(tmp_path)
    assert next(n for n in g3.nodes if n.id == "hub:h").content_hash != hub.content_hash


def test_no_graph_node_ships_an_empty_content_hash(tmp_path):
    import time

    from api.services import bank_index
    from api.services.graph_builder import build_graph

    bank_index.invalidate()
    (tmp_path / "entities").mkdir()
    (tmp_path / "entities" / "a.md").write_text(
        "---\nname: A\ntype: project\nrepos:\n  - path: ~/code/alpha\n---\nbody\n"
    )
    # Two claim contexts on one subject spawn `a#career` / `a#personal` facet
    # sub-nodes — a third family of synthetic, file-less nodes.
    claims_block = (
        "---\nname: C\ntype: person\n---\n\n"
        "```claims\n"
        "- id: clm_a\n  text: C works.\n  subject: c\n  predicate: works-at\n"
        "  object: a\n  context: career\n  confidence: 0.9\n"
        "- id: clm_b\n  text: C rests.\n  subject: c\n  predicate: enjoys\n"
        "  object: a\n  context: personal\n  confidence: 0.9\n"
        "```\n"
    )
    (tmp_path / "entities" / "c.md").write_text(claims_block)
    (tmp_path / "hubs").mkdir()
    (tmp_path / "hubs" / "h.md").write_text(
        "---\nname: H\ntype: hub\nmembers:\n  - id: a\n---\n"
    )
    time.sleep(0.01)
    g = build_graph(tmp_path)
    empty = [n.id for n in g.nodes if not n.content_hash]
    assert empty == [], f"nodes with no content_hash re-push on every delta: {empty}"
    kinds = {n.id.split(":")[0] for n in g.nodes if ":" in n.id}
    assert {"hub", "repo"} <= kinds
    # All three synthetic families must actually be present, or the assertion
    # above passes vacuously.
    facets = [n.id for n in g.nodes if n.is_facet]
    assert sorted(facets) == ["c#career", "c#personal"], facets
