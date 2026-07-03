from pathlib import Path
import yaml
from api.services.entity_merge import merge_entities


def _write(ents: Path, eid: str, fm: dict, body: str):
    (ents / f"{eid}.md").write_text("---\n" + yaml.safe_dump(fm, sort_keys=False) + "---\n\n" + body)


def test_merge_unions_sources_and_repoints_edges(tmp_path):
    ents = tmp_path / "entities"; ents.mkdir()
    _write(ents, "user", {"name": "user", "type": "person", "status": "active",
                          "confidence": 0.8, "source_episodes": ["ep_1"], "related": ["mongodb"]},
           "## Summary\nThe user.\n\n## Key Facts\n- likes concise summaries\n")
    _write(ents, "rorosaga", {"name": "rorosaga", "type": "person", "status": "active",
                             "confidence": 0.7, "source_episodes": ["ep_2"], "related": ["barcelona"]},
           "## Summary\nGitHub handle.\n\n## Key Facts\n- based in Barcelona\n")
    (tmp_path / "graph_edges.yaml").write_text(yaml.safe_dump(
        {"edges": [{"source": "rorosaga", "target": "mongodb", "label": "works-at"}]}))

    out = merge_entities(tmp_path, loser_id="rorosaga", winner_id="user")

    assert not (ents / "rorosaga.md").exists()          # loser deleted
    win = (ents / "user.md").read_text()
    assert "ep_1" in win and "ep_2" in win               # source_episodes unioned
    assert "based in Barcelona" in win                    # loser Key Facts merged in
    edges = yaml.safe_load((tmp_path / "graph_edges.yaml").read_text())["edges"]
    assert edges[0]["source"] == "user"                   # edge repointed
    assert out["repointed_edges"] == 1
