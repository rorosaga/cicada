"""Router tests for G21's maintenance dedup-sweep endpoint (the wiring for
``api/services/dedup_sweep.py`` + ``entity_merge.py``, which had zero
production call sites before this).

``dry_run=true`` (the default) must never write to ``entities/``: a pair the
judge would merge comes back under ``proposed`` instead. ``dry_run=false``
performs the merge for real.

Hermetic: the embedding gate (``find_candidate_pairs``) and the LLM judge
(``_default_judge_fn``) are monkeypatched on the ``dedup_sweep`` module —
no network, no real vector index, no real LLM call.
"""
from __future__ import annotations

import yaml
from fastapi.testclient import TestClient

from api import config, main
from api.services import dedup_sweep as dedup_sweep_module


def _write_entity(ents, eid, name):
    (ents / f"{eid}.md").write_text(
        f"---\nname: {name}\ntype: person\nstatus: active\nconfidence: 0.6\n"
        f"source_episodes: [ep_1]\n---\n\n## Summary\nx\n"
    )


def _client(tmp_path, monkeypatch, *, candidate_pairs=None):
    memory = tmp_path / "memory"
    ents = memory / "entities"
    ents.mkdir(parents=True)
    _write_entity(ents, "esa", "ESA")
    _write_entity(ents, "esta", "ESTA")
    (memory / "graph_edges.yaml").write_text(yaml.safe_dump({"edges": []}))

    pairs = candidate_pairs if candidate_pairs is not None else [("esa", "esta", 0.95)]
    monkeypatch.setattr(
        dedup_sweep_module,
        "find_candidate_pairs",
        lambda memory_path, *, embed_fn=None, min_cosine=0.85: pairs,
    )
    monkeypatch.setattr(
        dedup_sweep_module,
        "_default_judge_fn",
        lambda settings: (
            lambda a_body, b_body, a_id, b_id: {
                "verdict": "same", "confidence": 0.95, "winner": "esa"
            }
        ),
    )

    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    return TestClient(main.app), memory


def test_dry_run_defaults_true_and_does_not_write(tmp_path, monkeypatch):
    client, memory = _client(tmp_path, monkeypatch)
    resp = client.post("/maintenance/dedup-sweep", json={})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["dryRun"] is True
    assert body["candidatePairs"] == 1
    assert body["merged"] == []
    assert body["proposed"] == [{"loser": "esta", "winner": "esa"}]
    assert body["nudged"] == []
    # Nothing written: both entity pages still exist untouched.
    assert (memory / "entities" / "esa.md").exists()
    assert (memory / "entities" / "esta.md").exists()
    config.get_settings.cache_clear()


def test_dry_run_false_performs_the_merge(tmp_path, monkeypatch):
    client, memory = _client(tmp_path, monkeypatch)
    resp = client.post("/maintenance/dedup-sweep", json={"dryRun": False})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["dryRun"] is False
    assert body["merged"] == [{"loser": "esta", "winner": "esa"}]
    assert body["proposed"] == []
    assert not (memory / "entities" / "esta.md").exists()
    assert (memory / "entities" / "esa.md").exists()
    config.get_settings.cache_clear()


def test_limit_caps_candidate_pairs(tmp_path, monkeypatch):
    client, memory = _client(
        tmp_path, monkeypatch,
        candidate_pairs=[("esa", "esta", 0.95), ("ghost-a", "ghost-b", 0.9)],
    )
    resp = client.post("/maintenance/dedup-sweep", json={"limit": 1})
    assert resp.status_code == 200, resp.text
    assert resp.json()["candidatePairs"] == 1
    config.get_settings.cache_clear()


def test_uncertain_judge_nudges_not_merges(tmp_path, monkeypatch):
    client, memory = _client(tmp_path, monkeypatch)
    monkeypatch.setattr(
        dedup_sweep_module,
        "_default_judge_fn",
        lambda settings: (
            lambda a_body, b_body, a_id, b_id: {
                "verdict": "unsure", "confidence": 0.5, "winner": "esa"
            }
        ),
    )
    resp = client.post("/maintenance/dedup-sweep", json={"dryRun": False})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["merged"] == [] and body["proposed"] == []
    assert body["nudged"] == [{"a": "esa", "b": "esta"}]
    assert (memory / "entities" / "esa.md").exists()
    assert (memory / "entities" / "esta.md").exists()
    config.get_settings.cache_clear()
