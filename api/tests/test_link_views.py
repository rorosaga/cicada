"""Links show as what they are (owner rulings 2026-10-14): the view word is a standard markdown link title, Sleep keeps
writing plain links, nothing is fetched to draw a card, and the person's view choice is a pinned page edit (G198).

Synthetic bank only (alpha-project, example.com); git is real; nothing reaches a network or a real home.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from _synthetic_bank import _bank, _entity
from api.services import entity_body, link_views, markdown_parser, page_edits, page_links, page_sources, site_sources

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "link_views.json").read_text(encoding="utf-8"))
SEATS = "https://blog.example.com/seats"
PAGE = ("## Summary\nAlpha Project prices by seat.\n\n## Article\n\n### Pricing\n"
        f"They moved to usage billing; the team wrote it up in [How we priced seats]({SEATS}).\n\n"
        "## Links\n"
        f"- [How we priced seats]({SEATS}) — the write-up\n"
        "- [Roadmap](https://alpha.example.org/roadmap \"bookmark\") — linked when the launch date moved\n")


# --------------------------------------------------------------------------- the grammar (shared with Swift)


@pytest.mark.parametrize("case", FIXTURE["titles"], ids=lambda c: repr(c["title"]))
def test_every_view_word_and_date_parses_as_the_fixture_says(case):
    parsed = link_views.parse_title(case["title"])
    assert ((parsed.view, parsed.day) if parsed else (None, None)) == (case["view"], case["day"])


@pytest.mark.parametrize("case", FIXTURE["lines"], ids=lambda c: c["line"][:40])
def test_every_line_yields_the_fixtures_links(case):
    keys = ("label", "url", "view", "asked", "day", "block", "markdown")
    assert [{k: r.to_dict()[k] for k in keys} for r in link_views.links_in(case["line"])] == case["links"]


@pytest.mark.parametrize("case", FIXTURE["drawn"], ids=lambda c: c["line"][:40])
def test_a_link_with_no_view_word_draws_by_its_context(case):
    """Owner 2026-10-26 (Notion's model): a plain link in a sentence is a mention, alone on its line a bookmark; a view
    word always wins; embed is never a default."""
    assert [link_views.drawn(r) for r in link_views.links_in(case["line"])] == case["drawn"]


def test_embed_is_never_a_default_and_url_is_an_inline_view():
    assert "url" in link_views.INLINE_VIEWS and "embed" in link_views.BLOCK_VIEWS
    assert link_views.SWITCHER_VIEWS[:4] == ("mention", "bookmark", "embed", "url")
    for case in FIXTURE["drawn"]:
        if "embed" in case["drawn"]:
            assert '"embed"' in case["line"]
    assert link_views.plain('[T](https://example.com/t "url")') == "[T](https://example.com/t)"


def test_plain_drops_view_words_and_keeps_a_real_tooltip():
    for case in FIXTURE["plain"]:
        assert link_views.plain(case["in"]) == case["out"]


def test_the_token_for_a_view_and_the_raw_display():
    for case in FIXTURE["markdown"]:
        assert link_views.markdown(case["label"], case["url"], case["view"], case["day"]) == case["out"]
    for case in FIXTURE["display"]:
        assert link_views.display(case["url"]) == case["out"]
    with pytest.raises(ValueError):
        link_views.markdown("T", SEATS, "bookmark", "2026-10-14")     # a date goes only with screenshot or look
    with pytest.raises(ValueError):
        link_views.markdown("T", SEATS, "card")


def test_the_edit_tools_description_names_only_views_the_parser_accepts():
    """R12 for the view words: every quoted view the agent is taught parses, and every switcher view is taught."""
    import re

    from _stdio_server import stdio_server

    text = next(t for t in stdio_server().TOOLS if t["name"] == "cicada_edit_page")["description"]
    taught = set(re.findall(r'"((?:mention|bookmark|screenshot|captures|look|embed)(?: \d{4}-\d{2}-\d{2})?)"', text))
    taught |= set(re.findall(r"`(mention|bookmark|embed|url|screenshot|captures|look)`", text))
    assert taught, "the description teaches no view"
    for word in taught:
        assert link_views.parse_title(word) is not None, word
    assert set(link_views.SWITCHER_VIEWS) <= {w.split()[0] for w in taught}


# --------------------------------------------------------------------------- titled links survive every parser


def test_links_dedup_reads_a_titled_link_by_its_url():
    existing = f'- [How we priced seats]({SEATS} "bookmark") — the write-up'
    merged = entity_body._merge_links(existing, [{"url": SEATS, "title": "How we priced seats", "note": "again"}])
    assert merged.count(SEATS) == 1 and '"bookmark"' in merged


def test_where_this_comes_from_keeps_a_titled_links_url_and_title():
    assert page_sources._parse_link(f'[How we priced seats]({SEATS} "screenshot 2026-10-14") — the write-up') == (
        SEATS, "How we priced seats", "the write-up")


def test_the_site_reader_sees_an_official_link_with_a_view_word():
    body = '## Links\n- [Official site](https://alphaproject.io "bookmark")\n'
    assert site_sources._links_origin({"name": "Alpha Project"}, body) == "https://alphaproject.io"


def test_recall_quotes_never_show_a_view_word():
    from api.services import mcp_tools

    out = mcp_tools._type_aware_truncate(f'## Summary\nSee [the write-up]({SEATS} "bookmark").\n', "project")
    assert f"[the write-up]({SEATS})" in out and '"bookmark"' not in out


# --------------------------------------------------------------------------- the routes


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


@pytest.fixture
def bank(tmp_path, monkeypatch):
    from api import config

    memory = _bank(tmp_path)
    _entity(memory, "alpha-project", type="project", name="Alpha Project", body=PAGE)
    _entity(memory, "seats-post", type="media", name="How we priced seats", saved_at="2026-10-02",
            read_at="2026-10-03T08:00:00Z",
            media={"url": SEATS, "media_type": "url", "site": "blog.example.com",
                   "saved_at": "2026-10-02T09:00:00Z"},
            body="## Description\nA walk through the move from flat plans to usage billing.\n")
    from api.services import media_ingestor

    (memory / "sources").mkdir(exist_ok=True)
    media_ingestor.save_url_index(memory, {media_ingestor.url_hash(SEATS): {"media_entity_id": "seats-post",
                                                                             "url": SEATS}})
    (memory / "design").mkdir()
    markdown_parser.write(memory / "design" / "2026-10-14-seats.md",
                          {"title": "Seats", "url": SEATS, "site": "blog.example.com",
                           "captured": "2026-10-14T10:00:00Z",
                           "image": {"file": "assets/design/2026-10-14-seats.png", "sha256": "ab" * 32,
                                     "width": 100, "height": 60, "bytes": 10},
                           "palette": [{"hex": "#112233", "share": 0.6}]}, "## What I liked\nThe type.\n")
    _git(memory, "add", ".")
    _git(memory, "commit", "-q", "-m", "Seed\n\nCicada-Author: cicada")
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setenv("CICADA_ALLOW_LOGO_FETCH", "off")
    config.get_settings.cache_clear()
    yield memory
    config.get_settings.cache_clear()


def _client():
    from fastapi.testclient import TestClient

    from api import main

    return TestClient(main.app)


def test_the_link_facts_route_draws_from_what_cicada_holds_and_fetches_nothing(bank):
    client = _client()
    response = client.get("/entities/alpha-project/links")
    assert response.status_code == 200
    body = response.json()
    by_url = {fact["url"]: fact for fact in body["links"]}
    assert list(by_url) == [SEATS, "https://alpha.example.org/roadmap"]
    seats = by_url[SEATS]
    assert seats["pageId"] == "seats-post" and seats["title"] == "How we priced seats"
    assert seats["savedAt"] == "2026-10-02" and seats["readAt"] == "2026-10-03T08:00:00Z"
    assert seats["description"].startswith("A walk through") and seats["captures"] == []
    assert seats["looks"][0]["id"] == "2026-10-14-seats" and seats["looks"][0]["image"].startswith("/design/")
    assert seats["icon"] is True and seats["views"] == ["link"]
    roadmap = by_url["https://alpha.example.org/roadmap"]
    assert roadmap["views"] == ["bookmark"] and roadmap["icon"] is False and "pageId" not in roadmap
    etag = response.headers["ETag"]
    assert client.get("/entities/alpha-project/links", headers={"If-None-Match": etag}).status_code == 304
    assert client.get("/entities/no-such-page/links").status_code == 404


def test_a_saved_page_this_page_links_to_may_draw_its_mark_and_nothing_else(bank):
    assert page_links.linked_sites(bank, PAGE) == {"example.com"}     # the site key (`reading_hosts.site_of`)
    client = _client()
    # Not a source, not saved: no lookup, a 404 (the app draws a ring monogram).
    assert client.get("/entities/alpha-project/sources/icon/example.org").status_code == 404
    # A person's page never draws a mark (G159), whatever it links to.
    _entity(bank, "bob-example", type="person", body=PAGE)
    assert client.get("/entities/bob-example/sources/icon/example.com").status_code == 404
    assert all(not f["icon"] for f in client.get("/entities/bob-example/links").json()["links"])


def test_the_persons_view_switch_is_a_pinned_edit_under_their_name_that_outlives_a_rewrite(bank):
    client = _client()
    old = f"[How we priced seats]({SEATS})"
    new = link_views.markdown("How we priced seats", SEATS, "bookmark")
    response = client.post("/entities/alpha-project/edits", json={
        "reason": "Shown as a bookmark.", "edits": [{"old": old, "new": new, "all": True, "pin": True}]})
    assert response.status_code == 200, response.text
    assert response.json()["pinned"] == 1 and response.json()["entityId"] == "alpha-project"
    page = markdown_parser.parse(bank / "entities" / "alpha-project.md")
    assert page.body.count(new) == 2 and old not in page.body.replace(new, "")
    log = _git(bank, "log", "-1", "--format=%B")
    assert log.startswith("Page edit ") and "Cicada-Author: user" in log
    assert "Reason: Shown as a bookmark." in log and "trigger: user/companion_app" in log
    assert _git(bank, "status", "--porcelain") == ""
    # Sleep writes the plain link again: the pinned correction puts the view back (G198).
    rewritten, n = page_edits.apply_corrections(page.frontmatter, PAGE)
    assert n == 2 and rewritten.count(new) == 2
    # And the switch back is the same door.
    back = client.post("/entities/alpha-project/edits", json={
        "reason": "Shown as a link.", "edits": [{"old": new, "new": old, "all": True, "pin": True}]})
    assert back.status_code == 200
    fm = markdown_parser.parse(bank / "entities" / "alpha-project.md").frontmatter
    assert [(c["old"], c["new"]) for c in fm["corrections"]] == [(new, old)]


def test_the_person_edit_route_refuses_what_the_editor_refuses(bank):
    client = _client()
    assert client.post("/entities/alpha-project/edits", json={"reason": "", "edits": [
        {"old": "Alpha", "new": "Alfa"}]}).status_code == 400
    assert client.post("/entities/alpha-project/edits", json={"reason": "x", "edits": [
        {"old": "words not on the page", "new": "y"}]}).status_code == 409
    assert client.post("/entities/alpha-project/edits", json={"reason": "x", "edits": [
        {"old": "Alpha", "new": "## Heading"}]}).status_code == 400
    assert client.post("/entities/no-such-page/edits", json={"reason": "x", "edits": [
        {"old": "a", "new": "b"}]}).status_code == 404
    assert _git(bank, "log", "-1", "--format=%s").strip() == "Seed"


def test_the_person_edit_route_waits_for_sleep(bank, monkeypatch):
    from api.services import sleep_cycle

    monkeypatch.setattr(sleep_cycle, "is_writing", lambda *a, **k: True)
    response = _client().post("/entities/alpha-project/edits", json={"reason": "x", "edits": [
        {"old": "prices by seat", "new": "prices per seat"}]})
    assert response.status_code == 409
    assert "prices by seat" in (bank / "entities" / "alpha-project.md").read_text(encoding="utf-8")


# --------------------------------------------------------------------------- review B1: a switch edits one whole token


def test_a_view_switch_never_reaches_inside_a_longer_url_a_link_or_an_image():
    """A link or URL edit (and its pin) matches only the whole token: never ``…/a`` inside ``…/a/b``, never the target
    of ``[Guide](…/a)``, never an image. Before the fix, switching the bare URL nested a link inside the other two and
    the pin re-applied it on every Sleep."""
    url = "https://x.example.com/a"
    body = (f"## Summary\nSee {url} and [Guide]({url}) and {url}/b.\n\n![Guide]({url})\n")
    bare = link_views.markdown(url, url, "mention")
    out = page_edits.plan({"name": "P"}, body, page_edits.parse_request(
        [{"old": url, "new": bare, "all": True, "pin": True}]), author="user")
    assert out.body.strip() == body.replace(f"See {url} and", f"See {bare} and").strip()
    rewritten, n = page_edits.apply_corrections(out.frontmatter, body)
    assert n == 1 and rewritten.strip() == out.body.strip()
    assert page_edits.apply_corrections(out.frontmatter, out.body) == (out.body, 0)
    token, card = f"[Guide]({url})", link_views.markdown("Guide", url, "bookmark")
    out = page_edits.plan({"name": "P"}, body, page_edits.parse_request(
        [{"old": token, "new": card, "all": True, "pin": True}]), author="user")
    assert out.body.strip() == body.replace(f"and {token} and", f"and {card} and").strip()
    assert f"![Guide]({url})" in out.body and f"{url}/b" in out.body
    assert page_edits.apply_corrections(out.frontmatter, out.body) == (out.body, 0)


def test_a_url_with_parentheses_is_one_url_everywhere():
    wiki = "https://en.wikipedia.org/wiki/Foo_(bar)"
    assert entity_body._link_url(f"- [Foo]({wiki}) — a note") == wiki
    merged = entity_body._merge_links(f"- [Foo]({wiki}) — a note", [{"url": wiki, "title": "Foo", "note": "again"}])
    assert merged.count(wiki) == 1
    assert page_sources._parse_link(f'[Foo]({wiki} "bookmark") — a note') == (wiki, "Foo", "a note")
