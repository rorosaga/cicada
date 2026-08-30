"""Hermetic tests for sync_state.json + GET /sources/channels (G62).

Every test builds its own tmp_path workspace; the real memory/ is untouched.
No network: channel derivation is pure filesystem + env reads.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import bank_index, sync_state


def test_record_sync_writes_and_reads_back(tmp_path):
    sync_state.record_sync(tmp_path, "bookmarks", count=412, at="2026-08-29T10:00:00Z")
    state = sync_state.read_sync_state(tmp_path)
    assert state["bookmarks"] == {"last_sync": "2026-08-29T10:00:00Z", "count": 412}


def test_record_sync_preserves_other_channels(tmp_path):
    sync_state.record_sync(tmp_path, "bookmarks", count=412, at="2026-08-29T10:00:00Z")
    sync_state.record_sync(tmp_path, "notes", count=18, at="2026-08-30T09:00:00Z")
    state = sync_state.read_sync_state(tmp_path)
    assert set(state) == {"bookmarks", "notes"}
    assert state["notes"]["count"] == 18


def test_read_sync_state_missing_or_corrupt_is_empty(tmp_path):
    assert sync_state.read_sync_state(tmp_path) == {}
    sync_state.sync_state_path(tmp_path).write_text("{not json", encoding="utf-8")
    assert sync_state.read_sync_state(tmp_path) == {}


def _channels(memory_path, *, telegram_enabled=False):
    from api.services import channel_registry

    bank_index.invalidate()
    return {c["id"]: c for c in channel_registry.build_channels(
        memory_path, telegram_enabled=telegram_enabled)}


def test_rss_channel_connected_when_a_feed_is_subscribed(tmp_path):
    from api.services import feed_registry

    feed_registry.subscribe_feed(tmp_path, "https://example.com/feed.xml")
    ch = _channels(tmp_path)["rss"]
    assert ch["connected"] is True
    assert ch["count"] == 1
    assert ch["label"] == "RSS feeds"
    assert ch["actions"] == ["poll", "manage"]
    assert "1 feed" in ch["detail"]


def test_calendar_channel_disconnected_with_empty_registry(tmp_path):
    ch = _channels(tmp_path)["calendar"]
    assert ch["connected"] is False
    assert ch["count"] == 0
    assert ch["last_sync"] is None
    assert ch["detail"] is None
    assert ch["actions"] == ["poll", "manage"]


def test_bookmarks_and_notes_channels_read_sync_state(tmp_path):
    sync_state.record_sync(tmp_path, "bookmarks", count=412, at="2026-08-29T10:00:00Z")
    chans = _channels(tmp_path)
    bookmarks = chans["bookmarks"]
    assert bookmarks["connected"] is True
    assert bookmarks["count"] == 412
    assert bookmarks["last_sync"] == "2026-08-29T10:00:00Z"
    assert bookmarks["detail"].startswith("412 bookmarks")
    assert bookmarks["actions"] == ["sync"]
    assert chans["notes"]["connected"] is False


def test_telegram_channel_follows_the_env_flag_and_counts_episodes(tmp_path):
    episodes = tmp_path / "episodes"
    episodes.mkdir(parents=True)
    (episodes / "ep_2026-08-01_001.md").write_text(
        "---\nid: ep_2026-08-01_001\norigin: telegram\ntimestamp: '2026-08-01T09:00:00Z'\n---\nhi\n",
        encoding="utf-8")
    assert _channels(tmp_path, telegram_enabled=False)["telegram"]["connected"] is False
    ch = _channels(tmp_path, telegram_enabled=True)["telegram"]
    assert ch["connected"] is True
    assert ch["count"] == 1
    assert ch["detail"] == "Bot configured · 1 capture"
    assert ch["actions"] == []


def test_chat_export_channels_come_from_origin_counts(tmp_path):
    episodes = tmp_path / "episodes"
    episodes.mkdir(parents=True)
    for i, origin in enumerate(("claude-export", "claude-export", "chatgpt-export")):
        (episodes / f"ep_2026-06-1{i}_001.md").write_text(
            f"---\nid: ep_2026-06-1{i}_001\norigin: {origin}\ntimestamp: '2026-06-1{i}T09:00:00Z'\n---\nx\n",
            encoding="utf-8")
    chans = _channels(tmp_path)
    claude = chans["chat-export:claude"]
    assert claude["connected"] is True and claude["count"] == 2
    assert claude["label"] == "Claude chat export"
    assert claude["actions"] == ["import"]
    assert chans["chat-export:chatgpt"]["count"] == 1


def test_files_channel_counts_the_url_index(tmp_path):
    sources = tmp_path / "sources"
    sources.mkdir(parents=True)
    (sources / "url_index.json").write_text(
        json.dumps({"h1": {"url": "https://a.example"}, "h2": {"url": "https://b.example"}}),
        encoding="utf-8")
    ch = _channels(tmp_path)["files"]
    assert ch["connected"] is True and ch["count"] == 2
    assert ch["detail"] == "2 saved items"
    assert ch["actions"] == ["import"]


@pytest.fixture
def client(tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    for sub in ("episodes", "entities", "sources"):
        (memory / sub).mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("CICADA_TELEGRAM_BOT_TOKEN", raising=False)
    config.get_settings.cache_clear()
    bank_index.invalidate()
    yield TestClient(main.app), memory
    config.get_settings.cache_clear()


def test_get_sources_channels_returns_every_known_channel(client):
    c, _ = client
    resp = c.get("/sources/channels")
    assert resp.status_code == 200, resp.text
    ids = [ch["id"] for ch in resp.json()["channels"]]
    assert ids == [
        "chat-export:claude", "chat-export:chatgpt", "bookmarks", "notes",
        "rss", "calendar", "telegram", "files",
    ]
    assert all(ch["connected"] is False for ch in resp.json()["channels"])


def test_get_sources_channels_is_camel_cased(client):
    c, memory = client
    sync_state.record_sync(memory, "notes", count=7, at="2026-08-30T09:00:00Z")
    bank_index.invalidate()
    notes = next(ch for ch in c.get("/sources/channels").json()["channels"] if ch["id"] == "notes")
    assert notes["lastSync"] == "2026-08-30T09:00:00Z"
    assert notes["count"] == 7


def test_get_sources_channels_etag_304_then_200_after_a_sync(client):
    c, memory = client
    first = c.get("/sources/channels")
    etag = first.headers["etag"]
    assert c.get("/sources/channels", headers={"If-None-Match": etag}).status_code == 304

    sync_state.record_sync(memory, "bookmarks", count=3, at="2026-08-30T10:00:00Z")
    bank_index.invalidate()
    again = c.get("/sources/channels", headers={"If-None-Match": etag})
    assert again.status_code == 200, "a new sync_state entry must break the ETag"


def test_sync_state_rides_the_sources_version_component(client):
    c, memory = client
    before = c.get("/sync/version").json()["components"]["sources"]
    sync_state.record_sync(memory, "bookmarks", count=3, at="2026-08-30T10:00:00Z")
    bank_index.invalidate()
    after = c.get("/sync/version").json()["components"]["sources"]
    assert after != before


def test_sync_notes_endpoint_records_sync_state(client):
    c, memory = client
    # Malformed dump (wrong field count) parses to zero notes; what matters
    # here is only that `record_sync` fires with a non-null timestamp.
    dump = "not-a-valid-note-record"
    resp = c.post("/sources/sync-notes", json={"notesDump": dump})
    assert resp.status_code == 200, resp.text
    notes_state = sync_state.read_sync_state(memory).get("notes", {})
    assert notes_state.get("last_sync")
    assert notes_state.get("count") == 0


def test_build_channels_runs_off_the_event_loop(client, monkeypatch):
    """MED-2: `build_channels` runs the same full episode+entity origin scan
    `/origins` does, so it must go through `run_in_threadpool` — running it
    inline stalls the SSE stream and every concurrent request."""
    import asyncio

    from api.routers import sources as sources_router

    real = sources_router.channel_registry.build_channels
    seen: list[bool] = []

    def spy(memory_path, **kwargs):
        try:
            asyncio.get_running_loop()
            seen.append(True)  # called on the event loop thread
        except RuntimeError:
            seen.append(False)  # called on a worker thread — correct
        return real(memory_path, **kwargs)

    monkeypatch.setattr(sources_router.channel_registry, "build_channels", spy)
    assert client[0].get("/sources/channels").status_code == 200
    assert seen == [False], "build_channels must not run on the event loop"
