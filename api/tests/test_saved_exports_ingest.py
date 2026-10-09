"""What an imported platform export writes: dedupe, idempotence and scrubbing.

Synthetic fixtures only (placeholder accounts and ids, ``example.com``). Every
ingest runs offline: ``enrich`` is replaced by the URL-only fallback.
"""

from __future__ import annotations

import asyncio
import io
import json
import zipfile

import pytest

from api.services import markdown_parser, media_ingestor, saved_exports
from api.services.connectors import reddit, x
from api.services.media_ingestor import MediaMeta


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def memory(tmp_path, monkeypatch):
    async def fake_enrich(url, client, from_bookmark_file=False):
        return MediaMeta(title=media_ingestor._fallback_title(url), description="",
                         site=media_ingestor._site_of(url),
                         media_type=media_ingestor._classify(url, from_bookmark_file))

    monkeypatch.setattr(media_ingestor, "enrich", fake_enrich)
    root = tmp_path / "memory"
    for sub in ("episodes", "entities", "sources"):
        (root / sub).mkdir(parents=True)
    return root


def _zip(members: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


REDDIT_CHILD = {"kind": "t3", "data": {
    "url": "https://example.com/an-article", "permalink": "/r/example/comments/abc1/a_post/",
    "subreddit": "example", "title": "A post"}}
REDDIT_EXPORT = _zip({"saved_posts.csv": "id,permalink\nabc1,https://www.reddit.com/r/example/comments/abc1/a_post/\n"})


def _ingest(items, memory):
    return run(media_ingestor.ingest_batch(items, memory, commit=False))


def _files(memory):
    return sorted(p.name for p in (memory / "episodes").iterdir()) + sorted(
        p.name for p in (memory / "entities").iterdir())


def test_a_reddit_link_post_saved_by_the_connector_is_not_imported_again_from_the_export(memory):
    assert _ingest(reddit.children_to_items([REDDIT_CHILD]), memory) == (1, 0)
    items, _, _ = media_ingestor.parse_upload(REDDIT_EXPORT, "reddit-export.zip")
    assert _ingest(items, memory) == (0, 1)
    assert len(list((memory / "entities").glob("media-*.md"))) == 1


def test_an_export_first_then_the_connector_is_still_one_page(memory):
    items, _, _ = media_ingestor.parse_upload(REDDIT_EXPORT, "reddit-export.zip")
    assert _ingest(items, memory) == (1, 0)
    assert _ingest(reddit.children_to_items([REDDIT_CHILD]), memory) == (0, 1)
    idx = media_ingestor.load_url_index(memory)
    # The outbound link is now an alias of the export's page, so a later
    # bookmark of it is a duplicate too — and every reader skips alias rows.
    outbound = idx[media_ingestor.url_hash("https://example.com/an-article")]
    assert outbound["alias_of"] == media_ingestor.url_hash(
        "https://www.reddit.com/r/example/comments/abc1/a_post/")
    assert sum(1 for e in idx.values() if not e.get("alias_of")) == 1


def test_an_x_like_of_a_post_the_connector_bookmarked_is_one_page(memory):
    connector_items = x.bookmarks_to_items([{"id": "1000000000000000001", "text": "alpha-project"}])
    assert _ingest(connector_items, memory) == (1, 0)
    like = 'window.YTD.like.part0 = [{"like": {"tweetId": "1000000000000000001", "fullText": "alpha-project"}}]'
    items, _, _ = media_ingestor.parse_upload(_zip({"data/like.js": like}), "twitter-archive.zip")
    assert _ingest(items, memory) == (0, 1)


def test_re_importing_the_same_archive_writes_nothing(memory):
    ig = {"saved_saved_collections": [
        {"title": "Collection", "string_map_data": {"Name": {"value": "alpha-project"}}},
        {"string_map_data": {"Name": {"value": "bob-example", "href": "https://www.instagram.com/p/AAA111/"},
                             "Added Time": {"timestamp": 1700000000}}},
    ]}
    data = _zip({"your_instagram_activity/saved/saved_collections.json": json.dumps(ig),
                 "your_instagram_activity/saved/saved_posts.json": json.dumps({"saved_saved_media": [
                     {"title": "bob-example", "string_map_data": {"Saved on": {
                         "href": "https://www.instagram.com/p/AAA111/", "timestamp": 1700000000}}}]})})
    items, _, _ = media_ingestor.parse_upload(data, "instagram.zip")
    assert _ingest(items, memory) == (1, 0)
    before = _files(memory), (memory / "sources" / "url_index.json").read_text()
    items, _, _ = media_ingestor.parse_upload(data, "instagram.zip")
    assert _ingest(items, memory) == (0, 1)
    assert (_files(memory), (memory / "sources" / "url_index.json").read_text()) == before

    [page] = list((memory / "entities").glob("media-*.md"))
    fm = markdown_parser.parse(page).frontmatter
    assert fm["folder"] == "alpha-project" and fm["saved_at"] == "2023-11-14" and fm["origin"] == "instagram-saved"


def test_a_secret_in_a_liked_posts_words_is_never_stored(memory):
    secret = "sk-" + "Q" * 24
    like = json.dumps([{"like": {"tweetId": "1000000000000000003", "fullText": f"leaked key {secret} oops"}}])
    items, _, _ = media_ingestor.parse_upload(
        _zip({"data/like.js": "window.YTD.like.part0 = " + like}), "twitter-archive.zip")
    assert _ingest(items, memory) == (1, 0)
    for path in list((memory / "episodes").iterdir()) + list((memory / "entities").iterdir()):
        assert secret not in path.read_text()
    [episode] = list((memory / "episodes").glob("*.md"))
    body = markdown_parser.parse(episode).body
    # Not the person's note: the post's words are its description.
    assert "## User note" not in body and "## Description" in body


def test_x_likes_are_staged_without_a_network_read(memory, monkeypatch):
    async def must_not_fetch(*args, **kwargs):
        raise AssertionError("an X archive item is never fetched at import")

    monkeypatch.setattr(media_ingestor, "enrich", must_not_fetch)
    data = saved_exports.parse_x_archive_js(
        b'window.YTD.like.part0 = [{"like": {"tweetId": "1000000000000000004", "fullText": "hello"}}]', "like")
    assert _ingest(data, memory) == (1, 0)
