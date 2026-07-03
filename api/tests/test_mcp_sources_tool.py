import importlib
mcp = importlib.import_module("mcp.server")


def test_sources_tool_registered_and_dispatches(monkeypatch, tmp_path):
    # tool advertised
    assert "cicada_sources" in {t["name"] for t in mcp.TOOLS}
    # dispatch renders episode chunks
    ents = tmp_path / "entities"; ents.mkdir()
    eps = tmp_path / "episodes"; eps.mkdir()
    (ents / "e.md").write_text("---\nname: E\ntype: person\nstatus: active\nconfidence: 0.5\n"
                               "source_episodes:\n- ep_1\n---\n\n## Summary\nx\n")
    (eps / "ep_1.md").write_text("---\nid: ep_1\nsource_id: c1\n---\n\nuser: q\nassistant: a\n")
    monkeypatch.setattr(mcp, "get_memory_path", lambda: tmp_path)
    out = mcp.handle_tool("cicada_sources", {"entity_id": "e"})
    assert "ep_1" in out and "assistant: a" in out
