"""G136 — the derived search index is rebuilt by Sleep beside the vector
index, warmed at launch and on a bank switch, and never fails a cycle.

Drives the REAL ``sleep_cycle.run`` through the boundaries
``test_sleep_cycle_claims_wired`` already fakes (no LLM, no embeddings, no
git) — imported rather than copied so the two wired tests can never drift.
"""
from __future__ import annotations

import asyncio

import pytest

from api.services import bank_index, bank_registry, search_index, sleep_cycle, text_fold
from test_sleep_cycle_claims_wired import _patch_boundaries, _seed_bank, _settings

EXTRACTED = [{
    "episode_id": "ep_2026-06-17_001",
    "episode_timestamp": "2026-06-17T10:00:00",
    "origin": "claude-code",
    "entities": [{"name": "Cicada", "type": "project", "source_episode": "ep_2026-06-17_001"}],
    "relationships": [],
}]
RESOLVED = [{
    "id": "cicada", "action": "create", "source_episode": "ep_2026-06-17_001",
    "source_episodes": ["ep_2026-06-17_001"], "trigger": "sleep/extraction",
    "entity": {"name": "Cicada", "type": "project", "confidence": 0.8, "key_facts": ["Built on sqlite-vec."]},
}]


@pytest.fixture(autouse=True)
def _fresh_state():
    bank_index.invalidate()
    search_index.reset()
    yield
    search_index.reset()
    bank_index.invalidate()


def _run(tmp_path, monkeypatch):
    memory = _seed_bank(tmp_path)
    _patch_boundaries(monkeypatch, memory, extracted=EXTRACTED, resolved_changes=RESOLVED, resolved_edges=[])
    asyncio.run(sleep_cycle.run(_settings(memory), cycle_id="2026-06-17_search"))
    return memory


def _refs(memory, table, q):
    with search_index.Reader(memory) as r:
        rows = r.ranked(table, search_index.match_expression(text_fold.query_tokens(q)), 10)
        return sorted(d.ref for d in r.docs([d for d, _ in rows]).values())


def test_a_sleep_cycle_leaves_the_search_index_fresh(tmp_path, monkeypatch):
    memory = _run(tmp_path, monkeypatch)
    assert (memory / search_index.DB_FILE).exists()
    # Read straight from the file — no ensure_fresh — so this proves Sleep
    # itself indexed the page it created, not a later request-time refresh.
    assert _refs(memory, "ent", "cicada") == ["cicada"]
    with search_index.Reader(memory) as r:
        assert r.count("pas", search_index.match_expression(["sqlite"])) == 1
    assert sleep_cycle._state.index_warning is None


def test_a_failed_search_index_rebuild_is_a_warning_not_a_failed_cycle(tmp_path, monkeypatch):
    def boom(_memory_path):
        raise RuntimeError("boom")

    monkeypatch.setattr(search_index, "rebuild", boom)
    memory = _run(tmp_path, monkeypatch)
    assert (memory / "entities" / "cicada.md").exists(), "the cycle still wrote memory"
    assert sleep_cycle._state.error is None
    assert "search index rebuild failed: RuntimeError: boom" in (sleep_cycle._state.index_warning or "")


def test_warm_in_background_builds_and_never_raises(tmp_path):
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    search_index.warm_in_background(memory)
    assert search_index.wait_idle(memory, timeout=10)
    assert search_index.ensure_fresh(memory) == "ready"
    search_index.warm_in_background(tmp_path / "not-a-bank")  # no thread, no file, no raise
    assert not (tmp_path / "not-a-bank").exists()


def test_activating_a_bank_warms_its_search_index(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from api import config, main

    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path))
    config.get_settings.cache_clear()
    bank_registry.scaffold_bank(tmp_path, git_init=False)
    client = TestClient(main.app)
    assert client.post("/banks", json={"name": "Research"}).status_code in (200, 201)
    bank = tmp_path / "banks" / "research"
    assert client.post("/banks/research/activate").status_code == 200
    assert search_index.wait_idle(bank, timeout=10)
    assert (bank / search_index.DB_FILE).exists()
    config.get_settings.cache_clear()
