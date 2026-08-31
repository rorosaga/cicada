"""Hermetic tests for the X (Twitter) bookmarks connector (G71 follow-up, Task 14).

ZERO NETWORK: every HTTP call goes through an injected `http_fn`, and the
default transport is gated on CICADA_ALLOW_CONNECTOR_FETCH (scrubbed by the
autouse conftest fixture). Every fixture is synthetic — no real tweet, no real
user id, no real credential.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import os

import pytest

from api.services import media_ingestor, sync_state
from api.services.connections import secrets
from api.services.connectors import x


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    """Credentials go to a throwaway $CICADA_HOME — never the real ~/.cicada.

    ``secrets.set_secret`` also exports straight into ``os.environ``, which
    ``monkeypatch`` cannot auto-revert since it never made that write. Pop the
    four X names on teardown too, or a credential set by one test leaks into
    every test file collected afterward in the same session (matches
    test_connector_pinterest.py's convention).
    """
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    names = (x.CLIENT_ID_ENV, x.TOKEN_ENV, x.REFRESH_TOKEN_ENV, x.USER_ID_ENV)
    for name in names:
        monkeypatch.delenv(name, raising=False)
    yield
    for name in names:
        os.environ.pop(name, None)


TWEET_1 = {"id": "1001", "text": "First bookmark, a plain short tweet."}
TWEET_2 = {"id": "1002", "text": "x" * 120}  # forces title truncation
TWEET_3 = {"id": "1003", "text": "Third page tweet."}

PAGE_1 = {"data": [TWEET_1, TWEET_2], "meta": {"next_token": "cursor-2"}}
PAGE_2 = {"data": [TWEET_3], "meta": {}}

ME_PAYLOAD = {"data": {"id": "u-42", "username": "example_user"}}
TOKEN_PAYLOAD = {"access_token": "tok-abc", "refresh_token": "ref-abc"}
REFRESHED_PAYLOAD = {"access_token": "tok-new", "refresh_token": "ref-new"}


def _fake_http(recorder=None, *, pages=None, me=None, token=None, refreshed=None):
    pages = pages if pages is not None else [PAGE_1, PAGE_2]
    calls = {"page": 0}

    async def http(method, url, *, headers=None, params=None, data=None, auth=None):
        if recorder is not None:
            recorder.append((method, url, dict(params or {}), dict(data or {})))
        if url == x.ME_URL:
            return me if me is not None else ME_PAYLOAD
        if url == x.TOKEN_URL:
            if data and data.get("grant_type") == "refresh_token":
                return refreshed if refreshed is not None else REFRESHED_PAYLOAD
            return token if token is not None else TOKEN_PAYLOAD
        if url.endswith("/bookmarks"):
            page = pages[min(calls["page"], len(pages) - 1)]
            calls["page"] += 1
            return page
        raise AssertionError(f"unexpected request: {method} {url}")
    return http


# --- pure helpers ------------------------------------------------------------


def test_generate_pkce_pair_produces_a_verifier_and_a_matching_s256_challenge():
    verifier, challenge = x.generate_pkce_pair()
    assert 43 <= len(verifier) <= 128
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    assert challenge == expected
    # Two calls never collide.
    verifier2, challenge2 = x.generate_pkce_pair()
    assert verifier2 != verifier
    assert challenge2 != challenge


def test_authorize_url_carries_scopes_state_challenge_and_the_backend_redirect():
    secrets.set_secret(x.CLIENT_ID_ENV, "client-id-placeholder")
    url = x.authorize_url("state-xyz", "challenge-abc")
    assert url.startswith(x.AUTH_URL)
    assert "client_id=client-id-placeholder" in url
    assert "response_type=code" in url
    assert "state=state-xyz" in url
    assert "code_challenge=challenge-abc" in url
    assert "code_challenge_method=S256" in url
    assert "bookmark.read" in url and "offline.access" in url
    assert "%2Fsources%2Fconnectors%2Fx%2Fcallback" in url


def test_bookmarks_to_items_uses_tweet_text_as_the_note_and_has_no_folder():
    items = x.bookmarks_to_items([TWEET_1])
    assert len(items) == 1
    item = items[0]
    assert item.url == "https://x.com/i/web/status/1001"
    assert item.note == TWEET_1["text"]
    assert item.title == TWEET_1["text"]
    assert item.folder is None
    assert item.origin == "x-bookmarks"


def test_bookmarks_to_items_truncates_a_long_tweet_into_the_title():
    items = x.bookmarks_to_items([TWEET_2])
    assert items[0].title.endswith("…")
    assert len(items[0].title) == x._TITLE_MAX + 1
    assert items[0].note == TWEET_2["text"], "the full text still rides `note` untruncated"


def test_bookmarks_to_items_skips_junk_rows():
    assert x.bookmarks_to_items([None, {}, "nope", {"id": ""}]) == []


# --- sync --------------------------------------------------------------------


def _memory(tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    for sub in ("episodes", "entities", "sources"):
        (memory / sub).mkdir(parents=True, exist_ok=True)

    async def offline(url, client, from_bookmark_file=False):
        return media_ingestor.MediaMeta(
            title=media_ingestor._fallback_title(url), description="",
            site=media_ingestor._site_of(url), media_type="url")

    async def no_commit(memory_path, count):
        return None

    monkeypatch.setattr(media_ingestor, "enrich", offline)
    monkeypatch.setattr(media_ingestor, "_commit_media", no_commit)
    return memory


def test_sync_is_skipped_without_a_token(tmp_path, monkeypatch):
    memory = _memory(tmp_path, monkeypatch)
    result = run(x.sync(memory, http_fn=_fake_http()))
    assert result["status"] == "skipped"
    assert result["reason"] == "not connected"
    assert list((memory / "episodes").glob("*.md")) == []


def test_sync_ingests_every_page_and_records_the_sync(tmp_path, monkeypatch):
    memory = _memory(tmp_path, monkeypatch)
    secrets.set_secret(x.TOKEN_ENV, "tok-abc")
    secrets.set_secret(x.USER_ID_ENV, "u-42")
    calls: list = []

    result = run(x.sync(memory, http_fn=_fake_http(calls)))
    assert result["status"] == "ok"
    assert result["seen"] == 3
    assert result["new"] == 3
    assert result["resources_read"] == 3
    assert len(list((memory / "episodes").glob("*.md"))) == 3
    assert sync_state.read_sync_state(memory)["x"]["count"] == 3
    assert sync_state.read_sync_state(memory)["x"]["last_seen_id"] == "1001"
    assert all("Bearer" not in str(c) for c in calls), "no credential in the recorder"
    # No refresh token stored -> no token endpoint hit, straight to bookmarks.
    assert all(url != x.TOKEN_URL for _, url, _, _ in calls)


def test_sync_stops_at_the_previously_seen_id(tmp_path, monkeypatch):
    memory = _memory(tmp_path, monkeypatch)
    secrets.set_secret(x.TOKEN_ENV, "tok-abc")
    secrets.set_secret(x.USER_ID_ENV, "u-42")
    sync_state.record_sync(memory, "x", count=1, extra={"last_seen_id": "1002"})

    result = run(x.sync(memory, http_fn=_fake_http(pages=[PAGE_1])))
    assert result["status"] == "ok"
    assert result["seen"] == 1, "only the tweet newer than the stored cursor is new"
    assert result["resources_read"] == 1


def test_sync_is_idempotent_via_the_url_index(tmp_path, monkeypatch):
    """Distinct from the cursor stop (tested above): even if the cursor is
    lost — a corrupt/reset sync_state.json, say — and the API is asked for
    every bookmark again from scratch, url_index.json must still catch the
    duplicates and write zero new episodes."""
    memory = _memory(tmp_path, monkeypatch)
    secrets.set_secret(x.TOKEN_ENV, "tok-abc")
    secrets.set_secret(x.USER_ID_ENV, "u-42")
    run(x.sync(memory, http_fn=_fake_http()))
    sync_state.record_sync(memory, "x", count=0)  # simulate a lost cursor
    second = run(x.sync(memory, http_fn=_fake_http(pages=[PAGE_1, PAGE_2])))
    assert second["new"] == 0
    assert second["seen"] == 3, "the full history is re-fetched with no cursor"
    assert len(list((memory / "episodes").glob("*.md"))) == 3


def test_sync_resolves_the_user_id_lazily_when_missing(tmp_path, monkeypatch):
    memory = _memory(tmp_path, monkeypatch)
    secrets.set_secret(x.TOKEN_ENV, "tok-abc")
    # No USER_ID_ENV stored — must be resolved via /2/users/me before bookmarks.
    calls: list = []
    result = run(x.sync(memory, http_fn=_fake_http(calls)))
    assert result["status"] == "ok"
    assert any(url == x.ME_URL for _, url, _, _ in calls)
    assert secrets.load_secrets().get(x.USER_ID_ENV) == "u-42"


def test_sync_refreshes_the_access_token_when_a_refresh_token_is_stored(tmp_path, monkeypatch):
    memory = _memory(tmp_path, monkeypatch)
    secrets.set_secret(x.CLIENT_ID_ENV, "client-id-placeholder")
    secrets.set_secret(x.TOKEN_ENV, "tok-stale")
    secrets.set_secret(x.REFRESH_TOKEN_ENV, "ref-abc")
    secrets.set_secret(x.USER_ID_ENV, "u-42")
    calls: list = []

    result = run(x.sync(memory, http_fn=_fake_http(calls)))
    assert result["status"] == "ok"
    assert any(url == x.TOKEN_URL for _, url, _, _ in calls), "a refresh token must be spent"
    assert secrets.load_secrets()[x.TOKEN_ENV] == "tok-new"
    assert secrets.load_secrets()[x.REFRESH_TOKEN_ENV] == "ref-new", "the refresh token rotates"


def test_sync_records_a_failure_instead_of_raising(tmp_path, monkeypatch):
    memory = _memory(tmp_path, monkeypatch)
    secrets.set_secret(x.TOKEN_ENV, "tok-abc")
    secrets.set_secret(x.USER_ID_ENV, "u-42")

    async def boom(method, url, **kwargs):
        raise RuntimeError("rate limited")

    result = run(x.sync(memory, http_fn=boom))
    assert result["status"] == "error"
    assert "rate limited" in result["error"]
    entry = sync_state.read_sync_state(memory)["x"]
    assert "rate limited" in entry["last_error"]


def test_sync_refuses_the_default_transport_when_the_gate_is_closed(tmp_path, monkeypatch):
    memory = _memory(tmp_path, monkeypatch)
    secrets.set_secret(x.TOKEN_ENV, "tok-abc")
    result = run(x.sync(memory))  # no http_fn, gate scrubbed by conftest
    assert result["status"] == "skipped"
    assert result["reason"] == "network disabled"


def test_exchange_code_stores_tokens_and_resolves_the_user_id(tmp_path, monkeypatch):
    secrets.set_secret(x.CLIENT_ID_ENV, "client-id-placeholder")
    calls: list = []
    run(x.exchange_code("code-123", "verifier-xyz", http_fn=_fake_http(calls)))
    assert secrets.has_secret(x.TOKEN_ENV)
    assert x.is_connected() is True
    assert secrets.load_secrets()[x.REFRESH_TOKEN_ENV] == "ref-abc"
    assert secrets.load_secrets()[x.USER_ID_ENV] == "u-42"
    # The verifier reached the token exchange, and no client secret was sent.
    token_call = next(c for c in calls if c[1] == x.TOKEN_URL)
    assert token_call[3]["code_verifier"] == "verifier-xyz"
    assert token_call[3]["client_id"] == "client-id-placeholder"


def test_exchange_code_requires_a_client_id_first(tmp_path, monkeypatch):
    with pytest.raises(Exception):
        run(x.exchange_code("code-123", "verifier-xyz", http_fn=_fake_http()))
    assert not secrets.has_secret(x.TOKEN_ENV)


def test_exchange_code_survives_a_user_id_lookup_failure(tmp_path, monkeypatch):
    """A `/2/users/me` hiccup must not roll back the token — sync() resolves
    the user id lazily later."""
    secrets.set_secret(x.CLIENT_ID_ENV, "client-id-placeholder")

    async def flaky(method, url, **kwargs):
        if url == x.ME_URL:
            raise RuntimeError("503")
        if url == x.TOKEN_URL:
            return TOKEN_PAYLOAD
        raise AssertionError(f"unexpected request: {method} {url}")

    run(x.exchange_code("code-123", "verifier-xyz", http_fn=flaky))
    assert x.is_connected() is True
    assert not secrets.has_secret(x.USER_ID_ENV)


def test_credential_fields_never_leak_a_value():
    secrets.set_secret(x.CLIENT_ID_ENV, "client-id-placeholder")
    fields = x.credential_fields()
    assert len(fields) == 1
    assert fields[0]["name"] == x.CLIENT_ID_ENV
    assert fields[0]["present"] is True
    assert fields[0]["secret"] is False
    for field in fields:
        assert "client-id-placeholder" not in str(field)


def test_forget_removes_every_stored_credential():
    secrets.set_secret(x.CLIENT_ID_ENV, "client-id-placeholder")
    secrets.set_secret(x.TOKEN_ENV, "tok-abc")
    secrets.set_secret(x.REFRESH_TOKEN_ENV, "ref-abc")
    secrets.set_secret(x.USER_ID_ENV, "u-42")
    x.forget()
    assert x.is_connected() is False
    for f in x.credential_fields():
        assert f["present"] is False
    assert not secrets.has_secret(x.TOKEN_ENV)
    assert not secrets.has_secret(x.REFRESH_TOKEN_ENV)
    assert not secrets.has_secret(x.USER_ID_ENV)
