"""G246 (ruling 81), Track 3: "Saved another way". A post can reach Cicada through a door other than its site's own list (a
link pasted, the notch, a browser's bookmark, an agent's save, a chat). Once posts are drawn as rows under their lists, such
a post would show nowhere under its site; so each post site gains one more stream whose members are the site's posts from
any door that sit on none of its other streams, with a list page like the others.

Everything is dark behind `saved_posts.HIDE_POSTS`: every test that asserts a change runs with the constant on, and the
door test has a twin that pins the same surface with it off. The saves are written by the REAL writers (the list read, the
in-site save route, the bookmark sync, the paste route, an agent's `cicada_save_url`, the Telegram capture); only the
network is cut. Synthetic names and words only.
"""
from __future__ import annotations

import asyncio
import json
import plistlib
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from _reading_fixtures import reading  # noqa: F401 - a fixture
from api import config, main
from api.services import (bank_index, bookmark_sync, channel_items, graph_builder, list_pages, markdown_parser,
                          media_ingestor, reading_settings, saved_posts, source_overview, source_streams, telegram_capture)

STATUS = "https://x.com/alex_example/status/{n}"
ANOTHER = "x.another-way"


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    bank_index.invalidate()
    graph_builder.reset_cache()

    async def offline(url, client, from_bookmark_file=False):      # no network: the title is made from the link
        return media_ingestor.MediaMeta(title=media_ingestor._fallback_title(url), description="",
                                        site=media_ingestor._site_of(url),
                                        media_type=media_ingestor._classify(url, from_bookmark_file=from_bookmark_file))

    monkeypatch.setattr(media_ingestor, "enrich", offline)
    yield
    bank_index.invalidate()
    graph_builder.reset_cache()


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(saved_posts, "HIDE_POSTS", True)


def _client(memory, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    return TestClient(main.app)


def _page_id(memory: Path, url: str) -> str:
    index = media_ingestor.load_url_index(memory)
    entry = index[media_ingestor.url_hash(url)]
    return index.get(entry.get("alias_of"), entry)["media_entity_id"]


def _frontmatter(memory: Path, page: str) -> dict:
    return markdown_parser.parse(memory / "entities" / f"{page}.md").frontmatter


def _streams(memory: Path) -> dict[str, dict]:
    body = source_streams.build(memory, channels=[])
    return {s["id"]: s for src in body["sources"] for s in src["streams"]}


# ------------------------------------------------------------------------------------------------ the seven doors


def _chrome(memory, monkeypatch, url):
    data = json.dumps({"version": 1, "roots": {
        "bookmark_bar": {"type": "folder", "name": "Bookmarks bar",
                         "children": [{"type": "url", "name": "A saved post", "url": url}]},
        "other": {"type": "folder", "name": "Other bookmarks", "children": []}}}).encode()
    asyncio.run(bookmark_sync.sync_bookmarks(memory, chrome_data=data))


def _safari(memory, monkeypatch, url):
    data = plistlib.dumps({"Title": "", "WebBookmarkType": "WebBookmarkTypeList", "Children": [
        {"WebBookmarkType": "WebBookmarkTypeList", "Title": "BookmarksBar", "Children": [
            {"WebBookmarkType": "WebBookmarkTypeLeaf", "URLString": url, "URIDictionary": {"title": "A saved post"}}]}]})
    asyncio.run(bookmark_sync.sync_bookmarks(memory, safari_data=data))


def _paste(memory, monkeypatch, url):
    r = _client(memory, monkeypatch).post("/sources/save", json={"url": url})
    assert r.status_code == 200, r.text


def _site_click(memory, monkeypatch, url):
    r = _client(memory, monkeypatch).post("/sources/site-save", json={"site": "x", "url": url})
    assert r.status_code == 200, r.text


def _list_read(memory, monkeypatch, url, server=None):
    reading_settings.update(saved_lists_={"x": True})
    out = server.handle_tool("cicada_record_saved_list", {
        "platform": "x", "outcome": "read", "items": [{"url": url, "author": "alex_example", "text": "A short post"}]})
    assert out.startswith("Recorded"), out


def _agent(memory, monkeypatch, url, server=None):
    out = server.handle_tool("cicada_save_url", {"url": url})
    assert "Error" not in out, out


def _chat(memory, monkeypatch, url):
    async def no_commit(memory_path, count, paths=None, **kw):
        return None

    monkeypatch.setattr(media_ingestor, "_commit_media", no_commit)
    assert asyncio.run(telegram_capture._default_save_url(memory, url))["status"] == "created"


#: door -> (the writer, the stream the post is on). The first two are the site's own list: they land on its Bookmarks.
DOORS = {
    "list read": (_list_read, "x.bookmarks"),
    "a save clicked in the site": (_site_click, "x.bookmarks"),
    "a Chrome bookmark": (_chrome, ANOTHER),
    "a Safari bookmark": (_safari, ANOTHER),
    "a pasted link": (_paste, ANOTHER),
    "an agent's save": (_agent, ANOTHER),
    "a chat": (_chat, ANOTHER),
}


def _save_through(door: str, reading, monkeypatch, url: str) -> None:
    server, memory = reading
    write = DOORS[door][0]
    if write in (_list_read, _agent):
        write(memory, monkeypatch, url, server=server)
    else:
        write(memory, monkeypatch, url)
    bank_index.invalidate()


@pytest.mark.parametrize("door", list(DOORS))
def test_a_post_saved_through_any_door_is_a_row_on_one_list_that_counts_and_shows_it(door, reading, monkeypatch, on):
    server, memory = reading
    url = STATUS.format(n=1000000000000000001)
    _save_through(door, reading, monkeypatch, url)
    page = _page_id(memory, url)
    fm = _frontmatter(memory, page)
    assert saved_posts.is_post(fm) and saved_posts.site_of(fm) == "x", "a post by the one rule, whatever the door"

    # On exactly one list, the right one, and on no other stream of its site (nor twice on that one).
    stream = DOORS[door][1]
    mem = source_streams.members(memory)
    assert mem.streams_of[page] == (stream,)
    assert [sid for sid, held in mem.members.items() if page in held] == [stream]

    # The stream row counts it ...
    row = _streams(memory)[stream]
    assert row["count"] == 1
    # ... its rows show it, once ...
    shown = channel_items.items(memory, "x", stream=stream)
    assert shown["all"] == 1 and [i["id"] for i in shown["items"]] == [page]
    # ... and so does its list page, which counts it too.
    list_pages.sync(memory)
    bank_index.invalidate()
    pages = list_pages.stream_pages(memory)
    assert pages[stream]["page"], "the list has a page"
    block = list_pages.block(memory, pages[stream]["page"], _frontmatter(memory, pages[stream]["page"]))
    assert block["count"] == 1 and len(block["recent"]) == 1 and block["stream"] == stream
    # The whole of the site's page is the sum of its streams: the post is in its listing once.
    assert [i["id"] for i in channel_items.items(memory, "x")["items"]].count(page) == 1
    assert channel_items.items(memory, "x")["all"] == 1


@pytest.mark.parametrize("door", list(DOORS))
def test_dark_no_door_changes_what_a_person_sees(door, reading, monkeypatch):
    monkeypatch.setattr(list_pages, "ON", False)   # the writer's own switch off (on since ruling 81a): still dark
    server, memory = reading
    assert saved_posts.HIDE_POSTS is False
    url = STATUS.format(n=1000000000000000002)
    _save_through(door, reading, monkeypatch, url)
    page = _page_id(memory, url)
    assert not any(sid.endswith(".another-way") for sid in _streams(memory)), "the stream does not exist"
    assert not any(spec.id.endswith(".another-way") for g in source_streams.groups() for spec in g.specs)
    mem = source_streams.members(memory)
    own = DOORS[door][1] == "x.bookmarks"
    assert mem.streams_of.get(page, ()) == (("x.bookmarks",) if own else ())    # a post on no list is on none, as on dev
    assert source_streams.another_way(memory) == {}
    list_pages.sync(memory)
    assert not list(memory.glob("entities/list-*.md")), "dark: no list page is written"
    shown = channel_items.items(memory, "x")
    assert ([i["id"] for i in shown["items"]] == [page]) is own, "the site's page lists what its origins brought, as on dev"
    assert not any("page" in s for s in _streams(memory).values())


# ------------------------------------------------------------------------------------------- the rule, site by site


POSTS = {
    "x": "https://x.com/alex_example/status/1000000000000000003",
    "instagram": "https://www.instagram.com/p/AbCdE12345/",
    "linkedin": "https://www.linkedin.com/feed/update/urn:li:activity:7000000000000000001/",
    "reddit": "https://www.reddit.com/r/example_sub/comments/abc123/a_thread_title/",
    "pinterest": "https://www.pinterest.com/pin/1234567890/",
    "tiktok": "https://www.tiktok.com/@alex_example/photo/7000000000000000001",
}


@pytest.mark.parametrize("site", list(POSTS))
def test_each_post_site_has_the_stream_and_a_pasted_post_of_it_is_there_and_only_there(site, reading, monkeypatch, on):
    server, memory = reading
    _paste(memory, monkeypatch, POSTS[site])
    bank_index.invalidate()
    page = _page_id(memory, POSTS[site])
    mem = source_streams.members(memory)
    assert mem.streams_of[page] == (f"{site}.another-way",)
    row = _streams(memory)[f"{site}.another-way"]
    assert (row["label"], row["kind"], row["count"], row["state"]) == ("Saved another way", "saved", 1, "on")
    assert source_streams.another_way(memory) == {site: frozenset({page})}
    # The stream's page names the site and says what the stream is, in plain words.
    list_pages.sync(memory)
    bank_index.invalidate()
    pid = list_pages.stream_pages(memory)[f"{site}.another-way"]["page"]
    fm = _frontmatter(memory, pid)
    assert list_pages.is_list(fm) and fm["name"].endswith(": Saved another way")
    assert "saved another way" in markdown_parser.parse(memory / "entities" / f"{pid}.md").body
    # Never another site's stream, and every other post site has none yet (it holds nothing, so it has no row).
    assert [s for s in _streams(memory) if s.endswith(".another-way")] == [f"{site}.another-way"]


def test_a_link_that_is_not_a_post_is_never_on_the_stream(reading, monkeypatch, on):
    server, memory = reading
    links = ["https://x.com/alex_example",                                            # a profile
             "https://www.linkedin.com/feed/update/urn:li:article:7000000000000000009/",  # an article
             "https://www.tiktok.com/@alex_example/video/7000000000000000002",           # a video, the video rail's
             "https://www.youtube.com/watch?v=abcdefghijk",
             "https://blog.bob-example.org/post/1"]
    for link in links:
        _paste(memory, monkeypatch, link)
    bank_index.invalidate()
    assert source_streams.another_way(memory) == {}
    assert not any(s.endswith(".another-way") for s in _streams(memory))
    list_pages.sync(memory)
    assert not list(memory.glob("entities/list-*.md"))


def test_a_post_on_a_real_list_is_on_that_list_and_not_also_here(reading, monkeypatch, on):
    server, memory = reading
    url = STATUS.format(n=1000000000000000004)
    _paste(memory, monkeypatch, url)                    # first kept as a pasted link: on no list
    bank_index.invalidate()
    assert source_streams.members(memory).streams_of[_page_id(memory, url)] == (ANOTHER,)
    _list_read(memory, monkeypatch, url, server=server)     # then the site's own list read names it: one page, a list
    bank_index.invalidate()
    page = _page_id(memory, url)
    assert source_streams.members(memory).streams_of[page] == ("x.bookmarks",)
    assert not source_streams.another_way(memory)
    assert not any(s.endswith(".another-way") for s in _streams(memory)), "empty again: no row"


def test_a_post_bookmarked_in_a_browser_after_the_site_list_is_one_page_on_the_one_list(reading, monkeypatch, on):
    server, memory = reading
    url = STATUS.format(n=1000000000000000005)
    _list_read(memory, monkeypatch, url, server=server)
    _chrome(memory, monkeypatch, url)
    bank_index.invalidate()
    page = _page_id(memory, url)
    assert len([p for p in (memory / "entities").glob("media-*.md")]) == 1
    assert source_streams.members(memory).streams_of[page] == ("x.bookmarks",)


def test_the_same_post_through_three_doors_is_one_member(reading, monkeypatch, on):
    server, memory = reading
    url = STATUS.format(n=1000000000000000006)
    _paste(memory, monkeypatch, url)
    _chrome(memory, monkeypatch, url)
    _safari(memory, monkeypatch, url)
    bank_index.invalidate()
    assert len(list((memory / "entities").glob("media-*.md"))) == 1
    (page,) = source_streams.another_way(memory)["x"]
    assert _streams(memory)[ANOTHER]["count"] == 1
    assert [i["id"] for i in channel_items.items(memory, "x", stream=ANOTHER)["items"]] == [page]


# ------------------------------------------------------------------------------------------------- honest counts


def test_counts_add_up_on_a_site_with_a_list_and_other_doors(reading, monkeypatch, on):
    server, memory = reading
    mine = [STATUS.format(n=2000000000000000000 + i) for i in range(3)]
    _list_read(memory, monkeypatch, mine[0], server=server)
    _site_click(memory, monkeypatch, mine[1])
    for i, url in enumerate(["https://x.com/a_user/status/3001", "https://x.com/b_user/status/3002"]):
        (_chrome, _paste)[i](memory, monkeypatch, url)
    _paste(memory, monkeypatch, mine[2])
    bank_index.invalidate()
    streams = _streams(memory)
    assert streams["x.bookmarks"]["count"] == 2 and streams[ANOTHER]["count"] == 3
    whole = channel_items.items(memory, "x")
    assert whole["all"] == 5 and len({i["id"] for i in whole["items"]}) == 5
    # The streams partition the site's posts: nothing is on two of them.
    held = source_streams.members(memory).members
    assert sum(len(v) for k, v in held.items() if k.startswith("x.")) == 5
    # A row of the stream says it is on it, once.
    shown = channel_items.items(memory, "x", stream=ANOTHER)
    assert all(i["lists"].count("Saved another way") == 1 for i in shown["items"])
    assert not any("Saved another way" in (i.get("lists") or []) for i in channel_items.items(memory, "x", stream="x.bookmarks")["items"])


def test_the_overview_card_of_a_source_with_no_channel_counts_each_post_once(reading, monkeypatch, on):
    server, memory = reading
    # One Instagram post from the site's own list (its origin owns it) and two other doors' posts, one of them pasted.
    from api.services import saved_lists
    own = "https://www.instagram.com/p/OwnOne1111/"
    reading_settings.update(saved_lists_={"instagram": True})
    out = server.handle_tool("cicada_record_saved_list", {"platform": "instagram", "outcome": "read",
                                                          "items": [{"url": own, "author": "alex_example"}]})
    assert out.startswith("Recorded"), out
    _paste(memory, monkeypatch, "https://www.instagram.com/p/Pasted2222/")
    _chrome(memory, monkeypatch, "https://www.instagram.com/reel/Marked3333/")
    bank_index.invalidate()
    del saved_lists
    card = next(r for r in source_overview.build_overview(memory, channels=[]) if r["id"] == "instagram")
    streams = _streams(memory)
    assert card["items"] == 3 == streams["instagram.saved"]["count"] + streams["instagram.another-way"]["count"]
    assert channel_items.items(memory, "instagram")["all"] == 3


def test_a_source_that_has_only_pasted_posts_still_has_its_card(reading, monkeypatch, on):
    server, memory = reading
    _paste(memory, monkeypatch, POSTS["linkedin"])
    bank_index.invalidate()
    card = next(r for r in source_overview.build_overview(memory, channels=[]) if r["id"] == "linkedin")
    assert card["items"] == 1


def test_dark_the_overview_and_the_site_page_are_what_they_were(reading, monkeypatch):
    server, memory = reading
    _paste(memory, monkeypatch, POSTS["linkedin"])
    bank_index.invalidate()
    assert not [r for r in source_overview.build_overview(memory, channels=[]) if r["id"] == "linkedin"]
    assert channel_items.items(memory, "linkedin")["all"] == 0


# --------------------------------------------------------------------------------- the stream as the apps read it


def test_the_stream_row_has_the_shape_of_a_place_nothing_reads_or_switches(reading, monkeypatch, on):
    server, memory = reading
    _paste(memory, monkeypatch, POSTS["x"])
    bank_index.invalidate()
    row = _streams(memory)[ANOTHER]
    assert (row["kind"], row["how"], row["owner"], row["control"], row["state"], row["health"], row["depth"]) == (
        "saved", "app", "backend", "setup", "on", "read", "read")
    assert row["switch"] is None and row["lastReadAt"] is None and row["pausedUntil"] is None
    assert row["kind"] in source_streams.KINDS and row["how"] in source_streams.HOWS
    assert row["state"] in source_streams.STATES and row["health"] in source_streams.HEALTHS
    # It is a place posts go, so a check has nothing to run for it, and it sits after the lists the person's agent reads.
    ids = [s for src in source_streams.build(memory, channels=[])["sources"] if src["id"] == "x" for s in src["streams"]]
    assert ids[-2]["id"] == ANOTHER or ids[-1]["id"] == ANOTHER
    result = asyncio.run(source_streams.check(memory, ["x"], channels=[], connectors_connected={}))
    assert {"stream": ANOTHER, "result": "noted"} in result


def test_a_posts_page_is_never_a_row_of_its_own_list_and_the_list_page_is_no_member(reading, monkeypatch, on):
    server, memory = reading
    _paste(memory, monkeypatch, POSTS["x"])
    list_pages.sync(memory)
    bank_index.invalidate()
    pid = list_pages.stream_pages(memory)[ANOTHER]["page"]
    assert pid not in source_streams.members(memory).members[ANOTHER]
    assert pid not in {i["id"] for i in channel_items.items(memory, "x")["items"]}
    assert _streams(memory)[ANOTHER]["count"] == 1 and _streams(memory)[ANOTHER]["page"] == pid


def test_an_earned_post_is_joined_to_the_list_it_is_on_in_the_graph(reading, monkeypatch, on):
    server, memory = reading
    _paste(memory, monkeypatch, POSTS["x"])
    page = _page_id(memory, POSTS["x"])
    list_pages.sync(memory)
    bank_index.invalidate()
    pid = list_pages.stream_pages(memory)[ANOTHER]["page"]
    edges = list_pages.read_time_edges(memory, {page, pid}, {page})
    assert (page, pid, "saved in") in edges


def test_the_dry_run_counts_each_sites_stream_and_nothing_else(reading, monkeypatch):
    from api.scripts import saved_posts_dry_run

    server, memory = reading
    for url in (POSTS["x"], POSTS["instagram"], "https://blog.bob-example.org/post/1"):
        _paste(memory, monkeypatch, url)
    _chrome(memory, monkeypatch, STATUS.format(n=1000000000000000007))
    bank_index.invalidate()
    report = saved_posts_dry_run.measure(memory)
    assert report["saved_another_way"] == {"instagram": 1, "x": 2}
    assert saved_posts.HIDE_POSTS is False, "the dry run restores the constant"
    assert "alex_example" not in json.dumps(report), "counts only: no link, title or handle"
