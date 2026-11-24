"""G246 (ruling 81): which saves are posts drawn as a row under their list, and which keep a page (`saved_posts`).

The rule is a pure function of the page's own saved link, never of the door; a post earns its page by the person's own
words, a conversation or claim of theirs, an edit of its page, a link they made, or "Keep as a page"; Sleep's or an agent's
reading, an agent's note, a folder's reason and a second list earn nothing. Every reader asks `saved_posts` and nothing
else, behind `HIDE_POSTS` (off: every reader returns what it did before). Synthetic text only.
"""
from __future__ import annotations

import itertools
import re
import subprocess
from pathlib import Path

import pytest

from api.services import (bank_index, claims, graph_builder, history_index, hub_builder, markdown_parser, media_kinds,
                          quiet_pages, saved_posts)

X = "https://x.com/alex_example/status/1234567890123"
SAVE = "ep_2026-11-20_001"
TALK = "ep_2026-11-21_001"


@pytest.fixture(autouse=True)
def _reset():
    bank_index.invalidate()
    graph_builder.reset_cache()
    yield
    bank_index.invalidate()
    graph_builder.reset_cache()


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(saved_posts, "HIDE_POSTS", True)


# --------------------------------------------------------------------------------------------------- the rule


def media(url, **extra):
    fm = {"name": "A save", "type": "media", "status": "active", "media": {"url": url, "media_type": "url"}}
    for key, value in extra.items():
        if key == "media_kind":
            fm["media"]["kind"] = value
        else:
            fm[key] = value
    return fm


@pytest.mark.parametrize("url", [
    "https://x.com/alex_example/status/1234567890123",
    "https://twitter.com/alex_example/status/1234567890123",          # the old host: one post, either spelling
    "https://x.com/i/web/status/1234567890123",
    "https://www.instagram.com/p/Cabc12345/",
    "https://www.instagram.com/reel/Cabc12345/",                       # a reel cannot be told from a photo post by link
    "https://www.instagram.com/tv/Cabc12345/",
    "https://www.linkedin.com/feed/update/urn:li:activity:7000000000000000001/",
    "https://www.linkedin.com/feed/update/urn:li:share:7000000000000000001/",
    "https://www.linkedin.com/posts/alex-example_a-post-activity-7000000000000000001-abcd",
    "https://www.reddit.com/r/example/comments/abc123/a_thread/",
    "https://old.reddit.com/r/example/comments/abc123/a_thread/",
    "https://www.pinterest.com/pin/123456789012/",
    "https://www.tiktok.com/@alex.example/photo/7000000000000000001",    # a photo post is a post
])
def test_a_link_to_a_post_of_a_site_is_a_post(url):
    assert saved_posts.is_post(media(url))


@pytest.mark.parametrize("url", [
    "https://example.com/an-article",                                      # an ordinary web page
    "https://x.com/alex_example",                                          # a profile
    "https://x.com/search?q=alpha",
    "https://www.linkedin.com/feed/update/urn:li:article:7000000000000000001/",   # an article is a work
    "https://www.linkedin.com/in/alex-example/",
    "https://www.tiktok.com/@alex.example/video/7000000000000000001",    # a video is on the video rail
    "https://www.youtube.com/watch?v=abcdefghijk",
    "https://youtu.be/abcdefghijk",
    "https://open.spotify.com/track/1234567890abcdef",
    "https://github.com/alpha-org/alpha-repo",
    "https://arxiv.org/abs/2601.00001",
    "https://alpha.substack.com/p/a-newsletter-post",
    "https://example.com/story.mp4",
    "not a link",
    "",
])
def test_every_other_link_is_a_work(url):
    assert not saved_posts.is_post(media(url))


def test_a_reddit_link_post_is_a_work_because_its_page_is_the_outbound_link():
    # The page's own saved link is the article; the permalink is an alias row, never read by the rule.
    page = media("https://example.com/the-article", aliases=["https://www.reddit.com/r/example/comments/abc123/a/"])
    assert not saved_posts.is_post(page)


DOORS = ["x-bookmarks", "x-likes", "x-reposts", "instagram-saved", "linkedin-saved", "reddit-saved", "pinterest",
         "pinterest-saved", "tiktok-saved", "chrome-bookmark", "safari-bookmark", "brave-bookmark", "vivaldi-bookmark",
         "comet-bookmark", "dia-bookmark", "safari-tab", "saved-link", "telegram", "youtube-playlist", "spotify-saved",
         "substack-saved", "github-starred", "goodreads", "book", "file", "list", "", None]


@pytest.mark.parametrize("origin", DOORS)
def test_the_door_never_matters_for_a_post_link(origin):
    """The same status bookmarked in a browser, saved in the site, pasted or read from its list is one answer."""
    # Only the origin is varied (a page that declares its own kind is tested apart): every door answers alike.
    assert saved_posts.is_post(media(X, origin=origin) if origin is not None else media(X)) is True
    assert saved_posts.is_post(media("https://example.com/a", origin=origin)) is False


@pytest.mark.parametrize("kind", ["book", "paper", "repository", "file", "list"])
def test_a_declared_kind_is_never_a_row(kind):
    assert not saved_posts.is_post(media(X, media_kind=kind))


def test_a_feed_item_is_its_publishers_and_never_a_row():
    assert not saved_posts.is_post(media(X, origin="rss"))
    assert not saved_posts.is_post(media(X, published_at="2026-11-01"))


def test_only_a_media_page_can_be_a_post():
    assert not saved_posts.is_post({"name": "x", "type": "concept", "media": {"url": X}})
    assert not saved_posts.is_post(None)
    assert not saved_posts.is_post({"type": "media"})


def test_the_bookmark_knob_changes_only_browser_bookmarks(monkeypatch):
    bookmarked_post, bookmarked_page = media(X, origin="chrome-bookmark"), media("https://example.com/a", origin="chrome-bookmark")
    pasted_post = media(X, origin="saved-link")
    assert saved_posts.BOOKMARKED_LINKS == "by-link"
    assert saved_posts.is_post(bookmarked_post) and not saved_posts.is_post(bookmarked_page)
    monkeypatch.setattr(saved_posts, "BOOKMARKED_LINKS", "pages")
    assert not saved_posts.is_post(bookmarked_post) and saved_posts.is_post(pasted_post)
    monkeypatch.setattr(saved_posts, "BOOKMARKED_LINKS", "rows")
    assert saved_posts.is_post(bookmarked_page) and saved_posts.is_post(pasted_post)
    assert not saved_posts.is_post(media("https://www.youtube.com/watch?v=abcdefghijk", origin="chrome-bookmark"))
    assert not saved_posts.is_post(media("https://example.com/a", origin="saved-link"))


def test_kind_of_names_a_post_only_once_the_flip_is_on(monkeypatch):
    page = media(X)
    assert media_kinds.kind_of(page) == "link"
    monkeypatch.setattr(saved_posts, "HIDE_POSTS", True)
    assert media_kinds.kind_of(page) == "post"
    assert media_kinds.kind_of(media("https://example.com/a")) == "link"
    assert media_kinds.kind_of(media(X, media_kind="book")) == "book"
    assert "post" in media_kinds.KINDS and "list" in media_kinds.KINDS


def test_a_list_page_has_a_kind_and_its_source_is_its_origin():
    page = {"name": "X: Bookmarks", "type": "media", "media": {"kind": "list"}, "list": {"stream": "x.bookmarks", "source": "x"}}
    assert media_kinds.kind_of(page) == "list" and media_kinds.origin_of(page) == "x"
    assert not saved_posts.is_post(page)


# --------------------------------------------------------------------------------------------------- a bank


class Bank:
    def __init__(self, root: Path):
        self.root = root
        (root / "entities").mkdir(parents=True, exist_ok=True)
        (root / "episodes").mkdir(parents=True, exist_ok=True)
        self._save_numbers = itertools.count(100)

    def episode(self, eid, fm=None, body="body\n"):
        markdown_parser.write(self.root / "episodes" / f"{eid}.md",
                              {"id": eid, "source": "url", "timestamp": "2026-11-20T10:00:00+00:00", **(fm or {})}, body)

    def page(self, pid, fm, body="## Summary\nA post.\n", claim_list=None):
        text = claims.write_claims(body, claim_list) if claim_list else body
        markdown_parser.write(self.root / "entities" / f"{pid}.md", fm, text)

    def post(self, pid="media-a-post", *, save=None, page=None, url=X, episodes=(), claim_list=None, save_body="body\n"):
        """A saved post: its page, its save episode (with ``save`` on it) and any other episode it cites."""
        # One number per save, in the order the posts are made. It was ``hash(pid) % 900``, which varies per process: two
        # posts collided about one run in 300 and the second save overwrote the first's episode (a row inherited a
        # neighbour's why-answer), the failure seen once on CI.
        save_id = f"ep_2026-11-20_{next(self._save_numbers)}"
        self.episode(save_id, {"url": url, "origin": "x-bookmarks", "media_entity_id": pid, **(save or {})}, save_body)
        self.page(pid, {"name": pid.replace("-", " "), "type": "media", "status": "active",
                        "source_episodes": [save_id, *episodes],
                        "media": {"url": url, "media_type": "url"}, **(page or {})}, claim_list=claim_list)
        bank_index.invalidate()
        return pid

    def signs(self, pid):
        return set(saved_posts.verdict(self.root).signs.get(pid, ()))


@pytest.fixture
def bank(tmp_path):
    return Bank(tmp_path / "bank")


def person_claim(episode, observer="agent"):
    return claims.Claim(id="c1", text="The person used it", subject="a-post", observer=observer,
                        evidence=[claims.Evidence(episode=episode, start=0, end=4, kind="user")])


# --------------------------------------------------------------------------------------------------- what earns a page


def test_a_post_nobody_gave_a_reason_to_is_a_row(bank):
    pid = bank.post()
    assert bank.signs(pid) == set()
    assert pid in saved_posts.verdict(bank.root).rows


@pytest.mark.parametrize("save, sign", [
    ({"has_note": True}, "note"),
    ({"saved_why": {"answer": "to build alpha"}}, "why"),
    ({"saved_why_earlier": [{"answer": "x"}]}, "why"),
    ({"read_asked": {"why": "link", "at": "2026-11-21"}}, "named"),
    ({"named": {"why": "title", "at": "2026-11-21"}}, "named"),
    ({"kept_as_page": {"at": "2026-11-22"}}, "kept"),
])
def test_a_note_a_why_answer_his_words_naming_it_or_keeping_it_earns_a_page(bank, save, sign):
    pid = bank.post(save=save)
    assert bank.signs(pid) == {sign}


def test_his_edit_of_the_page_earns_it(bank):
    assert bank.signs(bank.post("media-b", page={"human_edited": True})) == {"edited"}
    assert bank.signs(bank.post("media-c", page={"corrections": [{"old": "a", "new": "b"}]})) == {"edited"}


def test_a_conversation_citing_the_page_earns_it(bank):
    bank.episode(TALK, {"source": "claude-code"}, "user: the post was useful\n")
    assert bank.signs(bank.post(episodes=[TALK])) == {"conversation"}


def test_his_own_claim_citing_it_earns_it_and_retracting_it_returns_the_row(bank):
    pid = bank.post(claim_list=[person_claim(SAVE)])
    assert bank.signs(pid) == {"claim"}
    bank.page(pid, {"name": "x", "type": "media", "status": "active", "source_episodes": [],
                    "media": {"url": X, "media_type": "url"}})   # the claim retracted
    bank_index.invalidate()
    assert bank.signs(pid) == set() and pid in saved_posts.verdict(bank.root).rows


def test_a_project_listing_it_or_a_source_link_he_took_earns_it_a_proposal_does_not(bank):
    a, b, c, d = (bank.post(f"media-{x}", url=f"https://x.com/alex_example/status/{i}") for i, x in
                  enumerate("abcd", start=1000000001))
    bank.page("alpha-project", {"name": "Alpha project", "type": "project", "status": "active",
                                "entities_added": [a, {"entity": c, "by": "claude-code", "proposed": True}]})
    bank.page("alpha-tool", {"name": "Alpha tool", "type": "tool", "status": "active",
                             "sources": [{"url": "https://example.com", "entity": b},
                                         {"url": "https://example.com/2", "entity": d, "inferred": True, "proposed": True,
                                          "added_by": "claude-code"}]})
    bank_index.invalidate()
    assert bank.signs(a) == {"project"} and bank.signs(b) == {"source"}
    assert bank.signs(c) == set() and bank.signs(d) == set()


def test_an_edge_one_of_his_claims_backs_earns_it_a_machine_edge_never_does(bank):
    pid = bank.post()
    bank.page("alpha-project", {"name": "Alpha project", "type": "project", "status": "active"},
              claim_list=[claims.Claim(id="c9", text="x", subject="alpha-project", predicate="references", object=pid,
                                       evidence=[claims.Evidence(episode=TALK, start=0, end=4, kind="user")])])
    markdown_parser.write_yaml(bank.root / "graph_edges.yaml", {"edges": [
        {"source": "alpha-project", "target": pid, "label": "references", "claim_id": "c9"}]})
    bank_index.invalidate()
    assert bank.signs(pid) == {"edge"}
    markdown_parser.write_yaml(bank.root / "graph_edges.yaml", {"edges": [
        {"source": "alpha-project", "target": pid, "label": "about", "claim_id": "c9"},
        {"source": "alpha-project", "target": pid, "label": "references"}]})
    bank_index.invalidate()
    assert bank.signs(pid) == set()


@pytest.mark.parametrize("save", [
    {"has_note": True, "session_id": "sess-1", "harness": "claude-code"},     # an agent's note on a save
    {"readable_by_folder": {"at": "2026-11-21", "folders": ["Alpha"]}},         # a folder's reason
    {"processed": True, "processed_by": "sleep"},                                # Sleep's reading
])
def test_an_agents_note_a_folders_reason_and_sleeps_reading_earn_nothing(bank, save):
    assert bank.signs(bank.post(save=save)) == set()


def test_a_note_given_on_an_already_saved_link_earns_the_page_before_sleep_lists_its_episode(bank):
    """``write_note_episode`` names its page by ``media_entity_id`` and leaves ``source_episodes`` to a later Sleep."""
    pid = bank.post()
    bank.episode("ep_2026-11-22_001", {"has_note": True, "media_entity_id": pid, "origin": "web"})
    bank_index.invalidate()
    assert bank.signs(pid) == {"note"} and pid not in saved_posts.verdict(bank.root).rows


def test_a_repeat_save_by_an_agent_session_or_another_page_earns_nothing(bank):
    pid = bank.post()
    other = bank.post("media-other", url=X.replace("1", "2"))
    bank.episode("ep_2026-11-22_001", {"has_note": True, "media_entity_id": pid, "session_id": "s"})
    bank.episode("ep_2026-11-22_002", {"has_note": True, "media_entity_id": "media-elsewhere"})
    bank_index.invalidate()
    assert bank.signs(pid) == set() and bank.signs(other) == set()


def test_a_note_listed_by_the_page_and_naming_it_counts_once(bank):
    pid = bank.post(save={"has_note": True})
    assert bank.signs(pid) == {"note"} and len(saved_posts.verdict(bank.root).signs[pid]) == 1


def test_an_agent_that_read_or_watched_it_earns_nothing(bank):
    read = "ep_2026-11-22_001"
    bank.episode(read, {"source": "page-read", "media_entity_id": "media-a-post", "session_id": "s"})
    assert bank.signs(bank.post(episodes=[read])) == set()


def test_sleeps_external_claim_earns_nothing_but_his_words_in_the_save_do(bank):
    pid = bank.post(claim_list=[claims.Claim(id="c2", text="x", subject="a-post", observer="external:alex_example",
                                             evidence=[claims.Evidence(episode=SAVE, start=0, end=4, kind="user")])])
    assert bank.signs(pid) == set()


def test_an_old_shape_connector_post_is_no_words_of_his(bank):
    old = "# A post\n\n## User note\nThe post's own text.\n"
    assert bank.signs(bank.post("media-old", save={"has_note": True}, save_body=old)) == set()
    new = "# A post\n\n## User note\nMy own note.\n\n## Saved because\nI wanted it.\n"
    assert bank.signs(bank.post("media-new", url="https://x.com/alex_example/status/2000000001", save={"has_note": True},
                                save_body=new)) == {"note"}
    other = bank.post("media-pin", url="https://www.pinterest.com/pin/123456789012/",
                      save={"has_note": True, "origin": "chrome-bookmark"}, save_body=old)
    assert bank.signs(other) == {"note"}   # only a connector's origin is judged old-shape


def test_a_second_list_earns_nothing(bank):
    assert bank.signs(bank.post(page={"collections": ["Bookmarks", "Likes"]})) == set()


def test_a_restage_drops_read_asked_and_the_post_stays_earned_by_named(bank):
    pid = bank.post(save={"read_asked": {"why": "link"}, "named": {"why": "link", "at": "2026-11-21"}})
    assert bank.signs(pid) == {"named"}
    bank.episode(next(p.stem for p in (bank.root / "episodes").glob("*.md")),
                 {"url": X, "origin": "x-bookmarks", "media_entity_id": pid, "named": {"why": "link", "at": "2026-11-21"}})
    bank_index.invalidate()
    assert bank.signs(pid) == {"named"}


# --------------------------------------------------------------------------------------------------- the flip


def test_with_the_constant_off_nothing_is_hidden_and_no_key_moves(bank):
    bank.post()
    assert saved_posts.HIDE_POSTS is False
    assert saved_posts.hidden_ids(bank.root) == frozenset() and saved_posts.earned_ids(bank.root) == frozenset()
    assert saved_posts.stamp(bank.root) == ""
    assert saved_posts.drawn_as_page(bank.root, "media-a-post", media(X))
    assert saved_posts.filter_related(bank.root, "## Related\n- [[media a post]] — about\n") == \
        "## Related\n- [[media a post]] — about\n"


def test_with_it_on_a_row_is_hidden_and_an_earned_post_is_a_page(bank, on):
    row = bank.post("media-row", url="https://x.com/alex_example/status/1")
    kept = bank.post("media-kept", url="https://x.com/alex_example/status/2", save={"saved_why": {"answer": "x"}})
    work = bank.post("media-work", url="https://example.com/an-article")
    assert saved_posts.hidden_ids(bank.root) == {row}
    assert saved_posts.earned_ids(bank.root) == {kept}
    assert not saved_posts.drawn_as_page(bank.root, row, media(X)) and saved_posts.drawn_as_page(bank.root, kept, media(X))
    assert saved_posts.drawn_as_page(bank.root, work, media("https://example.com/an-article"))


def test_the_stamp_moves_only_when_the_earned_set_does(bank, on):
    bank.post("media-a", url="https://x.com/alex_example/status/1")
    first = saved_posts.stamp(bank.root)
    assert first
    bank.episode("ep_2026-11-23_001", {"source": "claude-code"}, "user: an unrelated chat\n")
    bank_index.invalidate()
    assert saved_posts.stamp(bank.root) == first                      # an unrelated capture: no move
    bank.post("media-b", url="https://x.com/alex_example/status/2")
    assert saved_posts.stamp(bank.root) == first                      # a new row: no move
    bank.post("media-c", url="https://x.com/alex_example/status/3", save={"saved_why": {"answer": "x"}})
    assert saved_posts.stamp(bank.root) != first                      # a why-answer on a save: it moves


# --------------------------------------------------------------------------------------------------- Related lines


RELATED = """## Summary
An alpha tool.

## Related
- [[media row]] — about
- [[Bob Example]] — works with
- [[media kept]] — about
- mentioned: 4 pages — latest [[media row]], [[Bob Example]] and 2 more

## Other
text [[media row]]
"""


def test_a_hidden_posts_related_line_is_dropped_and_nothing_else(bank, on):
    bank.post("media-row", url="https://x.com/alex_example/status/1")
    bank.post("media-kept", url="https://x.com/alex_example/status/2", save={"saved_why": {"answer": "x"}})
    bank.page("bob-example", {"name": "Bob Example", "type": "person", "status": "active"})
    bank_index.invalidate()
    out = saved_posts.filter_related(bank.root, RELATED)
    assert "- [[media row]] — about" not in out and "[[media kept]] — about" in out and "[[Bob Example]] — works with" in out
    assert "latest [[Bob Example]] and 2 more" in out and "text [[media row]]" in out   # prose outside Related stays
    assert "[[media row]]" not in out.split("## Other")[0]


def test_a_related_section_left_empty_goes_and_a_shared_name_keeps_its_line(bank, on):
    bank.post("media-row", url="https://x.com/alex_example/status/1")
    text = "## Summary\nx\n\n## Related\n- [[media row]] — about\n\n## Other\ny\n"
    assert "## Related" not in saved_posts.filter_related(bank.root, text)
    bank.page("media-row-twin", {"name": "media row", "type": "person", "status": "active"})   # another page, same name
    bank_index.invalidate()
    assert "- [[media row]] — about" in saved_posts.filter_related(bank.root, text)


# --------------------------------------------------------------------------------------------------- one predicate


def test_every_reader_asks_saved_posts_and_none_holds_a_copy():
    root = Path(__file__).resolve().parents[1]
    readers = ["services/graph_builder.py", "services/meaning_neighbors.py", "services/hub_builder.py",
               "services/quiet_pages.py", "services/media_kinds.py", "routers/graph.py", "routers/entities.py"]
    for name in readers:
        assert "saved_posts" in (root / name).read_text(), name
    assert "page_is_dimmed" in (root / "services/inbox_service.py").read_text()     # the inbox asks through quiet_pages
    for path in sorted((root / "services").glob("*.py")) + sorted((root / "routers").glob("*.py")):
        if path.name == "saved_posts.py":
            continue
        text = path.read_text()
        # no second statement of the rule: the site list and the declared kinds live in one module
        assert "POST_SITES" not in text and "DECLARED_WORKS" not in text, path.name
        assert not re.search(r'canonical\("(x|instagram|linkedin|reddit|pinterest|tiktok)"', text) or path.name in (
            "saved_lists.py", "mcp_tools.py", "site_saves.py", "saved_exports.py", "connectors"), path.name


def test_the_earned_keys_are_the_one_person_definition_minus_a_folders_reason():
    assert set(saved_posts.EARNED_KEYS) == set(history_index.PERSON_KEYS) - {history_index.FOLDER_READ_KEY}
    assert history_index.FOLDER_READ_KEY in history_index.PERSON_KEYS


# --------------------------------------------------------------------------------------------------- quiet and hubs


def test_a_post_that_earned_its_page_is_not_dimmed_only_once_the_flip_is_on(bank, monkeypatch):
    pid = bank.post(save={"saved_why": {"answer": "x"}})
    row = bank.post("media-row", url="https://x.com/alex_example/status/9")
    assert quiet_pages.page_is_dimmed(bank.root, pid) and quiet_pages.page_is_quiet(bank.root, pid)   # today's answer
    monkeypatch.setattr(saved_posts, "HIDE_POSTS", True)
    assert not quiet_pages.page_is_dimmed(bank.root, pid)             # an ordinary page: the inbox may ask about it
    assert quiet_pages.page_is_quiet(bank.root, pid)                  # the mention readers' own rule is unchanged
    assert quiet_pages.page_is_dimmed(bank.root, row)                 # a row is never asked about


def test_a_list_page_is_never_quiet(bank):
    bank.episode("ep_2026-11-20_700", {"media_entity_id": "list-x-bookmarks"})
    bank.page("list-x-bookmarks", {"name": "X: Bookmarks", "type": "media", "status": "active",
                                   "source_episodes": ["ep_2026-11-20_700"], "media": {"kind": "list"},
                                   "list": {"stream": "x.bookmarks", "source": "x"}})
    bank_index.invalidate()
    assert not quiet_pages.page_is_quiet(bank.root, "list-x-bookmarks")


def test_hubs_take_an_earned_post_and_never_a_row_or_a_list_page(bank, monkeypatch):
    row = bank.post("media-row", url="https://x.com/alex_example/status/1")
    kept = bank.post("media-kept", url="https://x.com/alex_example/status/2", save={"saved_why": {"answer": "x"}})
    bank.page("list-x-bookmarks", {"name": "X: Bookmarks", "type": "media", "status": "active", "media": {"kind": "list"}})
    off, total_off = hub_builder._load_active_entities(bank.root / "entities")
    assert {m["id"] for m in off} == {row, kept}                       # a list page is no member even today
    monkeypatch.setattr(saved_posts, "HIDE_POSTS", True)
    on_, total_on = hub_builder._load_active_entities(bank.root / "entities")
    assert {m["id"] for m in on_} == {kept} and total_on == total_off == 3     # still counted as files


# --------------------------------------------------------------------------------------------------- the graph


def graph(bank, **kw):
    graph_builder.reset_cache()
    return graph_builder.build_graph(bank.root, **kw)


def edges(bank, rows):
    markdown_parser.write_yaml(bank.root / "graph_edges.yaml", {"edges": rows})
    bank_index.invalidate()


def test_the_graph_is_what_it_was_while_the_constant_is_off(bank):
    row = bank.post("media-row", url="https://x.com/alex_example/status/1")
    bank.post("media-kept", url="https://x.com/alex_example/status/2", save={"saved_why": {"answer": "x"}})
    bank.page("alpha-tool", {"name": "Alpha tool", "type": "tool", "status": "active"})
    edges(bank, [{"source": row, "target": "alpha-tool", "label": "about"}])
    g = graph(bank)
    nodes = {n.id: n for n in g.nodes}
    assert row in nodes and nodes[row].media_kind == "link" and nodes[row].quiet is True
    assert nodes["media-kept"].quiet is True and nodes["alpha-tool"].degree == 1
    assert [(l.source, l.target) for l in g.links] == [(row, "alpha-tool")]


def test_a_row_is_no_node_no_line_and_no_degree_once_the_flip_is_on(bank, on):
    row = bank.post("media-row", url="https://x.com/alex_example/status/1")
    kept = bank.post("media-kept", url="https://x.com/alex_example/status/2", save={"saved_why": {"answer": "x"}})
    work = bank.post("media-work", url="https://example.com/an-article")
    bank.page("alpha-tool", {"name": "Alpha tool", "type": "tool", "status": "active"})
    edges(bank, [{"source": row, "target": "alpha-tool", "label": "about"},
                 {"source": kept, "target": "alpha-tool", "label": "about"},
                 {"source": work, "target": "alpha-tool", "label": "about"}])
    g = graph(bank)
    nodes = {n.id: n for n in g.nodes}
    assert row not in nodes and kept in nodes and work in nodes
    assert nodes["alpha-tool"].degree == 2                                     # the row's edge no longer counts
    assert {(l.source, l.target) for l in g.links} == {(kept, "alpha-tool"), (work, "alpha-tool")}
    assert nodes[kept].media_kind == "post" and nodes[kept].quiet is False     # an earned post is an ordinary page
    assert nodes[work].media_kind == "link" and nodes[work].quiet is True      # a work's own rule is unchanged


def test_include_posts_draws_every_post_with_its_own_cache_slot(bank, on):
    row = bank.post("media-row", url="https://x.com/alex_example/status/1")
    graph_builder.reset_cache()
    plain = graph_builder.build_graph(bank.root)
    everything = graph_builder.build_graph(bank.root, include_posts=True)
    assert row not in {n.id for n in plain.nodes} and row in {n.id for n in everything.nodes}
    assert graph_builder.build_graph(bank.root) is plain and graph_builder.build_graph(bank.root, include_posts=True) is everything


def test_a_why_answer_with_no_page_change_moves_the_cache_key_and_an_unrelated_capture_does_not(bank, on):
    bank.post("media-a", url="https://x.com/alex_example/status/1")
    first = graph(bank)
    assert "media-a" not in {n.id for n in first.nodes}
    cached = graph_builder.build_graph(bank.root)
    assert cached is first
    bank.episode("ep_2026-11-23_001", {"source": "claude-code"}, "user: an unrelated chat\n")
    bank_index.invalidate()
    assert graph_builder.build_graph(bank.root) is first                       # an unrelated capture: the cache holds
    ep = next(p.stem for p in (bank.root / "episodes").glob("*.md") if "media_entity_id" in p.read_text())
    markdown_parser.write(bank.root / "episodes" / f"{ep}.md",
                          {"id": ep, "source": "url", "url": X, "origin": "x-bookmarks", "media_entity_id": "media-a",
                           "timestamp": "2026-11-20T10:00:00+00:00", "saved_why": {"answer": "x"}}, "body\n")
    bank_index.invalidate()
    again = graph_builder.build_graph(bank.root)
    assert again is not first and "media-a" in {n.id for n in again.nodes}     # the page file never moved


def test_a_graph_build_leaves_a_git_tree_clean(bank, on):
    bank.post("media-a", url="https://x.com/alex_example/status/1")
    for cmd in (["init", "-q"], ["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "x"]):
        subprocess.run(["git", "-C", str(bank.root), *cmd], check=True, capture_output=True)
    graph(bank)
    saved_posts.verdict(bank.root)
    saved_posts.filter_related(bank.root, RELATED)
    out = subprocess.run(["git", "-C", str(bank.root), "status", "--porcelain"], capture_output=True, text=True).stdout
    assert out.strip() == ""


# --------------------------------------------------------------------------------------------------- the routes


def test_the_graph_etag_moves_with_the_earned_set_only_once_the_flip_is_on(bank, monkeypatch):
    from fastapi.testclient import TestClient

    from api import config, main

    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank.root))
    monkeypatch.setenv("CICADA_HOME", str(bank.root.parent / "home"))
    config.get_settings.cache_clear()
    bank.post("media-a", url="https://x.com/alex_example/status/1")
    try:
        with TestClient(main.app) as c:
            before = c.get("/graph").headers["etag"]
            assert [n["id"] for n in c.get("/graph").json()["nodes"] if n["id"] == "media-a"]
            monkeypatch.setattr(saved_posts, "HIDE_POSTS", True)
            hidden = c.get("/graph")
            assert hidden.headers["etag"] != before and "media-a" not in [n["id"] for n in hidden.json()["nodes"]]
            everything = c.get("/graph?include_posts=true")
            assert everything.headers["etag"] != hidden.headers["etag"]
            assert "media-a" in [n["id"] for n in everything.json()["nodes"]]
            assert c.get("/graph", headers={"if-none-match": hidden.headers["etag"]}).status_code == 304
    finally:
        config.get_settings.cache_clear()


def test_an_entity_page_filters_its_related_lines_and_every_wikilink_opens(bank, monkeypatch):
    from fastapi.testclient import TestClient

    from api import config, main

    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank.root))
    monkeypatch.setenv("CICADA_HOME", str(bank.root.parent / "home"))
    config.get_settings.cache_clear()
    bank.post("media-row", url="https://x.com/alex_example/status/1")
    bank.post("media-kept", url="https://x.com/alex_example/status/2", save={"saved_why": {"answer": "x"}})
    bank.page("bob-example", {"name": "Bob Example", "type": "person", "status": "active"})
    bank.page("alpha-tool", {"name": "Alpha tool", "type": "tool", "status": "active"}, body=RELATED)
    bank_index.invalidate()
    try:
        with TestClient(main.app) as c:
            held = c.get("/entities/alpha-tool")
            assert "[[media row]]" in held.json()["markdownContent"]                  # today's page, byte for byte
            monkeypatch.setattr(saved_posts, "HIDE_POSTS", True)
            after = c.get("/entities/alpha-tool", headers={"if-none-match": held.headers["etag"]})
            assert after.status_code == 200 and after.headers["etag"] != held.headers["etag"]   # the card is re-read
            body = after.json()["markdownContent"]
            assert "- [[media row]]" not in body and "[[media kept]]" in body
            names = {n["name"] for n in c.get("/graph").json()["nodes"]}
            related = body.split("## Related")[1].split("## Other")[0]
            assert all(link in names for link in re.findall(r"\[\[([^\]|]+)", related))   # every wikilink opens a node
            assert "[[media row]]" in after.json()["rawMarkdown"]                   # the Source view stays verbatim
    finally:
        config.get_settings.cache_clear()


# --------------------------------------------------------------------------------------------------- nothing is lost


def test_a_row_is_still_stored_found_by_recall_and_opens_from_its_card(tmp_path, monkeypatch):
    """Ruling 62's lean pass for a post drawn as a row: indexed, found when it comes up, openable to its words and link."""
    from fastapi.testclient import TestClient
    from _synthetic_bank import _bank

    from api import config, main
    from api.services import media_ingestor, saved_lookup, search_index
    from api.services.media_ingestor import MediaMeta, PreparedItem, RawItem

    memory = _bank(tmp_path)
    item = RawItem(url="https://x.com/alex_example/status/1234567890123", title="Sourdough hydration thread",
                   origin="x-bookmarks")
    res = media_ingestor.write_prepared(PreparedItem(item, MediaMeta(title="Sourdough hydration thread", site="x.com",
                                                                     media_type="url")), memory, {})
    bank_index.invalidate()
    search_index.refresh(memory)
    monkeypatch.setattr(saved_posts, "HIDE_POSTS", True)
    assert res.media_entity_id in saved_posts.hidden_ids(memory)
    assert [h.url for h in saved_lookup.find(memory, "sourdough hydration", min_shared=1)] == [item.url]
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    config.get_settings.cache_clear()
    try:
        with TestClient(main.app) as c:
            card = c.get(f"/entities/{res.media_entity_id}")
            assert card.status_code == 200 and card.json()["media"]["url"] == item.url
            assert res.media_entity_id not in {n["id"] for n in c.get("/graph").json()["nodes"]}
    finally:
        config.get_settings.cache_clear()
    assert (memory / "entities" / f"{res.media_entity_id}.md").exists()          # the file is never moved or deleted


def test_the_inbox_never_asks_about_a_row_and_may_about_an_earned_post(bank, monkeypatch):
    from api.services import inbox_service

    row = bank.post("media-row", url="https://x.com/alex_example/status/1")
    kept = bank.post("media-kept", url="https://x.com/alex_example/status/2", save={"saved_why": {"answer": "x"}})
    assert inbox_service._subject_quiet(bank.root, row) and inbox_service._subject_quiet(bank.root, kept)   # today
    monkeypatch.setattr(saved_posts, "HIDE_POSTS", True)
    assert inbox_service._subject_quiet(bank.root, row) and not inbox_service._subject_quiet(bank.root, kept)


# --------------------------------------------------------------------------------------------------- meaning neighbours


def test_a_hidden_post_takes_no_neighbour_slot(tmp_path, monkeypatch):
    import numpy as np

    from api.services import meaning_neighbors
    from api.services.vector_index import SqliteVecIndexer

    directions = {"film-notes": [1.0, 0.1, 0.0, 0.0], "film-post": [0.99, 0.1, 0.0, 0.0],
                  "film-essay": [0.9, 0.3, 0.0, 0.0], "unrelated": [0.0, 0.0, 0.0, 1.0]}

    def embed(texts, *, is_query=False):
        return np.array([directions[next(k for k in directions if k.replace("-", " ") in t.lower())] for t in texts],
                        dtype=np.float32)

    memory = tmp_path / "bank"
    b = Bank(memory)
    for stem in ("film-notes", "film-essay", "unrelated"):
        b.page(stem, {"name": stem.replace("-", " "), "type": "concept", "status": "active", "confidence": 0.5},
               f"About {stem.replace('-', ' ')}.")
    b.post("film-post", url="https://x.com/alex_example/status/7", page={"name": "film post"})
    bank_index.invalidate()
    SqliteVecIndexer(memory, embed_fn=embed).index_entities()
    meaning_neighbors._cache.clear()
    off = meaning_neighbors.neighbors(memory)
    assert any("film-post" in (a, b_) for a, b_, _ in off["pairs"]) and off["embedded"] == 4
    monkeypatch.setattr(saved_posts, "HIDE_POSTS", True)
    on_ = meaning_neighbors.neighbors(memory)
    assert not any("film-post" in (a, b_) for a, b_, _ in on_["pairs"]) and on_["embedded"] == 3
    assert meaning_neighbors.signature(memory)[-1] == saved_posts.stamp(memory) != ""     # a key that moves with the set


def test_a_row_still_counts_toward_a_shared_title(bank, monkeypatch):
    """`same_name`'s map is every page's, keyed on the folder's stamp and read by the card and search too: building the
    graph without a row must not prime it with a partial set."""
    from api.services import same_name

    bank.post("media-row", url="https://x.com/alex_example/status/1", page={"name": "Thing"})
    bank.page("thing-tool", {"name": "Thing", "type": "tool", "status": "active"})
    bank_index.invalidate()
    held = {}
    for flag in (False, True):
        monkeypatch.setattr(saved_posts, "HIDE_POSTS", flag)
        graph(bank)
        held[flag] = same_name._CACHE[str(bank.root)][2]
    assert held[True] == held[False] and sorted(held[True]["thing"]) == ["media-row", "thing-tool"]
