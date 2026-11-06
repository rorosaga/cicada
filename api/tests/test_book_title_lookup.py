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


def _doc(key, title, authors, isbns=(ISBN,), subtitle=None):
    return {"key": f"/works/{key}", "title": title, "subtitle": subtitle, "author_name": authors, "isbn": list(isbns)}


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
