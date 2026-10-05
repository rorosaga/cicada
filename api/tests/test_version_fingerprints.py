"""Audit 2026-10-05 P2-9: a version stamp must move on every edit.

The stamps were "the newest mtime in the directory" (plus a count). With one
file dated in the future — a synced copy, a clock that stepped back — editing
any OTHER file leaves the max unchanged, so `/sync/version` never moved, the
app's ETags answered 304 and the graph cache served the old page. The stamp is
now a fingerprint of every file's name, size and nanosecond mtime, from the
shared directory scan (#173). Synthetic banks only.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from api.services import backlog, bank_index, graph_builder, markdown_parser, sync_service

FUTURE = time.time() + 86_400


def _page(path: Path, name: str, body: str = "## Summary\nA page.\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    markdown_parser.write(path, {"name": name, "type": "project", "status": "active", "confidence": 0.5}, body)


def _edit(path: Path, text: str) -> None:
    """Rewrite a file the way a writer does, with a clock in the present."""
    path.write_text(path.read_text() + text)
    now = time.time()
    os.utime(path, (now, now))


@pytest.fixture
def bank(tmp_path):
    bank = tmp_path / "bank"
    _page(bank / "entities" / "alpha-project.md", "alpha-project")
    _page(bank / "entities" / "beta-project.md", "beta-project")
    os.utime(bank / "entities" / "alpha-project.md", (FUTURE, FUTURE))
    for sub, name in (("episodes", "ep_2026-10-01_001.md"), ("episodes", "ep_2026-10-01_002.md"),
                      ("hubs", "h1.md"), ("hubs", "h2.md"), ("inbox", "inbox-001.md"), ("inbox", "inbox-002.md"),
                      ("sources", "s1.md"), ("sources", "s2.md")):
        (bank / sub).mkdir(exist_ok=True)
        (bank / sub / name).write_text("---\nstatus: pending\n---\nx\n")
    for sub, first in (("episodes", "ep_2026-10-01_001.md"), ("hubs", "h1.md"), ("inbox", "inbox-001.md"),
                       ("sources", "s1.md")):
        os.utime(bank / sub / first, (FUTURE, FUTURE))
    return bank


@pytest.mark.parametrize("component, path", [
    ("entities", "entities/beta-project.md"),
    ("episodes", "episodes/ep_2026-10-01_002.md"),
    ("hubs", "hubs/h2.md"),
    ("inbox", "inbox/inbox-002.md"),
    ("sources", "sources/s2.md"),
])
def test_an_edit_moves_its_component_beside_a_future_dated_file(bank, component, path):
    before = sync_service.components(bank)[component]
    _edit(bank / path, "\nmore\n")
    assert sync_service.components(bank)[component] != before


def test_the_backlog_stamp_moves_beside_a_future_dated_item(bank):
    root = bank / backlog.BACKLOG_DIR / "alpha-project"
    root.mkdir(parents=True)
    (root / "a.md").write_text("---\nid: A-1\n---\nx\n")
    (root / "b.md").write_text("---\nid: A-2\n---\ny\n")
    os.utime(root / "a.md", (FUTURE, FUTURE))
    os.utime(root, (FUTURE, FUTURE))
    before = backlog.stamp(bank)
    _edit(root / "b.md", "\nmore\n")
    assert backlog.stamp(bank) != before


def test_the_graph_cache_sees_an_edit_beside_a_future_dated_page(bank):
    graph_builder._CACHE["key"] = None
    names = {n.id: n.name for n in graph_builder.build_graph(bank).nodes}
    assert names["beta-project"] == "beta-project"
    _page(bank / "entities" / "beta-project.md", "Beta Renamed")
    now = time.time()
    os.utime(bank / "entities" / "beta-project.md", (now, now))
    names = {n.id: n.name for n in graph_builder.build_graph(bank).nodes}
    assert names["beta-project"] == "Beta Renamed"


def test_a_fingerprint_comes_from_the_shared_scan(bank, monkeypatch):
    calls = []
    real = bank_index._scan_uncached
    monkeypatch.setattr(bank_index, "_scan_uncached", lambda d: calls.append(Path(d).name) or real(d))
    with bank_index.shared_scans():
        sync_service.components(bank)
        sync_service.components(bank)
    assert calls.count("entities") == 1 and calls.count("episodes") == 1
