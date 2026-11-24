"""G245 (owner 2026-11-24, "Should reposts be kept as their own list?" "1. yes?"): X reposts as a list of their own, off
until turned on, and the list-table fields the daily read will lean on — a kind per list, its own cadence, a back-off after
reads that found nothing new, a pause of a site after two failed reads, and an `unattended` mode of `due()` (pinned here;
nothing uses it yet).

A repost read comes from the person's OWN profile timeline, which mixes in their own posts; so a row they wrote is dropped
and counted, and a timeline has no end, so the read stops at a screens bound and never claims the end. Synthetic bank,
scratch `$CICADA_HOME`, placeholder handles and words; nothing real is read or fetched."""
from __future__ import annotations

import dataclasses
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from _reading_fixtures import porcelain, reading  # noqa: F401 — `reading` is a fixture
from api import config, main
from api.services import (history_index, id_utils, markdown_parser, media_ingestor, reading_settings, saved_lists,
                          source_streams)

ME = "alex_example"
POST_A = "https://x.com/alice_example/status/1000000000000000001"
POST_B = "https://x.com/bob_example/status/1000000000000000002"
POST_C = "https://x.com/carol_example/status/1000000000000000003"
MINE = f"https://x.com/{ME}/status/1000000000000000009"
MINE_GENERIC = "https://x.com/i/web/status/1000000000000000008"
DAY0 = datetime(2026, 11, 24, 8, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def utc(monkeypatch):
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


@pytest.fixture
def client(reading, monkeypatch):  # noqa: F811
    _server, memory = reading
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    yield TestClient(main.app)
    config.get_settings.cache_clear()


def _on(*keys):
    reading_settings.update(saved_lists_={k: True for k in keys})


def _record(server, platform, items, outcome="read", **kw):
    args = {"platform": platform, "outcome": outcome, **kw}
    if items is not None:
        args["items"] = items
    return server.handle_tool("cicada_record_saved_list", args)


def _reposts(server, items, **kw):
    kw.setdefault("handle", ME)
    return _record(server, "x-reposts", items, **kw)


def _queue(server):
    return server.handle_tool("cicada_reading_queue", {})


def _page(memory, url):
    index = media_ingestor.load_url_index(memory)
    entry = index[media_ingestor.url_hash(url)]
    entry = index.get(entry.get("alias_of"), entry)
    return markdown_parser.parse(memory / "entities" / f"{entry['media_entity_id']}.md"), entry


# --- the list ---------------------------------------------------------------------------------------------------------


def test_x_reposts_is_a_list_like_x_likes_off_until_turned_on():
    p = saved_lists.PLATFORMS["x-reposts"]
    likes = saved_lists.PLATFORMS["x-likes"]
    assert (p.base, p.kind, p.origin, p.folder, p.label) == ("x", "posts", "x-reposts", "Reposts", "Reposts")
    assert (p.site, p.profile_hosts, p.name) == (likes.site, likes.profile_hosts, likes.name)
    assert "x-reposts" not in reading_settings.DEFAULT_ON_SAVED_LISTS
    assert tuple(saved_lists.PLATFORMS) == reading_settings.SAVED_LISTS
    assert saved_lists.canonical("x-reposts", POST_A) == saved_lists.canonical("x", POST_A) is not None
    assert saved_lists.base_of("x-reposts") == saved_lists.pause_key("x-reposts") == "x"


def test_a_repost_is_a_list_save_by_its_own_origin():
    """The gate (ruling 80): the origin is in `history_index.LIST_ORIGINS`, so a repost is a save by its record — the person's
    act, found, asked about when he talks about it — and waits its turn in the pile when it arrives in bulk."""
    assert "x-reposts" in history_index.LIST_ORIGINS
    assert history_index.save_shaped({"origin": "x-reposts", "folder": "Reposts"}) == "list"
    assert history_index.kind({"origin": "x-reposts", "folder": "Reposts", "processed": True, "processed_by": "index"}) == "list"


def test_every_list_has_a_kind_and_only_the_special_lists_are_not_posts():
    kinds = {k: p.kind for k, p in saved_lists.PLATFORMS.items()}
    assert set(kinds.values()) <= set(saved_lists.LIST_KINDS) and saved_lists.LIST_KINDS == (
        "posts", "people", "accounts", "books")
    assert {k for k, kind in kinds.items() if kind != "posts"} == {"linkedin-connections", "x-following", "goodreads"}
    assert kinds["linkedin-connections"] == "people" and kinds["goodreads"] == "books" and kinds["x-following"] == "accounts"
    with pytest.raises(ValueError):
        dataclasses.replace(saved_lists.PLATFORMS["x"], kind="feed")


def test_only_the_timeline_list_has_a_screens_bound_and_its_own_cadence():
    assert {k for k, p in saved_lists.PLATFORMS.items() if p.bounded} == {"x-reposts"}
    assert saved_lists.PLATFORMS["x-reposts"].max_screens == saved_lists.FIRST_READ_SCREENS
    assert saved_lists.PLATFORMS["x-reposts"].cadence > saved_lists.CADENCE


# --- a read of the person's own timeline ---------------------------------------------------------------------------------


def test_a_repost_read_with_no_handle_on_record_keeps_nothing_and_says_how_to_fix_it(reading):
    server, memory = reading
    _on("x-reposts")
    out = _record(server, "x-reposts", [{"url": POST_A, "author": "alice_example", "text": "words"}])
    assert out.startswith("Not recorded") and "`handle`" in out, out
    assert porcelain(memory) == ""
    assert saved_lists.reads_today(memory) == 0 and saved_lists.last(memory, "x-reposts").get("read_at") is None


def test_a_row_the_person_wrote_is_dropped_and_counted_never_filed_as_a_repost(reading):
    server, memory = reading
    _on("x-reposts")
    out = _reposts(server, [
        {"url": POST_A, "author": "alice_example", "text": "an example post"},
        {"url": MINE, "author": ME, "text": "my own words"},                   # the link's own user is the person
        {"url": MINE_GENERIC, "author": f"@{ME.upper()}", "text": "mine too"},  # a link with no user: the row's author, any case
        {"url": POST_B, "author": "bob_example", "text": "another"},
    ])
    assert "2 new post(s) saved" in out and "2 row(s) were the person's own posts" in out, out
    index = media_ingestor.load_url_index(memory)
    assert media_ingestor.url_hash(POST_A) in index and media_ingestor.url_hash(POST_B) in index
    assert media_ingestor.url_hash(MINE) not in index and media_ingestor.url_hash(MINE_GENERIC) not in index
    page, entry = _page(memory, POST_A)
    assert id_utils.page_lists(page.frontmatter) == ["Reposts"]
    ep = markdown_parser.parse(memory / "episodes" / f"{entry['episode_id']}.md").frontmatter
    assert (ep["origin"], ep["folder"]) == ("x-reposts", "Reposts")
    assert ep["processed"] is False and history_index.save_state(ep) == "waiting"   # ruling 80: one repost is read tonight


def test_a_read_that_showed_only_the_persons_own_posts_is_a_read_with_nothing_new_not_a_failure(reading):
    server, memory = reading
    _on("x-reposts")
    out = _reposts(server, [{"url": MINE, "author": ME}])
    assert "were the person's own posts" in out and "failed" not in out, out
    entry = saved_lists.last(memory, "x-reposts")
    assert entry["outcome"] == "read" and entry["items"] == 0


def test_the_handle_another_list_of_the_site_recorded_is_the_persons_on_this_one(reading):
    server, memory = reading
    _on("x", "x-reposts")
    _record(server, "x", [{"url": POST_C, "author": "carol_example"}], handle=ME)
    out = _record(server, "x-reposts", [{"url": MINE, "author": ME}, {"url": POST_A, "author": "alice_example"}])
    assert "1 new post(s) saved" in out and "1 row(s) were the person's own posts" in out, out


def test_a_post_bookmarked_liked_and_reposted_is_one_page_with_three_marks(reading, client):
    server, memory = reading
    _on("x", "x-likes", "x-reposts")
    item = [{"url": POST_A, "author": "alice_example", "text": "an example post"}]
    _record(server, "x", item, handle=ME)
    _record(server, "x-likes", item)
    out = _reposts(server, item)
    assert "0 new post(s) saved; 1 already in memory (1 now on this list too)" in out, out
    page, _ = _page(memory, POST_A)
    assert id_utils.page_lists(page.frontmatter) == ["Bookmarks", "Likes", "Reposts"]
    rows = {r["id"]: r for r in client.get("/sources/channels/x/items").json()["items"]}
    assert [r["lists"] for r in rows.values()] == [["Bookmarks", "Likes", "Reposts"]], "one page, three marks"
    only = {r["id"] for r in client.get("/sources/channels/x/items", params={"stream": "x.reposts"}).json()["items"]}
    assert only == set(rows)


# --- a timeline has no end -----------------------------------------------------------------------------------------------


def test_the_queue_names_the_one_page_a_timeline_may_be_read_from_and_never_asks_for_its_end(reading):
    server, memory = reading
    _on("x-reposts")
    out = _queue(server)
    assert "X Reposts" in out and "own profile" in out and "reposted" in out
    assert "no end" in out and f"at most {saved_lists.PLATFORMS['x-reposts'].max_screens} screens" in out
    assert "stops growing" not in out and "however long" not in out and "read all of it" not in out
    assert "never their own posts" in out and "`handle`" in out
    # The header every other list carries is not repeated for the one page where a timeline is allowed.
    assert "never their feed, timeline or messages" not in out


def test_a_repost_read_never_claims_it_reached_the_end_and_sets_whole_at_its_bound(reading):
    server, memory = reading
    _on("x-reposts")
    out = _reposts(server, [{"url": POST_A, "author": "alice_example"}])
    assert "Keep within" in out and "reached_end=true" in out and "whole list" not in out, out
    assert not saved_lists.whole(memory, "x-reposts")
    out = _reposts(server, [{"url": POST_B, "author": "bob_example"}], continues=True, reached_end=True)
    assert "no end" in out and "not claimed to be complete" in out, out
    assert "whole list" not in out and "to its end" not in out and "stops growing" not in out
    assert saved_lists.whole(memory, "x-reposts")
    # Later reads stop at known ground, like any whole list.
    assert f"at most {saved_lists.LATER_READ_SCREENS} screens" in saved_lists.screens_words(memory, "x-reposts")


def test_a_timeline_pass_never_gets_the_five_hundred_calls_of_a_list_with_an_end(reading):
    _server, memory = reading
    assert saved_lists.pass_calls(memory, "x-reposts") == saved_lists.PASS_CALLS
    assert saved_lists.pass_calls(memory, "x") == saved_lists.WHOLE_PASS_CALLS


# --- due(): cadence, back-off, the failed pause, the unattended mode ---------------------------------------------------------------


def _read(memory, key, at, *, new=1, whole=True):
    saved_lists.note(memory, key, "read", items=3, new=new, reached_end=whole, now=at)


def test_a_list_with_its_own_cadence_is_offered_again_after_that_not_after_the_global_one(reading):
    _server, memory = reading
    _on("x", "x-reposts")
    _read(memory, "x", DAY0)
    _read(memory, "x-reposts", DAY0)
    assert saved_lists.due(memory, DAY0 + timedelta(hours=21)) == ["x"]
    assert saved_lists.due(memory, DAY0 + timedelta(days=2)) == ["x"]
    _read(memory, "x", DAY0 + timedelta(days=2, hours=23))
    assert saved_lists.due(memory, DAY0 + timedelta(days=3, hours=1)) == ["x-reposts"]


def test_an_unattended_offer_takes_reposts_after_every_other_list_however_long_ago_they_were_read(reading):
    _server, memory = reading
    _on("x", "x-likes", "x-reposts", "instagram")
    _read(memory, "x-reposts", DAY0 - timedelta(days=30))
    for key, hours in (("x", 22), ("x-likes", 21), ("instagram", 40)):
        _read(memory, key, DAY0 - timedelta(hours=hours))
    for expected in (["instagram"], ["x"], ["x-likes"], ["x-reposts"]):
        assert saved_lists.due(memory, DAY0, unattended=True) == expected
        _read(memory, expected[0], DAY0)


def test_the_persons_own_read_never_starves_reposts_behind_other_lists(reading):
    """With more lists on than a day's reads, a timeline last of all would never be offered: the person's own read keeps
    the longest-ago-first order, and reposts' own cadence is what spaces them out."""
    _server, memory = reading
    _on("x", "x-likes", "x-reposts")
    _read(memory, "x-reposts", DAY0 - timedelta(days=30))
    _read(memory, "x", DAY0 - timedelta(hours=22))
    _read(memory, "x-likes", DAY0 - timedelta(hours=21))
    assert saved_lists.due(memory, DAY0) == ["x-reposts"]


def test_the_persons_check_goes_first_even_for_reposts(reading):
    _server, memory = reading
    _on("x", "x-reposts")
    assert saved_lists.request_check(memory, "x-reposts", DAY0)
    assert saved_lists.due(memory, DAY0) == ["x-reposts"]


def test_reads_that_find_nothing_new_back_a_whole_list_off_and_the_persons_check_resets_it(reading):
    _server, memory = reading
    _on("x")
    _read(memory, "x", DAY0)                      # found something
    assert saved_lists.cadence_of(memory, "x") == saved_lists.CADENCE
    _read(memory, "x", DAY0 + timedelta(days=1), new=0)
    assert saved_lists.cadence_of(memory, "x") == saved_lists.CADENCE, "one empty read is no reason to back off"
    _read(memory, "x", DAY0 + timedelta(days=2), new=0)
    assert saved_lists.cadence_of(memory, "x") == timedelta(days=3)
    assert saved_lists.due(memory, DAY0 + timedelta(days=4)) == []
    assert saved_lists.due(memory, DAY0 + timedelta(days=5, hours=1)) == ["x"]
    _read(memory, "x", DAY0 + timedelta(days=5), new=0)
    assert saved_lists.cadence_of(memory, "x") == timedelta(days=3)
    _read(memory, "x", DAY0 + timedelta(days=8), new=0)
    assert saved_lists.cadence_of(memory, "x") == timedelta(days=7)
    assert saved_lists.due(memory, DAY0 + timedelta(days=14)) == []
    assert saved_lists.due(memory, DAY0 + timedelta(days=15, hours=1)) == ["x"]
    # Only the person's own click ends it.
    assert saved_lists.request_check(memory, "x", DAY0 + timedelta(days=9))
    assert saved_lists.cadence_of(memory, "x") == saved_lists.CADENCE
    _read(memory, "x", DAY0 + timedelta(days=9, hours=1), new=0)
    assert saved_lists.cadence_of(memory, "x") == saved_lists.CADENCE
    # A read that finds something ends it too.
    for day in (10, 11):
        _read(memory, "x", DAY0 + timedelta(days=day), new=0)
    assert saved_lists.cadence_of(memory, "x") == timedelta(days=3)
    _read(memory, "x", DAY0 + timedelta(days=12), new=2)
    assert saved_lists.cadence_of(memory, "x") == saved_lists.CADENCE


def test_a_pass_that_kept_something_on_a_later_call_is_not_an_empty_read(reading):
    _server, memory = reading
    _on("x")
    _read(memory, "x", DAY0)
    _read(memory, "x", DAY0 + timedelta(days=1), new=0)
    saved_lists.note(memory, "x", "read", items=1, new=0, now=DAY0 + timedelta(days=2))          # a pass: first call, nothing
    assert saved_lists.last(memory, "x")["empty_reads"] == 2
    saved_lists.note(memory, "x", "read", items=1, new=3, continues=True, now=DAY0 + timedelta(days=2, minutes=1))
    assert saved_lists.last(memory, "x")["empty_reads"] == 0
    assert saved_lists.reads_today(memory, DAY0 + timedelta(days=2)) == 1, "the pass counted once"


def test_a_list_not_yet_read_to_its_end_never_backs_off(reading):
    _server, memory = reading
    _on("x")
    for day in range(4):
        _read(memory, "x", DAY0 + timedelta(days=day), new=0, whole=False)
    assert saved_lists.cadence_of(memory, "x") == saved_lists.CADENCE


def test_the_record_tool_counts_what_is_new_so_a_repeat_read_is_an_empty_one(reading):
    server, memory = reading
    _on("x")
    _record(server, "x", [{"url": POST_A}, {"url": POST_B}], reached_end=True)
    assert saved_lists.last(memory, "x")["empty_reads"] == 0
    _record(server, "x", [{"url": POST_A}, {"url": POST_B}])
    assert saved_lists.last(memory, "x")["empty_reads"] == 1
    _record(server, "x", [{"url": POST_A}, {"url": POST_B}])
    assert saved_lists.last(memory, "x")["empty_reads"] == 2 and saved_lists.cadence_of(memory, "x") == timedelta(days=3)
    _record(server, "x", [{"url": POST_C}])
    assert saved_lists.last(memory, "x")["empty_reads"] == 0


def test_two_failed_reads_in_a_row_pause_the_site_three_days_and_one_does_not(reading):
    _server, memory = reading
    _on("x", "x-likes", "instagram")
    saved_lists.note(memory, "x", "failed", now=DAY0)
    assert saved_lists.paused_until("x", DAY0) is None
    saved_lists.note(memory, "x-likes", "failed", now=DAY0 + timedelta(hours=21))      # another list of the same site
    until = saved_lists.paused_until("x", DAY0 + timedelta(hours=22))
    assert until == DAY0 + timedelta(hours=21) + saved_lists.FAILED_PAUSE
    assert saved_lists.paused_until("x-likes", DAY0 + timedelta(hours=22)) == until, "the site's pause, every list of it"
    assert saved_lists.paused_until("instagram", DAY0 + timedelta(hours=22)) is None
    assert saved_lists.due(memory, DAY0 + timedelta(hours=22)) == ["instagram"]
    assert "failed_streak" not in saved_lists._load(), "the count starts again after the pause"
    # Turning a list on again lifts it, as it lifts a login wall's.
    saved_lists.resume(["x"])
    assert saved_lists.paused_until("x", DAY0 + timedelta(hours=22)) is None


def test_a_read_between_two_failures_ends_the_count(reading):
    _server, memory = reading
    _on("x", "x-likes")
    saved_lists.note(memory, "x", "failed", now=DAY0)
    _read(memory, "x-likes", DAY0 + timedelta(hours=1))
    saved_lists.note(memory, "x", "failed", now=DAY0 + timedelta(hours=2))
    assert saved_lists.paused_until("x", DAY0 + timedelta(hours=3)) is None
    saved_lists.note(memory, "x", "failed", now=DAY0 + timedelta(hours=3))
    assert saved_lists.paused_until("x", DAY0 + timedelta(hours=4)) is not None


def test_the_second_failed_read_says_the_site_is_paused_and_not_to_retry(reading):
    server, memory = reading
    _on("x")
    assert "offered again later" in _record(server, "x", None, outcome="failed")
    out = _record(server, "x", None, outcome="failed")
    assert "second time in a row" in out and "paused for 3 days" in out and "do not retry" in out, out
    assert saved_lists.status(memory)["lists"]["x"]["pausedUntil"] is not None


def test_an_unattended_offer_never_includes_a_list_not_yet_read_to_its_end(reading):
    _server, memory = reading
    _on("x", "instagram")
    _read(memory, "x", DAY0 - timedelta(days=2), whole=False)
    _read(memory, "instagram", DAY0 - timedelta(days=2))
    assert saved_lists.due(memory, DAY0) == ["x"], "the person watching is offered the first long read"
    assert saved_lists.due(memory, DAY0, unattended=True) == ["instagram"]
    _read(memory, "instagram", DAY0)
    assert saved_lists.due(memory, DAY0, unattended=True) == []
    # Not even the person's own check starts a long first read in a run nobody is watching.
    saved_lists.request_check(memory, "x", DAY0)
    assert saved_lists.due(memory, DAY0, unattended=True) == []
    assert saved_lists.due(memory, DAY0) == ["x"]


def test_an_unattended_offer_never_includes_an_accounts_list(reading):
    _server, memory = reading
    _on("x-following", "x")
    _read(memory, "x-following", DAY0 - timedelta(days=9))
    _read(memory, "x", DAY0 - timedelta(days=8))
    assert saved_lists.due(memory, DAY0, unattended=True) == ["x"]
    _read(memory, "x", DAY0)
    assert saved_lists.due(memory, DAY0, unattended=True) == []
    assert saved_lists.due(memory, DAY0) == ["x-following"], "a read the person is watching may offer it"
    saved_lists.request_check(memory, "x-following", DAY0)
    assert saved_lists.due(memory, DAY0, unattended=True) == []


def test_an_unattended_offer_orders_posts_then_people_then_books_then_reposts_last(reading):
    _server, memory = reading
    _on("x", "x-reposts", "linkedin-connections", "goodreads", "instagram")
    for key, days in (("x-reposts", 30), ("linkedin-connections", 20), ("goodreads", 10), ("instagram", 3), ("x", 4)):
        _read(memory, key, DAY0 - timedelta(days=days))
    order = []
    for _ in range(5):
        offered = saved_lists.due(memory, DAY0, unattended=True)
        order += offered
        _read(memory, offered[0], DAY0)
    assert order == ["x", "instagram", "linkedin-connections", "goodreads", "x-reposts"]


def test_nothing_is_offered_unattended_or_not_past_the_days_reads(reading):
    _server, memory = reading
    _on("x")
    for _ in range(saved_lists.DAILY_READS):
        saved_lists.count_read(memory, DAY0)
    assert saved_lists.due(memory, DAY0) == [] == saved_lists.due(memory, DAY0, unattended=True)


# --- the stream ---------------------------------------------------------------------------------------------------------


def test_reposts_is_a_stream_of_its_own_kind_on_xs_page_with_a_switch_that_starts_off(reading, client):
    def streams():
        return {t["id"]: t for s in client.get("/sources/streams").json()["sources"] if s["id"] == "x" for t in s["streams"]}

    assert list(streams())[:3] == ["x.bookmarks", "x.likes", "x.reposts"]
    reposts = streams()["x.reposts"]
    assert (reposts["label"], reposts["kind"], reposts["how"], reposts["state"]) == ("Reposts", "reposted", "browser", "off")
    assert reposts["kind"] in source_streams.KINDS and reposts["switch"] == {"setting": "savedLists", "key": "x-reposts"}
    assert reposts["depth"] == "index", "a repost is kept and found, read by no model until the person talks about it"
    assert client.put("/reading/settings", json={"savedLists": {"x-reposts": True}}).status_code == 200
    assert streams()["x.reposts"]["state"] == "on" and streams()["x.bookmarks"]["state"] == "off"


def test_the_directory_count_is_by_the_lists_kind_not_its_key(reading):
    _server, memory = reading
    specs = {s.key: s for g in source_streams.groups() for s in g.specs if s.family == "saved"}
    assert specs["linkedin-connections"].counts == "directory"
    assert source_streams._directory_count(specs["linkedin-connections"], memory) == 0
    assert specs["x-following"].counts == "directory" and source_streams._directory_count(specs["x-following"], memory) == 0
    assert specs["goodreads"].counts == "channel" and specs["x-reposts"].counts == "members"
