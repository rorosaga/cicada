"""Hermetic tests for the media/sources ingestion pipeline (M4).

Covers:
- ``parse_rss`` (RSS 2.0 + Atom, namespace-tolerant, YouTube canonicalization,
  in-batch dedup) — the M4 connector gap;
- ``parse_upload`` dispatch for ``.xml``/``.atom``/``.rss`` feed files;
- end-to-end ``ingest_batch`` (enrichment monkeypatched to the offline fallback,
  so no network) writing episodes + ``media-*`` entities and deduping on a second
  ingest via ``url_index.json``;
- ``compute_relevance`` — the §3.4 relevance metric used by the feed view;
- a couple of cheap backfill tests for previously-untested
  ``normalize_url`` / ``url_hash`` / ``parse_netscape_bookmarks``.

Every test builds its own ``tmp_path`` workspace; the real ``memory/`` is never
touched. No live network: ``ingest_batch`` enrichment is monkeypatched to the
URL-only fallback (matching the "offline-safe" requirement).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest

from api.services import markdown_parser, media_ingestor
from api.services.media_ingestor import MediaMeta, RawItem


def run(coro):
    return asyncio.run(coro)


# --- Fixture feeds ---------------------------------------------------------

RSS_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
  <channel>
    <title>Example Blog</title>
    <link>https://example.com</link>
    <description>A test feed</description>
    <item>
      <title>First Post</title>
      <link>https://example.com/first-post</link>
      <description>An intro to the first post.</description>
      <category>python</category>
      <category>testing</category>
      <pubDate>Mon, 16 Jun 2026 10:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Second Post</title>
      <link>https://example.com/second-post</link>
      <content:encoded><![CDATA[<p>Rich body here.</p>]]></content:encoded>
      <pubDate>Tue, 17 Jun 2026 10:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Watch This</title>
      <link>https://youtu.be/dQw4w9WgXcQ</link>
    </item>
  </channel>
</rss>
"""

ATOM_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom Example</title>
  <link href="https://atom.example.com"/>
  <entry>
    <title>Atom Entry One</title>
    <link rel="alternate" href="https://atom.example.com/one"/>
    <summary>Summary of entry one.</summary>
    <category term="news"/>
    <updated>2026-06-17T10:00:00Z</updated>
  </entry>
  <entry>
    <title>Atom Entry Two</title>
    <link href="https://atom.example.com/two"/>
  </entry>
</feed>
"""

# A feed with a duplicate link, used to assert in-batch dedup downstream.
RSS_WITH_DUP = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>Dup</title>
  <item><title>A</title><link>https://dup.example.com/a</link></item>
  <item><title>A again</title><link>https://dup.example.com/a</link></item>
  <item><title>B</title><link>https://dup.example.com/b</link></item>
</channel></rss>
"""


# --- parse_rss -------------------------------------------------------------


def test_parse_rss_basic_fields():
    items = media_ingestor.parse_rss(RSS_FEED)
    assert len(items) == 3
    first = items[0]
    assert first.title == "First Post"
    assert first.url == "https://example.com/first-post"
    assert "python" in first.tags and "testing" in first.tags
    assert first.note  # description carried into note


def test_parse_rss_content_encoded_as_note():
    items = media_ingestor.parse_rss(RSS_FEED)
    second = items[1]
    assert second.title == "Second Post"
    assert second.note is not None and "Rich body" in second.note


def test_parse_rss_youtube_link_preserved_for_canonicalization():
    items = media_ingestor.parse_rss(RSS_FEED)
    yt = items[2]
    # parse_rss keeps the raw link; normalize_url canonicalizes downstream.
    assert "youtu.be/dQw4w9WgXcQ" in yt.url
    assert media_ingestor.normalize_url(yt.url) == (
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    )


def test_parse_atom_feed():
    items = media_ingestor.parse_rss(ATOM_FEED)
    assert len(items) == 2
    assert items[0].title == "Atom Entry One"
    # rel="alternate" link chosen.
    assert items[0].url == "https://atom.example.com/one"
    assert "news" in items[0].tags
    assert items[1].url == "https://atom.example.com/two"


def test_parse_rss_skips_entries_without_links():
    xml = """<rss version="2.0"><channel>
      <item><title>No link</title></item>
      <item><title>Has link</title><link>https://x.example.com/y</link></item>
    </channel></rss>"""
    items = media_ingestor.parse_rss(xml)
    assert len(items) == 1
    assert items[0].url == "https://x.example.com/y"


def test_parse_rss_malformed_returns_empty():
    assert media_ingestor.parse_rss("not xml at all <<<") == []
    assert media_ingestor.parse_rss("") == []


# --- parse_upload dispatch for feeds ---------------------------------------


@pytest.mark.parametrize("ext", [".xml", ".rss", ".atom"])
def test_parse_upload_routes_feed_extensions(ext):
    items, label, from_bookmark = media_ingestor.parse_upload(
        RSS_FEED.encode("utf-8"), f"feed{ext}"
    )
    assert len(items) == 3
    assert label == "RSS Feed"
    assert from_bookmark is False


def test_parse_upload_routes_atom():
    items, label, _ = media_ingestor.parse_upload(
        ATOM_FEED.encode("utf-8"), "feed.atom"
    )
    assert len(items) == 2
    assert label == "RSS Feed"


# --- end-to-end ingest (offline / monkeypatched enrichment) ----------------


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


def test_ingest_feed_creates_entities_and_episodes(tmp_path, monkeypatch):
    _offline_enrich(monkeypatch)
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    (memory / "entities").mkdir(parents=True)

    created, dups = run(
        media_ingestor.ingest_feed(RSS_FEED, memory, commit=False)
    )
    assert created == 3
    assert dups == 0

    episodes = list((memory / "episodes").glob("ep_*.md"))
    entities = list((memory / "entities").glob("media-*.md"))
    assert len(episodes) == 3
    assert len(entities) == 3

    # Frontmatter sanity on one entity.
    fm = markdown_parser.parse(entities[0]).frontmatter
    assert fm["type"] == "media"
    assert fm["status"] == "active"
    assert "media" in fm and "url" in fm["media"]


def test_ingest_feed_dedups_on_second_run(tmp_path, monkeypatch):
    _offline_enrich(monkeypatch)
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    (memory / "entities").mkdir(parents=True)

    run(media_ingestor.ingest_feed(RSS_FEED, memory, commit=False))
    created2, dups2 = run(
        media_ingestor.ingest_feed(RSS_FEED, memory, commit=False)
    )
    assert created2 == 0
    assert dups2 == 3  # every item already in the url_index


def test_ingest_feed_in_batch_dedup(tmp_path, monkeypatch):
    _offline_enrich(monkeypatch)
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    (memory / "entities").mkdir(parents=True)

    created, dups = run(
        media_ingestor.ingest_feed(RSS_WITH_DUP, memory, commit=False)
    )
    # 3 raw items, 2 unique urls (a appears twice) -> 2 created, 1 dropped.
    assert created == 2
    assert dups == 1


# --- compute_relevance (§3.4) ----------------------------------------------


def test_compute_relevance_high_for_fresh_high_confidence():
    now = datetime(2026, 6, 17)
    fm = {
        "confidence": 0.9,
        "last_referenced": "2026-06-17",
        "decay_rate": 0.03,
    }
    score = media_ingestor.compute_relevance(fm, now=now)
    assert 0.0 < score <= 1.0
    assert score > 0.8


def test_compute_relevance_decays_with_age():
    now = datetime(2026, 6, 17)
    fresh = {"confidence": 0.7, "last_referenced": "2026-06-17", "decay_rate": 0.05}
    old = {"confidence": 0.7, "last_referenced": "2026-01-01", "decay_rate": 0.05}
    assert media_ingestor.compute_relevance(fresh, now=now) > (
        media_ingestor.compute_relevance(old, now=now)
    )


def test_compute_relevance_personal_weight_boosts():
    now = datetime(2026, 6, 17)
    base = {"confidence": 0.6, "last_referenced": "2026-06-17", "decay_rate": 0.03}
    boosted = dict(base, personal_relevance_weight=2.0)
    assert media_ingestor.compute_relevance(boosted, now=now) > (
        media_ingestor.compute_relevance(base, now=now)
    )


def test_compute_relevance_clamped_to_unit_interval():
    now = datetime(2026, 6, 17)
    fm = {
        "confidence": 1.0,
        "last_referenced": "2026-06-17",
        "decay_rate": 0.0,
        "personal_relevance_weight": 10.0,
    }
    assert media_ingestor.compute_relevance(fm, now=now) <= 1.0


def test_compute_relevance_handles_missing_fields():
    # No frontmatter signals at all -> a sane non-crashing default in [0,1].
    score = media_ingestor.compute_relevance({}, now=datetime(2026, 6, 17))
    assert 0.0 <= score <= 1.0


# --- endpoint: POST /sources/rss + GET /sources?sort=relevance -------------


def _make_client(tmp_path, monkeypatch):
    """Build a TestClient with memory_path pointed at a tmp workspace and
    enrichment forced offline."""
    from fastapi.testclient import TestClient

    from api import main
    from api import config

    _offline_enrich(monkeypatch)
    memory = tmp_path / "memory"
    for sub in ("episodes", "entities", "sources"):
        (memory / sub).mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    return TestClient(main.app), memory


def test_post_rss_endpoint_ingests(tmp_path, monkeypatch):
    client, memory = _make_client(tmp_path, monkeypatch)
    resp = client.post("/sources/rss", json={"feedXml": RSS_FEED})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["episodesCreated"] == 3
    assert body["source"] == "RSS Feed"

    # Second ingest -> all dups.
    resp2 = client.post("/sources/rss", json={"feedXml": RSS_FEED})
    assert resp2.json()["episodesCreated"] == 0
    assert resp2.json()["duplicatesSkipped"] == 3


def test_post_rss_requires_input(tmp_path, monkeypatch):
    client, _ = _make_client(tmp_path, monkeypatch)
    resp = client.post("/sources/rss", json={})
    assert resp.status_code == 422


def test_get_sources_relevance_sort(tmp_path, monkeypatch):
    client, memory = _make_client(tmp_path, monkeypatch)
    client.post("/sources/rss", json={"feedXml": RSS_FEED})

    # Knock one entity's confidence down so relevance ordering is observable.
    entities = sorted((memory / "entities").glob("media-*.md"))
    parsed = markdown_parser.parse(entities[0])
    parsed.frontmatter["confidence"] = 0.1
    markdown_parser.write(entities[0], parsed.frontmatter, parsed.body)

    resp = client.get("/sources", params={"sort": "relevance"})
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 3
    rels = [i["relevance"] for i in items]
    assert rels == sorted(rels, reverse=True)
    # The knocked-down entity is last.
    assert items[-1]["mediaEntityId"] == entities[0].stem


# --- backfill: previously-untested primitives ------------------------------


def test_url_hash_stable_under_normalization():
    a = "https://www.youtube.com/watch?v=abc123&t=42s"
    b = "https://youtu.be/abc123"
    assert media_ingestor.url_hash(a) == media_ingestor.url_hash(b)


def test_normalize_url_strips_tracking_params():
    out = media_ingestor.normalize_url(
        "https://example.com/post?utm_source=x&id=7&fbclid=zzz"
    )
    assert "utm_source" not in out
    assert "fbclid" not in out
    assert "id=7" in out


def test_parse_netscape_bookmarks_extracts_links():
    html = """<!DOCTYPE NETSCAPE-Bookmark-file-1>
    <DL><p>
      <DT><H3>Reading</H3>
      <DL><p>
        <DT><A HREF="https://blog.example.com/a">Post A</A>
        <DT><A HREF="https://blog.example.com/b">Post B</A>
      </DL><p>
    </DL>"""
    items = media_ingestor.parse_netscape_bookmarks(html)
    urls = {i.url for i in items}
    assert "https://blog.example.com/a" in urls
    assert "https://blog.example.com/b" in urls
