"""Recall stays under the harness's result cap whatever the bank holds (2026-10-22).

Reproduced on a live install: a recall for a person's handle returned 221,719 characters — the owner page's ~2,300
related ids printed on one `Related:` line and its key facts kept whole — and Claude Code refuses an MCP result over
its cap, so the agent received only an error. Synthetic bank, placeholders only, no vector index, the FTS index
built inline.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from _stdio_server import stdio_server
from api.services import entity_body, markdown_parser, mcp_tools, search_index, vector_index

mcp = stdio_server()


def _owner_page(memory: Path, *, related: int = 2_400, facts: int = 600) -> None:
    body = ("## Summary\nOwner-example is the person this bank belongs to; handle bob-handle.\n\n"
            "## Key Facts\n" + "\n".join(f"- Fact number {i}: owner-example worked on alpha-project-{i} "
                                          f"with a synthetic detail that runs to a realistic length." for i in range(facts))
            + "\n\n## History\n" + "\n".join(f"- 2026-01-{1 + i % 28:02d}: event {i}" for i in range(200)) + "\n")
    markdown_parser.write(memory / "entities" / "owner-example.md",
                          {"name": "Owner-example", "type": "person", "status": "active", "confidence": 0.9,
                           "aliases": ["bob-handle"], "tags": [], "owner": True,
                           "related": [f"synthetic-related-page-{i:04d}" for i in range(related)]}, body)


def _page(memory: Path, eid: str, *, related=(), facts: int = 3) -> None:
    body = (f"## Summary\n{eid} mentions bob-handle once.\n\n## Key Facts\n"
            + "\n".join(f"- {eid} fact {i} about bob-handle" for i in range(facts)) + "\n")
    markdown_parser.write(memory / "entities" / f"{eid}.md",
                          {"name": eid, "type": "project", "status": "active", "confidence": 0.6,
                           "aliases": [], "tags": [], "related": list(related)}, body)


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


def test_a_huge_owner_page_keeps_recall_under_budget(bank):
    _owner_page(bank)
    for i in range(6):
        _page(bank, f"alpha-project-{i}", facts=40)
    search_index.ensure_fresh(bank, wait=True)
    reply = mcp.handle_recall("bob-handle")
    assert len(reply) <= mcp_tools.RECALL_BUDGET
    assert "### Owner-example (person" in reply
    related = next(line for line in reply.splitlines() if line.startswith("Related: synthetic-related-page"))
    assert related.split(" … ")[0].count(",") == mcp_tools.RECALL_RELATED_SHOWN - 1
    assert f"… and {2_400 - mcp_tools.RECALL_RELATED_SHOWN:,} more" in related
    assert 'cicada_recall_detail(entity_id="owner-example", start=1) lists them all' in related
    assert "- Fact number 0:" in reply and "more on the full page" in reply


def test_related_names_this_recall_returned_come_first(bank):
    _page(bank, "beta-hit", facts=1)
    rel = [f"filler-{i}" for i in range(40)] + ["beta-hit"]
    line = mcp_tools._related_line(rel, frozenset({"beta-hit"}), None)
    assert line.startswith("Related: beta-hit, filler-0")
    assert line.endswith("… and 29 more")


def test_a_short_related_list_is_unchanged():
    assert mcp_tools._related_line(["Bob Example"], frozenset(), "x") == "Related: Bob Example"


def test_key_facts_are_bounded_within_the_entity_budget():
    body = "## Summary\nShort.\n\n## Key Facts\n" + "\n".join(f"- fact {i} " + "x" * 80 for i in range(500))
    out = entity_body.summarize_for_recall(body, max_chars=3200)
    assert len(out) < 3400
    assert out.startswith("## Summary\nShort.") and "- fact 0 " in out
    assert out.rstrip().endswith("more on the full page")


def test_the_whole_result_guard_drops_lowest_ranked_first_and_says_so():
    blocks = ["### top\n" + "a" * 900, "### mid\n" + "b" * 900, "### low\n" + "c" * 900]
    text = mcp_tools._fit_recall(["hints", "joined"], 1, blocks, ["top", "mid", "low"], 2_200,
                                 lambda eid, **kw: f'cicada_recall_detail(entity_id="{eid}")')
    assert len(text) <= 2_200
    assert "### top" in text and "### mid" in text and "### low" not in text
    assert "1 lower-ranked page(s) left out" in text and "`low`" in text


def test_under_budget_the_reply_is_byte_for_byte_unchanged():
    parts = ["hints", "x", "tail"]
    assert mcp_tools._fit_recall(parts, 1, ["a", "b"], ["a", "b"], 10_000, None) == "hints\n\na\n\nb\n\ntail"
