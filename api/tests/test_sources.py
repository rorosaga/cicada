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
import json
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


def test_compute_relevance_never_fades_a_legacy_unmigrated_media_page():
    """M1: the rate comes from ``decay_policy.resolve``, not a raw read.

    A ``type: media`` page written before ``decay_class`` existed still carries
    the old ``decay_rate: 0.03``. Every other decay consumer (graph, entity
    engine, claim engine) resolves it to evergreen; the Feed used to be the one
    that kept fading it. An unmigrated bank must not disagree with itself.
    """
    now = datetime(2026, 6, 17)
    legacy_media = {
        "type": "media",
        "confidence": 0.8,
        "last_referenced": "2025-06-17",  # a year stale
        "decay_rate": 0.03,               # no decay_class:
    }
    assert media_ingestor.compute_relevance(legacy_media, now=now) == pytest.approx(0.8)


def test_compute_relevance_still_fades_an_ordinary_decaying_page():
    """The resolver's precedence is unchanged for the decaying classes."""
    now = datetime(2026, 6, 17)
    stale = {
        "type": "concept",
        "confidence": 0.8,
        "last_referenced": "2025-06-17",
        "decay_rate": 0.03,
    }
    assert media_ingestor.compute_relevance(stale, now=now) < 0.4


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


def test_post_rss_rejects_oversized_feed(tmp_path, monkeypatch):
    """A feed past MAX_BATCH must 413 (parity with /sources/upload) rather than
    ingesting unbounded inline. Build a feed with MAX_BATCH+1 unique items."""
    client, _ = _make_client(tmp_path, monkeypatch)
    n = media_ingestor.MAX_BATCH + 1
    items = "".join(
        f"<item><title>P{i}</title><link>https://big.example.com/{i}</link></item>"
        for i in range(n)
    )
    feed = f'<rss version="2.0"><channel><title>Big</title>{items}</channel></rss>'
    resp = client.post("/sources/rss", json={"feedXml": feed})
    assert resp.status_code == 413, resp.text
    assert str(media_ingestor.MAX_BATCH) in resp.json()["detail"]


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


def test_get_sources_populates_site_from_frontmatter(tmp_path, monkeypatch):
    """`site`/`channel` live in entity frontmatter (media.site/media.channel) but
    were never read back into the /sources response, leaving the Swift FeedRow
    site line and the site search filter permanently inert."""
    client, memory = _make_client(tmp_path, monkeypatch)
    client.post("/sources/rss", json={"feedXml": RSS_FEED})

    # Stamp a known site + channel onto one entity's frontmatter.
    entities = sorted((memory / "entities").glob("media-*.md"))
    parsed = markdown_parser.parse(entities[0])
    media = parsed.frontmatter.setdefault("media", {})
    media["site"] = "blog.example.com"
    media["channel"] = "Example Channel"
    markdown_parser.write(entities[0], parsed.frontmatter, parsed.body)

    resp = client.get("/sources")
    assert resp.status_code == 200
    by_id = {i["mediaEntityId"]: i for i in resp.json()["items"]}
    item = by_id[entities[0].stem]
    assert item["site"] == "blog.example.com"
    assert item["channel"] == "Example Channel"


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


# --- Source folder/category provenance --------------------------------------


def test_parse_netscape_bookmarks_carries_nearest_enclosing_folder():
    html = """<!DOCTYPE NETSCAPE-Bookmark-file-1>
    <DL><p>
      <DT><H3>Reading</H3>
      <DL><p>
        <DT><A HREF="https://blog.example.com/a">Post A</A>
        <DT><A HREF="https://blog.example.com/b">Post B</A>
      </DL><p>
    </DL>"""
    items = media_ingestor.parse_netscape_bookmarks(html)
    assert {i.folder for i in items} == {"Reading"}
    # Folder also lands as a tag (pre-existing behavior), now alongside the
    # dedicated ``folder`` field.
    assert all("Reading" in i.tags for i in items)


def test_parse_netscape_bookmarks_no_folder_is_none():
    html = """<!DOCTYPE NETSCAPE-Bookmark-file-1>
    <DL><p>
        <DT><A HREF="https://example.com/top">Top level</A>
    </DL>"""
    items = media_ingestor.parse_netscape_bookmarks(html)
    assert items[0].folder is None


def test_parse_chrome_bookmarks_json_nested_folders_yield_folder_paths():
    tree = {
        "roots": {
            "bookmark_bar": {
                "type": "folder",
                "name": "Bookmarks bar",
                "children": [
                    {
                        "type": "folder",
                        "name": "AI",
                        "children": [
                            {
                                "type": "folder",
                                "name": "Papers",
                                "children": [
                                    {
                                        "type": "url",
                                        "name": "Attention Is All You Need",
                                        "url": "https://example.com/attention",
                                    },
                                ],
                            },
                        ],
                    },
                    {
                        "type": "url",
                        "name": "Top level link",
                        "url": "https://example.com/top",
                    },
                ],
            },
            "other": {"type": "folder", "name": "Other bookmarks", "children": []},
        },
    }
    items = media_ingestor.parse_chrome_bookmarks_json(tree)
    by_url = {i.url: i for i in items}
    assert by_url["https://example.com/attention"].folder == "Bookmarks bar/AI/Papers"
    assert by_url["https://example.com/top"].folder == "Bookmarks bar"


def test_parse_safari_bookmarks_plist_nested_folder_path():
    import plistlib

    tree = {
        "Title": "",
        "WebBookmarkType": "WebBookmarkTypeList",
        "Children": [
            {
                "WebBookmarkType": "WebBookmarkTypeList",
                "Title": "Favorites",
                "Children": [
                    {
                        "WebBookmarkType": "WebBookmarkTypeList",
                        "Title": "Papers",
                        "Children": [
                            {
                                "WebBookmarkType": "WebBookmarkTypeLeaf",
                                "URLString": "https://example.org/paper",
                                "URIDictionary": {"title": "A Paper"},
                            },
                        ],
                    },
                    {
                        "WebBookmarkType": "WebBookmarkTypeLeaf",
                        "URLString": "https://example.org/top",
                        "URIDictionary": {"title": "Top"},
                    },
                ],
            },
        ],
    }
    data = plistlib.dumps(tree)
    items = media_ingestor.parse_safari_bookmarks(data)
    by_url = {i.url: i for i in items}
    assert by_url["https://example.org/paper"].folder == "Favorites/Papers"
    assert by_url["https://example.org/top"].folder == "Favorites"


def test_ingest_one_media_entity_carries_folder_frontmatter_and_tag(tmp_path, monkeypatch):
    _offline_enrich(monkeypatch)
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    (memory / "entities").mkdir(parents=True)

    item = RawItem(url="https://example.com/attention", folder="Bookmarks bar/AI/Papers")
    created, dups = run(
        media_ingestor.ingest_batch([item], memory, from_bookmark_file=True, commit=False)
    )
    assert created == 1
    assert dups == 0

    entities = list((memory / "entities").glob("media-*.md"))
    assert len(entities) == 1
    fm = markdown_parser.parse(entities[0]).frontmatter
    assert fm["folder"] == "Bookmarks bar/AI/Papers"
    assert "bookmarks-bar-ai-papers" in fm["tags"]

    episodes = list((memory / "episodes").glob("ep_*.md"))
    assert len(episodes) == 1
    ep_fm = markdown_parser.parse(episodes[0]).frontmatter
    assert ep_fm["folder"] == "Bookmarks bar/AI/Papers"


# --- G99d: RawItem.added -> episode/entity frontmatter -> url_index -------


def test_write_media_episode_records_saved_at_when_recoverable(tmp_path):
    item = RawItem(url="https://example.com/a", added="2023-06-15")
    meta = MediaMeta(title="A", media_type="url")
    episodes = tmp_path / "episodes"
    ep_id = media_ingestor.write_media_episode(episodes, item, meta, "media-a")

    parsed = markdown_parser.parse(episodes / f"{ep_id}.md")
    assert parsed.frontmatter["saved_at"] == "2023-06-15"
    # timestamp (ingest) is untouched and distinct from saved_at.
    assert parsed.frontmatter["timestamp"] != "2023-06-15"
    assert "**Originally saved:** 2023-06-15" in parsed.body


def test_write_media_episode_without_added_is_byte_identical_to_before(tmp_path):
    """Additive only: an item with no recoverable saved_at must behave exactly
    as before this feature existed — no `saved_at` key, no extra body line."""
    item = RawItem(url="https://example.com/a")
    meta = MediaMeta(title="A", media_type="url")
    episodes = tmp_path / "episodes"
    ep_id = media_ingestor.write_media_episode(episodes, item, meta, "media-a")

    parsed = markdown_parser.parse(episodes / f"{ep_id}.md")
    assert "saved_at" not in parsed.frontmatter
    assert "Originally saved" not in parsed.body


def test_write_media_entity_records_top_level_saved_at_when_recoverable(tmp_path):
    item = RawItem(url="https://example.com/a", added="2023-06-15")
    meta = MediaMeta(title="A", media_type="url")
    entities = tmp_path / "entities"
    media_ingestor.write_media_entity(entities, "media-a", item, meta, "ep_1")

    fm = markdown_parser.parse(entities / "media-a.md").frontmatter
    assert fm["saved_at"] == "2023-06-15"
    # The nested media.saved_at is a DIFFERENT, pre-existing field (despite the
    # name, always the ingest moment) and must be left completely alone.
    assert fm["media"]["saved_at"] != "2023-06-15"
    assert fm["media"]["saved_at"].endswith("Z")


def test_write_media_entity_without_added_is_byte_identical_to_before(tmp_path):
    item = RawItem(url="https://example.com/a")
    meta = MediaMeta(title="A", media_type="url")
    entities = tmp_path / "entities"
    media_ingestor.write_media_entity(entities, "media-a", item, meta, "ep_1")

    fm = markdown_parser.parse(entities / "media-a.md").frontmatter
    assert "saved_at" not in fm
    # The legacy nested ingest-time field is unaffected either way.
    assert "saved_at" in fm["media"]


def test_ingest_one_records_content_saved_at_in_url_index(tmp_path, monkeypatch):
    _offline_enrich(monkeypatch)
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    (memory / "entities").mkdir(parents=True)

    item = RawItem(url="https://example.com/a", added="2023-06-15")
    idx: dict = {}
    result = run(media_ingestor.ingest_one(item, memory, object(), idx))
    assert result.status == "created"

    entry = idx[media_ingestor.url_hash(item.url)]
    assert entry["content_saved_at"] == "2023-06-15"
    # Legacy ingest-time key is untouched and still distinct.
    assert entry["saved_at"] != "2023-06-15"


def test_ingest_one_without_added_omits_content_saved_at(tmp_path, monkeypatch):
    _offline_enrich(monkeypatch)
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    (memory / "entities").mkdir(parents=True)

    item = RawItem(url="https://example.com/a")
    idx: dict = {}
    result = run(media_ingestor.ingest_one(item, memory, object(), idx))
    assert result.status == "created"

    entry = idx[media_ingestor.url_hash(item.url)]
    assert "content_saved_at" not in entry


def test_parse_chrome_bookmarks_json_populates_added_from_date_added():
    tree = {
        "roots": {
            "bookmark_bar": {
                "type": "folder",
                "name": "Bookmarks bar",
                "children": [
                    {
                        "type": "url",
                        "name": "Attention",
                        "url": "https://example.com/attention",
                        # 2023-06-15T12:00:00Z as WebKit microseconds.
                        "date_added": "13331304000000000",
                    },
                ],
            },
        },
    }
    items = media_ingestor.parse_chrome_bookmarks_json(tree)
    assert items[0].added == "2023-06-15"


def test_parse_netscape_bookmarks_populates_added_from_add_date():
    html = """<!DOCTYPE NETSCAPE-Bookmark-file-1>
    <DL><p>
        <DT><A HREF="https://example.com/top" ADD_DATE="1686830400">Top</A>
    </DL>"""
    items = media_ingestor.parse_netscape_bookmarks(html)
    assert items[0].added == "2023-06-15"


def test_parse_youtube_takeout_populates_added_from_time():
    payload = [{"titleUrl": "https://www.youtube.com/watch?v=abc123", "title": "A Video",
                "time": "2023-06-15T12:00:00.000Z"}]
    items = media_ingestor.parse_youtube_takeout(json.dumps(payload).encode(), "watch-history.json")
    assert items[0].added == "2023-06-15"


def test_get_sources_recent_sort_prefers_content_saved_at(tmp_path, monkeypatch):
    """G99d: the Feed's default 'recent' sort must prefer the recovered true
    save date over the ingest timestamp — otherwise the whole point of the
    field (fixing a silent temporal-data-loss bug) is lost."""
    client, memory = _make_client(tmp_path, monkeypatch)

    idx = {
        # Item A: no recoverable save date -> falls back to a RECENT ingest.
        "hash-a": {
            "media_entity_id": "media-a", "episode_id": "ep_a",
            "url": "https://a.example", "title": "A", "media_type": "url",
            "thumbnail": None, "saved_at": "2026-08-30T12:00:00.000000Z",
        },
        # Item B: ingested a moment AFTER A, but its recovered save date is
        # from years earlier — it must sort AFTER A once fixed.
        "hash-b": {
            "media_entity_id": "media-b", "episode_id": "ep_b",
            "url": "https://b.example", "title": "B", "media_type": "url",
            "thumbnail": None, "saved_at": "2026-08-30T12:00:01.000000Z",
            "content_saved_at": "2023-01-01",
        },
    }
    media_ingestor.save_url_index(memory, idx)

    resp = client.get("/sources", params={"sort": "recent"})
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert [i["mediaEntityId"] for i in items] == ["media-a", "media-b"]
    by_id = {i["mediaEntityId"]: i for i in items}
    assert by_id["media-a"]["contentSavedAt"] is None
    assert by_id["media-b"]["contentSavedAt"] == "2023-01-01"


# --- G9 origin threading + media filename byte-cap (live-test findings) ----


def test_ingest_one_stamps_origin_on_episode_and_entity(tmp_path, monkeypatch):
    """RawItem.origin (set by bookmark_sync._tag_origin) must land in BOTH the
    episode and the media entity frontmatter, not just RawItem.tags."""
    _offline_enrich(monkeypatch)
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    (memory / "entities").mkdir(parents=True)

    item = RawItem(
        url="https://example.com/origin-test",
        title="Origin Test",
        tags=["chrome-bookmark"],
        origin="chrome-bookmark",
    )
    idx: dict = {}
    result = run(
        media_ingestor.ingest_one(item, memory, object(), idx, from_bookmark_file=True)
    )
    assert result.status == "created"

    ep_fm = markdown_parser.parse(memory / "episodes" / f"{result.episode_id}.md").frontmatter
    assert ep_fm["origin"] == "chrome-bookmark"

    ent_fm = markdown_parser.parse(
        memory / "entities" / f"{result.media_entity_id}.md"
    ).frontmatter
    assert ent_fm["origin"] == "chrome-bookmark"


def test_ingest_one_without_origin_omits_the_field(tmp_path, monkeypatch):
    """A plain /sources/save (no RawItem.origin) must not regress — no origin
    key at all, same as before G9 threading landed."""
    _offline_enrich(monkeypatch)
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    (memory / "entities").mkdir(parents=True)

    item = RawItem(url="https://example.com/no-origin")
    idx: dict = {}
    result = run(media_ingestor.ingest_one(item, memory, object(), idx))

    ep_fm = markdown_parser.parse(memory / "episodes" / f"{result.episode_id}.md").frontmatter
    assert "origin" not in ep_fm

    ent_fm = markdown_parser.parse(
        memory / "entities" / f"{result.media_entity_id}.md"
    ).frontmatter
    assert "origin" not in ent_fm


def test_ingest_one_media_entity_no_folder_omits_folder_tag(tmp_path, monkeypatch):
    _offline_enrich(monkeypatch)
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    (memory / "entities").mkdir(parents=True)

    item = RawItem(url="https://example.com/no-folder")
    run(media_ingestor.ingest_batch([item], memory, commit=False))

    entities = list((memory / "entities").glob("media-*.md"))
    fm = markdown_parser.parse(entities[0]).frontmatter
    assert fm["folder"] is None


def test_resync_same_url_with_folder_does_not_duplicate(tmp_path, monkeypatch):
    """Folder is provenance, not identity: re-seeing an already-ingested URL
    with a (possibly different) folder must still dedup on url_hash alone —
    no second episode/entity, no duplicate url_index entry."""
    _offline_enrich(monkeypatch)
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    (memory / "entities").mkdir(parents=True)

    first = RawItem(url="https://example.com/reused")
    created1, dups1 = run(
        media_ingestor.ingest_batch([first], memory, commit=False)
    )
    assert created1 == 1
    assert dups1 == 0

    # Same URL re-seen with a folder this time (e.g. the user later filed it
    # into a Chrome folder, or it shows up in a fresh bookmark export).
    second = RawItem(url="https://example.com/reused", folder="Bookmarks bar/Reading")
    created2, dups2 = run(
        media_ingestor.ingest_batch([second], memory, commit=False)
    )
    assert created2 == 0
    assert dups2 == 1

    assert len(list((memory / "episodes").glob("ep_*.md"))) == 1
    assert len(list((memory / "entities").glob("media-*.md"))) == 1


def test_bookmark_sync_tag_origin_sets_both_tags_and_origin_field():
    from api.services import bookmark_sync

    items = [RawItem(url="https://example.com/a")]
    tagged = bookmark_sync._tag_origin(items, "safari-bookmark")
    assert tagged[0].origin == "safari-bookmark"
    assert "safari-bookmark" in tagged[0].tags


def test_media_entity_id_caps_long_title_under_byte_limit():
    """A whole-paragraph OG title (heavy multi-byte emoji) must not blow past
    the 255-byte filesystem filename limit."""
    long_title = "💖🧸 moeru-ai airi " * 40  # far past 255 bytes once encoded
    meta = MediaMeta(title=long_title, media_type="bookmark")
    item = RawItem(url="https://github.com/moeru-ai/airi")

    entity_id = media_ingestor._media_entity_id(meta, item)
    filename_bytes = f"{entity_id}.md".encode("utf-8")

    assert len(filename_bytes) < 255
    assert entity_id.startswith("media-")


def test_media_entity_id_short_title_unaffected():
    """A normal, short title must not gain a hash suffix (no behavior change
    for the overwhelming majority of saves)."""
    meta = MediaMeta(title="A normal short title", media_type="bookmark")
    item = RawItem(url="https://example.com/normal")
    assert media_ingestor._media_entity_id(meta, item) == "media-a-normal-short-title"


def test_media_entity_id_no_collision_for_different_long_titles_same_prefix():
    """Two different long titles that share the same truncated prefix must not
    collide on the same filename — the hash suffix is derived from the URL."""
    prefix = "a" * 200
    meta1 = MediaMeta(title=prefix + " first article", media_type="bookmark")
    meta2 = MediaMeta(title=prefix + " second article", media_type="bookmark")
    item1 = RawItem(url="https://example.com/first")
    item2 = RawItem(url="https://example.com/second")

    id1 = media_ingestor._media_entity_id(meta1, item1)
    id2 = media_ingestor._media_entity_id(meta2, item2)

    assert id1 != id2
    assert len(f"{id1}.md".encode("utf-8")) < 255
    assert len(f"{id2}.md".encode("utf-8")) < 255


def test_truncate_utf8_never_splits_a_multibyte_character():
    # 3-byte-each characters; a byte budget that lands mid-character must back
    # off to the previous whole character, never raise, never emit invalid utf-8.
    s = "漢" * 50  # a CJK character, 3 bytes in utf-8
    truncated, was_truncated = media_ingestor._truncate_utf8(s, 100)
    assert was_truncated is True
    truncated.encode("utf-8")  # must not raise
    assert len(truncated.encode("utf-8")) <= 100


def test_ingest_one_with_long_title_end_to_end_creates_valid_files(tmp_path, monkeypatch):
    """The whole ingest_one path must succeed (no OSError) for a title long
    enough to have crashed pre-fix, and the resulting file must be readable."""
    _offline_enrich(monkeypatch)
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    (memory / "entities").mkdir(parents=True)

    first = RawItem(url="https://example.com/reused")
    created1, dups1 = run(
        media_ingestor.ingest_batch([first], memory, commit=False)
    )
    assert created1 == 1
    assert dups1 == 0

    # Same URL re-seen with a folder this time (e.g. the user later filed it
    # into a Chrome folder, or it shows up in a fresh bookmark export).
    second = RawItem(url="https://example.com/reused", folder="Bookmarks bar/Reading")
    created2, dups2 = run(
        media_ingestor.ingest_batch([second], memory, commit=False)
    )
    assert created2 == 0
    assert dups2 == 1

    assert len(list((memory / "episodes").glob("ep_*.md"))) == 1
    assert len(list((memory / "entities").glob("media-*.md"))) == 1
    long_title = "💖🧸 " * 60

    async def fake_enrich(url, client, from_bookmark_file=False):
        return MediaMeta(title=long_title, description="", site="github.com", media_type="bookmark")

    monkeypatch.setattr(media_ingestor, "enrich", fake_enrich)

    item = RawItem(url="https://github.com/moeru-ai/airi", origin="chrome-bookmark")
    idx: dict = {}
    result = run(
        media_ingestor.ingest_one(item, memory, object(), idx, from_bookmark_file=True)
    )
    assert result.status == "created"

    entity_path = memory / "entities" / f"{result.media_entity_id}.md"
    assert entity_path.exists()
    assert len(entity_path.name.encode("utf-8")) < 255
    fm = markdown_parser.parse(entity_path).frontmatter
    assert fm["origin"] == "chrome-bookmark"


# --- G47: saved-content importers (Instagram saved + YouTube playlists) ----

INSTAGRAM_SAVED_FLAT = {
    "saved_saved_media": [
        {
            "title": "account_one",
            "string_map_data": {
                "Saved on": {
                    "href": "https://www.instagram.com/reel/AAA111/",
                    "timestamp": 1699000000,
                }
            },
        },
        {
            "title": "account_two",
            "string_map_data": {
                "Saved on": {
                    "href": "https://www.instagram.com/reel/BBB222/",
                    "timestamp": 1699000001,
                }
            },
        },
    ]
}

INSTAGRAM_SAVED_COLLECTIONS = {
    "saved_saved_media": {
        "Recipes": [
            {
                "title": "chef_account",
                "string_map_data": {
                    "Saved on": {
                        "href": "https://www.instagram.com/p/CCC333/",
                        "timestamp": 1699000002,
                    }
                },
            },
        ],
        "Travel": [
            {
                "title": "wanderer_account",
                "string_map_data": {
                    "Saved on": {
                        "href": "https://www.instagram.com/p/DDD444/",
                        "timestamp": 1699000003,
                    }
                },
            },
        ],
    }
}

YOUTUBE_PLAYLIST_CSV = (
    "Video ID,Playlist Video Creation Timestamp\n"
    "abc123,2023-11-01T00:00:00Z\n"
    "def456,2023-11-02T00:00:00Z\n"
)


def test_parse_instagram_saved_flat_extracts_items():
    items = media_ingestor.parse_instagram_saved(INSTAGRAM_SAVED_FLAT)
    assert len(items) == 2
    urls = {i.url for i in items}
    assert "https://www.instagram.com/reel/AAA111/" in urls
    assert "https://www.instagram.com/reel/BBB222/" in urls
    assert all(i.origin == "instagram-saved" for i in items)
    # No collection -> default "Saved" folder.
    assert all(i.folder == "Saved" for i in items)
    titles = {i.title for i in items}
    assert titles == {"account_one", "account_two"}


def test_parse_instagram_saved_collections_variant_maps_folder():
    items = media_ingestor.parse_instagram_saved(INSTAGRAM_SAVED_COLLECTIONS)
    assert len(items) == 2
    by_url = {i.url: i for i in items}
    recipes = by_url["https://www.instagram.com/p/CCC333/"]
    travel = by_url["https://www.instagram.com/p/DDD444/"]
    assert recipes.folder == "Recipes"
    assert recipes.origin == "instagram-saved"
    assert travel.folder == "Travel"


def test_parse_instagram_saved_tolerates_unknown_keys():
    data = {
        "saved_saved_media": [
            {
                "title": "acct",
                "unexpected_field": {"nested": True},
                "string_map_data": {
                    "Saved on": {"href": "https://www.instagram.com/reel/ZZZ/", "timestamp": 1}
                },
            }
        ],
        "some_other_top_level_key": "ignored",
    }
    items = media_ingestor.parse_instagram_saved(data)
    assert len(items) == 1
    assert items[0].url == "https://www.instagram.com/reel/ZZZ/"


def test_parse_instagram_saved_malformed_returns_empty():
    assert media_ingestor.parse_instagram_saved({}) == []
    assert media_ingestor.parse_instagram_saved({"saved_saved_media": "not a list or dict"}) == []
    assert media_ingestor.parse_instagram_saved("not even a dict") == []


def test_is_instagram_saved_json_sniff_rule():
    assert media_ingestor._is_instagram_saved_json(INSTAGRAM_SAVED_FLAT) is True
    assert media_ingestor._is_instagram_saved_json({"saved_collections": []}) is True
    assert media_ingestor._is_instagram_saved_json({"roots": {}}) is False
    assert media_ingestor._is_instagram_saved_json(["a", "b"]) is False


def test_parse_upload_routes_instagram_json():
    items, label, from_bookmark = media_ingestor.parse_upload(
        json.dumps(INSTAGRAM_SAVED_FLAT).encode("utf-8"), "saved_posts.json"
    )
    assert label == "Instagram Saved"
    assert from_bookmark is False
    assert len(items) == 2


def test_parse_upload_generic_json_url_list_unaffected_by_instagram_sniff():
    """A plain JSON URL list (no ``saved_*`` key) must still hit the old
    generic-list path, not misfire into the Instagram parser."""
    items, label, _ = media_ingestor.parse_upload(
        json.dumps(["https://example.com/a", "https://example.com/b"]).encode("utf-8"),
        "links.json",
    )
    assert label == "URL List"
    assert len(items) == 2
    assert items[0].origin is None


def test_ingest_instagram_saved_stamps_origin_and_folder_end_to_end(tmp_path, monkeypatch):
    _offline_enrich(monkeypatch)
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    (memory / "entities").mkdir(parents=True)

    items = media_ingestor.parse_instagram_saved(INSTAGRAM_SAVED_COLLECTIONS)
    created, dups = run(media_ingestor.ingest_batch(items, memory, commit=False))
    assert created == 2
    assert dups == 0

    entities = list((memory / "entities").glob("media-*.md"))
    assert len(entities) == 2
    folders = set()
    for path in entities:
        fm = markdown_parser.parse(path).frontmatter
        assert fm["origin"] == "instagram-saved"
        folders.add(fm["folder"])
    assert folders == {"Recipes", "Travel"}

    episodes = list((memory / "episodes").glob("ep_*.md"))
    assert len(episodes) == 2
    for path in episodes:
        ep_fm = markdown_parser.parse(path).frontmatter
        assert ep_fm["origin"] == "instagram-saved"


def test_ingest_linkedin_saved_performs_zero_http_calls(tmp_path, monkeypatch):
    """Fix round (G71 §3 task-3-review.md Critical): a STAGED (non-preview)
    LinkedIn ingest must never touch the network — LinkedIn §8.2 bans fetching
    the post body, and that's a binding rail, not just a preview-time promise.

    Deliberately does NOT use ``_offline_enrich`` (which would monkeypatch
    ``enrich`` itself away and prove nothing about the real short-circuit).
    Instead this spies on the actual ``httpx.AsyncClient.get`` the real
    ``enrich``/``_enrich_opengraph`` path would call, so a regression that
    re-opens the ToS violation fails loudly here.
    """
    import httpx

    calls: list[str] = []

    async def spy_get(self, url, *args, **kwargs):
        calls.append(str(url))
        raise AssertionError(f"unexpected network fetch during LinkedIn ingest: {url}")

    monkeypatch.setattr(httpx.AsyncClient, "get", spy_get)

    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    (memory / "entities").mkdir(parents=True)

    item = RawItem(
        url="https://www.linkedin.com/posts/aaa",
        added="2026-01-02 10:00:00",
        folder="Saved Items",
        origin="linkedin-saved",
    )
    created, dups = run(media_ingestor.ingest_batch([item], memory, commit=False))

    assert created == 1
    assert dups == 0
    assert calls == [], "enrich() must short-circuit a linkedin.com URL before any client.get"

    entities = list((memory / "entities").glob("media-*.md"))
    assert len(entities) == 1
    fm = markdown_parser.parse(entities[0]).frontmatter
    assert fm["media"]["media_type"] == "linkedin"
    assert fm["origin"] == "linkedin-saved"


# --- YouTube playlist CSV ----------------------------------------------------


def test_parse_youtube_playlist_csv_builds_urls_and_folder_from_filename():
    items = media_ingestor.parse_youtube_playlist_csv(
        YOUTUBE_PLAYLIST_CSV.encode("utf-8"), "Watch later-videos.csv"
    )
    assert len(items) == 2
    assert items[0].url == "https://www.youtube.com/watch?v=abc123"
    assert items[1].url == "https://www.youtube.com/watch?v=def456"
    assert all(i.folder == "Watch later" for i in items)
    assert all(i.origin == "youtube-playlist" for i in items)
    assert all(i.title is None for i in items)


def test_parse_youtube_playlist_csv_strips_videos_suffix_preserving_case():
    items = media_ingestor.parse_youtube_playlist_csv(
        YOUTUBE_PLAYLIST_CSV.encode("utf-8"), "My Robotics Faves-videos.csv"
    )
    assert all(i.folder == "My Robotics Faves" for i in items)


def test_parse_youtube_playlist_csv_video_id_alt_header():
    csv_text = "Video Id\nxyz789\n"
    items = media_ingestor.parse_youtube_playlist_csv(csv_text.encode("utf-8"), "Custom-videos.csv")
    assert len(items) == 1
    assert items[0].url == "https://www.youtube.com/watch?v=xyz789"


def test_parse_youtube_playlist_csv_unrecognized_returns_empty_never_raises():
    assert media_ingestor.parse_youtube_playlist_csv(b"a,b,c\n1,2,3\n", "random.csv") == []
    assert media_ingestor.parse_youtube_playlist_csv(b"", "empty.csv") == []
    assert media_ingestor.parse_youtube_playlist_csv(b"\xff\xfe\x00garbage", "bad.csv") == []


def test_parse_upload_routes_playlist_csv():
    items, label, from_bookmark = media_ingestor.parse_upload(
        YOUTUBE_PLAYLIST_CSV.encode("utf-8"), "Watch later-videos.csv"
    )
    assert label == "YouTube Playlist"
    assert from_bookmark is False
    assert len(items) == 2
    assert items[0].folder == "Watch later"


def test_parse_upload_random_csv_still_falls_through_to_url_list():
    """A CSV with no video-id column and no url/link/href column yields []
    (via the existing ``parse_csv_url_list`` fallback), never raises."""
    items, label, _ = media_ingestor.parse_upload(b"name,age\nAda,36\n", "people.csv")
    assert label == "URL List"
    assert items == []


def test_parse_upload_csv_with_url_column_still_works_unaffected():
    items, label, _ = media_ingestor.parse_upload(
        b"url,note\nhttps://example.com/x,hi\n", "links.csv"
    )
    assert label == "URL List"
    assert len(items) == 1
    assert items[0].url == "https://example.com/x"


def test_ingest_youtube_playlist_creates_episode_and_entity_with_folder(tmp_path, monkeypatch):
    _offline_enrich(monkeypatch)
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    (memory / "entities").mkdir(parents=True)

    items, _, _ = media_ingestor.parse_upload(
        YOUTUBE_PLAYLIST_CSV.encode("utf-8"), "Watch later-videos.csv"
    )
    created, dups = run(media_ingestor.ingest_batch(items, memory, commit=False))
    assert created == 2
    assert dups == 0

    entities = list((memory / "entities").glob("media-*.md"))
    assert len(entities) == 2
    for path in entities:
        fm = markdown_parser.parse(path).frontmatter
        assert fm["origin"] == "youtube-playlist"
        assert fm["folder"] == "Watch later"
        assert fm["media"]["media_type"] == "youtube"


# --- YouTube Takeout zip walk -------------------------------------------------


def _build_takeout_zip() -> bytes:
    import io
    import zipfile

    watch_history = json.dumps([
        {
            "titleUrl": "https://www.youtube.com/watch?v=wat001",
            "title": "Watched Something",
            "time": "2023-11-01T00:00:00Z",
        }
    ])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "Takeout/YouTube and YouTube Music/playlists/Watch later-videos.csv",
            YOUTUBE_PLAYLIST_CSV,
        )
        zf.writestr(
            "Takeout/YouTube and YouTube Music/playlists/My Faves-videos.csv",
            "Video Id\nzzz999\n",
        )
        zf.writestr(
            "Takeout/YouTube and YouTube Music/history/watch-history.json",
            watch_history,
        )
        # Unrecognized member -> must be skipped, never raise.
        zf.writestr("Takeout/YouTube and YouTube Music/other-file.txt", "ignore me")
    return buf.getvalue()


def test_parse_youtube_takeout_zip_mixed_content():
    data = _build_takeout_zip()
    items = media_ingestor.parse_youtube_takeout_zip(data)
    # 2 items from Watch later, 1 from My Faves, 1 from watch-history.json.
    assert len(items) == 4
    urls = {i.url for i in items}
    assert "https://www.youtube.com/watch?v=abc123" in urls
    assert "https://www.youtube.com/watch?v=def456" in urls
    assert "https://www.youtube.com/watch?v=zzz999" in urls
    assert "https://www.youtube.com/watch?v=wat001" in urls

    by_url = {i.url: i for i in items}
    assert by_url["https://www.youtube.com/watch?v=abc123"].folder == "Watch later"
    assert by_url["https://www.youtube.com/watch?v=abc123"].origin == "youtube-playlist"
    assert by_url["https://www.youtube.com/watch?v=zzz999"].folder == "My Faves"
    # watch-history.json flows through parse_youtube_takeout, which doesn't
    # set folder/origin (distinct code path from the playlist CSVs).
    assert by_url["https://www.youtube.com/watch?v=wat001"].title == "Watched Something"


def test_parse_youtube_takeout_zip_unrecognized_or_corrupt_returns_empty():
    assert media_ingestor.parse_youtube_takeout_zip(b"not a zip file") == []
    assert media_ingestor.parse_youtube_takeout_zip(b"") == []


def test_parse_upload_routes_takeout_zip():
    data = _build_takeout_zip()
    items, label, from_bookmark = media_ingestor.parse_upload(data, "takeout.zip")
    assert label == "YouTube Takeout (zip)"
    assert from_bookmark is False
    assert len(items) == 4


def test_parse_upload_of_a_non_takeout_zip_labels_it_generically(tmp_path):
    """L4 (final review): a zip is sniffed by extension alone, but
    `parse_youtube_takeout_zip` only recognizes `playlists/*.csv` /
    `watch-history.json` — an Instagram/TikTok export zip (or anything else)
    must not be previewed as "YouTube Takeout (zip)" just because it's a
    .zip with nothing Takeout-shaped inside."""
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("saved_posts.json", "{}")
    data = buf.getvalue()

    items, label, from_bookmark = media_ingestor.parse_upload(data, "instagram_export.zip")
    assert items == []
    assert label == "ZIP archive"
    assert from_bookmark is False

    preview = media_ingestor.preview_upload(data, "instagram_export.zip")
    assert preview.recognized is False
    assert any(
        "Read this as ZIP archive" in w and "YouTube Takeout" not in w
        for w in preview.warnings
    )


def test_ingest_takeout_zip_dedups_on_second_import(tmp_path, monkeypatch):
    _offline_enrich(monkeypatch)
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    (memory / "entities").mkdir(parents=True)

    data = _build_takeout_zip()
    items, _, _ = media_ingestor.parse_upload(data, "takeout.zip")
    created1, dups1 = run(media_ingestor.ingest_batch(items, memory, commit=False))
    assert created1 == 4
    assert dups1 == 0

    items2, _, _ = media_ingestor.parse_upload(data, "takeout.zip")
    created2, dups2 = run(media_ingestor.ingest_batch(items2, memory, commit=False))
    assert created2 == 0
    assert dups2 == 4


# --- G71 §1: the reason on the episode body ---------------------------------


def test_write_media_episode_renders_the_saved_because_section(tmp_path):
    episodes = tmp_path / "episodes"
    item = media_ingestor.RawItem(
        url="https://example.com/recipe", reason="great for meal prep"
    )
    meta = MediaMeta(title="A Recipe", site="example.com", media_type="url")
    episode_id = media_ingestor.write_media_episode(episodes, item, meta, "media-a-recipe")

    body = (episodes / f"{episode_id}.md").read_text(encoding="utf-8")
    assert "## Saved because" in body
    assert "great for meal prep" in body


def test_write_media_episode_omits_the_section_without_a_reason(tmp_path):
    episodes = tmp_path / "episodes"
    item = media_ingestor.RawItem(url="https://example.com/plain")
    meta = MediaMeta(title="Plain", site="example.com", media_type="url")
    episode_id = media_ingestor.write_media_episode(episodes, item, meta, "media-plain")
    assert "Saved because" not in (episodes / f"{episode_id}.md").read_text(encoding="utf-8")
