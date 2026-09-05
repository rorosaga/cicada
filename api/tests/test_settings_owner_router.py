"""G117 — GET/PUT /settings/owner, end to end through the FastAPI app."""
from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from api import config, main
from api.services import bank_index, markdown_parser, owner_identity, predicates


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(repo), check=True, capture_output=True, text=True
    ).stdout


def _client(tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    predicates.install_predicate_map(memory)
    # A real git repo, matching every bank `PUT /settings/owner` will ever run
    # against in production (bank_registry inits git at bank creation) —
    # test_decay_endpoint.py's `_memory` fixture does the same for the same
    # reason: the router now commits the entity-page write via
    # git_service.commit_paths, which shells out to `git add`/`git commit`
    # and needs both a repo and a configured identity to succeed.
    _git(memory, "init", "-q")
    _git(memory, "config", "user.email", "test@cicada.local")
    _git(memory, "config", "user.name", "Cicada Test")
    _git(memory, "add", "-A")
    _git(memory, "commit", "-q", "-m", "seed", "--allow-empty")
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_API_AUTH", "off")
    config.get_settings.cache_clear()
    bank_index.invalidate()
    return TestClient(main.app), memory


def test_get_before_any_put_reads_as_unset(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    body = client.get("/settings/owner").json()
    assert body == {"name": "", "handle": None, "email": None, "observer": "owner", "entityId": None}


def test_put_writes_owner_json_and_the_entity_page_and_get_reflects_it(tmp_path, monkeypatch):
    client, memory = _client(tmp_path, monkeypatch)
    resp = client.put("/settings/owner", json={"name": "Bob Example", "handle": "@bob"})
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "name": "Bob Example", "handle": "@bob", "email": None,
        "observer": "bob-example", "entityId": "bob-example",
    }
    assert (memory / "entities" / "bob-example.md").exists()
    again = client.get("/settings/owner").json()
    assert again == body


def test_put_requires_a_name(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    assert client.put("/settings/owner", json={"name": "  "}).status_code == 400


def test_graph_marks_the_owner_node(tmp_path, monkeypatch):
    client, memory = _client(tmp_path, monkeypatch)
    client.put("/settings/owner", json={"name": "Bob Example"})
    nodes = client.get("/graph").json()["nodes"]
    owner_nodes = [n for n in nodes if n["id"] == "bob-example"]
    assert owner_nodes and owner_nodes[0]["isOwner"] is True


def test_put_commits_the_entity_page_scoped_and_authored_by_user(tmp_path, monkeypatch):
    """Reviewer round 1: the write must not land untracked — that risks the
    G85-class smear where a later `git add -A` writer sweeps it in under the
    wrong author. `commit_paths` stages only `entities/bob-example.md`, so
    the working tree is clean afterward and the commit carries the trailer.
    """
    client, memory = _client(tmp_path, monkeypatch)
    resp = client.put("/settings/owner", json={"name": "Bob Example"})
    assert resp.status_code == 200

    assert _git(memory, "status", "--porcelain").strip() == ""

    log = _git(memory, "log", "-1", "--pretty=%B")
    assert "entities/bob-example.md: created" in log
    assert "Cicada-Author: user" in log

    files = _git(memory, "show", "--name-only", "--pretty=format:", "HEAD").strip()
    assert files == "entities/bob-example.md"


def test_put_twice_commits_the_second_write_as_an_update(tmp_path, monkeypatch):
    client, memory = _client(tmp_path, monkeypatch)
    client.put("/settings/owner", json={"name": "Bob Example"})
    # Same slug ("bob-example" is case-insensitive per `sanitize_id`), but a
    # different `name:` value so the second write actually changes the page
    # — otherwise `commit_paths` correctly sees no diff and skips the commit,
    # which would leave HEAD still pointing at the first "created" commit.
    resp = client.put("/settings/owner", json={"name": "BOB EXAMPLE", "handle": "@bob"})
    assert resp.status_code == 200

    assert _git(memory, "status", "--porcelain").strip() == ""
    log = _git(memory, "log", "-1", "--pretty=%B")
    assert "entities/bob-example.md: updated" in log
    assert "Cicada-Author: user" in log
