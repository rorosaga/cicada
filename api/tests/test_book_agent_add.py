"""`cicada_add_book`: an agent adds a book on the person's ask, by the ISBN it found, through the scan's writer.

Synthetic numbers and titles only (the fixtures of ``test_books``)."""
from __future__ import annotations

import urllib.error

import pytest

from api.services import books, markdown_parser, mcp_tools
from api.services.claims import parse_claims
from test_books import PAPERBACK, UNKNOWN, _books, _run, client  # noqa: F401  (fixtures)

AGENT = {"harness": "claude-code", "sessionId": "sess-1"}


def test_preview_shows_the_edition_and_writes_nothing(client):
    c, memory, calls = client
    before = len(list((memory / "episodes").glob("*.md")))
    r = c.post("/sources/books/agent-add", json={"isbn": "978-0-00-000000-2", "preview": True, **AGENT})
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["state"], body["title"], body["authors"]) == ("found", "The Lantern Orchard", ["Ada Example"])
    assert len(list((memory / "episodes").glob("*.md"))) == before and not _books(memory)
    assert all("The Lantern" not in u for u in calls)             # the number is asked, never a title


def test_preview_of_an_unknown_number_says_so(client):
    c, _, _ = client
    assert c.post("/sources/books/agent-add", json={"isbn": UNKNOWN, "preview": True}).json()["state"] == "not_found"


def test_preview_with_the_network_off_does_not_fetch(client, monkeypatch):
    c, _, calls = client
    monkeypatch.setenv("CICADA_ALLOW_CONNECTOR_FETCH", "off")
    assert c.post("/sources/books/agent-add", json={"isbn": PAPERBACK, "preview": True}).json()["state"] == "unavailable"
    assert not calls


def test_an_add_is_a_quiet_save_by_the_harness_with_no_status(client):
    c, memory, _ = client
    body = c.post("/sources/books/agent-add", json={"isbn": PAPERBACK, **AGENT}).json()
    assert body["status"] == "created" and body["book"] == "waiting"
    fm = markdown_parser.parse(memory / "episodes" / f"{body['episodeId']}.md").frontmatter
    assert fm["origin"] == "book-scan" and fm["book"]["by"] == "claude-code" and fm["book"]["status"] is None
    _run(memory)
    [(eid, page)] = _books(memory).items()
    assert not [c_ for c_ in parse_claims(page.body) if c_.predicate == books.STATUS_PREDICATE]
    card = books.book_card(memory, eid)
    assert [w["label"] for w in card["ways"]] == [books.AGENT_WORDS]
    # the person's own scan of it afterwards is a second way in, labelled as theirs
    c.post("/capture/isbn", json={"isbn": PAPERBACK}, headers={"Idempotency-Key": "k"})
    _run(memory)
    assert len(_books(memory)) == 1


def test_a_repeat_changes_nothing_and_a_bad_number_is_refused(client):
    c, _, _ = client
    c.post("/sources/books/agent-add", json={"isbn": PAPERBACK})
    assert c.post("/sources/books/agent-add", json={"isbn": PAPERBACK}).json()["status"] == "unchanged"
    assert c.post("/sources/books/agent-add", json={"isbn": "1234567890123"}).status_code == 422


def test_the_tool_refuses_a_bad_number_and_names_a_missing_backend(client):
    class Ctx:
        harness, session_id, backend_url = "claude-code", "s", "http://127.0.0.1:1"
        def memory_path(self): return client[1]
        def backend_post(self, path, payload): raise urllib.error.URLError("down")
        def backend_headers(self): return {}
        sleep_answer = None
        def sleep_running(self): return False
    assert "not a book's ISBN" in str(mcp_tools.add_book(Ctx(), "12", False))
    assert "not running" in str(mcp_tools.add_book(Ctx(), PAPERBACK, False))
