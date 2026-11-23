"""G221 — a save the person made inside a site (X's Bookmark), noticed by the app and saved through
``POST /sources/site-save``: one row under the site's own origin, index-only until the person says why, the same row a
later list read names. Synthetic posts only."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import history_index, markdown_parser, saved_lists

from api.tests.test_saved_why import _bank, _client, _offline  # noqa: F401 — the offline fixture and scratch bank

POST = "https://x.com/alpha_user/status/1900000000000000001"


def _episode(memory: Path, episode_id: str) -> tuple[dict, str]:
    parsed = markdown_parser.parse(memory / "episodes" / f"{episode_id}.md")
    return parsed.frontmatter, parsed.body


def test_a_save_noticed_on_x_is_one_row_under_xs_own_origin(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    client = _client(memory, monkeypatch)
    # The share-sheet spelling of the same post: stored under the one canonical link.
    r = client.post("/sources/site-save", json={"site": "x", "url": POST + "?s=46&t=abc"})
    assert r.status_code == 200, r.text
    saved = r.json()
    assert saved["status"] == "created" and saved["url"] == POST and saved["origin"] == "x-bookmarks"
    assert saved["title"] == "Post by @alpha_user" and saved["addedAt"]
    fm, _ = _episode(memory, saved["episodeId"])
    assert fm["origin"] == "x-bookmarks" and fm["folder"] == saved_lists.PLATFORMS["x"].folder
    # Ruling 62: a save from a platform's list with no reason is indexed, never read by a model.
    assert history_index.kind(fm) == "list"
    # The same post again (a list read, a second click): the same row, never a second.
    again = client.post("/sources/site-save", json={"site": "x", "url": "https://twitter.com/alpha_user/status/1900000000000000001"})
    assert again.json()["status"] == "duplicate" and again.json()["episodeId"] == saved["episodeId"]
    assert len(list((memory / "episodes").glob("*.md"))) == 1
    # Another post by the same author is its own row and its own page.
    other = client.post("/sources/site-save", json={"site": "x", "url": POST[:-1] + "2"}).json()
    assert other["status"] == "created" and other["mediaEntityId"] != saved["mediaEntityId"]


def test_the_persons_reason_makes_sleep_read_it(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    client = _client(memory, monkeypatch)
    saved = client.post("/sources/site-save", json={"site": "x", "url": POST}).json()
    r = client.post("/sources/saved-why", json={"url": saved["url"], "reasons": ["read_later"], "text": "for the sync idea",
                                                "addedAt": saved["addedAt"], "via": "x-bookmarks"})
    assert r.status_code == 200, r.text
    fm, body = _episode(memory, saved["episodeId"])
    assert fm["saved_why"]["via"] == "x-bookmarks" and "for the sync idea" in body
    assert fm.get("processed") is False and history_index.kind(fm) is None


@pytest.mark.parametrize("body", [
    {"site": "x", "url": "https://x.com/home"},
    {"site": "x", "url": "https://alpha.example/a/status/12"},
    {"site": "no-such-site", "url": POST},
])
def test_a_link_that_is_not_a_post_of_a_known_site_is_refused_unwritten(tmp_path, monkeypatch, body):
    memory = _bank(tmp_path)
    r = _client(memory, monkeypatch).post("/sources/site-save", json=body)
    assert r.status_code == 422
    assert not any((memory / "episodes").glob("*.md"))


def test_the_posts_own_words_title_the_row_and_are_never_the_persons(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    saved = _client(memory, monkeypatch).post("/sources/site-save", json={
        "site": "x", "url": POST, "text": "  a way to sync two   replicas without a server  "}).json()
    assert saved["title"] == "a way to sync two replicas without a server"
    fm, body = _episode(memory, saved["episodeId"])
    assert "a way to sync two replicas without a server" in body
    assert history_index.kind(fm) == "list"          # the post's words are no reason: still index-only


def test_an_unsave_marks_the_save_and_saving_again_clears_the_mark(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    client = _client(memory, monkeypatch)
    assert client.post("/sources/site-unsave", json={"site": "x", "url": POST}).json()["status"] == "unknown"
    saved = client.post("/sources/site-save", json={"site": "x", "url": POST}).json()
    assert client.post("/sources/site-unsave", json={"site": "x", "url": POST}).json()["status"] == "marked"
    fm, _ = _episode(memory, saved["episodeId"])
    assert fm["left_site_at"]
    assert client.post("/sources/site-unsave", json={"site": "x", "url": POST}).json()["status"] == "unchanged"
    again = client.post("/sources/site-save", json={"site": "x", "url": POST}).json()
    assert again["status"] == "duplicate"
    fm, _ = _episode(memory, saved["episodeId"])
    assert "left_site_at" not in fm


@pytest.mark.parametrize("site,url,stored,origin", [
    ("instagram", "https://www.instagram.com/alpha_user/reel/AbCdEfGhIjK/", "https://www.instagram.com/reel/AbCdEfGhIjK/", "instagram-saved"),
    ("github", "https://github.com/alpha-org/alpha-project/", "https://github.com/alpha-org/alpha-project", "github-starred"),
    ("tiktok", "https://www.tiktok.com/@alpha.user/video/7300000000000000001", "https://www.tiktok.com/@alpha.user/video/7300000000000000001", "tiktok-saved"),
])
def test_the_other_sites_store_under_their_own_origin(tmp_path, monkeypatch, site, url, stored, origin):
    memory = _bank(tmp_path)
    saved = _client(memory, monkeypatch).post("/sources/site-save", json={"site": site, "url": url}).json()
    assert saved["status"] == "created" and saved["url"] == stored and saved["origin"] == origin
    fm, _ = _episode(memory, saved["episodeId"])
    assert history_index.kind(fm) == "list"


def test_one_instagram_post_is_one_row_by_any_of_its_addresses(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    client = _client(memory, monkeypatch)
    first = client.post("/sources/site-save", json={"site": "instagram", "url": "https://www.instagram.com/p/AbCdEfGhIjK/"}).json()
    again = client.post("/sources/site-save", json={"site": "instagram", "url": "https://www.instagram.com/reel/AbCdEfGhIjK/"}).json()
    assert again["status"] == "duplicate" and again["episodeId"] == first["episodeId"]


def test_githubs_own_sections_are_never_a_repository(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    r = _client(memory, monkeypatch).post("/sources/site-save", json={"site": "github", "url": "https://github.com/sponsors/alpha"})
    assert r.status_code == 422
