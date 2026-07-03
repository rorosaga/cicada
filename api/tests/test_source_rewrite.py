from pathlib import Path
from api.services.source_rewrite import rewrite_entity_from_sources


def _setup(tmp_path):
    ents = tmp_path / "entities"; ents.mkdir()
    eps = tmp_path / "episodes"; eps.mkdir()
    (ents / "e.md").write_text("---\nname: E\ntype: project\nstatus: active\nconfidence: 0.6\n"
                               "source_episodes:\n- ep_1\n---\n\n## Summary\nthin.\n")
    (eps / "ep_1.md").write_text("---\nid: ep_1\nsource_id: c1\n---\n\n"
                                 "user: We used Neo4j then dropped it for markdown.\n")
    return tmp_path


def test_rewrite_uses_injected_llm_and_enriches(tmp_path):
    m = _setup(tmp_path)

    def fake_llm(*, messages, response_format=None, **kw):
        # returns a richer, source-grounded body as JSON
        import json
        body = ("## Summary\nProject E used Neo4j initially, then moved to markdown.\n\n"
                "## Key Facts\n- Started on Neo4j\n- Switched to markdown files\n")
        return {"choices": [{"message": {"content": json.dumps({"body": body})}}]}

    out = rewrite_entity_from_sources(m, "e", settings=None, llm_fn=fake_llm)
    assert out["changed"] is True and out["after_words"] > out["before_words"]
    page = (m / "entities" / "e.md").read_text()
    assert "Switched to markdown" in page and "## Key Facts" in page


def test_preserves_human_edited_section(tmp_path):
    m = _setup(tmp_path)
    p = m / "entities" / "e.md"
    p.write_text("---\nname: E\ntype: project\nstatus: active\nconfidence: 0.6\n"
                 "human_edited: true\nsource_episodes:\n- ep_1\n---\n\n"
                 "## Summary\nthin.\n\n## My Notes\nDO NOT LOSE THIS.\n")
    def fake_llm(*, messages, response_format=None, **kw):
        import json
        return {"choices": [{"message": {"content": json.dumps(
            {"body": "## Summary\nRicher summary.\n\n## Key Facts\n- x\n"})}}]}
    rewrite_entity_from_sources(m, "e", settings=None, llm_fn=fake_llm)
    assert "DO NOT LOSE THIS" in p.read_text()   # human section preserved
