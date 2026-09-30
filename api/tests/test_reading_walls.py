"""G166 (ruling 14 amended 2026-09-30) — which saved pages Cicada's own reader could not read.

A wall page is decided from stamps the fetchers already write plus the closed host set; a page
that already holds words is never one; only the few candidates have their body parsed."""
from __future__ import annotations

import pytest

from _reading_fixtures import put_page
from _synthetic_bank import _bank
from api.services import link_enrichment, markdown_parser, reading_walls

ART = "https://articles.paperfold.io/post/1"


@pytest.fixture
def memory(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    reading_walls.reset_memo()
    return _bank(tmp_path)


def _kinds(memory):
    return {p.entity_id: p.wall for p in reading_walls.scan(memory)}


def test_each_wall_kind_from_its_existing_stamp(memory):
    put_page(memory, "walled", "https://x.com/alpha/status/1")
    put_page(memory, "refused", ART, fetch_status="blocked")
    put_page(memory, "consent", "https://news.paperfold.io/a", fetch_status="interstitial")
    put_page(memory, "consent2", "https://news.paperfold.io/b", fetch_status="skipped:interstitial")
    put_page(memory, "login", "https://wiki.paperfold.io/a", fetch_status="skipped:login_wall")
    assert _kinds(memory) == {"media-walled": "walled", "media-refused": "refused", "media-consent": "consent",
                              "media-consent2": "consent", "media-login": "login"}
    assert reading_walls.WALL_KINDS == ("walled", "login", "consent", "refused")


def test_a_saved_sign_in_or_consent_page_is_not_a_wall_page(memory):
    """A bookmark of a sign-in page has nothing behind it to read, and its host would list as a 'site'."""
    put_page(memory, "signin", "https://accounts.paperfold.io/login", fetch_status="skipped:login_wall")
    put_page(memory, "consent", "https://consent.paperfold.io/x", fetch_status="skipped:interstitial")
    put_page(memory, "blocked-login", "https://accounts.google.com/signin", fetch_status="blocked")
    put_page(memory, "walled-login", "https://www.linkedin.com/login")
    assert _kinds(memory) == {}


def test_failed_stamps_and_empty_pages_are_not_walls(memory):
    for i, status in enumerate(("failed:http_500", "failed:empty_body", "failed:Timeout", "failed:no_summary", "ok")):
        put_page(memory, f"f{i}", f"https://blog.paperfold.io/{i}", fetch_status=status)
    put_page(memory, "plain", "https://blog.paperfold.io/plain")
    assert _kinds(memory) == {}


def test_a_page_with_words_is_not_surfaced(memory):
    long_text = ("A long enough description that says what the saved post is about, in a full sentence or two. "
                 "It goes on to explain the index, the laptop and why nothing leaves it.")
    put_page(memory, "described", ART, fetch_status="blocked", body=f"## Description\n\n{long_text}\n")
    put_page(memory, "agent-read", "https://articles.paperfold.io/post/2", fetch_status="blocked",
             read={"by": "agent", "tier": "agent", "at": "2026-09-30T00:00:00Z"})
    put_page(memory, "summarised", "https://articles.paperfold.io/post/3", fetch_status="blocked",
             description_source="summary")
    claimed = put_page(memory, "claimed", "https://articles.paperfold.io/post/4", fetch_status="blocked")
    path = memory / "entities" / f"{claimed}.md"
    link_enrichment._append_claim(path, link_enrichment._build_describes_claim(
        claimed, "The post explains how the notes index works.", "ep_2026-09-01_001", "2026-09-01", "test"))
    put_page(memory, "bare", "https://articles.paperfold.io/post/5", fetch_status="blocked")
    pages = {p.entity_id: p for p in reading_walls.scan(memory)}
    assert {k for k, p in pages.items() if p.waiting} == {"media-bare"}
    assert pages["media-agent-read"].read_by_agent and not pages["media-agent-read"].waiting


def test_connector_saved_post_with_a_description_is_not_surfaced(memory):
    """H3: the reuse tier never runs for a walled host, so a saved post has its text and no claim."""
    text = ("A saved post whose text the connector already brought in, a couple of sentences long. It says things "
            "about the notes index and where the vectors live, and it says them at some length.")
    put_page(memory, "saved-post", "https://x.com/alpha/status/9", origin="x-bookmarks",
             body=f"## Description\n\n{text}\n")
    put_page(memory, "thin", "https://x.com/alpha/status/10", origin="x-bookmarks", body="## Description\n\nok\n")
    put_page(memory, "empty", "https://x.com/alpha/status/11", origin="x-bookmarks")
    waiting = {p.entity_id for p in reading_walls.scan(memory) if p.waiting}
    assert waiting == {"media-thin", "media-empty"}, "thin or empty descriptions are surfaced"


def test_denied_classes_are_never_wall_pages(memory):
    put_page(memory, "video", "https://vimeo.com/123456789", fetch_status="blocked")
    put_page(memory, "paper", "https://arxiv.org/abs/2401.00001", fetch_status="blocked")
    put_page(memory, "secret", "https://articles.paperfold.io/a?token=abc", fetch_status="blocked")
    put_page(memory, "local", "http://192.168.1.5/a", fetch_status="blocked")
    put_page(memory, "vendor", "https://chatgpt.com/share/abc", fetch_status="blocked")
    put_page(memory, "tco", "https://t.co/abc")
    put_page(memory, "archived", ART, fetch_status="blocked", status="archived")
    put_page(memory, "dropped", "https://articles.paperfold.io/b", fetch_status="blocked", status="dropped")
    put_page(memory, "paperpage", "https://articles.paperfold.io/c", fetch_status="blocked",
             media={"url": "https://articles.paperfold.io/c", "kind": "paper", "media_type": "url"})
    assert _kinds(memory) == {}


def test_only_candidates_are_parsed_and_the_second_scan_parses_none(memory):
    for i in range(300):
        put_page(memory, f"ok{i}", f"https://blog.paperfold.io/{i}", fetch_status="ok")
    for i in range(5):
        put_page(memory, f"w{i}", f"https://articles.paperfold.io/w{i}", fetch_status="blocked")
    reading_walls.reset_memo()
    assert len([p for p in reading_walls.scan(memory) if p.waiting]) == 5
    assert reading_walls.body_parses <= 5, "the 300 other media pages are never body-parsed"
    before = reading_walls.body_parses
    reading_walls.scan(memory)
    assert reading_walls.body_parses == before, "memoised per (bank, id, mtime, size)"
    # an edit invalidates exactly that page
    path = memory / "entities" / "media-w0.md"
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, parsed.frontmatter, parsed.body + "\n## Description\n\nSomething.\n")
    reading_walls.scan(memory)
    assert reading_walls.body_parses == before + 1


def test_the_memo_is_bounded(memory, monkeypatch):
    monkeypatch.setattr(reading_walls, "_MEMO_MAX", 3)
    for i in range(6):
        put_page(memory, f"w{i}", f"https://articles.paperfold.io/w{i}", fetch_status="blocked")
    reading_walls.scan(memory)
    assert len(reading_walls._words_memo) <= 3


def test_scan_one_finds_a_page_by_url_without_walking_the_bank(memory):
    put_page(memory, "w", ART, fetch_status="blocked")
    put_page(memory, "plain", "https://blog.paperfold.io/p")
    page = reading_walls.scan_one(memory, ART)
    assert page is not None and page.wall == "refused" and page.site == "paperfold.io" and page.waiting
    assert reading_walls.scan_one(memory, "https://blog.paperfold.io/p") is None
    assert reading_walls.scan_one(memory, "https://never-saved.paperfold.io/") is None
