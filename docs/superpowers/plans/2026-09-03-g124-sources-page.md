# G124 Sources Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Activity page (cost tiles first, a Usage · Contributors · Conversations segmented control, a horizontal non-clickable origins strip) with a **Sources** page that opens on *where memory comes from*: one clickable card per harness/origin/channel, a per-source page (a harness's conversations with Resume; a browser/social/feed source's channel state, folder counts and items), Contributors with a GitHub-style calendar per model, and an **Advanced** toggle holding counts only (memory writes, sleep runs, streak, most-written / most-read entities). **Prices and token usage leave the app UI entirely.** The `/consumption/*` endpoints and the telemetry ledger are untouched on the backend.

**Architecture:** Two small engine-free backend additions (`GET /sources/overview`, `GET /contributors/calendar`, `GET /contributors/top-entities`, `POST /entities/{id}/read`, a `read` ledger kind, `harness=`/`origin=` filters on `/conversations/recent`, `origin`/`folder` on `/sources` items), then the app: a new `sourcesOverview` Store domain, the tab rename with a `restored(from:)` mapping, the card grid → per-source page navigation, the contributors calendar, the Advanced counts view, and the deletion of every price/token surface. Docs last.

**Tech Stack:** Python 3 / FastAPI / Pydantic (`api/`), YAML frontmatter + git (`memory/`), MCP server (`mcp/server.py`), SwiftUI + XCTest (`app/CicadaApp`).

**Spec:** `docs/goals/memory-evolution.md` row **G124** (incl. its 2026-09-03 ruling) is the spec; this plan is its argument. Rows G9, G48, G51, G62, G106, G113, G120 bound it.

## Global Constraints

- Work ONLY in `/Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g124` (branch `feat/sources-page`, based on `dev` @ `bdcdc54`). Every shell command is `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g124 && <cmd>` with the ABSOLUTE path (`zoxide` hijacks relative `cd`; ignore its stderr banner). No `grep --include=*.ext` (zsh globbing breaks it) — grep a directory instead.
- **NEVER read** `/Users/rorosaga/Documents/roros_lab/cicada/memory` (any bank), `~/.cicada`, `~/Library/Safari`, or `~/.claude/projects` — real personal data. Test fixtures are synthetic (`alpha-project`, `bob-example`, `example.com`, the two UUID constants already used by `test_session_stats.py`).
- Python tests: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g124 && api/.venv/bin/python -m pytest <files> -q -p no:cacheprovider`. Full suite `api/tests` baseline: exactly 8 date-dependent failures in `test_calendar_registry.py` plus `test_agent_provenance.py::test_a_decay_only_change_lands_in_its_own_cicada_authored_commit` (order-dependent, pre-existing). Everything else must be green.
- Swift: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g124/app/CicadaApp && swift build 2>&1 | tail -5` must succeed and `swift test 2>&1 | tail -20` must report 0 failures. SourceKit diagnostics naming OTHER worktrees are noise. **NEVER** run `make dev`, `make install-app`, `swift run`, or launch/kill the Cicada app — the owner's installed app is live; the orchestrator installs at the end.
- Never `git add -A`; stage named files only (`git add -- <path> <path>`; `git mv` for moves). Never commit `memory/`, `logs/`, `.claude/settings.json`, `api/.venv`, `*-report.md`. No push, no new branches/worktrees, no PR, no subagents. Ignore Devin/PR comments.
- **Rails from CLAUDE.md that this track touches:** engine-free read paths (no LLM anywhere in this plan); ids-only telemetry (a `read` event carries an entity id and a surface enum — never a title, body, or query string); transcripts under `~/.claude` are never read (resume = `isfile()` + the existing descriptor endpoint, unchanged); every new payload's ETag covers every file it is computed from (ship-together); secrets stay in `~/.cicada/secrets.env` (nothing here touches them); portability (no owner name, no author-machine path — the harness label map is generic); Swift decode tolerance (every new wire field is optional-with-default so an older backend never blanks a page); `Store`/`Snapshot`/`Mutation` patterns kept.
- Another running track edits `mcp/server.py` (handshake). Task 2's change there is **three call lines plus one local import**; do not restructure that file. Expect a trivial merge.
- Cicada docstrings explain WHY, citing the G-row or review that motivated a rule. Match that density.
- Read code at the cited `file:line` before editing — line numbers are from base commit `bdcdc54` and drift as tasks land.

## Rulings (binding — decided here so no task stalls; each carries its reason)

- **R1 — Source identity is a closed catalog plus two open families.** `api/services/source_overview.py` declares `CATALOG` (one `SourceSpec` per known channel/origin, mapping origin ids → a source id that equals the `GET /sources/channels` id where one exists, so the per-source page joins channel state by equality). Two families are open-ended: `harness:<name>` (every distinct `harness` frontmatter value on MCP episodes, `harness:unknown` for MCP episodes with none) and `origin:<id>` (any origin the catalog does not know). Reason: the catalog gives labels, kinds and marks; the open families guarantee a new harness or importer appears the day it ships instead of vanishing into "other". **Every origin string in `CATALOG` was verified against a real writer** (`bookmark_sync.py:198-202` chrome/safari-bookmark, `safari_tabs.py` safari-tab, `conversations.py:599/622/669` gemini/chatgpt/claude-export, `media_ingestor.py:531/631/689/765/824` the export parsers, `connectors/*` pinterest/reddit-saved/x-bookmarks, `calendar_registry.py:363` calendar, `notes_sync.py:240` apple-notes, `capture.py` telegram). **Disclosed gap (verified, not fixed here):** three writers stamp NO `origin` at all — `POST /sources/save` (`sources.py:80`), MCP `cicada_save_url` (`mcp/server.py:732`) and the RSS poll (`feed_registry.poll_feeds` → `media_ingestor.ingest_feed`, which builds `RawItem(url=…)` bare). So there is no `share-sheet`/`bookmark`/`rss` origin on disk: the `files` row carries an empty `origins` tuple and its evidence is the `files` channel (the whole url index); the app shows it the items whose `origin` is nil. An MCP-saved link still lands on its harness row (it carries `session_id`). The `rss` row's evidence is channel state alone (connected = subscriptions exist, `items` = subscription count); its episodes and items are invisible to the overview until those writers stamp an origin — a one-line follow-up per writer, recorded on the G124 row in Task 5, out of scope here because it touches ingest paths this track otherwise never edits.
- **R2 — A row is shown when it has any evidence: `connected`, `episodes > 0`, `conversations > 0`, or `items > 0`.** A grid of seventeen empty cards is noise; the Feed's `+` catalog is where a person adds a source. The page's empty state points there (`Copy.addASource` already exists).
- **R3 — Entity credit on the overview is `source_episodes` only.** `session_stats._group` additionally credits claims stamped with a `session_id` (PR #20 review fix), which costs a body parse of every entity. The overview counts the same way `/origins` does and says so in its docstring; the per-harness conversation rows (which come from `session_stats`) keep the richer credit. Disclosed asymmetry, not a bug.
- **R4 — Legacy `origin: mcp` episodes without a `session_id` belong to a harness row.** They count toward `harness:<harness>` (or `harness:unknown`) episodes and entities but not toward `conversations` (there is no id to count). Reason: they *are* agent conversations; hiding them under-reports the harness that produced them.
- **R5 — `/conversations/recent` gains `harness=` and `origin=` query filters applied BEFORE the cap.** Filtering a capped 200-row page client-side would silently drop an older conversation of the selected harness. `harness=unknown` matches rows whose harness is empty. Both filters fold into the ETag `extra`.
- **R6 — The per-source item list is a client-side filter over the existing `sources` Store domain**, keyed on the new `origin` field of `MediaFeedItem` (read from the media entity's `origin:` frontmatter in `list_sources`, which already parses that page). Folder/device counts group the same items by the new `folder` field. No new endpoint, no new Store domain for items.
- **R7 — One new Store domain, `sourcesOverview`, riding the `episodes`, `entities` and `sources` version-vector components** — exactly the components its ETag covers (`etag_for(memory_path, "sources", "episodes", "entities", extra=<telegram|connectors>)`, mirroring `/sources/channels`). Ship-together holds: the payload is computed from episodes, entities, `sync_state.json`, the registries and the url index, all inside those three components.
- **R8 — The Advanced toggle reuses the persisted `cicada.usageMode` key.** `UsageMode` (`Minimal`/`Advanced`) already persists there; the segmented "Mode" picker becomes a `Toggle("Advanced")` bound to `viewModel.mode == .advanced`. No new defaults key, no migration.
- **R9 — What "no prices in the app" means concretely:** delete `UsageFormat.usd`, `UsageFormat.costLine`, `UsageFormat.tokens`; delete `UsageViewModel.costLine` and `.subscriptionUsdMonth`; delete `UsageAdvancedView.swift` and `UsageView.swift` (charts, connection cost cards, by-model/stage/bank token tables, lifetime-tokens / favorite-model / peak-day tiles, the connections price line, the cost tile); drop `tokens` from the heatmap tooltip and from `CalendarCell`'s tooltip use (the field stays decoded). Verification is a grep over `app/CicadaApp/Sources/CicadaApp/Views` for `usd`, `costUsd`, `equivCost`, `$/mo`, `tokens(` returning nothing. The Swift `Consumption*` models keep decoding the cost fields (wire compatibility; a decoded-but-unrendered field is not a UI surface). The backend `/consumption/*` routers, `consumption_stats.py`, `pricing.py` and `telemetry.py`'s cost fields are **not** edited.
- **R10 — The Feedback rate tile (G113 slice 4) does not exist yet on either side** (verified: no `feedback` in `api/routers/consumption.py`, no `ConsumptionFeedback` schema, no Swift caller). This plan does **not** build it — it is G113's own slice, still open in TODO.md item 2 — but `AdvancedStatsView` leaves a named slot (`feedbackTileSlot`, a `// G113 slice 4` comment beside the tile row) so that slice drops a tile in without re-laying out the page. It is a rate, not a price, so it is welcome under Advanced when it lands.
- **R11 — A `read` is: an MCP `cicada_recall_detail` of a page (`surface: mcp`), an MCP `cicada_recall` suggesting a page (`surface: mcp-recall`, one event per suggested id — the agent did see the summary), or the app opening an entity card (`surface: app`).** `top_read_entities` counts all three; the surface is kept in `refs` so a later reader can split them. Reason: G120 will want the split; recording it now costs nothing and re-deriving it later is impossible.
- **R12 — `read` is a non-spend kind.** `telemetry.NON_SPEND_KINDS = FEEDBACK_KINDS + ("read",)`; `consumption_stats.stats` filters `by_connection` on it (the G113 R7 rule, widened) so a `read` never invents an "unknown" connection. `summary()` already counts only `llm_call`/`ask` — unchanged.
- **R13 — Most-written is bounded: the last `TOP_ENTITIES_LOG_WINDOW = 2000` commits.** `git log --name-only` materialises every commit's file list before Python can stop (the reason `CONTRIBUTOR_LOG_WINDOW_*` exists); the response carries `commitsScanned` so the UI can say "over the last N commits" instead of implying all-time.
- **R14 — Contributors calendar = memory writes per UTC day per `Cicada-Author`, levels from writes alone.** It reuses `CalendarDay` (events/tokens/cost stay 0) so `HeatmapView` renders it unchanged. Reason: one heatmap component, one cell type, one layout test.
- **R15 — Navigation inside the page is a two-level stack (`grid` → `detail`) held in `@State`, with a back chevron and `⌘[`.** The entity card's `⌘[` (`EntityDetailCard.swift:194`) is only mounted on the Graph tab, so there is no conflict. Cross-page history is G108's decision — not built here.
- **R16 — `ConversationRow` and `ConversationPopover` move under `Views/Sources/`; `ConversationsSection`, `ActivityView`, `ActivitySection`, `UsageRangeControls`, `UsageSection`, `UsageAdvancedView` and `OriginPill` are deleted.** The `origins` Store domain and `OriginIconography` stay (the Sleep debt breakdown reads the iconography; removing a Store domain is G125's page-content decision, not this one's).
- **R17 — Harness marks reuse `OriginIconography`.** `mark` on a harness row is the harness id (`claude-code`, `cursor`, `codex`, …); `OriginIconography` already knows `claude-code` and falls back to `capitalized` + `tray` for the rest. New cases are added for `cursor`, `codex`, `claude-desktop` only — no image assets in this PR.

---

## File map

| File | Responsibility |
|---|---|
| `api/services/source_overview.py` (new) | `SourceSpec`, `CATALOG`, `source_key`, `build_overview` |
| `api/services/session_stats.py` | `aggregate_conversations(..., harness=, origin=)` filter |
| `api/routers/sources.py` | `GET /sources/overview`; `origin`/`folder` on `/sources` items |
| `api/routers/conversations.py` | `harness=`/`origin=` on `/conversations/recent` |
| `api/services/consumption_stats.py` | `_attributed_commits`, `memory_write_days_by_author`, `contributor_calendar`, `top_read_entities` |
| `api/services/git_service.py` | `top_written_entities`, `TOP_ENTITIES_LOG_WINDOW` |
| `api/services/telemetry.py` | `KINDS += "read"`, `NON_SPEND_KINDS`, `record_read` |
| `api/routers/contributors.py` | `GET /contributors/calendar`, `GET /contributors/top-entities` |
| `api/routers/entities.py` | `POST /entities/{id}/read` |
| `api/models/schemas.py` | `SourceOverview(+Response)`, `ContributorCalendar`, `TopEntities(+rows)`, `EntityReadRequest/Response`, `origin`/`folder` on `MediaSourceItem` |
| `mcp/server.py` | 3 `telemetry.record_read` call lines (recall + recall_detail) |
| `app/.../Views/Sidebar/SidebarView.swift`, `ContentView.swift`, `Theme/Copy.swift` | tab rename, icon, restore mapping, copy |
| `app/.../Models/SourceOverview.swift` (new), `Models/ContributorCalendar.swift` (new) | wire models |
| `app/.../Sync/Snapshot.swift`, `Store.swift`, `SyncAPI.swift`, `VersionVector.swift`, `Services/APIClient.swift` | `sourcesOverview` domain; conversation filters; new fetches; `recordEntityRead` |
| `app/.../Views/Sources/*` (new) | `SourcesPageView`, `SourceCardGrid`, `SourceDetailView`, `HarnessConversationsView`, `ChannelSourceView`, `ConversationRow` (moved), `ConversationPopover` (moved), `StatTile` (moved), `AdvancedStatsView` |
| `app/.../Views/Contributors/ContributorsView.swift`, `Views/Usage/HeatmapView.swift` | per-contributor calendar; tooltip without tokens |
| `app/.../ViewModels/UsageViewModel.swift`, `ConversationsViewModel.swift`, `Utilities/UsageFormat.swift` | cost projections removed; filters; formatters trimmed |
| `app/.../Views/Graph/EntityDetailCard.swift` | app-side `read` event on card open |
| `CLAUDE.md`, `docs/goals/memory-evolution.md`, `docs/goals/TODO.md` | docs |

---

### Task 1: Backend — `GET /sources/overview`, conversation filters, `origin`/`folder` on `/sources`

**Files:**
- Create: `api/services/source_overview.py`
- Modify: `api/services/session_stats.py:197-216` (`aggregate_conversations`)
- Modify: `api/routers/conversations.py:90-125` (`recent_conversations`)
- Modify: `api/routers/sources.py:471-568` (`list_sources`), add `GET /sources/overview` before line 570
- Modify: `api/models/schemas.py:1228-1258` (`MediaSourceItem`), add `SourceOverview` models after `OriginsResponse` (:256-260)
- Test: `api/tests/test_source_overview.py` (new), `api/tests/test_session_stats.py` (append two tests)

**Interfaces:**
- `source_overview.source_key(fm: dict) -> str` (pure; R1/R4).
- `source_overview.build_overview(memory_path: Path, *, channels: list[dict]) -> list[dict]` — snake_case rows matching `schemas.SourceOverview`.
- `session_stats.aggregate_conversations(memory_path, *, limit=20, transcript_exists=..., harness: str | None = None, origin: str | None = None)`.
- Wire: `GET /sources/overview → {"sources": [SourceOverview]}`; `GET /conversations/recent?harness=&origin=`; `MediaSourceItem.origin`, `.folder`.

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_source_overview.py
"""G124 — one row per memory source (harness / browser / social / feed /
messaging / import), computed from episode frontmatter, `source_episodes`
credits and `GET /sources/channels` state. Hermetic: a throwaway bank under
tmp_path; the real memory/ is never read. No network, no LLM."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import bank_index, channel_registry, source_overview, sync_state

UUID_A = "0f8f1c2a-4b5d-4e6f-8a9b-0c1d2e3f4a5b"
UUID_B = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"


def _episode(memory, episode_id, *, timestamp, origin=None, session_id=None,
             source_id=None, harness=None, title="Untitled"):
    d = memory / "episodes"
    d.mkdir(parents=True, exist_ok=True)
    lines = ["---", f"id: {episode_id}", f"timestamp: '{timestamp}'", f"title: {title}",
             "processed: true"]
    for key, value in (("origin", origin), ("session_id", session_id),
                       ("source_id", source_id), ("harness", harness)):
        if value is not None:
            lines.append(f"{key}: {value}")
    lines += ["---", "", "body"]
    (d / f"{episode_id}.md").write_text("\n".join(lines), encoding="utf-8")


def _entity(memory, entity_id, source_episodes):
    d = memory / "entities"
    d.mkdir(parents=True, exist_ok=True)
    eps = "\n".join(f"- {e}" for e in source_episodes) if source_episodes else "[]"
    (d / f"{entity_id}.md").write_text(
        f"---\nid: {entity_id}\ntype: concept\nstatus: active\nconfidence: 0.8\n"
        f"source_episodes:\n{eps}\n---\n\n# {entity_id}\n", encoding="utf-8")


@pytest.fixture
def bank(tmp_path):
    memory = tmp_path / "memory"
    memory.mkdir()
    # two Claude Code sessions, one Cursor session, one legacy mcp episode (no session)
    _episode(memory, "ep_2026-08-01_001", timestamp="2026-08-01T09:00:00+00:00",
             origin="mcp", session_id=UUID_A, harness="claude-code")
    _episode(memory, "ep_2026-08-01_002", timestamp="2026-08-01T10:00:00+00:00",
             origin="mcp", session_id=UUID_A, harness="claude-code")
    _episode(memory, "ep_2026-08-02_001", timestamp="2026-08-02T09:00:00+00:00",
             origin="mcp", session_id=UUID_B, harness="cursor")
    _episode(memory, "ep_2026-07-01_001", timestamp="2026-07-01T09:00:00+00:00", origin="mcp")
    # one imported Claude thread, two Safari bookmarks, one telegram capture
    _episode(memory, "ep_2026-08-03_001", timestamp="2026-08-03T09:00:00+00:00",
             origin="claude-export", source_id="thread-1")
    _episode(memory, "ep_2026-08-04_001", timestamp="2026-08-04T09:00:00+00:00", origin="safari-bookmark")
    _episode(memory, "ep_2026-08-04_002", timestamp="2026-08-04T10:00:00+00:00", origin="safari-bookmark")
    _episode(memory, "ep_2026-08-05_001", timestamp="2026-08-05T09:00:00+00:00", origin="telegram")
    # an origin the catalog does not know
    _episode(memory, "ep_2026-08-06_001", timestamp="2026-08-06T09:00:00+00:00", origin="mystery-app")
    _entity(memory, "alpha-project", ["ep_2026-08-01_001", "ep_2026-08-04_001"])
    _entity(memory, "bob-example", ["ep_2026-08-01_002"])
    _entity(memory, "gamma-tool", ["ep_2026-07-01_001"])
    sync_state.record_sync(memory, "safari-bookmarks", count=42, at="2026-08-04T10:05:00Z")
    bank_index.invalidate()
    return memory


def _rows(memory, telegram_enabled=False):
    channels = channel_registry.build_channels(memory, telegram_enabled=telegram_enabled)
    return {r["id"]: r for r in source_overview.build_overview(memory, channels=channels)}


def test_source_key_routes_mcp_and_session_episodes_to_a_harness_row():
    assert source_overview.source_key({"origin": "mcp", "session_id": UUID_A, "harness": "claude-code"}) == "harness:claude-code"
    assert source_overview.source_key({"origin": "mcp"}) == "harness:unknown", "R4: legacy mcp episodes still belong to a harness row"
    assert source_overview.source_key({"session_id": UUID_A, "harness": "cursor"}) == "harness:cursor"
    assert source_overview.source_key({"origin": "safari-bookmark"}) == "safari-bookmarks"
    assert source_overview.source_key({"origin": "claude-export", "source_id": "t"}) == "chat-export:claude"
    assert source_overview.source_key({"origin": "gemini-export", "source_id": "t"}) == "chat-export:gemini", "conversations.py:599 writes it"
    assert source_overview.source_key({"origin": "tiktok-history"}) == "tiktok"
    assert source_overview.source_key({"origin": "mystery-app"}) == "origin:mystery-app"
    assert source_overview.source_key({}) == "origin:unknown"


def test_harness_rows_count_conversations_episodes_and_entities(bank):
    rows = _rows(bank)
    cc = rows["harness:claude-code"]
    assert cc["kind"] == "harness" and cc["label"] == "Claude Code" and cc["mark"] == "claude-code"
    assert cc["conversations"] == 1 and cc["episodes"] == 2 and cc["entities"] == 2
    assert cc["harness"] == "claude-code" and cc["connected"] is True
    assert cc["last_activity_at"] == "2026-08-01T10:00:00+00:00"
    cursor = rows["harness:cursor"]
    assert cursor["conversations"] == 1 and cursor["episodes"] == 1 and cursor["entities"] == 0
    legacy = rows["harness:unknown"]
    assert legacy["conversations"] == 0 and legacy["episodes"] == 1 and legacy["entities"] == 1
    assert legacy["harness"] == "unknown", "the filter value the app sends back to /conversations/recent"


def test_catalog_rows_join_channel_state(bank):
    rows = _rows(bank)
    safari = rows["safari-bookmarks"]
    assert safari["kind"] == "browser" and safari["channel_id"] == "safari-bookmarks"
    assert safari["episodes"] == 2 and safari["entities"] == 1
    assert safari["items"] == 42 and safari["connected"] is True and safari["actions"] == ["sync"]
    assert safari["last_activity_at"] == "2026-08-04T10:05:00Z", "channel last_sync is newer than the last episode"
    assert safari["origins"] == ["safari-bookmark"]
    claude_export = rows["chat-export:claude"]
    assert claude_export["kind"] == "harness" and claude_export["conversations"] == 1
    assert claude_export["mark"] == "claude-export"


def test_telegram_row_follows_the_env_flag(bank):
    assert _rows(bank, telegram_enabled=False)["telegram"]["connected"] is False
    assert _rows(bank, telegram_enabled=True)["telegram"]["connected"] is True
    assert _rows(bank)["telegram"]["episodes"] == 1, "shown even when not connected — it has episodes (R2)"


def test_unknown_origin_gets_an_open_family_row_and_empty_catalog_rows_are_hidden(bank):
    rows = _rows(bank)
    mystery = rows["origin:mystery-app"]
    assert mystery["kind"] == "import" and mystery["label"] == "mystery-app" and mystery["episodes"] == 1
    assert "pinterest" not in rows and "rss" not in rows, "R2: no evidence, no card"
    assert "files" not in rows, "an empty url index is no evidence either (R1: files has no origins of its own)"


def test_rows_are_ordered_by_kind_then_recency(bank):
    ordered = source_overview.build_overview(
        bank, channels=channel_registry.build_channels(bank, telegram_enabled=False))
    kinds = [r["kind"] for r in ordered]
    assert kinds == sorted(kinds, key=source_overview.KIND_ORDER.index)
    harness_rows = [r for r in ordered if r["kind"] == "harness"]
    assert harness_rows[0]["id"] == "chat-export:claude", "newest activity first within a kind"


def test_empty_bank_yields_no_rows(tmp_path):
    memory = tmp_path / "memory"
    memory.mkdir()
    bank_index.invalidate()
    channels = channel_registry.build_channels(memory, telegram_enabled=False)
    assert source_overview.build_overview(memory, channels=channels) == []


# --- the route --------------------------------------------------------------


@pytest.fixture
def client(bank, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    monkeypatch.setenv("CICADA_HOME", str(bank.parent / "home"))
    config.get_settings.cache_clear()
    yield TestClient(main.app)
    config.get_settings.cache_clear()


def test_overview_route_is_camel_case_and_etagged(client, bank):
    first = client.get("/sources/overview")
    assert first.status_code == 200
    body = first.json()
    ids = {r["id"] for r in body["sources"]}
    assert {"harness:claude-code", "safari-bookmarks", "chat-export:claude"} <= ids
    row = next(r for r in body["sources"] if r["id"] == "safari-bookmarks")
    assert {"lastActivityAt", "channelId", "lastError", "conversations", "entities", "items"} <= set(row)
    etag = first.headers["etag"]
    assert client.get("/sources/overview", headers={"If-None-Match": etag}).status_code == 304
    # a new episode moves the `episodes` component -> the etag must move too
    _episode(bank, "ep_2026-08-07_001", timestamp="2026-08-07T09:00:00+00:00", origin="safari-bookmark")
    bank_index.invalidate()
    again = client.get("/sources/overview", headers={"If-None-Match": etag})
    assert again.status_code == 200 and again.headers["etag"] != etag


def test_sources_items_carry_origin_and_folder(client, bank):
    """R6 — the per-source page filters the existing Feed items by origin and
    groups them by folder, so both must ride `GET /sources`."""
    from api.services import media_ingestor
    media_ingestor.save_url_index(bank, {
        "h1": {"media_entity_id": "media-alpha", "episode_id": "ep_x", "url": "https://example.com/a",
               "title": "A", "media_type": "url", "thumbnail": None, "saved_at": "2026-08-04T10:00:00+00:00"},
    })
    (bank / "entities" / "media-alpha.md").write_text(
        "---\nid: media-alpha\ntype: media\nstatus: active\nconfidence: 0.9\norigin: safari-bookmark\n"
        "folder: Favorites/Papers\nsource_episodes: []\nrelated: []\nmedia:\n  url: https://example.com/a\n---\n\n# A\n",
        encoding="utf-8")
    bank_index.invalidate()
    items = client.get("/sources").json()["items"]
    row = next(i for i in items if i["mediaEntityId"] == "media-alpha")
    assert row["origin"] == "safari-bookmark" and row["folder"] == "Favorites/Papers"
```

Append to `api/tests/test_session_stats.py`:

```python


def test_aggregate_conversations_filters_by_harness_before_the_cap(tmp_path):
    """G124 R5: the filter runs before ``limit`` so a capped page never hides
    an older conversation of the selected harness."""
    memory = tmp_path / "memory"
    _episode(memory, "ep_2026-08-01_001", timestamp="2026-08-01T09:00:00Z",
             session_id=UUID_A, harness="claude-code", origin="mcp")
    _episode(memory, "ep_2026-08-02_001", timestamp="2026-08-02T09:00:00Z",
             session_id=UUID_B, harness="cursor", origin="mcp")
    _episode(memory, "ep_2026-08-03_001", timestamp="2026-08-03T09:00:00Z",
             source_id="thread-1", origin="claude-export")
    bank_index.invalidate()
    never = lambda project_dir, sid: False  # noqa: E731
    rows = session_stats.aggregate_conversations(memory, limit=1, transcript_exists=never,
                                                 harness="claude-code")
    assert [r["conversation_id"] for r in rows] == [UUID_A]
    rows = session_stats.aggregate_conversations(memory, limit=5, transcript_exists=never,
                                                 origin="claude-export")
    assert [r["conversation_id"] for r in rows] == ["thread-1"]


def test_aggregate_conversations_harness_unknown_matches_an_empty_harness(tmp_path):
    memory = tmp_path / "memory"
    _episode(memory, "ep_2026-08-01_001", timestamp="2026-08-01T09:00:00Z",
             session_id=UUID_A, origin="mcp")
    bank_index.invalidate()
    rows = session_stats.aggregate_conversations(
        memory, transcript_exists=lambda p, s: False, harness="unknown")
    assert [r["conversation_id"] for r in rows] == [UUID_A]
```

- [ ] **Step 2: Run the tests to confirm they fail**

```
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g124 && api/.venv/bin/python -m pytest api/tests/test_source_overview.py api/tests/test_session_stats.py -q -p no:cacheprovider 2>&1 | tail -5
```
Expected: `ImportError`/`AttributeError` on `source_overview`, `TypeError` on the new kwargs.

- [ ] **Step 3: Schemas** — in `api/models/schemas.py`, add `origin`/`folder` to `MediaSourceItem` (after `about`, :1258) and the overview models after `OriginsResponse` (:260):

```python
    # G124 R6 — the media entity's own `origin:` / `folder:` frontmatter
    # (written by media_ingestor.write_media_entity) so the Sources page can
    # filter the Feed's items to one source and group them by bookmark folder,
    # Pinterest board or iCloud device without a second endpoint. Optional:
    # a page ingested before origins were stamped simply has neither.
    origin: Optional[str] = None
    folder: Optional[str] = None
```

```python
# --- Sources overview (G124 — one card per memory source) ---


class SourceOverview(CamelModel):
    """One memory source as the Sources page shows it.

    ``id`` equals the ``GET /sources/channels`` id where the source is a
    channel (so the app joins channel state by equality), ``harness:<name>``
    for an MCP harness, ``origin:<id>`` for an origin the catalog does not
    know (see ``source_overview.CATALOG``). ``kind`` is one of
    ``source_overview.KIND_ORDER``. ``mark`` is an ``OriginIconography`` key.
    Counts are engine-free: episodes/entities from frontmatter (entities via
    ``source_episodes`` only — R3), conversations = distinct ``session_id`` /
    ``source_id``, items = the channel's own count. ``origins`` and
    ``harness`` are the filter values the app sends back (``GET /sources``
    items by origin; ``GET /conversations/recent?harness=``).
    """

    id: str
    label: str
    kind: str
    mark: str
    conversations: int = 0
    episodes: int = 0
    entities: int = 0
    items: int = 0
    last_activity_at: Optional[str] = None
    connected: bool = False
    last_error: Optional[str] = None
    actions: list[str] = []
    channel_id: Optional[str] = None
    origins: list[str] = []
    harness: Optional[str] = None


class SourceOverviewResponse(CamelModel):
    sources: list[SourceOverview] = []
```

- [ ] **Step 4: The service** — create `api/services/source_overview.py`:

```python
"""One row per memory source — the Sources page's grid (G124).

Where ``origin_stats`` answers "which capture origin" and ``session_stats``
answers "which conversation", this module answers the question the person
asks first: *which of my sources fed this memory, how much, and when last?*
It joins three facts that already exist on disk — episode frontmatter
(``origin``, ``harness``, ``session_id``/``source_id``), entity
``source_episodes`` credits, and ``GET /sources/channels`` state — into one
list. Pure filesystem read; no git, no network, no LLM.

Identity (R1): a closed ``CATALOG`` names every known channel/origin and maps
it to the channel id the app already knows, plus two open families —
``harness:<name>`` for MCP harnesses and ``origin:<id>`` for an origin the
catalog has never heard of — so a new harness or importer appears the day it
ships instead of vanishing into "other". Entity credit is ``source_episodes``
only (R3): ``session_stats`` also credits claims stamped with a session, at
the cost of a body parse per entity; this list counts the way ``/origins``
does and the per-harness conversation rows keep the richer credit.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from api.services import bank_index

KIND_ORDER = ("harness", "browser", "social", "feed", "messaging", "import")


@dataclass(frozen=True)
class SourceSpec:
    id: str
    label: str
    kind: str
    mark: str            # an OriginIconography key on the app side
    origins: tuple[str, ...]
    channel: str | None  # GET /sources/channels id, when the source is a channel


# Every origin below is one a real writer stamps today (see R1 in the plan for
# the file:line of each). Two rows deliberately carry NO origins: `files`
# (`POST /sources/save`, `cicada_save_url` and the RSS poll all build a bare
# `RawItem` — their pages have no `origin:`, so the app shows nil-origin items
# under Files & links) and `rss` (same cause; its evidence is the subscription
# registry alone until `ingest_feed` stamps one — follow-up on the G124 row).
CATALOG: tuple[SourceSpec, ...] = (
    SourceSpec("chat-export:claude", "Claude export", "harness", "claude-export", ("claude-export",), "chat-export:claude"),
    SourceSpec("chat-export:chatgpt", "ChatGPT export", "harness", "chatgpt-export", ("chatgpt-export",), "chat-export:chatgpt"),
    # conversations.py:599 — the Gemini Takeout importer; no channel row exists
    # for it yet, so channel=None and its evidence is its episodes.
    SourceSpec("chat-export:gemini", "Gemini export", "harness", "gemini-export", ("gemini-export",), None),
    SourceSpec("chrome-bookmarks", "Chrome bookmarks", "browser", "chrome-bookmark", ("chrome-bookmark",), "chrome-bookmarks"),
    SourceSpec("safari-bookmarks", "Safari bookmarks", "browser", "safari-bookmark", ("safari-bookmark",), "safari-bookmarks"),
    SourceSpec("safari-tabs", "Safari iCloud tabs", "browser", "safari-tab", ("safari-tab",), "safari-tabs"),
    SourceSpec("pinterest", "Pinterest", "social", "pinterest", ("pinterest",), "pinterest"),
    SourceSpec("reddit", "Reddit", "social", "reddit-saved", ("reddit-saved",), "reddit"),
    SourceSpec("x", "X", "social", "x-bookmarks", ("x-bookmarks",), "x"),
    SourceSpec("instagram", "Instagram", "social", "instagram-saved", ("instagram-saved",), None),
    SourceSpec("youtube", "YouTube", "social", "youtube-playlist", ("youtube-playlist",), None),
    SourceSpec("linkedin", "LinkedIn", "social", "linkedin-saved", ("linkedin-saved",), None),
    SourceSpec("tiktok", "TikTok", "social", "tiktok-saved", ("tiktok-saved", "tiktok-history"), None),
    SourceSpec("rss", "RSS feeds", "feed", "rss", (), "rss"),            # no origin stamped today — see R1
    SourceSpec("calendar", "Calendars", "feed", "calendar", ("calendar",), "calendar"),
    SourceSpec("telegram", "Telegram", "messaging", "telegram", ("telegram",), "telegram"),
    SourceSpec("notes", "Apple Notes", "import", "apple-notes", ("apple-notes",), "notes"),
    SourceSpec("files", "Files & links", "import", "bookmark", (), "files"),  # nil-origin pages — see R1
)
_BY_ID = {spec.id: spec for spec in CATALOG}
_ORIGIN_TO_ID = {origin: spec.id for spec in CATALOG for origin in spec.origins}

# Display names for harness ids an MCP client stamps (mcp/server.py SESSION).
# Generic on purpose — portability means no owner-specific client here; an
# unlisted harness reads as its id.
HARNESS_LABELS = {
    "claude-code": "Claude Code",
    "claude-desktop": "Claude Desktop",
    "cursor": "Cursor",
    "codex": "Codex",
    "unknown": "Other agents",
}
UNKNOWN = "unknown"


def source_key(fm: dict) -> str:
    """Which source row an episode belongs to.

    A ``session_id`` or ``origin: mcp`` means an agent conversation, so the
    row is the harness (R4: legacy ``mcp`` episodes with no session still
    belong to ``harness:unknown`` — they ARE conversations, just uncounted
    ones). Otherwise the origin looks itself up in the catalog and falls back
    to the open ``origin:`` family.
    """
    origin = str(fm.get("origin") or "").strip()
    if fm.get("session_id") or origin == "mcp":
        return "harness:" + (str(fm.get("harness") or "").strip() or UNKNOWN)
    if not origin:
        return f"origin:{UNKNOWN}"
    return _ORIGIN_TO_ID.get(origin, f"origin:{origin}")


def _new_state(key: str) -> dict:
    if key.startswith("harness:"):
        harness = key.split(":", 1)[1]
        label, kind, mark, origins, channel = (
            HARNESS_LABELS.get(harness, harness), "harness", harness, [], None)
    elif key in _BY_ID:
        spec = _BY_ID[key]
        label, kind, mark, origins, channel = spec.label, spec.kind, spec.mark, list(spec.origins), spec.channel
        harness = None
    else:
        origin = key.split(":", 1)[1]
        label, kind, mark, origins, channel, harness = origin, "import", origin, [origin], None, None
    return {
        "id": key, "label": label, "kind": kind, "mark": mark,
        "conversations": set(), "episodes": 0, "entities": set(),
        "items": 0, "last_activity_at": "", "connected": False,
        "last_error": None, "actions": [], "channel_id": channel,
        "origins": origins, "harness": harness,
    }


def build_overview(memory_path: Path, *, channels: list[dict]) -> list[dict]:
    """Every source with evidence (R2), ordered by kind then newest activity.

    ``channels`` is ``channel_registry.build_channels(...)``'s output — passed
    in, not recomputed, so the router computes it once for both the ETag's
    connector tag and this payload.
    """
    memory_path = Path(memory_path)
    states: dict[str, dict] = {}
    episode_key: dict[str, str] = {}

    for f in bank_index.files(memory_path, "episodes"):
        fm = f.frontmatter
        key = source_key(fm)
        episode_key[str(fm.get("id") or f.stem)] = key
        state = states.setdefault(key, _new_state(key))
        state["episodes"] += 1
        conversation = str(fm.get("session_id") or fm.get("source_id") or "").strip()
        if conversation:
            state["conversations"].add(conversation)
        ts = str(fm.get("timestamp") or "")
        if _sortable(ts) > _sortable(state["last_activity_at"]):
            state["last_activity_at"] = ts

    for f in bank_index.files(memory_path, "entities"):
        fm = f.frontmatter
        entity_id = str(fm.get("id") or f.stem)
        for ep_id in fm.get("source_episodes", []) or []:
            key = episode_key.get(ep_id)
            if key:
                states[key]["entities"].add(entity_id)

    for channel in channels:
        spec = _BY_ID.get(channel["id"])
        if spec is None:
            continue
        state = states.setdefault(spec.id, _new_state(spec.id))
        state["items"] = int(channel.get("count") or 0)
        state["connected"] = bool(channel.get("connected"))
        state["last_error"] = channel.get("last_error")
        state["actions"] = list(channel.get("actions") or [])
        last_sync = str(channel.get("last_sync") or "")
        # By instant, not lexically: a `Z` sync stamp and a `+00:00` episode
        # stamp differ in shape and would otherwise compare by string length.
        if _sortable(last_sync) > _sortable(state["last_activity_at"]):
            state["last_activity_at"] = last_sync

    rows = []
    for state in states.values():
        conversations = len(state["conversations"])
        if state["channel_id"] is None:
            # No channel to be "connected" to: a harness or import-only source
            # is connected exactly when it has fed memory.
            state["connected"] = state["episodes"] > 0
        if not (state["connected"] or state["episodes"] or conversations or state["items"]):
            continue  # R2
        rows.append({
            **state,
            "conversations": conversations,
            "entities": len(state["entities"]),
            "last_activity_at": state["last_activity_at"] or None,
        })
    rows.sort(key=lambda r: (KIND_ORDER.index(r["kind"]), -_sortable(r["last_activity_at"]), r["id"]))
    return rows


def _sortable(ts: str | None) -> float:
    """ISO timestamps compare lexically only within one shape; normalise
    ``Z``/``+00:00`` and bare dates to a float so a sync stamp and an episode
    stamp order by instant, never by string length."""
    from datetime import datetime, timezone
    if not ts:
        return 0.0
    try:
        parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()
```

- [ ] **Step 5: `session_stats.aggregate_conversations` filters** — at `api/services/session_stats.py:197-216` change the signature and body:

```python
def aggregate_conversations(
    memory_path: Path,
    *,
    limit: int = 20,
    transcript_exists=default_transcript_exists,
    harness: str | None = None,
    origin: str | None = None,
) -> list[dict]:
    """Recent conversations, newest write first.

    Returns snake_case dicts matching ``schemas.ConversationSummary``'s field
    names (``CamelModel`` has ``populate_by_name=True``, so
    ``ConversationSummary(**row)`` just works). ``project_dir`` is NOT included
    — only the resume endpoint ever sees it.

    ``harness`` / ``origin`` (G124 R5) filter BEFORE the cap: the Sources
    page's per-harness list must never lose an older conversation to a page
    limit. ``harness="unknown"`` matches rows whose harness is empty — the
    same value the overview reports for them.
    """
    groups = _group(Path(memory_path))
    rows = [
        project_conversation(g, transcript_exists=transcript_exists)
        for g in groups.values()
    ]
    if harness is not None:
        wanted = "" if harness == "unknown" else harness
        rows = [r for r in rows if r["harness"] == wanted]
    if origin is not None:
        rows = [r for r in rows if r["origin"] == origin]
    rows.sort(key=lambda r: (r["last_seen"], r["conversation_id"]), reverse=True)
    return rows[: max(1, int(limit or 20))]
```

- [ ] **Step 6: Router changes**

`api/routers/conversations.py:90-125` — add the two query params, fold them into the ETag, pass them through:

```python
@router.get("/conversations/recent", response_model=list[ConversationSummary])
async def recent_conversations(
    request: Request,
    response: Response,
    limit: int = Query(20, ge=1, le=200),
    harness: str | None = Query(None, max_length=64),
    origin: str | None = Query(None, max_length=64),
    settings: Settings = Depends(get_settings),
):
```
…keep the docstring, append one paragraph: `"""…\n\n    ``harness`` / ``origin`` (G124 R5) narrow the list to one source BEFORE the\n    cap, so the Sources page's per-harness view is complete up to ``limit``.\n    """` — and change the ETag `extra` to `f"limit={limit}|harness={harness or ''}|origin={origin or ''}"` and the threadpool call to pass `harness=harness, origin=origin`.

`api/routers/sources.py`:
1. In `list_sources` (:471-568) read the two fields inside the existing `try` right after `about = ...`:
```python
                # G124 R6 — the Sources page filters these items by source and
                # groups them by folder/board/device, straight from the page.
                origin = str(fm.get("origin") or "").strip() or None
                folder = str(fm.get("folder") or "").strip() or None
```
(declare `origin: str | None = None` and `folder: str | None = None` beside `description`/`about` above the `if entity_path.exists()` block, and pass `origin=origin, folder=folder` into `MediaSourceItem(...)`).
2. Add the route immediately BEFORE `@router.get("/sources/channels", ...)` (:570):

```python
@router.get("/sources/overview", response_model=SourceOverviewResponse)
async def sources_overview(
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
):
    """One card per memory source (G124) — the Sources page's grid.

    Same ETag recipe as ``/sources/channels`` (R7): the payload is computed
    from episodes, entities, ``sync_state.json``, the feed/calendar registries
    and the url index — all inside the ``sources``/``episodes``/``entities``
    components — plus the Telegram flag and connector credentials, which are
    config facts no component sees. Off the event loop for the same reason
    ``/origins`` and ``/sources/channels`` are: a cold ``bank_index`` re-parses
    every frontmatter.
    """
    memory_path = settings.memory_path
    connectors_connected = {cid: adapter.is_connected() for cid, adapter in ADAPTERS.items()}
    connector_tag = ",".join(f"{k}:{v}" for k, v in sorted(connectors_connected.items()))
    etag = sync_service.etag_for(
        memory_path, "sources", "episodes", "entities",
        extra=f"overview|telegram:{settings.telegram_enabled}|connectors:{connector_tag}",
    )
    if (early := sync_service.conditional(request, response, etag)) is not None:
        return early

    def _build() -> list[dict]:
        channels = channel_registry.build_channels(
            memory_path,
            telegram_enabled=settings.telegram_enabled,
            connectors_connected=connectors_connected,
        )
        return source_overview.build_overview(memory_path, channels=channels)

    rows = await run_in_threadpool(_build)
    return SourceOverviewResponse(sources=[SourceOverview(**r) for r in rows])
```
Add `source_overview` to the `from api.services import (...)` block and `SourceOverview, SourceOverviewResponse` to the schemas import.

- [ ] **Step 7: Run the tests until green**

```
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g124 && api/.venv/bin/python -m pytest api/tests/test_source_overview.py api/tests/test_session_stats.py api/tests/test_source_channels.py api/tests/test_origin_stats.py api/tests/test_conversation_resume.py api/tests/test_session_provenance_views.py -q -p no:cacheprovider 2>&1 | tail -5
```
Expected: all pass.

- [ ] **Step 8: Commit**

```
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g124 && git add -- api/services/source_overview.py api/services/session_stats.py api/routers/sources.py api/routers/conversations.py api/models/schemas.py api/tests/test_source_overview.py api/tests/test_session_stats.py && git commit -q -m "feat(api): GET /sources/overview — one engine-free row per memory source (G124)

One card per harness/origin/channel from episode frontmatter, source_episodes
credits and /sources/channels state; harness=/origin= filters on
/conversations/recent applied before the cap (R5); origin/folder on /sources
items so the per-source page filters the Feed client-side (R6). ETag rides
sources+episodes+entities, ship-together with /sources/channels (R7).

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj"
```

---

### Task 2: Backend — contributors calendar, top entities, the `read` ledger kind

**Files:**
- Modify: `api/services/telemetry.py:21-31` (`KINDS`, `NON_SPEND_KINDS`), add `record_read` after `record_audit` (:143-172)
- Modify: `api/services/consumption_stats.py:30-62` (`memory_write_days` → shared `_attributed_commits`), :213 (`NON_SPEND_KINDS`), add `memory_write_days_by_author`, `contributor_calendar`, `top_read_entities`
- Modify: `api/services/git_service.py` — add `TOP_ENTITIES_LOG_WINDOW` near :100-122 and `top_written_entities` after `get_contributor_commits` (:746-822)
- Modify: `api/routers/contributors.py:32-51` — add two routes
- Modify: `api/routers/entities.py` — add `POST /entities/{entity_id}/read` after `get_entity` (:55-90)
- Modify: `api/models/schemas.py` — `ContributorCalendar`, `TopEntityWrite`, `TopEntityRead`, `TopEntities`, `EntityReadRequest`, `EntityReadResponse` after `ContributorsResponse` (:239-243)
- Modify: `mcp/server.py:863-869` (`handle_recall`) and `:1084` (`handle_recall_detail`) — 3 lines + 1 local import each
- Test: `api/tests/test_contributor_calendar.py` (new), `api/tests/test_entity_read_events.py` (new)

**Interfaces:**
- `telemetry.record_read(entity_id: str, *, surface: str, bank: str | None) -> None` (never raises).
- `consumption_stats.memory_write_days_by_author(memory_path, author) -> dict[str, int]`; `contributor_calendar(memory_path, *, author, weeks, today) -> list[dict]` (CalendarDay rows); `top_read_entities(*, range_, today, limit) -> list[dict]`.
- `git_service.top_written_entities(memory_path, *, limit) -> tuple[list[dict], int]`.
- Wire: `GET /contributors/calendar?author=&weeks=` → `{author, days:[CalendarDay], weeks}`; `GET /contributors/top-entities?limit=&range=` → `{written:[{entityId,commits,lastWritten}], read:[{entityId,reads,lastRead}], commitsScanned, range}`; `POST /entities/{id}/read {surface}` → `{recorded: bool}`.

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_contributor_calendar.py
"""G124 — the GitHub-style calendar per Cicada-Author and the most-written
entities. Hermetic: throwaway git repos with hand-crafted trailers; the real
memory/ is never touched."""
from __future__ import annotations

import asyncio
import subprocess
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import consumption_stats, git_service


def run(coro):
    return asyncio.run(coro)


def _git(repo: Path, *args: str, env: dict | None = None) -> str:
    import os
    return subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True,
                          text=True, env={**os.environ, **(env or {})}).stdout


def _commit(repo: Path, rel: str, text: str, *, author: str | None, when: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    _git(repo, "add", "--", rel)
    message = git_service.build_commit_message(
        f"write {rel}", [f"{rel}: updated (source: ep_1, trigger: sleep/extraction)"],
        authors=[author] if author else None)
    _git(repo, "commit", "-q", "-m", message,
         env={"GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when})


@pytest.fixture
def repo(tmp_path) -> Path:
    r = tmp_path / "memory"
    (r / "entities").mkdir(parents=True)
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "test@cicada.local")
    _git(r, "config", "user.name", "Cicada Test")
    _commit(r, "entities/alpha-project.md", "v1", author="gpt-5.4-mini", when="2026-08-01T10:00:00+00:00")
    _commit(r, "entities/alpha-project.md", "v2", author="gpt-5.4-mini", when="2026-08-01T23:30:00-07:00")  # = 08-02 UTC
    _commit(r, "entities/bob-example.md", "v1", author="user", when="2026-08-03T10:00:00+00:00")
    _commit(r, "entities/alpha-project.md", "v3", author="user", when="2026-08-03T11:00:00+00:00")
    _commit(r, "entities/gamma-tool.md", "v1", author=None, when="2026-08-04T10:00:00+00:00")  # untrailered
    return r


def test_memory_write_days_by_author_buckets_by_utc_day(repo):
    days = run(consumption_stats.memory_write_days_by_author(repo, "gpt-5.4-mini"))
    assert days == {"2026-08-01": 1, "2026-08-02": 1}, "the -07:00 commit is the next UTC day"
    assert run(consumption_stats.memory_write_days_by_author(repo, "user")) == {"2026-08-03": 2}
    assert run(consumption_stats.memory_write_days_by_author(repo, "unknown")) == {"2026-08-04": 1}
    assert run(consumption_stats.memory_write_days_by_author(repo, "nobody")) == {}


def test_memory_write_days_total_is_unchanged_by_the_refactor(repo):
    total = run(consumption_stats.memory_write_days(repo))
    assert total == {"2026-08-01": 1, "2026-08-02": 1, "2026-08-03": 2}, "untrailered commits are not memory writes"


def test_contributor_calendar_levels_come_from_writes_alone(repo):
    days = run(consumption_stats.contributor_calendar(
        repo, author="user", weeks=1, today=date(2026, 8, 5)))
    assert [d["date"] for d in days] == [f"2026-07-{n}" for n in (30, 31)] + [f"2026-08-0{n}" for n in range(1, 6)]
    by_date = {d["date"]: d for d in days}
    assert by_date["2026-08-03"]["memory_writes"] == 2 and by_date["2026-08-03"]["level"] == 4
    assert by_date["2026-08-01"]["memory_writes"] == 0 and by_date["2026-08-01"]["level"] == 0
    assert all(d["tokens"] == 0 and d["cost_usd"] == 0.0 for d in days), "R14: writes only"


def test_top_written_entities_counts_commits_per_page(repo):
    rows, scanned = run(git_service.top_written_entities(repo, limit=10))
    assert scanned == 5
    assert rows[0] == {"entity_id": "alpha-project", "commits": 3, "last_written": "2026-08-03"}
    # ties on commit count (bob 08-03, gamma 08-04) show the newer page first
    assert [r["entity_id"] for r in rows] == ["alpha-project", "gamma-tool", "bob-example"]
    assert run(git_service.top_written_entities(repo, limit=1))[0] == rows[:1]


def test_top_written_entities_on_a_non_git_dir_is_empty(tmp_path):
    assert run(git_service.top_written_entities(tmp_path, limit=5)) == ([], 0)


@pytest.fixture
def client(repo, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(repo))
    monkeypatch.setenv("CICADA_HOME", str(repo.parent / "home"))
    monkeypatch.setenv("CICADA_TELEMETRY", "on")
    config.get_settings.cache_clear()
    yield TestClient(main.app)
    config.get_settings.cache_clear()


def test_calendar_route_is_per_author_and_etagged(client):
    r = client.get("/contributors/calendar?author=user&weeks=2")
    assert r.status_code == 200
    body = r.json()
    assert body["author"] == "user" and body["weeks"] == 2 and len(body["days"]) == 14
    assert {"date", "memoryWrites", "level"} <= set(body["days"][0])
    etag = r.headers["etag"]
    assert client.get("/contributors/calendar?author=user&weeks=2", headers={"If-None-Match": etag}).status_code == 304
    assert client.get("/contributors/calendar?author=gpt-5.4-mini&weeks=2").headers["etag"] != etag
    assert client.get("/contributors/calendar?weeks=2").status_code == 422, "author is required"


def test_top_entities_route_merges_git_and_ledger(client):
    from api.services import telemetry as tm
    tm.record_read("bob-example", surface="app", bank="memory")
    tm.record_read("bob-example", surface="mcp", bank="memory")
    tm.record_read("alpha-project", surface="mcp-recall", bank="memory")
    body = client.get("/contributors/top-entities?limit=5&range=all").json()
    assert body["written"][0]["entityId"] == "alpha-project" and body["written"][0]["commits"] == 3
    assert body["commitsScanned"] == 5 and body["range"] == "all"
    assert [(r["entityId"], r["reads"]) for r in body["read"]] == [("bob-example", 2), ("alpha-project", 1)]
    assert body["read"][0]["lastRead"]
```

```python
# api/tests/test_entity_read_events.py
"""G124 R11/R12 — the ids-only `read` ledger event: app card opens, MCP
recall_detail, MCP recall suggestions. Nothing but an entity id and a surface
enum ever reaches the ledger."""
from __future__ import annotations

import importlib
import json

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import consumption_stats, telemetry as tm

mcp = importlib.import_module("mcp.server")


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_TELEMETRY", "on")
    return tmp_path / "home"


def _events(home):
    out = []
    for path in sorted((home / "telemetry").glob("events-*.jsonl")):
        out += [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    return out


def test_record_read_is_ids_only_and_non_spend(home):
    tm.record_read("alpha-project", surface="app", bank="demo")
    tm.record_read("", surface="app", bank="demo")  # ignored, never raises
    events = _events(home)
    assert len(events) == 1
    ev = events[0]
    assert ev["kind"] == "read" and ev["refs"] == {"entity_id": "alpha-project", "surface": "app"}
    assert ev["invocations"] == 0 and ev["billing"] == "free" and ev["connection"] is None
    assert "read" in tm.KINDS and "read" in tm.NON_SPEND_KINDS


def test_reads_never_invent_an_unknown_connection_in_stats(home, tmp_path):
    from datetime import date
    tm.record_read("alpha-project", surface="app", bank="demo")
    data = __import__("asyncio").run(consumption_stats.stats(tmp_path, range_="all", today=date.today()))
    assert data["by_connection"] == [], "R12 widens G113 R7 to the read kind"
    assert data["by_stage"] and data["by_stage"][0]["stage"] == "recall"


def test_post_entities_read_records_and_404s_on_an_unknown_page(home, tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    (memory / "entities" / "alpha-project.md").write_text("---\nid: alpha-project\ntype: concept\n---\n# A\n")
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    client = TestClient(main.app)
    try:
        assert client.post("/entities/alpha-project/read", json={"surface": "app"}).json() == {"recorded": True}
        assert client.post("/entities/nope/read", json={"surface": "app"}).status_code == 404
        assert client.post("/entities/alpha-project/read", json={"surface": "browser"}).status_code == 422
    finally:
        config.get_settings.cache_clear()
    events = _events(home)
    assert [e["refs"] for e in events] == [{"entity_id": "alpha-project", "surface": "app"}]


def test_mcp_recall_detail_records_one_read_with_the_mcp_surface(home, tmp_path, monkeypatch):
    memory = tmp_path / "bank"
    (memory / "entities").mkdir(parents=True)
    (memory / "entities" / "alpha-project.md").write_text("---\nid: alpha-project\ntype: concept\n---\n# Alpha\n")
    monkeypatch.setattr(mcp, "get_memory_path", lambda: memory)
    text = mcp.handle_recall_detail("alpha-project")
    assert text.startswith("---")
    assert [e["refs"] for e in _events(home)] == [{"entity_id": "alpha-project", "surface": "mcp"}]
    mcp.handle_recall_detail("missing")
    assert len(_events(home)) == 1, "a miss is not a read"


def test_mcp_recall_records_the_suggested_ids_with_the_recall_surface(home, tmp_path, monkeypatch):
    memory = tmp_path / "bank"
    (memory / "entities").mkdir(parents=True)
    (memory / "entities" / "alpha-project.md").write_text(
        "---\nid: alpha-project\ntype: project\nname: Alpha Project\n---\n# Alpha Project\nA capstone about graphs.\n")
    # Same hermetic seam set as test_mcp_recall_episode_fallback.py: every
    # retrieval source but the keyword scan is stubbed, so the one suggested
    # id can only have come from the page written above.
    monkeypatch.setattr(mcp, "get_memory_path", lambda: memory)
    monkeypatch.setattr(mcp, "_relevant_inbox", lambda memory_path, query: [])
    monkeypatch.setattr(mcp, "_match_hub", lambda memory_path, query: (None, []))
    monkeypatch.setattr(mcp, "_leann_search_entities", lambda memory_path, query, top_k: [])
    monkeypatch.setattr(mcp, "_leann_search_episodes", lambda memory_path, query, top_k: [])
    # `_keyword_search_entities` (mcp/server.py:1439) is a whole-query
    # substring match on the name/tags/body, so the query must be a phrase the
    # page contains.
    mcp.handle_recall("alpha project")
    refs = [e["refs"] for e in _events(home)]
    assert refs and all(r["surface"] == "mcp-recall" for r in refs)
    assert {r["entity_id"] for r in refs} == {"alpha-project"}
    assert all(set(r) == {"entity_id", "surface"} for r in refs), "never the query, never text"
```

- [ ] **Step 2: Run to confirm failure**

```
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g124 && api/.venv/bin/python -m pytest api/tests/test_contributor_calendar.py api/tests/test_entity_read_events.py -q -p no:cacheprovider 2>&1 | tail -5
```

- [ ] **Step 3: `telemetry.py`** — `KINDS` gains `"read"`; after `FEEDBACK_KINDS` add:

```python
# G124 R12: kinds that carry no spend. ``read`` (an entity page opened by the
# app or served to an agent by cicada_recall/recall_detail) joins the feedback
# kinds in being excluded from connection rollups — a `connection=None` row
# would otherwise surface as an "unknown" connection in ``/consumption/stats``.
NON_SPEND_KINDS = FEEDBACK_KINDS + ("read",)
```
and after `record_audit`:

```python
def record_read(entity_id: str, *, surface: str, bank: str | None) -> None:
    """One ``read`` event: an entity page was looked at (G124 R11).

    ``refs`` carries the entity id and a surface enum (``app`` — a card opened
    in the companion app; ``mcp`` — ``cicada_recall_detail`` served the page;
    ``mcp-recall`` — ``cicada_recall`` suggested it) and NOTHING else: never
    the query, never the page. The ledger is machine-global and outside the
    bank, so this is the same privacy line the G113 feedback rows draw. An
    empty id is ignored; nothing here can raise into a recall or a card open.
    """
    if not (entity_id or "").strip():
        return
    record(UsageEvent(
        kind="read", stage="recall", bank=bank, invocations=0, billing="free",
        refs={"entity_id": entity_id, "surface": surface},
    ))
```

- [ ] **Step 4: `consumption_stats.py`** — replace `memory_write_days` (:30-62) with a shared walker plus the per-author variant, and add the two new aggregations after `calendar`:

```python
async def _attributed_commits(memory_path: Path) -> list[tuple[str, list[str]]]:
    """``(utc_day, authors)`` per commit carrying a ``Cicada-Author`` trailer.

    Buckets by **UTC** calendar day: ``git log --date=short`` (or any
    ``%ad``-based format) buckets by the author's recorded UTC *offset*, so a
    commit authored at ``2026-08-27T23:30:00-07:00`` (= ``2026-08-28T06:30Z``)
    would land on ``08-27`` there, one day off from the ledger's explicit-UTC
    ``ts[:10]``. Taking ``%aI`` and converting in Python makes both sources
    agree on one day definition. Shared by the repo-wide and per-author
    calendars (G124) so they can never disagree on what a "write" is.
    """
    if not (memory_path / ".git").exists():
        return []
    sep, rec = "\x1f", "\x1e"
    try:
        out = await git_service._run_git(memory_path, "log", f"--format=%aI{sep}%b{rec}")
    except git_service.GitError:
        return []
    commits: list[tuple[str, list[str]]] = []
    for record in out.split(rec):
        if sep not in record:
            continue
        iso_date, body = record.strip("\n").split(sep, 1)
        iso_date = iso_date.strip()
        if not iso_date:
            continue
        try:
            day = datetime.fromisoformat(iso_date).astimezone(timezone.utc).date().isoformat()
        except ValueError:
            continue
        authors = git_service._parse_authors(body)
        if authors:
            commits.append((day, authors))
    return commits


async def memory_write_days(memory_path: Path) -> dict[str, int]:
    """ISO-day -> attributed-commit count (every author). See ``_attributed_commits``."""
    days: Counter[str] = Counter(day for day, _authors in await _attributed_commits(memory_path))
    return dict(days)


async def memory_write_days_by_author(memory_path: Path, author: str) -> dict[str, int]:
    """ISO-day -> commit count for ONE ``Cicada-Author`` (G124 R14).

    ``"unknown"`` selects legacy untrailered commits, matching
    ``git_service.get_contributors``' bucket for them; ``_attributed_commits``
    skips those, so they are walked separately here through the same UTC rule.
    """
    if author == git_service.UNKNOWN_AUTHOR:
        if not (memory_path / ".git").exists():
            return {}
        sep, rec = "\x1f", "\x1e"
        try:
            out = await git_service._run_git(memory_path, "log", f"--format=%aI{sep}%b{rec}")
        except git_service.GitError:
            return {}
        days: Counter[str] = Counter()
        for record in out.split(rec):
            if sep not in record:
                continue
            iso_date, body = record.strip("\n").split(sep, 1)
            if git_service._parse_authors(body) or not iso_date.strip():
                continue
            try:
                days[datetime.fromisoformat(iso_date.strip()).astimezone(timezone.utc).date().isoformat()] += 1
            except ValueError:
                continue
        return dict(days)
    days = Counter(day for day, authors in await _attributed_commits(memory_path) if author in authors)
    return dict(days)
```

(after `calendar`)

```python
async def contributor_calendar(memory_path: Path, *, author: str, weeks: int, today: date) -> list[dict]:
    """The ``/consumption/calendar`` shape for ONE contributor (G124 R14):
    memory writes per UTC day, level from writes alone, every other counter
    zero so ``HeatmapView`` renders it with no new cell type."""
    start = today - timedelta(days=weeks * 7 - 1)
    writes = await memory_write_days_by_author(memory_path, author)
    rows: dict[str, dict] = {}
    for i in range(weeks * 7):
        d = (start + timedelta(days=i)).isoformat()
        rows[d] = {"date": d, "memory_writes": writes.get(d, 0), "events": 0, "tokens": 0,
                   "cost_usd": 0.0, "equiv_cost_usd": 0.0}
    levels = _levels({d: float(r["memory_writes"]) for d, r in rows.items()})
    for d, r in rows.items():
        r["level"] = levels[d]
    return list(rows.values())


def top_read_entities(*, range_: str, today: date, limit: int) -> list[dict]:
    """Most-read entity ids from the ``read`` ledger kind (G124 R11) — every
    surface counted, ids only, newest ``last_read`` kept per id."""
    counts: Counter[str] = Counter()
    last: dict[str, str] = {}
    for e in _events_in(range_, today):
        if e.kind != "read" or not isinstance(e.refs, dict):
            continue
        entity_id = str(e.refs.get("entity_id") or "").strip()
        if not entity_id:
            continue
        counts[entity_id] += 1
        last[entity_id] = max(last.get(entity_id, ""), e.ts)
    return [{"entity_id": eid, "reads": n, "last_read": last[eid]}
            for eid, n in counts.most_common(max(1, limit))]
```

At `:213` change `telemetry.FEEDBACK_KINDS` → `telemetry.NON_SPEND_KINDS` and extend the comment: `# R7 (G113) widened by G124 R12: reads carry no spend either.`

- [ ] **Step 5: `git_service.top_written_entities`** — constant beside `CONTRIBUTOR_LOG_WINDOW_MIN` (:122):

```python
# How far back `top_written_entities` walks (G124 R13). Same reason as the
# contributor window above: `git log --name-only` materialises every commit's
# file list before Python can stop, so an unbounded walk grows with every
# Sleep cycle. The response says how many commits were scanned so the UI can
# say "over the last N commits" instead of implying all-time.
TOP_ENTITIES_LOG_WINDOW = 2000
```
and the function after `get_contributor_commits`:

```python
async def top_written_entities(memory_path: Path, *, limit: int = 10) -> tuple[list[dict], int]:
    """Entity pages ranked by how many commits touched them (G124 R13).

    Engine-free: one ``git log --name-only`` over the last
    ``TOP_ENTITIES_LOG_WINDOW`` commits; every ``entities/*.md`` path counts
    once per commit. Returns ``(rows, commits_scanned)``; rows are
    ``{entity_id, commits, last_written}`` sorted by commits desc, then
    newest, then id. ``([], 0)`` for a non-git directory.
    """
    if not (memory_path / ".git").exists():
        return [], 0
    rec = "\x1e"
    try:
        out = await _run_git(
            memory_path, "log", f"--max-count={TOP_ENTITIES_LOG_WINDOW}",
            f"--format={rec}%ad", "--date=short", "--name-only",
        )
    except GitError:
        return [], 0
    counts: dict[str, int] = {}
    last: dict[str, str] = {}
    scanned = 0
    for record in out.split(rec):
        if not record.strip():
            continue
        scanned += 1
        date_str, _, tail = record.partition("\n")
        date_str = date_str.strip()
        for line in tail.splitlines():
            f = line.strip()
            if f.startswith("entities/") and f.endswith(".md"):
                entity_id = f[len("entities/"):-len(".md")].rsplit("/", 1)[-1]
                counts[entity_id] = counts.get(entity_id, 0) + 1
                if date_str > last.get(entity_id, ""):
                    last[entity_id] = date_str
    rows = [{"entity_id": eid, "commits": n, "last_written": last[eid]} for eid, n in counts.items()]
    # Two stable sorts: newest first, then commits desc — so ties on commit
    # count show the page that was written most recently first, then by id.
    rows.sort(key=lambda r: (r["last_written"], r["entity_id"]), reverse=True)
    rows.sort(key=lambda r: -r["commits"])
    return rows[: max(1, int(limit or 10))], scanned
```

- [ ] **Step 6: Schemas** — after `ContributorsResponse` (:239-243):

```python
class TopEntityWrite(CamelModel):
    entity_id: str
    commits: int = 0
    last_written: str = ""  # ISO date


class TopEntityRead(CamelModel):
    entity_id: str
    reads: int = 0
    last_read: str = ""  # ISO timestamp


class TopEntities(CamelModel):
    """Most-written (git, bounded by ``git_service.TOP_ENTITIES_LOG_WINDOW`` —
    ``commits_scanned`` says how far back) and most-read (the ids-only ``read``
    ledger kind) entity pages — G124's read/write stats, all engine-free."""

    written: list[TopEntityWrite] = []
    read: list[TopEntityRead] = []
    commits_scanned: int = 0
    range: str = "all"


class EntityReadRequest(CamelModel):
    surface: Literal["app", "mcp"] = "app"


class EntityReadResponse(CamelModel):
    recorded: bool
```
and, because it references `CalendarDay`, place THIS one directly after `ConsumptionCalendar` (:1592-1595) rather than beside the others:

```python
class ContributorCalendar(CamelModel):
    """`/consumption/calendar`'s shape for one `Cicada-Author` (G124 R14).
    ``days`` reuse ``CalendarDay`` with events/tokens/cost at zero so the app
    renders it with the same heatmap and no new cell type."""

    author: str
    days: list[CalendarDay] = []
    weeks: int = 53
```
`schemas.py:2` is `from typing import Optional` today — `Literal` is NOT imported. Change that line to `from typing import Literal, Optional`.

- [ ] **Step 7: Routers**

`api/routers/contributors.py` — imports gain `ContributorCalendar, TopEntities` and `consumption_stats, telemetry`; add `from datetime import date, datetime, timezone`; add after `get_contributor_commits`:

```python
def _utc_today() -> date:
    # The ledger's own clock — see api/routers/consumption.py::_utc_today.
    return datetime.now(timezone.utc).date()


@router.get("/contributors/calendar", response_model=ContributorCalendar)
async def get_contributor_calendar(
    request: Request,
    response: Response,
    author: str = Query(..., min_length=1, description="Model id, 'user', 'cicada', or 'unknown'"),
    weeks: int = Query(53, ge=1, le=106),
    settings: Settings = Depends(get_settings),
):
    """When this contributor wrote memory (G124 R14) — the GitHub-style
    calendar per model. Git only; the UTC date is part of the ETag because a
    rolling window moves at midnight with no commit to move ``git_head``."""
    today = _utc_today()
    etag = sync_service.etag_for(settings.memory_path, "git_head", extra=f"{author}:{weeks}:{today}")
    if (early := sync_service.conditional(request, response, etag)) is not None:
        return early
    days = await consumption_stats.contributor_calendar(
        settings.memory_path, author=author.strip(), weeks=weeks, today=today)
    return ContributorCalendar(author=author.strip(), days=[CalendarDay(**d) for d in days], weeks=weeks)


@router.get("/contributors/top-entities", response_model=TopEntities)
async def get_top_entities(
    request: Request,
    response: Response,
    limit: int = Query(10, ge=1, le=50),
    range_: str = Query("all", alias="range", pattern=r"^(all|month|\d{1,4}d)$"),
    settings: Settings = Depends(get_settings),
):
    """Most-written (git) and most-read (ledger) entity pages (G124).

    Two sources, one ETag: ``git_head`` for the writes, ``telemetry`` for the
    reads, the UTC date for the rolling range. Counts only — no cost, no
    tokens — by the 2026-09-03 ruling on the G124 row.
    """
    today = _utc_today()
    etag = sync_service.etag_for(
        settings.memory_path, "git_head", "telemetry", extra=f"{limit}:{range_}:{today}")
    if (early := sync_service.conditional(request, response, etag)) is not None:
        return early
    written, scanned = await git_service.top_written_entities(settings.memory_path, limit=limit)
    read = consumption_stats.top_read_entities(range_=range_, today=today, limit=limit)
    return TopEntities(
        written=[TopEntityWrite(**r) for r in written],
        read=[TopEntityRead(**r) for r in read],
        commits_scanned=scanned, range=range_,
    )
```
(also import `CalendarDay, TopEntityRead, TopEntityWrite` from schemas.)

`api/routers/entities.py` — after `get_entity` (:55-90):

```python
@router.post("/entities/{entity_id}/read", response_model=EntityReadResponse)
async def record_entity_read(
    entity_id: str,
    body: EntityReadRequest,
    settings: Settings = Depends(get_settings),
):
    """The app opened this entity's card (G124 R11) — one ids-only ``read``
    ledger event. 404 for a page that does not exist so a stray id can never
    seed the most-read list. Nothing is written to the bank; nothing here can
    fail the card open (``telemetry.record`` never raises)."""
    if not (settings.memory_path / "entities" / f"{entity_id}.md").is_file():
        raise HTTPException(status_code=404, detail="Entity not found")
    telemetry.record_read(entity_id, surface=body.surface, bank=telemetry.bank_name(settings))
    return EntityReadResponse(recorded=telemetry.enabled())
```
(import `telemetry` from `api.services` and the two schemas; check `HTTPException` is already imported there.)

- [ ] **Step 8: `mcp/server.py` — the minimal hook.** In `handle_recall`, immediately after the `suggested = [...]` assignment (:863-867) and BEFORE the `if not suggested and hub_member_ids:` line, add:

```python
    from api.services import telemetry  # G124 R11: a suggested page is a read (ids only)
    for _eid in suggested:
        telemetry.record_read(_eid, surface="mcp-recall", bank=memory_path.name)
```
In `handle_recall_detail`, replace the single line `return path.read_text(encoding="utf-8")` (:1084) with:

```python
            from api.services import telemetry  # G124 R11: ids only, never the page text
            telemetry.record_read(cid, surface="mcp", bank=memory_path.name)
            return path.read_text(encoding="utf-8")
```
Nothing else in that file changes.

- [ ] **Step 9: Run**

```
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g124 && api/.venv/bin/python -m pytest api/tests/test_contributor_calendar.py api/tests/test_entity_read_events.py api/tests/test_consumption_stats.py api/tests/test_consumption_api.py api/tests/test_contributors.py api/tests/test_contributor_commits.py api/tests/test_telemetry.py api/tests/test_feedback_ledger.py api/tests/test_mcp_recall_fusion.py api/tests/test_mcp_sources_tool.py -q -p no:cacheprovider 2>&1 | tail -5
```
Then the full suite: `api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider 2>&1 | tail -15` — only the baseline failures.

- [ ] **Step 10: Commit**

```
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g124 && git add -- api/services/telemetry.py api/services/consumption_stats.py api/services/git_service.py api/routers/contributors.py api/routers/entities.py api/models/schemas.py mcp/server.py api/tests/test_contributor_calendar.py api/tests/test_entity_read_events.py && git commit -q -m "feat(api): contributors calendar, top-entities and the ids-only read ledger kind (G124)

GET /contributors/calendar?author= (memory writes per UTC day per
Cicada-Author, R14), GET /contributors/top-entities (git-bounded most-written
+ ledger most-read, R13), POST /entities/{id}/read and telemetry.record_read
(entity id + surface enum, never text, R11) called from cicada_recall /
cicada_recall_detail; read joins the non-spend kinds (R12).

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj"
```

---

### Task 3: App — the Sources tab, the card grid, the per-source pages

**Files:**
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sidebar/SidebarView.swift:12-47`
- Modify: `app/CicadaApp/Sources/CicadaApp/ContentView.swift:167-172`
- Modify: `app/CicadaApp/Sources/CicadaApp/Theme/Copy.swift:20`, `:110`, `:117-119`
- Create: `app/CicadaApp/Sources/CicadaApp/Models/SourceOverview.swift`
- Modify: `app/CicadaApp/Sources/CicadaApp/Sync/Snapshot.swift:11-22`, `Store.swift:24-38, :192-207, :243-262, :480-491`, `VersionVector.swift:7-24`, `SyncAPI.swift:40-72`
- Modify: `app/CicadaApp/Sources/CicadaApp/Services/APIClient.swift:198-224` (`MediaFeedItem`), `:1170-1181` (`fetchRecentConversations`), add `fetchSourcesOverview(etag:)` beside `fetchOrigins(etag:)` (:1917-1923)
- Modify: `app/CicadaApp/Sources/CicadaApp/ViewModels/ConversationsViewModel.swift:47-59`
- Move (`mkdir -p Views/Sources` first, then `git mv`): `Views/Activity/ConversationPopover.swift` → `Views/Sources/ConversationPopover.swift`; extract `ConversationRow` (`Views/Activity/ConversationsSection.swift:96-261` — the doc comment starts at :96, `struct ConversationRow` at :100, the file ends with it; the struct is self-contained, nothing file-private) into `Views/Sources/ConversationRow.swift`
- Delete: `Views/Activity/ActivityView.swift`, `Views/Activity/ConversationsSection.swift` (after the extraction), `Views/Capture/OriginPill.swift` (only if `grep -rn "OriginPill(" app/CicadaApp/Sources` shows no other caller)
- Modify: `Views/Feed/FeedView.swift:231` — `private struct FeedRow` → `struct FeedRow`
- Modify: `Views/Capture/OriginIconography.swift:20-102` — `cursor`, `codex`, `claude-desktop` cases
- Create: `Views/Sources/SourcesPageView.swift`, `SourceCardGrid.swift`, `SourceDetailView.swift`, `HarnessConversationsView.swift`, `ChannelSourceView.swift`
- Tests: create `Tests/CicadaAppTests/SourcesPageTests.swift`; modify `SidebarTabTests.swift:10,21,29-30`, `CopyConstantsTests.swift:33-41`, `ConversationsTests.swift` (`:111`, `:123` new signature; delete `testActivitySectionRoundTripsTheConversationsCase` at `:366-371` — `ActivitySection` goes with `ActivityView.swift`), `StoreTests.swift:192-215` (`FakeSyncAPI`); delete `ActivitySectionTests.swift`

**Interfaces:**
- `AppTab.sources` (raw `"Sources"`, icon `"tray.2"`); `AppTab.restored(from: "Activity" | "Contributors" | "Usage") == .sources`.
- `SourceOverview: Codable, Identifiable, Hashable` (decode-tolerant); `SourceKind` enum with `.unknown`; `static func gridOrder(_:) -> [SourceOverview]`; `var countLines: [String]`.
- `SyncDomain.sourcesOverview`; `Store.sourcesOverview: Snapshot<[SourceOverview]>`; `SyncAPI.fetchSourcesOverview(etag:)`.
- `SyncAPI.fetchRecentConversations(limit: Int, harness: String?, origin: String?)`; `ConversationsViewModel.load(limit: Int = 20, harness: String? = nil, origin: String? = nil)`.
- `ConversationFilter.apply(_ rows: [ConversationSummary], query: String) -> [ConversationSummary]` (pure).
- `SourceItemsGrouping.folders(_ items: [MediaFeedItem]) -> [(folder: String, count: Int)]` (pure).

- [ ] **Step 1: Write the failing tests**

```swift
// Tests/CicadaAppTests/SourcesPageTests.swift
import XCTest
@testable import CicadaApp

/// G124 — the Sources page: wire model tolerance, grid order, the count lines
/// a card shows per kind, the harness title filter, and folder grouping.
final class SourcesPageTests: XCTestCase {

    func testSourceOverviewDecodesTheCamelCaseWireAndToleratesMissing() throws {
        let json = """
        {"sources":[{"id":"harness:claude-code","label":"Claude Code","kind":"harness","mark":"claude-code",
                     "conversations":12,"episodes":40,"entities":31,"items":0,
                     "lastActivityAt":"2026-09-01T10:00:00+00:00","connected":true,"lastError":null,
                     "actions":[],"channelId":null,"origins":[],"harness":"claude-code"},
                    {"id":"safari-bookmarks","label":"Safari bookmarks","kind":"browser","mark":"safari-bookmark"},
                    {"id":"origin:mystery","label":"mystery","kind":"space-elevator","mark":"mystery"}]}
        """.data(using: .utf8)!
        let rows = try JSONDecoder().decode(SourceOverviewResponse.self, from: json).sources
        XCTAssertEqual(rows.count, 3)
        XCTAssertEqual(rows[0].kind, .harness); XCTAssertEqual(rows[0].conversations, 12); XCTAssertTrue(rows[0].connected)
        XCTAssertEqual(rows[1].kind, .browser); XCTAssertEqual(rows[1].items, 0); XCTAssertFalse(rows[1].connected)
        XCTAssertNil(rows[1].lastActivityAt); XCTAssertEqual(rows[1].actions, [])
        XCTAssertEqual(rows[2].kind, .unknown, "an unknown kind never drops the whole grid")
    }

    func testGridOrderIsKindThenRecencyThenId() {
        let a = SourceOverview(id: "rss", label: "RSS", kind: .feed, lastActivityAt: "2026-09-02T00:00:00+00:00")
        let b = SourceOverview(id: "harness:cursor", label: "Cursor", kind: .harness, lastActivityAt: "2026-08-01T00:00:00+00:00")
        let c = SourceOverview(id: "harness:claude-code", label: "Claude Code", kind: .harness, lastActivityAt: "2026-09-01T00:00:00+00:00")
        let d = SourceOverview(id: "origin:x", label: "x", kind: .unknown)
        XCTAssertEqual(SourceOverview.gridOrder([a, b, c, d]).map(\.id), ["harness:claude-code", "harness:cursor", "rss", "origin:x"])
    }

    func testCountLinesShowOnlyWhatAppliesToTheKind() {
        let harness = SourceOverview(id: "harness:claude-code", label: "Claude Code", kind: .harness,
                                     conversations: 3, episodes: 9, entities: 5)
        XCTAssertEqual(harness.countLines, ["3 conversations", "5 entities"])
        let browser = SourceOverview(id: "safari-bookmarks", label: "Safari", kind: .browser, entities: 2, items: 412)
        XCTAssertEqual(browser.countLines, ["412 items", "2 entities"])
        let one = SourceOverview(id: "telegram", label: "Telegram", kind: .messaging, episodes: 1, entities: 1)
        XCTAssertEqual(one.countLines, ["1 capture", "1 entity"])
        let empty = SourceOverview(id: "rss", label: "RSS", kind: .feed)
        XCTAssertEqual(empty.countLines, ["Nothing yet"])
        // R1: RSS episodes carry no origin today, so the row's only number is
        // the subscription count the channel reports — never call it "items".
        let rss = SourceOverview(id: "rss", label: "RSS", kind: .feed, items: 3)
        XCTAssertEqual(rss.countLines, ["3 subscriptions"])
        let calendar = SourceOverview(id: "calendar", label: "Calendars", kind: .feed, episodes: 7, items: 1, entities: 2)
        XCTAssertEqual(calendar.countLines, ["7 captures", "2 entities"], "captures win when the origin IS stamped")
    }

    func testTitleFilterIsCaseInsensitiveAndKeepsOrder() {
        let rows = [
            ConversationSummary(conversationId: "a", title: "Index choice"),
            ConversationSummary(conversationId: "b", title: "Graph physics"),
            ConversationSummary(conversationId: "c", title: ""),  // "Untitled conversation"
        ]
        XCTAssertEqual(ConversationFilter.apply(rows, query: "").map(\.id), ["a", "b", "c"])
        XCTAssertEqual(ConversationFilter.apply(rows, query: "  GRAPH ").map(\.id), ["b"])
        XCTAssertEqual(ConversationFilter.apply(rows, query: "untitled").map(\.id), ["c"])
    }

    func testFolderGroupingCountsAndOrdersByCountThenName() throws {
        func item(_ id: String, folder: String?) throws -> MediaFeedItem {
            let f = folder.map { "\"folder\":\"\($0)\"," } ?? ""
            return try JSONDecoder().decode(MediaFeedItem.self, from:
                #"{"mediaEntityId":"\#(id)","url":"https://example.com/\#(id)","title":"t","mediaType":"url","savedAt":"2026-09-01T00:00:00Z","tags":[],"status":"active","relatedCount":0,"relevance":0,\#(f)"origin":"safari-bookmark"}"#.data(using: .utf8)!)
        }
        let items = [try item("1", folder: "Papers"), try item("2", folder: "Papers"), try item("3", folder: "Alpha"), try item("4", folder: nil)]
        XCTAssertEqual(items[0].origin, "safari-bookmark"); XCTAssertNil(items[3].folder)
        let groups = SourceItemsGrouping.folders(items)
        XCTAssertEqual(groups.map(\.folder), ["Papers", "Alpha", "No folder"])
        XCTAssertEqual(groups.map(\.count), [2, 1, 1])
    }
}
```
`SidebarTabTests.swift` edits: `:10` `allCases` ends in `.sources`; `:21` `AppTab.sources.rawValue == "Sources"`; `:29-30` the `Contributors`/`Usage` expectations become `.sources` and gain `XCTAssertEqual(AppTab.restored(from: "Activity"), .sources)`. `CopyConstantsTests.swift:33-41`: the `pairs` array has no Activity entry today — ADD `(Copy.sources, Copy.sourcesSubtitle)` so the ≤60-chars / no-title-repeat rule covers the new page. `ConversationsTests.swift`: `:111` and `:123` (`fetchRecentConversations(limit: 20)`) gain `harness: nil, origin: nil`; delete `testActivitySectionRoundTripsTheConversationsCase` (`:366-371`) — it tests `ActivitySection`, which is deleted with `ActivityView.swift`. Delete `ActivitySectionTests.swift` (`git rm`) — it is the only other reference to `Copy.activity`/`Copy.activitySubtitle`.

- [ ] **Step 2: Build to confirm failure** — `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g124/app/CicadaApp && swift build --build-tests 2>&1 | grep -c "error:"` — expected non-zero.

- [ ] **Step 3: Tab, copy, content**

`SidebarView.swift:12-47`:
```swift
/// The six primary views. Raw values are this tab's **stable identity** —
/// the persisted selection (`cicada.selectedTab`) and the ⌘-slot order in
/// `allCases` — so a surviving tab's raw value must never move, even when its
/// label changes.
///
/// G68 retired five tabs: Capture merged into Feed, Contributors + Usage
/// merged into Activity, and Connections + Connect became Settings tabs
/// (⌘,). G124 then replaced Activity with Sources. All six retired raw values
/// still sit in some user's defaults, so decode through `restored(from:)` —
/// never `AppTab(rawValue:)!`.
enum AppTab: String, CaseIterable {
    case graph = "Graph"
    case clusters = "Clusters"
    case feed = "Feed"
    case sleep = "Sleep"
    case inbox = "Inbox"
    case sources = "Sources"

    static func restored(from raw: String?) -> AppTab {
        guard let raw, !raw.isEmpty else { return .graph }
        if let tab = AppTab(rawValue: raw) { return tab }
        switch raw {
        case "Capture": return .feed
        case "Activity", "Contributors", "Usage": return .sources   // G124: Activity → Sources
        case "Connections", "Connect": return .graph   // now Settings tabs (⌘,)
        default: return .graph
        }
    }

    var icon: String {
        switch self {
        case .graph: "point.3.connected.trianglepath.dotted"
        case .clusters: "circle.grid.2x2"
        case .feed: "photo.stack"
        case .sleep: "moon.fill"
        case .inbox: "tray.full"
        case .sources: "tray.2"
        }
    }
```
`Copy.swift`: `:20` → `static let sources = "Sources"` (delete `activity`); `:110` → `static let sourcesSubtitle = "Where your memory comes from, and who wrote it."` (47 chars, no "sources", no "page"); delete `originsLabel` (:117-119) after confirming `grep -rn "originsLabel" app/CicadaApp` has no other caller. `ContentView.swift:167-172` → `case .sources: SourcesPageView { entityId in withAnimation(.spring(duration: 0.25)) { selectedTab = .graph }; graphVM.selectEntity(id: entityId) }` (keep the existing comment, reworded for a source page's entity chip).

- [ ] **Step 4: Wire model** — `Models/SourceOverview.swift`:

```swift
import Foundation

/// The kinds `api/services/source_overview.KIND_ORDER` declares, plus a
/// fallback so an unknown kind from a newer backend never drops the grid.
enum SourceKind: String, Codable, CaseIterable {
    case harness, browser, social, feed, messaging, `import`, unknown

    /// Grid order = the backend's `KIND_ORDER`; `unknown` sorts last.
    static let order: [SourceKind] = [.harness, .browser, .social, .feed, .messaging, .import, .unknown]
}

/// Mirror of `api/models/schemas.py::SourceOverview` (G124). Every field but
/// `id` is optional-with-a-default so an older backend — or a row with no
/// state at all — still yields a usable card.
struct SourceOverview: Codable, Identifiable, Hashable {
    let id: String
    let label: String
    let kind: SourceKind
    let mark: String
    let conversations: Int
    let episodes: Int
    let entities: Int
    let items: Int
    let lastActivityAt: String?
    let connected: Bool
    let lastError: String?
    let actions: [String]
    let channelId: String?
    let origins: [String]
    let harness: String?

    init(id: String, label: String, kind: SourceKind, mark: String = "", conversations: Int = 0,
         episodes: Int = 0, entities: Int = 0, items: Int = 0, lastActivityAt: String? = nil,
         connected: Bool = false, lastError: String? = nil, actions: [String] = [],
         channelId: String? = nil, origins: [String] = [], harness: String? = nil) {
        self.id = id; self.label = label; self.kind = kind; self.mark = mark
        self.conversations = conversations; self.episodes = episodes; self.entities = entities
        self.items = items; self.lastActivityAt = lastActivityAt; self.connected = connected
        self.lastError = lastError; self.actions = actions; self.channelId = channelId
        self.origins = origins; self.harness = harness
    }

    enum CodingKeys: String, CodingKey {
        case id, label, kind, mark, conversations, episodes, entities, items, lastActivityAt
        case connected, lastError, actions, channelId, origins, harness
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        label = try c.decodeIfPresent(String.self, forKey: .label) ?? id
        kind = SourceKind(rawValue: (try c.decodeIfPresent(String.self, forKey: .kind)) ?? "") ?? .unknown
        mark = try c.decodeIfPresent(String.self, forKey: .mark) ?? id
        conversations = try c.decodeIfPresent(Int.self, forKey: .conversations) ?? 0
        episodes = try c.decodeIfPresent(Int.self, forKey: .episodes) ?? 0
        entities = try c.decodeIfPresent(Int.self, forKey: .entities) ?? 0
        items = try c.decodeIfPresent(Int.self, forKey: .items) ?? 0
        lastActivityAt = try c.decodeIfPresent(String.self, forKey: .lastActivityAt)
        connected = try c.decodeIfPresent(Bool.self, forKey: .connected) ?? false
        lastError = try c.decodeIfPresent(String.self, forKey: .lastError)
        actions = try c.decodeIfPresent([String].self, forKey: .actions) ?? []
        channelId = try c.decodeIfPresent(String.self, forKey: .channelId)
        origins = try c.decodeIfPresent([String].self, forKey: .origins) ?? []
        harness = try c.decodeIfPresent(String.self, forKey: .harness)
    }

    /// `lastActivityAt` parsed for sorting — the same three shapes
    /// `SourceChannel.lastSyncDate` accepts.
    var lastActivityDate: Date? {
        guard let lastActivityAt, !lastActivityAt.isEmpty else { return nil }
        let withFraction = ISO8601DateFormatter()
        withFraction.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let d = withFraction.date(from: lastActivityAt) { return d }
        let plain = ISO8601DateFormatter()
        plain.formatOptions = [.withInternetDateTime]
        if let d = plain.date(from: lastActivityAt) { return d }
        let dayOnly = DateFormatter()
        dayOnly.dateFormat = "yyyy-MM-dd"
        dayOnly.timeZone = TimeZone(identifier: "UTC")
        return dayOnly.date(from: lastActivityAt)
    }

    /// The grid's order, pure and unit-tested: kind (the backend's
    /// `KIND_ORDER`), newest activity first, id for stability. Re-applied on
    /// the client because a cached snapshot from an older backend may not be
    /// sorted.
    static func gridOrder(_ rows: [SourceOverview]) -> [SourceOverview] {
        rows.sorted { a, b in
            let ka = SourceKind.order.firstIndex(of: a.kind) ?? .max
            let kb = SourceKind.order.firstIndex(of: b.kind) ?? .max
            if ka != kb { return ka < kb }
            switch (a.lastActivityDate, b.lastActivityDate) {
            case let (l?, r?) where l != r: return l > r
            case (_?, nil): return true
            case (nil, _?): return false
            default: return a.id < b.id
            }
        }
    }

    /// What a card counts, by kind: a harness counts conversations, a browser
    /// or social source counts items, a feed counts captures — or, when its
    /// episodes carry no origin yet (RSS, R1), the subscriptions the channel
    /// reports (`items` IS the subscription count for `rss`/`calendar`, see
    /// `channel_registry._subscription_channel`) — everything else counts
    /// captures; every kind shows the entities it credited. "Nothing yet" when
    /// all are zero — a row of zeroes reads as a broken card.
    var countLines: [String] {
        var lines: [String] = []
        switch kind {
        case .harness where conversations > 0:
            lines.append(Self.plural(conversations, "conversation"))
        case .browser, .social:
            if items > 0 { lines.append(Self.plural(items, "item")) }
        case .feed:
            if episodes > 0 { lines.append(Self.plural(episodes, "capture")) }
            else if items > 0 { lines.append(Self.plural(items, "subscription")) }
        default:
            if episodes > 0 { lines.append(Self.plural(episodes, "capture")) }
        }
        if entities > 0 { lines.append(Self.plural(entities, "entity", "entities")) }
        return lines.isEmpty ? ["Nothing yet"] : lines
    }

    private static func plural(_ n: Int, _ one: String, _ many: String? = nil) -> String {
        "\(UsageFormat.count(n)) \(n == 1 ? one : (many ?? one + "s"))"
    }
}

struct SourceOverviewResponse: Codable {
    let sources: [SourceOverview]
    init(from decoder: Decoder) throws {
        let c = try? decoder.container(keyedBy: CodingKeys.self)
        sources = (try? c?.decodeIfPresent([SourceOverview].self, forKey: .sources)) ?? []
    }
    enum CodingKeys: String, CodingKey { case sources }
}

/// Title filter for a harness's conversation list — the owner's words:
/// "search is secondary; the view of the conversations that exist is the
/// point", so this is a substring match over `displayTitle`, nothing more.
enum ConversationFilter {
    static func apply(_ rows: [ConversationSummary], query: String) -> [ConversationSummary] {
        let q = query.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard !q.isEmpty else { return rows }
        return rows.filter { $0.displayTitle.lowercased().contains(q) }
    }
}

/// Folder / board / device counts for a channel source's items (G124): the
/// media page's `folder:` is a bookmark folder path, a Pinterest board, a
/// TikTok section or an iCloud device name depending on the importer.
enum SourceItemsGrouping {
    static let noFolder = "No folder"
    static func folders(_ items: [MediaFeedItem]) -> [(folder: String, count: Int)] {
        var counts: [String: Int] = [:]
        for item in items {
            let key = (item.folder?.trimmingCharacters(in: .whitespaces)).flatMap { $0.isEmpty ? nil : $0 } ?? noFolder
            counts[key, default: 0] += 1
        }
        return counts.map { (folder: $0.key, count: $0.value) }
            .sorted { $0.count != $1.count ? $0.count > $1.count : $0.folder < $1.folder }
    }
}
```
`MediaFeedItem` (`APIClient.swift:198-224`): add `let origin: String?` and `let folder: String?` after `about`, with the doc comment `/// G124 R6 — the media page's own origin / folder (bookmark folder, board, device). Optional: an older backend or a pre-origin page has neither.` — the struct's decoder is synthesized (all optionals decode as nil when absent), so no `init(from:)` change; if the struct has an explicit `init(from:)`, add the two `decodeIfPresent` lines.

- [ ] **Step 5: Sync plumbing**

- `Snapshot.swift:11-22`: add `case sourcesOverview` with `/// G124 — one card per memory source. Per-bank; rides the episodes/entities/sources components (R7).`
- `Store.swift`: property `var sourcesOverview = Snapshot<[SourceOverview]>()` after `origins` (:33); `await take(.sourcesOverview, \.sourcesOverview)` after the `.origins` take (:195); `case .sourcesOverview: await refreshOne(domain, \.sourcesOverview) { [api] e in try await api.fetchSourcesOverview(etag: e) }` after `.origins` (:251); `sourcesOverview.isRefreshing = false` in the reset block (:488).
- `VersionVector.swift:8-9,12`: add `.sourcesOverview` to the `"entities"`, `"episodes"` and `"sources"` sets.
- `SyncAPI.swift`: after `fetchOrigins` add `func fetchSourcesOverview(etag: String?) async throws -> Conditional<[SourceOverview]>`; change `:67` to `func fetchRecentConversations(limit: Int, harness: String?, origin: String?) async throws -> [ConversationSummary]` with the doc line `/// G124 R5: `harness`/`origin` filter server-side, before the cap.`
- `APIClient.swift`: `:1170` becomes `func fetchRecentConversations(limit: Int = 20, harness: String? = nil, origin: String? = nil)`. Build the query exactly the way `fetchContributorCommits` (:1150-1152) encodes `author`: `var allowed = CharacterSet.urlQueryAllowed; allowed.remove(charactersIn: "&+=?/#")`, then append `"&harness=\(h)"` / `"&origin=\(o)"` only for a non-nil value percent-encoded with that set (`harness: "unknown"` travels literally — the backend matches it to an empty harness, R5). Keep the existing 404 → `[]` degrade. Beside `fetchOrigins(etag:)` (:1917) add:

```swift
    func fetchSourcesOverview(etag: String?) async throws -> Conditional<[SourceOverview]> {
        do {
            let c: Conditional<SourceOverviewResponse> = try await getConditional("/sources/overview", etag: etag)
            return c.map(\.sources)
        } catch APIError.httpError(404, _) {
            return .unavailable(etag: etag)   // backend predates G124 — keep what we have
        }
    }
```
- `StoreTests.swift:192-215` (`FakeSyncAPI`): `fetchRecentConversations(limit:harness:origin:)` filters `recentConversations` by `harness`/`origin` when non-nil (`harness == "unknown"` matches `""`); add `var sourcesOverview: [SourceOverview] = []` and `func fetchSourcesOverview(etag:) { try answer(.sourcesOverview, fallback: sourcesOverview) }`.
- `ConversationsViewModel.swift:47-59`: `func load(limit: Int = 20, harness: String? = nil, origin: String? = nil) async` passing both through.

- [ ] **Step 6: Views** — create `Views/Sources/`:

`SourcesPageView.swift`:
```swift
import SwiftUI

/// Where the page is: the grid, or one source's page. `@State`, not
/// `@AppStorage` — a relaunch lands on the grid (R15).
enum SourcesRoute: Hashable {
    case grid
    case detail(SourceOverview)
}

/// The Sources page (G124) — Activity's successor. Opens on *where memory
/// comes from*: a grid of clickable source cards, then Contributors, then
/// (behind the persisted Advanced toggle, R8) counts-only stats. No prices,
/// no tokens anywhere on this page — the 2026-09-03 ruling on the G124 row.
/// Every value is a projection over `Store` snapshots; the only on-demand
/// fetches are the per-source drill-downs.
struct SourcesPageView: View {
    /// Entity chip → the app's existing entity navigation (select in the
    /// graph, switch to it), threaded from `ContentView` like Ask citations.
    var onSelectEntity: ((String) -> Void)?

    @Environment(Store.self) private var store
    @Environment(UsageViewModel.self) private var usageVM
    @State private var route: SourcesRoute = .grid

    private var rows: [SourceOverview] { SourceOverview.gridOrder(store.sourcesOverview.value ?? []) }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            switch route {
            case .grid:
                PageHeader(title: Copy.sources, subtitle: Copy.sourcesSubtitle) {
                    Toggle("Advanced", isOn: Binding(
                        get: { usageVM.mode == .advanced },
                        set: { usageVM.mode = $0 ? .advanced : .minimal }
                    ))
                    .toggleStyle(.switch).controlSize(.small)
                    .accessibilityLabel("Show advanced read and write statistics")
                }
                ScrollView {
                    VStack(alignment: .leading, spacing: CicadaTheme.spacingXL) {
                        SourceCardGrid(rows: rows, hasLoaded: store.sourcesOverview.value != nil,
                                       isRefreshing: store.sourcesOverview.isRefreshing) { route = .detail($0) }
                        sectionHeader("Contributors")
                        ContributorsSection()
                        if usageVM.mode == .advanced {
                            sectionHeader("Advanced")
                            AdvancedStatsView(onSelectEntity: onSelectEntity)
                        }
                    }
                    .padding(.bottom, CicadaTheme.spacingXL)
                }
            case .detail(let source):
                SourceDetailView(source: source, onBack: { route = .grid }, onSelectEntity: onSelectEntity)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(CicadaTheme.background)
    }

    private func sectionHeader(_ title: String) -> some View {
        Text(title)
            .font(CicadaTheme.headingFont)
            .foregroundStyle(CicadaTheme.textPrimary)
            .padding(.horizontal, CicadaTheme.spacingXL)
    }
}
```
(`AdvancedStatsView` is created in Task 4; in THIS task create it as a stub `struct AdvancedStatsView: View { var onSelectEntity: ((String) -> Void)?; var body: some View { EmptyView() } }` in `Views/Sources/AdvancedStatsView.swift` so the branch builds; Task 4 fills it.)

`SourceCardGrid.swift`:
```swift
import SwiftUI

/// The grid of source cards (G124 — "in a grid, no horizontal scroll").
/// Never-loaded → loading; loaded-but-empty → the one call to action (R2);
/// otherwise adaptive columns.
struct SourceCardGrid: View {
    let rows: [SourceOverview]
    let hasLoaded: Bool
    let isRefreshing: Bool
    let onOpen: (SourceOverview) -> Void

    private let columns = [GridItem(.adaptive(minimum: 220, maximum: 320), spacing: CicadaTheme.spacingMD)]

    var body: some View {
        Group {
            if !hasLoaded {
                HStack(spacing: CicadaTheme.spacingSM) {
                    ProgressView().controlSize(.small)
                    Text("Reading your sources…").font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textTertiary)
                }
                .frame(maxWidth: .infinity, alignment: .center)
            } else if rows.isEmpty {
                Text("Nothing has fed this memory yet. Add a source from the Feed's + button.")
                    .font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textTertiary)
            } else {
                LazyVGrid(columns: columns, alignment: .leading, spacing: CicadaTheme.spacingMD) {
                    ForEach(rows) { row in
                        Button { onOpen(row) } label: { SourceCard(source: row) }
                            .buttonStyle(.cicadaPlain)
                            .accessibilityLabel("\(row.label), \(row.countLines.joined(separator: ", "))")
                    }
                }
            }
        }
        .padding(.horizontal, CicadaTheme.spacingXL)
    }
}

/// One card: mark, label, the counts that apply, last activity, state.
struct SourceCard: View {
    let source: SourceOverview

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack(spacing: CicadaTheme.spacingSM) {
                Image(systemName: OriginIconography.symbol(for: source.mark))
                    .font(.system(size: 14, weight: .medium))
                    .foregroundStyle(OriginIconography.color(for: source.mark))
                    .frame(width: 24, height: 24)
                    .background(OriginIconography.color(for: source.mark).opacity(0.12))
                    .clipShape(RoundedRectangle(cornerRadius: 6))
                Text(source.label).font(CicadaTheme.headingFont).foregroundStyle(CicadaTheme.textPrimary).lineLimit(1)
                Spacer()
                Circle().fill(source.connected ? CicadaTheme.success : CicadaTheme.textTertiary.opacity(0.4))
                    .frame(width: 7, height: 7)
                    .help(source.connected ? "Connected" : "Not connected")
            }
            ForEach(source.countLines, id: \.self) { line in
                Text(line).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
            }
            if let relative = relativeLastActivity {
                Text("Last \(relative)").font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
            }
            if let error = source.lastError, !error.isEmpty {
                Text("Needs attention").font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.danger).help(error)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(CicadaTheme.spacingMD)
        .glassCard()
        .contentShape(Rectangle())
    }

    private var relativeLastActivity: String? {
        guard let date = source.lastActivityDate else { return nil }
        let fmt = RelativeDateTimeFormatter(); fmt.unitsStyle = .abbreviated
        return fmt.localizedString(for: date, relativeTo: .now)
    }
}
```

`SourceDetailView.swift`:
```swift
import SwiftUI

/// One source's page (G124). A harness shows its conversations; every other
/// kind shows its channel state, folder counts and items. Back is a chevron
/// and ⌘[ (R15) — the same key the entity card uses on the Graph tab, which
/// is never mounted at the same time as this view.
struct SourceDetailView: View {
    let source: SourceOverview
    let onBack: () -> Void
    var onSelectEntity: ((String) -> Void)?

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            PageHeader(title: source.label, subtitle: source.countLines.joined(separator: " · ")) {
                Button(action: onBack) {
                    Label("Sources", systemImage: "chevron.left").labelStyle(.titleAndIcon)
                }
                .buttonStyle(.cicadaGlass(cornerRadius: CicadaTheme.cornerRadiusSmall))
                .keyboardShortcut("[", modifiers: .command)
                .help("Back to all sources (⌘[)")
                .accessibilityLabel("Back to all sources")
            }
            switch source.kind {
            case .harness:
                HarnessConversationsView(source: source, onSelectEntity: onSelectEntity)
            default:
                ChannelSourceView(source: source)
            }
        }
    }
}
```

`HarnessConversationsView.swift` (the body of the old `ConversationsSection`, filtered and with a title field):
```swift
import SwiftUI

/// A harness's conversations (G124 §2): title, date, mark, episodes/entities,
/// Resume when the backend says `resumable`, a title filter. Fetched on
/// demand through `/conversations/recent?harness=` (R5) — no Store domain,
/// like the contributor commit drill-down. Resume goes through the existing
/// endpoint: transcripts are never read (G48 — `isfile()` only).
struct HarnessConversationsView: View {
    let source: SourceOverview
    var onSelectEntity: ((String) -> Void)?

    @State private var viewModel = ConversationsViewModel()
    @State private var loadedOnce = false
    @State private var query = ""
    @Environment(Store.self) private var store

    private var visible: [ConversationSummary] { ConversationFilter.apply(viewModel.conversations, query: query) }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            TextField("Filter by title", text: $query)
                .textFieldStyle(.roundedBorder)
                .frame(maxWidth: 320)
                .accessibilityLabel("Filter conversations by title")
            if let err = viewModel.errorMessage {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                    Text(err).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.danger)
                    Button("Retry") { Task { await load() } }.buttonStyle(.bordered)
                }
            } else if !viewModel.hasLoaded {
                HStack(spacing: CicadaTheme.spacingSM) {
                    ProgressView().controlSize(.small)
                    Text("Loading conversations…").font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textTertiary)
                }
            } else if visible.isEmpty {
                Text(query.isEmpty ? "No conversations from this source yet." : "No titles match “\(query)”.")
                    .font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textTertiary)
            } else {
                ScrollView {
                    VStack(spacing: CicadaTheme.spacingSM) {
                        ForEach(visible) { conversation in
                            ConversationRow(
                                conversation: conversation,
                                onResume: { Task { await act(await viewModel.resume(conversation.id)) } },
                                onCopy: { Task { await act(await viewModel.copyCommand(for: conversation.id)) } },
                                onSelectEntity: onSelectEntity
                            )
                        }
                    }
                }
            }
            Spacer(minLength: 0)
        }
        .padding(.horizontal, CicadaTheme.spacingXL)
        .task {
            guard !loadedOnce else { return }
            loadedOnce = true
            await load()
        }
    }

    private func load() async {
        // Chat exports are harness-kind rows keyed by origin; MCP harnesses by
        // harness. The overview tells us which filter it wants.
        if let harness = source.harness {
            await viewModel.load(limit: 200, harness: harness)
        } else {
            await viewModel.load(limit: 200, origin: source.origins.first)
        }
    }

    /// Same outcomes as the old ConversationsSection: a clipboard fallback is
    /// never silent; a 409 reloads so the row drops its Resume affordance.
    private func act(_ outcome: ResumeOutcome) async {
        switch outcome {
        case .launched(let app): store.toast = "Reopening in \(app)…"
        case .copied(let command): store.toast = "Copied “\(command)” — paste it into any terminal"
        case .gone:
            store.toast = "That conversation's transcript is gone — nothing to resume"
            await load()
        case .failed(let message): store.toast = message
        }
    }
}
```

`ChannelSourceView.swift`:
```swift
import SwiftUI

/// A browser / social / feed / messaging / import source's page (G124): its
/// channel state (joined from the `channels` snapshot by `channelId`),
/// Sync/Poll now where the channel supports it (the same actions the Feed's
/// connected-channel rows run — browser files are read HERE and posted as
/// bytes, R1 of the Safari import), folder/device counts, and the Feed's
/// items filtered to this source's origins (R6).
struct ChannelSourceView: View {
    let source: SourceOverview

    @Environment(Store.self) private var store
    @State private var busy = false
    @State private var feedback: ChannelFeedback?

    private var channel: SourceChannel? {
        guard let id = source.channelId else { return nil }
        return (store.channels.value ?? []).first { $0.id == id }
    }
    /// The Feed's items that belong to this source (R6). A row with origins
    /// matches pages stamped with one of them; a row with NONE (`files` —
    /// R1: `POST /sources/save`, `cicada_save_url` and the RSS poll stamp no
    /// origin) owns the pages that carry no `origin:` at all, so a pasted
    /// link is still findable somewhere instead of nowhere.
    private var items: [MediaFeedItem] {
        let origins = Set(source.origins)
        let all = store.sources.value ?? []
        let mine = origins.isEmpty
            ? all.filter { ($0.origin ?? "").isEmpty }
            : all.filter { item in item.origin.map { origins.contains($0) } ?? false }
        return mine.sorted { $0.recencyDate > $1.recencyDate }
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                if let channel { stateCard(channel) }
                let groups = SourceItemsGrouping.folders(items)
                if groups.count > 1 || (groups.first?.folder != SourceItemsGrouping.noFolder) {
                    folderCounts(groups)
                }
                if items.isEmpty {
                    Text("No saved items from this source yet.").font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textTertiary)
                } else {
                    VStack(spacing: CicadaTheme.spacingSM) {
                        ForEach(items) { FeedRow(item: $0, showRelevance: false) }
                    }
                }
            }
            .padding(.horizontal, CicadaTheme.spacingXL)
            .padding(.bottom, CicadaTheme.spacingXL)
        }
    }

    private func stateCard(_ channel: SourceChannel) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack {
                Text(channel.connected ? "Connected" : "Not connected")
                    .font(CicadaTheme.headingFont).foregroundStyle(CicadaTheme.textPrimary)
                Spacer()
                if channel.actions.contains("sync") { actionButton("Sync now") { try await BrowserImportActions.syncChannel(channel.id, store: store) } }
                if channel.actions.contains("poll") { actionButton("Poll now") { try await pollNow(channel) } }
            }
            if let detail = channel.detail { Text(detail).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary) }
            if let error = channel.lastError, !error.isEmpty {
                Text(error).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.danger)
            }
            if let feedback {
                Text(feedback.text).font(CicadaTheme.captionFont)
                    .foregroundStyle(feedback.isError ? CicadaTheme.danger : CicadaTheme.success)
                    .task(id: feedback) { try? await Task.sleep(for: .seconds(5)); if !Task.isCancelled { self.feedback = nil } }
            }
        }
        .padding(CicadaTheme.spacingMD).glassCard()
    }

    private func actionButton(_ title: String, _ work: @escaping () async throws -> String) -> some View {
        Button(title) {
            Task {
                busy = true
                do { feedback = ChannelFeedback(text: try await work(), isError: false) }
                catch { feedback = ChannelFeedback(text: AddSourceSheet.friendlyError(error), isError: true) }
                busy = false
                await store.refresh([.channels, .sources, .sourcesOverview, .status])
            }
        }
        .buttonStyle(.bordered).controlSize(.small).disabled(busy)
    }

    private func pollNow(_ channel: SourceChannel) async throws -> String {
        if channel.id == "calendar" {
            let r = try await APIClient.shared.pollCalendars()
            return r.skippedNoNetwork > 0 ? "Live fetch is disabled on this backend — set CICADA_ALLOW_FEED_FETCH=1 and restart." : "\(r.new) new event(s)"
        }
        let r = try await APIClient.shared.pollFeeds()
        return r.skippedNoNetwork > 0 ? "Live fetch is disabled on this backend — set CICADA_ALLOW_FEED_FETCH=1 and restart." : "\(r.new) new item(s)"
    }

    private func folderCounts(_ groups: [(folder: String, count: Int)]) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            Text(source.kind == .browser && source.id == "safari-tabs" ? "By device" : "By folder")
                .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
            FlowLayout(spacing: 6) {
                ForEach(groups, id: \.folder) { g in
                    Text("\(g.folder) · \(g.count)")
                        .font(.system(size: 11)).padding(.horizontal, 8).padding(.vertical, 3)
                        .background(CicadaTheme.surfaceHover).clipShape(Capsule())
                }
            }
        }
    }
}
```
(`AddSourceSheet.friendlyError` (`static`, not private — `AddSourceSheet.swift:902`), `BrowserImportActions.syncChannel(_:store:)` (`BrowserImportPanels.swift:16`), `APIClient.pollFeeds()`/`pollCalendars()` (`APIClient.swift:1494`/`:1526`, both results carry `new` and `skippedNoNetwork`), `ChannelFeedback(text:isError:)` (`ConnectedChannelRow.swift:6`, `Equatable` — which `.task(id:)` needs), `FlowLayout(spacing:)` (`EntityDetailCard.swift:1579`), `SourceChannel.detail/lastError/actions` (`Models/SourceChannel.swift:9-19`) and `MediaFeedItem.recencyDate` all exist. Make `FeedRow` internal at `FeedView.swift:231`. `UsageViewModel` and `ContributorsViewModel` are injected at the app root (`CicadaApp.swift:74-81`), so `SourcesPageView` and `ContributorsSection` read them from the environment with no new plumbing. The old `@AppStorage("cicada.activitySection")` key dies with `ActivityView`; the stale defaults value is harmless and is left alone.)

Move `ConversationRow` (verbatim, `ConversationsSection.swift:96-261`) into `Views/Sources/ConversationRow.swift`; `git mv Views/Activity/ConversationPopover.swift Views/Sources/ConversationPopover.swift`; `git rm` `Views/Activity/ActivityView.swift` and `Views/Activity/ConversationsSection.swift`; `git rm Views/Capture/OriginPill.swift` only if `grep -rn "OriginPill(" app/CicadaApp/Sources` shows nothing else. `OriginIconography.swift`: add `case "cursor": "Cursor"`, `case "codex": "Codex"`, `case "claude-desktop": "Claude Desktop"` to `label(for:)`; `case "mcp", "claude-code", "cursor", "codex", "claude-desktop"` to the bubble symbol; `case "cursor": Color(hex: 0x6E56CF)`, `case "codex": Color(hex: 0x10A37F)`, `case "claude-desktop": CicadaTheme.accent` in `color(for:)`.

- [ ] **Step 7: Build and test**

```
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g124/app/CicadaApp && swift build 2>&1 | tail -5 && swift test 2>&1 | tail -20
```
Expected: build succeeds; 0 failures. If `UsageRangeTests`/`UsageFormatTests` fail because `UsageRangeControls` moved, leave them for Task 4 only if they compile — they must be green at the end of THIS task, so fix any signature break they hit now.

- [ ] **Step 8: Commit**

```
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g124 && git add -- app/CicadaApp/Sources/CicadaApp/Views/Sidebar/SidebarView.swift app/CicadaApp/Sources/CicadaApp/ContentView.swift app/CicadaApp/Sources/CicadaApp/Theme/Copy.swift app/CicadaApp/Sources/CicadaApp/Models/SourceOverview.swift app/CicadaApp/Sources/CicadaApp/Sync app/CicadaApp/Sources/CicadaApp/Services/APIClient.swift app/CicadaApp/Sources/CicadaApp/ViewModels/ConversationsViewModel.swift app/CicadaApp/Sources/CicadaApp/Views/Sources app/CicadaApp/Sources/CicadaApp/Views/Activity app/CicadaApp/Sources/CicadaApp/Views/Capture app/CicadaApp/Sources/CicadaApp/Views/Feed/FeedView.swift app/CicadaApp/Tests/CicadaAppTests/SourcesPageTests.swift app/CicadaApp/Tests/CicadaAppTests/SidebarTabTests.swift app/CicadaApp/Tests/CicadaAppTests/CopyConstantsTests.swift app/CicadaApp/Tests/CicadaAppTests/ConversationsTests.swift app/CicadaApp/Tests/CicadaAppTests/StoreTests.swift app/CicadaApp/Tests/CicadaAppTests/ActivitySectionTests.swift && git commit -q -m "feat(app): Sources page — Activity becomes a grid of clickable memory sources with per-source pages (G124)

Tab renamed (Activity/Contributors/Usage all restore to Sources, ⌘6 kept),
sourcesOverview Store domain riding episodes+entities+sources, card grid →
per-source page: a harness lists its conversations (title filter, Resume via
the existing descriptor endpoint), a channel shows state, Sync/Poll now,
folder/device counts and its Feed items. Origins strip and the segmented
control are gone.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj"
```
(`git rm`/`git mv` already staged the deletions and moves, so `git add -- app/.../Views/Activity` is only there to sweep any leftover edit; if it fails with `pathspec ... did not match any files` because the directory is now empty and gone, drop that one path — nothing is lost. Confirm with `git status --short` that no `memory/`, `logs/` or `.venv` path is staged before committing.)

---

### Task 4: App — contributors calendar, Advanced counts, prices and tokens removed

**Files:**
- Create: `Models/ContributorCalendar.swift` (`ContributorCalendar`, `TopEntities`, `TopEntityWrite`, `TopEntityRead`)
- Modify: `Services/APIClient.swift` — `fetchContributorCalendar(author:weeks:)`, `fetchTopEntities(limit:range:)`, `recordEntityRead(id:)` beside `fetchContributorCommits` (:1149)
- Modify: `Views/Contributors/ContributorsView.swift:74-135, :206-243` (calendar in the drill-down)
- Modify: `Views/Usage/HeatmapView.swift:47-49` (tooltip)
- Replace stub: `Views/Sources/AdvancedStatsView.swift`
- Move: `StatTile` (`Views/Usage/UsageView.swift:148-163`) → `Views/Sources/StatTile.swift`; `UsageRangeControls` range menu → inside `AdvancedStatsView`
- Delete: `Views/Usage/UsageView.swift`, `Views/Usage/UsageAdvancedView.swift`
- Modify: `ViewModels/UsageViewModel.swift:157-164` (delete `subscriptionUsdMonth`, `costLine`), `Utilities/UsageFormat.swift:14-30` (delete `usd`, `costLine`, `tokens`)
- Modify: `Views/Graph/EntityDetailCard.swift:362-375` (`read` event)
- Tests: create `Tests/CicadaAppTests/ContributorCalendarTests.swift`; modify `UsageFormatTests.swift:6-9` (`tokens`) and `:13-30` (`usd`, `costLine`) — delete those cases; `FixWaveTests.swift:118-122` (`UsageAdvancedView.showsProgress` → `UsageViewModel.showsProgress`, three call sites inside `testUsageAdvancedShowsProgressWhileEitherLoadingFlagIsSet`). Verified at `bdcdc54`: `UsageRangeTests.swift`, `ConsumptionModelTests.swift` and `CalendarLayoutTests.swift` reference none of `usd`/`costLine`/`subscriptionUsdMonth`/`UsageFormat.tokens`/`tooltip` — expect NO edits there; re-run the grep in Step 1 to confirm before assuming.

**Interfaces:**
- `ContributorCalendar: Codable` `{author, days: [CalendarDay], weeks}` decode-tolerant; `TopEntities: Codable` `{written, read, commitsScanned, range}` decode-tolerant.
- `APIClient.fetchContributorCalendar(author: String, weeks: Int = 53) async throws -> ContributorCalendar`; `fetchTopEntities(limit: Int = 10, range: String = "all") async throws -> TopEntities`; `recordEntityRead(id: String) async` (never throws — a ledger miss must never surface on a card).
- `HeatmapView.tooltip(_:)` becomes `static func tooltip(_ c: CalendarCell) -> String` (pure, tested): `"<date> · N memory write(s)"` + `" · M event(s)"` only when `events > 0`; never tokens.

- [ ] **Step 1: Write the failing tests**

```swift
// Tests/CicadaAppTests/ContributorCalendarTests.swift
import XCTest
@testable import CicadaApp

/// G124 — the per-contributor calendar and the read/write stats, and the
/// rule that nothing on this page prices anything.
final class ContributorCalendarTests: XCTestCase {

    func testContributorCalendarDecodesAndTolerates() throws {
        let json = #"{"author":"gpt-5.4-mini","days":[{"date":"2026-08-28","memoryWrites":2,"level":4}],"weeks":4}"#.data(using: .utf8)!
        let cal = try JSONDecoder().decode(ContributorCalendar.self, from: json)
        XCTAssertEqual(cal.author, "gpt-5.4-mini"); XCTAssertEqual(cal.weeks, 4)
        XCTAssertEqual(cal.days[0].cell, CalendarCell(date: "2026-08-28", level: 4, memoryWrites: 2, events: 0, tokens: 0))
        let sparse = try JSONDecoder().decode(ContributorCalendar.self, from: #"{"author":"user"}"#.data(using: .utf8)!)
        XCTAssertEqual(sparse.days, []); XCTAssertEqual(sparse.weeks, 53)
    }

    func testTopEntitiesDecodesAndTolerates() throws {
        let json = #"{"written":[{"entityId":"alpha-project","commits":3,"lastWritten":"2026-08-03"}],"read":[{"entityId":"bob-example","reads":2,"lastRead":"2026-09-01T10:00:00Z"}],"commitsScanned":5,"range":"all"}"#.data(using: .utf8)!
        let top = try JSONDecoder().decode(TopEntities.self, from: json)
        XCTAssertEqual(top.written.map(\.entityId), ["alpha-project"]); XCTAssertEqual(top.written[0].commits, 3)
        XCTAssertEqual(top.read[0].reads, 2); XCTAssertEqual(top.commitsScanned, 5)
        let empty = try JSONDecoder().decode(TopEntities.self, from: "{}".data(using: .utf8)!)
        XCTAssertEqual(empty.written, []); XCTAssertEqual(empty.read, []); XCTAssertEqual(empty.commitsScanned, 0)
    }

    func testHeatmapTooltipNeverMentionsTokens() {
        let writesOnly = CalendarCell(date: "2026-08-28", level: 4, memoryWrites: 1, events: 0, tokens: 99_000)
        XCTAssertEqual(HeatmapView.tooltip(writesOnly), "2026-08-28 · 1 memory write")
        let both = CalendarCell(date: "2026-08-29", level: 2, memoryWrites: 2, events: 3, tokens: 99_000)
        XCTAssertEqual(HeatmapView.tooltip(both), "2026-08-29 · 2 memory writes · 3 events")
        XCTAssertFalse(HeatmapView.tooltip(both).lowercased().contains("token"))
    }

    func testAdvancedTilesAreCountsOnly() {
        var s = ConsumptionSummary()
        s.memoryWrites = 12; s.sleepRuns = 3; s.agenticWrites = 4; s.streakCurrent = 2; s.streakBest = 9; s.costUsd = 42
        let tiles = AdvancedStatsView.tiles(for: s)
        XCTAssertEqual(tiles.map(\.title), ["Memory writes", "Sleep runs", "In-session writes", "Streak"])
        XCTAssertEqual(tiles.map(\.value), ["12", "3", "4", "2d"])
        XCTAssertFalse(tiles.contains { $0.value.contains("$") || ($0.footnote ?? "").contains("$") })
    }

    override func tearDown() {
        MockURLProtocol.handler = nil
        super.tearDown()
    }

    /// Same harness `ConversationsTests` uses (`MockURLProtocol` lives in
    /// `EntitySourceTests.swift:10-17`; `APIClient(session:)` at
    /// `APIClient.swift:805`). A URLProtocol sees a POST body as a stream, so
    /// the assertion reads `httpBodyStream` — `httpBody` is nil there.
    func testRecordEntityReadPostsIdsOnly() async throws {
        var captured: (method: String?, path: String?, body: Data?)?
        MockURLProtocol.handler = { request in
            var data = Data()
            if let stream = request.httpBodyStream {
                stream.open(); defer { stream.close() }
                var buffer = [UInt8](repeating: 0, count: 1024)
                while stream.hasBytesAvailable {
                    let n = stream.read(&buffer, maxLength: buffer.count)
                    if n <= 0 { break }
                    data.append(buffer, count: n)
                }
            } else if let body = request.httpBody { data = body }
            captured = (request.httpMethod, request.url?.path, data)
            return (HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!,
                    #"{"recorded":true}"#.data(using: .utf8)!)
        }
        await APIClient(session: MockURLProtocol.makeSession()).recordEntityRead(id: "alpha-project")
        XCTAssertEqual(captured?.method, "POST")
        XCTAssertEqual(captured?.path, "/entities/alpha-project/read")
        let body = try XCTUnwrap(captured?.body)
        XCTAssertEqual(try JSONSerialization.jsonObject(with: body) as? [String: String], ["surface": "app"])
    }

    /// A 404 (page gone) or an old backend must never surface: the call
    /// returns normally.
    func testRecordEntityReadSwallowsErrors() async {
        MockURLProtocol.handler = { request in
            (HTTPURLResponse(url: request.url!, statusCode: 404, httpVersion: nil, headerFields: nil)!, Data())
        }
        await APIClient(session: MockURLProtocol.makeSession()).recordEntityRead(id: "gone")
    }
}
```
`ConsumptionSummary` fields are `var`, so the mutation in `testAdvancedTilesAreCountsOnly` compiles. `FixWaveTests.swift:119-121` references `UsageAdvancedView.showsProgress(...)` — change those three lines to `UsageViewModel.showsProgress(...)` (the static moves in Step 5).

`UsageFormatTests.swift`: delete the `tokens` case (`:6-9`) and the `usd`/`costLine` cases (`:13-30`), keep `count`/`percent`/`duration`/`harnessValue`. `UsageRangeTests.swift` and `ConsumptionModelTests.swift` carry no cost/token assertion at `bdcdc54` (confirm: `grep -n "usd\|costLine\|subscriptionUsdMonth\|UsageFormat.tokens" Tests/CicadaAppTests/UsageRangeTests.swift Tests/CicadaAppTests/ConsumptionModelTests.swift Tests/CicadaAppTests/CalendarLayoutTests.swift` prints nothing) — leave them untouched unless that grep says otherwise.

- [ ] **Step 2: Build tests to confirm failure** — `swift build --build-tests 2>&1 | grep -c "error:"` non-zero.

- [ ] **Step 3: Models** — `Models/ContributorCalendar.swift`:

```swift
import Foundation

/// `GET /contributors/calendar?author=` (G124 R14): `/consumption/calendar`'s
/// shape for one `Cicada-Author`. `days` are `CalendarDay`s with only
/// `memoryWrites`/`level` populated. Decode-tolerant like every sibling.
struct ContributorCalendar: Codable {
    let author: String
    let days: [CalendarDay]
    let weeks: Int
    enum CodingKeys: String, CodingKey { case author, days, weeks }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        author = try c.decodeIfPresent(String.self, forKey: .author) ?? ""
        days = (try? c.decodeIfPresent([CalendarDay].self, forKey: .days)) ?? []
        weeks = try c.decodeIfPresent(Int.self, forKey: .weeks) ?? 53
    }
}

struct TopEntityWrite: Codable, Identifiable, Equatable {
    let entityId: String; let commits: Int; let lastWritten: String
    var id: String { entityId }
    enum CodingKeys: String, CodingKey { case entityId, commits, lastWritten }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        entityId = try c.decode(String.self, forKey: .entityId)
        commits = try c.decodeIfPresent(Int.self, forKey: .commits) ?? 0
        lastWritten = try c.decodeIfPresent(String.self, forKey: .lastWritten) ?? ""
    }
}

struct TopEntityRead: Codable, Identifiable, Equatable {
    let entityId: String; let reads: Int; let lastRead: String
    var id: String { entityId }
    enum CodingKeys: String, CodingKey { case entityId, reads, lastRead }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        entityId = try c.decode(String.self, forKey: .entityId)
        reads = try c.decodeIfPresent(Int.self, forKey: .reads) ?? 0
        lastRead = try c.decodeIfPresent(String.self, forKey: .lastRead) ?? ""
    }
}

/// `GET /contributors/top-entities` (G124): most-written from git (bounded —
/// `commitsScanned` says how far back), most-read from the ids-only `read`
/// ledger kind. Counts only, by the 2026-09-03 ruling.
struct TopEntities: Codable {
    let written: [TopEntityWrite]
    let read: [TopEntityRead]
    let commitsScanned: Int
    let range: String
    enum CodingKeys: String, CodingKey { case written, read, commitsScanned, range }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        written = (try? c.decodeIfPresent([TopEntityWrite].self, forKey: .written)) ?? []
        read = (try? c.decodeIfPresent([TopEntityRead].self, forKey: .read)) ?? []
        commitsScanned = try c.decodeIfPresent(Int.self, forKey: .commitsScanned) ?? 0
        range = try c.decodeIfPresent(String.self, forKey: .range) ?? "all"
    }
}
```

`APIClient.swift`, beside `fetchContributorCommits` (:1149):
```swift
    /// G124 R14 — one contributor's memory-write calendar. On demand, like the
    /// commit drill-down: no Store domain, no ETag on the app side.
    func fetchContributorCalendar(author: String, weeks: Int = 53) async throws -> ContributorCalendar {
        let encoded = author.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? author
        return try await get("/contributors/calendar?author=\(encoded)&weeks=\(weeks)")
    }

    /// G124 — most-written / most-read entity pages, counts only.
    func fetchTopEntities(limit: Int = 10, range: String = "all") async throws -> TopEntities {
        try await get("/contributors/top-entities?limit=\(limit)&range=\(range)")
    }

    /// G124 R11 — the app opened an entity card. Fire-and-forget: a ledger
    /// miss, a 404 (the page vanished between click and open) or an old
    /// backend must never surface on the card, so every error is swallowed.
    func recordEntityRead(id: String) async {
        _ = try? await post("/entities/\(id)/read", body: ["surface": "app"]) as Data
    }
```

- [ ] **Step 4: Contributors calendar** — in `ContributorsView.swift`'s `ContributorRow` add `@State private var calendar: ContributorCalendar?`, `@State private var calendarFailed = false`, `@State private var selectedDay: CalendarDay?`; extend `.task(id: isExpanded)` to also `await loadCalendar()` (guard `calendar == nil`); in `drillDown`, above the commits, render:

```swift
            // G124 R14 — when this contributor wrote memory. The same
            // `HeatmapView` the old Usage page used, fed per author.
            if let calendar {
                HeatmapView(days: calendar.days, selected: $selectedDay)
                if let day = selectedDay {
                    Text("\(day.date) · \(UsageFormat.count(day.memoryWrites)) memory write\(day.memoryWrites == 1 ? "" : "s")")
                        .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                }
            } else if calendarFailed {
                Text("Couldn't load this contributor's calendar").font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
            }
```
with
```swift
    private func loadCalendar() async {
        do { calendar = try await APIClient.shared.fetchContributorCalendar(author: contributor.author) }
        catch { guard !Self.isCancellation(error) else { return }; calendarFailed = true }
    }
```
`ContributorsSection`'s outer `ScrollView` (:40-51) becomes a plain `VStack` and the trailing `Spacer()` (:54) goes — the page (`SourcesPageView`) owns the single scroll now (nested scroll views fight, and a spacer inside a scroll view has nothing to push against). Keep the never-loaded / empty / error branches.

`HeatmapView.swift:47-49`:
```swift
    /// The cell's hover text. Writes always, events only when there are any,
    /// tokens NEVER — the 2026-09-03 ruling on the G124 row took token counts
    /// out of the app; `CalendarCell.tokens` stays decoded but unrendered.
    static func tooltip(_ c: CalendarCell) -> String {
        var text = "\(c.date) · \(c.memoryWrites) memory write\(c.memoryWrites == 1 ? "" : "s")"
        if c.events > 0 { text += " · \(c.events) event\(c.events == 1 ? "" : "s")" }
        return text
    }
```
(and the call site `.help(c.map(Self.tooltip) ?? "")`).

- [ ] **Step 5: Advanced, counts only** — replace the Task 3 stub `Views/Sources/AdvancedStatsView.swift`:

```swift
import SwiftUI

/// A tile's content, pure so the "counts only" rule is unit-tested.
struct StatTileSpec: Equatable {
    let title: String
    let value: String
    let footnote: String?
}

/// The Advanced section of the Sources page (G124, behind the persisted
/// `UsageMode` toggle — R8). Counts only, by the 2026-09-03 ruling: memory
/// writes, sleep runs, in-session writes, streak, then the read/write stats
/// (most-written from git, most-read from the ids-only `read` ledger kind)
/// and the harness panel's own session/message counts. No cost, no tokens,
/// no per-connection cards — `/consumption/*` still serves those fields; this
/// page simply never renders them.
struct AdvancedStatsView: View {
    var onSelectEntity: ((String) -> Void)?

    @Environment(UsageViewModel.self) private var viewModel
    @State private var top: TopEntities?
    @State private var topFailed = false
    @State private var loadedOnce = false

    /// Pure: the four tiles from a summary. Tested to contain no `$`.
    static func tiles(for s: ConsumptionSummary) -> [StatTileSpec] {
        [
            StatTileSpec(title: "Memory writes", value: UsageFormat.count(s.memoryWrites), footnote: nil),
            StatTileSpec(title: "Sleep runs", value: UsageFormat.count(s.sleepRuns), footnote: nil),
            StatTileSpec(title: "In-session writes", value: UsageFormat.count(s.agenticWrites), footnote: "claims agents wrote mid-conversation"),
            StatTileSpec(title: "Streak", value: "\(s.streakCurrent)d", footnote: "best \(s.streakBest)d"),
        ]
    }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            HStack(spacing: CicadaTheme.spacingSM) {
                Picker("Range", selection: Binding(get: { viewModel.range }, set: { viewModel.range = $0 })) {
                    Text("This month").tag("month"); Text("30 days").tag("30d"); Text("90 days").tag("90d"); Text("All time").tag("all")
                }
                .pickerStyle(.menu).labelsHidden().fixedSize()
                .accessibilityLabel("Choose the reporting range")
                if viewModel.isLoadingRange { ProgressView().controlSize(.small) }
            }
            if viewModel.showsProgress {
                ProgressView().frame(maxWidth: .infinity, alignment: .center).padding(CicadaTheme.spacingLG)
            } else if let err = viewModel.errorMessage {
                placeholder(err)
            } else if viewModel.isEmptyRange {
                placeholder("No activity in this range")
            } else {
                HStack(spacing: CicadaTheme.spacingMD) {
                    ForEach(Self.tiles(for: viewModel.summary), id: \.title) { t in
                        StatTile(title: t.title, value: t.value, footnote: t.footnote)
                    }
                    feedbackTileSlot
                }
            }
            readWriteStats
            harnessPanel
        }
        .padding(.horizontal, CicadaTheme.spacingXL)
        .task {
            guard !loadedOnce else { return }
            loadedOnce = true
            await viewModel.load()
            await loadTop()
        }
        .task(id: viewModel.range) { await loadTop() }
    }

    /// G113 slice 4 lands its Feedback-rate tile here (a rate, not a price —
    /// welcome under Advanced). Empty until that slice ships (R10).
    @ViewBuilder private var feedbackTileSlot: some View { EmptyView() }

    private func loadTop() async {
        do { top = try await APIClient.shared.fetchTopEntities(limit: 10, range: viewModel.range); topFailed = false }
        catch { topFailed = true }
    }

    @ViewBuilder
    private var readWriteStats: some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingMD) {
            entityList("Most written", footnote: top.map { "over the last \(UsageFormat.count($0.commitsScanned)) commits" },
                       rows: (top?.written ?? []).map { ($0.entityId, "\(UsageFormat.count($0.commits)) commits") })
            entityList("Most read", footnote: "opened in the app or recalled by an agent",
                       rows: (top?.read ?? []).map { ($0.entityId, "\(UsageFormat.count($0.reads)) reads") })
        }
        if topFailed {
            Text("Couldn't load read/write stats").font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
        }
    }

    private func entityList(_ title: String, footnote: String?, rows: [(String, String)]) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            Text(title).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
            if rows.isEmpty {
                Text("Nothing yet").font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
            }
            ForEach(rows, id: \.0) { id, count in
                HStack {
                    if let onSelectEntity {
                        Button(id) { onSelectEntity(id) }.buttonStyle(.cicadaPlain).foregroundStyle(CicadaTheme.accent)
                    } else {
                        Text(id).foregroundStyle(CicadaTheme.textPrimary)
                    }
                    Spacer()
                    Text(count).foregroundStyle(CicadaTheme.textTertiary)
                }
                .font(CicadaTheme.captionFont)
            }
            if let footnote { Text(footnote).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary) }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(CicadaTheme.spacingMD).glassCard()
    }

    private func placeholder(_ text: String) -> some View {
        Text(text).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textTertiary)
            .frame(maxWidth: .infinity, alignment: .center).padding(CicadaTheme.spacingLG).glassCard()
    }

    // `harnessPanel` and `sectionTitle(_:)` move here VERBATIM from
    // UsageAdvancedView.swift — `@ViewBuilder private var harnessPanel`
    // (:182-211) and `private func sectionTitle(_:)` (:213-215). Same
    // `viewModel` name, same `viewModel.harness` (UsageViewModel.swift:102),
    // same `StatTile`/`UsageFormat.harnessValue`/`UsageFormat.percent` calls,
    // so the two blocks compile unchanged once pasted below this comment.
    // (Claude Code sessions/messages from ~/.claude/stats-cache.json — a count
    // file, never a transcript — and the Codex rate-limit windows: counts and
    // percentages, never prices, so it survives the ruling.)
}
```
Copy the two members with `sed -n '182,215p' Sources/CicadaApp/Views/Usage/UsageAdvancedView.swift` BEFORE deleting that file, and paste them as the last members of `AdvancedStatsView` (replacing the comment block above). Do not retype them.
Move `StatTile` (verbatim from `UsageView.swift:148-163`) into `Views/Sources/StatTile.swift`. `git rm Views/Usage/UsageView.swift Views/Usage/UsageAdvancedView.swift`. `UsageViewModel.showsProgress` (:151-154) calls `UsageAdvancedView.showsProgress(isLoadingRange:isLoading:)` — move that static (`UsageAdvancedView.swift:17-19`, with its M1 doc comment) onto `UsageViewModel` as `static func showsProgress(isLoadingRange: Bool, isLoading: Bool) -> Bool` and point :153 at `Self.showsProgress(...)`; update the two doc-comment mentions at :135 and :150 to name `AdvancedStatsView`. In `UsageViewModel.swift` delete `subscriptionUsdMonth` and `costLine` (:156-164); `isEmptyRange` (:124-128) keeps `summary.invocations == 0 && summary.tokens == 0 && summary.memoryWrites == 0` — that is a data test, not a rendered token, and stays. `UsageFormat.swift`: delete `usd` (:14-19), `costLine` (:21-30), `tokens` (:6-12); update the enum doc comment to `/// Number formatting for the Sources page's counts. No currency and no token formatter live here any more — the 2026-09-03 G124 ruling took prices and token usage out of the app.`

- [ ] **Step 6: The app-side `read` event** — `EntityDetailCard.swift:362-375`, first line inside `.task(id: entity.id)`:

```swift
            // G124 R11 — a card open is a read. Fire-and-forget on its own
            // Task so a slow ledger never delays the sources fetch below.
            Task { await APIClient.shared.recordEntityRead(id: entity.id) }
```

- [ ] **Step 7: Build, test, and the no-prices grep**

```
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g124/app/CicadaApp && swift build 2>&1 | tail -5 && swift test 2>&1 | tail -20
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g124/app/CicadaApp && grep -rn "usd\|costUsd\|equivCost\|\$/mo\|UsageFormat.tokens\|priceUsdMonth" Sources/CicadaApp/Views ; echo "exit=$? (1 = clean)"
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g124/app/CicadaApp && grep -rn "import Charts" Sources ; echo "exit=$? (1 = clean)"
```
Expected: build ok, 0 failures, both greps print nothing (exit 1). (`Views/Settings` may legitimately show a plan's `priceUsdMonth` — Plans & keys is a Settings tab and not this page; if the grep hits there, narrow it to `Sources/CicadaApp/Views/Sources Sources/CicadaApp/Views/Contributors Sources/CicadaApp/Views/Usage` and record that in the commit body.)

- [ ] **Step 8: Commit**

```
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g124 && git add -- app/CicadaApp/Sources/CicadaApp/Models/ContributorCalendar.swift app/CicadaApp/Sources/CicadaApp/Services/APIClient.swift app/CicadaApp/Sources/CicadaApp/Views/Contributors/ContributorsView.swift app/CicadaApp/Sources/CicadaApp/Views/Usage app/CicadaApp/Sources/CicadaApp/Views/Sources app/CicadaApp/Sources/CicadaApp/ViewModels/UsageViewModel.swift app/CicadaApp/Sources/CicadaApp/Utilities/UsageFormat.swift app/CicadaApp/Sources/CicadaApp/Views/Graph/EntityDetailCard.swift app/CicadaApp/Tests/CicadaAppTests/ContributorCalendarTests.swift app/CicadaApp/Tests/CicadaAppTests/UsageFormatTests.swift app/CicadaApp/Tests/CicadaAppTests/UsageRangeTests.swift app/CicadaApp/Tests/CicadaAppTests/ConsumptionModelTests.swift app/CicadaApp/Tests/CicadaAppTests/FixWaveTests.swift && git commit -q -m "feat(app): contributors calendar per model, Advanced counts, prices and tokens leave the UI (G124)

GitHub-style heatmap per Cicada-Author in the contributor drill-down;
Advanced = memory writes / sleep runs / in-session writes / streak +
most-written / most-read entities (+ a slot for G113's feedback rate);
every cost tile, \$ column, token chart and price line deleted along with
UsageFormat.usd/costLine/tokens. Card opens record an ids-only read event.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj"
```

---

### Task 5: Docs — CLAUDE.md, the G124/G51/G9 rows, TODO.md

**Files:**
- Modify: `CLAUDE.md:635` (sidebar paragraph), `:705-707` and `:713` (API list), add the four new endpoints
- Modify: `docs/goals/memory-evolution.md:686` (G124 → shipped), `:594` (G51 note), `:478` (G9 note)
- Modify: `docs/goals/TODO.md:202-278` (Shipped), `:367` (12d out of Next), header `_Last synced_` line and the "Where things stand" list if it names Activity

**Privacy rule:** nothing personal — no bank contents, no episode titles, no names other than the owner's own design words already in the row.

- [x] **Step 1: CLAUDE.md sidebar paragraph (:635)** — replace the sentence `The sidebar is six rows — Graph, Clusters, Feed, Sleep, Inbox, Activity — reachable via ⌘1–6 …and Activity merges consumption and contributor attribution behind a segmented control with the origins strip.` with:

> The sidebar is six rows — Graph, Clusters, Feed, Sleep, Inbox, **Sources** — reachable via ⌘1–6 (with matching accessibility labels); Feed carries the capture channels and the `+`/⌘N add-source sheet, Sleep carries the episode queue, and **Sources (G124, replaced Activity 2026-09-03)** opens on *where memory comes from*: a grid of clickable cards from `GET /sources/overview` (one per harness, chat export, browser, social/feed/messaging channel or unknown origin — conversations, items and credited entities, last activity, connected state), each opening a per-source page (a harness's conversations with a title filter and a **Resume** button when the backend says `resumable` — `POST /conversations/{id}/resume`, transcripts never read; a channel's state, Sync/Poll now, folder/device counts and its Feed items), then Contributors (the attribution table plus a GitHub-style calendar per `Cicada-Author` from `GET /contributors/calendar`), then a persisted **Advanced** toggle holding counts only — memory writes, sleep runs, in-session writes, streak, most-written (git) and most-read (the ids-only `read` ledger kind) entities. **Ruling (2026-09-03): prices and token usage are not shown anywhere in the app** — no cost tiles, `$`/token columns or cost-per-day chart; the `/consumption/*` endpoints and the telemetry ledger are unchanged for future use. Sections are headers on one scrolling page; there is no segmented control and no horizontal origins strip.

Also update the `restored(from:)` sentence: `…maps the six retired ones (\`Capture\`, \`Contributors\`, \`Usage\`, \`Activity\`, \`Connections\`, \`Connect\`)…`.

- [x] **Step 2: CLAUDE.md API list** — after `GET  /contributors/commits…` (:706) add:
```
GET  /contributors/calendar?author=&weeks=  → one Cicada-Author's memory writes per UTC day (the /consumption/calendar
                                            shape, levels from writes alone) — the per-model GitHub calendar (G124)
GET  /contributors/top-entities?limit=&range= → most-written entity pages (git, last 2,000 commits — `commitsScanned`
                                            says so) + most-read (ids-only `read` ledger events) — counts only (G124)
```
after `GET  /conversations/recent …` (:713-715) append to its description: `; \`?harness=\`/\`?origin=\` filter BEFORE the cap (G124)`. After `POST /entities/{id}/sources` (:697) add:
```
POST /entities/{id}/read                  → record an ids-only `read` ledger event {surface: app|mcp} (G124);
                                            404 for an unknown page; nothing written to the bank
```
after `GET  /sources/channels` (:740) add:
```
GET  /sources/overview                    → one row per memory source (harness / chat export / browser / social /
                                            feed / messaging / import): conversations, episodes, entities credited,
                                            items, lastActivityAt, connected, lastError; ETag = sources+episodes+
                                            entities + the Telegram/connector tags, like /sources/channels (G124)
```
And in the Telemetry ledger paragraph (`### Telemetry ledger`, :487), append one sentence: `The \`read\` kind (G124) records an entity id and a surface enum (\`app\`, \`mcp\`, \`mcp-recall\`) when a page is opened in the app or served/suggested by \`cicada_recall_detail\`/\`cicada_recall\` — never a query or page text — and is excluded from connection rollups like the G113 feedback kinds (\`telemetry.NON_SPEND_KINDS\`).`

- [x] **Step 3: `memory-evolution.md`** — G124 row (:686): status cell `🔲` → `✅ (2026-09-03, PR #TBD — feat/sources-page: GET /sources/overview, /contributors/calendar, /contributors/top-entities, POST /entities/{id}/read + the read ledger kind; Sources tab replaces Activity with a card grid, per-source pages, Resume, per-model calendar, Advanced counts; every price/token surface removed from the app. OPEN: the G120 attention card on a per-source page (a slot, not built), G108's sidebar-order decision (tab stays sixth), G113 slice 4's feedback tile (a named slot in AdvancedStatsView), harness marks are OriginIconography glyphs — no brand assets.)`. Append to the row text: ` **Shipped shape (2026-09-03):** rulings R1–R17 in `docs/superpowers/plans/2026-09-03-g124-sources-page.md`; entity credit on the overview is `source_episodes`-only (R3, matching /origins), while a harness's conversation rows keep the claim-session credit. **Follow-up (R1, found while building):** three writers stamp no `origin` — `POST /sources/save` (`api/routers/sources.py`), MCP `cicada_save_url` (`mcp/server.py`) and the RSS poll (`feed_registry.poll_feeds` → `media_ingestor.ingest_feed`, bare `RawItem(url=…)`). Until they do, pasted links sit under Files & links as nil-origin items and the RSS card counts subscriptions, not captures. Fix = one `origin=` per writer (`share-sheet`/`mcp`-harness/`rss`) plus a `_ORIGIN_TO_ID` entry — no schema change.`
  G51 row (:594) status cell: append ` — UI half reshaped by G124 (2026-09-03): the Usage page is gone; counts survive under Sources ▸ Advanced, prices/tokens are no longer rendered anywhere; the endpoints and ledger stand.`
  G9 row (:478) status cell: append ` The app's origins strip was retired by G124 (2026-09-03) — the same provenance is now the Sources card grid.`

- [x] **Step 4: TODO.md** — move `12d. G124` (:367-370) out of Next into Shipped (`## ✅ Shipped`, :202) under **Provenance**: `**G124 Sources page (2026-09-03, PR #TBD)** — Activity → Sources: card grid from /sources/overview, per-source pages with Resume, contributors calendar per model, Advanced counts; prices/tokens out of the app`. Update the `_Last synced:` line (:198) with `G124 on feat/sources-page, PR pending`. Two lines name the old page and must be reworded: `:309` ("a fourth Activity card" — G113 slice 4's feedback-rate tile → "a tile in Sources ▸ Advanced, the `feedbackTileSlot`") and `:426` ("route Ask citations and Activity …" → "… and Sources entity chips …"). Add to the header's worktree list (:182-186): `.worktrees/g124` holds `feat/sources-page` until its PR merges.

- [x] **Step 5: Verify docs tests still pass** (some tests read CLAUDE.md? check `grep -rln "CLAUDE.md" api/tests app/CicadaApp/Tests`) and commit:

```
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g124 && git add -- CLAUDE.md docs/goals/memory-evolution.md docs/goals/TODO.md docs/superpowers/plans/2026-09-03-g124-sources-page.md && git commit -q -m "docs: Sources replaces Activity (G124) — sidebar paragraph, four new endpoints, G124/G51/G9 rows, TODO.md handoff

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj"
```

---

## Not in scope (deliberately)

- **G108** — the sidebar order / landing page decision. The tab stays sixth (⌘6); no prev/next or history navigation beyond the page's own grid→detail stack (R15).
- **G120** — the attention-frequency card on a per-source page. `SourceDetailView` has no slot code for it; the row notes where it goes.
- **G106** — the full conversation ↔ entity browser and content search. The per-harness page is a list with a title filter; entity chips still jump to the graph.
- **G113 slice 4** — `GET /consumption/feedback` and the Feedback rate tile (R10: named slot only).
- Any change to `/consumption/*` routers, `consumption_stats.summary/stats/per_connection` cost math, `pricing.py`, or the ledger's cost fields.
- Brand image assets for harness marks (R17); deleting the `origins` Store domain or `OriginIconography` (R16); backfilling `origin`/`folder` onto pre-existing media pages.
- Anything in `mcp/server.py` beyond the six lines of Task 2 Step 8.
- Stamping an `origin` on the three writers that omit it today (`POST /sources/save`, `cicada_save_url`, the RSS poll — R1). Recorded as a follow-up on the G124 row; the Sources page discloses the gap (Files & links = nil-origin items, RSS = subscription count) rather than pretending those pages are attributed.

## Verification the orchestrator runs at the end

```
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g124 && git status --porcelain -uall | grep -v "^?? api/.venv" ; echo "(must be empty apart from the .venv symlink)"
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g124 && git log --oneline bdcdc54..HEAD   # exactly 5 commits, Tasks 1–5 in order
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g124 && api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider 2>&1 | tail -15
#   → only the 8 test_calendar_registry.py failures + test_agent_provenance.py::test_a_decay_only_change_lands_in_its_own_cicada_authored_commit
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g124/app/CicadaApp && swift build 2>&1 | tail -5 && swift test 2>&1 | tail -20   # 0 failures
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g124/app/CicadaApp && grep -rn "usd\|costUsd\|equivCost\|\$/mo\|UsageFormat.tokens\|import Charts" Sources/CicadaApp/Views/Sources Sources/CicadaApp/Views/Contributors Sources/CicadaApp/Views/Usage Sources/CicadaApp/Utilities/UsageFormat.swift ; echo "exit=$? (1 = no prices/tokens rendered)"
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g124 && git diff bdcdc54..HEAD --stat -- mcp/server.py   # ≤ 8 lines changed
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g124 && git diff bdcdc54..HEAD --stat -- api/routers/consumption.py api/services/pricing.py   # no output: endpoints untouched
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g124 && grep -n "ActivityView\|ActivitySection\|originsLabel\|Copy.activity" -r app/CicadaApp/Sources CLAUDE.md ; echo "exit=$? (1 = Activity fully retired)"
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g124 && grep -rn "rorosaga\|/Users/" api/services/source_overview.py app/CicadaApp/Sources/CicadaApp/Views/Sources ; echo "exit=$? (1 = portable)"
```
Then the owner-present steps (not automatable here): `make install-app` from the main checkout after merge; open ⌘6, confirm a persisted "Activity" selection lands on Sources, click a harness card → Resume opens Terminal, click Safari → Sync now, toggle Advanced and confirm no `$` appears anywhere on the page.
