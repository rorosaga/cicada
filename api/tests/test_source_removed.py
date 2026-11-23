"""G104 slice 3 (T2): a claim whose evidence episode was removed from its source reads ``sourceRemoved`` on every door
that draws a claim's evidence. The claim stays open and counted, ``status`` stays what the offsets say, and nothing is
written to a page. Synthetic fixtures, placeholders only."""
from __future__ import annotations

import pytest
from _cli import envelope, run_cli
from _synthetic_bank import _bank
from fastapi.testclient import TestClient

from api import config, main
from api.services import bank_index, evidence, markdown_parser, mcp_tools, page_citations, provenance, source_spans
from api.services.claims import Claim, Evidence, parse_claims, write_claims
from api.tests import page_citation_fixture as cites

GONE = "ep_2026-09-01_001"
LIVE = "ep_2026-09-02_001"
GONE_TEXT = "user: The alpha-project studio opens in December."
LIVE_TEXT = "user: The alpha-project studio has a garden."
DAY = "2026-11-02"
SENTENCE = f"Removed from its source on {DAY}; kept as evidence."


def _claim(cid: str, doc: str, text: str, quote: str) -> Claim:
    at = text.index(quote)
    ev = Evidence(episode=doc, start=at, end=at + len(quote), hash=evidence.body_hash(text), kind="user")
    return Claim(id=cid, text=f"sentence of {cid}", subject="alpha-project", predicate="said", object="x",
                 object_kind="literal", observer="agent", context="general", epistemic="explicit",
                 source_trust="agent", confidence=0.8, valid_from="2026-09-01", recorded_at="2026-09-01",
                 source_episodes=[doc], evidence=[ev])


@pytest.fixture
def memory(tmp_path, monkeypatch):
    mem = tmp_path / "memory"
    (mem / "entities").mkdir(parents=True)
    (mem / "episodes").mkdir()
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(mem))
    monkeypatch.setenv("CICADA_API_AUTH", "off")
    config.get_settings.cache_clear()
    bank_index.invalidate()
    source_spans.forget()
    markdown_parser.write(mem / "episodes" / f"{GONE}.md",
                          {"id": GONE, "origin": "folder", "title": "A removed note", "processed": True,
                           "timestamp": "2026-09-01T08:00:00+00:00", "source_deleted_at": f"{DAY}T10:00:00+00:00"},
                          GONE_TEXT)
    markdown_parser.write(mem / "episodes" / f"{LIVE}.md",
                          {"id": LIVE, "origin": "folder", "title": "A kept note", "processed": True,
                           "timestamp": "2026-09-02T08:00:00+00:00"}, LIVE_TEXT)
    claims = [_claim("c-gone", GONE, GONE_TEXT, "studio opens in December"),
              _claim("c-live", LIVE, LIVE_TEXT, "studio has a garden")]
    markdown_parser.write(mem / "entities" / "alpha-project.md",
                          {"name": "Alpha Project", "type": "project", "status": "active", "confidence": 0.9,
                           "source_episodes": [GONE, LIVE]},
                          write_claims("## Summary\nAlpha Project.\n", claims))
    yield mem
    config.get_settings.cache_clear()
    source_spans.forget()


def test_the_spans_route_marks_a_removed_source_and_keeps_its_status(memory):
    page = memory / "entities" / "alpha-project.md"
    with TestClient(main.app) as client:   # startup's own migrations may touch a page: compare from here
        before = page.read_bytes()
        gone = client.get(f"/episodes/{GONE}/spans").json()
        live = client.get(f"/episodes/{LIVE}/spans").json()
    span = gone["groups"][0]["spans"][0]
    assert span["sourceRemoved"] is True and span["status"] == "current" and span["current"] is True
    assert span["at"] is not None, "the words are still there: the span still draws"
    assert live["groups"][0]["spans"][0]["sourceRemoved"] is False
    assert page.read_bytes() == before, "derived on read, nothing written to the page"
    assert [c.id for c in parse_claims(page.read_text())] == ["c-gone", "c-live"]


def test_the_citations_and_text_routes_mark_it_too(memory):
    start = GONE_TEXT.index("studio opens")
    with TestClient(main.app) as client:
        rows = client.get(f"/episodes/{GONE}/citations").json()["citations"]
        focus = client.get(f"/episodes/{GONE}/text", params={
            "start": start, "end": start + 5, "hash": evidence.body_hash(GONE_TEXT)}).json()["focus"]
        live_rows = client.get(f"/episodes/{LIVE}/citations").json()["citations"]
    assert rows and all(r["span"]["sourceRemoved"] is True for r in rows)
    assert rows[0]["current"] is True and rows[0]["span"]["status"] == "current"
    assert focus["span"]["sourceRemoved"] is True
    assert all(r["span"]["sourceRemoved"] is False for r in live_rows)


def test_entity_provenance_marks_a_removed_source(memory):
    docs = provenance._Episodes(memory)
    removed = provenance._section_evidence(
        _claim("c", GONE, GONE_TEXT, "studio opens").evidence[0], docs, {GONE})
    kept = provenance._section_evidence(
        _claim("c", LIVE, LIVE_TEXT, "studio has").evidence[0], docs, {LIVE})
    assert removed.source_removed is True and removed.span is not None and removed.span.source_removed is True
    assert removed.status == "current"
    assert kept.source_removed is False and kept.span.source_removed is False


def test_the_pages_citations_mark_a_removed_source(tmp_path):
    cites.write_episodes(tmp_path)
    path = tmp_path / "episodes" / f"{cites.EP_OTHER}.md"
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, dict(parsed.frontmatter, source_deleted_at=f"{DAY}T10:00:00+00:00"), parsed.body)
    (tmp_path / "entities").mkdir(exist_ok=True)
    front = dict({"name": "Alpha Place", "type": "location"}, section_provenance=cites.records(cites.BODY, tmp_path))
    markdown_parser.write(tmp_path / "entities" / "alpha-place.md", front, write_claims(cites.BODY, []))
    page = markdown_parser.parse(tmp_path / "entities" / "alpha-place.md", ledger=False)
    block = page_citations.block(tmp_path, "alpha-place", fm=page.frontmatter, body=page.body, claims=[])
    by_title = {r["title"]: r for r in block["refs"]}
    assert by_title["Market walk"]["sourceRemoved"] is True
    assert not by_title["Studio plan"].get("sourceRemoved")
    detail = page_citations.detail(tmp_path, "alpha-place", by_title["Market walk"]["n"], fm=page.frontmatter,
                                   body=page.body, claims=[])
    assert detail["sourceRemoved"] is True


def _ctx(memory):
    return mcp_tools.ToolContext(memory_path=lambda: memory, session_id="s", harness="unknown")


def test_recall_detail_says_which_claims_rest_on_a_removed_source(memory):
    page = memory / "entities" / "alpha-project.md"
    before = page.read_bytes()
    out = str(mcp_tools.recall_detail(_ctx(memory), "alpha-project"))
    tail = next(block for block in out.split("\n\n") if SENTENCE in block)
    assert SENTENCE in tail and "`c-gone`" in tail and f"`{GONE}`" in tail
    assert "c-live" not in tail and LIVE not in tail, "a claim from a source that is still there is not marked"
    assert page.read_bytes() == before


def test_recall_detail_of_a_page_with_no_removed_source_is_unchanged(memory):
    markdown_parser.write(memory / "episodes" / f"{GONE}.md",
                          {"id": GONE, "origin": "folder", "title": "A removed note", "processed": True,
                           "timestamp": "2026-09-01T08:00:00+00:00"}, GONE_TEXT)
    bank_index.invalidate()
    assert "Removed from its source" not in str(mcp_tools.recall_detail(_ctx(memory), "alpha-project"))


def test_cicada_sources_says_it_for_an_episode_and_for_a_page(memory):
    one = str(mcp_tools.sources(_ctx(memory), GONE))
    assert SENTENCE in one, "the existing sentence is the one wording"
    whole = str(mcp_tools.sources(_ctx(memory), "alpha-project"))
    head, _, rest = whole.partition(f"### episode {GONE}")
    gone_block, _, live_block = rest.partition(f"### episode {LIVE}")
    assert SENTENCE in gone_block and SENTENCE not in live_block


def test_the_cli_reads_the_same_line_through_the_same_body(tmp_path):
    from test_cli_unit2 import _env, _work

    mem = _bank(tmp_path, git=False)
    ep = "ep_2026-09-01_001"
    fm = markdown_parser.parse(mem / "episodes" / f"{ep}.md").frontmatter
    markdown_parser.write(mem / "episodes" / f"{ep}.md", dict(fm, source_deleted_at=f"{DAY}T10:00:00+00:00"),
                          "user: plan alpha")
    page = mem / "entities" / "alpha-project.md"
    parsed = markdown_parser.parse(page)
    claim = _claim("c-cli", ep, "user: plan alpha", "plan alpha")
    markdown_parser.write(page, dict(parsed.frontmatter, source_episodes=[ep]), write_claims(parsed.body, [claim]))
    out = envelope(run_cli(["get", "alpha-project", "--json"], _env(tmp_path, mem), cwd=_work(tmp_path)))
    assert out["ok"] is True and SENTENCE in out["text"] and "`c-cli`" in out["text"]
