# The companion app

Moved word for word from `CLAUDE.md` on 2026-10-01, when that file passed Claude Code's size limit (it is loaded into every
session). **`CLAUDE.md` keeps the rails and the map; this file keeps the detail.** A rail stated there binds here too. When
a change makes this file wrong, update it in the same PR (repository paths below are relative to the repository root).

The user-facing management layer for inspecting and curating the graph — it makes the system
observable rather than a black box. **The app is NOT the primary interaction surface** — that's the
chat, via MCP.

**Stack:** native SwiftUI macOS app; FastAPI backend at `localhost:8000` spawned as a child process
on launch (`Process()`) and terminated on quit; graph rendered with d3-force in a `WKWebView`.
SwiftUI→d3 via `evaluateJavaScript()`, d3→SwiftUI via `postMessage()`.

**Ruling (G109, 2026-09-02) — d3-force stays.** Evaluated against sigma.js/ForceAtlas2, Pixi,
cosmos, ngraph and d3-force-3d at ~1,900 nodes: the two G109 symptoms were three local bugs in how
`graph.js` drove d3-force, not a library problem. The only flip trigger is an in-app p95 frame time
above 16.7 ms on the live bank, or a graph well past ~10k nodes. **Two rules follow:**

1. **Every custom force multiplies by the `alpha` d3 passes it** (a guard that only removes energy
   is the one exception).
2. **The release path never bumps alpha** — a throw coasts on velocity, not on a hot graph.

`app/CicadaApp/Tests/graph/graph-physics.test.js` (real d3, real `graph.js`) is the regression net;
a KE/node plateau at tick 400 is the signature of a force that broke rule 1.

**Sync engine.** One `Store` holds a `Snapshot` per domain, hydrated instantly from a per-bank
on-disk cache before the first network round-trip, so the app renders real data cold even with the
backend down. A `SyncEngine` holds one SSE connection to `GET /sync/events`, reconnecting with
backoff and falling back to polling while disconnected; each `version` event refreshes only the
changed domains, always with `If-None-Match` so an unchanged domain costs a 304. View models are
thin projections and **never blank** — always last-known-good. Writes go through a `Mutation`:
optimistic apply, rollback with a toast on failure. **The graph receives deltas, not a full
re-layout**, so d3 node positions survive a Sleep cycle or a live edit.

**Ruling (2026-09-28, TODO ruling 12): plan usage and model prices show on the Sleep page's Details and its engine
menu — and nowhere else yet.** This supersedes the 2026-09-03 ruling ("prices and token usage are not shown anywhere
in the app") for those two surfaces only: no cost tiles, no `$`/token columns and no cost-per-day chart elsewhere, and
the `/consumption/*` endpoints are unchanged. Every figure states its basis in words ("charged", "at list price", a
plan window's share) and a plan's before → after carries the honest limit that it covers all use of the plan
(`CycleUsageText`, `UsageFormat.currency`).

**Navigation (Direction D, DS-1).** A 56 pt icon rail (`Views/Shell/NavRail.swift`): Home, Graph, Clusters, Feed,
Sleep, Inbox, Sources, Projects at ⌘1–8 in `AppTab.allCases` order (`RailItem`; a page switch is instant), each cell's tooltip
naming its page and shortcut (450 ms, then instant while warm), selection by brightness and one neutral fill
(`bgSelected` — never the accent, `SelectionTintLintTests`), the Inbox count a neutral `bgBadge` numeral, a spinner on
Sleep while a cycle runs, the gear and the sun/moon toggle at its foot, no wordmark. ⌃⌘S or the titlebar toggle swaps it
for a 208 pt labelled sidebar, remembered per viewer (`cicada.shell.labelledSidebar`). Relaunch restores the last tab:
nothing stored, or a value no build knows, opens Home, and a stored Graph stays on Graph; `AppTab` raw values are the
persisted identity and `AppTab.restored(from:)` maps retired ones. **The titlebar is a SwiftUI toolbar** with the
title hidden (AppKit keeps the drag area in every gap): the sidebar toggle after the traffic lights; the **command
bar** centred — the memory-bank selector (`BankSwitcher`, moved from the Graph page; the only switcher view in the
app, `SingleBankSwitcherTests` — the palette's "Switch to <bank>" row and the intake card's switch act on the same
`BanksViewModel` in the same window) and "Search your memory ⌘K", which opens the find palette through
`AppRouter.requestPalette()`; and the visible page's `?` at the right (`HelpContent.page`), one per window. macOS 26's
toolbar platter is hidden (`ChromeToolbarItem`). **Settings is a panel inside this window (DR-33)**: ⌘,
(`ShellCommands`, which opens the window first if none is) and the gear open it over a scrim — 880 × 620 at 1×,
inset ≥ 40 pt — with a `bgPane` sidebar that starts with a `CicadaSearchField` and groups its rows as Cicada ·
Customize · Engines & keys (`SettingsGroup`, G139) — Cicada: General · You · Privacy & data · Memory · Sleep;
Customize: Integrations · Reading the web · Agents · From anywhere · Skills; Engines & keys: Engines · Plans & keys · Advanced — and each
page's own header with an `esc` keycap and a close ×. It is modal: the shell under it is inert, ⌘K waits, Esc and a
scrim click close it. `AppRouter.openSettings(_:row:)` is the one door (`SettingsSectionLink`, the gear, ⌘,), every
hand-off to a page closes it, and `cicada.settingsSection` is only its remembered selection — the `Settings{}` scene
and its cross-window seeds are gone. Privacy & data exports a bank and moves one to `<root>/.trash/`, but never
switches banks (that is the command bar's); Memory has no "Look for duplicates" until the dedup endpoint stops
blocking the event loop and commits what it merges (R-O17). Memory also holds
G147's *How things fade*: pace suggestions from the person's own "Still tracking…?" answers
(Apply · Not now — the latter per viewer) and each chosen per-type pace (Reset). Search is `SettingsIndex` over `QuickMatch` — the
palette's one ranker — and landing always selects, scrolls, washes (the selected fill and the focus ring) and
announces the row (G139). `SettingsSection` raw values did not move. General's appearance offers System, which
follows the Mac's own light/dark through one app-scope observer (`ThemeStore.observeSystemAppearance`). General (F-10:
Look · Startup · When Cicada is closed) also holds Scene (four choices, the clock's scene beside it), Open Cicada at
login (`LoginItemService` over `SMAppService.mainApp`; an unsigned build that macOS does not keep says so), Show in
menu bar (per viewer, on by default; hides the 18 × 18 menu-bar bookworm (ruling 18), the Dock icon stays); a login launch opens no
window — the bookworm waits in the menu bar, and the Dock icon brings the window (`LaunchKind` from the 'oapp' event,
`LaunchState`, R-OB18) and Keep memory working when
Cicada is closed (`BackendAgentService`: a read-only `launchctl print`, and Install runs
`scripts/install-backend-agent.sh` from the app's own checkout after the click, `CICADA_CAPTURE=off`, then hands
launchd the port). ⌘K and ⌘F are
menu commands in `Support/FindCommands.swift` (`HiddenShortcutLintTests`); ⌘, and ⌃⌘S live in
`Support/ShellCommands.swift`. Track P's audit removed the global Sleep button, because a cycle starts from the Sleep
page's one Consolidate control (G125 R10) or the menu-bar bookworm.
**One intake (Track I, spec decision 13).** Every way a file arrives — a drop anywhere on the
window, the Dock icon, File → Import… (⌘⇧I), the menu-bar worm's *Import a file…*, an empty state,
each `+` chat tile, the Sleep room's worm — goes through one `IntakeRouter`: sniff (`POST /intake/sniff`, stages nothing) →
preview (counts, date range, new · grew · already here, skipped files by name, *Into* a memory) →
import (`POST /intake/import`; a 202 and a job counter above 10 episodes) → a *what happens next*
card that never closes on its own. `UploadOverlay` and the Feed's Upload button are gone; the router
owns `Store.intakeInFlight` through a counter of requests in flight. The card's *Read now* is G125
R10's first narrow amendment: a user trigger, subtitled with the manual engine like Consolidate,
shown only when an engine can run and the import landed in the active bank. **Every
`IntakeRouter` door refuses the same roots** (`IntakeRouter.feedGuard`, Track Z): a drop that
resolves under `~/.claude`, `~/.codex` or `~/.cicada` (or `$CLAUDE_CONFIG_DIR`, `$CODEX_HOME`,
`$CICADA_HOME`) is refused before any folder is walked, a refused root met inside a dropped folder
is never descended into and refuses the drop, a drop with nothing export-shaped in it is refused by
name, and nothing is sent; `accept` answers (`IntakeAcceptance`) so the Sleep room tells a refusal
in its worm's words while every other door shows it in the panel. Three pickers still sit outside
the router — the Add-source walkthrough's drop and *Choose file…*, its saved-content picker, and
Settings' local-folder picker — and check only the chosen file or folder
(`IntakeRouter.refusedRoot(of:)`); a watched folder that *contains* a refused root is still walked
(open, G125).

**Home (G108; Direction D, DS-3b; F-09, round 4).** The front door at ⌘1: a 208 pt living band —
`PaintedScene(.hero(band:))`, the one component Home, the Welcome and onboarding's panes share (C10) — painting the
person's Scene (Settings → General: Automatic · Day · Afternoon · Night; Automatic follows `SceneClock`, NOAA's sun
over the Mac's time zone's tzdb point, no location; the afternoon is the last two hours before sunset through civil
dusk), never the theme (G144); its meadow line at two thirds of the band, faded into the window from 72 %. Slow
one-way clouds, grass swaying from its roots, seeds by day, fireflies and stars by night and a slow camera breath run
in one `TimelineView` at ≤ 30 fps (15 under Low Power) that rests while the window cannot be seen, while the Welcome
covers the shell and off-tab; Reduce Motion or Low Power make it gentler, never frozen (DR-66); a scene change
crossfades the same composition in 1.2 s. Under it, "What would you like to remember?" as a `PageTitle` — text never
sits on paint — then the palette's own `FindPanelBody` in `.page` placement in a 640 pt block: a second
`FindPaletteModel` sharing the one Ask and keeping no recents; ⌘K on Home focuses it, a pasted `http(s)` link offers
*Save this link*. Below it, in one 760 pt column: Getting started (while it lasts), Today (one row to Sources:
captured today, UTC, with the three busiest origins' marks, names and counts), Needs you (the Inbox's kind glyph,
question and age, *Open Inbox* at the label's right, landing in STATE 1) and Last read (the newest Sleep commit, its
pages as `Tag`s) — each number once, each a link to the page that owns it; the waiting count links to Sleep, never a
Consolidate. Right after onboarding ends (Open Cicada or *Set up later*), *Make it yours* (Appearance and Scene; `AppearanceTipPolicy`, per
viewer) sits beside the column where it fits, else atop it; once hidden it lives only in Settings.

**Onboarding (G145, round 4 phase B).** Six pages in one full-window layer, raised by the unchanged `FirstRunGate`
(unknown is never empty) or by the one door, `OnboardingState.reset` + `AppRouter.requestFirstRun` (Settings →
General's *Run setup again*, the demo's *Finish setting up*): Welcome and You're set on the full living painting
with a card (`WelcomeHero`); Import, Agents, Who reads and Keep it running in a split frame — the page's pane
painting (`OnboardingPane`, 540 pt, which gives way before the column does), the column with "Step n of 6 · k still
coming in", Back and one primary (⏎ never animates). Get started is the owner PUT, alone and first; after it **a
tick starts that source at once** through the one turn-on (`FoundTurnOn`; app-side sources register an
`AppSourceDriver`), an untick stops it keeping up and keeps what came in, and × shows only where a run can stop
(a browser's; a chat export shows its progress and never an ×). Nothing is pre-ticked and nothing is read before a
tick. The Import rows are one table (`ImportCatalog`: supported installed browsers, Calendar, Apple Notes — a
one-time read — Wispr Flow when present, the chat drop zone and *See how* per provider, a drawn walkthrough over
`ExportWalkthrough`'s data opening `WalkthroughVendor.exportURL`; its clock is `ExportWalkthrough.cadence` — paused
while the window is hidden, one frame per step under Reduce Motion, the painted scenes' cadence halved under Low Power,
audit A11); Contacts sits under *Calendar & contacts* and
Chrome's open tab groups as a sub-row under Chrome (only where Chrome is), each one `ImportEntry` and one driver over
its own reader (`ContactsReader.connect`, `TabGroupWatcher.enable`), which Home's Getting started registers too. Every row, the topbar's count, You're set and Home's Getting started read one projection,
`SetupProgress`, over `SetupRunner`, `SyncActivity` and the channels. Agents reuse `AgentSelector` /
`AgentSetupSteps` with a live ✓; Claude Code's and Codex's *Connect for me* here also turns on *Remembers
automatically* (its commands shown first; Settings → Agents keeps it its own click). Who reads is `EngineChooser`,
writing only on a click; Keep it running holds the same switches as Settings → General and turns none on. You're
set shows one public-domain quote (`MemoryQuotes`, G153, kept per install) and Open Cicada marks the bank, records
the connected agents, asks `TourOffer` and lands on Home. *Set up later* and *Try the demo* (`SetupRunner.demoPlan`)
remain; export reminders (`ExportWaits`) ask for notification permission only when a delay is chosen. Getting started
continues on Home — the first read (*Read now*, G125 R10's second narrow amendment, only inside the card) and "Keep
reading on its own?" asked once of a person still on `manual`, its options gated by ruling 4.

**Settings → Engines: the engine picker (G122, Track E; moved by G139 A3).** A row of cards with real marks — Auto,
Claude plan, ChatGPT plan, OpenRouter, Ollama (tagged *Local*), API key — over the connections registry's candidates writes
`PUT /sleep/engine`, which lands in the same bank-independent `~/.cicada/connections.json` prefs
`use_for_sleep` already uses, never `api/.env`. A plan card is selectable once that plan is signed
in. The card shows both `preview.manual` and `preview.scheduled` lines rather than hiding **ruling
4** (a scheduled cycle never spends Claude *or* ChatGPT plan quota — `engine_select.SUBSCRIPTION_MODES`)
— the asymmetry stays visible, not silently applied. *Keep going on extra usage* (off) is the only
way a Claude cycle continues past the plan's included usage; otherwise it stops with one plain
sentence and the reset time. Ask follows the same choice. The ChatGPT plan runs as `codex exec` in
Cicada's own Codex home (`~/.cicada/codex`), signed into in-app with a device code; Cicada never
opens that home's files — `codex app-server` answers plan, limit and models.
`EngineChooser` is the component (`EngineCard` wraps it for onboarding); the Sleep page's quick engine
menu (beside Consolidate) reads and writes the same `PUT /sleep/engine` through the same
`SleepEngineViewModel` and the same write rule (`EngineWrite`), and shows both previews — "When you
start a cycle" / "Scheduled cycles", the one wording app-wide. The Claude plan's old *Use for Sleep* switch moved here too —
same `use_for_sleep` pref, same endpoint — but `engine_select.resolve_llm_mode` reads that pref only
when the chosen mode is `byok`, so it shows only while the API key card is chosen, as *Use my Claude
plan when I start a cycle*, and a flip reloads the chooser's preview. Plans & keys is credentials
only: the Max-tier cost-estimate picker is gone (prices live on the Sleep page, ruling 12).
**Who reads (round 4, R-AG10…R-AG14).** OpenRouter is its own card: *Sign in with OpenRouter* (PKCE, the nonce in
the callback path) or *Paste a key instead*; under the hood it is `byok` with an `openrouter/` model, so ruling 4 is
unchanged and `PUT {mode: "openrouter"}` is a 422 — every card becomes a mode through `EngineWrite.mode(of:)`, and
`selected` on the wire names the card. The API key card is a provider picker (Anthropic, OpenAI, Gemini, xAI, Groq,
Mistral), each writing its tested default model and offering its key field in place; a key's model pins its judge.
Ollama wears a *Local* tag and no card says "slower". Under the cards, `LeavesMacNote` — a pure function — says
where reads leave the Mac and to whom, only for engines that send data out (never Ollama, nor Auto resolving to it).
A preview line or the Sleep page's button that runs on an `openrouter/` model names and marks OpenRouter.

**Settings → Integrations (G126).** A categorized, logo-first page over the existing
`GET /sources/channels` registry — no new adapters, just a frame. The rule this page draws: a
*standing* connection (sign in once, polled on the Sleep tail, disconnect here) lives in
Integrations; a *one-shot* import (drop an export, sync a folder once) stays where it already was,
behind the Feed's `+`. Both read the same `channel_registry`, so a channel never drifts between the
two surfaces. Round 3 added **Notes & files** (Apple Notes, every watched folder, *Add a folder* and,
when Obsidian is installed, *Obsidian vault*) and **Voice & meetings** (Wispr Flow once it is on this
Mac) — both standing connections, so both live here; their marks are the installed apps' own icons.
Harness rows wear their app's real mark ("Other agents" a neutral glyph); a folder's Manage, Wispr
Flow and a connector's Connect/Manage open as sheets (`SettingsSheet`), never popovers; the
add-folder sheet labels its fields and asks which subfolders an agent wrote as a checklist
(`AgentFolders`), the wire still a `<folder>/**` glob (DS-3b). **Browsers (round 4, C9)** are drawn
from `BrowserInventory` — the browsers on this Mac by bundle id, each with its installed icon: Chrome,
Safari, Brave, Vivaldi, Comet and Dia as `SourceRow`s (Turn on / Sync now, or Try again with the
Full Disk Access fix under Safari when a read was refused, 'Last synced …'); under Chrome, *Open tab groups* is a
sub-row with its own switch and the open groups as tags in Chrome's colours (G160); and the ones Cicada cannot sync
yet (Arc, Firefox, Edge, Opera) named once in the header, never as a row. Safari's source page groups its items as
Recently saved · Favorites · Other bookmarks. **Calendars, contacts & feeds** offers Calendar on this Mac and
Contacts (G154), both app-owned rows.

**Agent wiring (Track I T3/T7).** `GET /agents/wiring` is read-only: per harness it reports
*recall* (the MCP server registered — `claude mcp get cicada` / `codex mcp get cicada --json`, 6 s
each and side by side (round 4: at 2 s the live Welcome read Claude Code as 'couldn't check in
time'), a timeout is `unknown`) and *auto-save* (the G105 Stop hook, via `api/hooks/registry.py`; an
unparseable settings file is `invalid`, never `off`), *auto-recall* (G149: `autorecall`
= `on|off|stale|invalid|n/a` for the recall hooks, with `autorecallOn` / `autorecallOff` argv kept apart from
`connect`: onboarding's *Connect for me* for Claude Code and Codex runs `connect` and then `autorecallOn` (every command
shown before the click), and Settings → Agents → *Remembers automatically* keeps its own click), plus the exact
argv install.sh would run. The **app** runs them, only after the person's click (spec decision 14, D-1), with
`CICADA_CAPTURE=off`, behind an allowlist pinned to its own checkout (which also accepts the recall hook's two
events and `registry.py uninstall --hook recall`); the backend never writes a harness root. `GET /agents/setup?harness=` (round 4 C5, G76's in-app half) serves what to hand an
agent instead of running anything:

- for Claude Code, Codex and Gemini CLI, a plain prompt (≤ 1,200 characters) that names the exact
  commands, built by the same step builders `/agents/wiring` uses (both steps always,
  `display == shlex.join(argv)`);
- for Cursor, its install link;
- for the Claude app, a config merge the APP performs.

No probe, no subprocess, no ETag.

Settings → Agents (round-4 D5) adds, per harness, Connect for me (the same `AgentConnect.run`), Copy
setup prompt (`GET /agents/setup`'s prompt shown verbatim, then copied — the agent runs the install itself), Open in
Cursor (the catalog's own deeplink) and Set up Claude (`ClaudeDesktopConfig` merges `mcpServers.cicada` into Claude
desktop's config: backup first, merge never replace, an unreadable file left untouched; the app computes the path and
the value itself). Round 4 C8: Settings → Agents is one selector of ten agents (`AgentCatalog`, pinned to
`agent_live.LIVE_AGENTS` by `api/tests/fixtures/agent_catalog.json`) with numbered steps below (`AgentSetupSteps`),
reused by onboarding. OpenCode, Hermes and OpenClaw register by editing their own config from a pasted prompt — Cicada
runs nothing for them and only reads that file (`agent_wiring.config_state`, ≤ 256 KB, parse-only); Claude, ChatGPT and
Grok go through From anywhere (`kind: remote`). `GET /agents/live` lights a pill's ✓ from the local handshake ledger
rows, a used connector (`last_used_at`) or the agent's own config — no subprocess, never `~/Library`, never
`~/.claude.json`; polled every 3 s while the page is visible.

**Settings → Skills (G138).** A reviewed catalog (`api/data/recommended_skills.json`: source,
licence, the reviewed commit and SKILL.md hash, needs, agents, a terms note, the Cicada tool it
bridges; `scripts/verify-skills.sh` re-checks it) served by `GET /skills/recommended` — at most
five not-installed entries by rank, install state derived per request from `SKILL.md` files and
Claude Code plugin ids, never an agent's config. **The backend never installs anything.** The app
runs only the agent's own installer (`claude`, `codex`, `npx skills` pinned to the reviewed
commit), after a consent sheet that shows the exact command, as an argv with
`CICADA_CAPTURE=off`; hosted MCP servers are copy-only. The app writes files only for Cicada's
own `cicada` and `cicada-librarian` (`SkillInstaller`, a `.cicada-managed.json` marker, never
over a changed copy). The handshake gains a capability line only for an installed, active bridge
whose tool exists: papers (`cicada_save_url`), video (`cicada_record_watch`) and meetings
(`cicada_save_episode`, one `speaker:<name>:` line per utterance, never `user:`) are active;
documents stays off until something says who wrote a document (F2-back R-B14).
**Role skills and the `agent-prompt` method (G166).** An entry may carry `roles` (`reading` | `watching`), the
`invoke` name the agent sees, a `pageName`, a catalog-authored `pageSummary` and a plain `reach` line, and its install
`method` may be **`agent-prompt`**: a text (≤ 1,200 characters, pinned to the reviewed version, no global trigger, "ask me
before any permission") for the person's own agent to run upstream's installer, so the plan is copy-only (`runnable: false`,
no steps, `prompt`) and `PROGRAMS` gains nothing — a bare `npx skills add` would copy the SKILL.md and leave the CLI the
skill drives missing, a half install that would read "installed". `browser-harness` and `macos-harness` (pinned, hash
verified by `scripts/verify-skills.sh`, whose `--print-urls` is pinned offline) are offered for reading and watching, each
with a `terms` line; `macos-harness` states plainly that it can control the whole Mac. Choosing one is Settings, How your
agent reads (`agent_methods`), not an install.

**Sources page — v2 in Direction D (G124, DS-3c).**
- **What stays from v2.** Every tile keeps Sources v2's five facts: mark · brand name · one status verb
  (`SourceLiveness`, no backend field) · a 14-day capture sparkline + lifetime total · four week-dots + delta.
  **Two nouns, never one**: the big number is the row's own unit, and the line and the delta are always
  *captured*. Every number goes through `UsageFormat.count` on the viewer's locale (`CountLiteralLintTests`).
- **D's material.** A tile is 96 pt including its padding, on `bgFocus` with a ring, the strong ring and a 1 pt
  lift on hover, and no shadow. It is clipped to its shape. Its mark stands bare. A failure speaks in `warning`
  with its dot hidden, and a live source keeps a green dot.
- **Packing.** One column count (`SourceGridColumns`, 2–4) is shared by every section. Sections share a row by
  span (`SourceGridPacking`), and the contributors block takes what the last row leaves when that is two columns
  or more.
- **Detail columns.** Opening a source, or an author in *Who wrote your memory* (a chip strip over a neutral,
  labelled share bar), narrows the page to a list of rows and opens it as the detail column (`SourcesSelection`,
  `SourceDetailView`, `ContributorDetailColumn`). A conversation's Reader is the third column.
- **What changed from v2.** The contributor drill-down is a column, not a sheet, so its "from conversation" is
  never under a modal. A compact G129 light never draws the Full Disk Access fix
  (`BrowserStatusLight.showsFixHint`); the fix lives in the source's detail column. *Advanced statistics* is a
  remembered disclosure on the old toggle's `cicada.usageMode` key. "Add a source" is a neutral button in the
  eyebrow row, which reads "Sources · n connected".

**Source rows and last sync (round 4).** Every source that keeps up renders one `SourceRow`
(`Views/Common/SourceRow.swift`) from a pure `SourceRowModel`: the bare mark, name and what it reads, what came in
(`SourceRowText.countLine`: the count in the reader's locale and the channel's `parts`), and on the right 'Syncing now'
with an × or 'Last synced 2 minutes ago' (the persisted `lastSync`, re-read every 30 s; an import says 'Imported …').
× cancels the run only (R-SR11). Sources' detail column, the browser, tab-group and Contacts rows in Integrations, and
Home's Getting started rows use it. `BrowserWatcher`, `TabGroupWatcher` and `ContactsReader` report their runs into
`SyncActivity`; `LocalSourceWatcher` and `CalendarReader` keep their own lights (R-SR17).

**What came in, by name (G161).** Under a source row, a "What came in" disclosure (collapsed, remembered per viewer
per channel, `cicada.sources.capturedOpen.<channel>`) lists the items that source brought in by their own title and
day, newest first, twenty at a time with "Show more" (`CapturedItemsList`): under onboarding's Import rows (a preview —
the rows open nothing there), under every Integrations row, and as the Sources detail column's content for a source
whose items are not saved links. `GET /sources/channels/{id}/items?offset&limit` (≤ 200; `api/services/channel_items.py`)
derives it at read from the same set the row's count means — the notes index, the calendar and tab-group episodes (never
a tombstoned one), the bookmark seen-set joined to the url index, a channel's media pages, a folder's files — engine-free
and read-only; titles only (scrubbed, one line), never a body, and for Contacts the matched page's name only. Its
`total` is its own count, not a promise to equal the row's (a notes index keeps a deleted note). It ETags over
`sources`+`episodes`+`entities` with the channel and page in `extra`, and is **not** a Store domain: `ChannelItemsCache`
keeps it in memory, revalidates when the list opens or the channels move, and empties on a bank switch. A row opens its
episode in the Reader, a saved item in the Feed, a person in Clusters.

**Clusters and the Feed (Direction D, DS-3c).** Both are list pages in progressive columns: an eyebrow row with
text tabs (`AdaptiveTextTabs`: with counts, then without, then a menu, so a tab is never clipped), the list, a
detail column, and the Reader as the third column (each list page hosts its own: `AppTab.hostsOwnReader`).
`ListColumns<ID>` holds the open row: a row that leaves the data, or that the chosen tab does not show, closes the
detail; one that find (or Clusters' View menu) hides stays open. Keys follow DR-68: ↑/↓ swap in place, ⏎ steps in, Esc closes the rightmost column, and ⌘F opens
the page's find row.
- **Clusters has one filter:** a View menu with the Graph's own types (`graphVM.filter.types`), labels, and a
  remembered *Expand all*. Its tabs are navigation: All plus each present type, by plural name. With nothing open it
  is mock A's icon-led cards (F-11, G146): People · Projects · Companies · Tools · Concepts · Media two to a row, the
  rest three to a short row, each a card of 56 pt tiles — `EntityPicture`, the name, one line in words (never tags or
  a percentage) — six in the first row of cards and four after, "Show all ›" opening the type's tab (one card, every
  tile); `ClustersGrid` decides it, pure. A click on a tile's picture opens the image picker (no separate hover button, owner 2026-09-30); its
  words open the card. ⌘F shows the list column (its find row, then find's ranked rows) in place of the cards while it
  is open. Beside a card the list keeps rows with pictures and an age, recently mentioned first
  (`lastReferenced` on `/graph` nodes). The detail column hosts DS-3a's `EntityDetailCard`, in its `.card` style, with
  its `TopicDetailNavigation` trail and the page's Esc order passed through the card's `onEscape`. A ⌘K ⌥⏎ landing
  opens the entity's type tab.
- **The Feed** has sort tabs (Relevance · Recent) and kind tabs (`FeedKind`: paper, video, bookmark, link). Its
  rows are 56 pt, each with the origin's real mark. The Connected strip and the export waits scroll with the list,
  and only with nothing open, so the eyebrow is the only fixed band. That fixed the header drawn under the
  titlebar.
- **A saved item's detail column** shows `MediaPreview` (a video plays at the column's width), "Why it's saved"
  (the page's own words, then the pages it is about, known ids only), and "Saved from" (the origin's mark, name,
  folder and day, or `[ no source recorded ]`). The palette's saved-item row and a source page's items land there
  through `AppRouter.routeToFeedItem`, and the preview sheet is gone. The one-shot import's `+` (with ⌘N) is an
  icon in the eyebrow row and opens the unchanged `AddSourceSheet`, whose root hosts the one `IntakePanel`.
- **Videos (G162, the approved boards, 2026-09-30).** The app reads `GET /videos/state` and `/videos/summary` through
  `VideoStateCache` (app-level, in memory, ETag-revalidated, never a Store domain; `VideoRefresh` follows the
  `videoQueue`, `episodes`, `entities` and `bank` components, one revalidation is scheduled at the wire's
  `nextChangeAt` so a lapsed lease never sticks as "Picked up", a bank switch empties it, and a 404 from an older
  backend hides every video addition). **The server is the only deriver** of a video's state; the app decodes and labels.
  A Feed video row carries a 64 × 36 frame (the stored thumbnail or a neutral play tile, never a URL derived from an id),
  "channel · site · length · saved day" and one state word (a queue word wins). The Videos tab's 44 pt strip says how
  many are not read yet and the one queue wording, and *Choose videos…* turns the page into the watch run: the picker's
  tabs (Not yet read · Queued · Read, disjoint, nothing pre-selected) replace the sort and kind tabs, the list becomes
  64 pt pick rows with `NeutralCheckToggleStyle`, and the detail becomes `VideoRunCard` — per-video Transcript/Watch,
  known-length size words (no price, no estimate), how the agent should read, the prompt shown before it is copied
  (`GET /videos/run/prompt`), and one primary, *Copy for an agent* (`POST /videos/run/handoff`, no cap); after it, the
  progress card counts `batch.done` only. `VideoBlock` ("What Cicada has from this video") sits in a saved video's
  detail column and the entity card's media block: the state, who recorded it (the harness and, where the turn join
  found one, the model — data only), whether Sleep read it, the first quote, the honesty line, and Queue transcript /
  Queue watch / Remove / Try again; a `needs_login` hand-back adds *Open in browser*, and the sentence about the
  reading permission and its Settings button wait for the reading branch (`VideoActions.for(_:permission:)` takes `nil`
  today, and `nil` shows no sentence — none points at a setting this build lacks). The honesty lines promise only what
  the record says: "a model's reading, not captions" only when its engine is `video_link`, else "may be approximate";
  a record with no basis reads "The agent didn't say how it read this", never a claim about when it was made.
  The Reader's header for a watch record and each `media` turn's fidelity are built from the episode's `watch` block.
  Every string is in `Copy+Videos.swift`, and `VideoCopyNeutralityTests` fails on a provider or model name.

**Projects (G141 PJ-5, Direction D).** The eighth page (⌘8, after Sources), the first designed for D: a list page in
progressive columns over `GET /projects` and `GET /projects/{id}/timeline`, which are **not** Store domains —
`ProjectsCache` (app-level, in memory) revalidates them with the server's ETag when the page appears, a project opens, a
write lands, or a sync event moves `entities`/`episodes`/`inbox`/`bank`, and a bank switch empties it (no
`VersionVector` mapping, nothing on disk). The wire decodes leniently into local `Project*` types (the shared `Claim` is
untouched); derived state is `ProjectState`, the Swift twin of `project_state.timeline_state`, running the same
`api/tests/fixtures/timeline_state.json`; every relative word comes from `RelativeDay` over `ISODay` in the viewer's
calendar (a lint keeps the day words there), and midnight re-derives the page with no network. The story is derived off the main actor (`ProjectDerived`, keyed
by project, day and cache revision; the last value stays up while the next builds) and Lately is one lazy list, so a
project whose happenings cite hundreds of pages opens at once (round-4 D6). Every Swift test reads
the demo scenario's real wire, `app/CicadaApp/Tests/fixtures/projects-demo.json`, pinned by
`api/tests/test_projects_app_fixture.py`.
- **The list:** text tabs Active · Quiet · All (resting projects only under All); sub-projects indented under a shown
  parent; each row's where-it-stands line, a mini `progressFill` bar, the next milestone or "No plan yet", people from
  the graph's `person` neighbours (never the owner), the compact age; "still indexing" while the server says `partial`.
- **The band** (`BandLayout`, pure, the approved mock's coordinates): `progressFill` from the first moment up to a
  "You, today" marker in `textPrimary`; done milestones filled inside the green, planned ones hollow on the track, a
  closed `due` slashed ("passed, no word on how it went"), a moved one's dashed ghost and bracket; happenings as neutral
  dots, ongoing threads as spans to today that dash once quiet; months and words near today. Every mark is a button: a
  `textPrimary` ring, its first words and date on hover, ←/→ along the band, ⏎ into the Reader. It is never called
  "Timeline" — that is the entity card's tab, which can share the screen.
- **The story:** Log progress (⏎ done, ⌘⏎ still going; the server dates it from the words, else the date chip, else
  today, and the page says which and how, with Undo = withdraw); Now (the threads; a quiet one whose follow-up waits in
  the Inbox links to that card); Lately (Today · Yesterday · This week · Earlier — one sentence per happening, every
  participant a chip that opens its card, at most eight per sentence with a '+N more' that opens that row (round-4
  D6; the server sends the first 12 and `participantsTotal`), the owner as the sentence's own word with a "you" tag; a status word; a
  source line with the origin's mark and "Show in conversation ›"; Resume where resumable; Not right); Plan (Add with
  an optional picked date, Mark done, Rename, "moved once ›"); Around this project (People · Tools & infrastructure, a
  tool unfolding its specs · Documents & links · Ideas · Parts of this project). The Reader or an entity card is the
  third column; Esc closes the Reader, then the item or card, then the project.
- **Backlog (G150):** after Plan, text tabs Open · Doing · Done · All (a dropped item only under All); rows with the
  id, the title, a triage tag and the age of the last note; Add to backlog. A row opens the item as the third column
  — the title as the heading, the moves, the description and every note as page prose signed with its author's mark,
  the links, Add a note. The third column is one slot: the Reader, else a backlog item, else an entity's card.
- **Writes** are `ProjectWrite` mutations through `Store.perform`: painted where the answer is known (a thread settled
  or restated, a milestone done, renamed or added, a withdrawal), rolled back with the server's own 409/422 sentence
  (a 400's or 404's detail is never shown — it names ids), disabled while Sleep runs; nothing relative is sent as a
  value. L · M · D are key presses on the focused project (the Inbox's O / L precedent), never menu key equivalents.

**Sleep page — the study room (G125 v4, Track Z).** The room and the worm are Aseprite sprite sheets; to watch every
animation, open `app/CicadaApp/Art/sprites/bookworm-2026-10-01/preview.html` in a browser (*The sprite art and its
preview*, below). One 760 pt column at every width: the room,
one sentence in the display face under it, one Consolidate/Cancel control with the engine menu
beside it — a neutral button naming what a cycle you start would run (`preview.manual`, "Auto ·"
under Auto) that opens the five engines with their real marks, the chosen engine's model and both
ruling-4 previews; the "Runs on …" caption retired into it, and Cancel's caption shows while running
— one whisper line for the schedule, and everything else under a single **Details** disclosure (Last
cycle · What's waiting · Readout · Past nights) in D's list grammar — section labels over rows, no
cards; Last cycle's rows in words, "Rested" as a sentence, the readout as key–value rows, and, while videos are
queued, one Videos row in What's waiting (`VideosWaitingRow`, G162: the queue wording and *Choose videos ›*, starting
nothing) — closed by
default, remembered per viewer
(`cicada.sleep.detailsOpen`) and not built while closed. The worm speaks in that one fixed slot —
`roomSentence` / `wormAnswers`, pure
`SentenceLine` values over `SleepPageModel` (lead ≤ 40, tail ≤ 80, clock-free; a missing fact
omits its rung, never shows a guess); the floating bubble is retired. **Two kinds of art (R-Z1, amended by ruling 18):**
*state art* — the owner's worm on a 160 × 64 lattice (3 pt per cell at 1.0), the real pile, the lamp (= the schedule)
and its pixel-size fly, the bean bag, mood-edge yawn/stretch and the Sleep moment overlays — and *response art* (gaze,
perk, talk, cheer), transient and never contradicting state. **Environment art (2026-10-02)** is the time, base weather
and room lighting, independent of the worm. The sheet player loads once, caches failures, uses per-frame boundary
schedules, shows key frames under Reduce Motion, plays every frame at half speed under Low Power and rests unseen.
Settings passes the room's pause to every sprite leaf as well as its clock and weather reader. The steady-state
redraw test covers all 240 weather/time/mood/lamp combinations and sums independent leaves, including 60 clock ticks:
rain's unchanged 48-frame loop now holds 100 ms (4.8 s total), giving a maximum of 1,758/minute against the 1,800 cap.
The room's wall/floor, plant and mug stay inert, with lighting chosen by the scenery. The art layer stays inert; interaction is a
hotspot layer derived from the pure layout (`deskHotspots`), and **no click on art changes what the
machine does**: the lamp's popover shows the scheduled engine and its reason *before* its labelled
toggle can flip, and Consolidate stays the one trigger. The strip appears only while running or
frozen after a cancel or failure; the running stage is `activeStage(completed:)` = completed + 1
everywhere (page, menu bar, onboarding, strip). A real completion cheers once and offers "See what
changed ›"; a cancel neither chews nor cheers. Memory sources left the page (Sources v2 draws it;
the series live in `Views/Sources/ActivitySeries.swift`). **Feeding (Z9).** A file, files or a
folder dropped on the room — or *Feed a file…* from the worm's context menu and VoiceOver actions,
which open the intake's own `IntakePicker` — go to `IntakeRouter.accept(urls:from: .sleepRoom)` and
nowhere else. While a file hovers, the worm is expectant toward it and eager over itself behind a
dashed chrome outline, and the window's veil steps aside (`nearerDrop`); it gulps when the router
takes the drop and shakes when it does not, and the sentence tells the router's own phase in words
with no number — the panel has the counts. A sleeping worm takes the drop and stays asleep; a stale
page sends nothing. **Meadow (Z10).** The sentence is the display face (SF Pro Display semibold 30,
`displayTracking`) over an SF italic tail (F1 R-FX13), Consolidate is the page's one `PrimaryActionButton`, `SleepMotion` forwards its shared names
to `CicadaMotion`, and the sky band above the page is OFF (`SkyBand.ships`, TODO ruling 10). The
pile is compressed to its column at every zoom and queue size — at most eight spines, the order and
every count kept, never cut (`fitPile`) — and the title is `PageTitle`, the view `PageHeader` draws.
Refused: motion with no state behind it (mug steam, plant sway), a flash or strobe in any weather, a count driving the window (time of day follows the clock or the person's choice, R-Z11 as amended 2026-10-02), duration estimates, and any price or plan figure outside Details and the engine menu (TODO ruling 12). State art loops (ruling 18).

**Consolidate reads everything — the app half (G163, ruling 13).** No new door: every trigger already POSTs with no body, and
the server drains. `SleepStatusResponse.drain` (`SleepDrainInfo`, lenient like every field) and the SSE event's compact
`SleepDrainSSE` are merged by one pure `resolveDrain(sse:status:)`: the status holds the whole block, the event overlays the
moving counts only when it describes the same run (same frozen total), and neither is ever a hybrid of two runs. While it
reads, the sentence's tail is "Batch 3 of 12 · 62 of 287 filed." (measured counts through `UsageFormat.count`, G107, and only
with more than one batch); the lead, the strip's Read fill and the study list already read the cumulative origin dicts. A plan
stop is a *pause*, not a failure: the tail is the vendor's own sentence (reset time inside it), the strip freezes where it
stopped and the worm neither chews nor cheers (`SleepPageModel.stoppedEarly` feeds `stageStripState`, `stageStripIsVisible`,
`deriveSleepPageMood` and `isRealCompletion(drainStop:)`). **Cancel keeps its name** and its semantics (stop at the next safe
point, drop a batch that has not begun filing), so its caption and tooltip say what is kept and what is not
(`Copy.cancelDrainCaption`), never "after this batch" and never "nothing is lost". Details › Last cycle gains a "Read everything"
row (only when it took more than one batch or something waits), a "Paused at your plan's limit" row carrying the vendor's whole
sentence, a drain-aware cancel text, and no "Episode cap reached" row for a drain. Home's Getting started says "Keep reading"
after an early stop (`FirstReadAction.keepReading`) and "Your memory has N pages now." after a full drain. Since ruling 16 the lamp's popover and the engine menu's Scheduled row say a scheduled run reads everything waiting too
(`Copy.scheduledReadsAll`), with how it spends in words from `preview.scheduled.billing` ("charged per use; Cicada sets no limit", "on this
Mac") — never a provider's name.
**The study room's scenery (G176, owner 2026-10-02).** `Scenery.resolve(mode:clock:forecast:mood:manual:)` is pure:
base weather · `SkyPhase` · optional overlay · effective source. The worm still means Sleep at any hour/in any weather.
Clock time is `SceneStore.phase` (day · dusk · night), shared with Home's existing boundary/hourly/wake/time-zone
checks, with no new per-second timer. Local weather (default) reads the time zone's principal city's public conditions,
not the person's location. Missing weather falls back to How Sleep is doing and says “Local weather unavailable.”
The fallback maps happy/sleeping/digesting → sunny, reading/curious → cloudy, hungry → windy, error → rainy,
awake → curtains. Choose ignores clock and forecast and pins a time/base. In every mode, sleeping adds calm mist and
digesting adds a rainbow by day/dusk or a shooting star at night. Night OR rainy makes the room dark; dusk otherwise
keeps day lighting. The lamp still means the schedule.

`room-weather` uses `<base>-<time>` (five bases × three times). `room-skyfx` uses six moment/time tags, with its layer
between pane and window in `DeskScene.plan`/`room-plan.json`. In darkness the backdrop/lamp and the window/plant/beanbag/
mug select `night-dark`/`night-lit`, and all eight worm states select `bookworm-<state>-night-dark`/`-night-lit`, including
beats, covers and both sleeping transitions. Tags, frame counts and timings match the day sheets; the small/menu worm
has no room lighting. The existing sleeping-outro → reading key frame can still change from a closed to an open
book in one frame; a reading opening beat is not part of the named contract. `SceneryRoomArt` crossfades room layers on weather/overlay/lamp appearance and keeps the worm outside that identity.
The worm crossfades only on its day / dark-lit / dark-unlit sheet set, and only while no transition or beat is active.
`StudyRoom` passes the active transition/reaction flag to suppress the worm swap's animation. This includes the
day/dusk error → sleeping edge in How Sleep is doing or Local weather fallback: rainy/dark becomes sunny/day,
but the new-sheet yawn starts fully visible. Passive lighting changes still use the existing 0.4 s opacity
`SleepMotion.weather` token; the room layers keep their crossfade during a worm response. Reduce Motion swaps instantly.
Hotspots and the real pile keep their layout/identity. Beat/transition cleanup tasks live on the stable study room,
so a sky/lighting crossfade cannot restart or extend them.
The current legend line, help and VoiceOver share `Scenery.text`, for example “Night · Rainy · local weather”;
mist/completion meaning is appended, and under How Sleep is doing the base meanings remain visible in its key-frame
legend. No scenery action starts work; the window offers a link to its Settings row.

**The wall clock (owner amendment, 2026-10-02).** `RoomClockReading.indices(at:zone:)` maps civil time to
sixty whole-pixel angles: hour = `(hour mod 12) × 5 + minute / 12`, minute/second = their integer values.
`RoomClock` is a separate inert leaf, with a `TimelineView(.periodic)` at `CicadaMotion.roomClockTick` (one second)
only while its window/room is visible and its host is active; it never redraws the parent room. `room-clock` has
`face`, `hour`, `minute`, `second` and each `-night` variant. Night-or-rain lighting selects the dark dial/hands;
black hour/minute hands and the thin red second hand use transparent state frames, not timed sprite loops.
Normal ticks start on whole seconds; Reduce Motion removes the second hand and ticks on minute boundaries while hour/minute keep time. Help and VoiceOver share “Wall clock, <time>”
in the system's short format, after the window and before the lamp; it is not a button. The 15 × 15 clock at
`(94,34)`, z1, follows the verified art plan and clears every worm frame/beat/transition, the window, lamp and pile column; art acceptance
also checks every new night frame. The preview includes the same clock leaf. Motion sidecars exclude its state angles.

**Settings → Sleep → The scenery.** One group in the in-app Settings panel's existing list grammar:
Source (Local weather · How Sleep is doing · Choose), then Time of day and Weather under Choose, then Preview.
Three time thumbnails (Day · Dusk · Night) and five weather thumbnails (Sunny · Cloudy · Windy · Rainy · Curtains drawn)
use the sheets' key frames; every native button has a text label, keyboard focus, VoiceOver label and selected trait.
Selection uses the neutral ground/ring, text below the art, no shadow. The small live preview uses the same room
composition and current Sleep mood/schedule, reading cached weather only. The Settings search indexes each row; hidden
Choose-only rows land on Source. Preferences are per viewer (`cicada.sleep.scenerySource`, `sceneryTime`,
`sceneryWeather`), separate from Home's scene and never in a bank. Local weather's one-line disclosure is
“Open-Meteo receives your time zone's city every half hour while the study room is open and, like any web request, your network address. Nothing from your memory is sent.”
`LocalWeatherReader` suppresses CFNetwork's preferred-language header with an empty field, pins fixed Accept/encoding/User-Agent headers,
and uses an ephemeral session without cookies, credentials or disk cache. Its freshness policy keeps the same city's stale
reading only when a visible refresh is due to start or in flight; failure clears it, and a backwards clock makes the next
attempt due. It is an in-memory read, not a Store domain; its own visibility/source gate, half-hour attempts and
four-second/64-KiB/no-cookie transport are detailed in `network.md`. The ImageRenderer hook uses isolated viewer
preferences and frozen sprite frames without native visibility probes; it renders the native source menu's current
text as a SwiftUI label because ImageRenderer cannot draw that menu. It verifies pane layout/art, not native menu
interaction. The actual menu remains keyboard-accessible. Six light/dark source panes are in the art review index.

**Settings → Sleep → Mascot (owner, 2026-10-02).** A group beside The scenery follows the same list/tile grammar.
`MascotRegistry` is the pure, ordered catalog; today its only entry is **Bookworm** (`bookworm`). Each entry names
its room-sheet prefix, menu sheet and repository-relative art folder for provenance. One tile shows the awake
room key frame, the 18 × 18 menu head at 2× and the name; a checkmark and neutral ring mark selection, with native
keyboard focus and “Bookworm, selected” for VoiceOver. No timer runs in the tile and there is no future-character copy.
The viewer's `cicada.mascot` preference defaults to `bookworm`; an unknown stored id resolves to Bookworm.
`BookwormView` observes that preference on every surface, including the room, empty states and intake; `BookwormArt`
resolves all states, lighting/lamp variants, cover timing, transitions and geometry through the entry. The menu
renderer keys its cache by mascot id, and a choice change redraws/restarts its frame timer immediately. Names of
the existing state/view types and the state/response matrix remain unchanged.

To add a mascot, author its own base with the same pipeline, export `<prefix><state>` and
`<prefix><state>-night-dark|lit` for all eight states plus its menu sheet, using the shared canvases, tag/timing
contract and slices. Add those PNG/JSON pairs with provenance/hashes to `sprites.manifest.json`, then add one
`MascotRegistry` entry naming that prefix, menu sheet and art folder. The picker and sprite readers enumerate/resolve
the registry; they need no character-specific wiring. Registry acceptance tests require every listed sheet in the
manifest. The ImageRenderer hook produces light/dark Mascot panes, including unknown-id fallback.

**Sleep page v5, the app half (2026-09-30; rulings 15, 16).** All copy is `Theme/Copy+SleepV5.swift`, provider-neutral
(`SleepProviderNeutralLintTests`: no provider or model named in a literal under `Views/Sleep`/`Views/Intake` outside the files that render the
person's own choice) and journal-honest (no "read and kept": a Pause reads the part in progress again). The **paused run** (`SleepPausedRun`, on
`GET /sleep/status` and in brief on the SSE event, where a present `null` means none) outranks every idle rung of the sentence — Paused / Paused to
leave room in your plan / Your plan window is full / The engine needs a look / Cicada restarted while reading — with what is filed and, when armed
(ruling 15), "Continues after 3:40 PM" (one locale-aware formatter, `sleepClockWords`); the mood is `.reading`, never an error or a cheer. **One
primary at a time (DR-40):** Consolidate / Pause (a drain's cancel, "Pausing…") / Continue (named for the manual engine; held while a weekly limit's
reset is ahead) with *End this run* beside it. `SleepViewModel.continueRun()` is the only sender of `{"continue": true}`; **every other door goes
through `triggerManually()`, which routes to the Sleep page while a run is paused** (`AppRouter.routeToSleep`), and the menu bar, the intake card's
and Home's *Read now* say what the click reads — "Consolidate now — all 287", "Reads all 318 waiting, oldest first, saving every 25." (`SleepDoor`,
readable = waiting minus parked, M7; a pause whose record has not loaded says only "Paused", and an unknown batch size is left out, never a
fallback — `Store.onSleepPausedChanged` refetches the record app-wide, not only on the Sleep page). While a drain reads: "Reading 14 of 25." / "Sorting 31 of 86." / "Deciding 4 of 12." / "Filing…" (a stage
fills only from finished work over a fixed total; Notice and File never), a caption under the strip in words, `RunProgressBar` (filed ·
read, waiting to file · waiting · could not be read, and calls made; one accessibility value; elapsed "Running 27 m", never a remaining time),
and the first save's "Your page has 31 beliefs so far" with *See your page ›*. *Reading options…* (`ReadingOptionsSheet`, 720 pt) sets batch size
10/25/50 and *Continue by itself when my plan resets* (off) on change; it has no Read faster row, no engine advice and no site list. The engine
menu's *Keep plan free* (Off or 5–30 % of the window, plan engines only, a line not a guarantee, an unreported window said so) is one of ruling
12's two homes; Details is the other: Last cycle's run rows (`LastCycleRow.runRows`, merged over the pre-v5 drain rows), per-source counts and
per-conversation rows from `GET /sleep/queue` (refetched when the run's counts move, never per tick) with Retry for a parked one — offered only while no run reads or waits paused, since the
server refuses it then (`LastCycleRow.canRetryParked`) — a scheduled run's spend note billed from the run's own usage, never today's preview, and Past nights
folded by run (`PastNightItem.group`, the run's numbers from the server's `run`, never summed from visible rows; opened: models, cost, pages,
batches and pauses from `GET /sleep/runs/{id}`, cached in the view model and refetched when the run's counts, pause or end move; touched pages
by name, the id in `.help`). The app-level `SleepViewModel` empties its queue, run details and history details on a bank switch
(`Store.onBankChanged`). `PriceLintTests` keeps `$` and token literals out of every other Sleep
file.
A refused bank switch shows the server's own 409 sentence (`BankSwitchFailure`), from every door: the switcher, the demo's enter and leave (`DemoMode.leaveToast`) and an active bank's rename.

**Mascot states (G107).** `BookwormState` gained `reading` for this page only —
`deriveSleepPageMood` returns it where the menu bar's `deriveBookwormState` returns `.curious`, and
the menu bar's own precedence and sprite meaning are unchanged. `store.intakeInFlight` (set while
the intake router has a request in flight) forces `reading` ahead of `happy`/`hungry` but never ahead of
`sleeping`/`error`/`digesting`. Per-cycle duration *estimates* stay deferred (G107's own ruling);
only a measured, telemetry-joined duration is ever shown. Track Z's **response art** remains
`BookwormPose` (idle · attentive(gaze) · expectant(gaze) · eager) and `BookwormReaction` (perk · talk · gulp · shake ·
cheer), gated by one state × response matrix (`BookwormState.allows`, `acceptsGaze`) so a sleeping worm's eyes stay
shut and the X-eyed error worm never looks away. The selected mascot resolves through `MascotRegistry`; the current
Bookworm entry is the owner's design as Aseprite sheets
(`Resources/sprites/bookworm-<state>`, 64 × 48; the menu bar's `bookworm-small`, 18 × 18, with badge and stage dots
drawn in code); a beat settles within 800 ms, a perk within 400 ms, and the yawn and stretch within 1.6 s (ruling 18).
Tags derive from `BookwormLook.keySegment` and are tested to match each sheet exactly; reading cycles three book
covers on its own loop. A transition always uses the sleeping sheet from the current room lighting/lamp set; a cold page never transitions, and a real
completion's cheer wins in either callback order. A lint bans `.offset`/`.scaleEffect`/`.rotationEffect`/`.spring(`
on every sprite except whole-cell lattice placement. Cached room crops are bounded by distinct frame rects and
decoded pixels; the small renderer's independent cache keeps its 1024-entry wipe bound. Spines use kind-specific
binary masks over the existing origin colour; `fitPile` and spine interactions are unchanged. **Feeding** — a file dropped
on the worm imports through the one intake (R-Z10) — shipped in Z9; the matrix decides its gulp and
shake like every other beat.

**The sprite art and its preview (G176).** The worm and the room are pixel art authored in Aseprite, in
`app/CicadaApp/Art/sprites/bookworm-2026-10-01/`: the owner's references in `reference/`, the saved parts (the source of
truth), the Lua builders, and `tools/export_all.sh`, which rebuilds every sheet into `Resources/sprites/`, verifies pixels
and timing, writes the manifest and regenerates the preview. **To see all of it move, open
`app/CicadaApp/Art/sprites/bookworm-2026-10-01/preview.html` in a browser straight from disk** (no server, no
network): every worm state, beat and transition, the contract's fifteen weather/time tags and six overlays behind the window, the clock's hand-angle states, the lamp and its fly, the room
in day/night lighting with the lamp lit or dark, every mood in every environment, Reduce Motion and Low Power, and the 18 × 18 menu-bar strips on a light and a dark
bar, all at their real per-frame timings. **To make another mascot** (every animation, the dark-room relight, its
menu-bar set, its registry entry and Settings tile), follow `app/CicadaApp/Art/sprites/MAKING_A_MASCOT.md` — it opens with
an agent quickstart — and start a session with `docs/specs/2026-10-02-new-mascot-handoff-prompt.md`. Owner 2026-10-01: the error worm has black X eyes, and the menu-bar worm keeps
its dark outlines on a dark bar (one sheet for both). The 2026-10-02 scenery contract and wall-clock amendment expand the bundle to 36
sheet pairs (429 tags, 4,426 frames), all integrated with the plan, motion sidecar, manifest and preview.
Both full and partial/worm-stage exports rebuild saved-parts predecessors, all night sheets and the manifest, then
run complete acceptance. Independent night/fx builders are repeatable; static `authoring-provenance.json` records
tool/model/effort/date per family, so rebuilding requires Aseprite and Python/Pillow rather than the Codex CLI.
`INTEGRATION_REPORT.md` in the art directory records the app checks and all inspected render paths: 480
environment/mood/lamp/zoom composites, 48 overlay composites, 24 fixed-clock composites and six scenery Settings panes.
`CICADA_WRITE_COMPOSITES=1 swift test --filter WindowSpritesTests` reproduces the room PNGs; run the same flag with
`--filter ScenerySettingsTests` for the panes and `tools/make_integration_review.py` for the review boards/index.
The same snapshot flag with `--filter MascotSettingsTests` adds four Mascot panes (valid/unknown choice × light/dark)
to that review index.
The palette loader follows the art verifier's complete declaration: authoring colours, night ramps/question glyph,
scenery ramps/overlay colours and clock colours. Only the 81 authoring keys count against 87; all 699 declared RGBs
still meet palette/alpha/reserved-hue checks. A defect reports sheet/frame/cell/colour once per sheet.
The registry and one-entry Mascot selector are built; a second character's own design remains open.
Count props, the queue as a room, G175 marks and Q1 remain open; app-side tests do not
establish the owner's visual acceptance or the live CPU budget.

**View menu (G130 slice 1a).** ⌘+ / ⌘− / ⌘0 scale the whole chrome — one persisted `uiScale` behind
every `CicadaTheme` font and spacing token, so every reader repaints with no `.id()` anywhere (the
PR #49 lesson repeated). The graph canvas keeps its own zoom; ⌘+/⌘− means chrome, not canvas, same
as a browser's page zoom vs. a map widget's. `Settings` gains a *General* tab (Appearance + a Text
size slider) alongside Agents, Plans & keys and Schedule. Slice 1b (PR #58) finished the job:
every literal `.font(.system(size:))` / `Font.system(size:)` in `Sources/` now goes through
`CicadaTheme.font(size:...)`, and `FontLiteralLintTests` fails the build on a new one.

**Find palette (G136).** ⌘K ("Find in Memory…") and ⌘F ("Find on This Page…") are menu commands in
`Support/FindCommands.swift` — a lint (`HiddenShortcutLintTests`) keeps both shortcuts there, and ⌘F
reaches only the visible page's field. The palette is an overlay anchored 4 pt under the titlebar — 640
pt, an opaque `bgMenu` floating surface over the panel scrim — that appears and leaves in one frame
(DR-60); its instant tier (`QuickIndex`) is rebuilt off the main actor from the Store's snapshots and
answers every keystroke with no network; ~150 ms later `GET /search` (prefix, then hybrid) appends
conversations, beliefs (superseded ones as history), backlog items (G150; the server tier only) and whatever
the local tier missed — a shown row
never moves. Ask is a mode (⌘⏎) hosting the unchanged `AskPanel` body. One ranker, `QuickMatch`,
folds text exactly like the server's `text_fold`; every in-page field is `CicadaSearchField`.
Recents are `(kind, id)` pairs in the cache-only `.quickRecents` domain; the query is never stored,
logged or sent anywhere but `/search` and `/conversations/recent?q=`. `FindPanelBody` is the hostable
body (Home). Settings' pages and every static row are in the palette from `SettingsIndex` (one index,
one ranker); ⏎ lands on the row through `AppRouter.openSettings(_:row:)` (DS-3b).

**The demo and the guided tour (G117 round 4, G152).** The demo bank shows every page with something in it:
`demo_showcase.write`, called last by `demo_bank.populate`, adds people and a company with pictures (the C11 upload
rung; pastel avatars drawn in code by `demo_pictures`, never a photo), a saved NASA video (read from its captions by an agent, through the same Leo session) plus two direct example.com
video files — one recorded from frames and captions, one nobody has read — and an article with a
public-domain preview, an arXiv paper with its CC0 details, a calendar day, an open Chrome tab group, beliefs Claude Code
wrote over MCP that the card signs with the model and effort of their turn, and every inbox kind — each in its live
writer's shape and committed as that writer commits, with `today` pinned; the only URLs off example.com are
`demo_showcase.PUBLIC_URLS`, each with its licence. `/banks` rows carry `demo` (`demo_guard`, never the name);
`POST /banks/demo` re-opens a demo that exists and `POST /banks/leave-demo` returns to the real bank left most recently
(else `default`, else a new "My memory"). While the demo is active, `DemoBanner` — a floating bar laid out under the
page area, never over a row — offers *Restart tour* and *Finish setting up →*, which leaves the demo and opens onboarding
through the one door (`OnboardingState.reset(bank:)` + `AppRouter.requestFirstRun()`). The guided tour (`TourController`,
`TourLayer`) is six coach marks — the command bar, Home, the Inbox, a person card, Projects, Sleep — on floating
surfaces over a scrim on the page area; Next (⏎) · Back (←) · Skip tour (Esc); it navigates through `AppRouter` and never
acts (`TourLintTests`), opening `DemoShowcase`'s person and project only in the demo. It starts by itself on the demo's
first visit, is offered once on Home after onboarding (`TourOffer`), and replays from Settings → General, every `?` and
the banner; finishing or skipping is remembered per viewer (`cicada.tour.done`).

**Brand marks (Track L).** One map, `OriginIconography.logoName(for:)`, and one precedence:
**installed app icon → bundled PNG → SF Symbol**. Apple's marks are never committed (Safari and
Apple Notes resolve through `NSWorkspace` by bundle id, then their own SF Symbol); every other mark
is fetched once by a maintainer with `scripts/fetch-logos.sh`, declared in
`Resources/logos/logos.manifest.json` (source, licence, trademark restriction, sha256) and
attributed in `Resources/logos/LOGOS.md` — marks committed before the pipeline are declared
`legacy` (10 of the 30): the script never fetches them, their sha256 is verified on every run, and
their licence line records the commit that introduced them rather than an upstream grant. Origins are
`commons | repo | recut | legacy`; a `repo` mark (R-AG9: OpenCode, OpenRouter) is pinned to a 40-hex
commit on the vendor's own repository, with the same upstream-drift guard as Commons. **No
runtime network:** none of the three outbound gates is involved. A raster whose background IS the
mark (`hermes`, the only one) is never recut — every surface that draws one clips it to its own
curvature instead, and `LogoAssetTests` names any opaque plate so another cannot arrive unnoticed.
**Claude Code is the Claude mark plus an app-drawn `>_` badge** (R-AG8, `BrandMark`, composed in
`LogoImage`: `claude-code` → `claude.png` + badge, `claude-desktop` → the plain `claude.png`); callers
keep passing the logical name, and no mark file is edited. Nominative use only — a vendor mark is never restyled or recoloured; the one permitted
transform is an exact luminance inversion of a *monochrome* mark into its `-dark` sibling, which
`LogoImage` picks under a dark theme. Drawn brand glyphs are gone and do not come back.

**Design rules — Direction D, "Focus columns" (2026-09-23).** [`docs/design/DESIGN_RULES.md`](../../docs/design/DESIGN_RULES.md)
is the binding target for every UI change: graphite neutrals, the system accent, SF Pro only, a 56 pt icon rail, a centred
command bar holding the bank selector and search, and progressive columns (the list alone → list + detail → list + detail +
Reader). Rules are numbered `DR-n` and a UI PR cites the ids it applies; a departure needs a dated ruling in its §9. The owner
chose D from three mocked directions (the Inbox and the Reader). DS-1 shipped the tokens, the type, the shell and the
Settings panel; DS-2 (2026-09-24) shipped the Inbox in progressive columns and the Reader as a column; DS-3b
(2026-09-24) shipped Home, the Sleep page's engine menu and Details, and the Settings panel's fixes. DS-3a (2026-09-24)
shipped the Graph page and the entity card, and DS-3c (2026-09-24) shipped Clusters, the Feed and Sources in progressive
columns. Every other
page paragraph below describes what ships until that page's DS track lands.

**Graphite and Meadow (Direction D, G137).** Working surfaces are graphite — `bgRail` · `bgBase` · `bgPane` · `bgHover`
· `bgFocus` · `bgOption` · `bgButton` · `bgSelected` · `bgMenu` · `bgKey` · `bgBadge` (DESIGN_RULES §3.1, chroma ≤ 4,
`ThemeTokenTests`) — with the pre-D names as aliases (`background`, `surface`, `surfaceHover`, `surfaceElevated`) and
`border`/`borderLight` the opaque twins of the resting ring and the input border (graph.js's edges). Text is four steps
plus `textTertiaryOnFill` (`ThemeContrastTests` holds every surface). The accent is the Mac's (`Color.accentColor`);
DR-5 allows it six uses, and the pre-D call sites that still read `CicadaTheme.accent` (now the Mac's accent, so a
state dot among them changes hue on a red or orange Mac) are swept by each page's DS track. `accentText` derives from it — exactly the rules' values for the default blue, pushed to ≥ 4.5:1 for
any other (`AccentInk`). The retired indigo survives only as a data hue (the "active" status, the heat ramp). Depth is
an inset ring, never a shadow in dark and one soft shadow on a light floating surface (`ringed`, `floatingSurface`,
`Theme/Elevation.swift`; `ElevationLintTests`) — the target; the two sites that lint still allowlists
(`MediaPreview`, `HeroPreview`) shadow until their tracks; `GlassCard` is a `bgFocus` card with a ring. The nature tokens (`sky`,
`meadow`, `dandelion`, `cloud`, `bark`, `soil`, their washes, the procedural skies) are for art and reward moments
only, never a data encoding and never behind a row — `progressFill` (§3.8) is the one exception, for Projects.
**Liquid Glass lives in the chrome layer only**, through `Theme/LiquidGlass.swift` (gated on macOS 26 with a material
fallback, opaque under Reduce Transparency); a lint fails the build on any glass API elsewhere. **Painted art**
(`Resources/art/`, `art.manifest.json` with generator, prompt, date, licence and sha256; every painting ships as day,
afternoon and night of one composition — `docs/design/ART_DIRECTION.md`) appears only on non-data surfaces — never the
graph, a list, a grid, a form or a number, and text never sits directly on paint — enforced by an allowlist lint;
Home's band and the Welcome are `PaintedScene` (C10), composed inside `Views/Meadow/`, and its particle colours are
the art's (`ScenePaint`), never theme tokens. Pixel sprites carry the same provenance in
`Resources/sprites/sprites.manifest.json` (script, source, sha256), checked by `SpriteAssetTests`. **Type:** SF only. `displayFont(size:italic:)` is SF Pro Display
semibold (tracking −0.3 at 20 pt, −0.4 above, floor 20, paired and counted by `FontLiteralLintTests`), `quoteFont` SF
15 regular, one `SectionLabel` (11 medium, sentence case, never mono or tracked — `SectionLabelLintTests`), monospace
only on `MonospaceLintTests`' allowlist (code, commands, paths, keys, ids), and `CitedSpan` the washed, underlined span,
read by the Inbox's quote and the Reader's turns since DS-2 (a mention found by name is its semibold, unwashed case). **Motion:** `CicadaMotion` (nil under Reduce Motion) is the only place outside
`SleepMotion` a duration is spelled; `hoverLift()` for things that open, `iconHover()` for glyphs; a keyboard action
never animates. Sprites play per frame from their sheets within `CicadaMotion`'s sprite caps (ruling 18).

**Video (Track V).** A saved video plays where the user already is — a saved item's detail column in the
Feed, the entity Content tab and the entity hero, all through `MediaPreview`/`HeroPreview` — and the provider is
derived from the URL at read time (`VideoRef.resolve`), never read out of the page, so a bank never
needs rewriting to teach the app a new one.

**Provenance viewer (G118 slice 2).** Every claim carries evidence chips (`Views/Provenance/`): the
label says who spoke ("You said", "<agent> replied", "From the page", "Inferred", "Mentioned here"
for a legacy claim's name match found at read) — an agent's chip names its model when capture recorded one ("Claude
Code · Opus 5.5 · high effort", `ModelNames`; round-4 C3/C4), as do the hover, the Reader's meta line and turn labels,
"Where this came from" and a belief's help; an app with no capture says "model not shared by this app" — hovering shows the words in the quote face — washed
when quoted, bold when derived, plain when stale — and a click opens the **Reader**, a column
(`ReaderColumn`): the third progressive column on the list pages that host it (the Inbox, Clusters, the Feed,
Sources and Projects — `AppTab.hostsOwnReader`), and on every other page the shell's trailing column (`ShellReaderHost`),
sized before the page so it is never pushed off-window. It is driven by
`ProvenanceRouter` (a stack of `ReaderTarget`s), beside whatever is open so a belief and its sentence
are on screen together (Direction D, DS-2). It shows C's header — mark, title, meta, and a neutral
Resume when an `isfile()` check says the session is resumable — the pinned "1 of N cited here"
navigator, the turns in the quote face with `CitedSpan`, and the "Noted from this conversation" rows;
a swap onto the same conversation re-lands in place (`ProvenanceRouter.refocus`) rather than stacking
a Back step. The dandelion wash and margin bar are gone (DR-13). It reads `/episodes/{id}/text`
and `/citations` through `ProvenanceCache` — in memory, ETag-revalidated, **never a Store domain**,
so there is no `VersionVector` mapping — slices every offset as a Unicode scalar through one
`ScalarText`, reads a quote and a turn without their markup or role labels (`ExcerptText.stripMarkup` /
`quoteParts`: deletion only, so every span maps exactly; the Reader keeps a turn's lines, drawing a bullet as "•"),
shows a time only when the episode stores one, and says stale / grown / derived /
inferred / truncated in words — a span its rewritten document no longer reaches (the server's 422) is
stale too, never "couldn't open". The entity card's "Where this came from" (Content, after the page and its beliefs) reads
`/entities/{id}/provenance` once per card; G61's section is "Look it up at". Chips read the router
and cache as optional environment values, so a chip outside the main window renders without a
click-through rather than trapping; the Ask sheet steps aside when the Reader
opens (the Belief Timeline is inline in its tab since DS-3a), and a bank switch closes it and empties the cache (episode ids repeat across banks).

---
