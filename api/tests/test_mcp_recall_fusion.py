import importlib
mcp = importlib.import_module("mcp.server")


def test_rrf_fuse_rewards_agreement():
    semantic = [{"entity_id": "a"}, {"entity_id": "b"}, {"entity_id": "c"}]
    keyword = [{"entity_id": "b"}, {"entity_id": "a"}]
    fused = mcp._rrf_fuse(semantic, keyword)
    ids = [h["entity_id"] for h in fused]
    # 'a' and 'b' both appear in both lists near the top -> outrank 'c'
    assert ids.index("a") < ids.index("c") and ids.index("b") < ids.index("c")
    assert set(ids) == {"a", "b", "c"}
