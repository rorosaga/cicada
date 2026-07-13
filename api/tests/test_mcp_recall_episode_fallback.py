"""Regression test: a total-miss query (no entity/inbox/hub signal) must still
surface episode excerpts instead of short-circuiting on the premature early
return that Task 5 originally introduced.

Hermetic: every retrieval source handle_recall touches is monkeypatched, so
this never hits LEANN, an LLM, or the live ~/cicada/memory bank.
"""

import importlib

mcp = importlib.import_module("mcp.server")


def test_total_miss_falls_through_to_episode_excerpts(monkeypatch, tmp_path):
    # Empty entities dir so handle_recall passes its `entities_dir.exists()`
    # guard but every entity-derived signal is empty.
    (tmp_path / "entities").mkdir()

    monkeypatch.setattr(mcp, "get_memory_path", lambda: tmp_path)
    monkeypatch.setattr(mcp, "_relevant_inbox", lambda memory_path, query: [])
    monkeypatch.setattr(mcp, "_match_hub", lambda memory_path, query: (None, []))
    monkeypatch.setattr(
        mcp, "_leann_search_entities", lambda memory_path, query, top_k: []
    )
    monkeypatch.setattr(
        mcp, "_keyword_search_entities", lambda entities_dir, query, top_k: []
    )
    monkeypatch.setattr(
        mcp,
        "_leann_search_episodes",
        lambda memory_path, query, top_k: [
            {
                "metadata": {"episode_id": "ep_x"},
                "text": "the answer text about A100 Dammam",
            }
        ],
    )

    result = mcp.handle_recall("some query")

    assert "A100 Dammam" in result
    assert result != "No entities found matching 'some query'."
