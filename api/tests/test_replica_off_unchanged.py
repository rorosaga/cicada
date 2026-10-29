"""G132 phase 1 B — unset, nothing changes (ruling 51a): with no `replica_of` a machine is local or a client exactly
as before (the mode, the lifespan's scheduler, the route table inert, no follower thread); set together with a client
address it fails closed to the client and says so; and the capture chain's overflow (review of #565) keeps nothing
apart. Synthetic banks only."""
from __future__ import annotations

import threading

import pytest
from fastapi.testclient import TestClient

from _synthetic_bank import _bank
from api.services import replica_guard, runtime_layout


def test_the_mode_is_local_or_client_as_before_and_both_fail_closed_to_client(tmp_path):
    env = {"CICADA_HOME": str(tmp_path / "home")}
    assert runtime_layout.mode(env) == "local" and not runtime_layout.is_replica(env)
    assert runtime_layout.mode({**env, "CICADA_API_BASE": "https://server.example.ts.net"}) == "client"
    assert runtime_layout.mode({**env, "CICADA_REPLICA_OF": "https://home.example.ts.net"}) == "replica"
    both = {**env, "CICADA_API_BASE": "https://server.example.ts.net", "CICADA_REPLICA_OF": "https://home.example"}
    assert runtime_layout.mode(both) == "client" and runtime_layout.mode_conflict(both)
    assert "keeps no copy" in runtime_layout.mode_conflict(both)
    with pytest.raises(ValueError):
        runtime_layout.replica_of({**env, "CICADA_REPLICA_OF": "http://home.example"})   # https unless loopback
    # The file the app writes, read like api_base's.
    (tmp_path / "home").mkdir()
    (tmp_path / "home" / "replica_of").write_text("https://home.example.ts.net\n")
    assert runtime_layout.mode(env) == "replica"


def test_off_the_lifespan_routes_and_threads_are_unchanged(tmp_path, monkeypatch):
    from api import config
    from api.main import app

    bank = _bank(tmp_path)
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    monkeypatch.delenv("CICADA_REPLICA_OF", raising=False)
    config.get_settings.cache_clear()
    with TestClient(app) as client:
        assert not replica_guard.active()
        assert app.state.scheduler is not None                     # Sleep schedules as before
        assert client.post("/banks", json={"name": "another"}).status_code in (200, 201)   # the table is inert
        r = client.post("/capture/note", json={"text": "a placeholder note"})
        assert r.status_code == 200 and "x-cicada-seq" not in r.headers   # no publishing, no seq header
        assert client.get("/sync/replica").json() == {"mode": "local", "conflict": None, "replica": None,
                                                      "outbox": None}
        assert not any(t.name.startswith("cicada-replica") for t in threading.enumerate())
    assert not (tmp_path / "home" / "spool" / "tx").exists()
    config.get_settings.cache_clear()


def test_a_chain_past_its_bound_keeps_nothing_apart(tmp_path, monkeypatch):
    from _sync_home import git
    from api.services import capture_commit
    from api.services import transcript_capture as tc

    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_SYNC_PUBLISH", "on")
    monkeypatch.setattr(capture_commit, "AUTOSTART", False)
    monkeypatch.setattr(capture_commit, "_BANKS", {})
    monkeypatch.setattr(capture_commit, "CHAIN_MAX", 2)
    bank = _bank(tmp_path)
    sid = "11111111-2222-4333-8444-555555555555"

    def capture(*turns):
        return tc.capture_posted(bank, harness="claude-code", session_id=sid,
                                 conversation={"kept": [{"role": r, "text": t} for r, t in turns], "gap": None,
                                               "summary": {}}, transcript_bytes=100 * len(turns),
                                 transcript_size=100 * len(turns), cwd="/home/example/a", keep_assistant=True)

    def due():
        return max(r.at for r in capture_commit._bank(bank).records.values()) + capture_commit.SETTLE_S + 1

    first = capture(("user", "plan alpha"))
    rel = f"episodes/{first.episode_id}.md"
    assert capture_commit.sweep(bank, now=due()) == 1    # committed: the next chain starts over HEAD
    turns = [("user", "plan alpha")]
    for word in ("one", "two"):
        turns.append(("assistant" if len(turns) % 2 else "user", word))
        capture(*turns)
    git(bank, "add", rel)
    git(bank, "commit", "-q", "-m", "Feed poll")         # a poll's add -A takes the chain's SECOND write
    for word in ("three", "four"):
        turns.append(("assistant" if len(turns) % 2 else "user", word))
        capture(*turns)
    rec = capture_commit._bank(bank).records[rel]
    assert rec.overflow and len(rec.chain) == 2
    when = due() + capture_commit.MIN_INTERVAL_S
    assert capture_commit.sweep(bank, now=when) == 0     # the chain forgot the write the poll took: nothing guessed
    assert "kept apart" not in git(bank, "log", "--format=%s") and capture_commit.pending(bank) == {}
