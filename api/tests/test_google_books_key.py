"""Google Books is asked only with the person's own API key (2026-11-08). Fake HTTP; no network, no real key."""
from __future__ import annotations

import asyncio
import json
import os

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import book_lookup, google_books_key
from api.services.connections import base as connections_base

KEY = "AIzaFakeKeyNotReal00000000000000000000"


@pytest.fixture
def home(tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    for sub in ("episodes", "entities"):
        (memory / sub).mkdir(parents=True)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    monkeypatch.delenv(google_books_key.SECRET_NAME, raising=False)
    config.get_settings.cache_clear()
    yield tmp_path / "home"
    os.environ.pop(google_books_key.SECRET_NAME, None)
    config.get_settings.cache_clear()


def _fake(calls, status=200, body=None):
    async def fetch(url):
        calls.append(url)
        return book_lookup.Response(status, json.dumps(body if body is not None else {"items": []}).encode())
    return fetch


def _run(coro):
    return asyncio.run(coro)


def test_no_key_no_request_and_open_library_alone_answers(home):
    calls: list[str] = []
    fetch = _fake(calls)
    assert not book_lookup.google_enabled()
    report = _run(book_lookup.resolve_google_titles([{"title": "Quiet Engines", "authors": ["Bea Sample"]}], fetch=fetch))
    assert report["off"] and report["asked"] == 0 and calls == []
    # the ISBN path: an Open Library miss is the whole answer, Google is not asked
    async def ol_404(url):
        calls.append(url)
        return book_lookup.Response(404)
    assert _run(book_lookup.lookup("9780140328721", fetch=ol_404, pacer=book_lookup._Pacer(0))) == {"found": False}
    assert not any("googleapis" in u for u in calls)


def test_with_a_key_the_google_request_carries_it_and_open_library_never_does(home, monkeypatch):
    monkeypatch.setenv(google_books_key.SECRET_NAME, KEY)
    calls: list[str] = []

    async def fetch(url):
        calls.append(url)
        return book_lookup.Response(404 if "openlibrary" in url else 200, b'{"items": []}')

    _run(book_lookup.lookup("9780140328721", fetch=fetch, pacer=book_lookup._Pacer(0)))
    google = [u for u in calls if "googleapis" in u]
    assert google and all(u.endswith(f"&key={KEY}") for u in google)
    assert not any(KEY in u for u in calls if "openlibrary" in u)


@pytest.mark.parametrize("status,body,kind", [(429, b"", "quota"), (403, b"", "not_enabled"),
                                              (400, b'{"error":{"message":"API key not valid."}}', "bad_key")])
def test_a_refused_key_or_closed_quota_stops_the_run_and_is_remembered(home, monkeypatch, status, body, kind):
    monkeypatch.setenv(google_books_key.SECRET_NAME, KEY)

    async def fetch(url):
        return book_lookup.Response(status, body)

    with pytest.raises(book_lookup.QuotaReached):
        _run(book_lookup.match_google("Quiet Engines", ["Bea Sample"], fetch=fetch, pacer=book_lookup._Pacer(0)))
    assert google_books_key.problem()["kind"] == kind
    s = google_books_key.status()
    assert s["problem"] == kind and "console.cloud.google.com" in s["problemWords"] and KEY not in json.dumps(s)
    # a later good answer clears it
    _run(book_lookup._get(_fake([]), book_lookup._Pacer(0), f"{book_lookup.GOOGLE_BOOKS}?q=isbn:1"))
    assert google_books_key.problem() is None


def test_a_400_that_is_not_about_the_key_is_not_a_problem(home):
    assert google_books_key.classify(400, b'{"error":{"message":"Invalid query"}}') is None


def test_connect_saves_only_a_key_google_accepts(home):
    calls: list[str] = []
    out = _run(google_books_key.connect(KEY, fetch=_fake(calls, body={"totalItems": 1})))
    assert out["connected"] is True and KEY not in json.dumps(out)
    assert calls == [f"{book_lookup.GOOGLE_BOOKS}?q=isbn:9780140328721&maxResults=1&fields=totalItems&key={KEY}"]
    assert google_books_key.key() == KEY
    assert f"{google_books_key.SECRET_NAME}={KEY}" in (home / "secrets.env").read_text()
    assert oct((home / "secrets.env").stat().st_mode & 0o777) == "0o600"


@pytest.mark.parametrize("status,kind", [(400, "bad_key"), (403, "not_enabled"), (429, "quota"), (0, "unreachable")])
def test_connect_refuses_with_the_fix_in_words_and_saves_nothing(home, status, kind):
    body = b'{"error":{"message":"API key not valid."}}'
    async def fetch(url):
        return book_lookup.Response(status, body)
    with pytest.raises(google_books_key.KeyRefused) as exc:
        _run(google_books_key.connect(KEY, fetch=fetch))
    assert str(exc.value) == google_books_key.PROBLEM_WORDS[kind]
    assert google_books_key.key() is None and not (home / "secrets.env").exists()


def test_a_key_of_the_wrong_shape_is_refused_before_any_request(home):
    calls: list[str] = []
    for bad in ("", "short", "has spaces in it and is long enough", "a" * 200):
        with pytest.raises(google_books_key.KeyRefused):
            _run(google_books_key.connect(bad, fetch=_fake(calls)))
    assert calls == []


def test_routes_never_return_the_key_and_remove_forgets_it(home, monkeypatch):
    async def ok(url):
        return book_lookup.Response(200, b'{"totalItems": 1}')
    monkeypatch.setattr(book_lookup, "default_fetch", ok)
    c = TestClient(main.app)
    first = c.get("/sources/google-books").json()
    assert first["connected"] is False and first["keyUrl"].startswith("https://console.cloud.google.com/")
    assert "costs nothing" in first["freeWords"] and "billing" not in first["freeWords"]
    put = c.put("/sources/google-books", json={"key": KEY})
    assert put.status_code == 200 and put.json()["connected"] is True and KEY not in put.text
    assert KEY not in c.get("/sources/google-books").text
    gone = c.delete("/sources/google-books")
    assert gone.json()["connected"] is False and google_books_key.key() is None
    assert KEY not in (home / "secrets.env").read_text()


def test_a_refused_key_is_a_422_with_the_words(home, monkeypatch):
    async def refuse(url):
        return book_lookup.Response(400, b'{"error":{"message":"API key not valid."}}')
    monkeypatch.setattr(book_lookup, "default_fetch", refuse)
    r = TestClient(main.app).put("/sources/google-books", json={"key": KEY})
    assert r.status_code == 422 and r.json()["detail"] == google_books_key.PROBLEM_WORDS["bad_key"]


def test_the_key_is_stripped_from_every_child_environment():
    assert google_books_key.SECRET_NAME in connections_base.CONNECTOR_SECRET_ENV
