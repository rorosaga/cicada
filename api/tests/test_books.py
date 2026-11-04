"""G39 / G233: books — a scanned ISBN, Apple Books, a Goodreads export — staged as episodes and made work pages.

Synthetic placeholders only: invented ISBNs with valid check digits, titles and authors that are no real book's, Open
Library and Google Books answers as fixtures (no network)."""
from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from _synthetic_bank import _bank
from api import config, main
from api.services import (apple_books, auth, bank_index, book_jobs, book_lookup, books, evidence, goodreads_export,
                          markdown_parser, quiet_pages, replica_routes)
from api.services.claims import HAPPENED, parse_claims

# Invented numbers that pass the EAN-13 check: one work in paperback and hardback, and a second work.
PAPERBACK = "9780000000002"
HARDBACK = "9781111111113"
OTHER = "9790000000001"
UNKNOWN = "9782222222224"


def _check(body12: str) -> str:
    total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(body12))
    return body12 + str((10 - total % 10) % 10)


def test_the_fixture_numbers_are_valid():
    for n in (PAPERBACK, HARDBACK, OTHER, UNKNOWN):
        assert _check(n[:12]) == n


EDITION = {"title": "The Lantern Orchard", "authors": [{"key": "/authors/OL1A"}], "works": [{"key": "/works/OL7W"}],
           "publish_date": "March 2019", "number_of_pages": 320, "covers": [1234], "isbn_13": [PAPERBACK]}
EDITION_HB = {**EDITION, "isbn_13": [HARDBACK], "publish_date": "2018"}


def _fake_fetch(calls: list):
    async def fetch(url):
        calls.append(url)
        if url.endswith(f"/isbn/{PAPERBACK}.json"):
            return book_lookup.Response(200, json.dumps(EDITION).encode())
        if url.endswith(f"/isbn/{HARDBACK}.json"):
            return book_lookup.Response(200, json.dumps(EDITION_HB).encode())
        if url.endswith("/authors/OL1A.json"):
            return book_lookup.Response(200, json.dumps({"name": "Ada Example"}).encode())
        if url.endswith(f"/isbn/{OTHER}.json"):
            return book_lookup.Response(404)
        if f"isbn:{OTHER}" in url:
            return book_lookup.Response(200, json.dumps({"totalItems": 1, "items": [{"volumeInfo": {
                "title": "Quiet Engines", "authors": ["Bea Sample"], "publishedDate": "2021-05-01",
                "industryIdentifiers": [{"type": "ISBN_13", "identifier": OTHER}]}}]}).encode())
        if url.endswith(f"/isbn/{UNKNOWN}.json"):
            return book_lookup.Response(404)
        if f"isbn:{UNKNOWN}" in url:
            return book_lookup.Response(200, b'{"totalItems": 0}')
        return book_lookup.Response(0)
    return fetch


class _NoWait(book_lookup._Pacer):
    def __init__(self):
        super().__init__(0)


@pytest.fixture
def client(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    monkeypatch.setenv("CICADA_ALLOW_CONNECTOR_FETCH", "on")
    monkeypatch.setattr(book_jobs, "schedule", lambda *a, **k: None)   # the tests run the job themselves
    monkeypatch.setattr(book_lookup, "_Pacer", lambda *a, **k: _NoWait())
    calls: list[str] = []
    monkeypatch.setattr(book_lookup, "default_fetch", _fake_fetch(calls))
    yield TestClient(main.app), memory, calls
    config.get_settings.cache_clear()


def _run(memory):
    return asyncio.run(book_jobs.resolve_and_apply(memory, author="user", trigger="capture/isbn"))


def _books(memory) -> dict:
    out = {}
    for f in sorted((memory / "entities").glob("*.md")):
        parsed = markdown_parser.parse(f)
        if books.is_book(parsed.frontmatter):
            out[f.stem] = parsed
    return out


def _claims(parsed, predicate):
    return [c for c in parse_claims(parsed.body) if c.predicate == predicate]


# --- ISBNs -------------------------------------------------------------------------------------------------------


def test_isbn13_accepts_an_isbn10_hyphens_and_spreadsheet_quoting_and_refuses_the_rest():
    assert books.isbn13("978-0-00-000000-2") == PAPERBACK
    assert books.isbn13('="9780000000002"') == PAPERBACK
    assert books.isbn13("0000000000") == "9780000000002"           # ISBN-10 → 13
    assert books.isbn13("000000000X") is None                       # wrong check digit
    assert books.isbn10(PAPERBACK) == "0000000000"
    assert books.isbn10(OTHER) is None                              # a 979 has no ISBN-10
    assert books.isbn13("9780000000003") is None                    # check digit off by one
    assert books.isbn13("4006381333931") is None                    # a valid EAN that is not a book's
    assert books.isbn13("12345") is None


# --- a scan ------------------------------------------------------------------------------------------------------


def test_a_scan_is_staged_then_resolved_at_the_home_into_a_work_page_with_its_isbns_as_aliases(client):
    c, memory, calls = client
    r = c.post("/capture/isbn", json={"isbn": "978-0-00-000000-2", "status": "reading"},
               headers={"Idempotency-Key": "scan-1"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["isbn"] == PAPERBACK and body["book"] == "waiting" and body["status"] == "created"
    ep = memory / "episodes" / f"{body['episodeId']}.md"
    fm = markdown_parser.parse(ep).frontmatter
    assert (fm["origin"], fm["processed"], fm["processed_by"]) == ("book-scan", True, "parser")
    assert fm["book"]["isbn"] == PAPERBACK and fm["book"]["status"] == "reading"
    assert not _books(memory)                                       # no page before the lookup

    report = _run(memory)
    assert report["lookup"]["found"] == 1 and report["apply"]["pages_created"] == 1
    [(eid, page)] = _books(memory).items()
    assert eid == "the-lantern-orchard"
    fm = page.frontmatter
    assert fm["type"] == "media" and fm["media"]["kind"] == "book"
    assert fm["book"]["work_id"] == "OL7W" and fm["book"]["authors"] == ["Ada Example"]
    assert PAPERBACK in fm["aliases"] and "0000000000" in fm["aliases"]
    [status] = _claims(page, books.STATUS_PREDICATE)
    assert (status.object, status.valid_to, status.evidence[0].kind) == ("reading", None, "user")
    [started] = _claims(page, HAPPENED)
    assert (started.status, started.object) == ("ongoing", "started reading")
    # The person acted: the page is lit, and the episode is applied as it stands.
    assert not quiet_pages.page_is_quiet(memory, eid)
    stamped = markdown_parser.parse(ep).frontmatter
    assert stamped[books.APPLIED_KEY] == stamped["content_hash"] and books.SAVE_KEY not in stamped
    assert not books.pending(memory)
    # The User-Agent names no person; Open Library was asked once for the edition and once for its author.
    assert "@" not in book_lookup.USER_AGENT
    assert [u.rsplit("/", 1)[-1] for u in calls] == [f"{PAPERBACK}.json", "OL1A.json"]


def test_a_resend_with_the_same_key_is_one_scan(client):
    c, memory, _ = client
    first = c.post("/capture/isbn", json={"isbn": PAPERBACK}, headers={"Idempotency-Key": "k-1"}).json()
    again = c.post("/capture/isbn", json={"isbn": PAPERBACK}, headers={"Idempotency-Key": "k-1"}).json()
    assert first == again
    assert len([p for p in (memory / "episodes").glob("*.md")
                if markdown_parser.parse(p).frontmatter.get("origin") == "book-scan"]) == 1


def test_a_number_that_is_not_a_books_is_refused_and_nothing_is_written(client):
    c, memory, _ = client
    before = sorted(p.name for p in (memory / "episodes").glob("*.md"))
    r = c.post("/capture/isbn", json={"isbn": "4006381333931", "status": "want"})
    assert r.status_code == 422
    assert sorted(p.name for p in (memory / "episodes").glob("*.md")) == before


def test_with_fetches_off_a_scan_waits_and_lands_once_they_are_on(client, monkeypatch):
    c, memory, calls = client
    c.post("/capture/isbn", json={"isbn": PAPERBACK, "status": "finished"})
    monkeypatch.setenv("CICADA_ALLOW_CONNECTOR_FETCH", "off")
    report = _run(memory)
    assert "lookup" not in report and report["apply"]["waiting"] == 1 and calls == []
    assert len(books.pending(memory)) == 1 and not _books(memory)
    monkeypatch.setenv("CICADA_ALLOW_CONNECTOR_FETCH", "on")
    report = _run(memory)
    assert report["apply"]["pages_created"] == 1 and not books.pending(memory)
    [page] = _books(memory).values()
    [done] = _claims(page, HAPPENED)
    assert done.status == "done" and done.object == "finished reading"


def test_a_want_to_read_scan_is_a_quiet_save_and_a_later_reading_scan_lights_the_same_page(client):
    c, memory, _ = client
    c.post("/capture/isbn", json={"isbn": PAPERBACK, "status": "want", "id": "s1"})
    _run(memory)
    [(eid, page)] = _books(memory).items()
    assert quiet_pages.page_is_quiet(memory, eid)
    assert not _claims(page, HAPPENED)                               # wanting a book is not a happening
    [want] = _claims(page, books.STATUS_PREDICATE)
    assert want.evidence[0].kind == "page"
    # Another edition of the same work, scanned as reading: one page, both numbers, the status moves on.
    c.post("/capture/isbn", json={"isbn": HARDBACK, "status": "reading", "id": "s2"})
    _run(memory)
    [(eid2, page)] = _books(memory).items()
    assert eid2 == eid and {PAPERBACK, HARDBACK} <= set(page.frontmatter["book"]["isbns"])
    statuses = sorted(_claims(page, books.STATUS_PREDICATE), key=lambda c: c.object)
    assert [(s.object, bool(s.valid_to)) for s in statuses] == [("reading", False), ("want", True)]
    assert not quiet_pages.page_is_quiet(memory, eid)


def test_a_definite_miss_makes_a_placeholder_page_that_a_later_answer_upgrades(client, monkeypatch):
    c, memory, _ = client
    c.post("/capture/isbn", json={"isbn": UNKNOWN, "status": "reading"})
    report = _run(memory)
    assert report["lookup"]["missing"] == 1
    [(eid, page)] = _books(memory).items()
    assert page.frontmatter["name"] == f"Book with ISBN {UNKNOWN}"
    assert page.frontmatter["book"]["title_from"] == "placeholder"
    # The number is asked again once its wait is over, and the page takes the title in place.
    monkeypatch.setattr(book_lookup, "due", lambda isbn, now=None: True)

    async def found(url):
        if url.endswith(f"/isbn/{UNKNOWN}.json"):
            return book_lookup.Response(200, json.dumps({**EDITION, "title": "Late Answer", "works": []}).encode())
        if url.endswith("/authors/OL1A.json"):
            return book_lookup.Response(200, b'{"name": "Ada Example"}')
        return book_lookup.Response(0)

    monkeypatch.setattr(book_lookup, "default_fetch", found)
    _run(memory)
    [(eid2, page)] = _books(memory).items()
    assert eid2 == eid and page.frontmatter["name"] == "Late Answer"
    assert page.frontmatter["book"]["title_from"] == "openlibrary"


def test_a_transient_failure_backs_off_and_is_never_a_page(client, monkeypatch):
    c, memory, _ = client

    async def down(url):
        return book_lookup.Response(503)

    monkeypatch.setattr(book_lookup, "default_fetch", down)
    c.post("/capture/isbn", json={"isbn": PAPERBACK})
    report = _run(memory)
    assert report["lookup"]["failed"] == 1 and not _books(memory)
    assert not book_lookup.due(PAPERBACK)                            # waits before asking again
    assert book_lookup.cached(PAPERBACK) is None


def test_google_books_answers_when_open_library_has_no_edition(client):
    c, memory, calls = client
    c.post("/capture/isbn", json={"isbn": OTHER, "status": "finished"})
    _run(memory)
    [page] = _books(memory).values()
    assert page.frontmatter["name"] == "Quiet Engines"
    assert page.frontmatter["book"]["title_from"] == "googlebooks"
    assert any("googleapis.com" in u for u in calls)


def test_the_capture_route_is_a_phones_and_waits_in_a_replicas_outbox():
    assert ("POST", "/capture/isbn") in auth.CAPTURE_ROUTES
    assert replica_routes.ROUTES["POST /capture/isbn"] == replica_routes.CAPTURE
    assert replica_routes.ROUTES["POST /sources/apple-books/sync"] == replica_routes.CAPTURE


# --- Apple Books ---------------------------------------------------------------------------------------------------


def _ab_book(asset, title, author, *, finished=False, progress=0.0, annotations=(), epub=None, **kw):
    return {"assetId": asset, "title": title, "author": author, "isFinished": finished, "progress": progress,
            "epubId": epub, "contentType": 1, "addedAt": "2026-03-01T10:00:00Z", "lastOpenedAt": "2026-09-10T20:00:00Z",
            "finishedAt": "2026-09-12T21:00:00Z" if finished else None, "annotations": list(annotations), **kw}


def _hl(uuid, text, when, note=None):
    return {"uuid": uuid, "createdAt": when, "selectedText": text, "note": note}


def test_apple_books_is_refused_until_the_person_turns_it_on(client):
    c, _, _ = client
    r = c.post("/sources/apple-books/sync", json={"books": [_ab_book("A1", "Some Title", "Some Author")]})
    assert r.status_code == 409


def test_apple_books_library_status_highlights_and_notes(client):
    c, memory, calls = client
    assert c.put("/sources/apple-books/settings", json={"enabled": True}).json() == {"enabled": True}
    payload = {"books": [
        _ab_book("A1", "The Lantern Orchard", "Ada Example", finished=True, epub=f"urn:isbn:{PAPERBACK}",
                 annotations=[_hl("u1", "Every orchard keeps a lantern for the last walker.", "2026-09-11T08:00:00Z",
                                  note="This is how I want the ending of my own story to feel.")]),
        _ab_book("A2", "Quiet Engines", "Bea Sample", progress=0.35),
        _ab_book("A3", "Unopened Atlas", "Cy Placeholder"),
        _ab_book("A4", "Hidden One", "Nobody", isHidden=True),
    ]}
    r = c.post("/sources/apple-books/sync", json=payload)
    assert r.status_code == 200, r.text
    out = r.json()
    assert (out["books"], out["created"], out["highlights"], out["notes"], out["queued"], out["pages"]) == (
        3, 3, 1, 1, 1, 3)
    assert calls == []                                               # a library needs no lookup
    pages = _books(memory)
    status = {eid: [s.object for s in _claims(p, books.STATUS_PREDICATE) if not s.valid_to] for eid, p in pages.items()}
    assert status == {"the-lantern-orchard": ["finished"], "quiet-engines": ["reading"],
                      "unopened-atlas": ["not_started"]}
    assert not _claims(pages["unopened-atlas"], HAPPENED)            # never opened is not a happening
    # Imports are quiet until the person writes or talks about the book.
    assert all(quiet_pages.page_is_quiet(memory, eid) for eid in pages)
    # The book with a highlight is queued for Sleep; the others landed read.
    eps = {markdown_parser.parse(p).frontmatter.get("source_id"): p for p in (memory / "episodes").glob("*.md")}
    hl = markdown_parser.parse(eps["apple-books:A1"])
    assert hl.frontmatter["processed"] is False and hl.frontmatter["timestamp"].startswith("2026-09-11")
    assert markdown_parser.parse(eps["apple-books:A3"]).frontmatter["processed_by"] == "index"
    # A highlight is the book's words, the note the person's.
    words_of = evidence.speaker_kind
    text = hl.body
    assert words_of(text, text.index("Every orchard"), saved=True) == "page"
    assert words_of(text, text.index("This is how I want"), saved=True) == "user"

    # A new highlight edits the same episode in place, appended after the first.
    payload["books"][0]["annotations"].append(_hl("u2", "Walk slowly where the roots are.", "2026-09-12T08:00:00Z"))
    out = c.post("/sources/apple-books/sync", json=payload).json()
    assert (out["created"], out["updated"], out["unchanged"]) == (0, 1, 2)
    again = markdown_parser.parse(eps["apple-books:A1"])
    assert again.body.index("Every orchard") < again.body.index("Walk slowly")
    assert again.frontmatter["revised"]["count"] == 1 and again.frontmatter["processed"] is False
    assert len(_books(memory)) == 3


def test_an_apple_books_copy_and_a_scanned_paperback_are_one_page(client):
    c, memory, _ = client
    c.post("/capture/isbn", json={"isbn": PAPERBACK})              # a scan with no tap says nothing about reading
    _run(memory)
    [page] = _books(memory).values()
    assert not _claims(page, books.STATUS_PREDICATE)
    c.put("/sources/apple-books/settings", json={"enabled": True})
    c.post("/sources/apple-books/sync", json={"books": [_ab_book("A9", "The Lantern Orchard: A Novel", "Ada Example",
                                                                    finished=True)]})
    [(eid, page)] = _books(memory).items()
    assert page.frontmatter["book"]["apple_books"] == ["A9"]
    assert "The Lantern Orchard: A Novel" in page.frontmatter["aliases"]      # the source's own spelling
    assert [s.object for s in _claims(page, books.STATUS_PREDICATE) if not s.valid_to] == ["finished"]
    finished = [h for h in _claims(page, HAPPENED) if h.status == "done"]
    assert finished and not [h for h in _claims(page, HAPPENED) if h.status == "ongoing" and not h.valid_to]


# --- Goodreads -----------------------------------------------------------------------------------------------------

CSV = (
    "Book Id,Title,Author,Author l-f,Additional Authors,ISBN,ISBN13,My Rating,Average Rating,Publisher,Binding,"
    "Number of Pages,Year Published,Original Publication Year,Date Read,Date Added,Bookshelves,"
    "Bookshelves with positions,Exclusive Shelf,My Review,Spoiler,Private Notes,Read Count,Owned Copies\n"
    f'101,The Lantern Orchard,Ada Example,"Example, Ada",,"=""0000000000""","=""{PAPERBACK}""",4,3.9,Pub,Paperback,'
    '320,2019,2019,2026/02/03,2025/12/01,"favorites, read","favorites (#1), read (#9)",read,'
    '"A slow book.<br/>I kept thinking about the orchard.",,,1,0\n'
    '102,Quiet Engines (Engines #1),Bea Sample,"Sample, Bea",,"=""""","=""""",0,4.1,Pub,Hardcover,200,2021,2021,,'
    '2026/10/01,currently-reading,currently-reading (#1),currently-reading,,,,0,0\n'
    '103,Someday Shelf,Cy Placeholder,"Placeholder, Cy",,"=""""","=""""",0,3.0,Pub,Ebook,100,2020,2020,,'
    '2026/10/05,to-read,to-read (#3),to-read,,,,0,0\n'
)


def test_goodreads_preview_counts_and_writes_nothing(client):
    c, memory, _ = client
    before = sorted(p.name for p in (memory / "episodes").glob("*.md"))
    r = c.post("/sources/goodreads/preview", files={"file": ("goodreads_library_export.csv", CSV.encode())})
    assert r.status_code == 200, r.text
    assert {k: r.json()[k] for k in ("books", "finished", "reading", "want", "reviews", "rated")} == {
        "books": 3, "finished": 1, "reading": 1, "want": 1, "reviews": 1, "rated": 1}
    assert sorted(p.name for p in (memory / "episodes").glob("*.md")) == before


def test_goodreads_import_maps_shelves_ratings_and_reviews_onto_the_same_pages(client):
    c, memory, _ = client
    c.post("/capture/isbn", json={"isbn": PAPERBACK, "status": "reading"})
    _run(memory)
    r = c.post("/sources/goodreads/import", files={"file": ("goodreads_library_export.csv", CSV.encode())})
    assert r.status_code == 200, r.text
    assert (r.json()["books"], r.json()["queued"]) == (3, 1)
    pages = _books(memory)
    assert set(pages) == {"the-lantern-orchard", "quiet-engines", "someday-shelf"}
    lantern = pages["the-lantern-orchard"]
    assert lantern.frontmatter["book"]["goodreads"] == ["101"]
    # The finish on Goodreads (2026-02-03) is older than today's scan as reading: reading stays the open status.
    open_status = [s for s in _claims(lantern, books.STATUS_PREDICATE) if not s.valid_to]
    assert [s.object for s in open_status] == ["reading"]
    [rated] = _claims(lantern, books.RATING_PREDICATE)
    assert rated.object == "4/5" and rated.valid_from == "2026-02-03"
    want = pages["someday-shelf"]
    assert [s.object for s in _claims(want, books.STATUS_PREDICATE)] == ["want"]
    assert quiet_pages.page_is_quiet(memory, "someday-shelf")
    # Only the row with the person's review is read by Sleep; its review is their words.
    eps = {markdown_parser.parse(p).frontmatter.get("source_id"): markdown_parser.parse(p)
           for p in (memory / "episodes").glob("*.md")}
    review = eps["goodreads:101"]
    assert review.frontmatter["processed"] is False
    assert evidence.speaker_kind(review.body, review.body.index("A slow book"), saved=True) == "user"
    assert eps["goodreads:103"].frontmatter["processed_by"] == "index"
    # A re-import changes nothing.
    again = c.post("/sources/goodreads/import", files={"file": ("x.csv", CSV.encode())}).json()
    assert (again["created"], again["updated"], again["unchanged"]) == (0, 0, 3)


def test_a_file_that_is_not_a_goodreads_export_is_refused(client):
    c, _, _ = client
    r = c.post("/sources/goodreads/import", files={"file": ("x.csv", b"Name,Url\nA,https://example.com\n")})
    assert r.status_code == 422


def test_the_summary_counts_books_by_status(client):
    c, memory, _ = client
    c.post("/sources/goodreads/import", files={"file": ("x.csv", CSV.encode())})
    s = c.get("/sources/books").json()
    assert (s["books"], s["finished"], s["reading"], s["want"], s["waiting"]) == (3, 1, 1, 1, 0)


def test_goodreads_drafts_never_carry_columns_outside_the_whitelist():
    import csv
    import io
    from datetime import datetime, timezone

    row = next(csv.DictReader(io.StringIO(CSV)))
    draft = goodreads_export.draft_for(row, now=datetime.now(timezone.utc))
    assert "3.9" not in draft.body and "Paperback" not in draft.body and "Pub" not in draft.body


def test_apple_books_status_follows_its_own_state_and_never_invents_progress():
    assert apple_books.status_of({"isFinished": True, "finishedAt": "2026-01-02T00:00:00Z"})[0] == books.FINISHED
    assert apple_books.status_of({"progress": 0.01})[0] == books.READING
    assert apple_books.status_of({"progress": 0, "lastOpenedAt": "2026-01-02T00:00:00Z"})[0] == books.NOT_STARTED
    assert apple_books.isbn_of(f"urn:isbn:{PAPERBACK}") == PAPERBACK
    assert apple_books.isbn_of("3A1B2C3D-EPUB-UUID") is None
