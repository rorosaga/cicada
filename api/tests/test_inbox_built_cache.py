"""Speed 2026-10-29: ``load_inbox`` keeps its built list on the stamps of everything it reads.

A hit must be exactly what a rebuild would serve, and every input moving must rebuild: the inbox, a page, an episode,
the predicate map, the held names, the day. The ETag computes only the components it names, each exactly as the full
map computes it.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from api.services import inbox_service, markdown_parser, pending_store, predicates, sync_service


def _write(path: Path, fm: dict, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    markdown_parser.write(path, fm, body)


@pytest.fixture
def memory(tmp_path):
    m = tmp_path / "memory"
    _write(m / "episodes" / "ep_2026-08-20_001.md",
           {"id": "ep_2026-08-20_001", "timestamp": "2026-08-20T10:00:00+00:00", "title": "Planning",
            "harness": "claude-code", "processed": True},
           "user: we talked about Alpha Project and its parser today\n")
    _write(m / "entities" / "alpha-project.md",
           {"name": "Alpha Project", "type": "project", "status": "active", "confidence": 0.6,
            "created": "2026-08-01", "last_referenced": "2026-08-20", "source_episodes": ["ep_2026-08-20_001"]},
           "# Alpha Project\n")
    _write(m / "inbox" / "inbox-001.md",
           {"kind": "conflict", "status": "pending", "priority": 0.5, "entity_id": "alpha-project",
            "entity_name": "Alpha Project", "title": "q", "predicate": "deploys-to", "question": "Where now?",
            "options": [{"key": "a", "label": "one"}, {"key": "b", "label": "two"}], "created_date": "2026-08-20"},
           "ctx")
    _write(m / "inbox" / "inbox-002.md",
           {"kind": "merge_suggestion", "status": "pending", "priority": 0.5, "entity_id": "beta-example",
            "entity_name": "Beta Example", "title": "Is Beta Example the same as Alpha Project?",
            "created_date": "2026-08-20"},
           "ctx")
    return m


def _served(memory) -> dict:
    return {i.id: i.model_dump(mode="json") for i in inbox_service.load_inbox(memory)}


def _fresh(memory) -> dict:
    inbox_service.reset_built()
    return _served(memory)


def test_a_hit_is_the_rebuild_and_builds_nothing(memory, monkeypatch):
    first = _served(memory)
    calls = []
    real = inbox_service._build_inbox
    monkeypatch.setattr(inbox_service, "_build_inbox", lambda *a, **k: calls.append(1) or real(*a, **k))
    assert _served(memory) == first and calls == []
    a, b = inbox_service.load_inbox(memory), inbox_service.load_inbox(memory)
    assert a is not b, "each caller gets its own list"
    assert _fresh(memory) == first


def test_each_input_moving_rebuilds(memory, monkeypatch):
    before = _served(memory)
    assert set(before) == {"inbox-001"}, "a merge question about a name with no page and no held line is gone"

    # The inbox: an item's words change.
    item = memory / "inbox" / "inbox-001.md"
    parsed = markdown_parser.parse(item)
    markdown_parser.write(item, {**parsed.frontmatter, "title": "q, reworded"}, parsed.body)
    assert _served(memory)["inbox-001"]["title"] == "q, reworded" == _fresh(memory)["inbox-001"]["title"]

    # An episode: the cause's excerpt follows the conversation's words.
    ep = memory / "episodes" / "ep_2026-08-20_001.md"
    parsed = markdown_parser.parse(ep)
    markdown_parser.write(ep, parsed.frontmatter, "user: Alpha Project moved to a new host this week, a longer line\n")
    got = _served(memory)["inbox-001"]["cause"]["excerpt"]
    assert "new host" in got and got == _fresh(memory)["inbox-001"]["cause"]["excerpt"]

    # The predicate map: the predicate turns multi-valued, so the conflict becomes informational.
    assert _served(memory)["inbox-001"]["informational"] is False
    (memory / predicates.RUNTIME_FILE).write_text("multi_valued:\n- deploys-to\n", encoding="utf-8")
    assert _served(memory)["inbox-001"]["informational"] is True

    # The held names: a parked name brings its merge question back (G209).
    monkeypatch.setattr(pending_store, "waiting_ids", lambda mp: frozenset({"beta-example"}))
    pending_store.store_path(memory).write_text("\n", encoding="utf-8")   # the file's stamp moves
    assert "inbox-002" in _served(memory)

    # A page: the subject archived, its question retires.
    page = memory / "entities" / "alpha-project.md"
    parsed = markdown_parser.parse(page)
    markdown_parser.write(page, {**parsed.frontmatter, "status": "archived"}, parsed.body)
    assert "inbox-001" not in _served(memory)


def test_the_day_is_in_the_key(memory, monkeypatch):
    item = memory / "inbox" / "inbox-001.md"
    parsed = markdown_parser.parse(item)
    markdown_parser.write(item, {**parsed.frontmatter, "remind_after": "2026-09-02"}, parsed.body)

    class Day(dt.date):
        value = dt.date(2026, 9, 1)

        @classmethod
        def today(cls):
            return cls.value

    monkeypatch.setattr(inbox_service, "date", Day)
    assert "inbox-001" not in _served(memory), "deferred until tomorrow"
    Day.value = dt.date(2026, 9, 2)
    assert "inbox-001" in _served(memory), "the day it is due, with nothing written"


def test_an_etag_computes_only_what_it_names_each_as_the_full_map_does(memory, monkeypatch):
    full = sync_service.components(memory)
    assert sync_service.components(memory, keys=("inbox", "entities", "episodes")) == {
        k: full[k] for k in ("inbox", "entities", "episodes")}
    walked = []
    monkeypatch.setattr(sync_service.backlog, "stamp", lambda mp: walked.append("backlog") or "")
    sync_service.etag_for(memory, "inbox", "entities", "episodes")
    assert walked == [], "a component the ETag does not name is never computed"
    with pytest.raises(KeyError):
        sync_service.etag_for(memory, "no-such-component")


def test_served_counts_from_a_current_built_list_are_the_walks(memory):
    inbox_service.reset_built()
    walked = inbox_service.served_counts(memory)            # no built list yet: the header walk
    inbox_service.load_inbox(memory)
    assert inbox_service.served_counts(memory) == walked     # answered from the built list
    item = memory / "inbox" / "inbox-001.md"
    parsed = markdown_parser.parse(item)
    markdown_parser.write(item, {**parsed.frontmatter, "status": "resolved"}, parsed.body)
    inbox_service.reset_built()
    fresh = inbox_service.served_counts(memory)
    inbox_service.load_inbox(memory)
    assert inbox_service.served_counts(memory) == fresh


def test_a_remembered_count_moves_with_what_it_counts(memory):
    inbox_service.reset_built()
    total, _ = inbox_service.served_counts(memory)          # the walk, remembered
    assert inbox_service.served_counts(memory)[0] == total
    _write(memory / "inbox" / "inbox-003.md",
           {"kind": "clarification", "status": "pending", "priority": 0.5, "entity_id": "gamma-example",
            "entity_name": "Gamma Example", "title": "Who is Gamma Example?", "created_date": "2026-08-20"}, "ctx")
    assert inbox_service.served_counts(memory)[0] == total + 1


def test_origins_are_remembered_only_while_both_folders_hold(memory):
    from api.services import origin_stats

    first = origin_stats.aggregate_origins(memory)
    first[0]["episodeCount"] = -1                            # a caller's edit never reaches the next answer
    assert origin_stats.aggregate_origins(memory) == origin_stats._aggregate(memory)
    _write(memory / "episodes" / "ep_2026-08-21_001.md",
           {"id": "ep_2026-08-21_001", "timestamp": "2026-08-21T10:00:00+00:00", "origin": "mcp"}, "user: hi\n")
    assert origin_stats.aggregate_origins(memory) == origin_stats._aggregate(memory)
    assert any(r["origin"] == "mcp" for r in origin_stats.aggregate_origins(memory))


def test_the_card_reads_the_page_file_exactly_as_a_parse(memory):
    from api.routers import entities

    page = memory / "entities" / "alpha-project.md"
    for _ in range(2):   # cold (bank_index parses it), then warm (its cached header)
        parsed, raw = entities._page_file(memory, page)
        want = markdown_parser.parse(page, ledger=False)
        assert (parsed.frontmatter, parsed.body, raw) == (want.frontmatter, want.body, page.read_text())
