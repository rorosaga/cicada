"""G71 (owner 2026-10-16): YouTube Watch later and watch history — Takeout once, Chrome's history live, and the
person's own agent. Watch later is a save; history is experience, one episode per day, never Saved. One identity for a
video across every door (``url_index``'s ``url_hash``). Synthetic exports, synthetic History rows, placeholder titles."""
from __future__ import annotations

import io
import json
import sqlite3
import subprocess
import time
import zipfile
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from _synthetic_bank import _bank
from api import config, main
from api.services import (bank_index, demo_guard, markdown_parser, media_ingestor, saved_exports, sync_state,
                          watch_history)

ROOT = Path(__file__).resolve().parents[2]
VID_A, VID_B, VID_C = "aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"


@pytest.fixture(autouse=True)
def utc(monkeypatch):
    """Days are the machine's local days: the suite pins the clock's zone so a day is the same on every machine."""
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


@pytest.fixture
def client(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    yield TestClient(main.app), memory
    config.get_settings.cache_clear()


def _days(memory: Path) -> dict[str, markdown_parser.ParsedFile]:
    out = {}
    for path in sorted((memory / "episodes").glob("*.md")):
        parsed = markdown_parser.parse(path)
        sid = str(parsed.frontmatter.get("source_id") or "")
        if sid.startswith(watch_history.SOURCE_PREFIX):
            out[sid] = parsed
    return out


def _head(memory: Path) -> str:
    return subprocess.run(["git", "-C", str(memory), "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=True).stdout.strip()


def _zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, text in files.items():
            zf.writestr(name, text)
    return buf.getvalue()


TAKEOUT_JSON = json.dumps([
    {"header": "YouTube", "title": "Watched Bridge design, part one", "titleUrl": f"https://www.youtube.com/watch?v={VID_A}",
     "subtitles": [{"name": "alice-example", "url": "https://www.youtube.com/channel/UCx"}],
     "time": "2026-10-14T09:14:03.000Z"},
    {"header": "YouTube", "title": "Watched Bridge design, part one", "titleUrl": f"https://www.youtube.com/watch?v={VID_A}",
     "time": "2026-10-14T09:20:00.000Z"},                                 # a reload, not a re-watch
    {"header": "YouTube", "title": "Watched Bridge design, part one", "titleUrl": f"https://www.youtube.com/watch?v={VID_A}",
     "time": "2026-10-14T21:00:00.000Z"},                                 # a re-watch that evening
    {"header": "YouTube", "title": "Watched An ad", "titleUrl": f"https://www.youtube.com/watch?v={VID_C}",
     "details": [{"name": "From Google Ads"}], "time": "2026-10-14T10:00:00.000Z"},
    {"header": "YouTube", "title": "Watched a video that has been removed", "time": "2026-10-14T11:00:00.000Z"},
    {"header": "YouTube", "title": "Viewed a post", "titleUrl": "https://www.youtube.com/post/UgkxEXAMPLE",
     "time": "2026-10-14T12:00:00.000Z"},
    {"header": "YouTube", "title": "Watched Knots", "titleUrl": f"https://www.youtube.com/watch?v={VID_B}",
     "time": "2026-10-15T08:00:00.000Z"},
])

TAKEOUT_HTML = (
    '<html><body><div class="mdl-grid">'
    '<div class="outer-cell mdl-cell"><div class="mdl-grid">'
    '<div class="header-cell mdl-cell"><p class="mdl-typography--title">YouTube<br></p></div>'
    '<div class="content-cell mdl-cell mdl-cell--6-col mdl-typography--body-1">Watched&nbsp;'
    f'<a href="https://www.youtube.com/watch?v={VID_A}">Bridge design, part one</a><br>'
    '<a href="https://www.youtube.com/channel/UCx">alice-example</a><br>Oct 14, 2026, 9:14:03 AM UTC<br></div>'
    '<div class="content-cell mdl-cell mdl-cell--6-col mdl-typography--caption"><b>Products:</b><br>YouTube<br></div>'
    '</div></div>'
    '<div class="outer-cell mdl-cell"><div class="mdl-grid">'
    '<div class="content-cell mdl-cell mdl-cell--6-col mdl-typography--body-1">Watched&nbsp;'
    f'<a href="https://www.youtube.com/watch?v={VID_C}">An ad</a><br>Oct 14, 2026, 10:00:00 AM UTC<br></div>'
    '<div class="content-cell mdl-cell mdl-cell--6-col mdl-typography--caption"><b>Details:</b><br>From Google Ads<br>'
    '</div></div></div>'
    '<div class="outer-cell mdl-cell"><div class="mdl-grid">'
    '<div class="content-cell mdl-cell mdl-cell--6-col mdl-typography--body-1">Watched&nbsp;'
    f'<a href="https://www.youtube.com/watch?v={VID_B}">Knots</a><br>'
    '<a href="https://www.youtube.com/channel/UCy">bob-example</a><br>Oct 15, 2026, 8:00:00 PM UTC<br></div>'
    '</div></div>'
    '</div></body></html>')

WATCH_LATER_CSV = ("Video ID,Playlist Video Creation Timestamp\n"
                   f"{VID_B},2026-10-01T10:00:00+00:00\n"
                   f"{VID_C},2026-10-02T10:00:00+00:00\n")
WATCH_LATER_CSV_OLD = ("Playlist Id,Channel Id,Time Created,Time Updated,Title,Description,Visibility\n"
                       "WL,UCx,2019-01-01 00:00:00 UTC,2019-01-02 00:00:00 UTC,Watch later,,Private\n\n"
                       f"Video Id,Time Added\n{VID_B},2020-03-04 05:06:07 UTC\n")


# --- Takeout: what is history, what is a save -----------------------------------------------------------------------


def test_takeout_json_history_rows_are_history_never_saves_and_ads_posts_and_removed_videos_are_left_out():
    items = media_ingestor.parse_youtube_takeout(TAKEOUT_JSON.encode(), "watch-history.json")
    assert {i.origin for i in items} == {"youtube-history"}
    assert [i.url.rsplit("=", 1)[1] for i in items] == [VID_A, VID_A, VID_A, VID_B]
    assert items[0].added_at == "2026-10-14T09:14:03+00:00" and items[0].channel == "alice-example"
    saves, history = watch_history.split(items)
    assert saves == [] and len(history) == 4


def test_takeout_html_history_the_default_format_is_read_as_history():
    items = media_ingestor.parse_youtube_history_html(TAKEOUT_HTML.encode())
    assert [(i.url.rsplit("=", 1)[1], i.title, i.channel, i.added_at) for i in items] == [
        (VID_A, "Bridge design, part one", "alice-example", "2026-10-14T09:14:03+00:00"),
        (VID_B, "Knots", "bob-example", "2026-10-15T20:00:00+00:00"),
    ]
    assert all(i.origin == "youtube-history" for i in items)


def test_a_dropped_watch_history_html_is_never_read_as_bookmarks():
    """Before 2026-10-16 a dropped watch-history.html went to the Netscape parser: every video and channel link a
    saved bookmark. Now it is history, read only on request."""
    warnings: list[str] = []
    stats: dict = {}
    items, label, from_bookmarks = media_ingestor.parse_upload(TAKEOUT_HTML.encode(), "watch-history.html",
                                                               warnings=warnings, stats=stats)
    assert items == [] and from_bookmarks is False and label == "YouTube Takeout"
    assert stats == {"history_excluded": 2} and warnings == [saved_exports.history_warning(2)]
    items, _, _ = media_ingestor.parse_upload(TAKEOUT_HTML.encode(), "watch-history.html", include_history=True)
    assert len(items) == 2 and all(i.origin == "youtube-history" for i in items)


NETSCAPE_BOOKMARKS = ('<!DOCTYPE NETSCAPE-Bookmark-file-1>\n<META HTTP-EQUIV="Content-Type" CONTENT="text/html; '
                      'charset=UTF-8">\n<TITLE>Bookmarks</TITLE>\n<H1>Bookmarks</H1>\n<DL><p>\n'
                      '<DT><H3>Videos</H3>\n<DL><p>\n'
                      f'<DT><A HREF="https://www.youtube.com/watch?v={VID_A}" ADD_DATE="1760000000">A talk</A>\n'
                      '<DT><A HREF="https://example.com/a-page" ADD_DATE="1760000000">A page</A>\n'
                      '</DL><p>\n</DL><p>\n')


def test_a_takeout_activity_page_under_another_name_is_still_history_never_bookmarks():
    """Review 2026-10-16: the name alone decided, so a browser's ``watch-history (1).html`` or a localized Takeout's
    own file name still went to the Netscape parser. The page's own markup decides now, at every door that reads by
    name (the upload, the sniff behind it, the command line)."""
    for name in ("watch-history (1).html", "historial-de-reproducciones.html", "Watch-History.HTML"):
        stats: dict = {}
        items, label, from_bookmarks = media_ingestor.parse_upload(TAKEOUT_HTML.encode(), name, stats=stats)
        assert (items, label, from_bookmarks) == ([], "YouTube Takeout", False), name
        assert stats == {"history_excluded": 2}, name
        items, _, _ = media_ingestor.parse_upload(TAKEOUT_HTML.encode(), name, include_history=True)
        assert [i.origin for i in items] == ["youtube-history"] * 2, name
    # An activity page of another product holds no watch: refused, never read as links.
    other = TAKEOUT_HTML.replace("youtube.com/watch?v=", "example.com/item?v=")
    with pytest.raises(ValueError):
        media_ingestor.parse_upload(other.encode(), "MyActivity (2).html")


def test_a_bookmarks_html_is_still_read_as_bookmarks():
    assert not media_ingestor.is_takeout_activity_html(NETSCAPE_BOOKMARKS.encode())
    items, label, from_bookmarks = media_ingestor.parse_upload(NETSCAPE_BOOKMARKS.encode(), "bookmarks_10_16_26.html")
    assert from_bookmarks is True and label == "Bookmarks"
    assert sorted(i.url for i in items) == ["https://example.com/a-page", f"https://www.youtube.com/watch?v={VID_A}"]
    assert all((i.origin or "") != "youtube-history" for i in items)


def test_watch_later_is_read_in_the_current_and_older_takeout_layouts_inside_a_whole_archive():
    for path, csv in (("Takeout/YouTube and YouTube Music/playlists/Watch later-videos.csv", WATCH_LATER_CSV),
                      ("Takeout/YouTube and YouTube Music/playlists/Watch later.csv", WATCH_LATER_CSV_OLD),
                      ("Takeout/YouTube/playlists/Watch later-videos.csv", WATCH_LATER_CSV)):
        result = saved_exports.parse_archive(_zip({path: csv, "Takeout/YouTube and YouTube Music/playlists/"
                                                   "playlists.csv": "Playlist ID,Title\nWL,Watch later\n"}))
        assert result.items, path
        assert {i.folder for i in result.items} == {"Watch later"}, path
        assert all(i.origin == "youtube-playlist" for i in result.items), path


def test_history_rows_inside_an_archive_are_never_merged_two_days_are_two_watches():
    data = _zip({"Takeout/YouTube and YouTube Music/history/watch-history.json": TAKEOUT_JSON,
                 "Takeout/YouTube and YouTube Music/playlists/Watch later-videos.csv": WATCH_LATER_CSV})
    plain = saved_exports.parse_archive(data)
    assert len(plain.items) == 2 and plain.history_excluded == 4
    full = saved_exports.parse_archive(data, include_history=True)
    saves, history = watch_history.split(full.items)
    assert len(saves) == 2 and len(history) == 4   # VID_B is in Watch later AND watched: one save, one watch


def test_the_preview_counts_history_apart_as_days_and_offers_the_switch():
    data = _zip({"Takeout/YouTube and YouTube Music/history/watch-history.html": TAKEOUT_HTML,
                 "Takeout/YouTube and YouTube Music/playlists/Watch later-videos.csv": WATCH_LATER_CSV})
    left_out = media_ingestor.preview_upload(data, "takeout.zip")
    assert (left_out.total, left_out.history_excluded, left_out.history_videos) == (2, 2, 0)
    asked = media_ingestor.preview_upload(data, "takeout.zip", include_history=True)
    assert (asked.total, asked.history_videos, asked.history_days) == (2, 2, 2)
    assert [c["name"] for c in asked.collections] == ["Watch later"]   # history is never a collection
    only_history = media_ingestor.preview_upload(TAKEOUT_JSON.encode(), "watch-history.json")
    assert only_history.recognized and only_history.history_excluded == 4


# --- the day's record --------------------------------------------------------------------------------------------


def _w(vid, *, at=None, day=None, door="chrome", title="Bridge design, part one", channel="alice-example"):
    return watch_history.make(f"https://www.youtube.com/watch?v={vid}", at=at, day=day, title=title,
                              channel=channel, door=door)


def test_one_episode_per_day_a_reread_writes_nothing_and_a_rewatch_adds_its_time(tmp_path):
    memory = _bank(tmp_path)
    first = watch_history.record(memory, [_w(VID_A, at="2026-10-14T09:14:03Z"), _w(VID_A, at="2026-10-14T09:20Z"),
                                          _w(VID_B, at="2026-10-15T08:00Z", title="Knots")])
    assert (first.days_created, first.added) == (2, 2)
    days = _days(memory)
    day = days["watch-history:youtube:2026-10-14"]
    # Owner ruling 2026-10-18: a watched day is indexed, never queued for a model read.
    assert day.frontmatter["origin"] == "youtube-history" and day.frontmatter["processed"] is True
    assert day.frontmatter["processed_by"] == "index"
    assert day.frontmatter["id"].startswith("ep_2026-10-14_")
    assert day.frontmatter["videos"] == 1 and watch_history.stored_rows(memory, day.frontmatter)[0]["times"] == ["2026-10-14T09:14:03+00:00"]
    assert "- 09:14 · Bridge design, part one — alice-example · https://www.youtube.com/watch?v=" in day.body
    again = watch_history.record(memory, [_w(VID_A, at="2026-10-14T09:14:03Z")])
    assert (again.days_unchanged, again.added, again.paths) == (1, 0, [])
    rewatch = watch_history.record(memory, [_w(VID_A, at="2026-10-14T21:00Z")])
    assert (rewatch.days_updated, rewatch.added) == (1, 1)
    assert "(watched 2 times)" in _days(memory)["watch-history:youtube:2026-10-14"].body


def test_every_door_and_every_url_shape_is_one_video(tmp_path):
    memory = _bank(tmp_path)
    watch_history.record(memory, [_w(VID_A, at="2026-10-14T09:14:03Z", door="chrome")])
    shapes = [watch_history.make(u, at="2026-10-14T09:16:00Z", door="takeout") for u in (
        f"https://youtu.be/{VID_A}?t=42", f"https://www.youtube.com/shorts/{VID_A}",
        f"https://m.youtube.com/watch?v={VID_A}&list=WL&index=3")]
    agent = _w(VID_A, day="2026-10-14", door="agent", title="")
    result = watch_history.record(memory, shapes + [agent])
    assert result.added == 0
    [row] = watch_history.stored_rows(memory, _days(memory)["watch-history:youtube:2026-10-14"].frontmatter)
    assert len(row["times"]) == 1
    # The same identity Watch later and bookmarks use.
    assert media_ingestor.url_hash(row["url"]) == media_ingestor.url_hash(f"https://youtu.be/{VID_A}")


def test_a_day_only_door_merges_into_the_timed_row_and_a_new_video_is_listed_without_a_time(tmp_path):
    memory = _bank(tmp_path)
    watch_history.record(memory, [_w(VID_A, at="2026-10-14T09:14:03Z")])
    watch_history.record(memory, [_w(VID_B, day="2026-10-14", door="agent", title="Knots")])
    rows = watch_history.stored_rows(memory, _days(memory)["watch-history:youtube:2026-10-14"].frontmatter)
    assert [r["url"][-11:] for r in rows] == [VID_A, VID_B] and rows[1]["times"] == []


def test_a_title_and_channel_are_scrubbed_and_tab_noise_is_stripped():
    w = watch_history.make(f"https://www.youtube.com/watch?v={VID_A}", at="2026-10-14T09:00:00Z",
                           title="(3) token sk-abcdefghijklmnopqrstuvwxyz123456 - YouTube", door="chrome")
    assert w.title == "token [redacted]"


def test_what_is_not_a_video_page_is_never_a_watch():
    for url in ("https://www.youtube.com/results?search_query=bridges", "https://www.youtube.com/@alice-example",
                "https://www.youtube.com/", "https://example.com/watch?v=aaaaaaaaaaa", "javascript:alert(1)",
                "https://www.youtube.com.evil.example/watch?v=aaaaaaaaaaa"):
        assert watch_history.watch_url(url) is None, url


# --- the doors --------------------------------------------------------------------------------------------------


def test_an_upload_with_history_saves_watch_later_and_keeps_history_as_days_never_in_saved(client, monkeypatch):
    c, memory = client
    monkeypatch.setattr(media_ingestor, "_INLINE_ENRICH_LIMIT", 0)   # the background path, no fetch in a test

    async def no_ingest(items, memory_path, from_bookmark_file=False):
        idx = media_ingestor.load_url_index(memory_path)
        for item in items:
            media_ingestor.write_prepared(media_ingestor.PreparedItem(item, None), memory_path, idx)
        media_ingestor.save_url_index(memory_path, idx)
        return len(items), 0

    monkeypatch.setattr(media_ingestor, "ingest_chunked", no_ingest)
    data = _zip({"Takeout/YouTube and YouTube Music/history/watch-history.json": TAKEOUT_JSON,
                 "Takeout/YouTube and YouTube Music/playlists/Watch later-videos.csv": WATCH_LATER_CSV})
    r = c.post("/sources/upload?include_history=true", files={"file": ("takeout.zip", data, "application/zip")})
    assert r.status_code == 200, r.text
    assert "one entry per day, not saves" in r.json()["message"]
    idx = media_ingestor.load_url_index(memory)
    assert {e["url"].rsplit("=", 1)[1] for e in idx.values()} == {VID_B, VID_C}   # Watch later only
    assert sorted(_days(memory)) == ["watch-history:youtube:2026-10-14", "watch-history:youtube:2026-10-15"]
    log = subprocess.run(["git", "-C", str(memory), "log", "--format=%B"], capture_output=True, text=True,
                         check=True).stdout
    assert "Watch history" in log and "user/watch_history" in log


def test_without_the_switch_an_upload_writes_no_history(client, monkeypatch):
    c, memory = client
    r = c.post("/sources/upload", files={"file": ("watch-history.json", TAKEOUT_JSON.encode(), "application/json")})
    assert r.status_code == 200, r.text
    assert _days(memory) == {} and media_ingestor.load_url_index(memory) == {}


def test_the_intake_sniff_offers_history_for_a_dropped_watch_history_page(client):
    c, _memory = client
    r = c.post("/intake/sniff", files={"file": ("watch-history.html", TAKEOUT_HTML.encode(), "text/html")})
    body = r.json()
    assert body["recognized"] and body["kind"] == "saved" and body["historyExcluded"] == 2
    r = c.post("/intake/sniff?include_history=true",
               files={"file": ("watch-history.html", TAKEOUT_HTML.encode(), "text/html")})
    assert (r.json()["historyVideos"], r.json()["historyDays"]) == (2, 2)


def _visit(vid_or_url, at, title="Bridge design, part one - YouTube"):
    url = vid_or_url if "://" in vid_or_url else f"https://www.youtube.com/watch?v={vid_or_url}"
    return {"url": url, "title": title, "visitedAt": at}


def test_the_intake_sniff_reads_a_renamed_watch_history_page_as_history(client):
    c, _memory = client
    r = c.post("/intake/sniff", files={"file": ("watch-history (1).html", TAKEOUT_HTML.encode(), "text/html")})
    body = r.json()
    assert body["recognized"] and body["kind"] == "saved" and body["historyExcluded"] == 2, body
    assert body["counts"]["items"] == 0


def test_chrome_visits_become_day_episodes_once_and_anything_else_is_dropped(client):
    c, memory = client
    visits = [_visit(VID_A, "2026-10-14T09:14:03Z"), _visit(VID_A, "2026-10-14T09:14:40Z"),
              _visit(f"https://youtu.be/{VID_B}", "2026-10-15T08:00:00Z", title="(2) Knots - YouTube"),
              _visit("https://www.youtube.com/results?search_query=x", "2026-10-15T08:01:00Z"),
              _visit("https://example.com/a-page", "2026-10-15T08:02:00Z")]
    r = c.post("/sources/watch-history/sync", json={"browser": "chrome", "visits": visits})
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["received"], body["kept"], body["ignored"], body["daysCreated"]) == (5, 3, 2, 2)
    assert body["videos"] == 2 and body["bank"] == memory.name
    day = _days(memory)["watch-history:youtube:2026-10-15"]
    assert "Knots · https://www.youtube.com/watch?v=" in day.body and "example.com" not in day.body
    assert sync_state.read_sync_state(memory)[watch_history.channel_id("chrome")]["count"] == 2
    head = _head(memory)
    again = c.post("/sources/watch-history/sync", json={"browser": "chrome", "visits": visits}).json()
    assert (again["added"], again["daysUnchanged"]) == (0, 2)
    assert _head(memory) == head   # a re-read with nothing new commits nothing
    channels = c.get("/sources/channels").json()
    row = next(ch for ch in channels["channels"] if ch["id"] == "chrome-youtube-history")
    assert row["connected"] and row["count"] == 2


def test_the_chrome_route_refuses_what_it_cannot_trust(client, monkeypatch):
    c, memory = client
    assert c.post("/sources/watch-history/sync", json={"browser": "safari", "visits": []}).status_code == 422
    assert c.post("/sources/watch-history/sync",
                  json={"browser": "chrome", "profile": "../x", "visits": []}).status_code == 422
    monkeypatch.setattr(watch_history, "MAX_VISITS", 1)
    big = [_visit(VID_A, "2026-10-14T09:00:00Z"), _visit(VID_B, "2026-10-14T10:00:00Z")]
    assert c.post("/sources/watch-history/sync", json={"browser": "chrome", "visits": big}).status_code == 413
    monkeypatch.setattr(demo_guard, "is_demo", lambda path: True)
    assert c.post("/sources/watch-history/sync", json={"browser": "chrome", "visits": []}).status_code == 409
    assert _days(memory) == {}


# --- the app's query, on a synthetic Chrome History database -------------------------------------------------------

READER = ROOT / "app/CicadaApp/Sources/CicadaApp/Services/WatchHistory/ChromeWatchHistoryReader.swift"


def _app_sql() -> str:
    """The app's one query, read from its source between its markers — so this test runs the SQL the app runs."""
    text = READER.read_text(encoding="utf-8")
    body = text.split("// sql:begin", 1)[1].split("// sql:end", 1)[0]
    return body.split('"""', 2)[1].strip()


def _webkit(iso: str) -> int:
    from datetime import datetime, timezone

    dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc)
    return int((dt - datetime(1601, 1, 1, tzinfo=timezone.utc)).total_seconds() * 1_000_000)


def test_the_apps_query_on_a_synthetic_history_db_reads_youtube_watch_pages_only(tmp_path):
    db = tmp_path / "History"
    con = sqlite3.connect(db)
    con.executescript((Path(__file__).parent / "fixtures" / "chrome_history_tables.sql").read_text(encoding="utf-8"))
    rows = [(1, f"https://www.youtube.com/watch?v={VID_A}&t=3", "Bridge design - YouTube"),
            (2, f"https://youtu.be/{VID_B}", "Knots - YouTube"),
            (3, f"https://www.youtube.com/shorts/{VID_C}", "A short - YouTube"),
            (4, "https://www.youtube.com/results?search_query=private", "private - YouTube"),
            (5, "https://example.com/private-page", "A private page"),
            (6, f"https://m.youtube.com/watch?v={VID_A}", "Bridge design - YouTube"),
            (7, f"https://www.youtube.com.evil.example/watch?v={VID_A}", "Not YouTube")]
    con.executemany("INSERT INTO urls(id, url, title) VALUES (?, ?, ?)", rows)
    for i, (uid, _u, _t) in enumerate(rows, start=1):
        con.execute("INSERT INTO visits(id, url, visit_time) VALUES (?, ?, ?)",
                    (i, uid, _webkit(f"2026-10-14T0{i}:00:00Z")))
    con.commit()
    got = con.execute(_app_sql(), (1, 100)).fetchall()   # past visit 1, at most 100 rows
    capped = con.execute(_app_sql(), (0, 2)).fetchall()
    con.close()
    urls = [r[1] for r in got]
    assert urls == [f"https://youtu.be/{VID_B}", f"https://www.youtube.com/shorts/{VID_C}",
                    f"https://m.youtube.com/watch?v={VID_A}"]   # past the cursor, YouTube video pages only
    assert [r[0] for r in capped] == [1, 2]   # oldest first, so a capped pass resumes where it stopped


def test_tiktok_browsing_history_is_days_too_never_saves(tmp_path):
    txt = ("Date: 2023-06-01 09:00:00\nLink: https://www.tiktokv.com/share/video/7000000000000000004/\n\n"
           "Date: 2023-06-01 21:00:00\nLink: https://www.tiktokv.com/share/video/7000000000000000005/\n")
    items, _, _ = media_ingestor.parse_upload(txt.encode(), "Browsing History.txt", include_history=True)
    saves, history = watch_history.split(items)
    assert saves == [] and len(history) == 2
    import asyncio

    memory = _bank(tmp_path)
    result = asyncio.run(watch_history.import_history(memory, history, door="takeout", trigger="user/watch_history"))
    assert (result.days_created, result.added) == (1, 2)
    [day] = _days(memory).values()
    assert day.frontmatter["origin"] == "tiktok-history" and day.frontmatter["source_id"] == "watch-history:tiktok:2023-06-01"
    assert {r["via"][0] for r in watch_history.stored_rows(memory, day.frontmatter)} == {"export"}
