"""G206 (redesign 2026-10-22): the person's own agent keeps their saved lists on X, Instagram and LinkedIn current,
from their signed-in browser — the YouTube lists' shape per site. Cicada only offers the task, and only while agent
reading is on AND the person turned that site's list on; the backend fetches nothing; ``needs_login`` pauses that
list; a read is a save from a platform's saved list — indexed, never read by a model (ruling 30) — joined by URL with
what an archive or a pasted link already saved. Also the walled-post title: a saved X post was titled by its status
id. Synthetic bank, placeholder handles and words."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest

from _reading_fixtures import git_log, porcelain, reading  # noqa: F401 — `reading` is a fixture
from api.remote import catalog
from api.services import (demo_guard, history_index, markdown_parser, media_ingestor, reading_queue,
                          reading_settings, saved_lists)

POST_A = "https://x.com/alice_example/status/1000000000000000001"
POST_B = "https://twitter.com/bob_example/status/1000000000000000002?s=20"
IG_A = "https://www.instagram.com/p/AbCdE12345/"
LI_A = "https://www.linkedin.com/feed/update/urn:li:activity:7000000000000000001/"


@pytest.fixture(autouse=True)
def utc(monkeypatch):
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def _on(*keys):
    reading_settings.update(saved_lists_={k: True for k in keys})


def _queue(server):
    return server.handle_tool("cicada_reading_queue", {})


def _record(server, platform, outcome="read", items=None, **kw):
    args = {"platform": platform, "outcome": outcome, **kw}
    if items is not None:
        args["items"] = items
    return server.handle_tool("cicada_record_saved_list", args)


def _page_of(memory, url):
    entry = media_ingestor.load_url_index(memory)[media_ingestor.url_hash(url)]
    entry = media_ingestor.load_url_index(memory).get(entry.get("alias_of"), entry)
    return entry, markdown_parser.parse(memory / "entities" / f"{entry['media_entity_id']}.md")


# --- the title of a walled post ------------------------------------------------------------------------------------


@pytest.mark.parametrize("url,title", [
    ("https://x.com/alice_example/status/1000000000000000001", "Post by @alice_example"),
    ("https://twitter.com/alice_example/status/1000000000000000001/photo/1", "Post by @alice_example"),
    ("https://x.com/i/web/status/1000000000000000001", "Post on X"),
    ("https://www.instagram.com/p/AbCdE12345/", "Instagram post"),
    ("https://www.instagram.com/reel/AbCdE12345/", "Instagram reel"),
    ("https://www.linkedin.com/feed/update/urn:li:activity:7000000000000000001/", "LinkedIn post"),
    ("https://blog.bob-example.org/notes/sqlite-vec", "sqlite vec"),     # every other link: unchanged
])
def test_a_walled_post_is_titled_from_its_url_never_by_its_id(url, title):
    assert media_ingestor._fallback_title(url) == title


def test_an_old_id_title_still_counts_as_a_placeholder_so_a_read_can_replace_it():
    assert media_ingestor.is_placeholder_title(POST_A, "1000000000000000001")
    assert media_ingestor.is_placeholder_title(POST_A, "Post by @alice_example")
    assert not media_ingestor.is_placeholder_title(POST_A, "A thread about sqlite-vec")
    assert not media_ingestor.is_placeholder_title("https://bob-example.org/1000", "1001")


def test_saving_an_x_post_with_no_fetch_titles_it_by_its_author(reading):
    import asyncio

    _, memory = reading
    idx = media_ingestor.load_url_index(memory)
    res = asyncio.run(media_ingestor.ingest_one(media_ingestor.RawItem(url=POST_A, defer_enrich=True), memory, None,
                                                idx))
    page = markdown_parser.parse(memory / "entities" / f"{res.media_entity_id}.md")
    assert page.frontmatter["name"] == "Post by @alice_example"


# --- the switch ----------------------------------------------------------------------------------------------------


def test_off_by_default_needs_the_sheet_and_counts_only_while_agent_reading_is_on(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    assert reading_settings.snapshot()["savedLists"] == {"x": False, "instagram": False, "linkedin": False}
    with pytest.raises(reading_settings.SettingsError):
        reading_settings.update(saved_lists_={"x": True})                     # no "I understand" yet
    with pytest.raises(reading_settings.SettingsError):
        reading_settings.update(acknowledge=True, saved_lists_={"facebook": True})   # not a list
    reading_settings.update(acknowledge=True, saved_lists_={"x": True})
    assert reading_settings.snapshot()["savedLists"]["x"] is True
    assert not saved_lists.allowed("x")                                       # master switch still off
    reading_settings.update(agent_enabled_=True)
    assert saved_lists.allowed("x") and not saved_lists.allowed("instagram")
    reading_settings.update(saved_lists_={"x": False})
    assert not saved_lists.allowed("x")


# --- the offer -----------------------------------------------------------------------------------------------------


def test_nothing_is_offered_until_a_list_is_on_then_one_site_at_a_time(reading):
    server, memory = reading
    assert _queue(server).startswith("Nothing is waiting")
    _on("x", "linkedin")
    out = _queue(server)
    assert "https://x.com/i/bookmarks" in out and "linkedin.com" not in out    # one site's list at a time
    assert "`cicada_record_saved_list(" in out and "do not sign in" in out and "never click" in out
    assert reading_queue.counts(memory)[0] == 1
    _record(server, "x", items=[{"url": POST_A, "author": "alice_example", "text": "Notes on indexes"}])
    assert saved_lists.due(memory) == ["linkedin"]
    later = datetime.now(timezone.utc) + saved_lists.CADENCE + timedelta(minutes=1)
    assert saved_lists.due(memory, now=later) == ["x"]


def test_the_day_bound_stops_the_offer_and_the_record(reading, monkeypatch):
    server, memory = reading
    _on("x")
    monkeypatch.setattr(saved_lists, "CADENCE", timedelta(0))   # the cadence alone would keep offering it
    for _ in range(saved_lists.DAILY_READS - 1):
        saved_lists.note(memory, "x", "read", items=1)
    assert saved_lists.due(memory) == ["x"]
    saved_lists.note(memory, "x", "read", items=1)
    assert saved_lists.due(memory) == []
    before = porcelain(memory)
    out = _record(server, "x", items=[{"url": POST_A}])
    assert out.startswith("Not recorded:") and "today" in out
    assert porcelain(memory) == before and media_ingestor.load_url_index(memory) == {}


def test_needs_login_pauses_only_that_list_writes_nothing_and_turning_it_on_again_is_try_again(reading):
    server, memory = reading
    _on("x", "instagram")
    before = porcelain(memory)
    out = _record(server, "x", "needs_login")
    assert "do not sign in" in out.lower()
    assert saved_lists.paused_until("x") is not None and saved_lists.paused_until("instagram") is None
    assert saved_lists.due(memory) == ["instagram"] and porcelain(memory) == before
    saved_lists.resume(["x"])          # the route calls this when the person turns the list on again
    assert saved_lists.due(memory) == ["x"]
    saved_lists.note(memory, "x", "needs_login")
    saved_lists.resume_site("www.x.com")   # "I signed in" on the agent request (G205)
    assert saved_lists.paused_until("x") is None


def test_needs_login_asks_the_person_to_sign_in_when_agent_requests_exist(reading, monkeypatch):
    import sys
    import types

    server, memory = reading
    _on("x")
    asked = []
    fake = types.ModuleType("api.services.agent_requests")
    fake.ask = lambda memory_path, **kw: asked.append(kw)
    monkeypatch.setitem(sys.modules, "api.services.agent_requests", fake)
    import api.services as services
    monkeypatch.setattr(services, "agent_requests", fake, raising=False)
    _record(server, "x", "needs_login")
    assert asked and asked[0]["site"] == "x.com" and asked[0]["reason"] == "to read your bookmarks"


def test_the_record_tool_is_never_offered_to_a_remote_connection():
    assert "cicada_record_saved_list" in catalog.NEVER_REMOTE


# --- what a read writes ------------------------------------------------------------------------------------------


def test_refusals_write_nothing(reading, monkeypatch):
    server, memory = reading
    before = porcelain(memory)
    assert _record(server, "x", items=[{"url": POST_A}]).startswith("Not recorded: the person has not")
    _on("x")
    assert _record(server, "facebook").startswith("Error: platform must be")
    assert _record(server, "x", "maybe").startswith("Error: outcome")
    assert _record(server, "x").startswith("Error: a read needs `items`")
    monkeypatch.setattr(demo_guard, "is_demo", lambda path: True)
    assert "demo" in _record(server, "x", items=[{"url": POST_A}]).lower()
    assert porcelain(memory) == before


def test_a_read_saves_each_post_indexed_never_read_and_one_already_saved_is_never_twice(reading):
    server, memory = reading
    _on("x")
    # POST_B came in earlier from the X archive (its own spelling of the same post).
    idx = media_ingestor.load_url_index(memory)
    media_ingestor.write_prepared(media_ingestor.PreparedItem(
        media_ingestor.RawItem(url="https://x.com/i/web/status/1000000000000000002", folder="Bookmarks",
                               origin="x-bookmarks", defer_enrich=True), None), memory, idx)
    media_ingestor.save_url_index(memory, idx)
    out = _record(server, "x", items=[
        {"url": POST_A, "author": "alice_example", "text": "How alpha-project keeps every vector on the laptop"},
        {"url": POST_B, "author": "@bob_example"},
        {"url": POST_A},                                              # the same post twice on screen
        {"url": "https://x.com/alice_example", "text": "a profile, not a post"},
    ], via="browser tools")
    assert "1 new post(s) saved; 1 already in memory" in out and "1 row(s) were not X posts" in out
    entry, page = _page_of(memory, POST_A)
    assert page.frontmatter["name"] == "How alpha-project keeps every vector on the laptop"
    episode = markdown_parser.parse(memory / "episodes" / f"{entry['episode_id']}.md")
    fm = episode.frontmatter
    assert fm["origin"] == "x-bookmarks" and fm["folder"] == "Bookmarks"
    assert fm["processed"] is True and fm["processed_by"] == history_index.INDEXED_BY   # ruling 30
    assert history_index.kind(fm) == "list" and not fm.get(history_index.NOTE_KEY)
    # The other spellings of the post are aliases: a later paste of any of them is the same row.
    idx = media_ingestor.load_url_index(memory)
    assert media_ingestor.existing_hash(media_ingestor.RawItem(url="https://x.com/i/web/status/1000000000000000001"),
                                        idx) is not None
    log = git_log(memory)
    assert "Cicada-Author: claude-code" in log and "Cicada-Session: ses_read_fixed" in log
    assert saved_lists.last(memory, "x")["items"] == 2


def test_instagram_and_linkedin_posts_save_under_their_own_lists(reading):
    server, memory = reading
    _on("instagram", "linkedin")
    out = _record(server, "instagram", items=[{"url": IG_A + "?igsh=abc", "author": "carol-example"},
                                              {"url": "https://www.instagram.com/carol-example/"}])
    assert "1 new post(s) saved" in out and "1 row(s) were not Instagram posts" in out
    entry, page = _page_of(memory, IG_A)
    assert page.frontmatter["name"] == "Post by carol-example"
    ep = markdown_parser.parse(memory / "episodes" / f"{entry['episode_id']}.md").frontmatter
    assert ep["origin"] == "instagram-saved" and ep["processed_by"] == history_index.INDEXED_BY
    _record(server, "linkedin", items=[{"url": LI_A, "text": "A note on retrieval"}])
    entry, _ = _page_of(memory, LI_A)
    ep = markdown_parser.parse(memory / "episodes" / f"{entry['episode_id']}.md").frontmatter
    assert ep["origin"] == "linkedin-saved" and ep["folder"] == "Saved Items"
    assert porcelain(memory) == ""
