"""G89 (owner 2026-11-04: "a direct app integration is best to see history of read stuff, saved stuff, etc."): Substack
gives a reader no API, no reader export and no Mac app, so the person's own agent keeps their Substack current from
their signed-in browser — Saved as indexed saves, History as reading days, Subscriptions as followed public feeds —
on the G206 rails (their switch, one site at a time, the shared day bound, never a sign-in). Also the feed side: a
post says which publication it came from, a paid post's stub never stands in for its words, and a feed the person
unfollowed is never followed again by an automatic writer. Synthetic bank; placeholder publications and words."""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone

import pytest

from _reading_fixtures import git_log, porcelain, reading  # noqa: F401 — `reading` is a fixture
from api.remote import catalog
from api.services import (demo_guard, episode_time, feed_registry, history_index, markdown_parser, media_ingestor,
                          reading_queue, reading_settings, saved_lists, substack, substack_lists, substack_reads)

POST_A = "https://alpha-example.substack.com/p/notes-on-indexes"
POST_B = "https://open.substack.com/pub/bob-example/p/a-week-of-vectors?r=abc&utm_medium=ios"
POST_C = "https://substack.com/@carol-example/p-123456789"
POST_D = "https://www.dana-example.org/p/on-memory"


@pytest.fixture(autouse=True)
def utc(monkeypatch):
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def _on(*names):
    reading_settings.update(substack_lists_={n: True for n in names})


def _record(server, name, outcome="read", items=None, **kw):
    args = {"list": name, "outcome": outcome, **kw}
    if items is not None:
        args["items"] = items
    return server.handle_tool("cicada_record_substack_list", args)


def _episode_of(memory, url):
    entry = media_ingestor.load_url_index(memory)[media_ingestor.url_hash(url)]
    entry = media_ingestor.load_url_index(memory).get(entry.get("alias_of"), entry)
    return markdown_parser.parse(memory / "episodes" / f"{entry['episode_id']}.md").frontmatter


# --- what a Substack link is ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("url,canonical", [
    (POST_A, POST_A),
    (POST_A + "/?utm_source=feed", POST_A),
    (POST_B, "https://bob-example.substack.com/p/a-week-of-vectors"),
    (POST_C, "https://substack.com/home/post/p-123456789"),
    ("https://substack.com/home/post/p-123456789", "https://substack.com/home/post/p-123456789"),
    (POST_D, POST_D),
])
def test_a_post_is_one_canonical_url_whatever_door_spelled_it(url, canonical):
    found = substack.post(url)
    assert found is not None and found[0] == canonical


@pytest.mark.parametrize("url", [
    "https://alpha-example.substack.com/", "https://alpha-example.substack.com/archive",
    "https://substack.com/@carol-example", "https://substack.com/inbox", "https://www.substack.com/p/x",
    "https://open.substack.com/pub/alpha-example", "https://alpha-example.substack.com/note/c-1",
    "javascript:alert(1)", "", None, "https://dana-example.org/about",
])
def test_anything_that_is_not_a_post_is_not_one(url):
    assert substack.post(url) is None


@pytest.mark.parametrize("url,feed", [
    ("https://alpha-example.substack.com", "https://alpha-example.substack.com/feed"),
    ("https://alpha-example.substack.com/p/notes-on-indexes", "https://alpha-example.substack.com/feed"),
    ("https://open.substack.com/pub/bob-example", "https://bob-example.substack.com/feed"),
    ("https://www.dana-example.org/", "https://www.dana-example.org/feed"),
])
def test_a_publication_is_followed_through_its_own_public_feed(url, feed):
    assert substack.publication(url)[1] == feed


@pytest.mark.parametrize("url", ["https://substack.com/@carol-example", "https://substack.com/home",
                                 "https://www.substack.com/", "ftp://alpha-example.substack.com", "not a url"])
def test_a_profile_or_substacks_own_page_is_no_publication(url):
    assert substack.publication(url) is None


STUB = ('<p>The first sentence of a paid post.</p><p><a href="https://alpha-example.substack.com/p/paid">Read more</a>'
        '</p>')


def test_a_paid_posts_stub_is_told_from_a_post():
    assert substack.is_paywall_stub(STUB)
    assert not substack.is_paywall_stub("<p>" + "A long free post. " * 60 + '</p><a href="x">Read more</a>')
    assert not substack.is_paywall_stub("<p>Short and free, with no link.</p>")
    assert not substack.is_paywall_stub(None)


FEED = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
<channel><title>Alpha Example</title><link>https://alpha-example.substack.com</link>
<item><title>Notes on indexes</title><link>{POST_A}</link>
<pubDate>Mon, 02 Nov 2026 10:00:00 GMT</pubDate>
<content:encoded><![CDATA[<p>{"A free post about indexes. " * 40}</p>]]></content:encoded></item>
<item><title>A paid post</title><link>https://alpha-example.substack.com/p/paid</link>
<pubDate>Tue, 03 Nov 2026 10:00:00 GMT</pubDate>
<description><![CDATA[{STUB}]]></description></item>
</channel></rss>"""


def test_a_feed_item_names_its_publication_and_a_stub_never_stands_in_for_a_post():
    items = media_ingestor.parse_rss(FEED)
    assert [i.channel for i in items] == ["Alpha Example", "Alpha Example"]
    assert items[0].preview and "indexes" in items[0].preview
    assert items[1].preview is None and items[1].title == "A paid post"
    assert items[1].published_at.startswith("2026-11-03")


def test_an_atom_feed_names_its_publication_too():
    atom = ('<feed xmlns="http://www.w3.org/2005/Atom"><title>Bob Example</title><entry><title>T</title>'
            '<link href="https://bob-example.org/p/t"/><updated>2026-11-01T00:00:00Z</updated></entry></feed>')
    assert media_ingestor.parse_rss(atom)[0].channel == "Bob Example"


# --- the feed registry remembers an unfollow -----------------------------------------------------------------------


def test_an_unfollowed_feed_is_never_followed_again_by_an_automatic_writer_only_by_the_person(tmp_path):
    memory = tmp_path / "bank"
    memory.mkdir()
    feed = "https://alpha-example.substack.com/feed"
    first = feed_registry.subscribe_feed(memory, feed, tags=["substack"], title="Alpha Example",
                                         via="substack-subscriptions", automatic=True)
    assert first["title"] == "Alpha Example" and first["via"] == "substack-subscriptions"
    assert feed_registry.unsubscribe_feed(memory, feed)
    assert feed_registry.removed_feeds(memory) == {media_ingestor.normalize_url(feed)}
    assert feed_registry.subscribe_feed(memory, feed, automatic=True) is None
    assert feed_registry.list_feeds(memory) == []
    # A poll rewrites the registry and keeps the memory of the removal.
    feed_registry._write_feeds_file(memory, [])
    assert feed_registry.removed_feeds(memory)
    again = feed_registry.subscribe_feed(memory, feed)                 # the person's own subscribe
    assert again is not None and feed_registry.removed_feeds(memory) == set()


def test_a_title_fills_a_record_that_lacks_one_and_a_repeat_writes_nothing(tmp_path):
    memory = tmp_path / "bank"
    memory.mkdir()
    feed = "https://alpha-example.substack.com/feed"
    feed_registry.subscribe_feed(memory, feed)
    feed_registry.subscribe_feed(memory, feed, tags=["substack"], title="Alpha Example")
    assert feed_registry.list_feeds(memory)[0]["title"] == "Alpha Example"
    before = (memory / "feeds.yaml").stat().st_mtime_ns
    time.sleep(0.01)
    feed_registry.subscribe_feed(memory, feed, tags=["substack"], title="Another name")
    assert (memory / "feeds.yaml").stat().st_mtime_ns == before
    assert feed_registry.list_feeds(memory)[0]["title"] == "Alpha Example"


# --- the switch and the offer --------------------------------------------------------------------------------------


def test_off_by_default_and_needs_the_sheet(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    assert reading_settings.snapshot()["substackLists"] == {"saved": False, "liked": False, "history": False, "subscriptions": False}
    with pytest.raises(reading_settings.SettingsError):
        reading_settings.update(substack_lists_={"saved": True})
    with pytest.raises(reading_settings.SettingsError):
        reading_settings.update(acknowledge=True, substack_lists_={"likes": True})
    reading_settings.update(acknowledge=True)
    assert not any(substack_lists.allowed(n) for n in substack_lists.LISTS)
    reading_settings.update(substack_lists_={"history": True})
    assert substack_lists.allowed("history") and not substack_lists.allowed("saved")
    reading_settings.update(agent_enabled_=False)
    assert not substack_lists.allowed("history")
    reading_settings.update(agent_enabled_=True, substack_lists_={"history": False})
    assert reading_settings.snapshot()["substackListsOff"]["history"] is True


def test_offered_one_list_at_a_time_after_every_other_sites_list(reading):
    server, memory = reading
    assert substack_lists.due(memory) == []
    _on("saved", "history")
    reading_settings.update(saved_lists_={"x": True})
    assert substack_lists.due(memory) == []                   # X's list is due: one site's list at a time
    assert "x.com/i/bookmarks" in server.handle_tool("cicada_reading_queue", {})
    saved_lists.note(memory, "x", "read", items=1)
    assert substack_lists.due(memory) == ["saved"]
    out = server.handle_tool("cicada_reading_queue", {})
    assert "https://substack.com/inbox" in out and "open Saved" in out and "History" not in out
    assert "`cicada_record_substack_list(" in out and "do not sign in" in out and "never click" in out
    assert reading_queue.counts(memory)[0] == 1
    _record(server, "saved", items=[{"url": POST_A, "title": "Notes on indexes"}])
    assert substack_lists.due(memory) == ["history"]
    later = datetime.now(timezone.utc) + timedelta(hours=21)
    assert substack_lists.due(memory, now=later) == []        # X's list is due again first
    reading_settings.update(saved_lists_={"x": False})
    assert substack_lists.due(memory, now=later) == ["saved"]
    assert saved_lists.reads_today(memory) == 2               # the Substack read spent the shared day bound


def test_the_shared_day_bound_stops_the_offer_and_the_record(reading):
    server, memory = reading
    _on("saved")
    for _ in range(saved_lists.DAILY_READS):
        saved_lists.count_read(memory)
    assert substack_lists.due(memory) == []
    before = porcelain(memory)
    out = _record(server, "saved", items=[{"url": POST_A}])
    assert out.startswith("Not recorded:") and "today" in out
    assert porcelain(memory) == before


def test_needs_login_pauses_every_substack_list_and_turning_one_on_is_try_again(reading):
    server, memory = reading
    _on("saved", "subscriptions")
    before = porcelain(memory)
    out = _record(server, "saved", "needs_login")
    assert "do not sign in" in out.lower() and porcelain(memory) == before
    assert substack_lists.paused_until() is not None and substack_lists.due(memory) == []
    substack_lists.resume()
    assert substack_lists.due(memory) == ["saved"]


def test_the_record_tool_is_never_offered_to_a_remote_connection():
    assert "cicada_record_substack_list" in catalog.NEVER_REMOTE


def test_refusals_write_nothing(reading, monkeypatch):
    server, memory = reading
    before = porcelain(memory)
    assert _record(server, "saved", items=[{"url": POST_A}]).startswith("Not recorded: the person has not")
    _on("saved")
    assert _record(server, "likes").startswith("Error: list must be")
    assert _record(server, "saved", "maybe").startswith("Error: outcome")
    assert _record(server, "saved").startswith("Error: a read needs `items`")
    monkeypatch.setattr(demo_guard, "is_demo", lambda path: True)
    assert "demo" in _record(server, "saved", items=[{"url": POST_A}]).lower()
    assert porcelain(memory) == before


# --- what a read writes ------------------------------------------------------------------------------------------


def test_saved_posts_are_indexed_saves_and_one_a_feed_brought_in_is_never_saved_twice(reading):
    import asyncio

    server, memory = reading
    _on("saved")
    asyncio.run(media_ingestor.ingest_batch([media_ingestor.RawItem(url=POST_A, title="Notes on indexes",
                                                                    origin="rss", defer_enrich=True)],
                                            memory, from_bookmark_file=False, commit=True))
    out = _record(server, "saved", items=[
        {"url": POST_A + "?utm_source=substack", "title": "Notes on indexes", "author": "Alice Example",
         "publication": "Alpha Example"},
        {"url": POST_B, "title": "A week of vectors", "author": "Bob Example", "publication": "Bob Example"},
        {"url": "https://substack.com/@carol-example", "title": "a profile"},
    ], via="browser tools")
    assert "1 new post(s) saved; 1 already in memory" in out and "1 row(s) were not Substack posts" in out
    fm = _episode_of(memory, "https://bob-example.substack.com/p/a-week-of-vectors")
    assert fm["origin"] == "substack-saved" and fm["folder"] == "Saved"
    assert fm["processed"] is True and fm["processed_by"] == history_index.INDEXED_BY      # ruling 30
    assert history_index.kind(fm) == "list"
    # The open.substack.com spelling is an alias: a later paste of it is the same row.
    idx = media_ingestor.load_url_index(memory)
    assert media_ingestor.existing_hash(media_ingestor.RawItem(
        url="https://open.substack.com/pub/bob-example/p/a-week-of-vectors"), idx) is not None
    log = git_log(memory)
    assert "Cicada-Author: claude-code" in log and "Cicada-Session: ses_read_fixed" in log
    assert porcelain(memory) == ""


def test_history_becomes_reading_days_dated_by_the_page_else_first_seen_and_never_twice(reading):
    server, memory = reading
    _on("history")
    today = datetime.now().astimezone().date()
    out = _record(server, "history", items=[
        {"url": POST_A, "title": "Notes on indexes", "author": "Alice Example", "publication": "Alpha Example",
         "read_on": "2026-10-30"},
        {"url": POST_C, "title": "On recall", "publication": "Carol Example"},
        {"url": POST_D, "title": "On memory", "read_on": (today + timedelta(days=3)).isoformat()},   # never a future day
        {"url": "https://substack.com/inbox", "title": "not a post"},
    ])
    assert "3 read posts kept across 2 days" in out and "1 row(s) were not Substack posts" in out
    days = {p.stem: p for p in (memory / "sources" / "reading" / "substack").glob("*.json")}
    assert set(days) == {"2026-10-30", today.isoformat()}
    episodes = {markdown_parser.parse(p).frontmatter.get("source_id"): markdown_parser.parse(p)
                for p in (memory / "episodes").glob("*.md")}
    first = episodes[f"reading-history:substack:{today.isoformat()}"]
    fm = first.frontmatter
    assert fm["source"] == "reading-history" and fm["origin"] == "substack-history"
    assert fm["processed_by"] == history_index.INDEXED_BY and history_index.kind(fm) == "reading"
    assert "read on or before it" in first.body and "On recall — Carol Example" in first.body
    assert "reading-history:substack:2026-10-30" in episodes
    # A second read of the same history adds nothing; a new post lands on today.
    again = _record(server, "history", items=[{"url": POST_A, "read_on": "2026-10-30"}, {"url": POST_C}])
    assert "No new reading history" in again
    assert porcelain(memory) == ""


def test_subscriptions_follow_each_publications_own_feed_never_one_the_person_unfollowed(reading):
    server, memory = reading
    _on("subscriptions")
    feed_registry.subscribe_feed(memory, "https://bob-example.substack.com/feed")
    feed_registry.unsubscribe_feed(memory, "https://bob-example.substack.com/feed")      # the person unfollowed it
    out = _record(server, "subscriptions", items=[
        {"url": "https://alpha-example.substack.com", "name": "Alpha Example"},
        {"url": "https://open.substack.com/pub/bob-example", "name": "Bob Example"},
        {"url": "https://www.dana-example.org/", "name": "Dana Example"},
        {"url": "https://substack.com/@carol-example", "name": "a person"},
    ])
    assert "2 publication(s) now followed" in out and "unfollowed in Cicada, left alone" in out
    assert "1 row(s) were not publications" in out
    feeds = feed_registry.list_feeds(memory)
    assert [(f["url"], f["title"], f["tags"]) for f in feeds] == [
        ("https://alpha-example.substack.com/feed", "Alpha Example", ["substack"]),
        ("https://www.dana-example.org/feed", "Dana Example", ["substack"])]
    assert porcelain(memory) == ""
    assert "feeds.yaml" in git_log(memory)
    # Weekly, not daily.
    assert substack_lists.due(memory) == []
    assert substack_lists.due(memory, now=datetime.now(timezone.utc) + timedelta(days=8)) == ["subscriptions"]


def test_a_reading_day_is_never_a_time_signal_from_a_model_read():
    fm = {"source": "reading-history", "source_id": "reading-history:substack:2026-11-01", "origin": "substack-history"}
    assert history_index.is_index_only(fm)
    assert substack_reads.source_id(date(2026, 11, 1)) == fm["source_id"]
    assert episode_time.counts_as_activity({"origin": "rss", "published_at": "2026-11-01T00:00:00+00:00"}) is False


# --- ROR-138 -------------------------------------------------------------------------------------------------------


def test_a_feed_item_page_says_it_came_from_a_feed_not_that_it_was_saved():
    from api.services import media_ingestor
    from api.services.media_ingestor import MediaMeta

    meta = MediaMeta(title="A post", description="", site="example.com", channel=None, media_type="url")
    assert media_ingestor._entity_body(meta, None, "rss").splitlines()[1] == "From a feed — A post."
    assert media_ingestor._entity_body(meta, None, "substack-saved").splitlines()[1] == "Saved url — A post."
    assert media_ingestor._entity_body(meta, None).splitlines()[1] == "Saved url — A post."


def test_media_kinds_split_by_what_the_page_is():
    from api.services import media_kinds

    def page(origin=None, **media):
        return {"type": "media", "origin": origin, "media": media}

    assert media_kinds.kind_of({"type": "person"}) is None
    assert media_kinds.kind_of(page(kind="book", media_type="book")) == "book"
    assert media_kinds.kind_of(page("youtube-playlist", media_type="youtube")) == "video"
    assert media_kinds.kind_of(page("rss", media_type="url")) == "feed"
    assert media_kinds.kind_of(page("substack-saved", media_type="url")) == "article"
    assert media_kinds.kind_of(page("chrome-bookmark", media_type="bookmark")) == "link"
    assert media_kinds.origin_of(page("rss")) == "rss"
    assert media_kinds.channel_of(page(channel="  A  Channel ")) == "A Channel"


def test_the_liked_list_saves_under_its_own_folder(tmp_path):
    assert "liked" in substack_lists.LISTS
    assert substack_lists.FOLDER_LIKED != substack_lists.FOLDER_SAVED
    assert "liked" in reading_settings.SUBSTACK_LISTS
