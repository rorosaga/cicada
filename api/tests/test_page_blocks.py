"""Page blocks (vision item 5, 2026-10-28): what a page holds, for the app and an agent alike.

``fixtures/page_blocks.json`` is the shared wire: this test builds it from a synthetic page and compares, and the app's
``PageBlocksTests.swift`` decodes the same file. Regenerate with ``CICADA_REGEN_FIXTURES=1`` after a deliberate change.
"""
from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.models.schemas import EntityResponse, PageBlocks
from api.services import git_service, markdown_parser, mcp_tools, page_blocks
from api.services.claims import Claim, write_claims
from api.tests import page_citation_fixture as cites

FIXTURE = Path(__file__).parent / "fixtures" / "page_blocks.json"
TODAY = date(2026, 10, 28)


def _claims() -> list[Claim]:
    return [
        Claim(id="c-ongoing", text="Building the alpha-project prototype.", subject="alpha-place",
              predicate="happened", status="ongoing", valid_from="2026-10-01", origin="companion_app"),
        Claim(id="c-planned", text="Open the alpha-project studio.", subject="alpha-place", predicate="milestone",
              status="planned", valid_from="2026-10-02", target="2026-12-01"),
        Claim(id="c-done", text="Visited once.", subject="alpha-place", predicate="happened", status="done",
              valid_from="2026-09-01"),
        Claim(id="c-old", text="Was planning it.", subject="alpha-place", predicate="happened", status="ongoing",
              valid_from="2026-08-01", superseded_by="c-ongoing"),
        Claim(id="c-fact", text="It is in a city.", subject="alpha-place", predicate="located-in", object="beta-city"),
    ]


_FM = {
    "name": "Alpha Place", "type": "location", "status": "active", "confidence": 0.8, "created": "2026-09-01",
    "last_referenced": "2026-10-20", "lat": 40.4168, "lon": -3.7038, "coordinates_by": "geocoder",
    "in_short": {"text": "Alpha Place is where you build the prototype. You go most weeks.", "written_at":
                 "2026-10-27T03:02:00+00:00", "model": "claude-haiku-4-5", "conversations": 6, "article": "abc"},
    "sources": [
        {"ref": "https://example.org/alpha", "kind": "url", "added_by": "user", "added_at": "2026-09-01"},
        {"ref": "https://example.com/alpha", "kind": "url", "added_by": "claude-code", "proposed": True,
         "evidence": {"page": True}},
        {"ref": "https://example.net/alpha", "kind": "url", "added_by": "cicada", "verified": {"at": "2026-10-10",
                                                                                               "how": "read"}},
        {"ref": "https://example.io/alpha", "kind": "url", "added_by": "user",
         "refresh": {"at": "2026-08-01", "outcome": "same"}},
    ],
}
_RELEVANCE = {"tense": "is", "line": "Why it matters to you: you are building something there (since 2026-10-01).",
              "conversations": 2, "lastMentioned": "2026-10-20", "basis": []}
_HISTORY = [
    {"date": "2026-10-20", "author": "claude-haiku-4-5", "author_kind": "model", "author_provider": "anthropic",
     "via": "sleep"},
    {"date": "2026-10-12", "author": "user", "author_kind": "user", "author_provider": None, "via": "app"},
    {"date": "2026-10-02", "author": "claude-haiku-4-5", "author_kind": "model", "author_provider": "anthropic",
     "via": "sleep"},
]


def _build(tmp_path: Path, monkeypatch) -> dict:
    monkeypatch.setattr(page_blocks, "looks", lambda mp, eid: [
        {"id": "2026-10-14-alpha-site", "title": "Alpha site", "site": "example.org", "day": "2026-10-14",
         "palette": ["#112233", "#F4F1EA"], "fonts": ["Inter"], "image": "/design/2026-10-14-alpha-site/image"}])
    # Ruling 48 (16): the article's lines carry their write-time provenance, which the citations number.
    cites.write_episodes(tmp_path)
    fm = dict(_FM, section_provenance=cites.records(cites.BODY, tmp_path))
    return page_blocks.build(tmp_path, "alpha-place", fm=fm, claims=_claims(), relevance=_RELEVANCE,
                             history_entries=_HISTORY, today=TODAY, body=cites.BODY)


def test_the_blocks_match_the_shared_fixture(tmp_path, monkeypatch):
    blocks = _build(tmp_path, monkeypatch)
    PageBlocks(**blocks)   # the wire model accepts it
    if os.environ.get("CICADA_REGEN_FIXTURES"):
        FIXTURE.write_text(json.dumps({"_comment": "Shared by test_page_blocks.py and PageBlocksTests.swift: the "
                                       "`blocks` of GET /entities/{id} (page_blocks.build). Regenerate with "
                                       "CICADA_REGEN_FIXTURES=1.", "blocks": blocks}, indent=2) + "\n")
    assert blocks == json.loads(FIXTURE.read_text())["blocks"]


def test_what_each_block_holds(tmp_path, monkeypatch):
    b = _build(tmp_path, monkeypatch)
    assert b["order"] == ["relevance", "summary", "sources", "coordinates", "looks", "ongoing", "citations", "history"]
    assert b["summary"] == {"text": "Alpha Place is where you build the prototype. You go most weeks.",
                            "writtenAt": "2026-10-27", "by": "sleep", "model": "claude-haiku-4-5", "conversations": 6}
    assert [o["claimId"] for o in b["ongoing"]] == ["c-planned", "c-ongoing"], "open heads only, newest first"
    assert b["ongoing"][1]["verbatim"] is True and b["ongoing"][0]["target"] == "2026-12-01"
    assert b["coordinates"] == {"lat": 40.4168, "lon": -3.7038, "label": "Alpha Place", "source": "page",
                                "by": "geocoder"}
    states = {s["ref"]: s["state"] for s in b["sources"]["items"]}
    assert states == {"https://example.org/alpha": "unchecked", "https://example.com/alpha": "proposed",
                      "https://example.net/alpha": "checked", "https://example.io/alpha": "stale"}
    assert next(s for s in b["sources"]["items"] if s["state"] == "stale")["checkedAt"] == "2026-08-01"
    assert b["sources"]["proposed"] == 1
    assert b["history"]["bySleep"] == 2 and b["history"]["contributors"][0]["author"] == "claude-haiku-4-5"


@pytest.mark.parametrize("fm, has", [({"lat": 91, "lon": 0}, False), ({"lat": "x", "lon": 1}, False),
                                     ({"latitude": "10.5", "longitude": 20}, True), ({"lat": True, "lon": 1}, False),
                                     ({}, False)])
def test_coordinates_are_only_what_the_page_stores(fm, has):
    assert (page_blocks.coordinates(fm) is not None) is has


def test_an_owner_page_and_an_empty_page(tmp_path):
    b = page_blocks.build(tmp_path, "me", fm={"owner": True}, claims=[],
                          relevance={"tense": "self", "line": "This is you."})
    assert b["order"] == [] and b["sources"] is None and b["coordinates"] is None


# ---- history: trigger and via --------------------------------------------------------------------------------------


@pytest.mark.parametrize("trigger, via", [
    ("sleep/extraction", "sleep"), ("inbox/conflict/settled:keep", "sleep"), ("user/companion_app", "app"),
    ("user/calendar_poll", "sync"), ("sync/bookmark_left", "sync"), ("mcp/claude-code", "agent"),
    ("remote/chatgpt", "remote"), ("inbox/decay/resolved:archive", "inbox"), ("migration/inbox", "cicada"),
    ("", "unknown"),
])
def test_history_via(trigger, via):
    assert git_service.history_via(trigger) == via


def test_each_page_reads_its_own_manifest_trigger():
    body = ("entities/alpha.md: updated (source: ep_1, trigger: sleep/extraction, sessions: s1)\n"
            "entities/beta.md: updated (trigger: user/companion_app)\n\nCicada-Author: user\n")
    assert git_service._parse_entity_trigger(body, "alpha") == "sleep/extraction"
    assert git_service._parse_entity_trigger(body, "beta") == "user/companion_app"
    assert git_service._parse_entity_trigger(body, "gamma") == ""


# ---- the route: blocks, ETag, 304 ----------------------------------------------------------------------------------


def _client(tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    markdown_parser.write(memory / "entities" / "alpha-place.md", dict(_FM),
                          write_claims("## Summary\n\nA place.\n", _claims()))
    return TestClient(main.app), memory


def test_the_card_serves_blocks_and_revalidates(tmp_path, monkeypatch):
    client, memory = _client(tmp_path, monkeypatch)
    first = client.get("/entities/alpha-place")
    assert first.status_code == 200
    body = first.json()
    EntityResponse(**body)
    assert body["blocks"]["coordinates"]["lat"] == 40.4168 and "ongoing" in body["blocks"]["order"]
    etag = first.headers["etag"]
    again = client.get("/entities/alpha-place", headers={"If-None-Match": etag})
    assert again.status_code == 304 and again.headers["etag"] == etag
    # A write to the page (atomic, as every bank write is) moves the ETag.
    fm, page_body = dict(_FM, name="Alpha Place Renamed"), markdown_parser.parse(memory / "entities"
                                                                                  / "alpha-place.md").body
    markdown_parser.write(memory / "entities" / "alpha-place.md", fm, page_body)
    changed = client.get("/entities/alpha-place", headers={"If-None-Match": etag})
    assert changed.status_code == 200 and changed.json()["name"] == "Alpha Place Renamed"
    # Another page appearing (a name the relevance line may use) moves it too.
    etag2 = changed.headers["etag"]
    markdown_parser.write(memory / "entities" / "beta-city.md", {"name": "Beta City", "type": "location"}, "x\n")
    assert client.get("/entities/alpha-place", headers={"If-None-Match": etag2}).status_code == 200


def test_the_etag_moves_with_the_day(tmp_path, monkeypatch):
    _, memory = _client(tmp_path, monkeypatch)
    a = page_blocks.card_etag(memory, "alpha-place")

    class Later(date):
        @classmethod
        def today(cls):
            return date(2099, 1, 1)

    monkeypatch.setattr(page_blocks, "date", Later)
    assert page_blocks.card_etag(memory, "alpha-place") != a


# ---- agent parity: cicada_recall_detail include=… -----------------------------------------------------------------


def _ctx(memory, **kw):
    return mcp_tools.ToolContext(memory_path=lambda: memory, session_id="s", harness="unknown", **kw)


def test_recall_detail_unchanged_without_include(tmp_path, monkeypatch):
    _, memory = _client(tmp_path, monkeypatch)
    plain = mcp_tools.recall_detail(_ctx(memory), "alpha-place")
    assert "## Page blocks" not in plain


def test_recall_detail_include_words_the_same_blocks(tmp_path, monkeypatch):
    _, memory = _client(tmp_path, monkeypatch)
    reply = mcp_tools.recall_detail(_ctx(memory), "alpha-place", include=["blocks"])
    assert "## Page blocks" in reply
    assert "- coordinates: 40.4168, -3.7038" in reply and "proposed: https://example.com/alpha" in reply
    assert "milestone planned, planned for 2026-12-01" in reply
    assert reply.data["blocks"]["order"][:3] == ["relevance", "summary", "sources"]
    assert "- in short (written by Sleep, claude-haiku-4-5, 2026-10-27): Alpha Place is where you build" in reply
    only = mcp_tools.recall_detail(_ctx(memory), "alpha-place", include=["coordinates", "looks"])
    assert "- looks: none on this page" in only and "sources:" not in only.split("## Page blocks")[1]


def test_a_remote_connection_gets_no_history_and_no_quoted_words(tmp_path, monkeypatch):
    _, memory = _client(tmp_path, monkeypatch)
    ctx = _ctx(memory, connector_id="c1", raw_excerpts=False)
    reply = mcp_tools.recall_detail(ctx, "alpha-place", include=["blocks", "history"])
    tail = reply.split("## Page blocks")[1]
    assert "history" not in tail
    assert "Building the alpha-project prototype." not in tail and "(in the person's own words)" in tail
    assert page_blocks.wanted(["history"], remote=True) == ()
    # The structured copy /v1 returns as it is carries the same mask, and no history (review of #505).
    data = reply.data["blocks"]
    assert "Building the alpha-project prototype." not in json.dumps(data)
    assert data["history"] is None and "history" not in data["order"]
    assert next(o for o in data["ongoing"] if o["claimId"] == "c-ongoing")["text"] == page_blocks.OWN_WORDS


def test_a_remote_page_over_its_budget_still_masks_the_data(tmp_path, monkeypatch):
    """The review's repro: prose over REMOTE_DETAIL_BUDGET (the digest path), include=["ongoing"]."""
    _, memory = _client(tmp_path, monkeypatch)
    page = memory / "entities" / "alpha-place.md"
    parsed = markdown_parser.parse(page)
    long_prose = "## Summary\n\n" + ("A place with a long article. " * 2000) + "\n"
    markdown_parser.write(page, parsed.frontmatter, write_claims(long_prose, _claims()))
    ctx = _ctx(memory, connector_id="c1", raw_excerpts=False)
    reply = mcp_tools.recall_detail(ctx, "alpha-place", include=["ongoing"])
    assert "Building the alpha-project prototype." not in json.dumps(reply.data)
    assert reply.data["blocks"]["order"] == ["ongoing"]
    assert reply.data["blocks"]["sources"] is None, "only the kinds asked for"
    # A local caller with the person's words keeps them.
    local = mcp_tools.recall_detail(_ctx(memory), "alpha-place", include=["ongoing"])
    assert "Building the alpha-project prototype." in json.dumps(local.data)


def test_the_include_argument_is_in_both_schemas():
    """R12 / G199: the argument the reply describes exists in the schema each door advertises."""
    from _stdio_server import stdio_server

    from api.remote import tools as remote_tools

    server = stdio_server()
    stdio = next(t for t in server.TOOLS if t["name"] == "cicada_recall_detail")["inputSchema"]["properties"]
    assert stdio["include"]["items"]["enum"] == list(page_blocks.INCLUDE)
    remote = remote_tools.REMOTE_TOOLS["cicada_recall_detail"]["inputSchema"]["properties"]
    assert remote["include"]["items"]["enum"] == list(page_blocks.REMOTE_INCLUDE)
