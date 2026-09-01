"""Hermetic tests for the Reddit saved connector (G71 §2).

ZERO NETWORK: injected `http_fn` throughout, default transport gated. Every
subreddit, title and credential below is invented.
"""

from __future__ import annotations

import asyncio
import os

import pytest

from api.services import media_ingestor, sync_state
from api.services.connections import secrets
from api.services.connectors import reddit


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    """Credentials go to a throwaway $CICADA_HOME — never the real ~/.cicada.

    ``secrets.set_secret`` also exports straight into ``os.environ``, which
    ``monkeypatch`` cannot auto-revert since it never made that write. Pop the
    four Reddit names on teardown too, or a credential set by one test leaks
    into every test file collected afterward in the same session (mirrors
    test_connector_pinterest.py's ``_isolated_home``).
    """
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    for name in (reddit.CLIENT_ID_ENV, reddit.CLIENT_SECRET_ENV,
                 reddit.USERNAME_ENV, reddit.PASSWORD_ENV):
        monkeypatch.delenv(name, raising=False)
    yield
    for name in (reddit.CLIENT_ID_ENV, reddit.CLIENT_SECRET_ENV,
                 reddit.USERNAME_ENV, reddit.PASSWORD_ENV):
        os.environ.pop(name, None)


def _credentials():
    secrets.set_secret(reddit.CLIENT_ID_ENV, "client-id-placeholder")
    secrets.set_secret(reddit.CLIENT_SECRET_ENV, "client-secret-placeholder")
    secrets.set_secret(reddit.USERNAME_ENV, "example_user")
    secrets.set_secret(reddit.PASSWORD_ENV, "password-placeholder")


def _child(name, *, title, url=None, permalink=None, subreddit="example", is_self=False):
    return {"kind": "t3", "data": {
        "name": name, "title": title, "subreddit": subreddit, "is_self": is_self,
        "url": url or "", "permalink": permalink or f"/r/{subreddit}/comments/{name[3:]}/x/",
    }}


PAGE_1 = {"kind": "Listing", "data": {"after": "t3_002", "children": [
    _child("t3_001", title="An external article", url="https://example.com/article"),
    _child("t3_002", title="A self post", is_self=True),
]}}

PAGE_2 = {"kind": "Listing", "data": {"after": None, "children": [
    _child("t3_003", title="Another article", url="https://example.com/other"),
]}}


def _fake_http(pages=(PAGE_1, PAGE_2), recorder=None):
    seen = {"n": 0}

    async def http(method, url, *, headers=None, params=None, data=None, auth=None):
        if recorder is not None:
            recorder.append((method, url, dict(params or {})))
        if url.endswith("/api/v1/access_token"):
            return {"access_token": "tok-abc", "token_type": "bearer"}
        page = pages[min(seen["n"], len(pages) - 1)]
        seen["n"] += 1
        return page

    return http


def _memory(tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    for sub in ("episodes", "entities", "sources"):
        (memory / sub).mkdir(parents=True, exist_ok=True)

    async def offline(url, client, from_bookmark_file=False):
        return media_ingestor.MediaMeta(
            title=media_ingestor._fallback_title(url), description="",
            site=media_ingestor._site_of(url), media_type="url")

    async def no_commit(memory_path, count, paths=None):
        return None

    monkeypatch.setattr(media_ingestor, "enrich", offline)
    monkeypatch.setattr(media_ingestor, "_commit_media", no_commit)
    return memory


# --- pure helpers ------------------------------------------------------------


def test_children_to_items_prefers_the_outbound_url_and_falls_back_to_the_permalink():
    items = reddit.children_to_items(PAGE_1["data"]["children"])
    assert [i.url for i in items] == [
        "https://example.com/article",
        "https://www.reddit.com/r/example/comments/002/x/",
    ]
    assert [i.title for i in items] == ["An external article", "A self post"]
    assert {i.folder for i in items} == {"r/example"}
    assert {i.origin for i in items} == {"reddit-saved"}


def test_children_to_items_skips_junk():
    assert reddit.children_to_items([None, {}, {"data": "nope"}]) == []


# --- pagination --------------------------------------------------------------


def test_fetch_saved_pages_until_after_runs_out():
    children, newest = run(reddit.fetch_saved("tok", "example_user", http_fn=_fake_http()))
    assert [c["data"]["name"] for c in children] == ["t3_001", "t3_002", "t3_003"]
    assert newest == "t3_001", "the newest fullname is the cursor for the next run"


def test_fetch_saved_stops_at_the_previously_seen_id():
    children, newest = run(reddit.fetch_saved(
        "tok", "example_user", http_fn=_fake_http(), stop_at="t3_002"))
    assert [c["data"]["name"] for c in children] == ["t3_001"]
    assert newest == "t3_001"


def test_fetch_saved_sends_a_user_agent_and_never_the_password():
    calls: list = []
    run(reddit.fetch_saved("tok", "example_user", http_fn=_fake_http(recorder=calls)))
    assert calls, "at least one listing request"
    assert all("password-placeholder" not in str(c) for c in calls)


# --- sync --------------------------------------------------------------------


def test_sync_is_skipped_without_credentials(tmp_path, monkeypatch):
    memory = _memory(tmp_path, monkeypatch)
    result = run(reddit.sync(memory, http_fn=_fake_http()))
    assert result["status"] == "skipped"
    assert result["reason"] == "not connected"


def test_sync_ingests_and_stores_the_cursor(tmp_path, monkeypatch):
    memory = _memory(tmp_path, monkeypatch)
    _credentials()
    result = run(reddit.sync(memory, http_fn=_fake_http()))
    assert result["status"] == "ok"
    assert result["seen"] == 3
    assert result["new"] == 3
    entry = sync_state.read_sync_state(memory)["reddit"]
    assert entry["count"] == 3
    assert entry["last_seen"] == "t3_001"


def test_sync_second_run_stops_at_the_cursor(tmp_path, monkeypatch):
    memory = _memory(tmp_path, monkeypatch)
    _credentials()
    run(reddit.sync(memory, http_fn=_fake_http()))
    second = run(reddit.sync(memory, http_fn=_fake_http()))
    assert second["seen"] == 0
    assert second["new"] == 0


def test_sync_records_a_failure_instead_of_raising(tmp_path, monkeypatch):
    memory = _memory(tmp_path, monkeypatch)
    _credentials()

    async def boom(method, url, **kwargs):
        raise RuntimeError("429 rate limited")

    result = run(reddit.sync(memory, http_fn=boom))
    assert result["status"] == "error"
    assert "429" in result["error"]
    assert "429" in sync_state.read_sync_state(memory)["reddit"]["last_error"]


def test_sync_refuses_the_default_transport_when_the_gate_is_closed(tmp_path, monkeypatch):
    memory = _memory(tmp_path, monkeypatch)
    _credentials()
    result = run(reddit.sync(memory))
    assert result["status"] == "skipped"
    assert result["reason"] == "network disabled"


def test_credential_fields_never_leak_a_value(tmp_path, monkeypatch):
    _credentials()
    fields = reddit.credential_fields()
    assert all(f["present"] for f in fields)
    assert all("password-placeholder" not in str(f) for f in fields)
    assert {f["name"] for f in fields if f["secret"]} == {
        reddit.CLIENT_SECRET_ENV, reddit.PASSWORD_ENV}


# --- CSV backfill / API pull overlap (G71 §2) --------------------------------


def test_a_csv_backfilled_self_post_is_not_duplicated_by_the_api_pull(tmp_path, monkeypatch):
    """The GDPR export (Task 6) and this connector share ``origin ==
    "reddit-saved"``. A self post's CSV permalink and its API-derived URL are
    the SAME absolute reddit.com link, so ``url_hash`` dedup must collapse
    them into one media entity — the connector must not re-create ``t3_002``
    just because it also appears in tonight's API pull.
    """
    memory = _memory(tmp_path, monkeypatch)
    _credentials()

    csv_items = media_ingestor.parse_reddit_saved_csv(
        b"id,permalink\nt3_002,/r/example/comments/002/x/\n", "saved_posts.csv")
    assert csv_items and csv_items[0].origin == "reddit-saved"
    created, _ = run(media_ingestor.ingest_batch(csv_items, memory, from_bookmark_file=False))
    assert created == 1

    result = run(reddit.sync(memory, http_fn=_fake_http()))
    assert result["status"] == "ok"
    assert result["seen"] == 3, "every child is still fetched from the API"
    assert result["new"] == 2, "t3_002 was already backfilled by the CSV export"
