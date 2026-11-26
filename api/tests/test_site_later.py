"""G221 (ruling 77e) — a save the app noticed on a page that names no post (LinkedIn's feed), named by the words the
post's block showed: settled by the record when Cicada holds the post, else held outside the bank with the person's
answer until the site's saved list names it. Synthetic posts and words only."""
from __future__ import annotations

from pathlib import Path

import pytest

from api.services import markdown_parser, mcp_tools, site_later

from api.tests.test_saved_why import _bank, _client, _offline  # noqa: F401 — the offline fixture and scratch bank

LI = "https://www.linkedin.com/feed/update/urn:li:activity:7000000000000000001/"
POST = "We rebuilt the sync engine around an append-only log, and three things surprised us along the way."
#: What the feed's block shows around the post: who liked it, the author and their headline, then the post, cut off.
BLOCK = "\n".join(["Carol Example likes this", "Alice Example", "Staff engineer at alpha-project", "3d",
                   POST[:70], "…more", "42 comments"])


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))


def _words(client, words=BLOCK, site="linkedin"):
    return client.post("/sources/site-words", json={"site": site, "words": words})


def test_a_post_nobody_named_is_held_outside_the_bank_and_answered_there(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    client = _client(memory, monkeypatch)
    r = _words(client)
    assert r.status_code == 200, r.text
    said = r.json()
    assert said["direction"] == "saved" and said["save"]["status"] == "created"
    address = said["save"]["url"]
    assert site_later.key_of(address) is not None and address.startswith("https://www.linkedin.com/?")
    assert said["save"]["origin"] == "linkedin-saved" and said["save"]["episodeId"] == ""
    # Nothing is written into the bank for a post with no link.
    assert not list((memory / "episodes").glob("*.md")) and not list((memory / "entities").glob("*.md"))
    # The notch's answer is kept beside the held save.
    why = client.post("/sources/saved-why", json={"url": address, "reasons": ["read_later"], "text": "for the sync idea",
                                                  "addedAt": said["save"]["addedAt"], "via": "linkedin-saved"})
    assert why.status_code == 200, why.text
    assert why.json()["savedWhy"]["text"] == "for the sync idea" and why.json()["episodeId"] == ""
    held = site_later.find(memory, site_later.key_of(address)[1])
    assert held is not None and len(held["answers"]) == 1
    # The person changes it before the list was read.
    at = why.json()["savedWhy"]["at"]
    edited = client.put("/sources/saved-why", json={"url": address, "at": at, "reasons": ["idea"], "text": "sync"})
    assert edited.status_code == 200, edited.text
    assert site_later.find(memory, held["key"])["answers"][0]["text"] == "sync"


def test_the_list_read_names_the_post_and_its_answer_joins_the_save(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    client = _client(memory, monkeypatch)
    address = _words(client).json()["save"]["url"]
    client.post("/sources/saved-why", json={"url": address, "reasons": ["read_later"], "text": "for the sync idea"})
    # The list read brings the post with its link (stored here the way a read stores it), then names the held save.
    saved = client.post("/sources/site-save", json={"site": "linkedin", "url": LI, "text": POST}).json()
    other = "https://www.linkedin.com/feed/update/urn:li:activity:7000000000000000002/"
    shown = [(other, "A different post about hiring that shares nothing with the first one at all."), (LI, POST)]
    assert mcp_tools._name_held_saves(memory, "linkedin", shown) == 1
    parsed = markdown_parser.parse(memory / "episodes" / f"{saved['episodeId']}.md")
    assert parsed.frontmatter["saved_why"]["text"] == "for the sync idea" and "for the sync idea" in parsed.body
    assert site_later.find(memory, site_later.key_of(address)[1]) is None
    # Named once: a second read attaches nothing.
    assert mcp_tools._name_held_saves(memory, "linkedin", shown) == 0


def test_a_post_cicada_holds_is_settled_by_the_record(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    client = _client(memory, monkeypatch)
    saved = client.post("/sources/site-save", json={"site": "linkedin", "url": LI, "text": POST}).json()
    # Held as on the list: the click took it off.
    off = _words(client).json()
    assert off["direction"] == "unsaved" and off["unsave"]["url"] == LI and off["unsave"]["status"] == "marked"
    # Off the list: the next click saved it again, by its link.
    again = _words(client).json()
    assert again["direction"] == "saved" and again["save"]["url"] == LI
    assert again["save"]["episodeId"] == saved["episodeId"]


def test_another_authors_post_that_starts_alike_is_not_the_held_one(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    client = _client(memory, monkeypatch)
    saved = client.post("/sources/site-save", json={"site": "linkedin", "url": LI, "text": POST}).json()
    page = memory / "entities" / f"{saved['mediaEntityId']}.md"
    parsed = markdown_parser.parse(page)
    markdown_parser.write(page, {**parsed.frontmatter, "media": {**parsed.frontmatter["media"],
                                                                 "channel": "Alice Example"}}, parsed.body)
    theirs = BLOCK.replace("Alice Example", "Bob Example")
    assert site_later.held_url(memory, "linkedin", theirs) is None
    assert site_later.held_url(memory, "linkedin", BLOCK) == LI


def test_the_same_words_clicked_again_take_the_save_back(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    client = _client(memory, monkeypatch)
    first = _words(client).json()
    # The count on the post moved between the two clicks: still the same post.
    second = _words(client, BLOCK.replace("42 comments", "43 comments")).json()
    assert second["direction"] == "unsaved" and second["unsave"]["url"] == first["save"]["url"]
    assert site_later.find(memory, site_later.key_of(first["save"]["url"])[1]) is None
    assert client.post("/sources/saved-why", json={"url": first["save"]["url"], "reasons": ["idea"]}).status_code == 404


@pytest.mark.parametrize("body", [
    {"site": "x", "words": BLOCK},                 # a site whose pages name their posts
    {"site": "linkedin", "words": "Too short"},    # nothing a post could be told by
])
def test_what_names_no_post_is_refused(tmp_path, monkeypatch, body):
    client = _client(_bank(tmp_path), monkeypatch)
    assert client.post("/sources/site-words", json=body).status_code == 422


def test_folding_and_the_placeholder_address():
    assert site_later.fold("Héllo,  WORLD — #sync…more") == "héllo" + "world" + "sync" + "more"
    assert site_later.key_of("https://www.linkedin.com/feed/update/urn:li:activity:7000000000000000001/") is None
    assert site_later.key_of("https://example.org/?cicada-later=abc123") is None
    assert site_later.key_of(site_later.later_url("linkedin", "abc123")) == ("linkedin", "abc123")
