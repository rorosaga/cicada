"""The article carries the beliefs (ruling 48 (16), DR-80): citation markers numbered from the page's write-time line
provenance, the lazy popover, belief sentences on a page whose prose cites nothing yet, and the agent door."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import markdown_parser, mcp_tools, page_citations
from api.services.claims import Claim, served_prose, write_claims
from api.tests import page_citation_fixture as cites

FM = {"name": "Alpha Place", "type": "location"}


def _page(memory, body=cites.BODY, claims=(), **fm):
    (memory / "entities").mkdir(parents=True, exist_ok=True)
    cites.write_episodes(memory)
    front = dict(FM, section_provenance=cites.records(cites.BODY, memory), **fm)
    markdown_parser.write(memory / "entities" / "alpha-place.md", front, write_claims(body, list(claims)))
    return markdown_parser.parse(memory / "entities" / "alpha-place.md", ledger=False)


def _block(memory, parsed, claims=()):
    return page_citations.block(memory, "alpha-place", fm=parsed.frontmatter, body=parsed.body, claims=list(claims))


def test_each_cited_line_ends_with_its_markers_and_sources_are_numbered_in_reading_order(tmp_path):
    parsed = _page(tmp_path)
    block = _block(tmp_path, parsed)
    served = served_prose(parsed.body)[0]
    ends = [served[:at].rstrip().rsplit("\n", 1)[-1] for at, *_ in block["markers"]]
    assert ends == ["Alpha Place is where the alpha-project studio is being built. It opens in December.",
                    "It sits next to Beta City's old market.", "- It is in Beta City.", "- Open on Saturdays."]
    assert [m[1:] for m in block["markers"]] == [[1], [2], [2], [3]], "one conversation is one reference"
    assert [(r["n"], r["kind"], r["title"]) for r in block["refs"]] == [
        (1, "conversation", "Studio plan"), (2, "conversation", "Market walk"), (3, "web", "Opening hours")]
    first = block["refs"][0]
    assert first["first"].startswith("2026-10-01") and first["last"].startswith("2026-10-05")
    assert (block["total"], block["conversations"], block["web"], block["pages"]) == (3, 2, 1, 0)
    assert block["beliefs"] == [], "a page whose prose cites draws no belief sentences"


def test_an_edited_line_loses_its_marker_rather_than_being_recertified(tmp_path):
    parsed = _page(tmp_path, body=cites.BODY.replace("It opens in December.", "It opened in May."))
    block = _block(tmp_path, parsed)
    assert [m[1:] for m in block["markers"]] == [[1], [1], [2]], "the edited paragraph is uncited"


def test_the_popover_reads_the_located_words_lazily(tmp_path):
    parsed = _page(tmp_path)
    block = _block(tmp_path, parsed)
    at = block["markers"][0][0]
    detail = page_citations.detail(tmp_path, "alpha-place", 1, at=at, fm=parsed.frontmatter, body=parsed.body,
                                   claims=[])
    assert detail["evidenceKind"] == "user" and detail["status"] == "current"
    span = detail["span"]
    excerpt = span["excerpt"]
    assert cites.SAID in excerpt and span["episode"] == cites.EP_SAID
    assert detail["lines"] == 1
    # A reasoning-only source names its conversation without a quote.
    other = page_citations.detail(tmp_path, "alpha-place", 2, at=None, fm=parsed.frontmatter, body=parsed.body,
                                  claims=[])
    assert other["evidenceKind"] == "reasoning" and other["span"] is None and other["lines"] == 2
    assert page_citations.detail(tmp_path, "alpha-place", 9, fm=parsed.frontmatter, body=parsed.body,
                                 claims=[]) is None


def test_a_marker_from_before_a_renumbering_never_shows_another_source(tmp_path):
    """Review of #517: the card drew `2` at 188 (paragraph 2); paragraph 1 was then edited, so 1 left and 2 became the
    looked-up page. The old marker must not open that page's details."""
    parsed = _page(tmp_path)
    old = _block(tmp_path, parsed)
    assert [188, 2] in old["markers"]
    parsed = _page(tmp_path, body=cites.BODY.replace("It opens in December.", "It opened in May."))
    with pytest.raises(page_citations.StaleMarker):
        page_citations.detail(tmp_path, "alpha-place", 2, at=188, fm=parsed.frontmatter, body=parsed.body, claims=[])
    with pytest.raises(page_citations.StaleMarker):
        page_citations.detail(tmp_path, "alpha-place", 1, claim_id="c-gone", fm=parsed.frontmatter,
                              body=parsed.body, claims=[])


def test_a_page_whose_prose_cites_nothing_shows_its_beliefs_as_sentences(tmp_path):
    claims = [
        Claim(id="c-now", text="Alpha Place is in Beta City.", subject="alpha-place", predicate="located-in",
              object="beta-city", source_episodes=[cites.EP_OTHER]),
        Claim(id="c-was", text="Alpha Place was a warehouse.", subject="alpha-place", predicate="was",
              valid_to="2025-03-01", source_episodes=[cites.EP_SAID]),
        Claim(id="c-guess", text="Alpha Place seems busy on weekends.", subject="alpha-place", predicate="is",
              epistemic="inductive", source_episodes=[cites.EP_OTHER]),
        Claim(id="c-gone", text="Replaced.", subject="alpha-place", predicate="is", superseded_by="c-now"),
    ]
    (tmp_path / "entities").mkdir(parents=True)
    cites.write_episodes(tmp_path)
    markdown_parser.write(tmp_path / "entities" / "alpha-place.md", dict(FM), write_claims("## Summary\n\nA place.\n",
                                                                                           claims))
    parsed = markdown_parser.parse(tmp_path / "entities" / "alpha-place.md", ledger=False)
    block = _block(tmp_path, parsed, claims)
    assert block["markers"] == []
    rows = {b["claimId"]: b for b in block["beliefs"]}
    assert set(rows) == {"c-now", "c-was", "c-guess"}, "superseded beliefs are history, not sentences"
    assert rows["c-was"]["until"] == "2025-03-01" and rows["c-guess"]["inferred"] is True
    assert rows["c-now"]["refs"] == [rows["c-guess"]["refs"][0]]
    detail = page_citations.detail(tmp_path, "alpha-place", rows["c-was"]["refs"][0], claim_id="c-was",
                                   fm=parsed.frontmatter, body=parsed.body, claims=claims)
    assert detail["title"] == "Studio plan"
    assert page_citations.belief_words(rows["c-guess"]).startswith("(inferred) ")
    assert "(until 2025-03-01)" in page_citations.belief_words(rows["c-was"])


def test_the_numbering_is_cached_per_page_and_renumbered_when_it_changes(tmp_path, monkeypatch):
    parsed = _page(tmp_path)
    _block(tmp_path, parsed)
    calls = []
    real = page_citations.section_provenance.scan
    monkeypatch.setattr(page_citations.section_provenance, "scan", lambda body: calls.append(1) or real(body))
    _block(tmp_path, parsed)
    assert calls == [], "a held page is a lookup"
    parsed = _page(tmp_path, body=cites.BODY + "\n- Has a garden.\n")
    _block(tmp_path, parsed)
    assert calls, "a written page is renumbered"


def test_a_remote_caller_without_sources_sees_no_titles_or_own_words():
    block = {"refs": [{"n": 1, "kind": "conversation", "title": "Studio plan"},
                      {"n": 2, "kind": "web", "title": "Opening hours"}],
             "beliefs": [{"claimId": "c", "text": "My words.", "verbatim": True, "refs": [1]}]}
    masked = page_citations.for_caller(block, verbatim=False)
    assert "Studio plan" not in json.dumps(masked) and "My words." not in json.dumps(masked)
    assert masked["refs"][1]["title"] == "Opening hours", "a looked-up page is no one's words"
    assert page_citations.for_caller(block, verbatim=True) is block


def _client(tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    _page(memory)
    return TestClient(main.app), memory


def test_the_card_carries_the_markers_and_the_popover_is_its_own_read(tmp_path, monkeypatch):
    client, memory = _client(tmp_path, monkeypatch)
    card = client.get("/entities/alpha-place").json()
    block = card["blocks"]["citations"]
    assert "citations" in card["blocks"]["order"] and block["total"] == 3
    served = card["markdownContent"]
    assert served[:block["markers"][0][0]].endswith("It opens in December."), "offsets are the served prose's"
    at = block["markers"][0][0]
    pop = client.get(f"/entities/alpha-place/citations/1?at={at}")
    assert pop.status_code == 200 and pop.json()["evidenceKind"] == "user"
    assert cites.SAID in pop.json()["span"]["excerpt"]
    assert client.get("/entities/alpha-place/citations/7").status_code == 404
    assert client.get("/entities/alpha-place/citations/3?at=1").status_code == 409, "no line ends there"
    assert client.get("/entities/nowhere/citations/1").status_code == 404


def test_an_agent_reads_the_same_citations(tmp_path, monkeypatch):
    _, memory = _client(tmp_path, monkeypatch)
    ctx = mcp_tools.ToolContext(memory_path=lambda: memory, session_id="s", harness="unknown")
    reply = mcp_tools.recall_detail(ctx, "alpha-place", include=["citations"])
    tail = reply.split("## Page blocks")[1]
    assert "- citations: 3 sources (2 conversations, 1 looked up, 0 pages), 4 cited lines" in tail
    assert '[1] conversation "Studio plan" (claude-code, 2026-10-01 – 2026-10-05)' in tail
    assert reply.data["blocks"]["citations"]["markers"][0][1:] == [1]
    remote = mcp_tools.recall_detail(mcp_tools.ToolContext(memory_path=lambda: memory, session_id="s",
                                                           harness="unknown", connector_id="c1", raw_excerpts=False),
                                     "alpha-place", include=["citations"])
    assert "Studio plan" not in json.dumps(remote.data) and "Studio plan" not in str(remote)
    # Review of #517: /v1 returns `data` as it is — no session id, episode id or chat partner's name without `sources`.
    refs = remote.data["blocks"]["citations"]["refs"]
    assert refs and all(r["conversationId"] is None and r["episodeId"] is None and r["correspondent"] is None
                        for r in refs)
    dumped = json.dumps(remote.data)
    assert "verify-" not in dumped and "sess-a" not in dumped and "Bob Example" not in dumped
    assert cites.EP_SAID not in dumped and cites.EP_OTHER not in dumped
