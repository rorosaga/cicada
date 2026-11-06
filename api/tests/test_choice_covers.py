"""G233 / G39: a cover for a row of the book choice list, before any page exists. Invented ISBNs, no network."""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from api import main
from api.services import book_lookup, choice_covers, goodreads_export, media_preview, net_guard, pdf_page

ISBN = "9780000000002"
OTHER = "9781111111113"


def png(width=40, height=30) -> bytes:
    return pdf_page.encode_png(width, height, b"\x80" * (width * 3 * height), width * 3)


class Web:
    def __init__(self, routes):
        self.routes, self.asked = routes, []

    async def __call__(self, url):
        self.asked.append(url)
        got = self.routes.get(url)
        return got if got is not None else media_preview.Fetched(404, b"")


@pytest.fixture(autouse=True)
def _public(monkeypatch):
    monkeypatch.setattr(net_guard, "_resolve_host", lambda host: ["93.184.216.34"])


def run(coro):
    return asyncio.run(coro)


def test_a_number_the_lookup_knows_draws_the_catalogues_cover_and_is_kept_outside_the_bank():
    book_lookup._remember(ISBN, {"found": True, "v": book_lookup.VERSION, "title": "T", "authors": [], "cover_id": 77,
                                 "isbns": [ISBN]}, now=book_lookup._now())
    web = Web({media_preview.COVER_BY_ID.format(id=77): media_preview.Fetched(200, png(), "image/png")})
    got = run(choice_covers.cover_for(ISBN, fetcher=web))
    assert got is not None and got.suffix == ".png" and "choice_covers" in str(got)
    assert run(choice_covers.cover_for(ISBN, fetcher=Web({}))) == got   # kept: the second look asks nobody


def test_no_cover_is_remembered_for_a_day_and_never_a_stand_in():
    book_lookup._remember(ISBN, {"found": False, "v": book_lookup.VERSION}, now=book_lookup._now())
    web = Web({})
    assert run(choice_covers.cover_for(ISBN, fetcher=web)) is None
    assert web.asked == [media_preview.COVER_BY_ISBN.format(isbn=ISBN)]
    again = Web({})
    assert run(choice_covers.cover_for(ISBN, fetcher=again)) is None and again.asked == []


def test_a_row_with_no_valid_number_asks_nobody():
    web = Web({})
    for bad in ("", "12345", "../x", "9780000000003x"):
        assert run(choice_covers.cover_for(bad, fetcher=web)) is None
    assert web.asked == []


def test_with_fetches_off_nothing_is_asked(monkeypatch):
    monkeypatch.setenv("CICADA_ALLOW_LOGO_FETCH", "off")
    assert run(choice_covers.cover_for(OTHER)) is None


def test_the_route_answers_404_for_no_cover(client_ok=None):
    client = TestClient(main.app)
    assert client.get("/sources/books/choice-cover/not-a-number").status_code == 404


def test_the_goodreads_preview_carries_each_rows_number():
    csv = ('Book Id,Title,Author,Additional Authors,ISBN,ISBN13,My Rating,Number of Pages,Year Published,'
           'Date Added,Exclusive Shelf,My Review\n'
           f'1,An Invented Book,A. Writer,,"=""""","=""{ISBN}""",0,100,2001,2026/01/01,to-read,\n')
    items = goodreads_export.preview(csv.encode())["items"]
    assert items and items[0]["isbn"] == ISBN
