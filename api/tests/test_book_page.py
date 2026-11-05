"""G233: a scanned book's page is worth opening — authors from the work, Google Books filling what Open Library lacks, a
capped description under its source, no placeholder line, an old cached lookup asked again once.

Synthetic placeholders only: invented ISBNs, titles, authors and blurbs; no network."""
from __future__ import annotations

import asyncio
import json

from api.services import book_lookup, books, markdown_parser
from api.services.claims import strip_claims_block
from test_books import EDITION, PAPERBACK, _NoWait, _books, _run, client  # noqa: F401  (client: a fixture)

BARE = {k: v for k, v in EDITION.items() if k != "authors"}      # an edition that names no author
BLURB = "A lamplighter learns the orchard keeps its own hours. " * 20   # longer than the cap


def _fetch(calls, *, edition=BARE, work=None, google=None):
    async def fetch(url):
        calls.append(url)
        if url.endswith(f"/isbn/{PAPERBACK}.json"):
            return book_lookup.Response(200, json.dumps(edition).encode())
        if url.endswith("/works/OL7W.json"):
            return book_lookup.Response(200, json.dumps(work or {}).encode()) if work is not None \
                else book_lookup.Response(404)
        if url.endswith("/authors/OL1A.json"):
            return book_lookup.Response(200, b'{"name": "Ada Example"}')
        if f"isbn:{PAPERBACK}" in url:
            return book_lookup.Response(200, json.dumps(google or {"totalItems": 0}).encode())
        return book_lookup.Response(0)
    return fetch


def _look(fetch):
    return asyncio.run(book_lookup.lookup(PAPERBACK, fetch=fetch, pacer=_NoWait()))


GOOGLE = {"totalItems": 1, "items": [{"id": "abCD1234", "volumeInfo": {
    "title": "The Lantern Orchard", "authors": ["Bea Sample"], "publisher": "Example House", "pageCount": 300,
    "description": "<p>A short <b>tale</b> of lamps &amp; boats.</p>", "categories": ["Fiction"]}}]}


def test_authors_come_from_the_work_when_the_edition_names_none():
    calls: list[str] = []
    work = {"authors": [{"author": {"key": "/authors/OL1A"}, "type": {"key": "/type/author_role"}}],
            "description": {"type": "/type/text", "value": "A lamplighter learns the orchard keeps its hours."},
            "subjects": ["Orchards", "Lamps", {"name": "Night"}]}
    hit = _look(_fetch(calls, work=work, google=GOOGLE))
    assert hit["authors"] == ["Ada Example"]                       # the work's, not Google's
    assert hit["description"].startswith("A lamplighter") and hit["description_source"] == "openlibrary"
    assert hit["description_url"].endswith("/works/OL7W") and hit["subjects"] == ["Orchards", "Lamps", "Night"]
    assert hit["publisher"] == "Example House" and hit["v"] == book_lookup.VERSION   # Google filled what was missing


def test_google_books_fills_authors_description_and_publisher_beside_an_open_library_edition():
    hit = _look(_fetch([], work={}, google=GOOGLE))
    assert hit["authors"] == ["Bea Sample"] and hit["pages"] == 320  # the edition's page count stays
    assert hit["description"] == "A short tale of lamps & boats." and hit["description_source"] == "googlebooks"
    assert hit["description_url"] == "https://books.google.com/books?id=abCD1234"
    assert hit["subjects"] == ["Fiction"]


def test_google_books_is_not_asked_when_open_library_gave_everything():
    calls: list[str] = []
    full = {**EDITION, "publishers": ["Example House"]}
    work = {"description": "Short.", "subjects": ["Lamps"]}
    hit = _look(_fetch(calls, edition=full, work=work))
    assert hit["authors"] == ["Ada Example"] and hit["publisher"] == "Example House"
    assert not any("googleapis" in u for u in calls)


def test_the_description_is_capped_at_a_sentence_and_markup_is_dropped():
    text = book_lookup.description_text(BLURB)
    assert len(text) <= book_lookup.DESCRIPTION_CAP and text.endswith(".")
    assert book_lookup.description_text("One.\r\n----------\r\n([source][1])\r\nContains: x") == "One."
    assert book_lookup.description_text(None) == "" and book_lookup.description_text({"value": " "}) == ""
    no_stop = book_lookup.description_text("word " * 400)
    assert len(no_stop) <= book_lookup.DESCRIPTION_CAP + 1 and no_stop.endswith("…")


def _scan_with(client, edition, work, google, monkeypatch):
    c, memory, calls = client
    monkeypatch.setattr(book_lookup, "default_fetch", _fetch(calls, edition=edition, work=work, google=google))
    r = c.post("/capture/isbn", json={"isbn": PAPERBACK, "status": "want"})
    assert r.status_code == 200, r.text
    _run(memory)
    [(eid, page)] = _books(memory).items()
    return c, memory, eid, page


def test_the_page_carries_the_description_under_its_source_and_no_placeholder(client, monkeypatch):
    c, memory, eid, page = _scan_with(client, BARE, {"description": "A lamplighter learns the orchard."}, GOOGLE, monkeypatch)
    prose = strip_claims_block(page.body)
    assert "— a book" not in page.body
    assert prose.startswith("## Summary\nA lamplighter learns the orchard.")
    assert "From [Open Library](https://openlibrary.org/works/OL7W), saved " in prose
    assert page.frontmatter["book"]["description_source"] == "openlibrary"
    assert page.frontmatter["book"]["publisher"] == "Example House"
    shown = c.get(f"/entities/{eid}").json()["media"]
    assert shown["description"].startswith("A lamplighter learns the orchard.")


def test_a_book_with_no_description_draws_nothing_and_never_invents_one(client, monkeypatch):
    c, memory, eid, page = _scan_with(client, BARE, {}, None, monkeypatch)
    assert strip_claims_block(page.body) == ""
    assert "description_at" not in page.frontmatter["book"]


def test_an_old_page_loses_its_placeholder_line_and_a_page_with_words_keeps_them(client, monkeypatch):
    c, memory, eid, page = _scan_with(client, BARE, {}, None, monkeypatch)
    path = memory / "entities" / f"{eid}.md"
    markdown_parser.write(path, page.frontmatter, "## Summary\nThe Lantern Orchard by Ada Example — a book.")
    from api.services import bank_index
    bank_index.invalidate(memory)
    from api.services.book_lookup import _remember
    books.apply_pending(memory)
    assert strip_claims_block(markdown_parser.parse(path).body) == ""
    markdown_parser.write(path, page.frontmatter, "## Summary\nMy own words about the orchard.")
    bank_index.invalidate(memory)
    books.apply_pending(memory)
    assert "My own words" in markdown_parser.parse(path).body


def test_a_title_the_person_gave_is_never_replaced_by_a_lookup(client, monkeypatch):
    c, memory, eid, page = _scan_with(client, BARE, {}, None, monkeypatch)
    path = memory / "entities" / f"{eid}.md"
    fm = {**page.frontmatter, "name": "My Name For It", "book": {**page.frontmatter["book"], "title_from": "user"}}
    markdown_parser.write(path, fm, "")
    from api.services import bank_index
    bank_index.invalidate(memory)
    books.apply_pending(memory)
    kept = markdown_parser.parse(path).frontmatter
    assert kept["name"] == "My Name For It" and kept["book"]["title_from"] == "user"


def test_a_lookup_cached_before_descriptions_is_asked_again_once_and_only_once(client, monkeypatch):
    c, memory, calls = client
    old = {"found": True, "source": "openlibrary", "title": "The Lantern Orchard", "subtitle": None, "authors": [],
           "work_id": "OL7W", "published": "2019", "pages": 320, "cover_id": 1234, "isbns": [PAPERBACK]}
    book_lookup._remember(PAPERBACK, old, now=book_lookup._now())
    # The page the old answer made: authors none, the placeholder line.
    facts = books.facts_from_hit(old, [PAPERBACK], door="book-scan")
    from api.services import bank_index
    index = books.BookIndex(memory)
    eid, _, _ = books.ensure_page(memory, index, facts, "ep_2026-11-01_001", "2026-11-01")
    path = memory / "entities" / f"{eid}.md"
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, parsed.frontmatter, "## Summary\nThe Lantern Orchard — a book.")
    bank_index.invalidate(memory)
    assert books.waiting_isbns(memory) == [PAPERBACK]
    monkeypatch.setattr(book_lookup, "default_fetch", _fetch(
        calls, work={"authors": [{"author": {"key": "/authors/OL1A"}}], "description": "A lamplighter returns."},
        google=GOOGLE))
    first = _run(memory)
    assert first["lookup"]["found"] == 1 and calls
    page = markdown_parser.parse(path)
    assert page.frontmatter["book"]["authors"] == ["Ada Example"]
    assert "A lamplighter returns." in page.body and "— a book" not in page.body
    assert book_lookup.cached(PAPERBACK)["v"] == book_lookup.VERSION and cover_kept(page)
    calls.clear()
    assert books.waiting_isbns(memory) == []
    again = _run(memory)
    assert not calls and not again.get("lookup")


def cover_kept(page) -> bool:
    return page.frontmatter["book"]["cover_id"] == 1234


def test_a_failed_refresh_keeps_the_old_answer_and_backs_off(client, monkeypatch):
    c, memory, calls = client
    old = {"found": True, "source": "openlibrary", "title": "The Lantern Orchard", "authors": ["Ada Example"],
           "isbns": [PAPERBACK]}
    book_lookup._remember(PAPERBACK, old, now=book_lookup._now())

    async def down(url):
        return book_lookup.Response(503)
    asyncio.run(book_lookup.resolve([PAPERBACK], fetch=down, pacer=_NoWait()))
    assert book_lookup.cached(PAPERBACK)["authors"] == ["Ada Example"]
    assert not book_lookup.due(PAPERBACK)                           # waits, then asks again


def test_the_card_names_the_ways_in_with_the_scan_day_and_the_scan_result_carries_authors(client, monkeypatch):
    c, memory, eid, page = _scan_with(client, BARE, {"description": "A lamplighter."}, GOOGLE, monkeypatch)
    card = c.get(f"/entities/{eid}/book").json()
    assert card["authors"] == ["Ada Example"] or card["authors"] == ["Bea Sample"]
    assert card["publisher"] == "Example House"
    assert card["descriptionSource"] == "Open Library" and card["descriptionAt"]
    [way] = card["ways"]
    assert way["door"] == "book-scan" and way["label"] == "Scanned" and len(way["day"]) == 10
    assert c.get("/entities/nobody/book").status_code == 404
    [episode] = [p.stem for p in (memory / "episodes").glob("*.md")
                 if markdown_parser.parse(p).frontmatter.get("origin") == "book-scan"]
    seen = c.get(f"/sources/books/scans/{episode}").json()
    assert seen["state"] == "added" and seen["authors"] == card["authors"] and seen["entityId"] == eid


def test_a_scan_is_no_item_of_its_own_in_the_list(client):
    c, memory, calls = client
    c.post("/capture/isbn", json={"isbn": PAPERBACK})
    [row] = c.get("/sources/channels/book-scan/items").json()["items"]
    assert row["kind"] == "unknown" and PAPERBACK not in row["title"] and "scan" not in row["title"].lower()
    _run(memory)
    [row] = c.get("/sources/channels/book-scan/items").json()["items"]
    assert row["kind"] == "page" and row["book"] is True and row["title"] == "The Lantern Orchard"


def test_machine_tags_are_not_subjects_and_a_few_remain():
    tags = ["nyt:fiction=2020", "series_lamps", "Orchards", "Lamps", "Night", "Boats", "Hours", "Late"]
    assert book_lookup.readable_subjects(tags) == ["Orchards", "Lamps", "Night", "Boats"]
    hit = _look(_fetch([], work={"subjects": tags}))
    assert hit["subjects"] == ["Orchards", "Lamps", "Night", "Boats"]


def _git(memory, *args):
    import subprocess
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@e", *args], cwd=memory, check=True,
                          capture_output=True, text=True).stdout


def test_a_scan_with_enrichment_pending_commits_twice_the_scan_alone_as_the_person(client, monkeypatch):
    from test_books import OTHER, _fake_fetch
    from api.services import bank_index
    c, memory, eid, page = _scan_with(client, BARE, {}, None, monkeypatch)
    path = memory / "entities" / f"{eid}.md"
    markdown_parser.write(path, page.frontmatter, "## Summary\nThe Lantern Orchard by Ada Example — a book.")
    bank_index.invalidate(memory)
    _git(memory, "init", "-q")
    _git(memory, "add", "-A")
    _git(memory, "commit", "-q", "-m", "base")
    monkeypatch.setattr(book_lookup, "default_fetch", _fake_fetch([]))
    assert c.post("/capture/isbn", json={"isbn": OTHER, "status": "want"}).status_code == 200
    _git(memory, "add", "-A")                       # the staged scan episode is not this job's to commit
    _git(memory, "commit", "-q", "-m", "episode")
    out = _run(memory)
    log = _git(memory, "log", "-3", "--format=%H%x1f%B%x1e").split("\x1e")
    commits = [e.strip().split("\x1f") for e in log if e.strip()]
    changed = [set(_git(memory, "show", "--name-only", "--format=", sha).split()) for sha, _ in commits[:2]]
    apply = out["apply"]
    assert apply["cicada_paths"] == [f"entities/{eid}.md"] and apply["paths"]
    assert changed[0] == {f"entities/{eid}.md"}                              # Cicada's rewrite, alone
    assert f"entities/{eid}.md" not in changed[1] and changed[1]            # the scan's own pages
    assert "Cicada-Author: cicada" in commits[0][1] and "Cicada-Author: user" in commits[1][1]
