"""Hermetic tests for ORIGIN-PROVENANCE aggregation ("where did this memory
come from" — bookmark / telegram / claude-export / mcp / ...).

Every test builds a throwaway ``memory/`` tree in ``tmp_path`` with hand-written
episode + entity markdown files. The real ``memory/`` directory is never
touched. No network.
"""

from __future__ import annotations

from api.services import origin_stats


def _write_episode(memory, episode_id, *, origin=None, timestamp="2026-01-01T00:00:00Z"):
    episodes_dir = memory / "episodes"
    episodes_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "---",
        f"id: {episode_id}",
        f"timestamp: '{timestamp}'",
        "processed: true",
    ]
    if origin is not None:
        lines.append(f"origin: {origin}")
    lines += ["---", "", "some episode body"]
    (episodes_dir / f"{episode_id}.md").write_text("\n".join(lines), encoding="utf-8")


def _write_entity(memory, entity_id, *, source_episodes):
    entities_dir = memory / "entities"
    entities_dir.mkdir(parents=True, exist_ok=True)
    eps_yaml = "\n".join(f"- {ep}" for ep in source_episodes) if source_episodes else "[]"
    text = (
        "---\n"
        f"id: {entity_id}\n"
        "type: concept\n"
        "status: active\n"
        "confidence: 0.8\n"
        f"source_episodes:\n{eps_yaml}\n"
        "---\n\n"
        f"# {entity_id}\n"
    )
    (entities_dir / f"{entity_id}.md").write_text(text, encoding="utf-8")


# --- aggregate_origins (pure) -----------------------------------------------


def test_aggregate_origins_empty_when_no_episodes_dir(tmp_path):
    memory = tmp_path / "memory"
    memory.mkdir()
    assert origin_stats.aggregate_origins(memory) == []


def test_aggregate_origins_counts_episodes_per_origin(tmp_path):
    memory = tmp_path / "memory"
    _write_episode(memory, "ep_2026-01-01_001", origin="telegram", timestamp="2026-01-01T00:00:00Z")
    _write_episode(memory, "ep_2026-01-02_001", origin="chrome-bookmark", timestamp="2026-01-02T00:00:00Z")
    _write_episode(memory, "ep_2026-01-03_001", origin="mcp", timestamp="2026-01-03T00:00:00Z")
    _write_episode(memory, "ep_2026-01-04_001", origin="mcp", timestamp="2026-01-04T00:00:00Z")
    # No origin stamped at all -> falls back to "unknown".
    _write_episode(memory, "ep_2026-01-05_001", origin=None, timestamp="2026-01-05T00:00:00Z")

    results = origin_stats.aggregate_origins(memory)
    by_origin = {r["origin"]: r for r in results}

    assert by_origin["mcp"]["episodeCount"] == 2
    assert by_origin["telegram"]["episodeCount"] == 1
    assert by_origin["chrome-bookmark"]["episodeCount"] == 1
    assert by_origin["unknown"]["episodeCount"] == 1

    # Sorted by episodeCount desc; mcp (2) must come first.
    assert results[0]["origin"] == "mcp"


def test_aggregate_origins_absent_origin_defaults_to_unknown(tmp_path):
    memory = tmp_path / "memory"
    _write_episode(memory, "ep_2026-01-01_001", origin=None)

    results = origin_stats.aggregate_origins(memory)
    assert len(results) == 1
    assert results[0]["origin"] == "unknown"
    assert results[0]["episodeCount"] == 1
    assert results[0]["entityCount"] == 0


def test_aggregate_origins_counts_distinct_entities_per_origin(tmp_path):
    memory = tmp_path / "memory"
    _write_episode(memory, "ep_2026-01-01_001", origin="telegram")
    _write_episode(memory, "ep_2026-01-02_001", origin="telegram")
    _write_episode(memory, "ep_2026-01-03_001", origin="mcp")

    # entity-a cites two telegram episodes -> still counts ONCE toward telegram.
    _write_entity(memory, "entity-a", source_episodes=["ep_2026-01-01_001", "ep_2026-01-02_001"])
    # entity-b cites one telegram + one mcp episode -> counts toward BOTH origins.
    _write_entity(memory, "entity-b", source_episodes=["ep_2026-01-02_001", "ep_2026-01-03_001"])
    # entity-c cites nothing real -> contributes to no origin.
    _write_entity(memory, "entity-c", source_episodes=["ep_does_not_exist"])

    results = origin_stats.aggregate_origins(memory)
    by_origin = {r["origin"]: r for r in results}

    assert by_origin["telegram"]["entityCount"] == 2  # entity-a, entity-b
    assert by_origin["mcp"]["entityCount"] == 1  # entity-b only
    assert "entity-c" not in by_origin  # never manufactures a phantom origin


def test_aggregate_origins_last_seen_is_most_recent_timestamp(tmp_path):
    memory = tmp_path / "memory"
    _write_episode(memory, "ep_2026-01-01_001", origin="mcp", timestamp="2026-01-01T00:00:00Z")
    _write_episode(memory, "ep_2026-03-15_001", origin="mcp", timestamp="2026-03-15T09:30:00Z")

    results = origin_stats.aggregate_origins(memory)
    by_origin = {r["origin"]: r for r in results}
    assert by_origin["mcp"]["lastSeen"] == "2026-03-15T09:30:00Z"


def test_aggregate_origins_sorted_by_episode_count_desc(tmp_path):
    memory = tmp_path / "memory"
    _write_episode(memory, "ep_2026-01-01_001", origin="rare-origin")
    _write_episode(memory, "ep_2026-01-02_001", origin="common-origin")
    _write_episode(memory, "ep_2026-01-03_001", origin="common-origin")
    _write_episode(memory, "ep_2026-01-04_001", origin="common-origin")

    results = origin_stats.aggregate_origins(memory)
    assert [r["origin"] for r in results] == ["common-origin", "rare-origin"]


# --- GET /origins endpoint ---------------------------------------------------


def _make_client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from api import config, main

    memory = tmp_path / "memory"
    for sub in ("episodes", "entities"):
        (memory / sub).mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    return TestClient(main.app), memory


def test_get_origins_endpoint_returns_aggregated_list(tmp_path, monkeypatch):
    client, memory = _make_client(tmp_path, monkeypatch)

    _write_episode(memory, "ep_2026-01-01_001", origin="telegram")
    _write_episode(memory, "ep_2026-01-02_001", origin="mcp")
    _write_episode(memory, "ep_2026-01-03_001", origin="mcp")
    _write_entity(memory, "entity-a", source_episodes=["ep_2026-01-02_001"])

    resp = client.get("/origins")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert "origins" in body
    origins_by_name = {o["origin"]: o for o in body["origins"]}
    assert origins_by_name["mcp"]["episodeCount"] == 2
    assert origins_by_name["mcp"]["entityCount"] == 1
    assert origins_by_name["telegram"]["episodeCount"] == 1
    assert origins_by_name["telegram"]["entityCount"] == 0
    # Response is sorted by episodeCount desc.
    assert body["origins"][0]["origin"] == "mcp"


def test_get_origins_endpoint_empty_memory(tmp_path, monkeypatch):
    client, _memory = _make_client(tmp_path, monkeypatch)
    resp = client.get("/origins")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"origins": []}
