"""marks-2 (owner 2026-10-20) — site marks that actually appear, and YouTube saves that show their stills.

"None of the YouTube stuff shows thumbnails, just low-res YouTube logos" and "I don't like, app-wide, when we show a
picture that has a letter when we can get something specific to the site." What the API does about it: a saved
YouTube video's row says it is a video and its still is served by the page's id (the watched-video fetch and cache,
that id only, behind the picture gate); a saved source's faces put sites whose icon is already cached first, and the
overview's ETag moves when an icon lands. Synthetic banks, placeholder names; nothing is fetched (the gate is off in
the suite, and every fetch here is injected).
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import bank_index, channel_items, logo_service, media_ingestor, media_preview, source_overview

VID = "abcDEF12345"
YT = f"https://www.youtube.com/watch?v={VID}"


def _page(bank, entity_id, **fm):
    path = bank / "entities" / f"{entity_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["---", *(f"{k}: {json.dumps(v)}" for k, v in {"id": entity_id, "status": "active", **fm}.items()),
             "---", "", "page"]
    path.write_text("\n".join(lines), encoding="utf-8")


@pytest.fixture
def bank(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "cicada-home"))
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


def _hit(bank, site):
    own = logo_service.own_site_bank(logo_service.bank_name(bank))
    (logo_service.logos_dir(own) / f"{site}.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    import asyncio
    from datetime import datetime, timezone

    asyncio.run(logo_service._record_meta(own, site, {"fetched_at": datetime.now(timezone.utc).isoformat(),
                                                      "miss": False, "etag": None, "ext": "png",
                                                      "v": logo_service.OWN_SITE_DISCOVERY}))


def _overview_row(bank, key="chrome-bookmarks", count=4):
    bank_index.invalidate()
    rows = {r["id"]: r for r in source_overview.build_overview(bank, channels=[{"id": key, "count": count,
                                                                                 "connected": True}])}
    return rows[key]


# --- the faces ----------------------------------------------------------------------------------------------------


def test_faces_put_sites_with_a_cached_icon_first_then_the_rest_newest_first(bank):
    for i, (host, day) in enumerate([("site-a.zz", "01"), ("site-b.zz", "02"), ("site-c.zz", "03"),
                                     ("site-d.zz", "04")]):
        _page(bank, f"media-{i}", type="media", origin="chrome-bookmark", name=f"Saved {i}",
              url=f"https://{host}/p/{i}", created=f"2026-10-{day}")
    assert [f["site"] for f in _overview_row(bank)["faces"]] == ["site-d.zz", "site-c.zz", "site-b.zz"]
    _hit(bank, "site-a.zz")
    row = _overview_row(bank)
    assert [f["site"] for f in row["faces"]] == ["site-a.zz", "site-d.zz", "site-c.zz"], \
        "the oldest site leads once its icon is known; the rest stay newest first"
    assert row["faces_more"] == 1


def test_an_icon_landing_moves_the_site_icons_component(bank):
    """Security review of #387: the overview's ETag rides a sync component the app maps (`siteIcons` →
    `.sourcesOverview`), never a bare extra the SSE stream cannot see."""
    from api.services import sync_service

    before = sync_service.components(bank)["siteIcons"]
    _hit(bank, "site-a.zz")
    after = sync_service.components(bank)["siteIcons"]
    assert after != before
    assert sync_service.components(bank)["logos"] == sync_service.components(bank)["logos"], "logos is untouched"


def test_the_overview_etag_moves_when_an_icon_lands(client, bank):
    _page(bank, "media-0", type="media", origin="chrome-bookmark", name="Saved", url="https://site-a.zz/p",
          created="2026-10-01")
    bank_index.invalidate()
    before = client.get("/sources/overview").headers["etag"]
    _hit(bank, "site-a.zz")
    assert client.get("/sources/overview").headers["etag"] != before


# --- a saved YouTube video's still ---------------------------------------------------------------------------------


def _index(bank, entries):
    (bank / "sources" / "url_index.json").write_text(json.dumps(
        {media_ingestor.url_hash(u): {"media_entity_id": e, "url": u, "title": e} for u, e in entries.items()}))


def test_a_saved_youtube_row_says_video_and_others_do_not(bank):
    _page(bank, "media-v", type="media", origin="chrome-bookmark", name="A video", url=YT, created="2026-10-02")
    _page(bank, "media-p", type="media", origin="chrome-bookmark", name="A page", url="https://site-a.zz/p",
          created="2026-10-01")
    _index(bank, {YT: "media-v", "https://site-a.zz/p": "media-p"})
    bank_index.invalidate()
    page = channel_items.items(bank, "chrome-bookmarks")
    rows = {r["id"]: r for r in page["items"]}
    assert rows["media-v"].get("video") is True
    assert "video" not in rows["media-p"]
    assert VID not in json.dumps(page), "the id never rides the list; the still is asked by the page's id"


def test_the_video_id_comes_from_the_pages_own_url_only(bank):
    _page(bank, "media-v", type="media", origin="youtube-playlist", name="A video", url=YT)
    _page(bank, "media-p", type="media", name="A page", url="https://site-a.zz/p")
    _page(bank, "media-gone", type="media", name="Gone", url=YT, status="archived")
    _page(bank, "concept-x", type="concept", name="Not media", url=YT)
    _page(bank, "media-rss", type="media", origin="rss", name="A captured video", url=YT)
    bank_index.invalidate()
    assert channel_items.media_video_id(bank, "media-rss") is None, "only a saved link's page (security review of #387)"
    assert channel_items.media_video_id(bank, "media-v") == VID
    assert channel_items.media_video_id(bank, "media-p") is None
    assert channel_items.media_video_id(bank, "media-gone") is None, "a page the lists hide asks nothing"
    assert channel_items.media_video_id(bank, "concept-x") is None
    assert channel_items.media_video_id(bank, "../../etc/passwd") is None


def test_the_still_route_asks_the_watched_video_store_by_the_pages_id(client, bank, monkeypatch, tmp_path):
    _page(bank, "media-v", type="media", origin="youtube-playlist", name="A video", url=YT)
    _page(bank, "media-p", type="media", name="A page", url="https://site-a.zz/p")
    bank_index.invalidate()
    # The suite runs with the picture gate off: a video page asks nothing and stores nothing.
    assert client.get("/sources/saved/media-v/still").status_code == 404
    assert not media_preview._watched_root("memory").exists()
    asked: list[str] = []
    still = tmp_path / "still.jpg"
    still.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 32)

    async def fake(memory_path, video_id, **_):
        asked.append(video_id)
        return still

    monkeypatch.setattr(media_preview, "ensure_video_still", fake)
    got = client.get("/sources/saved/media-v/still")
    assert got.status_code == 200 and got.headers["content-type"] == "image/jpeg" and asked == [VID]
    assert client.get("/sources/saved/media-v/still", headers={"If-None-Match": got.headers["etag"]}).status_code == 304
    assert client.get("/sources/saved/media-p/still").status_code == 404
    assert client.get("/sources/saved/nope/still").status_code == 404
    assert asked == [VID, VID], "a page that is no video never reaches the store"
