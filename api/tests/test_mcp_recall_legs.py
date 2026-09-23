"""G140 Q-R1..Q-R3 (R3 P1, P2, P4) — MCP recall's legs, and history on request.

Before: recall's keyword leg matched the WHOLE query as one substring of
name/tags/related/body and never read `aliases`; claims were never a recall
leg; a closed claim never surfaced anywhere an agent looks. Hermetic: no
vector index (the indexer raises, as in the golden run), a synthetic bank, the
FTS index built inline (Q-R16). Placeholders only.
"""
from __future__ import annotations

import inspect
import json
import re
from datetime import date, timedelta
from pathlib import Path

import pytest

from _stdio_server import stdio_server
from api.remote import runtime as remote_runtime
from api.remote import tools as remote_tools
from api.services import markdown_parser, mcp_tools, search_index, search_service, vector_index
from api.services.claims import Claim, write_claims
from api.services.vector_index import SqliteVecIndexer

mcp = stdio_server()
TODAY = date.today()


def _ago(days: int) -> str:
    return (TODAY - timedelta(days=days)).isoformat()


def _page(memory: Path, eid: str, name: str, *, etype: str = "concept", aliases=(), body: str = "",
          claims=()) -> None:
    text = f"## Summary\n{body or name + ' is a synthetic page.'}\n"
    if claims:
        text = write_claims(text, list(claims))
    markdown_parser.write(memory / "entities" / f"{eid}.md",
                          {"name": name, "type": etype, "status": "active", "confidence": 0.6,
                           "aliases": list(aliases), "tags": [], "related": []}, text)


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


FENCE = "`" * 3  # spelled out so this file never holds a literal fence


def _suggested(reply: str) -> list[str]:
    m = re.search(FENCE + r"cicada-hints\n(.*?)\n" + FENCE, reply, re.S)
    return json.loads(m.group(1))["suggested_entities"] if m else []


def _changes(reply: str) -> list[str]:
    head = f"**Changed recently (last {mcp_tools.RECENT_CHANGE_DAYS} days):**\n"
    return reply.split(head, 1)[1].split("\n\n", 1)[0].splitlines() if head in reply else []


def _closed_pair(subject: str, old_obj: str, new_obj: str, closed_on: str) -> list[Claim]:
    new = Claim(id=f"clm_{subject}_uses_{new_obj}", text=f"{subject} uses {new_obj}", subject=subject,
                predicate="uses", object=new_obj, valid_from=closed_on)
    old = Claim(id=f"clm_{subject}_uses_{old_obj}", text=f"{subject} uses {old_obj}", subject=subject,
                predicate="uses", object=old_obj, valid_from="2026-01-01", valid_to=closed_on,
                superseded_by=new.id)
    return [old, new]


def test_an_alias_reaches_its_page(bank):
    _page(bank, "dining-preferences", "Dining", aliases=["takeout", "delivery"])
    _page(bank, "alpha-project", "Alpha Project", etype="project")
    search_index.ensure_fresh(bank, wait=True)
    assert _suggested(mcp.handle_recall("takeout")) == ["dining-preferences"]


def test_query_words_match_one_by_one(bank):
    _page(bank, "alpha-project", "Alpha Project", etype="project",
          body="Alpha Project is a synthetic search index.")
    search_index.ensure_fresh(bank, wait=True)
    assert "alpha-project" in _suggested(mcp.handle_recall("project alpha"))


def test_a_matching_claim_leads_to_its_subject(bank):
    claim = Claim(id="clm_bob_partner", text="Bob Example is the partner of the person",
                  subject="bob-example", predicate="partner-of", object="owner", valid_from="2026-01-01")
    _page(bank, "bob-example", "Bob Example", etype="person", body="Bob Example is a synthetic person.",
          claims=[claim])
    search_index.ensure_fresh(bank, wait=True)
    assert mcp_tools._claim_subject_search(bank, "partner", 8) == [
        {"entity_id": "bob-example", "source": "claim", "score": 0.0}]


def test_the_claim_leg_is_fused_as_a_third_list(bank, monkeypatch):
    _page(bank, "bob-example", "Bob Example", etype="person")
    monkeypatch.setattr(mcp.mcp_tools, "_keyword_search_entities", lambda entities_dir, query, top_k: [])
    monkeypatch.setattr(mcp.mcp_tools, "_claim_subject_search",
                        lambda memory_path, query, top_k: [{"entity_id": "bob-example", "source": "claim"}])
    assert _suggested(mcp.handle_recall("anything at all")) == ["bob-example"]


def test_recall_fuses_with_the_one_rrf():
    assert mcp_tools._rrf_fuse is search_service.rrf_fuse
    assert mcp._rrf_fuse is search_service.rrf_fuse, "the stdio server keeps re-exporting the name"


def test_a_replaced_value_reads_was_until_now(bank):
    _page(bank, "alpha-project", "Alpha Project", etype="project",
          claims=_closed_pair("alpha-project", "sqlite", "duckdb", _ago(5)))
    search_index.ensure_fresh(bank, wait=True)
    assert _changes(mcp.handle_recall("alpha project")) == [
        f'- `alpha-project` uses: was "sqlite" until {_ago(5)} → now "duckdb"']


def test_history_is_bounded_per_page_and_by_age(bank):
    claims = [Claim(id=f"clm_t{i}", text=f"alpha tried tool {i}", subject="alpha-project",
                    predicate=f"tried-{i}", object=f"tool-{i}", valid_from="2026-01-01",
                    valid_to=_ago(1 + i)) for i in range(4)]
    claims.append(Claim(id="clm_ancient", text="alpha was hosted on ancient", subject="alpha-project",
                        predicate="hosted-on", object="ancient", valid_from="2025-01-01",
                        valid_to=_ago(mcp_tools.RECENT_CHANGE_DAYS + 5)))
    _page(bank, "alpha-project", "Alpha Project", etype="project", claims=claims)
    search_index.ensure_fresh(bank, wait=True)
    lines = _changes(mcp.handle_recall("alpha project"))
    assert [line.split(":")[0] for line in lines] == ["- `alpha-project` tried-0", "- `alpha-project` tried-1"]


def test_history_is_capped_across_pages(bank):
    for eid in ("alpha-one", "alpha-two", "alpha-three"):
        _page(bank, eid, eid.replace("-", " ").title(), claims=[
            Claim(id=f"clm_{eid}_{i}", text=f"{eid} tried {i}", subject=eid, predicate=f"tried-{i}",
                  object=f"tool-{i}", valid_from="2026-01-01", valid_to=_ago(1 + i)) for i in range(2)])
    search_index.ensure_fresh(bank, wait=True)
    assert len(_changes(mcp.handle_recall("alpha"))) == mcp_tools.RECENT_CHANGES_TOTAL


def test_perspective_history_lists_earlier_claims_on_request(bank):
    _page(bank, "alpha-project", "Alpha Project", etype="project",
          claims=_closed_pair("alpha-project", "sqlite", "duckdb", _ago(5)))
    plain = mcp.handle_tool("cicada_get_perspective", {"subject": "alpha-project"})
    assert "Earlier" not in plain and "1 valid claim" in plain
    full = mcp.handle_tool("cicada_get_perspective", {"subject": "alpha-project", "history": True})
    assert full.startswith(plain), "the current half is byte-identical"
    assert "Earlier, newest first (1):" in full
    assert 'replaced by "duckdb"' in full and f"→ {_ago(5)}" in full


def test_history_is_in_both_schemas_and_the_remote_dispatch(monkeypatch):
    stdio = {t["name"]: t for t in mcp.TOOLS}["cicada_get_perspective"]["inputSchema"]["properties"]
    remote = remote_tools.REMOTE_TOOLS["cicada_get_perspective"]["inputSchema"]["properties"]
    assert stdio["history"]["type"] == remote["history"]["type"] == "boolean"
    seen: dict = {}
    monkeypatch.setattr(mcp_tools, "get_perspective",
                        lambda ctx, subject, observer, context, history: seen.update(history=history) or "ok")
    remote_runtime._DISPATCH["cicada_get_perspective"](None, {"subject": "x", "history": True})
    assert seen == {"history": True}


def test_search_claims_has_no_dead_flag():
    assert "include_superseded" not in inspect.signature(SqliteVecIndexer.search_claims).parameters
