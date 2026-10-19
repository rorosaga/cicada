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

**The app is one client of the backend's API (G180 parity, 2026-10-09).** Everything it shows or changes about a bank
goes through a route; the `cicada` command's app commands are a second client of the same routes (`mcp.md`, "The
app's commands"), and a browser front end would be a third. What the app still holds alone — the Mac readers that
post bytes, per-viewer UserDefaults, and the Swift-only presentation logic listed in the G180 parity map — is the
web door's remaining work; the entity card's bands are the first piece moved (`entity_bands`, `features.md`).

**Ruling (G109, 2026-09-02) — d3-force stays.** Evaluated against sigma.js/ForceAtlas2, Pixi,
cosmos, ngraph and d3-force-3d at ~1,900 nodes: the two G109 symptoms were three local bugs in how
`graph.js` drove d3-force, not a library problem. The only flip trigger is an in-app p95 frame time
above 16.7 ms on the live bank, or a graph well past ~10k nodes. **Two rules follow:**

1. **Every custom force multiplies by the `alpha` d3 passes it** (a guard that only removes energy
   is the one exception).
2. **The release path never bumps alpha** — a throw coasts on velocity, not on a hot graph.

`app/CicadaApp/Tests/graph/graph-physics.test.js` (real d3, real `graph.js`) is the regression net;
a KE/node plateau at tick 400 is the signature of a force that broke rule 1.

**The layout settles and stops (G109, 2026-10-14).** Collide is alpha-scaled too (below alpha 0.03), so every force
cools together and the layout comes to rest instead of freezing mid-motion at the alpha cut-off; a settle check ends a
cooled layout once it looks still. The simulation keeps one link per connected pair at d3's default strength, weakened on a
link to a page with more than 50 neighbours (never a leaf's; see the look paragraph below). Every pair draws once,
batched into one path per colour and alpha, and leaves sit close to their page. Every component of ≤ 30 nodes other than the largest — isolates, pairs, triples — is packed in a
halo round the whole body (2026-10-15: a loose scatter, below; it replaced #287's annulus of per-type arcs), out
of the body's charge. A hold on a settled graph moves only the
dragged page and its neighbours. `graph-settle.test.js` holds this on a synthetic with the live bank's shape
(`graph-bank-shape.js`, 3,698 nodes / 41,570 links): the timer stops within ~130 steps with no node faster than
1 wu/tick, nothing beyond 1.7 giant radii, and no frame requested after the stop. The numbers are in G109.

**The look at rest is Obsidian's (G109, 2026-10-15).** Nodes are small dots sized by distinct neighbours (parallel
claims between a pair count once; `computeDegree` → `_neighbours`), with confidence a small second term: at scale 1
a median page ~3.5 wu, the owner's page ~23 (max / median ~6.7, was ~14 on the bank shape). Hubs carry no ring and no
size floor — they read by size and fan. **Dots scale with the graph (proportion pass, 2026-10-15):** one `sizeScale`
multiplies every radius (`nodeRadius` = scale × `baseRadius`, so bigger still means more connected), and collide, link
rest lengths and the halo's footprints use the scaled radii. The scale is chosen so the median dot's on-screen radius
at the fit zoom is √(6 % of the view ÷ (π × visible nodes)), clamped to 2.2–8 pt (`DOT_COVER`, `DOT_MIN_PT`,
`DOT_MAX_PT`); since the fit depends on the layout, the scale follows the fit while a full layout is hot
(`adaptSize`, damped; a cold layout until alpha 0.15, a warm one such as a filter change until 0.02, since its
extent keeps changing) and is fixed after — a push of newcomers keeps it. A full push none of whose nodes carries a
position (a bank switch: blank, then the new bank) is a cold layout with a fit; one whose carried layout wants a scale
more than 1.25× off (a switch back to a cached bank) lays out every node from where it is, and fits. On the bank shape in a 1200×800
view: scale 2.3, median 2.2 pt, smallest 1.5 pt; 500 nodes 6.0 pt; 50 nodes 7.7 pt. A satellite keeps the halo room it
had at scale 1 (never under 1.8 footprints), so bigger dots do not widen the halo; `MIN_ZOOM` is 0.1. Every pair draws
one hairline at every zoom (`drawLinks`; neutral α 0.55, context-coloured α 0.22), 0.12 of the smallest dot's
on-screen diameter and at most 0.75 pt (`linkStroke`); thinner than a device pixel it is drawn one device pixel wide at
a proportionally lower alpha. A hovered or focused link is 1 pt. Every body page has one charge (no degree weighting, which carved holes and lined dots into
chains), links to a page with more than 50 neighbours are dissuaded (never a leaf's), and such a page is pulled to the
middle. The satellites form a loose **halo**, not rows: each unit's angle and depth come from its own id (`unitHash`),
so the scatter is irregular and keeps its place across pushes, around the body's own edge read per angle, with a
wobbling outer reach. The pending pulse ring hugs its dot (≤ 5.5 px out). Names fade in with zoom, biggest dots first,
never overlapping, at most `LABEL_BUDGET` (at the fit zoom only a page as big as the owner's is named); the fade reads
the dot's scale-1 radius, so names follow the zoom whatever the dot scale. The Legend's
**Show unlinked** switch (on by default; Obsidian's Orphans filter) is `minDegree` 1 when off.
`graph-look.test.js` holds the look on the 2026-10-15 shape (`bankShaped1015`: 4,544 nodes, 9,046 pairs, 984
isolates) and on `bankShapedAt(50 | 500)`: the median dot within 10 % of the curve at the fit zoom (also in an
800×560 view), no page dot under 1.4 pt, none over 24 pt, a link ≤ 15 % of the smallest dot's diameter at every zoom
tier (dpr 1 and 2), discs 5–10 % of the fitted view on the bank shape, no overlap, halo nearest-neighbour CV ≥ 0.28 and
Clark–Evans ≤ 1.3, the owner's page ≤ 0.25 giant radii off the middle, and the #285/#287 settle guarantees.

**The graph rests when nobody can see it (audit 2026-10-02 A07–A09).** `GraphPage` stays mounted under
every tab, so it tells the page whether it is on screen: `GraphView(isActive:)` is the Graph tab
selected *and* its window visible (`WindowVisibilityReader`: occluded, minimized or hidden reads
false), pushed once per change as `setGraphActive(bool)`. Inactive, `graph.js` cancels its queued
frame and pulse timer, ends any drag, and stops the d3 timer — a data push lays out later rather than
in the background (`holdIfInactive` after every `restart`). Resuming continues a simulation that was
still moving at its own alpha, never a reheat, and leaves positions and the zoom untouched. While
visible, a settled graph redraws only for a pending node whose ring is on screen, on a ~30 fps timer
with the phase taken from elapsed time (the ring keeps its ~1 s period). One `cancelInteraction`
ends a gesture whose release never arrived (window blur, a move with no button held, a pointer
cancel, going inactive): the node is unpinned, its throw velocity dropped, and the alpha target set to
0 with no restart. `GraphView.Coordinator` holds the web view weakly (the content controller retains
the coordinator) and `dismantleNSView` suspends the page and removes its handler, so a closed window
releases its graph. Regression nets: `Tests/graph/graph-lifecycle.test.js` and
`GraphViewLifecycleTests`. Capture, SSE and the menu-bar worm are untouched by any of this.

**Sync engine.** One `Store` holds a `Snapshot` per domain, hydrated instantly from a per-bank
on-disk cache before the first network round-trip, so the app renders real data cold even with the
backend down. A `SyncEngine` holds one SSE connection to `GET /sync/events`, reconnecting with
backoff and falling back to polling while disconnected; each `version` event refreshes only the
changed domains, always with `If-None-Match` so an unchanged domain costs a 304. A domain whose refresh failed stays
pending; the server's 15 s `ping` retries it while connected (`Store.retryPending`, at most `maxPendingRetries` = 8
heartbeats until the next version event re-arms it — a version event comes only when the vector moves, so before audit
2026-10-05 P2-7 a failed refresh stayed stale on a healthy stream). View models are
thin projections and **never blank** — always last-known-good. Writes go through a `Mutation`:
optimistic apply, rollback with a toast on failure. A Sleep-window refusal (`SleepRefusal`: a 409 with `code: "sleep_writing"`,
or from an older backend one of its exact known opening sentences — never "sleep" anywhere in the body) toasts "Sleep is running — try again when it finishes." from an inbox answer (`InboxResolve`) and
the entity card's Fades chip (`DecayChangeFailure`, which until G177 failed silently); any other failure keeps its own
words, never a 409's raw detail. **The graph receives deltas, not a full
re-layout**, so d3 node positions survive a Sleep cycle or a live edit.

**A late answer never lands in the wrong place** (audit 2026-10-02 A03/A05/A06). `Store.entity(_:)` compares the
bank and an invalidation generation across its fetch: an answer from a bank the person has since left is dropped
(nil, nothing memoised), and one that started before `invalidateEntity`/`invalidateAllEntities` is fetched again. The
entity card's sources are card-local, so their writes run through a card-local `SourceWriteQueue`, one at a time in
the order made — a failure rolls back only its own change and a slow answer never overwrites a newer one; the card's
list outlives an entity switch, so a write touches it only while the card is still on that entity (`isCurrent`). A
queued edit paints when its turn comes, not at the click. An add is
the `EntitySourceAdd` mutation: the draft stays in the field until the answer, a failure keeps it and toasts the
server's sentence (`SourceDraft.afterAdd` decides what the field holds), and a second ⏎ on pending text is ignored.

**Ruling (2026-09-28, TODO ruling 12; surface renamed 2026-10-16): plan usage and model prices show on the Sleep
page's Past reads run detail and its engine menu — and nowhere else yet.** This supersedes the 2026-09-03 ruling ("prices and token usage are not shown anywhere
in the app") for those two surfaces only: no cost tiles, no `$`/token columns and no cost-per-day chart elsewhere, and
the `/consumption/*` endpoints are unchanged, except that a cost bucket no call priced is `null` (unknown), never
`0.0` (2026-10-16). Every figure states its basis in words ("charged", "at list price", a
plan window's share) and a plan's before → after carries the honest limit that it covers all use of the plan
(`CycleUsageText`, `UsageFormat.currency`). Past reads' Last cycle describes the latest *finished* cycle from one history
record the backend finds, `/sleep/status`'s `lastFinishedCycle` (`LastCycleFigures.resolve`, 2026-10-16): a drain is
one cycle — its run's reading time, the engine its commits name, and the whole run's cost — and a run still reading or
paused is skipped; a plan run's line is its window and no price
(`CycleUsageText.lastCycleLine`); past nights' rows keep each batch's own figures. **A plan run leads with how much of
the plan it used, not dollars (owner 2026-10-16):** a row, Last cycle and the engine menu's last line ("Last run: under
1% of your weekly limit · reading unchanged") say the backend's `planShare` with its basis in words — measured (only
when the reading moved), reading unchanged (an "under 1%"), or estimated, never an estimate presented as a reading and never "0%" (`CycleUsageText.shareLine`/`shareFigure`); the help states
each basis in full and the list-price equivalent, "Would have cost about $0.49 on an API key". An opened plan run (Past
nights' run detail and a cycle's Models) puts the share above the models, drops the models' list price, and moves the
dollars to that secondary line under the total; a metered run keeps its dollars as before. A plan run with no share reads
its window shift, else "share of the plan not recorded". Past nights' folded run row does not carry the figure (its
detail does): the row has no whole-run usage on the wire.

**Navigation (Direction D, DS-1).** A 56 pt icon rail (`Views/Shell/NavRail.swift`): Home, Graph, Clusters, Skills,
Sleep, Inbox, Sources, Projects, Looks at ⌘1–9 in `AppTab.allCases` order (`RailItem`; a page switch is instant). The Feed
retired into Sleep on 2026-10-16 and Skills took its cell, so ⌘4 opens Skills and no other shortcut moved (⌘ map A);
for one release the first ⌘4 that lands on Skills toasts "The Feed is now part of Sleep (⌘5) → Saved." once per viewer
(`FeedMovedHint`, the key only — a click on the cell never shows it), and a stored "Feed" or "Capture" selection
restores to Sleep. Each cell's tooltip
naming its page and shortcut (450 ms, then instant while warm), selection by brightness and one neutral fill
(`bgSelected` — never the accent, `SelectionTintLintTests`), the Inbox count a neutral `bgBadge` numeral, a spinner on
Sleep while a cycle runs, the gear and the sun/moon toggle at its foot, no wordmark. The gear's `warning` dot lights only
when the engine the person chose is a plan that is installed but signed out (owner 2026-10-16,
`ConnectionsViewModel.needsAttention(engine:)` over `EngineOption.connectionId` — a plan merely available, never chosen,
is not the person's problem; the engine choice is read once the backend answers). ⌃⌘S or the titlebar toggle swaps it
for a 208 pt labelled sidebar, remembered per viewer (`cicada.shell.labelledSidebar`). Relaunch restores the last tab:
nothing stored, or a value no build knows, opens Home, and a stored Graph stays on Graph; `AppTab` raw values are the
persisted identity and `AppTab.restored(from:)` maps retired ones. **The titlebar is a SwiftUI toolbar** with the
title hidden (AppKit keeps the drag area in every gap): the sidebar toggle after the traffic lights; the **command
bar** centred — the memory-bank selector (`BankSwitcher`, moved from the Graph page; the only switcher view in the
app, `SingleBankSwitcherTests` — the palette's "Switch to <bank>" row and the intake card's switch act on the same
`BanksViewModel` in the same window) and "Search your memory ⌘K", which opens the find palette through
`AppRouter.requestPalette()`; and the visible page's `?` at the right (`HelpContent.page`), one per window. macOS 26's
toolbar platter is hidden (`ChromeToolbarItem`). The rail starts under the titlebar band (2026-10-05), and the band and the rail are one L-shaped frame
on the rail's surface (owner 2026-10-07): `CicadaTheme.titlebarBackground(for:)` is the window colour
`syncWindowChrome` sets (`windowBackground` stays `bgBase` for `AccentInk`), and the page host is a panel
(`shellContentPanel()`, `ShellContentPanel`) whose top-leading corner alone is rounded at
`CicadaTheme.contentCornerRadius` (`radiusLarge`, fixed) and clips what scrolls up into the band.
`RailCornerSnapshotTests` writes it offscreen on request. **Settings is a panel inside this window (DR-33)**: ⌘,
(`ShellCommands`, which opens the window first if none is) and the gear open it over a scrim — 880 × 620 at 1×,
inset ≥ 40 pt — with a `bgPane` sidebar that starts with a `CicadaSearchField` and groups its rows as Cicada ·
Customize · Engines & keys (`SettingsGroup`, G139) — Cicada: General · You · Privacy & data · Memory · Sleep;
Customize: Integrations · Reading the web · Agents · From anywhere · Devices · Skills; Engines & keys: Engines · Plans & keys · Advanced — and each
page's own header with an `esc` keycap and a close ×. It is modal: the shell under it is inert, ⌘K waits, Esc and a
scrim click close it. `AppRouter.openSettings(_:row:)` is the one door (`SettingsSectionLink`, the gear, ⌘,), every
hand-off to a page closes it, and `cicada.settingsSection` is only its remembered selection — the `Settings{}` scene
and its cross-window seeds are gone. Privacy & data exports a bank and moves one to `<root>/.trash/`, but never
switches banks (that is the command bar's); Memory has no "Look for duplicates" yet (R-O17) — the dedup endpoint
now runs off the event loop and commits what it merges (G183(e)), so the button is the remaining half. Memory also holds
G147's *How things fade*: pace suggestions from the person's own "Still tracking…?" answers
(Apply · Not now — the latter per viewer) and each chosen per-type pace (Reset). Advanced lists the environment
switches by name (G139) and, under *Settings file* (2026-10-13, `SettingsFileText`), whether a developer checkout's
`api/.env` was read, which settings it set, which the environment replaced with another value, and the pace and page-writing values in
effect — from `/status`'s `settings` block (`api.md`), names only. Search is `SettingsIndex` over `QuickMatch` — the
palette's one ranker — and landing always selects, scrolls, washes (the selected fill and the focus ring) and
announces the row (G139). `SettingsSection` raw values did not move. General's appearance offers System, which
follows the Mac's own light/dark through one app-scope observer (`ThemeStore.observeSystemAppearance`). General (F-10:
Look · Startup · When Cicada is closed) holds Appearance and Text size (Scene retired with the painted art, owner
2026-10-16: it picked a painting, and none is left), Open Cicada at
login (`LoginItemService` over `SMAppService.mainApp`; an unsigned build that macOS does not keep says so), Show in
menu bar (per viewer, on by default; hides the 18 × 18 menu-bar bookworm (ruling 18), the Dock icon stays); a login launch opens no
window — the bookworm waits in the menu bar, and the Dock icon brings the window (`LaunchKind` from the 'oapp' event,
`LaunchState`, R-OB18) and Keep memory working when
Cicada is closed (`BackendAgentService`: a read-only `launchctl print`, and Install runs
`scripts/install-backend-agent.sh` from the app's own checkout after the click, `CICADA_CAPTURE=off`, then hands
launchd the port). **Where your memory lives** (G181 phase 3, its own card before *When Cicada is closed*;
`MemoryHomeSetting`, `ConnectionSettingsModel`): *This Mac* or *A server* — an address (https, or http to a loopback
tunnel) and this device's token from `cicada device add`. *Check and use* writes nothing until `ServerProbe` hears the
server (`/healthz` open, then `/devices` with the token, which names this device); then `device_token` and
`$CICADA_HOME/api_base.next` (0600) and *Restart Cicada* (`AppRelaunch`, waits while Sleep runs, DR-41). At launch
`ServerConnection.applyPending` puts the choice into `api_base` — the file the hooks, MCP and CLI read — before
`ServerConnection` is resolved once, so the agents and the app switch together: `APIClient`'s one base and token, the Store's disk cache (`Cicada/cache` + a per-server
suffix), the pictures/logos stores and every reader's cursor or last-synced signature (`ServerConnection.scoped`) are
per connection, so a server is sent what it has not had and This Mac's keys are unchanged byte for byte. On a server
the app starts no backend, stops a background service left from This Mac (`BackendAgentService.stopForServer`:
`launchctl bootout`, plist kept), *Keep memory working* says it is not needed, an update repairs no service, the demo is
refused before any request (`ServerLinkError.demoStaysLocal`), and Advanced's token row names `device_token`; a reader's
post the server did not take waits in `ReaderOutbox` (`$CICADA_HOME/spool/app/`; a newer post on its route waits
behind it, never overtakes it) and is flushed when the event stream connects, lane by lane (route + memory: another
memory's refused post waits without blocking the active memory's — owner decision 6, 2026-10-16; no answer or a
refused token still stops the flush; `headless.md`, "The Mac app as a client"). **Settings → Devices** (`DevicesSettingsView`,
`DevicesPageModel`; not a Store domain): *This app* — where the memory lives, reachable or not as of when (DR-58),
captures waiting with *Send now* — and *Your devices* (name, added, last seen, *this Mac*; Add a device with its
token shown once and Revoke on This Mac only, the server's two commands named on a client). Where memory came from is
one quiet word (`DeviceOrigin`, names from `DeviceDirectory`, read on demand): *from laptop* last on a Saved item's
"Saved from" line (`FeedSourceLine.text(_:device:)`), in the Reader's meta line (`ReaderHeader.meta(_:device:)`) and on
each conversation under *Where this came from*; on a server's client, the server's own writes read *from this server*;
on This Mac, this Mac's own say nothing. The bank picker's menu leads with *on <host>* on a server.
Setup's card also holds *Command-line tool* (G180, ruling 21; `CommandLineTool`,
`CommandLineToolRow`): one neutral *Install the command-line tool* button (DR-40) that links `~/.local/bin/cicada`
with no admin.
  - The target follows `CicadaRuntime`: a release links its `~/.cicada/bin/cicada` launcher, and only once that
    launcher exists and the app runs from a real folder. A developer build links its checkout's `scripts/cicada`.
  - A working link or a file already at that path is left alone and named. A dangling link is rewritten.
  - The row says Installed / not on PATH (with the `export PATH` line in a `CommandBox`, DR-19) / installed
    elsewhere. It sits in Setup's card, never a card of its own (DR-37).
  - "On PATH" is read from `/etc/paths` and the shell's profile files (`ShellPath`), never by running a shell. ⌘K and ⌘F are
menu commands in `Support/FindCommands.swift` (`HiddenShortcutLintTests`); ⌘, and ⌃⌘S live in
`Support/ShellCommands.swift`. Track P's audit removed the global Sleep button, because a cycle starts from the Sleep
page's one Consolidate control (G125 R10) or the menu-bar bookworm.
**One intake (Track I, spec decision 13).** Every way a file arrives — a drop anywhere on the
window, the Dock icon, File → Import… (⌘⇧I), the menu-bar worm's *Import a file…*, an empty state,
each `+` chat tile, the Sleep room's worm — goes through one `IntakeRouter`: sniff (`POST /intake/sniff`, stages nothing) →
preview (counts, date range, new · grew · already here, skipped files by name, *Into* a memory) →
import (`POST /intake/import`; a 202 and a job counter above 10 episodes) → a *what happens next*
card that never closes on its own. `UploadOverlay` and the retired Feed's Upload button are gone; the router
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

**Home (G108; Direction D, DS-3b; F-09, round 4).** The front door at ⌘1. The painted band is gone (off since G189(a),
2026-10-06; retired with every painting on 2026-10-16, owner: "Remove it from everywhere"), so the first content is
"What would you like to remember?" as a `PageTitle` at the room pages' 24 pt top inset (`HomeLayout.headlineTop`) — then the palette's own `FindPanelBody` in `.page` placement in a 640 pt block: a second
`FindPaletteModel` sharing the one Ask and keeping no recents; ⌘K on Home focuses it, a pasted `http(s)` link offers
*Save this link*. The headline, the field and the blocks scroll as one page (owner 2026-10-06), under macOS 26's soft top scroll edge
(`softTopScrollEdge()`), so no card is cut under the field; the first block sits one 24 pt block gap below it, and with
results showing the page pins to the window (never `scrollDisabled`, which the results' own scroll could inherit) and
the results fill it, with no animation. The field's Find/Ask switch is DR-45 text tabs inside it with a neutral glyph,
and it never animates. Below it, in one 760 pt column, blocks **ordered by the person's state** (owner ruling
2026-10-14, "Graduate + Needs you first"; `HomeArrangement`, `HomeSetup`, `HomeEmptiness` in `Support/HomeArrangement.swift`,
`HomeFrontDoorTests`): while the whole Getting started card is up and the person has no chats in memory, (the tour
offer →) Getting started → Today → Needs you → Needs your browser → Last time Cicada read; otherwise Needs you leads (→ Needs your
browser → Today → Last read) and setup is the last line. "Chats in memory" is a fact of the bank: a `harness` row of
`/sources/overview` (an imported export or a connected agent) with `entities > 0`, i.e. its conversations fed a page;
unknown is never an answer. Graduated, Getting started is one line, "Setup · N things left · Show ›" (rows not On), and
gone when nothing is left; its open/closed choice is `GettingStartedState.expanded`, per bank, set only by *Show
setup checklist* (`showChecklist`; the Welcome's record never opens it). The tour offer leads the first week, above the
card, so it is never off-screen. Inside, three labelled groups 20 pt apart — Connected, Your past chats, First read — and *Also
on this Mac* as an offer. Your past chats has one 36 pt row per vendor still to ask (`ExportVendorRow`; a vendor whose
`chat-export:<vendor>` row has episodes is not asked again), the whole row opening onboarding's drawn walkthrough over
Home (`HomeWalkthroughLayer`), with waits above them leading with "Check your email for the … link". Today is one row to
Sources (captured today, UTC, with the three busiest origins' marks, names and counts) plus the waiting count as a row
to Sleep; Needs you is the Inbox's kind glyph, question and age, *Open Inbox* at the label's right, landing in STATE 1;
Last read is the newest Sleep commit as a row to that read in Sleep's Past reads ("Today 07:27 · 33 updated", the commit's
instant on the viewer's clock), its pages as `Tag`s in 24 pt hit frames — each number once, never a Consolidate. The
history is not a Store domain: `SleepViewModel` holds it in memory, Home fetches it on arrival and whenever the status's
`lastSleepAt` moves (`refreshForHome`), and a bank switch empties and rereads it (`bankChanged`) — the launch's own
switch to the roster's bank used to drop Home's first fetch, leaving "—" until the Sleep page was opened. Each state is
in words (`HomeFigures.lastRead`): "Looking up the last read…" while it loads; "Nothing read yet" when the status says
no read ran; a failed fetch falls back to the status's last read, or says "Couldn't look up the last read". An empty block is only its label and a note ("Needs you · nothing right now");
all three empty is one `HomeEmptyBlock` (*Choose a file…*), or nothing while Getting started already says so. Every
`InlineLink` hits 28 pt (layout-neutral, `LinkHitShape`). Right after onboarding ends (Open Cicada or *Set up later*),
*Make it yours* (Appearance; `AppearanceTipPolicy`, per viewer) is a row after
Needs you for that one session; once hidden or seen it lives only in Settings.

**Onboarding (G145, round 4 phase B).** Seven pages in one full-window layer, raised by `FirstRunGate`
(unknown is never empty; never over the demo, which its plan marks onboarded one step after the switch — QA
2026-10-16) or by the one door, `OnboardingState.reset` + `AppRouter.requestFirstRun` (Settings →
General's *Run setup again*, the demo's *Finish setting up*). **The illustration is the study room** (owner
2026-10-16, replacing the paintings): `OnboardingRoom` draws the Sleep page's room art (`SceneryRoomArt` with the worm,
its floor faded into the ground, no hotspot, no pile, no word on it — DR-13) at a whole number of points per lattice
cell (`OnboardingRoomLayout`: up to 4 over the card, up to 3 in the pane), in the person's own scenery from what is
already known (no fetch), the worm's mood set per step (`OnboardingPage.roomMood`: awake, reading, happy, asleep for
Keep it running). Welcome and You're set are the room over the card (a short window drops the room first, then scrolls
the card); Import, Agents, Skills, Who reads and Keep it running are a split frame — the room centred in a `bgPane`
pane (540 pt, which gives way before the column does), the column with "Step n of 7 · k still
coming in", Back and one primary (⏎ never animates). Get started is the owner PUT, alone and first; after it **a
tick starts that source at once** through the one turn-on (`FoundTurnOn`; app-side sources register an
`AppSourceDriver`), an untick stops it keeping up and keeps what came in, and × shows only where a run can stop
(a browser's; a chat export shows its progress and never an ×). Nothing is pre-ticked and nothing is read before a
tick. The Import rows are one table (`ImportCatalog`: supported installed browsers, Calendar, Apple Notes — a
one-time read — Wispr Flow when present, the chat drop zone and *See how* per provider, a drawn walkthrough over
`ExportWalkthrough`'s data opening `WalkthroughVendor.exportURL`; its clock is `ExportWalkthrough.cadence` — paused
while the window is hidden, one frame per step under Reduce Motion, `SceneRunPolicy`'s cadence halved under Low Power,
audit A11); Contacts sits under *Calendar & contacts* and
Chrome's open tab groups as a sub-row under Chrome (only where Chrome is), each one `ImportEntry` and one driver over
its own reader (`ContactsReader.connect`, `TabGroupWatcher.enable`), which Home's Getting started registers too. Every row, the topbar's count, You're set and Home's Getting started read one projection,
`SetupProgress`, over `SetupRunner`, `SyncActivity` and the channels. Agents reuse `AgentSelector` /
`AgentSetupSteps` with a live ✓; Claude Code's and Codex's *Connect for me* here also turns on *Remembers
automatically* (its commands shown first; Settings → Agents keeps it its own click). **Skills** (owner 2026-10-15,
`SkillsStepPage` over `SkillsStepModel`, the Agents step's happy worm) is three switch tiles: Websites (browser-harness) and Mac
apps (macos-harness; macOS asks once) on, Videos (the video skill) off; *Skip* beside Continue. Nothing installs on the
page: **Continue is the consent** — `POST /skills/onboarding` records the answer (Skip too, never asked again) and
installs what is on in the background. A saved answer is where a later run starts (rerun or a new bank): what the
person declined starts off. Without uv it says so, shows the official install command and link, and the two can't be ticked until
*Check again* finds it. Who reads is `EngineChooser`,
writing only on a click; Keep it running holds the same switches as Settings → General and turns none on. You're
set shows one public-domain quote (`MemoryQuotes`, G153, kept per install) and Open Cicada marks the bank, records
the connected agents, asks `TourOffer` and lands on Home. *Set up later* and *Try the demo* (`SetupRunner.demoPlan`)
remain; export reminders (`ExportWaits`) ask for notification permission only when a delay is chosen. Getting started
continues on Home — the first read (*Read now*, G125 R10's second narrow amendment, only inside the card) and "Read
new conversations automatically?" asked once of a person still on `manual`, its options gated by ruling 4.
The first-read failure row uses the same calm “Reading stopped” / “See what needs a fix in Past reads, then try again”
copy as Sleep (DR-7/59), never a raw server sentence. Its one *Past reads* action (DR-40) stages Sleep's Last cycle
section through `AppRouter`; Sleep consumes it once on appear/change, selects Past reads and brings its tab row to the top.

**Settings → Engines: the engine picker (G122, Track E; moved by G139 A3).** A row of cards with real marks — Auto,
Claude plan, ChatGPT plan, OpenRouter, Ollama (tagged *Local*), API key — over the connections registry's candidates writes
`PUT /sleep/engine`, which lands in the same bank-independent `~/.cicada/connections.json` prefs
`use_for_sleep` already uses, never `api/.env`. A plan card is selectable once that plan is signed
in. **Auto is the default (ruling 31, 2026-10-19):** an untouched install selects the Auto card, whose caption says it
reads with the Claude plan, else the ChatGPT plan, else Ollama — never an API key unless the person chooses it; with
none of them a preview's engine is `none` ("No engine yet", `Copy.engineLabel`), the chooser asks for a choice before a
read (`EngineReadiness.needsChoice`) and the onboarding caption says nothing can read yet. OpenRouter and the API key
stay cards the person may pick. The card shows both `preview.manual` and `preview.scheduled` lines rather than hiding
**ruling 4** (a scheduled cycle uses a plan only through Settings → Sleep's switch, on by default —
`engine_select.SUBSCRIPTION_MODES`) — the asymmetry stays visible, not silently applied. *Keep going on extra usage* (off) is the only
way a Claude cycle continues past the plan's included usage; otherwise it stops with one plain
sentence and the reset time. Ask follows the same choice. The ChatGPT plan runs as `codex exec` in
Cicada's own Codex home (`~/.cicada/codex`), signed into in-app with a device code; Cicada never
opens that home's files — `codex app-server` answers plan, limit and models.
`EngineChooser` is the component (`EngineCard` wraps it for onboarding); the Sleep page's quick engine
menu (beside Consolidate) reads and writes the same `PUT /sleep/engine` through the same
`SleepEngineViewModel` and the same write rule (`EngineWrite`), and shows both previews — "When you
start a cycle" / "Scheduled cycles", the one wording app-wide. **A change made elsewhere reaches the page** (2026-10-08):
the sync vector's `engine` component (the prefs file's stamp, plus the engine a reading run pinned at its start) moves on a
`PUT /sleep/engine` from curl, an agent or the CLI, and `SleepEngineRefresh` reloads `SleepEngineViewModel` — not a
Store domain, no `VersionVector` mapping, like `VideoRefresh`; before, the page named the old engine until reopened. A
run keeps the engine it resolved at its start or Continue; while the choice now resolves to another, `runKeepsEngine`
puts one provider-neutral sentence under the Consolidate row and in the menu (*This run keeps the engine it started
with…*), naming neither engine. The Claude plan's old *Use for Sleep* switch moved here too —
same `use_for_sleep` pref, same endpoint — but `engine_select.resolve_llm_mode` reads that pref only
when the chosen mode is `byok`, so it shows only while the API key card is chosen, as *Use my Claude
plan when I start a cycle*, and a flip reloads the chooser's preview. Plans & keys is credentials
only: the Max-tier cost-estimate picker is gone (prices live on the Sleep page, ruling 12).
**Who reads (round 4, R-AG10…R-AG14).** OpenRouter is its own card: *Sign in with OpenRouter* (PKCE, the nonce in
the callback path) or *Paste a key instead*; under the hood it is `byok` with an `openrouter/` model, so ruling 4 is
unchanged and `PUT {mode: "openrouter"}` is a 422 — every card becomes a mode through `EngineWrite.mode(of:)`, and
`selected` on the wire names the card. The API key card is a provider picker (Anthropic, OpenAI, Gemini, xAI, Groq,
Mistral), each writing its tested default model and offering its key field in place; a key's model pins its judge.
The defaults live in `byok.PROVIDERS` and must be in the installed litellm's bundled table, priced and with structured
output (`test_byok_providers`; the table is never fetched, `network.md`): OpenRouter's is `openrouter/openai/gpt-oss-120b`
and xAI's `xai/grok-4-1-fast-reasoning-latest` since 2026-10-16 — the earlier `openrouter/~openai/gpt-mini-latest` and
`xai/grok-4.5-latest` were only ever in the fetched table.
Ollama wears a *Local* tag and no card says "slower". Under the cards, `LeavesMacNote` — a pure function — says
where reads leave the Mac and to whom, only for engines that send data out (never Ollama, nor Auto resolving to it).
A preview line or the Sleep page's button that runs on an `openrouter/` model names and marks OpenRouter.

**Settings → Integrations (G126).** A categorized, logo-first page over the existing
`GET /sources/channels` registry — no new adapters, just a frame. The rule this page draws: a
*standing* connection (sign in once, polled on the Sleep tail, disconnect here) lives in
Integrations; a *one-shot* import (drop an export, sync a folder once) stays where it already was,
behind the `+` on the Sleep page's tab row (the Feed's, until 2026-10-16). Both read the same `channel_registry`, so a channel never drifts between the
two surfaces. Round 3 added **Notes & files** (Apple Notes and, when Obsidian is installed, *Obsidian vault*; the
watched folders and *Add a folder* moved to Settings → Search & files on 2026-10-14, and Notes & files keeps one
pointer, "Folders are in Search & files ›") and **Voice & meetings** (Wispr Flow once it is on this
Mac) — both standing connections, so both live here; their marks are the installed apps' own icons.
Harness rows wear their app's real mark ("Other agents" a neutral glyph); a folder's Manage, Wispr
Flow and a connector's Connect/Manage open as sheets (`SettingsSheet`), never popovers; the
add-folder sheet labels its fields and asks which subfolders an agent wrote as a checklist
(`AgentFolders`), the wire still a `<folder>/**` glob (DS-3b). **Browsers (round 4, C9)** are drawn
from `BrowserInventory` — the browsers on this Mac by bundle id, each with its installed icon: Chrome,
Safari, Brave, Vivaldi, Comet and Dia as `SourceRow`s (Turn on / Sync now, or Try again with the
Full Disk Access fix under Safari when a read was refused, 'Last synced …'); under Chrome, *Open tab groups* is a
sub-row with its own switch and the open groups as tags in Chrome's colours (G160), and **YouTube history** (G71,
2026-10-16; `WatchHistoryRow`, `WatchHistoryWatcher`, channel `chrome-youtube-history`) a second sub-row with its own
switch, off by default ("Off — … Only YouTube video pages are read, never the rest of your history"), then "Live",
"N videos watched, one entry per day" and 'Last synced …': the app copies Chrome's `History` into a private temporary
folder, reads the copy with one query that names YouTube video pages only (`ChromeWatchHistoryReader`), deletes the
copy, and posts link, title and visit time past a per-bank visit-id cursor (advanced only after the backend accepted a
batch) — on turning on, launch, a bank switch, Sync now, and every 10 minutes when the file's size or time moved (a
stat; Chrome rewrites History on most page loads, so no FSEvents watch); and the ones Cicada cannot sync
yet (Arc, Firefox, Edge, Opera) named once in the header, never as a row. Safari's source page groups its items as
Recently saved · Favorites · Other bookmarks. Under the browsers, **Ask why when I bookmark something** (G191, `saveWhy`,
off by default; `cicada.saveWhy.enabled`, per Mac like the watch's consent flags) — one switch that works: turning it
on also turns on the bookmark watch of every installed browser Cicada can sync (`SaveWhySetup`), named under the switch
before the flip — see *Ask why* below.
**Calendars, contacts & feeds** offers Calendar on this Mac and
Contacts (G154), both app-owned rows.

**Messages (G179, 2026-10-15).** Integrations → Messaging carries an app-owned **Messages** row (`MessagesRow`: the
Messages app's own icon, "Pick the conversations Cicada should remember" / "Remembering N conversations", *Sync now*
once one is ticked, *Choose…*, the browsers' `FullDiskAccessHint` when the read was refused, and *What came in*). *Choose…*
is a `SettingsSheet` (`MessagesPanel`): one sentence on what Cicada reads and why it needs Full Disk Access, one on
who is who, then each one-to-one conversation (`MessagesConversationRow`) — the contact's Contacts photo (else a
person's monogram, `EntityPictureFallback`), name (the contact's when Contacts is allowed, else the chat's own, else
the handle — shown in the app only, never sent), last activity and message count, a pill for who it is with ("AI
agent", "AI agent · suggested", "A person" — the person's own mark, `marked`, wins; "· suggested" only for a
detector's own answer; the free-form `actor` block keeps the backend's `decided_by`, which the app reads in either
spelling), *Is <name> an AI agent?* with Yes/No when the detectors are unsure, a menu
(This is an AI agent · This is a person · Let Cicada suggest) and the tick. `MessagesWatcher` (environment, started
on launch, `bankChanged` on a switch) owns the list, the per-memory ROWID cursors (`cicada.messages.cursor.<bank>.<id>`
in UserDefaults), the FSEvents watch on `~/Library/Messages` and the waiting bubbles; `MessagesReader` is the one SQL
reader (`SQLiteReadOnly`, read-only, one transaction; a BLOB projected only from a column named in `base64Blobs`).
The Sources card's *Sync now* routes to it (`ChannelActions.SyncRoute.messages`). **The bubbles:** on the Sleep page's
Waiting tab they ride the Messages source row itself (owner, 2026-10-16: one row — the Messages mark, its name, the
waiting chats' pictures, "N messages", the oldest age and the row's count; the second line is gone), and only when no
Messages episode is queued yet does `MessagesWaitingRow` draw a line of its own in the same grammar; Home's Today waiting
line carries the same `MessageBubbleStack` (non-interactive there): up to three overlapping profile bubbles, "+N" past
three, and the number of messages Sleep will read. A bubble's face follows the picture precedence
(`MessageBubbles.face`, pure and tested; owner 2026-10-16) — the person's choice on the chat's page (their upload, or
the monogram they chose; the page is the one `GET /sources/messages/waiting` links as `page`, the correspondent's own
page found by its decided record, never a page that merely shares the chat's name; loaded from Cicada's own picture
store) → the chat's Contacts photo (the card on this Mac, else the page's own Contacts rung) → **the photo the chat
shares in Messages** ("Share Name and Photo": `MessagesSharedPhotos` reads `~/Library/Messages/NickNameCache/` only
for the handles of every ticked conversation, at most once an hour per chat (after each read pass) —
`handledNicknamesKeyStore.db` copied with its
`-wal`/`-shm` into a private temporary folder and queried there, so Messages' files are never written or locked; the
record's keyed archive read as a property list, never unarchived; the `…-ad` avatar file used only as a regular file
directly in that folder, ≤ 8 MB, made ≤ 128 px — named either as a bare file or, as the current macOS writes it
(measured 2026-10-19: every real record had yielded nothing), as an absolute `imageFilePath` inside a nested
`NickNameImage` dictionary, accepted only when its parent is exactly that folder and then used by its last component
through the same checks (`folderFileName`); the record's `rid` (the same base64 with "/" where the file has "_") is not
turned into a name, since the path is what Messages wrote and the "/" → "_" rule would be a guess; the bytes stay in `MessagesWatcher.sharedPhotos` for the bubbles and,
when they changed since the last post, go to `PUT /sources/messages/photos` (2026-10-16), which keeps them outside every
bank and draws them at the chat's page everywhere — the `messages` picture rung, `storage.md`; a chat that stopped
sharing is posted as none, and a key store that could not be read posts nothing, so a revoked permission never removes
a page's picture; unticking forgets it on both sides) → the page's own `messages` rung (the server's copy of the same
photo, before this session looked it up) → a monogram (`MessageBubbleFace`: the face
inset 1.5 pt inside a disc of the ground's colour; the monogram is a disc filled with the person's hue at 35 % over the
ground with the letter in `textPrimary` — a hue ring round one letter read as "ⓘ" — and below 24 units its letters are
half its height, semibold; the bubbles only; never a shadow). Hovering a bubble names it ("Instinct · 34 messages
waiting to be read"); the Messages row's tooltip and VoiceOver label carry every waiting chat's line. `MessageBubbles.model` is pure and tested. Not a Store domain: `GET /sources/messages/waiting` is fetched
in memory whenever the status's unprocessed count moves. **Who is who in the Reader:** `EpisodeText.correspondent`
names a message conversation's `assistant` turns ("Instinct", through `ModelNames.agentLine`) and its `speaker`
turns; `ProvenanceConversation.correspondent` makes an evidence chip read "Instinct replied".

**Ask why (G191).** When the bookmark watch's own file event starts a sync (`BookmarkSyncSignal.live`, a task-local
the watcher sets; a catch-up, Sync now, Turn on or folder import is never live) and the result has exactly one fresh
bookmark, `SaveWhyPolicy` asks "What made you save this?" — unless the switch is off, the channel's sync was a first
sync, the browser's `addedAt` is older than 5 minutes (or 1 minute in the future), the site is muted ("Don't ask for
this site", `cicada.saveWhy.mutedHosts`, cleared from the Settings row), the same save already asked (a question
in the last 3 s, or the same save of the same link in the last 60 s — v3: a link saved again carries a new browser
instant, so it asks), or the person is typing in the panel's field (G191 live: no
three-minute limit — each bookmark in a row asks, and a newer one replaces the open panel). `SaveWhyCenter` fetches `GET /sources/saved-why/options` and shows `SaveWhyPanelController`: a
borderless non-activating `NSPanel` one level above the menu bar's (`.mainMenu + 3`, under menus) on every Space and
over full screen, shown with `orderFrontRegardless` (never key until the person clicks it). **It is the notch growing**
(v2, owner 2026-10-14): the window's top edge is the screen's top edge (`SaveWhyNotch.frame`, `constrainFrameRect`
overridden), centred under the hardware notch (`SaveWhyNotch.notchRect`, the gap between `auxiliaryTopLeftArea` and
`auxiliaryTopRightArea`), and its body is pure notch black in both appearances (`CicadaTheme.Notch`, the dark ladder's
text, `darkAqua` for AppKit's own field). `SaveWhyNotchShape` is the outline: at progress 0 it is exactly the notch
(its width plus two outward ears where it meets the top edge, the notch's height, its 9 pt bottom corners), at 1 the
whole panel (22 pt continuous bottom corners); `CicadaMotion.notchGrow` springs it out (0.34 s, bounce 0.16) and
`notchShrink` back in (0.22 s) before the window orders out. Under Reduce Motion it is drawn grown and only fades. The
top band (the notch's height, else the menu bar's) stays empty — the camera sits there — with the content under it. On a
Mac without a notch the same shape grows from a zero-height sliver at the top centre. One hairline sheen
(`CicadaTheme.Notch.edge`) marks the grown edge, faded out across the band; no glass, no shadow (DESIGN_RULES §9,
2026-10-14). The header carries the bookworm, `curious` room art (64 × 48) on its sheet's own frame timings. The chips are
the backend's reasons and "For <project>" per offered project, drawn as toggles (v3, below); under them a field that
is always there and **Save** (Return in the field). A click elsewhere (global and local mouse monitors), Esc (once the
panel is key) or the timeout closes it — silently with nothing chosen; what was chosen and typed is kept
(`SaveWhyPanelState`, pure and tested). The bookmark itself is captured as always; the app posts only the answer. The bookmark sync runs inside
Sleep's write window, so the answer can meet a 409: on a 409, a 5xx or an unreachable backend it is held in
`SaveWhyOutbox` (`cicada.saveWhy.pending`, per Mac, outside every bank, one per moment of saving, at most 20) with the time it was
given, and sent again — with that `at` — when the status's `writing` goes false, when the backend first answers and
on launch; a 422 or an answer over 24 h old is dropped (v6: a 404 is held for the next sync, below). Esc reaches the panel only once it is clicked, so its
hint names a click elsewhere as the way to skip.

**Ask why, live (2026-10-14, branch `fix/notch-live`).** Measured on the owner's Mac: the panel came 18 s after a
Chrome save, a Safari save was never seen, and "Something else…" was found open with nothing chosen. Four changes:
*Speed* — the 18 s were the sync itself (each new link's page fetch and two commits: 6-7 s) plus `Store.perform`
reconciling four domains before `syncChannel` posted its result, plus a fresh options fetch. A live sync now first
sends the same bytes to the read-only **`POST /sources/sync-bookmarks/fresh`** (`bookmark_sync.fresh_preview`: the
sync's own parse and `url_index` check, no lock, no write, never a 409) through `BookmarkSyncSignal.lookEarly` →
`SaveWhyCenter.lookEarly`, and the question is decided on that, with the options cached from the last fetch; the
sync's own result then arrives as `.afterEarlyLook` and only says the links are saved. An answer given before that
meets a 404, which is held (`awaitingIngest`) and sent when the sync lands; without the route (an older backend) the
sync's result decides as before. The watch settles 300 ms (`BrowserWatchPolicy.bookmarkDebounce`; the folder
watches keep 1.2 s), so save → panel is about 0.5 s; `SaveWhyLiveTests` drives the real watcher against a 3 s sync
and holds it to `SaveWhyPolicy.showBudget` (2 s). A save inside the 5 s floor or during a sync is now owed and read
after it, not dropped until the next save. *Safari* — the watch is an FSEvents stream per browser folder with
per-file events (`BrowserFileEvents`), filtered to the bookmark file's own name, not a kqueue on the folder: a kqueue
sees only entries added, removed or renamed in that folder, and its descriptor was opened once at launch, when
Safari's folder may still have been refused. A stream armed while the file was refused is armed again once an open
says it is readable (`BrowserWatcher.refreshAccess`: on the app becoming active, and every 5 s while one is refused),
with a catch-up that is never live. *Per memory* (owner decision 5, 2026-10-16): what was synced is kept per connection
AND per memory (`BrowserWatcher.signatureKey(channel, bank:)`), so a bank switch catches the newly active memory up on
the browsers' bookmarks like every other reader (`bankChanged`, from the app's bank-change hook); each sync's posts are
bound to the memory it read for (`BankScope.bound`) and its signature is recorded under that memory; a demo memory is
never read for. The old per-connection signature moves, once, to the active memory at the first launch after the
upgrade — only once the roster has loaded and `Store.bank` names it (before `hydrate()` it is the placeholder `default`,
and the old signature is then only read, never moved) — and the consent it implied is written down explicitly so no other memory reads as
turned off. *No self-opening field* — every chip and click from the panel goes through
`SaveWhyCenter.input`, which ignores a choice (and a click elsewhere) within `SaveWhyPolicy.armDelay` (0.5 s) of the
panel showing — at 0.5 s after a save the hand is still on the page beneath — and `SaveWhyNSPanel.canBecomeKey` is false
until a mouse-down lands in it, so no activation or stray key can press a chip or type; only `tapOther` opens the field.
*A save while a sync runs* (measured after #288: the second of two bookmarks 12 s apart asked at +12 s, when the
first's sync — ingest plus the store's reconcile — let the owed one start): a live change that cannot sync yet (a sync
running, or inside the 5 s floor) is looked at at once (`BrowserImportActions.peek` → the early look), and the sync
follows when the way is clear. Its bytes still hold the earlier bookmark, not saved yet, so every link an early look
saw is remembered with the look's number — taken before its file is read (`BookmarkSyncSignal.takeLook`), so a
higher number always read newer bytes and a sync that read before a bookmark existed never releases its held answer
(review B2) — (`SaveWhyCenter.seenFresh`) until a sync that read after it lands
(`.afterEarlyLook(look:)`), and a later look counts only what is new since — one fresh bookmark, not two. An answer's
404 is held until the sync of the look that asked it lands. Tested: two saves 10 s apart under a 14 s first sync, each
panel in ≈ 0.5 s.
*In a row* (owner, live: "shouldn't it be immediate?" — every bookmark after the first was silenced by the old
three-minute limit) — the limit is gone. Each single fresh bookmark asks; a newer one **replaces** the open panel
(`.superseded`, closing like a timeout, so a tap already made is posted) rather than queueing behind it: the person is
looking at the new page, and a queued question would ask about one they have left. Floods stay structural (more than
one fresh URL, a first sync, an import or a reorganisation never asks), plus `SaveWhyPolicy.repeatGuard` (3 s, one
save's double event) and `sameLinkGuard` (60 s, `cicada.saveWhy.lastURL`); nothing replaces a panel the person is typing in.
*Screen* — `SaveWhyScreen` puts the panel on the screen holding most of the browser's front window (window-list
bounds; no Screen Recording needed), else the front app's, else `NSScreen.main`, and the notch is that screen's own.

**Ask why: one switch that works (v2, 2026-10-14).** Measured on the owner's Mac: nothing appeared after a Chrome
bookmark because the switch was off *and* both browsers' bookmark watches were off — the question can only follow a
bookmark the watch sees. Turning the switch on (`SaveWhySetup.turnOn`) records it and calls `BrowserWatcher.enable` for
every installed, supported browser whose watch is off, explicit offs included — the row names those browsers before
the flip ("Turning this on also watches your bookmarks in Chrome and Safari."). Turning it off leaves the watches on:
bookmarks are still captured. Once on, the row says, in order: a browser whose file macOS refuses ("Safari keeps its
bookmarks in a folder macOS protects…", with **Open Full Disk Access** and **Check again**, which re-arms and re-probes
through `enable`), what is watched plus the seed sentence ("Your next bookmark will ask — the ones you already have
never do": `enable` syncs through the watch but never live, and a first read is a first sync), and a browser left off.
Access, as the watch already reads it: Chrome and the Chromium family live under `~/Library/Application Support` and
need nothing; Safari's `Bookmarks.plist` is in `~/Library/Safari`, which needs Full Disk Access to read *and* to watch
its folder — Safari exposes no bookmarks API to another app or a web extension, so there is no lighter route.
**The grant has to survive updates (2026-10-14).** macOS keys Full Disk Access (and every TCC grant) to the app's
designated requirement; an ad-hoc build's is its cdhash, so each update dropped the grant and Safari read "Needs Full
Disk Access" again. A developer install signs with the self-signed **Cicada Local** identity once `make
signing-identity` has made it (`sign_identity.sh`, `scripts/dev/README.md`), and keeps the grant across rebuilds; a
release keeps it only once a Developer ID signs it (`docs/RELEASING.md`, "Keeping macOS permissions across updates").
**Developer harness:** with `defaults write <bundle id> cicada.debug.saveWhyPreview -bool YES` in a developer build
(never a release app, `SaveWhyPreview.isAvailable`), the menu-bar menu gains *Preview "Ask why" (Chrome)* and
*(Safari)*: the panel for a placeholder bookmark at once, past every rule, posting and muting nothing
(`SaveWhyCenter.preview`).

**Ask why, v3 (2026-10-15, branch `feat/bookmarks-v3`; owner: "When I bookmark something in Chrome, it takes quite a
bit for the prompt to appear … If I remove the bookmark and bookmark it again, the prompt doesn't appear … We should
have the option to select various reasons … as well as input something in the text bar").**
*At once in Chrome, no extension* (v3's mechanics; **v4 below replaces the size learning and the tick**). Chrome holds a bookmark change for `BookmarkStorage::kSaveDelay` = 2,500 ms before
it writes `Bookmarks`, so no file watch can ask sooner. But ⌘D or the star opens Chrome's "Bookmark added" bubble as a
window of its own, and the window list (`CGWindowListCopyWindowInfo`) gives every window's owner, number, layer and
bounds without Screen Recording — never a title. `BookmarkBubbleWatcher` runs only while Chrome is the frontmost app:
each 50 ms tick asks `CGEventSource.secondsSinceLastEventType` (no permission) and only in the 1.2 s after the
person's own key or click reads Chrome's windows (at most every 100 ms). `BookmarkBubbleDetector` (pure) takes a new
window of a bubble's size (280–420 × 100–480), under the toolbar (56–170 pt below the browser window's top), its right
edge within 320 pt of the window's right edge and its left edge in the window's right part, on a browser window at
least 700 pt wide, within 1 s of the person's input. Chromium's other bubbles there share the bubble width: the
password and translate bubbles open on their own (no input), permission prompts and suggestions sit elsewhere, and the
extensions/profile/downloads menus are learned away — a size that came with no bookmark `refuseAfter` (3) times, and
never with one, is refused (one miss never is: Chrome's "Edit bookmark" bubble on a page already bookmarked, or Remove
pressed in the bubble, brings no new bookmark from the real bubble), and once one came with a bookmark only that size
counts (`BubbleMemory`, `cicada.saveWhy.bubble.<bundle id>`, sizes and miss counts only). A bookmark is recorded for
the bubble as soon as the app's diff (or the look) sees one new bookmark on that browser, whatever the ask-or-skip
decision — a muted site never teaches a miss. The center
(`SaveWhyCenter.bubbleSeen`) opens the panel at once, **pending**: "Saving in Chrome…", the toggles and field live,
"Don't ask for this site" held in place but hidden. *The link before the backend answers.* Each read of a bookmark
file is parsed and diffed in the app too (`BookmarkFileDiff`, beside the early look: `BookmarkSyncSignal.diffAndLook`):
one link the last read did not hold, or a node newer than any it saw, is named at once (`candidate`) — the link fills
in, or the panel opens with it (Safari, a missed bubble). The baseline is per channel in memory, seeded at launch when
the switch is on; with none yet the backend's look decides alone. *Confirmed, never guessed.* A panel opened by the
bubble or the diff is unconfirmed: nothing is posted until the early look or the sync agrees about a bookmark on that
browser (`noticed` binds it and sends an answer already given, with that save's `addedAt`); a refusal (first sync, many,
old, muted) or no bookmark within `SaveWhyPolicy.pendingBound` (6 s; `confirmBound`, 15 s, once the diff named one)
withdraws it and drops the taps. Measured on a synthetic 20,000-bookmark Chrome file (2.4 MB): the app's read < 1 ms,
its parse 78 ms and diff 82 ms; the early look's round trip (base64 3.3 MB body, the backend's parse and `url_index`
check) 343–401 ms in process. So click → panel went from ≈ 3.25 s (2.5 s Chrome + 0.35 s watch + 0.4 s look) to
≈ 0.1 s (the bubble), with the link at ≈ 3.0 s and the confirmation at ≈ 3.25 s. Safari's ⌘D opens its own popover
*before* anything is saved (the bookmark is made only on Add), so no bubble path there: Safari asks on the diff
(Cicada's part on a synthetic 20k-leaf binary plist: parse 39 ms, diff 14 ms; Safari's own write delay is not measurable from synthetic files).
*Re-saving asks again.* The backend reports a link saved again as fresh with `resave: true`
(`bookmark_sync._resaved`: absent from the channel's last seen-set and present now, or a browser instant newer than the
newest the last sync saw — a move keeps both); the panel's subject says "Saved again"; `sameLinkGuard` holds only the
same save (the same `addedAt`, `cicada.saveWhy.lastAddedAt`). *Several reasons, plus words.* The chips are toggles with
a check slot that is always there (one weight both ways, so a tap never reflows the row); the field and Save are there
from the first frame, so the shape grows once and never jumps. After a tap the panel waits `answerIdle` (10 s;
`writingIdle`, 45 s, once words are typed) and then keeps what was chosen (v6: gone — a touched panel waits for the
person); Save, Return, a click elsewhere, Esc or a newer bookmark keep it too; one tap and leaving is an answer. *Settings* adds, under the switch while Chrome is
watched: "To ask at once, Cicada notices when Chrome shows its bookmark bubble — it looks only at where Chrome's windows
are, never at what they show, and needs no permission." The optional instant link through Apple Events (`URL of active
tab`) is not built: the diff fills it 2.5 s after the click without a permission.

**Ask why, v4 (2026-10-15).** *A few basic reasons* (owner: "keep options to a minimal"):
the panel offers exactly four — The design · The product · To read later · Useful someday (`design`, `product`,
`read_later`, `someday`) — in two fixed rows of two (v6: one line, below), and the field's placeholder is "Something
else…". No project chips (`tapProject` is gone; the options' `projects`
is always empty). The app carries the four as `SavedWhyOptions.basic`, so no panel waits on the options fetch and its size
never depends on it. An answer given before keeps its retired reason (`technique`) and its project wherever answers are
listed; the bookmark page's editor shows them as chips only for that answer, so an edit never drops them unseen.
*The click is the trigger, the file the only confirmation* (owner: "the size check of the popup seems like depending on
that is not great. What about just checking when the star is clicked … make sure this polling is efficient"). Measured on
the owner's Mac: Chrome's "Bookmark added" and "Edit bookmark" bubbles are both 448 × 224 pt, layer 0, 80 pt under the
window's top, right edge 232 pt in — v3's 280–420 width range refused it every time, and size cannot tell the two apart.
`BookmarkBubbleWatcher` now: nothing while Chrome is not frontmost (armed and disarmed on
`NSWorkspace.didActivateApplicationNotification`); while it is, one global mouse-down monitor (no permission for mouse
events) and nothing else — no timer; a click reads the window list once and, only when it landed in a browser window's
toolbar band (top 110 pt), runs a burst of at most 8 reads 50 ms apart that ends at the first new small Chrome window
anchored under the toolbar on the right (`BookmarkBubbleDetector`: 160–720 × 60–720, the v3 position rules, layer ≤ 20 —
a 149 × 18 tooltip at layer 103 never counts) or by itself at 400 ms. v3's `cicada.saveWhy.bubble.<bundle id>` keys
(refusals among them) are removed on start.
*Only a shape a bookmark confirmed (v5, 2026-10-16; owner: "when i open chrome extensions there is a popup that triggers
cicada popup. thats bad").* Every toolbar surface is anchored where the star's bubble is, so position cannot tell them
apart: the Extensions menu (≈ 287 × 481, 102 pt under the window's top, right edge 132 pt in, taller with each
extension) opened the panel pending, and the profile menu and downloads bubble fit too. Their shape does: the bookmark
bubble is a fixed 448 × 224 (Chrome's modal-dialog width) on every page, 161 pt wider than the Extensions menu. So the
anchored window opens the panel only when its size is within 4 pt of a **confirmed shape** and it hangs from the click
(the click's x within its span, up to 48 pt past its right edge — the star sits at its right end). Confirmed shapes
are the measured 448 × 224, in code, plus any learned **positively** (`BubbleShapeMemory`,
`cicada.saveWhy.bubbleShapes.<bundle id>`, shapes only, newest first, at most 4): an anchored window of an unknown shape
opens nothing and is held in memory; when the app's diff then names one new bookmark on that browser
(`SaveWhyCenter.onNamed` → `BookmarkBubbleWatcher.bookmarkNamed`, any decision, a muted site included) whose own
instant (Chrome's `date_added`, microseconds since 1601 read to the microsecond from the file, never the backend's
seconds-floored `addedAt`) lies between the click (less 0.5 s of monitor lag) and the moment the window was seen, within
20 s, that shape is remembered — Chrome makes the bookmark before it shows the bubble, so a ⌘D with a menu open, an
extension saving from its popup or a bookmark synced in falls after the window and teaches nothing (review 2026-10-16:
the floored instant with 1.6 s / 0.5 s slack let a ⌘D ≈ 1.5 s after the Extensions menu teach the menu for good). Two
held windows that both fit teach nothing, and a measured bubble drops every held window on its browser. Nothing is ever refused or counted against a shape, so a bookmark that fails to match teaches
nothing (v3's flaw); a menu followed seconds later by a ⌘D is not that window's bookmark. A Chrome
update or a font change that resizes the bubble costs one slower question — that save is caught by the file (≈ 2.5 s,
as ⌘D is) and teaches the new shape — and the next star click is instant again. Still no permission, no title, no
timer; the click → panel path is unchanged for the measured bubble. ⌘D gives no permission-free event (another app's keystrokes
need Accessibility or Input Monitoring, never asked), so a ⌘D save is caught by the file. Idle with Chrome in front,
measured over 60 s in a synthetic harness: 0 window-list reads, 0.07 s CPU for the whole test process (0.11 %). The
pending panel binds to the one new bookmark the app's diff finds; a removal-only change ("Edit bookmark", then Remove)
withdraws it at once, and no bookmark within `pendingBound` withdraws it — keeping nothing either way; a second bubble
while one waits restarts the wait. *File write → panel, waiting on nothing else.* The coordinator measured ≈ 0.3–1.3 s
from Chrome's write to the panel. The watcher now looks at once on a save's first file event (`instantLook`, before the
300 ms settle): it reads the file through its own paths, diffs it in the app and offers one new bookmark to the center —
never behind this channel's running sync or its 5 s floor, another browser (a Safari refused Full Disk Access, its 5 s
recheck), the network or the options. One read per channel at a time; a file caught mid-write parses to nothing and never
moves the baseline (`BookmarkFileDiff.record`), and reads are numbered so an older one never overwrites a newer. The
baseline is read when a turned-on browser's watch is armed (`primeBaseline`), not only at launch with the switch on.
Measured (354 bookmarks, a rename as Chrome writes, Chrome's sync and Safari's both hung, the look never answering):
write → event 11 ms, read < 1 ms, diff 5–6 ms, **panel 17 ms**. Stage timings are logged as durations only
(`com.cicada.app`, category `save-why`). *No longer in the browser.* A bookmark removed in the browser is kept, its
reasons and page untouched, and marked from the sync that saw it gone (`leftBrowser` on `GET /sources`, see `api.md`):
the bookmark's page says "No longer in Chrome since Oct 15" with "Cicada keeps it, with why you saved it. Bookmark it
again to link it back."; the ⌘B row is dimmed (60 %) with a quiet `bookmark.slash` mark carrying that line as its help;
Sources' bookmark list keeps the row, its title tertiary, with the same mark. The import summary says "N no longer in the
browser". Re-adding it clears the mark and asks again (a re-save). Nothing reaches the inbox.

**Ask why, v6 (2026-10-19, branch `fix/save-why-panel`; owner, with a screenshot of the panel beside Chrome's "Edit
bookmark" bubble).** *One line* ("The four options could all fit on a single line"): the card is 468 pt (`SaveWhyPanelView.width`)
and the chips a little tighter, so the four sit on one row at 1× (measured on the real chips in a test: 94 + 101 + 102 +
122 pt plus three 6 pt gaps in 444); `SaveWhyChipRows`, a SwiftUI `Layout`, wraps them into the fewest balanced rows that
fit — two and two at 1.4×, never three and one — when a larger text size leaves no room (DR-70).
*Never lost to a dismissal* ("I bookmarked a website, explained what interested me, and pressed anywhere else on the
screen (not the Done button). In Cicada I see that it didn't save"). What happened before: a click elsewhere did keep the
taps and words (`SaveWhyPanelState` posts the selection on leaving; the field's binding updates on every keystroke), but
an answer given before the backend confirmed the bookmark lived only in memory (`unconfirmedAnswer`) and was dropped when
no confirmation came within `confirmBound` (15 s, from the diff naming the link) — and none comes when the early look is
unanswered and the sync itself is refused while Sleep writes (409: nothing posts a result, and a refused sync was not read
again until the next bookmark); an open unconfirmed panel was even withdrawn under the person's hands by the same timer;
and a held answer that met a 404 ("that link isn't saved yet": its sync had not run) was dropped for good. Now an answer
about a link the app's diff named is held in `SaveWhyOutbox` at once, `awaiting` that browser's sync — never posted before
a sync of that browser lands (the rail), posted when one does (`SaveWhyCenter.syncLanded`, after every sync the watch, a
catch-up or Sync now finishes); a 404 holds it for the next sync instead of dropping it (`Verdict.waitForSync`); and when
Sleep lets go the watch catches up (`BrowserWatcher.catchUp`) before the held answers are retried, so a sync refused
during Sleep is read again at once. A withdraw closes only an untouched panel; a touched pending panel whose browser saved
nothing stays and says "No new bookmark was saved, so there's nothing to keep this with." — an answer with no bookmark is
the one thing never kept. Remove pressed in Chrome's bubble, or the backend naming another link, still withdraws and
keeps nothing.
*Only the person closes a touched panel* ("I use Wispr Flow a lot for dictation … I selected the text box and was
dictating and [the panel] went away"): dictation types nothing until it is done, so the field read empty and the
question's own 12 s timer (`askTimeout`) dismissed it — and an unconfirmed one also met `pendingBound`. A tap, a word or
a click into the field (`engage`, also on the field taking focus) stops every timer (`answerIdle`/`writingIdle` are gone):
the panel closes only on Save, Return, Esc, a newer bookmark, or a click outside both it and Chrome's bubble. Losing the
keyboard to another app's floating window never closes it (nothing listens for it). A click inside Chrome's bookmark
bubble (its frame from the watcher's own read, `BookmarkBubbleWatcher.lastBubble`) is the person working there: the panel
stays, and one window-list read 0.25 s after that click (`SaveWhyPolicy.bubbleCloseCheck`, bounds only) tells whether it
closed the bubble — Done or Remove — which closes the panel too. Bounds cannot tell Done from Remove, so that answer (or
edit) is held, awaiting, until Chrome's file says: a removal on that browser drops it (`bookmarkRemoved`), no removal
within `pendingBound` (Done writes nothing) lets it go (`removalWatch`). Review 2026-10-19: an answer given on the pending
panel and closed before Chrome wrote is held the moment the diff names its link (`holdUnconfirmed`); the backend
agreeing about another link withdraws only an untouched panel and never drops an answer already bound to its own link
(it waits for that link's sync); every held answer carries the memory it was given in and is sent only while that memory
is active (the split-brain rule); a 404 on an edit is final. *Typing and dictation land in the panel* (2026-10-19, after "the panel never takes focus from Chrome", so an
inserter that writes into the frontmost app's focused element wrote into Chrome): a click into the field makes the panel
the **key window** — still a non-activating panel (`canBecomeKey` once clicked, `canBecomeMain` never), so Chrome stays
the active app and no other Cicada window comes forward — and the field its first responder, which is what the key
window's Accessibility answers as focused (`AXTextField`, tested in-process). The app that had the keyboard is noted at
that click (`SaveWhyNSPanel.onTakingKey`) and gets it back on Save, Return, Esc or a newer bookmark
(`SaveWhyPresenting.hide(returnFocus:)`: `NSApp.yieldActivation(to:)` then `activate(from:)`); a click elsewhere leaves
the keyboard where the person put it.
*The star on a page already saved* ("Touching the star, even if it's already bookmarked, keeps prompting me … It should
just put the same Cicada prompt, but with the text already filled in"). The "Edit bookmark" bubble is the same window as
"Bookmark added" and Chrome writes nothing, so neither bounds nor the file can tell which page it is. `SavedBookmarkLookup`
asks Chrome for the front tab's URL through Apple Events **only when Automation of Chrome is already allowed**
(`AEDeterminePermissionToAutomateTarget` with `askUserIfNeeded` false — never the prompt, which still comes only from
Remove bookmark…; **owner ruling 2026-10-19**: the prefill reads Chrome's front-tab URL only when Automation is already
allowed, never prompting), right after the star click opened the bubble; the URL is matched exactly against what Chrome's file held
before the click (the diff's baseline) and the Store's `chrome-bookmark` records, and is never stored, logged or posted.
A match turns the pending panel into that bookmark's (`SaveWhyCenter.adopt`, confirmed — Cicada holds it): its newest
answer's chips and words filled in ("Already saved · <title>", "Already saved. Change anything, or click anywhere else to
keep it."). Leaving unchanged writes nothing; a change is one `PUT /sources/saved-why` of that answer (by its `at`, held
through a 409 like any answer), never a new answer or a second save; an emptied answer is never written as a deletion; a
retired reason or a project the panel cannot show is kept. A saved bookmark never answered asks as usual and posts a first
answer for that save's own moment. Remove in Chrome's bubble withdraws it, writing nothing. Without the Automation grant
the star on a saved page still opens the pending question, which leaves on its own unless touched.

**Bookmarks in the menu bar (G191 v3).** The status menu's **Bookmarks…** (⌘B) opens `BookmarkHistoryController`, a
Maccy-like panel under the status item (borderless, key without activating the app, closed by Esc, a click elsewhere or
opening a row): a search field, then every bookmark (`origin` `<browser>-bookmark`) from the Store's `sources`
snapshot — warm, no new fetch — newest saved first (`lastSavedAt`, a re-save moving it up), the first 300 shown and
the rest one search away; ⌘1…⌘9 open the first nine, ↑/↓ and Return the selection. A row (`BookmarkHistory.row`, pure)
is a picture, the title, the newest answer's reasons and words (else the site) and the age. **Pictures:** the site
capture's thumbnail when Cicada holds one (`captureThumb`, `/explore/captures/…/thumb` from the bank), else the stored
preview (`/entities/{id}/preview`, fetched once by the backend under its gates), else a monogram — both through
`StoredPreview` with the bearer; never a URL the page names (`PictureURL.parse` admits `/explore/captures/` as an API
path). A row opens the app on that bookmark's page: Sleep › Saved's detail (`AppRouter.routeToBookmark` → `pendingSavedItem`,
the window opened if closed) — the saved item's established landing (R-DL16), a Store domain in memory, showing the
link itself; the entity page is one click on. There `BookmarkReasonsSection` lists every answer newest first ("Saved
again 15 Oct, 12:00 · said …"), each editable with the same toggles and words (`SavedWhyWrite` → `PUT /sources/saved-why`,
or `POST` for a first answer; painted at once, rolled back on a refusal), and **Remove bookmark…**: asked first in words.
Cicada forgets it first (`BookmarkRemove` → `POST /sources/bookmarks/remove`; a refusal such as a 409 while Sleep writes
leaves Chrome untouched — `BookmarkRemoveFlow`), and only then is Chrome changed. Only the copy this save made is
targeted: the node in Chrome's default-profile file whose `date_added` matches the record's `lastSavedAt`
(`ChromeRemovalPlan`); with several copies of the link the confirmation says so and offers "Remove the copy saved …" or
"Remove all N copies". The script (`ChromeBookmarkScript`, `osascript` as Cicada's child, so the one-time "Cicada
wants to control Google Chrome" comes only now) addresses each node and each folder of its chain by its `guid` —
what Chrome's AppleScript calls `id` (fix 2026-10-15, verified live: the numeric `id` fails with -1728, so v3's script
deleted nothing) — quoted and accepted only as an 8-4-4-4-12 hex UUID, the numeric id (digits only) only for a node
with no `guid` (an older Chrome); the generated script is compiled in a test (`osacompile`, never run) — but deletes it
only `if URL of b is targetURL` — Chrome's Apple Events act on the last-used profile, where the same id can be another
bookmark — with the URL passed as `on run argv`'s argument, never in the source, and returns how many it really
deleted (0: "the Chrome profile that's open doesn't hold this bookmark"). Mobile bookmarks cannot be reached and are
named. A refused Automation or a failure leaves it removed in Cicada and says how to finish in Chrome. Safari offers no way for another app to edit its bookmarks: the section
says so and offers **Open Safari** (Bookmarks › Edit Bookmarks).

**Agent wiring (Track I T3/T7).** `GET /agents/wiring` is read-only: per harness it reports
*recall* (the MCP server registered — `claude mcp get cicada` / `codex mcp get cicada --json`, 6 s
each and side by side (round 4: at 2 s the live Welcome read Claude Code as 'couldn't check in
time'), a timeout is `unknown`) and *auto-save* (the G105 Stop hook, via `api/hooks/registry.py`; an
unparseable settings file is `invalid`, never `off`), *auto-recall* (G149: `autorecall`
= `on|off|stale|invalid|n/a` for the recall hooks, with `autorecallOn` / `autorecallOff` argv kept apart from
`connect`: onboarding's *Connect for me* for Claude Code and Codex runs `connect` and then `autorecallOn` (every command
shown before the click), and Settings → Agents → *Remembers automatically* keeps its own click), *the capture
flush* (G110 gate A: `autosaveFlush` = `on|off|stale|invalid|n/a` for the capture command under `PreCompact` and
`SessionEnd`, with `flushOn` argv kept apart from `connect` — the setup prompt runs exactly `connect` and four commands
do not fit it; `autosave` stays the Stop hook alone, so an install from before the flush still reads on; the app
appends `flushOn` only to a Connect it is already running, `AgentWiring.turnOnSteps`, and install.sh registers it),
plus the exact argv install.sh would run. The **app** runs them, only after the person's click (spec decision 14, D-1), with
`CICADA_CAPTURE=off`, behind an allowlist pinned to its own checkout (which also accepts the recall hook's two
events, the capture command under `Stop`, `PreCompact` and `SessionEnd` only, and `registry.py uninstall --hook recall`); the backend never writes a harness root. **Claude Code through the Cicada plugin**
(owner 2026-10-19; `mcp.md`, "The Claude Code plugin"): when the plugin is enabled, installed and able to run a Cicada
(`registry.plugin_state` is `on`), Claude Code's row reads `recall`, `autosave` and `autosaveFlush` `on` and
`autorecall` as the plugin's own `recall` setting, with `capabilities.via = "plugin"` and no argv at all (the plugin
carries the server and every hook; an `mcp add` or a settings hook beside it would run twice), and `detail` names any
Cicada hook still in the settings file; an enabled plugin that would run nothing leaves the row probed as before, with
why in `detail`. `AgentWiring.viaPlugin` makes *Remembers automatically* say it is switched in the plugin's settings
(`Copy.autoRecallPluginOn` / `Copy.autoRecallPluginOff`) and offer no button. `GET /agents/setup?harness=` (round 4 C5, G76's in-app half) serves
what to hand an agent instead of running anything (for Claude Code with the plugin on, a prompt that runs nothing):

- for Claude Code, Codex and Gemini CLI, a plain prompt (≤ 1,200 characters) that names the exact
  commands, built by the same step builders `/agents/wiring` uses (both steps always,
  `display == shlex.join(argv)`);
- for Cursor, its MCP install link and the startup-hook and capture-hook merge argv, plus (2026-10-14) a `prompt` for
  Cursor's own agent that adds the MCP server to `~/.cursor/mcp.json` and nothing else — both hooks stay their own
  clicks (R-H11); Remembers automatically offers the startup action independently, and Settings → Agents' Cursor
  steps add *Save chats on their own* (the wiring's `connect`, the capture hooks) while capture is off;
- for OpenCode, Hermes and OpenClaw, a prompt with no commands naming the server and where it lives in the agent's own
  settings;
- for `other` (2026-10-14, "Another agent"), one generic prompt — the server spec, "add one MCP server named cicada to
  your own MCP settings, in the shape they already use", change nothing else, if you can't, say where they live and
  what to add, uploads nothing, one sentence back — that names no agent (provider-neutral copy);
- for the Claude app, a config merge the APP performs and **no prompt**: its chat cannot edit its own config, and
  handing the file to some other agent would trade the app's backup-first merge for a hand edit of a file holding
  other servers' secrets.

Every prompt names the server through `agent_wiring.server_lines` (command, one `argument:` line per argument,
environment), so a release app's argument-less `~/.cicada/bin/cicada-mcp` reads right (G182; the config prompts used to
index a first argument and failed there). ≤ 1,200 characters, commands and paths never shortened. No probe, no
subprocess, no ETag.

Cursor's registered local IDE adapter adds a wiring row with independent MCP registration (`recall`),
startup configuration (`autorecall`) and capability/evidence (`capabilities`) fields; the Swift decoder
defaults capabilities to an empty dictionary for older payloads. This endpoint remains request/response,
outside Store/sync/VersionVector. The existing neutral startup button/command disclosure is reused
(DR-38/39/40/41); its allowlist pins the helper/command to the app runtime and the settings file to this
user's `~/.cursor/hooks.json`, and the hook group to `--hook startup | capture` (capture-everywhere,
2026-10-14). No project hook or Stop registration is allowed. Cursor and Gemini CLI are in
`ModelNames.savingHarnesses`, so their steps drop the no-autosave honesty line; they stay out of
`capturingHarnesses` because their MCP writes are not yet joined to a captured turn. Installed Cursor hook delivery,
timing/tool choice and visual rendering are unverified; `mcp.md` and `capture-and-sleep.md` specify the capture,
CLI/cloud/remote boundaries. No app launch is needed to configure or test this seam.

Settings → Agents → **Editing pages** (G198, `PageEditorsGroup`, its own file plus one line in `ConnectView`, row id
`agentsEditors` in the index): one row per local agent `GET /settings/editors` lists as a candidate (plus any already
allowed that it no longer lists), its Track L mark (DR-52), "Allowed since <day>", "On by default" (a default with no
day) or "Asks in your inbox first", and a system switch with its label spoken (DR-40/41). While the response says
`customized: false`, a note names its `defaults` (owner 2026-10-14: "Claude Code and Codex edit pages directly unless you
turn them off.") — the names come from the backend, never from app copy. `PageEditorsModel` reads the list when the page appears (and on the SSE
reachability flip), writes one switch at a time with `PUT /settings/editors` (`{trusted: {harness: bool}}`), shows the
change at once and puts it back with the server's sentence on a refusal. Machine-wide, outside every bank, not a Store
domain (no ETag). Copy names only the agent's app (provider-neutral).

Settings → Agents (round-4 D5) adds, per harness, Connect for me (the same `AgentConnect.run`), Copy
setup prompt (`GET /agents/setup`'s prompt shown verbatim, then copied — the agent runs the install itself), Open in
Cursor (the catalog's own deeplink) and Set up Claude (`ClaudeDesktopConfig` merges `mcpServers.cicada` into Claude
desktop's config: backup first, merge never replace, an unreadable file left untouched; the app computes the path and
the value itself). Round 4 C8: Settings → Agents is one selector of eleven agents (`AgentCatalog`, pinned to
`agent_live.LIVE_AGENTS` by `api/tests/fixtures/agent_catalog.json`) with numbered steps below (`AgentSetupSteps`),
reused by onboarding. OpenCode, Hermes and OpenClaw register by editing their own config from a pasted prompt — Cicada
runs nothing for them and only reads that file (`agent_wiring.config_state`, ≤ 256 KB, parse-only); Claude, ChatGPT and
Grok go through From anywhere (`kind: remote`). **Sign-in (ruling 32):** while the switch is on, From anywhere polls
`GET /remote/oauth/requests` every 3 s (everything else every 30 s) and, while any wait, shows *A sign-in is waiting*
above the reach card: a field for the code the person's own sign-in page shows (`RemoteSignInApproval`: Find shows who
it is — "Unverified app (registered … ago)" with the generic mark, or a metadata-document app "published by <host>" —
where it returns, a loopback warning, scope checkboxes starting from what it asked, else the defaults, a 7/30/90-day
expiry, Cancel and Approve), and *Waiting requests* listed only by when they started, each with Deny, plus Deny all.
It is the only place a sign-in is approved, and only by the typed code (security review of #359). The connectors card
says, under its header, how Claude and ChatGPT sign in with `<address>/mcp`; a signed-in connector (`auth: oauth`) shows
no Rotate. Cursor's card adds *Or copy and send this to Cursor* (its prompt, shown
before it is copied) after Open in Cursor. The last pill, *Another agent* (`AgentCatalogEntry.Kind.anyAgent`, the
neutral glyph Integrations' "Other agents" wears, DR-52; Settings-only, so onboarding keeps the owner's nine), is
*Copy and send this to your agent* → Confirm, with its own "Do it by hand" `mcpServers` snippet; its ✓ lights for a
local `initialize` from a client that names itself but matches no other pill (`agent_live.agent_for` → `other`; the
release smoke test is excluded). `GET /agents/live` lights a pill's ✓ from the local handshake ledger
rows, a used connector (`last_used_at`) or the agent's own config — no subprocess, never `~/Library`, never
`~/.claude.json`; polled every 3 s while the page is visible.

**The Skills page (owner 2026-10-15, third take).** The tenth rail page, after Looks (DR-22 as amended 2026-10-15: no
shortcut moved; it has no ⌘ digit — the row ends at 9 and ⌘0 is Actual Size — so it opens from the rail and ⌘K; `RailItem.key` is nil
past nine). `SkillsPage` over `SkillsPageModel` (in memory, not a Store domain; `SkillsAPI`, faked in `SkillsPageTests`)
shows `GET /skills` as **one plain table** — Skill (the name and one muted line), Agents, Status — with no pictures.
The Agents cell is one pull-down ("Claude Code, Codex +1 ▾", `SkillAgentWords`) listing every agent installed on this
Mac: tick to turn the skill on for it, untick to turn it off; an agent that reads another's folder shows a hollow tick
and "through Claude Code"; agents not installed are hidden. Status is one quiet word from the backend's `status`:
"Up to date" with a dot, "Local", "⚠ Refresh" (a tool skill's text older than its tool), or an **Update** chip whose
popover (`SkillChangesPopover`) lists what changed ("0.1.13 → 0.2.0", each commit or release) and holds the one Update.
Selecting a row opens the side column (`SkillDetailColumn`: the repo link, versions, the Mac permissions in words
labelled "Checked for Cicada" with a line that an agent in another app may differ, an instructions excerpt, Remove…). The header has the add field ("Add from GitHub, or paste npx skills add…", ⌘N), which
opens `AddSkillSheet` (the SKILL.md, the files with scripts called out, the commit; Install installs exactly that); an
agent's request is one line above the table; tabs Installed · Discover (the catalog) · Drafts (agents' drafts and what
Sleep noticed). The page opening re-checks for updates only past an hour.

**Settings → Skills (G138).** A reviewed catalog (`api/data/recommended_skills.json`: source,
licence, the reviewed commit and SKILL.md hash, needs, agents, a terms note, the Cicada tool it
bridges, and for the two harnesses a `tool` block and for them and the video skill an `onboarding` line;
`scripts/verify-skills.sh` re-checks it) served by `GET /skills/recommended` — at most
five not-installed entries by rank, install state derived per request from `SKILL.md` files and
Claude Code plugin ids, never an agent's config. Since the Skills page (2026-10-15) **the app installs nothing and
writes no skill folder**: `SkillInstaller` and its consent sheet are gone, Cicada's own `cicada`,
`cicada-librarian` and `linkedin-people` rows and a skill's detail hand off to the page (`AppRouter.routeToSkills`), and every install is the
backend's `skill_store` (`api.md`, "Skills"). Hosted MCP servers and agent-prompt texts stay copy-only. The handshake gains a capability line only for an installed, active bridge
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

**Sources page — v3 (owner 2026-10-19; supersedes v2's tile grid, G124, DS-3c).** The owner: *"The Sources page needs
an urgent redesign. It has these graphs and stuff, and it's not intuitive … in two clicks I click on something, then I
click on Chrome, and then I can see all the things that I've saved in Chrome. Instead of putting the Chrome logo maybe put
the website's logo … Clicking again on Sources takes me back to the main Sources page also."* Dated ruling:
`docs/design/DESIGN_RULES.md` §9, 2026-10-19.
- **The root answers "where did my stuff come from".** Two groups of rows (`SourceIntentGroups`, pure): **Saved by
  you** — the sources whose items the person saved on purpose (every browser's bookmarks, Pinterest, Reddit, X,
  Instagram, YouTube, LinkedIn, TikTok, Files & links) — then **Captured for you** (agent conversations, chat exports,
  messages, calendars, feeds, Notes, folders, open tabs and tab groups). The split is the backend's: every
  `GET /sources/overview` row carries `intent` (`source_overview.intent_of`, `SAVED_SOURCES`; an unknown origin, a
  harness and a folder are captured; the ETag's shape moved to `overview-v3`), and an older payload reads as captured.
  Within a group the newest activity leads. A row (`SourceListRow`, 56 pt, `listRowSurface`) is the bare mark, the
  brand and one line — what came from it in its own unit and what it is doing ("342 saved · Watching", "204
  conversations · Captured by hook"; `SourceListText`); a failing source says its failure in `warning` instead, the
  whole error in `.help`. No sparkline, week-dots, delta or tile (v2's `SourceCardGrid`, `SourceGridColumns` and
  `SourceGridPacking` are gone).
- **Statistics, one quiet disclosure.** *Statistics* (collapsed, remembered on the old `cicada.usageMode` key, DR-39)
  holds *Who wrote your memory* (`ContributorsStrip`, whose chips still open the contributor column) and
  `AdvancedStatsView`. Both are statistics, so neither sits on the first screen; the contributors are no longer rows
  of the list and ↑/↓ walks sources only.
- **Two clicks.** Opening a source narrows the page to the same two groups (`SourceGroupsList`, triage) and opens its
  detail column. A **saved** source's column is its list: the sync row (Sync now / Last synced, as before) and
  `CapturedItemsList(style: .saved)` — everything saved from it, newest first, twenty a page with *Show more*
  (`ChannelItemsCache`, a `LazyVStack`), read from `GET /sources/channels/{id}/items` under the channel, or under the
  row id for a channel-less import (`SourceOverview.itemsListId`). Its 30-day header card and queue strip stay with
  captured sources only. Each `SavedItemRow` (56 pt) is the **site's mark**, the title and the day ("Today",
  "Yesterday", a weekday, "Oct 3"; the full date in `.help`, DR-58), and under them the person's own words from *Ask
  why*, then the reasons they tapped, then the host (`SavedItemText`). A row opens where a saved item opens (Sleep ›
  Saved, `CapturedItemRoute`). A bookmark that left the browser keeps its dimmed row and `bookmark.slash` mark.
- **The site's own mark (owner ruling 2026-10-19).** `SiteIcon(site:savedItem:)`: the row asks
  `GET /sources/saved/{id}/site-icon` (`SiteIconStore`, one answer per site and bank, misses too), and the backend asks
  the link's own site — never an icon service (`storage.md`, "A saved link's own site icon"). Until it arrives, or for a
  site with none: the bundled mark of a known family (LinkedIn, X, Instagram, TikTok, Reddit), else a ring monogram of
  the site. Never the browser's mark. With `CICADA_ALLOW_LOGO_FETCH=off` every row is its monogram.
- **Watch history is never a save.** YouTube and TikTok history days are their own captured rows (*YouTube history*,
  *TikTok history*), headlined by their days ("30 watched days", `SourceOverview.isWatchHistory`), and their detail
  lists those days by title under the row's own id (`GET /sources/channels/youtube-history/items`, each opening in the
  Reader); a channel-less saved row counts its saved media pages — the set its list lists — never its episodes
  (review of #347).
- **Clicking Sources again returns to the root.** `NavRail` reports a cell tapped while its page shows
  (`RailReselect`) to `AppRouter.reselect(_:byKey:)`; `SourcesPageView` closes the Reader and the detail together on the
  columns' curve, instantly when the ⌘ shortcut did it (DR-60). Since *say it once* (2026-10-19) every rail page does
  this through the same two calls: `.onRailReselect(tab, router:)` hears the second click, `AppRouter.popToRoot(reduceMotion:_:)`
  applies the page's own root (instant for ⌘N, on the columns' curve for a click). Home clears the field (back to Find)
  and scrolls to its headline; Graph closes find, the legend, the Reader and the card; Clusters returns to All's cards
  with nothing open and find closed; Skills to Installed with nothing selected; Sleep leaves the watch run, closes the
  item, the Reader and find, lets its state choose the tab again and scrolls to the room; Inbox ends a review and
  returns to All with nothing open — unless a field holds a half-typed answer (`InboxViewModel.drafts`, reported by
  Other…, a free answer, a name and the review's field), when only the Reader closes; Projects as below; Looks closes the open look and clears its search
  (`SayItOnceTests`).
- Kept from v2: the eyebrow ("Sources · n connected", "Sources · 2 of 9 · Saved by you"), "Add a source" and *Explore
  saved sites* in the eyebrow row, the contributor and conversation columns, the Reader as the third column, and every
  number through `UsageFormat.count`. Tests: `SourcesV3Tests`, `SourcesListTests`; screenshots render offscreen from a
  demo-bank dump in `SourcesV3RenderTests` (skipped without `SOURCES_V3_RENDER_DIR`).

**Sources page — v4 (owner 2026-10-19, on v3 against his real bank; DESIGN_RULES §9).** *"Remove the graph and just put
what the source is. Avoid repetition."* — *"just have a 'Consolidate now' button at the top, with how many things are
pending from that category, as a small notification."*
- **One header per source** (`SourceDetailHead`): the bare mark, the name, what the source is in one line
  (`SourceBlurb`, now with Messages, Apple Calendar and "Other agents"), then one state line with only what the row
  beside it can't say — when it last synced, the whole error in `warning`, or "Syncing now" with its × — never the
  row's own "Watching" / "Syncs when you ask" (`SourceDetailText.state`; no line at all when there is nothing), with
  Sync now / Poll now inline, and **"Consolidate now · N waiting"** as a compact `NeutralButton` only while
  `waiting > 0` (or a read runs); when other sources wait too it says "N here, M in all" (a read takes everything).
  The run state follows the Store's status and re-reads Sleep's status when it moves, so the button is never enabled
  during a run. The eyebrow stays the page's ("Sources · n connected") whatever is open — v3's position and group
  repeated the selected row and its group label beside it. `waiting` is the backend's per-source count on every
  `/sources/overview` row (`history_index.waits_for_model`, Sleep's own rule), so the app no longer derives it from the
  Sleep queue. Gone: v3's 30-day card and sparkline, the queue strip and its "Consolidated so far" line, the sync card that
  named the source a third time (`SourceHeaderCard`, `SourceQueueStrip` deleted), and an empty "By folder" heading
  (`SourceItemsGrouping.showsFolders`). The Full Disk Access fix stays under the state line where the read failed.
- **Faces on the root rows** (wide style only): up to three, newest first, then a "+N" ring (`SourceFaces`,
  `SourceFaceStack`) — the chats that fed Messages (each the photo the chat shares, `GET /sources/messages/chats/{id}/
  photo`, else a ring with a letter) and the sites a saved source's things came from (their own icon by the saved page,
  `SiteIcon(savedItem:)`). Served as `faces`/`facesMore` on the overview row; the overview's ETag folds `photos` in and
  `VersionVector` routes `photos` to `.sourcesOverview` too; a saved source's faces come from the set its list lists
  (a bookmark that left the browser is none), and a row whose count is zero has none. Pictures load through
  `SourcePictureStore` (in memory, misses kept, per bank, at most four asks at a time). Bundled marks draw on the first
  frame (`LogoImage.bundledImageNow`), never the generic "app" placeholder.
- **Rows say each thing once.** A list row's title drops a trailing " · <its own day>" (`channel_items._without_day`).
  Messages lists one row per chat — its face, who it is with, its newest day and "N sittings" — opening in place to
  its sittings by day and message count, each opening in the Reader (`ChatSittingsRow`, `GET /sources/messages/chats/
  {id}/sittings`, `ChannelItemsCache.refreshSittings`); the list follows the overview too, so a chat photo reaches it. A conversation row inside its
  harness's list shows neither the harness badge nor "1 episode" (`ConversationRow.inSourceList`). The conversations'
  find moved out from under the header into the list's own header, behind its magnifier and ⌘F (DR-46; kept, not
  dropped, because the list holds the newest 200 and find is how an older one is reached by title, and where the
  palette's hand-off lands).
- **YouTube history by day** (`WatchedDayRow`, sharing `InPlaceDisclosureRow` with chats): one row per watched day — the day said once ("Today", a weekday, "Oct
  3") and "12 videos" — opening in place to that day's videos (read then, `ChannelItemsCache.refreshDay` over
  `GET /sources/watch-history/days/{episode}`, emptied on a bank switch): the still, the title, the channel and when it
  was watched on this Mac's clock, laid out lazily so a still is asked only as its row comes on screen; a click opens the saved item in Sleep › Saved when the person also saved it, else
  the provider's own watch page in the browser (`WatchedVideoRoute`, `LinkOpen`'s target). Month summaries are not
  listed. Stills: `storage.md`, "A watched or saved YouTube video's still".
- **Sleep is not a source.** The owner's `origin:sleep` row ("1 capture", empty) was the citation episode a web check
  Sleep settled writes (`web_settle`, `source: web-check`, `origin: sleep`); its home is Inbox › "Settled by a check".
  Check records (`web-check`, `source-check`) are left out of every row (`source_overview.CHECK_RECORD_SOURCES`), so
  an agent's check no longer makes an "Other agents" conversation either. **"Other agents"** (`harness:unknown`) stays
  for real conversations an agent saved without naming its app, with its own sentence, never folded into an app it may
  not be. Tests: `SourcesV4Tests`; screenshots render offscreen in `SourcesV4RenderTests` (skipped without
  `SOURCES_V4_RENDER_DIR`).

**Explore saved sites (G166 slice 1, owner 2026-10-14).** A neutral **Explore saved sites** button beside "Add a source"
in the Sources eyebrow (hidden when the backend answers 404) opens `ExploreSheet`: sites not explored yet or every saved
site, with counts, a checkbox per browser when there are several, the run's size (Light / Medium / Heavy and minutes with
four agents, never a price — ruling 12), whether the agent will use the signed-in session, and what is left out. The
Explore button is disabled with a `.help` saying why (reading off, no site, the demo, an unverified capture script;
DR-41). After the click the sheet shows the hand-off prompt with **Copy for an agent** (`AppPasteboard`). While a run
exists, `ExploreRunCard` sits atop the grid: one line ("Exploring 212 of 534 · 4 agents working · 3 need your sign-in ·
2 gone · about 40 min left"), "Started by <agent> at your request" for an agent's start (D5), **Copy for an agent** (to
add a worker) and **Stop** (one tap). `ExploreCache` (owned by `CicadaApp`, in memory, never a Store domain) reads
`GET /explore/state` and `/explore/candidates` by ETag, revalidates when `exploreQueue`, `captures`, `sources`, `reading`
or `bank` moves (`ExploreRefresh`), and is emptied on a bank switch. Per-row chips and the capture gallery are the
link-render branch's (it reads `GET /explore/captures/{entity_id}`, `storage.md`). Settings → Reading the web gains
**Explore in your signed-in browser** (on by default, D2 amended; `ReadingAgentModel.setExploreSignedIn`, row
`readingExploreSignedIn`) and the first-use sheet's exploring paragraph (ack v3, D3). Copy: `Theme/Copy+Explore.swift`.
Tests: `ExploreTests`.

**Your YouTube lists (G71, owner 2026-10-16).** Settings → Reading the web shows, while agent reading is on, a group of
two switches — *Keep Watch later current* and *Keep watch history current* (off by default; `ReadingAgentModel.
setYouTubeList`, one `PUT /reading/settings` `youtubeLists` patch, rows `readingYouTube` and `reading:youtube:<list>`) —
each with one line from `YouTubeListWords`: off, "Waiting for your agent", "Last read by your agent · <day>", or "Your
agent wasn't signed in to YouTube. Paused until <day> — turn it on again to try sooner" (turning it on again is Try
again). Nothing in the app reads YouTube; the person's own agent does (`mcp.md`, "YouTube lists"). Tests:
`YouTubeListSettingsTests`.

**Source rows and last sync (round 4).** Every source that keeps up renders one `SourceRow`
(`Views/Common/SourceRow.swift`) from a pure `SourceRowModel`: the bare mark, name and what it reads, what came in
(`SourceRowText.countLine`: the count in the reader's locale and the channel's `parts`), and on the right 'Syncing now'
with an × or 'Last synced 2 minutes ago' (the persisted `lastSync`, re-read every 30 s; an import says 'Imported …').
× cancels the run only (R-SR11). The browser, tab-group and Contacts rows in Integrations (Sources' detail column says the same in its header's state line since v4), and
Home's Getting started rows use it. `BrowserWatcher`, `TabGroupWatcher` and `ContactsReader` report their runs into
`SyncActivity`; `LocalSourceWatcher` and `CalendarReader` keep their own lights (R-SR17).

**What came in, by name (G161).** Under a source row, a "What came in" disclosure (collapsed, remembered per viewer
per channel, `cicada.sources.capturedOpen.<channel>`) lists the items that source brought in by their own title and
day, newest first, twenty at a time with "Show more" (`CapturedItemsList`): under onboarding's Import rows (a preview —
the rows open nothing there), under every Integrations row, and as the Sources detail column's content for a source
whose items are not saved links (a saved source's column is the same list in its `.saved` style, above).
`GET /sources/channels/{id}/items?offset&limit` (≤ 200; `api/services/channel_items.py`)
derives it at read from the same set the row's count means — the notes index, the calendar and tab-group episodes (never
a tombstoned one), the bookmark seen-set joined to the url index, a channel's media pages, a folder's files — engine-free
and read-only; titles only (scrubbed, one line), never a body, and for Contacts the matched page's name only; a saved link's row adds `host` (its bare host, never the URL), `site` (the key its mark is asked under, `reading_hosts.site_of`) and `why` (the newest *Ask why* answer: reason labels and the person's words, one line ≤ 160 characters), read only for the page served. A channel-less saved import (Instagram, YouTube, LinkedIn, TikTok) is listed by its Sources row id. Its
`total` is its own count, not a promise to equal the row's (a notes index keeps a deleted note). It ETags over
`sources`+`episodes`+`entities` with the channel and page in `extra`, and is **not** a Store domain: `ChannelItemsCache`
keeps it in memory, revalidates when the list opens or the channels move, and empties on a bank switch. A row opens its
episode in the Reader, a saved item in Sleep › Saved, a person in Clusters.

**Clusters and Sleep's saved lists (Direction D, DS-3c; the Feed folded into Sleep 2026-10-16).** Clusters is a list
page in progressive columns, and the Feed's list lives on as the Sleep page's Saved and Videos tabs (below, and the
Sleep page): an eyebrow row with
text tabs (`AdaptiveTextTabs`: with counts, then without, then a menu, so a tab is never clipped; the Inbox's kinds use
`OverflowTextTabs` instead, below), the list, a
detail column, and the Reader as the third column (each list page hosts its own: `AppTab.hostsOwnReader`).
`ListColumns<ID>` holds the open row: a row that leaves the data, or that the chosen tab does not show, closes the
detail; one that find (or Clusters' View menu) hides stays open. Keys follow DR-68: ↑/↓ swap in place, ⏎ steps in, Esc closes the rightmost column, and ⌘F opens
the page's find row. **Say it once (owner 2026-10-19):** the eyebrow is the page's name ("Clusters", "Inbox", "Sleep")
plus find's match count, never a count or a position the tabs, the selected row or the card already say; Clusters'
type cards and list headers drop the count their type's tab carries (a find's per-type count stays); an Inbox row,
⌘K row or card header leaves out the page's name when the question already names it (`InboxRowWords`: the whole
name on word boundaries, literal characters, diacritic-insensitive and case-insensitive after the first letter, never
the start or end of a longer name — "Claude" is not named by "Claude Code"; in doubt the name shows).
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
- **Saved (the Feed until 2026-10-16)** keeps the Feed's sort (Relevance · Recent, one always on) and kinds
  (`FeedKind`: paper, video, bookmark, link), now in one View menu on the tab row (`SavedViewMenu`), never a second tab
  row (DR-38). Its rows are 56 pt, each with the origin's real mark (`FeedRowsContent`). With nothing open they scroll
  with the room under the sticky tab row; beside an open item they are `FeedListColumn`'s triage column and the tab
  row rides the eyebrow ("Sleep" — the tab row beside it names the list and its count, the View menu the kind; "Sleep ·
3 matches" while find narrows it). The Feed's Connected strip retired (Sources' cards sync each
  connected source); its export waits (`ExportWaitStrip`, R-IB22) head the Saved list, as they headed the Feed's, since
  Home's Getting started shows them only until it graduates and the menu bar's line cannot be stopped or dropped on.
- **A saved item's detail column** shows `MediaPreview` (a video plays at the column's width), "Why it's saved"
  (the page's own words, then the pages it is about, known ids only), and "Saved from" (the origin's mark, name,
  folder and day, or `[ no source recorded ]`). The palette's saved-item row, ⌘B's bookmark rows and a source page's
  items land there through `AppRouter.routeToSavedItem` / `routeToBookmark` (Sleep, the Saved tab, the item open), and
  the preview sheet is gone. The one-shot import's `+` (with ⌘N) is an icon on the tab row (`SleepTabRow`) and opens the
  unchanged `AddSourceSheet`, whose root hosts the one `IntakePanel`; Settings → Integrations' "Import in Sleep →"
  stages a tile there (`AppRouter.routeToAddSource`). **Include watch history (G71, 2026-10-16):** a drop whose sniff
  reports history (`historyExcluded`, or `historyVideos`/`historyDays` once asked) shows the switch in the preview
  (`IntakeRouter.includeHistory`, off for every new drop); flipping it sniffs again with `?include_history=true`, the
  line under it says "N watched videos left out" or "N watched videos over D days", the import counts them and
  `/sources/upload` carries the flag. The YouTube and TikTok tiles carry the same switch, and a walked Takeout folder
  now sends `watch-history.html`. **LinkedIn → Connections (2026-10-16):** the LinkedIn tile (blurb "Saved items, and
  your connections for the people you already know."; route lines *Saved items export · Connections*) carries, under
  its saved-items walkthrough, `LinkedInConnectionsPanel` (`AddSourceTile.offersConnections`): one sentence —
  "Adds each connection's profile link, company and role to the people already in your memory — it never adds anyone
  new." —, where the export lives, and *Choose Connections.csv…* (or a drop of the CSV or the export `.zip`; the
  intake's refused roots apply). From a `.zip` the app reads only `Connections.csv` — the archive's tail, its central
  directory and that one member (`LinkedInConnectionsFile`; the export also holds messages and is often past the
  32 MB cap), never another member's bytes; a zip without it says so in words. The app posts just those bytes to
  `POST /sources/linkedin-connections/preview` (with a lone CSV's modification day, or the member's own date, as
  `?exported_on=`) and shows counts only — "12 of your 420 connections are people Cicada
  already knows. 2 share a name with more than one person and are left out. As of <day>." — then *Add to 12 people*
  (or *Keep for later* when none match: the backend keeps the directory for later matches) posts `/import` and
  refreshes the graph. Words in `LinkedInConnectionsWords`, tested in `LinkedInConnectionsTests`. Settings → Skills
  lists Cicada's third own skill, *What people do now* (`CicadaSkillBundle.linkedinPeople`, `mcp.md`).
- **Videos (G162, the approved boards, 2026-09-30).** The app reads `GET /videos/state` and `/videos/summary` through
  `VideoStateCache` (app-level, in memory, ETag-revalidated, never a Store domain; `VideoRefresh` follows the
  `videoQueue`, `episodes`, `entities` and `bank` components, one revalidation is scheduled at the wire's
  `nextChangeAt` so a lapsed lease never sticks as "Picked up", a bank switch empties it, and a 404 from an older
  backend hides every video addition). **The server is the only deriver** of a video's state; the app decodes and labels.
  A saved video row carries a 64 × 36 frame (Cicada's stored preview, `MediaFeedItem.preview` through `StoredPreview` —
  oEmbed's thumbnail or YouTube's standard still, fetched once by the backend — or a neutral play tile; the app never
  asks the provider),
  "channel · site · length · saved day" and one state word (a queue word wins). The Sleep page's Videos tab (drawn only
  while a video is saved; the queue's one place since Details' Videos row retired, 2026-10-16) opens on a 44 pt strip
  that says how many are not read yet and the one queue wording, and *Choose videos…* turns the lists into the watch
  run: the picker's tabs (Not yet read · Queued · Read, disjoint, nothing pre-selected) replace the page's tabs, the list becomes
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

**Projects (G141 PJ-5, Direction D; v2 owner 2026-10-19 — dated ruling in `docs/design/DESIGN_RULES.md` §9).** The
eighth page (⌘8, after Sources): a list page in progressive columns over `GET /projects` and `GET /projects/{id}/timeline`, which are **not** Store domains —
`ProjectsCache` (app-level, in memory) revalidates them with the server's ETag when the page appears, a project opens, a
write lands, or a sync event moves `entities`/`episodes`/`inbox`/`bank`, and a bank switch empties it (no
`VersionVector` mapping, nothing on disk). Overlapping refreshes of one resource keep only the newest request's answer,
and a confirmed write's paint is cleared only by an answer requested after the confirm (`RequestGenerations`, audit
2026-10-05 P2-6; `BacklogCache` the same). The wire decodes leniently into local `Project*` types (the shared `Claim` is
untouched); derived state is `ProjectState`, the Swift twin of `project_state.timeline_state`, running the same
`api/tests/fixtures/timeline_state.json`; every relative word comes from `RelativeDay` over `ISODay` in the viewer's
calendar (a lint keeps the day words there), and midnight re-derives the page with no network. The story is derived off the main actor (`ProjectDerived`, keyed
by project, day and cache revision; the last value stays up while the next builds) and Lately is one lazy list, so a
project whose happenings cite hundreds of pages opens at once (round-4 D6). Every Swift test reads
the demo scenario's real wire, `app/CicadaApp/Tests/fixtures/projects-demo.json`, pinned by
`api/tests/test_projects_app_fixture.py`.
- **The list (v2):** text tabs **Current · Past** with counts (`ProjectsModel.tabs`; tapping the selected one keeps
  it). A project's group is `ProjectState`'s section (`ProjectsGroup`): in motion → Current; quiet → **Fading**, one
  folded disclosure at Current's foot, remembered on `cicada.projects.fadingOpen`; resting (decaying or archived, or
  nothing heard for 90 days) → Past. `ProjectsModel.entries` is the whole column as `ProjectsEntry` values — rows,
  the Fading head, Past's year labels and "Show 50 more" — pure, so a test pins it. A row (`ProjectRowView`, 56 pt)
  is the name over the one-liner and ONE signal (`ProjectsModel.standing`): the next milestone ("Next · First grasp,
  Oct 1", overdue in words; a milestone named after its own project only its day, "Next · Oct 5" —
  `ProjectsModel.milestoneName`), else the plan's count, else "Heard 9 days ago"; Fading "Quiet 30 days"; Past the
  day alone ("Mar 3", `RelativeDay.dayInYear` — the year is the label), nothing under *Nothing heard yet*. Beside an
  open project the narrow rows say where they stand and the open row only its name (`ProjectsModel.secondLine`). Sub-projects nest under a parent in the same group behind a chevron (`ProjectsModel.nest`, folded by
  default, every parent unfolded while a find runs); `ProjectsModel.tap` — a parent's click opens it and unfolds its
  parts, the open parent clicked again folds them; the chevron folds without opening. Past keeps its find field
  always, sorts newest heard first under year labels and draws 50 rows at a time (`pageSize`); a ⌘K landing on a
  hidden project opens its tab, Fading, its parents and enough of Past first (`ProjectsModel.reveal`). Find matches
  the name and one-liner (`QuickMatch`). The eyebrow is "Projects" (+ "still indexing" while the server says
  `partial`): the tabs carry the counts, `counts` computed once per render. **Keys** (`ProjectsModel.step` / `side`,
  `listKeys(side:)`, all `Instant.run`): ↑/↓ open the neighbour — past Current's last row ↓ opens Fading onto its
  first row, past Past's page ↓ draws the next; → unfolds the open parent, ← folds it or goes from a part to its
  parent. **Projects clicked again
  in the rail** (`AppRouter.reselect`, the Sources v3 mechanism) closes the Reader, card or item and project, clears
  the find and shows the default tab; ⌘8 does it without animation.
- **The summary (v2):** under the name and one-liner, `ProjectSummary` — *Where it stands* ("In motion · 1 of 4
  milestones done"), *Last* (the newest happening with `RelativeDay.phrase`) and *Next* (the next milestone with its
  day, else the newest live thread Last did not already say, else "Nothing planned" with Add a milestone), each said
  once; Last and Next select their row on the band and unfold its section. The band's old header line and the
  eyebrow's Planned / No plan yet retired with it. Folded sections say their bare count ("2", "9"); Plan says nothing
  when *Where it stands* gives the plan (`ProjectSummary.planMeta`).
- **The band** (`BandLayout`, pure, the approved mock's coordinates): `progressFill` from the first moment up to a
  "You, today" marker in `textPrimary`; done milestones filled inside the green, planned ones hollow on the track, a
  closed `due` slashed ("passed, no word on how it went"), a moved one's dashed ghost and bracket; happenings as neutral
  dots, ongoing threads as spans to today that dash once quiet; months and words near today. Every mark is a button: a
  `textPrimary` ring, its first words and date on hover, ←/→ along the band, ⏎ into the Reader. It is never called
  "Timeline" — that is the entity card's tab, which can share the screen.
- **The story:** every section starts folded and says what it holds; the viewer's opened set is remembered on
  `cicada.projects.opened`. Log progress (⏎ done, ⌘⏎ still going; the server dates it from the words, else the date chip, else
  today, and the page says which and how, with Undo = withdraw); In progress (the threads; a quiet one whose follow-up waits in
  the Inbox links to that card); What happened (Today · Yesterday · This week · Earlier — one sentence per happening, every
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
  (a 400's or 404's detail is never shown — it names ids), disabled while Sleep holds the pages; nothing relative is
  sent as a value. `ProjectWriteGate.blocked` (Projects, Backlog) reads `sleep.writing` from `/status` and the SSE `sleep` event —
  the server's own refusal predicate, so a person-started drain gives the controls back between its batches (G177) —
  and falls back to `status == "running"` when an older backend sends no `writing`. `ProjectWriteGate.sleepRunning`
  (the whole run) stays on the search-model switch, whose route refuses while any run goes, and on what stops the
  backend (the background install, Restart to update and the updater's cached check), since that ends a drain between
  batches too. L · M · D are key presses on the focused project (the Inbox's O / L precedent), never menu key equivalents.

**Looks (design taste, owner 2026-10-14).** The ninth rail page (⌘9, `paintpalette`, after Projects so no shortcut
moves; the placement is the owner's call). A board of the looks the person likes over `GET /design`, not a Store domain:
`LooksCache` (in the page, in memory) revalidates by ETag when the page appears, after a write, when an SSE version moves
`design` or `bank` (`LooksRefresh`), and is emptied on a bank switch. `LooksBoardView` is pure over its inputs (the page
feeds it the cache; the offscreen renders feed it fixtures): the eyebrow (`Looks · 5 saved`, `… · 3 matches`), a search
field (⏎ searches by words through `POST /design/search`; the board re-ranks), `+` (an image file), and, when this Mac
supports it but images aren't understood here yet, one row (DR-37) saying what it is for and its download size with
*Turn on* (`POST /embeddings/install` with `part: vision`; the page polls while it installs). This is the in-context
shortcut to Settings → Search & files → *Understand images* and keeps its one click: on a Mac without the meaning part
it fetches both, and `vision.includesText` makes the row state the combined size ("…which also sets up Understand what
you mean") before the click. Tiles: the screenshot through
`StoredPreview` (`PictureURL` accepts `/design/…` as Cicada's own API), its colours as one strip, the site and the day.
**Looks v2 (2026-10-15):** the strip gives the ground half and the colours after it equal shares in their salience
order (`LooksPaletteStrip.widths`) — by area a thin ink that *is* the look drew as a hairline. The screenshot was never
drawn before v2: `APIClient.fetchPictureBytes` accepted `/entities/…` only, answered nil for `/design/…`, and
`PictureStore` remembered the miss, so the palette placeholder stayed; the loader's gate is now `APIClient.isPicturePath`,
exactly `PictureURL.parse`'s `.api` case (`LooksImageTests` holds the two gates together and loads a screenshot end to
end). A click opens the reference beside the board: the screenshot, the link, the note — *What you liked* only when it
is the person's own words, *Noted by Claude Code* (`LooksNote`, the agent's label from `OriginIconography`) when an agent
wrote it, no section for an agent's empty note — the colours with their share, role and words (pills), *Colour roles*
(ground, ink, accent, wash; "from the page" or "from the picture"), *Type* by role (body, headings, subheadings,
captions, links, drop cap: family, then size · weight · leading; the bare font list when the server has no computed
type), the snippets (`MarkdownBody` code blocks), who saved it and how, *Remove from Looks*.
**Looks polish (2026-10-15).** *Type* shows one specimen per family (`Views/Looks/LooksSpecimens.swift`): a large
"Aa", the family's name, and where it is used ("Body 19 px · Drop cap 88 px"). The "Aa" is the page's own drawing
(`/design/{id}/type/{n}`, a transparent PNG tinted to the text colour of either appearance); a look without one sets
"Aa" in the family's generic kind (the system serif, sans or monospace) and says "Shown in a generic serif; the page's
own face wasn't drawn" — a stand-in is never taken for the page's face (DESIGN_RULES 2026-10-15, DR-15). *Colours*
shows a share only where area means something (`Copy.Looks.share(_:role:)`): the ground, a wash, an unnamed colour;
none for ink and accent (thin lines read "0 %"); "< 1 %" for a sliver. **The enlarged screenshot**
(`Views/Looks/LooksZoom.swift`): a click on a tile's picture (which also opens the look beside the board) or on the
detail's picture grows it over a scrim from that thumbnail's frame to fit the board (`CicadaMotion.morph`), at full
resolution; a tall full-page shot fits the width and scrolls. Esc, a click outside or × shrinks it back into the
picture that is there now (`LooksFrameBook`: the detail's picture when the look is open). The keyboard path — ⌘Y on
the open look, Space on a focused picture, Esc — opens and closes in one frame (`LooksZoom.style`, read from the
current event; DR-60); Reduce Motion only fades (`CicadaMotion.fade`, DR-66). While it shows, Esc is the overlay's,
not the detail column's. Tested in `LooksPolishTests`; the review renders add `looks-enlarged-*.png`.
**Save its look** (`Views/Looks/SaveLookAction.swift`): a neutral compact button in a saved web link's detail (Sleep › Saved)
(`SaveLook.offers`: a link or bookmark over http(s), not a video or a paper) and a context-menu item on a ⌘B bookmark
row. One click posts `POST /explore/look`; the answer's hand-off prompt is copied through `AppPasteboard` and a toast
says it is queued for the person's agent (the "Ask an agent" pattern); a refusal shows the server's sentence. A picture dropped anywhere on the page or pasted (⌘V, `onPasteCommand` — never `NSPasteboard.general`) is
shrunk by `DesignImageShrink` (≤ 2560 px; PNG ≤ 1.5 MB else JPEG) and opens `LooksComposer`: link, name, note,
*Find similar* (a picture search) or *Save to Looks* (the one primary action). The app reads the file or the image and
posts bytes; every colour, token and ranking is the server's. Copy is `Theme/Copy+Looks.swift`, provider-neutral.
Renders: `LooksTests.testRenderTheBoardForReview` with `LOOKS_RENDER_DIR`; a hosting-view capture cannot draw Liquid
Glass, so the composer's action row (`LooksComposerActions`, Save the one primary) is also rendered with `ImageRenderer`.

**Sleep page — the study room (G125 v4, Track Z; the Sleep redesign, 2026-10-16).** The room and the worm are Aseprite
sprite sheets; to watch every animation, open `app/CicadaApp/Art/sprites/bookworm-2026-10-01/preview.html` in a browser
(*The sprite art and its preview*, below). **A room-over-list page (DESIGN_RULES §5.2, owner approval 2026-10-16):** one
scroll — no title (the "Sleep Cycle" `PageTitle` retired; the page opens on an eyebrow, "Sleep · last read
2 h ago", `SleepEyebrow` — what waits is the room's headline ("23 to read.") and the Waiting tab's count, so the eyebrow
no longer counts it a third time (say it once, 2026-10-19; the pinned tab keeps the total once the room scrolls away) — with the staleness chip at its right, R-A12); then the room **out of its card**, on the page
ground, drawn at a whole 5, 4 or 3 pt per lattice cell by the width the art may take (`SleepLayout.artScale`: 5 from
880, 4 from 720, else 3 — 2 only under ⌘+ zoom with the Reader open; `StudyRoom(cell:)`), its floor fading into the
page over its bottom five cells (`RoomFloorFade`, a mask on the art layer only, never the pile). **The painted room is
the lattice (2026-10-16):** the backdrop's wall, floor and trim span all 160 columns, so the pile stands on the room's
floor in its own columns and the worm, props, pile and every hotspot sit inside `DeskSceneLayout.paintedFrame` at every
step (`SleepRoomFrameTests`; the backdrop was 110 columns, which the old card hid). **The pile is books (owner pick
"A · Stack", 2026-10-16):** one pixel-art book per waiting source, lying flat, the fattest at the bottom, drawn from the
`room-books` sheet at the room's own cell size and in its lighting (the night frame in a dark room) — `PileBooks.stack`,
pure: thickness by count in four steps (1 · 2–9 · 10–49 · 50+ → 7/9/11/13 rows), a colour per source kind from existing
palette keys (`bookKind`: agent chats the worm's book blue, conversations with people — Messages, Telegram — leaf
green, pages ochre, notes plum, videos red, the rest and the "+N" steel), a width per kind, each book right-aligned
against the corner post and nudged 0–3 cells; past 40 rows a second, narrower stack stands to its left, and what neither
holds folds into one "+N" book (`bookPileLayout` already folds past seven sources). Every book is whole cells inside the
column and the painted room at 5/4/3/2 pt (`PileStackTests`). `BookArt` joins the sheet's leading cap, its one middle
column repeated and its trailing cap to any whole width, so a book is the drawing as authored, never a resample. The
count (and the source's mark, when it fits) sits on a plate of the page ground in whole cells inside the book's outline
(`PileBooks.plate`); a book too thin for a 15 pt plate at the current scale carries none, and its count lives in the
tooltip, the popover and the Waiting tab. A book is opaque art, so nothing behind it shows through (DR-13,
`SleepPileGroundTests`); hover lifts it one whole cell. Under it, in the 760 pt
text column, one sentence in the display face, one Consolidate/Cancel control with the engine menu
snug beside it (`HugWidth`: the button is its own width up to its 300 pt cap, never the cap) — a neutral button naming what a cycle you start would run (`preview.manual`, "Auto ·"
under Auto) that opens the five engines with their real marks, the chosen engine's model and both
ruling-4 previews; the "Runs on …" caption retired into it, and Cancel's caption shows while running
— and one whisper line for the schedule. Under the room, **the tab row** (`SleepTabRow`, DR-45 text tabs with counts):
**Waiting · Saved · Videos · Past reads**, a `LazyVStack` pinned header so it sticks under the titlebar once the room
scrolls away; a count of zero hides its tab (`SleepTab.visible`), the page opens on Waiting while anything waits and on
Past reads otherwise (`SleepTab.resolve`), and a tab switch is instant and closes whatever was open. **Waiting**
(`SleepWaitingList`, Details' What's waiting until 2026-10-16) is the run's own block and the queued rows — fetched as
`GET /sleep/episodes?processed=false` (the waiting episodes only, never the read ones: every episode was 8,237 rows and
4.5 MB per load on a large bank, 2026-10-19) and revalidated with its ETag, the rows and tag held in `SleepViewModel`
(not a Store domain; a 304 keeps them, a bank switch drops both); **Saved** and
**Videos** are the Feed's lists (above, *Clusters and Sleep's saved lists*); **Past reads** (`SleepPastReads`) is Last
cycle · Readout · Past nights in D's list grammar — section labels over rows, no cards; Last cycle's rows in words,
"Rested" as a sentence, the readout as key–value rows, a past read opening in place under its row with its Models, tokens
and cost (ruling 12). Said once (2026-10-19): a Past nights row prints its day only when it is the first of that day;
when no row — a run's batches included — recorded usage or a time the section's label says so once ("Past nights ·
usage and time not recorded", `PastNightsLayout`) instead of every row; a run's row names its engine in words beside
its mark; the readout's *Last engine* row steps aside while the newest Past nights row
names the same engine and the backend gave no reason to add. A tail link, a spine or a Home hand-off names an old Details section (`DetailsSection`), and the
page selects the tab holding it (`SleepTab.holding`) and brings the tab row to the top in one frame. Opening a saved item
(or the watch run) turns the page into progressive columns: the tab row rides the eyebrow, the list is the triage
column, the item the detail, the Reader the third column (`AppTab.hostsOwnReader`); Esc closes the rightmost.
Each queued episode row (`EpisodeRow`, Waiting and Past reads' lists and the spine popover) is one button: a click opens the stored episode in the Reader (`ReaderTarget(episode:)`, `GET /episodes/{id}/text`, from the top; `EpisodeRowAction.primary`, owner 2026-10-19 — "episode ID copied" gave the person nothing to do). Copying what Sleep would read — `GET /sleep/episodes`'s `copyValue` from `episode_copy` (a page's link, a conversation's session id, a tab group's links, a folder file's full path, else the episode id) — is the row's context menu and a named VoiceOver action ("Copy Link", "Copy Conversation ID"), with its brief toast (`Store.flash`). The meta line names only a target a person can read (a site and path, "3 tab links", a file's name) and "read"; a session id and the raw `ep_` id left it for `.help` ("… · Episode ep_…", DR-54). It ends with its day (`changedAt`: a conversation's last capture, else when it arrived; owner 2026-10-05). DR-48, DR-54, DR-69. The worm speaks in that one fixed slot —
`roomSentence` / `wormAnswers`, pure
`SentenceLine` values over `SleepPageModel` (lead ≤ 40, tail ≤ 80, clock-free; a missing fact
omits its rung, never shows a guess); the floating bubble is retired. The slot reserves nothing (R-Z5 as amended
2026-10-16 and 2026-10-17, `SentenceSlot.drawsTail`): a line with no tail is the lead alone, with no empty line under the
headline; a tail takes one line at 17 pt, else one line at 15 pt (17/15 since 2026-10-16, it was 22/20 in the display
face), and only a tail too long for that wraps to a second. A poke's answer with a tail steps the control row down by
that line as it appears, and back once its cross-fade ends — never a slide (DR-60: a key can poke the worm). **Two kinds of art (R-Z1, amended by ruling 18):**
*state art* — the owner's worm on a 160 × 64 lattice (5/4/3 pt per cell by the column's width since 2026-10-16), the real pile, the lamp (= the schedule)
and its pixel-size fly, the bean bag, mood-edge yawn/stretch and the Sleep moment overlays — and *response art* (gaze,
perk, talk, cheer), transient and never contradicting state. **Environment art (2026-10-02)** is the time, base weather
and room lighting, independent of the worm. The sheet player loads once, caches failures, uses per-frame boundary
schedules, shows key frames under Reduce Motion, plays every frame at half speed under Low Power and rests unseen.
**Moving frames are swapped on a layer, never through a `TimelineView` (2026-10-05).** `SpriteLayerPlayer` (an
`NSViewRepresentable`) arms one timer per boundary of `SpriteFrameSchedule` and sets its layer's `contents` to the
frame the caller's closure picks — `SpriteLayerView` for room props, `BookwormView` for the worm everywhere. Measured on
macOS 26: a `TimelineView` whose entries fall under ~0.3 s apart makes SwiftUI lay the whole window out at the display
rate (240 host layouts a second for 4 ticks a second), which is what held the Sleep page at ~12% of a core; a 1 s
timeline still costs one whole-window render a second, so the wall clock's second hand is a layer too. Still frames, Reduce Motion, a paused host, an unseen window
and `ImageRenderer` snapshots keep the plain SwiftUI image (a snapshot cannot draw a platform view), and mounting that
image tears the player and its timer down. `SpriteLayerPlayerTests` pins one draw per boundary and bans
`TimelineView(SpriteFrameSchedule` from the sources.
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
`displayTracking`) over one SF regular tail at 17 pt, never italic (F1 R-FX13; off the display face and out of italic since 2026-10-16), Consolidate is the page's one `PrimaryActionButton`, `SleepMotion` forwards its shared names
to `CicadaMotion`, and the sky band above the page is OFF (`SkyBand.ships`, TODO ruling 10). The
pile fits its column at every scale and queue size — two stacks before a fold, the order and every count kept,
never cut (`PileBooks.stack`).
**The room's column, one centred group (2026-10-16).** Owner, live during a run: *"those stages of reading and stuff
are kind of ugly … center it"*. Everything under the room is `SleepRoomColumn` (out of `SleepView.roomBlock`) in the
760 pt column (DR-36), every row centred on one axis: the sentence (lead + one 17 pt line), the control group
(`SleepControlRow` — its whisper on its own line under the buttons, never beside them), the notes, the schedule line,
then `RunInstrument`: the stage stepper and the progress bar at the column's full width, the counts centred under the
bar ("Batch 4 of 12 · 74 filed · … · 222 calls made"). The stepper (`SleepStageStrip`, `StepLook`) replaced the five
56 pt pixel-icon tiles: per stage a 14 pt marker and its word, joined by connectors that stretch — done is a check in a
`bgBadge` disc with the word in `textSecondary`, current an accent ring (the focus-ring use, DR-5) holding a live dot
with the word in `textPrimary` medium, to come an empty ring in `textTertiary`, failed a `danger` cross (VoiceOver says
"failed"). Only a counted stage's fraction fills the connector leaving it (P15). The live dot breathes on its own Core
Animation layer (`LiveDot`, `SleepMotion.liveBreathHalfPeriod`), held lit under Reduce Motion and in snapshots — the old
strip's 0.1 s `TimelineView` is gone. Each thing is said once: while the last stage files, "Filing…" is the lead, the
stage's purpose the tail, and what a stop does now (`Copy.SleepV5.filingWhisper` — honoured after the batch commits, so
the control stays enabled) the whisper and the Pause/Cancel tooltip. The control row reads the page's own drain (H1).
`SleepRunStripTests` lays the real column out offscreen and checks every row's ink is centred and only the stepper and
the bar span the column; `CICADA_RUN_STRIP_SNAPSHOTS=<dir>` writes every run state, dark and light, at 1440 and 1079 pt.
Refused: motion with no state behind it (mug steam, plant sway), a flash or strobe in any weather, a count driving the window (time of day follows the clock or the person's choice, R-Z11 as amended 2026-10-02), duration estimates, and any price or plan figure outside Past reads and the engine menu (TODO ruling 12). State art loops (ruling 18).

**Consolidate reads everything — the app half (G163, ruling 13).** No new door: every trigger already POSTs with no body, and
the server drains. `SleepStatusResponse.drain` (`SleepDrainInfo`, lenient like every field) and the SSE event's compact
`SleepDrainSSE` are merged by one pure `resolveDrain(sse:status:)`: the status holds the whole block, the event overlays the
moving counts only when it describes the same run (same frozen total), and neither is ever a hybrid of two runs. While it
reads, the legend under the progress bar leads with "Batch 3 of 12" (measured counts through `UsageFormat.count`, G107, and only
with more than one batch; until 2026-10-16 the tail said "Batch 3 of 12 · 62 of 287 filed.", a second saying of the legend's
filed count, and the tail now says what the stage does); the lead, the strip's Read fill and the study list already read the cumulative origin dicts. A plan
stop is a *pause*, not a failure: the tail is the vendor's own sentence (reset time inside it), the strip freezes where it
stopped and the worm neither chews nor cheers (`SleepPageModel.stoppedEarly` feeds `stageStripState`, `stageStripIsVisible`,
`deriveSleepPageMood` and `isRealCompletion(drainStop:)`). **Cancel keeps its name** and its semantics (stop at the next safe
point, drop a batch that has not begun filing), so its caption and tooltip say what is kept and what is not
(`Copy.cancelDrainCaption`), never "after this batch" and never "nothing is lost". Past reads › Last cycle gains a "Read everything"
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
between pane and window in `DeskScene.plan`/`room-plan.json`. The backdrop is 160 × 64 (2026-10-16: `lua/widen_room_parts.lua` carried
the saved wall, floor and trim across the pile's columns once; `verify_night` still pins the authored 0–107 and the corner
post against the day contract). In darkness the backdrop/lamp and the window/plant/beanbag/
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
`RoomClock` is a separate inert leaf, with a `TimelineView(.everyMinute)` for the hour and minute hands and its words,
and the second hand on a `SpriteLayerPlayer` that wakes every whole second (`RoomClockReading.secondTrack`,
`CicadaMotion.roomClockTick`), only while its window/room is visible and its host is active; a per-second timeline
re-rendered the whole window each second (2026-10-05). It never redraws the parent room. `room-clock` has
`face`, `hour`, `minute`, `second` and each `-night` variant. Night-or-rain lighting selects the dark dial/hands;
black hour/minute hands and the thin red second hand use transparent state frames, not timed sprite loops.
Normal ticks start on whole seconds; Reduce Motion removes the second hand and ticks on minute boundaries while hour/minute keep time. Help and VoiceOver share “Wall clock, <time>”
in the system's short format, after the window and before the lamp; it is not a button. The 15 × 15 clock at
`(94,34)`, z1, follows the verified art plan and clears every worm frame/beat/transition, the window, lamp and pile column; art acceptance
also checks every new night frame. The preview includes the same clock leaf. Motion sidecars exclude its state angles.

**Settings → Sleep → Scheduled runs (TODO ruling 4b, owner 2026-10-16).** One switch, *Scheduled runs may use my
plan* (`SettingsRowID.sleepUsePlan`, in the find index), **on unless the person turned it off** (ruling 4c, 2026-10-19;
an older server that sends no value reads as off): the machine's `scheduledUsePlan` on
`/sleep/run-options` (`SleepRunOptionsChange.scheduledUsePlan`). Its detail says what it costs while on
(runs on their own count against the plan's limits; a limit pauses one and the next picks up after the reset) and,
off, that a run on its own never reads with the plan — only with an API key the person chose or a local model. Writing it reloads the schedule (its warning) and
the engine previews (the scheduled line). While the schedule runs on its own and the server says a scheduled run would
have no engine it may use (`ScheduleConfig.warning`/`warningCode`, decoded only, never sent back), the Runs card shows
that sentence with the app's own fix, connecting a plan first (`Copy.ServerPlan`, provider-neutral). The engine menu's
and the chooser's caption and `Copy.sleepEngineExplainer` say a scheduled cycle uses a plan only when allowed here.

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
leave room in your plan / Your plan window is full / The engine stopped answering / Cicada restarted while reading — with what is filed and, when armed
(ruling 15), "Continues after 3:40 PM" (one locale-aware formatter, `sleepClockWords`); the mood is `.reading`, never an error or a cheer.
An engine pause's `engineKind` (`transient | needs_fix`) travels in status and the compact SSE block. Transient
timeouts/errors say "The engine stopped answering" and "Continue to try again" with the filed count. Sign-out and
model-not-found pauses retain "The engine needs a look" and "Continue when it is fixed"; older backends without the
kind retain that fix guidance. Past reads shows the backend's diagnosis (DR-59), including the sign-in/model fix or a
trimmed transient failure detail. For a timeout, the diagnosis says the interrupted part is read again. The existing
`sleep` version component includes kind and diagnosis and maps to `.status` in `VersionVector`; a changed SSE kind
refetches the paused record. An engine pause never implies automatic continuation.
An engine connection loss uses the transient pause/Continue machinery. Neither an engine pause nor a genuine
failure renders an exception class, CLI command or raw diagnosis in the page's sentence or worm answers. A failure
instead says "Reading stopped" / "See what needs a fix in Past reads, then try again", in warning tone (DR-7, DR-59);
the existing Last cycle rows retain the full diagnosis (DR-37/48). **One
primary at a time (DR-40):** Consolidate / Pause (a drain's cancel, "Pausing…") / Continue (named for the manual engine; held while a weekly limit's
reset is ahead) with *End this run* beside it. `SleepViewModel.continueRun()` is the only sender of `{"continue": true}`; **every other door goes
through `triggerManually()`, which routes to the Sleep page while a run is paused** (`AppRouter.routeToSleep`), and the menu bar, the intake card's
and Home's *Read now* say what the click reads — "Consolidate now — all 287", "Reads all 318 waiting, oldest first, saving every 25." (`SleepDoor`,
readable = waiting minus parked, M7; a pause whose record has not loaded says only "Paused", and an unknown batch size is left out, never a
fallback — `Store.onSleepPausedChanged` refetches the record app-wide, not only on the Sleep page). While a drain reads: "Reading 14 of 25." / "Sorting 31 of 86." / "Deciding 4 of 12." / "Filing…" (a stage
fills only from finished work over a fixed total; Notice and File never), under the stepper only a batch failure in words
(`batchFailureNote`; the stage caption that repeated the lead retired 2026-10-16), `RunProgressBar` (batch position · filed ·
read, waiting to file · waiting · could not be read, and calls made; one accessibility value; elapsed "Running 27 m", never a remaining time),
and the first save's "Your page has 31 beliefs so far" with *See your page ›*.
**At rest (owner 2026-10-16): one headline, one row of controls, one schedule sentence.** The lead says "23 to read —
overdue." in its own colour (the `warning` tone left the lead; DR-7); the tail is news only — T11 ("The lamp is off — I
read when you ask.") and T12 ("The <source> pile is the big one.") retired, the first because the schedule line under
the controls now says it (`whisperLine` → `Copy.lampOffSentence` with the lamp off), the second because the room draws
the pile. The control row is Consolidate · the engine menu · *Options…*, all at Consolidate's 28 pt (`NeutralButton`
`.compact`; `SleepAtRestTests`); *Options…* replaced the "Reading options…" link that floated on its own line. Waiting
and Saved hide at a count of zero (`SleepTab.visible(waitingHasRows:saved:exportWaiting:videos:)`; Waiting stays for a
parked conversation, a run's block or an unreadable queue, never for the "your own page" note alone; Saved stays while
an export is being waited on, because `ExportWaitStrip` heads it, R-IB22), so a fresh page opens on Past reads. *Options…* (`ReadingOptionsSheet`, 720 pt) sets batch size
10/25/50 and *Continue by itself when my plan resets* (off) on change; it has no Read faster row, no engine advice and no site list. The engine
menu's *Keep plan free* (Off or 5–30 % of the window, plan engines only, a line not a guarantee, an unreported window said so) is one of ruling
12's two homes; the page's lists are the other (Past reads and Waiting, Details until 2026-10-16): Last cycle's run rows (`LastCycleRow.runRows`, merged over the pre-v5 drain rows), per-source counts and
per-conversation rows from `GET /sleep/queue` (refetched when the run's counts move, never per tick) with Retry for a parked one — offered only while no run reads or waits paused, since the
server refuses it then (`LastCycleRow.canRetryParked`) — a scheduled run's spend note billed from the run's own usage, never today's preview, and Past nights
folded by run (`PastNightItem.group`, the run's numbers from the server's `run`, never summed from visible rows; opened: models, cost, pages,
batches and pauses from `GET /sleep/runs/{id}`, cached in the view model and refetched when the run's counts, pause or end move; touched pages
by name, the id in `.help`). A scheduled run that caught up a time the Mac slept or was off through (`sleep_catch_up`,
`features.md`) carries `catchUpFor` on its `run` and its row says so in words — "Missed 3:00 AM — caught up at 8:12 AM",
"tried" for a failed one, the missed day added when it is not the run's (`RunPresentation.catchUp`, owner 2026-10-19). The app-level `SleepViewModel` empties its queue, waiting rows (and their ETag), run details and history details on a bank switch
(`Store.onBankChanged`). `PriceLintTests` keeps `$` and token literals out of every other Sleep
file.
A refused bank switch shows the server's own 409 sentence (`BankSwitchFailure`), from every door: the switcher, the demo's enter and leave (`DemoMode.leaveToast`) and an active bank's rename.
**A write is bound to the bank it started in (G183(d)); the switch around it is one serialized transition.**
*The safety net is the server's.* Every request runs in one bank, pinned when it starts (a switch while it awaits a
lock or a commit leaves it finishing there), and a write names the bank it STARTED in: `APIClient` sends it on every
POST/PUT/PATCH/DELETE (`X-Cicada-Bank`, `BankScope`), and the server refuses a write whose bank is no longer active
before its handler runs (`bank_mismatch`; both in api.md). The bank named is a `@TaskLocal` origin, captured at the
person's action, before anything is awaited: `Store.bankTask` captures the bank on screen synchronously and starts the
work bound to it (the schedule, the reading options, the reserve, Getting started's schedule question, the Safari tab
and bookmark imports, a feed or calendar removal, a backlog add, a picture's initials or removal); a picture upload
captures it before its detached preparation and builds its write from it (`PictureActions.upload(…, bank:)`, the drop
too); the Fades chip, Fade pace and the owner save capture it before their task; `Store.perform` binds the bank at
admission unless an enclosing binding already named one (so work queued across a switch keeps its own); a held answer
carries its own bank; a folder or Wispr Flow scan binds the bank whose configuration and manifest it read; a Mac reader with a per-memory
cursor or digest (YouTube history, Messages, tab groups, Contacts) binds each run to the bank it reads for, and a switch
that lands mid-run stops that run and starts the new memory's own read rather than joining the old one; and
`SleepViewModel.updateSchedule` / `updateRunOptions` honour an enclosing origin. Work that binds nothing names the bank
on screen at send time (`BankScope.onScreen`, kept by the app's `Store`) — during a switch still the old bank while the
server is on the new one, so it too is refused rather than misfiled; such work started in A that first sends after
the app reached B would name B (the binding rule above is what prevents that, site by site). On `bank_mismatch`
`Store.perform` rolls back and toasts "Memory switched — try that again" (the Fades chip and Fade pace say the same).
*The UX is the Store's.* `Store.switchBank` is the one transition for every route that changes the active bank: a
switch by name (`Store.activateBank`, reached by the switcher, the find palette and the intake card through
`BanksViewModel.activate`), entering the demo (`LiveSetupEffects.createDemoBank`) and leaving it (`DemoMode.liveExit`).
It reserves `Store.bankSwitch` (a generation and the target) before its first await, so a second switch from any door
is refused with "Switching memory — try again in a moment." and never interleaved. It sends the held answer and waits
for every answer already accepted — queued by the next tap or on the wire — so each lands in the bank it was made in
(R-DI3); an answer is never dropped by the switch, a late one is refused by the server and its question reopens, and
the "sent" callback runs only for an answer that landed. While the switch waits, new `Store.perform` writes, a new
inbox answer, the Fades chip and Fade pace are refused with the switching words; other direct writes are not held by
the Store — the server's check covers them. On the answer the Store moves to the bank the returned roster names and
hydrates it from cache, unless `refresh`'s fan-out saw the server move somewhere else meanwhile
(`bankSeenDuringSwitch`; then the server's roster decides and the older answer is never shown); it reconciles the
roster, releases writes (only the owning generation clears the marker) and reconciles the other domains. A failure
changes nothing and is said by its door. The switcher keeps the current name while it waits, disabled at 45 % with
"Switching to <bank>…" in `.help` (DR-41) — no spinner, no animation (DR-60). **Not covered:** reads are not
bank-bound — a GET answered by the new bank during the switch can be painted and cached under the old one until the
next reconcile (re-review finding 3, left open).

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
drawn in code — the badge counts **the conversations waiting for Sleep** up to 99, then "99+" (`BookwormOverlays.badgeText`, a
13-pixel pill; owner 2026-10-19: "can we make it so it counts things to consolidate?" — it counted the inbox's questions
from 2026-10-14). The count is `GET /status` `episodes.readable`, the count Sleep itself would read (`sleep_debt.readable_count`:
not parked, not index-only history, ruling 30), refreshed through the `.status` domain the `episodes` component already
maps to; an older backend's `unprocessed` stands in (`StatusSnapshot.waitingForSleep`). At 0 there is no badge. The mood
stays `.curious(count:)` — the sheet's "what's this?" beat at an unread pile — and never `.reading`, which in the menu
bar would say Sleep is at work while nothing runs; `.happy` now reads "nothing waiting for Sleep". It is said in words
(DR-69, DR-21): the header's "Curious — 12 conversations waiting for Sleep" and the status item's tooltip; the inbox
keeps its own line in the menu ("Inbox: 190 questions waiting"); a beat settles within 800 ms, a perk within 400 ms, and the yawn and stretch within 1.6 s (ruling 18).
Tags derive from `BookwormLook.keySegment` and are tested to match each sheet exactly; reading cycles three book
covers on its own loop. A transition always uses the sleeping sheet from the current room lighting/lamp set; a cold page never transitions, and a real
completion's cheer wins in either callback order. A lint bans `.offset`/`.scaleEffect`/`.rotationEffect`/`.spring(`
on every sprite except whole-cell lattice placement. Cached room crops are bounded by distinct frame rects and
decoded pixels; the small renderer's independent cache keeps its 1024-entry wipe bound. The pile's books are the
`room-books` sheet (six kinds × four count steps, day and night; the spine masks and `room-spines` retired 2026-10-16),
joined to width by `BookArt` and cached per kind, step, width and lighting; the book interactions are the spines' were. **Feeding** — a file dropped
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
never moves. Ask is a mode (⌘⏎) hosting the `AskPanel` body — the one place the app draws an Ask answer (the palette
and Home's field both host it). Under the page sources (chips, then each page's evidence chips) it lists **From
conversations**: `POST /ask` `conversations` (2026-10-19), the conversations the answer used that no page cites. A row
is a conversation glyph, the title ("A conversation" without one) and the day; the episode id only in `.help` (DR-54,
DR-48, DR-34); a click opens it in the Reader from the top (`AskConversationRow.primary`, the target a Sleep page row
opens; DR-31) and the palette steps aside as for an evidence chip. An older backend sends no field and nothing is
drawn; an answer kept in Ask history keeps its rows. One ranker, `QuickMatch`,
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
columns. The Inbox's focus card gained a name variant on 2026-10-14 (`NameBody`, `FocusCardVariant.name`, chosen by an
item's `asks: "name"` before its options; DR-43's table and §9): the question about a person Cicada knows only by a
relation (`features.md`) takes a typed name through `resolve`, or "I'd rather not say" (`NameAnswer.decline`).
**Settled by a check (owner ruling 2026-10-16):** below the questions at full width (`InboxQuestionList`'s `footer`) and
on the empty page, `SettledChecksSection` — closed until clicked ("Settled by a check · N"), then one filled row per
settled question (the subject and its answer, the quote, "From <site> · <age> · your agent looked it up | looked up while
reading your memory", the link in `.help`) with two compact `NeutralButton`s: Undo (`SettledChecks.undo`: the row leaves
at once and comes back with a sentence if the server refuses; on success the Inbox refreshes and the question is back)
and, for a public citation on a subject with a page, Track this source (`SettledChecks.track` → the person's own
`addEntitySource`, then "Tracked", disabled). `SettledChecks` is in memory, not a Store domain: loaded when the Inbox
appears, on a bank switch and whenever its questions change (`SettledChecksAPI`, faked in `SettledChecksTests`). Its
rows are per memory (their ids are inbox ids, which repeat across banks): another bank's read starts empty, and Undo
and Track name the bank the row was read in (G183(d)), so a row left on screen across a switch is refused.
**Settled by Sleep (ruling 29, 2026-10-17)** is the same section's second closed group ("Settled by Sleep · N"), from the
same list (`SettledCheck.group == "sleep"`, `bySleep`): the subject and Sleep's answer, the person's own words when it
rests on them, then the rule's reason and when (`settledSleepMeta`); Undo only (no Track — Sleep's settle cites no
page), its failure saying the page changed since (`settledSleepUndoFailed`). Neutral buttons, no accent (DR-40). A
`page_edit` item (G198, an agent's proposed change to a page's words or aliases) is `InboxKind.pageEdit` ("Page edit",
`pencil`, clarification's hue in both palettes — no new hue, DR-8) and renders as an options card (`apply` / `dismiss`
from the server, Not now); `InboxBodyPreview` draws its `body` — "Why: …" and the changes as "- Replace “old” with
“new”" lines — even beside a cause quote, because the body is the change itself (every other kind keeps the old rule:
the body only when there is neither a cause nor a quote).
**The quick review (owner 2026-10-19)** goes one kind at a time inside the Inbox page, never a new window. Above the
questions at full width (`InboxQuestionList`'s `header`), `InboxReviewEntriesRow` lists one text button per kind with
something to review — "Fading pages · 49", then Folds, Conflicts and Questions with theirs (`ReviewEntries`, counts
through `UsageFormat`) — and a click replaces the columns with `InboxReviewView`: the eyebrow says the place ("Inbox ·
Fading pages"; the line under the card counts answered, skipped and left), one card at a time (`ReviewCardView`, capped at the focus card's width), the same answers in
the same place on every card (`ReviewCard.answers`): **Keep / Let fade** for decay (`keep`/`archive`, in that order
whatever order the server sent), **Same / Different** for a fold (`0`/`1`, each described in the fold's two names), **A /
B (/ C…) / Both** for a conflict (every side with the day it was said; Neither and Other… stay the full card's), a typed
answer for a question (`NameAnswer` for a name, else `FreeTextSubmit`; "I'd rather not say" keeps its option). Sleep's
proposal is marked Recommended and never pre-picked — ⏎ accepts nothing, and there is no "accept all": one decision per
card. Context to decide without opening the page comes from `GET /inbox`'s `subject` / `fold` (`features.md`): a decay
card says when the page was last said and in how many conversations, and its lead sentence; a fold card asks "Is
“built with” the same as “uses”?", what it covers and an example; a conflict or question shows the quote and source line
that raised it. Keys (`ReviewKeys`, DR-68's grammar, DR-60 — every path runs in `Instant.run`): 1–9 answer, S skips, O or
⏎ moves into the answer field, ⌘Z (the Undo button's shortcut, never while the field has focus — R-DI4) takes back the
last skip or the last answer while the Inbox still holds it, Esc leaves the field and then ends the review. An answer is
the Inbox's own (`InboxViewModel.answer` → `Store.hold`, the 5 s send delay — nothing new writes); a skip writes nothing
and the question stays. The queue (`InboxReview`) is the kind's reviewable questions frozen at the start in the Inbox's
order; the card on screen is the first undecided one, so Undo puts a card back exactly where it was; a question settled
elsewhere leaves the queue, and an answer the server refused comes back at the END of it — after the card being read,
never in front of it (`reconcile`). Every answer and skip names the card it was drawn for (`reviewAnswer(itemId:)`): one
for a card no longer on screen is a no-op, so a key or click never lands on a card that swapped in under it. The Inbox's
own decay card has the same order (1 = Keep active, 2 = Archive, served fixed by `decay_question`; Recommended marks
Archive, it no longer moves it first), so one key never means opposite things in the two views. A legacy decay with no options,
a multi-valued conflict (G98) and the other kinds stay in the Inbox's full card ("Open in Inbox" on every card lands
there too). A bank switch ends the review. Tests: `InboxReviewTests`. Every other
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
fallback, opaque under Reduce Transparency); a lint fails the build on any glass API elsewhere. **Painted art is
retired** (owner 2026-10-16: "Remove it from everywhere"): the paintings (`Resources/art/`), `PaintedScene`, the Home
band, the Welcome hero, onboarding's panes and the empty states' grass and cloud are gone, and
`MeadowPlacementLintTests` fails on any painted component or a bundled painting. **The study room is the app's one
illustration** — pixel art on the Sleep page and in onboarding (`OnboardingRoom`), never behind data or text. Empty
states (`EmptyStateView`) are plain, well-set text: a 22 pt display title, the line, at most one action, centred in the
space the page gives them, with no card. Pixel sprites carry their provenance in
`Resources/sprites/sprites.manifest.json` (script, source, sha256), checked by `SpriteAssetTests`. **Type:** SF only. `displayFont(size:italic:)` is SF Pro Display
semibold (tracking −0.3 at 20 pt, −0.4 above, floor 20, paired and counted by `FontLiteralLintTests`), `quoteFont` SF
15 regular, one `SectionLabel` (11 medium, sentence case, never mono or tracked — `SectionLabelLintTests`), monospace
only on `MonospaceLintTests`' allowlist (code, commands, paths, keys, ids), and `CitedSpan` the washed, underlined span,
read by the Inbox's quote and the Reader's turns since DS-2 (a mention found by name is its semibold, unwashed case). **Motion:** `CicadaMotion` (nil under Reduce Motion) is the only place outside
`SleepMotion` a duration is spelled; `hoverLift()` for things that open, `iconHover()` for glyphs; a keyboard action
never animates. Sprites play per frame from their sheets within `CicadaMotion`'s sprite caps (ruling 18).

**Links show as what they are (owner rulings 2026-10-14; DR-5, 9, 13, 32, 37, 45, 52, 53, 58, 61, 63, 71).** A link on a
page draws the way its markdown title asks (`storage.md`, the link-title grammar; `LinkGrammar` in `LinkView.swift`, one
fixture with the backend). In the article (`WikiArticle`/`WikiInline`): a link in a sentence is accent and underlined; a bare
URL or `<URL>` is a live link that reads as its address (`example.com/guide` — the design guessed a bare URL was dead text,
`LinkViewTests` shows Foundation links it, so the fix is its words); a **mention** — `"mention"`, a block view written
inside a sentence, or a plain link in a `## Links` bullet — reads as the site in `textTertiary` (a `WikiInline.SitePart`
run, coloured when the row is drawn so a cached article follows the theme) then the title with a 30% underline; a view
word is never shown. A link alone on its line asking for a block view is a row of its own (`WikiRow.Kind.link`) drawn by
`LinkBlockView`: **bookmark** → `BookmarkCard` (title, two lines of description, mark · site · one date — "Read Oct 2"
when Cicada read the site's words, else "Saved Oct 2", else "Not read yet" — the stored picture left at ≥ 440 pt, on top
when narrower, on a ring, hover a fill); **screenshot** → `CaptureCard` (16:10, the caption below the picture never over
it: "Captured Oct 14, 2026 · 3 months ago", or "Saved to Looks Oct 14 · today" while a saved look stands in, "· nearest
to Oct 14" for a pinned day with none that day; ⤢ opens the lightbox with the date line); **captures** → `CaptureStrip`;
**look** → `LookSwatch` (the crop, `LooksPaletteStrip`, site · "Saved to Looks Oct 14"). Each degrades one step and says
so: "No capture of this page yet", "No captures of this page yet", "No saved look of this page yet" (DR-32). ⧗ Site
exploration's dated captures (the screenshot from a capture, the gallery, "Changed since you saved it", a gone site, the
Reader's "How it looked when you saved it", ⌘K's site mark) wait for that pipeline; until then `captures[]` is empty and
a look's screenshot of the same URL stands in. Every fact comes from `GET /entities/{id}/links` through `LinkFactsCache`
(in memory, not a Store domain); the app fetches nothing of the web: a click opens the saved item's page when the backend
matched the URL to one, else the browser, and ⌘-click always opens the browser (`LinkOpen`). A line with links has a 🔗
in the gutter (and an accessibility action, `LineLinksAction`) opening `LinkLinePopover`: each link's bookmark card, then
**the person's view switcher** — text tabs (DR-45) of the views Cicada has something for (Link, Mention; and for a link
alone on its line Bookmark, Screenshot with a picture of the page, Captures with a capture, Look with a saved look), ↗ and
Copy link (DR-53). Choosing one is `POST /entities/{id}/edits` with the link's token as `old` and the same link with its
view word as `new`, `all` and `pinned`, committed under the person with the reason "Shown as a bookmark." (owner ruling
4: the choice is memory, in git, visible to every agent; undo is the page's history). `PageLinkRow` (Where this comes
from) adds the link's date to its URL line and opens the same bookmark card after a short hover
(`CicadaMotion.linkPreviewOpenDelay` 0.25 s / `linkPreviewCloseDelay` 0.08 s). A media page's website card is now a
`BookmarkCard` (no all-caps site, a ring, DR-20/9). **Pictures in prose go through the gate:** `ImageThumbnail` loads only a
path on Cicada's own API (`StoredPreviewPath`, through `PictureStore`), and `ProseImage` draws a web image named in a
page's prose as a bookmark of its URL ("A picture from the web, not kept by Cicada") — the app used to hand any https
image a page named to `AsyncImage`; a saved image's hero and media card draw its stored copy. `LinkViewTests` keeps
`AsyncImage(` out of every page surface (the contributors view's avatar is the one left); `LinkRenderTests` draws every
view light and dark (`LINK_RENDER_DIR` writes the PNGs).

**Video (Track V).** A saved video plays where the user already is — a saved item's detail column in the
Feed, the entity Content tab and the entity hero, all through `MediaPreview`/`HeroPreview` — and the provider is
derived from the URL at read time (`VideoRef.resolve`), never read out of the page, so a bank never
needs rewriting to teach the app a new one.

**Prose provenance decode (G118 sections, 1a-i).** `Models/Provenance.swift` accepts
the additive section/item rows, source evidence and server body token. Older backends
default to no section rows/schema and a nil token. R-PB11 keeps this in the existing
on-demand memory cache, without a new Store/VersionVector domain. This slice adds no
disclosure or Reader UI. In 1b, the graph-node stub has no `pageBodyHash`: it must show
no section controls until a full entity response supplies a matching non-nil token;
nil tokens must never match. Server identity/ranges must not be recreated in Swift.

**Provenance viewer (G118 slice 2).** Every claim carries evidence chips (`Views/Provenance/`): the
label says who spoke ("You said", "<agent> replied", "From the page", "Inferred", "Mentioned here"
for a legacy claim's name match found at read; a feed item or a calendar entry is "From the feed" / "On your calendar"
with its source's mark, never "You said", here, in the Reader's turns and Noted rows, Where this came from and ⌘K —
`EvidenceSpeaker.sourceSpeaker`, 2026-10-17) — an agent's chip names its model when capture recorded one ("Claude
Code · Opus 5.5 · high effort", `ModelNames`; round-4 C3/C4), as do the hover, the Reader's meta line and turn labels,
"Where this came from" and a belief's help; an app with no capture says "model not shared by this app" — hovering shows the words in the quote face — washed
when quoted, bold when derived, plain when stale — and a click opens the **Reader**, a column
(`ReaderColumn`): the third progressive column on the pages that host it (the Inbox, Clusters, Sleep,
Sources and Projects — `AppTab.hostsOwnReader`), and on every other page the shell's trailing column (`ShellReaderHost`),
sized before the page so it is never pushed off-window. It is driven by
`ProvenanceRouter` (a stack of `ReaderTarget`s), beside whatever is open so a belief and its sentence
are on screen together (Direction D, DS-2). It shows C's header — mark, title, meta, and a neutral
Resume when an `isfile()` check says the session is resumable — the pinned "1 of N cited here"
navigator, the turns in the quote face with `CitedSpan`, and the "Noted from this conversation" rows. **A conversation
reads as a chat** (owner 2026-10-19, DESIGN_RULES §9): `ReaderChat.isChat` — an episode, not a page, a page-read, a watch
record, a feed item or a calendar entry, with at least one turn a conversation marker WROTE (`user:`/`human:`,
`assistant:`/`ai:`, `speaker:<name>:`; a role forced by `evidence_kind` on a marker-less file never counts) — draws
`ReaderChat.rows` (`ReaderChatModel.swift`, pure, `ReaderChatTests`) through `ReaderChatRows` (`ReaderChatView.swift`)
in the same `LazyVStack`, over the very `ReaderLayout.blocks` the document view uses, so washes, landing, the navigator
and both rotors address the same `ReaderBlock.Key`s. The person's turns sit right in a `chatBubbleFill` bubble, the
other party's left as plain text — the side read from each turn's written marker, not its role, because a relayed
conversation (ruling 32) forces every role to `assistant`: `/episodes/{id}/text` carries `relay: {app, label}` until an
export upgrades the episode, and then the person's side reads "Relayed by ChatGPT" (never "You") and the capture line
says the words came through the app's model; a run (one side and speaker, turns under 15 minutes apart) shows the face — the
Messages chat's own picture by `MessageBubbles.face`, the chat parsed from the sitting's `imessage:<chat>:…` source id
(`ReaderChat.messagesChat`), a monogram for a meeting speaker — or the agent's mark, the name only when it differs from
the one the header already names (`ReaderChat.namedParty`), and its first stored time, once. A chat's title drops a
trailing " · YYYY-MM-DD" and its meta drops the day and the turn count, naming the agent only when the capture line
does not (`ReaderHeader.title`, `chatMeta`); a document's header is unchanged. Day separators ("Today", "Yesterday", a weekday, "Thu, Sep 3") replace a date per turn,
computed when read; a gate-B2 gap is a centred line with its stamps as clock times. No "turn N", on screen or in
VoiceOver. A turn over 1,000 characters or 12 lines folds to 480 / 6 lines behind "Show more" (`unfolded`, per load) —
whole lines when cut at a break, else trailing punctuation dropped before "…" — except `ReaderChat.keepOpen`'s turns:
the one landed on and any holding a cited or found span. A chat with no quote to land on opens at its newest row
(scrolled twice, so the lazy stack's estimate settles) and pins its banners above the scroll; ↑/↓, ⇞/⇟, ⌘↑/⌘↓ and
Home/End move from the row at the column's top as the scroll view reports it (`scrollTargetLayout` +
`scrollPosition(id:)`, so a trackpad scroll moves the start too; `ReaderChatKeys`), top-aligned, in one frame. The
built layout is memoised per document, target, unfolded set, jump and citations (`LayoutMemo`). Everything else keeps the document view. A turn is
selectable **and** washed through `CitedPassage` (2026-10-16): a selectable `Text` never reaches a `TextRenderer`, and
a renderer-drawn copy behind the words breaks lines differently from them (the wash on the wrong words at some widths),
so the passage is one selectable `Text` whose wash and underline are attributes of its own string (`CitedSpan.fallback`:
square fill, the text system's underline, no fade) — until then the navigator counted spans nothing showed
(`CitedPassageTests`; the Inbox's quote too);
a swap onto the same conversation re-lands in place (`ProvenanceRouter.refocus`) rather than stacking
a Back step. The dandelion wash and margin bar are gone (DR-13). It reads `/episodes/{id}/text`
and `/citations` through `ProvenanceCache` — in memory, ETag-revalidated, **never a Store domain**,
so there is no `VersionVector` mapping — slices every offset as a Unicode scalar through one
`ScalarText`, reads a quote and a turn without their markup or role labels (`ExcerptText.stripMarkup` /
`quoteParts`: deletion only, so every span maps exactly; the Reader keeps a turn's lines, drawing a bullet as "•"),
shows a time only when the episode stores one, and says stale / grown / derived /
inferred / truncated in words — a span its rewritten document no longer reaches (the server's 422) is
stale too, never "couldn't open". The entity card's "Where this comes from" (Content, after the page and its beliefs) reads
`/entities/{id}/provenance` once per card and `/entities/{id}/sources/overview` when the section or the beliefs list
opens (both through `ProvenanceCache`);
G61's sources, the page's links and its conversations by app are one section since 2026-10-14 (`features.md`). Its last part,
**Who wrote it** (G198, `WhoWroteItSection`), is `GET /entities/{id}/blame` read when the section shows
(`PageSourcesSection` asks `ProvenanceCache.blame`; no ETag, so it asks again on every show, keeps the last answer on a
failure and draws the held one at once on a re-open; a 404 — an older backend — leaves it out; a `pending` answer, the
backend's blame still running, never replaces the held copy and is asked again `CicadaTiming.blamePendingTries` times,
`blamePendingRetry` apart): per part of the page's
text (an H2, an Article section as "Article › title", the opening before any heading), who last changed its lines with
the shared marks and names (`ContributorAvatar`, `ContributorIdentity.displayName`), how many lines and the day
(`EntityDates.shortDay`, DR-58), and an agent edit's reason in quotes, "· accepted by you" when the person applied it
from the inbox; at most three writers a part and four parts before "Show all" (DR-38/39). Words in `PageBlameWords`,
copy in `Copy+PageEdits.swift`. Chips read the router
and cache as optional environment values, so a chip outside the main window renders without a
click-through rather than trapping; the Ask sheet steps aside when the Reader
opens (the Belief Timeline is inline in its tab since DS-3a), and a bank switch closes it and empties the cache (episode ids repeat across banks).

**Versions and builds (G182).** The repo's one `VERSION` file is the version everywhere: `bundle.sh` stamps it as
`CFBundleShortVersionString`, `api/version.py` reads it for FastAPI's `app.version` (and so `/healthz`) and the MCP
server's `serverInfo`, and `api/pyproject.toml` carries the same string (`test_version.py`). `CFBundleVersion` is the
build number — the commit count, or `CICADA_BUILD_NUMBER` when a build passes one — so it only grows along `main`.
Settings → General ends with a Version row ("Version 0.3.0 (1523)", `AppVersion`); when `/healthz` answers with a
different version (an updated app beside a background service still running the old one) the row says so.

**The release app (G182 phase 2).** `bundle.sh --release --with-backend` builds the installable app: it runs
`scripts/release/build-backend.sh` (python-build-standalone CPython 3.12 for arm64; the release dependency set from
`scripts/release/requirements.lock`, hashed, no torch; Cicada's tracked `api/`, `mcp/`, `skills/`, `SKILL.md`,
`VERSION` and agent script; dugite-native git, pruned, with its GPLv2 `COPYING` and a source pointer; the int8 ONNX
`intfloat/multilingual-e5-small`, owner 2026-10-06, fetched through `scripts/fetch-embedding-model.sh` — the same script
a developer checkout's `make embedding-model` runs, the one reader of the model pins in `scripts/release/inputs.env`; and
`coremltools` with the sympy/mpmath it imports, ≈ 28 MB unzipped, for EmbeddingGemma 2 — whose model is downloaded into
`~/.cicada/models` on request, never bundled: about 340 MB more in the zip, for a model only macOS 15 runs), copies it to `Contents/Resources/backend/`, stamps `CicadaDistribution=release` (and no
`CicadaRepoRoot`), strips the binary and signs every Mach-O ad hoc, inside out, never `--deep`
(`scripts/release/sign-app.sh`). 347 MB unzipped, 138 MB zipped with the English-only model; the multilingual
model adds about 95 MB (113 MB model and 16 MB tokenizer against 34 MB). Nothing is written inside the signed app:
bytecode goes to `~/.cicada/cache/pycache`. `scripts/release/smoke-test.sh <app>` copies a build to a temp folder and
proves it there with a temporary home, bank and port (health and version, the bundled git, an MCP save, the bundled
model through sqlite-vec, a hook, a launcher that fails loudly when its app moved). `CicadaRuntime` decides the
distribution once at launch (the plist stamp plus the bundled launcher on disk); a developer build — `make dev`,
`install_app.sh`, the auto-updater — has no stamp and behaves exactly as before. A release writes
`~/.cicada/bin/cicada-{backend,mcp,hook,python}` and `~/.cicada/bin/cicada` (the G180 command line) on every launch
(`LauncherInstaller`, atomic, 0755; the inner scripts come from `scripts/release/write-launchers.sh`), each a few lines
that exec the matching script inside whichever copy of the app opened last and exit 127 with a sentence when it is
gone; MCP registrations, the Stop and recall hooks and the launchd plist name only those paths
(`api/services/runtime_layout.py` and `CicadaRuntime` hold the same shapes; `AgentConnectPolicy` accepts exactly the
running distribution's). The hook registry knows both forms as Cicada's own, so one entry per script survives a switch
between a source install and the app. Memory defaults to `~/cicada/memory`, never inside the bundle. The background
service stays opt-in; a release re-points an existing `com.cicada.backend` plist at its launcher
(`BackendAgentPolicy.needsMigration`, then the bundled `install-backend-agent.sh` in its `CICADA_BACKEND_PROGRAM`
mode, logs in `~/.cicada/logs`). `CICADA_PORT` (default 8000; the app also reads the `cicada.port` default) is honoured
by the app, the backend, the MCP server, the hooks and the launchers. The bundled git is first on the backend's
`PATH`; the app's own repo reads try the person's git first and the bundled one last.

**Releases (G182 phase 4; TODO ruling 19).** A release is a `dev` → `main` PR, and merging it is the release. `VERSION`
is the one version: `scripts/release/check_version.py` holds `api/pyproject.toml`, uv.lock's `cicada-api` entry, the
built app's `CFBundleShortVersionString` and `latest.json` to it, and judges it against the remote's `v*` tags (already
tagged → publish nothing; not greater than the latest → fail). The owner's two commands open PRs and nothing else
(`scripts/release/release.sh`; never pushes `main`, never tags, never force-pushes; `--dry-run`): `make release
VERSION=x.y.z` bumps the version files on `release/vx.y.z` off `origin/dev` and opens its PR to `dev`; `make release-pr`
opens `dev` → `main` "Release vX.Y.Z". `.github/workflows/release-check.yml` fails a PR to `main` whose head isn't this
repo's `dev` or whose `VERSION` CI would not publish. A push to `main` runs `.github/workflows/release.yml` (one
concurrency group per commit, so a run never cancels or replaces another commit's): a **plan** job on ubuntu (stamps
agree, tags decide), a **build** job on `macos-26` (arm64, Xcode 26) — `bundle.sh --release --with-backend` with the
commit count as the build number, the Info.plist version check, `smoke-test.sh`, a `ditto -c -k --keepParent` zip, its
Ed25519 signature (`scripts/release/sign_update.py`, private key in the `CICADA_UPDATE_SIGNING_KEY` secret, verified
against the committed `update-public-key.txt`), `latest.json` (`latest_json.py`: version, build, versioned asset URL,
size, sha256, signature, notes URL) and `Cicada-macos-arm64.zip`, the same bytes under a stable name the website links
as `releases/latest/download/Cicada-macos-arm64.zip` — and a **publish** job, the only one with write access
(`scripts/release/publish.sh`): the version judged again against the live tags (a re-run reuses a stale plan) and the
commit checked to still be main's tip (only the tip publishes; a superseded run ends green and deletes only its own
draft, so of two release merges in flight only the newer ships), a draft release at the merged commit created through
the REST API and owned by the id in its response (never rediscovered through the lagging releases list; two drafts may
share a tag), all four assets uploaded to that id with notes (`release-notes-header.md` + notes generated since the
previous tag), the draft read back by id (tag, target, every asset's name and size), main's tip checked again, then
published by a PATCH that spells out `tag_name` and `target_commitish` (one that omits `tag_name` drops the tag) —
GitHub creates the tag only then — and marked latest only when it is the highest version; the release must then read
back public under `vX.Y.Z` and the remote tag must point at the merged commit, else the run fails loudly and touches
nothing. A failure before publication deletes the id it created and nothing else (a draft has no tag, so no tag is
touched); a published release is never touched again. A push to `ci/release-dry-run` or a manual run off `main` does
everything but publish and uploads the files as an artifact; a re-run or a manual run on `main` re-attempts an untagged
`VERSION` only while main's tip is still its commit (a fix ships as a new release PR). The app carries the public key
and the repo (`CicadaUpdatePublicKey`, `CicadaUpdateRepo` in Info.plist) for the updater.

**Installing and updating a release (G182 phase 5).** Testers install with
`curl -fsSL https://raw.githubusercontent.com/rorosaga/cicada/main/scripts/install-release.sh | bash`: it reads the
latest release's `latest.json`, downloads the zip with curl (no quarantine flag, so Gatekeeper doesn't block the
not-yet-notarized app), checks its sha256 and `codesign --verify`, installs into `~/Applications` (else
`/Applications`), moves an older copy to the Trash, quits only the copy it replaces, and opens the app. In the app,
`UpdateService` runs only in a release (`CicadaRuntime.isRelease` and a stable path; a developer build never checks):
20 s after launch and every 6 hours while Settings → General → *Install updates automatically* is on (default), and
from Cicada → Check for Updates…, it reads GitHub's latest release and its `latest.json` (`UpdateChecker`; newer by
semver, refusing a release that needs a newer macOS), downloads the zip, and `UpdateInstaller.stage` verifies size,
sha256 and the Ed25519 signature against `CicadaUpdatePublicKey` (`UpdateVerifier`, CryptoKit) before unzipping,
checks the bundle id, distribution and version and `codesign --verify`, and copies it beside the installed app. It
installs when the person quits — or at once with *Restart to update* — never while Sleep is writing: a detached
helper (`posix_spawn` in its own session) waits for the app to exit, boots out `com.cicada.backend` if its plist
exists, swaps the two copies by rename in the same folder, moves the old one to the Trash, bootstraps the service
again (three tries) and relaunches. The backend is asked fresh whether Sleep is writing — by the app at hand-off and by
the helper just before it stops the service — busy means a cycle `running`, `writing: true`, or a real inbox tidy
settling questions (`inboxTidy: true`, ruling 29); a paused run waiting
on Continue is neither (its sidecar outlives the restart, 2026-10-17) — and a busy answer defers the swap to the next quit
(`~/.cicada/update-deferred.json`; the staged copy and its `.Cicada.app.update.json` sidecar are kept, so nothing is
downloaded twice). Any failure puts the old copy back and leaves `~/.cicada/update-failed.json`, which the next launch
shows once in the Version row ("couldn't be installed … You're still on 0.3.0"); a service that didn't start again is
reinstalled once on that launch. The zip must be one of the same release's own assets, over https. The new copy rewrites the
`~/.cicada/bin` launchers when it opens. Log: `~/.cicada/logs/update.log`.

**Settings → Search & files (owner, 2026-10-14; G182 phase 3, EmbeddingGemma 2 owner 2026-10-09, G133, G195 frame).**
A section in the Cicada group between Privacy & data and Memory (`SettingsSection.searchFiles`, a new case): sidebar
*Search & files*, page title *What Cicada can look through* (`SettingsSection.pageTitle`; the header shows it, the
sidebar and search show the short name). One place for what Cicada can look through, in plain words — the owner: "without
mentioning embeddings". `SearchFilesView`, top to bottom:
- **Folders** — one row per watched folder (`FolderChannelRow`, moved from Integrations → Notes & files): name, its depth
  as a `Tag` (DR-44) — *Kept in memory* today, the one depth that exists (G133) — and one state line ("312 notes · Last
  synced 2 hours ago", `LocalSourceRowText.folderState`); the path is the row's `.help` (DR-19/DR-54); *Manage* is the
  one control and the sheet holds *Read now*, the agent-folder checklist and *Stop watching* (behind a confirmation).
  *Add a folder* is the list's last row; on an empty list it is the page's one `PrimaryActionButton` (DR-40); in the
  demo it is dimmed and says "Folders are added to your own memory, not the demo" (DR-41). The add sheet keeps *Look
  inside* before *Start watching* (R-LS13) and now says "Sleep will read 9 notes of your own" (a count of notes, never
  of passes). The onboarding Import page's *Add a folder* opens the same sheet. Failures lead with one `warning` glyph
  and are never `danger` text (DR-7, `WarningLine`).
- **How search understands** — two consent rows, each one `NeutralButton` that names what it does, with the size in the
  detail before the click (`SearchUnderstanding`, pure and tested in every state): *Understand what you mean* ("On, built
  in. A sharper version finds looser matches, in any language: a one-time download of about 585 MB…" — the built-in
  version already understands meaning, so the download is framed as sharper, never as turning meaning on); *Turn on*
  downloads it (`POST /embeddings/install` with `model`, the size from the catalog's `downloadBytes`) and clears a
  choice that would keep it off first, so one click means "use it" (the backend's re-read follows the download). While
  it runs: the backend's step in words and a native linear bar from `install.done/total` (bytes); then "Re-reading your
  memory for sharper matches — step 1 of 3. Search keeps working meanwhile."; while Sleep runs the button is dimmed with
  the reason (DR-41). *Understand images* is its own second click (`POST /embeddings/install` with `part: vision`),
  dimmed with "Turn on Understand what you mean first — images build on it." until the text part is here, so the two
  clicks stay two; on an unsupported Mac it is a fact with no button. It reads `vision`, which `GET /embeddings` already
  served and the app now decodes (`EmbeddingVisionState`; nil from an older backend hides the row). `install.part`
  (`text`|`vision`|`larger`) puts a step on the right row.
- One privacy line ("Folders are read on this Mac, and everything search downloads stays here.").
- **Advanced**, collapsed by default and remembered per viewer (`cicada.searchFiles.advancedOpen`, DR-39): *Search
  version* — the `PillPicker` of the catalog's labels (*Sharper*, *Built in*, and *Larger* only where Sharper can't run
  or the bank already uses it) with its detail line (`SearchModelLogic.detail`). A selection is never the consent: picking
a version not on this Mac sends nothing and raises a confirm that names its size (`SearchModelRoute.confirmDownload`,
`SearchModelLogic.confirmation`), and only its *Download* button starts the download; picking *Larger* opens
  `LargerSearchModelSheet` (the terms are accepted on Hugging Face with the person's own account, so a read-only key from
  that account downloads it once; the key rides one request body, is cleared from the view at once and is never
  stored); and *Rebuild search* (the old Search index row; costs only time, no confirmation, TODO ruling 3). Version
  names appear here and nowhere else.
A failed re-read on the default view is the page's own sentence, never the backend's diagnostic; *Turn on* is dimmed
with the reason while any download runs (the Looks shortcut included), never an enabled click that answers 409.
`SearchFilesTests.testDefaultVisibleWordsAreNeverTechnical` holds every default-visible string (`Copy.SearchFiles.
defaultVisible` and every state the two rows can render) free of model, embedding, index, vector, token, runtime and
checksum; Advanced is exempt; the hidden Settings-search keywords keep every technical word so "embeddings" still lands
on *Understand what you mean* and "rebuild" opens Advanced (`SettingsIndex`, anchors on `.searchAdvanced`). The backend
writes its catalog labels, steps and errors in the same words (`api/tests/test_search_words_are_plain.py`). Folder
channels index on this page, and a saved folder row opens it (`ChannelActions.settingsSection`). **Memory** keeps *Fetch
link previews* and *How things fade*. Not yet (G195): the search-only depth, kinds per folder, reading N of M files and
the idle/on-power pause — none is rendered until something computes it.

---
