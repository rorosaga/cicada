"""Hermetic tests for Safari iCloud-tab ingestion (2026-09-02 brief, G30 follow-up).

Every CloudTabs.db here is built in ``tmp_path`` with stdlib ``sqlite3`` from
synthetic rows — the real ``~/Library/Containers/com.apple.Safari/…/CloudTabs.db``
is never opened (CLAUDE.md privacy rule; the launchd backend could not read it
anyway, R1). Device names, titles and URLs are placeholders.
"""
from __future__ import annotations

import base64
import sqlite3
from pathlib import Path

import pytest

from api.services import safari_tabs, saved_at, sync_state
from api.services.media_ingestor import RawItem

COCOA_2026_01_13 = 790_000_000.0  # = 1768307200 Unix = 2026-01-13T11:06:40Z (only the date matters)

DEVICES = [("dev-phone", "Bob's iPhone"), ("dev-mac", "Bob's MacBook")]
TABS = [
    # (tab_uuid, device_uuid, title, url, position)
    ("t1", "dev-phone", "Example One", "https://example.com/one", 0),
    ("t2", "dev-phone", "Example Two", "https://example.com/two", 1),
    ("t3", "dev-phone", "Dup of one", "https://example.com/one", 2),        # in-batch dup
    ("t4", "dev-phone", "Bookmarklet", "javascript:void(0)", 3),            # non-http
    ("t5", "dev-phone", "Local dev", "http://localhost:8000/", 4),          # private
    ("t6", "dev-phone", "LAN", "http://192.168.1.10/admin", 5),             # private
    ("t7", "dev-mac", "Example Three", "https://example.org/three", 0),
    ("t8", "dev-ghost", "Orphan", "https://example.net/orphan", 0),          # unknown device
]


def _make_db(path: Path, *, with_timestamp: bool = False, wal: bool = False) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    if wal:
        conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE cloud_tab_devices (device_uuid TEXT PRIMARY KEY, device_name TEXT, "
                 "has_duplicate_group_title INTEGER, last_modified REAL)")
    cols = "tab_uuid TEXT PRIMARY KEY, device_uuid TEXT, title TEXT, url TEXT, position BLOB"
    if with_timestamp:
        cols += ", last_viewed_time REAL"
    conn.execute(f"CREATE TABLE cloud_tabs ({cols})")
    conn.executemany("INSERT INTO cloud_tab_devices (device_uuid, device_name) VALUES (?, ?)", DEVICES)
    for row in TABS:
        if with_timestamp:
            conn.execute("INSERT INTO cloud_tabs VALUES (?, ?, ?, ?, ?, ?)", (*row, COCOA_2026_01_13))
        else:
            conn.execute("INSERT INTO cloud_tabs VALUES (?, ?, ?, ?, ?)", row)
    conn.commit()
    return conn


def _db_bytes(tmp_path: Path, **kwargs) -> bytes:
    path = tmp_path / "CloudTabs.db"
    _make_db(path, **kwargs).close()
    return path.read_bytes()


# --- load_tabs ----------------------------------------------------------------


def test_load_tabs_joins_devices_and_skips_unimportable_urls(tmp_path):
    snap = safari_tabs.load_tabs(_db_bytes(tmp_path))
    # Set, not list: rows come back in SQLite's scan order and nothing may
    # depend on it (`position` is an opaque BLOB — there is no honest ORDER BY).
    assert {i.url for i in snap.items} == {
        "https://example.com/one", "https://example.com/two",          # phone, dedup'd
        "https://example.org/three",                                     # mac
        "https://example.net/orphan",                                    # unknown device
    }
    by_url = {i.url: i for i in snap.items}
    assert by_url["https://example.com/one"].folder == "Bob's iPhone"
    assert by_url["https://example.com/one"].title == "Example One"
    assert by_url["https://example.net/orphan"].folder == safari_tabs.UNKNOWN_DEVICE
    assert all(i.origin == "safari-tab" and "safari-tab" in i.tags for i in snap.items)
    assert snap.skipped == 4  # dup + javascript + localhost + LAN


def test_load_tabs_device_counts_are_importable_tabs_sorted_by_count(tmp_path):
    snap = safari_tabs.load_tabs(_db_bytes(tmp_path))
    assert snap.devices == [
        {"name": "Bob's iPhone", "count": 2},
        {"name": "Bob's MacBook", "count": 1},
        {"name": safari_tabs.UNKNOWN_DEVICE, "count": 1},
    ]
    assert snap.total == 4


def test_load_tabs_added_is_none_without_a_timestamp_column(tmp_path):
    snap = safari_tabs.load_tabs(_db_bytes(tmp_path))
    assert all(i.added is None for i in snap.items)


def test_load_tabs_reads_a_cocoa_timestamp_column_when_present(tmp_path):
    snap = safari_tabs.load_tabs(_db_bytes(tmp_path, with_timestamp=True))
    expected = saved_at.from_cocoa_seconds(COCOA_2026_01_13)
    assert expected is not None and expected.startswith("20")
    assert all(i.added == expected for i in snap.items)


def test_from_cocoa_seconds_rejects_garbage():
    assert saved_at.from_cocoa_seconds(None) is None
    assert saved_at.from_cocoa_seconds("x") is None
    assert saved_at.from_cocoa_seconds(0) is None
    assert saved_at.from_cocoa_seconds(-5) is None


def test_load_tabs_replays_a_wal_sidecar(tmp_path):
    """R2: a bare copy of a WAL-mode db misses un-checkpointed pages; with the
    sidecar supplied the parse sees them."""
    path = tmp_path / "CloudTabs.db"
    conn = _make_db(path, wal=True)                    # stays OPEN so the WAL holds frames
    wal_path = tmp_path / "CloudTabs.db-wal"
    assert wal_path.exists() and wal_path.stat().st_size > 0
    db_bytes, wal_bytes = path.read_bytes(), wal_path.read_bytes()
    try:
        with_wal = safari_tabs.load_tabs(db_bytes, wal_bytes)
        assert with_wal.total == 4
        # The bare copy is page 1 only — every table still lives in the WAL —
        # so without the sidecar the parse finds no `cloud_tabs` at all
        # (verified against SQLite 3.47 while writing this plan).
        with pytest.raises(safari_tabs.SafariTabsError):
            safari_tabs.load_tabs(db_bytes)
    finally:
        conn.close()


def test_load_tabs_rejects_non_sqlite_and_missing_tables(tmp_path):
    with pytest.raises(safari_tabs.SafariTabsError):
        safari_tabs.load_tabs(b"definitely not a database")
    other = tmp_path / "other.db"
    c = sqlite3.connect(other); c.execute("CREATE TABLE unrelated (x)"); c.commit(); c.close()
    with pytest.raises(safari_tabs.SafariTabsError):
        safari_tabs.load_tabs(other.read_bytes())


def test_load_tabs_maps_schema_drift_to_safari_tabs_error(tmp_path):
    """Final review, finding 1: a CloudTabs.db whose tables exist but carry
    different column names (here `link` for `url`) must surface as
    SafariTabsError so the router's 422 mapping covers it — not as a bare
    sqlite3.OperationalError the router turns into a 500."""
    path = tmp_path / "drift.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE cloud_tab_devices (device_uuid TEXT PRIMARY KEY, device_name TEXT)")
    conn.execute("CREATE TABLE cloud_tabs (tab_uuid TEXT PRIMARY KEY, device_uuid TEXT, title TEXT, link TEXT)")
    conn.execute("INSERT INTO cloud_tab_devices VALUES ('d', 'Bob''s iPhone')")
    conn.execute("INSERT INTO cloud_tabs VALUES ('t', 'd', 'Example', 'https://example.com/')")
    conn.commit(); conn.close()
    with pytest.raises(safari_tabs.SafariTabsError, match="schema"):
        safari_tabs.load_tabs(path.read_bytes())


def _shared_url_db_bytes(tmp_path: Path) -> bytes:
    """One page open on BOTH devices, plus one page each device has alone.
    The MacBook row is inserted first so SQLite scans it first — the shape in
    which the pre-fix dedup credited the shared tab to the MacBook only."""
    path = tmp_path / "shared.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE cloud_tab_devices (device_uuid TEXT PRIMARY KEY, device_name TEXT)")
    conn.execute("CREATE TABLE cloud_tabs (tab_uuid TEXT PRIMARY KEY, device_uuid TEXT, title TEXT, url TEXT)")
    conn.executemany("INSERT INTO cloud_tab_devices VALUES (?, ?)", DEVICES)
    conn.executemany("INSERT INTO cloud_tabs VALUES (?, ?, ?, ?)", [
        ("m1", "dev-mac", "Shared", "https://example.com/shared"),
        ("m2", "dev-mac", "Mac only", "https://example.com/mac-only"),
        ("p1", "dev-phone", "Shared", "https://example.com/shared"),
        ("p2", "dev-phone", "Phone only", "https://example.com/phone-only"),
    ])
    conn.commit(); conn.close()
    return path.read_bytes()


def test_a_tab_open_on_two_devices_counts_on_both_and_imports_under_either(tmp_path):
    """Final review, finding 2: dedup by URL used to run BEFORE the device
    filter, so selecting the second-scanned device silently dropped the shared
    tab and its preview count under-reported."""
    snap = safari_tabs.load_tabs(_shared_url_db_bytes(tmp_path))
    assert snap.devices == [{"name": "Bob's MacBook", "count": 2}, {"name": "Bob's iPhone", "count": 2}]
    assert snap.total == 3  # distinct URLs — what an unfiltered sync imports
    assert snap.skipped == 0  # a cross-device duplicate is not a skip
    phone = safari_tabs.select(snap, ["Bob's iPhone"])
    assert {i.url for i in phone} == {"https://example.com/shared", "https://example.com/phone-only"}
    assert all(i.folder == "Bob's iPhone" for i in phone)
    assert {i.url for i in safari_tabs.select(snap, ["Bob's MacBook"])} == {
        "https://example.com/shared", "https://example.com/mac-only"}
    # Unfiltered: one item per URL, so ingest never sees the shared tab twice.
    everything = safari_tabs.select(snap, None)
    assert len(everything) == 3
    assert len({i.url for i in everything}) == 3


def test_sync_tabs_imports_a_shared_tab_for_the_selected_device(tmp_path):
    seen: list[RawItem] = []

    async def fake_ingest(items, memory_path, from_bookmark_file=False, **kwargs):
        seen.extend(items)
        return len(items), 0

    memory = tmp_path / "memory"; memory.mkdir()
    result = run(safari_tabs.sync_tabs(
        memory, _shared_url_db_bytes(tmp_path), devices=["Bob's iPhone"], ingest_fn=fake_ingest))
    assert result["new"] == 2 and result["seen"] == 2
    assert {i.url for i in seen} == {"https://example.com/shared", "https://example.com/phone-only"}
    assert {d["name"]: d["count"] for d in result["devices"]} == {"Bob's MacBook": 2, "Bob's iPhone": 2}


def test_select_filters_by_exact_device_name(tmp_path):
    snap = safari_tabs.load_tabs(_db_bytes(tmp_path))
    assert {i.url for i in safari_tabs.select(snap, ["Bob's iPhone"])} == {
        "https://example.com/one", "https://example.com/two"}
    assert len(safari_tabs.select(snap, None)) == 4
    assert safari_tabs.select(snap, ["Nobody's iPad"]) == []


# --- sync_tabs ----------------------------------------------------------------


def run(coro):
    import asyncio
    return asyncio.run(coro)


def test_sync_tabs_chunks_and_records_sync_state(tmp_path, monkeypatch):
    monkeypatch.setattr(safari_tabs, "MAX_BATCH", 3)
    calls: list[list[RawItem]] = []

    async def fake_ingest(items, memory_path, from_bookmark_file=False, **kwargs):
        calls.append(list(items))
        assert from_bookmark_file is True
        return len(items) - 1, 1

    memory = tmp_path / "memory"; memory.mkdir()
    result = run(safari_tabs.sync_tabs(memory, _db_bytes(tmp_path), ingest_fn=fake_ingest))
    assert [len(c) for c in calls] == [3, 1]
    assert result["new"] == 2 and result["skipped"] == 2 and result["seen"] == 4
    assert [d["selected"] for d in result["devices"]] == [True, True, True]
    entry = sync_state.read_sync_state(memory)["safari-tabs"]
    assert entry["count"] == 4 and entry["devices"] == ["Bob's iPhone", "Bob's MacBook", safari_tabs.UNKNOWN_DEVICE]


def test_sync_tabs_device_filter_marks_selection(tmp_path):
    async def fake_ingest(items, memory_path, from_bookmark_file=False, **kwargs):
        return len(items), 0

    memory = tmp_path / "memory"; memory.mkdir()
    result = run(safari_tabs.sync_tabs(memory, _db_bytes(tmp_path), devices=["Bob's MacBook"], ingest_fn=fake_ingest))
    assert result["new"] == 1 and result["seen"] == 1
    assert {d["name"]: d["selected"] for d in result["devices"]}["Bob's MacBook"] is True
    assert {d["name"]: d["selected"] for d in result["devices"]}["Bob's iPhone"] is False


def test_sync_tabs_records_an_error_and_reraises(tmp_path):
    async def boom(items, memory_path, from_bookmark_file=False, **kwargs):
        raise RuntimeError("disk full")

    memory = tmp_path / "memory"; memory.mkdir()
    with pytest.raises(RuntimeError):
        run(safari_tabs.sync_tabs(memory, _db_bytes(tmp_path), ingest_fn=boom))
    assert "disk full" in sync_state.read_sync_state(memory)["safari-tabs"]["last_error"]


# --- endpoint -----------------------------------------------------------------


def _client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from api import config, main
    from api.services import bank_index

    memory = tmp_path / "memory"
    for sub in ("episodes", "entities", "sources"):
        (memory / sub).mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    return TestClient(main.app), memory


def _offline_enrich(monkeypatch):
    from api.services import media_ingestor
    from api.services.media_ingestor import MediaMeta, _classify, _fallback_title, _site_of

    async def fake(url, client, from_bookmark_file=False):
        return MediaMeta(title=_fallback_title(url), description="", site=_site_of(url),
                         media_type=_classify(url, from_bookmark_file=from_bookmark_file))
    monkeypatch.setattr(media_ingestor, "enrich", fake)


def test_endpoint_preview_stages_nothing(tmp_path, monkeypatch):
    client, memory = _client(tmp_path, monkeypatch)
    before = sorted(p.relative_to(memory) for p in memory.rglob("*"))
    b64 = base64.b64encode(_db_bytes(tmp_path)).decode()
    resp = client.post("/sources/sync-safari-tabs?preview=true", json={"safariTabsDbB64": b64})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 4
    assert body["devices"][0] == {"name": "Bob's iPhone", "count": 2}
    assert sorted(p.relative_to(memory) for p in memory.rglob("*")) == before
    assert "safari-tabs" not in sync_state.read_sync_state(memory)


def test_endpoint_sync_is_idempotent_and_lights_the_channel(tmp_path, monkeypatch):
    _offline_enrich(monkeypatch)
    client, memory = _client(tmp_path, monkeypatch)
    b64 = base64.b64encode(_db_bytes(tmp_path)).decode()
    first = client.post("/sources/sync-safari-tabs", json={"safariTabsDbB64": b64, "devices": ["Bob's iPhone"]})
    assert first.status_code == 200, first.text
    assert first.json()["new"] == 2 and first.json()["seen"] == 2
    second = client.post("/sources/sync-safari-tabs", json={"safariTabsDbB64": b64, "devices": ["Bob's iPhone"]})
    assert second.json()["new"] == 0 and second.json()["skipped"] == 2

    from api.services import bank_index
    bank_index.invalidate()
    channels = {c["id"]: c for c in client.get("/sources/channels").json()["channels"]}
    assert channels["safari-tabs"]["connected"] is True
    assert channels["safari-tabs"]["count"] == 2
    assert channels["safari-tabs"]["detail"].startswith("2 tabs · synced ")


def test_endpoint_rejects_bad_base64_and_non_db(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    assert client.post("/sources/sync-safari-tabs", json={"safariTabsDbB64": "%%%"}).status_code == 422
    b64 = base64.b64encode(b"not a db").decode()
    assert client.post("/sources/sync-safari-tabs", json={"safariTabsDbB64": b64}).status_code == 422


def test_endpoint_maps_schema_drift_to_422_on_both_paths(tmp_path, monkeypatch):
    """Final review, finding 1: the reproduction was HTTP 500 on both the sync
    and the preview for a db whose cloud_tabs has `link` instead of `url`."""
    client, _ = _client(tmp_path, monkeypatch)
    path = tmp_path / "drift.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE cloud_tab_devices (device_uuid TEXT PRIMARY KEY, device_name TEXT)")
    conn.execute("CREATE TABLE cloud_tabs (tab_uuid TEXT PRIMARY KEY, device_uuid TEXT, title TEXT, link TEXT)")
    conn.commit(); conn.close()
    b64 = base64.b64encode(path.read_bytes()).decode()
    preview = client.post("/sources/sync-safari-tabs?preview=true", json={"safariTabsDbB64": b64})
    assert preview.status_code == 422, preview.text
    assert "schema" in preview.json()["detail"]
    sync = client.post("/sources/sync-safari-tabs", json={"safariTabsDbB64": b64})
    assert sync.status_code == 422, sync.text
