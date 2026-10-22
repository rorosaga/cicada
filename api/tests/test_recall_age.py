"""Recall says how old a page is, not a raw confidence (G210).

Before: each page's heading read `(type, confidence: 0.31937296013304495, status: decaying)`, so an agent could
not tell a page last said yesterday from one silent for eleven months, and a closed claim read "was X until D".
Now the heading reads `(type, last said 3 weeks ago on <day> · fading)` and a closed claim says on which day it was
superseded, ended, withdrawn or closed. Ranking is unchanged: "Confidence does not rank recall". Placeholders only.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from _stdio_server import stdio_server
from api.services import entity_bands, markdown_parser, mcp_tools, search_index, vector_index
from api.services.claims import Claim

TODAY = date(2026, 10, 22)


@pytest.mark.parametrize("days, words", [
    (0, "today"), (1, "yesterday"), (5, "5 days ago"), (13, "13 days ago"), (14, "2 weeks ago"),
    (21, "3 weeks ago"), (59, "8 weeks ago"), (60, "2 months ago"), (330, "11 months ago"),
    (729, "24 months ago"), (730, "2 years ago"), (-3, ""),
])
def test_age_words(days, words):
    assert entity_bands.age_words(TODAY - timedelta(days=days), TODAY) == words


@pytest.mark.parametrize("last, status, line", [
    ("2026-10-01", "decaying", "last said 3 weeks ago on 2026-10-01 · fading"),
    ("2026-10-22T09:00:00", "active", "last said today on 2026-10-22 · active"),
    ("2025-11-20", "archived", "last said 11 months ago on 2025-11-20 · archived"),
    (None, "active", "active"),
    ("someday", "decaying", "fading"),
    ("2026-12-01", "active", "last said on 2026-12-01 · active"),
])
def test_said_line(last, status, line):
    assert entity_bands.said_line(last_referenced=last, status=status, today=TODAY) == line


mcp = stdio_server()


@pytest.fixture
def bank(tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox", "hubs"):
        (memory / sub).mkdir(parents=True)

    class _NoIndex:
        def __init__(self, *a, **k):
            raise RuntimeError("no vector index in this bank")

    monkeypatch.setattr(vector_index, "SqliteVecIndexer", _NoIndex)
    monkeypatch.setattr(mcp, "get_memory_path", lambda: memory)
    monkeypatch.setattr(mcp, "_STATE_HINT_SENT", False)
    monkeypatch.setattr(mcp.mcp_tools, "_relevant_inbox", lambda memory_path, query, **_: [])
    return memory


def _page(memory: Path, eid: str, name: str, *, confidence: float, last: str, status: str = "active") -> None:
    markdown_parser.write(memory / "entities" / f"{eid}.md",
                          {"name": name, "type": "project", "status": status, "confidence": confidence,
                           "last_referenced": last, "tags": [], "related": []},
                          f"## Summary\n{name} is a synthetic alpha page.\n")


def test_the_heading_says_age_and_state_and_never_the_raw_confidence(bank):
    day = (date.today() - timedelta(days=21)).isoformat()
    _page(bank, "alpha-project", "Alpha Project", confidence=0.31937296013304495, last=day, status="decaying")
    search_index.ensure_fresh(bank, wait=True)
    reply = mcp.handle_recall("alpha project")
    assert f"### Alpha Project (project, last said 3 weeks ago on {day} · fading)" in reply
    assert "confidence" not in reply


def test_confidence_still_ranks_nothing(bank):
    """Two pages whose confidence is swapped come back in the same order."""
    def order(conf_a, conf_b):
        for f in (bank / "entities").glob("*.md"):
            f.unlink()
        _page(bank, "alpha-one", "Alpha One", confidence=conf_a, last="2026-01-01")
        _page(bank, "alpha-two", "Alpha Two", confidence=conf_b, last="2026-01-01")
        search_index.ensure_fresh(bank, wait=True)
        reply = mcp.handle_recall("alpha")
        return [reply.index("### Alpha One"), reply.index("### Alpha Two")]
    first = order(0.9, 0.1)
    second = order(0.1, 0.9)
    assert (first[0] < first[1]) == (second[0] < second[1])


def _claim(cid, obj, **kw):
    return Claim(id=cid, text=f"alpha uses {obj}", subject="alpha-project", predicate="uses", object=obj, **kw)


def test_each_closed_claim_says_the_day_it_stopped():
    new = _claim("clm_new", "duckdb", valid_from="2026-10-17")
    replaced = _claim("clm_old", "sqlite", valid_from="2026-01-01", valid_to="2026-10-17", superseded_by="clm_new")
    gone = _claim("clm_gone", "redis", valid_from="2026-01-01", valid_to="2026-10-15", superseded_by="clm_missing")
    closed = _claim("clm_closed", "lmdb", valid_from="2026-01-01", valid_to="2026-10-14")
    page = [new, replaced, gone, closed]
    line = lambda c: mcp_tools._history_line("alpha-project", c, page)   # noqa: E731
    assert line(replaced) == '- `alpha-project` uses: "sqlite" — superseded on 2026-10-17 by "duckdb"'
    assert line(gone) == '- `alpha-project` uses: "redis" — superseded on 2026-10-15'
    assert line(closed).startswith('- `alpha-project` uses: "lmdb" — ')
    assert "on 2026-10-14" in line(closed)
