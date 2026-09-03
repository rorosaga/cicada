"""G124 R11/R12 — the ids-only `read` ledger event: app card opens, MCP
recall_detail, MCP recall suggestions. Nothing but an entity id and a surface
enum ever reaches the ledger."""
from __future__ import annotations

import importlib
import json

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import consumption_stats, sync_service, telemetry as tm

mcp = importlib.import_module("mcp.server")


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_TELEMETRY", "on")
    return tmp_path / "home"


def _events(home, prefix="*"):
    """Ledger rows on disk. Reads are filed in `reads-*.jsonl` beside the
    `events-*.jsonl` spend ledger (final review M2); the default reads both."""
    out = []
    for path in sorted((home / "telemetry").glob(f"{prefix}-*.jsonl")):
        out += [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    return out


def test_record_read_is_ids_only_and_non_spend(home):
    tm.record_read("alpha-project", surface="app", bank="demo")
    tm.record_read("", surface="app", bank="demo")  # ignored, never raises
    events = _events(home)
    assert len(events) == 1
    ev = events[0]
    assert ev["kind"] == "read" and ev["refs"] == {"entity_id": "alpha-project", "surface": "app"}
    assert ev["invocations"] == 0 and ev["billing"] == "free" and ev["connection"] is None
    assert "read" in tm.KINDS and "read" in tm.NON_SPEND_KINDS


def test_reads_land_in_a_sibling_file_and_never_tick_the_telemetry_component(home, tmp_path):
    """Final review M2: the app maps `components["telemetry"]` onto its
    `.consumption` domain and refetches every `/consumption/*` endpoint on a
    tick — so an entity-card open must not move it. Reads go to
    `reads-YYYY-MM.jsonl`; `events-*.jsonl` is untouched; `read_events` still
    returns one ledger."""
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    before = sync_service.components(memory)["telemetry"]
    tm.record_read("alpha-project", surface="app", bank="demo")
    assert sync_service.components(memory)["telemetry"] == before
    assert _events(home, "reads") and not _events(home, "events")
    assert [e.kind for e in tm.read_events()] == ["read"]
    # a spend event still lands in events-* and still ticks the component
    tm.record(tm.UsageEvent(kind="llm_call", model="gpt-5.4-mini", input_tokens=1, output_tokens=1))
    assert sync_service.components(memory)["telemetry"] != before
    assert [e["kind"] for e in _events(home, "events")] == ["llm_call"]
    assert sorted(e.kind for e in tm.read_events()) == ["llm_call", "read"]


def test_reads_never_invent_an_unknown_connection_in_stats(home, tmp_path):
    from datetime import date
    tm.record_read("alpha-project", surface="app", bank="demo")
    data = __import__("asyncio").run(consumption_stats.stats(tmp_path, range_="all", today=date.today()))
    assert data["by_connection"] == [], "R12 widens G113 R7 to the read kind"
    assert data["by_stage"] and data["by_stage"][0]["stage"] == "recall"


def test_post_entities_read_records_and_404s_on_an_unknown_page(home, tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    (memory / "entities" / "alpha-project.md").write_text("---\nid: alpha-project\ntype: concept\n---\n# A\n")
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    client = TestClient(main.app)
    try:
        assert client.post("/entities/alpha-project/read", json={"surface": "app"}).json() == {"recorded": True}
        assert client.post("/entities/nope/read", json={"surface": "app"}).status_code == 404
        assert client.post("/entities/alpha-project/read", json={"surface": "browser"}).status_code == 422
    finally:
        config.get_settings.cache_clear()
    events = _events(home)
    assert [e["refs"] for e in events] == [{"entity_id": "alpha-project", "surface": "app"}]


def test_mcp_recall_detail_records_one_read_with_the_mcp_surface(home, tmp_path, monkeypatch):
    memory = tmp_path / "bank"
    (memory / "entities").mkdir(parents=True)
    (memory / "entities" / "alpha-project.md").write_text("---\nid: alpha-project\ntype: concept\n---\n# Alpha\n")
    monkeypatch.setattr(mcp, "get_memory_path", lambda: memory)
    text = mcp.handle_recall_detail("alpha-project")
    assert text.startswith("---")
    assert [e["refs"] for e in _events(home)] == [{"entity_id": "alpha-project", "surface": "mcp"}]
    mcp.handle_recall_detail("missing")
    assert len(_events(home)) == 1, "a miss is not a read"


def test_mcp_recall_records_the_suggested_ids_with_the_recall_surface(home, tmp_path, monkeypatch):
    memory = tmp_path / "bank"
    (memory / "entities").mkdir(parents=True)
    (memory / "entities" / "alpha-project.md").write_text(
        "---\nid: alpha-project\ntype: project\nname: Alpha Project\n---\n# Alpha Project\nA capstone about graphs.\n")
    # Same hermetic seam set as test_mcp_recall_episode_fallback.py: every
    # retrieval source but the keyword scan is stubbed, so the one suggested
    # id can only have come from the page written above.
    monkeypatch.setattr(mcp, "get_memory_path", lambda: memory)
    monkeypatch.setattr(mcp, "_relevant_inbox", lambda memory_path, query: [])
    monkeypatch.setattr(mcp, "_match_hub", lambda memory_path, query: (None, []))
    monkeypatch.setattr(mcp, "_leann_search_entities", lambda memory_path, query, top_k: [])
    monkeypatch.setattr(mcp, "_leann_search_episodes", lambda memory_path, query, top_k: [])
    # `_keyword_search_entities` (mcp/server.py:1439) is a whole-query
    # substring match on the name/tags/body, so the query must be a phrase the
    # page contains.
    mcp.handle_recall("alpha project")
    refs = [e["refs"] for e in _events(home)]
    assert refs and all(r["surface"] == "mcp-recall" for r in refs)
    assert {r["entity_id"] for r in refs} == {"alpha-project"}
    assert all(set(r) == {"entity_id", "surface"} for r in refs), "never the query, never text"
