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
