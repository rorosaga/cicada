"""A title finds the book (ruling 61, amended 2026-11-06): only a confident match, only for a book the person added, marked
and undoable. Open Library answers are fixtures (no network)."""
from __future__ import annotations

import asyncio
import json
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from _synthetic_bank import _bank
from api import config, main
from api.services import bank_index, book_jobs, book_lookup, books, markdown_parser
from test_books import _NoWait, _ab_book, _books, _run

ISBN = "9780000000002"
OTHER_ISBN = "9781111111113"
WORK = {"description": {"value": "A quiet novel about engines that learn to wait."}}


def _doc(key, title, authors, isbns=(ISBN,), subtitle=None, editions=None):
    doc = {"key": f"/works/{key}", "title": title, "subtitle": subtitle, "author_name": authors, "isbn": list(isbns)}
    if editions is not None:
        doc["edition_count"] = editions
    return doc


def _fetch(docs, calls):
    async def fetch(url):
        calls.append(url)
        if "/search.json" in url:
            return book_lookup.Response(200, json.dumps({"docs": docs}).encode())
        if url.endswith(f"/isbn/{ISBN}.json"):
            return book_lookup.Response(200, json.dumps({"title": "Quiet Engines", "works": [{"key": "/works/OL9W"}],
                                                         "authors": [], "isbn_13": [ISBN], "number_of_pages": 210,
                                                         "publish_date": "2021"}).encode())
        if url.endswith("/works/OL9W.json"):
            return book_lookup.Response(200, json.dumps(WORK).encode())
        return book_lookup.Response(404)
    return fetch


@pytest.fixture
def env(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    monkeypatch.setenv("CICADA_ALLOW_CONNECTOR_FETCH", "on")
    monkeypatch.setattr(book_jobs, "schedule", lambda *a, **k: None)
    monkeypatch.setattr(book_lookup, "_shared_pacer", lambda: _NoWait())
    calls: list[str] = []
    docs: list[dict] = []
    monkeypatch.setattr(book_lookup, "default_fetch", _fetch(docs, calls))
    c = TestClient(main.app)
    assert c.put("/sources/apple-books/settings", json={"enabled": True}).status_code == 200
    yield c, memory, calls, docs
    config.get_settings.cache_clear()


def _sync(c, *entries):
    assert c.post("/sources/apple-books/sync", json={"books": list(entries)}).status_code == 200


def test_a_confident_title_and_author_give_the_book_its_description_marked_as_a_title_match(env):
    c, memory, calls, docs = env
    docs += [_doc("OL9W", "Quiet Engines!", ["Bea Sample", "Cy Extra"])]
    _sync(c, _ab_book("A2", "Quiet Engines", "Bea Sample"))
    _run(memory)
    page = _books(memory)["quiet-engines"]
    book = page.frontmatter["book"]
    assert book["title_match"]["isbn"] == ISBN and book["isbns"] == [] and book["pages"] == 210
    assert "engines that learn to wait" in page.body and "Open Library" in page.body
    search = [u for u in calls if "/search.json" in u]
    assert len(search) == 1
    q = parse_qs(urlparse(search[0]).query)
    assert q["title"] == ["Quiet Engines"] and q["author"] == ["Bea Sample"]          # the title and one author, nothing else
    card = c.get("/entities/quiet-engines/book").json()
    assert card["matchedByTitle"] is True and "engines that learn to wait" in card["description"]
    _run(memory)
    assert len([u for u in calls if "/search.json" in u]) == 1                       # asked once, cached


@pytest.mark.parametrize("docs_in,why", [
    ([_doc("OL9W", "Quiet Engines Revisited", ["Bea Sample"])], "none"),             # not the same title
    ([_doc("OL9W", "Quiet Engines", ["Someone Else"])], "none"),                     # another author
    ([_doc("OL9W", "Quiet Engines", ["Bea Sample"]), _doc("OL8W", "Quiet Engines", ["Bea Sample"])], "ambiguous"),
    ([_doc("OL9W", "Quiet Engines", ["Bea Sample"], isbns=())], "no_isbn"),
])
def test_anything_less_than_a_confident_match_leaves_the_book_without_a_description(env, docs_in, why):
    c, memory, calls, docs = env
    docs += docs_in
    _sync(c, _ab_book("A2", "Quiet Engines", "Bea Sample"))
    _run(memory)
    page = _books(memory)["quiet-engines"]
    assert "title_match" not in page.frontmatter["book"] and "description_at" not in page.frontmatter["book"]
    entry = book_lookup.cached(book_lookup.title_key("Quiet Engines", ["Bea Sample"]))
    assert entry == {**entry, "found": False, "why": why}


def _verdict(docs, authors=("Bea Sample",)):
    return book_lookup.confident_match({"docs": docs}, "Quiet Engines", list(authors))


def test_identical_title_and_authors_across_works_is_one_book_and_the_most_editions_wins():
    v = _verdict([_doc("OL1W", "Quiet Engines", ["Bea Sample"], isbns=(OTHER_ISBN,), editions=3),
                  _doc("OL2W", "Quiet Engines", ["Bea Sample"], editions=40),
                  _doc("OL3W", "Quiet Engines", ["Bea Sample"], isbns=(OTHER_ISBN,), editions=7)])
    assert v["match"] == {"work_id": "OL2W", "isbn": ISBN}


def test_the_tiebreak_is_exact_only():
    tie = [_doc("OL1W", "Quiet Engines", ["Bea Sample"], editions=5), _doc("OL2W", "Quiet Engines", ["Bea Sample"], editions=5)]
    assert _verdict(tie)["why"] == "ambiguous"                                      # equal counts: still a doubt
    unknown = [_doc("OL1W", "Quiet Engines", ["Bea Sample"]), _doc("OL2W", "Quiet Engines", ["Bea Sample"])]
    assert _verdict(unknown)["why"] == "ambiguous"                                  # no counts: nothing to rank by
    extra = [_doc("OL1W", "Quiet Engines", ["Bea Sample", "Cy Other"], editions=90),
             _doc("OL2W", "Quiet Engines", ["Bea Sample", "Di Third"], editions=80)]
    assert _verdict(extra)["why"] == "ambiguous"                                    # authors not exactly the page's
    near = [_doc("OL1W", "Quiet Engines Revisited", ["Bea Sample"], editions=90),
            _doc("OL2W", "Quiet Engines", ["Bea Sample"], editions=2)]
    assert _verdict(near)["match"]["work_id"] == "OL2W"                              # a near title never counts or ranks


def test_several_editions_of_one_work_are_one_match(env):
    c, memory, calls, docs = env
    docs += [_doc("OL9W", "Quiet Engines", ["Bea Sample"], isbns=(OTHER_ISBN, ISBN)),
             _doc("OL9W", "Quiet Engines", ["Bea Sample"], isbns=(ISBN,))]
    _sync(c, _ab_book("A2", "Quiet Engines", "Bea Sample"))
    _run(memory)
    assert _books(memory)["quiet-engines"].frontmatter["book"]["title_match"]["isbn"] == ISBN   # the least, deterministic


def test_a_book_with_no_author_or_with_an_isbn_is_never_searched(env):
    c, memory, calls, docs = env
    docs += [_doc("OL9W", "Quiet Engines", ["Bea Sample"])]
    _sync(c, _ab_book("A1", "Quiet Engines", ""), _ab_book("A3", "Another Book", "Dee Sample", epub=f"urn:isbn:{ISBN}"))
    _run(memory)
    assert not [u for u in calls if "/search.json" in u]


def test_with_fetches_off_no_title_leaves_the_machine(env, monkeypatch):
    c, memory, calls, docs = env
    monkeypatch.setenv("CICADA_ALLOW_CONNECTOR_FETCH", "off")
    _sync(c, _ab_book("A2", "Quiet Engines", "Bea Sample"))
    _run(memory)
    assert calls == []


def test_not_this_book_takes_the_match_back_and_it_is_never_asked_again(env):
    c, memory, calls, docs = env
    docs += [_doc("OL9W", "Quiet Engines", ["Bea Sample"])]
    _sync(c, _ab_book("A2", "Quiet Engines", "Bea Sample"))
    _run(memory)
    assert c.post("/entities/quiet-engines/book/not-this-book").json() == {"undone": True}
    page = _books(memory)["quiet-engines"]
    assert page.frontmatter["book"]["title_match_declined"] is True and "title_match" not in page.frontmatter["book"]
    assert "engines that learn" not in page.body and "description_at" not in page.frontmatter["book"]
    assert not any(page.frontmatter["book"].get(k) for k in ("cover_id", "pages", "publisher", "published", "subjects"))
    assert c.get("/entities/quiet-engines/book").json()["description"] is None
    _run(memory)
    assert "engines that learn" not in _books(memory)["quiet-engines"].body
    assert c.post("/entities/quiet-engines/book/not-this-book").status_code == 404   # nothing left to take back


def test_the_backfill_plan_counts_and_asks_nothing(env):
    c, memory, calls, docs = env
    _sync(c, _ab_book("A2", "Quiet Engines", "Bea Sample"), _ab_book("A1", "No Author Book", ""),
          _ab_book("A3", "Another Book", "Dee Sample", epub=f"urn:isbn:{ISBN}"))
    plan = c.get("/sources/books/backfill-plan").json()
    assert plan["books"] == 3 and plan["title_searches"] == 1 and plan["isbn_lookups"] == 1 and plan["cannot"] == 1
    assert calls == []


def test_a_described_book_is_read_once_for_why_and_not_this_book_takes_it_back(env):
    import asyncio
    from types import SimpleNamespace

    from api.services import book_why
    c, memory, calls, docs = env
    docs += [_doc("OL9W", "Quiet Engines", ["Bea Sample"])]
    _sync(c, _ab_book("A2", "Quiet Engines", "Bea Sample"))
    _run(memory)
    sent = []

    async def llm(messages, max_tokens, temperature):
        sent.append(messages[0]["content"])
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="A study of machines that learn."))])

    assert asyncio.run(book_why.run(memory, None, llm_fn=llm, today="2026-11-06")) == ["entities/quiet-engines.md"]
    assert asyncio.run(book_why.run(memory, None, llm_fn=llm, today="2026-11-06")) == []   # once
    assert len(sent) == 1 and "engines that learn" in sent[0].lower() and len(sent[0]) < 1200
    assert c.get("/entities/quiet-engines/book").json()["why"] == "A study of machines that learn."
    c.post("/entities/quiet-engines/book/not-this-book")
    assert c.get("/entities/quiet-engines/book").json()["why"] is None


def test_a_title_matched_book_draws_its_cover_by_the_catalogue_id_never_by_title():
    from api.services import media_preview
    src = media_preview._book_source({"book": {"title": "Quiet Engines", "isbns": [], "cover_id": 1234,
                                               "title_match": {"isbn": ISBN}}})
    assert src is not None and "1234" in src.url and "Quiet" not in src.url
    assert media_preview._book_source({"book": {"title": "Quiet Engines", "isbns": []}}) is None


def test_a_page_made_before_the_doors_field_is_known_by_its_apple_books_block():
    """A dry run on a real bank found 272 of 286 book pages with no ``doors`` and an ``apple_books`` block: they are
    Apple Books pages, so a title may find them."""
    assert books.door_set({"apple_books": {"asset_id": "x"}}) == {books.APPLE_ORIGIN}
    assert books.door_set({"goodreads": {"id": "1"}, "doors": ["book-scan"]}) == {books.GOODREADS_ORIGIN, "book-scan"}
    assert books.door_set({}) == set()


def test_an_identifier_is_not_a_title():
    assert books.id_title("09BBED25F11B9396") and books.id_title("2412.06769v2")
    assert not books.id_title("Essentialism: The Disciplined Pursuit of Less") and not books.id_title("1984")


def test_lookup_names_reads_the_same_name_in_catalogue_order():
    names = books.lookup_names
    assert names("T", ["Mckeown, Greg"]) == ("T", ["Greg Mckeown"])
    assert names("T", ["Bostrom, Nick;"]) == ("T", ["Nick Bostrom"])
    assert names("T", ["A. One & Two, Bee; C. Three and D. Four"])[1] == ["A. One", "Bee Two", "C. Three", "D. Four"]
    assert names("T", ["King, Martin Luther, Jr."])[1] == ["King, Martin Luther, Jr."]   # not one comma: left alone
    assert names("Superintelligence_ Paths, Dangers -- Nick Bostrom -- 2014", [])[0] == "Superintelligence: Paths, Dangers"
    assert names("Plain Title", ["Plain Author"]) == ("Plain Title", ["Plain Author"])


def test_confident_match_is_exact_after_normalising():
    docs = {"docs": [_doc("OL1W", "Essentialism", ["Greg McKeown"])]}
    assert book_lookup.confident_match(docs, "Essentialism", ["Mckeown, Greg"])["match"]["work_id"] == "OL1W"
    # any one of several authors; a different person or a near-miss name is still no match
    two = {"docs": [_doc("OL2W", "Grit", ["Angela Duckworth", "Someone Else"])]}
    assert book_lookup.confident_match(two, "Grit", ["Duckworth, Angela"])["match"]
    assert book_lookup.confident_match(docs, "Essentialism", ["Greg McKeon"])["match"] is None
    # a file name's title is cleaned, then compared exactly
    named = {"docs": [_doc("OL3W", "Superintelligence", ["Nick Bostrom"], subtitle="Paths, Dangers, Strategies")]}
    got = book_lookup.confident_match(named, "Superintelligence_ Paths, Dangers, Strategies -- Nick Bostrom -- 2014",
                                      ["Bostrom, Nick;"])
    assert got["match"]["work_id"] == "OL3W"


def test_key_is_the_same_for_the_same_name_in_either_order():
    assert book_lookup.title_key("Essentialism", ["Mckeown, Greg"]) == book_lookup.title_key("Essentialism", ["Greg Mckeown"])


# ---- Google Books, the second catalogue (2026-11-08) ----------------------------------------------------------------

def _gvol(vid, title, authors, description="A calm study of machines that wait.", **info):
    return {"id": vid, "volumeInfo": {"title": title, "authors": authors, "description": description,
                                      "publishedDate": "2019-05-01", "pageCount": 188, "publisher": "Sample Press",
                                      "categories": ["Fiction"], **info}}


@pytest.fixture
def google(env, monkeypatch):
    """The env, with a Google Books volumes search answered from a list (`gitems`, or a status through `gstatus`)."""
    c, memory, calls, docs = env
    gitems: list[dict] = []
    gstatus = [200]
    inner = book_lookup.default_fetch

    async def fetch(url):
        if "googleapis.com/books" in url:
            calls.append(url)
            if gstatus[0] != 200:
                return book_lookup.Response(gstatus[0])
            return book_lookup.Response(200, json.dumps({"items": [] if "q=isbn" in url else gitems}).encode())
        return await inner(url)

    monkeypatch.setattr(book_lookup, "default_fetch", fetch)
    return c, memory, calls, docs, gitems, gstatus


def _gcalls(calls):
    return [u for u in calls if "googleapis.com/books" in u and "intitle" in u]


def test_google_books_describes_a_book_open_library_could_not_find(google):
    c, memory, calls, docs, gitems, _ = google
    gitems += [_gvol("abcDEF123", "Quiet Engines", ["Bea Sample"])]
    _sync(c, _ab_book("A2", "Quiet Engines", "Bea Sample"))
    _run(memory)
    page = _books(memory)["quiet-engines"]
    book = page.frontmatter["book"]
    assert book["title_match"]["source"] == "googlebooks" and book["title_match"]["volume"] == "abcDEF123"
    assert book["description_source"] == "googlebooks" and book["isbns"] == [] and book["pages"] == 188
    assert "machines that wait" in page.body and "[Google Books](https://books.google.com/books?id=abcDEF123)" in page.body
    assert len(_gcalls(calls)) == 1
    q = parse_qs(urlparse(_gcalls(calls)[0]).query)
    assert q["q"] == ['intitle:"Quiet Engines" inauthor:"Bea Sample"']             # the title and one author, nothing else
    assert c.get("/entities/quiet-engines/book").json()["matchedByTitle"] is True
    _run(memory)
    assert len(_gcalls(calls)) == 1                                                 # cached outside the bank


def test_open_library_stays_first_and_a_described_book_is_never_asked_of_google(google):
    c, memory, calls, docs, gitems, _ = google
    docs += [_doc("OL9W", "Quiet Engines", ["Bea Sample"])]
    gitems += [_gvol("abcDEF123", "Quiet Engines", ["Bea Sample"], description="Google's words.")]
    _sync(c, _ab_book("A2", "Quiet Engines", "Bea Sample"))
    _run(memory)
    page = _books(memory)["quiet-engines"]
    assert "engines that learn to wait" in page.body and page.frontmatter["book"]["description_source"] == "openlibrary"
    assert _gcalls(calls) == []


def test_google_fills_a_description_open_library_matched_without_and_not_this_book_takes_it_all_back(google, monkeypatch):
    c, memory, calls, docs, gitems, _ = google
    monkeypatch.delitem(WORK, "description")                                         # Open Library's record holds none
    docs += [_doc("OL9W", "Quiet Engines", ["Bea Sample"])]
    gitems += [_gvol("abcDEF123", "Quiet Engines", ["Bea Sample"])]
    _sync(c, _ab_book("A2", "Quiet Engines", "Bea Sample"))
    _run(memory)
    book = _books(memory)["quiet-engines"].frontmatter["book"]
    assert book["title_match"]["isbn"] == ISBN and book["title_match"]["google"]["volume"] == "abcDEF123"
    assert book["description_source"] == "googlebooks" and "machines that wait" in _books(memory)["quiet-engines"].body
    assert c.post("/entities/quiet-engines/book/not-this-book").json() == {"undone": True}
    page = _books(memory)["quiet-engines"]
    assert "machines that wait" not in page.body and "title_match" not in page.frontmatter["book"]
    assert not any(page.frontmatter["book"].get(k) for k in ("pages", "publisher", "published", "subjects", "description_at"))
    _run(memory)
    assert "machines that wait" not in _books(memory)["quiet-engines"].body        # never matched again


@pytest.mark.parametrize("items,why", [
    ([_gvol("aaaa1111", "Quiet Engines Revisited", ["Bea Sample"])], "none"),        # not the same title
    ([_gvol("aaaa1111", "Quiet Engines", ["Someone Else"])], "none"),                # another author
    ([_gvol("aaaa1111", "Quiet Engines", ["Bea Sample"], description="")], "no_description"),
])
def test_google_needs_the_exact_title_an_author_and_a_description(google, items, why):
    c, memory, calls, docs, gitems, _ = google
    gitems += items
    _sync(c, _ab_book("A2", "Quiet Engines", "Bea Sample"))
    _run(memory)
    page = _books(memory)["quiet-engines"]
    assert "title_match" not in page.frontmatter["book"] and "description_at" not in page.frontmatter["book"]
    entry = book_lookup.cached(book_lookup.google_key("Quiet Engines", ["Bea Sample"]))
    assert entry["found"] is False and entry["why"] == why


def test_google_prefers_the_volume_whose_authors_are_exactly_the_pages_then_the_fuller_description():
    items = [_gvol("aaaa1111", "Quiet Engines", ["Bea Sample", "Cy Extra"], description="Short."),
             _gvol("bbbb2222", "Quiet Engines", ["Bea Sample"], description="A longer text."),
             _gvol("cccc3333", "Quiet Engines", ["Bea Sample"], description="Longest of all, by some margin.")]
    got = book_lookup.google_match({"items": items}, "Quiet Engines", ["Bea Sample"])["match"]
    assert got["volume"] == "cccc3333"


def test_a_429_stops_the_run_and_nothing_is_written(google):
    c, memory, calls, docs, gitems, gstatus = google
    gstatus[0] = 429
    _sync(c, _ab_book("A2", "Quiet Engines", "Bea Sample"), _ab_book("A3", "Another Book", "Dee Sample"))
    _run(memory)
    assert len(_gcalls(calls)) == 1                                                 # the second book was not asked
    assert "title_match" not in _books(memory)["quiet-engines"].frontmatter["book"]


def test_with_fetches_off_google_is_not_asked_either(google, monkeypatch):
    c, memory, calls, docs, gitems, _ = google
    monkeypatch.setenv("CICADA_ALLOW_CONNECTOR_FETCH", "off")
    _sync(c, _ab_book("A2", "Quiet Engines", "Bea Sample"))
    _run(memory)
    assert calls == []
