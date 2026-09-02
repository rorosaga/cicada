# Capture "+" redesign, Plans & keys clarity, entity logos, import walkthrough links (G62, G63, G59, G64)

**Status:** approved for implementation 2026-08-30 (Rodrigo: "go ahead and work on all these things until done").
**Backlog:** G62 (Capture page), G63 (Connections copy + naming), G59 (entity logos), G64 (walkthrough links; recordings deferred).

## 1. Capture page — connected list + "+" (G62)

### 1.1 Backend: `GET /sources/channels`

One endpoint the page can render from, replacing inference from transient button results. Returns:

```json
{
  "channels": [
    {"id": "rss", "label": "RSS feeds", "connected": true, "count": 3,
     "last_sync": "2026-08-30T08:12:00Z", "detail": "3 feeds · polled 2 h ago",
     "actions": ["poll", "manage"]},
    {"id": "calendar", "label": "Calendars", "connected": false, "count": 0, "last_sync": null, "detail": null, "actions": ["poll", "manage"]},
    {"id": "bookmarks", "label": "Chrome & Safari bookmarks", "connected": true, "count": 412, "last_sync": "...", "detail": "412 bookmarks · synced yesterday", "actions": ["sync"]},
    {"id": "notes", "label": "Apple Notes", "connected": false, ...},
    {"id": "telegram", "label": "Telegram bot", "connected": true, "detail": "Bot configured · 18 captures", "actions": []},
    {"id": "chat-export:claude", "label": "Claude chat export", "connected": true, "count": 1730, "detail": "1,730 conversations · imported 2026-06-18", "actions": ["import"]},
    {"id": "chat-export:chatgpt", ...},
    {"id": "files", "label": "Files & links", "connected": true, "count": 57, "detail": "57 saved items", "actions": ["import"]}
  ]
}
```

- `connected` is **derived from persisted state only**: feeds/calendars = registry non-empty; bookmarks/notes = a `last_sync` entry exists in a new `<memory>/sync_state.json` (`{"bookmarks": {"last_sync": iso, "count": n}, "notes": {...}}`) written by the sync endpoints on success; telegram = `CICADA_TELEGRAM_BOT_TOKEN` set; chat exports & files = origin counts from `origin_stats` (`origin` values `claude`, `chatgpt`, `telegram`, `bookmark`, `rss`, …).
- `last_sync` for feeds/calendars comes from the registries' per-feed `last_polled` if present, else null.
- ETag via `sync_service.etag_for` with the same extra-digest pattern the other list endpoints use; the `sources` domain of the version vector covers it (the `sync_state.json` mtime is added to that domain's components).
- The app `Store` gets a `channels` domain (`Snapshot<[SourceChannel]>`, cached on disk like the others, refreshed with `.sources`).

### 1.2 Page layout

`SourcesView` is rewritten (target ≤ 450 lines; the old sub-views that still apply are moved to `Views/Capture/Sheets/`):

1. **Header**: "Capture" / "What Cicada reads from. Add a source with +." with a trailing **`+`** button (circular, accent) — ⌘N while the page is focused.
2. **Connected** list: one compact row per `connected == true` channel — logo/icon in a 28-pt circle, label, `detail` in secondary text, a trailing ⋯ menu with the channel's `actions` (Poll now / Sync now / Manage… / Import another file / Remove). Rows are `Button`s (accessibility labels), sorted by `last_sync` desc. When nothing is connected the list is replaced by an empty-state card: icon, "Nothing connected yet", "Add a chat export, bookmarks, a feed or a calendar." and the same `+` button.
3. **Queue** card (unchanged: unprocessed count + Consolidate now).
4. **Origins strip** (unchanged, moved below the queue).

The RSS/Calendars sections with sample URLs and the Synced-apps prose are removed from the page.

### 1.3 The "+" picker sheet

`AddSourceSheet` — a grid of tiles, each `{icon/logo, title, one-line description}`:

| Tile | Action |
|------|--------|
| Chat export (Claude, ChatGPT) | File picker → existing upload flow; the tile expands first into a **walkthrough panel** (§4) |
| Bookmarks file (HTML/JSON) | File picker → existing flow |
| Paste a link | Text field → `POST /sources/save` |
| RSS feed | Text field → `POST /sources/feeds` |
| Calendar (webcal/ICS) | Text field → `POST /sources/calendars` |
| Chrome & Safari bookmarks | "Sync now" → `POST /sources/sync-bookmarks` (shows the result inline) |
| Apple Notes | "Sync now" → `POST /sources/sync-notes` |
| Telegram bot | Instructions card (bot token env var, `/save`, `/note`) + "Open BotFather" link |
| Instagram saved / YouTube playlists | File picker (existing importers) with walkthrough panel |

Explanatory copy lives **only** in this sheet. "Manage…" from a row reopens the sheet on that tile with the current list (feeds/calendars show their rows with remove buttons there).

## 2. Plans & keys / Agents (G63)

### 2.1 Naming

- Sidebar **Connections** → **Plans & keys** (⌘8 keeps its slot), page title "Plans & keys", subtitle "What Cicada bills against. Subscriptions sign in through their own CLI — Cicada never sees the token."
- Sidebar **Connect** → **Agents**, page title "Agents", subtitle "Wire your AI agents into Cicada over MCP so they read and write your memory."
- Sidebar section label stays "Setup". Accessibility labels and ⌘-shortcut hints follow the new names. `ContentView` tab enum cases keep their identifiers (no cache invalidation).

### 2.2 Card copy

Each `ConnectionCard` gains a **"How it's connected"** line under the price line, per adapter (`ConnectionStatus.how` from the backend, so the copy is defined once next to the probe):

- Claude plan: "Signed in to Claude Code on this Mac as `<email>`. Cicada runs its memory work through the `claude` CLI on your plan — it never sees your token."
- ChatGPT plan: "Signed in to Codex CLI on this Mac. Cicada runs through `codex exec` on your ChatGPT plan."
- BYOK: "Key stored in `~/.cicada/secrets.env` (0600); billed per token by <provider>."
- Ollama: "Local models at `localhost:11434` — free."

Plus a **"Powers"** line (`ConnectionStatus.powers: [str]`, from the registry's engine assignment): e.g. "Sleep extraction · Ask · clarification wording" for the engine currently selected, "Standby" otherwise. The Max tier picker is relabelled "Your Max tier (for cost estimates only)" and appears only when `plan == "max"`. The "Not connected" Claude card explains the one-liner to run (`claude auth login`) with the existing Terminal hand-off.

## 3. Entity logos (G59)

### 3.1 Backend

- `api/services/logo_service.py`:
  - `domain_for(entity) -> str | None`: explicit `logo:` frontmatter (URL) short-circuits; else first `url`-kind `sources:` entry (G61); else first `## Links` URL; else `media.url`; else a heuristic map for `company`/`tool` names (`slug(name) + ".com"` **only** when a `website` claim exists or the name is a single token and the DuckDuckGo probe returns a real icon — never for `person`).
  - `fetch_logo(domain) -> bytes | None`: try `https://<domain>/apple-touch-icon.png`, then parse `<link rel="icon"|"apple-touch-icon">` from the homepage, then `https://icons.duckduckgo.com/ip3/<domain>.ico`; 4 s timeout, ≤ 512 KB, converted to PNG (Pillow already in requirements? — verify; if not, accept ICO/PNG/SVG passthrough with the correct `Content-Type`), refuses images < 16 px.
  - Cache at `~/.cicada/logos/<bank>/<entity-id>.<ext>` + `meta.json` (`fetched_at`, `etag`, `domain`, `miss: bool`); TTL 30 days for hits, 7 days for misses; never inside a bank.
  - `CICADA_ALLOW_LOGO_FETCH` defaults on; tests run with it off and use injected fetchers.
- `GET /entities/{id}/logo` → `FileResponse` with `ETag`/`Cache-Control: max-age=86400`; `404` when no domain or a miss. Fetch happens on first request (bounded by an in-process semaphore of 4) so the graph never blocks; `GET /graph` nodes gain `has_logo: bool` from the cache index only (no network in the graph path).
- Sleep: a tail step `warm_logos(bank, limit=50)` fetches missing logos for the highest-degree `company`/`tool` entities so the common ones are ready before the user opens them.

### 3.2 App

- `LogoImage` gains an `entity:` initializer: source order = remote (`GET /entities/{id}/logo`, disk-cached under `~/Library/Application Support/Cicada/logos/<bank>/`) → monogram fallback (initials on the entity-type color, white text). Always rendered as a **circle** with a 1-pt hairline ring; sizes 20 (list rows), 28 (inbox title), 40 (detail card header).
- Rendered in: `EntityDetailCard` header (leading of the name), `InboxCardView` title row, search results rows, Ask citations chips (20 pt).
- Graph: nodes with `has_logo` draw the cached image clipped to the circle at zoom ≥ 1.2 (canvas `drawImage` with an in-memory `Image` cache fed by `GraphView` pushing data URLs for the visible top-N); below that zoom the plain disc stays (performance). Off by default behind the existing graph settings toggle "Show logos".

## 4. Import walkthrough links (G64, buttons + steps only)

In the `+` sheet, the Chat export tile (and Instagram/YouTube tiles) expands into a **walkthrough panel**: a segmented picker (Claude / ChatGPT / Google Takeout / Instagram), a numbered 3–4 step list per vendor, an **"Open <vendor> export settings"** button (`NSWorkspace.shared.open`) to `https://claude.ai/settings/data-privacy-controls`, `https://chatgpt.com/#settings/DataControls`, `https://takeout.google.com/`, `https://accountscenter.instagram.com/info_and_permissions/dyi/`, and a drop target / "Choose file…" button. A reserved 16:9 area shows the walkthrough video when a bundled `Resources/walkthroughs/<vendor>.mp4` exists (AVPlayer, muted, looping) and a static illustration placeholder otherwise. Recording the videos is a separate manual session (documented in `docs/walkthrough-recording.md`: Screen Studio or `screencapture -v` + cursor zoom, ≤ 2 MB, 1280×720).

## 5. Testing

- Pytest: `/sources/channels` derivation for each channel (registry fixtures, `sync_state.json`, env var, origin counts), ETag/304, `sync_state` written by sync endpoints; `logo_service.domain_for` ladder incl. the person guard; `fetch_logo` with an injected fetcher (touch-icon hit, HTML `<link>` parse, DDG fallback, miss caching, TTL expiry); `/entities/{id}/logo` 200/304/404; `ConnectionStatus.how/powers` present for every adapter.
- Swift: `SourceChannel` decoding and row sort; `AddSourceSheet` tile catalogue completeness (one tile per channel id the backend knows); walkthrough URL table; `LogoImage` monogram initials logic (pure function); Store `channels` domain cache round-trip.
- Live: Capture page shows only connected rows on the `claude-chats` bank; `+` sheet flows for RSS and Paste link; Plans & keys copy visible; MongoDB entity shows its logo in the detail card and inbox row.
