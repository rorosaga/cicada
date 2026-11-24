"""G245 (ruling 78): the new browser lists (`saved_lists` keys with a base, YouTube's playlists and liked videos) seen through
the streams (`source_streams`, `GET /sources/streams`, the items route) — the two tracks' mechanisms meeting: one shared
pause, a post's own day stored by the record tool and served by the items route, a fair due order across more keys than
the day's bound, each new switch a setting the route accepts, and the folder pass counted and filtered.

Synthetic bank and scratch `$CICADA_HOME`; placeholder handles and words only; nothing real is read or fetched."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from _reading_fixtures import reading  # noqa: F401 — a fixture
from api import config, main
from api.services import reading_settings, saved_lists, source_streams, youtube_lists

POST_A = "https://x.com/alice_example/status/1000000000000000001"
POST_B = "https://x.com/bob_example/status/1000000000000000002"
POST_C = "https://x.com/carol_example/status/1000000000000000003"
DAY0 = datetime(2026, 11, 24, 8, 0, tzinfo=timezone.utc)


@pytest.fixture
def client(reading, monkeypatch):  # noqa: F811
    _server, memory = reading
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    yield TestClient(main.app)
    config.get_settings.cache_clear()


def _record(server, platform, items, **kw):
    return server.handle_tool("cicada_record_saved_list", {"platform": platform, "outcome": "read", "items": items, **kw})


def _stream(client, stream_id):
    for source in client.get("/sources/streams").json()["sources"]:
        for stream in source["streams"]:
            if stream["id"] == stream_id:
                return stream
    raise AssertionError(f"no stream {stream_id}")


def _rows(client, channel, **params):
    out = client.get(f"/sources/channels/{channel}/items", params=params)
    assert out.status_code == 200, out.text
    return {r["id"]: r for r in out.json()["items"]}, out.json()


# --- a post's own day: stored by the tool, served by the route -------------------------------------------------------------


def test_a_posted_day_the_record_tool_stores_is_what_the_items_route_serves(reading, client):
    server, memory = reading
    reading_settings.update(saved_lists_={"x": True})
    _record(server, "x", [{"url": POST_A, "posted": "2026-11-20"}, {"url": POST_B}, {"url": POST_C, "posted": "last week"}])
    rows, body = _rows(client, "x")
    by_url = {r["title"]: r for r in rows.values()}
    assert body["total"] == 3
    dated = [r for r in rows.values() if r.get("posted")]
    assert [r["posted"] for r in dated] == ["2026-11-20"]
    # `day` stays the day it was kept on: today, never the post's own day.
    # (ruling 80: a post recorded with a link and no words holds nothing to read yet.)
    assert dated[0]["day"] != "2026-11-20" and all(r["depth"] == "empty" for r in rows.values()), by_url


def test_a_day_a_later_read_gives_a_post_kept_before_is_served_too(reading, client):
    server, memory = reading
    reading_settings.update(saved_lists_={"x": True})
    _record(server, "x", [{"url": POST_A}])
    rows, _ = _rows(client, "x")
    assert all("posted" not in r for r in rows.values())
    _record(server, "x", [{"url": POST_A, "posted": "2026-11-18"}])
    rows, _ = _rows(client, "x")
    assert [r["posted"] for r in rows.values()] == ["2026-11-18"]


def test_an_author_the_record_tool_stores_is_what_the_items_route_serves(reading, client):
    server, memory = reading
    reading_settings.update(saved_lists_={"x": True})
    _record(server, "x", [{"url": POST_A, "author": "alice_example", "text": "words"}, {"url": POST_B, "text": "more words"}])
    rows, body = _rows(client, "x")
    assert body["total"] == 2
    by_author = {r.get("author"): r for r in rows.values()}
    # An X handle wears its @, as the post's title does; a post whose list showed no author says none.
    assert set(by_author) == {"@alice_example", None}
    # Nothing but a line is kept: a long or multi-line author is cut to one line.
    _record(server, "x", [{"url": POST_C, "author": "Carol\nExample " + "x" * 200, "text": "third"}])
    rows, _ = _rows(client, "x")
    carol = [r["author"] for r in rows.values() if r.get("author", "").startswith("Carol")]
    assert carol and "\n" not in carol[0] and len(carol[0]) <= 60


def test_an_author_a_later_read_gives_a_post_kept_before_is_served_too(reading, client):
    server, memory = reading
    reading_settings.update(saved_lists_={"x": True})
    _record(server, "x", [{"url": POST_A}])
    rows, _ = _rows(client, "x")
    assert all("author" not in r for r in rows.values())
    _record(server, "x", [{"url": POST_A, "author": "alice_example"}])
    rows, _ = _rows(client, "x")
    assert [r["author"] for r in rows.values()] == ["@alice_example"]
    # Once given it stays: a later read that names someone else does not rewrite it.
    _record(server, "x", [{"url": POST_A, "author": "bob_example"}])
    rows, _ = _rows(client, "x")
    assert [r["author"] for r in rows.values()] == ["@alice_example"]


def test_a_linkedin_save_is_listed_under_its_streams_own_name(reading, client):
    server, memory = reading
    reading_settings.update(saved_lists_={"linkedin": True})
    _record(server, "linkedin", [{"url": "https://www.linkedin.com/posts/alice-example_post-activity-1000000000000000001-abcd",
                                  "author": "Alice Example", "text": "a post"}])
    rows, _ = _rows(client, "linkedin")
    assert [r.get("lists") for r in rows.values()] == [["Saved posts"]]


# --- every new list is a stream with a switch the settings route accepts -----------------------------------------------------

_SAVED = [("x-likes", "x.likes"), ("instagram-likes", "instagram.likes"), ("reddit-upvoted", "reddit.upvoted")]
_YOUTUBE = [("playlists", "youtube.playlists"), ("liked", "youtube.liked")]


@pytest.mark.parametrize("key, stream_id", _SAVED)
def test_a_new_saved_list_is_a_stream_whose_switch_the_settings_route_flips(reading, client, key, stream_id):
    stream = _stream(client, stream_id)
    assert stream["switch"] == {"setting": "savedLists", "key": key}
    assert (stream["state"], stream["how"], stream["control"]) == ("off", "browser", "switch")
    assert client.put("/reading/settings", json={stream["switch"]["setting"]: {key: True}}).status_code == 200
    assert _stream(client, stream_id)["state"] == "on"
    client.put("/reading/settings", json={"savedLists": {key: False}})
    assert _stream(client, stream_id)["state"] == "off"


@pytest.mark.parametrize("name, stream_id", _YOUTUBE)
def test_a_new_youtube_list_is_a_stream_whose_switch_the_settings_route_flips(reading, client, name, stream_id):
    stream = _stream(client, stream_id)
    assert stream["switch"] == {"setting": "youtubeLists", "key": name}
    assert client.put("/reading/settings", json={"youtubeLists": {name: True}}).status_code == 200
    assert _stream(client, stream_id)["state"] == "on"


def test_the_stream_ids_are_the_ones_the_streams_module_emits_for_each_source(reading, client):
    sources = {s["id"]: [t["id"] for t in s["streams"]] for s in client.get("/sources/streams").json()["sources"]}
    assert sources["x"][:2] == ["x.bookmarks", "x.likes"]
    assert sources["instagram"][:2] == ["instagram.saved", "instagram.likes"]
    assert sources["reddit"][:2] == ["reddit.saved", "reddit.upvoted"]
    assert {"youtube.playlists", "youtube.liked"} <= set(sources["youtube"])
    for key in saved_lists.PLATFORMS:      # every table key has a stream, whatever its name
        assert any(t["switch"] == {"setting": "savedLists", "key": key} for s in client.get("/sources/streams").json()[
            "sources"] for t in s["streams"] if t["switch"]), key
    assert set(youtube_lists.LISTS) <= {
        t["switch"]["key"] for s in client.get("/sources/streams").json()["sources"] for t in s["streams"]
        if t["switch"] and t["switch"]["setting"] == "youtubeLists"}


def test_a_likes_pause_is_the_sites_in_the_streams_and_both_resumes_lift_the_one_pause(reading, client):
    server, memory = reading
    reading_settings.update(saved_lists_={"x": True, "x-likes": True})
    saved_lists.note(memory, "x-likes", "needs_login")
    stored = saved_lists._load()["paused_until"]
    assert list(stored) == ["x"], "one pause, kept under the site's own key; no entry for a list with a base"
    assert _stream(client, "x.bookmarks")["pausedUntil"] == _stream(client, "x.likes")["pausedUntil"] is not None
    assert not saved_lists.status(memory)["lists"]["x"]["lastOutcome"], "the site's first list was never read or noted"
    # The settings route's resume (a list switched on again) and an agent request's resume (the site's host) agree.
    client.put("/reading/settings", json={"savedLists": {"x-likes": True}})
    assert saved_lists.paused_until("x") is None and saved_lists.paused_until("x-likes") is None
    saved_lists.note(memory, "x", "blocked")
    saved_lists.resume_site("x.com")
    assert saved_lists.paused_until("x-likes") is None and "paused_until" not in saved_lists._load()


def test_a_likes_pause_or_read_makes_no_phantom_entry_for_the_base_list(reading):
    from api.services import list_defaults

    _server, memory = reading
    saved_lists.note(memory, "x-likes", "needs_login")
    saved_lists.note(memory, "x-likes", "read", items=2, handle="alice_example")
    assert saved_lists.last(memory, "x").get("read_at") is None and saved_lists.last(memory, "x")["handle"] == "alice_example"
    held = list_defaults.read_before()
    assert "saved:x-likes" in held and "saved:x" not in held


# --- the due order across more keys than a day's bound -----------------------------------------------------------------------


def _drain(memory, now):
    """One day's offers, the way an agent takes them: a read recorded for each offered key, until none is offered."""
    offered = []
    while keys := saved_lists.due(memory, now):
        offered.append(keys[0])
        saved_lists.note(memory, keys[0], "read", items=1, now=now)
        now += timedelta(minutes=1)
    return offered


def test_every_key_on_none_is_starved_across_days_though_there_are_more_than_the_daily_bound(reading):
    _server, memory = reading
    keys = list(saved_lists.PLATFORMS)
    assert len(keys) > saved_lists.DAILY_READS
    reading_settings.update(saved_lists_={k: True for k in keys})
    day1 = _drain(memory, DAY0)
    assert len(day1) == saved_lists.DAILY_READS and len(set(day1)) == len(day1)
    left_out = [k for k in keys if k not in day1]
    day2 = _drain(memory, DAY0 + timedelta(days=1, hours=1))
    assert day2[: len(left_out)] == left_out, "the keys day one could not reach go first, never the table's first"
    assert set(day1 + day2) == set(keys)
    assert len(_drain(memory, DAY0 + timedelta(days=2, hours=2))) == saved_lists.DAILY_READS


def test_a_key_with_a_base_follows_its_sites_pause_in_the_offer(reading):
    _server, memory = reading
    reading_settings.update(saved_lists_={"x": True, "x-likes": True, "instagram": True})
    saved_lists.note(memory, "x", "needs_login", now=DAY0)
    assert _drain(memory, DAY0) == ["instagram"]                  # neither of X's lists is offered while the site waits
    later = DAY0 + saved_lists.PAUSE + timedelta(hours=1)
    assert set(_drain(memory, later)) == {"x", "x-likes", "instagram"}


# --- the folder pass is counted and filterable --------------------------------------------------------------------------------


def test_folders_the_folder_pass_wrote_are_counted_and_filter_the_items(reading, client):
    server, memory = reading
    reading_settings.update(saved_lists_={"x": True})
    _record(server, "x", [{"url": POST_A}, {"url": POST_B}], folder_names=["Reading", "Cooking"])
    _record(server, "x", [{"url": POST_A}], folder="Reading")
    _record(server, "x", [{"url": POST_C}], folder="Cooking", continues=True)
    assert _stream(client, "x.bookmarks")["folderCount"] == 2
    reading_rows, body = _rows(client, "x", folder="reading")
    assert len(reading_rows) == 1 and body["all"] == 1
    assert [r["folders"] for r in reading_rows.values()] == [["Reading"]]
    assert len(_rows(client, "x", folder="Cooking")[0]) == 1
    assert len(_rows(client, "x", folder="Nowhere")[0]) == 0
    assert _stream(client, "x.likes")["folderCount"] == 0, "a likes tab has no folders"


def test_a_youtube_playlist_the_tool_wrote_counts_as_a_folder_of_the_playlists_stream(reading, client):
    server, memory = reading
    reading_settings.update(youtube_lists_={"playlists": True})
    vid = "https://www.youtube.com/watch?v=aaaaaaaaaaa"
    server.handle_tool("cicada_record_youtube_list", {"list": "playlists", "outcome": "read",
                                                       "videos": [{"url": vid, "title": "One", "playlist": "Alpha mix"}]})
    assert _stream(client, "youtube.playlists")["folderCount"] == 1
    rows, _ = _rows(client, "youtube", folder="alpha mix")
    assert len(rows) == 1
