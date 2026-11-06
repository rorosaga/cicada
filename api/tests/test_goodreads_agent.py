"""ROR-128 (owner 2026-11-06): the person's own agent reads their Goodreads shelves in their own browser; the books wait
for the person's choice and enter like a file's rows. Also Spotify's library as a saved list, whose "never" is lifted.
Synthetic titles and ids only."""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from _reading_fixtures import reading  # noqa: F401 — `reading` is a fixture
from api import config, main
from api.services import bank_index, book_jobs, book_lookup, goodreads_waiting, reading_settings, saved_lists

BOOKS = [
    {"id": "101", "title": "The Lantern Orchard", "author": "Ada Example", "shelf": "read", "rating": "4",
     "date_read": "2026-02-03", "date_added": "2025-12-01", "review": "A slow book."},
    {"id": "102", "title": "Quiet Engines", "author": "Bea Sample", "shelf": "currently-reading",
     "date_added": "2026-10-01"},
    {"id": "103", "title": "Someday Shelf", "author": "Cy Placeholder", "shelf": "to-read", "date_added": "2026-10-05"},
    {"title": "No id so not a book"},
]


def _on(*keys):
    reading_settings.update(saved_lists_={k: True for k in keys})


def _record(server, items=BOOKS, outcome="read", platform="goodreads"):
    args = {"platform": platform, "outcome": outcome}
    if items is not None:
        args["items"] = items
    return server.handle_tool("cicada_record_saved_list", args)


def _episodes(memory):
    return sorted(p.name for p in (memory / "episodes").glob("*.md"))


@pytest.fixture
def client(reading, monkeypatch):  # noqa: F811
    server, memory = reading
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    monkeypatch.setattr(book_jobs, "schedule", lambda *a, **k: None)

    async def offline(url):
        return book_lookup.Response(404, b"")
    monkeypatch.setattr(book_lookup, "default_fetch", offline)
    yield server, memory, TestClient(main.app)
    config.get_settings.cache_clear()


def test_goodreads_is_a_saved_list_off_until_the_person_turns_it_on(reading):
    server, memory = reading
    assert "goodreads" in saved_lists.PLATFORMS and "goodreads" in reading_settings.SAVED_LISTS
    assert "goodreads" not in reading_settings.DEFAULT_ON_SAVED_LISTS
    assert "Not recorded" in _record(server)
    assert saved_lists.due(memory) == []
    _on("goodreads")
    assert saved_lists.due(memory) == ["goodreads"]
    lines = "\n".join(saved_lists.queue_lines(memory, can_record=True))
    assert "goodreads.com/review/list" in lines and "Want to Read" in lines and "never click" in lines
    assert "chooses which books to add" in lines


def test_a_read_holds_the_books_and_writes_nothing_into_the_bank(client):
    server, memory, c = client
    _on("goodreads")
    before = _episodes(memory)
    out = _record(server)
    assert "3 new book(s) wait" in out and "1 row(s) were not books" in out
    assert _episodes(memory) == before
    shown = c.get("/sources/goodreads/waiting").json()["items"]
    assert [b["title"] for b in shown] == ["Quiet Engines", "Someday Shelf", "The Lantern Orchard"]
    assert {"id", "title", "author", "status"} == set(shown[0])
    assert saved_lists.last(memory, "goodreads")["outcome"] == "read"


def test_choosing_stages_the_ticked_books_and_leaves_the_rest_out_for_good(client):
    server, memory, c = client
    _on("goodreads")
    before = len(_episodes(memory))
    _record(server)
    r = c.post("/sources/goodreads/waiting/choose", json={"ids": ["101"]})
    assert r.status_code == 200, r.text
    assert r.json()["books"] == 1 and r.json()["created"] == 1
    assert len(_episodes(memory)) == before + 1
    assert c.get("/sources/goodreads/waiting").json()["items"] == []
    # The two left out are not asked about again, and the one added is already in memory.
    again = _record(server)
    assert "0 new book(s) wait" in again and "3 were already in memory or left out" in again


def test_choosing_none_leaves_every_book_out(client):
    server, memory, c = client
    _on("goodreads")
    before = _episodes(memory)
    _record(server)
    r = c.post("/sources/goodreads/waiting/choose", json={"ids": []})
    assert r.json()["books"] == 0 and _episodes(memory) == before
    assert goodreads_waiting.waiting(memory) == []


def test_a_login_wall_pauses_the_list_and_writes_nothing(client):
    server, memory, _ = client
    _on("goodreads")
    assert "needs the person to sign in" in _record(server, items=None, outcome="needs_login")
    assert saved_lists.paused_until("goodreads") is not None and saved_lists.due(memory) == []
    assert goodreads_waiting.waiting(memory) == []


def test_a_book_from_the_file_and_from_the_agent_are_the_same_episode(client):
    server, memory, c = client
    _on("goodreads")
    _record(server)
    c.post("/sources/goodreads/waiting/choose", json={"ids": ["101"]})
    after_agent = _episodes(memory)
    csv = ("Book Id,Title,Author,My Rating,Date Read,Date Added,Exclusive Shelf,My Review\n"
           "101,The Lantern Orchard,Ada Example,4,2026/02/03,2025/12/01,read,A slow book.\n")
    out = c.post("/sources/goodreads/import", files={"file": ("x.csv", csv.encode())}).json()
    assert out["created"] == 0 and _episodes(memory) == after_agent


# --- Spotify ----------------------------------------------------------------------------------------------------------


def test_spotify_is_a_browser_list_with_the_exports_origin(reading):
    server, memory = reading
    assert "spotify" in saved_lists.PLATFORMS and "spotify" in reading_settings.SAVED_LISTS
    assert saved_lists.canonical("spotify", "https://open.spotify.com/intl-es/track/aaaaaaaaaaaaaaaaaaaaaa?si=x") == (
        "https://open.spotify.com/track/aaaaaaaaaaaaaaaaaaaaaa", ())
    assert saved_lists.canonical("spotify", "https://open.spotify.com/user/someone") is None
    assert saved_lists.canonical("spotify", "https://example.com/track/aaaaaaaaaaaaaaaaaaaaaa") is None
    _on("spotify")
    out = _record(server, platform="spotify", items=[
        {"url": "https://open.spotify.com/playlist/bbbbbbbbbbbbbbbbbbbbbb", "text": "Morning run"},
        {"url": "https://open.spotify.com/user/someone", "text": "not an item"}])
    assert "1 new post(s) saved" in out and "1 row(s) were not Spotify posts" in out
