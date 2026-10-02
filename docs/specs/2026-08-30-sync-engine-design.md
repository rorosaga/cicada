# Sync Engine — Linear-feel companion app (G58) + in-app Ask (G52)

**Date:** 2026-08-30 · **Status:** design, executing under Rodrigo's "go ahead" · **Branch:** `feat/sync-engine` (off `dev`)
**Backlog:** G58 (new — sync engine + backend hot-path fixes), G52 (in-app "ask your memory anything")
**Plan:** [`../plans/2026-08-30-sync-engine.md`](../plans/2026-08-30-sync-engine.md)

## 1. Goal

Make the companion app feel like Linear: every page renders **instantly** from a local snapshot, data refreshes **in the background** from a cheap change signal, mutations apply **optimistically**, and nothing blanks while loading. Same architecture Linear's sync engine uses, scaled to a single-user localhost backend: *client-side store + version stamps + delta pushes*, not request-per-view.

## 2. What is slow today (measured 2026-08-30, real bank, 1,730 entities / 1,193 episodes)

| Symptom | Measured | Root cause (file:line) |
|---|---|---|
| Search takes 5 s every time | `/search` 4.7–5.2 s warm | `providers.resolve_embed_fn_for_model` constructs a new `SentenceTransformer` **per request** (`vector_index.py:109-127`) — model load, not inference |
| Menu bar / status sluggish | `/status` 0.62–0.80 s | parses **every** episode file twice per call: `sleep_cycle._get_unprocessed_episodes` (0.94 s) + `status._last_ingested_at` (0.85 s) = 2,452 YAML parses |
| Capture page origins strip | `/origins` 1.0–3.2 s | `origin_stats.aggregate_origins` parses 2,923 files per call |
| Contributors | 0.2–1.0 s | 33 sequential `git` subprocesses (`git_service.get_contributors`) |
| Every tab switch shows spinners / empties | — | `ContentView.detailContent` recreates page views → per-view `@State` view models re-init and refetch (`ContentView.swift:64-86`); nothing persisted to disk |
| Bank switch / post-Sleep freeze | — | full `/graph` reload (1.5 MB) → full re-serialise on the main actor in `updateNSView` → full `updateGraph` replace (`GraphView.swift:69`, `GraphViewModel.swift:79-125`) |
| Entity click opens empty card | — | graph nodes carry no body; `GET /entities/{id}` round-trip every click (`GraphViewModel.swift:163-179`) |
| Writes feel laggy | — | ~18 of ~20 mutations are wait-then-refetch-all (feeds, calendars, banks, connections); only inbox resolve is optimistic |
| Event loop stalls | — | `/graph`, `/status`, `/origins` are `async def` doing blocking file I/O on the loop |

## 3. Assumptions (override any)

1. Same-machine backend: latency is dominated by *server compute* and *client re-render*, not the wire. So the engine is **pull-based with a push signal** (SSE), no CRDTs, no offline write log beyond an in-memory retry.
2. Snapshots persist under `~/Library/Application Support/Cicada/cache/<bank>/` as JSON (same pattern as `UploadHistoryStore`). They are a *cache*, disposable; the backend stays the source of truth.
3. Change detection = one cheap **version vector** computed from directory mtimes + git HEAD read from `.git/HEAD` (no subprocess). Sub-10 ms.
4. Graph deltas are computed **client-side** by diffing the previous snapshot with the new payload (ids + a per-node content hash the backend adds), then pushed to d3 as add/update/remove. The backend stays simple.
5. The graph payload gains a `summary` (≤ 200 chars) per node so detail cards open with content; the full markdown stays lazy.
6. Optimistic mutations roll back on failure with a transient banner; no conflict resolution beyond "server wins on next sync".
7. Sidebar rows become real `Button`s (accessibility + ⌘1…⌘9); this is part of "feels right", not scope creep.
8. G52 rides the same store: the Ask panel keeps its history per bank in the cache dir; answers come from the existing `POST /ask`.

## 4. Backend design

### 4.1 `bank_index` — parsed-frontmatter cache (`api/services/bank_index.py`)
An in-process cache of `{path: (mtime_ns, size, frontmatter)}` per bank for `entities/`, `episodes/`, `inbox/`. `refresh(memory_path)` does one `os.scandir` per dir (~5 ms for 3k files), re-parses only files whose `(mtime_ns, size)` changed, drops deleted ones. API: `episodes(memory_path) -> list[IndexedFile]`, `entities(...)`, `inbox(...)`, each `IndexedFile(path, mtime_ns, size, frontmatter)`; body is loaded lazily via `IndexedFile.body()`. Consumers: `status._last_ingested_at`, `sleep_cycle._get_unprocessed_episodes` (frontmatter filter first, bodies only for unprocessed), `origin_stats.aggregate_origins`. Thread-safe via a lock; keyed by bank path.

### 4.2 Embedding function cache (`api/services/providers.py`)
`resolve_embed_fn_for_model` / `resolve_embed_fn` memoise the built `(embed_fn, model)` per `(model_id, mode)` in a module dict guarded by a lock; `SqliteVecIndexer._query_embed_fn` therefore reuses the loaded model. `lifespan` warms the active bank's query embedder in a background thread (`asyncio.to_thread`) so the first search is fast; failure is logged, never fatal.

### 4.3 Version vector + SSE (`api/services/sync_service.py`, `api/routers/sync.py`)
```
GET /sync/version → {"version": "<sha1 of components>", "components": {"entities": <mtime>, "edges": <mtime>, "hubs": <mtime>, "inbox": <mtime>, "episodes": <mtime>, "sources": <mtime>, "git_head": "<sha>", "bank": "<name>", "sleep": "<status>:<cycle_id>"}}
GET /sync/events  → text/event-stream; events: `version` (payload = the object above, sent on change, polled server-side every 1 s), `sleep` (sleep state on change), `ping` every 15 s
```
Components come from `graph_builder`'s existing `_dir_mtime`/`_mtime`/`_inbox_mtime` helpers (made public) plus `.git/HEAD` → ref file read. `ETag` middleware for `GET /graph`, `/inbox`, `/contributors`, `/sources`, `/origins`, `/banks`: the router sets `ETag: "<component-hash>"` and returns 304 on `If-None-Match`.

### 4.4 Graph payload
`GraphNode` gains `summary: str | None` (first paragraph of the `## Summary` section or the first 200 body chars, computed in `_build_full` from the cached parse) and `content_hash: str` (sha1 of frontmatter + body, so the client can diff). `_build_full` reads through `bank_index` instead of re-parsing.

### 4.5 Blocking work off the loop
`/graph`, `/status`, `/origins`, `/contributors`, `/search`, `/sources` route bodies use `await run_in_threadpool(...)` (Starlette) for the file-scanning/parsing parts. `/status` drops to: sleep state + inbox count (from `bank_index`) + unprocessed count (frontmatter only) + last ingested (max timestamp from index) + last sleep (from `.git` log cache in `sync_service`, refreshed on HEAD change) + connections (cached). Target < 20 ms.

### 4.6 Small fixes surfaced by the live check
`pricing.SUBSCRIPTION_PRICES["chatgpt-plan"]["free"] = 0.0` with label "ChatGPT Free" (Codex included); `plan_label` handles it.

## 5. App design

### 5.1 `Store` — single source of truth (`app/…/Sync/Store.swift`)
`@Observable @MainActor final class Store` holding per-domain `Snapshot<T>` values: `graph: Snapshot<GraphResponse>`, `inbox: Snapshot<[InboxItem]>`, `banks: Snapshot<BanksResponse>`, `sources: Snapshot<[SourceItem]>`, `feeds`, `calendars`, `contributors: Snapshot<[Contributor]>`, `origins`, `connections: Snapshot<[ConnectionStatus]>`, `status: Snapshot<StatusSnapshot>`, `entities: [String: Entity]` (full bodies, LRU 200). `Snapshot<T> { value: T?; etag: String?; loadedAt: Date?; isRefreshing: Bool }`. Injected once in `CicadaApp` via `.environment(store)`.

### 5.2 `SnapshotCache` — disk persistence (`app/…/Sync/SnapshotCache.swift`)
`actor SnapshotCache` writes/reads `Application Support/Cicada/cache/<bank>/<domain>.json` (+ `.etag` sidecar) off the main actor; debounced 500 ms per domain; versioned envelope `{schema: 1, etag, savedAt, payload}` so a schema bump invalidates cleanly. On launch `Store.hydrate(bank:)` loads all domains from disk **before** the first frame, then triggers a reconcile.

### 5.3 `SyncEngine` — change detection + refresh (`app/…/Sync/SyncEngine.swift`)
Owns one long-lived `URLSession.bytes(for:)` SSE connection to `/sync/events` (bearer header), parses `event:`/`data:` lines, reconnects with backoff (1 s → 30 s), and falls back to polling `/sync/version` every 3 s while disconnected. On a `version` event it compares components with the last-seen vector and refreshes only the affected domains (`entities|edges|hubs|inbox → graph+contributors+origins`, `inbox → inbox`, `sources → sources/feeds`, `bank → everything (hydrate that bank)`, `sleep → status`). Every refresh sends `If-None-Match`; 304 = no-op. Replaces the 30 s menu-bar loop, the 30 s connections poll and the per-view `.task` fetches.

### 5.4 Optimistic mutations (`app/…/Sync/Mutations.swift`)
`Store.perform(_ mutation: Mutation)`: apply `mutation.optimistic(&store)` immediately, run `mutation.request()` in a background task, on failure apply `mutation.rollback(&store)` and post `store.toast = "Couldn't … — reverted"`. Mutations: `InboxResolve`, `ConnectionTier`, `ConnectionKey/RemoveKey/Logout`, `FeedSubscribe/Unsubscribe`, `CalendarSubscribe/Unsubscribe`, `BankActivate` (swap to the target bank's cached snapshots instantly, then reconcile), `SleepTrigger` (flip status to running). Existing view models keep their method names but delegate to `store.perform`.

### 5.5 View models as projections
`GraphViewModel`, `InboxViewModel`, `SleepViewModel`, `BanksViewModel`, `FeedViewModel`, `ContributorsViewModel`, `ConnectionsViewModel` read from `Store` (computed properties over snapshots) and are all environment-injected and `@MainActor`. `isLoading` is true only when the snapshot has no value. `load()` becomes `store.refresh(.x)` (kept for pull-to-refresh buttons).

### 5.6 Graph delta transport
`GraphViewModel` keeps `lastPushed: [String: String]` (id → content_hash) and edge set; on a new snapshot it computes `added/updated/removed` node ids and edge diffs and calls `updateGraphDelta({added, updated, removed, links})` in `graph.js` (new function beside `updateGraph`; it mutates the simulation's node/link arrays in place, preserves positions, reheats at 0.3). First load and bank switch still use `updateGraph`. JSON serialisation moves to a detached task; `updateNSView` only evaluates the prepared string.

### 5.7 Instant detail cards
`Entity` stubs built from graph nodes carry `node.summary` as `markdownContent` placeholder; `EntityDetailCard` renders the summary immediately and swaps in the full body when `store.entity(id)` resolves (cached thereafter).

### 5.8 Polish
Sidebar rows → `Button` with `.keyboardShortcut` (⌘1…⌘9), AX labels; `APIClient.loadToken()` cached after first success (invalidate on 401); `GraphViewModel`/`InboxViewModel` become `@MainActor`; `NSImage(contentsOf:)` loads memoised in a static cache; `FeedViewModel` never wipes items on error.

### 5.9 In-app Ask (G52)
`AskPanel` opened with ⌘K (and a search-bar "Ask" toggle): question field → `POST /ask` → answer rendered as markdown where each citation becomes a `[[wikilink]]`-style chip; clicking opens the entity (via `store.entity`); `gaps` listed beneath as "I don't know: …"; recent questions persisted per bank in `SnapshotCache` (`ask-history.json`). Degrades honestly when no LLM connection: citation-only answer (already what `/ask` returns).

## 6. Non-goals
Offline write queue across launches; multi-client conflict resolution; WebSockets; server-side per-client cursors; changing the memory format.

## 7. Testing
Python: hermetic tests for `bank_index` (tmp dirs, mtime edits), embed cache (fake factory called once), `sync_service` version vector (changes when a file changes, stable otherwise, git HEAD read), SSE endpoint (TestClient stream first event), ETag 304, `/status` no longer parsing bodies (assert parse count via monkeypatch), pricing free plan. Swift (`CicadaAppTests`, target added here): `SnapshotCache` round-trip, SSE line parser, graph diff, mutation rollback, version-vector domain mapping. Views build-verified + live smoke via the harness (window capture) with timings.

## 8. Success criteria (measured at the end)
`/status` < 30 ms, `/search` < 200 ms warm, `/origins` < 50 ms cached; tab switch renders in the same frame with data; bank switch shows the cached bank instantly; inbox resolve removes the card immediately and survives a failed request with a rollback; after a Sleep cycle the graph updates in place without a full re-layout.
