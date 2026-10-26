"""G61 (owner 2026-10-26) — the Sources page's "where to check" list: every page's sources the person or one of their
agents added, in one read; the adds and removals stay on the page's own routes.

Synthetic bank (alpha-project, bob-example, example.com); nothing reaches a network."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from _synthetic_bank import _bank
from api import config, main
from api.services import bank_index, fact_sources, source_roster


@pytest.fixture(autouse=True)
def _fresh():
    bank_index.invalidate()
    yield
    bank_index.invalidate()


@pytest.fixture
def client(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    yield TestClient(main.app), memory
    config.get_settings.cache_clear()


def _seed(memory):
    fact_sources.add_source(memory, "alpha-project", "https://example.com/alpha/changelog", added_by="user",
                            added_at="2026-10-20")
    fact_sources.add_source(memory, "bob-example", "https://example.com/team", predicate="works-at",
                            added_by="claude-code", added_at="2026-10-24")
    # Left out: Cicada's own find, a Sleep model's citation, the engine-free step, a Contacts card, an archived page.
    fact_sources.add_source(memory, "alpha-project", "https://doi.org/10.0/x", added_by="cicada")
    fact_sources.add_source(memory, "alpha-project", "https://example.com/cited", added_by="claude-haiku-4-5")
    fact_sources.add_source(memory, "beta-project", "https://example.com/beta", added_by="agent", proposed=True)
    fact_sources.add_source(memory, "bob-example", "addressbook://card-1", kind="app", added_by="user")
    fact_sources.add_source(memory, "gamma-project", "https://example.com/gamma", added_by="user")


def test_lists_the_persons_and_their_agents_sources_newest_first(tmp_path):
    memory = _bank(tmp_path, git=False)
    _seed(memory)
    rows = source_roster.roster(memory)
    assert [(r["entity_id"], r["ref"], r["who"], r["agent"]) for r in rows] == [
        ("bob-example", "https://example.com/team", "agent", "Claude Code"),
        ("alpha-project", "https://example.com/alpha/changelog", "you", None),
    ]
    assert rows[0]["predicate"] == "works-at" and rows[0]["added_by"] == "claude-code"
    assert rows[0]["entity_name"] == "Bob Example" and rows[0]["entity_type"] == "person"
    assert rows[1]["kind"] == "url" and rows[1]["proposed"] is False


def test_route_serves_the_list_with_an_etag_and_a_304(client):
    tc, memory = client
    _seed(memory)
    first = tc.get("/sources/where-to-check")
    assert first.status_code == 200
    body = first.json()
    assert body["total"] == 2 and [r["who"] for r in body["items"]] == ["agent", "you"]
    assert body["items"][0]["entityName"] == "Bob Example" and body["items"][0]["addedBy"] == "claude-code"
    etag = first.headers["etag"]
    assert tc.get("/sources/where-to-check", headers={"If-None-Match": etag}).status_code == 304


def test_an_add_and_a_removal_through_the_pages_routes_move_the_list(client):
    tc, memory = client
    _seed(memory)
    etag = tc.get("/sources/where-to-check").headers["etag"]
    added = tc.post("/entities/beta-project/sources", json={"ref": "https://example.com/beta/news"})
    assert added.status_code == 200
    after = tc.get("/sources/where-to-check", headers={"If-None-Match": etag})
    assert after.status_code == 200
    assert ("beta-project", "https://example.com/beta/news", "you") in {
        (r["entityId"], r["ref"], r["who"]) for r in after.json()["items"]}
    # The person removes the agent's entry: gone from the list, and remembered on the page.
    gone = tc.post("/entities/bob-example/sources/change",
                   json={"ref": "https://example.com/team", "predicate": "works-at", "action": "remove"})
    assert gone.status_code == 200
    refs = {r["ref"] for r in tc.get("/sources/where-to-check").json()["items"]}
    assert "https://example.com/team" not in refs
    with pytest.raises(fact_sources.SourceRemoved):
        fact_sources.add_source(memory, "bob-example", "https://example.com/team", predicate="works-at",
                                added_by="claude-code", via_agent=True)
