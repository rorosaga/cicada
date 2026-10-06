"""G177/G183(a) — every route that rewrites a bank page refuses while Sleep holds the pages, and works between a
drain's batches.

`sleep_cycle.is_writing()` is the one predicate (never `status == "running"`): a person-started drain is writable
between batches. The window is simulated through `get_sleep_state`, the accessor `is_writing` reads.
"""
from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import markdown_parser, sleep_cycle


def _git(repo, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True).stdout


@pytest.fixture
def bank(tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    (memory / "inbox").mkdir()
    markdown_parser.write(memory / "entities" / "alpha-project.md",
                          {"name": "alpha-project", "type": "project", "status": "active", "confidence": 0.8},
                          "## Summary\nx\n")
    markdown_parser.write(memory / "inbox" / "inbox-001.md",
                          {"kind": "decay", "status": "pending", "entity_id": "alpha-project",
                           "entity_name": "alpha-project", "title": "Still tracking alpha-project?",
                           "created_date": "2026-10-01"},
                          "context")
    _git(memory, "init", "-q")
    _git(memory, "config", "user.email", "test@cicada.local")
    _git(memory, "config", "user.name", "Cicada Test")
    _git(memory, "add", "-A")
    _git(memory, "commit", "-q", "-m", "seed")
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    yield memory
    config.get_settings.cache_clear()


ROUTES = [
    ("put", "/entities/alpha-project/decay", {"decayClass": "durable"}),
    ("patch", "/entities/alpha-project/repos", {"repos": []}),
    ("post", "/inbox/inbox-001/resolve", {"action": "defer"}),
    ("post", "/nudges/inbox-001/resolve", {"action": "defer"}),
    ("post", "/clarifications/inbox-001", {"action": "defer"}),
]


def _drain(monkeypatch, *, writing: bool):
    monkeypatch.setattr(sleep_cycle, "get_sleep_state",
                        lambda: SimpleNamespace(status="running", drain_run=True, writing=writing))


@pytest.mark.parametrize("method,path,body", ROUTES, ids=[r[1] for r in ROUTES])
def test_a_page_writing_route_refuses_inside_the_write_window(bank, monkeypatch, method, path, body):
    _drain(monkeypatch, writing=True)
    head = _git(bank, "rev-parse", "HEAD")
    resp = getattr(TestClient(main.app), method)(path, json=body)
    assert resp.status_code == 409, resp.text
    assert "Sleep" in resp.json()["detail"]
    assert _git(bank, "status", "--porcelain") == "", "nothing written"
    assert _git(bank, "rev-parse", "HEAD") == head


@pytest.mark.parametrize("method,path,body", ROUTES, ids=[r[1] for r in ROUTES])
def test_a_page_writing_route_works_between_drain_batches_and_commits_alone(bank, monkeypatch, method, path, body):
    _drain(monkeypatch, writing=False)
    # Someone else's dirty file must not ride this write's commit.
    (bank / "entities" / "bob-example.md").write_text("---\nname: bob-example\ntype: person\n---\n\nx\n")
    resp = getattr(TestClient(main.app), method)(path, json=body)
    assert resp.status_code == 200, resp.text
    assert _git(bank, "status", "--porcelain").strip() == "?? entities/bob-example.md"


def test_a_plain_cycle_refuses_for_its_whole_run(bank, monkeypatch):
    monkeypatch.setattr(sleep_cycle, "get_sleep_state", lambda: SimpleNamespace(status="running"))
    resp = TestClient(main.app).put("/entities/alpha-project/decay", json={"decayClass": "durable"})
    assert resp.status_code == 409


def test_reading_routes_are_never_gated(bank, monkeypatch):
    """`POST /entities/{id}/read` writes a ledger row outside the bank, never a page."""
    _drain(monkeypatch, writing=True)
    resp = TestClient(main.app).post("/entities/alpha-project/read", json={"surface": "app"})
    assert resp.status_code == 200, resp.text
