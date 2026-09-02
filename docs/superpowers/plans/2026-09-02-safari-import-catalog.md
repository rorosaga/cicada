# Safari iCloud Tabs + Bookmark Folders + Logo-first Import Catalog — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the owner import (1) every Safari tab open on their iPhone (iCloud tabs, ~200 today), (2) one chosen Safari bookmark folder (a large folder under Favorites, ~500 leaves — name redacted per the privacy rule) instead of everything-or-nothing, and (3) find both from a `+` sheet that reads as *where things come from* — one logo-first tile per family (Browsers, Websites & apps, Chat exports, Feeds & calendars, Files) that opens into its members, each carrying its own logo, its import routes and its live channel state.

**Architecture:** Same division of labour the bookmark sync already has (`api/routers/sources.py:308-318`): **the app reads the files under `~/Library` and the backend parses bytes.** The launchd backend has no Full Disk Access and never will — the app bundle is the thing the user grants it to. Two new backend seams (`safari_tabs.py`; folder filter + folder-tree preview on `bookmark_sync.py`), both engine-free, LLM-free, and idempotent through the one existing dedup (`media_ingestor.ingest_batch` re-checks `url_index.json` — the 331 `safari-bookmark` + 271 `chrome-bookmark` entities already in the live bank are never re-created). In the app, one `BrowserFileReader` (off-main, exact Full-Disk-Access fix on failure), two `Mutation`s, two leaf panels (device picker, folder tree), and a two-level family catalog in front of the existing leaf flows.

**Tech Stack:** Python 3.12 / FastAPI / Pydantic (`api/`), stdlib `sqlite3` + `plistlib`, SwiftUI + XCTest (`app/CicadaApp`, macOS 14).

**Spec:** the owner's brief (2026-09-02) as relayed by the orchestrator; backlog rows **G30** (browser bookmarks), **G47** (importer family), **G71** (Imports catalog). Task 5 adds the follow-up row **G118** (Arc / Firefox / Brave).

## Global Constraints

- Work ONLY in `/Users/rorosaga/Documents/roros_lab/cicada/.worktrees/safari-import` (branch `feat/safari-import`, based on `dev` @ `bad8461`). Every shell command is `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/safari-import && …` with absolute paths (`zoxide` hijacks relative `cd`; ignore its stderr warning). Never `grep --include=*.ext` (zsh globbing breaks it) — use `grep -rn … <dir>` and filter by path.
- **Never read** `/Users/rorosaga/Documents/roros_lab/cicada/memory` (any bank), `~/.cicada`, `~/Library/Safari`, `~/Library/Containers/com.apple.Safari`, or `~/.claude/projects` — real personal data. Every fixture is synthetic (`alpha-project`, `bob-example`, `example.com`, device names like `Bob's iPhone`).
- Python tests: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/safari-import && api/.venv/bin/python -m pytest <files> -q -p no:cacheprovider`. Full suite: `api/tests`. **Baseline failures (not yours):** 8 date-dependent ones in `test_calendar_registry.py` and `test_agent_provenance.py::test_a_decay_only_change_lands_in_its_own_cicada_authored_commit` (order-dependent). Everything else must be green.
- Swift: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/safari-import/app/CicadaApp && swift build 2>&1 | tail -5` must succeed and `swift test 2>&1 | tail -20` must report 0 failures. SourceKit diagnostics naming OTHER worktrees are noise. **NEVER** run `make dev`, `make install-app`, `swift run`, or launch/kill the Cicada app — the owner's installed app is live.
- Never `git add -A`; stage named files only. Never commit `memory/`, `logs/`, `.claude/settings.json`, `api/.venv`, `*-report.md`. No push, no new branches/worktrees, no subagents. Ignore Devin/PR comments.
- **Privacy rule (CLAUDE.md, standing):** no owner device names, bookmark folder names, URLs or titles in code comments, tests, docs, commit messages or this plan. Fixtures use placeholders.
- **Sleep-safety rails:** no LLM anywhere in this track; every new read path is engine-free; no new network call is introduced by any task (the existing best-effort enrichment inside `ingest_batch` is unchanged — see R3). Secrets are not involved.
- **ETag ship-together:** anything that changes what `GET /sources/channels` returns must change in the same commit as its ETag inputs (`sync_state.json` already rides the `sources` component, `api/services/sync_service.py:159-166`).
- Docstrings explain WHY and cite the rule that motivated them (G-row / review), matching the density of `bookmark_sync.py:1-24` and `connectors/base.py:110-119`.
- Line numbers below are from `bad8461` and drift by a few lines as tasks land — read at the anchor before editing.

## Rulings (binding — decided here so no task stalls)

- **R1 — the app reads, the backend parses; the app actually sends bytes now.** Today `AddSourceSheet.syncBookmarks()` (`AddSourceSheet.swift:574-580`) and `ConnectedChannelsStrip.sync` (`ConnectedChannelsStrip.swift:163-170`) call `APIClient.syncBookmarks()` with **no** data, so the launchd backend tries `~/Library/Safari/Bookmarks.plist` itself and — lacking Full Disk Access — silently syncs nothing (`bookmark_sync.sync_from_local_files` swallows the `OSError`, `bookmark_sync.py:156-186`). After this track the app reads the four browser files (`BrowserFileReader`, Task 3) off the main thread and POSTs base64 bytes; the body-less local-file fallback on `POST /sources/sync-bookmarks` stays for `curl`/tests and is never the app's path. **No `sync_from_local_files` twin exists for iCloud tabs** — the backend never opens a `~/Library` path for tabs, so a missing-FDA failure surfaces exactly once, in the app, with the fix.
- **R2 — CloudTabs.db is parsed from a temp copy, read-only, with the WAL sidecar accepted.** `safari_tabs.load_tabs` writes the bytes to a private `tempfile.mkdtemp()` and opens `sqlite3.connect("file:<path>?mode=ro", uri=True)`; when no WAL bytes are supplied it adds `&immutable=1`. Safari keeps its SQLite stores in WAL mode, and a bare copy of the main file can be missing the pages still sitting in `CloudTabs.db-wal`, so the request carries an optional `safariTabsWalB64`; the app sends it whenever the sidecar exists (Task 3). Tests prove both shapes. The temp dir is removed in a `finally`.
- **R3 — origin `safari-tab`, `from_bookmark_file=True`, folder = device name, no new network.** Tabs ride `ingest_batch` exactly as bookmarks do (`bookmark_sync.py:143`): `from_bookmark_file=True` so `_classify` yields `media_type: bookmark` (`media_ingestor.py:178-189`), origin stamped on both `tags` and `origin` (`bookmark_sync._tag_origin`, `:92-101`). `ingest_batch`'s existing best-effort OpenGraph enrichment (`media_ingestor.py:213-239`) is **left exactly as it is** — this track adds no fetch and gates nothing; page-content summaries are a separate track. Ingest is chunked in `MAX_BATCH` slices the way `connectors/base._run_sync_locked` does (`base.py:199-219`).
- **R4 — the combined `bookmarks` channel splits into `chrome-bookmarks` and `safari-bookmarks`, read-time legacy fallback, no bank write.** The catalog now has one tile per browser and a channel must map to exactly one tile (`SourceChannelTests.swift:92-96`, `AddSourceTileTests.swift:41-47`), so a shared "Chrome & Safari bookmarks" row can no longer be honest. `POST /sources/sync-bookmarks` records `sync_state` per origin actually synced (`chrome-bookmark` → `chrome-bookmarks`, `safari-bookmark` → `safari-bookmarks`); `channel_registry` renders the two rows plus `safari-tabs`, and each browser row falls back to the legacy `bookmarks` entry when its own is absent — so an existing bank keeps showing "connected · N bookmarks · synced <date>" on both rows until each syncs on its own (disclosed asymmetry: until then both rows show the same legacy count). No migration touches `sync_state.json`.
- **R5 — folder selection is a list of path prefixes at segment boundaries; empty means everything.** `folders: [str]` on `POST /sources/sync-bookmarks`; an item matches when `item.folder == f` or `item.folder.startswith(f + "/")`, or when `f == ""` (the tree root). Case-sensitive, exact, applied after parse and before ingest, per source. Omitting `folders` (or `[]`/`null`) is byte-identical to today's behaviour. `?preview=true` returns the folder tree with leaf counts and stages nothing (mirrors `POST /sources/upload?preview=true`, `sources.py:134-154`). Safari's parser output is **unchanged** (`media_ingestor.parse_safari_bookmarks`, `:329-380`, keeps threading raw `Title`s: `BookmarksBar`, `BookmarksMenu`, `com.apple.ReadingList`); only the preview's display `name` maps those three to "Favorites", "Bookmarks Menu", "Reading List". So Reading List shows as its own folder with its real path key.
- **R6 — `AddSourceTile` stays the leaf identity; families are a layer in front, not a rewrite.** Every flow, `forChannel`, `initialTile` ("Manage…") and the tests key on `AddSourceTile`. `.browserBookmarks` is replaced by `.safari` (channels `safari-bookmarks`, `safari-tabs`) and `.chrome` (channel `chrome-bookmarks`). A new `ImportFamily` enum groups tiles; the sheet gains a third level (`families → members → flow`). `ConnectorSetupPanel`, `WalkthroughPanel`, `ImportPreviewSection` are reused as-is as leaf panels.
- **R7 — browser marks are drawn, not downloaded.** Safari uses the SF Symbol `safari` (Apple's own glyph, already used by `OriginIconography.symbol(for: "safari-bookmark")`, `OriginIconography.swift:58`); Chrome is a `Canvas`-drawn `ChromeGlyph` (three 120° arcs in Chrome's green/red/yellow around a blue disc). Both live behind `AddSourceTile.brandGlyph: BrandGlyph?`, distinct from `logoName`, so `ImportCatalogTests.testEveryDeclaredLogoNameResolvesToABundledImage` stays true. **To use official PNGs later** the owner drops `Resources/logos/chrome.png` / `safari.png` and flips the two tiles' `logoName` — `LogoImage.exists(name:)` (`LogoImage.swift:120-122`) picks them up, and `PlatformTile` prefers a PNG over a glyph.
- **R8 — syncs go through `Store.perform` with a no-op optimistic step.** A browser sync has no client state to paint ahead of time, but `Store.perform` (`Store.swift:436-455`) is the one place that gives every write the same failure toast + domain reconcile, and the brief asks for the Store/Mutation pattern. `SyncSafariTabs` / `SyncBrowserBookmarks` capture the server's `{new, skipped}` in a `MutationMemo` (the `UnsubscribeFeed` pattern, `Mutations.swift:336-338`) so the panel can show the honest result; `refreshDomains = [.channels, .sources, .status]`. Previews are read-only and go through `APIClient` directly, like `previewSource` (`APIClient.swift:1553-1556`).
- **R9 — an unreadable file shows the exact fix, once, in the panel.** `BrowserFileError.userMessage` says: "Cicada can't read <path>. Allow it under System Settings → Privacy & Security → Full Disk Access → Cicada, then try again." with a button opening `x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles`. `NSFileReadNoPermissionError` (257) → `.notReadable`; `NSFileReadNoSuchFileError` (260) / ENOENT → `.missing` ("Safari hasn't synced any iCloud tabs on this Mac yet" for the tabs db).
- **R10 — keyboard model is a pure struct.** `CatalogFocus` (index, columns, count) with `move(.up/.down/.left/.right)` clamped, tested without SwiftUI; the grid attaches `.focusable()` + `.onKeyPress` and `Enter` activates the focused tile. `Esc` walks back one level (`flow → members → families → close`), extending the existing `escapeAction` (`AddSourceSheet.swift:225-231`).

## Not in scope

- Page-content fetching or summaries for tabs/bookmarks (separate track). No new network call in any task.
- Arc / Firefox / Brave parsers — filed as **G118** in Task 5, not built.
- Running the import against the owner's real files — the orchestrator does that after merge (see Verification).
- Walkthrough videos (G64), non-Takeout zip walking, Pinterest/X scope verification — unchanged from G71's disclosed list.
- Renaming the `bookmarks` sync_state key on disk, or any migration that writes a bank.

---

## File map

| File | Responsibility |
|---|---|
| `api/services/safari_tabs.py` (new) | CloudTabs.db bytes → `TabsSnapshot` (devices + `RawItem`s), device filter, chunked sync, channel constants |
| `api/services/saved_at.py` | `from_cocoa_seconds` (Core Data epoch → `YYYY-MM-DD`) |
| `api/services/bookmark_sync.py` | `folder_tree`, `filter_by_folders`, `display_name`, `CHANNEL_BY_ORIGIN`, `sync_bookmarks(folders=)`, `preview_bookmarks` |
| `api/services/channel_registry.py` | `safari-tabs`, `chrome-bookmarks`, `safari-bookmarks` rows; legacy fallback |
| `api/models/schemas.py` | `SafariTabs*` models, `BookmarkFolderNode`, `BookmarkTreePreview`, `folders` on `BookmarkSyncRequest` |
| `api/routers/sources.py` | `POST /sources/sync-safari-tabs[?preview=true]`, `POST /sources/sync-bookmarks[?preview=true]` + `folders` |
| `api/tests/test_safari_tabs.py` (new), `test_bookmark_sync.py`, `test_source_channels.py` | tests |
| `app/…/Services/BrowserFiles.swift` (new) | `BrowserFile`, `BrowserFileError`, `BrowserFileReader` (off-main reads, FDA fix copy) |
| `app/…/Models/BrowserImport.swift` (new) | `SafariTabsPreview`, `SafariTabsSyncResult`, `BookmarkFolderNode`, `BookmarkTreePreview`, `BookmarkFolderSelection` |
| `app/…/Services/APIClient.swift`, `Sync/SyncAPI.swift`, `Sync/Mutations.swift` | preview + sync calls, `SyncSafariTabs`, `SyncBrowserBookmarks` |
| `app/…/Views/Capture/Sheets/BrowserImportPanels.swift` (new) | `SafariTabsPanel`, `BookmarkFolderPanel`, `FullDiskAccessHint`, `BrowserImportActions` |
| `app/…/Views/Capture/Sheets/ImportFamilies.swift` (new) | `ImportFamily`, `CatalogFocus`, `BrandGlyph`, `ChromeGlyph`, `FamilyMarkCluster` |
| `app/…/Views/Capture/Sheets/AddSourceSheet.swift`, `ImportCatalog.swift`, `Views/Feed/ConnectedChannelsStrip.swift`, `Views/Capture/ConnectedChannelRow.swift`, `OriginIconography.swift` | tiles, flows, levels, channel rows |
| `app/…/Tests/CicadaAppTests/{BrowserFilesTests,BrowserImportModelTests,ImportFamilyTests}.swift` (new) + `ImportCatalogTests`, `AddSourceTileTests`, `SourceChannelTests`, `FeedChannelStripTests`, `MutationTests`, `StoreTests` | tests |
| `CLAUDE.md`, `docs/goals/memory-evolution.md`, `docs/goals/TODO.md` | docs |

---

### Task 1: Backend — Safari iCloud tabs (`POST /sources/sync-safari-tabs`)

**Files:**
- Create: `api/services/safari_tabs.py`
- Modify: `api/services/saved_at.py:74-80` (add `from_cocoa_seconds` after `_epoch_seconds_to_iso_date`)
- Modify: `api/models/schemas.py:1237` (after `BookmarkSyncResponse`)
- Modify: `api/routers/sources.py:351` (after `sync_bookmarks`), imports at `:10-38`
- Modify: `api/services/channel_registry.py:33-45, 200-231`
- Modify: `api/tests/test_source_channels.py:226-232, 278-283` (channel id ordering)
- Create: `api/tests/test_safari_tabs.py`

**Interfaces:**
- `safari_tabs.load_tabs(db: bytes, wal: bytes | None = None) -> TabsSnapshot` — raises `SafariTabsError` (a `ValueError`) when the bytes are not a SQLite database or lack the two tables.
- `safari_tabs.select(snapshot, devices: list[str] | None) -> list[RawItem]`
- `safari_tabs.sync_tabs(memory_path, db, *, wal=None, devices=None, ingest_fn=None) -> dict` → `{"new", "skipped", "seen", "devices": [{"name", "count", "selected"}]}`
- `saved_at.from_cocoa_seconds(raw: object) -> str | None`
- `channel_registry.CHANNEL_IDS` gains `"safari-tabs"` right after `"bookmarks"`.

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_safari_tabs.py
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
```

Also edit the two ordering assertions in `api/tests/test_source_channels.py:229-232` and `:280-283` to:

```python
    assert ids == [
        "chat-export:claude", "chat-export:chatgpt", "bookmarks", "safari-tabs", "notes",
        "rss", "calendar", "pinterest", "reddit", "x", "telegram", "files",
    ]
```

Run: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/safari-import && api/.venv/bin/python -m pytest api/tests/test_safari_tabs.py api/tests/test_source_channels.py -q -p no:cacheprovider`
Expected: `test_safari_tabs.py` fails on import (`ModuleNotFoundError: api.services.safari_tabs`); the two ordering tests fail.

- [ ] **Step 2: `saved_at.from_cocoa_seconds`**

Insert after `_epoch_seconds_to_iso_date` (`api/services/saved_at.py:80`):

```python
# Core Data / CFAbsoluteTime epoch: seconds since 2001-01-01T00:00:00Z. Safari's
# SQLite stores (CloudTabs.db, History.db) stamp REAL columns in this epoch,
# not the Unix one.
COCOA_EPOCH_OFFSET = 978_307_200.0


def from_cocoa_seconds(raw: object) -> str | None:
    """Core Data seconds -> ``YYYY-MM-DD``; ``None`` for anything unusable.

    Same contract as the sibling converters (G99d): the parser normalises at
    parse time and never carries a raw value downstream. ``<= 0`` is treated
    as "unset" — Safari writes 0 for a column it never populated.
    """
    try:
        seconds = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if seconds <= 0:
        return None
    return _epoch_seconds_to_iso_date(seconds + COCOA_EPOCH_OFFSET)
```

- [ ] **Step 3: `api/services/safari_tabs.py`**

```python
"""Safari iCloud tabs → saved-for-later media items (2026-09-02 brief, extends G30).

The bytes of ``~/Library/Containers/com.apple.Safari/Data/Library/Safari/
CloudTabs.db`` arrive from the companion app (R1: the app reads ``~/Library``
because it is the bundle the user grants Full Disk Access to; the launchd
backend has none and must never try). This module never opens a path under
the user's home — it only ever parses bytes it was handed.

Parsing (R2): the bytes are written to a private temp dir and opened with
stdlib ``sqlite3`` through a read-only URI. Safari keeps the store in WAL
mode, so a bare copy of the main file can be missing whatever still sits in
``CloudTabs.db-wal``; when the caller supplies the sidecar it is written
beside the copy and SQLite replays it. Without a sidecar the copy is opened
``immutable=1`` — nothing can change under us and no ``-shm`` is needed.

Each tab becomes a ``RawItem`` with ``origin="safari-tab"`` (also in ``tags``,
same double-stamp as ``bookmark_sync._tag_origin`` — ``tags`` alone is not a
provenance signal), ``folder`` = the device's display name (so the Feed can
group "everything open on the phone"), and ``added`` from a Core Data
timestamp column when the schema has one. Non-http(s), loopback, ``.local``
and RFC-1918 URLs are dropped: a tab pointing at a dev server is not a save.

Ingest rides ``media_ingestor.ingest_batch`` in ``MAX_BATCH`` slices exactly
like ``connectors/base._run_sync_locked`` (final-review H3 there: a single
``items[:MAX_BATCH]`` call silently drops the tail). Dedup is the existing
``url_index.json`` hash check inside ``ingest_batch`` — a tab that is already
a bookmark entity is reported ``skipped``, never re-created (R3).
"""

from __future__ import annotations

import ipaddress
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

from loguru import logger

from api.services import media_ingestor, saved_at, sync_state
from api.services.media_ingestor import MAX_BATCH, RawItem

ORIGIN = "safari-tab"
CHANNEL_ID = "safari-tabs"
UNKNOWN_DEVICE = "Unknown device"

# Columns a CloudTabs.db has carried across macOS versions for "when was this
# tab last touched", in preference order. Probed with PRAGMA table_info at
# parse time — the schema is Apple's, not ours, so nothing here is assumed.
_TIMESTAMP_COLUMNS = ("last_viewed_time", "date_modified", "last_modified", "creation_date")

IngestFn = Callable[..., Awaitable[tuple[int, int]]]


class SafariTabsError(ValueError):
    """The bytes are not a CloudTabs.db (not SQLite, or missing its tables)."""


@dataclass
class TabsSnapshot:
    """What one CloudTabs.db contains, already filtered to importable tabs."""

    items: list[RawItem]
    devices: list[dict]  # [{"name": str, "count": int}], count desc then name
    skipped: int  # in-batch duplicates + unimportable URLs
    warnings: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.items)


def _is_importable(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = (parsed.hostname or "").lower()
    if not host or host in {"localhost", "0.0.0.0"} or host.endswith(".local"):
        return False
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        return True  # a DNS name, not a literal address


def _timestamp_column(conn: sqlite3.Connection) -> str | None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(cloud_tabs)")}
    return next((c for c in _TIMESTAMP_COLUMNS if c in cols), None)


def load_tabs(db: bytes, wal: bytes | None = None) -> TabsSnapshot:
    """Parse CloudTabs.db bytes (plus an optional ``-wal`` sidecar) into a snapshot."""
    tmp = Path(tempfile.mkdtemp(prefix="cicada-cloudtabs-"))
    try:
        db_path = tmp / "CloudTabs.db"
        db_path.write_bytes(db)
        if wal:
            (tmp / "CloudTabs.db-wal").write_bytes(wal)
        uri = f"file:{db_path}?mode=ro" + ("" if wal else "&immutable=1")
        try:
            conn = sqlite3.connect(uri, uri=True)
        except sqlite3.Error as e:
            raise SafariTabsError(f"Not a SQLite database: {e}") from e
        try:
            try:
                tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            except sqlite3.DatabaseError as e:
                raise SafariTabsError(f"Not a SQLite database: {e}") from e
            if not {"cloud_tabs", "cloud_tab_devices"} <= tables:
                raise SafariTabsError("Not a Safari CloudTabs.db (missing cloud_tabs / cloud_tab_devices)")
            ts_col = _timestamp_column(conn)
            ts_select = f", t.{ts_col}" if ts_col else ", NULL"
            rows = conn.execute(
                "SELECT d.device_name, t.title, t.url" + ts_select +
                " FROM cloud_tabs t LEFT JOIN cloud_tab_devices d ON d.device_uuid = t.device_uuid"
            ).fetchall()
        finally:
            conn.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # Rows arrive in SQLite's scan order and nothing downstream depends on it:
    # `position` is an opaque BLOB in Safari's schema, so there is no honest
    # ORDER BY — the device picker sorts by count, the Feed by its own dates.
    # Only `device_name`, `title`, `url` and the probed timestamp column are
    # named: the fewer Apple columns the SQL mentions, the fewer schema
    # versions can break the parse.
    seen: set[str] = set()
    items: list[RawItem] = []
    counts: dict[str, int] = {}
    skipped = 0
    for device_name, title, url, stamp in rows:
        device = (device_name or "").strip() or UNKNOWN_DEVICE
        if not isinstance(url, str) or not _is_importable(url):
            skipped += 1
            continue
        h = media_ingestor.url_hash(url)
        if h in seen:
            skipped += 1
            continue
        seen.add(h)
        items.append(RawItem(
            url=url,
            title=(title or "").strip() or None,
            tags=[ORIGIN],
            origin=ORIGIN,
            folder=device,
            added=saved_at.from_cocoa_seconds(stamp) if ts_col else None,
        ))
        counts[device] = counts.get(device, 0) + 1

    devices = [{"name": n, "count": counts[n]} for n in sorted(counts, key=lambda n: (-counts[n], n))]
    return TabsSnapshot(items=items, devices=devices, skipped=skipped)


def select(snapshot: TabsSnapshot, devices: list[str] | None) -> list[RawItem]:
    """The tabs to import: every tab, or only those on the named devices (exact name match)."""
    if not devices:
        return list(snapshot.items)
    wanted = set(devices)
    return [i for i in snapshot.items if i.folder in wanted]


async def sync_tabs(
    memory_path: Path,
    db: bytes,
    *,
    wal: bytes | None = None,
    devices: list[str] | None = None,
    ingest_fn: IngestFn | None = None,
) -> dict[str, Any]:
    """Parse, filter, ingest in ``MAX_BATCH`` slices, and stamp ``sync_state``.

    A failure inside ingest is recorded on the channel (``record_error``) so
    ``GET /sources/channels`` says "Last sync failed · …" instead of a stale
    success, and then re-raised — the app just asked for this sync and must
    see the error, unlike a connector's unattended poll.
    """
    fn: IngestFn = ingest_fn or media_ingestor.ingest_batch
    memory_path = Path(memory_path)
    snapshot = load_tabs(db, wal)
    items = select(snapshot, devices)
    selected = set(devices) if devices else {d["name"] for d in snapshot.devices}

    created = skipped = 0
    try:
        for start in range(0, len(items), MAX_BATCH):
            chunk = items[start:start + MAX_BATCH]
            c, d = await fn(chunk, memory_path, from_bookmark_file=True)
            created += c
            skipped += d
    except Exception as e:
        message = f"{type(e).__name__}: {e}"
        logger.warning(f"{CHANNEL_ID} sync failed: {message}")
        sync_state.record_error(memory_path, CHANNEL_ID, message)
        raise

    sync_state.record_sync(
        memory_path, CHANNEL_ID, count=len(items),
        extra={"devices": [d["name"] for d in snapshot.devices if d["name"] in selected]},
    )
    return {
        "new": created,
        "skipped": skipped,
        "seen": len(items),
        "devices": [{**d, "selected": d["name"] in selected} for d in snapshot.devices],
    }
```

(`media_ingestor.url_hash` exists — it is what `_dedup_items` calls at `media_ingestor.py:1657`.)

- [ ] **Step 4: Schemas and router**

After `BookmarkSyncResponse` (`api/models/schemas.py:1237`):

```python
class SafariTabsSyncRequest(CamelModel):
    """Bytes of Safari's CloudTabs.db, read by the app (R1) — plus the WAL
    sidecar when one exists (R2) and an optional exact-name device filter."""

    safari_tabs_db_b64: str
    safari_tabs_wal_b64: Optional[str] = None
    devices: Optional[list[str]] = None


class SafariTabsDevice(CamelModel):
    name: str
    count: int = 0
    selected: Optional[bool] = None


class SafariTabsPreview(CamelModel):
    """`POST /sources/sync-safari-tabs?preview=true` — per-device counts, stages nothing."""

    total: int = 0
    devices: list[SafariTabsDevice] = []
    warnings: list[str] = []


class SafariTabsSyncResponse(CamelModel):
    new: int
    skipped: int
    seen: int = 0
    devices: list[SafariTabsDevice] = []
```

In `api/routers/sources.py`: add `SafariTabsDevice, SafariTabsPreview, SafariTabsSyncRequest, SafariTabsSyncResponse` to the schemas import (`:10-25`) and `safari_tabs` to the services import (`:26-36`). After `sync_bookmarks` (`:351`):

```python
@router.post("/sources/sync-safari-tabs", response_model=None)
async def sync_safari_tabs(
    request: SafariTabsSyncRequest,
    preview: bool = Query(False),
    settings: Settings = Depends(get_settings),
) -> SafariTabsSyncResponse | SafariTabsPreview:
    """Import Safari's iCloud tabs from CloudTabs.db bytes the app read (R1).

    ``?preview=true`` parses and returns per-device counts WITHOUT ingesting
    anything — same staging-free contract as ``/sources/upload?preview=true``
    — so the app can show "iPhone · 202 tabs" before the user picks devices.
    Nothing is cached server-side; the import re-posts the same bytes.
    """
    import base64

    try:
        db = base64.b64decode(request.safari_tabs_db_b64, validate=True)
    except Exception:
        raise HTTPException(status_code=422, detail="Invalid safariTabsDbB64")
    wal = None
    if request.safari_tabs_wal_b64:
        try:
            wal = base64.b64decode(request.safari_tabs_wal_b64, validate=True)
        except Exception:
            raise HTTPException(status_code=422, detail="Invalid safariTabsWalB64")

    if preview:
        try:
            snap = await run_in_threadpool(safari_tabs.load_tabs, db, wal)
        except safari_tabs.SafariTabsError as e:
            raise HTTPException(status_code=422, detail=str(e))
        return SafariTabsPreview(
            total=snap.total,
            devices=[SafariTabsDevice(**d) for d in snap.devices],
            warnings=snap.warnings,
        )

    try:
        result = await safari_tabs.sync_tabs(
            settings.memory_path, db, wal=wal, devices=request.devices
        )
    except safari_tabs.SafariTabsError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return SafariTabsSyncResponse(**result)
```

- [ ] **Step 5: Channel row**

`api/services/channel_registry.py:33-40` — add `"safari-tabs",` right after `"bookmarks",` in `_NON_CONNECTOR_HEAD`. In `build_channels` (`:205-206`) add after the `bookmarks` entry:

```python
        # 2026-09-02 brief: the iPhone's open tabs are their own channel — a
        # different file, a different question ("what is open right now")
        # and its own sync_state entry, written by `safari_tabs.sync_tabs`.
        "safari-tabs": _sync_channel("safari-tabs", "Safari iCloud tabs", state, "tab"),
```

Update the module docstring line 7 to `* ``bookmarks`` / ``safari-tabs`` / ``notes`` -> a ``sync_state.json`` entry exists`.

- [ ] **Step 6: Run, then the full suite**

Run: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/safari-import && api/.venv/bin/python -m pytest api/tests/test_safari_tabs.py api/tests/test_source_channels.py api/tests/test_bookmark_sync.py -q -p no:cacheprovider`
Expected: all pass.
Then `api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider 2>&1 | tail -15` — only the baseline failures.

- [ ] **Step 7: Commit**

```bash
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/safari-import && git add api/services/safari_tabs.py api/services/saved_at.py api/models/schemas.py api/routers/sources.py api/services/channel_registry.py api/tests/test_safari_tabs.py api/tests/test_source_channels.py && git commit -m "feat(sources): Safari iCloud tabs — POST /sources/sync-safari-tabs (+preview), safari_tabs parser, safari-tabs channel (G30)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj"
```

---

### Task 2: Backend — bookmark folder selection, folder-tree preview, per-browser channels

**Files:**
- Modify: `api/services/bookmark_sync.py` (`_tag_origin` region `:89-101`, `sync_bookmarks` `:104-153`)
- Modify: `api/models/schemas.py:1220-1237`
- Modify: `api/routers/sources.py:303-351`
- Modify: `api/services/channel_registry.py:33-45, 82-96, 200-231`
- Modify: `api/tests/test_bookmark_sync.py`, `api/tests/test_source_channels.py`
- Check: `grep -rn "\"bookmarks\"" mcp api/services api/routers` for any other consumer of the channel id (expected: only `channel_registry`, `sync_state` docstring, `sources.py:349`).

**Interfaces:**
- `bookmark_sync.filter_by_folders(items, folders: list[str] | None) -> list[RawItem]`
- `bookmark_sync.folder_tree(items) -> dict` (`{"name","path","count","children"}`, root `path == ""`, name `"All bookmarks"`)
- `bookmark_sync.display_name(segment: str) -> str`
- `bookmark_sync.preview_bookmarks(*, chrome_data=None, safari_data=None) -> dict` → `{"sources": [{"origin","total","tree"}]}`
- `bookmark_sync.sync_bookmarks(..., folders=None)`; result `sources[i]` gains `"channel"`.
- `bookmark_sync.CHANNEL_BY_ORIGIN = {"chrome-bookmark": "chrome-bookmarks", "safari-bookmark": "safari-bookmarks"}`
- `channel_registry._sync_channel(..., legacy_key: str | None = None)`; `CHANNEL_IDS` = `chat-export:claude, chat-export:chatgpt, chrome-bookmarks, safari-bookmarks, safari-tabs, notes, rss, calendar, <adapters>, telegram, files`.

- [ ] **Step 1: Failing tests**

Append to `api/tests/test_bookmark_sync.py` (extend `SAFARI_PLIST_TREE` first — replace the fixture at `:65-86` with a two-folder tree):

```python
SAFARI_PLIST_TREE = {
    "Title": "",
    "WebBookmarkType": "WebBookmarkTypeList",
    "Children": [
        {
            "WebBookmarkType": "WebBookmarkTypeList",
            "Title": "BookmarksBar",
            "Children": [
                {"WebBookmarkType": "WebBookmarkTypeLeaf", "URLString": "https://example.org/bar",
                 "URIDictionary": {"title": "On the bar"}},
                {
                    "WebBookmarkType": "WebBookmarkTypeList",
                    "Title": "Big Folder",
                    "Children": [
                        {"WebBookmarkType": "WebBookmarkTypeLeaf", "URLString": "https://example.org/a",
                         "URIDictionary": {"title": "Page A"}},
                        {"WebBookmarkType": "WebBookmarkTypeLeaf", "URLString": "https://example.org/b",
                         "URIDictionary": {"title": "Page B"}},
                    ],
                },
            ],
        },
        {
            "WebBookmarkType": "WebBookmarkTypeList",
            "Title": "com.apple.ReadingList",
            "Children": [
                {"WebBookmarkType": "WebBookmarkTypeLeaf", "URLString": "https://example.org/rl",
                 "URIDictionary": {"title": "Read later"}},
            ],
        },
    ],
}
```

Then fix the three existing Safari assertions to the new shape: `test_sync_bookmarks_safari_fixture_flows_through` → `result["new"] == 4`, sources `found: 4, new: 4`, and replace the `folder == "Reading List"` line with `assert {i.folder for i in captured} == {"BookmarksBar", "BookmarksBar/Big Folder", "com.apple.ReadingList"}`; `test_sync_bookmarks_both_sources_aggregate` → `result["new"] == 6`; `test_sync_bookmarks_endpoint_inline_safari_data` → `body["new"] == 4`.

Step 2 also adds a `"channel"` key to every `sources` entry, and two existing tests compare that list with `==`, so add it there in the same edit: `test_sync_bookmarks_reports_new_and_skipped_via_injected_ingest_fn` (`:145-151`) → `{"origin": "chrome-bookmark", "channel": "chrome-bookmarks", "found": 2, "new": 1, "skipped": 1}`, and `test_sync_bookmarks_safari_fixture_flows_through` (`:186-188`) → `{"origin": "safari-bookmark", "channel": "safari-bookmarks", "found": 4, "new": 4, "skipped": 0}`. (`test_sync_bookmarks_no_data_provided_ingests_nothing` compares `sources: []` and needs nothing.) Then append:

```python
# --- folder selection + tree preview (2026-09-02 brief, R5) ------------------


def _safari_items():
    from api.services import media_ingestor
    return media_ingestor.parse_safari_bookmarks(plistlib.dumps(SAFARI_PLIST_TREE))


def test_folder_tree_counts_leaves_per_folder_with_display_names():
    tree = bookmark_sync.folder_tree(_safari_items())
    assert tree["name"] == "All bookmarks" and tree["path"] == "" and tree["count"] == 4
    by_path = {c["path"]: c for c in tree["children"]}
    assert set(by_path) == {"BookmarksBar", "com.apple.ReadingList"}
    bar = by_path["BookmarksBar"]
    assert bar["name"] == "Favorites" and bar["count"] == 3
    assert bar["children"] == [
        {"name": "Big Folder", "path": "BookmarksBar/Big Folder", "count": 2, "children": []},
    ]
    rl = by_path["com.apple.ReadingList"]
    assert rl["name"] == "Reading List" and rl["count"] == 1 and rl["children"] == []


def test_folder_tree_puts_rootless_leaves_on_the_root_only():
    items = [RawItem(url="https://example.com/x"), RawItem(url="https://example.com/y", folder="Reading")]
    tree = bookmark_sync.folder_tree(items)
    assert tree["count"] == 2
    assert [c["path"] for c in tree["children"]] == ["Reading"]


def test_filter_by_folders_matches_prefixes_at_segment_boundaries():
    items = _safari_items()
    urls = lambda sel: {i.url for i in sel}
    assert urls(bookmark_sync.filter_by_folders(items, ["BookmarksBar/Big Folder"])) == {
        "https://example.org/a", "https://example.org/b"}
    assert urls(bookmark_sync.filter_by_folders(items, ["BookmarksBar"])) == {
        "https://example.org/bar", "https://example.org/a", "https://example.org/b"}
    assert urls(bookmark_sync.filter_by_folders(items, ["BookmarksBar/Big"])) == set()  # no partial segment
    assert urls(bookmark_sync.filter_by_folders(items, ["bookmarksbar"])) == set()      # case-sensitive
    assert bookmark_sync.filter_by_folders(items, None) == items
    assert bookmark_sync.filter_by_folders(items, []) == items
    assert bookmark_sync.filter_by_folders(items, [""]) == items


def test_sync_bookmarks_with_folders_ingests_only_that_folder(tmp_path):
    captured: list = []

    async def fake_ingest_fn(items, memory_path, from_bookmark_file=False, **kwargs):
        captured.extend(items)
        return len(items), 0

    result = run(bookmark_sync.sync_bookmarks(
        tmp_path / "memory", safari_data=plistlib.dumps(SAFARI_PLIST_TREE),
        folders=["BookmarksBar/Big Folder"], ingest_fn=fake_ingest_fn))
    assert result["sources"] == [
        {"origin": "safari-bookmark", "channel": "safari-bookmarks", "found": 2, "new": 2, "skipped": 0},
    ]
    assert {i.url for i in captured} == {"https://example.org/a", "https://example.org/b"}


def test_sync_bookmarks_without_folders_is_unchanged(tmp_path, monkeypatch):
    def unreachable_filter(*a, **k):
        raise AssertionError("filter_by_folders must not run when no folders are given")

    # `sync_bookmarks` looks the helper up as a module global, so patching the
    # module attribute is what proves the no-folders path never calls it.
    monkeypatch.setattr(bookmark_sync, "filter_by_folders", unreachable_filter)

    async def fake_ingest_fn(items, memory_path, from_bookmark_file=False, **kwargs):
        return len(items), 0

    result = run(bookmark_sync.sync_bookmarks(
        tmp_path / "memory", chrome_data=json.dumps(CHROME_BOOKMARKS_JSON).encode(), ingest_fn=fake_ingest_fn))
    assert result["sources"][0]["found"] == 2 and result["sources"][0]["channel"] == "chrome-bookmarks"


def test_preview_bookmarks_returns_a_tree_per_source_and_stages_nothing(tmp_path):
    preview = bookmark_sync.preview_bookmarks(
        chrome_data=json.dumps(CHROME_BOOKMARKS_JSON).encode(),
        safari_data=plistlib.dumps(SAFARI_PLIST_TREE))
    assert [s["origin"] for s in preview["sources"]] == ["chrome-bookmark", "safari-bookmark"]
    assert preview["sources"][0]["total"] == 2
    assert preview["sources"][0]["tree"]["children"][0]["path"] == "Bookmarks bar"
    assert preview["sources"][1]["total"] == 4
    assert not (tmp_path / "memory").exists()


def test_sync_bookmarks_endpoint_preview_and_folders(tmp_path, monkeypatch):
    _offline_enrich(monkeypatch)
    client, memory = _make_client(tmp_path, monkeypatch)
    safari_b64 = base64.b64encode(plistlib.dumps(SAFARI_PLIST_TREE)).decode()

    preview = client.post("/sources/sync-bookmarks?preview=true", json={"safariDataB64": safari_b64})
    assert preview.status_code == 200, preview.text
    assert preview.json()["sources"][0]["tree"]["count"] == 4
    assert not list((memory / "entities").iterdir()), "preview must stage nothing"

    resp = client.post("/sources/sync-bookmarks",
                       json={"safariDataB64": safari_b64, "folders": ["com.apple.ReadingList"]})
    assert resp.status_code == 200, resp.text
    assert resp.json()["new"] == 1
    from api.services import sync_state
    state = sync_state.read_sync_state(memory)
    assert state["safari-bookmarks"]["count"] == 1
    assert "chrome-bookmarks" not in state and "bookmarks" not in state
```

In `api/tests/test_source_channels.py`: set both ordering assertions (`:229-232`, `:280-283`) to

```python
    assert ids == [
        "chat-export:claude", "chat-export:chatgpt", "chrome-bookmarks", "safari-bookmarks",
        "safari-tabs", "notes", "rss", "calendar", "pinterest", "reddit", "x", "telegram", "files",
    ]
```

then `grep -n '"bookmarks"' api/tests/test_source_channels.py`. Exactly one test reads the row that no longer exists — `test_bookmarks_and_notes_channels_read_sync_state` (`:88-97`, `chans["bookmarks"]` → `KeyError`). Make it the legacy-fallback contract: keep its `record_sync(tmp_path, "bookmarks", count=412, ...)` write and assert `chans["chrome-bookmarks"]` AND `chans["safari-bookmarks"]` each read `connected is True`, `count == 412`, `last_sync == "2026-08-29T10:00:00Z"`, `detail.startswith("412 bookmarks")`, `actions == ["sync"]`, with `chans["notes"]["connected"] is False` unchanged. The two ETag/version tests at `:302` and `:327` also write the `bookmarks` key — leave them: they assert that *any* `sync_state.json` write breaks the ETag, and the key's name is irrelevant there. `:19-28` exercise `sync_state` directly and are untouched. Then add one explicit test:

```python
def test_browser_rows_fall_back_to_the_legacy_bookmarks_entry_until_they_sync(tmp_path):
    sync_state.record_sync(tmp_path, "bookmarks", count=412, at="2026-08-29T10:00:00Z")
    ch = _channels(tmp_path)
    assert ch["chrome-bookmarks"]["connected"] and ch["chrome-bookmarks"]["count"] == 412
    assert ch["safari-bookmarks"]["connected"] and ch["safari-bookmarks"]["count"] == 412
    sync_state.record_sync(tmp_path, "safari-bookmarks", count=7, at="2026-09-02T10:00:00Z")
    bank_index.invalidate()
    ch = _channels(tmp_path)
    assert ch["safari-bookmarks"]["count"] == 7, "its own entry wins once it exists"
    assert ch["chrome-bookmarks"]["count"] == 412, "the other row keeps the legacy value"
```

Run: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/safari-import && api/.venv/bin/python -m pytest api/tests/test_bookmark_sync.py api/tests/test_source_channels.py -q -p no:cacheprovider`
Expected: the new tests fail (`AttributeError: folder_tree`, ordering mismatch).

- [ ] **Step 2: `bookmark_sync.py`**

Add after `_tag_origin` (`:101`):

```python
# Which `sync_state.json` channel each browser's sync stamps (R4). The old
# combined "bookmarks" key is read back as a legacy fallback by
# `channel_registry._sync_channel` and never written again.
CHANNEL_BY_ORIGIN = {"chrome-bookmark": "chrome-bookmarks", "safari-bookmark": "safari-bookmarks"}

# Safari's plist names its top-level folders by internal key; the preview
# shows the names the user sees in Safari while the PATH keeps the raw key
# (R5: the parser's `folder` output is unchanged, so an existing entity's
# `folder:` and a new one's still agree byte for byte).
SAFARI_FOLDER_LABELS = {
    "BookmarksBar": "Favorites",
    "BookmarksMenu": "Bookmarks Menu",
    "com.apple.ReadingList": "Reading List",
}

ROOT_NAME = "All bookmarks"


def display_name(segment: str) -> str:
    return SAFARI_FOLDER_LABELS.get(segment, segment)


def folder_tree(items: list[RawItem]) -> dict[str, Any]:
    """Nested ``{name, path, count, children}`` over the items' ``folder`` paths.

    ``count`` is every leaf at or below that folder, so a parent's count is
    the number the user gets by ticking it. Root-level leaves (``folder is
    None``) count on the root only. Children sort by display name.
    """
    root: dict[str, Any] = {"name": ROOT_NAME, "path": "", "count": 0, "children": {}}
    for item in items:
        if not item.url:
            continue
        root["count"] += 1
        node = root
        segments = [s for s in (item.folder or "").split("/") if s]
        for depth, seg in enumerate(segments):
            path = "/".join(segments[: depth + 1])
            child = node["children"].get(seg)
            if child is None:
                child = node["children"][seg] = {"name": display_name(seg), "path": path, "count": 0, "children": {}}
            child["count"] += 1
            node = child

    def freeze(n: dict[str, Any]) -> dict[str, Any]:
        kids = sorted(n["children"].values(), key=lambda c: c["name"].lower())
        return {"name": n["name"], "path": n["path"], "count": n["count"], "children": [freeze(k) for k in kids]}

    return freeze(root)


def filter_by_folders(items: list[RawItem], folders: list[str] | None) -> list[RawItem]:
    """Keep items whose ``folder`` equals a selected path or sits beneath one (R5).

    Segment-boundary prefix match, case-sensitive; ``""`` selects everything
    (it is the tree root's path). ``None``/``[]`` means "no filter" — the
    pre-existing everything-or-nothing behaviour, unchanged.
    """
    if not folders:
        return items
    wanted = list(folders)
    if "" in wanted:
        return items
    out: list[RawItem] = []
    for item in items:
        f = item.folder or ""
        if any(f == w or f.startswith(w + "/") for w in wanted):
            out.append(item)
    return out


def _batches(chrome_data: bytes | None, safari_data: bytes | None) -> list[tuple[str, list[RawItem]]]:
    batches: list[tuple[str, list[RawItem]]] = []
    if chrome_data is not None:
        batches.append(("chrome-bookmark", _tag_origin(read_chrome_bookmarks(chrome_data), "chrome-bookmark")))
    if safari_data is not None:
        batches.append(("safari-bookmark", _tag_origin(media_ingestor.parse_safari_bookmarks(safari_data), "safari-bookmark")))
    return batches


def preview_bookmarks(*, chrome_data: bytes | None = None, safari_data: bytes | None = None) -> dict[str, Any]:
    """Folder trees per supplied source — parse only, nothing staged (mirrors
    ``media_ingestor.preview_upload``'s contract)."""
    return {"sources": [
        {"origin": origin, "total": sum(1 for i in items if i.url), "tree": folder_tree(items)}
        for origin, items in _batches(chrome_data, safari_data)
    ]}
```

Rewrite `sync_bookmarks` (`:104-153`) so its signature is `sync_bookmarks(memory_path, *, chrome_data=None, safari_data=None, folders: list[str] | None = None, ingest_fn=None)`, it builds `batches = _batches(chrome_data, safari_data)`, applies `items = filter_by_folders(items, folders) if folders else items` at the top of the loop, and every `sources` entry carries `"channel": CHANNEL_BY_ORIGIN[origin]` right after `"origin"` (both the empty and the ingested branch). Add to the docstring: "``folders`` (R5) narrows each source to the selected folder paths before ingest; omitted, the behaviour is byte-identical to before the option existed." Keep `sync_from_local_files` as is.

- [ ] **Step 3: Schemas + router**

`api/models/schemas.py:1220-1237`: add `folders: Optional[list[str]] = None` to `BookmarkSyncRequest` with the comment `# R5 — exact folder-path prefixes at segment boundaries; "" = everything; omitted = everything (unchanged behaviour).`; add `channel: str = ""` to `BookmarkSyncSourceSummary`; and after `BookmarkSyncResponse`:

```python
class BookmarkFolderNode(CamelModel):
    """One folder in a bookmark tree: `count` includes every leaf beneath it."""

    name: str
    path: str
    count: int = 0
    children: list["BookmarkFolderNode"] = []


class BookmarkTreeSource(CamelModel):
    origin: str
    total: int = 0
    tree: BookmarkFolderNode


class BookmarkTreePreview(CamelModel):
    """`POST /sources/sync-bookmarks?preview=true` — folder trees, stages nothing."""

    sources: list[BookmarkTreeSource] = []
```

(`schemas.py` has `from __future__ import annotations`, so the `children: list["BookmarkFolderNode"]` self-reference is resolved lazily by Pydantic v2. If importing the module raises `PydanticUserError: ... is not fully defined`, add `BookmarkFolderNode.model_rebuild()` on the line after the class — that is the only fix needed.)

`api/routers/sources.py:303-351`: signature gains `preview: bool = Query(False)`; after decoding, if `preview`:

```python
    if preview:
        if chrome_data is None and safari_data is None:
            raise HTTPException(status_code=422, detail="Preview needs chromeDataB64 and/or safariDataB64")
        result = await run_in_threadpool(
            bookmark_sync.preview_bookmarks, chrome_data=chrome_data, safari_data=safari_data
        )
        return BookmarkTreePreview(**result)
```

pass `folders=request.folders if request is not None else None` into `bookmark_sync.sync_bookmarks`, and replace the single `record_sync(memory_path, "bookmarks", …)` (`:345-349`) with:

```python
    # R4: one sync_state entry per browser actually synced — the catalog has
    # one tile per browser, and a channel must map to exactly one tile. The
    # legacy combined "bookmarks" key is read as a fallback, never written.
    for s in result.get("sources", []):
        channel = s.get("channel") or bookmark_sync.CHANNEL_BY_ORIGIN.get(s.get("origin", ""))
        if channel:
            sync_state.record_sync(memory_path, channel, count=int(s.get("found") or 0))
```

Set `response_model=None` on the route and annotate the return `-> BookmarkSyncResponse | BookmarkTreePreview`; import `BookmarkTreePreview`. Update the docstring: preview mode + folders.

- [ ] **Step 4: `channel_registry.py`**

`_NON_CONNECTOR_HEAD` (`:33-40`) becomes `("chat-export:claude", "chat-export:chatgpt", "chrome-bookmarks", "safari-bookmarks", "safari-tabs", "notes", "rss", "calendar")`. `_sync_channel` (`:82-96`) gains `legacy_key: str | None = None`:

```python
def _sync_channel(channel_id: str, label: str, state: dict, noun: str, *, legacy_key: str | None = None) -> dict:
    """A local-file sync row. ``legacy_key`` (R4): the browser rows read the
    pre-split combined ``bookmarks`` entry when they have none of their own,
    so an existing bank stays "connected" until each browser syncs on its
    own — a read-time fallback, never a write to ``sync_state.json``."""
    entry = state.get(channel_id) or (state.get(legacy_key) if legacy_key else None) or {}
```

and `build_channels` replaces the `bookmarks` entry with:

```python
        "chrome-bookmarks": _sync_channel("chrome-bookmarks", "Chrome bookmarks", state, "bookmark", legacy_key="bookmarks"),
        "safari-bookmarks": _sync_channel("safari-bookmarks", "Safari bookmarks", state, "bookmark", legacy_key="bookmarks"),
        "safari-tabs": _sync_channel("safari-tabs", "Safari iCloud tabs", state, "tab"),
```

Docstring line 7 → `* ``chrome-bookmarks`` / ``safari-bookmarks`` / ``safari-tabs`` / ``notes`` -> a ``sync_state.json`` entry exists (the two browser rows also read the legacy ``bookmarks`` entry, R4)`. Update `sync_state.py:3-12` docstring shape to name the new keys.

- [ ] **Step 5: Run + full suite**

Run: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/safari-import && api/.venv/bin/python -m pytest api/tests/test_bookmark_sync.py api/tests/test_source_channels.py api/tests/test_safari_tabs.py api/tests/test_bookmarks_safari.py -q -p no:cacheprovider` → all pass. Then the full suite → only baseline failures. Also `grep -rn '"bookmarks"' mcp api/services api/routers` → only `channel_registry.py` (the `legacy_key`) and docstrings.

- [ ] **Step 6: Commit**

```bash
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/safari-import && git add api/services/bookmark_sync.py api/services/channel_registry.py api/services/sync_state.py api/models/schemas.py api/routers/sources.py api/tests/test_bookmark_sync.py api/tests/test_source_channels.py && git commit -m "feat(sources): bookmark folder selection + folder-tree preview on /sources/sync-bookmarks; per-browser channels with legacy fallback (G30, R4/R5)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj"
```

---

### Task 3: App — read the browser files, device picker, folder tree, honest results

**Files:**
- Create: `app/CicadaApp/Sources/CicadaApp/Services/BrowserFiles.swift`
- Create: `app/CicadaApp/Sources/CicadaApp/Models/BrowserImport.swift`
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Capture/Sheets/BrowserImportPanels.swift`
- Modify: `Services/APIClient.swift:1416-1426` (syncBookmarks), `:1553-1556` (add previews next to `previewSource`), `:1806` (SyncAPI conformance), `:312-316` (`BookmarkSyncResult` — add `channel`)
- Modify: `Sync/SyncAPI.swift:93-98`, `Sync/Mutations.swift` (append), `Tests/CicadaAppTests/StoreTests.swift:149-160` (FakeSyncAPI)
- Modify: `Views/Capture/Sheets/AddSourceSheet.swift` (`:13-22` cases, `:26-36` route, `:38-56` title, `:58-76` blurb, `:78-96` icon, `:108-125` channelIds, `:359-437` flow, `:574-580` `syncBookmarks`)
- Modify: `Views/Feed/ConnectedChannelsStrip.swift:163-170`, `Views/Capture/ConnectedChannelRow.swift:169` (icons for the three ids), `Views/Capture/OriginIconography.swift:28-29, 57-58, 82-83` (add `safari-tab`)
- Modify tests: `SourceChannelTests.swift:14, 51, 71-74`, `FeedChannelStripTests.swift:29-38` (every fixture id `bookmarks` → `chrome-bookmarks`; the `forChannel` list at `:38` gains all three browser ids), `ImportCatalogTests.swift:25-34, 121-128, 166-175`, `AddSourceTileTests.swift:52-55`
- Create tests: `Tests/CicadaAppTests/BrowserFilesTests.swift`, `BrowserImportModelTests.swift`; append to `MutationTests.swift`

**Interfaces:**

```swift
enum BrowserFile: CaseIterable { case safariTabsDb, safariTabsWal, safariBookmarks, chromeBookmarks
    var candidatePaths: [URL]        // home-relative; tabs: container path then legacy
    var displayName: String }
enum BrowserFileError: Error, Equatable { case missing(BrowserFile, [String]); case notReadable(BrowserFile, String)
    var userMessage: String; static let fullDiskAccessURL: URL
    static func classify(_ error: Error, file: BrowserFile, path: String) -> BrowserFileError }
enum BrowserFileReader { static func read(_ file: BrowserFile) async throws -> Data   // off-main
                          static func readIfPresent(_ file: BrowserFile) async -> Data? }
struct SafariTabsDevice: Codable, Hashable, Identifiable { name, count, selected: Bool? ; id = name }
struct SafariTabsPreview: Codable { total, devices, warnings }
struct SafariTabsSyncResult: Codable { new, skipped, seen, devices }
struct BookmarkFolderNode: Codable, Hashable, Identifiable { name, path, count, children; id = path }
struct BookmarkTreeSource: Codable { origin, total, tree }
struct BookmarkTreePreview: Codable { sources }
struct BookmarkFolderSelection: Equatable { var paths: Set<String>
    func isSelected(_ path) ; mutating func toggle(_ node: BookmarkFolderNode) ; func selectedCount(in tree) -> Int
    var requestFolders: [String]? }   // nil when root is selected (= everything)
struct SyncSafariTabs: Mutation ; struct SyncBrowserBookmarks: Mutation   // memo carries the result
protocol SyncAPI { … func syncSafariTabs(db: Data, wal: Data?, devices: [String]?) async throws -> SafariTabsSyncResult
                     func syncBookmarks(chromeData: Data?, safariData: Data?, folders: [String]?) async throws -> BookmarkSyncResult }
APIClient: func previewSafariTabs(db:wal:) async throws -> SafariTabsPreview ; func previewBookmarks(chromeData:safariData:) async throws -> BookmarkTreePreview
enum BrowserImportActions { static func syncChannel(_ id: String, store: Store) async throws -> String }
```

- [ ] **Step 1: Failing tests**

```swift
// Tests/CicadaAppTests/BrowserFilesTests.swift
import XCTest
@testable import CicadaApp

/// R1/R9 — the app reads the browser files (it is what the user grants Full
/// Disk Access to); an unreadable file names the exact fix.
final class BrowserFilesTests: XCTestCase {

    func testSafariTabsPrefersTheContainerPathThenTheLegacyOne() {
        let paths = BrowserFile.safariTabsDb.candidatePaths.map(\.path)
        XCTAssertEqual(paths.count, 2)
        XCTAssertTrue(paths[0].hasSuffix("/Library/Containers/com.apple.Safari/Data/Library/Safari/CloudTabs.db"))
        XCTAssertTrue(paths[1].hasSuffix("/Library/Safari/CloudTabs.db"))
        XCTAssertTrue(BrowserFile.safariTabsWal.candidatePaths.allSatisfy { $0.path.hasSuffix("CloudTabs.db-wal") })
        XCTAssertTrue(BrowserFile.safariBookmarks.candidatePaths[0].path.hasSuffix("/Library/Safari/Bookmarks.plist"))
        XCTAssertTrue(BrowserFile.chromeBookmarks.candidatePaths[0].path.hasSuffix("/Library/Application Support/Google/Chrome/Default/Bookmarks"))
    }

    func testNoPermissionBecomesNotReadableWithTheFullDiskAccessFix() {
        let err = NSError(domain: NSCocoaErrorDomain, code: NSFileReadNoPermissionError)
        let classified = BrowserFileError.classify(err, file: .safariTabsDb, path: "/x/CloudTabs.db")
        XCTAssertEqual(classified, .notReadable(.safariTabsDb, "/x/CloudTabs.db"))
        XCTAssertTrue(classified.userMessage.contains("Full Disk Access"))
        XCTAssertTrue(classified.userMessage.contains("System Settings → Privacy & Security → Full Disk Access → Cicada"))
        XCTAssertEqual(BrowserFileError.fullDiskAccessURL.absoluteString,
                       "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles")
    }

    func testMissingFileIsNotAPermissionProblem() {
        let err = NSError(domain: NSCocoaErrorDomain, code: NSFileReadNoSuchFileError)
        let classified = BrowserFileError.classify(err, file: .safariTabsDb, path: "/x/CloudTabs.db")
        XCTAssertEqual(classified, .missing(.safariTabsDb, ["/x/CloudTabs.db"]))
        XCTAssertFalse(classified.userMessage.contains("Full Disk Access"))
        XCTAssertTrue(classified.userMessage.contains("iCloud tabs"))
    }

    func testReadIfPresentReturnsNilForAMissingSidecar() async {
        // Every candidate path lives under the real home; the WAL sidecar is
        // the one file that legitimately may not exist. A permission failure
        // here must NOT be swallowed into nil — only a genuine absence.
        let data = await BrowserFileReader.readIfPresent(.safariTabsWal, candidates: [URL(fileURLWithPath: "/nonexistent/CloudTabs.db-wal")])
        XCTAssertNil(data)
    }
}
```

```swift
// Tests/CicadaAppTests/BrowserImportModelTests.swift
import XCTest
@testable import CicadaApp

final class BrowserImportModelTests: XCTestCase {

    private func node(_ path: String, _ count: Int, _ children: [BookmarkFolderNode] = []) -> BookmarkFolderNode {
        BookmarkFolderNode(name: path.split(separator: "/").last.map(String.init) ?? "All bookmarks",
                           path: path, count: count, children: children)
    }

    private var tree: BookmarkFolderNode {
        node("", 6, [
            node("BookmarksBar", 5, [node("BookmarksBar/Big Folder", 4)]),
            node("com.apple.ReadingList", 1),
        ])
    }

    func testDefaultSelectionIsEverythingAndSendsNoFilter() {
        let sel = BookmarkFolderSelection.all
        XCTAssertNil(sel.requestFolders)
        XCTAssertEqual(sel.selectedCount(in: tree), 6)
        XCTAssertTrue(sel.isSelected(""))
        XCTAssertTrue(sel.isSelected("BookmarksBar/Big Folder"), "a selected parent covers its children")
    }

    func testTogglingOneFolderNarrowsTheRequest() {
        var sel = BookmarkFolderSelection.all
        sel.toggle(tree)                                   // untick root → nothing
        XCTAssertEqual(sel.selectedCount(in: tree), 0)
        XCTAssertEqual(sel.requestFolders, [])
        sel.toggle(tree.children[0].children[0])           // tick Big Folder
        XCTAssertEqual(sel.requestFolders, ["BookmarksBar/Big Folder"])
        XCTAssertEqual(sel.selectedCount(in: tree), 4)
        XCTAssertFalse(sel.isSelected("BookmarksBar"))
    }

    func testTogglingAParentClearsItsChildrenFromTheRequest() {
        var sel = BookmarkFolderSelection(paths: ["BookmarksBar/Big Folder"])
        sel.toggle(tree.children[0])                       // tick Favorites
        XCTAssertEqual(sel.requestFolders, ["BookmarksBar"], "the child is implied, not sent twice")
        XCTAssertEqual(sel.selectedCount(in: tree), 5)
    }

    func testDeviceSummaryLine() {
        let devices = [SafariTabsDevice(name: "Bob's iPhone", count: 202), SafariTabsDevice(name: "Bob's MacBook", count: 0)]
        XCTAssertEqual(SafariTabsDevice.line(devices[0]), "Bob's iPhone · 202 tabs")
        XCTAssertEqual(SafariTabsDevice.line(devices[1]), "Bob's MacBook · 0 tabs")
        XCTAssertEqual(SafariTabsDevice.line(SafariTabsDevice(name: "iPad", count: 1)), "iPad · 1 tab")
    }

    func testSyncSummaries() {
        XCTAssertEqual(BrowserImportSummary.tabs(SafariTabsSyncResult(new: 180, skipped: 22, seen: 202, devices: [])),
                       "180 new · 22 already saved · 202 tabs seen")
        XCTAssertEqual(BrowserImportSummary.bookmarks(BookmarkSyncResult(new: 0, skipped: 500, sources: [])),
                       "Nothing new · 500 already saved")
    }

    func testDecodesTheBackendShapes() throws {
        let preview = try JSONDecoder().decode(SafariTabsPreview.self, from: Data(#"{"total":3,"devices":[{"name":"Bob's iPhone","count":3}],"warnings":[]}"#.utf8))
        XCTAssertEqual(preview.devices.first?.count, 3)
        let tree = try JSONDecoder().decode(BookmarkTreePreview.self, from: Data(#"{"sources":[{"origin":"safari-bookmark","total":1,"tree":{"name":"All bookmarks","path":"","count":1,"children":[{"name":"Reading List","path":"com.apple.ReadingList","count":1,"children":[]}]}}]}"#.utf8))
        XCTAssertEqual(tree.sources[0].tree.children[0].name, "Reading List")
    }
}
```

Append to `MutationTests.swift`:

```swift
    // MARK: - Browser syncs (R8)

    func testSyncSafariTabsRecordsTheWriteKeepsTheResultAndRefreshesChannels() async {
        let api = FakeSyncAPI()
        let store = Store(cache: tempCache(), api: api)
        api.replies[.channels] = .notModified
        api.replies[.sources] = .notModified
        let mutation = SyncSafariTabs(db: Data("db".utf8), wal: nil, devices: ["Bob's iPhone"])
        let ok = await store.perform(mutation)
        XCTAssertTrue(ok)
        XCTAssertEqual(api.writes, ["syncSafariTabs:1"])
        XCTAssertEqual(mutation.result?.new, 1)
        XCTAssertTrue(api.calls.contains(.channels))
    }

    func testSyncBrowserBookmarksFailureToasts() async {
        let api = FakeSyncAPI()
        let store = Store(cache: tempCache(), api: api)
        api.failWrites = true
        api.replies[.channels] = .notModified
        api.replies[.sources] = .notModified
        let ok = await store.perform(SyncBrowserBookmarks(chromeData: nil, safariData: Data("p".utf8), folders: ["x"]))
        XCTAssertFalse(ok)
        XCTAssertEqual(store.toast, "Couldn't sync those bookmarks — nothing was imported")
    }
```

In `StoreTests.swift` `FakeSyncAPI` add (after `unsubscribeCalendar`, `:158-160`):

```swift
    func syncSafariTabs(db: Data, wal: Data?, devices: [String]?) async throws -> SafariTabsSyncResult {
        try await record("syncSafariTabs:\(devices?.count ?? 0)")
        return SafariTabsSyncResult(new: 1, skipped: 0, seen: 1, devices: [])
    }
    func syncBookmarks(chromeData: Data?, safariData: Data?, folders: [String]?) async throws -> BookmarkSyncResult {
        try await record("syncBookmarks:\(folders?.count ?? 0)")
        return BookmarkSyncResult(new: 1, skipped: 0, sources: [])
    }
```

Existing-test edits: `SourceChannelTests.swift:71-74` → the 13-id list from Task 2, and its JSON fixture at `:14` (`"id":"bookmarks","label":"Chrome & Safari bookmarks"` → `"id":"chrome-bookmarks","label":"Chrome bookmarks"`) with the sort expectation at `:51` following (`["rss", "chrome-bookmarks", "telegram"]`) — the row's label no longer exists on the backend and Task 5's final grep must find it nowhere; `FeedChannelStripTests.swift:29` and `:32` fixture `"bookmarks"` → `"chrome-bookmarks"`, and the `forChannel` list at `:38` → `["rss", "calendar", "chrome-bookmarks", "safari-bookmarks", "safari-tabs", "notes", "telegram", "chat-export:claude", "chat-export:chatgpt", "files"]`; `ImportCatalogTests.swift:26` → `XCTAssertEqual(AddSourceTile.safari.route, .sync); XCTAssertEqual(AddSourceTile.chrome.route, .sync)`; `:123-125` list → replace `"browserBookmarks"` with `"safari", "chrome"`; `:171-172` → replace `.browserBookmarks` with `.safari, .chrome`; add `XCTAssertNil(AddSourceTile(rawValue: "browserBookmarks"))` next to the retired-tile test at `:130-132`. `AddSourceTileTests.swift` needs no change (new tiles have no vendors).

Run: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/safari-import/app/CicadaApp && swift build --build-tests 2>&1 | tail -5` → compile errors on the new types (expected).

- [ ] **Step 2: `BrowserFiles.swift`**

```swift
import Foundation

/// The four files this Mac's browsers keep under `~/Library` that Cicada
/// imports from. **The app reads them, the backend parses the bytes (R1)**:
/// the launchd backend has no Full Disk Access and must never try — the app
/// bundle is the thing the user grants it to.
enum BrowserFile: CaseIterable {
    case safariTabsDb, safariTabsWal, safariBookmarks, chromeBookmarks

    /// Where the file lives, most-likely first. iCloud tabs moved into
    /// Safari's container on modern macOS; the legacy path is kept second
    /// (R2 — verified by the orchestrator, not assumed).
    var candidatePaths: [URL] {
        let home = FileManager.default.homeDirectoryForCurrentUser
        let container = home.appendingPathComponent("Library/Containers/com.apple.Safari/Data/Library/Safari")
        let legacy = home.appendingPathComponent("Library/Safari")
        switch self {
        case .safariTabsDb:
            return [container.appendingPathComponent("CloudTabs.db"), legacy.appendingPathComponent("CloudTabs.db")]
        case .safariTabsWal:
            return [container.appendingPathComponent("CloudTabs.db-wal"), legacy.appendingPathComponent("CloudTabs.db-wal")]
        case .safariBookmarks:
            return [legacy.appendingPathComponent("Bookmarks.plist")]
        case .chromeBookmarks:
            return [home.appendingPathComponent("Library/Application Support/Google/Chrome/Default/Bookmarks")]
        }
    }

    var displayName: String {
        switch self {
        case .safariTabsDb, .safariTabsWal: "Safari iCloud tabs"
        case .safariBookmarks: "Safari bookmarks"
        case .chromeBookmarks: "Chrome bookmarks"
        }
    }
}

/// Why a read failed, with the exact fix (R9). Only two cases matter to the
/// user: "grant Full Disk Access" and "there is nothing here yet".
enum BrowserFileError: Error, Equatable {
    case missing(BrowserFile, [String])
    case notReadable(BrowserFile, String)

    static let fullDiskAccessURL = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles")!

    static func classify(_ error: Error, file: BrowserFile, path: String) -> BrowserFileError {
        let ns = error as NSError
        if ns.domain == NSCocoaErrorDomain && ns.code == NSFileReadNoSuchFileError { return .missing(file, [path]) }
        if ns.domain == NSPOSIXErrorDomain && ns.code == Int(ENOENT) { return .missing(file, [path]) }
        return .notReadable(file, path)
    }

    var userMessage: String {
        switch self {
        case .notReadable(let file, let path):
            return "Cicada can't read \(path) (\(file.displayName)). Allow it under System Settings → Privacy & Security → Full Disk Access → Cicada, then try again."
        case .missing(let file, _):
            switch file {
            case .safariTabsDb, .safariTabsWal:
                return "No iCloud tabs on this Mac yet — turn on Safari in iCloud settings on both devices and wait for a sync."
            case .safariBookmarks:
                return "Safari has no Bookmarks.plist on this Mac."
            case .chromeBookmarks:
                return "Chrome isn't installed, or has no default profile bookmarks yet."
            }
        }
    }
}

/// Off-main file reads. `read` tries every candidate path in order and
/// reports the LAST error only when all of them failed; a permission error
/// on the first candidate is not masked by a "missing" on the second — the
/// permission error wins, because it is the one with a fix.
enum BrowserFileReader {
    static func read(_ file: BrowserFile, candidates: [URL]? = nil) async throws -> Data {
        let urls = candidates ?? file.candidatePaths
        return try await Task.detached(priority: .userInitiated) {
            var firstPermissionError: BrowserFileError?
            for url in urls {
                do {
                    return try Data(contentsOf: url, options: [.uncached])
                } catch {
                    let classified = BrowserFileError.classify(error, file: file, path: url.path)
                    if case .notReadable = classified, firstPermissionError == nil { firstPermissionError = classified }
                }
            }
            throw firstPermissionError ?? BrowserFileError.missing(file, urls.map(\.path))
        }.value
    }

    /// For the WAL sidecar: nil when genuinely absent, but a permission
    /// failure still throws through `read` semantics — so call this only
    /// AFTER the main file read succeeded (same directory, same grant).
    static func readIfPresent(_ file: BrowserFile, candidates: [URL]? = nil) async -> Data? {
        let urls = candidates ?? file.candidatePaths
        let existing = urls.filter { FileManager.default.fileExists(atPath: $0.path) }
        guard !existing.isEmpty else { return nil }
        return try? await read(file, candidates: existing)
    }
}
```

- [ ] **Step 3: `Models/BrowserImport.swift`**

```swift
import Foundation

struct SafariTabsDevice: Codable, Hashable, Identifiable {
    let name: String
    let count: Int
    var selected: Bool? = nil
    var id: String { name }

    init(name: String, count: Int, selected: Bool? = nil) { self.name = name; self.count = count; self.selected = selected }

    /// "iPhone · 202 tabs" — the device picker row.
    static func line(_ d: SafariTabsDevice) -> String { "\(d.name) · \(d.count) \(d.count == 1 ? "tab" : "tabs")" }
}

struct SafariTabsPreview: Codable {
    let total: Int
    let devices: [SafariTabsDevice]
    let warnings: [String]
}

struct SafariTabsSyncResult: Codable {
    let new: Int
    let skipped: Int
    let seen: Int
    let devices: [SafariTabsDevice]
}

/// Mirror of `schemas.BookmarkFolderNode`. `id` is the path — unique by
/// construction and stable across previews of the same file.
struct BookmarkFolderNode: Codable, Hashable, Identifiable {
    let name: String
    let path: String
    let count: Int
    let children: [BookmarkFolderNode]
    var id: String { path }
}

struct BookmarkTreeSource: Codable { let origin: String; let total: Int; let tree: BookmarkFolderNode }
struct BookmarkTreePreview: Codable { let sources: [BookmarkTreeSource] }

/// Which folders are ticked (R5). Stored as the MINIMAL set of paths — a
/// ticked parent implies its children — and sent to the backend as-is.
/// `""` (the root) means everything and sends no filter at all, which is
/// byte-identical to the pre-existing sync.
struct BookmarkFolderSelection: Equatable {
    var paths: Set<String>

    static let all = BookmarkFolderSelection(paths: [""])

    func isSelected(_ path: String) -> Bool {
        paths.contains("") || paths.contains(path) || paths.contains { $0 != "" && path.hasPrefix($0 + "/") }
    }

    mutating func toggle(_ node: BookmarkFolderNode) {
        if isSelected(node.path) {
            // Untick: drop the node and anything beneath it. If it was only
            // covered by an ancestor, the whole ancestor comes off — the
            // user is narrowing, not carving; they re-tick siblings.
            paths = paths.filter { !($0 == node.path || $0.hasPrefix(node.path + "/") || node.path.hasPrefix($0 + "/") || $0 == "") }
        } else {
            paths = paths.filter { !$0.hasPrefix(node.path + "/") }
            paths.insert(node.path)
        }
    }

    func selectedCount(in tree: BookmarkFolderNode) -> Int {
        if isSelected(tree.path) { return tree.count }
        return tree.children.reduce(0) { $0 + selectedCount(in: $1) }
    }

    /// nil = everything (no `folders` key on the wire); [] = nothing selected.
    var requestFolders: [String]? { paths.contains("") ? nil : paths.sorted() }
}

enum BrowserImportSummary {
    static func tabs(_ r: SafariTabsSyncResult) -> String {
        let newPart = r.new == 0 ? "Nothing new" : "\(r.new) new"
        return "\(newPart) · \(r.skipped) already saved · \(r.seen) \(r.seen == 1 ? "tab" : "tabs") seen"
    }
    static func bookmarks(_ r: BookmarkSyncResult) -> String {
        "\(r.new == 0 ? "Nothing new" : "\(r.new) new") · \(r.skipped) already saved"
    }
}
```

Note the `toggle` untick rule when the node is only covered by an ancestor: the test `testTogglingOneFolderNarrowsTheRequest` unticks the root (`""`) so `paths` becomes empty; that is the documented behaviour.

- [ ] **Step 4: API + SyncAPI + Mutations**

`APIClient.swift:312-316` → `BookmarkSyncSourceSummary` gains `let channel: String?` (tolerant: `decodeIfPresent`; check its declaration near `:305` and add `enum CodingKeys` only if needed). `syncBookmarks` (`:1421-1426`) gains `folders: [String]? = nil` and `if let folders { body["folders"] = folders }`. After `previewSource` (`:1556`):

```swift
    /// `POST /sources/sync-safari-tabs?preview=true` — per-device tab counts
    /// from bytes the app read (R1). Stages nothing.
    func previewSafariTabs(db: Data, wal: Data?) async throws -> SafariTabsPreview {
        var body: [String: Any] = ["safariTabsDbB64": db.base64EncodedString()]
        if let wal { body["safariTabsWalB64"] = wal.base64EncodedString() }
        return try await post("/sources/sync-safari-tabs?preview=true", body: body)
    }

    func syncSafariTabs(db: Data, wal: Data?, devices: [String]?) async throws -> SafariTabsSyncResult {
        var body: [String: Any] = ["safariTabsDbB64": db.base64EncodedString()]
        if let wal { body["safariTabsWalB64"] = wal.base64EncodedString() }
        if let devices { body["devices"] = devices }
        return try await post("/sources/sync-safari-tabs", body: body)
    }

    /// `POST /sources/sync-bookmarks?preview=true` — folder trees with leaf counts. Stages nothing.
    func previewBookmarks(chromeData: Data?, safariData: Data?) async throws -> BookmarkTreePreview {
        var body: [String: Any] = [:]
        if let chromeData { body["chromeDataB64"] = chromeData.base64EncodedString() }
        if let safariData { body["safariDataB64"] = safariData.base64EncodedString() }
        return try await post("/sources/sync-bookmarks?preview=true", body: body)
    }
```

`SyncAPI.swift:96` — add the two write signatures from the Interfaces block. `APIClient`'s `extension APIClient: SyncAPI` (`:1806`) needs no body for `syncSafariTabs` (the method above satisfies it) and `syncBookmarks(chromeData:safariData:folders:)` is satisfied by the extended method. Append to `Mutations.swift`:

```swift
// MARK: - Browser syncs (R8)

/// A local-file sync has nothing to paint optimistically, but routing it
/// through `Store.perform` gives it the same failure toast and channel
/// reconcile every other write gets. The server's honest `{new, skipped}`
/// lands in `result` so the panel can show it (the `UnsubscribeFeed` memo pattern).
struct SyncSafariTabs: Mutation {
    let db: Data
    let wal: Data?
    let devices: [String]?
    private let memo = MutationMemo<SafariTabsSyncResult>()

    init(db: Data, wal: Data?, devices: [String]?) { self.db = db; self.wal = wal; self.devices = devices }

    var result: SafariTabsSyncResult? { memo.value }
    func optimistic(_ store: Store) async {}
    func request(_ api: any SyncAPI) async throws { memo.value = try await api.syncSafariTabs(db: db, wal: wal, devices: devices) }
    func rollback(_ store: Store) async {}
    var failureMessage: String { "Couldn't import those tabs — nothing was imported" }
    var refreshDomains: Set<SyncDomain> { [.channels, .sources, .status] }
}

struct SyncBrowserBookmarks: Mutation {
    let chromeData: Data?
    let safariData: Data?
    let folders: [String]?
    private let memo = MutationMemo<BookmarkSyncResult>()

    init(chromeData: Data?, safariData: Data?, folders: [String]?) { self.chromeData = chromeData; self.safariData = safariData; self.folders = folders }

    var result: BookmarkSyncResult? { memo.value }
    func optimistic(_ store: Store) async {}
    func request(_ api: any SyncAPI) async throws { memo.value = try await api.syncBookmarks(chromeData: chromeData, safariData: safariData, folders: folders) }
    func rollback(_ store: Store) async {}
    var failureMessage: String { "Couldn't sync those bookmarks — nothing was imported" }
    var refreshDomains: Set<SyncDomain> { [.channels, .sources, .status] }
}
```

(If `Store.refresh` does not accept `.status` in a set, check `Store.swift:225-276` — it does, via `refreshStatus()` at `:342`.)

- [ ] **Step 5: Tiles and flows in `AddSourceSheet.swift`**

Replace `browserBookmarks` with two cases: in the enum (`:14`) `case safari, chrome, appleNotes, telegram`; `route` → `.safari, .chrome, .appleNotes: .sync`; `title` → `"Safari"`, `"Chrome"`; `blurb` → `.safari: "Bookmarks by folder, Reading List, and every tab open on your iPhone."`, `.chrome: "Bookmarks by folder, read straight off this Mac."`; `icon` → `.safari: "safari"`, `.chrome: "globe"`; `channelIds` → `.safari: ["safari-bookmarks", "safari-tabs"]`, `.chrome: ["chrome-bookmarks"]` (update the doc comment: the two Safari rows both manage from the Safari tile); `logoName` → both `nil` (Task 4 adds `brandGlyph`). Update the `channelIds` doc comment paragraph about a channel mapping to exactly one tile.

Flow (`:423-430`) becomes:

```swift
            case .safari:
                SafariImportPanel()
            case .chrome:
                BookmarkFolderPanel(browser: .chrome)
```

Delete `syncBookmarks()` (`:574-580`). `ConnectedChannelsStrip.sync` (`:163-170`) becomes:

```swift
    private static func sync(_ channel: SourceChannel, store: Store) async throws -> String {
        if channel.id == "notes" {
            let r = try await APIClient.shared.syncNotes()
            return "\(r.new) new · \(r.skipped) unchanged"
        }
        return try await BrowserImportActions.syncChannel(channel.id, store: store)
    }
```

(and the call at `:135` passes `store:`). `ConnectedChannelRow.icon(for:)` (`:169-183`) — replace `case "bookmarks": "globe"` with `case "chrome-bookmarks": "globe"` and `case "safari-bookmarks", "safari-tabs": "safari"`; make the matching edit in `tint(for:)` right below it (`:185`) — Chrome `Color(hex: 0x4285F4)`, Safari `Color(hex: 0x00A2E8)`, the same values `OriginIconography.color(for:)` uses. `OriginIconography` — add `case "safari-tab": "Safari tab"` (`:29`), `"safari-tab"` to the `safari` symbol line (`:58`) and to the Safari colour line (`:83`).

- [ ] **Step 6: `BrowserImportPanels.swift`**

```swift
import AppKit
import SwiftUI

/// Shared by the Safari/Chrome flows and the Feed strip's "Sync now" (R1):
/// read the file(s) off-main, POST bytes through `Store.perform`, return the
/// honest one-line result. Throws `BrowserFileError` (with the fix) or the
/// API error.
///
/// `@MainActor` because `Store` is, and — unlike the panels below, which
/// inherit it from `View` — a bare enum gets no isolation inference: without
/// it `store.toast` is an error under Swift 5.10 ("main actor-isolated
/// property referenced from a nonisolated context"). The file reads still
/// happen off-main inside `BrowserFileReader.read`'s detached task.
enum BrowserImportActions {
    @MainActor
    static func syncChannel(_ id: String, store: Store) async throws -> String {
        switch id {
        case "safari-tabs":
            let db = try await BrowserFileReader.read(.safariTabsDb)
            let wal = await BrowserFileReader.readIfPresent(.safariTabsWal)
            let m = SyncSafariTabs(db: db, wal: wal, devices: nil)
            guard await store.perform(m), let r = m.result else { throw ImportActionError.failed(store.toast ?? "Sync failed") }
            return BrowserImportSummary.tabs(r)
        case "safari-bookmarks":
            let data = try await BrowserFileReader.read(.safariBookmarks)
            let m = SyncBrowserBookmarks(chromeData: nil, safariData: data, folders: nil)
            guard await store.perform(m), let r = m.result else { throw ImportActionError.failed(store.toast ?? "Sync failed") }
            return BrowserImportSummary.bookmarks(r)
        case "chrome-bookmarks":
            let data = try await BrowserFileReader.read(.chromeBookmarks)
            let m = SyncBrowserBookmarks(chromeData: data, safariData: nil, folders: nil)
            guard await store.perform(m), let r = m.result else { throw ImportActionError.failed(store.toast ?? "Sync failed") }
            return BrowserImportSummary.bookmarks(r)
        default:
            throw ImportActionError.failed("Unknown channel \(id)")
        }
    }

    enum ImportActionError: Error, LocalizedError {
        case failed(String)
        var errorDescription: String? { if case .failed(let m) = self { return m }; return nil }
    }
}

/// The Full-Disk-Access fix, shown exactly where the read failed (R9).
struct FullDiskAccessHint: View {
    let error: BrowserFileError
    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            Text(error.userMessage)
                .font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.danger)
                .fixedSize(horizontal: false, vertical: true)
            if case .notReadable = error {
                Button("Open Full Disk Access settings") { NSWorkspace.shared.open(BrowserFileError.fullDiskAccessURL) }
                    .buttonStyle(.bordered)
                    .accessibilityLabel("Open System Settings at Full Disk Access")
            }
        }
    }
}

/// Where a browser import is: read → preview → pick → import → done.
enum BrowserImportStage: Equatable {
    case idle, reading, previewing, ready, importing
    case done(String)
    case fileError(BrowserFileError)
    case failed(String)
}

/// Safari: two sub-flows on one panel — bookmark folders and iCloud tabs —
/// each with its own preview, selection and result. Reads happen on
/// appear so the counts are visible before any decision.
struct SafariImportPanel: View {
    @State private var picked: Sub = .bookmarks
    enum Sub: String, CaseIterable, Identifiable { case bookmarks, tabs; var id: String { rawValue } }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            Picker("Import", selection: $picked) {
                Text("Bookmarks & Reading List").tag(Sub.bookmarks)
                Text("iCloud tabs").tag(Sub.tabs)
            }
            .pickerStyle(.segmented)
            .accessibilityLabel("Choose what to import from Safari")
            switch picked {
            case .bookmarks: BookmarkFolderPanel(browser: .safari)
            case .tabs: SafariTabsPanel()
            }
        }
    }
}

struct SafariTabsPanel: View {
    @Environment(Store.self) private var store
    @State private var stage: BrowserImportStage = .idle
    @State private var preview: SafariTabsPreview?
    @State private var selected: Set<String> = []
    @State private var bytes: (db: Data, wal: Data?)?
    @State private var task: Task<Void, Never>?

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            Text("Every tab open in Safari on your other devices, as iCloud last synced them. Only tabs Cicada hasn't saved become new items.")
                .font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            switch stage {
            case .idle, .reading, .previewing:
                HStack(spacing: CicadaTheme.spacingSM) { ProgressView().controlSize(.small); Text(stage == .previewing ? "Counting tabs…" : "Reading Safari's tab list…").font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary) }
            case .ready, .importing:
                if let preview {
                    ForEach(preview.devices) { device in
                        Toggle(isOn: Binding(get: { selected.contains(device.name) },
                                             set: { on in if on { selected.insert(device.name) } else { selected.remove(device.name) } })) {
                            Text(SafariTabsDevice.line(device)).font(CicadaTheme.bodyFont)
                        }
                        .toggleStyle(.checkbox)
                        .disabled(stage == .importing || device.count == 0)
                        .accessibilityLabel(SafariTabsDevice.line(device))
                    }
                    HStack(spacing: CicadaTheme.spacingSM) {
                        Button(stage == .importing ? "Importing…" : "Import \(selectedCount) tabs") { importSelected() }
                            .buttonStyle(.borderedProminent)
                            .disabled(stage == .importing || selectedCount == 0)
                            .accessibilityLabel("Import \(selectedCount) tabs")
                        if stage == .importing { ProgressView().controlSize(.small) }
                    }
                }
            case .done(let summary):
                Text(summary).font(.system(size: 13, weight: .semibold)).foregroundStyle(CicadaTheme.success)
                Text("Processed on the next Sleep cycle.").font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                Button("Import again") { load() }.buttonStyle(.bordered)
            case .fileError(let error):
                FullDiskAccessHint(error: error)
                Button("Try again") { load() }.buttonStyle(.bordered)
            case .failed(let message):
                Text(message).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.danger)
                Button("Try again") { load() }.buttonStyle(.bordered)
            }
        }
        .onAppear { if stage == .idle { load() } }
        .onDisappear { task?.cancel() }
    }

    private var selectedCount: Int {
        (preview?.devices ?? []).filter { selected.contains($0.name) }.reduce(0) { $0 + $1.count }
    }

    private func load() {
        task?.cancel()
        stage = .reading
        task = Task {
            do {
                let db = try await BrowserFileReader.read(.safariTabsDb)
                let wal = await BrowserFileReader.readIfPresent(.safariTabsWal)
                guard !Task.isCancelled else { return }
                stage = .previewing
                let p = try await APIClient.shared.previewSafariTabs(db: db, wal: wal)
                guard !Task.isCancelled else { return }
                bytes = (db, wal)
                preview = p
                selected = Set(p.devices.filter { $0.count > 0 }.map(\.name))
                stage = .ready
            } catch let e as BrowserFileError {
                stage = .fileError(e)
            } catch {
                stage = .failed(AddSourceSheet.friendlyError(error))
            }
        }
    }

    private func importSelected() {
        guard let bytes, stage == .ready else { return }
        stage = .importing
        let devices = Array(selected).sorted()
        task = Task {
            let m = SyncSafariTabs(db: bytes.db, wal: bytes.wal, devices: devices)
            let ok = await store.perform(m)
            guard !Task.isCancelled else { return }
            if ok, let r = m.result { stage = .done(BrowserImportSummary.tabs(r)) }
            else { stage = .failed(store.toast ?? "Import failed") }
        }
    }
}

/// Folder tree with checkboxes for one browser's bookmarks (R5). Default:
/// everything ticked; the user can narrow to one folder.
struct BookmarkFolderPanel: View {
    enum Browser { case safari, chrome }
    let browser: Browser

    @Environment(Store.self) private var store
    @State private var stage: BrowserImportStage = .idle
    @State private var tree: BookmarkFolderNode?
    @State private var selection = BookmarkFolderSelection.all
    @State private var data: Data?
    @State private var task: Task<Void, Never>?

    private var file: BrowserFile { browser == .safari ? .safariBookmarks : .chromeBookmarks }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            Text(browser == .safari
                 ? "Tick the folders to import — Favorites, Bookmarks Menu and Reading List are all here. Only URLs Cicada hasn't seen become new items."
                 : "Tick the folders to import from Chrome's default profile. Only URLs Cicada hasn't seen become new items.")
                .font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            switch stage {
            case .idle, .reading, .previewing:
                HStack(spacing: CicadaTheme.spacingSM) { ProgressView().controlSize(.small); Text("Reading bookmarks…").font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary) }
            case .ready, .importing:
                if let tree {
                    ScrollView {
                        VStack(alignment: .leading, spacing: 2) { folderRows(tree, depth: 0) }
                    }
                    .frame(maxHeight: 220)
                    HStack(spacing: CicadaTheme.spacingSM) {
                        Button(stage == .importing ? "Importing…" : "Import \(selection.selectedCount(in: tree)) bookmarks") { importSelected() }
                            .buttonStyle(.borderedProminent)
                            .disabled(stage == .importing || selection.selectedCount(in: tree) == 0)
                            .accessibilityLabel("Import \(selection.selectedCount(in: tree)) bookmarks")
                        if stage == .importing { ProgressView().controlSize(.small) }
                    }
                }
            case .done(let summary):
                Text(summary).font(.system(size: 13, weight: .semibold)).foregroundStyle(CicadaTheme.success)
                Text("Processed on the next Sleep cycle.").font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                Button("Import again") { load() }.buttonStyle(.bordered)
            case .fileError(let error):
                FullDiskAccessHint(error: error)
                Button("Try again") { load() }.buttonStyle(.bordered)
            case .failed(let message):
                Text(message).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.danger)
                Button("Try again") { load() }.buttonStyle(.bordered)
            }
        }
        .onAppear { if stage == .idle { load() } }
        .onDisappear { task?.cancel() }
    }

    @ViewBuilder
    private func folderRows(_ node: BookmarkFolderNode, depth: Int) -> some View {
        Toggle(isOn: Binding(get: { selection.isSelected(node.path) }, set: { _ in selection.toggle(node) })) {
            HStack {
                Text(node.name).font(CicadaTheme.bodyFont)
                Spacer()
                Text("\(node.count)").font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
            }
        }
        .toggleStyle(.checkbox)
        .padding(.leading, CGFloat(depth) * 16)
        .disabled(stage == .importing)
        .accessibilityLabel("\(node.name), \(node.count) bookmarks")
        ForEach(node.children) { child in folderRows(child, depth: depth + 1) }
    }

    private func load() {
        task?.cancel()
        stage = .reading
        task = Task {
            do {
                let bytes = try await BrowserFileReader.read(file)
                guard !Task.isCancelled else { return }
                stage = .previewing
                let p = try await APIClient.shared.previewBookmarks(
                    chromeData: browser == .chrome ? bytes : nil, safariData: browser == .safari ? bytes : nil)
                guard !Task.isCancelled else { return }
                data = bytes
                tree = p.sources.first?.tree
                selection = .all
                stage = tree == nil ? .failed("No bookmarks found in that file.") : .ready
            } catch let e as BrowserFileError {
                stage = .fileError(e)
            } catch {
                stage = .failed(AddSourceSheet.friendlyError(error))
            }
        }
    }

    private func importSelected() {
        guard let data, stage == .ready else { return }
        stage = .importing
        let folders = selection.requestFolders
        task = Task {
            let m = SyncBrowserBookmarks(chromeData: browser == .chrome ? data : nil, safariData: browser == .safari ? data : nil, folders: folders)
            let ok = await store.perform(m)
            guard !Task.isCancelled else { return }
            if ok, let r = m.result { stage = .done(BrowserImportSummary.bookmarks(r)) }
            else { stage = .failed(store.toast ?? "Import failed") }
        }
    }
}
```

`folderRows` is recursive inside a `@ViewBuilder`; if the compiler rejects the recursion, extract it to a small `struct FolderRow: View` that renders itself and `ForEach(node.children) { FolderRow(...) }` — the same shape, one level of indirection.

- [ ] **Step 7: Build, test, commit**

Run: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/safari-import/app/CicadaApp && swift build 2>&1 | tail -5 && swift test 2>&1 | tail -20` → 0 failures.

```bash
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/safari-import && git add app/CicadaApp/Sources/CicadaApp/Services/BrowserFiles.swift app/CicadaApp/Sources/CicadaApp/Models/BrowserImport.swift app/CicadaApp/Sources/CicadaApp/Views/Capture/Sheets/BrowserImportPanels.swift app/CicadaApp/Sources/CicadaApp/Services/APIClient.swift app/CicadaApp/Sources/CicadaApp/Sync/SyncAPI.swift app/CicadaApp/Sources/CicadaApp/Sync/Mutations.swift app/CicadaApp/Sources/CicadaApp/Views/Capture/Sheets/AddSourceSheet.swift app/CicadaApp/Sources/CicadaApp/Views/Feed/ConnectedChannelsStrip.swift app/CicadaApp/Sources/CicadaApp/Views/Capture/ConnectedChannelRow.swift app/CicadaApp/Sources/CicadaApp/Views/Capture/OriginIconography.swift app/CicadaApp/Tests/CicadaAppTests/BrowserFilesTests.swift app/CicadaApp/Tests/CicadaAppTests/BrowserImportModelTests.swift app/CicadaApp/Tests/CicadaAppTests/MutationTests.swift app/CicadaApp/Tests/CicadaAppTests/StoreTests.swift app/CicadaApp/Tests/CicadaAppTests/SourceChannelTests.swift app/CicadaApp/Tests/CicadaAppTests/FeedChannelStripTests.swift app/CicadaApp/Tests/CicadaAppTests/ImportCatalogTests.swift && git commit -m "feat(app): Safari iCloud tabs device picker + bookmark folder tree; app reads ~/Library and posts bytes, Full Disk Access fix on failure (R1/R8/R9)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj"
```

---

### Task 4: App — logo-first, two-level import catalog with keyboard navigation

**Files:**
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Capture/Sheets/ImportFamilies.swift`
- Modify: `AddSourceSheet.swift` (`:133-146` add `brandGlyph`; `:225-231` `escapeAction`; `:233-266` body; `:268-283` back control; `:296-305` `open`/`collapse`; `:329-364` tile button), `ImportCatalog.swift:37-79` (unchanged logic, doc only), `Views/Common/LogoImage.swift:154-190` (`PlatformTile` gains an optional glyph fallback)
- Modify tests: `ImportCatalogTests.swift` (add glyph assertions), `AddSourceTileTests.swift:49-55`
- Create: `Tests/CicadaAppTests/ImportFamilyTests.swift`

**Interfaces:**

```swift
enum ImportFamily: String, CaseIterable, Identifiable { case browsers, websites, chatExports, feedsAndCalendars, files
    var title: String; var blurb: String; var members: [AddSourceTile]; var icon: String
    static func forTile(_ tile: AddSourceTile) -> ImportFamily     // total: every tile belongs to exactly one family
    var previewMarks: [AddSourceTile] }                             // first four members carrying a logo or glyph
enum BrandGlyph { case safari, chrome }
extension AddSourceTile { var brandGlyph: BrandGlyph?; var routeLines: [String] }   // "Bookmarks (folders)", "iCloud tabs", …
struct CatalogFocus: Equatable { var index: Int; let columns: Int; let count: Int
    enum Direction { case up, down, left, right }
    func moved(_ d: Direction) -> CatalogFocus }
enum CatalogLevel: Equatable { case families, members(ImportFamily), flow(AddSourceTile) }
AddSourceSheet.escapeAction(level:) -> EscapeAction   // .back for members/flow, .close for families
```

- [ ] **Step 1: Failing tests**

```swift
// Tests/CicadaAppTests/ImportFamilyTests.swift
import XCTest
@testable import CicadaApp

/// 2026-09-02 brief — the `+` sheet is logo-first and two-level: one tile per
/// family, Enter/click expands to its members, each with its own logo, routes
/// and live channel state. Keyboard: arrows move, Enter opens, Esc backs out.
final class ImportFamilyTests: XCTestCase {

    func testEveryTileBelongsToExactlyOneFamily() {
        let all = ImportFamily.allCases.flatMap(\.members)
        XCTAssertEqual(Set(all).count, all.count, "a tile is listed in two families")
        XCTAssertEqual(Set(all), Set(AddSourceTile.allCases), "a tile is unreachable from the families level")
        for tile in AddSourceTile.allCases {
            XCTAssertTrue(ImportFamily.forTile(tile).members.contains(tile), tile.rawValue)
        }
    }

    func testFamiliesMatchTheBrief() {
        XCTAssertEqual(ImportFamily.browsers.members, [.safari, .chrome])
        XCTAssertEqual(ImportFamily.websites.members, [.tiktok, .instagram, .youtube, .linkedin, .reddit, .pinterest, .x])
        XCTAssertEqual(ImportFamily.chatExports.members, [.chatExport])
        XCTAssertEqual(ImportFamily.feedsAndCalendars.members, [.rssFeed, .calendar, .telegram])
        XCTAssertEqual(ImportFamily.files.members, [.bookmarksFile, .pasteLink, .appleNotes])
        XCTAssertEqual(ImportFamily.allCases.map(\.title), ["Browsers", "Websites & apps", "Chat exports", "Feeds & calendars", "Files"])
    }

    func testBrowserTilesCarryDrawnGlyphsNotDownloadedPNGs() {
        XCTAssertEqual(AddSourceTile.safari.brandGlyph, .safari)
        XCTAssertEqual(AddSourceTile.chrome.brandGlyph, .chrome)
        XCTAssertNil(AddSourceTile.safari.logoName)
        XCTAssertNil(AddSourceTile.chrome.logoName)
        for tile in AddSourceTile.allCases where tile.brandGlyph == nil && tile.logoName == nil {
            XCTAssertFalse(tile.icon.isEmpty, "\(tile.rawValue) has no mark at all")
        }
    }

    func testFamilyPreviewMarksAreItsFirstBrandedMembers() {
        XCTAssertEqual(ImportFamily.browsers.previewMarks, [.safari, .chrome])
        XCTAssertEqual(ImportFamily.websites.previewMarks, [.tiktok, .instagram, .youtube, .linkedin])
        XCTAssertEqual(ImportFamily.chatExports.previewMarks, [.chatExport])
    }

    func testRouteLinesNameEveryWayIn() {
        XCTAssertEqual(AddSourceTile.safari.routeLines, ["Bookmarks (folders)", "Reading List", "iCloud tabs"])
        XCTAssertEqual(AddSourceTile.chrome.routeLines, ["Bookmarks (folders)"])
        XCTAssertEqual(AddSourceTile.tiktok.routeLines, ["Favourites & likes export", "Browsing history (opt-in)"])
        XCTAssertEqual(AddSourceTile.reddit.routeLines, ["Connect account", "GDPR export"])
        XCTAssertEqual(AddSourceTile.pinterest.routeLines, ["Connect account"])
        XCTAssertEqual(AddSourceTile.x.routeLines, ["Connect account"])
        XCTAssertEqual(AddSourceTile.instagram.routeLines, ["Saved export"])
        XCTAssertEqual(AddSourceTile.youtube.routeLines, ["Playlist / Takeout export"])
        for tile in AddSourceTile.allCases { XCTAssertFalse(tile.routeLines.isEmpty, tile.rawValue) }
    }

    // MARK: - Keyboard (R10)

    func testFocusMovesWithinAThreeColumnGridAndClamps() {
        var f = CatalogFocus(index: 0, columns: 3, count: 5)
        f = f.moved(.right); XCTAssertEqual(f.index, 1)
        f = f.moved(.down);  XCTAssertEqual(f.index, 4)
        f = f.moved(.down);  XCTAssertEqual(f.index, 4, "no row below")
        f = f.moved(.right); XCTAssertEqual(f.index, 4, "last item")
        f = f.moved(.up);    XCTAssertEqual(f.index, 1)
        f = f.moved(.left);  XCTAssertEqual(f.index, 0)
        f = f.moved(.left);  XCTAssertEqual(f.index, 0)
        f = f.moved(.up);    XCTAssertEqual(f.index, 0)
    }

    func testFocusOnAnEmptyGridStaysAtZero() {
        let f = CatalogFocus(index: 0, columns: 3, count: 0)
        XCTAssertEqual(f.moved(.down).index, 0)
    }

    func testEscapeWalksBackOneLevel() {
        XCTAssertEqual(AddSourceSheet.escapeAction(level: .flow(.safari)), .back)
        XCTAssertEqual(AddSourceSheet.escapeAction(level: .members(.browsers)), .back)
        XCTAssertEqual(AddSourceSheet.escapeAction(level: .families), .close)
    }
}
```

Update `AddSourceTileTests.swift:52-55` to the new `escapeAction(level:)` form (`.flow(.rssFeed)` → `.back`, `.families` → `.close`).

- [ ] **Step 2: `ImportFamilies.swift`**

```swift
import SwiftUI

/// The top level of the `+` sheet (2026-09-02 brief): one tile per family,
/// wearing its members' marks, so the user sees *where things come from*
/// before any route detail. `AddSourceTile` stays the leaf (R6) — every
/// flow, `forChannel` and "Manage…" still key on it.
enum ImportFamily: String, CaseIterable, Identifiable {
    case browsers, websites, chatExports, feedsAndCalendars, files
    var id: String { rawValue }

    var title: String {
        switch self {
        case .browsers: "Browsers"
        case .websites: "Websites & apps"
        case .chatExports: "Chat exports"
        case .feedsAndCalendars: "Feeds & calendars"
        case .files: "Files"
        }
    }

    var blurb: String {
        switch self {
        case .browsers: "Bookmarks, Reading List, and the tabs open on your iPhone."
        case .websites: "Everything you saved on TikTok, Instagram, YouTube, LinkedIn, Reddit, Pinterest and X."
        case .chatExports: "Your Claude and ChatGPT conversations, backdated."
        case .feedsAndCalendars: "Blogs, newsletters, calendars — and a Telegram bot for the road."
        case .files: "A bookmarks file, a pasted link, or Apple Notes."
        }
    }

    var icon: String {
        switch self {
        case .browsers: "globe"
        case .websites: "square.grid.2x2"
        case .chatExports: "bubble.left.and.bubble.right"
        case .feedsAndCalendars: "dot.radiowaves.up.forward"
        case .files: "doc"
        }
    }

    var members: [AddSourceTile] {
        switch self {
        case .browsers: [.safari, .chrome]
        case .websites: [.tiktok, .instagram, .youtube, .linkedin, .reddit, .pinterest, .x]
        case .chatExports: [.chatExport]
        case .feedsAndCalendars: [.rssFeed, .calendar, .telegram]
        case .files: [.bookmarksFile, .pasteLink, .appleNotes]
        }
    }

    static func forTile(_ tile: AddSourceTile) -> ImportFamily {
        allCases.first { $0.members.contains(tile) } ?? .files
    }

    /// The marks the family tile wears: up to four members, in listed order,
    /// preferring ones with a logo or glyph. A family whose members have
    /// only SF Symbols (Files) still shows them — never an empty cluster.
    var previewMarks: [AddSourceTile] {
        let branded = members.filter { $0.logoName != nil || $0.brandGlyph != nil }
        return Array((branded.isEmpty ? members : branded).prefix(4))
    }
}

/// Marks drawn in-app for the browsers (R7): no brand asset is downloaded.
/// Drop `Resources/logos/safari.png` / `chrome.png` and set the tile's
/// `logoName` to switch to an official mark; `PlatformTile` prefers a PNG.
enum BrandGlyph: Equatable { case safari, chrome }

extension AddSourceTile {
    var brandGlyph: BrandGlyph? {
        switch self {
        case .safari: .safari
        case .chrome: .chrome
        default: nil
        }
    }

    /// Every way this member can import — the lines under its name at the
    /// members level, so the user can tell "folders" from "tabs" before
    /// opening it.
    var routeLines: [String] {
        switch self {
        case .safari: ["Bookmarks (folders)", "Reading List", "iCloud tabs"]
        case .chrome: ["Bookmarks (folders)"]
        case .tiktok: ["Favourites & likes export", "Browsing history (opt-in)"]
        case .instagram: ["Saved export"]
        case .youtube: ["Playlist / Takeout export"]
        case .linkedin: ["Saved items export"]
        case .reddit: ["Connect account", "GDPR export"]
        case .pinterest, .x: ["Connect account"]
        case .chatExport: ["Claude export", "ChatGPT export"]
        case .rssFeed: ["Subscribe to a feed URL"]
        case .calendar: ["Subscribe to a webcal/ICS URL"]
        case .telegram: ["Your own bot"]
        case .bookmarksFile: ["HTML / JSON / CSV / Takeout zip"]
        case .pasteLink: ["One URL"]
        case .appleNotes: ["One-way sync"]
        }
    }
}

/// Which level the sheet is showing.
enum CatalogLevel: Equatable {
    case families
    case members(ImportFamily)
    case flow(AddSourceTile)
}

/// Pure grid-focus arithmetic (R10): arrows move within a `columns`-wide
/// grid of `count` items, clamped at the edges — never wrapping, so a held
/// key stops rather than cycles.
struct CatalogFocus: Equatable {
    var index: Int
    let columns: Int
    let count: Int

    enum Direction { case up, down, left, right }

    func moved(_ d: Direction) -> CatalogFocus {
        guard count > 0, columns > 0 else { return CatalogFocus(index: 0, columns: columns, count: count) }
        var next = index
        switch d {
        case .left: next = max(0, index - 1)
        case .right: next = min(count - 1, index + 1)
        case .up: next = index - columns >= 0 ? index - columns : index
        case .down: next = index + columns < count ? index + columns : index
        }
        return CatalogFocus(index: next, columns: columns, count: count)
    }
}

/// Chrome's mark: three 120° arcs (green, red, yellow) around a blue disc.
struct ChromeGlyph: View {
    var size: CGFloat = 24
    var body: some View {
        Canvas { ctx, sz in
            let c = CGPoint(x: sz.width / 2, y: sz.height / 2)
            let r = min(sz.width, sz.height) / 2
            let colors: [Color] = [Color(hex: 0xDB4437), Color(hex: 0xF4B400), Color(hex: 0x0F9D58)]
            for (i, color) in colors.enumerated() {
                var p = Path()
                p.move(to: c)
                p.addArc(center: c, radius: r, startAngle: .degrees(-90 + Double(i) * 120), endAngle: .degrees(30 + Double(i) * 120), clockwise: false)
                p.closeSubpath()
                ctx.fill(p, with: .color(color))
            }
            let inner = CGRect(x: c.x - r * 0.42, y: c.y - r * 0.42, width: r * 0.84, height: r * 0.84)
            ctx.fill(Path(ellipseIn: inner), with: .color(.white))
            let core = inner.insetBy(dx: r * 0.08, dy: r * 0.08)
            ctx.fill(Path(ellipseIn: core), with: .color(Color(hex: 0x4285F4)))
        }
        .frame(width: size, height: size)
        .accessibilityHidden(true)
    }
}

/// Safari's mark is Apple's own compass symbol, tinted Safari blue.
struct SafariGlyph: View {
    var size: CGFloat = 24
    var body: some View {
        Image(systemName: "safari")
            .resizable().scaledToFit()
            .foregroundStyle(Color(hex: 0x00A2E8))
            .frame(width: size, height: size)
            .accessibilityHidden(true)
    }
}

/// One member's mark: PNG when bundled, else its glyph, else its SF Symbol.
struct MemberMark: View {
    let tile: AddSourceTile
    var size: CGFloat = 32
    var body: some View {
        if let name = tile.logoName, LogoImage.exists(name: name) {
            LogoImage.platformTile(name: name, size: size, systemFallback: tile.icon)
        } else if let glyph = tile.brandGlyph {
            ZStack {
                RoundedRectangle(cornerRadius: size * 0.2).fill(CicadaTheme.surfaceElevated)
                RoundedRectangle(cornerRadius: size * 0.2).stroke(CicadaTheme.border, lineWidth: 1)
                switch glyph {
                case .safari: SafariGlyph(size: size * 0.6)
                case .chrome: ChromeGlyph(size: size * 0.6)
                }
            }
            .frame(width: size, height: size)
        } else {
            LogoImage.platformTile(name: "", size: size, systemFallback: tile.icon)
        }
    }
}

/// The family tile's cluster: up to four member marks in a 2×2 grid (two
/// side by side when there are only two).
struct FamilyMarkCluster: View {
    let family: ImportFamily
    var body: some View {
        let marks = family.previewMarks
        let cols = marks.count <= 2 ? marks.count : 2
        LazyVGrid(columns: Array(repeating: GridItem(.fixed(22), spacing: 4), count: max(cols, 1)), spacing: 4) {
            ForEach(marks) { MemberMark(tile: $0, size: 22) }
        }
        .frame(height: marks.count <= 2 ? 22 : 48, alignment: .topLeading)
        .accessibilityHidden(true)
    }
}
```

(`Color(hex:)` already exists — used at `OriginIconography.swift:82`.)

- [ ] **Step 3: Re-layer `AddSourceSheet`**

Replace `@State private var expanded: AddSourceTile?` with `@State private var level: CatalogLevel = .families` and `@State private var focus = CatalogFocus(index: 0, columns: 3, count: ImportFamily.allCases.count)`. Keep a computed `private var expanded: AddSourceTile? { if case .flow(let t) = level { return t }; return nil }` so the existing flow code compiles unchanged.

- `escapeAction` (`:225-231`) becomes `static func escapeAction(level: CatalogLevel) -> EscapeAction { if case .families = level { return .close }; return .back }`; the `.onKeyPress(.escape)` calls `back()`.
- Body grid (`:239-243`): switch on `level` — `.families` renders `ForEach(Array(ImportFamily.allCases.enumerated()), id: \.element.id)` of `familyTile(family, focused: focus.index == i)`; `.members(let family)` renders its `members` as `memberTile(tile, focused:)`; `.flow` keeps `backControl` + `flow(for:)`.
- Keyboard: on the `ScrollView` add `.focusable()` and `.onKeyPress(.upArrow) { focus = focus.moved(.up); return .handled }` (same for the other three arrows) and `.onKeyPress(.return) { activateFocused(); return .handled }` — all guarded `if case .flow = level { return .ignored }` so text fields inside a flow keep Enter.
- `open(_ tile:)` sets `level = .flow(tile)` (rest unchanged); `openFamily(_:)` sets `level = .members(f)` and `focus = CatalogFocus(index: 0, columns: 3, count: f.members.count)`; `back()` walks `.flow(t)` → `.members(ImportFamily.forTile(t))` (resetting `stage`, cancelling `importTask`, bumping `importGeneration` exactly as `collapse()` does at `:296-305`) and `.members` → `.families`; `initialTile` on appear goes straight to `.flow(initialTile)`.
- `backControl` shows the family title when at `.members` and the tile title when at `.flow` (breadcrumb: "All sources › Browsers › Safari").
- `familyTile`: `FamilyMarkCluster` + title + blurb + a one-line summary of connected members (`"\(n) connected"` from `tileState` over its members, or the family blurb); `.overlay` a 2-pt `CicadaTheme.accent` stroke when `focused`; `.accessibilityLabel("\(family.title). \(family.blurb)")`.
- `memberTile` = the existing `tileButton` (`:329-364`) with `MemberMark(tile:)` in place of the logo/icon branch and `routeLines.joined(separator: " · ")` as a third caption line above the badge; focused ring as above. The `tileState` detail line (connected · last sync · count) stays exactly where it is.
- Remove the `.browserBookmarks`-era three-column note only if it no longer applies; keep three columns.

- [ ] **Step 4: Build, test, commit**

Run: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/safari-import/app/CicadaApp && swift build 2>&1 | tail -5 && swift test 2>&1 | tail -20` → 0 failures.

```bash
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/safari-import && git add app/CicadaApp/Sources/CicadaApp/Views/Capture/Sheets/ImportFamilies.swift app/CicadaApp/Sources/CicadaApp/Views/Capture/Sheets/AddSourceSheet.swift app/CicadaApp/Sources/CicadaApp/Views/Capture/Sheets/ImportCatalog.swift app/CicadaApp/Sources/CicadaApp/Views/Common/LogoImage.swift app/CicadaApp/Tests/CicadaAppTests/ImportFamilyTests.swift app/CicadaApp/Tests/CicadaAppTests/ImportCatalogTests.swift app/CicadaApp/Tests/CicadaAppTests/AddSourceTileTests.swift && git commit -m "feat(app): logo-first two-level import catalog — families → members → flow, drawn Safari/Chrome glyphs, arrow/Enter/Esc navigation (G71 follow-up)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj"
```

---

### Task 5: Docs — CLAUDE.md, backlog rows, TODO.md

**Files:**
- Modify: `CLAUDE.md:149` (Ingested sources bullet), `:166-173` (Export parsers bullet — add one bullet after it), `:545-552` (Feed sheet sentence), `:628-632` (API list)
- Modify: `docs/goals/memory-evolution.md:505` (G30), `:536` (G47), `:633` (G71); append **G118** after line 679 (G117)
- Modify: `docs/goals/TODO.md` (Shipped "2026-09-02" block, "Where things stand", "Pick up here")

**Privacy check before writing:** no device names, folder names, URLs, counts that identify a person. "~200 tabs" / "one large folder" are fine; the folder's name is not.

- [ ] **Step 1: CLAUDE.md**

1. Replace the `Ingested sources` bullet (`:149`) with: ``- **Browsers (G30 + 2026-09-02):** Safari bookmarks (by folder — Favorites, Bookmarks Menu, Reading List — via `folders:` on `POST /sources/sync-bookmarks`, tree preview with `?preview=true`), **Safari iCloud tabs** (`POST /sources/sync-safari-tabs`, `api/services/safari_tabs.py`: CloudTabs.db bytes → one item per open tab, `origin: safari-tab`, folder = device name, per-device preview), and Chrome bookmarks (by folder). **The app reads the files under `~/Library` and the backend parses bytes** — the launchd backend has no Full Disk Access and never opens those paths itself; an unreadable file shows the exact fix in the app. Channels are per browser (`chrome-bookmarks`, `safari-bookmarks`, `safari-tabs`; the legacy `bookmarks` sync_state entry is read as a fallback, never written). Plus saved links, RSS feeds, PDFs, repos — all indexed in the sqlite-vec vector index.``
2. After the Export parsers bullet (`:173`) add: ``- **Import catalog (Feed `+`/⌘N):** logo-first and two-level — one tile per family (Browsers, Websites & apps, Chat exports, Feeds & calendars, Files) opening to its members, each with its own mark (bundled PNGs; Safari/Chrome are drawn glyphs, `BrandGlyph`), its import routes and its live `/sources/channels` state. Arrows move, Enter opens, Esc backs out (`CatalogFocus`). `AddSourceTile` stays the leaf every flow keys on.``
3. `:545-552` — extend the final sentence of the Sync-engine paragraph: replace "Feed's `+`/⌘N sheet (G71) is now a two-level Imports catalog: platform tiles wearing brand logos route either to …" with "Feed's `+`/⌘N sheet (G71, re-layered 2026-09-02) is a family → member → flow catalog: family tiles wear their members' marks; member tiles route either to …" keeping the rest of the sentence.
4. API list (`:628-632`) — change the `sync-bookmarks` line and add two:
```
POST /sources/save, /sources/upload,
     /sources/rss, /sources/sync-bookmarks → capture links/files/RSS/bookmarks into memory
                                            (sync-bookmarks: `folders: [str]` path prefixes; `?preview=true`
                                             returns the folder tree with leaf counts, stages nothing)
POST /sources/sync-safari-tabs            → Safari iCloud tabs from CloudTabs.db bytes the app read
                                            (`safariTabsDbB64`, optional `safariTabsWalB64`, `devices`);
                                            `?preview=true` → per-device counts, stages nothing
```

- [ ] **Step 2: Backlog rows** (edit with a targeted string replace, never by retyping a long line)

```bash
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/safari-import && api/.venv/bin/python - <<'PY'
from pathlib import Path
p = Path("docs/goals/memory-evolution.md"); s = p.read_text()

def patch(old_tail, addition):
    global s
    assert s.count(old_tail) == 1, old_tail
    s = s.replace(old_tail, addition)

# G30 — append a shipped clause inside the status cell.
patch('`POST /sources/sync-bookmarks`; Capture page "Sync now") |',
      '`POST /sources/sync-bookmarks`; Capture page "Sync now"). **2026-09-02 (`feat/safari-import`):** Safari **iCloud tabs** (`safari_tabs.py`, `POST /sources/sync-safari-tabs` + per-device preview, `origin: safari-tab`, folder = device), **folder selection** (`folders:` prefixes + `?preview=true` folder tree; Reading List as its own folder), per-browser channels with a read-time legacy fallback, and the app now reads the `~/Library` files itself and posts bytes — the launchd backend never could (no Full Disk Access; the old "Sync now" silently synced nothing). Arc/Firefox/Brave → G118 |')

# G47 — one clause.
patch('TikTok/Reddit/X listed as future members) |',
      'TikTok/Reddit/X listed as future members; 2026-09-02: catalog re-layered into families → members with per-member routes, see G71) |')

# G71 — one clause at the start of the disclosed-partial list.
patch('**Partial/deferred:** walkthrough VIDEOS are still absent',
      '**2026-09-02 follow-up (`feat/safari-import`):** the catalog is logo-first and two-level — family tiles (Browsers, Websites & apps, Chat exports, Feeds & calendars, Files) → member tiles with their own mark, route lines and live channel state; arrows/Enter/Esc; Safari and Chrome marks are drawn in-app (`BrandGlyph`), official PNGs can be dropped into `Resources/logos/` later. **Partial/deferred:** walkthrough VIDEOS are still absent')

# G118 — new row after G117.
g117_start = s.index("| G117 |"); g117_end = s.index("\n", g117_start)
row = ("\n| G118 | **Other browsers — Arc, Firefox, Brave (bookmarks; open tabs where the browser exposes them)** (follow-up from the 2026-09-02 Safari track) | "
       "Same shape as G30: the app reads the profile file, the backend parses bytes, `folders:` selection and the tree preview come for free via `bookmark_sync.folder_tree`. "
       "Arc keeps `~/Library/Application Support/Arc/StorableSidebar.json` (spaces/folders/tabs in one JSON); Brave is Chromium (`~/Library/Application Support/BraveSoftware/Brave-Browser/Default/Bookmarks`, the Chrome parser as-is with a `brave-bookmark` origin); "
       "Firefox is `places.sqlite` (`moz_bookmarks` ⋈ `moz_places`, WAL-mode — reuse `safari_tabs.load_tabs`'s temp-copy + sidecar pattern). One `BrowserFile` case + one `AddSourceTile` member of the Browsers family each. "
       "Rail: no network, no LLM, idempotent through `url_index`. → **APPLY**, S each; do Brave first (zero parser work). | 🔲 |")
s = s[:g117_end] + row + s[g117_end:]
p.write_text(s); print("ok")
PY
```

If the G30 tail string does not match exactly (the row may have been edited), run `sed -n 505p docs/goals/memory-evolution.md | cut -c400-` first and adjust `old_tail` to the literal last 60 characters of the status cell.

- [ ] **Step 3: TODO.md**

1. Under `**2026-09-02**` in `## ✅ Shipped` add: `- **Safari import track** (`feat/safari-import`, PR #TBD) — Safari iCloud tabs (device picker), bookmark folder selection with tree preview (Reading List as its own folder), per-browser channels, the app reads `~/Library` and posts bytes (the launchd backend never could), Full-Disk-Access fix shown in place, and the `+` sheet re-layered into a logo-first family → member catalog with keyboard navigation. Follow-up: G118 (Arc/Firefox/Brave).`
2. In `## Where things stand` (TODO.md `:7`, currently headed "2026-09-01, evening"), retitle the heading to 2026-09-02 and add a first paragraph naming `feat/safari-import` as the open PR and the one manual step the orchestrator runs (Verification below).
3. In `## Pick up here`, add item **0.**: "Merge `feat/safari-import` after an independent re-run of both suites, then run the live import once with the owner present (Full Disk Access to Cicada.app is a one-time grant)."
4. Refresh `_Last synced:` line.

- [ ] **Step 4: Verify and commit**

Run: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/safari-import && grep -n "browserBookmarks\|Chrome & Safari bookmarks" CLAUDE.md docs/goals/TODO.md app/CicadaApp/Sources -r` → no output (the retired tile and the combined label are gone from prose and code; the G30 backlog row's history may still mention the old label — that is fine).

```bash
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/safari-import && git add CLAUDE.md docs/goals/memory-evolution.md docs/goals/TODO.md && git commit -m "docs: Safari iCloud tabs, folder selection, family catalog; G30/G47/G71 shipped clauses, G118 filed, TODO handoff

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj"
```

---

## Verification the orchestrator runs at the end

1. `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/safari-import && api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider 2>&1 | tail -15` → only the 8 `test_calendar_registry.py` baseline failures plus the order-dependent `test_agent_provenance` one.
2. `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/safari-import/app/CicadaApp && swift build 2>&1 | tail -5 && swift test 2>&1 | tail -20` → 0 failures.
3. `git -C /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/safari-import log --oneline bad8461..HEAD` → 5 commits, one per task; `git status --porcelain` shows nothing staged from `memory/`, `logs/`, `api/.venv`, `*-report.md`.
4. Privacy grep on the diff: `git -C /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/safari-import diff bad8461..HEAD -- . ':!api/.venv' | grep -in "rodrigo's\|rodrigo’s\|rorosaga"` → no hits in code, tests or docs (the only allowed "Rodrigo" mentions are pre-existing backlog voice lines; `rorosaga` is fine only inside the pre-existing `repos:` example in `CLAUDE.md`, which this track never touches). The orchestrator additionally greps for the owner's real device and folder names locally — they are deliberately not written into this plan.
5. Static contract checks: `grep -rn "sync_from_local_files" api/services/safari_tabs.py` → none (R1); `grep -n "immutable=1" api/services/safari_tabs.py` → present (R2); `grep -n '"bookmarks"' api/routers/sources.py` → none (R4 — nothing writes the legacy key).
6. **After merge, with the owner at the machine** (the only step touching real data, never done by an agent): install via `make install-app`, grant Full Disk Access to Cicada.app once, open Feed → `+` → Browsers → Safari → *iCloud tabs*: the preview should list the iPhone with ~200 tabs and the Mac with 0; import; expect `new ≈ tabs − already-bookmarked`, `skipped` for the rest, and the `safari-tabs` row lit in the Connected strip. Then *Bookmarks & Reading List*: tick only the large folder under Favorites; expect `new: 0`-ish if those URLs were already synced as `safari-bookmark` entities (dedup is by URL hash) — a non-zero `skipped` there is the idempotency proof. `GET /sources/channels` should show `chrome-bookmarks` / `safari-bookmarks` reading the legacy count until each syncs on its own.

## Self-review notes (for the executor, not a task)

- Task 1 must land the `safari-tabs` channel and the ordering-test edits in the same commit as the router (ETag ship-together — `sync_state.json` already rides the `sources` component).
- Task 2's `SAFARI_PLIST_TREE` change shifts three existing assertions — update them in the same edit or the suite goes red mid-task.
- `BookmarkFolderSelection.toggle` on a node only covered by an ancestor drops the ancestor (documented; the test pins it). Do not "improve" it into carve-out semantics without a test.
- `BrowserFileReader.readIfPresent` must be called only after the main db read succeeded — a permission failure on the sidecar would otherwise be swallowed as "no WAL" (comment in code says why).
- The recursive `folderRows` `@ViewBuilder` may need the `FolderRow` struct indirection; either shape is acceptable.
- Nothing in any task opens a path under the real home in tests: `BrowserFilesTests.testReadIfPresentReturnsNilForAMissingSidecar` passes explicit candidates, and every Python fixture lives in `tmp_path`.
