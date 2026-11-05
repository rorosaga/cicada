"""Ruling 61: a book's picture — the person's own copy's cover first, then Open Library by id or ISBN, never a title, and
nothing when neither has one. Fake HTTP only (the conftest pins the logo gate off)."""
from __future__ import annotations

import asyncio
import base64
import struct
import zlib
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import pytest

from api.services import book_covers, books, channel_items, entity_picture, logo_service, markdown_parser, media_preview

ISBN = "9780306406157"


def _jpeg(size=(120, 180)) -> bytes:
    """A real picture's header (a PNG: the checks read headers, never decode)."""
    width, height = size

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    rows = zlib.compress((b"\x00" + b"\x28\x3c\x50" * width) * height)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", rows) + chunk(b"IEND", b"")


def _fm(**book) -> dict:
    return {"type": "media", "name": "Example Title", "media": {"kind": "book", "url": "https://openlibrary.org/x"},
            "book": book}


@pytest.fixture
def bank(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    root = tmp_path / "memory"
    (root / "entities").mkdir(parents=True)
    return root


def _page(bank, entity_id="example-title", **book) -> str:
    markdown_parser.write(bank / "entities" / f"{entity_id}.md", _fm(**book), "## Summary\nA book.")
    return entity_id


def test_the_kinds_stay_spelled_the_same():
    assert media_preview.BOOK_KIND == books.KIND


# ---------------------------------------------------------------- the source ------------------------------------


def test_a_catalogue_cover_id_comes_first_and_needs_no_isbn_lookup():
    source = media_preview.source_for(_fm(cover_id=240727, isbns=[ISBN]))
    assert source.url == "https://covers.openlibrary.org/b/id/240727-M.jpg?default=false"


def test_an_isbn_when_the_catalogue_gave_no_id():
    source = media_preview.source_for(_fm(isbns=[ISBN]))
    assert source.url == f"https://covers.openlibrary.org/b/isbn/{ISBN}-M.jpg?default=false"


def test_the_persons_own_copy_beats_the_catalogue_and_asks_nothing():
    source = media_preview.source_for(_fm(local_cover="abcdef012345", cover_id=240727, isbns=[ISBN]))
    assert (source.kind, source.url) == ("local", "abcdef012345")


@pytest.mark.parametrize("book", [{}, {"title": "Example Title", "authors": ["An Author"]}, {"isbns": ["not-a-number"]},
                                  {"cover_id": True}, {"cover_id": 0}, {"local_cover": "../../etc"}])
def test_no_identifier_means_no_picture_and_a_title_is_never_a_query(book):
    assert media_preview.source_for(_fm(**book)) is None
    assert entity_picture.resolve_page is not None
    assert entity_picture.media_picture("example-title", _fm(**book)) is None


def test_a_page_with_a_cover_answers_on_the_picture_precedence():
    assert entity_picture.media_picture("example-title", _fm(isbns=[ISBN])).startswith("/entities/example-title/preview")


# ---------------------------------------------------------------- the fetch -------------------------------------


def _fetcher(status=200, body=None, seen=None):
    async def fetch(url):
        if seen is not None:
            seen.append(url)
        return media_preview.Fetched(status=status, body=_jpeg() if body is None else body,
                                     content_type="image/jpeg")
    return fetch


def test_fetched_once_then_served_from_the_store_outside_the_bank(bank):
    _page(bank, isbns=[ISBN])
    seen: list[str] = []
    first = asyncio.run(media_preview.ensure_preview(bank, "example-title", fetcher=_fetcher(seen=seen)))
    again = asyncio.run(media_preview.ensure_preview(bank, "example-title", fetcher=_fetcher(seen=seen)))
    assert first == again and first.is_file() and len(seen) == 1
    assert bank not in first.parents
    assert urlparse(seen[0]).query == "default=false" and urlparse(seen[0]).hostname == media_preview.COVERS_HOST


def test_no_cover_is_a_remembered_miss_not_a_blank(bank):
    _page(bank, isbns=[ISBN])
    seen: list[str] = []
    assert asyncio.run(media_preview.ensure_preview(bank, "example-title", fetcher=_fetcher(404, b"", seen))) is None
    assert asyncio.run(media_preview.ensure_preview(bank, "example-title", fetcher=_fetcher(404, b"", seen))) is None
    assert len(seen) == 1


def test_their_blank_image_is_not_a_cover_should_one_ever_come(bank):
    blank = b"GIF89a" + struct.pack("<HH", 1, 1) + b"\x80\x00\x00" + b"\x00" * 30
    _page(bank, isbns=[ISBN])
    assert asyncio.run(media_preview.ensure_preview(bank, "example-title", fetcher=_fetcher(body=blank))) is None


def test_a_403_on_the_covers_host_is_their_rate_limit_and_asks_again_within_the_hour(bank):
    _page(bank, isbns=[ISBN])
    now = datetime(2026, 11, 4, tzinfo=timezone.utc)
    seen: list[str] = []
    asyncio.run(media_preview.ensure_preview(bank, "example-title", fetcher=_fetcher(403, b"", seen), now=now))
    meta = media_preview.read_meta(logo_service.bank_name(bank), "example-title")
    assert meta["miss"]["transient"] is True
    later = now + media_preview.RETRY_TTL + timedelta(minutes=1)
    asyncio.run(media_preview.ensure_preview(bank, "example-title", fetcher=_fetcher(seen=seen), now=later))
    assert len(seen) == 2


def test_their_retry_after_is_kept_longer_than_our_hour_but_never_past_a_week(bank):
    _page(bank, isbns=[ISBN])
    now = datetime(2026, 11, 4, tzinfo=timezone.utc)
    seen: list[str] = []

    async def limited(url):
        seen.append(url)
        return media_preview.Fetched(status=403, body=b"", retry_after="7200")
    asyncio.run(media_preview.ensure_preview(bank, "example-title", fetcher=limited, now=now))
    meta = media_preview.read_meta(logo_service.bank_name(bank), "example-title")
    key = meta["miss"]["key"]
    assert meta["miss"]["wait_s"] == 7200
    assert media_preview.fresh_miss(meta, key, now=now + timedelta(minutes=90))
    assert not media_preview.fresh_miss(meta, key, now=now + timedelta(minutes=121))
    meta["miss"]["wait_s"] = 60
    assert media_preview.fresh_miss(meta, key, now=now + timedelta(minutes=30)), "never sooner than our hour"
    meta["miss"]["wait_s"] = 10 ** 9
    assert not media_preview.fresh_miss(meta, key, now=now + media_preview.MISS_TTL + timedelta(minutes=1))
    assert media_preview._retry_after_s("nonsense") is None and media_preview._retry_after_s(None) is None
    assert media_preview._retry_after_s("Wed, 21 Oct 2015 07:28:00 GMT") == 0


def test_a_cover_id_redirects_to_their_archive_and_each_hop_is_guarded(bank, monkeypatch):
    _page(bank, isbns=[ISBN], cover_id=12345)
    hops: list[str] = []

    async def fetch(url):
        hops.append(urlparse(url).hostname)
        if urlparse(url).hostname == media_preview.COVERS_HOST:
            return media_preview.Fetched(status=302, body=b"", location="https://archive.org/download/x/y.jpg")
        return media_preview.Fetched(status=200, body=_jpeg(), content_type="image/jpeg")
    assert asyncio.run(media_preview.ensure_preview(bank, "example-title", fetcher=fetch)) is not None
    assert hops == [media_preview.COVERS_HOST, "archive.org"]


def test_the_picture_gate_closes_it_and_records_no_miss(bank, monkeypatch):
    _page(bank, isbns=[ISBN])
    monkeypatch.setattr(logo_service, "fetch_allowed", lambda: False)
    assert asyncio.run(media_preview.ensure_preview(bank, "example-title")) is None
    assert "miss" not in media_preview.read_meta(logo_service.bank_name(bank), "example-title")


def test_every_hop_goes_through_net_guard(bank, monkeypatch):
    _page(bank, isbns=[ISBN])
    asked: list[str] = []

    async def guard(url):
        asked.append(url)
        return False

    monkeypatch.setattr(media_preview.net_guard, "is_fetchable_url_async", guard)
    assert asyncio.run(media_preview.ensure_preview(bank, "example-title", fetcher=_fetcher())) is None
    assert asked and urlparse(asked[0]).hostname == media_preview.COVERS_HOST


def test_the_budget_stays_under_their_limit_and_a_refusal_is_no_miss(bank, monkeypatch):
    assert media_preview.COVER_BUDGET < 100
    clock = [0.0]
    monkeypatch.setattr(media_preview, "_cover_asks", [])
    take = lambda: media_preview._take_cover_budget(clock=lambda: clock[0])  # noqa: E731
    assert all(take() for _ in range(media_preview.COVER_BUDGET)) and not take()
    clock[0] = media_preview.COVER_WINDOW_S + 1
    assert take()
    # Spent: the default fetcher is not reached, and nothing is remembered against the book.
    _page(bank, isbns=[ISBN])
    monkeypatch.setattr(logo_service, "fetch_allowed", lambda: True)
    monkeypatch.setattr(media_preview, "_take_cover_budget", lambda **_: False)

    async def never(_url):
        raise AssertionError("asked over the budget")

    monkeypatch.setattr(media_preview, "_http_get", never)
    assert asyncio.run(media_preview.ensure_preview(bank, "example-title")) is None
    assert "miss" not in media_preview.read_meta(logo_service.bank_name(bank), "example-title")


# ---------------------------------------------------------------- Apple Books' own cover -------------------------


def _post(*items):
    return [{"assetId": a, "coverB64": base64.b64encode(d).decode()} for a, d in items]


def test_a_posted_cover_is_kept_outside_the_bank_and_the_page_names_it(bank):
    apple = bank.name
    assert book_covers.store(apple, _post(("asset-a", _jpeg()))) == {"stored": 1, "unchanged": 0, "refused": 0}
    assert book_covers.store(apple, _post(("asset-a", _jpeg()))) == {"stored": 0, "unchanged": 1, "refused": 0}
    sha = book_covers.read_index(apple)["asset-a"]
    kept = book_covers.stored(apple, sha)
    assert kept.is_file() and bank not in kept.parents
    _page(bank, apple_books=["asset-a"], isbns=[ISBN])
    from api.services import bank_index

    bank_index.invalidate(bank)
    assert books._stamp_local_covers(bank) == ["entities/example-title.md"]
    fm = markdown_parser.parse(bank / "entities" / "example-title.md").frontmatter
    assert fm["book"]["local_cover"] == sha
    # Served as it is: no fetcher, no gate.
    assert asyncio.run(media_preview.ensure_preview(bank, "example-title")) == kept
    bank_index.invalidate(bank)
    assert books._stamp_local_covers(bank) == []


def test_a_page_whose_cover_stayed_on_another_computer_falls_back_to_the_catalogue(bank):
    _page(bank, local_cover="abcdef012345", isbns=[ISBN])
    seen: list[str] = []
    assert asyncio.run(media_preview.ensure_preview(bank, "example-title", fetcher=_fetcher(seen=seen))).is_file()
    assert media_preview.COVERS_HOST in seen[0]


def test_what_is_not_a_picture_is_refused_alone():
    out = book_covers.store("b", _post(("a", b"not a picture"), ("b", _jpeg()), ("", _jpeg()),
                                       ("c", b"\xff" * (media_preview.MAX_BYTES + 1))))
    assert out == {"stored": 1, "unchanged": 0, "refused": 3}
    assert book_covers.store("b", [{"assetId": "x", "coverB64": "%%%"}])["refused"] == 1


def test_too_many_in_one_post_is_refused():
    with pytest.raises(book_covers.PayloadError):
        book_covers.store("b", _post(*[(f"a{i}", b"x") for i in range(book_covers.MAX_PER_POST + 1)]))


def test_stored_never_walks_out_of_its_folder(bank):
    assert book_covers.stored(bank.name, "../../../etc/passwd") is None


# ---------------------------------------------------------------- a source's rows -------------------------------


def test_a_door_lists_each_book_once_with_its_cover_and_a_coverless_one_with_none(bank, monkeypatch):
    from api.services import bank_index

    (bank / "episodes").mkdir()
    _page(bank, "with-cover", isbns=[ISBN])
    _page(bank, "no-cover")
    for ep, page, save in (("ep_a", "with-cover", False), ("ep_b", "with-cover", True), ("ep_c", "no-cover", True)):
        markdown_parser.write(bank / "episodes" / f"{ep}.md",
                              {"id": ep, "origin": "book-scan", "title": "Book scan", "timestamp": "2026-11-01T10:00:00Z",
                               "book": {"isbn": ISBN}, "book_entity_id": page,
                               **({"media_entity_id": page} if save else {})}, "**ISBN:** x\n")
    bank_index.invalidate(bank)
    channel_items.reset_caches() if hasattr(channel_items, "reset_caches") else None
    rows = {r["id"]: r for r in channel_items._book_rows(bank, "book-scan", channel_items._Media(bank))}
    assert set(rows) == {"with-cover", "no-cover"}
    assert rows["with-cover"]["kind"] == "page" and rows["with-cover"]["book"] is True
    assert rows["with-cover"]["cover"].startswith("/entities/with-cover/preview?v=")
    assert "cover" not in rows["no-cover"] and rows["no-cover"]["book"] is True


# ---------------------------------------------------------------- the routes ------------------------------------


def test_the_undo_route_takes_it_back_and_a_missing_record_is_404(tmp_path, monkeypatch):
    from _synthetic_bank import _bank
    from fastapi.testclient import TestClient

    from api import config, main

    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    bank = _bank(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    config.get_settings.cache_clear()
    (bank / "episodes").mkdir(exist_ok=True)
    monkeypatch.setattr(books, "_owner", lambda _m: "user")
    index = books.BookIndex(bank)
    page, _, _ = books.ensure_page(bank, index, books.BookFacts(title="Example Title", isbns=[ISBN],
                                                                title_from="openlibrary"), "ep_a", "2026-10-01")
    for ep, status, day in (("ep_a", "reading", "2026-10-01"), ("ep_b", "finished", "2026-10-20")):
        markdown_parser.write(bank / "episodes" / f"{ep}.md", {"id": ep, "origin": "claude-code"},
                              f"user: {books.STATUS_WORDS[status]}\n")
        books.set_status(bank, page, status=status, day=day, episode_id=ep, quote=books.STATUS_WORDS[status],
                         observer="user", today="2026-11-04")

    client = TestClient(main.app)
    from api.services import bank_index

    bank_index.invalidate(bank)
    record = client.get(f"/entities/{page}/book-status").json()
    assert record["status"] == "finished" and record["fromChat"] is True
    assert client.post(f"/entities/{page}/book-status/undo", json={"claimId": "clm_book_nope"}).status_code == 404
    out = client.post(f"/entities/{page}/book-status/undo", json={"claimId": record["claimId"]})
    assert out.status_code == 200 and out.json() == {"status": "reading"}
    bank_index.invalidate(bank)
    assert client.get(f"/entities/{page}/book-status").json()["status"] == "reading"
    assert client.get("/entities/nothing-here/book-status").status_code == 404
    config.get_settings.cache_clear()
