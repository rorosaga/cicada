"""G136 / K9 — the person's search words are never logged (`api/main.py`'s `_RedactQueryString` on uvicorn's access log).

source-page-v3 review (#561): the source page's `?q=` landed in plain text in `logs/backend.*.log`, because the filter
knew paths, not parameters. It now cuts the query of ANY request naming a words or credential parameter; the gate
below walks every route so a new word-carrying parameter cannot slip past it.
"""
from __future__ import annotations

import logging

import pytest
from fastapi.routing import APIRoute

from api import main


def _line(path_and_query: str) -> str:
    record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
                               ("127.0.0.1:5000", "GET", path_and_query, "1.1", 200), None)
    main._RedactQueryString().filter(record)
    return record.getMessage()


@pytest.mark.parametrize("path_and_query", [
    "/sources/channels/whatsapp/items?offset=0&limit=20&q=dinner%20with%20person-a",
    "/sources/channels/chat-export:claude/items?q=secret%20plan",
    "/search?q=alpha&top_k=8",
    "/conversations/recent?limit=200&q=release%20notes",
    "/episodes/ep_2026-10-01_001/evidence?focus=exact%20words",
    "/anything/new?query=private",
    "/sources/connectors/readwise/callback?code=abc123&state=x",
    "/connections/notion/callback/n0nce?code=abc123",
    "/sources/channels/notes/items?Q=upper%20case",
])
def test_a_request_carrying_words_or_a_code_is_logged_without_its_query(path_and_query):
    message = _line(path_and_query)
    path = path_and_query.partition("?")[0]
    assert f"{path}?…" in message
    after = path_and_query.partition("?")[2]
    assert after not in message
    for word in ("dinner", "secret", "alpha", "release", "exact", "private", "abc123", "upper"):
        assert word not in message


def test_a_request_with_no_words_keeps_its_query():
    assert "/sources/channels/notes/items?offset=20&limit=20" in _line("/sources/channels/notes/items?offset=20&limit=20")
    assert "/status" in _line("/status")


def test_a_record_that_is_not_an_access_line_is_left_alone():
    record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, "%s", ("/search?q=x",), None)
    main._RedactQueryString().filter(record)
    assert record.args == ("/search?q=x",)


#: Names a person's words or a secret would travel under. A route whose string query parameter has one of these names
#: must be redacted by the filter; add the name to `_REDACTED_PARAMS` (or rename the parameter to `q`).
_WORD_LIKE = {"q", "query", "search", "text", "term", "terms", "words", "phrase", "prefix", "filter", "title",
              "focus", "quote", "message", "prompt", "code", "token", "secret", "password"}


def test_every_routes_word_like_query_parameter_is_redacted():
    missing = []
    for route in main.app.routes:
        if not isinstance(route, APIRoute):
            continue
        for param in route.dependant.query_params:
            name = (param.alias or param.name).lower()
            if name in _WORD_LIKE and name not in main._REDACTED_PARAMS:
                missing.append(f"{route.path} ?{name}")
    assert not missing, f"query parameters that would log a person's words or a secret: {missing}"


def test_the_routes_that_take_words_today_are_all_covered():
    names = {(param.alias or param.name) for route in main.app.routes if isinstance(route, APIRoute)
             for param in route.dependant.query_params}
    assert {"q", "focus", "code"} <= names, "the gate must see the parameters it exists for"
