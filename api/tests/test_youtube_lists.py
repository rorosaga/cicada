"""G71 / G166 (owner 2026-10-16): the person's own agent keeps their YouTube Watch later and watch history current,
from their signed-in browser. Cicada only offers the task — and only while agent reading is on AND the person turned
that list on; the backend fetches nothing; ``needs_login`` pauses the lists; a read joins the same identities as
Takeout, bookmarks and Chrome's history. Synthetic bank, placeholder titles."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest

from _reading_fixtures import enable, git_log, porcelain, reading  # noqa: F401 — `reading` is a fixture
from api.remote import catalog
from api.services import (demo_guard, markdown_parser, media_ingestor, reading_queue, reading_settings,
                          watch_history, youtube_lists)

VID_A, VID_B, VID_C = "aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"


@pytest.fixture(autouse=True)
def utc(monkeypatch):
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def _on(*names):
    reading_settings.update(youtube_lists_={n: True for n in names})


def _queue(server):
    return server.handle_tool("cicada_reading_queue", {})


def _record(server, list_name, outcome="read", videos=None, **kw):
    args = {"list": list_name, "outcome": outcome, **kw}
    if videos is not None:
        args["videos"] = videos
    return server.handle_tool("cicada_record_youtube_list", args)


def _url(vid):
    return f"https://www.youtube.com/watch?v={vid}"


# --- the switch ----------------------------------------------------------------------------------------------------


def test_off_by_default_needs_the_sheet_and_counts_only_while_agent_reading_is_on(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    assert reading_settings.snapshot()["youtubeLists"] == {"watchLater": False, "history": False}
    with pytest.raises(reading_settings.SettingsError):
        reading_settings.update(youtube_lists_={"watch_later": True})          # no "I understand" yet
    with pytest.raises(reading_settings.SettingsError):
        reading_settings.update(acknowledge=True, youtube_lists_={"liked": True})   # not a list
    reading_settings.update(acknowledge=True, youtube_lists_={"watch_later": True})
    assert reading_settings.snapshot()["youtubeLists"]["watchLater"] is True
    # Agent reading is on by default once the sheet is accepted (2026-10-22); the person's off still wins.
    assert youtube_lists.allowed("watch_later") and not youtube_lists.allowed("history")
    reading_settings.update(agent_enabled_=False)
    assert not youtube_lists.allowed("watch_later")                          # master switch off
    reading_settings.update(agent_enabled_=True)
    assert youtube_lists.allowed("watch_later")


# --- the offer -----------------------------------------------------------------------------------------------------


def test_nothing_is_offered_until_the_person_turns_a_list_on(reading):
    server, memory = reading
    assert _queue(server).startswith("Nothing is waiting")
    assert reading_queue.counts(memory) == (0, 0)
    _on("watch_later")
    out = _queue(server)
    assert "https://www.youtube.com/playlist?list=WL" in out and "feed/history" not in out
    assert "`cicada_record_youtube_list(" in out and "do not sign in" in out
    assert reading_queue.counts(memory)[0] == 1   # the recall hook's count hears it as an ask


def test_a_read_is_not_offered_again_until_the_cadence_passes(reading):
    server, memory = reading
    _on("watch_later", "history")
    assert youtube_lists.due(memory) == ["watch_later", "history"]
    _record(server, "watch_later", videos=[{"url": _url(VID_A), "title": "Bridge design", "channel": "alice-example"}])
    assert youtube_lists.due(memory) == ["history"]
    later = datetime.now(timezone.utc) + youtube_lists.CADENCE + timedelta(minutes=1)
    assert youtube_lists.due(memory, now=later) == ["watch_later", "history"]


def test_needs_login_pauses_both_lists_writes_nothing_and_turning_one_on_again_is_try_again(reading):
    server, memory = reading
    _on("watch_later", "history")
    before = porcelain(memory)
    out = _record(server, "history", "needs_login")
    assert "do not sign in" in out.lower()
    assert youtube_lists.due(memory) == [] and youtube_lists.paused_until() is not None
    assert porcelain(memory) == before and _queue(server).startswith("Nothing is waiting")
    week = datetime.now(timezone.utc) + youtube_lists.PAUSE + timedelta(minutes=1)
    assert youtube_lists.due(memory, now=week) == ["watch_later", "history"]
    reading_settings.update(youtube_lists_={"history": True})
    youtube_lists.resume()   # the route calls this when the person turns a list on again
    assert youtube_lists.due(memory) == ["watch_later", "history"]


def test_the_record_tool_is_never_offered_to_a_remote_connection():
    assert "cicada_record_youtube_list" in catalog.NEVER_REMOTE


# --- what a read writes ------------------------------------------------------------------------------------------


def test_refusals_write_nothing(reading, monkeypatch):
    server, memory = reading
    before = porcelain(memory)
    assert _record(server, "watch_later", videos=[{"url": _url(VID_A)}]).startswith("Not recorded: the person has not")
    _on("watch_later")
    assert _record(server, "liked").startswith("Error: list must be")
    assert _record(server, "watch_later", "maybe").startswith("Error: outcome")
    assert _record(server, "watch_later").startswith("Error: a read needs `videos`")
    monkeypatch.setattr(demo_guard, "is_demo", lambda path: True)
    assert "demo" in _record(server, "watch_later", videos=[{"url": _url(VID_A)}]).lower()
    assert porcelain(memory) == before


def test_watch_later_is_saved_where_saved_videos_go_and_one_already_saved_is_never_twice(reading):
    server, memory = reading
    _on("watch_later")
    # VID_B came in earlier from a Takeout playlist CSV (a `youtu.be` link from a bookmark would be the same row).
    idx = media_ingestor.load_url_index(memory)
    media_ingestor.write_prepared(media_ingestor.PreparedItem(
        media_ingestor.RawItem(url=f"https://youtu.be/{VID_B}", folder="Watch later", origin="youtube-playlist"),
        None), memory, idx)
    media_ingestor.save_url_index(memory, idx)
    seeded = porcelain(memory)
    out = _record(server, "watch_later", videos=[
        {"url": _url(VID_A), "title": "Bridge design - YouTube", "channel": "alice-example"},
        {"url": f"https://www.youtube.com/watch?v={VID_B}&list=WL&index=2", "title": "Knots"},
        {"url": f"https://www.youtube.com/shorts/{VID_C}", "title": "A short"},
        {"url": "https://example.com/not-a-video", "title": "elsewhere"},
    ], via="browser tools")
    assert "2 new Watch later video(s) saved; 1 already in memory" in out and "1 row(s) were not YouTube" in out
    idx = media_ingestor.load_url_index(memory)
    assert len(idx) == 3
    entry = idx[media_ingestor.url_hash(_url(VID_A))]
    page = markdown_parser.parse(memory / "entities" / f"{entry['media_entity_id']}.md")
    assert page.frontmatter["name"] == "Bridge design"
    episode = markdown_parser.parse(memory / "episodes" / f"{entry['episode_id']}.md")
    assert episode.frontmatter["folder"] == "Watch later" and episode.frontmatter["origin"] == "youtube-playlist"
    log = git_log(memory)
    assert "Cicada-Author: claude-code" in log and "Cicada-Session: ses_read_fixed" in log
    after = porcelain(memory)   # the read's own pages and the index committed; the seed's page is not this tool's
    assert f"media-{VID_A}" not in after and "sources/" not in after and f"media-{VID_B}" in seeded


def test_history_from_the_agent_is_days_merged_with_what_chrome_wrote_never_saves(reading):
    server, memory = reading
    _on("history")
    watch_history.record(memory, [watch_history.make(_url(VID_A), at="2026-10-14T09:14:03Z", title="Bridge design",
                                                     door="chrome")])
    out = _record(server, "history", videos=[
        {"url": _url(VID_A), "title": "Bridge design", "watched_on": "2026-10-14"},
        {"url": _url(VID_B), "title": "Knots", "channel": "bob-example", "watched_on": "2026-10-14"},
        {"url": _url(VID_C), "title": "No day"},
    ])
    assert "Recorded the person's YouTube watch history" in out and "1 row(s) were not YouTube" in out
    assert media_ingestor.load_url_index(memory) == {}   # history is never a save
    days = [markdown_parser.parse(p) for p in sorted((memory / "episodes").glob("*.md"))]
    [day] = [d for d in days if d.frontmatter.get("source_id") == "watch-history:youtube:2026-10-14"]
    rows = watch_history.stored_rows(memory, day.frontmatter)
    assert [r["url"][-11:] for r in rows] == [VID_A, VID_B]
    assert rows[0]["times"] == ["2026-10-14T09:14:03+00:00"] and rows[1]["channel"] == "bob-example"
    assert porcelain(memory) == ""
