"""G232 (owner 2026-11-04): the ways into Cicada for Spotify, Reddit, Pinterest, TikTok and Instagram.

* Connect Reddit — Cicada's own installed app: a browser sign-in with no client secret (the client id and an empty
  password), a refresh token renewed the same way, Disconnect revoking at Reddit; offered only while the build carries
  a client id. Reads saved, upvoted and joined communities; the last two index-only (ruling 30).
* Read through your browser — the saved-list machinery (G206) for Reddit, Pinterest and TikTok; Spotify since ROR-128.
* Import a file — Reddit's votes and joined communities, Spotify's playlists.
* ``GET /sources/ways-in`` — what the standard source page's connect area shows.

ZERO NETWORK: a fake Reddit throughout. Every account, community and id is a placeholder.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import time
import zipfile
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from _reading_fixtures import reading  # noqa: F401 — `reading` is a fixture
from api import config, main
from api.routers import connectors as connectors_router
from api.services import (history_index, markdown_parser, media_ingestor, reading_settings, saved_exports,
                          saved_lists, spotify_export, sync_state, ways_in)
from api.services.connections import secrets
from api.services.connectors import reddit

CID = "app-client-id-placeholder"
ALL_NAMES = (*reddit.SECRET_NAMES, reddit.APP_CLIENT_ID_ENV, reddit.REDIRECT_URI_ENV)


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    for name in ALL_NAMES:
        monkeypatch.delenv(name, raising=False)
    connectors_router._pending_states.clear()
    yield
    for name in ALL_NAMES:
        os.environ.pop(name, None)
    connectors_router._pending_states.clear()


@pytest.fixture
def memory(tmp_path, monkeypatch):
    root = tmp_path / "memory"
    for sub in ("episodes", "entities", "sources"):
        (root / sub).mkdir(parents=True, exist_ok=True)

    async def offline(url, client, from_bookmark_file=False):
        return media_ingestor.MediaMeta(title=media_ingestor._fallback_title(url), description="",
                                        site=media_ingestor._site_of(url), media_type="url")

    async def no_commit(memory_path, count, paths=None):
        return None

    monkeypatch.setattr(media_ingestor, "enrich", offline)
    monkeypatch.setattr(media_ingestor, "_commit_media", no_commit)
    return root


@pytest.fixture
def api(memory, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    yield TestClient(main.app)
    config.get_settings.cache_clear()


def _post(name, title, *, sub="example", url=""):
    return {"kind": "t3", "data": {"name": name, "title": title, "subreddit": sub, "is_self": not url, "url": url,
                                   "permalink": f"/r/{sub}/comments/{name[3:]}/a_post/"}}


def _listing(*children):
    return {"kind": "Listing", "data": {"after": None, "children": list(children)}}


class FakeReddit:
    """Reddit's sign-in endpoints and the three listings, recording every request."""

    def __init__(self, *, refresh_error=None):
        self.calls: list[dict] = []
        self.refresh_error = refresh_error
        self.saved = _listing(_post("t3_aaa111", "A saved self post"))
        self.upvoted = _listing(_post("t3_bbb222", "An upvoted link", url="https://example.com/upvoted"))
        self.subscriber = _listing({"kind": "t5", "data": {"name": "t5_x", "display_name": "example_sub"}},
                                   {"kind": "t5", "data": {"name": "t5_y", "display_name": "u_someone"}})

    async def __call__(self, method, url, *, headers=None, params=None, data=None, auth=None):
        self.calls.append({"method": method, "url": url, "headers": dict(headers or {}), "data": dict(data or {}),
                           "auth": auth})
        if url == reddit.TOKEN_URL:
            grant = (data or {}).get("grant_type")
            if grant == "refresh_token" and self.refresh_error:
                return {"error": self.refresh_error}
            out = {"access_token": f"access-{grant}", "token_type": "bearer", "expires_in": 3600}
            if grant == "authorization_code":
                out["refresh_token"] = "refresh-placeholder"
            return out
        if url == reddit.REVOKE_URL:
            return {}
        if url.endswith("/api/v1/me"):
            return {"name": "example_user"}
        key = url.rstrip("/").rsplit("/", 1)[-1]
        return getattr(self, key)


# --- Connect Reddit --------------------------------------------------------------------------------------------------


def test_connect_reddit_is_offered_only_while_the_build_carries_a_client_id(api):
    assert not reddit.app_available()
    assert api.post("/sources/connectors/reddit/authorize").status_code == 400
    from api.services import auth

    assert "/sources/connectors/reddit/callback" not in auth._OPEN_PATHS
    os.environ[reddit.APP_CLIENT_ID_ENV] = CID
    assert reddit.app_available()
    assert "/sources/connectors/reddit/callback" in auth._OPEN_PATHS
    resp = api.post("/sources/connectors/reddit/authorize")
    assert resp.status_code == 200, resp.text
    q = parse_qs(urlparse(resp.json()["authorizeUrl"]).query)
    assert q["client_id"] == [CID] and q["duration"] == ["permanent"] and q["response_type"] == ["code"]
    assert q["scope"] == ["identity history mysubreddits"]
    assert q["redirect_uri"] == ["http://127.0.0.1:8000/sources/connectors/reddit/callback"]
    status = api.get("/sources/connectors/reddit").json()
    assert status["appSignIn"] is True and status["connected"] is False


def test_connect_reddit_off_its_registered_address_says_so_in_words(api, monkeypatch):
    os.environ[reddit.APP_CLIENT_ID_ENV] = CID
    monkeypatch.setenv("CICADA_PORT", "8123")
    config.get_settings.cache_clear()
    resp = api.post("/sources/connectors/reddit/authorize")
    assert resp.status_code == 422 and "127.0.0.1:8000" in resp.json()["detail"]


def test_the_code_is_exchanged_with_no_secret_and_replaces_the_persons_own_app():
    os.environ[reddit.APP_CLIENT_ID_ENV] = CID
    for f in reddit.FIELDS:
        secrets.set_secret(f["name"], "placeholder-value")
    fake = FakeReddit()
    run(reddit.exchange_code("code-placeholder", state="s", http_fn=fake))
    token_call = fake.calls[0]
    assert token_call["auth"] == (CID, ""), "an installed app has no secret: the client id and an empty password"
    assert token_call["data"]["grant_type"] == "authorization_code"
    assert "client_secret" not in str(token_call)
    assert reddit.how() == "app" and reddit.is_connected()
    values = secrets.load_secrets()
    assert values[reddit.ACCOUNT_ENV] == "example_user" and values[reddit.REFRESH_ENV] == "refresh-placeholder"
    assert not any(secrets.has_secret(f["name"]) for f in reddit.FIELDS), "one way connected at a time"


def test_a_sync_reads_saves_upvotes_and_communities_and_files_the_last_two_index_only(memory):
    os.environ[reddit.APP_CLIENT_ID_ENV] = CID
    fake = FakeReddit()
    run(reddit.exchange_code("code", http_fn=fake))
    result = run(reddit.sync(memory, http_fn=fake))
    assert result["status"] == "ok" and result["new"] == 3, result
    listed = [c["url"] for c in fake.calls if c["method"] == "GET"]
    assert f"{reddit.API_BASE}/user/example_user/saved" in listed
    assert f"{reddit.API_BASE}/user/example_user/upvoted" in listed
    assert f"{reddit.API_BASE}/subreddits/mine/subscriber" in listed
    assert all(c["url"].startswith(("https://oauth.reddit.com/", "https://www.reddit.com/api/v1/")) for c in fake.calls)
    kinds = {}
    for path in (memory / "episodes").glob("*.md"):
        fm = markdown_parser.parse(path).frontmatter
        kinds[fm["folder"]] = history_index.kind(fm)
    assert kinds == {"r/example": "saved", "Upvoted": "list", "Joined communities": "list"}, \
        "a bare save is indexed (ruling 62); an upvote and a community are index-only (ruling 30)"
    pages = [markdown_parser.parse(p).frontmatter for p in (memory / "entities").glob("*.md")]
    assert not any("u_someone" in json.dumps(p) for p in pages), "a person's profile is never a community"
    state = sync_state.read_sync_state(memory)["reddit"]
    assert state["last_seen"] == "t3_aaa111" and state["last_upvoted"] == "t3_bbb222"


def test_a_lapsed_token_is_renewed_with_the_client_id_alone():
    os.environ[reddit.APP_CLIENT_ID_ENV] = CID
    fake = FakeReddit()
    run(reddit.exchange_code("code", http_fn=fake))
    secrets.set_secret(reddit.EXPIRES_ENV, str(int(time.time()) - 10))
    token = run(reddit.fetch_token(http_fn=fake))
    refresh = fake.calls[-1]
    assert token == "access-refresh_token"
    assert refresh["auth"] == (CID, "") and refresh["data"]["refresh_token"] == "refresh-placeholder"


def test_a_refused_renewal_asks_to_connect_again_in_words(memory):
    os.environ[reddit.APP_CLIENT_ID_ENV] = CID
    fake = FakeReddit(refresh_error="invalid_grant")
    run(reddit.exchange_code("code", http_fn=fake))
    secrets.set_secret(reddit.EXPIRES_ENV, "1")
    result = run(reddit.sync(memory, http_fn=fake))
    assert result["status"] == "error" and "Connect Reddit again" in result["error"]
    assert reddit.needs_reconnect() and not reddit.is_connected()
    assert ways_in.describe("reddit", memory)["primary"]["action"] == "reconnect"


def test_disconnect_revokes_at_reddit_then_forgets_everything(api, monkeypatch):
    os.environ[reddit.APP_CLIENT_ID_ENV] = CID
    fake = FakeReddit()
    run(reddit.exchange_code("code", http_fn=fake))
    run(reddit.revoke(http_fn=fake))
    revoke = fake.calls[-1]
    assert revoke["url"] == reddit.REVOKE_URL and revoke["auth"] == (CID, "")
    assert revoke["data"] == {"token": "refresh-placeholder", "token_type_hint": "refresh_token"}
    fake.calls.clear()
    monkeypatch.setattr(reddit.base, "default_http", fake)
    resp = api.delete("/sources/connectors/reddit/credentials")
    assert [c["url"] for c in fake.calls] == [reddit.REVOKE_URL], "the one click is Disconnect and revoke"
    assert resp.status_code == 200 and resp.json()["connected"] is False
    assert not any(secrets.has_secret(n) for n in reddit.SECRET_NAMES)


def test_the_persons_own_script_app_still_syncs(memory):
    for f, v in zip(reddit.FIELDS, ("id", "secret", "example_user", "pw")):
        secrets.set_secret(f["name"], v)
    assert reddit.how() == "own-app"
    fake = FakeReddit()
    result = run(reddit.sync(memory, http_fn=fake))
    assert result["status"] == "ok"
    assert fake.calls[0]["data"]["grant_type"] == "password"


def test_every_sign_in_secret_is_stripped_from_engine_children():
    from api.services.connections import base as connections_base

    assert set(reddit.SECRET_NAMES) <= set(connections_base.CONNECTOR_SECRET_ENV)


# --- Read through your browser ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("key,url,canonical", [
    ("reddit", "https://old.reddit.com/r/example_sub/comments/abc123/a_title/?utm=1",
     "https://www.reddit.com/r/example_sub/comments/abc123/a_title/"),
    ("reddit", "https://www.reddit.com/r/example_sub/comments/abc123/a_title/def456/",
     "https://www.reddit.com/r/example_sub/comments/abc123/a_title/def456/"),
    ("pinterest", "https://uk.pinterest.co.uk/pin/123456789012/", "https://www.pinterest.com/pin/123456789012/"),
    ("tiktok", "https://www.tiktok.com/@carol.example/video/7100000000000000001?lang=en",
     "https://www.tiktok.com/@carol.example/video/7100000000000000001"),
])
def test_each_new_list_keeps_only_its_sites_posts(key, url, canonical):
    assert saved_lists.canonical(key, url)[0] == canonical
    assert saved_lists.canonical(key, "https://www.reddit.com/r/example_sub/") is None
    assert saved_lists.canonical(key, "https://example.com/pin/123456789012/") is None


def test_spotify_has_a_browser_list_since_ror_128():
    assert "spotify" in saved_lists.PLATFORMS and "spotify" in reading_settings.SAVED_LISTS
    assert ways_in.SOURCES["spotify"].browser == "spotify" and list(ways_in.SOURCES["spotify"].not_offered) == ["account"]


def test_a_tiktok_favorite_read_in_the_browser_is_the_exports_row_and_index_only(reading):
    server, memory = reading
    # The export brought this video in earlier, under its share link.
    idx = media_ingestor.load_url_index(memory)
    media_ingestor.write_prepared(media_ingestor.PreparedItem(media_ingestor.RawItem(
        url="https://www.tiktokv.com/share/video/7100000000000000001/", folder="Favorites", origin="tiktok-saved",
        defer_enrich=True), None), memory, idx)
    media_ingestor.save_url_index(memory, idx)
    reading_settings.update(saved_lists_={"tiktok": True})
    out = server.handle_tool("cicada_record_saved_list", {"platform": "tiktok", "outcome": "read", "items": [
        {"url": "https://www.tiktok.com/@carol.example/video/7100000000000000001", "author": "carol.example"},
        {"url": "https://www.tiktok.com/@carol.example/video/7100000000000000002", "text": "a placeholder caption"},
        {"url": "https://www.tiktok.com/@carol.example"}]})
    assert "1 new post(s) saved; 1 already in memory" in out and "1 row(s) were not TikTok posts" in out
    fms = [fm for fm in (markdown_parser.parse(p).frontmatter for p in (memory / "episodes").glob("*.md"))
           if fm.get("origin")]
    assert len(fms) == 2 and {fm["origin"] for fm in fms} == {"tiktok-saved"}
    assert all(history_index.kind(fm) == "list" for fm in fms)


def test_reddit_and_pinterest_lists_save_index_only(reading):
    server, memory = reading
    reading_settings.update(saved_lists_={"reddit": True, "pinterest": True})
    server.handle_tool("cicada_record_saved_list", {"platform": "reddit", "outcome": "read", "items": [
        {"url": "https://www.reddit.com/r/example_sub/comments/abc123/a_title/", "text": "A placeholder title"}]})
    server.handle_tool("cicada_record_saved_list", {"platform": "pinterest", "outcome": "read", "items": [
        {"url": "https://www.pinterest.com/pin/123456789012/", "text": "A placeholder pin"}]})
    fms = {fm["origin"]: fm for fm in (markdown_parser.parse(p).frontmatter for p in (memory / "episodes").glob("*.md"))
           if fm.get("origin")}
    assert fms["reddit-saved"]["folder"] == "Saved posts" and fms["pinterest-saved"]["folder"] == "Saved"
    assert all(history_index.kind(fm) == "list" for fm in fms.values())


def test_the_record_tool_schema_names_every_list(reading):
    stdio, _ = reading
    schema = next(t for t in stdio.TOOLS if t["name"] == "cicada_record_saved_list")["inputSchema"]
    assert schema["properties"]["platform"]["enum"] == list(saved_lists.PLATFORMS)


# --- Import a file ---------------------------------------------------------------------------------------------------


def _zip(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


VOTES = (b"id,permalink,direction\nabc1,https://www.reddit.com/r/example/comments/abc1/up/,up\n"
         b"abc2,https://www.reddit.com/r/example/comments/abc2/down/,down\n")
COMMUNITIES = b"subreddit\nexample_sub\nu_someone\n"


def test_reddits_export_brings_upvotes_and_communities_filed_as_the_connector_files_them():
    result = saved_exports.parse_archive(_zip({"export/post_votes.csv": VOTES,
                                               "export/subscribed_subreddits.csv": COMMUNITIES,
                                               "export/messages.csv": b"id,body\n1,never read\n"}))
    got = {(i.url, i.folder) for i in result.items}
    assert got == {("https://www.reddit.com/r/example/comments/abc1/up/", "Upvoted"),
                   ("https://www.reddit.com/r/example_sub/", "Joined communities")}, "downvotes and profiles never"
    assert result.platforms == ["reddit"] and result.skipped == 1


def test_a_votes_file_dropped_alone_is_never_read_as_saves():
    items, label, _ = media_ingestor.parse_upload(VOTES, "post_votes.csv")
    assert [(i.folder, i.url.endswith("/up/")) for i in items] == [("Upvoted", True)]


def test_spotifys_playlists_become_saved_items_dated_the_day_each_was_added():
    playlist = {"playlists": [{"name": "Morning  run", "description": "never read", "items": [
        {"track": {"trackName": "Track A", "artistName": "Artist A", "trackUri": "spotify:track:aaaaaaaaaaaaaaaaaaaaaa"},
         "episode": None, "localTrack": None, "addedDate": "2024-03-05"},
        {"episode": {"episodeName": "Episode B", "showName": "Show B",
                     "episodeUri": "spotify:episode:bbbbbbbbbbbbbbbbbbbbbb"}, "addedDate": "2024-03-06"},
        {"track": None, "localTrack": {"uri": "spotify:local:x"}}]}]}
    assert spotify_export.is_member("Spotify Account Data/Playlist1.json")
    result = saved_exports.parse_archive(_zip({"Spotify Account Data/Playlist1.json": json.dumps(playlist).encode()}))
    got = [(i.url, i.title, i.folder, i.added, i.origin) for i in result.items]
    assert got == [
        ("https://open.spotify.com/track/aaaaaaaaaaaaaaaaaaaaaa", "Track A — Artist A", "Morning run", "2024-03-05",
         "spotify-saved"),
        ("https://open.spotify.com/episode/bbbbbbbbbbbbbbbbbbbbbb", "Episode B — Show B", "Morning run", "2024-03-06",
         "spotify-saved")]
    assert "never read" not in json.dumps([i.__dict__ for i in result.items])


# --- GET /sources/ways-in --------------------------------------------------------------------------------------------


def _by_kind(desc):
    return {w["kind"]: w for w in desc["ways"]}


def test_the_connect_area_for_each_source(api, memory):
    body = api.get("/sources/ways-in").json()
    by = {s["source"]: s for s in body["sources"]}
    assert list(by) == ["spotify", "reddit", "pinterest", "tiktok", "instagram"]
    spotify = by["spotify"]
    assert spotify["primary"] is None and set(_by_kind(spotify)) == {"browser", "file"}
    assert {n["kind"] for n in spotify["notOffered"]} == {"account"}
    reddit_area = by["reddit"]
    assert reddit_area["primary"] is None and reddit_area["ownApp"] is False and reddit_area["recommended"] == "browser"
    assert set(_by_kind(reddit_area)) == {"browser", "file"}
    assert _by_kind(reddit_area)["file"]["requestUrl"] == "https://www.reddit.com/settings/data-request"
    assert set(_by_kind(by["pinterest"])) == {"browser"}
    assert {n["kind"] for n in by["pinterest"]["notOffered"]} == {"account", "file"}
    for sid in ("tiktok", "instagram"):
        assert set(_by_kind(by[sid])) == {"browser", "file"} and by[sid]["account"] is None
    os.environ[reddit.APP_CLIENT_ID_ENV] = CID
    one = api.get("/sources/ways-in/reddit").json()
    assert one["primary"] == {"action": "connect", "connector": "reddit"} and one["recommended"] == "account"
    assert api.get("/sources/ways-in/nowhere").status_code == 404


def test_the_browser_way_follows_the_persons_switch(api, memory):
    reading_settings.update(agent_enabled_=True, acknowledge=True)
    reading_settings.update(saved_lists_={"reddit": True})
    way = _by_kind(api.get("/sources/ways-in/reddit").json())["browser"]
    assert way["on"] is True and way["agentReading"] is True and way["label"] == "Saved"


def test_reading_the_ways_in_writes_nothing(api, memory, tmp_path):
    before = {p: p.stat().st_mtime_ns for p in tmp_path.rglob("*") if p.is_file()}
    api.get("/sources/ways-in")
    after = {p: p.stat().st_mtime_ns for p in tmp_path.rglob("*") if p.is_file()}
    assert before == after
