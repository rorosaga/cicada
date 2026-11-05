"""ROR-116, G233: one book is one page whichever door it came in by — Apple Books (no ISBN), a scan, Goodreads, either order.

Synthetic placeholders only: invented ISBNs with valid check digits, titles and authors that are no real book's."""
from __future__ import annotations

import json

import pytest

from _synthetic_bank import _bank  # noqa: F401  (the `client` fixture builds on it)
from api.services import book_lookup, books, markdown_parser, quiet_pages
from api.services.claims import HIGHLIGHTED, parse_claims
from test_books import _ab_book, _books, _claims, _hl, _run, client  # noqa: F401  (client: a fixture)


def _isbn(body12: str) -> str:
    total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(body12))
    return body12 + str((10 - total % 10) % 10)


PAPER, HARD, SEQUEL, OTHER_AUTHOR = (_isbn(b) for b in ("978400000000", "978500000000", "978600000000", "978700000000"))

#: Open Library has none of these; Google Books answers with a title and authors and no work id — so the only thing two
#: editions of one work share is their words.
WORKS = {
    PAPER: ("Harbour of Small Lights", ["Wren Example"]),
    HARD: ("Harbour of Small Lights", ["Wren Example"]),
    SEQUEL: ("Harbour of Small Lights: The Second Tide", ["Wren Example"]),
    OTHER_AUTHOR: ("Harbour of Small Lights", ["Quill Sample"]),
}


@pytest.fixture
def shelf(client, monkeypatch):
    c, memory, calls = client

    async def fetch(url):
        for isbn, (title, authors) in WORKS.items():
            if url.endswith(f"/isbn/{isbn}.json"):
                return book_lookup.Response(404)
            if f"isbn:{isbn}" in url:
                return book_lookup.Response(200, json.dumps({"totalItems": 1, "items": [{"volumeInfo": {
                    "title": title, "authors": authors, "publishedDate": "2020-01-01",
                    "industryIdentifiers": [{"type": "ISBN_13", "identifier": isbn}]}}]}).encode())
        return book_lookup.Response(0)

    monkeypatch.setattr(book_lookup, "default_fetch", fetch)
    c.put("/sources/apple-books/settings", json={"enabled": True})
    return c, memory


def _apple(c, *books_):
    r = c.post("/sources/apple-books/sync", json={"books": list(books_)})
    assert r.status_code == 200, r.text
    return r.json()


def _scan(c, memory, isbn, status=None, ident=None):
    body = {"isbn": isbn, **({"status": status} if status else {}), **({"id": ident} if ident else {})}
    r = c.post("/capture/isbn", json=body)
    assert r.status_code == 200, r.text
    _run(memory)
    return r.json()["episodeId"]


def _questions(memory):
    out = []
    for f in sorted((memory / "inbox").glob("*.md")) if (memory / "inbox").is_dir() else []:
        fm = markdown_parser.parse(f).frontmatter
        if fm.get("kind") == "merge_suggestion" and fm.get("status") == "pending":
            out.append(fm)
    return out


# --- the two orders ------------------------------------------------------------------------------------------------


def test_an_apple_books_entry_with_no_isbn_and_a_scan_of_the_same_work_are_one_page_with_its_marks(shelf):
    c, memory = shelf
    _apple(c, _ab_book("A1", "Harbour of Small Lights", "Wren Example", progress=0.4, annotations=[
        _hl("u1", "The lamps were lit in the order the boats came home.", "2026-09-11T08:00:00Z",
            note="Remember this when planning the autumn.")]))
    [(eid, before)] = _books(memory).items()
    marks = [c_.id for c_ in parse_claims(before.body) if c_.predicate == HIGHLIGHTED]
    assert len(marks) == 1 and before.frontmatter["book"]["isbns"] == []

    episode = _scan(c, memory, PAPER, "finished")
    [(eid2, page)] = _books(memory).items()
    assert eid2 == eid                                                      # no second page
    assert page.frontmatter["book"]["isbns"] == [PAPER] and page.frontmatter["book"]["apple_books"] == ["A1"]
    assert PAPER in page.frontmatter["aliases"]
    assert [c_.id for c_ in parse_claims(page.body) if c_.predicate == HIGHLIGHTED] == marks    # its marks stand
    statuses = _claims(page, books.STATUS_PREDICATE)
    assert [s.object for s in statuses if not s.valid_to] == ["finished"] and len(statuses) == 2   # history kept
    assert not quiet_pages.page_is_quiet(memory, eid)
    assert books.ways_in(page.frontmatter) == ["Apple Books", "Scanned"]
    got = c.get(f"/sources/books/scans/{episode}").json()
    assert got == {"state": "added", "entityId": eid, "name": "Harbour of Small Lights", "existing": True}
    assert c.get(f"/entities/{eid}/book-status").json()["ways"] == ["Apple Books", "Scanned"]
    assert not _questions(memory)


def test_a_scan_and_a_later_apple_books_entry_with_the_same_words_are_one_page(shelf):
    c, memory = shelf
    episode = _scan(c, memory, PAPER, "reading")
    [(eid, _)] = _books(memory).items()
    assert c.get(f"/sources/books/scans/{episode}").json()["existing"] is False     # the scan made it
    # Case, spacing and an ampersand-style difference in the author: still exactly the same words.
    _apple(c, _ab_book("A1", "HARBOUR of small lights", "Wren  Example", progress=0.1))
    [(eid2, page)] = _books(memory).items()
    assert eid2 == eid and page.frontmatter["book"]["apple_books"] == ["A1"]
    assert books.ways_in(page.frontmatter) == ["Apple Books", "Scanned"]
    assert [s.object for s in _claims(page, books.STATUS_PREDICATE) if not s.valid_to]       # a status in force


def test_two_editions_of_one_work_with_no_shared_identifier_are_one_page(shelf):
    c, memory = shelf
    _scan(c, memory, PAPER, "want", "e1")
    _scan(c, memory, HARD, "reading", "e2")
    [(_, page)] = _books(memory).items()
    assert set(page.frontmatter["book"]["isbns"]) == {PAPER, HARD}
    assert books.ways_in(page.frontmatter) == ["Scanned"]                    # one way in: nothing to say


def test_a_volume_with_a_longer_title_and_the_same_title_by_another_author_are_other_books(shelf):
    c, memory = shelf
    _scan(c, memory, PAPER, "reading", "e1")
    _scan(c, memory, SEQUEL, "reading", "e2")
    _scan(c, memory, OTHER_AUTHOR, "reading", "e3")
    assert len(_books(memory)) == 3
    assert not _questions(memory)                  # a different author is a different book, not a doubt


# --- when the words are not enough ---------------------------------------------------------------------------------


def test_a_record_with_no_author_beside_a_page_of_that_title_is_asked_about_never_joined(shelf):
    c, memory = shelf
    _scan(c, memory, PAPER, "reading", "e1")
    _apple(c, _ab_book("A1", "Harbour of Small Lights", ""))
    pages = _books(memory)
    assert len(pages) == 2
    [question] = _questions(memory)
    assert {question["entity_id"], question["merge_target_hint"]} == set(pages)


def test_a_title_two_pages_hold_asks_once_for_each_and_joins_neither(shelf):
    c, memory = shelf
    for n, title in enumerate(("Harbour of Small Lights", "Harbour of Small Lights")):
        # two pages from a time before the words joined anything: each made by its own door
        _apple(c, _ab_book(f"X{n}", f"Placeholder {n}", "Wren Example"))
    for f, title in zip(sorted((memory / "entities").glob("placeholder-*.md")), ("Harbour of Small Lights",) * 2):
        parsed = markdown_parser.parse(f)
        fm = dict(parsed.frontmatter)
        fm["name"] = title
        fm["book"] = {**fm["book"], "title": title}
        markdown_parser.write(f, fm, parsed.body)
    from api.services import bank_index
    bank_index.invalidate(memory)
    assert len(_books(memory)) == 2
    _scan(c, memory, PAPER, "reading", "e1")
    pages = _books(memory)
    assert len(pages) == 3                                                    # a third page, joined to neither
    assert len(_questions(memory)) == 2
    new = next(p for eid, p in pages.items() if PAPER in p.frontmatter["book"]["isbns"])
    assert new.frontmatter["book"]["apple_books"] == []


def test_the_old_guarantee_holds_titles_that_only_share_a_head_stay_apart(shelf):
    c, memory = shelf
    _apple(c, _ab_book("A1", "Harbour of Small Lights: The Second Tide", "Wren Example"))
    _scan(c, memory, PAPER, "reading", "e1")
    assert len(_books(memory)) == 2 and not _questions(memory)


# --- the result of an Add ------------------------------------------------------------------------------------------


def test_the_scan_result_waits_then_names_the_page_and_a_stranger_is_a_404(shelf):
    c, memory = shelf
    r = c.post("/capture/isbn", json={"isbn": PAPER, "status": "want"}).json()
    assert c.get(f"/sources/books/scans/{r['episodeId']}").json() == {"state": "waiting"}
    _run(memory)
    got = c.get(f"/sources/books/scans/{r['episodeId']}").json()
    assert got["state"] == "added" and got["existing"] is False and got["name"] == "Harbour of Small Lights"
    assert c.get("/sources/books/scans/ep_2026-01-01_999").status_code == 404


def test_a_page_made_before_the_doors_were_recorded_still_names_its_apple_books_way_in():
    fm = {"book": {"apple_books": ["A1"], "goodreads": ["9"]}}
    assert books.ways_in(fm) == ["Apple Books", "Goodreads"]
    assert books.ways_in({"book": {"doors": ["book-scan"]}}) == ["Scanned"]
    assert books.ways_in({}) == []


def test_words_that_are_the_same_set_aside_only_case_accents_and_punctuation():
    assert books.norm_words("  Café — L’été, & Co.  ") == books.norm_words("cafe l ete and co")
    assert books.author_set(["A. B. Example & C Sample"]) == books.author_set(["a b example", "C. Sample"])
    assert books.title_forms("Title", "A Novel") >= {"title", "title a novel"}
    # A volume number is part of the words, never set aside.
    assert books.norm_words("Berserk (Volume 1)") != books.norm_words("Berserk (Volume 2)")
