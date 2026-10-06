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


# --------------------------------------------------------------------------- #
# G183(e): the sweep waits for Sleep's write window, and commits its own merges
# --------------------------------------------------------------------------- #

import subprocess
from types import SimpleNamespace

from api.services import page_lock, sleep_cycle


def _git(repo, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True).stdout


def _git_bank(client_and_memory):
    client, memory = client_and_memory
    _git(memory, "init", "-q")
    _git(memory, "config", "user.email", "test@cicada.local")
    _git(memory, "config", "user.name", "Cicada Test")
    _git(memory, "add", "-A")
    _git(memory, "commit", "-q", "-m", "seed")
    return client, memory


def _writing(monkeypatch, writing: bool):
    """A drain in progress: inside a batch's write window, or between batches."""
    monkeypatch.setattr(sleep_cycle, "get_sleep_state",
                        lambda: SimpleNamespace(status="running", drain_run=True, writing=writing))


def test_a_real_sweep_commits_exactly_its_merge_under_cicada_and_leaves_the_tree_clean(tmp_path, monkeypatch):
    client, memory = _git_bank(_client(tmp_path, monkeypatch))
    seed = _git(memory, "rev-parse", "HEAD").strip()
    # A file someone else left dirty must not ride the sweep's commit.
    (memory / "entities" / "bob-example.md").write_text("---\nname: bob-example\ntype: person\n---\n\nx\n")

    resp = client.post("/maintenance/dedup-sweep", json={"dryRun": False})
    assert resp.status_code == 200, resp.text
    assert resp.json()["merged"] == [{"loser": "esta", "winner": "esa"}]

    log = _git(memory, "log", "--format=%H", f"{seed}..HEAD").split()
    assert len(log) == 1, "one commit for the one merge"
    files = set(_git(memory, "show", "--name-only", "--format=", log[0]).split())
    assert files == {"entities/esa.md", "entities/esta.md"}
    message = _git(memory, "log", "-1", "--format=%B")
    assert message.startswith("Dedup sweep ")
    assert "entities/esta.md: removed (merged, trigger: maintenance/dedup-sweep)" in message
    assert "entities/esa.md: updated (trigger: maintenance/dedup-sweep)" in message
    assert "Cicada-Author: cicada" in message.splitlines()
    status = _git(memory, "status", "--porcelain")
    assert status.strip() == "?? entities/bob-example.md", "only the other writer's file is left"
    config.get_settings.cache_clear()


def test_the_sweep_holds_the_page_lock_across_each_merge_and_its_commit(tmp_path, monkeypatch):
    client, memory = _git_bank(_client(tmp_path, monkeypatch))
    from api.services import git_service

    seen = []
    real = git_service.commit_paths_sync

    def spy(memory_path, message, paths):
        seen.append(page_lock.held(memory_path))
        return real(memory_path, message, paths)

    monkeypatch.setattr(git_service, "commit_paths_sync", spy)
    assert client.post("/maintenance/dedup-sweep", json={"dryRun": False}).status_code == 200
    assert seen == [True]
    config.get_settings.cache_clear()


def test_a_dry_run_writes_and_commits_nothing(tmp_path, monkeypatch):
    client, memory = _git_bank(_client(tmp_path, monkeypatch))
    head = _git(memory, "rev-parse", "HEAD")
    resp = client.post("/maintenance/dedup-sweep", json={"dryRun": True})
    assert resp.status_code == 200, resp.text
    assert _git(memory, "rev-parse", "HEAD") == head
    assert _git(memory, "status", "--porcelain") == ""
    config.get_settings.cache_clear()


def test_the_sweep_answers_409_inside_sleeps_write_window(tmp_path, monkeypatch):
    client, memory = _git_bank(_client(tmp_path, monkeypatch))
    _writing(monkeypatch, True)
    for dry_run in (True, False):
        resp = client.post("/maintenance/dedup-sweep", json={"dryRun": dry_run})
        assert resp.status_code == 409, resp.text
        assert "Sleep" in resp.json()["detail"]
    assert (memory / "entities" / "esta.md").exists()
    assert _git(memory, "status", "--porcelain") == ""
    config.get_settings.cache_clear()


def test_the_sweep_runs_between_drain_batches(tmp_path, monkeypatch):
    client, memory = _git_bank(_client(tmp_path, monkeypatch))
    _writing(monkeypatch, False)
    resp = client.post("/maintenance/dedup-sweep", json={"dryRun": False})
    assert resp.status_code == 200, resp.text
    assert resp.json()["merged"] == [{"loser": "esta", "winner": "esa"}]
    config.get_settings.cache_clear()


def test_a_sweep_stops_merging_once_sleep_starts_writing(tmp_path, monkeypatch):
    """The judge is a model call; a window can open while it thinks. No merge after it does."""
    client, memory = _git_bank(_client(tmp_path, monkeypatch))
    state = {"writing": False}
    monkeypatch.setattr(sleep_cycle, "get_sleep_state",
                        lambda: SimpleNamespace(status="running", drain_run=True, writing=state["writing"]))

    def judge(a_body, b_body, a_id, b_id):
        state["writing"] = True   # Sleep's batch reached Stage 2 while the judge answered
        return {"verdict": "same", "confidence": 0.95, "winner": "esa"}

    monkeypatch.setattr(dedup_sweep_module, "_default_judge_fn", lambda settings: judge)
    resp = client.post("/maintenance/dedup-sweep", json={"dryRun": False})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["merged"] == []
    assert body["stoppedForSleep"] is True
    assert (memory / "entities" / "esta.md").exists()
    assert _git(memory, "status", "--porcelain") == ""
    config.get_settings.cache_clear()


def test_a_merge_whose_commit_fails_is_put_back(tmp_path, monkeypatch):
    """Never a dirty tree for the next `git add -A` writer to sweep under its own author."""
    client, memory = _git_bank(_client(tmp_path, monkeypatch))
    from api.services import git_service

    def boom(memory_path, message, paths):
        raise git_service.GitError("simulated")

    monkeypatch.setattr(git_service, "commit_paths_sync", boom)
    resp = client.post("/maintenance/dedup-sweep", json={"dryRun": False})
    assert resp.status_code == 200, resp.text
    assert resp.json()["merged"] == []
    assert (memory / "entities" / "esta.md").exists()
    assert _git(memory, "status", "--porcelain") == ""
    config.get_settings.cache_clear()
