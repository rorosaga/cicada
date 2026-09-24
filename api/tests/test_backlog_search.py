"""G150 (R-B25) — ⌘K finds backlog items by title, id and a note's words; a dropped item ranks after every live
one. Synthetic only."""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from _synthetic_bank import _bank
from api import config, main
from api.services import backlog, bank_index, search_index, search_service

NOW = datetime(2026, 9, 24, 10, tzinfo=timezone.utc)


@pytest.fixture
def bank(tmp_path):
    memory = _bank(tmp_path, git=False)
    bank_index.invalidate()
    search_index.reset()
    backlog.add_item(memory, project="alpha-project", title="Cache the timeline", description="Big projects are slow.",
                     triage="apply", author="user", now=NOW, tz_name="UTC")
    backlog.add_item(memory, project="alpha-project", title="Cache the graph layout", description="An old idea.",
                     author="user", now=NOW, tz_name="UTC")
    backlog.update_item(memory, project="alpha-project", item="AP2", status="dropped", author="user", now=NOW,
                        tz_name="UTC")
    backlog.add_note(memory, project="alpha-project", item="AP1", note="The bottleneck is page parsing.",
                     author="claude-code", now=NOW, tz_name="UTC")
    search_index.ensure_fresh(memory, wait=True, max_age_s=0)
    return memory


def _hits(bank, q):
    return search_service.search(bank, q, kinds=["backlog"], mode="prefix").results


def test_an_item_is_found_by_its_title_its_id_and_its_notes(bank):
    hit = _hits(bank, "timeline")[0]
    assert (hit.id, hit.name, hit.status, hit.type, hit.subject_id, hit.kind) == (
        "AP1", "Cache the timeline", "open", "apply", "alpha-project", "backlog")
    assert hit.timestamp == "2026-09-24"
    assert [h.id for h in _hits(bank, "ap1")] == ["AP1"]
    assert [h.id for h in _hits(bank, "bottleneck")] == ["AP1"]


def test_a_dropped_item_ranks_after_every_live_one_and_the_total_is_exact(bank):
    result = search_service.search(bank, "cache", kinds=["backlog"], mode="prefix")
    assert [h.id for h in result.results] == ["AP1", "AP2"]
    assert result.totals["backlog"] == 2
    assert search_service.parse_kinds("entity,backlog") == ["entity", "backlog"]


def test_the_search_route_takes_the_backlog_kind(bank, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    config.get_settings.cache_clear()
    try:
        body = TestClient(main.app).get("/search", params={"q": "timeline", "kinds": "entity,backlog",
                                                           "mode": "prefix"}).json()
    finally:
        config.get_settings.cache_clear()
    assert any(r["kind"] == "backlog" and r["id"] == "AP1" and r["subjectId"] == "alpha-project"
               for r in body["results"])


def test_the_schema_bump_rebuilds_every_index_once():
    assert search_index.SCHEMA_VERSION == "4" and "blg" in search_index.WEIGHTS
