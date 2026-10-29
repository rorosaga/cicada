"""Inbox lag (owner, 2026-10-17): opening the Inbox spun the cursor.

``load_inbox`` asks, for every item, whether its subject still has a page (G98). A subject merged away or renamed
has none under any spelling, and ``resolve_entity_file``'s last rung — the case-insensitive stem match — ran a fresh
``entities/*.md`` glob for each such item: on a bank of 4,700 pages and 900 items, 3.5 M paths and ~6 s per read,
inside an ``async`` route, so every other request waited behind it. The match now reads one cached index of the
folder (rebuilt when the folder changes), the subject's header comes from ``bank_index``, and the route reads off
the event loop. These tests pin the behaviour (same hidden/gone decisions) and the scan count; the timing budget at
the owner's scale is the ``bench`` tier (``make test-bench``), like every other wall-clock assertion in this suite.
"""
from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from _inbox_bench_bank import build
from api import config, main
from api.services import id_utils, inbox_service, markdown_parser


def _settle(directory: Path) -> None:
    """Date the folder's last change a minute back, past the listing's racy window — what a bank looks like between
    writes. A folder changed this instant is listed again on each call, by design (``id_utils._RACY_NS``)."""
    past = time.time() - 60
    os.utime(directory, (past, past))


def _page(memory: Path, eid: str, *, status: str = "active") -> None:
    (memory / "entities").mkdir(parents=True, exist_ok=True)
    markdown_parser.write(memory / "entities" / f"{eid}.md",
                          {"name": eid.replace("-", " ").title(), "type": "concept", "status": status}, "Body.")


def _item(memory: Path, item_id: str, entity_id: str, kind: str = "merge_suggestion") -> None:
    (memory / "inbox").mkdir(parents=True, exist_ok=True)
    markdown_parser.write(memory / "inbox" / f"{item_id}.md",
                          {"kind": kind, "status": "pending", "priority": 0.5, "entity_id": entity_id,
                           "entity_name": entity_id, "title": f"About {entity_id}", "created_date": "2026-09-01"},
                          "Context.")


def test_gone_archived_and_case_variant_subjects_keep_their_decisions(tmp_path):
    memory = tmp_path / "memory"
    _page(memory, "alpha-project")
    _page(memory, "Beta-Example")                    # an on-disk stem that is not lowercase
    _page(memory, "gamma-project", status="archived")
    _item(memory, "inbox-001", "alpha-project")       # exact slug: served
    _item(memory, "inbox-002", "Alpha Project")       # display name, sanitized: served
    _item(memory, "inbox-003", "beta-example")        # only the case-insensitive stem finds it: served
    _item(memory, "inbox-004", "gone-subject")        # no page by any spelling: hidden
    _item(memory, "inbox-005", "Gone Subject", kind="conflict")  # hidden
    _item(memory, "inbox-006", "gamma-project")       # archived: hidden
    _item(memory, "inbox-007", "never-paged", kind="clarification")  # answering it makes the page: served

    served = [i.id for i in inbox_service.load_inbox(memory)]

    assert sorted(served) == ["inbox-001", "inbox-002", "inbox-003", "inbox-007"]
    assert id_utils.resolve_entity_file(memory, "BETA-EXAMPLE") == memory / "entities" / "Beta-Example.md"
    assert inbox_service.served_counts(memory)[0] == 4


def test_a_page_written_after_a_read_is_found_on_the_next(tmp_path):
    """The cached index follows the folder: a merge that brings a subject back (or a new page) is seen at once."""
    memory = tmp_path / "memory"
    _page(memory, "alpha-project")
    _item(memory, "inbox-001", "Delta-Example")
    _settle(memory / "entities")
    assert inbox_service.load_inbox(memory) == []

    _page(memory, "delta-example")
    assert [i.id for i in inbox_service.load_inbox(memory)] == ["inbox-001"]

    (memory / "entities" / "delta-example.md").unlink()
    assert inbox_service.load_inbox(memory) == []


def test_the_entities_folder_is_listed_once_per_read_not_once_per_item(tmp_path, monkeypatch):
    memory = build(tmp_path / "memory", pages=400, items=150)   # 100 of the 150 name a subject with no page
    entities = str(memory / "entities")
    _settle(memory / "entities")
    inbox_service.load_inbox(memory)                 # warm: the one listing this folder state needs

    listed: list[str] = []
    globbed: list[str] = []
    real_listdir, real_glob = os.listdir, Path.glob
    monkeypatch.setattr(id_utils.os, "listdir", lambda d: listed.append(str(d)) or real_listdir(d))
    monkeypatch.setattr(Path, "glob", lambda self, pattern, **kw: globbed.append(str(self)) or real_glob(self, pattern, **kw))

    assert inbox_service.load_inbox(memory), "the fixture serves some items"
    assert listed.count(entities) == 0, "a settled folder is answered from the cached index"
    assert globbed.count(entities) == 0, "no per-item scan of the pages"

    # A folder that changed is listed again: once for the whole read, never once per item.
    _page(memory, "zeta-example")
    _settle(memory / "entities")
    listed.clear()
    inbox_service.load_inbox(memory)
    assert listed.count(entities) == 1
    assert globbed.count(entities) == 0


def test_the_inbox_route_reads_off_the_event_loop(tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    _page(memory, "alpha-project")
    _item(memory, "inbox-001", "alpha-project")
    seen: list[bool] = []
    real = inbox_service.load_inbox

    def spy(memory_path, **kw):
        try:
            asyncio.get_running_loop()
            seen.append(True)                         # called on the event loop: every request waits
        except RuntimeError:
            seen.append(False)
        return real(memory_path, **kw)

    monkeypatch.setattr(inbox_service, "load_inbox", spy)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    try:
        client = TestClient(main.app)
        for route in ("/inbox", "/nudges", "/clarifications"):
            assert client.get(route).status_code == 200, route
    finally:
        config.get_settings.cache_clear()
    assert seen == [False, False, False]


@pytest.mark.bench
def test_load_inbox_at_the_owners_scale_is_well_under_half_a_second(tmp_path):
    memory = build(tmp_path / "memory")              # 4,700 pages, 913 items
    _settle(memory / "entities")
    inbox_service.load_inbox(memory)
    # The build itself, every run (the built list would answer a repeat for nothing, speed 2026-10-29), in CPU time:
    # a wall clock failed this whenever the Mac ran 30–55 other processes, and the budget is the code's cost.
    # Each budget also holds the wall clock under 4× itself (review of #518): CPU alone would pass a read that waits.
    def timed(reset) -> tuple[float, float]:
        cpus, walls = [], []
        for _ in range(3):
            reset()
            cpu, wall = time.process_time(), time.perf_counter()
            inbox_service.load_inbox(memory)
            cpus.append(time.process_time() - cpu)
            walls.append(time.perf_counter() - wall)
        return min(cpus), min(walls)

    def rebuild():
        inbox_service.reset_built()

    def cold():   # and the caches a rebuild leans on: the cut excerpts and the untimed ids (review of #518)
        from api.services import episode_time, inbox_context

        inbox_service.reset_built()
        inbox_context._EXCERPTS.clear()
        episode_time._UNTIMED.clear()

    for label, reset in (("rebuild", rebuild), ("cold rebuild", cold)):
        cpu, wall = timed(reset)
        print(f"load_inbox {label} at 4,700 pages / 913 items: {cpu * 1000:.0f} ms CPU, {wall * 1000:.0f} ms wall")
        assert cpu < 0.5 and wall < 2.0, (label, cpu, wall)
    cpu, wall = timed(lambda: None)
    print(f"load_inbox, nothing moved: {cpu * 1000:.1f} ms CPU, {wall * 1000:.1f} ms wall")
    assert cpu < 0.1 and wall < 0.4, (cpu, wall)
