"""Hermetic tests for RSS feed subscriptions + polling (feed_registry).

Covers:
- ``subscribe_feed`` idempotency (dedup on normalized URL, tag merge on
  re-subscribe), ``list_feeds``, ``unsubscribe_feed``;
- ``poll_feeds`` with an injected ``fetch_fn`` — ingests only new items
  through the existing ``media_ingestor.ingest_feed`` path (url-hash dedup),
  updates ``last_polled``;
- ``poll_feeds`` is a no-op (``skipped_no_network``) when no ``fetch_fn`` is
  given and the network gate is closed;
- a malformed/unreachable feed is recorded as an error, not raised, and
  polling continues with the remaining feeds;
- the four ``/sources/feeds*`` endpoints via ``TestClient``.

Every test builds its own ``tmp_path`` workspace; the real ``memory/`` is
never touched, and no test ever performs a real network call — ``fetch_fn``
is always injected or the network gate is deliberately left closed.
"""

from __future__ import annotations

import asyncio

import pytest

from api.services import feed_registry, media_ingestor
from api.services.media_ingestor import MediaMeta


def run(coro):
    return asyncio.run(coro)


RSS_FEED_A = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Feed A</title>
    <link>https://a.example.com</link>
    <item>
      <title>A First Post</title>
      <link>https://a.example.com/first-post</link>
      <description>Intro post.</description>
    </item>
    <item>
      <title>A Second Post</title>
      <link>https://a.example.com/second-post</link>
      <description>Another post.</description>
    </item>
  </channel>
</rss>
"""

RSS_FEED_A_UPDATED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Feed A</title>
    <link>https://a.example.com</link>
    <item>
      <title>A First Post</title>
      <link>https://a.example.com/first-post</link>
      <description>Intro post.</description>
    </item>
    <item>
      <title>A Second Post</title>
      <link>https://a.example.com/second-post</link>
      <description>Another post.</description>
    </item>
    <item>
      <title>A Third Post — Brand New</title>
      <link>https://a.example.com/third-post</link>
      <description>Freshly published since the last poll.</description>
    </item>
  </channel>
</rss>
"""

RSS_FEED_B = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Feed B</title>
    <link>https://b.example.com</link>
    <item>
      <title>B Post</title>
      <link>https://b.example.com/post</link>
    </item>
  </channel>
</rss>
"""

NOT_XML = "this is not xml at all <<<"


def _offline_enrich(monkeypatch):
    """Force ``enrich`` to the URL-only fallback so no network is touched."""

    async def fake_enrich(url, client, from_bookmark_file=False):
        media_type = media_ingestor._classify(url, from_bookmark_file)
        return MediaMeta(
            title=media_ingestor._fallback_title(url),
            description="",
            site=media_ingestor._site_of(url),
            media_type=media_type,
        )

    monkeypatch.setattr(media_ingestor, "enrich", fake_enrich)


def _memory(tmp_path):
    memory = tmp_path / "memory"
    for sub in ("episodes", "entities", "sources"):
        (memory / sub).mkdir(parents=True, exist_ok=True)
    return memory


# --- subscribe / list / unsubscribe -----------------------------------------


def test_subscribe_feed_creates_record(tmp_path):
    memory = _memory(tmp_path)
    record = feed_registry.subscribe_feed(memory, "https://a.example.com/rss", tags=["news"])
    assert record["url"] == "https://a.example.com/rss"
    assert record["tags"] == ["news"]
    assert record["added"]
    assert record["last_polled"] is None

    feeds = feed_registry.list_feeds(memory)
    assert len(feeds) == 1
    assert feeds[0]["url"] == "https://a.example.com/rss"


def test_subscribe_feed_is_idempotent(tmp_path):
    memory = _memory(tmp_path)
    feed_registry.subscribe_feed(memory, "https://a.example.com/rss")
    feed_registry.subscribe_feed(memory, "https://a.example.com/rss")
    feed_registry.subscribe_feed(memory, "https://a.example.com/rss/")  # normalizes equal

    feeds = feed_registry.list_feeds(memory)
    assert len(feeds) == 1


def test_subscribe_feed_merges_tags_on_resubscribe(tmp_path):
    memory = _memory(tmp_path)
    feed_registry.subscribe_feed(memory, "https://a.example.com/rss", tags=["news"])
    record = feed_registry.subscribe_feed(memory, "https://a.example.com/rss", tags=["tech"])

    assert set(record["tags"]) == {"news", "tech"}
    assert len(feed_registry.list_feeds(memory)) == 1


def test_list_feeds_empty_when_no_registry(tmp_path):
    memory = _memory(tmp_path)
    assert feed_registry.list_feeds(memory) == []


def test_unsubscribe_feed_removes_record(tmp_path):
    memory = _memory(tmp_path)
    feed_registry.subscribe_feed(memory, "https://a.example.com/rss")
    feed_registry.subscribe_feed(memory, "https://b.example.com/rss")

    removed = feed_registry.unsubscribe_feed(memory, "https://a.example.com/rss")
    assert removed is True

    feeds = feed_registry.list_feeds(memory)
    assert len(feeds) == 1
    assert feeds[0]["url"] == "https://b.example.com/rss"


def test_unsubscribe_feed_returns_false_when_not_found(tmp_path):
    memory = _memory(tmp_path)
    assert feed_registry.unsubscribe_feed(memory, "https://nope.example.com/rss") is False


def test_registry_survives_corrupt_yaml(tmp_path):
    memory = _memory(tmp_path)
    (memory / feed_registry.FEEDS_FILENAME).write_text("{not: valid: yaml: [", encoding="utf-8")
    assert feed_registry.list_feeds(memory) == []


# --- poll_feeds: injected fetch_fn ------------------------------------------


def test_poll_feeds_ingests_new_items_via_injected_fetch(tmp_path, monkeypatch):
    _offline_enrich(monkeypatch)
    memory = _memory(tmp_path)
    feed_registry.subscribe_feed(memory, "https://a.example.com/rss")

    calls = []

    def fetch_fn(url):
        calls.append(url)
        return RSS_FEED_A

    result = run(feed_registry.poll_feeds(memory, fetch_fn=fetch_fn))

    assert calls == ["https://a.example.com/rss"]
    assert result["polled"] == 1
    assert result["new"] == 2
    assert result["per_feed"] == [
        {"url": "https://a.example.com/rss", "status": "ok", "new": 2, "duplicates": 0}
    ]

    feeds = feed_registry.list_feeds(memory)
    assert feeds[0]["last_polled"] is not None

    episodes = list((memory / "episodes").glob("ep_*.md"))
    entities = list((memory / "entities").glob("media-*.md"))
    assert len(episodes) == 2
    assert len(entities) == 2


def test_poll_feeds_only_ingests_new_items_on_second_poll(tmp_path, monkeypatch):
    _offline_enrich(monkeypatch)
    memory = _memory(tmp_path)
    feed_registry.subscribe_feed(memory, "https://a.example.com/rss")

    run(feed_registry.poll_feeds(memory, fetch_fn=lambda url: RSS_FEED_A))

    # The feed gained one new item since the last poll — only that one should
    # be ingested (existing url-hash dedup in media_ingestor).
    result = run(feed_registry.poll_feeds(memory, fetch_fn=lambda url: RSS_FEED_A_UPDATED))

    assert result["polled"] == 1
    assert result["new"] == 1
    assert result["per_feed"][0]["duplicates"] == 2

    entities = list((memory / "entities").glob("media-*.md"))
    assert len(entities) == 3


def test_poll_feeds_polls_multiple_subscriptions(tmp_path, monkeypatch):
    _offline_enrich(monkeypatch)
    memory = _memory(tmp_path)
    feed_registry.subscribe_feed(memory, "https://a.example.com/rss")
    feed_registry.subscribe_feed(memory, "https://b.example.com/rss")

    xml_by_url = {
        "https://a.example.com/rss": RSS_FEED_A,
        "https://b.example.com/rss": RSS_FEED_B,
    }

    result = run(feed_registry.poll_feeds(memory, fetch_fn=lambda url: xml_by_url[url]))

    assert result["polled"] == 2
    assert result["new"] == 3  # 2 from feed A + 1 from feed B


def test_poll_feeds_accepts_async_fetch_fn(tmp_path, monkeypatch):
    _offline_enrich(monkeypatch)
    memory = _memory(tmp_path)
    feed_registry.subscribe_feed(memory, "https://a.example.com/rss")

    async def async_fetch(url):
        return RSS_FEED_A

    result = run(feed_registry.poll_feeds(memory, fetch_fn=async_fetch))
    assert result["new"] == 2


def test_poll_feeds_no_subscriptions_is_noop(tmp_path, monkeypatch):
    _offline_enrich(monkeypatch)
    memory = _memory(tmp_path)
    result = run(feed_registry.poll_feeds(memory, fetch_fn=lambda url: RSS_FEED_A))
    assert result == {"polled": 0, "new": 0, "per_feed": []}


# --- poll_feeds: network gate -----------------------------------------------


def test_poll_feeds_skips_when_no_fetch_and_gate_closed(tmp_path, monkeypatch):
    monkeypatch.delenv("CICADA_ALLOW_FEED_FETCH", raising=False)
    memory = _memory(tmp_path)
    feed_registry.subscribe_feed(memory, "https://a.example.com/rss")
    feed_registry.subscribe_feed(memory, "https://b.example.com/rss")

    result = run(feed_registry.poll_feeds(memory))

    assert result == {"polled": 0, "new": 0, "skipped_no_network": 2, "per_feed": []}

    # last_polled must remain untouched — nothing was actually polled.
    feeds = feed_registry.list_feeds(memory)
    assert all(f["last_polled"] is None for f in feeds)


def test_poll_feeds_allow_fetch_true_without_fetch_fn_uses_default(tmp_path, monkeypatch):
    """allow_fetch=True with no fetch_fn falls through to the default HTTP
    fetch — we don't want a real network call here, so just assert it is NOT
    the skipped_no_network no-op (the default fetch will fail against a bogus
    host, which must be recorded as a per-feed error, not raised)."""
    memory = _memory(tmp_path)
    feed_registry.subscribe_feed(memory, "https://this-host-does-not-resolve.invalid/rss")

    result = run(feed_registry.poll_feeds(memory, allow_fetch=True))

    assert "skipped_no_network" not in result
    assert result["polled"] == 1
    assert result["per_feed"][0]["status"] == "error"


# --- poll_feeds: malformed / unreachable feed never raises ------------------


def test_poll_feeds_records_malformed_feed_without_raising(tmp_path, monkeypatch):
    _offline_enrich(monkeypatch)
    memory = _memory(tmp_path)
    feed_registry.subscribe_feed(memory, "https://a.example.com/rss")
    feed_registry.subscribe_feed(memory, "https://bad.example.com/rss")

    def fetch_fn(url):
        if "bad" in url:
            return NOT_XML
        return RSS_FEED_A

    result = run(feed_registry.poll_feeds(memory, fetch_fn=fetch_fn))

    # parse_rss on non-XML yields [] -> ingest_feed returns (0, 0), not an
    # error — but the feed is still successfully polled.
    assert result["polled"] == 2
    statuses = {f["url"]: f["status"] for f in result["per_feed"]}
    assert statuses["https://a.example.com/rss"] == "ok"
    assert statuses["https://bad.example.com/rss"] == "ok"

    a_entry = next(f for f in result["per_feed"] if f["url"] == "https://a.example.com/rss")
    bad_entry = next(f for f in result["per_feed"] if f["url"] == "https://bad.example.com/rss")
    assert a_entry["new"] == 2
    assert bad_entry["new"] == 0


def test_poll_feeds_records_unreachable_feed_error_and_continues(tmp_path, monkeypatch):
    _offline_enrich(monkeypatch)
    memory = _memory(tmp_path)
    feed_registry.subscribe_feed(memory, "https://unreachable.example.com/rss")
    feed_registry.subscribe_feed(memory, "https://a.example.com/rss")

    def fetch_fn(url):
        if "unreachable" in url:
            raise ConnectionError("could not connect")
        return RSS_FEED_A

    result = run(feed_registry.poll_feeds(memory, fetch_fn=fetch_fn))

    assert result["polled"] == 2
    assert result["new"] == 2  # only the reachable feed contributed
    statuses = {f["url"]: f["status"] for f in result["per_feed"]}
    assert statuses["https://unreachable.example.com/rss"] == "error"
    assert statuses["https://a.example.com/rss"] == "ok"

    # last_polled is stamped even for the errored feed (we did attempt it).
    feeds = {f["url"]: f for f in feed_registry.list_feeds(memory)}
    assert feeds["https://unreachable.example.com/rss"]["last_polled"] is not None


# --- endpoints ---------------------------------------------------------------


def _make_client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from api import config, main

    _offline_enrich(monkeypatch)
    memory = _memory(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.delenv("CICADA_ALLOW_FEED_FETCH", raising=False)
    config.get_settings.cache_clear()
    return TestClient(main.app), memory


def test_endpoint_subscribe_and_list(tmp_path, monkeypatch):
    client, memory = _make_client(tmp_path, monkeypatch)

    resp = client.post(
        "/sources/feeds", json={"url": "https://a.example.com/rss", "tags": ["news"]}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["url"] == "https://a.example.com/rss"

    resp2 = client.get("/sources/feeds")
    assert resp2.status_code == 200
    body = resp2.json()
    assert body["total"] == 1
    assert body["feeds"][0]["url"] == "https://a.example.com/rss"


def test_endpoint_subscribe_rejects_bad_url(tmp_path, monkeypatch):
    client, _ = _make_client(tmp_path, monkeypatch)
    resp = client.post("/sources/feeds", json={"url": "not-a-url"})
    assert resp.status_code == 422


def test_endpoint_subscribe_is_idempotent(tmp_path, monkeypatch):
    client, _ = _make_client(tmp_path, monkeypatch)
    client.post("/sources/feeds", json={"url": "https://a.example.com/rss"})
    client.post("/sources/feeds", json={"url": "https://a.example.com/rss"})

    resp = client.get("/sources/feeds")
    assert resp.json()["total"] == 1


def test_endpoint_unsubscribe(tmp_path, monkeypatch):
    client, _ = _make_client(tmp_path, monkeypatch)
    client.post("/sources/feeds", json={"url": "https://a.example.com/rss"})

    resp = client.request(
        "DELETE", "/sources/feeds", json={"url": "https://a.example.com/rss"}
    )
    assert resp.status_code == 200, resp.text

    resp2 = client.get("/sources/feeds")
    assert resp2.json()["total"] == 0


def test_endpoint_unsubscribe_missing_returns_404(tmp_path, monkeypatch):
    client, _ = _make_client(tmp_path, monkeypatch)
    resp = client.request(
        "DELETE", "/sources/feeds", json={"url": "https://nope.example.com/rss"}
    )
    assert resp.status_code == 404


def test_endpoint_poll_feeds_no_network_by_default(tmp_path, monkeypatch):
    client, _ = _make_client(tmp_path, monkeypatch)
    client.post("/sources/feeds", json={"url": "https://a.example.com/rss"})

    resp = client.post("/sources/poll-feeds")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["polled"] == 0
    assert body["skipped_no_network"] == 1


def test_endpoint_poll_feeds_no_subscriptions(tmp_path, monkeypatch):
    client, _ = _make_client(tmp_path, monkeypatch)
    resp = client.post("/sources/poll-feeds")
    assert resp.status_code == 200
    assert resp.json() == {"polled": 0, "new": 0, "per_feed": []}
