"""Track C — two saved links with the same title must never share a page.

`_media_entity_id` slugs the title; `write_media_entity` overwrites. The URL-hash
suffix is added when the plain id names a page written for a different URL, and
an existing id is never renamed.
"""
from __future__ import annotations

import asyncio

from api.services import markdown_parser, media_ingestor
from api.services.media_ingestor import MediaMeta, RawItem


def _ingest(monkeypatch, tmp_path, url: str, title: str, idx: dict):
    async def enrich(u, client, from_bookmark_file=False):
        return MediaMeta(title=title, description="", site="example.com", media_type="bookmark")

    monkeypatch.setattr(media_ingestor, "enrich", enrich)
    return asyncio.run(media_ingestor.ingest_one(RawItem(url=url), tmp_path, None, idx))


def test_same_title_different_url_gets_its_own_page(tmp_path, monkeypatch):
    idx: dict = {}
    first = _ingest(monkeypatch, tmp_path, "https://example.com/one", "Home", idx)
    second = _ingest(monkeypatch, tmp_path, "https://example.com/two", "Home", idx)

    assert first.media_entity_id == "media-home"           # the plain id is unchanged
    assert second.media_entity_id != first.media_entity_id
    assert second.media_entity_id.startswith("media-home-")
    entities = tmp_path / "entities"
    pages = {p.stem: markdown_parser.parse(p).frontmatter for p in entities.glob("media-*.md")}
    assert set(pages) == {first.media_entity_id, second.media_entity_id}
    # Each page still says which link it is, and each index row points at its own page.
    assert pages[first.media_entity_id]["media"]["url"] == "https://example.com/one"
    assert pages[second.media_entity_id]["media"]["url"] == "https://example.com/two"
    for url, result in (("https://example.com/one", first), ("https://example.com/two", second)):
        assert idx[media_ingestor.url_hash(url)]["media_entity_id"] == result.media_entity_id


def test_the_suffixed_id_is_deterministic_and_a_third_link_gets_another(tmp_path, monkeypatch):
    idx: dict = {}
    _ingest(monkeypatch, tmp_path, "https://example.com/one", "Home", idx)
    second = _ingest(monkeypatch, tmp_path, "https://example.com/two", "Home", idx)
    third = _ingest(monkeypatch, tmp_path, "https://example.com/three", "Home", idx)
    assert third.media_entity_id not in ("media-home", second.media_entity_id)
    # A lost index must not fork the page either: the same URL finds its suffixed id again.
    again = _ingest(monkeypatch, tmp_path, "https://example.com/two", "Home", {})
    assert again.media_entity_id == second.media_entity_id


def test_an_existing_pages_id_is_stable_on_resave_and_lost_index(tmp_path, monkeypatch):
    idx: dict = {}
    first = _ingest(monkeypatch, tmp_path, "https://example.com/one", "Home", idx)
    # Saving the same link again is a duplicate that names the same page…
    dup = _ingest(monkeypatch, tmp_path, "https://example.com/one", "Home", idx)
    assert dup.status == "duplicate" and dup.media_entity_id == first.media_entity_id
    # …and with the index gone, the same URL rewrites its own page in place (no rename).
    again = _ingest(monkeypatch, tmp_path, "https://example.com/one", "Home", {})
    assert again.media_entity_id == first.media_entity_id
    assert [p.stem for p in (tmp_path / "entities").glob("media-*.md")] == [first.media_entity_id]


def test_a_legacy_page_without_url_hash_is_judged_by_its_url(tmp_path):
    entities = tmp_path / "entities"
    entities.mkdir()
    markdown_parser.write(entities / "media-home.md",
                          {"name": "Home", "type": "media", "media": {"url": "https://example.com/old"}}, "body")
    meta = MediaMeta(title="Home", media_type="bookmark")
    assert media_ingestor._media_entity_id(meta, RawItem(url="https://example.com/old"), entities) == "media-home"
    other = media_ingestor._media_entity_id(meta, RawItem(url="https://example.com/new"), entities)
    assert other.startswith("media-home-") and other != "media-home"


def test_no_directory_means_the_id_is_the_title_slug_alone():
    meta = MediaMeta(title="Home", media_type="bookmark")
    assert media_ingestor._media_entity_id(meta, RawItem(url="https://example.com/x")) == "media-home"


def test_batch_of_same_titled_links_writes_one_page_each(tmp_path, monkeypatch):
    async def enrich(u, client, from_bookmark_file=False):
        return MediaMeta(title="Untitled document", description="", site="example.com", media_type="bookmark")

    monkeypatch.setattr(media_ingestor, "enrich", enrich)
    items = [RawItem(url=f"https://example.com/doc/{n}") for n in range(4)]
    created, _ = asyncio.run(media_ingestor.ingest_batch(items, tmp_path, commit=False))
    assert created == 4
    idx = media_ingestor.load_url_index(tmp_path)
    ids = {row["media_entity_id"] for row in idx.values()}
    assert len(idx) == 4 and len(ids) == 4
    assert {p.stem for p in (tmp_path / "entities").glob("media-*.md")} == ids
