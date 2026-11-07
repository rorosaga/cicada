"""G132 phase 1 B (ruling 51e2) — on a replica a read never writes and never answers 500: every GET route is walked
against a copy and the bank is the same, byte for byte, afterwards (the derived indexes aside, which a copy keeps
current itself). Synthetic bank; the home is an address nothing answers on, so nothing leaves loopback."""
from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from _synthetic_bank import _bank

#: Streams that never end on their own (the SSE change stream): opened elsewhere, not walked.
STREAMS = {"/sync/events"}
PARAMS = {"entity_id": "alpha-project", "project_id": "alpha-project", "name": "memory", "episode_id": "ep_2026-09-01_001",
          "conversation_id": "ep_2026-09-01_001", "item_id": "inbox-001", "commit_hash": "0" * 40, "commit": "0" * 40}
DERIVED = re.compile(r"(^|/)(search_index|vector_index|image_index)\.db(-wal|-shm|-journal)?$|^\.git/")


def _snapshot(bank: Path) -> dict[str, str]:
    out = {}
    for p in sorted(bank.rglob("*")):
        rel = p.relative_to(bank).as_posix()
        if p.is_file() and not DERIVED.search(rel):
            out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    out["HEAD"] = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(bank), capture_output=True,
                                 text=True).stdout.strip()
    return out


@pytest.fixture
def copy(tmp_path, monkeypatch):
    from api import config
    from api.services import replica

    bank = _bank(tmp_path)
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    monkeypatch.setenv("CICADA_REPLICA_OF", "https://127.0.0.1:9")
    monkeypatch.setattr(replica, "start", lambda: None)
    config.get_settings.cache_clear()
    from api.main import app

    with TestClient(app) as client:
        yield client, bank, app
    config.get_settings.cache_clear()


def test_every_get_route_on_a_copy_writes_nothing_and_never_answers_500(copy):
    client, bank, app = copy
    before = _snapshot(bank)
    failures = []
    walked = 0
    for route in app.routes:
        if not isinstance(route, APIRoute) or "GET" not in route.methods or route.path in STREAMS:
            continue
        path = route.path
        for name in re.findall(r"{(\w+)(?::\w+)?}", path):
            path = re.sub(r"{" + name + r"(?::\w+)?}", PARAMS.get(name, "x"), path)
        r = client.get(path)
        walked += 1
        if r.status_code >= 500 and not (route.path == "/sleep/status" and r.status_code == 503):
            failures.append(f"{route.path}: {r.status_code}")
    assert walked > 100
    assert failures == []
    for path in ("/graph", "/inbox", "/entities/alpha-project", "/search?q=alpha"):
        assert client.get(path).status_code == 200, path      # the reads answer from the copy
    after = _snapshot(bank)
    changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    assert changed == [], f"a read wrote on a copy: {changed}"


def test_a_copy_refuses_a_bank_write_and_says_so(copy):
    client, bank, _app = copy
    r = client.post("/banks", json={"name": "another"})
    assert r.status_code == 409 and r.json()["code"] == "replica_read_only"
    r = client.post("/inbox/inbox-001/resolve", json={"option_key": "keep"})
    assert r.status_code == 503 and r.json()["code"] == "home_away"      # forwarded, and the home is not there
    r = client.post("/capture/note", json={"text": "a placeholder note"})
    assert r.status_code == 202 and r.json()["status"] == "queued"        # kept for the home
    assert client.get("/sync/replica").json()["outbox"]["waiting"] == 1
