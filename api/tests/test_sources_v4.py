"""Sources v4 (owner 2026-10-19) — what the API serves so a source says what it is once: the per-source waiting count,
the faces on a row (the chats that fed Messages, the sites saved things came from), Messages rows by chat, a watched
day's videos and their stills, and check records that are never a source.

Every test builds a synthetic bank under tmp_path with placeholder names; nothing real is read and nothing is fetched.
"""

from __future__ import annotations

import asyncio
import base64
import json
import struct

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import (
    bank_index,
    channel_items,
    check_record,
    media_ingestor,
    media_preview,
    messages_photos,
    messages_source,
    source_overview,
    web_settle,
)

CHAT_A = "a" * 32
CHAT_B = "b" * 32
CHAT_C = "c" * 32
CHAT_D = "d" * 32
VID_1 = "abcDEF12345"
VID_2 = "zyx-_987654"


def _write(path, fm: dict, body: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["---", *(f"{k}: {json.dumps(v)}" for k, v in fm.items()), "---", "", body]
    path.write_text("\n".join(lines), encoding="utf-8")


def _episode(bank, ep_id, **fm):
    _write(bank / "episodes" / f"{ep_id}.md", {"id": ep_id, "processed": True, **fm}, "body")


def _page(bank, entity_id, **fm):
    _write(bank / "entities" / f"{entity_id}.md", {"id": entity_id, "status": "active", **fm}, "page")


def _png(tag: bytes = b"\x00") -> bytes:
    ihdr = struct.pack(">II", 128, 128) + b"\x08\x06\x00\x00\x00"
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + ihdr + tag * 4 + b"\x00\x00\x00\x00IEND\xaeB`\x82"


def _sitting(bank, ep_id, cid, name, last, **extra):
    _episode(bank, ep_id, origin="imessage", source="imessage", conversation=cid, title=f"Messages with {name} · {last[:10]}",
             timestamp=last, original_date=last[:10], sitting_last_at=last,
             correspondent={"name": name, "kind": "person", "decided_by": "person"}, **extra)


def _day(bank, ep_id, day, rows, **extra):
    _episode(bank, ep_id, origin="youtube-history", source="watch-history", source_id=f"watch-history:youtube:{day}",
             title=f"Watched on YouTube · {day}", timestamp=f"{day}T20:00:00+00:00", original_date=day,
             watched_on=day, platform="youtube", videos=len(rows), watched=rows, processed_by="index", **extra)


@pytest.fixture
def home(tmp_path, monkeypatch):
    path = tmp_path / "cicada-home"
    monkeypatch.setenv("CICADA_HOME", str(path))
    messages_photos._MEMO.clear()
    return path


@pytest.fixture
def bank(tmp_path, home):
    b = tmp_path / "memory"
    for sub in ("episodes", "entities", "sources"):
        (b / sub).mkdir(parents=True)
    bank_index.invalidate()
    return b


@pytest.fixture
def client(bank, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    yield TestClient(main.app)
    config.get_settings.cache_clear()


def _rows(bank, channels=()) -> dict[str, dict]:
    bank_index.invalidate()
    return {r["id"]: r for r in source_overview.build_overview(bank, channels=list(channels))}


# --- check records are never a source --------------------------------------------------------------------------------


def test_the_check_record_constants_are_the_writers_own():
    assert source_overview.CHECK_RECORD_SOURCES == {web_settle.SOURCE, check_record.SOURCE}


def test_a_check_sleep_settled_is_not_a_source_called_sleep(bank):
    """The owner's "Sleep is also a source … '1 capture' and is empty": Sleep's web check wrote `origin: sleep`."""
    _episode(bank, "ep_2026-10-19_001", source="web-check", origin="sleep", title="Web check: alpha-project",
             timestamp="2026-10-19T08:00:00+00:00")
    _episode(bank, "ep_2026-10-19_002", source="web-check", origin="mcp", session_id="s-1",
             title="Web check: beta", timestamp="2026-10-19T09:00:00+00:00")
    _episode(bank, "ep_2026-10-19_003", source="source-check", origin="mcp", session_id="s-2",
             title="Check: gamma", timestamp="2026-10-19T09:30:00+00:00")
    _episode(bank, "ep_2026-10-19_004", origin="claude-code", session_id="s-3", harness="claude-code",
             timestamp="2026-10-19T10:00:00+00:00")
    rows = _rows(bank)
    assert "origin:sleep" not in rows
    assert "harness:unknown" not in rows, "an agent's check alone is no conversation"
    assert rows["harness:claude-code"]["episodes"] == 1


# --- waiting, per source ---------------------------------------------------------------------------------------------


def test_each_source_says_how_many_of_its_episodes_wait_for_sleep(bank):
    _episode(bank, "ep_2026-10-19_001", origin="apple-notes", processed=False, timestamp="2026-10-19T08:00:00+00:00")
    _episode(bank, "ep_2026-10-19_002", origin="apple-notes", processed=False, timestamp="2026-10-19T08:01:00+00:00")
    _episode(bank, "ep_2026-10-19_003", origin="apple-notes", timestamp="2026-10-19T08:02:00+00:00")
    # A watched day is indexed, never read by a model: it never waits (ruling 30, 2026-10-18).
    _day(bank, "ep_2026-10-19_004", "2026-10-19", [], processed=False)
    rows = _rows(bank)
    assert rows["notes"]["waiting"] == 2
    assert rows["youtube-history"]["waiting"] == 0


# --- faces -----------------------------------------------------------------------------------------------------------


def test_messages_carries_the_three_newest_chats_and_how_many_more(bank):
    _sitting(bank, "ep_2026-10-15_001", CHAT_A, "Alice Example", "2026-10-15T10:00:00+00:00")
    _sitting(bank, "ep_2026-10-16_001", CHAT_B, "Bob Example", "2026-10-16T10:00:00+00:00")
    _sitting(bank, "ep_2026-10-17_001", CHAT_C, "Carol Example", "2026-10-17T10:00:00+00:00")
    _sitting(bank, "ep_2026-10-18_001", CHAT_D, "Dave Example", "2026-10-18T10:00:00+00:00")
    _sitting(bank, "ep_2026-10-19_001", CHAT_A, "Alice Example", "2026-10-19T10:00:00+00:00")
    row = _rows(bank)["imessage"]
    assert [f["id"] for f in row["faces"]] == [CHAT_A, CHAT_D, CHAT_C], "newest sitting first, one face per chat"
    assert [f["label"] for f in row["faces"]][0] == "Alice Example"
    assert all(f["kind"] == "chat" and f["photo"] is None for f in row["faces"])
    assert row["faces_more"] == 1


def test_a_ticked_chat_that_shares_a_photo_gives_its_face_the_photo(bank):
    _sitting(bank, "ep_2026-10-19_001", CHAT_A, "Alice Example", "2026-10-19T10:00:00+00:00")
    messages_source.update_settings(bank, conversation={"id": CHAT_A, "name": "Alice Example", "ticked": True})
    messages_photos.store(bank, [{"conversation": CHAT_A, "photo_b64": base64.b64encode(_png()).decode()}])
    face = _rows(bank)["imessage"]["faces"][0]
    assert face["photo"] and len(face["photo"]) == 12


def test_a_saved_source_carries_the_sites_its_things_came_from(bank):
    for i, (host, day) in enumerate([("example.com", "01"), ("example.org", "02"), ("example.net", "03"),
                                     ("example.com", "04"), ("example.edu", "05")]):
        _page(bank, f"media-{i}", type="media", origin="chrome-bookmark", name=f"Saved {i}",
              url=f"https://www.{host}/p/{i}", created=f"2026-10-{day}")
    _page(bank, "media-hidden", type="media", origin="chrome-bookmark", name="Hidden", status="archived",
          url="https://hidden.example/p", created="2026-10-09")
    row = _rows(bank, [{"id": "chrome-bookmarks", "count": 5, "connected": True}])["chrome-bookmarks"]
    assert [f["label"] for f in row["faces"]] == ["example.edu", "example.com", "example.net"]
    assert row["faces"][1]["id"] == "media-3", "a site's face is its newest saved page"
    assert all(f["kind"] == "site" and f["site"] for f in row["faces"])
    assert row["faces_more"] == 1, "example.org; a hidden page is no face"
    assert not any("url" in f or "/p/" in json.dumps(f) for f in row["faces"]), "never the URL"


def test_the_overview_route_serves_the_new_fields(client, bank):
    _sitting(bank, "ep_2026-10-19_001", CHAT_A, "Alice Example", "2026-10-19T10:00:00+00:00", processed=False)
    bank_index.invalidate()
    rows = {r["id"]: r for r in client.get("/sources/overview").json()["sources"]}
    assert rows["imessage"]["waiting"] == 1
    assert rows["imessage"]["faces"][0] == {"kind": "chat", "id": CHAT_A, "label": "Alice Example",
                                            "site": None, "photo": None}
    assert rows["imessage"]["facesMore"] == 0


# --- the chat photo route -------------------------------------------------------------------------------------------


def test_the_chat_photo_route_serves_only_a_ticked_chats_stored_photo(client, bank):
    assert client.get(f"/sources/messages/chats/{CHAT_A}/photo").status_code == 404
    assert client.get("/sources/messages/chats/not-a-hash/photo").status_code == 404
    messages_source.update_settings(bank, conversation={"id": CHAT_A, "name": "Alice Example", "ticked": True})
    assert client.get(f"/sources/messages/chats/{CHAT_A}/photo").status_code == 404, "ticked, but no photo"
    data = _png()
    messages_photos.store(bank, [{"conversation": CHAT_A, "photo_b64": base64.b64encode(data).decode()}])
    r = client.get(f"/sources/messages/chats/{CHAT_A}/photo")
    assert r.status_code == 200 and r.content == data and r.headers["content-type"] == "image/png"
    assert client.get(f"/sources/messages/chats/{CHAT_A}/photo",
                      headers={"If-None-Match": r.headers["etag"]}).status_code == 304
    messages_source.update_settings(bank, conversation={"id": CHAT_A, "ticked": False})
    messages_photos.forget(bank, CHAT_A)
    assert client.get(f"/sources/messages/chats/{CHAT_A}/photo").status_code == 404


# --- lists -----------------------------------------------------------------------------------------------------------


def test_messages_rows_are_titled_by_the_chat_and_say_their_day_once(bank):
    _sitting(bank, "ep_2026-10-19_001", CHAT_A, "Alice Example", "2026-10-19T10:00:00+00:00")
    rows = channel_items.items(bank, "imessage")["items"]
    assert rows[0]["title"] == "Alice Example" and rows[0]["day"] == "2026-10-19"
    assert rows[0]["chat"] == {"id": CHAT_A, "label": "Alice Example", "photo": None}


def test_a_title_drops_the_day_its_row_already_shows():
    assert channel_items._without_day("Watched on YouTube · 2026-10-19", "2026-10-19") == "Watched on YouTube"
    assert channel_items._without_day("Plan · 2026-10-18", "2026-10-19") == "Plan · 2026-10-18", "another day stays"
    assert channel_items._without_day("2026-10-19", "2026-10-19") == "2026-10-19", "never an empty title"


def _watch(url, title, *times, channel="A channel"):
    return {"url": url, "title": title, "channel": channel, "times": list(times), "via": ["chrome"], "seen": list(times)}


def test_history_lists_days_with_their_video_count_and_never_the_month_summary(bank):
    _day(bank, "ep_2026-10-18_001", "2026-10-18", [_watch(f"https://www.youtube.com/watch?v={VID_1}", "One",
                                                          "2026-10-18T19:00:00+00:00")])
    _day(bank, "ep_2026-10-19_001", "2026-10-19", [
        _watch(f"https://www.youtube.com/watch?v={VID_1}", "One", "2026-10-19T08:00:00+00:00"),
        _watch(f"https://www.youtube.com/watch?v={VID_2}", "Two", "2026-10-19T09:00:00+00:00")])
    _episode(bank, "ep_2026-10-19_002", origin="youtube-history", source="watch-history-month",
             source_id="watch-history-month:youtube:2026-10", title="Watched on YouTube · October 2026",
             timestamp="2026-10-19T21:00:00+00:00")
    page = channel_items.items(bank, "youtube-history")
    assert page["total"] == 2
    assert [(r["id"], r["videos"], r["title"]) for r in page["items"]] == [
        ("ep_2026-10-19_001", 2, "Watched on YouTube"), ("ep_2026-10-18_001", 1, "Watched on YouTube")]


def test_a_watched_day_opens_to_its_videos(client, bank):
    _day(bank, "ep_2026-10-19_001", "2026-10-19", [
        _watch(f"https://www.youtube.com/watch?v={VID_1}", "One", "2026-10-19T08:00:00+00:00",
               "2026-10-19T12:00:00+00:00"),
        _watch(f"https://www.youtube.com/watch?v={VID_2}", "Two", "2026-10-19T09:00:00+00:00")])
    # The second video is also saved (Watch later): a click lands where a saved item opens.
    _page(bank, "media-two", type="media", origin="youtube-playlist", name="Two")
    url = f"https://www.youtube.com/watch?v={VID_2}"
    (bank / "sources" / "url_index.json").write_text(json.dumps({
        media_ingestor.url_hash(url): {"media_entity_id": "media-two", "url": url, "title": "Two"}}))
    bank_index.invalidate()
    day = channel_items.watched_day(bank, "ep_2026-10-19_001")
    assert day["day"] == "2026-10-19" and day["platform"] == "youtube"
    one, two = day["videos"]
    assert (one["title"], one["video_id"], len(one["times"]), one["media_entity_id"]) == ("One", VID_1, 2, None)
    assert (two["video_id"], two["media_entity_id"]) == (VID_2, "media-two")
    r = client.get("/sources/watch-history/days/ep_2026-10-19_001")
    assert r.status_code == 200 and r.json()["videos"][0]["videoId"] == VID_1
    assert client.get("/sources/watch-history/days/ep_2026-10-19_001",
                      headers={"If-None-Match": r.headers["etag"]}).status_code == 304
    _episode(bank, "ep_2026-10-19_009", origin="apple-notes", timestamp="2026-10-19T08:00:00+00:00")
    bank_index.invalidate()
    assert client.get("/sources/watch-history/days/ep_2026-10-19_009").status_code == 404, "not a watched day"


# --- a watched video's still ----------------------------------------------------------------------------------------


def test_a_still_is_asked_only_for_a_video_the_bank_records(client, bank):
    _day(bank, "ep_2026-10-19_001", "2026-10-19", [
        _watch(f"https://www.youtube.com/watch?v={VID_1}", "One", "2026-10-19T08:00:00+00:00")])
    bank_index.invalidate()
    assert channel_items.watched_video_id(bank, VID_1)
    assert not channel_items.watched_video_id(bank, VID_2), "an id the request merely names"
    assert not channel_items.watched_video_id(bank, "../../etc"), "never a path"
    assert client.get(f"/sources/watch-history/videos/{VID_2}/thumbnail").status_code == 404
    # The suite runs with the picture-fetch gate off: a known id asks nothing and draws no picture.
    assert client.get(f"/sources/watch-history/videos/{VID_1}/thumbnail").status_code == 404
    assert not (media_preview._watched_root("memory")).exists(), "a gated-off ask stores nothing, not even a miss"


def test_a_still_is_fetched_once_from_youtubes_own_host_and_a_miss_is_remembered(bank, monkeypatch):
    asyncio.run(_still_once(bank, monkeypatch))


async def _still_once(bank, monkeypatch):
    monkeypatch.setattr(media_preview.net_guard, "is_fetchable_url_async", _always_ok)
    asked: list[str] = []
    jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 64

    async def fetcher(url):
        asked.append(url)
        return media_preview.Fetched(status=200, body=jpeg, content_type="image/jpeg")

    path = await media_preview.ensure_video_still(bank, VID_1, fetcher=fetcher)
    assert path is not None and path.read_bytes() == jpeg and path.suffix == ".jpg"
    assert asked == [f"https://i.ytimg.com/vi/{VID_1}/hqdefault.jpg"]
    assert await media_preview.ensure_video_still(bank, VID_1, fetcher=fetcher) == path
    assert len(asked) == 1, "fetched once, then served from the store"

    async def blocked(url):
        asked.append(url)
        return media_preview.Fetched(status=403, body=b"")

    assert await media_preview.ensure_video_still(bank, VID_2, fetcher=blocked) is None
    assert await media_preview.ensure_video_still(bank, VID_2, fetcher=blocked) is None
    assert asked.count(f"https://i.ytimg.com/vi/{VID_2}/hqdefault.jpg") == 1, "a wall is a miss, never retried"
    assert not any(p.is_relative_to(bank) for p in (path,)), "cached outside every bank"


async def _always_ok(url):
    return True
