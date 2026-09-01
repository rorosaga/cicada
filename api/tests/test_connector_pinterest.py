"""Hermetic tests for the Pinterest v5 connector (G71 §2).

ZERO NETWORK: every HTTP call goes through an injected `http_fn`, and the
default transport is disabled by CICADA_ALLOW_CONNECTOR_FETCH=off (set for the
whole suite by conftest; the gate defaults to on in production). Every fixture is synthetic — no real board name,
no real pin, no real credential.
"""

from __future__ import annotations

import asyncio
import os

import pytest

from api.services import media_ingestor, sync_state
from api.services.connections import secrets
from api.services.connectors import pinterest


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    """Credentials go to a throwaway $CICADA_HOME — never the real ~/.cicada.

    ``secrets.set_secret`` also exports straight into ``os.environ`` (so
    litellm/connectors see it without a reload), which ``monkeypatch`` cannot
    auto-revert since it never made that write. Pop the three Pinterest names
    on teardown too, or a credential set by one test leaks into every test
    file collected afterward in the same session (e.g. it flips
    `test_source_channels.py`'s "every channel starts disconnected" case).
    """
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    for name in (pinterest.APP_ID_ENV, pinterest.APP_SECRET_ENV, pinterest.TOKEN_ENV):
        monkeypatch.delenv(name, raising=False)
    yield
    for name in (pinterest.APP_ID_ENV, pinterest.APP_SECRET_ENV, pinterest.TOKEN_ENV):
        os.environ.pop(name, None)


BOARDS = {"items": [
    {"id": "b1", "name": "Recipes"},
    {"id": "b2", "name": "Type inspo"},
], "bookmark": None}

PINS_B1 = {"items": [
    {"id": "p1", "link": "https://example.com/recipe-one", "title": "Recipe one",
     "description": "A soup", "created_at": "2026-01-02T10:00:00"},
    {"id": "p2", "link": "", "title": "Pin with no outbound link"},
], "bookmark": None}

PINS_B2 = {"items": [
    {"id": "p3", "link": "https://example.com/type-sample", "title": "Type sample"},
], "bookmark": None}


def _fake_http(recorder=None):
    async def http(method, url, *, headers=None, params=None, data=None, auth=None):
        if recorder is not None:
            recorder.append((method, url, dict(params or {})))
        if url.endswith("/boards"):
            return BOARDS
        if url.endswith("/boards/b1/pins"):
            return PINS_B1
        if url.endswith("/boards/b2/pins"):
            return PINS_B2
        if url.endswith("/oauth/token"):
            return {"access_token": "tok-abc", "refresh_token": "ref-abc"}
        raise AssertionError(f"unexpected request: {method} {url}")
    return http


# --- pure helpers ------------------------------------------------------------


def test_authorize_url_carries_scopes_state_and_the_backend_redirect():
    secrets.set_secret(pinterest.APP_ID_ENV, "client-id-placeholder")
    url = pinterest.authorize_url("state-xyz")
    assert url.startswith(pinterest.AUTH_URL)
    assert "client_id=client-id-placeholder" in url
    assert "response_type=code" in url
    assert "state=state-xyz" in url
    assert "boards%3Aread" in url and "pins%3Aread" in url
    assert "%2Fsources%2Fconnectors%2Fpinterest%2Fcallback" in url


def test_pins_to_items_uses_the_outbound_link_and_the_board_as_folder():
    items = pinterest.pins_to_items("Recipes", PINS_B1["items"])
    assert [i.url for i in items] == [
        "https://example.com/recipe-one",
        "https://www.pinterest.com/pin/p2/",
    ]
    assert {i.folder for i in items} == {"Recipes"}
    assert {i.origin for i in items} == {"pinterest"}
    assert items[0].title == "Recipe one"
    assert items[0].note == "A soup"


def test_pins_to_items_skips_junk_rows():
    assert pinterest.pins_to_items("Recipes", [None, {}, "nope"]) == []


def test_pins_to_items_normalizes_created_at_through_the_shared_normalizer():
    """G99d (Devin round 1, PR #26 finding 2): a raw Pinterest `created_at`
    must not leak into RawItem.added un-normalized — route it through the
    same saved_at.from_iso8601 normalizer the export parsers use, so it
    compares correctly in the recency sort against every other source.
    """
    items = pinterest.pins_to_items("Recipes", PINS_B1["items"])
    # p1 carries a real-shaped Pinterest created_at (ISO-8601, no timezone
    # offset — "2026-01-02T10:00:00") -> normalized to a bare ISO date.
    assert items[0].added == "2026-01-02"
    # p2 has no created_at at all -> None, never a guess.
    assert items[1].added is None


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
    result = run(pinterest.sync(memory, http_fn=_fake_http()))
    assert result["status"] == "skipped"
    assert result["reason"] == "not connected"
    assert list((memory / "episodes").glob("*.md")) == []


def test_sync_ingests_every_board_and_records_the_sync(tmp_path, monkeypatch):
    memory = _memory(tmp_path, monkeypatch)
    secrets.set_secret(pinterest.TOKEN_ENV, "tok-abc")
    calls: list = []

    result = run(pinterest.sync(memory, http_fn=_fake_http(calls)))
    assert result["status"] == "ok"
    assert result["seen"] == 3
    assert result["new"] == 3
    assert len(list((memory / "episodes").glob("*.md"))) == 3
    assert sync_state.read_sync_state(memory)["pinterest"]["count"] == 3
    assert all("Bearer" not in str(c) for c in calls), "no credential in the recorder"


def test_sync_is_idempotent_via_the_url_index(tmp_path, monkeypatch):
    memory = _memory(tmp_path, monkeypatch)
    secrets.set_secret(pinterest.TOKEN_ENV, "tok-abc")
    run(pinterest.sync(memory, http_fn=_fake_http()))
    second = run(pinterest.sync(memory, http_fn=_fake_http()))
    assert second["new"] == 0
    assert len(list((memory / "episodes").glob("*.md"))) == 3


def test_sync_records_a_failure_instead_of_raising(tmp_path, monkeypatch):
    memory = _memory(tmp_path, monkeypatch)
    secrets.set_secret(pinterest.TOKEN_ENV, "tok-abc")

    async def boom(method, url, **kwargs):
        raise RuntimeError("token expired")

    result = run(pinterest.sync(memory, http_fn=boom))
    assert result["status"] == "error"
    assert "token expired" in result["error"]
    entry = sync_state.read_sync_state(memory)["pinterest"]
    assert "token expired" in entry["last_error"]


def test_sync_refuses_the_default_transport_when_the_gate_is_closed(tmp_path, monkeypatch):
    memory = _memory(tmp_path, monkeypatch)
    secrets.set_secret(pinterest.TOKEN_ENV, "tok-abc")
    result = run(pinterest.sync(memory))  # no http_fn, gate scrubbed by conftest
    assert result["status"] == "skipped"
    assert result["reason"] == "network disabled"


def test_exchange_code_stores_only_the_token(tmp_path, monkeypatch):
    secrets.set_secret(pinterest.APP_ID_ENV, "client-id-placeholder")
    secrets.set_secret(pinterest.APP_SECRET_ENV, "client-secret-placeholder")
    run(pinterest.exchange_code("code-123", http_fn=_fake_http()))
    assert secrets.has_secret(pinterest.TOKEN_ENV)
    assert pinterest.is_connected() is True


def test_credential_fields_never_leak_a_value(tmp_path, monkeypatch):
    secrets.set_secret(pinterest.APP_SECRET_ENV, "client-secret-placeholder")
    fields = pinterest.credential_fields()
    names = {f["name"]: f for f in fields}
    assert names[pinterest.APP_SECRET_ENV]["present"] is True
    assert names[pinterest.APP_SECRET_ENV]["secret"] is True
    assert names[pinterest.APP_ID_ENV]["present"] is False
    for field in fields:
        assert "client-secret-placeholder" not in str(field)
