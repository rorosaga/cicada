"""G132 phase 1 B, review of #567 — leaving and entering replica mode safely.

Stopping "Keep a full copy here" makes the bank this computer had open before active again (on the DELETE and, at the
latest, on the first start in local mode), and a copy is never written outside replica mode: not activated, not
captured into, not paged. A backend keeps the mode it started in — `replica_of` written while it runs changes nothing
— and "Keep a copy" is refused while Sleep runs, before anything is written. `/sync/publish` always says whether the
memory is a demo. The control routes are never refused as another bank's. Synthetic banks only."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from _synthetic_bank import _bank
from api.services import bank_registry, markdown_parser, replica, replica_guard


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True).stdout


def _root_with_a_copy(tmp_path: Path, *, previous: str | None = "notes-here") -> tuple[Path, Path, Path]:
    """A memory root that kept a copy: its own bank ``notes-here`` and the active copy ``memory`` (replica: true)."""
    root = tmp_path / "root"
    own = root / "banks" / "notes-here"
    (own / "entities").mkdir(parents=True)
    (own / "entities" / "gamma-example.md").write_text("---\nname: Gamma Example\n---\nhere\n")
    for args in (["init", "-q"], ["config", "user.email", "t@example.com"], ["config", "user.name", "t"],
                 ["add", "."], ["commit", "-q", "-m", "seed"]):
        _git(own, *args)
    with replica_guard.applying():
        copy = _bank(root / "banks" / "_tmp")
        copy.rename(root / "banks" / "memory")
    copy = root / "banks" / "memory"
    (root / "banks" / "_tmp").rmdir()
    (root / "banks.yaml").write_text(
        "active: memory\nbanks:\n  notes-here:\n    legacy: false\n    id: " + "1" * 32 + "\n"
        "  memory:\n    legacy: false\n    id: " + "2" * 32 + "\n    replica: true\n")
    marker = replica.marker_path(copy)
    marker.write_text(json.dumps({"home": "home.example", "bankId": "2" * 32, "seq": 3, "sha": "0" * 40,
                                  "previous": previous}))
    return root, own, copy


@pytest.fixture
def local_home(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("CICADA_REPLICA_OF", raising=False)
    replica_guard.thaw()
    return tmp_path


def _active(root: Path) -> str:
    return bank_registry.current_active(root)[0]


def test_stopping_the_copy_opens_the_previous_bank_again(local_home, monkeypatch):
    root, own, copy = _root_with_a_copy(local_home)
    assert replica.leave_copy(root) == "notes-here" and _active(root) == "notes-here"
    assert copy.exists()                                       # the copy stays on disk, inactive
    assert replica.leave_copy(root) is None                    # nothing more to do


def test_with_no_bank_before_it_falls_back_to_the_roots_own_memory(local_home):
    root, own, copy = _root_with_a_copy(local_home, previous=None)
    registry = bank_registry.load_registry(root)
    del registry["banks"]["notes-here"]
    bank_registry.save_registry(root, registry)
    assert replica.leave_copy(root) == bank_registry.DEFAULT_BANK
    assert bank_registry.current_active(root)[1] == root


def test_a_copy_is_never_written_or_opened_outside_replica_mode(local_home, monkeypatch):
    root, own, copy = _root_with_a_copy(local_home)
    from api import config

    monkeypatch.setenv("CICADA_MEMORY_PATH", str(root))
    config.get_settings.cache_clear()
    try:
        # Left active (the registry says so), it is refused like a copy: pages, episodes, capture, git.
        assert replica_guard.active_bank_is_copy() and replica_guard.blocks()
        with pytest.raises(replica_guard.ReplicaReadOnly):
            markdown_parser.write(copy / "entities" / "x.md", {"name": "X"}, "x")
        from api.services import transcript_capture as tc

        with pytest.raises(replica_guard.ReplicaReadOnly):
            tc.capture_posted(copy, harness="claude-code", session_id="11111111-2222-4333-8444-555555555555",
                              conversation={"kept": [{"role": "user", "text": "x"}], "gap": None, "summary": {}},
                              transcript_bytes=10, transcript_size=10, cwd="/home/example/a", keep_assistant=True)
        replica.leave_copy(root)
        assert not replica_guard.active_bank_is_copy()
        # And it is never opened again by a switch.
        with pytest.raises(ValueError, match="copy"):
            bank_registry.activate_bank(root, "memory")
        assert _active(root) == "notes-here"
    finally:
        config.get_settings.cache_clear()


def test_the_first_local_start_opens_this_computers_own_memory_and_schedules_only_there(local_home, monkeypatch):
    root, own, copy = _root_with_a_copy(local_home)
    from api import config
    from api.main import app

    monkeypatch.setenv("CICADA_MEMORY_PATH", str(root))
    config.get_settings.cache_clear()
    copy_head = _git(copy, "rev-parse", "HEAD")
    with TestClient(app) as client:
        assert _active(root) == "notes-here" and app.state.scheduler is not None
        assert client.post("/capture/note", json={"text": "a placeholder note"}).status_code == 200
    config.get_settings.cache_clear()
    assert _git(copy, "rev-parse", "HEAD") == copy_head and _git(copy, "status", "--porcelain") == ""
    assert any("placeholder note" in p.read_text() for p in (own / "episodes").glob("ep_*.md"))


def test_the_delete_route_reopens_the_previous_bank(local_home, monkeypatch):
    root, own, copy = _root_with_a_copy(local_home)
    from api import config
    from api.main import app

    monkeypatch.setenv("CICADA_MEMORY_PATH", str(root))
    monkeypatch.setattr(replica, "leave_copy", replica.leave_copy)
    config.get_settings.cache_clear()
    # A backend that started as a copy (the follower stubbed), stopped from the app.
    (local_home / "home").mkdir(exist_ok=True)
    (local_home / "home" / "replica_of").write_text("https://127.0.0.1:9\n")
    monkeypatch.setattr(replica, "start", lambda: None)
    with TestClient(app) as client:
        assert replica_guard.active()
        r = client.delete("/sync/replica", headers={"X-Cicada-Bank": "memory"})
        assert r.status_code == 200 and r.json()["bank"] == "notes-here", r.text
        assert not (local_home / "home" / "replica_of").exists() and _active(root) == "notes-here"
        assert replica_guard.active()             # still the mode it started in, until it starts again
    config.get_settings.cache_clear()


def test_a_running_backend_keeps_the_mode_it_started_in_and_keep_a_copy_waits_for_sleep(local_home, monkeypatch):
    from api import config
    from api.main import app
    from api.services import sleep_cycle

    bank = _bank(local_home)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    config.get_settings.cache_clear()
    with TestClient(app) as client:
        (local_home / "home" / "replica_of").write_text("https://home.example.ts.net\n")
        assert not replica_guard.active()                       # written while running: nothing changes here
        markdown_parser.write(bank / "entities" / "still-writable.md", {"name": "Still"}, "ok")
        (local_home / "home" / "replica_of").unlink()
        running = type("S", (), {"status": "running"})()
        monkeypatch.setattr(sleep_cycle, "get_sleep_state", lambda: running)
        r = client.put("/sync/replica", json={"home": "https://home.example.ts.net", "code": "ABCD"},
                       headers={"X-Cicada-Bank": "not-this-one"})   # never refused as another bank's either
        assert r.status_code == 409 and "Sleep is running" in r.json()["detail"]
        assert not (local_home / "home" / "replica_of").exists()
        assert not (local_home / "home" / "device_token").exists()
    config.get_settings.cache_clear()


def test_publish_always_says_whether_the_memory_is_a_demo(local_home, monkeypatch):
    from api import config
    from api.main import app
    from api.services import demo_guard

    bank = _bank(local_home)
    (bank / demo_guard.MANIFEST).write_text(f"kind: {demo_guard.DEMO_KIND}\n")
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    monkeypatch.delenv("CICADA_SYNC_PUBLISH", raising=False)
    config.get_settings.cache_clear()
    with TestClient(app) as client:
        body = client.get("/sync/publish").json()
        assert body["publish"] is False and body["demo"] is True
    config.get_settings.cache_clear()


def test_a_first_copy_cut_short_is_taken_up_again_never_a_second_copy(local_home, monkeypatch):
    """Review of #566: registered, no marker yet (the process died) — the retry reuses that bank under the same id."""
    from api import config

    home = local_home / "home-bank"
    home.mkdir()
    with replica_guard.applying():
        bank = _bank(home)
    bundle = local_home / "full.bundle"
    subprocess.run(["git", "bundle", "create", "-q", str(bundle), "HEAD"], cwd=str(bank), check=True,
                   capture_output=True)
    head = _git(bank, "rev-parse", "HEAD").strip()
    root = local_home / "copy-root"
    root.mkdir()
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(root))
    monkeypatch.setenv("CICADA_REPLICA_OF", "https://home.example.ts.net")
    config.get_settings.cache_clear()
    frame = {"bankId": "3" * 32, "bank": "memory", "seq": 1}
    monkeypatch.setattr(replica, "request", lambda *a, **k: (200, {}, frame))
    monkeypatch.setattr(replica, "_fetch_pack",
                        lambda have, folder: (bundle, {"X-Cicada-Seq": "1", "X-Cicada-Head": head}, {}))
    monkeypatch.setattr(replica, "_index_after", lambda *a, **k: 0.0)
    try:
        first = replica.bootstrap()
        replica.marker_path(first).unlink()                  # cut short before the marker was written
        again = replica.bootstrap()
        assert again == first
        banks = bank_registry.load_registry(root)["banks"]
        assert [n for n, r in banks.items() if r.get("replica")] == ["memory"]
        assert replica.read_marker(again)["sha"] == head
    finally:
        config.get_settings.cache_clear()


def test_a_stop_that_lands_while_the_follower_fetches_is_never_undone(local_home, monkeypatch):
    """Review of #567: the follower passed its check, then "Stop keeping a copy" removed `replica_of` while it fetched
    the pack — it checks again under the stop's own lock and writes nothing (no copy registered or made active)."""
    from api import config

    home = local_home / "home-bank"
    home.mkdir()
    with replica_guard.applying():
        bank = _bank(home)
    bundle = local_home / "full.bundle"
    subprocess.run(["git", "bundle", "create", "-q", str(bundle), "HEAD"], cwd=str(bank), check=True,
                   capture_output=True)
    root = local_home / "copy-root"
    root.mkdir()
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(root))
    monkeypatch.setenv("CICADA_REPLICA_OF", "https://home.example.ts.net")
    config.get_settings.cache_clear()
    monkeypatch.setattr(replica, "request", lambda *a, **k: (200, {}, {"bankId": "3" * 32, "bank": "memory"}))

    def fetched_then_stopped(have, folder):
        monkeypatch.delenv("CICADA_REPLICA_OF")            # the person's stop, between the check and the write
        return bundle, {"X-Cicada-Seq": "1"}, {}

    monkeypatch.setattr(replica, "_fetch_pack", fetched_then_stopped)
    try:
        with pytest.raises(replica.NoLongerACopy):
            replica.bootstrap()
        assert not (root / "banks" / "memory").exists()
        assert not any(r.get("replica") for r in bank_registry.load_registry(root)["banks"].values())
    finally:
        config.get_settings.cache_clear()


def test_a_forwarded_write_that_timed_out_says_it_may_have_landed_and_is_resent_with_its_key(local_home, monkeypatch):
    from api import config

    with replica_guard.applying():
        bank = _bank(local_home)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    monkeypatch.setenv("CICADA_REPLICA_OF", "https://home.example.ts.net")
    monkeypatch.setattr(replica, "start", lambda: None)
    keys = []

    def timed_out(method, path, *, headers=None, **kw):
        keys.append((headers or {}).get("Idempotency-Key"))
        return None, {replica.NO_ANSWER: "timeout"}, None

    monkeypatch.setattr(replica, "request", timed_out)
    config.get_settings.cache_clear()
    from api.main import app

    with TestClient(app) as client:
        for _ in range(2):
            r = client.post("/inbox/inbox-001/resolve", json={"option_key": "keep"})
            assert r.status_code == 503 and r.json()["code"] == "home_unsure"
            assert "may or may not" in r.json()["detail"] and "nothing" not in r.json()["detail"].lower()
    config.get_settings.cache_clear()
    assert len(keys) == 2 and keys[0] and keys[0] == keys[1]          # the retry reuses the first key
