"""G245 (ruling 78b, owner 2026-11-24): the new browser lists — X likes, Instagram likes, Reddit upvoted, YouTube playlists
and liked videos — the folder pass (X bookmark folders, Instagram collections, YouTube playlists), catching up, and a post's
own day. The person's own agent reads each list in their own signed-in browser; Cicada only offers the task and keeps
what the agent records. Synthetic bank, placeholder handles and words; nothing reads a real bank."""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone

import pytest

from _reading_fixtures import git_log, porcelain, reading  # noqa: F401 — `reading` is a fixture
from api.remote import catalog
from api.services import (folder_pass, history_index, id_utils, markdown_parser, media_ingestor, reading_settings,
                          save_folders, saved_lists, youtube_lists)

POST_A = "https://x.com/alice_example/status/1000000000000000001"
POST_B = "https://x.com/bob_example/status/1000000000000000002"
POST_C = "https://x.com/carol_example/status/1000000000000000003"
POST_D = "https://x.com/dave_example/status/1000000000000000004"
IG_A = "https://www.instagram.com/p/AbCdE12345/"
IG_B = "https://www.instagram.com/p/ZyXwV98765/"
RD_A = "https://www.reddit.com/r/alpha_sub/comments/abc123/a_title/"
VID_A, VID_B, VID_C = "aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"


@pytest.fixture(autouse=True)
def utc(monkeypatch):
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def _on(*keys):
    reading_settings.update(saved_lists_={k: True for k in keys})


def _yt_on(*names):
    reading_settings.update(youtube_lists_={n: True for n in names})


def _queue(server):
    return server.handle_tool("cicada_reading_queue", {})


def _record(server, platform, outcome="read", items=None, **kw):
    args = {"platform": platform, "outcome": outcome, **kw}
    if items is not None:
        args["items"] = items
    return server.handle_tool("cicada_record_saved_list", args)


def _record_yt(server, name, outcome="read", videos=None, **kw):
    args = {"list": name, "outcome": outcome, **kw}
    if videos is not None:
        args["videos"] = videos
    return server.handle_tool("cicada_record_youtube_list", args)


def _entry(memory, url):
    idx = media_ingestor.load_url_index(memory)
    entry = idx[media_ingestor.url_hash(url)]
    return idx.get(entry.get("alias_of"), entry)


def _page(memory, url):
    return markdown_parser.parse(memory / "entities" / f"{_entry(memory, url)['media_entity_id']}.md")


def _episode(memory, url):
    return markdown_parser.parse(memory / "episodes" / f"{_entry(memory, url)['episode_id']}.md")


def _seed(memory, url, *, origin, folder):
    idx = media_ingestor.load_url_index(memory)
    media_ingestor.write_prepared(media_ingestor.PreparedItem(
        media_ingestor.RawItem(url=url, folder=folder, origin=origin, defer_enrich=True), None), memory, idx)
    media_ingestor.save_url_index(memory, idx)


# --- the keys ------------------------------------------------------------------------------------------------------


def test_the_new_lists_are_keys_with_a_base_and_none_is_ever_on_by_default():
    assert tuple(saved_lists.PLATFORMS) == reading_settings.SAVED_LISTS
    bases = {k: p.base for k, p in saved_lists.PLATFORMS.items() if p.base}
    assert bases == {"x-likes": "x", "x-reposts": "x", "x-following": "x", "instagram-likes": "instagram", "linkedin-connections": "linkedin",
                     "reddit-upvoted": "reddit"}
    assert not set(bases) & set(reading_settings.DEFAULT_ON_SAVED_LISTS)
    assert not {"playlists", "liked"} & set(reading_settings.DEFAULT_ON_YOUTUBE_LISTS)
    assert reading_settings.YOUTUBE_LISTS == tuple(youtube_lists.LISTS)
    for key in bases:   # a base's own site: the address rules, host and reason are the site's
        p, base = saved_lists.PLATFORMS[key], saved_lists.PLATFORMS[bases[key]]
        assert (p.site, p.profile_hosts, p.name) == (base.site, base.profile_hosts, base.name)


def test_the_record_tools_name_every_new_list_in_their_schema(reading):
    server, _ = reading
    schema = {t["name"]: t["inputSchema"]["properties"] for t in server.TOOLS}
    assert schema["cicada_record_saved_list"]["platform"]["enum"] == list(saved_lists.PLATFORMS)
    assert schema["cicada_record_youtube_list"]["list"]["enum"] == list(youtube_lists.LISTS)
    assert {"continues", "folder", "folder_names"} <= set(schema["cicada_record_saved_list"])
    assert "playlist_names" in schema["cicada_record_youtube_list"]
    assert "posted" in schema["cicada_record_saved_list"]["items"]["items"]["properties"]
    assert "playlist" in schema["cicada_record_youtube_list"]["videos"]["items"]["properties"]


def test_a_second_list_shares_its_sites_address_rules():
    for key, url in (("x-likes", POST_A), ("instagram-likes", IG_A), ("reddit-upvoted", RD_A)):
        assert saved_lists.canonical(key, url) == saved_lists.canonical(saved_lists.base_of(key), url)
        assert saved_lists.canonical(key, url) is not None
    assert saved_lists.canonical("x-likes", "https://x.com/alice_example") is None   # a profile is not a post
    assert saved_lists.clean_profile_url("x-likes", "https://x.com/alice_example") == "https://x.com/alice_example"
    assert saved_lists.clean_profile_url("x-likes", "https://evil.example/alice_example") is None


# --- every list is a registered save (ruling 80, which withdrew ruling 30's index-only half) --------------------------


SAMPLES = {
    "x": POST_A, "x-likes": POST_B, "x-reposts": POST_C, "instagram": IG_A, "instagram-likes": IG_B,
    "linkedin": "https://www.linkedin.com/feed/update/urn:li:activity:7000000000000000001/",
    "reddit": RD_A, "reddit-upvoted": "https://www.reddit.com/r/alpha_sub/comments/def456/another/",
    "pinterest": "https://www.pinterest.com/pin/1234567890/",
    "tiktok": "https://www.tiktok.com/@alice.example/video/1234567890123",
    "spotify": "https://open.spotify.com/track/abcdefgh12345",
}


def test_every_saved_list_label_is_a_list_save_by_its_own_origin_and_folder():
    """The gate: a list's origin and folder label are what ``history_index.save_shaped`` reads (and ``mention_asks`` and
    the wake ride on), so a list that forgot to register would be a conversation to every reader."""
    for key, p in saved_lists.PLATFORMS.items():
        if p.kind in ("books", "people", "accounts"):   # kept outside the bank: no save at all
            continue
        assert history_index.save_shaped({"origin": p.origin, "folder": p.folder}) == "list", key
        assert history_index.kind({"origin": p.origin, "folder": p.folder, "processed": True, "processed_by": "index"}) == "list", key
    for name, folder in youtube_lists.FOLDERS.items():
        assert history_index.save_shaped({"origin": "youtube-playlist", "folder": folder}) == "list", name
    assert history_index.save_shaped({"origin": "youtube-playlist", "folder": "An example playlist"}) == "list"


@pytest.mark.parametrize("key", [k for k in SAMPLES])
def test_every_saved_list_read_writes_a_save_waiting_for_tonight_never_the_persons_words(reading, key):
    server, memory = reading
    _on(key)
    # A list read off the person's own timeline needs their handle to tell their own posts from reposts.
    who = {"handle": "alex_example"} if saved_lists.PLATFORMS[key].bounded else {}
    out = _record(server, key, items=[{"url": SAMPLES[key], "author": "alice_example", "text": "Notes on indexes"}], **who)
    assert "1 new post(s) saved" in out, out
    fm = _episode(memory, SAMPLES[key]).frontmatter
    p = saved_lists.PLATFORMS[key]
    assert (fm["origin"], fm["folder"]) == (p.origin, p.folder)
    # Ruling 80: one post read from a list is a save made singly: Sleep reads it tonight, as its author's words.
    assert fm["processed"] is False and "processed_by" not in fm
    assert history_index.save_state(fm) == "waiting" and history_index.kind(fm) is None and not fm.get(history_index.NOTE_KEY)
    assert porcelain(memory) == ""


@pytest.mark.parametrize("name,videos", [
    ("watch_later", [{"url": f"https://www.youtube.com/watch?v={VID_A}"}]),
    ("liked", [{"url": f"https://www.youtube.com/watch?v={VID_A}"}]),
    ("playlists", [{"url": f"https://www.youtube.com/watch?v={VID_A}", "playlist": "Example mix"}]),
])
def test_every_youtube_save_list_read_is_a_list_save_with_nothing_to_read(reading, name, videos):
    server, memory = reading
    _yt_on(name)
    assert "1 new" in _record_yt(server, name, videos=videos)
    fm = _episode(memory, videos[0]["url"]).frontmatter
    assert fm["origin"] == "youtube-playlist" and history_index.save_shaped(fm) == "list"
    # A video's title and link: no text to read, no page read for it (ruling 80). Its transcript follows his talking.
    assert fm["processed_by"] == history_index.NO_WORDS_BY


# --- one post, several lists -----------------------------------------------------------------------------------------


def test_a_liked_post_already_bookmarked_gains_the_list_on_its_page_not_a_second_page(reading):
    server, memory = reading
    _on("x", "x-likes")
    _record(server, "x", items=[{"url": POST_A, "text": "How alpha-project keeps vectors local"}])
    out = _record(server, "x-likes", items=[{"url": POST_A, "text": "How alpha-project keeps vectors local"},
                                            {"url": POST_B}])
    assert "1 new post(s) saved; 1 already in memory (1 now on this list too)" in out, out
    assert id_utils.page_lists(_page(memory, POST_A).frontmatter) == ["Bookmarks", "Likes"]
    assert len(media_ingestor.load_url_index(memory)) >= 2
    pages = [p for p in (memory / "entities").glob("media-*.md")]
    assert len(pages) == 2
    assert _episode(memory, POST_A).frontmatter["origin"] == "x-bookmarks"       # the first list keeps the row
    assert _episode(memory, POST_B).frontmatter["origin"] == "x-likes"
    assert porcelain(memory) == ""


def test_a_like_the_archive_brought_in_is_the_same_row_the_browser_read_finds(reading):
    server, memory = reading
    _on("x-likes", "instagram-likes", "reddit-upvoted")
    _seed(memory, POST_A, origin="x-likes", folder="Likes")                         # saved_exports' like.js row
    _seed(memory, IG_A, origin="instagram-saved", folder="Liked posts")             # media_ingestor's liked_posts.json row
    _seed(memory, RD_A, origin="reddit-saved", folder="Upvoted")                    # post_votes.csv row
    before = len(list((memory / "entities").glob("media-*.md")))
    for key, url in (("x-likes", POST_A), ("instagram-likes", IG_A), ("reddit-upvoted", RD_A)):
        out = _record(server, key, items=[{"url": url}])
        assert "0 new post(s) saved; 1 already in memory" in out and "now on this list" not in out, (key, out)
    assert len(list((memory / "entities").glob("media-*.md"))) == before


# --- one pause for a site; one handle ---------------------------------------------------------------------------------


def test_a_login_wall_pauses_every_list_of_the_site_and_try_again_lifts_it(reading):
    server, memory = reading
    _on("x", "x-likes", "instagram")
    assert "do not sign in" in _record(server, "x-likes", "needs_login").lower()
    assert saved_lists.paused_until("x") is not None and saved_lists.paused_until("x-likes") is not None
    assert saved_lists.paused_until("instagram") is None
    assert saved_lists.due(memory) == ["instagram"]
    states = saved_lists.status(memory)["lists"]
    assert states["x-likes"]["state"] == "signed_out" and states["x"]["pausedUntil"] == states["x-likes"]["pausedUntil"]
    reading_settings.update(saved_lists_={"x-likes": True})
    saved_lists.resume(["x-likes"])
    assert saved_lists.paused_until("x") is None and saved_lists.due(memory) == ["x"]
    saved_lists.resume_site("x.com")
    assert saved_lists.paused_until("x-likes") is None


def test_a_site_has_one_handle_and_profile_link_whichever_list_recorded_it(reading):
    server, memory = reading
    _on("x", "x-likes")
    _record(server, "x-likes", items=[{"url": POST_A}], handle="alice_example",
            profile_url="https://x.com/alice_example")
    for key in ("x", "x-likes"):
        row = saved_lists.status(memory)["lists"][key]
        assert (row["handle"], row["profileUrl"]) == ("alice_example", "https://x.com/alice_example"), key
    assert saved_lists.status(memory)["lists"]["x"]["lastReadAt"] is None     # only the handle is shared, never a read


# --- the offer ------------------------------------------------------------------------------------------------------


def test_the_queue_says_which_page_and_what_to_read_for_each_new_list(reading):
    server, memory = reading
    _on("x-likes")
    out = _queue(server)
    assert "Likes tab" in out and "holds only their likes" in out and "never their feed, timeline or messages" in out
    assert "never click anything that changes the list" in out and "`x-likes`" in out
    assert "bookmark folders" not in out                                          # likes has no folders
    reading_settings.update(saved_lists_={"x-likes": False, "instagram-likes": True})
    out = _queue(server)
    assert "your_activity/interactions/likes" in out and "send the link and author only" in out
    reading_settings.update(saved_lists_={"instagram-likes": False, "reddit-upvoted": True})
    assert "https://www.reddit.com/user/me/upvoted/" in _queue(server)


def test_the_queue_asks_for_folders_only_where_the_site_has_them(reading):
    server, memory = reading
    _on("x")
    out = _queue(server)
    assert "bookmark folders" in out and "`folder_names`" in out and "at most 12" not in out.split("folders")[0]
    assert f"{folder_pass.FOLDERS_PER_PASS} at most to open next" in out
    assert "counts once" in out and "`continues=true`" in out
    reading_settings.update(saved_lists_={"x": False, "instagram": True})
    assert "collections" in _queue(server)
    reading_settings.update(saved_lists_={"instagram": False, "reddit": True})
    assert "folder_names" not in _queue(server)


def test_a_list_is_read_to_its_end_once_and_only_then_does_a_read_stop_at_what_is_kept(reading):
    """Ruling 78 as amended 2026-11-24 (the owner's "all"): measured on a real list, twenty screens kept one post in ten."""
    server, memory = reading
    _on("x")
    first = _queue(server)
    assert "read all of it" in first and "stops growing" in first and "`reached_end=true`" in first
    assert "screens" not in first.split("read all of it")[1].split("Add `posted`")[0]     # no bound in screens
    assert "export" not in first
    # A read that stopped early leaves the list unfinished: the next one is asked to go to the end again.
    out = _record(server, "x", items=[{"url": POST_A}])
    assert "has not been read to its end yet" in out and not saved_lists.whole(memory, "x")
    later = datetime.now(timezone.utc) + saved_lists.CADENCE + timedelta(minutes=1)
    lines = "\n".join(saved_lists.queue_lines(memory, can_record=True, now=later))
    assert "read all of it" in lines and "no reason to stop" in lines
    # Posts already kept are where the earlier read stopped, never a reason to stop this one.
    again = _record(server, "x", items=[{"url": POST_A}, {"url": POST_B}])
    assert "Known ground" not in again and "keep scrolling" in again
    done = _record(server, "x", items=[{"url": POST_C}], continues=True, reached_end=True)
    assert "whole list is in memory now" in done and saved_lists.whole(memory, "x")
    lines = "\n".join(saved_lists.queue_lines(memory, can_record=True, now=later + saved_lists.CADENCE))
    assert "read all of it" not in lines and f"at most {folder_pass.LATER_READ_SCREENS} screens" in lines
    assert "already in memory" in lines


def test_a_list_not_yet_read_to_its_end_may_take_far_more_calls_in_one_read(reading, monkeypatch):
    server, memory = reading
    _on("x")
    monkeypatch.setattr(saved_lists, "PASS_CALLS", 2)
    monkeypatch.setattr(saved_lists, "DAILY_READS", 1)
    _record(server, "x", items=[{"url": POST_A}])
    for n in range(2, 7):                                    # six calls, one read: the list is long
        url = f"https://x.com/alice_example/status/10000000000000000{n:02d}"
        assert "not counted again today" in _record(server, "x", items=[{"url": url}], continues=True)
    assert saved_lists.reads_today(memory) == 1 and saved_lists.pass_calls(memory, "x") == saved_lists.WHOLE_PASS_CALLS
    _record(server, "x", items=[{"url": POST_B}], continues=True, reached_end=True)
    assert saved_lists.pass_calls(memory, "x") == 2          # read to its end: an ordinary pass from now on


def test_a_folders_end_is_not_the_lists_end_and_an_empty_list_is_whole(reading):
    server, memory = reading
    _on("x", "linkedin")
    _record(server, "x", items=[{"url": POST_A}], folder_names=["Alpha"])
    _record(server, "x", items=[{"url": POST_B}], folder="Alpha", reached_end=True)
    assert not saved_lists.whole(memory, "x")
    _record(server, "linkedin", items=[])
    assert saved_lists.whole(memory, "linkedin")


def test_what_tonights_live_lists_showed_is_accepted_and_said(reading):
    """Measured 2026-11-24 on real lists (values redacted): a saved article among LinkedIn's saved posts, results with no
    link to their post, and X filing Bookmarks and Likes under History."""
    server, memory = reading
    article = "https://www.linkedin.com/feed/update/urn:li:article:7000000000000000001/"
    assert saved_lists.canonical("linkedin", article) == (article, (article.replace("www.", ""),))
    built = "https://www.linkedin.com/feed/update/urn:li:activity:7000000000000000002/"
    assert saved_lists.canonical("linkedin", built.rstrip("/"))[0] == built
    assert saved_lists.canonical("x", POST_A + "?s=20")[0] == POST_A
    assert saved_lists.canonical("x-likes", POST_A)[0] == POST_A
    _on("linkedin")
    out = _queue(server)
    assert "data-chameleon-result-urn" in out and "https://www.linkedin.com/feed/update/<that urn>/" in out
    reading_settings.update(saved_lists_={"linkedin": False, "x": True})
    assert "/i/history" in _queue(server)
    assert saved_lists.PLATFORMS["x-likes"].url == "https://x.com/i/history/likes"
    assert (saved_lists.PLATFORMS["x-likes"].origin, saved_lists.PLATFORMS["x-likes"].folder) == ("x-likes", "Likes")


def test_a_read_that_reaches_posts_already_kept_says_so_so_the_agent_stops(reading):
    server, memory = reading
    _on("x")
    posts = [POST_A, POST_B, POST_C]
    _record(server, "x", items=[{"url": u} for u in posts], reached_end=True)      # the whole list is in memory
    saved_lists.note(memory, "x", "read", items=1)          # a later read
    out = _record(server, "x", items=[{"url": POST_D}] + [{"url": u} for u in posts])
    assert "Known ground: 3 of these 4" in out and "stop scrolling" in out
    fresh = _record(server, "x", items=[{"url": POST_D}, {"url": "https://x.com/e_example/status/1000000000000000005"}])
    assert "Known ground" not in fresh


# --- a post's own day ------------------------------------------------------------------------------------------------


def test_a_row_may_carry_the_day_the_post_was_posted_and_only_a_real_day_is_kept(reading):
    server, memory = reading
    _on("x")
    _record(server, "x", items=[{"url": POST_A, "posted": "2026-11-20"}, {"url": POST_B, "posted": "3 days ago"},
                                {"url": POST_C, "posted": "2026-02-30"}, {"url": POST_D}])
    assert _episode(memory, POST_A).frontmatter["posted"] == "2026-11-20"
    for url in (POST_B, POST_C, POST_D):
        assert "posted" not in _episode(memory, url).frontmatter, url
    assert porcelain(memory) == ""


def test_a_post_kept_before_its_list_showed_a_day_gains_it_once_in_place(reading):
    server, memory = reading
    _on("x")
    _seed(memory, POST_A, origin="x-bookmarks", folder="Bookmarks")
    before = _entry(memory, POST_A)["episode_id"]
    out = _record(server, "x", items=[{"url": POST_A, "posted": "2026-11-20"}])
    assert "0 new post(s) saved; 1 already in memory" in out
    assert _entry(memory, POST_A)["episode_id"] == before
    assert _episode(memory, POST_A).frontmatter["posted"] == "2026-11-20"
    assert "given the day they were posted" in git_log(memory)
    _record(server, "x", items=[{"url": POST_A, "posted": "2026-11-21"}])           # a second read never rewrites it
    assert _episode(memory, POST_A).frontmatter["posted"] == "2026-11-20"
    assert "episodes/" not in porcelain(memory)                      # the episode edit is committed (the seed's page is not)


# --- the folder pass -------------------------------------------------------------------------------------------------


def test_one_pass_is_the_all_page_then_its_folders_and_counts_once(reading):
    server, memory = reading
    _on("x")
    out = _record(server, "x", items=[{"url": POST_A}, {"url": POST_B}], folder_names=["Reading", "Cooking"])
    assert "2 folder(s) on this list" in out and "“Reading”; “Cooking”" in out
    assert saved_lists.reads_today(memory) == 1 and saved_lists.folder_count(memory, "x") == 2
    out = _record(server, "x", items=[{"url": POST_A}], folder="Reading")        # a folder page implies `continues`
    assert "Filed in “Reading”" in out and "not counted again today" in out
    out = _record(server, "x", items=[{"url": POST_B}], folder="Cooking", continues=True)
    assert saved_lists.reads_today(memory) == 1
    assert save_folders.explicit_of(_episode(memory, POST_A).frontmatter) == {"x-bookmarks": ["Reading"]}
    assert save_folders.explicit_of(_episode(memory, POST_B).frontmatter) == {"x-bookmarks": ["Cooking"]}
    assert _episode(memory, POST_A).frontmatter["folder"] == "Bookmarks"            # the fixed list label is untouched
    assert saved_lists.last(memory, "x")["items"] == 4                                  # the pass adds up
    assert porcelain(memory) == ""


def test_the_folders_least_recently_read_come_first_and_only_twelve(reading):
    server, memory = reading
    _on("instagram")
    names = [f"Collection {n:02d}" for n in range(15)]
    out = _record(server, "instagram", items=[{"url": IG_A}], folder_names=names)
    shown = [n for n in names if f"“{n}”" in out]
    assert shown == names[:12] and "15 folder(s)" in out
    for name in shown[:6]:
        _record(server, "instagram", items=[{"url": IG_A}], folder=name)
    again = _record(server, "instagram", items=[{"url": IG_B}], continues=False, folder_names=names)   # a new read
    shown = [n for n in names if f"“{n}”" in again]
    assert sorted(shown) == sorted(names[6:15] + names[:3])                          # the six read go to the back
    assert again.index("Collection 06") < again.index("Collection 00")
    assert saved_lists.reads_today(memory) == 2


def test_a_site_or_account_with_no_folders_reports_none(reading):
    server, memory = reading
    _on("x", "x-likes")
    out = _record(server, "x", items=[{"url": POST_A}], folder_names=[])
    assert "No folders on this list" in out and saved_lists.folder_count(memory, "x") == 0
    out = _record(server, "x-likes", items=[{"url": POST_B}], folder_names=["Anything"])
    assert "has no folders" in out and saved_lists.folder_count(memory, "x-likes") == 0
    out = _record(server, "x-likes", items=[{"url": POST_C}], folder="Anything")
    assert out.startswith("Error:") and "no folders" in out
    assert media_ingestor.url_hash(POST_C) not in media_ingestor.load_url_index(memory)


def test_machine_state_keeps_a_folders_hash_and_time_never_its_name(reading):
    server, memory = reading
    _on("x")
    _record(server, "x", items=[{"url": POST_A}], folder_names=["Alpha-project reading"])
    _record(server, "x", items=[{"url": POST_A}], folder="Alpha-project reading")
    state = saved_lists.path().read_text()
    assert "Alpha-project" not in state and folder_pass.folder_hash("alpha-project  READING") in state
    assert saved_lists.last(memory, "x")["folder_reads"]


def test_continues_cannot_be_a_way_round_the_bound(reading, monkeypatch):
    server, memory = reading
    _on("x")
    monkeypatch.setattr(saved_lists, "DAILY_READS", 1)
    out = _record(server, "x", items=[{"url": POST_A}])
    assert "not counted again" not in out and saved_lists.reads_today(memory) == 1
    assert "not counted again today" in _record(server, "x", items=[{"url": POST_B}], continues=True)
    refused = _record(server, "x", items=[{"url": POST_C}])                          # a new read: the day is spent
    assert refused.startswith("Not recorded:") and "today" in refused
    assert media_ingestor.url_hash(POST_C) not in media_ingestor.load_url_index(memory)
    # No read open (a different list) and `continues` set: it is a new read, counted and bound like any.
    _on("instagram")
    refused = _record(server, "instagram", items=[{"url": IG_A}], continues=True)
    assert refused.startswith("Not recorded:")


def test_a_pass_ends_after_its_calls_or_its_window(reading, monkeypatch):
    server, memory = reading
    _on("x")
    monkeypatch.setattr(saved_lists, "PASS_CALLS", 2)
    saved_lists.note(memory, "x", "read", items=0, reached_end=True)               # a list already read to its end
    before = saved_lists.reads_today(memory)
    _record(server, "x", items=[{"url": POST_A}])
    assert "not counted again" in _record(server, "x", items=[{"url": POST_B}], continues=True)
    out = _record(server, "x", items=[{"url": POST_C}], continues=True)           # the third call: the pass is full
    assert "none was open" in out and saved_lists.reads_today(memory) == before + 2
    _record(server, "x", items=[{"url": POST_D}])
    later = datetime.now(timezone.utc) + saved_lists.PASS_WINDOW + timedelta(minutes=1)
    assert saved_lists.pass_open(memory, "x") and not saved_lists.pass_open(memory, "x", now=later)


def test_a_login_wall_closes_the_open_pass(reading):
    server, memory = reading
    _on("x")
    _record(server, "x", items=[{"url": POST_A}])
    assert saved_lists.pass_open(memory, "x")
    _record(server, "x", "needs_login")
    assert not saved_lists.pass_open(memory, "x")


# --- YouTube ---------------------------------------------------------------------------------------------------------


def test_the_youtube_queue_names_each_new_list_and_playlists_ask_for_names_first(reading):
    server, memory = reading
    _yt_on("playlists", "liked")
    out = _queue(server)
    assert "https://www.youtube.com/feed/playlists" in out and "https://www.youtube.com/playlist?list=LL" in out
    assert "`playlist_names`" in out and "`playlist`" in out and f"{folder_pass.FOLDERS_PER_PASS} at most" in out
    assert "first read of this list" in out
    assert "`playlists` or `liked`" in out and "watch_later" not in out.split("`cicada_record_youtube_list")[0]


def test_liked_videos_are_filed_under_their_own_list_and_a_repeat_joins_the_page(reading):
    server, memory = reading
    _yt_on("watch_later", "liked")
    _record_yt(server, "watch_later", videos=[{"url": f"https://www.youtube.com/watch?v={VID_A}", "title": "Knots"}])
    out = _record_yt(server, "liked", videos=[{"url": f"https://www.youtube.com/watch?v={VID_A}"},
                                              {"url": f"https://www.youtube.com/watch?v={VID_B}", "title": "Bridges"}])
    assert "1 new Liked videos video(s) saved; 1 already in memory" in out
    assert id_utils.page_lists(_page(memory, f"https://www.youtube.com/watch?v={VID_A}").frontmatter) == [
        "Watch later", "Liked videos"]
    assert _episode(memory, f"https://www.youtube.com/watch?v={VID_B}").frontmatter["folder"] == "Liked videos"
    assert porcelain(memory) == ""


def test_a_playlist_is_the_videos_folder_and_one_video_in_two_playlists_is_one_page(reading):
    server, memory = reading
    _yt_on("playlists")
    out = _record_yt(server, "playlists", videos=[
        {"url": f"https://www.youtube.com/watch?v={VID_A}", "title": "Knots", "playlist": "Ropes"},
        {"url": f"https://www.youtube.com/watch?v={VID_A}", "title": "Knots", "playlist": "Camping"},
        {"url": f"https://www.youtube.com/watch?v={VID_B}", "title": "Bridges", "playlist": "Camping"},
        {"url": f"https://www.youtube.com/watch?v={VID_C}", "title": "No playlist"},
        {"url": "https://example.com/x", "playlist": "Ropes"},
    ])
    assert "2 new playlist video(s) saved in 2 playlist(s); 1 already in memory" in out, out
    assert "1 row(s) named no playlist" in out and "1 row(s) were not YouTube" in out
    assert id_utils.page_lists(_page(memory, f"https://www.youtube.com/watch?v={VID_A}").frontmatter) == ["Ropes", "Camping"]
    assert _episode(memory, f"https://www.youtube.com/watch?v={VID_B}").frontmatter["folder"] == "Camping"
    assert porcelain(memory) == ""


def test_the_playlists_index_names_which_playlists_to_open_and_is_not_yet_a_read(reading):
    server, memory = reading
    _yt_on("playlists")
    names = [f"Playlist {n:02d}" for n in range(14)]
    out = _record_yt(server, "playlists", videos=[], playlist_names=names)
    assert "14 playlist(s)" in out and sum(f"“{n}”" in out for n in names) == 12
    assert not youtube_lists.last(memory, "playlists").get("read_at")                 # not read until a page is
    assert youtube_lists.folder_count(memory, "playlists") == 14
    _record_yt(server, "playlists", videos=[{"url": f"https://www.youtube.com/watch?v={VID_A}",
                                             "playlist": names[0]}])
    assert youtube_lists.last(memory, "playlists")["read_at"]
    out = _record_yt(server, "playlists", videos=[], playlist_names=names)
    assert "Playlist 00" not in out and "Playlist 13" not in out and "Playlist 12" in out   # the one just read goes last
    state = youtube_lists.path().read_text()
    assert "Playlist 00" not in state and folder_pass.folder_hash(names[0]) in state


def test_an_account_with_no_playlists_is_a_read_of_nothing(reading):
    server, memory = reading
    _yt_on("playlists")
    out = _record_yt(server, "playlists", videos=[], playlist_names=[])
    assert "is empty" in out and youtube_lists.folder_count(memory, "playlists") == 0
    assert youtube_lists.last(memory, "playlists")["read_at"]
    refused = _record_yt(server, "liked", videos=[], playlist_names=["x"])
    assert refused.startswith("Not recorded")                                         # a list that is not on


def test_playlist_names_belong_to_the_playlists_list_alone(reading):
    server, _ = reading
    _yt_on("liked")
    assert _record_yt(server, "liked", videos=[], playlist_names=["x"]).startswith("Error:")


def test_a_youtube_login_wall_pauses_every_list_and_the_new_lists_follow_the_cadence(reading):
    server, memory = reading
    _yt_on("playlists", "liked")
    assert youtube_lists.due(memory) == ["playlists", "liked"]
    _record_yt(server, "liked", "needs_login")
    assert youtube_lists.due(memory) == [] and "Every YouTube list is paused" in _record_yt(server, "playlists", "blocked")
    youtube_lists.resume()
    assert youtube_lists.due(memory) == ["playlists", "liked"]


def test_the_new_youtube_lists_are_off_by_default_even_for_an_account_the_memory_shows(reading):
    from api.services import list_defaults

    server, memory = reading
    _seed(memory, f"https://www.youtube.com/watch?v={VID_A}", origin="youtube-playlist", folder="Watch later")
    reading_settings.update(acknowledge=True)
    list_defaults.apply(memory)
    snap = reading_settings.snapshot()
    assert snap["youtubeLists"] == {"watchLater": True, "history": True, "playlists": False, "liked": False}
    assert all(not on for k, on in snap["savedLists"].items() if "-" in k)


# --- the door --------------------------------------------------------------------------------------------------------


def test_the_new_arguments_ride_the_record_tools_and_neither_is_ever_remote():
    assert "cicada_record_saved_list" in catalog.NEVER_REMOTE and "cicada_record_youtube_list" in catalog.NEVER_REMOTE


def test_the_tool_door_passes_the_pass_arguments_through(reading, monkeypatch):
    from api.services import mcp_tools, tool_door

    seen = {}

    def fake(ctx, platform, outcome, items=None, via=None, handle=None, profile_url=None, continues=None, folder=None,
             folder_names=None, reached_end=None):
        seen.update(continues=continues, folder=folder, folder_names=folder_names, reached_end=reached_end)
        return "ok"

    monkeypatch.setattr(mcp_tools, "record_saved_list", fake)
    tool_door.DISPATCH["cicada_record_saved_list"](None, {"platform": "x", "outcome": "read", "continues": True,
                                                       "folder": "A", "folder_names": ["A"], "reached_end": True})
    assert seen == {"continues": True, "folder": "A", "folder_names": ["A"], "reached_end": True}
    assert json.dumps(seen)
