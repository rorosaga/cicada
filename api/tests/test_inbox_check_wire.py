"""G61 phase 2 S2 — `check` rides `GET /inbox`, derived at read (plan R-AC40):
additive, camelCase, the ETag recipe unchanged, and the read writes nothing,
fetches nothing and calls no model."""
from __future__ import annotations

import inspect
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.routers import inbox as inbox_router
from api.services import bank_index, engine_select, inbox_service, markdown_parser, providers, source_check
from api.services.claims import Claim, write_claims

PAGE = "https://example.com/company-b/team"


def _bank(root: Path) -> Path:
    memory = root / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (memory / sub).mkdir(parents=True, exist_ok=True)
    body = write_claims("## Summary\nA synthetic person.\n", [
        Claim(id="clm_a", text="bob-example works at company-a", subject="bob-example", predicate="works-at",
              object="company-a", valid_from="2026-05-01", recorded_at="2026-05-01"),
        Claim(id="clm_b", text="bob-example works at company-b", subject="bob-example", predicate="works-at",
              object="company-b", valid_from="2026-08-01", recorded_at="2026-08-01"),
    ])
    markdown_parser.write(memory / "entities" / "bob-example.md",
                          {"name": "Bob Example", "type": "person", "status": "active",
                           "sources": [{"ref": PAGE, "kind": "url", "predicate": "works-at",
                                        "access": "public", "added_by": "user", "added_at": "2026-09-01"}]},
                          body)
    markdown_parser.write(memory / "entities" / "beta-project.md",
                          {"name": "Beta Project", "type": "project", "status": "active",
                           "last_referenced": "2026-03-01"}, "## Summary\nQuiet.\n")
    markdown_parser.write(memory / "inbox" / "inbox-001.md", {
        "kind": "conflict", "required_input": "choice", "status": "pending", "entity_id": "bob-example",
        "entity_name": "Bob Example", "title": "Where does Bob Example work now?", "predicate": "works-at",
        "question": "Where does Bob Example work now?", "claim_id": "clm_b", "created_date": "2026-08-02",
        "options": [{"key": "a", "label": "company-a", "claim_id": "clm_a", "last_referenced": "2026-05-01"},
                    {"key": "b", "label": "company-b", "claim_id": "clm_b", "last_referenced": "2026-08-01"}],
    }, "Conflicting beliefs.")
    markdown_parser.write(memory / "inbox" / "inbox-002.md", {
        "kind": "decay", "status": "pending", "entity_id": "beta-project", "entity_name": "Beta Project",
        "title": "Still tracking Beta?", "created_date": "2026-08-01"}, "ctx")
    return memory


@pytest.fixture
def memory(tmp_path):
    bank_index.invalidate()
    return _bank(tmp_path)


@pytest.fixture
def client(memory, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setenv("CICADA_HOME", str(memory.parent / "home"))
    config.get_settings.cache_clear()
    with TestClient(main.app) as c:
        yield c
    config.get_settings.cache_clear()


def test_load_inbox_serves_check_and_the_legacy_reader_does_not(memory):
    items = {i.id: i for i in inbox_service.load_inbox(memory)}
    check = items["inbox-001"].check
    assert (check.state, check.reason, check.settle_eligible, check.rungs) == (
        "checkable", "settle_eligible", True, ["fetch", "agent"])
    assert items["inbox-002"].check.state == "never"
    legacy = inbox_service._item_from_file(memory / "inbox" / "inbox-001.md", today="2026-09-23")
    assert legacy.check is None


def test_a_checkability_failure_never_hides_the_card(memory, monkeypatch):
    """R-AC40: `load_inbox` skips an item whose read raises, so a derived
    field that fails must degrade to `check: null`, never cost the card."""
    def broken(*a, **k):
        raise RuntimeError("synthetic")

    monkeypatch.setattr(source_check, "for_item", broken)
    items = {i.id: i for i in inbox_service.load_inbox(memory)}
    assert set(items) == {"inbox-001", "inbox-002"} and items["inbox-001"].check is None


def test_get_inbox_carries_check_in_camel_case(client):
    by_id = {i["id"]: i for i in client.get("/inbox").json()}
    check = by_id["inbox-001"]["check"]
    assert check["state"] == "checkable" and check["settleEligible"] is True
    assert check["targets"][0]["predicateMatched"] is True and check["targets"][0]["ownSessionOnly"] is False
    assert by_id["inbox-002"]["check"]["state"] == "never"


def test_the_inbox_etag_recipe_is_unchanged():
    src = inspect.getsource(inbox_router.list_inbox)
    assert 'etag_for(settings.memory_path, "inbox", "entities", "episodes", extra=kind or "")' in src


def test_reading_checkability_writes_nothing_fetches_nothing_and_calls_no_model(memory, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("a read path never fetches or calls a model")

    monkeypatch.setattr(httpx, "AsyncClient", boom)
    monkeypatch.setattr(httpx, "Client", boom)
    monkeypatch.setattr(providers, "resolve_llm_fn", boom)
    monkeypatch.setattr(engine_select, "resolve_settings", boom)
    before = {p: p.read_bytes() for p in memory.rglob("*") if p.is_file()}
    inbox_service.load_inbox(memory)
    source_check.census(memory)
    after = {p: p.read_bytes() for p in memory.rglob("*") if p.is_file()}
    assert after == before
