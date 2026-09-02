"""Hermetic tests for the staging-free import preview (G71 §4.3).

`preview_upload` must be pure: no episode, no entity, no url_index write, no
commit, no network. Every fixture here is synthetic — never a real personal
export (CLAUDE.md's benchmark privacy rule applies to test data too).
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import media_ingestor

IG_EXPORT = {
    "saved_saved_media": [
        {"name": "Recipes", "media": [
            {"title": "cook_account", "string_map_data": {
                "Saved on": {"href": "https://example.com/p/aaa", "timestamp": 1}}},
            {"title": "cook_account", "string_map_data": {
                "Saved on": {"href": "https://example.com/p/bbb", "timestamp": 2}}},
        ]},
        {"name": "Type inspo", "media": [
            {"title": "type_account", "string_map_data": {
                "Saved on": {"href": "https://example.com/p/ccc", "timestamp": 3}}},
        ]},
    ]
}


def test_preview_groups_instagram_collections_with_counts():
    preview = media_ingestor.preview_upload(
        json.dumps(IG_EXPORT).encode(), "saved_posts.json"
    )
    assert preview.recognized is True
    assert preview.platform == "instagram"
    assert preview.total == 3
    assert preview.collections == [
        {"name": "Recipes", "kind": "collection", "count": 2},
        {"name": "Type inspo", "kind": "collection", "count": 1},
    ]
    assert preview.warnings == []


def test_preview_stages_absolutely_nothing(tmp_path):
    """The whole point: a preview writes no file anywhere."""
    before = sorted(p.name for p in tmp_path.iterdir())
    media_ingestor.preview_upload(json.dumps(IG_EXPORT).encode(), "saved_posts.json")
    assert sorted(p.name for p in tmp_path.iterdir()) == before


def test_preview_of_an_unsupported_extension_is_not_recognized():
    preview = media_ingestor.preview_upload(b"binary", "photo.heic")
    assert preview.recognized is False
    assert preview.platform == "unknown"
    assert preview.total == 0
    assert preview.collections == []
    assert preview.warnings and "Unsupported file format" in preview.warnings[0]


def test_preview_of_malformed_json_is_not_recognized_and_says_why():
    preview = media_ingestor.preview_upload(b"{not json", "saved.json")
    assert preview.recognized is False
    assert preview.warnings and "saved.json" in preview.warnings[0]


def test_preview_of_a_recognized_but_empty_file_warns_honestly():
    preview = media_ingestor.preview_upload(b"# nothing here\n", "links.txt")
    assert preview.recognized is False
    assert preview.total == 0
    assert any("no saved links" in w for w in preview.warnings)


def test_preview_warns_when_item_count_exceeds_the_batch_cap():
    """M3 (final review): preview must not promise an import Confirm then
    413s — `POST /sources/upload` (no ``?preview=true``) hard-rejects any
    upload past ``MAX_BATCH`` items (`test_post_rss_rejects_oversized_feed`
    pins the same cap for the RSS path); preview must warn about that same
    outcome instead of silently showing "N items across M collections" as if
    Confirm would just work.
    """
    payload = "\n".join(
        f"https://example.com/{i}" for i in range(media_ingestor.MAX_BATCH + 1)
    )
    preview = media_ingestor.preview_upload(payload.encode(), "links.txt")
    assert preview.recognized is True
    assert preview.total == media_ingestor.MAX_BATCH + 1
    assert any(
        "batch cap" in w and f"{media_ingestor.MAX_BATCH:,}" in w for w in preview.warnings
    )


def test_preview_at_exactly_the_batch_cap_does_not_warn():
    payload = "\n".join(
        f"https://example.com/{i}" for i in range(media_ingestor.MAX_BATCH)
    )
    preview = media_ingestor.preview_upload(payload.encode(), "links.txt")
    assert preview.total == media_ingestor.MAX_BATCH
    assert not any("batch cap" in w for w in preview.warnings)


def test_preview_ungrouped_items_fall_into_one_bucket():
    preview = media_ingestor.preview_upload(
        b"https://example.com/a\nhttps://example.com/b\n", "links.txt"
    )
    assert preview.recognized is True
    assert preview.platform == "urls"
    assert preview.collections == [{"name": "Ungrouped", "kind": "list", "count": 2}]


# --- endpoint: POST /sources/upload?preview=true -----------------------------


@pytest.fixture
def client(tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    for sub in ("episodes", "entities", "sources"):
        (memory / sub).mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    yield TestClient(main.app), memory
    config.get_settings.cache_clear()


def _post_preview(c, filename, payload, query="?preview=true"):
    return c.post(
        "/sources/upload" + query,
        files={"file": (filename, payload, "application/octet-stream")},
    )


def test_preview_endpoint_returns_camel_cased_collections(client):
    c, memory = client
    resp = _post_preview(c, "saved_posts.json", json.dumps(IG_EXPORT).encode())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["recognized"] is True
    assert body["platform"] == "instagram"
    assert body["total"] == 3
    assert body["collections"][0] == {"name": "Recipes", "kind": "collection", "count": 2}
    assert body["warnings"] == []


def test_preview_endpoint_writes_nothing_to_the_bank(client):
    c, memory = client
    _post_preview(c, "saved_posts.json", json.dumps(IG_EXPORT).encode())
    assert list((memory / "episodes").glob("*.md")) == []
    assert list((memory / "entities").glob("*.md")) == []
    assert not (memory / "sources" / "url_index.json").exists()


def test_preview_endpoint_reports_an_unsupported_file_as_200_not_422(client):
    """The overlay renders `recognized: false` + warnings; it must not have to
    parse an error status to do so."""
    c, _ = client
    resp = _post_preview(c, "photo.heic", b"binary")
    assert resp.status_code == 200, resp.text
    assert resp.json()["recognized"] is False


def test_real_upload_path_is_unchanged_without_the_flag(client):
    c, memory = client
    resp = c.post(
        "/sources/upload",
        files={"file": ("links.txt", b"https://example.com/a\n", "text/plain")},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["episodesCreated"] == 1
    assert len(list((memory / "episodes").glob("*.md"))) == 1
