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
    # Ruling 80: a click on a site's save is its own reason. A post with no words on a login-walled site has nothing for
    # a model to read (kept, found by title, read when he talks about it); one with words waits for tonight.
    assert history_index.save_shaped(fm) == "list" and history_index.save_state(fm) == "no-words"
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
    # The post's words are the post's, never his (`authorship`): read tonight as its author's.
    assert history_index.save_state(fm) == "waiting" and not any(fm.get(k) for k in history_index.PERSON_KEYS)


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


def test_a_click_whose_direction_the_page_did_not_say_is_decided_by_the_record(tmp_path, monkeypatch):
    """Owner 2026-11-25: a save control that changed with nothing on the page to say which way is no longer dropped."""
    memory = _bank(tmp_path)
    client = _client(memory, monkeypatch)
    # Nothing held for the post: the click saved it.
    first = client.post("/sources/site-change", json={"site": "x", "url": POST, "text": "A synthetic post."})
    assert first.status_code == 200, first.text
    assert first.json()["direction"] == "saved" and first.json()["unsave"] is None
    saved = first.json()["save"]
    assert saved["status"] == "created" and saved["url"] == POST and saved["origin"] == "x-bookmarks"
    # Held as on the list: the next unreadable click took it off, and the save stays, marked.
    second = client.post("/sources/site-change", json={"site": "x", "url": POST})
    assert second.json()["direction"] == "unsaved" and second.json()["save"] is None
    assert second.json()["unsave"] == {"status": "marked", "url": POST}
    fm, _ = _episode(memory, saved["episodeId"])
    assert fm.get("left_site_at")
    # Held but off the list: the click after that saved it again, the same row, the mark gone.
    third = client.post("/sources/site-change", json={"site": "x", "url": POST})
    assert third.json()["direction"] == "saved" and third.json()["save"]["status"] == "duplicate"
    assert third.json()["save"]["episodeId"] == saved["episodeId"]
    fm, _ = _episode(memory, saved["episodeId"])
    assert not fm.get("left_site_at")
    # Not a post of a known site: refused unwritten, as the other two routes refuse it.
    assert client.post("/sources/site-change", json={"site": "x", "url": "https://x.com/home"}).status_code == 422


@pytest.mark.parametrize("site,url,stored,origin", [
    ("instagram", "https://www.instagram.com/alpha_user/reel/AbCdEfGhIjK/", "https://www.instagram.com/reel/AbCdEfGhIjK/", "instagram-saved"),
    ("github", "https://github.com/alpha-org/alpha-project/", "https://github.com/alpha-org/alpha-project", "github-starred"),
    ("tiktok", "https://www.tiktok.com/@alpha.user/video/7300000000000000001", "https://www.tiktok.com/@alpha.user/video/7300000000000000001", "tiktok-saved"),
    ("reddit", "https://old.reddit.com/r/alpha_sub/comments/1abc234/a_synthetic_post/?share=1", "https://www.reddit.com/r/alpha_sub/comments/1abc234/a_synthetic_post/", "reddit-saved"),
    ("youtube", "https://www.youtube.com/watch?v=AbCdEfGhIjK&list=PLalpha&t=42s", "https://www.youtube.com/watch?v=AbCdEfGhIjK", "youtube-playlist"),
    ("youtube", "https://youtu.be/AbCdEfGhIjK", "https://www.youtube.com/watch?v=AbCdEfGhIjK", "youtube-playlist"),
])
def test_the_other_sites_store_under_their_own_origin(tmp_path, monkeypatch, site, url, stored, origin):
    memory = _bank(tmp_path)
    saved = _client(memory, monkeypatch).post("/sources/site-save", json={"site": site, "url": url}).json()
    assert saved["status"] == "created" and saved["url"] == stored and saved["origin"] == origin
    fm, _ = _episode(memory, saved["episodeId"])
    assert history_index.save_shaped(fm) == "list" and history_index.kind(fm) is None   # a save, kept for Sleep or for lookup


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


def test_a_youtube_video_is_filed_under_watch_later_or_the_playlist_the_person_chose(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    client = _client(memory, monkeypatch)
    later = client.post("/sources/site-save", json={"site": "youtube", "url": "https://www.youtube.com/watch?v=AbCdEfGhIjK"}).json()
    fm, _ = _episode(memory, later["episodeId"])
    assert fm["origin"] == "youtube-playlist" and fm["folder"] == "Watch later"
    listed = client.post("/sources/site-save", json={"site": "youtube", "url": "https://www.youtube.com/watch?v=ZyXwVuTsRqP",
                                                     "folders": ["Alpha tutorials"]}).json()
    fm, _ = _episode(memory, listed["episodeId"])
    assert fm["folder"] == "Alpha tutorials" and listed["folders"] == ["Alpha tutorials"]
    # A channel, a search or the home feed is not a video.
    for url in ("https://www.youtube.com/@alpha", "https://www.youtube.com/results?search_query=alpha", "https://www.youtube.com/"):
        assert client.post("/sources/site-save", json={"site": "youtube", "url": url}).status_code == 422
