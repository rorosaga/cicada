from pathlib import Path
import yaml
from api.services.promote_targets import promote_relationship_targets


def test_promotes_unpaged_relationship_target(tmp_path):
    ents = tmp_path / "entities"; ents.mkdir()
    (ents / "specialist-role.md").write_text(
        "---\nname: Specialist Role\ntype: project\nstatus: active\nconfidence: 0.7\n---\n\n"
        "## Summary\nReports to Diego Albano.\n")
    (tmp_path / "graph_edges.yaml").write_text(yaml.safe_dump({"edges": [
        {"source": "specialist-role", "target": "diego-albano", "label": "reports-to"},
    ]}))
    created = promote_relationship_targets(tmp_path, min_refs=1)
    assert "diego-albano" in created
    page = (ents / "diego-albano.md").read_text()
    assert "Diego Albano" in page and "reports-to" in page.lower()
