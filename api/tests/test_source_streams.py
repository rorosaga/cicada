"""G245 (ruling 78) — what each source reads, as streams: `source_streams`, `GET /sources/streams`,
`POST /sources/streams/check` and the items route's `stream` / `folder` parameters and row fields.

Every test builds a synthetic bank and a scratch `$CICADA_HOME` under tmp_path; nothing real is read and nothing is
fetched. Placeholder handles and words only."""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import (
    bank_index, channel_items, channel_registry, history_index, reading_settings, saved_lists, source_streams,
    substack_lists, youtube_lists,
)

NOW = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)


def _write(path: Path, fm: dict, body: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["---"] + [f"{k}: {json.dumps(v)}" for k, v in fm.items()] + ["---", "", body]
    path.write_text("\n".join(lines), encoding="utf-8")


def _json(bank: Path, rel: str, data) -> None:
    path = bank / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _save(bank: Path, slug: str, url: str, *, origin: str, folder: str, collections=(), posted=None, read=False,
          save_folders=None, status="active") -> None:
    """A saved-list post the way the ingest leaves it: a media page, its url-index row and its episode."""
    page, episode = f"media-{slug}", f"ep_2026-11-01_{slug}"
    _write(bank / "entities" / f"{page}.md", {
        "id": page, "type": "media", "name": slug, "status": status, "origin": origin, "folder": folder,
        "media": {"url": url},
        **({"collections": [folder, *collections]} if collections else {}), "created": "2026-11-01"}, "PAGE BODY")
    ep = {"id": episode, "timestamp": "2026-11-01T08:00:00+00:00", "origin": origin, "url": url,
          "media_entity_id": page, "folder": folder, "source": "url",
          "processed": True, "processed_by": "sleep" if read else history_index.INDEXED_BY}
    if save_folders:
        ep["save_folders"] = {origin: list(save_folders)}
    _write(bank / "episodes" / f"{episode}.md", ep, "EPISODE BODY")
    index_path = bank / "sources" / "url_index.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else {}
    entry = {"media_entity_id": page, "url": url, "title": slug, "saved_at": "2026-11-02T10:00:00+00:00",
             "episode_id": episode}
    if posted:
        entry["posted_at"] = posted
    index[f"h-{slug}"] = entry
    _json(bank, "sources/url_index.json", index)


@dataclass(frozen=True)
class _Based(saved_lists.Platform):
    """A table entry as the track adding the likes lists writes it: a ``base`` site."""
    base: str | None = None


@pytest.fixture(autouse=True)
def _no_list_page_timer(monkeypatch):
    """A streams read asks list pages to be written on a 3 s timer (#940). A write landing between a test's requests
    changes the bank under it (the membership pass then runs twice), so here the timer never starts."""
    from api.services import list_pages

    monkeypatch.setattr(list_pages, "start_sync", lambda mp, **kw: False)


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    reading_settings.update(agent_enabled_=True, acknowledge=True)
    return tmp_path / "home"


@pytest.fixture
def bank(tmp_path, home):
    b = tmp_path / "memory"
    b.mkdir()
    return b


@pytest.fixture
def more_lists(monkeypatch):
    """The keys another track adds to the tables: X likes, Instagram likes, Reddit upvoted, LinkedIn connections, and
    YouTube's playlists and liked videos — appearing here with no edit to ``source_streams``."""
    table = dict(saved_lists.PLATFORMS)
    # X likes, Instagram likes and Reddit upvoted are real keys now (`saved_lists.PLATFORMS`); only what no track has
    # built yet is added here, and only when it is missing.
    table.setdefault("linkedin-connections", _Based(
        "linkedin-connections", "LinkedIn", "Connections", "https://www.linkedin.com/mynetwork/invite-connect/connections/",
        "", "", "", "linkedin.com", "to read who you connected with", ("linkedin.com",), base="linkedin"))
    monkeypatch.setattr(saved_lists, "PLATFORMS", table)
    lists = dict(youtube_lists.LISTS)
    lists.setdefault("playlists", {"url": "https://www.youtube.com/feed/playlists", "label": "Playlists"})
    lists.setdefault("liked", {"url": "https://www.youtube.com/playlist?list=LL", "label": "Liked videos"})
    monkeypatch.setattr(youtube_lists, "LISTS", lists)
    # The person's switches validate against the tuples the same track extends.
    monkeypatch.setattr(reading_settings, "SAVED_LISTS", tuple(dict.fromkeys(
        (*reading_settings.SAVED_LISTS, "linkedin-connections"))))
    monkeypatch.setattr(reading_settings, "YOUTUBE_LISTS", tuple(dict.fromkeys(
        (*reading_settings.YOUTUBE_LISTS, "playlists", "liked"))))
    return table


def _sources(bank, *, channels=None, connected=None, now=NOW, feed_fetch=True) -> dict[str, dict]:
    body = source_streams.build(bank, channels=channels if channels is not None else [],
                                connectors_connected=connected, feed_fetch_allowed=feed_fetch, now=now)
    return {s["id"]: s for s in body["sources"]}


def _streams(bank, source, **kw) -> dict[str, dict]:
    return {s["id"]: s for s in _sources(bank, **kw)[source]["streams"]}


# --- the ids the app's catalogue uses ----------------------------------------------------------------------------------

#: `SourceCatalog.fixed`'s ids (app/CicadaApp/Sources/CicadaApp/Models/SourceCatalog.swift), copied: a source id this
#: module emits is one of these, a browser (`browser:<id>`), or an agent (`overview:<id>`) — what the app matches by.
CATALOGUE_IDS = {
    "x", "youtube", "instagram", "linkedin", "reddit", "pinterest", "github", "linear", "spotify", "tiktok", "substack",
    "calendar-local", "contacts-local", "reminders-local", "imessage", "whatsapp", "traces", "notes", "voice-memos",
    "folders", "apple-books", "google-books", "goodreads", "book-scan", "files", "notion", "chat-exports", "rss",
    "calendar", "telegram", "telegram-chats", "hex", "meeting-folders",
}


def test_every_emitted_source_id_is_one_the_apps_catalogue_uses(bank, more_lists):
    for source in _sources(bank):
        assert (source in CATALOGUE_IDS or re.fullmatch(r"browser:[a-z]+", source)
                or source.startswith("overview:harness:")), source


def test_the_pinned_ids_are_still_in_the_catalogue_source():
    swift = Path(__file__).resolve().parents[2] / "app/CicadaApp/Sources/CicadaApp/Models/SourceCatalog.swift"
    if not swift.exists():
        pytest.skip("the app is not in this checkout")
    text = swift.read_text(encoding="utf-8")
    literal = set(re.findall(r'SourceCatalogEntry\(id: "([a-z-]+)"', text))
    assert literal <= CATALOGUE_IDS, sorted(literal - CATALOGUE_IDS)
    for needed in ("x", "youtube", "instagram", "linkedin", "reddit", "pinterest", "github", "notes", "notion"):
        assert needed in literal


def test_the_sources_the_plan_names_are_there_with_their_streams(bank, more_lists):
    out = _sources(bank)
    assert [s["id"] for s in out["x"]["streams"]] == ["x.bookmarks", "x.likes", "x.reposts", "x.following", "x.saves-you-make"]
    assert [s["id"] for s in out["instagram"]["streams"]] == ["instagram.saved", "instagram.likes",
                                                              "instagram.saves-you-make"]
    assert [s["id"] for s in out["reddit"]["streams"]] == ["reddit.saved", "reddit.upvoted", "reddit.saves-you-make"]
    assert [s["id"] for s in out["linkedin"]["streams"]] == ["linkedin.saved", "linkedin.connections",
                                                             "linkedin.saves-you-make"]
    assert [s["id"] for s in out["youtube"]["streams"]] == [
        "youtube.watch_later", "youtube.history", "youtube.playlists", "youtube.liked", "youtube.saves-you-make"]
    assert [s["id"] for s in out["substack"]["streams"]] == [
        "substack.saved", "substack.liked", "substack.history", "substack.subscriptions"]
    assert "browser:chrome" in out and "browser:safari" in out and "notes" in out and "github" in out


def test_a_list_added_to_the_tables_appears_under_its_source_with_its_kind(bank, more_lists):
    x = _streams(bank, "x")
    assert (x["x.likes"]["kind"], x["x.likes"]["label"], x["x.likes"]["how"]) == ("liked", "Likes", "browser")
    assert x["x.likes"]["switch"] == {"setting": "savedLists", "key": "x-likes"}
    assert x["x.bookmarks"]["kind"] == "saved" and x["x.bookmarks"]["owner"] == "backend"
    assert _streams(bank, "linkedin")["linkedin.connections"]["kind"] == "connections"
    yt = _streams(bank, "youtube")
    assert yt["youtube.playlists"]["kind"] == "playlists" and yt["youtube.liked"]["kind"] == "liked"
    assert yt["youtube.watch_later"]["kind"] == "later" and yt["youtube.history"]["kind"] == "history"
    assert yt["youtube.liked"]["switch"] == {"setting": "youtubeLists", "key": "liked"}


def test_a_key_the_annotations_do_not_know_still_gets_a_stream(bank, monkeypatch):
    table = dict(saved_lists.PLATFORMS)
    table["x-polls"] = _Based("x-polls", "X", "Polls", "https://x.com/", "", "x-polls", "Polls", "x.com",
                              "to read your polls", ("x.com",), base="x")
    monkeypatch.setattr(saved_lists, "PLATFORMS", table)
    stream = _streams(bank, "x")["x.polls"]
    assert (stream["label"], stream["kind"], stream["how"]) == ("Polls", "saved", "browser")
    # Reposts is annotated: its own kind, never "saved" or "liked" (the app draws the word the person knows).
    assert _streams(bank, "x")["x.reposts"]["kind"] == "reposted"


def test_a_table_entry_with_no_base_is_its_own_source(bank):
    assert not saved_lists.PLATFORMS["x"].base and saved_lists.PLATFORMS["x-likes"].base == "x"
    out = _sources(bank)
    assert set(saved_lists.PLATFORMS) - {"x-likes", "x-reposts", "x-following", "instagram-likes",
                                      "linkedin-connections", "reddit-upvoted"} <= set(out)
    assert _streams(bank, "reddit")["reddit.saved"]["label"] == "Saved"
    assert saved_lists.pause_key("x") == "x" and saved_lists.pause_key("x-likes") == "x"


# --- state, health and the pause ------------------------------------------------------------------------------------------


def test_a_list_is_off_until_the_person_turns_it_on_and_reads_when_an_agent_reported(bank, home):
    assert _streams(bank, "x")["x.bookmarks"]["state"] == "off"
    reading_settings.update(saved_lists_={"x": True})
    stream = _streams(bank, "x")["x.bookmarks"]
    assert (stream["state"], stream["health"], stream["lastReadAt"]) == ("on", "not_read", None)
    saved_lists.note(bank, "x", "read", items=3, handle="alice_example",
                     profile_url="https://x.com/alice_example", now=NOW)
    out = _sources(bank)
    assert out["x"]["streams"][0]["health"] == "read" and out["x"]["streams"][0]["lastReadAt"] == "2026-11-24T12:00:00Z"
    assert out["x"]["account"] == {"handle": "alice_example", "profileUrl": "https://x.com/alice_example"}
    assert out["instagram"]["account"] is None


def test_a_login_wall_pauses_every_list_of_the_site_and_a_check_never_lifts_it(bank, home, more_lists):
    reading_settings.update(saved_lists_={"x": True, "x-likes": True})
    saved_lists.note(bank, "x", "needs_login", now=NOW)
    x = _streams(bank, "x")
    until = (NOW + saved_lists.PAUSE).isoformat().replace("+00:00", "Z")
    for stream in ("x.bookmarks", "x.likes"):
        assert (x[stream]["health"], x[stream]["pausedUntil"]) == ("signed_out", until), stream
    assert saved_lists.paused_until("x-likes", NOW) is not None   # one pause for the site
    assert saved_lists.request_check(bank, "x-likes", NOW) is False
    assert saved_lists.paused_until("x", NOW) is not None
    saved_lists.note(bank, "x-likes", "read", items=1, now=NOW + timedelta(days=8))
    assert saved_lists.paused_until("x", NOW + timedelta(days=8)) is None


def test_a_site_wide_pause_one_list_did_not_cause_says_paused_or_the_cause(bank, home):
    reading_settings.update(youtube_lists_={"watch_later": True, "history": True})
    youtube_lists.note(bank, "history", "blocked", now=NOW)
    yt = _streams(bank, "youtube")
    assert yt["youtube.watch_later"]["health"] == "couldnt_read" and yt["youtube.history"]["health"] == "couldnt_read"
    assert yt["youtube.watch_later"]["pausedUntil"] is not None


def test_turned_off_means_no_health(bank, home):
    reading_settings.update(saved_lists_={"x": True})
    saved_lists.note(bank, "x", "read", items=1, now=NOW)
    reading_settings.update(saved_lists_={"x": False})
    stream = _streams(bank, "x")["x.bookmarks"]
    assert (stream["state"], stream["health"]) == ("off", None) and stream["lastReadAt"] == "2026-11-24T12:00:00Z"


def test_a_connector_the_person_connected_is_the_way_in_use_for_its_stream(bank, home):
    channels = [{"id": "x", "connected": True, "count": 5, "count_is_delta": True, "last_sync": "2026-11-24T08:10:00Z",
                 "last_error": None}]
    stream = _streams(bank, "x", channels=channels, connected={"x": True})["x.bookmarks"]
    assert (stream["how"], stream["control"], stream["state"], stream["health"], stream["switch"]) == (
        "account", "setup", "on", "read", None)
    assert stream["lastReadAt"] == "2026-11-24T08:10:00Z"
    off = _streams(bank, "x")["x.bookmarks"]
    assert (off["how"], off["control"], off["state"]) == ("browser", "switch", "off")
    refused = [{**channels[0], "last_error": "x", "last_error_code": "sign-in"}]
    assert _streams(bank, "x", channels=refused, connected={"x": True})["x.bookmarks"]["health"] == "signed_out"


def test_an_app_read_stream_takes_its_state_from_its_channel_row(bank):
    rows = [{"id": "notes", "connected": True, "count": 41, "count_is_delta": False, "last_sync": "2026-11-24T07:00:00Z"},
            {"id": "calendar-local", "connected": False, "count": 0, "count_is_delta": False, "last_sync": None}]
    out = _sources(bank, channels=rows)
    notes = out["notes"]["streams"][0]
    assert (notes["id"], notes["kind"], notes["how"], notes["owner"], notes["state"], notes["count"], notes["depth"]) == (
        "notes.notes", "notes", "app", "app", "on", 41, "read")
    assert out["calendar-local"]["streams"][0]["state"] == "off"
    bad = [{**rows[0], "last_error": "boom"}]
    assert _sources(bank, channels=bad)["notes"]["streams"][0]["health"] == "couldnt_read"


def test_a_feed_stream_is_unavailable_with_its_reason_while_feeds_are_not_fetched(bank):
    rows = [{"id": "rss", "connected": False, "count": 2, "count_is_delta": False, "last_sync": None}]
    rss = _sources(bank, channels=rows, feed_fetch=False)["rss"]["streams"][0]
    assert rss["state"] == "unavailable" and "Keep memory working" in rss["why"]
    assert _sources(bank, channels=rows)["rss"]["streams"][0]["why"] is None


def test_the_click_stream_is_the_apps_to_overwrite(bank):
    click = _streams(bank, "github")["github.saves-you-make"]
    assert (click["how"], click["owner"], click["control"], click["state"], click["count"]) == (
        "click", "app", "switch", "off", None)
    assert {"x", "instagram", "github", "tiktok", "reddit", "youtube"} <= {
        sid for sid, s in _sources(bank).items() if any(t["how"] == "click" for t in s["streams"])}


def test_every_value_on_the_wire_is_in_the_contract(bank, more_lists):
    for source in _sources(bank).values():
        for s in source["streams"]:
            assert s["kind"] in source_streams.KINDS and s["how"] in source_streams.HOWS, s["id"]
            assert s["state"] in source_streams.STATES and s["owner"] in ("backend", "app"), s["id"]
            assert s["health"] is None or s["health"] in source_streams.HEALTHS, s["id"]
            assert s["control"] in ("switch", "setup") and s["depth"] in ("index", "read"), s["id"]
            assert s["id"].startswith(source["id"] + "."), s["id"]
            assert s["why"] is None or s["state"] == "unavailable", s["id"]


# --- counts are list membership ----------------------------------------------------------------------------------------------


def _x_bank(bank):
    # Bookmarked first (keeps the origin x-bookmarks), liked later (holds Likes only in collections), a like only, a
    # bookmark only — plus one the Feed hides.
    _save(bank, "both", "https://x.com/alice_example/status/1", origin="x-bookmarks", folder="Bookmarks",
          collections=["Likes"], save_folders=["Reading"])
    _save(bank, "like", "https://x.com/alice_example/status/2", origin="x-likes", folder="Likes")
    _save(bank, "mark", "https://x.com/alice_example/status/3", origin="x-bookmarks", folder="Bookmarks",
          save_folders=["Reading", "Ideas"], posted="2026-10-30")
    _save(bank, "gone", "https://x.com/alice_example/status/4", origin="x-bookmarks", folder="Bookmarks",
          status="archived")


def test_a_post_on_two_lists_counts_on_both(bank, more_lists):
    _x_bank(bank)
    x = _streams(bank, "x")
    assert (x["x.bookmarks"]["count"], x["x.likes"]["count"]) == (2, 2)
    assert x["x.bookmarks"]["folderCount"] == 2 and x["x.likes"]["folderCount"] == 0


def test_a_save_naming_no_known_list_counts_on_the_stream_of_its_own_origin(bank, more_lists):
    _save(bank, "sub", "https://www.reddit.com/r/alpha/comments/abc123/x/", origin="reddit-saved", folder="r/alpha")
    reddit = _streams(bank, "reddit")
    assert reddit["reddit.saved"]["count"] == 1 and reddit["reddit.upvoted"]["count"] is None   # never read: unknown


def test_a_list_never_read_has_no_count_and_a_list_read_and_found_empty_has_zero(bank, more_lists):
    assert _streams(bank, "reddit")["reddit.upvoted"]["count"] is None
    assert _streams(bank, "youtube")["youtube.playlists"]["count"] is None
    saved_lists.note(bank, "reddit-upvoted", "read", items=0, now=NOW)
    reddit = _streams(bank, "reddit")["reddit.upvoted"]
    assert reddit["count"] == 0 and reddit["lastReadAt"], "read and empty is a zero, said with its day"
    youtube_lists.note(bank, "playlists", "needs_login", now=NOW)
    assert _streams(bank, "youtube")["youtube.playlists"]["count"] is None   # an attempt that read nothing is not a read
    youtube_lists.note(bank, "playlists", "read", videos=0, now=NOW)
    assert _streams(bank, "youtube")["youtube.playlists"]["count"] == 0


def test_youtube_counts_playlists_apart_from_watch_later_and_liked(bank, more_lists):
    _save(bank, "wl", "https://www.youtube.com/watch?v=aaaaaaaaaaa", origin="youtube-playlist", folder="Watch later")
    _save(bank, "pl", "https://www.youtube.com/watch?v=bbbbbbbbbbb", origin="youtube-playlist", folder="Alpha trip",
          collections=["Watch later"])
    _save(bank, "pl2", "https://www.youtube.com/watch?v=ccccccccccc", origin="youtube-playlist", folder="Beta")
    _save(bank, "lk", "https://www.youtube.com/watch?v=ddddddddddd", origin="youtube-playlist", folder="Liked videos")
    yt = _streams(bank, "youtube")
    assert (yt["youtube.watch_later"]["count"], yt["youtube.liked"]["count"], yt["youtube.playlists"]["count"]) == (
        2, 1, 2)
    assert yt["youtube.playlists"]["folderCount"] == 2


def test_history_counts_its_days_and_a_non_list_stream_its_channel_rows(bank, home):
    for n, origin in enumerate(("youtube-history", "youtube-history", "substack-history"), 1):
        _write(bank / "episodes" / f"ep_2026-11-0{n}_001.md", {
            "id": f"ep_2026-11-0{n}_001", "origin": origin, "source": "watch-history",
            "source_id": f"watch-history:{origin}:2026-11-0{n}", "timestamp": f"2026-11-0{n}T08:00:00+00:00"})
    assert _streams(bank, "youtube")["youtube.history"]["count"] == 2
    assert _streams(bank, "substack")["substack.history"]["count"] == 1


def test_the_membership_pass_is_kept_between_requests(bank, more_lists, monkeypatch):
    _x_bank(bank)
    calls = []
    real = source_streams._build_members
    monkeypatch.setattr(source_streams, "_build_members", lambda *a: calls.append(1) or real(*a))
    for _ in range(3):
        assert _streams(bank, "x")["x.bookmarks"]["count"] == 2
    assert len(calls) == 1                                            # one pass for three answers
    _save(bank, "more", "https://x.com/alice_example/status/5", origin="x-bookmarks", folder="Bookmarks")
    assert _streams(bank, "x")["x.bookmarks"]["count"] == 3          # and a changed page moves it
    assert len(calls) == 2


# --- checking a connection -------------------------------------------------------------------------------------------------------


def test_a_requested_list_is_offered_first_and_a_check_never_passes_the_daily_bound(bank, home):
    reading_settings.update(saved_lists_={"x": True, "instagram": True, "linkedin": True})
    saved_lists.note(bank, "x", "read", now=NOW - timedelta(hours=30))
    saved_lists.note(bank, "instagram", "read", now=NOW - timedelta(hours=26))
    saved_lists.note(bank, "linkedin", "read", now=NOW - timedelta(hours=40))
    # Three are due; the one read longest ago goes first (not the first key in table order).
    assert saved_lists.due(bank, NOW) == ["linkedin"]
    assert saved_lists.request_check(bank, "x", NOW) is True
    assert saved_lists.due(bank, NOW) == ["x"]                      # requested first, whatever its cadence
    assert _streams(bank, "x", now=NOW)["x.bookmarks"]["checkRequestedAt"] == "2026-11-24T12:00:00Z"
    saved_lists.note(bank, "x", "read", now=NOW)
    assert saved_lists.check_requested_at(bank, "x") is None       # the next read answers it
    assert saved_lists.due(bank, NOW) == ["linkedin"]
    saved_lists.request_check(bank, "instagram", NOW)
    for _ in range(saved_lists.DAILY_READS):
        saved_lists.count_read(bank, NOW)
    assert saved_lists.due(bank, NOW) == []                         # never beyond the bound


def test_a_list_never_read_goes_before_one_read_long_ago_and_ties_keep_table_order(bank, home):
    reading_settings.update(saved_lists_={"x": True, "instagram": True, "linkedin": True})
    saved_lists.note(bank, "x", "read", now=NOW - timedelta(days=3))
    assert saved_lists.due(bank, NOW) == ["instagram"]
    saved_lists.note(bank, "instagram", "read", now=NOW - timedelta(days=2))
    assert saved_lists.due(bank, NOW) == ["linkedin"]
    saved_lists.note(bank, "linkedin", "read", now=NOW - timedelta(days=1))
    assert saved_lists.due(bank, NOW) == ["x"]                      # now x was read longest ago, not first-by-order


def test_a_blocked_attempt_also_answers_a_requested_check(bank, home):
    reading_settings.update(saved_lists_={"x": True})
    saved_lists.request_check(bank, "x", NOW)
    saved_lists.note(bank, "x", "needs_login", now=NOW)
    assert saved_lists.check_requested_at(bank, "x") is None and saved_lists.due(bank, NOW) == []


def test_youtube_and_substack_serve_requested_lists_first_then_the_longest_unread(bank, home):
    reading_settings.update(youtube_lists_={"watch_later": True, "history": True},
                            substack_lists_={"saved": True, "liked": True})
    youtube_lists.note(bank, "watch_later", "read", now=NOW - timedelta(hours=21))
    youtube_lists.note(bank, "history", "read", now=NOW - timedelta(hours=40))
    assert youtube_lists.due(bank, NOW) == ["history", "watch_later"]
    youtube_lists.note(bank, "watch_later", "read", now=NOW - timedelta(hours=1))
    assert youtube_lists.due(bank, NOW) == ["history"]
    assert youtube_lists.request_check(bank, "watch_later", NOW) is True
    assert youtube_lists.due(bank, NOW) == ["watch_later", "history"]
    substack_lists.note(bank, "saved", "read", now=NOW - timedelta(hours=21))
    substack_lists.note(bank, "liked", "read", now=NOW - timedelta(hours=60))
    assert substack_lists.due(bank, NOW) == ["liked"]
    substack_lists.request_check(bank, "saved", NOW)
    assert substack_lists.due(bank, NOW) == ["saved"]
    youtube_lists.note(bank, "history", "needs_login", now=NOW)
    assert youtube_lists.request_check(bank, "history", NOW) is False   # a pause is never lifted by a check


def test_check_stamps_lists_reports_apps_and_runs_a_connector_once(bank, home):
    reading_settings.update(saved_lists_={"x": True, "instagram": True})
    saved_lists.note(bank, "instagram", "needs_login", now=NOW)
    rows = [{"id": "notes", "connected": True, "count": 1, "count_is_delta": False, "last_sync": None},
            {"id": "github", "connected": True, "count": 1, "count_is_delta": True, "last_sync": None}]
    ran = []

    async def sync(adapter, memory_path):
        ran.append(adapter.CHANNEL_ID)
        return {"status": "ok"}

    out = asyncio.run(source_streams.check(bank, None, channels=rows, connectors_connected={"github": True},
                                           sync=sync, now=NOW))
    by = {r["stream"]: r["result"] for r in out}
    assert by["x.bookmarks"] == "requested" and by["instagram.saved"] == "signed_out"
    assert by["reddit.saved"] == "off" and by["notes.notes"] == "app" and by["x.saves-you-make"] == "noted"
    assert by["github.stars"] == "read" and by["github.repositories"] == "read" and ran == ["github"]


def test_check_for_some_sources_touches_only_those(bank, home):
    reading_settings.update(saved_lists_={"x": True, "instagram": True})
    out = asyncio.run(source_streams.check(bank, ["instagram"], channels=[], connectors_connected={}, now=NOW))
    assert {r["stream"].split(".")[0] for r in out} == {"instagram"}
    assert saved_lists.check_requested_at(bank, "x") is None and saved_lists.check_requested_at(bank, "instagram")


# --- the routes -----------------------------------------------------------------------------------------------------------------


@pytest.fixture
def client(bank, home, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    config.get_settings.cache_clear()
    yield TestClient(main.app)
    config.get_settings.cache_clear()


def test_the_streams_route_answers_a_body_and_304s_on_its_digest(client, bank):
    first = client.get("/sources/streams")
    assert first.status_code == 200 and first.json()["shape"] == source_streams.SHAPE
    etag = first.headers["etag"]
    assert client.get("/sources/streams", headers={"If-None-Match": etag}).status_code == 304
    reading_settings.update(saved_lists_={"x": True})
    changed = client.get("/sources/streams", headers={"If-None-Match": etag})
    assert changed.status_code == 200 and changed.headers["etag"] != etag


def test_the_streams_route_writes_nothing(client, bank, home):
    before = sorted(str(p) for p in bank.rglob("*")) + sorted(str(p) for p in home.rglob("*"))
    client.get("/sources/streams")
    assert sorted(str(p) for p in bank.rglob("*")) + sorted(str(p) for p in home.rglob("*")) == before


def test_check_route_stamps_a_requested_list_and_returns_the_rows_with_what_it_did(client, bank):
    reading_settings.update(saved_lists_={"x": True})
    out = client.post("/sources/streams/check", json={"sources": ["x"]})
    assert out.status_code == 200
    body = out.json()
    assert [s["id"] for s in body["sources"]] == ["x"]
    assert body["sources"][0]["streams"][0]["checkRequestedAt"] is not None
    assert {"stream": "x.bookmarks", "result": "requested"} in body["checked"]
    assert saved_lists.due(bank) == ["x"]
    assert client.post("/sources/streams/check").status_code == 200   # no body: every source


def test_check_route_runs_a_connected_connectors_own_sync_once(client, bank, monkeypatch):
    from api.services.connectors import ADAPTERS

    ran = []

    async def sync(adapter, memory_path):
        ran.append(adapter.CHANNEL_ID)
        return {"status": "ok"}

    monkeypatch.setattr(ADAPTERS["github"], "is_connected", lambda: True)
    monkeypatch.setattr(source_streams, "_default_sync", sync)
    body = client.post("/sources/streams/check", json={"sources": ["github"]}).json()
    assert ran == ["github"]
    assert {r["stream"]: r["result"] for r in body["checked"]} == {
        "github.stars": "read", "github.repositories": "read", "github.saves-you-make": "noted"}
    stars = body["sources"][0]["streams"][0]
    assert (stars["how"], stars["state"]) == ("account", "on")


# --- the items route ------------------------------------------------------------------------------------------------------------


def _items(client, channel, **params):
    return client.get(f"/sources/channels/{channel}/items", params=params)


def test_the_items_route_narrows_to_a_stream_and_a_folder(client, bank, more_lists):
    _x_bank(bank)
    everything = _items(client, "x").json()
    assert everything["total"] == 3
    likes = _items(client, "x", stream="x.likes").json()
    assert {r["id"] for r in likes["items"]} == {"media-both", "media-like"} and likes["all"] == 2
    marks = _items(client, "x", stream="x.bookmarks").json()
    assert {r["id"] for r in marks["items"]} == {"media-both", "media-mark"}
    ideas = _items(client, "x", stream="x.bookmarks", folder="ideas").json()      # a folder, any case
    assert [r["id"] for r in ideas["items"]] == ["media-mark"] and ideas["all"] == 1
    assert _items(client, "x", folder="Reading").json()["total"] == 2
    assert _items(client, "x", stream="x.nope").status_code == 404
    assert _items(client, "x", stream="x.likes").headers["etag"] != _items(client, "x", stream="x.bookmarks").headers["etag"]


def test_a_post_first_kept_as_a_saved_link_is_on_the_list_that_later_saw_it(client, bank, more_lists):
    """A post kept first as a plain saved link, then seen on X's Bookmarks list, is counted once under that stream and
    listed by ``stream=``; another site's same-named list does not take it, nor does a browser folder of that name."""
    _x_bank(bank)
    before = _streams(bank, "x")["x.bookmarks"]["count"]
    _save(bank, "link", "https://x.com/alice_example/status/7", origin="saved-link", folder="", collections=["Bookmarks"])
    # The same words on a page of another site, and on a Chrome bookmark of X: neither is X's list.
    _save(bank, "elsewhere", "https://blog.bob-example.org/post/1", origin="saved-link", folder="", collections=["Bookmarks"])
    _save(bank, "folder", "https://x.com/alice_example/status/8", origin="chrome-bookmark", folder="Bookmarks")
    x = _streams(bank, "x")
    assert x["x.bookmarks"]["count"] == before + 1 and x["x.likes"]["count"] == 2
    shown = _items(client, "x", stream="x.bookmarks").json()
    assert "media-link" in {r["id"] for r in shown["items"]} and shown["all"] == before + 1   # the list shows what the count says
    assert "media-elsewhere" not in {r["id"] for r in shown["items"]} and "media-folder" not in {r["id"] for r in shown["items"]}
    row = next(r for r in shown["items"] if r["id"] == "media-link")
    assert row["lists"] == ["Bookmarks"] and row["depth"] == "kept"
    assert all(r["id"] != "media-link" for r in _items(client, "x", stream="x.likes").json()["items"])


def test_a_saved_link_on_one_sites_list_is_not_another_sites_same_named_list(bank):
    # Instagram's list and Pinterest's are both called "Saved": the page's own site says which.
    _save(bank, "pin", "https://www.pinterest.com/pin/1/", origin="saved-link", folder="", collections=["Saved"])
    assert _streams(bank, "pinterest")["pinterest.saved"]["count"] == 1
    assert _streams(bank, "instagram")["instagram.saved"]["count"] in (0, None)


def test_the_list_display_names_are_built_once_a_request_not_once_a_row(client, bank, more_lists, monkeypatch):
    _x_bank(bank)
    for i in range(5):
        _save(bank, f"extra{i}", f"https://x.com/alice_example/status/6{i}", origin="x-bookmarks", folder="Bookmarks")
    calls = []
    real = source_streams._list_display_names
    monkeypatch.setattr(source_streams, "_list_display_names", lambda: calls.append(1) or real())
    body = _items(client, "x").json()
    assert body["total"] >= 8 and all("lists" in r for r in body["items"])
    assert len(calls) == 1


def test_a_saved_list_row_says_its_lists_folders_depth_and_post_day(client, bank, more_lists):
    _x_bank(bank)
    _save(bank, "seen", "https://x.com/alice_example/status/9", origin="x-bookmarks", folder="Bookmarks", read=True)
    rows = {r["id"]: r for r in _items(client, "x").json()["items"]}
    both, mark = rows["media-both"], rows["media-mark"]
    assert both["lists"] == ["Bookmarks", "Likes"] and both["folders"] == ["Reading"] and both["depth"] == "kept"
    assert "posted" not in both
    assert mark["lists"] == ["Bookmarks"] and mark["folders"] == ["Reading", "Ideas"] and mark["posted"] == "2026-10-30"
    assert mark["day"] == "2026-11-02"                              # the row's own day stays "kept on"
    assert rows["media-seen"]["depth"] == "read"


def test_an_agent_that_read_or_watched_a_link_makes_its_row_read(client, bank, more_lists):
    url = "https://x.com/alice_example/status/7"
    _save(bank, "agent", url, origin="x-bookmarks", folder="Bookmarks")
    _write(bank / "episodes" / "ep_2026-11-05_001.md", {"id": "ep_2026-11-05_001", "source": "page-read", "url": url,
                                                         "timestamp": "2026-11-05T08:00:00+00:00", "processed": True})
    [row] = _items(client, "x").json()["items"]
    assert row["depth"] == "read"


def test_rows_that_are_not_saved_list_posts_gain_no_list_fields(client, bank, more_lists):
    _write(bank / "entities" / "media-one.md", {"id": "media-one", "type": "media", "name": "One", "status": "active",
                                                 "origin": "chrome-bookmark", "folder": "Bar", "created": "2026-09-01"})
    _json(bank, "sources/url_index.json", {"h": {"media_entity_id": "media-one", "title": "One",
                                                  "url": "https://example.com/1", "saved_at": "2026-09-01T10:00:00+00:00"}})
    _json(bank, "sources/bookmark_seen.json", {"chrome-bookmarks": {"folders": None, "hashes": ["h"],
                                                                    "at": "2026-09-08T00:00:00Z"}})
    [row] = _items(client, "chrome-bookmarks").json()["items"]
    assert not ({"lists", "folders", "depth", "posted"} & set(row))


def test_a_stream_that_is_the_whole_channel_keeps_every_row(client, bank, more_lists):
    _x_bank(bank)
    assert _items(client, "x", stream="x.saves-you-make").json()["total"] == 3


def test_the_folder_parameter_is_never_logged():
    assert "folder" in main._REDACTED_PARAMS
    assert main._redacts("/sources/channels/x/items", "stream=x.bookmarks&folder=Ideas")


def test_the_items_shape_was_bumped():
    assert channel_items.SHAPE == "g161-25"
