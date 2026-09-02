# Capture "+", Plans & keys, Entity Logos, Import Walkthroughs — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the Capture page around a backend-derived "connected channels" list with a `+` picker sheet, make the Connections page say what "Connected" actually means (renamed Plans & keys / Agents), and give entities real logos end-to-end (resolution ladder → cached fetch → API → SwiftUI circle → graph canvas).

**Architecture:** Four independent slices sharing one delivery. (1) A new `sync_state.json` + `channel_registry` service derives `GET /sources/channels` purely from persisted state, and the app gets a `channels` sync domain so `SourcesView` renders from a `Store` snapshot instead of transient button results. (2) `ConnectionStatus` grows `how` + `powers`, authored next to each adapter's probe, with the engine assignment computed in the registry. (3) A keyless `logo_service` resolves a domain from an entity page, fetches an icon through a swappable fetcher, and caches it under `~/.cicada/logos/<bank>/`; `GET /entities/{id}/logo` serves it, `GET /graph` reports `has_logo` from the cache index only (never the network), and the Sleep cycle warms the common ones. (4) The app renders that logo as a circle in the detail card, inbox row, cluster rows and Ask chips, and optionally on graph nodes behind a "Show logos" toggle.

**Tech Stack:** FastAPI + Pydantic v2 (`api/`, Python 3.12, venv at `api/.venv`), pytest with `fastapi.testclient.TestClient`; SwiftUI macOS 14 SwiftPM package (`app/CicadaApp`), XCTest; d3 + canvas in `Resources/graph/graph.js` with a plain-`node` regression harness in `Tests/graph/`.

**Spec:** `docs/superpowers/specs/2026-08-30-capture-connections-logos-design.md`

## Spec Ambiguities Resolved

The spec is the authority; these four points had no single reading, and the plan
commits to one. Each is called out again at the task that implements it.

1. **Pillow** (§3.1, explicitly left to verify) — it is **not** a dependency
   (`api/pyproject.toml` lists no imaging library). The plan takes the spec's own
   fallback: store whatever the site serves, with the correct `Content-Type`, and
   sniff PNG/GIF/ICO/JPEG headers directly for the ≥ 16 px guard. No decode, no
   new dependency. (Task 8.)
2. **"the existing graph settings toggle"** (§3.2) — `graph.js` has no settings
   UI at all; the only Swift→JS channel is `applyFilters`. The plan adds
   `showLogos` as a new, off-by-default filter axis and a `Toggle("Show logos")`
   in the existing graph filter popover (`ContentView.swift:268`). (Task 11.)
3. **"search results rows"** (§3.2) — the app has no search-results list view;
   `APIClient.search(q:topK:)` has no UI consumer. The nearest real surface is
   the Clusters entity list (`TopicRowListItem`), whose 10-pt type dot the logo
   replaces. (Task 10.)
4. **`files` channel count** (§1.1 says "origin counts") — no single origin
   corresponds to "saved items"; bookmarks, RSS, Instagram and Telegram links all
   land in `sources/url_index.json`. The plan counts that index, which is exactly
   what "57 saved items" means and what `GET /sources` already reports. (Task 1.)

## Global Constraints

- **Never touch `.claude/settings.json`.** It is already modified in the working tree and is not part of this work.
- **Never run `git add -A`.** Stage only the exact files each commit step names.
- **Memory bank contents under `memory/` are never part of a branch.** No test, fixture, or commit may add, modify, or stage anything under `memory/`. Every test builds its own `tmp_path` workspace.
- **Every commit message ends with these two trailer lines**, after a blank line:
  ```
  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
  ```
- **Logo cache lives under `~/.cicada/logos/<bank>/`** (resolved via `api.services.auth.cicada_home()`), **never inside a memory bank**.
- **No network in `GET /graph`.** The graph path may only read the on-disk logo cache index.
- **Tests never hit the network.** `api/tests/conftest.py` sets `CICADA_ALLOW_LOGO_FETCH=off` for every test; every logo test injects a fake fetcher.
- **Swift views read from `Store` snapshots**; every write goes through a `Mutation` (`app/CicadaApp/Sources/CicadaApp/Sync/Mutations.swift`).
- **Sidebar tab identifiers (`AppTab` raw values) stay unchanged** when labels are renamed. Add a `title` property; do not touch `case connections = "Connections"` / `case connect = "Connect"`.
- **Every new sidebar/list row is a `Button` with an `.accessibilityLabel`.**
- **`SourcesView.swift` must end at ≤ 450 lines.** Check with `wc -l`.

**Verification commands used throughout:**
- Backend: `api/.venv/bin/python -m pytest api/tests -q`
- App: `cd app/CicadaApp && swift test`
- Graph JS: `node app/CicadaApp/Tests/graph/graph-logo.test.js`

---

## File Structure

**Backend — created**
- `api/services/sync_state.py` — read/write `<memory>/sync_state.json` (the only durable record that a bookmark/notes sync ever ran).
- `api/services/channel_registry.py` — derive the capture-channel list from persisted state only. No network, no LLM.
- `api/services/logo_service.py` — entity → domain ladder, keyless icon fetch behind an injectable fetcher, on-disk cache + TTL under `~/.cicada/logos/<bank>/`.
- `api/tests/test_source_channels.py`, `api/tests/test_logo_service.py`, `api/tests/test_entity_logo_endpoint.py`, `api/tests/test_connection_how_powers.py`.

**Backend — modified**
- `api/models/schemas.py` — `SourceChannel`, `SourceChannelsResponse`; `ConnectionStatus.how` / `.powers`; `GraphNode.has_logo`.
- `api/routers/sources.py` — `GET /sources/channels`; record sync state in `sync_bookmarks` / `sync_notes`.
- `api/services/sync_service.py` — fold `sync_state.json` mtime into the `sources` component.
- `api/services/connections/{claude_cli,codex_cli,byok,ollama}.py` — author the `how` line next to each probe.
- `api/services/connections/registry.py` — assign `powers` across the probed statuses.
- `api/routers/entities.py` — `GET /entities/{id}/logo`.
- `api/services/graph_builder.py` — `has_logo` from the cache index, folded into `content_hash`.
- `api/services/sleep_cycle.py` — `warm_logos` tail step.
- `api/tests/conftest.py` — `CICADA_ALLOW_LOGO_FETCH=off` for the whole suite.

**App — created**
- `Views/Capture/Sheets/AddSourceSheet.swift` — the `+` tile grid and each tile's flow.
- `Views/Capture/Sheets/WalkthroughPanel.swift` — vendor picker, steps, "Open … export settings", reserved 16:9 area.
- `Views/Capture/Sheets/CaptureRows.swift` — `ImportTileButton`, `FeedSubscriptionRow`, `CalendarSubscriptionRow` moved out of `SourcesView.swift`.
- `Views/Capture/ConnectedChannelRow.swift` — one connected-channel row + its ⋯ menu.
- `Views/Capture/OriginPill.swift` — `OriginPill` moved out of `SourcesView.swift`.
- `Models/SourceChannel.swift` — wire model for `GET /sources/channels`.
- `Services/LogoStore.swift` — remote logo fetch + per-bank disk cache.
- `Tests/CicadaAppTests/SourceChannelTests.swift`, `Tests/CicadaAppTests/LogoImageTests.swift`, `Tests/CicadaAppTests/WalkthroughTests.swift`.
- `Tests/graph/graph-logo.test.js`.
- `docs/walkthrough-recording.md`.

**App — modified**
- `Sync/Snapshot.swift` (`SyncDomain.channels`), `Sync/Store.swift`, `Sync/SyncAPI.swift`, `Sync/VersionVector.swift`, `Services/APIClient.swift`.
- `Views/Capture/SourcesView.swift` — rewritten, ≤ 450 lines.
- `Views/Sidebar/SidebarView.swift` (`AppTab.title`), `Views/Connections/ConnectionsView.swift`, `Views/Connect/ConnectView.swift`, `Models/Connection.swift`.
- `Views/Common/LogoImage.swift`, `Views/Graph/EntityDetailCard.swift`, `Views/Inbox/InboxCardView.swift`, `Views/Topics/TopicsView.swift`, `Ask/AskPanel.swift`.
- `Models/GraphFilter.swift`, `Models/Entity.swift`, `ViewModels/GraphViewModel.swift`, `Views/Graph/GraphView.swift`, `ContentView.swift`, `Resources/graph/graph.js`.

**Docs — modified**
- `CLAUDE.md` (API list + router count), `docs/goals/memory-evolution.md` (G59/G62/G63/G64 status).

---

### Task 1: `sync_state.json` + `GET /sources/channels`

**Files:**
- Create: `api/services/sync_state.py`
- Create: `api/services/channel_registry.py`
- Create: `api/tests/test_source_channels.py`
- Modify: `api/models/schemas.py` (append after `NotesSyncResponse`, currently ends line 888)
- Modify: `api/routers/sources.py` (imports at top; `sync_bookmarks` ~line 232; `sync_notes` at the end of the file; new endpoint)
- Modify: `api/services/sync_service.py:73-79` (the `sources` component)

**Interfaces:**
- Consumes: `feed_registry.list_feeds(memory_path) -> list[dict]` (records carry `url`, `tags`, `added`, `last_polled`), `calendar_registry.list_calendars(memory_path) -> list[dict]` (same shape), `origin_stats.aggregate_origins(memory_path) -> list[dict]` (`origin`, `episodeCount`, `entityCount`, `lastSeen`), `media_ingestor.load_url_index(memory_path) -> dict`, `sync_service.etag_for(memory_path, *keys, extra="")`, `sync_service.conditional(request, response, etag)`.
- Produces:
  - `sync_state.SYNC_STATE_FILENAME = "sync_state.json"`
  - `sync_state.sync_state_path(memory_path: Path) -> Path`
  - `sync_state.read_sync_state(memory_path: Path) -> dict`
  - `sync_state.record_sync(memory_path: Path, channel: str, *, count: int, at: str | None = None) -> dict`
  - `channel_registry.build_channels(memory_path: Path, *, telegram_enabled: bool) -> list[dict]`
  - `GET /sources/channels` → `{"channels": [...]}` with camelCase keys `id/label/connected/count/lastSync/detail/actions`.

- [ ] **Step 1: Write the failing test for `sync_state`**

Create `api/tests/test_source_channels.py`:

```python
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
```

- [ ] **Step 2: Run it and watch it fail**

Run: `api/.venv/bin/python -m pytest api/tests/test_source_channels.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'api.services.sync_state'`.

- [ ] **Step 3: Write `api/services/sync_state.py`**

```python
"""Durable "this sync actually ran" record — ``<memory>/sync_state.json``.

Bookmark and Notes sync leave no subscription record behind (unlike
``feeds.yaml`` / ``calendars.yaml``): their only trace is whatever episodes
they wrote, which is indistinguishable from any other capture path. The
Capture page needs to know "is this channel connected", so the sync endpoints
stamp one small JSON file on success and ``channel_registry`` reads it back.

Shape::

    {"bookmarks": {"last_sync": "2026-08-29T10:00:00Z", "count": 412},
     "notes":     {"last_sync": "2026-08-30T09:00:00Z", "count": 18}}

Corrupt or missing file degrades to ``{}`` — a channel simply reads as not
connected rather than breaking the page.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

SYNC_STATE_FILENAME = "sync_state.json"


def sync_state_path(memory_path: Path) -> Path:
    return Path(memory_path) / SYNC_STATE_FILENAME


def read_sync_state(memory_path: Path) -> dict:
    path = sync_state_path(memory_path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def record_sync(memory_path: Path, channel: str, *, count: int, at: str | None = None) -> dict:
    """Stamp ``channel``'s last successful sync. Returns the full new state."""
    state = read_sync_state(memory_path)
    state[channel] = {
        "last_sync": at or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "count": int(count),
    }
    path = sync_state_path(memory_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError as exc:  # a read-only bank must never fail the sync itself
        logger.warning(f"Could not write {SYNC_STATE_FILENAME}: {type(exc).__name__}: {exc}")
    return state
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `api/.venv/bin/python -m pytest api/tests/test_source_channels.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Write the failing test for `channel_registry.build_channels`**

Append to `api/tests/test_source_channels.py`:

```python
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
```

- [ ] **Step 6: Run it and watch it fail**

Run: `api/.venv/bin/python -m pytest api/tests/test_source_channels.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'api.services.channel_registry'`.

- [ ] **Step 7: Write `api/services/channel_registry.py`**

```python
"""Capture-channel derivation for ``GET /sources/channels`` (G62).

One list the Capture page can render from, derived from **persisted state
only** — never from the transient result of a button press:

* ``rss`` / ``calendar``  -> the subscription registries are non-empty
* ``bookmarks`` / ``notes`` -> a ``sync_state.json`` entry exists
* ``telegram``            -> ``CICADA_TELEGRAM_BOT_TOKEN`` is configured
* ``chat-export:*`` / ``files`` -> origin counts / the saved-URL index

Pure filesystem + one env flag passed in by the router. No network, no LLM,
never raises: a corrupt registry or a missing directory yields a
not-connected channel, never an error.
"""

from __future__ import annotations

from pathlib import Path

from api.services import (
    calendar_registry,
    feed_registry,
    media_ingestor,
    origin_stats,
    sync_state,
)

# Canonical order; the app sorts the *connected* rows by last_sync itself.
CHANNEL_IDS = (
    "chat-export:claude",
    "chat-export:chatgpt",
    "bookmarks",
    "notes",
    "rss",
    "calendar",
    "telegram",
    "files",
)


def _plural(n: int, singular: str, plural: str | None = None) -> str:
    return f"{n:,} {singular if n == 1 else (plural or singular + 's')}"


def _short_date(iso: str | None) -> str:
    """`2026-08-29T10:00:00Z` / `2026-08-29` -> `2026-08-29`; '' when absent."""
    return (iso or "").split("T", 1)[0]


def _latest(values: list[str | None]) -> str | None:
    present = sorted(v for v in values if v)
    return present[-1] if present else None


def _subscription_channel(
    channel_id: str, label: str, records: list[dict], noun: str
) -> dict:
    count = len(records)
    last = _latest([r.get("last_polled") for r in records if isinstance(r, dict)])
    detail = None
    if count:
        when = f"polled {_short_date(last)}" if last else "not polled yet"
        detail = f"{_plural(count, noun)} · {when}"
    return {
        "id": channel_id,
        "label": label,
        "connected": count > 0,
        "count": count,
        "last_sync": last,
        "detail": detail,
        "actions": ["poll", "manage"],
    }


def _sync_channel(channel_id: str, label: str, state: dict, noun: str) -> dict:
    entry = state.get(channel_id) or {}
    last = entry.get("last_sync") or None
    count = int(entry.get("count") or 0)
    connected = bool(last)
    detail = f"{_plural(count, noun)} · synced {_short_date(last)}" if connected else None
    return {
        "id": channel_id,
        "label": label,
        "connected": connected,
        "count": count,
        "last_sync": last,
        "detail": detail,
        "actions": ["sync"],
    }


def _origin_channel(
    channel_id: str, label: str, origin: str, by_origin: dict, noun: str
) -> dict:
    stat = by_origin.get(origin) or {}
    count = int(stat.get("episodeCount") or 0)
    last = stat.get("lastSeen") or None
    detail = f"{_plural(count, noun)} · imported {_short_date(last)}" if count else None
    return {
        "id": channel_id,
        "label": label,
        "connected": count > 0,
        "count": count,
        "last_sync": last,
        "detail": detail,
        "actions": ["import"],
    }


def build_channels(memory_path: Path, *, telegram_enabled: bool) -> list[dict]:
    memory_path = Path(memory_path)
    state = sync_state.read_sync_state(memory_path)
    by_origin = {o["origin"]: o for o in origin_stats.aggregate_origins(memory_path)}

    try:
        url_index = media_ingestor.load_url_index(memory_path)
    except Exception:
        url_index = {}
    saved_count = len(url_index)

    telegram_count = int((by_origin.get("telegram") or {}).get("episodeCount") or 0)

    channels = {
        "chat-export:claude": _origin_channel(
            "chat-export:claude", "Claude chat export", "claude-export", by_origin, "conversation"),
        "chat-export:chatgpt": _origin_channel(
            "chat-export:chatgpt", "ChatGPT chat export", "chatgpt-export", by_origin, "conversation"),
        "bookmarks": _sync_channel(
            "bookmarks", "Chrome & Safari bookmarks", state, "bookmark"),
        "notes": _sync_channel("notes", "Apple Notes", state, "note"),
        "rss": _subscription_channel(
            "rss", "RSS feeds", feed_registry.list_feeds(memory_path), "feed"),
        "calendar": _subscription_channel(
            "calendar", "Calendars", calendar_registry.list_calendars(memory_path), "calendar"),
        "telegram": {
            "id": "telegram",
            "label": "Telegram bot",
            "connected": bool(telegram_enabled),
            "count": telegram_count,
            "last_sync": (by_origin.get("telegram") or {}).get("lastSeen") or None,
            "detail": (f"Bot configured · {_plural(telegram_count, 'capture')}"
                       if telegram_enabled else None),
            "actions": [],
        },
        "files": {
            "id": "files",
            "label": "Files & links",
            "connected": saved_count > 0,
            "count": saved_count,
            "last_sync": None,
            "detail": _plural(saved_count, "saved item") if saved_count else None,
            "actions": ["import"],
        },
    }
    return [channels[cid] for cid in CHANNEL_IDS]
```

- [ ] **Step 8: Run the tests and watch them pass**

Run: `api/.venv/bin/python -m pytest api/tests/test_source_channels.py -q`
Expected: PASS (9 tests).

- [ ] **Step 9: Commit the services**

```bash
git add api/services/sync_state.py api/services/channel_registry.py api/tests/test_source_channels.py
git commit -m "$(cat <<'EOF'
feat(sources): sync_state.json + channel_registry derivation (G62)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

- [ ] **Step 10: Write the failing endpoint + version-vector tests**

Append to `api/tests/test_source_channels.py`:

```python
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
    dump = "\x1eid-1\x1fFirst note\x1fBody text\x1f2026-08-30T09:00:00Z"
    resp = c.post("/sources/sync-notes", json={"notesDump": dump})
    assert resp.status_code == 200, resp.text
    assert sync_state.read_sync_state(memory).get("notes", {}).get("last_sync")
```

> Note for the implementer: `notes_sync.parse_notes_dump` owns the dump grammar.
> Before writing the assertion above, run
> `api/.venv/bin/python -c "from api.services import notes_sync; import inspect; print(inspect.getsource(notes_sync.parse_notes_dump))"`
> and build the `dump` string with that exact separator set. The assertion that
> matters is only that `sync_state` gained a `notes` entry — if a valid dump is
> awkward to construct, assert on `record_sync` being called by posting a dump
> that parses to zero notes and expecting `count == 0` with a non-null `last_sync`.

- [ ] **Step 11: Run them and watch them fail**

Run: `api/.venv/bin/python -m pytest api/tests/test_source_channels.py -q`
Expected: FAIL — `/sources/channels` returns 404 (route not defined).

- [ ] **Step 12: Add the schemas**

In `api/models/schemas.py`, immediately after the `NotesSyncResponse` class (which ends at line 888, just before the `# --- Provider connections (G50) ---` comment):

```python
# --- Capture channels (G62) --------------------------------------------------


class SourceChannel(CamelModel):
    """One capture channel as the Capture page sees it. `connected` is derived
    from persisted state only (registries, sync_state.json, env, origin counts)
    — never from the transient result of a sync/import button press."""

    id: str
    label: str
    connected: bool = False
    count: int = 0
    last_sync: Optional[str] = None
    detail: Optional[str] = None
    actions: list[str] = []


class SourceChannelsResponse(CamelModel):
    channels: list[SourceChannel] = []
```

- [ ] **Step 13: Fold `sync_state.json` into the `sources` version component**

In `api/services/sync_service.py`, add the import next to the other registry imports at the top:

```python
from api.services.sync_state import SYNC_STATE_FILENAME
```

and extend the `sources` component (currently `api/services/sync_service.py:73-79`) to:

```python
        # `feeds.yaml` / `calendars.yaml` (the RSS + ICS subscription registries)
        # ride the `sources` component: subscribing or unsubscribing changes
        # neither the sources dir nor the url index, so without them the app's
        # feed/calendar lists never learned they were stale. `sync_state.json`
        # (G62) rides it for the same reason: a bookmark/Notes sync flips a
        # channel to "connected" without touching any other component.
        "sources": (
            f"{src_count}:{src_max}"
            f":{file_mtime(mp / 'sources' / 'url_index.json'):.6f}"
            f":{file_mtime(mp / FEEDS_FILENAME):.6f}"
            f":{file_mtime(mp / CALENDARS_FILENAME):.6f}"
            f":{file_mtime(mp / SYNC_STATE_FILENAME):.6f}"
        ),
```

- [ ] **Step 14: Add the endpoint and the two `record_sync` calls**

In `api/routers/sources.py`, extend the service import line to include the new modules:

```python
from api.services import (
    bookmark_sync,
    calendar_registry,
    channel_registry,
    feed_registry,
    media_ingestor,
    notes_sync,
    sync_service,
    sync_state,
)
```

and the schema import to include `SourceChannel, SourceChannelsResponse`.

Add the endpoint directly below the existing `list_sources` function (before the `# --- Feed subscriptions` banner):

```python
@router.get("/sources/channels", response_model=SourceChannelsResponse)
async def list_source_channels(
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
):
    """Every capture channel + whether it is actually connected (G62).

    The Capture page renders its "Connected" list straight from this. State is
    derived from what is on disk (feeds/calendars registries, sync_state.json,
    origin counts, the saved-URL index) plus the Telegram env flag — nothing
    here reflects the result of the last button press, so the page is correct
    on a cold launch.
    """
    memory_path = settings.memory_path
    etag = sync_service.etag_for(memory_path, "sources", "episodes", "entities")
    if (early := sync_service.conditional(request, response, etag)) is not None:
        return early
    channels = channel_registry.build_channels(
        memory_path, telegram_enabled=settings.telegram_enabled
    )
    return SourceChannelsResponse(channels=[SourceChannel(**c) for c in channels])
```

In `sync_bookmarks`, replace the final `return BookmarkSyncResponse(**result)` with:

```python
    # G62: the only durable trace that bookmark sync ever ran. `found` is the
    # number of bookmarks seen this pass (new + already-known), which is what
    # the Capture row means by "412 bookmarks".
    found = sum(int(s.get("found") or 0) for s in result.get("sources", []))
    sync_state.record_sync(memory_path, "bookmarks", count=found)

    return BookmarkSyncResponse(**result)
```

In `sync_notes`, replace the final `return NotesSyncResponse(**result)` with:

```python
    sync_state.record_sync(memory_path, "notes", count=int(result.get("total") or 0))

    return NotesSyncResponse(**result)
```

- [ ] **Step 15: Run the whole backend suite**

Run: `api/.venv/bin/python -m pytest api/tests -q`
Expected: PASS. `api/tests/test_sync.py::test_etag_304_on_graph_and_inbox` and the sources tests must still pass — the `sources` component only gained a term.

- [ ] **Step 16: Commit**

```bash
git add api/models/schemas.py api/routers/sources.py api/services/sync_service.py api/tests/test_source_channels.py
git commit -m "$(cat <<'EOF'
feat(api): GET /sources/channels with ETag + sync_state in the version vector (G62)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

---

### Task 2: App `channels` sync domain

**Files:**
- Create: `app/CicadaApp/Sources/CicadaApp/Models/SourceChannel.swift`
- Create: `app/CicadaApp/Tests/CicadaAppTests/SourceChannelTests.swift`
- Modify: `app/CicadaApp/Sources/CicadaApp/Sync/Snapshot.swift:11-18` (`SyncDomain`)
- Modify: `app/CicadaApp/Sources/CicadaApp/Sync/Store.swift` (snapshot property, `hydrate` take, `refresh` switch, `resetInFlight`)
- Modify: `app/CicadaApp/Sources/CicadaApp/Sync/SyncAPI.swift` (protocol method)
- Modify: `app/CicadaApp/Sources/CicadaApp/Sync/VersionVector.swift:7-13` (mapping)
- Modify: `app/CicadaApp/Sources/CicadaApp/Services/APIClient.swift` (`extension APIClient: SyncAPI`, after `fetchSources`)
- Modify: `app/CicadaApp/Tests/CicadaAppTests/StoreTests.swift` (`FakeSyncAPI` gains `fetchChannels`)

**Interfaces:**
- Consumes: `GET /sources/channels` from Task 1 (camelCase `id/label/connected/count/lastSync/detail/actions`); `Conditional<T>`, `Snapshot<T>`, `SyncDomain`, `SnapshotCache` (all in `Sync/`).
- Produces:
  - `struct SourceChannel: Codable, Identifiable, Hashable` with `id, label, connected, count, lastSync, detail, actions` plus `var lastSyncDate: Date?` and `static func sortedConnected(_:) -> [SourceChannel]`.
  - `struct SourceChannelsResponse: Codable { let channels: [SourceChannel] }`
  - `SyncDomain.channels`
  - `Store.channels: Snapshot<[SourceChannel]>`
  - `SyncAPI.fetchChannels(etag: String?) async throws -> Conditional<[SourceChannel]>`

- [ ] **Step 1: Write the failing test**

Create `app/CicadaApp/Tests/CicadaAppTests/SourceChannelTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// `GET /sources/channels` decoding + the Capture page's row ordering (G62).
final class SourceChannelTests: XCTestCase {

    private static let json = """
    {"channels":[
      {"id":"rss","label":"RSS feeds","connected":true,"count":3,
       "lastSync":"2026-08-30T08:12:00Z","detail":"3 feeds · polled 2026-08-30",
       "actions":["poll","manage"]},
      {"id":"calendar","label":"Calendars","connected":false,"count":0,
       "lastSync":null,"detail":null,"actions":["poll","manage"]},
      {"id":"bookmarks","label":"Chrome & Safari bookmarks","connected":true,"count":412,
       "lastSync":"2026-08-29T10:00:00Z","detail":"412 bookmarks · synced 2026-08-29",
       "actions":["sync"]},
      {"id":"telegram","label":"Telegram bot","connected":true,
       "detail":"Bot configured · 18 captures","actions":[]}
    ]}
    """

    private func decoded() throws -> [SourceChannel] {
        try JSONDecoder().decode(SourceChannelsResponse.self, from: Data(Self.json.utf8)).channels
    }

    func testDecodesEveryField() throws {
        let byId = Dictionary(uniqueKeysWithValues: try decoded().map { ($0.id, $0) })
        let rss = try XCTUnwrap(byId["rss"])
        XCTAssertEqual(rss.label, "RSS feeds")
        XCTAssertTrue(rss.connected)
        XCTAssertEqual(rss.count, 3)
        XCTAssertEqual(rss.lastSync, "2026-08-30T08:12:00Z")
        XCTAssertEqual(rss.detail, "3 feeds · polled 2026-08-30")
        XCTAssertEqual(rss.actions, ["poll", "manage"])
    }

    /// A backend that omits the optional fields (older build, or a channel with
    /// no state) must still decode — never drop the row.
    func testDecodesToleratesMissingOptionalFields() throws {
        let byId = Dictionary(uniqueKeysWithValues: try decoded().map { ($0.id, $0) })
        let telegram = try XCTUnwrap(byId["telegram"])
        XCTAssertEqual(telegram.count, 0)
        XCTAssertNil(telegram.lastSync)
        XCTAssertTrue(telegram.actions.isEmpty)
    }

    /// The Connected list shows only connected channels, newest sync first,
    /// with a null lastSync sorting last and ties broken by label.
    func testSortedConnectedDropsDisconnectedAndOrdersByLastSyncDesc() throws {
        let sorted = SourceChannel.sortedConnected(try decoded())
        XCTAssertEqual(sorted.map(\.id), ["rss", "bookmarks", "telegram"])
    }

    func testChannelsRoundTripThroughTheSnapshotCache() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let cache = SnapshotCache(root: root)
        let channels = try decoded()
        await cache.save(channels, etag: "\"c1\"", domain: .channels, bank: "work")
        await cache.flush()
        let hit = await cache.load(.channels, bank: "work", as: [SourceChannel].self)
        XCTAssertEqual(hit?.value.map(\.id), channels.map(\.id))
        XCTAssertEqual(hit?.etag, "\"c1\"")
    }
}
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd app/CicadaApp && swift test --filter SourceChannelTests`
Expected: FAIL — `cannot find 'SourceChannel' in scope`.

- [ ] **Step 3: Write the model**

Create `app/CicadaApp/Sources/CicadaApp/Models/SourceChannel.swift`:

```swift
import Foundation

/// Mirror of api/models/schemas.py::SourceChannel (G62). One capture channel
/// and whether it is actually connected — derived server-side from persisted
/// state, so the Capture page is correct on a cold, offline launch.
///
/// Tolerant decoding: every field but `id` is optional so an older backend
/// (or a channel with no state at all) still yields a usable row.
struct SourceChannel: Codable, Identifiable, Hashable {
    let id: String
    let label: String
    let connected: Bool
    let count: Int
    let lastSync: String?
    let detail: String?
    let actions: [String]

    enum CodingKeys: String, CodingKey {
        case id, label, connected, count, lastSync, detail, actions
    }

    init(id: String, label: String, connected: Bool = false, count: Int = 0,
         lastSync: String? = nil, detail: String? = nil, actions: [String] = []) {
        self.id = id; self.label = label; self.connected = connected
        self.count = count; self.lastSync = lastSync; self.detail = detail
        self.actions = actions
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        label = try c.decodeIfPresent(String.self, forKey: .label) ?? id
        connected = try c.decodeIfPresent(Bool.self, forKey: .connected) ?? false
        count = try c.decodeIfPresent(Int.self, forKey: .count) ?? 0
        lastSync = try c.decodeIfPresent(String.self, forKey: .lastSync)
        detail = try c.decodeIfPresent(String.self, forKey: .detail)
        actions = try c.decodeIfPresent([String].self, forKey: .actions) ?? []
    }

    /// `lastSync` parsed for sorting. Accepts both the fractional- and
    /// plain-second ISO8601 forms the backend emits, and a bare `2026-08-29`.
    var lastSyncDate: Date? {
        guard let lastSync, !lastSync.isEmpty else { return nil }
        let withFraction = ISO8601DateFormatter()
        withFraction.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let d = withFraction.date(from: lastSync) { return d }
        let plain = ISO8601DateFormatter()
        plain.formatOptions = [.withInternetDateTime]
        if let d = plain.date(from: lastSync) { return d }
        let dayOnly = DateFormatter()
        dayOnly.dateFormat = "yyyy-MM-dd"
        dayOnly.timeZone = TimeZone(identifier: "UTC")
        return dayOnly.date(from: lastSync)
    }

    /// The Capture page's "Connected" list: connected rows only, most recently
    /// synced first. A channel with no timestamp (Telegram, Files & links)
    /// sorts after the timestamped ones; ties break on label for stability.
    static func sortedConnected(_ channels: [SourceChannel]) -> [SourceChannel] {
        channels.filter(\.connected).sorted { a, b in
            switch (a.lastSyncDate, b.lastSyncDate) {
            case let (l?, r?): return l == r ? a.label < b.label : l > r
            case (_?, nil): return true
            case (nil, _?): return false
            case (nil, nil): return a.label < b.label
            }
        }
    }
}

struct SourceChannelsResponse: Codable {
    let channels: [SourceChannel]
}
```

- [ ] **Step 4: Add the `channels` domain**

In `Sync/Snapshot.swift`, extend the enum's first case line:

```swift
enum SyncDomain: String, CaseIterable, Codable {
    case graph, inbox, banks, sources, channels, feeds, calendars, contributors, origins, connections, status
```

In `Sync/VersionVector.swift`, add `.channels` to the two components that can change it:

```swift
        "inbox": [.inbox, .graph, .status], "episodes": [.status, .origins, .sources, .channels],
        // The `sources` component folds in `feeds.yaml`, `calendars.yaml` and
        // `sync_state.json` (see `sync_service.components`), so the feed,
        // calendar and capture-channel lists all ride it.
        "sources": [.sources, .feeds, .calendars, .channels], "git_head": [.contributors], "sleep": [.status],
```

In `Sync/SyncAPI.swift`, add to the `SyncAPI` protocol right after `fetchSources`:

```swift
    func fetchChannels(etag: String?) async throws -> Conditional<[SourceChannel]>
```

In `Services/APIClient.swift`, inside `extension APIClient: SyncAPI`, right after `fetchSources(etag:)`:

```swift
    func fetchChannels(etag: String?) async throws -> Conditional<[SourceChannel]> {
        do {
            let c: Conditional<SourceChannelsResponse> = try await getConditional("/sources/channels", etag: etag)
            return c.map(\.channels)
        } catch APIError.httpError(404, _) {
            return .unavailable(etag: etag)
        }
    }
```

In `Sync/Store.swift`: add the snapshot next to `sources` (line 27),

```swift
    var sources = Snapshot<[MediaFeedItem]>()
    var channels = Snapshot<[SourceChannel]>()
```

hydrate it next to `.sources` (inside `hydrate`),

```swift
        await take(.sources, \.sources)
        await take(.channels, \.channels)
```

refresh it in the `refresh` switch, right after the `.sources` case,

```swift
            case .channels: await refreshOne(domain, \.channels) { [api] e in try await api.fetchChannels(etag: e) }
```

and clear it in `resetInFlight()`, next to `sources.isRefreshing = false`:

```swift
        sources.isRefreshing = false
        channels.isRefreshing = false
```

- [ ] **Step 5: Teach `FakeSyncAPI` about the new domain**

In `app/CicadaApp/Tests/CicadaAppTests/StoreTests.swift`, right after `fetchSources(etag:)`:

```swift
    func fetchChannels(etag: String?) async throws -> Conditional<[SourceChannel]> {
        try answer(.channels, fallback: [])
    }
```

- [ ] **Step 6: Run the app tests**

Run: `cd app/CicadaApp && swift test`
Expected: PASS. `StoreTests.testApplyVersionRefreshesOnlyChangedDomains` still passes because its changed component is `inbox`, which does not map to `.channels`; `testHydrateLoadsFromSeededCache` still passes because a cache miss resets the snapshot.

- [ ] **Step 7: Commit**

```bash
git add app/CicadaApp/Sources/CicadaApp/Models/SourceChannel.swift app/CicadaApp/Sources/CicadaApp/Sync/Snapshot.swift app/CicadaApp/Sources/CicadaApp/Sync/Store.swift app/CicadaApp/Sources/CicadaApp/Sync/SyncAPI.swift app/CicadaApp/Sources/CicadaApp/Sync/VersionVector.swift app/CicadaApp/Sources/CicadaApp/Services/APIClient.swift app/CicadaApp/Tests/CicadaAppTests/SourceChannelTests.swift app/CicadaApp/Tests/CicadaAppTests/StoreTests.swift
git commit -m "$(cat <<'EOF'
feat(app): channels sync domain backed by GET /sources/channels (G62)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

---

### Task 3: Move the reusable Capture sub-views + build the walkthrough panel

This task only *relocates* existing views and adds the walkthrough panel and its
docs. `SourcesView.swift` still compiles and behaves identically at the end of
it; the rewrite is Task 4.

**Files:**
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Capture/Sheets/CaptureRows.swift`
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Capture/OriginPill.swift`
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Capture/Sheets/WalkthroughPanel.swift`
- Create: `app/CicadaApp/Tests/CicadaAppTests/WalkthroughTests.swift`
- Create: `docs/walkthrough-recording.md`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Capture/SourcesView.swift` — delete lines 1107–1341 (the four `private struct`s).

**Interfaces:**
- Consumes: `CicadaTheme` tokens, `FeedSubscription` / `CalendarSubscription` (`Services/APIClient.swift:270+`), `OriginStat`.
- Produces:
  - `struct ImportTileButton: View` — `init(icon:label:isBusy:isActive:action:)`, unchanged behaviour.
  - `struct FeedSubscriptionRow: View` — `init(feed:isRemoving:onRemove:)`.
  - `struct CalendarSubscriptionRow: View` — `init(calendar:isRemoving:onRemove:)`.
  - `struct OriginPill: View` — `init(origin:)`.
  - `enum WalkthroughVendor: String, CaseIterable, Identifiable` with `title`, `exportURL: URL`, `steps: [String]`, `videoName: String`.
  - `struct WalkthroughPanel: View` — `init(vendor: Binding<WalkthroughVendor>, onChooseFile: @escaping () -> Void)`.

- [ ] **Step 1: Move the four sub-views, unchanged apart from dropping `private`**

Create `app/CicadaApp/Sources/CicadaApp/Views/Capture/Sheets/CaptureRows.swift` holding
`ImportTileButton`, `FeedSubscriptionRow` and `CalendarSubscriptionRow`, and
`app/CicadaApp/Sources/CicadaApp/Views/Capture/OriginPill.swift` holding `OriginPill`.
Copy each body **verbatim** from `SourcesView.swift` (lines 1107–1141, 1145–1199,
1203–1257 and 1265–1341 respectively), changing only `private struct X: View` to
`struct X: View` and keeping the `// MARK:` banner comments. Then delete those
four declarations from `SourcesView.swift`.

Each new file starts with:

```swift
import SwiftUI
```

(`OriginPill.swift` needs nothing else; `CaptureRows.swift` needs nothing else.)

- [ ] **Step 2: Verify the move is behaviour-neutral**

Run: `cd app/CicadaApp && swift build`
Expected: builds clean. Then `wc -l app/CicadaApp/Sources/CicadaApp/Views/Capture/SourcesView.swift` — expect ~1103.

- [ ] **Step 3: Commit the move on its own**

```bash
git add app/CicadaApp/Sources/CicadaApp/Views/Capture/Sheets/CaptureRows.swift app/CicadaApp/Sources/CicadaApp/Views/Capture/OriginPill.swift app/CicadaApp/Sources/CicadaApp/Views/Capture/SourcesView.swift
git commit -m "$(cat <<'EOF'
refactor(app): extract Capture sub-views out of SourcesView (G62)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

- [ ] **Step 4: Write the failing walkthrough test**

Create `app/CicadaApp/Tests/CicadaAppTests/WalkthroughTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// The import walkthroughs (G64): every vendor must carry a real, reachable
/// settings URL and a short numbered step list. These strings are the whole
/// feature — a typo'd host silently opens nothing, so pin them.
final class WalkthroughTests: XCTestCase {

    func testEveryVendorHasAnHTTPSExportURL() {
        for vendor in WalkthroughVendor.allCases {
            XCTAssertEqual(vendor.exportURL.scheme, "https", "\(vendor.rawValue)")
            XCTAssertNotNil(vendor.exportURL.host, "\(vendor.rawValue)")
        }
    }

    func testTheVendorURLTableIsExactlyTheSpecTable() {
        let table = Dictionary(uniqueKeysWithValues:
            WalkthroughVendor.allCases.map { ($0.rawValue, $0.exportURL.absoluteString) })
        XCTAssertEqual(table, [
            "claude": "https://claude.ai/settings/data-privacy-controls",
            "chatgpt": "https://chatgpt.com/#settings/DataControls",
            "takeout": "https://takeout.google.com/",
            "instagram": "https://accountscenter.instagram.com/info_and_permissions/dyi/",
        ])
    }

    func testEveryVendorHasThreeOrFourSteps() {
        for vendor in WalkthroughVendor.allCases {
            XCTAssertTrue((3...4).contains(vendor.steps.count),
                          "\(vendor.rawValue) has \(vendor.steps.count) steps")
            XCTAssertFalse(vendor.steps.contains(where: \.isEmpty), "\(vendor.rawValue)")
        }
    }

    func testVideoNamesAreDistinctAndFilenameSafe() {
        let names = WalkthroughVendor.allCases.map(\.videoName)
        XCTAssertEqual(Set(names).count, names.count)
        XCTAssertTrue(names.allSatisfy { $0.allSatisfy { c in c.isLetter || c.isNumber || c == "-" } })
    }
}
```

- [ ] **Step 5: Run it and watch it fail**

Run: `cd app/CicadaApp && swift test --filter WalkthroughTests`
Expected: FAIL — `cannot find 'WalkthroughVendor' in scope`.

- [ ] **Step 6: Write the walkthrough panel**

Create `app/CicadaApp/Sources/CicadaApp/Views/Capture/Sheets/WalkthroughPanel.swift`:

```swift
import AVKit
import AppKit
import SwiftUI

/// The export walkthrough shown inside the "+" sheet (G64): pick a vendor, read
/// three or four steps, jump straight to that vendor's export settings page,
/// then drop the file. The 16:9 area plays `Resources/walkthroughs/<vendor>.mp4`
/// when one has been recorded (muted, looping) and shows a static placeholder
/// otherwise — the recordings are a separate manual pass, see
/// docs/walkthrough-recording.md.
enum WalkthroughVendor: String, CaseIterable, Identifiable {
    case claude, chatgpt, takeout, instagram

    var id: String { rawValue }

    var title: String {
        switch self {
        case .claude: "Claude"
        case .chatgpt: "ChatGPT"
        case .takeout: "Google Takeout"
        case .instagram: "Instagram"
        }
    }

    /// The page that actually holds the export button. Opened with
    /// `NSWorkspace.shared.open` — no deep-link scheme, just the web settings.
    var exportURL: URL {
        switch self {
        case .claude: URL(string: "https://claude.ai/settings/data-privacy-controls")!
        case .chatgpt: URL(string: "https://chatgpt.com/#settings/DataControls")!
        case .takeout: URL(string: "https://takeout.google.com/")!
        case .instagram: URL(string: "https://accountscenter.instagram.com/info_and_permissions/dyi/")!
        }
    }

    var steps: [String] {
        switch self {
        case .claude: [
            "Open Settings → Privacy on claude.ai.",
            "Click “Export data” and confirm.",
            "Anthropic emails you a .zip — unzip it.",
            "Drop conversations.json here.",
        ]
        case .chatgpt: [
            "Open Settings → Data controls on chatgpt.com.",
            "Click “Export data” and confirm.",
            "OpenAI emails you a .zip — unzip it.",
            "Drop conversations.json here.",
        ]
        case .takeout: [
            "Open Google Takeout and click “Deselect all”.",
            "Select YouTube, then limit it to “playlists” and “history”.",
            "Export as a .zip and download it.",
            "Drop the .zip here — Cicada reads the playlists and watch history.",
        ]
        case .instagram: [
            "Open Accounts Center → Your information and permissions.",
            "Choose “Download your information”, JSON format.",
            "Instagram emails you a link — download and unzip it.",
            "Drop saved_posts.json here.",
        ]
        }
    }

    /// Base name of the bundled recording, if one exists.
    var videoName: String { rawValue }

    /// The one-line "what this gets you" under the picker.
    var summary: String {
        switch self {
        case .claude: "Every Claude conversation, backdated to when it happened."
        case .chatgpt: "Every ChatGPT conversation, backdated to when it happened."
        case .takeout: "Your YouTube playlists and watch history as saved links."
        case .instagram: "Your saved Instagram posts as saved links."
        }
    }
}

struct WalkthroughPanel: View {
    @Binding var vendor: WalkthroughVendor
    let onChooseFile: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            Picker("Export from", selection: $vendor) {
                ForEach(WalkthroughVendor.allCases) { v in
                    Text(v.title).tag(v)
                }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .accessibilityLabel("Choose which service to export from")

            Text(vendor.summary)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textSecondary)

            stage

            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                ForEach(Array(vendor.steps.enumerated()), id: \.offset) { index, step in
                    HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
                        Text("\(index + 1)")
                            .font(.system(size: 10, weight: .semibold, design: .monospaced))
                            .foregroundStyle(CicadaTheme.accent)
                            .frame(width: 14, alignment: .trailing)
                        Text(step)
                            .font(CicadaTheme.bodyFont)
                            .foregroundStyle(CicadaTheme.textSecondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            }

            HStack(spacing: CicadaTheme.spacingMD) {
                Button {
                    NSWorkspace.shared.open(vendor.exportURL)
                } label: {
                    Label("Open \(vendor.title) export settings", systemImage: "arrow.up.forward.app")
                        .font(.system(size: 12, weight: .semibold))
                }
                .buttonStyle(.borderedProminent)
                .accessibilityLabel("Open \(vendor.title) export settings in your browser")

                Button("Choose file…", action: onChooseFile)
                    .buttonStyle(.bordered)
                    .accessibilityLabel("Choose the exported file to import")
            }
        }
    }

    /// Reserved 16:9 area: the recording when it ships, a labelled placeholder
    /// until then. Sized by aspect ratio so the panel doesn't jump when a video
    /// is dropped in later.
    @ViewBuilder
    private var stage: some View {
        ZStack {
            RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                .fill(CicadaTheme.surfaceElevated)
            if let url = Self.videoURL(for: vendor) {
                LoopingVideo(url: url)
                    .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
            } else {
                VStack(spacing: CicadaTheme.spacingXS) {
                    Image(systemName: "play.rectangle")
                        .font(.system(size: 22))
                        .foregroundStyle(CicadaTheme.textTertiary)
                    Text("Walkthrough video coming soon")
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
            }
        }
        .aspectRatio(16.0 / 9.0, contentMode: .fit)
        .frame(maxWidth: .infinity)
        .accessibilityLabel("\(vendor.title) export walkthrough")
    }

    static func videoURL(for vendor: WalkthroughVendor) -> URL? {
        Bundle.module.url(forResource: vendor.videoName, withExtension: "mp4",
                          subdirectory: "Resources/walkthroughs")
    }
}

/// Muted, looping, chrome-less player for a bundled walkthrough clip.
private struct LoopingVideo: NSViewRepresentable {
    let url: URL

    func makeNSView(context: Context) -> AVPlayerView {
        let item = AVPlayerItem(url: url)
        let queue = AVQueuePlayer(items: [item])
        queue.isMuted = true
        context.coordinator.looper = AVPlayerLooper(player: queue, templateItem: item)
        let view = AVPlayerView()
        view.controlsStyle = .none
        view.videoGravity = .resizeAspect
        view.player = queue
        queue.play()
        return view
    }

    func updateNSView(_ nsView: AVPlayerView, context: Context) {}

    func makeCoordinator() -> Coordinator { Coordinator() }

    final class Coordinator {
        var looper: AVPlayerLooper?
    }
}
```

- [ ] **Step 7: Run the walkthrough tests**

Run: `cd app/CicadaApp && swift test --filter WalkthroughTests`
Expected: PASS (4 tests).

- [ ] **Step 8: Write the recording runbook**

Create `docs/walkthrough-recording.md`:

```markdown
# Recording the import walkthrough clips (G64)

The `+` sheet on the Capture page reserves a 16:9 area per vendor. It plays
`app/CicadaApp/Sources/CicadaApp/Resources/walkthroughs/<vendor>.mp4` when that
file exists (muted, looping, no controls) and shows a "coming soon" placeholder
otherwise. Nothing else needs to change to ship a clip — `Package.swift` uses
`.copy("Resources")`, so dropping the file in is enough.

## Vendors and file names

| Vendor | File | Export page the clip must land on |
|---|---|---|
| Claude | `claude.mp4` | https://claude.ai/settings/data-privacy-controls |
| ChatGPT | `chatgpt.mp4` | https://chatgpt.com/#settings/DataControls |
| Google Takeout | `takeout.mp4` | https://takeout.google.com/ |
| Instagram | `instagram.mp4` | https://accountscenter.instagram.com/info_and_permissions/dyi/ |

The vendor list and these URLs are pinned by
`app/CicadaApp/Tests/CicadaAppTests/WalkthroughTests.swift`; change them there
first if a vendor moves its page.

## Constraints

- **1280×720, 16:9**, H.264 MP4.
- **≤ 2 MB per clip.** They ship inside the app bundle.
- **No audio** — the player is muted and looping, so a soundtrack is dead weight.
- **10–20 s.** Long enough to show the click path, short enough to loop cleanly.
- **Never record real personal data.** Use a throwaway account, or blur the
  conversation list. The clip ships to every user.

## How to record

Either works:

1. **Screen Studio** — records at 2× with automatic cursor zoom, exports MP4
   directly. Set the canvas to 1280×720 and turn the background padding off.
2. **`screencapture -v`** (built in):
   ```sh
   screencapture -v -R 0,0,1280,720 ~/Desktop/claude-raw.mov
   # ...perform the click path, then Ctrl-C
   ffmpeg -i ~/Desktop/claude-raw.mov -vf scale=1280:720 -an \
       -c:v libx264 -crf 30 -preset slow -movflags +faststart \
       app/CicadaApp/Sources/CicadaApp/Resources/walkthroughs/claude.mp4
   ```
   `screencapture` has no cursor zoom, so keep the click targets large — resize
   the browser window rather than relying on post-hoc magnification.

Check the size with `ls -lh` before committing; re-encode at a higher `-crf` if
a clip is over 2 MB.
```

- [ ] **Step 9: Commit**

```bash
git add app/CicadaApp/Sources/CicadaApp/Views/Capture/Sheets/WalkthroughPanel.swift app/CicadaApp/Tests/CicadaAppTests/WalkthroughTests.swift docs/walkthrough-recording.md
git commit -m "$(cat <<'EOF'
feat(app): import walkthrough panel with vendor export links (G64)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

---

### Task 4: The "+" picker sheet (`AddSourceSheet`)

All explanatory copy for capture lives here and nowhere else — the page itself
(Task 5) shows only what is connected.

**Files:**
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Capture/Sheets/AddSourceSheet.swift`
- Modify: `app/CicadaApp/Tests/CicadaAppTests/SourceChannelTests.swift` (add the catalogue-completeness test)

**Interfaces:**
- Consumes: `WalkthroughPanel` / `WalkthroughVendor` (Task 3), `ImportTileButton` (Task 3), `FeedSubscriptionRow` / `CalendarSubscriptionRow` (Task 3), `SourceChannel` (Task 2), `Store` (`store.feeds`, `store.calendars`), `SubscribeFeed` / `UnsubscribeFeed` / `SubscribeCalendar` / `UnsubscribeCalendar` mutations (`Sync/Mutations.swift`), `APIClient.shared.saveURL(_:note:)`, `.uploadFile(fileURL:)`, `.uploadSource(fileURL:)`, `.syncBookmarks()`, `.syncNotes()`.
- Produces:
  - `enum AddSourceTile: String, CaseIterable, Identifiable` with `title`, `blurb`, `icon`, `channelIds: [String]`, and `static func forChannel(_:) -> AddSourceTile?`.
  - `struct AddSourceSheet: View` — `init(initialTile: AddSourceTile? = nil, onClose: @escaping () -> Void)`.

- [ ] **Step 1: Write the failing catalogue test**

Append to `app/CicadaApp/Tests/CicadaAppTests/SourceChannelTests.swift`:

```swift
/// The "+" sheet must be able to explain every channel the backend can report
/// as connected — a channel with no tile is a dead end for the user (the row
/// appears, "Manage…" opens nothing).
final class AddSourceCatalogTests: XCTestCase {

    /// Mirrors api/services/channel_registry.py::CHANNEL_IDS.
    private static let backendChannelIds: Set<String> = [
        "chat-export:claude", "chat-export:chatgpt", "bookmarks", "notes",
        "rss", "calendar", "telegram", "files",
    ]

    func testEveryBackendChannelHasATile() {
        let covered = Set(AddSourceTile.allCases.flatMap(\.channelIds))
        XCTAssertEqual(Self.backendChannelIds.subtracting(covered), [],
                       "backend channels with no tile in the + sheet")
    }

    func testEveryTileHasTitleAndBlurb() {
        for tile in AddSourceTile.allCases {
            XCTAssertFalse(tile.title.isEmpty, tile.rawValue)
            XCTAssertFalse(tile.blurb.isEmpty, tile.rawValue)
            XCTAssertFalse(tile.icon.isEmpty, tile.rawValue)
        }
    }

    func testChannelIdsAreUniqueAcrossTiles() {
        let ids = AddSourceTile.allCases.flatMap(\.channelIds)
        XCTAssertEqual(Set(ids).count, ids.count, "two tiles claim the same channel")
    }
}
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd app/CicadaApp && swift test --filter AddSourceCatalogTests`
Expected: FAIL — `cannot find 'AddSourceTile' in scope`.

- [ ] **Step 3: Write the sheet**

Create `app/CicadaApp/Sources/CicadaApp/Views/Capture/Sheets/AddSourceSheet.swift`:

```swift
import AppKit
import SwiftUI
import UniformTypeIdentifiers

/// The Capture page's "+" picker (G62). A grid of tiles; picking one expands it
/// into that channel's flow inline. **All** explanatory copy about capture
/// lives here — the page behind it shows only what is already connected, so
/// this sheet is the single place a user learns what Cicada can read.
///
/// "Manage…" from a connected row opens this sheet already expanded on that
/// channel's tile (`initialTile:`), where feeds and calendars show their
/// current rows with remove buttons.
enum AddSourceTile: String, CaseIterable, Identifiable {
    case chatExport, bookmarksFile, pasteLink, rssFeed, calendar
    case browserBookmarks, appleNotes, telegram, savedContent

    var id: String { rawValue }

    var title: String {
        switch self {
        case .chatExport: "Chat export"
        case .bookmarksFile: "Bookmarks file"
        case .pasteLink: "Paste a link"
        case .rssFeed: "RSS feed"
        case .calendar: "Calendar"
        case .browserBookmarks: "Chrome & Safari bookmarks"
        case .appleNotes: "Apple Notes"
        case .telegram: "Telegram bot"
        case .savedContent: "Instagram saved / YouTube playlists"
        }
    }

    var blurb: String {
        switch self {
        case .chatExport: "Everything you've said to Claude or ChatGPT, backdated."
        case .bookmarksFile: "An exported bookmarks file — HTML or JSON."
        case .pasteLink: "One URL, saved and enriched right now."
        case .rssFeed: "A blog or Substack Cicada checks for new posts."
        case .calendar: "A webcal/ICS URL — events become episodes."
        case .browserBookmarks: "Read straight off this Mac. No login, no OAuth."
        case .appleNotes: "One-way import from your local Notes library."
        case .telegram: "Forward links and voice notes to your own bot."
        case .savedContent: "Saved posts and playlists from a data export."
        }
    }

    var icon: String {
        switch self {
        case .chatExport: "bubble.left.and.bubble.right"
        case .bookmarksFile: "bookmark"
        case .pasteLink: "link"
        case .rssFeed: "dot.radiowaves.up.forward"
        case .calendar: "calendar"
        case .browserBookmarks: "globe"
        case .appleNotes: "note.text"
        case .telegram: "paperplane.fill"
        case .savedContent: "camera.fill"
        }
    }

    /// The `GET /sources/channels` ids this tile manages.
    ///
    /// Chat export owns **both** export channels — its walkthrough picker is
    /// where the user chooses Claude or ChatGPT, so one tile covers two rows.
    /// `pasteLink` and `savedContent` own none: they are alternative routes
    /// into `files`, which `bookmarksFile` already claims, and a channel must
    /// map back to exactly one tile for "Manage…" to be unambiguous.
    var channelIds: [String] {
        switch self {
        case .chatExport: ["chat-export:claude", "chat-export:chatgpt"]
        case .bookmarksFile: ["files"]
        case .pasteLink: []
        case .rssFeed: ["rss"]
        case .calendar: ["calendar"]
        case .browserBookmarks: ["bookmarks"]
        case .appleNotes: ["notes"]
        case .telegram: ["telegram"]
        case .savedContent: []
        }
    }

    /// Reverse lookup for "Manage…" on a connected row.
    static func forChannel(_ channelId: String) -> AddSourceTile? {
        allCases.first { $0.channelIds.contains(channelId) }
    }
}

struct AddSourceSheet: View {
    var initialTile: AddSourceTile?
    let onClose: () -> Void

    @Environment(Store.self) private var store

    @State private var expanded: AddSourceTile?
    @State private var vendor: WalkthroughVendor = .claude
    @State private var linkText = ""
    @State private var feedText = ""
    @State private var calendarText = ""
    @State private var busy = false
    @State private var result: String?
    @State private var error: String?
    @State private var removingFeed: String?
    @State private var removingCalendar: String?

    private var feeds: [FeedSubscription] { store.feeds.value ?? [] }
    private var calendars: [CalendarSubscription] { store.calendars.value ?? [] }

    private let columns = [GridItem(.adaptive(minimum: 190), spacing: CicadaTheme.spacingMD)]

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            Divider().background(CicadaTheme.border)
            ScrollView {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                    LazyVGrid(columns: columns, spacing: CicadaTheme.spacingMD) {
                        ForEach(AddSourceTile.allCases) { tile in
                            tileButton(tile)
                        }
                    }
                    if let expanded { flow(for: expanded) }
                    statusLine
                }
                .padding(CicadaTheme.spacingXL)
            }
        }
        .frame(width: 640, height: 620)
        .background(CicadaTheme.background)
        .onAppear {
            if expanded == nil, let initialTile {
                expanded = initialTile
                vendor = initialTile == .savedContent ? .instagram : .claude
            }
        }
    }

    private var header: some View {
        HStack(alignment: .firstTextBaseline) {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                Text("Add a source")
                    .font(CicadaTheme.titleFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                Text("Anything you add lands in the queue for the next Sleep cycle.")
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
            }
            Spacer()
            Button("Done", action: onClose)
                .buttonStyle(.bordered)
                .accessibilityLabel("Close the add-source sheet")
        }
        .padding(CicadaTheme.spacingXL)
    }

    private func tileButton(_ tile: AddSourceTile) -> some View {
        Button {
            error = nil
            result = nil
            expanded = expanded == tile ? nil : tile
            if tile == .savedContent { vendor = .instagram }
            if tile == .chatExport { vendor = .claude }
        } label: {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                Image(systemName: tile.icon)
                    .font(.system(size: 16, weight: .medium))
                    .foregroundStyle(expanded == tile ? CicadaTheme.accent : CicadaTheme.textSecondary)
                Text(tile.title)
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1)
                Text(tile.blurb)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(CicadaTheme.spacingMD)
            .background(
                RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                    .fill(expanded == tile ? CicadaTheme.accent.opacity(0.12) : CicadaTheme.surfaceElevated)
            )
            .overlay(
                RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                    .stroke(expanded == tile ? CicadaTheme.accent.opacity(0.5) : CicadaTheme.border, lineWidth: 1)
            )
        }
        .buttonStyle(.plain)
        .disabled(busy)
        .accessibilityLabel("\(tile.title). \(tile.blurb)")
    }

    // MARK: - Per-tile flows

    @ViewBuilder
    private func flow(for tile: AddSourceTile) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            switch tile {
            case .chatExport:
                WalkthroughPanel(vendor: $vendor) { pickChatExport() }
            case .savedContent:
                WalkthroughPanel(vendor: $vendor) { pickSavedContent() }
            case .bookmarksFile:
                Text("A Netscape-format .html, a Chrome .json, a YouTube playlist .csv, or a whole Takeout .zip.")
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                Button("Choose file…") { pickSavedContent() }
                    .buttonStyle(.borderedProminent)
                    .accessibilityLabel("Choose a bookmarks file to import")
            case .pasteLink:
                textFlow(placeholder: "https://…", text: $linkText, action: "Save") { await saveLink() }
            case .rssFeed:
                textFlow(placeholder: "https://example.com/feed.xml", text: $feedText, action: "Subscribe") { await subscribeFeed() }
                feedList
            case .calendar:
                textFlow(placeholder: "webcal://… or https://…/calendar.ics", text: $calendarText, action: "Subscribe") { await subscribeCalendar() }
                calendarList
            case .browserBookmarks:
                Text("Cicada reads the Chrome and Safari bookmark files on this Mac directly. Only URLs it hasn't seen become new episodes.")
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                Button("Sync now") { Task { await syncBookmarks() } }
                    .buttonStyle(.borderedProminent)
                    .disabled(busy)
                    .accessibilityLabel("Sync Chrome and Safari bookmarks now")
            case .appleNotes:
                Text("One-way import from Notes.app. The first sync asks macOS for automation access — allow it once.")
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                Button("Sync now") { Task { await syncNotes() } }
                    .buttonStyle(.borderedProminent)
                    .disabled(busy)
                    .accessibilityLabel("Sync Apple Notes now")
            case .telegram:
                telegramInstructions
            }
        }
        .padding(CicadaTheme.spacingLG)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard()
    }

    private func textFlow(placeholder: String, text: Binding<String>, action: String,
                          run: @escaping () async -> Void) -> some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            TextField(placeholder, text: text)
                .textFieldStyle(.roundedBorder)
                .onSubmit { Task { await run() } }
            Button(action) { Task { await run() } }
                .buttonStyle(.borderedProminent)
                .disabled(busy || text.wrappedValue.trimmingCharacters(in: .whitespaces).isEmpty)
                .accessibilityLabel(action)
        }
    }

    @ViewBuilder
    private var feedList: some View {
        if !feeds.isEmpty {
            VStack(spacing: CicadaTheme.spacingXS) {
                ForEach(feeds) { feed in
                    FeedSubscriptionRow(feed: feed, isRemoving: removingFeed == feed.url) {
                        Task {
                            removingFeed = feed.url
                            await store.perform(UnsubscribeFeed(url: feed.url))
                            removingFeed = nil
                        }
                    }
                }
            }
        }
    }

    @ViewBuilder
    private var calendarList: some View {
        if !calendars.isEmpty {
            VStack(spacing: CicadaTheme.spacingXS) {
                ForEach(calendars) { cal in
                    CalendarSubscriptionRow(calendar: cal, isRemoving: removingCalendar == cal.url) {
                        Task {
                            removingCalendar = cal.url
                            await store.perform(UnsubscribeCalendar(url: cal.url))
                            removingCalendar = nil
                        }
                    }
                }
            }
        }
    }

    private var telegramInstructions: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            Text("Create a bot with @BotFather, then set CICADA_TELEGRAM_BOT_TOKEN in api/.env and restart the backend. Forward it a link to save it, or send /note to capture a thought.")
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            CommandBox(command: "CICADA_TELEGRAM_BOT_TOKEN=<token>")
            Button {
                NSWorkspace.shared.open(URL(string: "https://t.me/BotFather")!)
            } label: {
                Label("Open BotFather", systemImage: "arrow.up.forward.app")
            }
            .buttonStyle(.bordered)
            .accessibilityLabel("Open BotFather in Telegram")
        }
    }

    @ViewBuilder
    private var statusLine: some View {
        if busy {
            HStack(spacing: CicadaTheme.spacingSM) {
                ProgressView().controlSize(.small)
                Text("Working…").font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
            }
        } else if let result {
            Text(result).font(CicadaTheme.captionFont).foregroundStyle(Color(hex: 0x22C55E))
        } else if let error {
            Text(error).font(CicadaTheme.captionFont).foregroundStyle(Color(hex: 0xEF4444))
        }
    }

    // MARK: - Actions

    private func finish(_ message: String) async {
        result = message
        error = nil
        busy = false
        await store.refresh([.channels, .status, .sources])
    }

    private func fail(_ err: Error) {
        error = Self.friendlyError(err)
        result = nil
        busy = false
    }

    private func saveLink() async {
        let url = linkText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !url.isEmpty else { return }
        busy = true
        do {
            let r = try await APIClient.shared.saveURL(url)
            linkText = ""
            await finish(r.message)
        } catch { fail(error) }
    }

    private func subscribeFeed() async {
        let url = feedText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !url.isEmpty else { return }
        busy = true
        let ok = await store.perform(SubscribeFeed(url: url, tags: []))
        feedText = ok ? "" : feedText
        busy = false
        if ok { await finish("Subscribed — Cicada polls it from now on") } else { error = store.toast }
    }

    private func subscribeCalendar() async {
        let url = calendarText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !url.isEmpty else { return }
        busy = true
        let ok = await store.perform(SubscribeCalendar(url: url, tags: []))
        calendarText = ok ? "" : calendarText
        busy = false
        if ok { await finish("Subscribed — events arrive on the next poll") } else { error = store.toast }
    }

    private func syncBookmarks() async {
        busy = true
        do {
            let r = try await APIClient.shared.syncBookmarks()
            await finish("\(r.new) new · \(r.skipped) already saved")
        } catch { fail(error) }
    }

    private func syncNotes() async {
        busy = true
        do {
            let r = try await APIClient.shared.syncNotes()
            await finish("\(r.new) new · \(r.updated) updated · \(r.skipped) unchanged")
        } catch { fail(error) }
    }

    private func pickChatExport() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.json, .html]
        panel.allowsMultipleSelection = true
        panel.canChooseDirectories = true
        panel.message = "Select a Claude, ChatGPT, or Gemini conversation export"
        guard panel.runModal() == .OK else { return }
        let files = Self.expandToFiles(panel.urls, exts: ["json", "html"])
        guard !files.isEmpty else { error = "No JSON or HTML files found"; return }
        runImport(files: files) { try await APIClient.shared.uploadFile(fileURL: $0) }
    }

    private func pickSavedContent() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.json, .html, .commaSeparatedText, .zip]
        panel.allowsMultipleSelection = true
        panel.canChooseDirectories = false
        panel.message = "Select a bookmarks/saved-content export (HTML, JSON, CSV, or ZIP)"
        guard panel.runModal() == .OK, !panel.urls.isEmpty else { return }
        runImport(files: panel.urls) { try await APIClient.shared.uploadSource(fileURL: $0) }
    }

    private func runImport(files: [URL], upload: @escaping (URL) async throws -> UploadResponse) {
        busy = true
        error = nil
        result = nil
        Task {
            var created = 0, skipped = 0
            var firstError: String?
            for file in files {
                do {
                    let r = try await upload(file)
                    created += r.episodesCreated
                    skipped += r.duplicatesSkipped
                } catch {
                    if firstError == nil { firstError = Self.friendlyError(error) }
                }
            }
            if created == 0, let firstError {
                self.error = firstError
                self.result = nil
                busy = false
            } else {
                var summary = "Imported \(created), skipped \(skipped)"
                if firstError != nil { summary += " (some files failed)" }
                await finish(summary)
            }
        }
    }

    private static func expandToFiles(_ urls: [URL], exts: Set<String>) -> [URL] {
        var out: [URL] = []
        let fm = FileManager.default
        for url in urls {
            var isDir: ObjCBool = false
            if fm.fileExists(atPath: url.path, isDirectory: &isDir), isDir.boolValue {
                if let e = fm.enumerator(at: url, includingPropertiesForKeys: nil) {
                    for case let f as URL in e where exts.contains(f.pathExtension.lowercased()) {
                        out.append(f)
                    }
                }
            } else if exts.contains(url.pathExtension.lowercased()) {
                out.append(url)
            }
        }
        return out
    }

    /// Same rule as the old SourcesView: surface the backend's `detail` rather
    /// than raw JSON, and give 404 a "not shipped yet" spin.
    static func friendlyError(_ error: Error) -> String {
        if case APIError.httpError(let code, let msg) = error {
            if code == 404 { return "That endpoint isn't available yet — update the Cicada backend." }
            if let data = msg.data(using: .utf8),
               let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               let detail = obj["detail"] as? String {
                return detail
            }
            return msg
        }
        return error.localizedDescription
    }
}
```

- [ ] **Step 4: Run the tests**

Run: `cd app/CicadaApp && swift test --filter AddSourceCatalogTests`
Expected: PASS (3 tests). Then `cd app/CicadaApp && swift build` — the sheet must compile against the real `Store`/mutation signatures.

- [ ] **Step 5: Commit**

```bash
git add app/CicadaApp/Sources/CicadaApp/Views/Capture/Sheets/AddSourceSheet.swift app/CicadaApp/Tests/CicadaAppTests/SourceChannelTests.swift
git commit -m "$(cat <<'EOF'
feat(app): AddSourceSheet — one tile per capture channel (G62)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

---

### Task 5: Rewrite `SourcesView`

**Files:**
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Capture/ConnectedChannelRow.swift`
- Modify (rewrite): `app/CicadaApp/Sources/CicadaApp/Views/Capture/SourcesView.swift`

**Interfaces:**
- Consumes: `SourceChannel` + `SourceChannel.sortedConnected` (Task 2), `store.channels` (Task 2), `AddSourceSheet` / `AddSourceTile` (Task 4), `OriginPill` (Task 3), `PageHeader`, `SleepViewModel`.
- Produces: `struct ConnectedChannelRow: View` — `init(channel:onAction:)` where `onAction: (String) -> Void` receives the action id (`"poll" | "sync" | "manage" | "import" | "remove"`).

- [ ] **Step 1: Write `ConnectedChannelRow`**

Create `app/CicadaApp/Sources/CicadaApp/Views/Capture/ConnectedChannelRow.swift`:

```swift
import SwiftUI

/// One connected capture channel on the Capture page (G62): a 28-pt circular
/// icon, the channel label, the server's own `detail` line, and a trailing ⋯
/// menu carrying exactly the actions the backend said this channel supports.
///
/// The whole row is a `Button` (opens "Manage…") so VoiceOver and UI automation
/// can reach it; the ⋯ menu is a second, separately-labelled control.
struct ConnectedChannelRow: View {
    let channel: SourceChannel
    /// Receives an action id from `channel.actions`, or `"manage"` when the row
    /// itself is activated.
    let onAction: (String) -> Void

    @State private var isHovered = false

    var body: some View {
        HStack(spacing: CicadaTheme.spacingMD) {
            Button { onAction("manage") } label: {
                HStack(spacing: CicadaTheme.spacingMD) {
                    Image(systemName: Self.icon(for: channel.id))
                        .font(.system(size: 13, weight: .medium))
                        .foregroundStyle(Self.tint(for: channel.id))
                        .frame(width: 28, height: 28)
                        .background(Circle().fill(Self.tint(for: channel.id).opacity(0.12)))
                        .overlay(Circle().stroke(CicadaTheme.border, lineWidth: 1))

                    VStack(alignment: .leading, spacing: 2) {
                        Text(channel.label)
                            .font(.system(size: 13, weight: .medium))
                            .foregroundStyle(CicadaTheme.textPrimary)
                            .lineLimit(1)
                        if let detail = channel.detail {
                            Text(detail)
                                .font(CicadaTheme.captionFont)
                                .foregroundStyle(CicadaTheme.textSecondary)
                                .lineLimit(1)
                        }
                    }
                    Spacer()
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel(channel.detail.map { "\(channel.label). \($0)" } ?? channel.label)

            if !channel.actions.isEmpty {
                Menu {
                    ForEach(channel.actions, id: \.self) { action in
                        Button(Self.actionTitle(action, channel: channel)) { onAction(action) }
                    }
                } label: {
                    Image(systemName: "ellipsis")
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .frame(width: 24, height: 24)
                }
                .menuStyle(.borderlessButton)
                .menuIndicator(.hidden)
                .frame(width: 24)
                .accessibilityLabel("Actions for \(channel.label)")
            }
        }
        .padding(.horizontal, CicadaTheme.spacingMD)
        .padding(.vertical, CicadaTheme.spacingSM)
        .background(
            RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                .fill(isHovered ? CicadaTheme.surfaceHover : .clear)
        )
        .onHover { isHovered = $0 }
        .animation(.easeInOut(duration: 0.12), value: isHovered)
    }

    static func actionTitle(_ action: String, channel: SourceChannel) -> String {
        switch action {
        case "poll": "Poll now"
        case "sync": "Sync now"
        case "manage": "Manage…"
        case "import": "Import another file…"
        case "remove": "Remove"
        default: action.capitalized
        }
    }

    /// Icons/tints mirror `OriginPill` so a channel and its origin pill read as
    /// the same thing on the same page.
    static func icon(for id: String) -> String {
        switch id {
        case "rss": "dot.radiowaves.up.forward"
        case "calendar": "calendar"
        case "bookmarks": "globe"
        case "notes": "note.text"
        case "telegram": "paperplane.fill"
        case "chat-export:claude", "chat-export:chatgpt": "bubble.left.and.bubble.right"
        case "files": "link"
        default: "tray"
        }
    }

    static func tint(for id: String) -> Color {
        switch id {
        case "rss": Color(hex: 0xEE802F)
        case "calendar": Color(hex: 0xFF3B30)
        case "bookmarks": Color(hex: 0x4285F4)
        case "notes": Color(hex: 0xFFCC00)
        case "telegram": Color(hex: 0x26A5E4)
        case "chat-export:claude", "chat-export:chatgpt": CicadaTheme.accent
        case "files": Color(hex: 0x8896FF)
        default: CicadaTheme.textSecondary
        }
    }
}
```

- [ ] **Step 2: Rewrite `SourcesView.swift`**

Replace the entire file with:

```swift
import SwiftUI

/// The Capture page (G62). Shows **only what is actually connected** — one
/// compact row per channel the backend reports as having state — plus the Sleep
/// queue and the origins strip. Everything explanatory (what a channel is, how
/// to export from a vendor, where a bookmarks file lives) lives behind the `+`
/// button in `AddSourceSheet`, so this page stays a status readout rather than
/// a wall of onboarding copy.
///
/// Every value here is a projection over `Store` snapshots (§5.5): the page
/// renders correct, real data on a cold launch with the backend down.
struct SourcesView: View {
    @Environment(SleepViewModel.self) private var sleepVM
    @Environment(Store.self) private var store

    @State private var showAddSheet = false
    @State private var sheetTile: AddSourceTile?
    @State private var actionResult: String?
    @State private var actionError: String?
    @State private var busyChannel: String?

    // MARK: - Store projections (§5.5)

    private var channels: [SourceChannel] { store.channels.value ?? [] }
    private var connected: [SourceChannel] { SourceChannel.sortedConnected(channels) }
    private var channelsLoading: Bool { store.channels.isEmpty && store.channels.isRefreshing }
    private var origins: [OriginStat] { store.origins.value ?? [] }
    private var status: StatusSnapshot? { store.status.value }
    private var statusLoading: Bool { store.status.isEmpty && store.status.isRefreshing }

    var body: some View {
        VStack(spacing: 0) {
            PageHeader(
                title: "Capture",
                subtitle: "What Cicada reads from. Add a source with +."
            ) {
                addButton
            }

            ScrollView {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                    connectedCard
                    queueCard
                    originsStrip
                }
                .padding(.horizontal, CicadaTheme.spacingXL)
                .padding(.bottom, CicadaTheme.spacingXXL)
            }
        }
        .background(CicadaTheme.background)
        .onChange(of: sleepVM.isRunning) { _, running in
            if !running { Task { await store.refresh([.status, .channels]) } }
        }
        // ⌘N while the Capture page is on screen opens the picker. Hidden-button
        // pattern, same as ContentView's ⌘K.
        .background {
            Button("") { openSheet(nil) }
                .keyboardShortcut("n", modifiers: .command)
                .buttonStyle(.plain)
                .frame(width: 0, height: 0)
                .opacity(0)
        }
        .sheet(isPresented: $showAddSheet) {
            AddSourceSheet(initialTile: sheetTile) { showAddSheet = false }
        }
    }

    private var addButton: some View {
        Button { openSheet(nil) } label: {
            Image(systemName: "plus")
                .font(.system(size: 13, weight: .semibold))
                .foregroundStyle(.white)
                .frame(width: 28, height: 28)
                .background(Circle().fill(CicadaTheme.accent))
        }
        .buttonStyle(.plain)
        .keyboardShortcut("n", modifiers: .command)
        .help("Add a source (⌘N)")
        .accessibilityLabel("Add a source")
    }

    private func openSheet(_ tile: AddSourceTile?) {
        actionError = nil
        actionResult = nil
        sheetTile = tile
        showAddSheet = true
    }

    // MARK: - Connected

    @ViewBuilder
    private var connectedCard: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            sectionLabel("CONNECTED")

            if channelsLoading && channels.isEmpty {
                HStack(spacing: CicadaTheme.spacingSM) {
                    ProgressView().controlSize(.small)
                    Text("Checking your sources…")
                        .font(CicadaTheme.bodyFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
            } else if connected.isEmpty {
                emptyState
            } else {
                VStack(spacing: 2) {
                    ForEach(connected) { channel in
                        ConnectedChannelRow(channel: channel) { action in
                            handle(action, for: channel)
                        }
                        .opacity(busyChannel == channel.id ? 0.5 : 1)
                    }
                }
                if let actionResult {
                    Text(actionResult)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(Color(hex: 0x22C55E))
                } else if let actionError {
                    Text(actionError)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(Color(hex: 0xEF4444))
                }
            }
        }
        .padding(CicadaTheme.spacingLG)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard()
    }

    private var emptyState: some View {
        VStack(spacing: CicadaTheme.spacingSM) {
            Image(systemName: "tray")
                .font(.system(size: 26))
                .foregroundStyle(CicadaTheme.textTertiary)
            Text("Nothing connected yet")
                .font(CicadaTheme.headingFont)
                .foregroundStyle(CicadaTheme.textPrimary)
            Text("Add a chat export, bookmarks, a feed or a calendar.")
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .multilineTextAlignment(.center)
            addButton.padding(.top, CicadaTheme.spacingXS)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, CicadaTheme.spacingXL)
    }

    private func handle(_ action: String, for channel: SourceChannel) {
        actionResult = nil
        actionError = nil
        switch action {
        case "manage", "import", "remove":
            openSheet(AddSourceTile.forChannel(channel.id))
        case "poll":
            Task { await run(channel) { try await Self.poll(channel) } }
        case "sync":
            Task { await run(channel) { try await Self.sync(channel) } }
        default:
            openSheet(AddSourceTile.forChannel(channel.id))
        }
    }

    private func run(_ channel: SourceChannel, _ work: @escaping () async throws -> String) async {
        busyChannel = channel.id
        do {
            actionResult = try await work()
        } catch {
            actionError = AddSourceSheet.friendlyError(error)
        }
        busyChannel = nil
        await store.refresh([.channels, .status, .sources, .feeds, .calendars])
    }

    private static func poll(_ channel: SourceChannel) async throws -> String {
        if channel.id == "calendar" {
            let r = try await APIClient.shared.pollCalendars()
            return "\(r.new) new event(s)"
        }
        let r = try await APIClient.shared.pollFeeds()
        return "\(r.new) new item(s)"
    }

    private static func sync(_ channel: SourceChannel) async throws -> String {
        if channel.id == "notes" {
            let r = try await APIClient.shared.syncNotes()
            return "\(r.new) new · \(r.updated) updated · \(r.skipped) unchanged"
        }
        let r = try await APIClient.shared.syncBookmarks()
        return "\(r.new) new · \(r.skipped) already saved"
    }

    // MARK: - Queue

    private var queueCard: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            sectionLabel("QUEUE")

            if statusLoading && status == nil {
                HStack(spacing: CicadaTheme.spacingSM) {
                    ProgressView().controlSize(.small)
                    Text("Checking the queue…")
                        .font(CicadaTheme.bodyFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
            } else {
                let count = status?.episodes.unprocessed ?? 0
                HStack(alignment: .center, spacing: CicadaTheme.spacingMD) {
                    Image(systemName: count == 0 ? "checkmark.circle" : "tray.full")
                        .font(.system(size: 18))
                        .foregroundStyle(count == 0 ? Color(hex: 0x22C55E) : CicadaTheme.accent)
                        .frame(width: 44, height: 44)
                        .background(RoundedRectangle(cornerRadius: 10).fill(CicadaTheme.surfaceElevated))

                    VStack(alignment: .leading, spacing: 2) {
                        Text(count == 0
                             ? "All caught up"
                             : "\(count) item\(count == 1 ? "" : "s") queued for the next Sleep cycle")
                            .font(CicadaTheme.headingFont)
                            .foregroundStyle(CicadaTheme.textPrimary)
                        if count > 0 {
                            Text("Consolidate now to fold them into the graph immediately.")
                                .font(CicadaTheme.captionFont)
                                .foregroundStyle(CicadaTheme.textTertiary)
                        } else if let last = formattedLastSleep {
                            Text("Last consolidated \(last)")
                                .font(CicadaTheme.captionFont)
                                .foregroundStyle(CicadaTheme.textTertiary)
                        }
                    }

                    Spacer()

                    consolidateButton(count: count)
                }
            }
        }
        .padding(CicadaTheme.spacingLG)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard()
    }

    private func consolidateButton(count: Int) -> some View {
        Button {
            Task {
                await sleepVM.triggerManually()
                await store.refresh([.status, .channels])
            }
        } label: {
            HStack(spacing: CicadaTheme.spacingXS) {
                if sleepVM.isRunning {
                    ProgressView().controlSize(.small).frame(width: 12, height: 12)
                } else {
                    Image(systemName: "moon.fill").font(.system(size: 12))
                }
                Text(sleepVM.isRunning ? "Sleeping…" : "Consolidate now")
                    .font(.system(size: 12, weight: .semibold))
            }
            .foregroundStyle(count == 0 && !sleepVM.isRunning ? CicadaTheme.textTertiary : .white)
            .padding(.horizontal, CicadaTheme.spacingLG)
            .padding(.vertical, CicadaTheme.spacingSM)
            .background(count == 0 && !sleepVM.isRunning ? CicadaTheme.surfaceElevated : CicadaTheme.accent.opacity(0.9))
            .clipShape(Capsule())
        }
        .buttonStyle(.plain)
        .disabled(sleepVM.isRunning || count == 0)
        .help(count == 0 ? "Nothing queued right now" : "Run the Sleep cycle now")
        .accessibilityLabel("Consolidate now")
    }

    private var formattedLastSleep: String? {
        guard let date = StatusSnapshot.parseDate(status?.lastSleepAt) else { return nil }
        let f = DateFormatter()
        f.dateFormat = "MMM d, h:mm a"
        return f.string(from: date)
    }

    // MARK: - Origins strip

    @ViewBuilder
    private var originsStrip: some View {
        if !origins.isEmpty {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                sectionLabel("WHERE YOUR MEMORY COMES FROM")
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: CicadaTheme.spacingSM) {
                        ForEach(origins) { OriginPill(origin: $0) }
                    }
                    .padding(.vertical, 2)
                }
            }
        }
    }

    // MARK: - Shared

    private func sectionLabel(_ text: String) -> some View {
        Text(text)
            .font(.system(size: 10, weight: .semibold, design: .monospaced))
            .foregroundStyle(CicadaTheme.textTertiary)
            .tracking(1.2)
    }
}
```

- [ ] **Step 3: Check the size budget and build**

Run: `wc -l app/CicadaApp/Sources/CicadaApp/Views/Capture/SourcesView.swift`
Expected: well under 450.
Run: `cd app/CicadaApp && swift build`
Expected: builds clean. If `pollFeeds()` / `pollCalendars()` return types differ from `.new`, fix the two `Self.poll` lines to match the real `PollFeedsResult` / `PollCalendarsResult` fields (`APIClient.swift:1067` and `:1099`).

- [ ] **Step 4: Run the whole app suite**

Run: `cd app/CicadaApp && swift test`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/CicadaApp/Sources/CicadaApp/Views/Capture/ConnectedChannelRow.swift app/CicadaApp/Sources/CicadaApp/Views/Capture/SourcesView.swift
git commit -m "$(cat <<'EOF'
feat(app): Capture page shows only connected channels, + adds a source (G62)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

---

### Task 6: `ConnectionStatus.how` + `.powers` (backend)

**Files:**
- Create: `api/tests/test_connection_how_powers.py`
- Modify: `api/models/schemas.py` (the `ConnectionStatus` class, currently lines 904–921)
- Modify: `api/services/connections/claude_cli.py`, `codex_cli.py`, `byok.py`, `ollama.py`
- Modify: `api/services/connections/registry.py` (`statuses`)

**Interfaces:**
- Consumes: `ConnectionStatus`, `pricing.price_for` / `.plan_label`, `secrets.secrets_path()`, `Settings.ollama_base_url` / `.ollama_model`.
- Produces:
  - `ConnectionStatus.how: Optional[str]` — one sentence saying *why this card says Connected*, authored next to the probe that decided it.
  - `ConnectionStatus.powers: list[str]` — what this connection currently does for Cicada.
  - `registry.ENGINE_POWERS = ["Sleep extraction", "Ask", "clarification wording"]`
  - `registry.STANDBY_POWERS = ["Standby"]`
  - `Registry.assign_powers(statuses: list[ConnectionStatus]) -> list[ConnectionStatus]` (mutates in place, returns the same list).

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_connection_how_powers.py`:

```python
"""Every adapter must explain itself (G63).

"Connected" on the Claude card means `claude auth status --json` reported a
claude.ai login for the Claude Code CLI on this Mac — the page never said so.
`how` is that sentence, authored next to the probe that decided it; `powers`
says what the connection is actually doing right now.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from api.config import Settings
from api.services.connections import byok, claude_cli, codex_cli, ollama, registry
from api.services.connections.base import CliResult


def run(coro):
    return asyncio.run(coro)


def _claude_runner(payload: dict):
    async def fake(argv):
        if argv[:3] == ["claude", "auth", "status"]:
            return CliResult(0, json.dumps(payload), "")
        return CliResult(0, "", "")
    return fake


def test_claude_how_names_the_cli_the_mac_and_the_account(monkeypatch):
    monkeypatch.setattr(claude_cli.shutil, "which", lambda name: "/usr/local/bin/claude")
    adapter = claude_cli.ClaudePlanAdapter(runner=_claude_runner(
        {"loggedIn": True, "authMethod": "claude.ai", "email": "r@example.com",
         "subscriptionType": "max"}))
    status = run(adapter.status())
    assert status.connected
    assert status.how == (
        "Signed in to Claude Code on this Mac as `r@example.com`. Cicada runs its "
        "memory work through the `claude` CLI on your plan — it never sees your token."
    )


def test_claude_how_is_absent_when_not_connected(monkeypatch):
    monkeypatch.setattr(claude_cli.shutil, "which", lambda name: "/usr/local/bin/claude")
    adapter = claude_cli.ClaudePlanAdapter(runner=_claude_runner({"loggedIn": False}))
    status = run(adapter.status())
    assert status.connected is False
    assert status.how is None


def test_codex_how_names_codex_exec(monkeypatch, tmp_path):
    monkeypatch.setattr(codex_cli.shutil, "which", lambda name: "/usr/local/bin/codex")

    async def fake(argv):
        return CliResult(0, "Logged in", "")

    (tmp_path / "auth.json").write_text(json.dumps({"auth_mode": "chatgpt", "tokens": {}}))
    adapter = codex_cli.CodexPlanAdapter(runner=fake, codex_home=tmp_path)
    status = run(adapter.status())
    assert status.connected
    assert status.how == (
        "Signed in to Codex CLI on this Mac. Cicada runs through `codex exec` "
        "on your ChatGPT plan."
    )


def test_byok_how_names_the_secrets_file_and_the_provider(monkeypatch):
    monkeypatch.setattr(byok.secrets, "has_secret", lambda _var: True)
    adapter = byok.ByokAdapter("openai")
    status = run(adapter.status())
    assert status.connected
    assert status.how == (
        f"Key stored in {byok.secrets.secrets_path()} (0600); billed per token by OpenAI."
    )


def test_ollama_how_names_the_local_endpoint():
    settings = Settings()

    async def tags(_url):
        return [settings.ollama_model]

    adapter = ollama.OllamaAdapter(settings, fetch_tags=tags)
    status = run(adapter.status())
    assert status.connected
    assert status.how == f"Local models at `{settings.ollama_base_url}` — free."


def test_every_adapter_defines_how_when_connected(monkeypatch, tmp_path):
    """Regression net: a new adapter that forgets `how` is caught here."""
    monkeypatch.setattr(claude_cli.shutil, "which", lambda name: "/usr/local/bin/claude")
    monkeypatch.setattr(byok.secrets, "has_secret", lambda _var: True)
    settings = Settings()

    async def tags(_url):
        return [settings.ollama_model]

    adapters = [
        claude_cli.ClaudePlanAdapter(runner=_claude_runner(
            {"loggedIn": True, "authMethod": "claude.ai", "email": "r@example.com",
             "subscriptionType": "max"})),
        *[byok.ByokAdapter(p) for p in byok.BYOK_PROVIDERS],
        ollama.OllamaAdapter(settings, fetch_tags=tags),
    ]
    for adapter in adapters:
        status = run(adapter.status())
        assert status.connected, adapter.id
        assert status.how, f"{adapter.id} is connected but has no `how` line"


def test_powers_go_to_the_selected_engine_and_standby_to_the_rest():
    from api.models.schemas import ConnectionKind, ConnectionStatus

    def make(cid, connected, role=None):
        return ConnectionStatus(id=cid, label=cid, kind=ConnectionKind.subscription,
                                available=True, connected=connected, engine_role=role)

    statuses = [
        make("claude-plan", True, "subscription-cli"),
        make("chatgpt-plan", True, "subscription-cli"),
        make("byok-openai", False),
    ]
    registry.Registry.assign_powers(statuses)
    assert statuses[0].powers == registry.ENGINE_POWERS
    assert statuses[1].powers == registry.STANDBY_POWERS
    assert statuses[2].powers == []


def test_powers_are_empty_when_nothing_is_connected():
    from api.models.schemas import ConnectionKind, ConnectionStatus

    statuses = [ConnectionStatus(id="ollama-local", label="Ollama", kind=ConnectionKind.local)]
    registry.Registry.assign_powers(statuses)
    assert statuses[0].powers == []
```

- [ ] **Step 2: Run it and watch it fail**

Run: `api/.venv/bin/python -m pytest api/tests/test_connection_how_powers.py -q`
Expected: FAIL — `ConnectionStatus` has no `how` field (pydantic rejects the assertion / the attribute is missing).

- [ ] **Step 3: Add the schema fields**

In `api/models/schemas.py`, inside `class ConnectionStatus(CamelModel)`, after `detail`:

```python
    detail: Optional[str] = None
    # G63: one sentence explaining *why this card says Connected*, authored
    # next to the probe that decided it so the copy can never drift from the
    # check. None when the connection isn't connected — there is nothing to
    # explain yet, and `detail` already carries the "here's how to connect" hint.
    how: Optional[str] = None
    # What this connection currently does for Cicada. The registry assigns
    # these across the probed set (only one adapter is the engine at a time),
    # so an adapter can't know its own answer.
    powers: list[str] = []
    login: Optional[LoginHint] = None
```

- [ ] **Step 4: Author each adapter's `how`**

`api/services/connections/claude_cli.py` — in the connected `return` at the end of `status()`:

```python
        account = info.get("email")
        who = f"as `{account}`" if account else "on your Claude account"
        return self._base(
            available=True, connected=True, plan=plan, engine_role="subscription-cli",
            plan_label=pricing.plan_label(self.id, plan, self._tier),
            account=account, price_usd_month=usd, price_note=note,
            detail=info.get("orgName"),
            how=(
                f"Signed in to Claude Code on this Mac {who}. Cicada runs its "
                "memory work through the `claude` CLI on your plan — it never "
                "sees your token."
            ),
        )
```

`api/services/connections/codex_cli.py` — in the connected `return` at the end of `status()`:

```python
        return self._base(
            available=True, connected=True, plan=plan, engine_role="subscription-cli",
            plan_label=pricing.plan_label(self.id, plan, self._tier),
            account=email, price_usd_month=usd, price_note=note,
            how=(
                "Signed in to Codex CLI on this Mac. Cicada runs through "
                "`codex exec` on your ChatGPT plan."
            ),
        )
```

`api/services/connections/byok.py` — in `status()`:

```python
    async def status(self) -> ConnectionStatus:
        connected = secrets.has_secret(self.env_var)
        brand = {"openai": "OpenAI", "anthropic": "Anthropic",
                 "openrouter": "OpenRouter", "gemini": "Gemini"}[self.provider]
        return ConnectionStatus(
            id=self.id, label=self.label, kind=self.kind, available=True, connected=connected,
            billing="usage", engine_role="byok" if connected else None,
            plan_label="usage-based" if connected else None,
            how=(f"Key stored in {secrets.secrets_path()} (0600); billed per token by {brand}."
                 if connected else None),
            detail=None if connected else f"Paste a key; it is stored in {secrets.secrets_path()} (0600) and exported as {self.env_var}.",
            login=LoginHint(mode="key"),
        )
```

`api/services/connections/ollama.py` — in the connected branch of `status()`:

```python
        if model in names or any(n.split(":")[0] == model for n in names):
            base.connected, base.engine_role, base.plan_label = True, "local", model
            base.how = f"Local models at `{self._settings.ollama_base_url}` — free."
        else:
            base.detail = f"Model not pulled — run `ollama pull {model}`"
```

- [ ] **Step 5: Assign `powers` in the registry**

In `api/services/connections/registry.py`, add the constants next to `VALID_TIERS`:

```python
VALID_TIERS = ("5x", "20x")
# G63: what the *selected* engine actually does, and what every other connected
# connection is doing instead. Only one adapter is the engine at a time (see
# api/routers/status.py, which picks the first connected `engine_role`), so this
# assignment belongs to the registry — an adapter probing itself cannot know.
ENGINE_POWERS = ["Sleep extraction", "Ask", "clarification wording"]
STANDBY_POWERS = ["Standby"]
```

Add the static method to `Registry` (above `status`):

```python
    @staticmethod
    def assign_powers(statuses: list[ConnectionStatus]) -> list[ConnectionStatus]:
        """Stamp `powers` across a probed set, in place.

        The first connected adapter in adapter order is the engine — the same
        rule `GET /status` uses to report `engine` — so it gets the real list
        and every other connected one reads "Standby". Disconnected adapters
        keep an empty list: they aren't powering anything.
        """
        engine_assigned = False
        for status in statuses:
            if not status.connected:
                status.powers = []
                continue
            if not engine_assigned:
                status.powers = list(ENGINE_POWERS)
                engine_assigned = True
            else:
                status.powers = list(STANDBY_POWERS)
        return statuses
```

and call it at the end of `statuses()`, replacing `return statuses`:

```python
        return self.assign_powers(statuses)
```

- [ ] **Step 6: Run the tests**

Run: `api/.venv/bin/python -m pytest api/tests/test_connection_how_powers.py api/tests/test_connections_api.py api/tests/test_connection_claude.py api/tests/test_connection_codex.py api/tests/test_connection_byok_ollama.py -q`
Expected: PASS.

- [ ] **Step 7: Run the whole backend suite**

Run: `api/.venv/bin/python -m pytest api/tests -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add api/models/schemas.py api/services/connections/claude_cli.py api/services/connections/codex_cli.py api/services/connections/byok.py api/services/connections/ollama.py api/services/connections/registry.py api/tests/test_connection_how_powers.py
git commit -m "$(cat <<'EOF'
feat(connections): ConnectionStatus.how + .powers, authored next to each probe (G63)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

---

### Task 7: "Plans & keys" / "Agents" rename + card copy

**Files:**
- Modify: `app/CicadaApp/Sources/CicadaApp/Models/Connection.swift` (fields, `CodingKeys`, memberwise init, `init(from:)`, `patching`)
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sidebar/SidebarView.swift` (add `AppTab.title`; use it in `SidebarRow` and the accessibility label)
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Connections/ConnectionsView.swift` (header + `ConnectionCard`)
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Connect/ConnectView.swift` (header)
- Modify: `app/CicadaApp/Tests/CicadaAppTests/StoreTests.swift` (`connectionFixture` gains the two arguments)
- Create: `app/CicadaApp/Tests/CicadaAppTests/ConnectionCopyTests.swift`

**Interfaces:**
- Consumes: `ConnectionStatus.how` / `.powers` from Task 6.
- Produces: `ConnectionStatus.how: String?`, `ConnectionStatus.powers: [String]`, `ConnectionStatus.powersLine: String?`, `AppTab.title: String`.

- [ ] **Step 1: Write the failing test**

Create `app/CicadaApp/Tests/CicadaAppTests/ConnectionCopyTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// G63 — the sidebar renames and the card's new explanatory lines.
final class ConnectionCopyTests: XCTestCase {

    /// The raw values are persisted identifiers used as `SyncDomain`-adjacent
    /// keys and cache-facing strings; only the *displayed* title moves.
    func testTabIdentifiersAreUnchanged() {
        XCTAssertEqual(AppTab.connections.rawValue, "Connections")
        XCTAssertEqual(AppTab.connect.rawValue, "Connect")
        XCTAssertEqual(AppTab.sources.rawValue, "Capture")
    }

    func testRenamedTabsShowTheNewTitles() {
        XCTAssertEqual(AppTab.connections.title, "Plans & keys")
        XCTAssertEqual(AppTab.connect.title, "Agents")
        XCTAssertEqual(AppTab.graph.title, "Graph")
        XCTAssertEqual(AppTab.sources.title, "Capture")
    }

    /// ⌘-shortcut slots are derived from `AppTab.allCases` order — the rename
    /// must not move Plans & keys off ⌘7 or Agents off ⌘8.
    func testShortcutSlotsAreUnchanged() {
        XCTAssertEqual(AppTab.allCases.firstIndex(of: .connections), 6)
        XCTAssertEqual(AppTab.allCases.firstIndex(of: .connect), 7)
    }

    func testConnectionDecodesHowAndPowers() throws {
        let json = """
        {"id":"claude-plan","label":"Claude plan","kind":"subscription","available":true,
         "connected":true,"billing":"subscription",
         "how":"Signed in to Claude Code on this Mac as `r@example.com`.",
         "powers":["Sleep extraction","Ask","clarification wording"]}
        """
        let c = try JSONDecoder().decode(ConnectionStatus.self, from: Data(json.utf8))
        XCTAssertEqual(c.how, "Signed in to Claude Code on this Mac as `r@example.com`.")
        XCTAssertEqual(c.powersLine, "Sleep extraction · Ask · clarification wording")
    }

    /// An older backend emits neither field; the card must simply not render
    /// those rows rather than failing to decode.
    func testConnectionDecodesWithoutHowAndPowers() throws {
        let json = #"{"id":"ollama-local","label":"Ollama (local)","billing":"free"}"#
        let c = try JSONDecoder().decode(ConnectionStatus.self, from: Data(json.utf8))
        XCTAssertNil(c.how)
        XCTAssertNil(c.powersLine)
    }

    /// The tier picker is a cost-estimate control only, and only Claude Max
    /// has tiers — a Claude Pro or an Ollama card must not show it.
    func testTierPickerOnlyForClaudeMax() {
        func make(_ id: String, plan: String?) -> ConnectionStatus {
            ConnectionStatus(id: id, label: id, kind: "subscription", available: true,
                             connected: true, plan: plan, planLabel: nil, tier: nil,
                             account: nil, priceUsdMonth: nil, priceNote: nil,
                             billing: "subscription", engineRole: nil, detail: nil,
                             how: nil, powers: [], login: nil)
        }
        XCTAssertTrue(make("claude-plan", "max").showsTierPicker)
        XCTAssertFalse(make("claude-plan", "pro").showsTierPicker)
        XCTAssertFalse(make("chatgpt-plan", "pro").showsTierPicker)
        XCTAssertFalse(make("ollama-local", nil).showsTierPicker)
    }
}
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd app/CicadaApp && swift test --filter ConnectionCopyTests`
Expected: FAIL — `value of type 'AppTab' has no member 'title'`.

- [ ] **Step 3: Extend the `ConnectionStatus` model**

In `app/CicadaApp/Sources/CicadaApp/Models/Connection.swift`:

- add the stored properties after `detail`:
  ```swift
      let detail: String?
      /// G63: why this card says "Connected", authored server-side next to the
      /// probe that decided it. `nil` when not connected.
      let how: String?
      /// What this connection currently does for Cicada ("Sleep extraction",
      /// "Ask", … for the selected engine; "Standby" for the rest).
      let powers: [String]
      let login: LoginHint?
  ```
- add `how, powers` to `CodingKeys`:
  ```swift
      enum CodingKeys: String, CodingKey {
          case id, label, kind, available, connected, plan, planLabel, tier, account
          case priceUsdMonth, priceNote, billing, engineRole, detail, how, powers, login
      }
  ```
- add both to the memberwise init's parameter list (after `detail: String?`, before `login:`) and body:
  ```swift
      init(id: String, label: String, kind: String, available: Bool, connected: Bool,
           plan: String?, planLabel: String?, tier: String?, account: String?,
           priceUsdMonth: Double?, priceNote: String?, billing: String,
           engineRole: String?, detail: String?, how: String? = nil,
           powers: [String] = [], login: LoginHint?) {
          ...
          self.engineRole = engineRole; self.detail = detail
          self.how = how; self.powers = powers; self.login = login
      }
  ```
- carry them through `patching(...)`: add `how: how, powers: powers,` alongside `detail: detail` in the constructed value.
- decode them tolerantly in `init(from:)`:
  ```swift
          detail = try c.decodeIfPresent(String.self, forKey: .detail)
          how = try c.decodeIfPresent(String.self, forKey: .how)
          powers = try c.decodeIfPresent([String].self, forKey: .powers) ?? []
  ```
- add the two derived properties next to `priceLine`:
  ```swift
      /// "Sleep extraction · Ask · clarification wording", or nil when this
      /// connection isn't powering anything.
      var powersLine: String? {
          powers.isEmpty ? nil : powers.joined(separator: " · ")
      }

      /// The Max tier picker is a **cost-estimate** control, and only Claude
      /// Max is tiered — showing it anywhere else implied it changed behaviour.
      var showsTierPicker: Bool {
          connected && isSubscription && id == "claude-plan" && plan == "max"
      }
  ```

- [ ] **Step 4: Add `AppTab.title` and use it**

In `app/CicadaApp/Sources/CicadaApp/Views/Sidebar/SidebarView.swift`, add to `AppTab` after `icon`:

```swift
    /// The label the user sees. Deliberately separate from `rawValue`, which is
    /// this tab's stable identifier (persisted state, cache keys, the ⌘-slot
    /// order in `allCases`) and must not move when the copy changes — G63
    /// renames Connections → "Plans & keys" and Connect → "Agents".
    var title: String {
        switch self {
        case .connections: "Plans & keys"
        case .connect: "Agents"
        default: rawValue
        }
    }
```

In `sidebarButton(for:)` change the accessibility label line:

```swift
        let label = count > 0 ? "\(tab.title), \(count) pending" : tab.title
```

In `SidebarRow.body` change the text:

```swift
            Text(tab.title)
```

- [ ] **Step 5: Update the two page headers and the card**

In `ConnectionsView.swift`:

```swift
            PageHeader(title: "Plans & keys",
                       subtitle: "What Cicada bills against. Subscriptions sign in through their own CLI — Cicada never sees the token.") {
                Button { Task { await viewModel.load(fresh: true) } } label: { Image(systemName: "arrow.clockwise") }
            }
```

In `ConnectView.swift`:

```swift
            PageHeader(
                title: isOnboarding ? "Welcome to Cicada" : "Agents",
                subtitle: "Wire your AI agents into Cicada over MCP so they read and write your memory."
            ) {
```

In `ConnectionCard.body`, replace the `detail` block and the tier `if` with:

```swift
            if let detail = connection.detail, !connection.connected {
                Text(detail).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
            }

            // G63: "why does this say Connected?" — the sentence comes from the
            // backend adapter that ran the probe, so the copy can never drift
            // from the check that produced it.
            if let how = connection.how {
                Text(how)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if let powers = connection.powersLine {
                HStack(spacing: CicadaTheme.spacingXS) {
                    Text("POWERS")
                        .font(.system(size: 9, weight: .semibold, design: .monospaced))
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .tracking(1.1)
                    Text(powers)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                }
            }

            if connection.showsTierPicker {
                Picker("Your Max tier (for cost estimates only)",
                       selection: Binding(get: { connection.tier ?? "" },
                                          set: { onTier($0.isEmpty ? nil : $0) })) {
                    Text("Pick tier…").tag("")
                    Text("5x").tag("5x")
                    Text("20x").tag("20x")
                }
                .pickerStyle(.segmented).frame(maxWidth: 300)
                Text("Your Max tier (for cost estimates only)")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
```

And in `actions`, replace the plain `Button("Connect", ...)` fallback for a not-connected Claude card so the one-liner is visible before the user clicks:

```swift
        } else {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                if let cmd = connection.login?.command, connection.login?.mode == "terminal" {
                    Text("Cicada can't sign you in — Claude Code does. Run this once and this card updates itself:")
                        .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                    CommandBox(command: cmd)
                }
                Button("Connect", action: onConnect).buttonStyle(.borderedProminent)
            }
        }
```

- [ ] **Step 6: Fix the test fixture**

In `app/CicadaApp/Tests/CicadaAppTests/StoreTests.swift`, `connectionFixture(id:)` must pass the two new arguments:

```swift
    private func connectionFixture(id: String) throws -> ConnectionStatus {
        ConnectionStatus(id: id, label: id, kind: "subscription", available: true,
                         connected: true, plan: "max", planLabel: nil, tier: nil,
                         account: nil, priceUsdMonth: nil, priceNote: nil,
                         billing: "subscription", engineRole: nil, detail: nil,
                         how: nil, powers: [], login: nil)
    }
```

Then grep for any other memberwise construction: `grep -rn "ConnectionStatus(id:" app/CicadaApp` and add `how: nil, powers: [],` to each (the mutations in `Sync/Mutations.swift` use `patching`, which needs no change).

- [ ] **Step 7: Run the app suite**

Run: `cd app/CicadaApp && swift test`
Expected: PASS, including the 6 new `ConnectionCopyTests`.

- [ ] **Step 8: Commit**

```bash
git add app/CicadaApp/Sources/CicadaApp/Models/Connection.swift app/CicadaApp/Sources/CicadaApp/Views/Sidebar/SidebarView.swift app/CicadaApp/Sources/CicadaApp/Views/Connections/ConnectionsView.swift app/CicadaApp/Sources/CicadaApp/Views/Connect/ConnectView.swift app/CicadaApp/Tests/CicadaAppTests/ConnectionCopyTests.swift app/CicadaApp/Tests/CicadaAppTests/StoreTests.swift
git commit -m "$(cat <<'EOF'
feat(app): Plans & keys / Agents rename, how + powers on each card (G63)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

---

### Task 8: `logo_service` — domain ladder, keyless fetch, cache + TTL

**Files:**
- Create: `api/services/logo_service.py`
- Create: `api/tests/test_logo_service.py`
- Modify: `api/tests/conftest.py`

**Interfaces:**
- Consumes: `api.services.auth.cicada_home()`, `api.services.entity_body.parse_sections(body) -> dict[str, str]`, `api.services.claims.parse_claims(body) -> list[Claim]` (each `Claim` has `.predicate`, `.object`, `.valid_to`, `.superseded_by`), `api.services.markdown_parser.parse(path)` (returns `.frontmatter`, `.body`).
- Produces:
  - `logo_service.FetchResult` — dataclass `(status: int, body: bytes, content_type: str, etag: str | None)`.
  - `logo_service.Fetcher = Callable[[str], Awaitable[FetchResult]]`
  - `logo_service.fetch_allowed() -> bool`
  - `logo_service.logos_dir(bank: str) -> Path`
  - `logo_service.bank_name(memory_path: Path) -> str`
  - `logo_service.domain_for(frontmatter: dict, body: str) -> str | None`
  - `logo_service.ext_for(content_type: str) -> str | None`
  - `logo_service.min_dimension(data: bytes) -> int | None`
  - `async logo_service.fetch_logo(domain: str, *, fetcher: Fetcher | None = None) -> tuple[bytes, str, str | None] | None` → `(body, ext, etag)`
  - `logo_service.read_meta(bank) -> dict` / `logo_service.write_meta(bank, meta) -> None`
  - `logo_service.is_fresh(entry: dict, *, now: datetime | None = None) -> bool`
  - `logo_service.cached_path(bank: str, entity_id: str) -> Path | None`
  - `logo_service.cached_ids(bank: str) -> set[str]`
  - `async logo_service.ensure_logo(memory_path: Path, entity_id: str, *, fetcher=None) -> Path | None`
  - `async logo_service.warm_logos(memory_path: Path, *, limit: int = 50, fetcher=None) -> int`

- [ ] **Step 1: Make the test suite offline for logos**

Rewrite `api/tests/conftest.py`:

```python
"""Suite-wide fixtures.

The local API now requires a bearer token (api/services/auth.py). The existing
tests hit ``TestClient(main.app)`` without headers, so auth is switched off for
every test by default; ``test_auth.py`` re-enables it explicitly.

Logo fetching (G59) is likewise off for the whole suite: no test may reach the
network. The tests that exercise the fetch ladder inject their own fetcher,
which runs regardless of this flag — the same seam ``feed_registry`` uses.
"""
import pytest


@pytest.fixture(autouse=True)
def _disable_api_auth(monkeypatch):
    monkeypatch.setenv("CICADA_API_AUTH", "off")


@pytest.fixture(autouse=True)
def _disable_logo_fetch(monkeypatch):
    monkeypatch.setenv("CICADA_ALLOW_LOGO_FETCH", "off")
```

- [ ] **Step 2: Write the failing ladder tests**

Create `api/tests/test_logo_service.py`:

```python
"""Entity logo resolution + fetch (G59).

Hermetic: every test builds its own tmp workspace and passes an explicit
fetcher. ``conftest`` sets ``CICADA_ALLOW_LOGO_FETCH=off`` for the whole suite,
so nothing here can reach the network even by accident.
"""

from __future__ import annotations

import asyncio
import json
import struct
from datetime import datetime, timedelta, timezone

import pytest

from api.services import logo_service


def run(coro):
    return asyncio.run(coro)


def png_bytes(width: int, height: int) -> bytes:
    """Minimal valid-enough PNG: signature + IHDR with the given dimensions."""
    ihdr = struct.pack(">II", width, height) + b"\x08\x06\x00\x00\x00"
    return (b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + ihdr
            + b"\x00\x00\x00\x00" + b"\x00\x00\x00\x00IEND\xaeB`\x82")


# --- domain_for ladder ------------------------------------------------------


def test_domain_for_prefers_explicit_logo_frontmatter():
    fm = {"type": "company", "name": "Acme",
          "logo": "https://cdn.acme-corp.example/mark.png",
          "sources": [{"ref": "https://other.example/x", "kind": "url"}]}
    assert logo_service.domain_for(fm, "## Links\n- https://third.example/y\n") == "cdn.acme-corp.example"


def test_domain_for_falls_back_to_the_first_url_kind_source():
    fm = {"type": "tool", "name": "Widget",
          "sources": [{"ref": "check my notes", "kind": "note"},
                      {"ref": "https://widget.example/docs", "kind": "url"}]}
    assert logo_service.domain_for(fm, "") == "widget.example"


def test_domain_for_falls_back_to_the_links_section():
    body = "## Summary\n\nA thing.\n\n## Links\n- [Docs](https://links.example/docs)\n- https://second.example\n"
    assert logo_service.domain_for({"type": "tool", "name": "Thing"}, body) == "links.example"


def test_domain_for_falls_back_to_media_url():
    fm = {"type": "media", "name": "A video", "media": {"url": "https://www.youtube.com/watch?v=abc"}}
    assert logo_service.domain_for(fm, "") == "youtube.com"


def test_domain_for_uses_a_website_claim_before_guessing():
    body = (
        "## Summary\n\nx\n\n```claims\n"
        '- {"id": "c1", "text": "MongoDB is at mongodb.com", "subject": "mongodb",'
        ' "predicate": "website", "object": "https://www.mongodb.com/"}\n'
        "```\n"
    )
    assert logo_service.domain_for({"type": "tool", "name": "Mongo DB"}, body) == "mongodb.com"


def test_domain_for_guesses_dot_com_only_for_a_single_token_name():
    assert logo_service.domain_for({"type": "tool", "name": "MongoDB"}, "") == "mongodb.com"
    assert logo_service.domain_for({"type": "company", "name": "Acme Holdings Ltd"}, "") is None


def test_domain_for_never_guesses_for_a_person():
    assert logo_service.domain_for({"type": "person", "name": "Rodrigo"}, "") is None
    # …but an explicit link on a person page is still honoured.
    fm = {"type": "person", "name": "Rodrigo", "sources": [{"ref": "https://rodrigo.example", "kind": "url"}]}
    assert logo_service.domain_for(fm, "") == "rodrigo.example"


def test_domain_for_returns_none_for_a_bare_concept():
    assert logo_service.domain_for({"type": "concept", "name": "Context Engineering"}, "") is None
```

- [ ] **Step 3: Run and watch it fail**

Run: `api/.venv/bin/python -m pytest api/tests/test_logo_service.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'api.services.logo_service'`.

- [ ] **Step 4: Write the ladder half of `logo_service.py`**

Create `api/services/logo_service.py`:

```python
"""Entity logos (G59) — keyless resolution, fetch, and an on-disk cache.

The ladder, cheapest first, never guessing where a guess would be wrong:

1. explicit ``logo:`` frontmatter (a URL) — the user said so, stop here;
2. the first ``kind: url`` entry in the page's ``sources:`` list (G61);
3. the first URL in the body's ``## Links`` section;
4. ``media.url`` (a saved link's own site);
5. a heuristic, and **only** for ``company``/``tool`` pages: a ``website``
   claim's host if one exists, else ``<slug>.com`` when the name is a single
   token. Never for a ``person`` — "Rodrigo" is not rodrigo.com.

Fetching is keyless (apple-touch-icon → the homepage's ``<link rel=icon>`` →
DuckDuckGo's icon service) behind an injectable ``fetcher`` so tests never
touch the network, and is gated by ``CICADA_ALLOW_LOGO_FETCH`` (on by default,
off for the whole test suite). Results — hits *and* misses — are cached under
``$CICADA_HOME/logos/<bank>/``, **never inside a memory bank**: a logo is a
derived, disposable artifact of the outside world, not part of the user's
versioned memory.

Pillow is deliberately not a dependency. Whatever the site serves is stored
as-is with the right ``Content-Type``; ``min_dimension`` sniffs PNG/GIF/ICO/JPEG
headers directly so a 1×1 tracking pixel is rejected without a decode.
"""

from __future__ import annotations

import json
import os
import re
import struct
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Awaitable, Callable
from urllib.parse import urljoin, urlparse

from loguru import logger

from api.services import entity_body, markdown_parser
from api.services.auth import cicada_home
from api.services.claims import parse_claims

CACHE_DIR_NAME = "logos"
META_FILENAME = "meta.json"
HIT_TTL = timedelta(days=30)
MISS_TTL = timedelta(days=7)
MAX_BYTES = 512 * 1024
TIMEOUT_SECONDS = 4.0
MIN_PIXELS = 16
USER_AGENT = "Mozilla/5.0 (CicadaBot)"
# Only these page types plausibly have a brand mark worth guessing at.
GUESSABLE_TYPES = {"company", "tool"}

_URL_RE = re.compile(r"https?://[^\s<>\")\]]+")
_ICON_LINK_RE = re.compile(
    r"""<link\b[^>]*\brel\s*=\s*["']?[^"'>]*\b(?:apple-touch-icon|icon)\b[^"'>]*["']?[^>]*>""",
    re.IGNORECASE,
)
_HREF_RE = re.compile(r"""\bhref\s*=\s*["']([^"']+)["']""", re.IGNORECASE)

_EXT_BY_TYPE = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
    "image/svg+xml": "svg",
    "image/x-icon": "ico",
    "image/vnd.microsoft.icon": "ico",
    "image/ico": "ico",
}


@dataclass
class FetchResult:
    status: int
    body: bytes
    content_type: str
    etag: str | None = None


Fetcher = Callable[[str], Awaitable[FetchResult]]


def fetch_allowed() -> bool:
    return os.environ.get("CICADA_ALLOW_LOGO_FETCH", "on").strip().lower() not in {"off", "0", "false"}


def logos_dir(bank: str) -> Path:
    """``$CICADA_HOME/logos/<bank>/`` — machine-global, never inside a bank."""
    path = cicada_home() / CACHE_DIR_NAME / (bank or "default")
    path.mkdir(parents=True, exist_ok=True)
    return path


def bank_name(memory_path: Path) -> str:
    return Path(memory_path).name or "default"


# --- domain resolution ------------------------------------------------------


def _host(raw: str | None) -> str | None:
    """Host of a URL, lowercased, ``www.`` stripped. None when unusable."""
    if not raw:
        return None
    candidate = raw.strip()
    if not candidate:
        return None
    if "://" not in candidate:
        candidate = "https://" + candidate
    try:
        host = (urlparse(candidate).hostname or "").lower()
    except ValueError:
        return None
    if host.startswith("www."):
        host = host[4:]
    return host or None


def _first_source_url(frontmatter: dict) -> str | None:
    for entry in frontmatter.get("sources") or []:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("kind") or "").strip().lower() != "url":
            continue
        ref = entry.get("ref")
        if isinstance(ref, str) and ref.strip():
            return ref
    return None


def _first_links_url(body: str) -> str | None:
    links = entity_body.parse_sections(body or "").get("Links", "")
    match = _URL_RE.search(links)
    return match.group(0).rstrip(").,") if match else None


def _website_claim_host(body: str) -> str | None:
    try:
        claims = parse_claims(body or "")
    except Exception:
        return None
    for claim in claims:
        if claim.valid_to is not None or claim.superseded_by:
            continue
        if (claim.predicate or "").strip().lower() != "website":
            continue
        host = _host(claim.object)
        if host:
            return host
    return None


def _slug_guess(name: str) -> str | None:
    """``MongoDB`` -> ``mongodb.com``. Only for a single-token name: a
    multi-word name maps to a domain far too unreliably to be worth a fetch."""
    cleaned = (name or "").strip()
    if not cleaned or any(c.isspace() for c in cleaned):
        return None
    slug = re.sub(r"[^a-z0-9-]", "", cleaned.lower())
    return f"{slug}.com" if len(slug) >= 2 else None


def domain_for(frontmatter: dict, body: str) -> str | None:
    """Resolve an entity page to the domain whose icon should represent it."""
    fm = frontmatter or {}

    explicit = _host(fm.get("logo") if isinstance(fm.get("logo"), str) else None)
    if explicit:
        return explicit

    from_source = _host(_first_source_url(fm))
    if from_source:
        return from_source

    from_links = _host(_first_links_url(body))
    if from_links:
        return from_links

    media = fm.get("media")
    if isinstance(media, dict):
        from_media = _host(media.get("url") if isinstance(media.get("url"), str) else None)
        if from_media:
            return from_media

    entity_type = str(fm.get("type") or "").strip().lower()
    if entity_type not in GUESSABLE_TYPES:
        return None

    claimed = _website_claim_host(body)
    if claimed:
        return claimed

    return _slug_guess(str(fm.get("name") or ""))
```

- [ ] **Step 5: Run the ladder tests**

Run: `api/.venv/bin/python -m pytest api/tests/test_logo_service.py -q`
Expected: PASS (8 tests).

- [ ] **Step 6: Write the failing fetch + cache tests**

Append to `api/tests/test_logo_service.py`:

```python
# --- fetch ladder -----------------------------------------------------------


def make_fetcher(responses: dict, calls: list | None = None):
    """Injected fetcher: a URL -> FetchResult map. Anything unmapped 404s."""
    async def fetcher(url: str) -> logo_service.FetchResult:
        if calls is not None:
            calls.append(url)
        hit = responses.get(url)
        if hit is None:
            return logo_service.FetchResult(404, b"", "text/html")
        return hit
    return fetcher


def test_fetch_logo_takes_the_apple_touch_icon_first():
    calls: list[str] = []
    fetcher = make_fetcher({
        "https://acme.example/apple-touch-icon.png":
            logo_service.FetchResult(200, png_bytes(180, 180), "image/png", '"abc"'),
    }, calls)
    body, ext, etag = run(logo_service.fetch_logo("acme.example", fetcher=fetcher))
    assert ext == "png" and etag == '"abc"' and body.startswith(b"\x89PNG")
    assert calls == ["https://acme.example/apple-touch-icon.png"]


def test_fetch_logo_parses_the_homepage_link_rel_icon():
    html = b'<html><head><link rel="apple-touch-icon" href="/static/icon.png"></head></html>'
    fetcher = make_fetcher({
        "https://acme.example/": logo_service.FetchResult(200, html, "text/html"),
        "https://acme.example/static/icon.png":
            logo_service.FetchResult(200, png_bytes(64, 64), "image/png"),
    })
    body, ext, _ = run(logo_service.fetch_logo("acme.example", fetcher=fetcher))
    assert ext == "png" and len(body) > 0


def test_fetch_logo_falls_back_to_duckduckgo():
    fetcher = make_fetcher({
        "https://icons.duckduckgo.com/ip3/acme.example.ico":
            logo_service.FetchResult(200, b"\x00\x00\x01\x00\x01\x00\x20\x20", "image/x-icon"),
    })
    body, ext, _ = run(logo_service.fetch_logo("acme.example", fetcher=fetcher))
    assert ext == "ico"


def test_fetch_logo_returns_none_when_every_rung_misses():
    assert run(logo_service.fetch_logo("acme.example", fetcher=make_fetcher({}))) is None


def test_fetch_logo_rejects_a_tracking_pixel():
    fetcher = make_fetcher({
        "https://acme.example/apple-touch-icon.png":
            logo_service.FetchResult(200, png_bytes(1, 1), "image/png"),
    })
    assert run(logo_service.fetch_logo("acme.example", fetcher=fetcher)) is None


def test_fetch_logo_rejects_an_oversized_body():
    fetcher = make_fetcher({
        "https://acme.example/apple-touch-icon.png":
            logo_service.FetchResult(200, b"x" * (logo_service.MAX_BYTES + 1), "image/png"),
    })
    assert run(logo_service.fetch_logo("acme.example", fetcher=fetcher)) is None


def test_min_dimension_reads_png_gif_and_ico_and_shrugs_at_svg():
    assert logo_service.min_dimension(png_bytes(180, 64)) == 64
    assert logo_service.min_dimension(b"GIF89a" + struct.pack("<HH", 48, 32)) == 32
    assert logo_service.min_dimension(b"\x00\x00\x01\x00\x01\x00\x20\x20") == 32
    assert logo_service.min_dimension(b"<svg xmlns='http://www.w3.org/2000/svg'/>") is None


# --- cache + TTL ------------------------------------------------------------


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    memory = tmp_path / "banks" / "claude-chats"
    (memory / "entities").mkdir(parents=True)
    return memory


def write_entity(memory, entity_id, frontmatter_lines, body=""):
    path = memory / "entities" / f"{entity_id}.md"
    path.write_text("---\n" + "\n".join(frontmatter_lines) + "\n---\n" + body, encoding="utf-8")
    return path


def test_ensure_logo_writes_the_file_and_a_hit_meta_entry(workspace):
    write_entity(workspace, "mongodb",
                 ["name: MongoDB", "type: tool", "logo: https://mongodb.com/x.png"])
    fetcher = make_fetcher({
        "https://mongodb.com/apple-touch-icon.png":
            logo_service.FetchResult(200, png_bytes(180, 180), "image/png", '"v1"'),
    })
    path = run(logo_service.ensure_logo(workspace, "mongodb", fetcher=fetcher))
    assert path is not None and path.exists() and path.suffix == ".png"
    assert path.parent == logo_service.logos_dir("claude-chats")

    meta = logo_service.read_meta("claude-chats")["mongodb"]
    assert meta["domain"] == "mongodb.com"
    assert meta["miss"] is False
    assert meta["etag"] == '"v1"'


def test_ensure_logo_second_call_is_served_from_cache(workspace):
    write_entity(workspace, "mongodb",
                 ["name: MongoDB", "type: tool", "logo: https://mongodb.com/x.png"])
    calls: list[str] = []
    fetcher = make_fetcher({
        "https://mongodb.com/apple-touch-icon.png":
            logo_service.FetchResult(200, png_bytes(180, 180), "image/png"),
    }, calls)
    run(logo_service.ensure_logo(workspace, "mongodb", fetcher=fetcher))
    before = len(calls)
    run(logo_service.ensure_logo(workspace, "mongodb", fetcher=fetcher))
    assert len(calls) == before, "a fresh cache entry must not re-fetch"


def test_ensure_logo_caches_a_miss_and_does_not_retry_within_the_ttl(workspace):
    write_entity(workspace, "widget", ["name: Widget", "type: tool"])
    calls: list[str] = []
    fetcher = make_fetcher({}, calls)
    assert run(logo_service.ensure_logo(workspace, "widget", fetcher=fetcher)) is None
    first = len(calls)
    assert first > 0
    assert run(logo_service.ensure_logo(workspace, "widget", fetcher=fetcher)) is None
    assert len(calls) == first, "a cached miss must not re-fetch"
    assert logo_service.read_meta("claude-chats")["widget"]["miss"] is True


def test_an_expired_entry_is_refetched(workspace):
    write_entity(workspace, "widget", ["name: Widget", "type: tool"])
    calls: list[str] = []
    fetcher = make_fetcher({}, calls)
    run(logo_service.ensure_logo(workspace, "widget", fetcher=fetcher))
    first = len(calls)

    meta = logo_service.read_meta("claude-chats")
    stale = datetime.now(timezone.utc) - logo_service.MISS_TTL - timedelta(days=1)
    meta["widget"]["fetched_at"] = stale.isoformat()
    logo_service.write_meta("claude-chats", meta)

    run(logo_service.ensure_logo(workspace, "widget", fetcher=fetcher))
    assert len(calls) > first, "an expired miss must be retried"


def test_is_fresh_uses_different_ttls_for_hits_and_misses():
    now = datetime.now(timezone.utc)
    eight_days_ago = (now - timedelta(days=8)).isoformat()
    assert logo_service.is_fresh({"fetched_at": eight_days_ago, "miss": False}, now=now) is True
    assert logo_service.is_fresh({"fetched_at": eight_days_ago, "miss": True}, now=now) is False
    assert logo_service.is_fresh({}, now=now) is False


def test_ensure_logo_returns_none_without_a_domain_and_never_fetches(workspace):
    write_entity(workspace, "rodrigo", ["name: Rodrigo", "type: person"])
    calls: list[str] = []
    assert run(logo_service.ensure_logo(workspace, "rodrigo", fetcher=make_fetcher({}, calls))) is None
    assert calls == [], "a person page must not trigger any network call"


def test_cached_ids_reports_only_hits(workspace):
    write_entity(workspace, "mongodb",
                 ["name: MongoDB", "type: tool", "logo: https://mongodb.com/x.png"])
    write_entity(workspace, "widget", ["name: Widget", "type: tool"])
    fetcher = make_fetcher({
        "https://mongodb.com/apple-touch-icon.png":
            logo_service.FetchResult(200, png_bytes(180, 180), "image/png"),
    })
    run(logo_service.ensure_logo(workspace, "mongodb", fetcher=fetcher))
    run(logo_service.ensure_logo(workspace, "widget", fetcher=fetcher))
    assert logo_service.cached_ids("claude-chats") == {"mongodb"}


def test_fetch_is_refused_when_the_gate_is_off_and_no_fetcher_is_injected(workspace, monkeypatch):
    monkeypatch.setenv("CICADA_ALLOW_LOGO_FETCH", "off")
    write_entity(workspace, "mongodb",
                 ["name: MongoDB", "type: tool", "logo: https://mongodb.com/x.png"])
    assert run(logo_service.ensure_logo(workspace, "mongodb")) is None
    assert logo_service.read_meta("claude-chats") == {}, "a gated-off run must not cache a miss"


def test_warm_logos_visits_the_highest_degree_company_and_tool_pages(workspace):
    for i, (eid, etype) in enumerate([("mongodb", "tool"), ("acme", "company"),
                                      ("rodrigo", "person"), ("idea", "concept")]):
        write_entity(workspace, eid, [f"name: {eid}", f"type: {etype}",
                                      f"logo: https://{eid}.example/x.png"])
    fetcher = make_fetcher({
        f"https://{eid}.example/apple-touch-icon.png":
            logo_service.FetchResult(200, png_bytes(64, 64), "image/png")
        for eid in ("mongodb", "acme", "rodrigo", "idea")
    })
    warmed = run(logo_service.warm_logos(workspace, limit=50, fetcher=fetcher))
    assert warmed == 2
    assert logo_service.cached_ids("claude-chats") == {"mongodb", "acme"}
```

- [ ] **Step 7: Run and watch it fail**

Run: `api/.venv/bin/python -m pytest api/tests/test_logo_service.py -q`
Expected: FAIL — `module 'api.services.logo_service' has no attribute 'fetch_logo'`.

- [ ] **Step 8: Append the fetch + cache half of `logo_service.py`**

```python
# --- image sniffing ---------------------------------------------------------


def min_dimension(data: bytes) -> int | None:
    """Smaller of width/height, read straight from the header.

    Returns None for a format we don't sniff (SVG, WEBP) — "unknown" means
    "accept", because refusing a perfectly good vector mark would be worse
    than letting a rare oddity through.
    """
    if len(data) < 8:
        return None
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        width, height = struct.unpack(">II", data[16:24])
        return min(width, height)
    if data[:6] in (b"GIF87a", b"GIF89a") and len(data) >= 10:
        width, height = struct.unpack("<HH", data[6:10])
        return min(width, height)
    if data[:4] == b"\x00\x00\x01\x00" and len(data) >= 8:
        # ICO directory entry: a 0 byte means 256.
        width = data[6] or 256
        height = data[7] or 256
        return min(width, height)
    if data[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                height, width = struct.unpack(">HH", data[i + 5:i + 9])
                return min(width, height)
            segment = struct.unpack(">H", data[i + 2:i + 4])[0]
            i += 2 + segment
        return None
    return None


def ext_for(content_type: str) -> str | None:
    return _EXT_BY_TYPE.get((content_type or "").split(";", 1)[0].strip().lower())


# --- fetching ---------------------------------------------------------------


async def _http_get(url: str) -> FetchResult:
    """Default fetcher: bounded, keyless, follows redirects."""
    import httpx

    async with httpx.AsyncClient(follow_redirects=True, timeout=TIMEOUT_SECONDS) as client:
        resp = await client.get(url, headers={"User-Agent": USER_AGENT})
        body = resp.content[: MAX_BYTES + 1]
        return FetchResult(
            status=resp.status_code,
            body=body,
            content_type=resp.headers.get("content-type", ""),
            etag=resp.headers.get("etag"),
        )


def _accept(result: FetchResult) -> tuple[bytes, str, str | None] | None:
    if result.status != 200 or not result.body:
        return None
    if len(result.body) > MAX_BYTES:
        return None
    ext = ext_for(result.content_type)
    if ext is None:
        return None
    smallest = min_dimension(result.body)
    if smallest is not None and smallest < MIN_PIXELS:
        return None
    return result.body, ext, result.etag


def _icon_href(html: bytes, base_url: str) -> str | None:
    text = html.decode("utf-8", "replace")
    for tag in _ICON_LINK_RE.findall(text):
        href = _HREF_RE.search(tag)
        if href:
            return urljoin(base_url, href.group(1).strip())
    return None


async def fetch_logo(domain: str, *, fetcher: Fetcher | None = None) -> tuple[bytes, str, str | None] | None:
    """Try the three rungs in order. Returns ``(body, ext, etag)`` or None.

    An injected ``fetcher`` always runs (the caller supplied the mechanism, so
    there is nothing left to gate); the default HTTP one is gated by
    ``CICADA_ALLOW_LOGO_FETCH``.
    """
    if fetcher is None:
        if not fetch_allowed():
            return None
        fetcher = _http_get

    homepage = f"https://{domain}/"
    candidates = [f"https://{domain}/apple-touch-icon.png"]

    for url in candidates:
        try:
            accepted = _accept(await fetcher(url))
        except Exception as exc:  # a dead host must never raise into the caller
            logger.debug(f"logo fetch failed for {url}: {type(exc).__name__}: {exc}")
            accepted = None
        if accepted:
            return accepted

    try:
        page = await fetcher(homepage)
        if page.status == 200 and page.body:
            href = _icon_href(page.body, homepage)
            if href:
                accepted = _accept(await fetcher(href))
                if accepted:
                    return accepted
    except Exception as exc:
        logger.debug(f"logo homepage parse failed for {domain}: {type(exc).__name__}: {exc}")

    try:
        accepted = _accept(await fetcher(f"https://icons.duckduckgo.com/ip3/{domain}.ico"))
    except Exception as exc:
        logger.debug(f"DDG icon fetch failed for {domain}: {type(exc).__name__}: {exc}")
        accepted = None
    return accepted


# --- cache ------------------------------------------------------------------


def _meta_path(bank: str) -> Path:
    return logos_dir(bank) / META_FILENAME


def read_meta(bank: str) -> dict:
    try:
        data = json.loads(_meta_path(bank).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_meta(bank: str, meta: dict) -> None:
    try:
        _meta_path(bank).write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError as exc:
        logger.warning(f"Could not write logo meta for {bank}: {type(exc).__name__}: {exc}")


def is_fresh(entry: dict, *, now: datetime | None = None) -> bool:
    """A hit is good for 30 days, a miss for 7 — a brand mark changes rarely,
    but a site that had no icon last week might have one now."""
    raw = (entry or {}).get("fetched_at")
    if not raw:
        return False
    try:
        fetched = datetime.fromisoformat(str(raw))
    except ValueError:
        return False
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=timezone.utc)
    ttl = MISS_TTL if (entry or {}).get("miss") else HIT_TTL
    return (now or datetime.now(timezone.utc)) - fetched < ttl


def cached_path(bank: str, entity_id: str) -> Path | None:
    """The cached logo file for this entity, if there is a fresh hit on disk."""
    entry = read_meta(bank).get(entity_id)
    if not entry or entry.get("miss") or not is_fresh(entry):
        return None
    ext = entry.get("ext")
    if not ext:
        return None
    path = logos_dir(bank) / f"{entity_id}.{ext}"
    return path if path.exists() else None


def cached_ids(bank: str) -> set[str]:
    """Every entity id with a fresh cached logo. Read-only, no network — this
    is what ``GET /graph`` uses to fill ``has_logo``."""
    meta = read_meta(bank)
    directory = logos_dir(bank)
    return {
        eid for eid, entry in meta.items()
        if isinstance(entry, dict) and not entry.get("miss") and is_fresh(entry)
        and entry.get("ext") and (directory / f"{eid}.{entry['ext']}").exists()
    }


async def ensure_logo(memory_path: Path, entity_id: str, *, fetcher: Fetcher | None = None) -> Path | None:
    """Resolve → cache-check → fetch → store. Returns the file, or None for a
    page with no resolvable domain, a fetch miss, or a gated-off fetch."""
    memory_path = Path(memory_path)
    bank = bank_name(memory_path)

    entry = read_meta(bank).get(entity_id)
    if entry and is_fresh(entry):
        return cached_path(bank, entity_id)

    entity_file = memory_path / "entities" / f"{entity_id}.md"
    if not entity_file.exists():
        return None
    try:
        parsed = markdown_parser.parse(entity_file)
    except Exception:
        return None

    domain = domain_for(parsed.frontmatter or {}, parsed.body or "")
    if not domain:
        return None

    if fetcher is None and not fetch_allowed():
        # Not a miss: we never asked. Caching one would suppress the real fetch
        # for a week once the gate is turned back on.
        return None

    result = await fetch_logo(domain, fetcher=fetcher)
    now = datetime.now(timezone.utc).isoformat()
    meta = read_meta(bank)

    if result is None:
        meta[entity_id] = {"fetched_at": now, "domain": domain, "miss": True, "etag": None, "ext": None}
        write_meta(bank, meta)
        return None

    body, ext, etag = result
    path = logos_dir(bank) / f"{entity_id}.{ext}"
    try:
        path.write_bytes(body)
    except OSError as exc:
        logger.warning(f"Could not cache logo for {entity_id}: {type(exc).__name__}: {exc}")
        return None
    meta[entity_id] = {"fetched_at": now, "domain": domain, "miss": False, "etag": etag, "ext": ext}
    write_meta(bank, meta)
    return path


async def warm_logos(memory_path: Path, *, limit: int = 50, fetcher: Fetcher | None = None) -> int:
    """Sleep tail step: fetch missing logos for the busiest company/tool pages
    so the common ones are ready before the user ever opens them.

    Bounded by ``limit`` and never raises — a cycle must not fail because a
    CDN was down.
    """
    from api.services import bank_index

    memory_path = Path(memory_path)
    if fetcher is None and not fetch_allowed():
        return 0

    candidates: list[tuple[int, str]] = []
    for f in bank_index.files(memory_path, "entities"):
        fm = f.frontmatter or {}
        if str(fm.get("type") or "").lower() not in GUESSABLE_TYPES:
            continue
        related = fm.get("related") or []
        candidates.append((len(related) if isinstance(related, list) else 0, f.stem))
    # Highest degree first; the id breaks ties so a warm run is deterministic.
    candidates.sort(key=lambda pair: (-pair[0], pair[1]))

    warmed = 0
    for _, entity_id in candidates[:limit]:
        try:
            if await ensure_logo(memory_path, entity_id, fetcher=fetcher) is not None:
                warmed += 1
        except Exception as exc:
            logger.debug(f"warm_logos: {entity_id} failed: {type(exc).__name__}: {exc}")
    return warmed
```

- [ ] **Step 9: Run the logo tests**

Run: `api/.venv/bin/python -m pytest api/tests/test_logo_service.py -q`
Expected: PASS (all 24).

- [ ] **Step 10: Run the whole backend suite**

Run: `api/.venv/bin/python -m pytest api/tests -q`
Expected: PASS.

- [ ] **Step 11: Commit**

```bash
git add api/services/logo_service.py api/tests/test_logo_service.py api/tests/conftest.py
git commit -m "$(cat <<'EOF'
feat(logos): keyless entity-logo resolution, fetch and cache under ~/.cicada (G59)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

---

### Task 9: `GET /entities/{id}/logo`, `has_logo` on graph nodes, Sleep warm-up

**Files:**
- Create: `api/tests/test_entity_logo_endpoint.py`
- Modify: `api/routers/entities.py`
- Modify: `api/models/schemas.py` (`GraphNode`, currently lines 381–412)
- Modify: `api/services/graph_builder.py` (`_build_full` node construction; the post-pass at lines ~251–260)
- Modify: `api/services/sleep_cycle.py` (tail step, right before `await _finalize(...)`)

**Interfaces:**
- Consumes: `logo_service.ensure_logo`, `.cached_path`, `.cached_ids`, `.bank_name` (Task 8); `sync_service.conditional`.
- Produces:
  - `GET /entities/{id}/logo` → `FileResponse` with `ETag` + `Cache-Control: max-age=86400`; `304` on a matching `If-None-Match`; `404` when the entity is missing, has no resolvable domain, or the fetch missed.
  - `GraphNode.has_logo: bool` (camelCase `hasLogo` on the wire), folded into `content_hash`.
  - `logo_service.warm_logos` called once per Sleep cycle with `limit=50`.

- [ ] **Step 1: Write the failing endpoint + graph tests**

Create `api/tests/test_entity_logo_endpoint.py`:

```python
"""GET /entities/{id}/logo + has_logo on graph nodes (G59).

The graph path must never touch the network: `has_logo` is read from the cache
index only. The endpoint is the only place a fetch can start, and it is bounded
by an in-process semaphore so opening a busy graph can't fan out.
"""

from __future__ import annotations

import asyncio
import struct

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import bank_index, logo_service


def png_bytes(width: int, height: int) -> bytes:
    ihdr = struct.pack(">II", width, height) + b"\x08\x06\x00\x00\x00"
    return (b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + ihdr
            + b"\x00\x00\x00\x00" + b"\x00\x00\x00\x00IEND\xaeB`\x82")


@pytest.fixture
def client(tmp_path, monkeypatch):
    memory = tmp_path / "banks" / "work"
    (memory / "entities").mkdir(parents=True)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    yield TestClient(main.app), memory
    config.get_settings.cache_clear()


def write_entity(memory, entity_id, lines, body=""):
    (memory / "entities" / f"{entity_id}.md").write_text(
        "---\n" + "\n".join(lines) + "\n---\n" + body, encoding="utf-8")


def seed_cached_logo(memory, entity_id, domain="acme.example"):
    """Put a real cached hit on disk without any fetch."""
    async def fetcher(url):
        if url.endswith("/apple-touch-icon.png"):
            return logo_service.FetchResult(200, png_bytes(180, 180), "image/png", '"v1"')
        return logo_service.FetchResult(404, b"", "text/html")

    return asyncio.run(logo_service.ensure_logo(memory, entity_id, fetcher=fetcher))


def test_logo_404_for_an_unknown_entity(client):
    c, _ = client
    assert c.get("/entities/nope/logo").status_code == 404


def test_logo_404_for_a_person_page(client):
    c, memory = client
    write_entity(memory, "rodrigo", ["name: Rodrigo", "type: person"])
    bank_index.invalidate()
    assert c.get("/entities/rodrigo/logo").status_code == 404


def test_logo_200_then_304_from_the_cache(client):
    c, memory = client
    write_entity(memory, "acme", ["name: Acme", "type: company", "logo: https://acme.example/x.png"])
    assert seed_cached_logo(memory, "acme") is not None
    bank_index.invalidate()

    first = c.get("/entities/acme/logo")
    assert first.status_code == 200, first.text
    assert first.headers["content-type"].startswith("image/png")
    assert first.headers["cache-control"] == "max-age=86400"
    etag = first.headers["etag"]
    assert first.content.startswith(b"\x89PNG")

    again = c.get("/entities/acme/logo", headers={"If-None-Match": etag})
    assert again.status_code == 304


def test_graph_nodes_report_has_logo_from_the_cache_only(client):
    c, memory = client
    write_entity(memory, "acme", ["name: Acme", "type: company", "logo: https://acme.example/x.png"])
    write_entity(memory, "widget", ["name: Widget", "type: tool"])
    bank_index.invalidate()

    before = {n["id"]: n for n in c.get("/graph").json()["nodes"]}
    assert before["acme"]["hasLogo"] is False
    assert before["widget"]["hasLogo"] is False

    assert seed_cached_logo(memory, "acme") is not None
    bank_index.invalidate()
    from api.services import graph_builder
    graph_builder._CACHE["key"] = None  # the graph cache keys on mtimes, not the logo cache

    after = {n["id"]: n for n in c.get("/graph").json()["nodes"]}
    assert after["acme"]["hasLogo"] is True
    assert after["widget"]["hasLogo"] is False
    assert after["acme"]["contentHash"] != before["acme"]["contentHash"], (
        "has_logo must move the node's content_hash or the app's delta never repaints it")


def test_graph_never_fetches(client, monkeypatch):
    c, memory = client
    write_entity(memory, "acme", ["name: Acme", "type: company", "logo: https://acme.example/x.png"])
    bank_index.invalidate()

    async def explode(_url):
        raise AssertionError("GET /graph must never fetch a logo")

    monkeypatch.setattr(logo_service, "_http_get", explode)
    assert c.get("/graph").status_code == 200
```

- [ ] **Step 2: Run and watch it fail**

Run: `api/.venv/bin/python -m pytest api/tests/test_entity_logo_endpoint.py -q`
Expected: FAIL — `/entities/acme/logo` 404s for a reason other than the ladder (route missing), and `hasLogo` is absent from the graph payload.

- [ ] **Step 3: Add `has_logo` to the schema**

In `api/models/schemas.py`, inside `class GraphNode(CamelModel)`, after `content_hash`:

```python
    summary: Optional[str] = None
    content_hash: str = ""
    # G59: does this entity have a *cached* logo right now? Filled from the
    # on-disk logo index only — `GET /graph` never fetches. Folded into
    # `content_hash` below so the app's delta repaints the node when a logo
    # lands (e.g. after a Sleep warm-up).
    has_logo: bool = False
```

- [ ] **Step 4: Fill it in `graph_builder`**

In `api/services/graph_builder.py`, add the import at the top:

```python
from api.services import logo_service
```

Inside `_build_full`, before the entity loop, read the index once:

```python
    # G59: which entities already have a cached logo. One read of a small JSON
    # index — never a fetch, never a per-node stat storm.
    try:
        logo_ids = logo_service.cached_ids(logo_service.bank_name(memory_path))
    except Exception:
        logo_ids = set()
```

and pass it into the `GraphNode(...)` construction, after `content_hash=content_hash(fm, body),`:

```python
                content_hash=content_hash(fm, body),
                has_logo=eid in logo_ids,
```

Then extend the render-flag re-hash pass (`api/services/graph_builder.py:251-260`) so a logo change moves the hash:

```python
            node.content_hash = synthetic_hash(
                node.content_hash, node.degree, node.has_pending, node.hub_id,
                node.has_logo,
            )
```

- [ ] **Step 5: Add the endpoint**

In `api/routers/entities.py`, add to the imports:

```python
import asyncio
import hashlib

from fastapi.responses import FileResponse, Response

from api.services import git_service, logo_service, markdown_parser, repo_context
```

and add near the top of the module, after `router = APIRouter()`:

```python
# G59: bound concurrent first-fetches so opening a graph full of new companies
# can't fan out into dozens of simultaneous outbound requests.
_LOGO_FETCH_SEMAPHORE = asyncio.Semaphore(4)

_LOGO_MEDIA_TYPES = {
    "png": "image/png", "jpg": "image/jpeg", "gif": "image/gif",
    "webp": "image/webp", "svg": "image/svg+xml", "ico": "image/x-icon",
}
```

and the route (place it directly after `get_entity`, so it reads next to the page it decorates):

```python
@router.get("/entities/{entity_id}/logo")
async def get_entity_logo(
    entity_id: str,
    request: Request,
    settings: Settings = Depends(get_settings),
):
    """The entity's logo as an image (G59).

    404 means "no logo" — no resolvable domain, or the fetch ladder came up
    empty — and the app draws its monogram fallback. The first request for an
    uncached entity performs the fetch (bounded by a semaphore of 4); every
    later one is served straight off ``~/.cicada/logos/<bank>/``. ``GET /graph``
    never comes through here: it reads the cache index only.
    """
    memory_path = settings.memory_path
    if not (memory_path / "entities" / f"{entity_id}.md").exists():
        raise HTTPException(404, f"Entity {entity_id} not found")

    bank = logo_service.bank_name(memory_path)
    path = logo_service.cached_path(bank, entity_id)
    if path is None:
        async with _LOGO_FETCH_SEMAPHORE:
            path = await logo_service.ensure_logo(memory_path, entity_id)
    if path is None or not path.exists():
        raise HTTPException(404, "no logo for this entity")

    stat = path.stat()
    etag = '"' + hashlib.sha1(f"{path.name}:{stat.st_mtime_ns}:{stat.st_size}".encode()).hexdigest()[:16] + '"'
    headers = {"ETag": etag, "Cache-Control": "max-age=86400"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)

    media_type = _LOGO_MEDIA_TYPES.get(path.suffix.lstrip("."), "application/octet-stream")
    return FileResponse(path, media_type=media_type, headers=headers)
```

Add `Request` to the existing `from fastapi import ...` line if it isn't already imported.

- [ ] **Step 6: Add the Sleep tail step**

In `api/services/sleep_cycle.py`, immediately before `# Commit` / `await _finalize(memory_path, cycle_id, changes, settings)`:

```python
        # G59: warm the logo cache for the busiest company/tool pages so the
        # common marks are on disk before the user opens the graph. Bounded,
        # keyless, and never fatal — a CDN outage must not fail a cycle.
        try:
            from api.services.logo_service import warm_logos

            warmed = await warm_logos(memory_path, limit=50)
            if warmed:
                logger.info(f"Warmed {warmed} entity logo(s)")
        except Exception as e:
            logger.warning(f"Logo warm-up failed: {type(e).__name__}: {e}")

        # Commit
        await _finalize(memory_path, cycle_id, changes, settings)
```

- [ ] **Step 7: Run the tests**

Run: `api/.venv/bin/python -m pytest api/tests/test_entity_logo_endpoint.py api/tests/test_graph_builder.py -q`
Expected: PASS. If `test_graph_builder.py::test_graph_nodes_have_summary_and_hash` fails on hash length, note the assertion is `len(node.content_hash) == 12` and `synthetic_hash` still returns 12 hex chars — no change needed.

- [ ] **Step 8: Run the whole backend suite**

Run: `api/.venv/bin/python -m pytest api/tests -q`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add api/routers/entities.py api/models/schemas.py api/services/graph_builder.py api/services/sleep_cycle.py api/tests/test_entity_logo_endpoint.py
git commit -m "$(cat <<'EOF'
feat(logos): GET /entities/{id}/logo, hasLogo on graph nodes, Sleep warm-up (G59)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

---

### Task 10: `LogoImage(entity:)` + the four surfaces

**Files:**
- Create: `app/CicadaApp/Sources/CicadaApp/Services/LogoStore.swift`
- Create: `app/CicadaApp/Tests/CicadaAppTests/LogoImageTests.swift`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Common/LogoImage.swift`
- Modify: `app/CicadaApp/Sources/CicadaApp/Services/APIClient.swift` (add `fetchEntityLogo`)
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Graph/EntityDetailCard.swift` (line 119)
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Inbox/InboxCardView.swift` (line 58)
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Topics/TopicsView.swift` (`TopicRowListItem`, line 653)
- Modify: `app/CicadaApp/Sources/CicadaApp/Ask/AskPanel.swift` (`citationChip`)

**Interfaces:**
- Consumes: `GET /entities/{id}/logo` (Task 9); `CicadaTheme.entityColor(for:)`; `Store.bank`; `InboxItem.entityId` (verify the exact property name with `grep -n "entityId\|displayName" app/CicadaApp/Sources/CicadaApp/Models/InboxItem.swift` — if the item exposes no entity id, render the monogram from `item.displayName` with `entityId: ""`, which short-circuits the remote fetch).
- Produces:
  - `LogoImage.Source` — `.bundled(String)` / `.entity(id: String, name: String, type: EntityType)`
  - `LogoImage(name:size:)` (unchanged call sites) and `LogoImage(entityId:name:type:size:)`
  - `LogoImage.monogram(for name: String) -> String`
  - `actor LogoStore` with `static let shared` and `func image(entityId: String, bank: String) async -> NSImage?`, plus `func dataURL(entityId: String, bank: String) async -> String?` (used by Task 11).
  - `APIClient.fetchEntityLogo(id: String) async throws -> Data?` (nil on 404).

- [ ] **Step 1: Write the failing test**

Create `app/CicadaApp/Tests/CicadaAppTests/LogoImageTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// The monogram fallback (G59). Pure string logic, so it is the one part of
/// the logo path worth unit-testing — the rest is disk and network.
final class LogoImageTests: XCTestCase {

    func testTwoWordNameGivesTwoInitials() {
        XCTAssertEqual(LogoImage.monogram(for: "Rodrigo Sagastegui"), "RS")
        XCTAssertEqual(LogoImage.monogram(for: "IE University"), "IU")
    }

    func testSingleWordNameGivesOneInitial() {
        XCTAssertEqual(LogoImage.monogram(for: "MongoDB"), "M")
        XCTAssertEqual(LogoImage.monogram(for: "cicada"), "C")
    }

    func testThreeOrMoreWordsUseTheFirstTwo() {
        XCTAssertEqual(LogoImage.monogram(for: "Acme Holdings International"), "AH")
    }

    func testLeadingNonLettersAreSkipped() {
        XCTAssertEqual(LogoImage.monogram(for: "  ~/Documents roros_lab"), "DR")
        XCTAssertEqual(LogoImage.monogram(for: "3M Company"), "3C")
    }

    func testEmptyOrSymbolOnlyNameFallsBackToAQuestionMark() {
        XCTAssertEqual(LogoImage.monogram(for: ""), "?")
        XCTAssertEqual(LogoImage.monogram(for: "   "), "?")
        XCTAssertEqual(LogoImage.monogram(for: "—"), "?")
    }

    func testMonogramIsAlwaysUppercaseAndAtMostTwoCharacters() {
        for name in ["a b c d", "über alles", "x", "Zeta"] {
            let m = LogoImage.monogram(for: name)
            XCTAssertLessThanOrEqual(m.count, 2, name)
            XCTAssertEqual(m, m.uppercased(), name)
        }
    }
}
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd app/CicadaApp && swift test --filter LogoImageTests`
Expected: FAIL — `type 'LogoImage' has no member 'monogram'`.

- [ ] **Step 3: Add the API client method**

In `app/CicadaApp/Sources/CicadaApp/Services/APIClient.swift`, next to `fetchEntity(id:)`:

```swift
    /// `GET /entities/{id}/logo`. Returns nil on 404 — "this entity has no
    /// logo" is an ordinary answer, not an error, and the caller draws a
    /// monogram instead.
    func fetchEntityLogo(id: String) async throws -> Data? {
        var request = makeRequest("/entities/\(encodedID(id))/logo", method: "GET", json: false)
        request.timeoutInterval = Self.refreshTimeout
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw APIError.serverUnreachable }
        if http.statusCode == 404 { return nil }
        guard (200...299).contains(http.statusCode) else {
            if http.statusCode == 401 { Self.invalidateToken() }
            throw APIError.httpError(http.statusCode, String(data: data, encoding: .utf8) ?? "Unknown error")
        }
        return data
    }
```

- [ ] **Step 4: Write `LogoStore`**

Create `app/CicadaApp/Sources/CicadaApp/Services/LogoStore.swift`:

```swift
import AppKit
import Foundation

/// Per-bank disk + memory cache for entity logos (G59).
///
/// Order: memory → `~/Library/Application Support/Cicada/logos/<bank>/<id>` →
/// `GET /entities/{id}/logo`. A 404 (no logo for this entity) is remembered in
/// memory as a negative result so a graph full of concept nodes doesn't
/// re-ask on every scroll; negatives are **not** written to disk, so a restart
/// picks up whatever the Sleep cycle warmed in the meantime.
actor LogoStore {
    static let shared = LogoStore()

    private var memory: [String: NSImage] = [:]
    private var misses: Set<String> = []
    private let root: URL

    init(root: URL? = nil) {
        self.root = root ?? FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("Cicada/logos", isDirectory: true)
    }

    private func key(_ entityId: String, _ bank: String) -> String { "\(bank)/\(entityId)" }

    private func fileURL(_ entityId: String, _ bank: String) -> URL {
        let safeBank = bank.replacingOccurrences(of: "/", with: "_")
        let safeId = entityId.replacingOccurrences(of: "/", with: "_")
        return root.appendingPathComponent(safeBank, isDirectory: true)
            .appendingPathComponent("\(safeId).img")
    }

    func image(entityId: String, bank: String) async -> NSImage? {
        guard !entityId.isEmpty else { return nil }
        let k = key(entityId, bank)
        if let hit = memory[k] { return hit }
        if misses.contains(k) { return nil }

        let url = fileURL(entityId, bank)
        if let data = try? Data(contentsOf: url), let image = NSImage(data: data) {
            memory[k] = image
            return image
        }

        let data: Data?
        do {
            data = try await APIClient.shared.fetchEntityLogo(id: entityId)
        } catch {
            return nil  // transient: don't poison the cache with a network blip
        }
        guard let data, let image = NSImage(data: data) else {
            misses.insert(k)
            return nil
        }
        try? FileManager.default.createDirectory(
            at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try? data.write(to: url, options: .atomic)
        memory[k] = image
        return image
    }

    /// Base64 `data:` URL for the graph canvas (Task 11), which cannot fetch
    /// through the bearer-authenticated API from inside the WKWebView.
    func dataURL(entityId: String, bank: String) async -> String? {
        guard let image = await image(entityId: entityId, bank: bank),
              let tiff = image.tiffRepresentation,
              let rep = NSBitmapImageRep(data: tiff),
              let png = rep.representation(using: .png, properties: [:])
        else { return nil }
        return "data:image/png;base64," + png.base64EncodedString()
    }

    /// Drop everything for one bank (bank switch, or a manual refresh).
    func clear(bank: String) {
        let prefix = "\(bank)/"
        memory = memory.filter { !$0.key.hasPrefix(prefix) }
        misses = misses.filter { !$0.hasPrefix(prefix) }
    }
}
```

- [ ] **Step 5: Extend `LogoImage`**

Replace `app/CicadaApp/Sources/CicadaApp/Views/Common/LogoImage.swift` with:

```swift
import SwiftUI
import AppKit

/// Two jobs, one view.
///
/// **Bundled mode** (`LogoImage(name:)`) is the original: a small square PNG
/// from `Resources/logos/<name>.png` keyed by a provider id (`claude-code`,
/// `codex`, `chrome`, …), loaded off the main thread and cached for the life
/// of the process.
///
/// **Entity mode** (`LogoImage(entityId:name:type:)`, G59) renders an entity's
/// own logo: `GET /entities/{id}/logo` via `LogoStore` (memory + disk cached),
/// falling back to a monogram on the entity-type color. Always a **circle**
/// with a 1-pt hairline ring, so an entity reads the same in the detail card,
/// the inbox, the cluster list and an Ask citation.
struct LogoImage: View {
    enum Source: Equatable {
        case bundled(String)
        case entity(id: String, name: String, type: EntityType)
    }

    let source: Source
    var size: CGFloat = 28

    @Environment(Store.self) private var store
    @State private var image: NSImage?

    init(name: String, size: CGFloat = 28) {
        self.source = .bundled(name)
        self.size = size
    }

    init(entityId: String, name: String, type: EntityType = .concept, size: CGFloat = 28) {
        self.source = .entity(id: entityId, name: name, type: type)
        self.size = size
    }

    var body: some View {
        Group {
            switch source {
            case .bundled:
                bundledBody
            case let .entity(_, name, type):
                entityBody(name: name, type: type)
            }
        }
        .frame(width: size, height: size)
        .task(id: taskKey) { await load() }
    }

    private var taskKey: String {
        switch source {
        case let .bundled(name): "bundled:\(name)"
        case let .entity(id, _, _): "entity:\(id):\(store.bank)"
        }
    }

    @ViewBuilder
    private var bundledBody: some View {
        if let image {
            Image(nsImage: image).resizable().interpolation(.high).scaledToFit()
        } else {
            Image(systemName: "app")
                .resizable().scaledToFit()
                .foregroundStyle(CicadaTheme.textTertiary)
                .padding(size * 0.2)
        }
    }

    @ViewBuilder
    private func entityBody(name: String, type: EntityType) -> some View {
        ZStack {
            if let image {
                Image(nsImage: image)
                    .resizable()
                    .interpolation(.high)
                    .scaledToFill()
            } else {
                CicadaTheme.entityColor(for: type)
                Text(Self.monogram(for: name))
                    .font(.system(size: size * 0.42, weight: .semibold, design: .rounded))
                    .foregroundStyle(.white)
                    .minimumScaleFactor(0.6)
                    .lineLimit(1)
            }
        }
        .frame(width: size, height: size)
        .clipShape(Circle())
        .overlay(Circle().stroke(CicadaTheme.border, lineWidth: 1))
        .accessibilityLabel(name)
    }

    private func load() async {
        switch source {
        case let .bundled(name):
            image = await Self.bundledImage(for: name)
        case let .entity(id, _, _):
            image = await LogoStore.shared.image(entityId: id, bank: store.bank)
        }
    }

    /// Initials for the monogram fallback: the first letter or digit of the
    /// first two words, uppercased. `?` when there is nothing usable — never
    /// an empty circle.
    static func monogram(for name: String) -> String {
        let words = name
            .split(whereSeparator: { $0.isWhitespace || $0 == "/" || $0 == "_" || $0 == "-" })
            .compactMap { word -> Character? in
                word.first(where: { $0.isLetter || $0.isNumber })
            }
        let initials = words.prefix(2)
        return initials.isEmpty ? "?" : String(initials).uppercased()
    }

    /// Cheap synchronous existence check for a *bundled* logo (a bundle
    /// resource lookup, not a file read) so callers can pick a fallback layout
    /// without waiting on the async PNG decode.
    static func exists(name: String) -> Bool {
        Bundle.module.url(forResource: name, withExtension: "png", subdirectory: "Resources/logos") != nil
    }

    // MARK: - Bundled cache

    @MainActor
    private static var cache: [String: NSImage] = [:]

    private static func bundledImage(for name: String) async -> NSImage? {
        if let cached = await MainActor.run(body: { cache[name] }) { return cached }
        let loaded = await Task.detached(priority: .utility) {
            guard let url = Bundle.module.url(
                forResource: name, withExtension: "png", subdirectory: "Resources/logos"
            ) else { return nil as NSImage? }
            return NSImage(contentsOf: url)
        }.value
        if let loaded { await MainActor.run { cache[name] = loaded } }
        return loaded
    }
}
```

> `@Environment(Store.self)` is now required by every `LogoImage`, including the
> bundled ones on the Plans & keys page. `Store` is injected at the app root, so
> this is already satisfied for every in-app call site. If `swift build` reports
> a missing environment value in a preview or a detached sheet, inject it there
> with `.environment(store)` rather than reintroducing a store-free init.

- [ ] **Step 6: Use it on the four surfaces**

`EntityDetailCard.swift` — replace the bare `Text(entity.name)` at line 119 with:

```swift
            HStack(spacing: CicadaTheme.spacingMD) {
                LogoImage(entityId: entity.id, name: entity.name, type: entity.type, size: 40)
                Text(entity.name)
                    .font(CicadaTheme.titleFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
            }
```

`InboxCardView.swift` — in `header`, put the entity's mark before the kind icon:

```swift
        HStack(spacing: CicadaTheme.spacingMD) {
            LogoImage(entityId: item.entityId ?? "", name: item.displayName, size: 28)

            Image(systemName: item.kind.icon)
                .font(.system(size: 16))
                .foregroundStyle(item.kind.color)
                .frame(width: 24)
```

(If `InboxItem` has no `entityId`, pass `entityId: ""` — `LogoStore.image` short-circuits on an empty id and the monogram from `displayName` is drawn.)

`TopicsView.swift` — in `TopicRowListItem`, replace the 10-pt type dot with the entity mark:

```swift
            HStack(spacing: CicadaTheme.spacingMD) {
                LogoImage(entityId: entity.id, name: entity.name, type: entity.type, size: 20)

                Text(entity.name)
```

`AskPanel.swift` — in `citationChip`, put a 20-pt mark inside the capsule:

```swift
    private func citationChip(_ citation: AskCitation) -> some View {
        Button {
            onSelectEntity(citation.entityId)
        } label: {
            HStack(spacing: 6) {
                LogoImage(entityId: citation.entityId, name: citation.entityName, size: 20)
                Text("[[\(citation.entityName)]]")
                    .font(.system(size: 12, weight: .medium, design: .monospaced))
                    .foregroundStyle(CicadaTheme.accent)
            }
            .padding(.leading, 4)
            .padding(.trailing, CicadaTheme.spacingSM)
            .padding(.vertical, 4)
            .background(Capsule().fill(CicadaTheme.accent.opacity(0.12)))
        }
        .buttonStyle(.plain)
        .help(citation.snippet)
        .accessibilityLabel("Open \(citation.entityName)")
    }
```

- [ ] **Step 7: Run the app suite**

Run: `cd app/CicadaApp && swift test`
Expected: PASS, including the 6 new `LogoImageTests`.

- [ ] **Step 8: Commit**

```bash
git add app/CicadaApp/Sources/CicadaApp/Services/LogoStore.swift app/CicadaApp/Sources/CicadaApp/Views/Common/LogoImage.swift app/CicadaApp/Sources/CicadaApp/Services/APIClient.swift app/CicadaApp/Sources/CicadaApp/Views/Graph/EntityDetailCard.swift app/CicadaApp/Sources/CicadaApp/Views/Inbox/InboxCardView.swift app/CicadaApp/Sources/CicadaApp/Views/Topics/TopicsView.swift app/CicadaApp/Sources/CicadaApp/Ask/AskPanel.swift app/CicadaApp/Tests/CicadaAppTests/LogoImageTests.swift
git commit -m "$(cat <<'EOF'
feat(app): entity logos in the detail card, inbox, clusters and Ask chips (G59)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

---

### Task 11: Logos on the graph canvas, behind a "Show logos" toggle

**Files:**
- Create: `app/CicadaApp/Tests/graph/graph-logo.test.js` (a plain `node` script, outside any SwiftPM target — same as `graph-delta.test.js`)
- Modify: `app/CicadaApp/Sources/CicadaApp/Resources/graph/graph.js` (globals ~line 149; node draw ~line 1029; `applyFilters` ~line 1445)
- Modify: `app/CicadaApp/Sources/CicadaApp/Models/GraphFilter.swift` (`showLogos` + `jsPayload`)
- Modify: `app/CicadaApp/Sources/CicadaApp/Models/Entity.swift` (`GraphNode.hasLogo`)
- Modify: `app/CicadaApp/Sources/CicadaApp/ViewModels/GraphViewModel.swift` (`nodeDict`, logo push)
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Graph/GraphView.swift` (evaluate `setNodeLogos`)
- Modify: `app/CicadaApp/Sources/CicadaApp/ContentView.swift` (`FilterPopoverContent` toggle, line 268)

**Interfaces:**
- Consumes: `hasLogo` on `/graph` nodes (Task 9); `LogoStore.shared.dataURL(entityId:bank:)` (Task 10).
- Produces:
  - `graph.js`: `filters.showLogos` (boolean, default `false`), global `setNodeLogos(payload)` where `payload` is `{ "<node id>": "data:image/png;base64,…" }`.
  - `GraphFilter.showLogos: Bool` carried in `jsPayload` as `"showLogos"`.
  - `GraphNode.hasLogo: Bool` (decode-tolerant, default `false`), emitted by `GraphViewModel.nodeDict` only when true.
  - `GraphViewModel.pendingLogoPushJSON: String?` + `func clearPendingLogoPush()`.

- [ ] **Step 1: Write the failing JS test**

Create `app/CicadaApp/Tests/graph/graph-logo.test.js`:

```js
#!/usr/bin/env node
//
// Regression net for graph.js's logo layer (G59). Run it with:
//
//     node app/CicadaApp/Tests/graph/graph-logo.test.js
//
// Same vm-sandbox trick as graph-delta.test.js: load the real graph.js with a
// stubbed canvas/document and a chainable no-op d3, then poke the globals. The
// point is the bookkeeping (does the toggle land, does an image register, does
// hasLogo survive an update) — not the pixels, which canvas owns.

const fs = require("fs");
const vm = require("vm");
const path = require("path");

const dir = path.join(__dirname, "..", "..", "Sources", "CicadaApp", "Resources", "graph");

const noop = () => {};
let canvasStub;
const ctxStub = new Proxy({}, {
    get: (t, k) => {
        if (k === "canvas") return canvasStub;
        if (k === "measureText") return () => ({ width: 10 });
        if (k === "createLinearGradient") return () => ({ addColorStop: noop });
        return typeof k === "string" ? noop : undefined;
    },
    set: () => true,
});
canvasStub = {
    clientWidth: 1200, clientHeight: 800, width: 1200, height: 800,
    style: {}, classList: { add: noop, remove: noop },
    getContext: () => ctxStub, addEventListener: noop,
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 1200, height: 800 }),
};

// Minimal Image stub: records the src it was given and fires onload at once,
// so `setNodeLogos` reaches its "ready" state deterministically.
function ImageStub() {
    this.src = "";
    this.onload = null;
    this.onerror = null;
    Object.defineProperty(this, "srcSetter", { value: true });
}

function freshSandbox() {
    const sandbox = {
        console,
        document: { getElementById: () => canvasStub, addEventListener: noop, documentElement: {}, body: {} },
        window: { devicePixelRatio: 2, innerWidth: 1200, innerHeight: 800, addEventListener: noop },
        requestAnimationFrame: noop, cancelAnimationFrame: noop,
        setTimeout, clearTimeout, Math, Date, JSON, Map, Set, Number, String, Boolean, Array, Object,
        Image: ImageStub,
    };
    sandbox.globalThis = sandbox;
    sandbox.self = sandbox;
    vm.createContext(sandbox);
    const chainable = () => new Proxy(function () {}, {
        get: () => chainable(),
        apply: () => chainable(),
    });
    sandbox.d3 = new Proxy({}, { get: () => chainable() });
    vm.runInContext(fs.readFileSync(path.join(dir, "graph.js"), "utf8"), sandbox, { filename: "graph.js" });
    vm.runInContext("canvas = document.getElementById('graph'); ctx = canvas.getContext('2d');", sandbox);
    return sandbox;
}

const run = (sandbox, src) => vm.runInContext(src, sandbox);
const call = (sandbox, fn, arg) => run(sandbox, `${fn}(${JSON.stringify(arg)})`);

let failures = 0;
const check = (label, cond) => {
    console.log((cond ? "PASS " : "FAIL ") + label);
    if (!cond) failures += 1;
};

const node = (id, type, hash, extra = {}) => ({
    id, name: id.toUpperCase(), type, status: "active", confidence: 0.9, tags: [],
    degree: 0, isHub: false, hasPending: false, memberCount: 0, contentHash: hash, ...extra,
});

// ---------------------------------------------------------------- case 1
// showLogos is off until Swift says otherwise, and applyFilters carries it.
{
    const sb = freshSandbox();
    check("showLogos defaults to false", run(sb, "filters.showLogos") === false);
    call(sb, "applyFilters", { showLogos: true });
    check("applyFilters turns showLogos on", run(sb, "filters.showLogos") === true);
    call(sb, "applyFilters", { showLogos: false });
    check("applyFilters turns showLogos back off", run(sb, "filters.showLogos") === false);
}

// ---------------------------------------------------------------- case 2
// A filter payload without the key must not clobber the current setting —
// the same "in f" contract every other axis follows.
{
    const sb = freshSandbox();
    call(sb, "applyFilters", { showLogos: true });
    call(sb, "applyFilters", { minDegree: 2 });
    check("an unrelated filter update leaves showLogos alone",
        run(sb, "filters.showLogos") === true);
}

// ---------------------------------------------------------------- case 3
// setNodeLogos registers one entry per id and is additive across calls.
{
    const sb = freshSandbox();
    call(sb, "setNodeLogos", { a: "data:image/png;base64,AAA", b: "data:image/png;base64,BBB" });
    check("setNodeLogos registers both ids", run(sb, "logoImages.size") === 2);
    check("the src is handed to the Image", run(sb, "logoImages.get('a').img.src") === "data:image/png;base64,AAA");

    call(sb, "setNodeLogos", { c: "data:image/png;base64,CCC" });
    check("a second call adds without dropping the first", run(sb, "logoImages.size") === 3);

    // Re-sending the same id must not rebuild the Image (which would restart
    // the decode and flicker the node on every delta push).
    const before = run(sb, "logoImages.get('a').img");
    call(sb, "setNodeLogos", { a: "data:image/png;base64,AAA" });
    check("re-sending an unchanged id reuses the existing Image",
        run(sb, "logoImages.get('a').img") === before);
}

// ---------------------------------------------------------------- case 4
// hasLogo survives a full update and a delta update, like every other field.
{
    const sb = freshSandbox();
    call(sb, "updateGraph", {
        nodes: [node("a", "company", "h1", { hasLogo: true }), node("b", "tool", "h2")],
        links: [],
    });
    check("hasLogo survives updateGraph",
        run(sb, "nodes.find(n => n.id === 'a').hasLogo") === true &&
        run(sb, "!nodes.find(n => n.id === 'b').hasLogo") === true);

    run(sb, "nodes.forEach((n, i) => { n.x = 100 + i * 37; n.y = 200 - i * 11; });");
    call(sb, "updateGraphDelta", {
        added: [], updated: [node("b", "tool", "h3", { hasLogo: true })], removed: [],
        isFull: false,
    });
    check("a delta can turn hasLogo on for an existing node",
        run(sb, "nodes.find(n => n.id === 'b').hasLogo") === true);
    check("the updated node kept its position",
        run(sb, "nodes.find(n => n.id === 'b').x") === 137);
}

console.log(failures === 0 ? "\nAll graph logo checks passed." : `\n${failures} check(s) FAILED.`);
process.exit(failures === 0 ? 0 : 1);
```

- [ ] **Step 2: Run it and watch it fail**

Run: `node app/CicadaApp/Tests/graph/graph-logo.test.js`
Expected: FAIL — `filters.showLogos` is `undefined` and `setNodeLogos` is not defined.

- [ ] **Step 3: Add the logo layer to `graph.js`**

Extend the `filters` object (`graph.js:149-157`):

```js
let filters = {
    types: null,        // null = all types; otherwise Set<string>
    statuses: null,     // null = all except dropped; otherwise Set<string>
    minConfidence: 0,
    tags: null,         // null/empty = no tag filter; otherwise Set<string>
    minDegree: 1,       // default drops only fully isolated nodes
    contexts: null,     // null = all contexts; otherwise Set<string> — DROPS non-matching edges/facets
    observers: null,    // null = all observers; otherwise Set<string> — DIMS non-matching nodes (kept visible)
    // G59: draw cached brand marks inside the node discs. Off by default —
    // drawImage per node costs real frames on a 1800-node graph, and the
    // colored discs are the primary type signal. Toggled from the Swift
    // filter popover.
    showLogos: false,
};

// G59: id -> { img, ready }. Fed by `setNodeLogos`, which Swift calls with
// base64 data URLs (the webview can't reach the bearer-authenticated API).
// Entries are additive and reused: rebuilding an Image restarts its decode and
// flickers the node on every delta push.
const logoImages = new Map();

function setNodeLogos(payload) {
    const data = typeof payload === "string" ? JSON.parse(payload) : payload;
    let added = 0;
    for (const [id, src] of Object.entries(data || {})) {
        const existing = logoImages.get(id);
        if (existing && existing.img && existing.img.src === src) continue;
        if (typeof Image !== "function") continue;
        const entry = { img: new Image(), ready: false };
        entry.img.onload = () => { entry.ready = true; scheduleRedraw(); };
        entry.img.onerror = () => { logoImages.delete(id); };
        entry.img.src = src;
        logoImages.set(id, entry);
        added += 1;
    }
    if (added) scheduleRedraw();
}
```

In `applyFilters`, alongside the other `in f` reads (after the `observers` line):

```js
    if ("observers" in f) filters.observers = toSet(f.observers);
    // Not set-affecting: no node enters or leaves the visible set, so this
    // must not trigger a rebuild + reheat — just a repaint.
    if ("showLogos" in f) filters.showLogos = Boolean(f.showLogos);
```

In the node-draw loop, immediately after the `ctx.fill()` that paints the disc (`graph.js:1029-1032`) and before the `decaying` stroke:

```js
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
        ctx.fill();

        // G59: the entity's own brand mark, clipped to the disc. Only past the
        // node-label zoom tier — below that the marks smear into indistinct
        // pixels and cost a drawImage per node for nothing.
        if (filters.showLogos && n.hasLogo && transform.k >= ZOOM_NODE_LABELS && alpha > 0.2) {
            const entry = logoImages.get(n.id);
            if (entry && entry.ready) {
                ctx.save();
                ctx.beginPath();
                ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
                ctx.clip();
                ctx.drawImage(entry.img, n.x - r, n.y - r, r * 2, r * 2);
                ctx.restore();
                ctx.globalAlpha = alpha;
            }
        }

        if (n.status === "decaying") {
```

- [ ] **Step 4: Run the JS test**

Run: `node app/CicadaApp/Tests/graph/graph-logo.test.js`
Expected: `All graph logo checks passed.` — and re-run the existing one:
Run: `node app/CicadaApp/Tests/graph/graph-delta.test.js`
Expected: `All graph delta checks passed.`

- [ ] **Step 5: Carry `hasLogo` and `showLogos` from Swift**

`Models/Entity.swift` — in `GraphNode`, add the stored property after `contentHash`:

```swift
    let summary: String?
    let contentHash: String
    /// G59: the backend has a cached logo for this entity. Purely a render
    /// hint — the bytes arrive separately via `setNodeLogos`.
    let hasLogo: Bool
```

add `hasLogo` to `CodingKeys` (`case summary, contentHash, hasLogo`), to the memberwise init
(`summary: String? = nil, contentHash: String = "", hasLogo: Bool = false` and
`self.hasLogo = hasLogo`), and to `init(from:)`:

```swift
        contentHash = try c.decodeIfPresent(String.self, forKey: .contentHash) ?? ""
        hasLogo = try c.decodeIfPresent(Bool.self, forKey: .hasLogo) ?? false
```

`Models/GraphFilter.swift` — add the field and carry it:

```swift
    var observers: Set<String> = []
    /// G59: draw cached entity logos on graph nodes. Off by default — see the
    /// perf note in graph.js.
    var showLogos: Bool = false
```

and in `jsPayload`, after the observers line:

```swift
        payload["observers"] = Array(observers)
        payload["showLogos"] = showLogos
```

`ViewModels/GraphViewModel.swift` — in `nodeDict`, after the `context` line:

```swift
        if let context = node.context { d["context"] = context }
        if node.hasLogo { d["hasLogo"] = true }
        return d
```

and add the bounded logo push next to the existing push plumbing:

```swift
    /// Base64 data URLs for the highest-degree nodes that have a logo, ready
    /// for `graph.js::setNodeLogos`. Consumed by `GraphView.updateNSView`.
    var pendingLogoPushJSON: String?

    func clearPendingLogoPush() { pendingLogoPushJSON = nil }

    /// Fetch (from `LogoStore`'s memory/disk cache, or the API once) the marks
    /// for the busiest logo-bearing nodes and hand them to the canvas.
    ///
    /// Bounded by `limit` on purpose: pushing 1800 base64 PNGs through
    /// `evaluateJavaScript` would be tens of megabytes of string. Only runs
    /// while the toggle is on — with logos off, nothing is fetched at all.
    func pushVisibleLogos(limit: Int = 60) async {
        guard filter.showLogos else { return }
        let bank = store.bank
        let candidates = (store.graph.value?.nodes ?? [])
            .filter(\.hasLogo)
            .sorted { $0.degree > $1.degree }
            .prefix(limit)
        guard !candidates.isEmpty else { return }

        var payload: [String: String] = [:]
        for node in candidates {
            if let url = await LogoStore.shared.dataURL(entityId: node.id, bank: bank) {
                payload[node.id] = url
            }
        }
        guard !payload.isEmpty,
              let data = try? JSONSerialization.data(withJSONObject: payload),
              let json = String(data: data, encoding: .utf8)
        else { return }
        pendingLogoPushJSON = json
    }
```

`Views/Graph/GraphView.swift` — in `updateNSView`, after the filter-update block:

```swift
        // G59: hand the canvas the cached logo bitmaps as data URLs. The
        // webview can't call the bearer-authenticated API itself.
        if viewModel.isGraphReady, let logoJSON = viewModel.pendingLogoPushJSON {
            webView.evaluateJavaScript("setNodeLogos(\(logoJSON))") { _, error in
                if let error { print("Logo push error: \(error)") }
            }
            DispatchQueue.main.async {
                self.viewModel.clearPendingLogoPush()
            }
        }
```

`ContentView.swift` — add the toggle to `FilterPopoverContent` (line 268), after the confidence slider:

```swift
            Divider()
            Toggle("Show logos", isOn: Binding(
                get: { graphVM.filter.showLogos },
                set: { newValue in
                    graphVM.filter.showLogos = newValue
                    if newValue { Task { await graphVM.pushVisibleLogos() } }
                }
            ))
            .toggleStyle(.switch)
            .accessibilityLabel("Show entity logos on graph nodes")
```

(Use whatever the popover already calls its view model — check the property name
with `grep -n "graphVM\|viewModel" app/CicadaApp/Sources/CicadaApp/ContentView.swift | sed -n '1,40p'` and match it.)

- [ ] **Step 6: Build and run every suite**

Run: `cd app/CicadaApp && swift build && swift test`
Expected: PASS. `GraphPushTests` still passes — `nodeDict` only gained a conditional key.
Run: `node app/CicadaApp/Tests/graph/graph-logo.test.js && node app/CicadaApp/Tests/graph/graph-delta.test.js`
Expected: both print their "all checks passed" line.

- [ ] **Step 7: Commit**

```bash
git add app/CicadaApp/Sources/CicadaApp/Resources/graph/graph.js app/CicadaApp/Sources/CicadaApp/Models/GraphFilter.swift app/CicadaApp/Sources/CicadaApp/Models/Entity.swift app/CicadaApp/Sources/CicadaApp/ViewModels/GraphViewModel.swift app/CicadaApp/Sources/CicadaApp/Views/Graph/GraphView.swift app/CicadaApp/Sources/CicadaApp/ContentView.swift app/CicadaApp/Tests/graph/graph-logo.test.js
git commit -m "$(cat <<'EOF'
feat(graph): draw cached entity logos on nodes behind a Show logos toggle (G59)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

---

### Task 12: Docs

**Files:**
- Modify: `CLAUDE.md` (the API section around lines 258–312)
- Modify: `docs/goals/memory-evolution.md` (the G59 / G62 / G63 / G64 rows, lines 581–584)

- [ ] **Step 1: Update the API surface in `CLAUDE.md`**

In the paragraph at line 267, add `/sources/channels` to the ETag list:

```markdown
`/graph`, `/inbox`, `/contributors`, `/sources`, `/sources/channels`, `/origins`, and `/banks` all support ETags: each response carries an `ETag` header, and a request sent with `If-None-Match` gets back a `304 Not Modified` (empty body) whenever nothing in that domain changed, letting the app skip re-parsing and re-rendering large payloads (`/graph` on the live bank is ~1.8 MB).
```

In the endpoint block, add the logo route after the `/entities/{id}/repos` lines:

```
GET  /entities/{id}/logo                  → cached entity logo image (ETag, max-age=86400; 404 = draw a monogram)
```

and the channels route next to the other `/sources` entries:

```
GET  /sources/channels                    → capture channels + whether each is actually connected (G62)
```

Update the `GET /graph` line to mention the flag:

```
GET  /graph                               → nodes + edges JSON for d3 (incl. synthetic repo: nodes, has_logo)
```

Add a paragraph to the **Storage Layer** section, after the sqlite-vec block:

```markdown
### Entity logos (`~/.cicada/logos/<bank>/`)
`api/services/logo_service.py` resolves an entity page to a domain (explicit
`logo:` frontmatter → a `url`-kind `sources:` entry → the first `## Links` URL →
`media.url` → a `website` claim or a single-token-name `.com` guess, and never
for a `person`), fetches an icon keylessly (`apple-touch-icon` → the homepage's
`<link rel=icon>` → DuckDuckGo's icon service, 4 s, ≤ 512 KB, ≥ 16 px), and
caches the result — hits for 30 days, misses for 7 — under
`$CICADA_HOME/logos/<bank>/` with a `meta.json` index. **Never inside a bank:**
a logo is a derived artifact of the outside world, not versioned memory.
`GET /entities/{id}/logo` serves it (first request fetches, bounded by a
semaphore of 4); `GET /graph` only reads the index to set `has_logo` and never
touches the network. `CICADA_ALLOW_LOGO_FETCH=off` disables fetching entirely —
the test suite runs that way and injects fetchers instead.
```

Add `sync_state.json` to the **Sleep Cycle / storage** narrative wherever
`feeds.yaml` and `calendars.yaml` are mentioned, and update the sync-engine
paragraph's domain list to include `channels`:

```markdown
A single `Store` holds one `Snapshot` per domain (graph, inbox, sources, channels, contributors, origins, status, banks, feeds, calendars, connections), …
```

- [ ] **Step 2: Update the backlog rows**

In `docs/goals/memory-evolution.md`, change the trailing status cell of rows G59,
G62, G63 and G64 from `🔲` to `✅`, and append one sentence to each row's
description recording what actually shipped:

- **G59** — `Shipped: api/services/logo_service.py (ladder + keyless fetch + ~/.cicada/logos/<bank>/ cache, 30 d hits / 7 d misses), GET /entities/{id}/logo, has_logo on graph nodes, a warm_logos Sleep tail step, LogoImage's entity mode (circle + monogram fallback) in the detail card / inbox / clusters / Ask chips, and an off-by-default "Show logos" graph toggle.`
- **G62** — `Shipped: GET /sources/channels derived from persisted state only (registries, sync_state.json, origin counts, the Telegram env flag), a channels sync domain, a Capture page that lists only connected channels with per-channel ⋯ actions, and an AddSourceSheet ("+", ⌘N) that owns all the explanatory copy. SourcesView is 1,341 → under 450 lines.`
- **G63** — `Shipped: ConnectionStatus.how (authored next to each adapter's probe) and .powers (assigned by the registry's engine selection); sidebar Connections → "Plans & keys" and Connect → "Agents" with AppTab raw values unchanged; the Max tier picker relabelled "Your Max tier (for cost estimates only)" and shown only for Claude Max.`
- **G64** — `Shipped (buttons + steps): a WalkthroughPanel in the "+" sheet with a Claude/ChatGPT/Takeout/Instagram picker, 3–4 numbered steps, an "Open <vendor> export settings" button, and a reserved 16:9 area that plays Resources/walkthroughs/<vendor>.mp4 when one exists. Recording the clips is a separate manual pass — docs/walkthrough-recording.md.`

- [ ] **Step 3: Sanity-check the doc edits**

Run: `grep -n "sources/channels\|entities/{id}/logo\|CICADA_ALLOW_LOGO_FETCH" CLAUDE.md`
Expected: each appears at least once.
Run: `grep -n "^| G59\|^| G62\|^| G63\|^| G64" docs/goals/memory-evolution.md`
Expected: all four rows end in `✅`.

- [ ] **Step 4: Final full verification**

Run: `api/.venv/bin/python -m pytest api/tests -q`
Run: `cd app/CicadaApp && swift test`
Run: `node app/CicadaApp/Tests/graph/graph-logo.test.js && node app/CicadaApp/Tests/graph/graph-delta.test.js`
Run: `wc -l app/CicadaApp/Sources/CicadaApp/Views/Capture/SourcesView.swift` — must be ≤ 450.
Run: `git status --short` — confirm nothing under `memory/` is staged or modified, and that `.claude/settings.json` is untouched by this branch.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md docs/goals/memory-evolution.md
git commit -m "$(cat <<'EOF'
docs: record the capture/channels, plans-and-keys, logo and walkthrough work (G59, G62, G63, G64)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

---

## Manual verification (after Task 12)

These need a running backend and the app; they are the spec's "Live" checks.

1. Start the backend and open the app on the `claude-chats` bank. The **Capture**
   page lists only channels that actually have state, most recently synced first,
   with the queue below and the origins strip under that.
2. Press **⌘N**. The picker opens. Add an RSS feed and paste a link; both report
   success inline and the Capture list updates without a manual refresh.
3. Open the Chat-export tile. Switch the vendor picker; the steps change and
   "Open Claude export settings" opens `claude.ai/settings/data-privacy-controls`
   in the browser.
4. Sidebar reads **Plans & keys** (⌘7) and **Agents** (⌘8). The Claude card shows
   the "Signed in to Claude Code on this Mac as …" line and a POWERS line.
5. Open the MongoDB entity: a circular logo sits left of the name in the detail
   card, and the same mark appears on its inbox rows and Ask citations. A person
   entity shows initials on the type color instead.
6. Turn on **Show logos** in the graph filter popover and zoom past ~1.2×: the
   marks appear inside the node discs; node positions do not jump.
