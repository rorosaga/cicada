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
    assert "type: person" in page


def test_skips_date_like_targets(tmp_path):
    ents = tmp_path / "entities"; ents.mkdir()
    (ents / "specialist-role.md").write_text(
        "---\nname: Specialist Role\ntype: project\nstatus: active\nconfidence: 0.7\n---\n\n"
        "## Summary\nDeadline mentioned.\n")
    (tmp_path / "graph_edges.yaml").write_text(yaml.safe_dump({"edges": [
        {"source": "specialist-role", "target": "2026-09-01", "label": "reports-to"},
    ]}))
    created = promote_relationship_targets(tmp_path, min_refs=1)
    assert "2026-09-01" not in created
    assert not (ents / "2026-09-01.md").exists()


def test_skips_target_without_person_signal(tmp_path):
    ents = tmp_path / "entities"; ents.mkdir()
    (ents / "specialist-role.md").write_text(
        "---\nname: Specialist Role\ntype: project\nstatus: active\nconfidence: 0.7\n---\n\n"
        "## Summary\nReferences some-concept.\n")
    (tmp_path / "graph_edges.yaml").write_text(yaml.safe_dump({"edges": [
        {"source": "specialist-role", "target": "some-concept", "label": "references"},
    ]}))
    created = promote_relationship_targets(tmp_path, min_refs=1)
    assert "some-concept" not in created
    assert not (ents / "some-concept.md").exists()


def test_promotes_person_signal_target(tmp_path):
    ents = tmp_path / "entities"; ents.mkdir()
    (ents / "specialist-role.md").write_text(
        "---\nname: Specialist Role\ntype: project\nstatus: active\nconfidence: 0.7\n---\n\n"
        "## Summary\nWorks with Jane Doe.\n")
    (tmp_path / "graph_edges.yaml").write_text(yaml.safe_dump({"edges": [
        {"source": "specialist-role", "target": "jane-doe", "label": "works-with"},
    ]}))
    created = promote_relationship_targets(tmp_path, min_refs=1)
    assert "jane-doe" in created
    page = (ents / "jane-doe.md").read_text()
    assert "Jane Doe" in page
    assert "type: person" in page
