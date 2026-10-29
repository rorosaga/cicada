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

**The connection model in the app (ruling 36 D6, G217, G212, G213, G50; 2026-10-22).** Three nouns: **Sources** feed
Cicada (the Sources page), **Intelligence** consolidates it (Settings → Intelligence), **Agents** read and write it (the
Agents page, ⌘9, `AppTab.agents`, appended so no shortcut moved — DR-22).

- **Settings in six:** General · You · Intelligence · Sleep · Devices · Privacy & data (`SettingsSection`), one
  unlabelled sidebar group, no page subtitles, under 400 words (measured 295 on the demo bank with the inventory's AX
  counter, from ~2,030 across eleven sections). Every retired raw value has a home in `SettingsSection.retired` — a row on
  a surviving page (`engines`/`plansAndKeys` → Intelligence, `memory`/`searchFiles` → Privacy's search row, `remote` →
  Devices) or a sidebar page (`integrations`/`reading` → Sources, `agents` → Agents, `skills` → Skills) — and every
  retired row id one in `SettingsIndex.retiredRows`; `AppRouter.open(_:)` and `SettingsSectionLink(home:)` follow either
  kind. A saved `cicada.settingsSection` naming a page opens General. `SettingsAnchorsTests` holds all of it.
- **Intelligence** (`IntelligenceView`): one *In use* row (the engine's mark and name from `preview.manual`, a model menu
  when the chosen card offers several, *Use Auto*), then *Plans* and *API keys* from `GET /providers` `intelligence[]`
  joined to `/connections` (`ProviderDirectory` caches the static table in memory; `/providers` names the local engine
  `ollama`, `/connections` `ollama-local`). A local model is the quiet last key row, never pitched. A key is pasted,
  checked (`PUT /connections/{id}/key` with `check`; 422 refused — nothing saved; 503 — *Save without checking*), then
  shown as its last four, where it lives and when it was checked, with the provider's terms note. Below: *Scheduled runs
  may use my plan* (ruling 4c), *Keep going on extra usage* (R-E13, only under a plan) and *Use my Claude plan when I
  start* (only under a key). The Sleep page's engine menu is a label that opens this page (`EngineLabelButton`); the
  full menu stays in Sleep → Options, which keeps the plan reserve and the model prices (ruling 12).
  **Your agent tools (G49/G50, 2026-10-28)** sits between Plans and API keys: one `OwnToolRow` per Cursor, OpenCode or
  Grok card from `GET /sleep/engine` (mark, *Connected* / *Not connected* / *Not installed*, the tool's billing note or
  a stale saved model in words, *Use* once signed in, and — signed out — the sign-in command in a `CommandBox`; Cicada
  never signs in for them). **The picker is data-driven:** a candidate's optional `kind`, `engine`, `mark`,
  `billingNote`, `modelNote` and `signIn` drive `EngineOption.isPlan` / `isOwnTool` / `logoName(for:)` /
  `costModel(for:)`, `previewName` / `previewMark` / `candidateId(forEngine:candidates:)` and `EngineReadiness`, so a
  new engine renders, selects and names its runs without an id table; a body without them (an older backend) answers
  as before. The quick menu lists an own tool's models (live, else its documented defaults, plus a saved one) and says
  a stale one; onboarding keeps its four engines (`compactCandidates`); `EngineMark` wears the tool's mark for a
  `<tool>-cli` run. **Engine picker v2 (ruling 48 part 11, `10-engine-picker`, 2026-10-28):** the quick menu's model
  `Picker` is gone (amends R-HS10). A card with models opens a second column, `EngineModelList`
  (`EngineModelListModel` holds every decision): the filter focused on open (`CicadaSearchField`, ↑/↓ and ⏎ choose,
  no animation, DR-60), the catalogue's families as `SectionLabel`s with their counts (DR-47), newest three per family
  and *Show N older*, "New" a `Tag` (DR-44) for 14 days, a model's list price only where the wire gives one (ruling
  12), and "<card>'s own list, as of N min ago · Refresh" — Refresh is `POST /sleep/engine/models/refresh` on the
  click only (`SleepEngineViewModel.refreshModels`; a failure keeps the list and says so). The only drop-down left in
  the menu is the reserve's (DR-81). Every engine card keeps its own bundled mark (all `same` in the 2026-10-28
  freshness check); Cursor and Grok are not merged under a parent mark — they stay two tools with two sign-ins.
- **You:** the name and photo (`EntityPicture`, editable), the email the photo ladder hashes, and *Your profiles* — any
  profile link pasted as-is, stored as the owner page's sources (`/entities/{owner}/sources`, G61); a pre-D6 GitHub
  handle shows as its profile link. *Connect* only for a service read through a connection (X, Reddit, Pinterest),
  which opens the Sources page.
- **Devices:** `GET /devices/status` rows — the server by its Computer Name, never "this Mac" — each a dot and one word,
  how it connects, last seen and its waiting count, Revoke; *Pair a device* (`PairDeviceSheet`) draws the
  `POST /devices/pairing` code as a CoreImage QR (level M) with the code beside it, polls every 2 s, cancels on close.
  The QR's `url` is the backend's to fill (this machine's Tailscale name for the backend port, when it can tell); the
  app sends none. With it the sheet says the address and "Scan with Cicada on your phone"; without it, one line says
  which address to type.
  *Memory on* and the folded *Apps outside this machine* (the remote connector, `page:remote`) follow.
- **Privacy & data** gains Search & memory's one row (*Search runs on this Mac* and the sharper-model download); the
  fade card shows only while it holds a suggestion or a chosen pace. Watched folders are sources (`WatchedFoldersGroup`
  is kept whole for the Sources page). Under *Agent conversations*, *Your agents' notes* (ruling 43, `.agentNotes`) is
  the memory's one switch for the agents' own memory notes (`GET`/`PUT /capture/agent-memory/settings`), on by
  default, optimistic with rollback; disabled until the backend answers (`capture-and-sleep.md`).
- **Reading in your browser** (fix round 2026-10-22): Reading the web's switches — the master switch (on by default
  behind the versioned first-use sheet), the signed-in session (ruling 25), the YouTube lists, Never explore, how the
  agent reads and watches, the sites — in one sheet from the Sources page's header (`ReadingInBrowserSheet`); the
  retired `reading` section and its rows open it (`SettingsHome.readingInBrowser`, `AppRouter.routeToReadingInBrowser`).
  **Where to check** (owner 2026-10-26, G61) opens the sheet, above the switches (`AddedSourcesSection`): paste a link,
  optionally pick a page by name (live pages only, never creating one), *Add* — with a page it is that page's source
  as the person's own (`POST /entities/{id}/sources`), with none it is saved as a link (`POST /sources/save`). Below it,
  every page's sources the person and their agents added (`GET /sources/where-to-check`, an agent named by its harness),
  each with who and when and an ✕ that removes it as the person (`/sources/change` remove — remembered). Not a Store
  domain: `AddedSourcesModel` keeps the list in memory with its ETag (a 304 keeps it) and reads it again after each
  write; a removal is optimistic with rollback.
- **Status words** (fix round; words ruling 39, 2026-10-24): a dot and one word from one vocabulary — *Connected*,
  *Not connected*, *Off* (the person turned it off), *Needs sign-in* — across onboarding, the Agents page, Sources and
  Settings; "Found" and "Not set up" are never a status. The dot and the word agree: an agent or a paired device is *Connected* (green) when seen within the backend's window, configured, with conversations or seen before — recency lives in the line ("3 min ago", "last seen <day>"), never in the dot — else *Not connected* (`Copy.Presence`: `.connected`, `.idle` (only the line's wording differs), `.notConnected`). A plan or key in Settings → Intelligence nobody connected reads *Not connected*, never *Off*. An agent's detail draws the connect steps (`AgentSetupSteps`:
  Connect for me, Open in Cursor, the copied prompt) for the product picked among its umbrella's.
- **Sleep:** the study room's preview first, the hours, then the scenery's source (the weather sentence in one line) and
  the mascot.
- **Agents page** (`AgentsSidebarPage`): one row per umbrella from `/providers` — `LogoTile` · name · where it was seen
  (never where it could connect: a row nothing has seen has no line) · last seen · conversations · a dot and one word (`/agents/live`, polled every 3 s while shown; conversations summed from
  `sourcesOverview` by harness). A row opens its detail (DR-74): products and how each connects (`AgentProducts`: a way with a `remoteLabel` is two lines — "Claude Desktop · on this machine" and "claude.ai · from anywhere · by export" — so the connector is never named after the Mac app), page edits as *Writes
  at once* / *Proposes* (G198's list), *Copy setup prompt* (`/agents/setup`), *Import its chat export*, and *Remembers
  automatically* for a harness with hooks. *Add an agent token* (DR-75) makes a G213 token and shows its paragraph once;
  active tokens list with Revoke; the command-line tool closes the page. **Who is listed (owner 2026-10-26):** only a
  product that can actually reach Cicada, by its current name and its own mark — *Devin* (Windsurf became Devin Desktop
  on 2026-06-02; with the Devin CLI and cloud Devin, way id `windsurf` kept), *GitHub Copilot* with the Copilot glyph
  (VS Code agent mode and the Copilot CLI; way id `vscode` and the G135 app id kept, its label "GitHub Copilot"), *Muse*
  with Muse's own mark (Meta's agent; umbrella id `meta` kept), and xAI's three ways (Grok Build, the Grok app's custom
  connector, Grok Bot asked in chat). Cline, Goose, Kiro and Poke left the table and the logo set; a person who had
  connected one still lights *Another agent* and an old sign-in request reads "An agent" (`agent_catalog`'s docstring).
- **Marks:** one per provider umbrella from the curated set (`app/assets/logo-set/`, `scripts/build-logo-set.py`, origin
  `set` in `logos.manifest.json`); `codex`/`chatgpt` draw OpenAI's mark and `gemini-cli` Gemini's through `BrandMark`.
  A listed connection's mark sits in `LogoTile` (26 pt in a 36 pt ring tile; `.dense` 18 in 24); a status is
  `StatusDot`; a row is `ConnectionLine` (DESIGN_RULES §9, 2026-10-22). **Freshness** (vision item 4, 2026-10-28):
  `scripts/logo-freshness.py` asks each set mark's own `source_url` once and reports `same` (bytes, or pixels for a
  re-encoded PNG — a pure-stdlib decoder, Adam7 included), `changed` (the fetched file kept under `--save-dir` for
  review), `pinned` (a commit, npm version or Commons file page: never asked) or `unreachable`; the weekly
  `.github/workflows/logo-freshness.yml` puts the table in the job summary and the changed files in an artifact, with a
  read-only token — it never commits or opens a pull request; replacing a mark stays a reviewed `fetch-logos.sh` run.
  Audit 2026-10-28 (45 set sources behind the 54 bundled PNGs): 23 same (8 of them PNGs the vendor re-encoded), 20 pinned, 2 visible redraws (Fireworks, OpenClaw — waiting on
  the owner), 0 unreachable; every bundled PNG is 256 px except Instinct (64) and Warp (196), which their vendors still
  serve no larger, and a 256 px raster is ≥ 4.9× the 52 px the tile draws on Retina, so nothing was re-cut at 512.

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
Sleep, Sources, Projects, Agents at ⌘1–5 and ⌘7–9 in `AppTab.allCases` order (`RailItem`; a page switch is instant).
**The Inbox left the rail (ruling 48 (2), owner 2026-10-28):** its questions live on Home and on each page, and the
full grouped list is Home's sub-view — `AppTab.inbox` stays a destination (⌘K, the menu bar, a notification, Home's
*All N questions*) but draws no cell (`AppTab.onRail`), Home's cell reads as selected while it shows (`railCell`), its
eyebrow is the path back ("Home · All questions") and Esc with nothing open returns to Home; ⌘6 is left unused and no
other digit moved (DR-22). The pending count is Home's badge now. Looks
(⌘9 from 2026-10-14) went on 2026-10-20 — its looks live on their pages' cards — and a stored "Looks" selection restores
to Clusters; Agents took the free ⌘9 on 2026-10-22 (ruling 36 D6). The Feed
retired into Sleep on 2026-10-16 and Skills took its cell, so ⌘4 opens Skills and no other shortcut moved (⌘ map A);
for one release the first ⌘4 that lands on Skills toasts "The Feed is now part of Sleep (⌘5) → Saved." once per viewer
(`FeedMovedHint`, the key only — a click on the cell never shows it), and a stored "Feed" or "Capture" selection
restores to Sleep. Each cell's tooltip
naming its page and shortcut (450 ms, then instant while warm), selection by brightness and one neutral fill
(`bgSelected` — never the accent, `SelectionTintLintTests`), the pending count on Home a neutral `bgBadge` numeral, a spinner on
Sleep while a cycle runs, the gear alone at its foot (the sun/moon toggle retired into Settings → General → Appearance,
owner 2026-10-26), no wordmark. The gear's `warning` dot lights only
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
Customize · Engines & keys (`SettingsGroup`, G139) — Cicada: General · You · Privacy & data · Search & memory · Sleep;
Customize: Integrations · Reading the web · Agents · Devices & access · Skills; Engines & keys: Engines — and each
page's own header with an `esc` keycap and a close ×. It is modal: the shell under it is inert, ⌘K waits, Esc and a
scrim click close it. `AppRouter.openSettings(_:row:)` is the one door (`SettingsSectionLink`, the gear, ⌘,), every
hand-off to a page closes it, and `cicada.settingsSection` is only its remembered selection — the `Settings{}` scene
and its cross-window seeds are gone. Privacy & data exports a bank and moves one to `<root>/.trash/`, but never
switches banks (that is the command bar's). **Eleven sections, not fourteen (Hyrum audit B1, 2026-10-22,
`docs/research/2026-10-22-hyrum-audit.md`):** Memory's one card joined Search & files, now *Search & memory*; From
anywhere joined Devices, now *Devices & access*; Plans & keys closes Engines. Each moved page is a group on its new page
under the anchor its header had (`SettingsRowID.memoryGroup` = `page:memory`, `.fromAnywhere` = `page:remote`,
`.plansAndKeys` = `page:plansAndKeys`), so `settings.row.page:<old>` still names it. `SettingsSection.retired` maps the
three old raw values onto their new section and group: a saved `cicada.settingsSection`, the R-O11 `agentsMode`
hand-off (now Devices & access) and a ⌘K recent (the group keeps its page's palette key) all open there, never
General. Search still finds each by its old name (`SettingsIndex.formerNames`, the groups' own entries). General's
Setup row joined the tour and the demo in one *Getting started* card (B12); the command-line tool moved to Agents' last
card (B11); Reading's two method groups wait under *How your agent reads and watches* while its switch is off, and a
landing on any of them opens the fold for that view only, never stored (B23, `ReadingMethodsFold`; Plans & keys' key
fold the same; both draw through `DisclosureHeader`, DR-39). A saved retired value lands on its group
(`SettingsSection.restoredLanding`). A landing keeps its row on screen while late cards arrive (Agents' setup steps,
the devices list): the row reports its place in the scroll content's own space, and each move inside
`CicadaMotion.settingsLandingWindow` (3 s) lands again, never animated; the person's scroll wheel or a key, a new
search, a sidebar pick or a newer landing ends it (`SettingsFocus.settlingRowMoved`, `endSettle`). From anywhere's
public-address check runs once its group is on screen and switched on, not on every visit to Devices & access. `SettingsAnchorsTests` fails when a search entry, an in-app deep link, a retired value or a
"Settings → <old section>" pointer in copy or docs stops resolving. No stored key, default, route, wire field or
`cicada` command changed. Search & memory has no "Look for duplicates" yet (R-O17) — the dedup endpoint
now runs off the event loop and commits what it merges (G183(e)), so the button is the remaining half. It also holds
G147's *How things fade*: pace suggestions from the person's own "Still tracking…?" answers
(Apply · Not now — the latter per viewer) and each chosen per-type pace (Reset). **Settings defaults (owner
2026-10-22: "Remove all those environment variables and stuff in the settings page. Let's just work towards the good
defaults").** No Settings page shows an environment variable, a settings file, a home-relative path, a raw model id or a
maintenance button; `SettingsDefaultsTests` holds that and holds every data, privacy, consent and trust control drawn
and found by search. Advanced is gone (its backend status, MCP command, token path, environment switches and
*Settings file*); a saved `"advanced"` selection reopens on General. Engines has no model picker or model-id field
(each engine runs its own default, a model already chosen keeps being used, and the Sleep page's engine menu is where a
model is switched); its preview lines say who reads, never the model. Search & memory has no Advanced (version picker,
larger-version account sheet, *Rebuild search*) and no *Fetch link previews* (Sleep's tail describes saved
links every run); Agents has no `make install` card; Engines' Plans & keys group folds the key cards nobody has saved a key in under
*Use an API key instead* (DR-39, per viewer `cicada.plansAndKeys.keysOpen`). Privacy names the memory folder in words
(Show in Finder opens it), and keys, tokens and the pinned engine are said in words, never a path or a variable. Every
value already set (`api/.env`, the environment, the bank's prefs, `~/.cicada`, UserDefaults) is still honoured; the
routes, `GET /status`'s `envOverrides` and `settings` blocks (`api.md`) and the `cicada` commands (`cicada sleep engine
--model`, `cicada index use|install|rebuild`) stay for developers. The full control table is in PR #405 and
`docs/research/2026-10-22-hyrum-audit.md`. **Pass 2 (same day):** Engines opens on Auto (below, "Settings → Intelligence");
Plans & keys says each card's state in words (`ConnectionsView.howLine` and `unconnectedDetail` map the plans', the
local model's and the keys' backend sentences — a CLI, `localhost:…`, a key file's path, the variables Cicada strips —
to `Copy.ConnectionLine`; an install hint keeps the backend's sentence, and `cicada engine list` prints them all
unchanged). A value Cicada's setup fixes says where it is changed through `SettingsHelpLink`, which opens one public
docs page, `docs/settings-outside-the-app.md` (the fixed engine on Engines, the fixed server on Devices, the usage
ledger's *How to turn it off/on* on Privacy) — the page names the variable, the app never does. Search & files no
longer says a fresh memory "was set up for the larger version on another Mac": `GET /embeddings` sends `recorded`
(null when the bank's index records nothing yet, where `model` is only the configured default — the larger one in a
checkout with no bundled model) and `SearchUnderstanding.meaning` then offers the sharper version
(`meaningNotYet`); a backend without the key reads as before. Search is `SettingsIndex` over `QuickMatch` — the
palette's one ranker — and landing always selects, scrolls, washes (the selected fill and the focus ring) and
announces the row (G139). `SettingsSection` raw values did not move. General's appearance is three live miniatures —
Light · Dark · System (`AppearancePicker`, owner 2026-10-26), each a drawing of the app in that appearance's own palette
(`AppearancePalette`), System the two halves side by side; the chosen tile wears the accent ring, ← / → move the choice;
a pointer's choice cross-fades the window on `CicadaMotion.settle`, a key switches in one frame (`AppearanceMotion`,
DR-60). **System is the default** (`AppearancePreference.defaultChoice`: an absent or unknown value; a stored `light`/`dark`
is an explicit choice, kept on upgrade) and follows the Mac's own light/dark through one app-scope observer
(`ThemeStore.observeSystemAppearance`). The palette's Switch to light/dark actions write the same key. General (F-10:
Look · Startup · When Cicada is closed) holds Appearance and Text size (Scene retired with the painted art, owner
2026-10-16: it picked a painting, and none is left), Open Cicada at
login (`LoginItemService` over `SMAppService.mainApp`; an unsigned build that macOS does not keep says so), Show in
menu bar (per viewer, on by default; hides the 18 × 18 menu-bar bookworm (ruling 18), the Dock icon stays); a login launch opens no
window — the bookworm waits in the menu bar, and the Dock icon brings the window (`LaunchKind` from the 'oapp' event,
`LaunchState`, R-OB18) and Keep memory working when
Cicada is closed (`BackendAgentService`: a read-only `launchctl print`, and Install runs
`scripts/install-backend-agent.sh` from the app's own checkout after the click, `CICADA_CAPTURE=off`, then hands
launchd the port). **Where your memory lives** (G181 phase 3; the first card of Settings → Devices since the settings
audit of 2026-10-22, `docs/research/2026-10-22-hyrum-audit.md`, before that on General;
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
refused before any request (`ServerLinkError.demoStaysLocal`); a reader's
post the server did not take waits in `ReaderOutbox` (`$CICADA_HOME/spool/app/`; a newer post on its route waits
behind it, never overtakes it) and is flushed when the event stream connects, lane by lane (route + memory: another
memory's refused post waits without blocking the active memory's — owner decision 6, 2026-10-16; no answer or a
refused token still stops the flush; `headless.md`, "The Mac app as a client"). **Settings → Devices** (`DevicesSettingsView`,
`DevicesPageModel`; not a Store domain): *Where your memory lives* (above; only while this app runs on a server, the
same card adds which server it is using, reachable or not as of when (DR-58), and captures waiting with *Send now*;
on This Mac the choice already says it, DR-38) — and *Your devices* (name, added, last seen, *this Mac*; Add a device with its
token shown once and Revoke on This Mac only, the server's two commands named on a client). Where memory came from is
one quiet word (`DeviceOrigin`, names from `DeviceDirectory`, read on demand): *from laptop* last on a Saved item's
"Saved from" line (`FeedSourceLine.text(_:device:)`), in the Reader's meta line (`ReaderHeader.meta(_:device:)`) and on
each conversation under *Where this came from*; on a server's client, the server's own writes read *from this server*;
on This Mac, this Mac's own say nothing. The bank picker's menu leads with *on <host>* on a server.
Agents' last card holds *Command-line tool* (G180, ruling 21; on General's Setup card until B11; `CommandLineTool`,
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

**Recordings and videos (meaning index 2, 2026-10-28).** **File → Add Recording or Video…** (2026-10-29) is the
keyboard and VoiceOver twin: the intake's own open panel (`IntakePicker.chooseMedia`, audio and video types, no folders)
hands what was chosen to `IntakeRouter.accept`, so the menu takes the drop's door and its rules. An audio or video file among a drop (by its type; a folder
is never walked for them) leaves the import before the sniff and goes to `MediaFileIndexer` (`IntakeRouter.onMedia`,
after `refusedRoot(of:)`): it transcribes the speech on this Mac and, for a video, keeps one frame per shot, and posts
only those derivatives to `/files` (`storage.md`, "Recordings and videos the person adds"). One toast says it is being
read and one what landed — the Store's existing toast (DR-59 sentence case; no new visual pattern) — including that
the words are the recording's, not the person's, and why a file was kept without its words (speech recognition off, or
no speech model for the language: the toast names Dictation's own setting; Cicada never downloads one). The only
Speech Recognition request is inside the person's own drop; nothing on launch or in the background asks.
`MediaFileIndexer.swift` is the one more file allowed to import AVFoundation (`AVImportLintTests`), every call behind
`Transcribing` / `FrameSampling` seams its tests fake.

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
to Sleep; Needs you (ruling 48 (1), owner 2026-10-28; `NeedsYouSection`, `HomeQuestions`) is two blocks: **Catch me
up** on its own (`CatchupBlock`, `07-home-b`'s separation — the chat glyph, "N questions about M pages, the ones you use
most first · or say "catch me up" to your agent", *Start* a `NeutralButton`), then *Pages with a question*, one row per
page (at most four, the server's `page_use` order), each leading with the page's picture (`EntityPicture`: face, logo
or type glyph — the kind moves to `.help`, DR-48), the question in plain words (`spokenQuestion`), its reason and the page
as an `InlineLink`, "N questions" when the page has more, and the question's age; a row opens that question in the
list (STATE 1), the link opens the page; *All N questions* at the label's right opens the full list (never a fold —
ruling 48 (17)). Drawn from the Store's disk-hydrated snapshot, so Home never waits on `GET /inbox`;
Last read is the newest Sleep commit as a row to that read in Sleep's Past reads ("Today 07:27 · 33 updated", the commit's
instant on the viewer's clock), its pages as `Tag`s in 24 pt hit frames — each number once, never a Consolidate. The
history is not a Store domain: `SleepViewModel` holds it in memory, Home fetches it on arrival and whenever the status's
`lastSleepAt` moves (`refreshForHome`), and a bank switch empties and rereads it (`bankChanged`) — the launch's own
switch to the roster's bank used to drop Home's first fetch, leaving "—" until the Sleep page was opened. Each state is
in words (`HomeFigures.lastRead`): "Looking up the last read…" while it loads; "Nothing read yet" when the status says
no read ran; a failed fetch falls back to the status's last read, or says "Couldn't look up the last read". An empty block is only its label and a note ("Needs you · nothing right now");
all three empty is one `HomeEmptyBlock` (*Choose a file…*), or nothing while Getting started already says so. Every
`InlineLink` hits 28 pt (layout-neutral, `LinkHitShape`). Right after onboarding ends (Open Cicada or *Set up later*),
*Make it yours* (Appearance; `AppearanceTipPolicy`, per viewer; × closes it, its foot links Settings → General) is a row after
Needs you for that one session; once hidden or seen it lives only in Settings.

**Catch me up, the chat (ruling 48 (8), owner 2026-10-28: "not a monotone interrogation").** *Start* opens the chat in
place on Home (`CatchupView`, mock `08-catchup`; held by `HomeSearch.catchup`, so opening a page from it and coming
back resumes it; Home's cell, Esc, × or *Stop for now* leave it; a bank switch ends it). Cicada on the left, the person
on the right (the 2026-10-19 Reader ruling); the eyebrow "Home · Catching up · 3 of 6". `CatchupSession` asks the
askable questions (`HomeQuestions.askable`: not an agent's request, the grouped link review, a shown-never-asked
conflict or a pair with no other side) in the inbox's order, each in its plain words with its reason and its page as a
link. **One tap still answers** (DR-42): the chips are the inbox's own resolutions (`CatchupAnswers.chips` — the
options, *Yes, the same* / *No, different* for a pair, Keep / Archive for a legacy decay, *Not now* = the 7-day defer,
*Skip* sends nothing), held through `InboxViewModel.answer` for the same Undo window, with a "✓ Noted: … · Undo" line
(Undo asks the question again, and removes the tap and its receipt). A tap is drawn on the person's side but is never
their words: it stays out of the record and the model's history (only typed words are `user:`, review B1 of #509). **Their own words** go to `POST /inbox/catchup/turn` (`features.md`): one turn on the
person's chosen engine that answers like a person — a follow-up, the question in other words, or a move to a related
upcoming question (asked in the reply's words, never repeated from the template). **A reading from their words is
never applied on its own** (agent proposes, user disposes — the coordinator's ruling on #509): it shows as a proposal
under the reply, "Note it as “Paused”?" with *Yes* / *Not quite* (`CatchupSession.Confirmation`); *Yes* applies it
through the same hold, carrying the person's located words as the resolve's `quote` (`relayedBy: cicada-catchup`, the
chat's session — kept by the backend as the answer's relay evidence); *Not quite* applies nothing and leaves the
question for them to say again; "another day" is proposed the same way. Their typed words stay in the record as theirs
either way. With no engine the chat says "I can only take taps right now — <why>" and offers their words
as a free answer for one tap where the question takes words. After each thing the person says the chat is posted to
`POST /inbox/catchup/record` (one episode per session; posts never overlap). **The worm is Cicada's face**
(`WormFace`): the menu bar's own 18 × 18 sheet at 32 pt beside the latest Cicada line only — *curious* while asking,
*reading* while the person types, *digesting* while a turn is out, *happy* after a noted answer, *awake* at the end —
the sheet's own clips on the shared sprite clock (ruling 18; no new frames), the menu bar's code-drawn badge left off; a
mood swaps the clip in one frame, never through `withAnimation`, so typing and ⏎ never animate (DR-60), and Reduce
Motion holds the key frame (DR-66). **A page's questions strip** (`PageQuestionsStrip`, first on every entity page's
content): its open questions (either side of a pair, `HomeQuestions.onPage`), one at a time — "A question · 1 of N"
with ‹ › — the plain question, its reason, the one-tap answers through the same hold, and *Open the full question*;
nothing when the page has none. **The full list** (`InboxPage`) is unchanged but for the path eyebrow, Esc back to
Home (in one frame, `AppRouter.pendingTabByKey`, DR-60), and no folds anywhere on it (ruling 48 (17), DR-81): its kind
groups are always open, a section label with the kind's glyph, plural and count (`InboxGroups.isOpen`); *Settled by a
check* and *Settled by Sleep* show their first three, open, with *All N* opening the whole group in a sheet
(`FullListSheet`); *Confirm N links* shows its first pages and *All N pages* opens every page in the same sheet. A new
day refreshes the inbox (`.NSCalendarDayChanged`), whose ETag moves with the date, so a reason's age is never
yesterday's. Copy that named the Inbox tab or ⌘6 now says Home or "your questions". DR ids: DR-22, DR-40, DR-42, DR-48, DR-60, DR-66, DR-81.

**Onboarding v2 (G92, G217, ruling 36; 2026-10-22; replaces G145's seven pages).** Six steps of one verb each in
one full-window layer, raised by `FirstRunGate` (unknown is never empty; never over the demo) or by the one door,
`OnboardingState.reset` + `AppRouter.requestFirstRun` (Settings → General's *Run setup again*, the demo's *Finish setting
up*): **Welcome · Intelligence · Agents · Sources · Meet your bookworm · Done** (`OnboardingPage`; the worm's step since
2026-10-23, below). Welcome (and, until v3, Done — now the menu-bar worm over its card) is the study room over a
card (`OnboardingRoom`, the one illustration, DR-13; the worm's mood per step); the three working steps are the split
frame — the room in its `bgPane` pane, the column with "Step n of 6 · k still coming in", *Set up later*, and a foot of
Back, a visible **Skip** and the one primary Continue (⏎ never animates). What each step shows is pure data in
`Support/OnboardingSteps.swift` (`OnboardingStepsTests`), each step's fixed words under 40.
*Welcome*: the greeting (saved name, else the Mac account's, *Not you?* corrects it), one sentence, Continue — the owner
PUT alone and first (G117 R1; a file dropped here waits for it) — *Try the demo* and *Set up later*.
*Intelligence* (`IntelligenceStep`, ruling 36 D1): `IntelligenceStepState` — a signed-in plan (Auto resolving to it, or
chosen) is pre-selected, the plan said once ("Using your Claude plan" / "Cicada runs your own Claude Code.", ruling 39,
2026-10-24 — Settings' own headline keeps "— you're signed in."), *Use an API key* opens Settings → Intelligence's own `IntelligenceRow`s for four keys (`featuredKeys`;
paste → Verify, the 422/503 sentences) with "More keys in Settings → Intelligence"; with nothing that can read, the plans
and those keys show side by side. A local model is never offered. The step writes only from a row's click (Sign in,
Verify, *Use* through `IntelligenceView.write(using:)`); Continue and Skip change nothing.
*Agents* (`AgentsStep`, fix round 2026-10-22): one row per provider umbrella (`ProviderDirectory`, `GET /providers`,
as the Agents page lists them) holding the products of it found on this machine (`AgentStepRows.rows`: `/agents/wiring`
says installed, Claude Desktop is present, or `/agents/live` saw it; `umbrellas` groups them) — Anthropic: Claude Code ·
Claude Desktop; OpenAI: Codex. The umbrella's own mark in a `LogoTile`, never a product badge (a product no umbrella claims
wears its vendor's mark, `umbrellaLogo`); a dot and one word (Not connected → Waiting → Connected, green when any product
first calls, polled every 3 s; the Agents page's vocabulary, never "Found"). One *Connect* opens each found product's own
action, Settings' paths: Connect for me plus
Remembers automatically (R-OB12) through `AgentConnect.run` with the wiring answer's binaries — "Cicada runs exactly these
commands…" and *Run these*, the commands behind a collapsed *Show commands* (spec decision 14); *Set up Claude Desktop*'s merge;
*Open in Cursor*; else *Copy setup prompt*. A plugin-wired Claude Code is offered nothing to run. Below: *Another agent*
(the generic prompt) and *Personal agents* → *Add an agent token* (G213, `AddAgentTokenSheet`).
*Sources* (`SourcesStep`): `SourceTiles` — a grid of `SourceLogoTile`s: Calendar, Contacts and each supported browser
tick through the one turn-on (`SetupRunner.start`, `FoundTurnOn`; untick stops keeping up), Messages, YouTube, X and
Instagram open the Sources page's own `SourceCatalogDetail` over onboarding (its consents, chat picker and per-site switch);
each tick tile shows what it reads and the consent it leads to before the click (`SourceTiles.caption`: the catalog's own
idle line or a browser's reads, "Needs Full Disk Access" for a browser macOS hides),
chat history takes a drop or the file panel, *How to get an export* opens `ExportWalkthroughSheet`. Nothing is pre-ticked
or read before a tick (R-OB6, R-IB12).
*Saved lists* (`SavedListsStep`, owner 2026-10-26, ruling 39's dated line; step 5 of 7, stored `savedLists`): every
list the person's own agent can keep current from their signed-in browser (`SavedListItem`: YouTube Watch later and
history, X Bookmarks, Instagram Saved, LinkedIn Saved posts), each with its platform's mark, **pre-ticked** — except one
the reading settings record as turned off (`youtubeListsOff` / `savedListsOff`) — under "Keep your saved lists
current" and one line: their own agent, their signed-in browser, at most 10 times a day, and that the sites' terms
discourage automated access. The foot's primary reads *Keep them current* (*Continue* with nothing ticked) and is the
consent: one `PUT /reading/settings` (`SavedListsStepModel.write`) with the ticked lists on, `agentEnabled` and
`acknowledge` when anything is ticked, every unticked list `false` (recorded off, so no later default turns it on);
a failure stays on the step with its sentence. Skip writes nothing. Nothing is read before the button; the first read
starts when the person's agent next opens a session (the SessionStart note counts the due lists, and
`cicada_reading_queue` lists them; verified on scratch state, 2026-10-26). The one departure from "nothing is
pre-ticked", dated in DESIGN_RULES §9. *Meet your bookworm*'s Back returns here.
*Meet your bookworm* (`MenuBarStep`, owner 2026-10-23: "have the little worm with the number appear only after
explaining it"): after Sources, because what Sources brings in is what the number counts, and right before Done, so the
worm lands in the menu bar as setup closes. No room on this step: the menu bar's own 18 × 18 sprite with its code-drawn
badge (`BookwormView(artSet: .small)`, 8 pt per art pixel, nearest-neighbour) stands where the room stands, over a ringed
card — "Meet your bookworm" / "It lives in your menu bar." / "Its number is how many conversations are waiting to become
memory." / "When Cicada sleeps, it reads them and the number goes down." — with Back, Skip and Continue (⏎). The number is
the badge's own source, `StatusSnapshot.waitingForSleep`; the worm counts up to it when some already wait ("3 waiting
now"), else to an example of 12 ("For example"), holds, shows Sleep's five stage dots and starts again
(`MenuBarStepModel`, timings `CicadaMotion.wormCount…`, the sprite's own frames on their sheet timings, ruling 18). Reduce
Motion holds it on its number. Since v3 the worm speaks for itself ("I'll live in your menu bar." / "My number counts
conversations waiting to become memory." / "When I sleep, I read them and it goes down."); on a rerun, with the real
item already up, it says "That's me, up in your menu bar." and the real menu-bar worm says hello while the step talks
about it (`MenuBarManager.greet`: the happy sheet's frames after its key frame, on their own sheet timings (ruling 18),
under the real state's overlay so a waiting worm keeps its number; never hidden, mid-flight or under Reduce Motion,
`MenuBarGreeting`). A first run's worm says the same hello on landing. **The menu-bar item waits for this step** (`MenuBarIntro`, `cicada.menuBar.intro`:
`waiting` | `done`, an absent key reads `done`): it is written `waiting` only at the launch of a fresh install (no
`cicada.` key in the app's defaults — decided by `CicadaApp`'s first stored property, before any other writes one), so
every earlier install keeps its worm and *Show in menu bar* (`cicada.menuBar.visible`) is untouched; the item shows when
the switch is on and the intro is not waiting. Since v3 (below) the flight is Done's closing beat: Open Cicada by
pointer flies the worm into the menu bar (`MenuBarFlight`: a
transient borderless non-activating `NSPanel` at `.mainMenu + 3`, born over Done's worm and animated by AppKit to the
status item's button frame in `wormFlightDuration`, a layer with nearest-neighbour filters, ordered out once the real
item shows under it — a window cannot draw over the menu bar from inside its content); Reduce Motion fades the item in;
⏎, *Set up later*, the demo and every other way out show it with no flight (`OnboardingExit`, and `ContentView` on
onboarding closing), and a first-run gate that settles with no onboarding coming lets it in at once. A status item macOS
keeps off screen (a full menu bar) is shown without a flight. Continue, ⏎ and Skip on *Meet your bookworm* only move on
to Done.
*Done* (`DonePage`, v3): the menu-bar worm over the card (6 pt per art pixel, the badge's own number), "That's it. I'll
take it from here." (the flow's one wink), then what is already in this memory (`DoneReveal`: the first three pages —
never the owner's seeded page, a facet or a hub — then conversations waiting to be read, each with its origin's mark,
"and N more"; "Nothing yet." alone when empty; "Reading now" while a read runs, its pages landing through the Store's
live graph), `DoneLine` in the worm's voice — "Talk to your agent; I'll remember." plus the schedule's own time when a
schedule can read (a new memory reads nightly, `features.md`) and "and now for what you brought in" when something came
in during setup and an engine can read it, else "Read now on Home builds your first pages." — one `MemoryQuotes` line
(G153, now caption-sized), Open Cicada (the worm flies up; the one read after an import when something came in — the
owner's "+ once after an import", the only read onboarding ever starts, Done itself starts none; mark the bank, record
connected agents, offer the tour, Home). **Persisted values (Hyrum mode B):** `cicada.hasOnboarded.<bank>` unchanged; new `cicada.onboarding.step.<bank>`
holds the step reached as a word, so a person who quits mid-way resumes there once their name is saved; finishing,
*Set up later* and *Run setup again* clear it; `OnboardingPage(stored:)` maps the seven-step names (`import` → Sources,
`whoReads` → Intelligence, `skills` → Sources, `keepRunning`/`ready` → Done; the worm's step stores `menuBar`). The old Skills step (`POST
/skills/onboarding`) and Keep it running are gone from onboarding: skills install from the Skills page, and the login-item
and menu-bar switches stay in Settings → General (Keep it running turned none on). The first-run empty states (Graph,
Inbox, Home's all-empty block) lead with one SF Symbol (DR-50 amendment, 2026-10-22). Getting started continues on Home,
and once `OnboardingState.isOnboarded` it never asks again what onboarding covered (`GettingStartedFold`): rows already on
or coming in fold into one line ("N things already set up"), only open rows stay, and the past-chats and *Also on this
Mac* offers go. Settings → Intelligence's In use row says in one line when ruling 36 D1's one-time step kept a local model
as the person's choice (`autoLocalKeptOn`).

**Onboarding v3 (2026-10-24, after HeyClicky's onboarding; DR-5, DR-13, DR-39, DR-59, DR-60, DR-61, DR-66; §9).**
Same six steps, ids and stored names (Hyrum: no saved step is reset). (1) **Permissions as a designed flow.**
`PermissionDragHelper` is the Full Disk Access door for Messages and Safari: `FullDiskAccessHint` (Messages' row and
panel, a browser's row, the import panels) and a hidden browser's tick (`FoundTurnOn` → `FoundTurnOnDeps
.askFullDiskAccess`, so onboarding's Sources tile and Home's Getting started too) open it instead of System Settings.
The ask card's line follows `PermissionAsk`: *drag* ("Drag me into the … list.") until Cicada has been seen in that list
(`PermissionMemory`, `cicada.permission.seen.<kind>`, written on a preflight yes), then *flip* ("I'm already in the …
list. Flip my toggle on."); back from System Settings with no grant (`didBecomeActive` → `returned()`), Accessibility
moves to *flip* and Screen Recording / Full Disk Access to *reopen* ("Already on? Reopen Cicada to apply it.", their
preflight can stay false until a fresh process) with *Reopen Cicada*; once Settings is open those two also offer
"Already on? Reopen Cicada" as a quiet text button. *Reopen Cicada* writes `PermissionResume`
(`cicada.permission.resume`: kind, place, time; read once, dropped after ten minutes) and relaunches through
`LiveAppRelauncher` (a shell that waits for this pid, then `open`s the bundle). The next launch comes back to the same
step: onboarding's marker resumes Sources and ticks the browser again — a rerun's tick records the rerun
(`.onboardingRerun`), and since a rerun's bank keeps its pages the first-run gate would not raise onboarding, so the
shell reopens it in the marker's mode (`PermissionResume.reopensOnboarding`, also for a first run whose memory already
has pages) and onboarding takes the marker whatever its mode — Traces' opens Sources → Traces, any other opens
Sources, and the helper looks again by preflight. A host row's button is `PermissionAllowButton`: its title, an *Open*
link once × closed the helper (`PermissionRowState.retry`), nothing once granted. Calendar and Contacts keep macOS's
prompt; refused (`.denied`), their tile says "Turned off in macOS. Click to open the setting" and opens the exact list
(`SourceTileGroups.deniedSettingsURL`). Reminders, Chrome's Automation and Notes are untouched. Every look is a preflight;
the live Full Disk Access look opens Safari's bookmarks or Messages' database (`opensProtectedFile`). (2) **A live first
call on Agents:** "Then try it:" and a chip "Ask <the person's own agent, else your agent>: what do you remember about
me?" with a copy button (copies the question); `AgentLiveProbe` keeps the first answer's `lastCalledAt` per agent as
a baseline — a tool call, never `lastSeenAt`, which Cicada's own wiring check (`claude mcp get` initializes as Claude
Code) and a session merely starting both move — and the first agent whose call is later is `firstCall`
(`FirstAgentCall`), and the chip gives way to
"<Agent> just called me. It works." with a check (card fade; a plain fade under Reduce Motion). Continue stays enabled.
(3) Done ends on the person's memory (above). (4) The real menu-bar worm reacts (above). (5) **Fewer words:** titles ≤ 7
words and bodies ≤ 25 (`OnboardingWords`, measured on each step's longest variant), the worm in a light first person,
one wink (Done's title), no "!" or capitals; *Another agent* and *Personal agents* fold under *Other agents*
(`cicada.onboarding.otherAgents`), and Messages, YouTube, X and Instagram under *More sources*
(`cicada.onboarding.moreSources`, open by itself when one inside is on) — DR-39. (6) **Sound, soft and rare** (owner 2026-10-24, DESIGN_RULES §9): `OnboardingSound`, one per onboarding run, held by `OnboardingView`, plays macOS's own *Tink* when a permission lands — the drag helper's grant (`FoundTurnOnDeps.live`'s `onPermissionGranted`, passed only by onboarding), a preflight that turns an asked-for row ready (`startGranted`), or the relaunch's fresh look (`resumePermissionTick`) — and *Pop* when the Agents step's `firstCall` lands. Each moment at most once, spent the first time even when silent; at the alert volume (`com.apple.sound.beep.volume`) through `NSSound(named:)`; never with "Play user interface sound effects" off (`com.apple.sound.uiaudio.enabled`), a muted default output (Core Audio's mute, or its volume at zero) or a zero alert volume; never under XCTest, in a demo bank or in a verify-cicada copy (bundle id `com.rorosaga.cicada.verify.*`). Both moments come from outside Cicada, so no key or click in it makes a sound. Nothing else in the app plays one (`OnboardingSoundTests`' source lint).

**Tester readiness (2026-10-26, branch `fix/tester-readiness`; the readiness assessment's blockers 2–3 and two
should-fixes).** (1) **A list only an agent reads is never "Connected" without one.** `SourceCatalog.status` takes
`localAgent` — an agent on this Mac connected through stdio or its config (`AgentLiveRow.connectedLocally`: `via`
`mcp` or `config`, never only `remote`; the reading tools are stdio only), from `GET /agents/live`, polled by the
Sources page while it shows (`AgentLiveProbe`, ids and times only). An allowed walled site, a saved list kept current
(X, Instagram, LinkedIn) and YouTube's Watch later / history read **Connected** only with one; turned on with none they
read **On · waits for your agent** (`SourceCatalogStatus.waitingForAgent`, a grey dot — nothing is broken, nothing is
read), the detail says why under the word, no last-sync line shows, and the header ("Sources · N connected") does not
count them. Onboarding's Sources tiles use the same rule, and the saved-lists step says "No agent is connected yet…"
when none is. (2) **Report a problem…** (Help menu, and Settings → General beside Version): `ReportProblemSheet` shows the
whole report before anything leaves the Mac — the app's version and build and the macOS version on top
(`ProblemReport.header`), then the backend's half from `GET /diagnostics/report` (`api/services/diagnostics.py`: backend
version, platform, engine mode as an enum — never an account or email, G148 — connected source ids, the bank count,
recent warnings and errors, and the tail of `backend*.log` and the app's `update.log`, every line through one `Redactor`:
the bank's own page ids, names, aliases and waiting names withheld as tokens, then URLs, emails, file names, homes,
quoted text, slugs and the rest, and a line where anything risky survives withheld down to its structure — `api.md`); the header also carries the one known issue (an update
can make macOS ask again for permissions, while releases are ad-hoc signed). **Copy**, **Save…**, and — only in a
release whose Info.plist carries `CicadaReportEmail` (from CI's `CICADA_REPORT_EMAIL` variable, owner 2026-10-26; never
an address in the repo, docs/RELEASING.md) — one **Send** that copies the report and opens a new email with a short
template. Without the address (developer builds, or before it is set) there is no Send: the sheet says "Send this to
the person who gave you Cicada" — never a public issue page. Nothing is sent by itself. (3) **The Mac account's
name is a suggestion.** With no saved name, Welcome opens on the name field prefilled with it under "From this Mac's
account. Is that what you go by?" (`WelcomeName.suggestion`); Continue or ⏎ confirms it, an edit replaces it, and Set up
later saves no name for an untouched suggestion (`WelcomeName.unconfirmed` → `OnboardingFlow.laterSteps(name: nil)`), so
the bank keeps `owner_identity`'s "Owner" placeholder (G169's self-references still land on it) until a name is given.
(4) **The prerequisite, said once in each place:** the Agents step, the README's install section and
`install-release.sh`'s first line name Claude Code or Codex signed in to a paid plan (or an API key in Settings).

**Engine choice in onboarding: Auto first (settings defaults pass 2, owner 2026-10-22; ruling 31).** Until D6 Settings drew
`EngineChooser(foldsOtherEngines: true)` (the engine card): the card opens on `EngineHeadline` — *Auto* and what it uses now from
`preview.manual` ("Using your Claude plan — you're signed in.", the ChatGPT plan, the model on this Mac, or "Nothing to
read with yet" with a Plans & keys link), the rule in one line (the Claude plan, then the ChatGPT plan, then Cursor, then OpenCode — ruling 36 D1 removed the local rung, ruling 46 added the two tools — never a key
nobody chose), or, for a stored choice that isn't Auto, that card's name, its cost model and state, and *Back to Auto*
(`EngineWrite(mode: "auto", model: nil)`; hidden while the environment fixes the engine). Every other card waits
under *Use a different engine* (`DisclosureGroup`, DR-39, per viewer `cicada.engines.othersOpen`; landing on
`.engineChoice` opens it). The extra-usage switch, `LeavesMacNote`, the chosen card's one step and both previews stay
outside the fold. Engines and Plans & keys were kept two
sections in pass 2 because sign-in, sign-out and key removal would sit below an open chooser; B1 merged them once the
chooser folds: with *Use a different engine* closed, the Plans & keys group starts on the panel's first screen at 1×. Auto that
resolved to no engine says nothing leaves the Mac (`LeavesMacNote` returned the key's sentence before).
**The engine picker (G122, Track E; moved by G139 A3).** The Engine card ends with one *Ask* row,
"Answers your questions with the same engine as a cycle you start" (its own card until the 2026-10-22 settings audit,
DR-37/DR-38). A row of cards with real marks — Auto,
Claude plan, ChatGPT plan, OpenRouter, Ollama (tagged *Local*), API key — over the connections registry's candidates writes
`PUT /sleep/engine`, which lands in the same bank-independent `~/.cicada/connections.json` prefs
`use_for_sleep` already uses, never `api/.env`. A plan card is selectable once that plan is signed
in. **Auto is the default (ruling 31, 2026-10-19):** an untouched install selects the Auto card, whose caption says it
reads with the Claude plan, else the ChatGPT plan (never a local model since ruling 36 D1; a person who read through one under Auto was kept on it as an explicit choice, once, recorded) — never an API key unless the person chooses it; with
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

**the Sources page (G126).** A categorized, logo-first page over the existing
`GET /sources/channels` registry — no new adapters, just a frame. The rule this page draws: a
*standing* connection (sign in once, polled on the Sleep tail, disconnect here) lives in
Integrations; a *one-shot* import (drop an export, sync a folder once) stays where it already was,
behind the `+` on the Sleep page's tab row (the Feed's, until 2026-10-16). Both read the same `channel_registry`, so a channel never drifts between the
two surfaces. Round 3 added **Notes & files** (Apple Notes and, when Obsidian is installed, *Obsidian vault*; the
watched folders and *Add a folder* moved to Settings → Privacy & data on 2026-10-14, and Notes & files keeps one
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

**Activity traces (G218, ruling 38, 2026-10-23).** Sources → This Mac → **Traces** (`SourceCatalog.tracesId`, after
the chat sources — Messages, WhatsApp — the `timeline.selection` symbol): Connected only while the recorder records — paused, off, a server connection
and a failed read all read **Off** (ruling 36's three words), each with its own line in the controls ("Paused until
3:40 PM.", "This Mac only…"). Off, the detail says what traces are and offers **Turn on…**, which opens
`TracesConsentSheet`: what is recorded, where (this Mac only, encrypted, outside memory and its history, never sent),
how long (timeline 30 days, screenshots and their text 7), what goes into memory (what you watch and read on any site;
a day summary Sleep learns from only when asked), how to wipe, and the honest limit ("anything running as you on this Mac can read what you can"); *Turn on*
posts the consent (`TraceRecorder.turnOn`), then two skippable steps — Accessibility (window titles) and Screen
Recording (screenshots) — each through **`PermissionDragHelper(kind:)`**, the one reusable permission component
(kinds `screenRecording`, `accessibility`, `fullDiskAccess` — the last for Messages and Safari, wired by onboarding v3
below): a
small non-activating floating panel with one line ("I need screen recording. Drag me into the Screen Recording list.")
and *Open*, which deep-links `x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture` /
`?Privacy_Accessibility` / `?Privacy_AllFiles`; a second card placed over System Settings (by its window bounds only)
holding the app's icon and name as a draggable tile (the bundle URL as a file, the way Finder drags an app) and a
near-miss hint ("Drag into 'Screen & System Audio Recording', not the audio-only list."); it polls the preflight only
(`TracePermissionProbe` → `CGPreflightScreenCaptureAccess` / `AXIsProcessTrusted`, every `CicadaTiming.permissionPoll`,
1 s) and closes itself and ticks the step on a grant — **no prompting API is ever called**. On, `TracesControls` holds
the state line, Pause (1 hour · until tomorrow · until I resume) / Resume, *Forget the last 15 minutes*, *Wipe all
traces…* (a destructive confirmation that says the key goes and memory keeps what was already added), the switches
(screenshots, window titles — what joins memory moved to the Traces page itself on 2026-10-28), retention steppers that only shorten, the never-recorded apps (pick a running app
or type an identifier; never prefilled) and sites (typed), the browsers whose address may be read (only names with an
installed bundle id; turning one on is the one moment Cicada asks for Automation, `LiveTraceBrowserTabs.ask`, off the
main thread — "Open Chrome, then ask again" when it is not running), titles allowed per chat app, and the days kept,
size on disk and where the key is. *Browse traces…* opens `TracesTimelineView` (`TracesBrowserModel`): a day's spans
and a search over titles, sites and screenshot text; screenshots and their text (search snippets included) only after
**Touch ID or the login password** (`TraceAuthenticator`, LocalAuthentication), held in memory only and cleared on close
or after `CicadaTiming.traceScreenshotsShown` (5 min). The menu bar shows "Recording traces" and Pause traces ▸ /
Resume traces / Forget the last 15 minutes while traces are on (`MenuBarManager` `TraceMenuState`, read as the menu
opens; no dot on the sprite, which would collide with the count badge). The recorder (`TraceRecorder`, environment,
`start()` on launch) is described in `capture-and-sleep.md`, "Activity traces"; the store in `storage.md`.

**The Traces page (owner 2026-10-26, G218).** Once traces are on or were ever on (`TracesPageVisibility`: enabled,
consent given, or a day kept — the recorder's answer, mirrored per viewer into `cicada.traces.pageShown` so the rail
knows at launch; a server connection or a Wipe takes it away), **Traces** is a rail page (`AppTab.traces`, appended
tenth with no ⌘ digit — DR-22, ⌘0 is Actual Size) and ⌘K offers *Go to Traces*. `TracesPage`: the eyebrow (Traces ·
the state line) with *Settings…* (`TracesSettingsSheet`: `TracesControls` without *Browse*) and *Wipe all traces…*; one
line, "Everything here stays on this Mac, encrypted; screenshots N days, timeline N days" from the person's own
retention.

**Redesigned 2026-10-28 (mock 11; the owner's answers, Q12).** No drop-downs on the page (owner): an empty section is
hidden and a long list is capped with "All N" (`TracesPageLogic.capped`). In order:
*Into memory* — **Learn from my day** (off by default; the help says what Sleep reads and never reads, and "the engine
you chose for Sleep", provider-neutral) and **What you watch and read** (any site, on); while recording under consent
sheet 1 with screenshots on, one line offers the newer sheet ("Screenshots can now cover every screen you have
connected." · *Review…*, which reopens `TracesConsentSheet`). *Yesterday, as Sleep would read it* — trailing
"Counted on this Mac · nothing sent": the exact counted digest (`GET /sources/traces/preview`) as rows — Your projects
(one row per project), Reading, Watching, Calls, Everything else — each with a neutral-ink bar (DR-7: one hue, data),
its words and minutes, and the attribution rule in one line under it; a part under a minute is not shown, and the
section is hidden on a day with nothing counted. *What traces added* (only when there is something, or a removal can be
undone) — "N beliefs and M progress notes, since <day>", *Show* (the claims, capped at 5 + All N) and *Remove from
memory…* behind a confirmation in words; after it, "Removed N from memory." and *Undo* (`TracesMemoryModel`). *Days*
(`TracesDaysView`, on `TracesBrowserModel`) — one card per kept day ("kind of like BeReal"): the screenshot that stands
for it, shown only after Touch ID like every screenshot (a lock until then), the day's words, a two-screens glyph when
more than one screen was connected, and "2 h 17 m · 3 apps"; *Show screenshots* and the search in the header. A card
opens the day: *All days*, the day's name, "2 screens connected", *Delete day…* (confirmation in words: what already
joined memory stays); its screenshots grouped by moment ("Screen 1 of 2"), each with a delete button; Apps and Sites
with time (8 + All N); the Timeline, every span with a delete button (it takes the screenshots of that span with it).
Leaving the page drops every screenshot like closing the sheet did. DR-4, DR-7, DR-22, DR-25, DR-40, DR-50, DR-58,
DR-60; depth is a ring. Screenshots of the scratch-app verification are in the traces-v2 report. Sources' Traces detail becomes one line and *Open Traces*
(`TracesSourcesLink`) once the page exists; before traces were first turned on it keeps the switch (`TracesControls`).
A hidden Traces page lands on Sources (`AppTab.landing`).

**Messages (G179, 2026-10-15).** Its panel's **Read again** (2026-10-20, shown while a chat is ticked) re-reads every
ticked chat from its first message so sittings saved before reactions, replies, edits and attachments were kept get
them (`MessagesWatcher.readAgain`; capture-and-sleep.md). Integrations → Messaging carries an app-owned **Messages** row (`MessagesRow`: the
Messages app's own icon, "Pick the conversations Cicada should remember" / "Remembering N conversations", *Sync now*
once one is ticked, *Choose…*, the browsers' `FullDiskAccessHint` when the read was refused, and *What came in*). *Choose…*
is a `SettingsSheet` (`MessagesPanel`): one sentence on what Cicada reads and why it needs Full Disk Access, one on
who is who, then each one-to-one conversation (`MessagesConversationRow`) — the contact's Contacts photo (else a
person's monogram, `EntityPictureFallback`), name (the contact's when Contacts is allowed, else the chat's own, else
the handle — shown in the app only, never sent), last activity and message count, a pill for who it is with ("AI
agent", "AI agent · suggested", "A person" — the person's own mark, `marked`, wins; "· suggested" only for a
detector's own answer; the free-form `actor` block keeps the backend's `decided_by`, which the app reads in either
spelling), *Is <name> an AI agent?* with Yes/No when the detectors are unsure, a menu
(This is an AI agent · This is a person · Let Cicada suggest) and the tick. **A group chat** (2026-10-28) is the
same row (DR-48, DR-34: no new pattern): its title is the chat's own name, else its members' Contacts names ("Alice,
Bob and 2 more"), else "Group of N" (`Copy.Messages.groupTitle`), the one pill `Tag` reads "Group" (DR-44) with the
who-is-who line as its help, and it has no *Who is this?* menu or question — a member keeps the mark of their own
one-to-one chat. Its members' handles stay in the app (`MessagesConversation.members`), looked up in Contacts only
when Contacts is already allowed; a pass posts each member as `MessagesReader.memberKey` with their Contacts name.
Since 2026-10-28 (one person across sources) the look-up also keeps the card's `identifier` when exactly ONE card
holds the handle (`MessagesContactCard.id`), and a pass posts it — `members[].contact`, or `conversation.contact` for
a one-to-one chat — never the handle.
`MessagesWatcher` (environment, started
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

**WhatsApp (G179, 2026-10-28).** Integrations → Messaging and the Sources detail carry an app-owned **WhatsApp** row
(`WhatsAppSourceRow`), drawn exactly as Messages' (DR-38 head not repeated under a detail, DR-40 `NeutralButton`s
*Refresh* and *Choose…*, `FullDiskAccessHint` on a refused read, *What came in*). *Choose…* is a `SettingsSheet`
(`WhatsAppPanel`, R-HS16): one sentence on what is read and when, then each chat (`ChatTickRow`) — the Contacts photo
for a one-to-one chat's number (else a monogram), the name (Contacts, else WhatsApp's own; the number only in the app),
a *Group* `Tag` (DR-44), last activity, *Read history* once ticked (a small `.bordered` button, as Messages' *Read
again*; "History read" after) and the tick. No new visual pattern. `WhatsAppWatcher` (environment, started on launch,
`bankChanged` on a switch) owns the list, the per-memory `Z_PK` cursors (`cicada.whatsapp.cursor.<bank>.<id>`), the
FSEvents watch on the group container and every read off the main actor; `WhatsAppReader` is the one SQL reader.

**Telegram chats (ruling 47a, 2026-10-28).** The same row and sheet (`TelegramSourceRow`, `TelegramPanel`;
`TelegramChats` holds the state, the backend the client). Not connected: the backend's consent sentence word for word,
then the steps in native rounded fields (DR-76: setup sheets keep the native field) — phone number → the code Telegram
sends → the two-step password when the account has one. Connected: the one-to-one chats only (no group, no channel),
each with *Read history* and the tick; ticking opens a system alert (*Did they agree?*) carrying the backend's
per-chat sentence with the chat's name — *They agreed* ticks, Cancel doesn't — and unticking withdraws it; *Disconnect*
ends the session at Telegram.

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

**Ask why, v7 — the notch, second version (2026-10-23, branch `feat/save-notch-v2`; owner, paraphrased: the field
should grow smoothly for the first few lines and then scroll; more reasons that appear smoothly, chosen from a bank by
what is being saved).** *The field grows.* `TextField(axis: .vertical)` starts at one line and grows a line at a time as
the words wrap or break (⌥⏎, the Mac's line break in a field; Return still saves) up to **five lines**
(`SaveWhyField.maxLines`), then scrolls inside. Five because the words cap at 500 characters and a line holds about 60,
so five show ≈ 300 — most answers whole — while the card stays a short drop from the notch. The height is measured, not
left to AppKit (`SaveWhyField.lineCount`: the text's own breaks plus wrapping at the field's measured width, in the
field's font), so the card and the notch's shape grow with it in one transaction: `CicadaMotion.fieldGrow` (0.12 s,
`CicadaCurve.out`), in one frame under Reduce Motion. DR-60 lists keyboard *commands*; a field growing to hold typed words
is the content's own size, which the owner asked to be smooth — dated ruling in DESIGN_RULES (2026-10-23). The window is
made `SaveWhyField.growthReserve` taller than the card up front (clear below it, the view top-aligned), so it never resizes
while the person writes; a click that reaches that clear band leaves, as a click anywhere else does, and never takes the
keyboard (`SaveWhyNSPanel.isBelowCard`, the card's height reported by the view). The words are stored as before — whitespace folded to single spaces by the panel and the
backend. Fixed in passing: the field now shows the panel's own words (an answer filled in on a saved page arrives after
the panel shows; before, its chips filled in and its words never did). *More reasons, by what is saved.* The four stay
the fixed first row (`SavedWhyOptions.basic`, unchanged keys, labels and order — nothing a person relies on moves). The
backend's options add `more`, a bank of 38 short reasons (`saved_why.MORE`: Found it funny · Asset for a video · For a
moodboard · Inspiration · The aesthetic · A product idea · A tool to try · To buy · A gift idea · A reference · A recipe
to try · To watch later · To listen to · To learn from · A how-to · Research · The typography · A UI pattern · The colours
· The photo · The art · The music · A quote I liked · An idea to explore · To share · News to follow · Someone to follow ·
For work · A place to go · Travel idea · Outfit idea · For the home · A workout · Code to reuse · Good writing ·
Interesting data · An event to go to · Good advice). Once the panel's link is known — at once for a diff- or
backend-opened panel, when the file names it for Chrome's pending bubble panel, after `adopt` for a saved page —
`SaveWhyCenter.considerSuggestions` ranks the bank (`SaveWhySuggest.rank`, pure) and three to six fade in under the fixed
row as the same toggles (`SaveWhySuggestedChips`; the card makes room on `CicadaMotion.suggestGrow`, the chips fade on
`suggestFade`; only the fade under Reduce Motion). **No generative model at save time:** the score is a sum of four
local signals — the site (`sitePriors`, the registrable domain or a host ending in a listed one: youtube.com → To watch
later, Asset for a video; pinterest.com → For a moodboard, The aesthetic; github.com → A tool to try, Code to reuse …,
weight 3), the link's own words (title and path, never the query; `wordPriors`, weight 2), the person's own past picks
(every answer in the active memory's Store sources, `SaveWhySuggest.picks`: 1.5 per pick on the same site up to 3, 0.4
per pick anywhere up to 5 — nothing new is stored for it) and, only when the backend has EmbeddingGemma installed and
answers `POST /sources/saved-why/suggest` within `SaveWhyPolicy.suggestBudget` (0.35 s), its cosine similarity scaled to
0–2 (`api.md`); otherwise that term is absent. Ties keep the bank's order; with no signal the three generic ones stand
(Inspiration · A reference · An idea to explore). A reason already chosen (an edited answer's) is shown first, so
nothing selected is hidden. Ranked once per link — a late model answer or a repeated bind never reorders chips on screen
— and a tap on a suggestion within `armDelay` of it appearing is ignored, as the panel's own first half second is. A
chosen suggestion is posted exactly as a reason always was (`SavedWhyAnswer.reasons`, the key; the backend writes its
label). An older backend sends no `more`, and the panel then suggests nothing (it would refuse an unknown key). Tested in
`SaveWhySuggestTests` (growth cap, fixed row, ranking by site / words / past picks / model / no model, the stored shape,
the budget, no download path in the panel's sources); the backend in `test_saved_why.py`. Shots (render harness — the real
panel needs a Chrome bookmark): `~/cicada-redesign-2026-10-22/shots/save-notch/`. Detecting saves in other apps is G221.

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
shown before the click), and the Agents page → *Remembers automatically* keeps its own click), *the capture
flush* (G110 gate A: `autosaveFlush` = `on|off|stale|invalid|n/a` for the capture command under `PreCompact` and
`SessionEnd`, with `flushOn` argv kept apart from `connect` — the setup prompt runs exactly `connect` and four commands
do not fit it; `autosave` stays the Stop hook alone, so an install from before the flush still reads on; the app
appends `flushOn` only to a Connect it is already running, `AgentWiring.turnOnSteps`, and install.sh registers it),
plus the exact argv install.sh would run. The **app** runs them, only after the person's click (spec decision 14, D-1), with
`CICADA_CAPTURE=off` and `CICADA_RECALL=off`, behind an allowlist pinned to its own checkout (which also accepts the recall hook's two
events, the capture command under `Stop`, `PreCompact` and `SessionEnd` only — Codex's SessionEnd with exactly
`--timeout 3` — `registry.py uninstall --hook recall`, and, 2026-10-23, `registry.py agents-md-install` on
`~/.codex/AGENTS.md` only, Codex's `agents-md` step in `connect`); the backend never writes a harness root. **Claude Code through the Cicada plugin**
(owner 2026-10-19; `mcp.md`, "The Claude Code plugin"): when the plugin is enabled, installed and able to run a Cicada
(`registry.plugin_state` is `on`), Claude Code's row reads `recall`, `autosave` and `autosaveFlush` `on` and
`autorecall` as the plugin's own `recall` setting, with `capabilities.via = "plugin"` and no argv at all (the plugin
carries the server and every hook; an `mcp add` or a settings hook beside it would run twice), and `detail` names any
Cicada hook still in the settings file; an enabled plugin that would run nothing leaves the row probed as before, with
why in `detail`. `AgentWiring.viaPlugin` makes *Remembers automatically* say it is switched in the plugin's settings
(`Copy.autoRecallPluginOn` / `Copy.autoRecallPluginOff`) and offer no button. `GET /agents/setup?harness=` (round 4 C5, G76's in-app half) serves
what to hand an agent instead of running anything (for Claude Code with the plugin on, a prompt that runs nothing):

- for Claude Code, Codex and Gemini CLI, a plain prompt (≤ 1,500 characters) that names the exact
  commands, built by the same step builders `/agents/wiring` uses (both steps always, and for Codex a third, its
  `~/.codex/AGENTS.md` block, 2026-10-23; `display == shlex.join(argv)`);
- for Cursor, its MCP install link and the startup-hook and capture-hook merge argv, plus (2026-10-14) a `prompt` for
  Cursor's own agent that adds the MCP server to `~/.cursor/mcp.json` and nothing else — both hooks stay their own
  clicks (R-H11); Remembers automatically offers the startup action independently, and the Agents page' Cursor
  steps add *Save chats on their own* (the wiring's `connect`, the capture hooks) while capture is off;
- for OpenCode, Hermes and OpenClaw, a prompt with no commands naming the server and where it lives in the agent's own
  settings;
- for `other` (2026-10-14, "Another agent"), one generic prompt — the server spec, "add one MCP server named cicada to
  your own MCP settings, in the shape they already use", change nothing else, if you can't, say where they live and
  what to add, uploads nothing, one sentence back — that names no agent (provider-neutral copy);
- for Claude Desktop, a config merge the APP performs and **no prompt**: its chat cannot edit its own config, and
  handing the file to some other agent would trade the app's backup-first merge for a hand edit of a file holding
  other servers' secrets.

Every prompt names the server through `agent_wiring.server_lines` (command, one `argument:` line per argument,
environment), so a release app's argument-less `~/.cicada/bin/cicada-mcp` reads right (G182; the config prompts used to
index a first argument and failed there). ≤ 1,500 characters, commands and paths never shortened. No probe, no
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

the Agents page → **Editing pages** (G198, `PageEditorsGroup`, its own file plus one line in `ConnectView`, row id
`agentsEditors` in the index): one row per local agent `GET /settings/editors` lists as a candidate (plus any already
allowed that it no longer lists), its Track L mark (DR-52), "Allowed since <day>", "On by default" (a default with no
day) or "Asks in your inbox first", and a system switch with its label spoken (DR-40/41). While the response says
`customized: false`, a note names its `defaults` (owner 2026-10-14: "Claude Code and Codex edit pages directly unless you
turn them off.") — the names come from the backend, never from app copy. `PageEditorsModel` reads the list when the page appears (and on the SSE
reachability flip), writes one switch at a time with `PUT /settings/editors` (`{trusted: {harness: bool}}`), shows the
change at once and puts it back with the server's sentence on a refusal. Machine-wide, outside every bank, not a Store
domain (no ETag). Copy names only the agent's app (provider-neutral).

the Agents page (round-4 D5) adds, per harness, Connect for me (the same `AgentConnect.run`), Copy
setup prompt (`GET /agents/setup`'s prompt shown verbatim, then copied — the agent runs the install itself), Open in
Cursor (the catalog's own deeplink) and Set up Claude (`ClaudeDesktopConfig` merges `mcpServers.cicada` into Claude
desktop's config: backup first, merge never replace, an unreadable file left untouched; the app computes the path and
the value itself). Round 4 C8: the Agents page is one selector of eleven agents (`AgentCatalog`, pinned to
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
rows, the last-seen registry (`agent_seen`, G217: survives telemetry off), a used connector (`last_used_at`) or the agent's own config — no subprocess, never `~/Library`, never
`~/.claude.json`; polled every 3 s while the page is visible.
**Wire for the redesign (G217/G205/G212/G50, 2026-10-22; app not built yet):** `GET /providers` is the one table the
Agents and Intelligence pages draw (umbrella, logo slug, ways, plans and keys); `/agents/live` adds rows for every
tracked way after the eleven pills; `GET /devices/status` names each machine by its own name with `connected`, `how` and
`queue`; an `agent_request` inbox item carries `request.notification` for a Mac notification; key cards carry `keyHint`,
`keyStore`, `verifiedAt`, `termsNote`, and a 503 from `PUT …/key` means offer "Save without checking" (`api.md`).

**The Skills page (owner 2026-10-15, third take).** At ⌘4 since ⌘ map A (2026-10-16). **Its top row is every other
page's (owner 2026-10-20):** the tabs Installed · Discover · Drafts sit in the eyebrow row, then Check for updates and a
labelled *Add a skill* (`PageAddButton`, DR-75, ⌘N) that opens the Add sheet empty — the header's add field is gone. `SkillsPage` over `SkillsPageModel` (in memory, not a Store domain; `SkillsAPI`, faked in `SkillsPageTests`)
shows `GET /skills` as **one plain table** — Skill (the name and one muted line), Agents, Status — with no pictures.
The Agents cell is one pull-down ("Claude Code, Codex +1 ▾", `SkillAgentWords`) listing every agent installed on this
Mac: tick to turn the skill on for it, untick to turn it off; an agent that reads another's folder shows a hollow tick
and "through Claude Code"; agents not installed are hidden. Status is one quiet word from the backend's `status`:
"Up to date" with a dot, "Local", "⚠ Refresh" (a tool skill's text older than its tool), or an **Update** chip whose
popover (`SkillChangesPopover`) lists what changed ("0.1.13 → 0.2.0", each commit or release) and holds the one Update.
Selecting a row opens the skill on the shared progressive columns (round 2 of the consistency pass, 2026-10-20, like
Sources and Projects): the table narrows to the triage list (`SkillListRow`, two-line rows; titles only beside the
Reader) and `SkillDetailColumn` takes the rest, its words held to the focus card's measure; the Reader is the third
column (`AppTab.hostsOwnReader`), DR-27 hides the list first ("‹ N skills"), ↑/↓ move the open skill, ⏎ steps in, Esc
closes the rightmost. The detail is headed by the shared `DetailHeader` (2026-10-20): the repo link, versions, the install day in words, the Mac permissions in words
labelled "Checked for Cicada" with a line that an agent in another app may differ, an instructions excerpt, Remove…).
A first read shows `ListSkeleton`; a failed one `ListErrorCard` with Retry. The header has the add field ("Add from GitHub, or paste npx skills add…", ⌘N), which
opens `AddSkillSheet` (the SKILL.md, the files with scripts called out, the commit; Install installs exactly that); an
agent's request is one line above the table; tabs Installed · Discover (the catalog) · Drafts (agents' drafts and what
Sleep noticed). The page opening re-checks for updates only past an hour.
**Plugins, kinds and weight (G201 slice (a), TODO ruling 35, 2026-10-22).** The table gains a **Kind** column: one quiet
word — *About you*, *Generic*, *Not sure* — on a `TextButton` pull-down (`SkillKindMenu`, the Agents cell's pattern,
DR-40) whose choice goes to `PUT /skills/kinds`; "your choice" marks one the person set. Drafts and *Noticed by Sleep*
rows carry the same menu. Under the table, **Plugins** (`SkillPluginsGroup`, `SectionLabel` DR-20/DR-47, one line under
it saying plugins are turned on and off in Claude Code) lists each Claude Code plugin read-only on the table's columns —
its name and "v1.2.0 · marketplace", the agent, and *On* / *Off* / *Per project* — then its skills indented, each with
its kind and "you run it" for a skill only the person starts; nothing there toggles. Above the table one meta line gives
the weight ("Loaded every session: Claude Code 14 skills, about 1,200 tokens · …", `SkillPluginWords.weight`), its
basis on hover — DR-59's dated exception for an estimated token count (ruling 35 §6). Plugin rows are not selectable and
show only in the full-width table. Tests: `SkillsPageTests` (decode, words, a kind flip sends the row's key).

**the Skills page (G138).** A reviewed catalog (`api/data/recommended_skills.json`: source,
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

**The redesign, Sources · Inbox · entity card · Sleep (G217, G205, G212, G61, G206; ruling 36 D5/D6, 2026-10-22).**
- **Sources is the one catalogue** (`SourceCatalog`, pure; `SourceCatalogViews`). Every way in, on or off, grouped
  *Accounts and browser* (X, YouTube, Instagram, LinkedIn, Reddit, Pinterest, TikTok) · *This Mac* (Calendar, Contacts,
  Messages, each browser on this Mac, Apple Notes, Folders, Wispr Flow once present) · *Exports* (Files and links; Chat
  exports, which point at their agent — `AppRouter.routeToAgents`, the Agents page) ·
  *Feeds* (RSS, Calendar feeds, Telegram), then *Agents' conversations* for an overview harness row no entry speaks for.
  A row is a `LogoTile` (through the `SourceLogoTile` adapter: an origin key or an umbrella logo slug in), the name, the
  last sync only while on, and a dot with one word: **Connected · Needs sign-in · Off** (`SourceCatalog.status`: a
  channel whose last failure reads as a lapsed sign-in, else any connected channel, an allowed site for Instagram, a
  harness with conversations). Its detail (`SourceCatalogDetail`, DR-74's head) holds the source's own control — the
  very rows Settings drew (`CalendarRow`, `ContactsRow`, `MessagesRow`, `BrowsersSection`, `WatchHistoryRow`,
  `FolderChannelRow` + *Add a folder*, `WisprFlowRow`), or `ChannelActionsBar` (Connect / Refresh / Manage) for a
  registry channel, or a tile's flow — then the per-site reading switch for a walled site (x, instagram, linkedin,
  reddit, tiktok; `PUT /reading/settings` `{sites}`, turning a site on also turns reading on with its acknowledgement:
  Reading the web left Settings, default on), then what came in (the source's v4 list when the overview has a row).
  Instagram is offered with **Turn on** = the reading switch, saying the browser reader is still coming (G206) and
  offering the data export. Obsidian's entry is gone (a vault is a folder). Contacts stays (ruling 33).
- **One catalogue (Hyrum mode B):** the *Add a source* grid opens from nowhere now. The eyebrow keeps DR-75's labelled
  add as *Import a file* (opens Files and links); Sleep's `+`/⌘N opens the Sources page; `routeToAddSource(tile)` lands
  on that tile's entry (was Sleep's sheet); a tile's flow still opens alone (`AddSourceSheet(flowOnly: true)`, leaving
  the flow closes it). *Sync now* / *Poll now* read **Refresh** everywhere on these surfaces. The `.source(id)`
  selection and `routeToSourceDetail` still open the v4 detail; an overview id lands on its catalogue entry.
- **Connectors that say what they do (2026-10-23, `fix/sources-connectors`).** A row reads Connected only while
  something will keep arriving: `SourceCatalog.status` takes `localReaders` (`LocalReaders.on`: Calendar, Contacts,
  tab groups, YouTube history, each browser's bookmark watch and Apple Notes, by this Mac's own switches), so a reader
  turned off here reads Off whatever it synced before; the backend answers Messages (no conversation ticked), Wispr
  Flow (turned off), a feed while `CICADA_ALLOW_FEED_FETCH` is off (with `lastError` saying why) and Telegram (only
  once a message arrived). Needs sign-in is a connector's alone (`signInChannels`: X, Reddit, Pinterest). In the
  detail, a feed's `manage` opens its tile's flow (*Add a feed* / *Manage*: the Subscribe field and the list — the bar
  drew only Refresh, so RSS and Calendar feeds could not be added), Refresh shows only with something to poll, and a
  channel's `lastError` is the line under its actions; Apple Notes has its own control (`NotesControls`: Connect, then
  Refresh and Disconnect; `AppleNotesWatcher` keeps up every two hours while Notes is open); Telegram says plainly it
  needs a public address Cicada never opens, with *How to set it up* opening its steps (`~/.cicada/secrets.env`, not
  `api/.env`). The overview files a nil-origin save (a bookmarks file imported through Files and links) under Files &
  links instead of a row called "unknown", and a phone's note reads *Phone*. Live test, same day: YouTube claims the
  overview's `youtube-history` and `youtube` rows, and an account's import that fed memory reads Connected (an overview
  row no channel speaks for, so a reader turned off never returns through its episodes); a row's last sync is the newest
  capture write (`captured_at` / `last_turn_at`), not a session's start; Instagram's line says what G206 shipped and a
  saved list switched on reads Connected.
- **Lists on by default, where a file comes from, Google Calendar (owner 2026-10-26; G71, G206, G142).** *Lists:*
  the YouTube row's detail now holds its two list switches (`youtubeListToggle`, `YouTubeListWords`' titles and lines;
  the first-use sheet first when agent reading is not on, `ReadingFirstUseSheet(youtubeList:)`), and a YouTube list
  kept current reads Connected (`savedListsOn` holds `youtube`). The backend turns on an older install's undecided
  lists for accounts its memory shows when `GET /reading/settings` is read (`list_defaults`, ruling 39's dated line);
  an off the person chose is never overridden. *Import a file:* every row that imports a file says, before its button,
  where the platform hands the file out (`SourceCatalog.exportHow`: YouTube's Takeout, Instagram's Export your
  information, TikTok's Download your data in JSON, LinkedIn's Get a copy of your data, a browser's bookmarks export;
  Notion keeps `notionHow`); the walkthroughs name TikTok's file `user_data_tiktok.json` and Instagram's Export your
  information. *Calendar:* `CalendarRow` lists the accounts the last read included (`CalendarReader.accounts`,
  `CalendarAccountGroup.groups`: "Includes iCloud (3 calendars) · …", On My Mac last; shown on this Mac only, never
  posted) and, always, "Google calendars come in through macOS…" with *Add a Google account*, which opens System
  Settings → Internet Accounts (`CalendarRow.internetAccountsURL`) and asks macOS for nothing. A Google calendar's
  secret iCal address through Calendar feeds is not offered: a feed subscription is stored in the bank's
  `calendars.yaml`, and that address is a credential.
- **Reminders and Notion (G219, ruling 38: one way in, never written back; 2026-10-23).** *This Mac* gains
  **Reminders** after Contacts (`SourceCatalog.fixed`, id `reminders-local`, the installed Reminders app's icon,
  `com.apple.reminders`). Its detail is `RemindersRow`: `CalendarRow`'s line and buttons (Connect · Refresh ·
  Disconnect behind "Stop reading your reminders?"; Open Privacy Settings when refused) with the Off line saying,
  before the prompt, that macOS only offers full access and Cicada only reads; once connected, *Lists to read* — one
  checkbox per list on this Mac, nothing pre-ticked — and beside every list, before it is ticked, *Others add to it*
  (its items are read as someone else's words; offered before the tick so a shared list's first read is never stored
  as the person's). The reader is `RemindersReader` (`.shared`, in the environment beside `CalendarReader`;
  `RemindersStore` the EventKit seam, `EventKitRemindersStore` the real one, tests inject a fake and never raise a
  prompt): ticks and Connect live in this Mac's defaults (`cicada.reminders.enabled`, `.lists`, `.shared`), Refresh on
  a card routes through `ChannelActions.SyncRoute.remindersLocal` and never starts a first read. **Status is honest
  (#448):** `LocalReaders.on(reminders:)` is `isOn` — connected, macOS still says yes, and at least one list ticked —
  so a Reminders connected with nothing ticked, or disconnected here, reads **Off** whatever synced before; the dot
  reads Connected and the last sync once the backend's always-listed `reminders-local` row has synced. Not added to
  onboarding's tiles: the grid already holds Calendar, Contacts, each browser, Messages, YouTube, X, Instagram and chat
  history, and Reminders needs its list picker (it would be a fifth "open" tile); it is one click away on Sources.
  *Exports* gains **Notion** (id `notion`, origin `notion-export`): its detail says how to export (Settings → Export,
  Markdown & CSV with subpages) and holds the one intake's drop (`IntakePanel`); the preview reads "Notion pages" with
  "N pages · N database rows" (`IntakeCounts.pages`/`rows`, `IntakeSummary`), and the row reads Connected once an
  import fed memory (the backend's `notion` origin row, like a chat export).
  **Ruling 47 tier 2 (2026-10-29):** *Accounts* gains **Readwise** (id `readwise`), and Notion's row also speaks for the
  live connection (`channels: ["notion", "notion-api"]`). Both details open `ConnectorSetupPanel` — the panel Reddit,
  Pinterest and X already use, so no new pattern (DR-40 buttons, DR-20/DR-2 caption text, DR-81 no fold, DR-52 marks:
  Readwise draws the `highlighter` symbol, Notion its export's symbol) — which says what the connector reads
  (`reads`) and where the token comes from (`tokenHelp`) before Save, then Refresh and Disconnect. A refused token reads
  Needs sign-in (`signInChannels`). Notion's detail keeps the export's steps and drop below the live panel.
  **G32 (2026-10-29):** *Accounts* gains **Spotify** (id `spotify`, `verb: .importFile`, channels `spotify` — the
  library's saved items — and `spotify-listening` — the listening days). Its detail is the Files & links row's own
  controls (the where-it-comes-from line, then `IntakePanel`): `Copy.Catalog.howSpotify` says to ask Spotify's privacy
  settings for Extended streaming history or Account data and drop the zip it emails. The bundled `spotify` mark.
- **Inbox top cards (G205, G61):** `agent_request` (`InboxKind.agentRequest`) and the grouped *Confirm N links* review
  (`asks: sources`, `review: true`) are cards above the questions, out of the list, its tabs and the quick review
  (`InboxViewModel.questions`). A request: the agent's tile, *Sign in to <site>*, whose and why, **I signed in**
  (`optionKey: done`) / **Not now** (`dismiss`), both held for Undo like any answer. `AgentRequestNotifier` posts each
  new request once as a local notification in the backend's words (title, body, category with the same two buttons, a
  tap opens `openUrl` if http(s)); macOS is asked only from the card's in-words line *Get a notification when an agent
  asks? Notify me*, at the first request; posted ids are remembered per viewer (`cicada.agentRequests.notified`). The
  review: per row the link-kind glyph (`LinkKindGlyph`), the link, its page (opens it), where it was found on hover
  (never an episode id), **Yes / No** answered alone (`POST /inbox/{id}/resolve` with `row`), optimistic with a toast.
- **The entity page, v2 (ruling 48 (3), (4), (7), (16), (17); DR-78…DR-81; part A, 2026-10-29).** The Content tab
  draws `GET /entities/{id}`'s `blocks` top to bottom, the same for every type, and nothing folds: *In short*
  (`PageInShort` — the served why-it-matters line and, under it, what a person's facts strip repeated: "N conversations
  · the latest …"; Sleep's summary lands here in part B), *Where to check* (`WhereToCheckBox`, DR-79: one box of mention
  rows — site in `textTertiary`, the link's own words in primary ink, its state in words on the trailing edge — a
  person's rows drawing the link kind's glyph, never a site icon (G159); proposals one "N suggested links · Review" line
  whose popover takes or drops each; at most five rows, then *All N* in a popover; a right-click removes; *Add a link*),
  the type block (the brand block, `PageBrandBlock`, above the article when looks are what the page is about — two or
  more, or no article — then the look tiles; a folder, a repository), *Ongoing* (`PageOngoing`, open happenings and
  planned milestones on the Projects band's hollow node, at most five), the article carrying its beliefs, and
  *References* (`PageReferences`, at most six numbered lines, then "N conversations and M web pages in all · who wrote
  each change is in History", with a History link). **The article carries the beliefs (DR-80):** every line the
  page's write-time provenance cites ends with a superscript per source (`CitationMarks`, `labelFont`, `textTertiary`,
  a `cicada://cite/<n>?at=<offset>` link); a click opens a popover (`CitationPopover`: the kind — *You said*,
  *<agent> replied*, *Looked up*, *From this conversation*, *Inferred* — when, where, the located words through
  `QuoteBlock` (DR-18) and *Show in conversation* into the Reader, DR-31), read lazily from
  `GET /entities/{id}/citations/{n}` and held in `CitationDetailCache`. Keys and VoiceOver: each cited line keeps its
  sources as focusable chips in the gutter (the 🔗's place; ⏎ opens, Esc closes) and as named actions "Source N" on
  the line. A page whose prose cites nothing yet draws its beliefs as one paragraph of sentences
  (`PageBeliefSentences`): an inference worded "It seems that …", an ended one "(until March 2025)"; past twelve, "N
  more in Perspectives". **Gone from the page:** the beliefs list, *Where this came from*, the person's *How you know*
  and *What's happening*, the facts strip, *Details* and the empty *Looks* fold; *How it fades*, *Add a link* and *Add
  a look…* live in the header's "…" menu. **One request on open:** the card no longer reads `/sources`, `/provenance`
  or a person's fact claims when it opens — `/provenance` is read when History, Perspectives or Timeline opens — and
  the Clusters column reads its page through the Store's memo, which now shares one read in flight per page
  (`Store.entity`).
- **Sleep's machines strip (G212):** under the room, `GET /devices/status` polled every `CicadaTiming.machinePoll`
  (30 s) while the page shows, held in memory: each machine by its own name (this server's Computer Name), a green dot
  while connected, how (Local · Tailscale · SSH · Local network), *N waiting*. A click opens that machine's queue in
  Waiting (rows rebuilt from its own episodes; `GET /sleep/episodes` rows carry `device`, shape `episodes-3`). The
  engine line is UI-A's.

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
  the link's own site, the way a browser finds its icon (declared in its homepage first, 2026-10-20; an SVG-only site's icon arrives as a PNG the backend drew, 2026-10-20)
  — never an icon service (`storage.md`, "A saved link's own site icon"). Until it arrives, or for a
  site with none: the bundled mark of a known family (LinkedIn, X, Instagram, TikTok, Reddit), else a ring monogram of
  the site. Never the browser's mark. With `CICADA_ALLOW_LOGO_FETCH=off` every row is its monogram.
- **One mark for a saved link (owner 2026-10-20).** *"Instead of the Chrome logo make this an app-wide change."* Every
  surface that draws a saved link draws `SavedLinkMark` (`Views/Common/SavedLinkMark.swift`), from one pure rule,
  `SavedLinkMarkModel`: the site the backend named (`siteKey` / `site`, `reading_hosts.mark_key`) → `SiteIcon`, asked by
  the item's media id or, before Sleep made its page, its episode id; else the family's bundled mark; else the site's
  monogram. Drawn by Sources' saved rows, Sleep › Saved and Videos rows, Sleep › Waiting rows of a saved link (a
  conversation, note or file keeps its source's mark), an open saved item's eyebrow, the Reader's header for a
  saved link, and the ⌘K palette's conversation row of a saved link (review of #372: the search hit carries `site`,
  recorded by the search index from the episode's own frontmatter; `FindMark.savedLink`, asked by the episode id). Where it was saved from stays in words: the open item's "Saved from" line keeps the browser's mark beside
  its name (that line answers that question), and a source's group row, spine and pile plate keep the source's mark
  (the group *is* the source). Entity pictures (Find's saved rows, Ask's citations, the entity card, the graph) keep
  the picture precedence — a page's own thumbnail outranks a site icon there. `SiteIconStore` keeps an icon per
  site and bank whichever id asked but a miss per id (one refused id never hides the site's icon), and puts at most four requests on the wire (`maxConcurrent`); a row that scrolled
  away before its turn asks nothing. A miss is believed for ten minutes (`missTTL`, marks-2), so a window left open
  across a backend update asks once more — a cache read there while the backend's own miss is fresh. A saved list's
  row of a link Sleep has not made a page of yet asks by its episode (`SavedItemText.door`; the list names its site,
  `channel_items` `g161-6`). **A saved YouTube video's row draws its still** (`VideoStill`, the watched day's view, at
  64 × 36; `GET /sources/saved/{id}/still`, `SourcePictures.savedStillPath`), not the site's mark (owner 2026-10-20).
- **Saved lists in your browser (G206, spec 2026-10-22; first slice built 2026-10-23 on the catalogue's detail: the switch, its off line and the first-use sheet first, whose Turn on then enables agent reading and that list in one call, never a `sites` grant — the last-read line and *Try again* are not built yet).** On a saved source's detail
  column for X, Instagram and LinkedIn, one row under the sync row: label "Read my <Bookmarks|Saved|Saved posts> in my
  browser" (`SectionLabel` above it reads *In your browser*, DR-20/47) with a `Toggle` bound to
  `GET /reading/settings` `savedLists.<site>` and written by `PUT /reading/settings {"savedLists": {"<site>": bool}}`
  (optimistic with rollback; the reading settings are not a Store domain, so the row says so and caches in memory). The
  second line, in `textTertiary`: off — "Your own agent reads this list in your signed-in browser. Saved posts are
  kept for lookup, never read."; on — the last read from `saved.lists.<site>` ("Read today · 24 posts", relative day
  computed when read, DR-58; counts `monospacedDigit`, DR-21), or "Paused until Oct 29 — your agent needed you to sign
  in" with a neutral *Try again* button (DR-40) that PUTs the switch on again. When agent reading is off or its sheet
  is not acknowledged, turning the switch on first opens the Reading-the-web sheet (the same acknowledgement; the
  PUT answers 422 with that sentence otherwise). The accent is not used here beyond the toggle's own tint (DR-5); no
  new mark (the family's bundled mark already heads the column, DR-52). A `needs_login` lands as the G205 agent
  request in the Inbox, not on this row.
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
  (a bookmark that left the browser is none), and a row whose count is zero has none. **Icons first (owner direction 2026-10-20, "a picture specific to the site, not a letter"; marks-2):** a saved row's faces put the sites whose own icon is already cached first, then the rest, each newest
  first (`channel_items.saved_faces`), and the overview's ETag folds in the `siteIcons` sync component (the own-site
  icon index outside the bank: its mtime plus entries past their TTL), which `VersionVector` maps to `.sourcesOverview`
  only, so a letter shows only beside sites still unasked or truly iconless — and those faces ask as they appear. Pictures load through
  `SourcePictureStore` (in memory, misses kept, per bank, at most four asks at a time). Bundled marks draw on the first
  frame (`LogoImage.bundledImageNow`), never the generic "app" placeholder.
- **Rows say each thing once.** A list row's title drops a trailing " · <its own day>" (`channel_items._without_day`).
  Messages lists one row per chat — its face, who it is with, its newest day and "N sittings" — opening in place to
  its sittings by day and message count, each opening in the Reader (`ChatSittingsRow`, `GET /sources/messages/chats/
  {id}/sittings`, `ChannelItemsCache.refreshSittings`); the list follows the overview too, so a chat photo reaches it. A conversation row inside its
  harness's list shows neither the harness badge nor "Saved once" (`ConversationRow.inSourceList`); a conversation saved more than once says "Saved 3 times" (its `episodeCount`, never "episodes", ruling 39), and the pages it wrote are neutral `Tag`s by name, the id in `.help` (as Past reads' run detail). The conversations'
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
link-render branch's (it reads `GET /explore/captures/{entity_id}`, `storage.md`). the Sources page gains
**Explore in your signed-in browser** (on by default, D2 amended; `ReadingAgentModel.setExploreSignedIn`, row
`readingExploreSignedIn`) and the first-use sheet's exploring paragraph (ack v3, D3). Copy: `Theme/Copy+Explore.swift`.
Tests: `ExploreTests`.

**Your YouTube lists (G71, owner 2026-10-16).** the Sources page shows, while agent reading is on, a group of
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
**Both dates (TODO ruling 39, 2026-10-24):** a row's line shows the item's own day only; when the item came in days
later (a feed's back catalogue, an old bookmark) its help and spoken label add "· added <day>"
(`CapturedItems.withReceived`), and the Reader's meta line reads "May 1, 2023 · added Oct 24, 2026"
(`EpisodeText.receivedAt`, `Copy.Provenance.added`).
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
  is mock A's cards (F-11, G146; plain labels and no type glyphs since 2026-10-28): People · Projects · Companies · Tools · Concepts · Media two to a row, the
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
  unchanged `AddSourceSheet`, whose root hosts the one `IntakePanel`; the Sources page' "Import in Sleep →"
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
  refreshes the graph. Words in `LinkedInConnectionsWords`, tested in `LinkedInConnectionsTests`. the Skills page
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

**Hidden (owner 2026-10-26) until the G222 redesign.** `PageSwitches.projectsPage` is off: the rail draws no Projects
cell (⌘8 opens nothing; no other digit moved), ⌘K has no *Go to Projects* and a project's row opens its page on the
graph, the tour skips its Projects stop (`TourStop.shown`), `routeToProject` / `routeToBacklogItem` open the project's
own page (`routeToEntity`), and a stored "Projects" selection lands on Clusters (`AppTab.landing`). Nothing below is
deleted and no project page changes; turning the switch back on restores all of it. Projects still appear in Clusters,
on the graph, on a person's card ("What's happening", which now opens the project's page) and in ⌘K as pages.

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

**Projects v2 redesign — the person's own list, Suggested, the knowledge panel (TODO ruling 45, 2026-10-27; wire
g141-7; DESIGN_RULES §9 2026-10-27).** The page is back on the rail (`PageSwitches.projectsPage`, ⌘8). What it does:
- **The list draws only the person's own** (`ProjectRow.mine`; an older server's rows, with no `mine`, all count as
  theirs). After the rows, a *Suggested · N* fold (`ProjectsSuggestedSection`): each suggestion's reason glyph, its
  reason in words (`why`), the person's located sentence for a words birth, and two neutral buttons, *Add to my
  projects* and *Not mine*. It opens the first time and is remembered (`cicada.projects.suggestedOpen`); dismissed ones
  sit behind "N dismissed · Show". A provider grouping (`kind: group`) asks for a name on accept (`ProjectNameSheet`).
  With none of the person's own yet, the list says so above the fold (`ProjectsListState.emptyMine`).
- **New project** is the eyebrow row's `PageAddButton`; its sheet takes a name and a description and opens the new
  project.
- **The header** is `ProjectHeaderEditor`: the name and the person's description, edited in place (PATCH), a meta
  line saying how it became theirs and who last set the description (with that agent's mark). Sleep's first line shows,
  dimmer, only when the person wrote no description.
- **The knowledge panel** (`ProjectKnowledgePanel`) sits beside the card when the column is wide enough
  (`ProjectKnowledgeLayout.sideBySide`), else under it: Conversations · N from `GET /projects/{id}/conversations`
  (`ProjectsCache.refreshConversations`, ETag-revalidated, never a Store domain; a row opens the Reader, its context
  menu unties it), the why line in words, Sources & influences grouped by kind with *Add an influence*
  (`AddInfluenceSheet`) and Undo on the person's own, then a provider project's instructions and documents.
- **Writes** are `ProjectOwnershipWrite` (`ProjectChange`: create, accept, dismiss, header, tie, add or withdraw an
  influence) through `Store.perform`: painted over the cache (`ProjectPaint`: a project moved in or out of the list,
  the header's words, an untie, an influence taken back), rolled back with the server's sentence on failure, settled
  by the first answer requested after the confirmation. The groupings file rides the sync `entities` component, which
  `ProjectsRefresh` already watches.
- **"Timeline"** names the dated list (the old *What happened*, Q6). A separate *Done* fold is not built: done items
  read in the Timeline with their state (disclosed in the build report).

**Projects v3 — where it came from, six standard sections (ruling 36 D4, G141; backend shipped 2026-10-22, the SwiftUI
part is a spec and needs a Mac).** The wire is `api.md`'s g141-6. What the page does with it:
- **The row** keeps its one signal (DR-38) and adds nothing for a page with `origin` null. A row with `origin: repo`
  leads its second line with the `chevron.left.forwardslash.chevron.right` glyph (DR-53, `textTertiary`); `words`
  carries no mark — it is the common case and needs none.
- **The header** (`DetailHeader`, DR-74) says where it came from in one line under the name, in `metaFont`
  `textSecondary`: repo → "From the repository alpha-project · 22 Oct" (`repoName`); words → "You said this is a
  project · 22 Oct", the day a button that opens the Reader on `episode` with the span highlighted (DR-31, DR-57
  "You said"); folder → "You named this folder a project"; `kind` null → nothing (the review list is the Inbox's, after
  the owner reads the dry run, never a banner here). `quote` is shown only in the Reader, through `quoteFont` (DR-18).
- **The body is the six `sections` in their order**, each under one `SectionLabel` (DR-20, DR-47): *Overview*
  (`markdown` rendered as page prose), *Timeline* (today's band and Lately, unchanged — the section's `entries` are ids
  into `items`, so nothing is drawn twice, DR-38), *Done*, *Expected* (milestones then backlog items; a backlog entry
  opens the item), *Design* (the page's `## Design` markdown, then its Looks as thumbnails opening the look), *People
  involved* (person chips from `people`, each opening the person's card). An empty section is one `textTertiary` line
  saying who would fill it (from `writtenBy`, in words: "Nothing done yet — tell an agent or log it here"), never a
  blank and never a card of its own (DR-32, DR-37); Design and People start collapsed when empty (DR-39). `more` > 0
  ends a section with "Show all n" opening the full list in the column. The existing folds (In progress · What
  happened · Plan · Backlog) retire into these six; Log progress stays above them.
- **Swift work:** decode `origin`, `sections`, `people` leniently into `ProjectOrigin`/`ProjectSection`/`ProjectPerson`
  (`ProjectsCache` unchanged — the ETag shape moved, so caches refetch once), re-pin `projects-demo.json`'s decode test,
  add `Copy+Projects` strings (provider-neutral, DR-59), and a `ProjectDetailSectionsTests` over the fixture.
- **Projects v3 (2026-10-28, ruling 48: DESIGN_RULES §9 2026-10-28 (9), (10), (17); DR-81, DR-38, DR-44, DR-45, DR-74,
  §3.8) — the page has no folds.** A section with nothing in it is not drawn; a section with something is open and
  holds at most five rows (`ProjectOpen.cap`); more is a plain "All N" on the section's label that swaps the card's
  column to that full list (`ProjectOpen.Full`, `ProjectFullHead`: ‹ Back · title · count; Esc returns), never an
  in-place expansion. A source lint (`ProjectPulseTests.testTheProjectsPageHasNoFolds`) fails any `Disclosure*` under
  `Views/Projects`. **The head** is the name, the person's line and ONE standing line ("In motion · 3 of 6 milestones
  done · Next: Fibreglass the hull, Nov 8", Next a button onto its row; with nothing planned, "Add a milestone" M):
  the meta line ("You added this project · … · description last edited by …") moved into the head's `.help`
  (`ProjectHeaderEditor.provenance`), and *Last* left — the Timeline's first row and the band's newest mark say it
  (DR-38). **Under the band and Log progress:** *Pulse* (`ProjectPulseView`, read at the viewer's today by
  `ProjectPulse`, the twin of `project_pulse.py` on one fixture): the last 4 weeks as words over four neutral weekly
  bars (text ink, never a hue — the band's green stays the page's one colour), what it is *waiting on* (an open
  thread's `from` participant, `waitingOn`), what has *gone quiet* (an open thread silent past Q); each fact is drawn
  only when it has something to say. *In motion* (the open threads, `ProjectNowSection(limit:)`, and the Sleep queue's
  line). *Coming up* (`ProjectOpen.comingUp`: planned milestones by target, then the backlog's open and doing items,
  each opening as the third column; its full list adds the whole backlog with its tabs and its add fields; the ⋯ menu's
  *Add to the backlog* opens it). *Timeline* (`ProjectOpen.timeline`: every story row plus every milestone marked done
  as a filled diamond with a "Milestone done" Tag, newest first; the full list ends with "Cicada started tracking
  this"). Done, Plan, Backlog and Around this project are gone as sections. A pick on the band (or Next, or a pulse
  fact) whose row the capped section does not show opens that section's full list and scrolls to it
  (`ProjectOpen.isShown`). **The knowledge panel** leads with *Pages in this project* (`ProjectPagesBlock`: the
  pages a claim or an event ties, the ones tied by hand with a "You tied it" / "<agent> tied it" Tag, and an agent's
  proposal first with Add and Not part of it; on hover a row offers *Not part of it*, also in its menu; Add opens
  `AddProjectPageSheet` over the pages already in memory, never making one), then Conversations and Sources &
  influences, each capped with its own "All N". Writes are `ProjectChange.tiePage` through `Store.perform`, painted at
  once (`ProjectPagesPaint`). **The list:** sub-projects sit indented under their parent, always shown (no chevron —
  amends 2026-10-19's "dropdown that moves if I press again", the owner's newer preference); the quiet projects sit
  under a static *Gone quiet* label (`ProjectsEntry.quiet`), never a fold; Suggested is one line, "N suggested by
  Cicada · Review" (`ProjectsSuggestedLine`), which opens the suggestions as the detail column
  (`ProjectsSuggestedColumn`: DR-74's head, text tabs Suggested · Not mine). ← on a sub-project opens its parent; →
  has nothing left to unfold. The bullets below describe v2; where they name a fold, v3's open section replaces it.
- **The list (v2):** text tabs **Current · Past** with counts (`ProjectsModel.tabs`; tapping the selected one keeps
  it). A project's group is `ProjectState`'s section (`ProjectsGroup`): in motion → Current; quiet → **Fading**, one
  folded disclosure at Current's foot, remembered on `cicada.projects.fadingOpen`; resting (decaying or archived, or
  nothing heard for 90 days) → Past. **Activity inside the rhythm wins over the decay status (2026-10-28):** a page
  Sleep marked decaying or archived but heard from within its quiet threshold Q (progress logged, a claim's day, a
  repository session, or a conversation tied by hand, by the provider's project id or by the relaying app's word —
  `project_timeline._tied_days`, list and detail alike) is in motion; the status rests it only once it is quiet past Q. `ProjectsModel.entries` is the whole column as `ProjectsEntry` values — rows,
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

**Looks on pages (owner rulings 2026-10-20).** The Looks page is gone: a look lives on the page of the thing it shows
(`storage.md`). The entity card draws a page's looks from `LooksCache.shared` (one in-memory cache for the card and
Clusters, revalidated by ETag on appear and when an SSE version moves `design` or `bank`), never from the page's
`## Looks` markdown, which the article drops (`WikiArticle.ownSurfaces`). `PageLooksSection` (`Views/Looks/PageLooks.swift`,
pure as `PageLooksBlock`): with looks, a block under the article — "Looks · N looks", a grid of `LooksTile`s, the add
row; with none, a remembered `CardDisclosure` (`CardSections.looksKey`) among the sections behind a click. A tile opens
`PageLookSheet`: `LooksDetailColumn` (its new `extra` slot holds `PageLookExtra` — the looks most like it from
`GET /design/{id}/similar`, each "On <page>", a click opening that page — and *Take it off this page*,
`PUT /design/{id}/entity` with null), the screenshot enlarging over the sheet by `LooksZoom`'s rules. Adding: a pasted
link (`PageLooks.link`, http/https only, else said) → `POST /sources/save` then `POST /explore/look` with `subject` (the
prompt copied, "Queued for your agent…"); a picture dropped anywhere on the card's Content tab → `DesignImageShrink` →
`POST /design` with `entity` (`PageLooks.drop`; a dashed ring while held); *Put a saved look here* lists the looks on no
page (`LooksCache.unplaced`) and moves one with `PUT /design/{id}/entity`. Clusters' View menu gains "Only pages with
looks" (`ClustersModel.filtered(withLooks:)` over `LooksCache.pagesWithLooks`). **Clusters' Looks tab** (review of #384,
the owner's "filter looks inside the entities page"): after the type tabs (`ClustersTab.looks`), `LooksGallery` — every
look, on a page or not, as tiles each saying "On <page>" or "Not on a page"; words search on ⏎ (`LooksCache.search`), a
picture dropped or pasted there finds the looks like it; a tile opens `PageLookSheet`. The sheet also holds the
person's own words (`PageLookEdit`: name, link, what they liked → `PATCH /design/{id}`; an agent's note is never
prefilled as theirs) and *Put it on a page* / *Move it to another page* (`PageLookPlace`, a find over the graph's names
→ `PUT /design/{id}/entity`). Renders: `LooksTests.
testRenderThePageLooksForReview` with `LOOKS_RENDER_DIR`. What follows describes the board as it was; its tile, palette
strip, detail column, specimens, zoom and intake are the views the card uses (`Views/Looks/LooksViews.swift`).

**Looks (design taste, owner 2026-10-14; retired as a page 2026-10-20).** The ninth rail page (⌘9, `paintpalette`, after
Projects so no shortcut moved; the placement was the owner's call). A board of the looks the person likes over `GET /design`, not a Store domain:
`LooksCache` (in the page, in memory) revalidates by ETag when the page appears, after a write, when an SSE version moves
`design` or `bank` (`LooksRefresh`), and is emptied on a bank switch. `LooksBoardView` is pure over its inputs (the page
feeds it the cache; the offscreen renders feed it fixtures): the eyebrow (`Looks · 5 saved`, `… · 3 matches`), a search
field (⏎ searches by words through `POST /design/search`; the board re-ranks), *Add a look* (`PageAddButton`, DR-75;
an image file), and, when this Mac
supports it but images aren't understood here yet, one row (DR-37) saying what it is for and its download size with
*Turn on* (`POST /embeddings/install` with `part: vision`; the page polls while it installs). This is the in-context
shortcut to Settings → Privacy & data → *Understand images* and keeps its one click: on a Mac without the meaning part
it fetches both, and `vision.includesText` makes the row state the combined size ("…which also sets up Understand what
you mean") before the click. Tiles: the screenshot through
`StoredPreview` (`PictureURL` accepts `/design/…` as Cicada's own API), its colours as one strip, the site and the day
(`LooksDay`, the app's one day grammar — never the stored stamp). A look opens on the shared progressive columns (round
2, 2026-10-20): the board narrows to the triage column (one tile across) and the detail, headed by the shared
`DetailHeader`, takes the rest with its words at the focus card's measure; the Reader is the third column, DR-27 hides
the board first ("‹ N looks"), ↑/↓ move the open look, Esc closes the rightmost (the enlarged picture first). A first
read shows `ListSkeleton`, a failed one `ListErrorCard` with Retry.
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
cycle · Readout · Past nights; Last cycle's rows in words, "Rested" as a sentence, the readout as key–value rows.
**Past nights is one card per consolidation** (owner 2026-10-26, `RunCardModel` / `RunCardView`): a run that read in batches
is one card, a plain cycle one card, a decay pass or an inbox resolution none. The card says when it ran and who started
it ("You started it" / "On schedule", a catch-up's missed time), one line of what it included ("12 conversations · 3 new
pages · 18 updates · 2 questions" — the server's whole-run figures on `SleepRunRef`: `created`, `updated`,
`models`, `usageSummary`; the questions are the dropdown's own count, raised + settled, asked for each card as it
comes on screen; unknown is left out, never zero), the engine's mark and words with the
models the ledger says ran, the plan share or cost with its basis (ruling 12, `CycleUsageText`), how long it read, and
how it ended (Finished · Reading now · Paused at your plan's limit · Paused to leave room in your plan · Paused ·
Stopped · Didn't finish). A resting ring on `bgFocus`, no shadow (DR-9, DR-37; §9 2026-10-26). Opening it (one card
open at a time; only a pointer's click eases, on `CicadaMotion.groupExpand`; a key, an event-less action or an assistive press opens in one frame, `RunCardMotion`) drops down what it
consolidated, grouped under `DisclosureHeader`s — Conversations read (each opens in the Reader), New pages and Updated
pages (neutral `Tag`s, each opens its page; a page gone since shows its id), Questions raised and settled (each opens
in the Inbox) — from `GET /sleep/runs/{id}/items` or `GET /sleep/history/{commit}/items` (`SleepConsolidated`, held by
`SleepViewModel.consolidated` with its ETag, revalidated on each open, a 304 keeping it, emptied on a bank switch); a
group shows 8 rows (pages 24) then *Show all N*. *Models and batches* folds the run's models, tokens and cost with
their basis, and its batches and pauses (`RunDetailBlock`; a plain cycle's `CycleUsageBlock`). Said once (2026-10-19): a Past nights row prints its day only when it is the first of that day;
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

**Settings → Sleep, in order (D6, 2026-10-22):** the study room's preview, the Runs card (no header repeating its one
row's title, DR-38), the scenery's source and Mascot. Scheduled runs and the engine moved to Intelligence.

**Settings → Intelligence → Scheduled runs (TODO ruling 4b, owner 2026-10-16; on Sleep until D6).** One switch, *Scheduled runs may use my
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
folded by run into one card each (`PastNightItem.group` → `RunCardModel`, the run's numbers from the server's `run`, never summed from
visible rows; opened: its items from `/items`, and models, cost, batches and pauses from `GET /sleep/runs/{id}` under *Models and
batches*, cached in the view model and refetched when the run's counts, pause or end move; pages by name, the id in `.help`). A scheduled run that caught up a time the Mac slept or was off through (`sleep_catch_up`,
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
maps to; an older backend's `unprocessed` stands in (`StatusSnapshot.waitingForSleep`). At 0 there is no badge. On a
fresh install the item first appears through onboarding's *Meet your bookworm* (`MenuBarIntro`, above). The mood
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
never moves. **Files** (2026-10-29, meaning index 2): the hybrid pass alone also asks `file` and `image`
(`FindServerRows.hybridKinds`; the prefix pass never does) and a **Files** group after Sources & papers holds a
recording's or video's words — the conversation row's grammar: name, kind as the one `Tag` ("Recording" / "Video",
DR-44), "the recording's words, at m:ss" as the detail, the passage in the quote face, a kind glyph (DR-48) — and a
video's kept frames, each its own thumbnail (`FindStill`: the stored frame at the mark's height, 16:9, the Feed video
frame's continuous corner, DR-12), or **no mark at all** while it isn't on this Mac, never a stand-in tile (the
2026-10-28 "a page with no picture draws none" ruling, #512). No folds (DR-81): the group counts exactly what the server
gave (it serves only what clears its floor), so it never offers a "More…" that fetches nothing. ⏎ opens the file where
this Mac last saw it (`MediaFilePlaces`, the app's own record; the backend never has a path), ⌥⏎ shows it in Finder; a
moved file says so in a toast. Other pictures (looks, previews, stills) are not in the palette yet. Ask is a mode (⌘⏎) hosting the `AskPanel` body — the one place the app draws an Ask answer (the palette
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
page area, never over a row — offers *Restart tour* and *Finish setting up →* (a neutral button since the looks pass, so
the page's own primary stays the only one), which leaves the demo and opens onboarding
through the one door (`OnboardingState.reset(bank:)` + `AppRouter.requestFirstRun()`). The guided tour (`TourController`,
`TourLayer`) is six coach marks — the command bar, Home, the Inbox, a person card, Projects, Sleep — on floating
surfaces over a scrim on the page area; Next (⏎) · Back (←) · Skip tour (Esc); it navigates through `AppRouter` and never
acts (`TourLintTests`), opening `DemoShowcase`'s person and project only in the demo. It starts by itself on the demo's
first visit, is offered once on Home after onboarding (`TourOffer`), and replays from Settings → General, every `?` and
the banner; finishing or skipping is remembered per viewer (`cicada.tour.done`).

**The app icon (owner 2026-10-26, provisional: "for now"; DESIGN_RULES §9).** The Dock, Finder, About panel and
Launchpad show the menu-bar bookworm — the `awake` key frame of `Resources/sprites/bookworm-small.png`, without the
status item's code-drawn badge — on a graphite plate (`bgButton` `#232427` → `bgPane` `#141517`) on Apple's 824-in-1024
grid. `Art/AppIcon/make-icon.swift` (run from the repository root) writes `Art/AppIcon/Cicada.icns` (ten sizes),
`Cicada-1024.png` and the plugin's `.claude-plugin/icon.png`; `--preview <png>` writes a review sheet. From 32 px up each
art pixel is a whole (size / 32) device-pixel square, nearest-neighbour; 16@1x carries a hand-drawn 12 × 12 worm
(`smallRows`). `bundle.sh` copies the committed `.icns` into every build (`make app`, `make install-app`, the release
build) and `Info.plist` names it (`CFBundleIconFile`); nothing in the app sets the icon at runtime. The previous
book-and-glasses art stays in `docs/design/cicada-icon/v4/`.

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

**Looks pass (2026-10-23; DESIGN_RULES §9).** Before people other than the owner use the app, one sweep of first run
and every page in both themes (the ranked audit is outside the repo, with its shots). What it changed:
- **Onboarding.** Welcome's and Done's card under the study room is ringed, never shadowed (`onboardingCard()`: it sits
  in the page, DR-9/DR-10). A text button that starts a column sets its words on the column's edge
  (`TextButton(flushLeading:)`: Back, *Use an API key*, *Not you? Change*, *How to get an export*; the entity card's lone
  *Add a place to check* sits in a scroll view, which reaches out by `TextButton.inset` instead, so its hover fill is not
  clipped). A row of Sources' tiles is one height: at least `OnboardingLayout.sourceTileHeight`, growing with its
  longest caption (never cut — a consent is read before the tick), and every tile in the row grows with it;
  Chat history wears a neutral glyph (any vendor's export lands there), and so does *Personal agents* (five agents, so no
  one agent's mark).
- **Home's first run.** Getting started is the same grouped block as the tour offer and *Make it yours* (`glassCard`,
  12 pt inset, a 13 pt title; it was the focus card); the worm left its rows — the first-read line and the waiting line
  carry Sleep's `moon` glyph (DR-13: never on a row). *Make it yours* has one way to close (×) and one foot line,
  "Also in Settings → General".
- **Empty and first-run states.** Skills' empty Installed tab is `EmptyStateView` with the rail's glyph and words that no
  longer point at the header field that left on 2026-10-20; Projects' carries its glyph and says how a project is born
  now (ruling 36 D4). A bank Sleep has never read says "Nothing to read yet." over "Talk to a connected agent, or drop a
  file on me." (L10b), never "All caught up."
- **The rail.** Agents' glyph is `powerplug` (the outline twin of the solid `cable.connector`, DR-53).
- **Agents page.** The list starts under the eyebrow; beside an open agent, the list's status goes under the name
  (`ConnectionLine(statusBelowName:)`), so no name is cut to "O…".
- **Graph.** The theme reaches each page's own graph.js only once that page is ready (`Coordinator.themeCall()`, the A07
  rule): gated on the app-wide ready flag, a second web view was sent `setTheme` before it existed and latched dark —
  white labels on the light canvas.
- **Words.** The app says "conversation" where it said "episode" (Past reads, the bank menu and Privacy's bank list, the
  worm's answers and its value, the waiting line); the informational question no longer names its raw predicate; a daily
  schedule and the next-run half share the viewer's own clock (`clockTime`: the locale's short time style — "3:00 AM" in
  en_US, "03:00" in a 24-hour locale; looks pass 2); the demo bar is one line and its *Finish setting
  up →* a neutral button, so a page's own primary is the only one (DR-40).
- **Status.** Settings → General's *Keep memory working* shows a dot and "On" when it runs (it was a label with nothing
  beside it); Privacy's active bank and its three internet gates are dots and words, never the accent (DR-5).
- **Past reads.** A run's changed pages are neutral `Tag`s with their names, as a batched run's detail draws them, not
  accent-coloured slugs (DR-44, DR-54, DR-56).

**Looks pass 2 (2026-10-23; DESIGN_RULES §9).** The Sources page, which the first pass left to the connectors fix, and
three of that pass's own leftovers:
- **Sources, the list.** The root's rows run the page's width (as Inbox's and Clusters' do), so each dot-and-word status
  trails on the eyebrow's trailing edge instead of floating at the 760 pt text cap; the name and line stay capped (DR-36).
  Every two-line row wears the 36 pt `SourceLogoTile` (`.row`) at the root and beside an open source alike — the size the
  detail head and onboarding draw — and only a title-only row the dense 24 pt (`SourceCatalogRowView.tileSize`).
- **Sources, the header.** *Reading in your browser* is a compact `NeutralButton` with a `globe` glyph beside *Explore
  saved sites* and *Import a file*; as bare text it read as a label (DR-40). Same words, help and sheet.
- **Sources, the detail.** The head shows the source's mark, name and status once: the source's own row under it
  (`CalendarRow`, `ContactsRow`, `MessagesRow`, `WisprFlowRow`, a browser's row) draws only its line and buttons when
  `\.sourceDetailHeadShown` is set (`SourceCatalogDetail` sets it; `SourceRow(showsIdentity:)`), never a second, smaller
  mark and the same name; sub-sources (tab groups, YouTube history) keep theirs. Calendar's head and row read one value,
  the reader's status (`LocalReaders.calendarOn`: off and denied are Off), and the Off lines for Calendar and Contacts no
  longer open with "Not connected —" under a head that says Off (DR-38). Messages' and Wispr Flow's buttons are
  `NeutralButton`s, never native bordered ones (DR-40), with the same words.
- **The tour offer** is answered by any start of the tour, the demo's own included, and by a finish or skip
  (`TourController.start` / `finish`): it was still asking "Take a quick tour?" on Home after the demo's tour was skipped.
- **Past reads' readout** never repeats the headline: a hungry room's sentence says what Rested n% is made of, not
  "overdue" again (the hero says "N to read — overdue.").
- **The entity card** leaves out an empty page block (no paper or media card, no hero, no article) instead of drawing it
  empty with the column's spacing on both sides — about 50 pt of nothing above "What Cicada knows".

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
**The Inbox in groups (owner 2026-10-26: "super dense … grouping things would be best"; DR-40, 45, 48, 59, 60, 61).**
Under All the full-width list is one collapsible group per kind (`InboxGroups`, `InboxListLine`, `InboxGroupHeader`):
the kind's tab word and its count, and *Review one at a time* — the quick review below, the group's one action. There is
no answer-all: a header only opens or closes (a click eases, a key is one frame — *One fold motion* below), and every answer is still one question through
the card or the review, held for the Undo window. Groups sit where their most urgent question would (the G115 order);
past `InboxGroups.openFirstUpTo` (12) questions every group starts closed, so a full inbox reads as its kinds and counts;
the person's open/closed choice holds for the memory, and the open question's group is always open. Inside a group (and
under a kind's tab) two or more questions about one page sit together under the page's name, said once (`InboxPageHeader`;
the rows leave the name out). The order the groups draw is the list's walk (`InboxViewModel.visible`): ↑/↓ and the next
question after an answer follow the screen; the narrow columns draw the same order flat. Under a kind's tab the review
row shows that kind's review only (say it once).

**Inbox v2 (owner 2026-10-26: "fix how dense the inbox looks … I don't really get the confirmation of links … as are
possible duplicates … When I open the drop-downs, it can be smoother"; DR-35, 38, 39, 40, 42, 43, 52, 59, 60, 61, 62, 65,
66; §9 2026-10-26).** *Words:* a kind is named in a person's words (`InboxKind.label` — Fading, Conflict, Question,
Possible duplicate, Disagreement, Wording, …; the wire values never change), a group by its plural (`groupTitle` —
"Fading pages", "Possible duplicates"), and an open group starts with one plain sentence of what its questions ask and
what the answers do (`InboxGroupExplainer`, `Copy.Inbox.kindExplainer`). *Density:* the kind's glyph leads its header
once and the rows under it leave theirs out (the slot stays, so the questions line up); groups sit `spacingLG` apart;
*Review one at a time* shows only while its group is open, so a closed inbox is kinds and counts alone. *Motion:* a
group's body is one block (`InboxListBlock`) that grows out of its header and fades in (`disclosureReveal()`), the
groups below easing down with it. **Possible duplicate** (`MergeBody`, `MergePair`): the two sides side by side — "Name
from a conversation" and "Existing page", each with its `EntityPicture`, type and the graph's one-line summary, or "No
page yet" for a name below the promotion bar — then what each answer does (Merge files the name under the existing page
as another name, or folds its page into it; Keep separate is remembered; each answer can be undone in its window), then
**Merge** (the one neutral button), *Keep separate* and *Skip* (text buttons). Describing it, merging with another page
and the Keep-as-canonical picker with its "A → B" line wait under *Something else* (open from the start when Sleep named
no page); a page typed there becomes the existing side ("Page you named", found by id or name) and Merge's sentence names
it, so the card always shows what will be sent; every resolution sent is the one it sent before. **Confirm N links** (`WhereToCheckReviewCard`,
`WhereToCheckWords`): one sentence of what the card is ("Nothing is used until you confirm it"), each page once with its
picture and name (a click opens it), and under it each waiting link: its label, what it is and where ("GitHub profile ·
github.com/…"), why it is there ("You mentioned it in a conversation.") and what confirming changes ("their picture and
updates can come from here" for a person's own profile, "its logo and updates come from here" for a site on any other
page). **Confirm** (neutral) and *Not theirs* / *Not this one* (text) answer one link, as before; past three pages the
rest wait under *N more pages*.

**One fold motion (inbox v2).** `DisclosureHeader` and `DisclosureButton` toggle through `DisclosureMotion`: a click
eases on `CicadaMotion.disclosure` (drawer curve, 240 ms open, 180 ms close), a key — the event running the action is a
key press — or an assistive press (`AssistivePress`) lands in one frame (DR-60), and Reduce Motion keeps a ~100 ms fade
(DR-66). Content a fold inserts takes `.disclosureReveal()`: an animatable `DisclosureReveal` reports its share of the
content's natural height (`DisclosureRevealLayout`) and fades it in, clipped only while it moves. The Inbox's groups and
settled sections, the entity card's sections (`CardDisclosure`), *Confirm N links*' *N more pages*, the duplicate card's
*Something else* and onboarding's two folds use it; every other `DisclosureHeader` caller eases its layout through the
header without a change (Projects keeps its own `groupExpand`, the inner transaction winning).

**The quick review (owner 2026-10-19)** goes one kind at a time inside the Inbox page, never a new window. Above the
questions at full width under a kind's tab (`InboxQuestionList`'s `header`; under All each group's header carries it),
`InboxReviewEntriesRow` lists one text button per kind with something to review — "Fading pages · 49", then Folds, Conflicts and Questions with theirs (`ReviewEntries`, counts
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
space the page gives them, with no card. **One component per thing (consistency pass, 2026-10-20; DR-39, DR-40,
DR-43, DR-53, DR-58, DR-74):** a section that folds is `DisclosureHeader` and any other fold draws `DisclosureChevron`
(`Views/Common/Disclosure.swift`: `chevron.right` turned a quarter when open, `icon(.disclosure)` 10 pt semibold);
a side column that shows one thing opens on `DetailHeader` (the focus-card head line of a project or a saved item is
the one other head); a list page's first read is `ListSkeleton` and its failure `ListErrorCard` with Retry; a page's
buttons are the four kinds, the native bordered styles only in Settings and setup sheets; a column's edge is
`columnEdge()`; a stored day is shown through `RelativeDay`. **Round 2 (2026-10-20; DR-48, DR-53, DR-75, DR-76):** a
list row's fill is `rowHover` / `rowHoverFill` (`Views/Common/RowHover.swift`: `bgSelected` over `bgHover`, only the
pointer's hover eased, so a key never animates); a page adds through `PageAddButton` in its eyebrow (Sleep's tab-row
`+` the one exception); a field on a page, a column or a page's own sheet is `cicadaField` (`bgBase`, the input ring,
the accent ring while focused — the field tracks its own focus unless its caller passes `isFocused:`; the field draws its
own prompt in `textTertiary`); a fold whose only control is its glyph is `DisclosureButton`; Skills and Looks sit on
`ProgressiveColumns`; Sources' lists read in words over `ListSkeleton`, no spinner. `DesignConsistencyLintTests` holds
all of these. **Round 3 (2026-10-20; DR-12, DR-16, DR-43, DR-44, DR-45, DR-48, DR-53, DR-58, DR-70):** the menu-bar
menu's words, hover text and the bookworm's moods live in `Copy.MenuBar` / `Copy.Mood` (`Theme/Copy+MenuBar.swift`), its
next run in `RelativeDay`'s day words with the viewer's clock ("Next sleep: Today, 3:00 AM"; AppKit draws the rows
themselves); onboarding's "still coming in" is words alone and the export walkthrough's vendor switch is `TextTabs`
with each vendor's mark (`TextTab.mark`); the ⌘K palette waits in words — the footer's "Searching conversations…"
with no bar over the divider, Ask's "Asking your memory…" over `ListSkeleton` (above the dimmed answer when it asks
again) with no spinner in the field — its row type is a `Tag`, its recent questions are rows on `rowHover`; the
Reader's "Noted from this conversation" row is on `rowHover` (the current row a selection; the cited span's wash is
`CitedSpan`'s, unchanged). Every rounded rectangle draws through `CicadaTheme.shape` (continuous), a `Text` at a ladder
size uses its type token and a glyph at 14/12/10 its icon role, and a padding or spacing equal to a step is the
spacing token. `DesignConsistency3LintTests` and `ContinuousCornerLintTests` hold these. Pixel sprites carry their provenance in
`Resources/sprites/sprites.manifest.json` (script, source, sha256), checked by `SpriteAssetTests`. **Type:** SF only. `displayFont(size:italic:)` is SF Pro Display
semibold (tracking −0.3 at 20 pt, −0.4 above, floor 20, paired and counted by `FontLiteralLintTests`), `quoteFont` SF
15 regular, one `SectionLabel` (11 medium, sentence case, never mono or tracked — `SectionLabelLintTests`), monospace
only on `MonospaceLintTests`' allowlist (code, commands, paths, keys, ids), and `CitedSpan` the washed, underlined span,
read by the Inbox's quote and the Reader's turns since DS-2 (a mention found by name is its semibold, unwashed case);
its tint (`wash` / `washSoft`) is neutral ink since 2026-10-20 — an accent fill behind words read as a text selection —
and the accent stays on the current span's underline; `washSoft` is `wash` (white 10 % / black 7 %) since the review
of #383, so another cited span is as findable as the current one in the document view, and that view's blocks say
"Cited here" / "Also cited here" to VoiceOver (`ReaderTurnView.accessibilityWords`). **Motion:** `CicadaMotion` (nil under Reduce Motion) is the only place outside
`SleepMotion` a duration is spelled; `hoverLift()` for things that open, `iconHover()` for glyphs; a keyboard action
never animates. Sprites play per frame from their sheets within `CicadaMotion`'s sprite caps (ruling 18).

**Links show as what they are (owner rulings 2026-10-14; Notion's model, owner 2026-10-26; DR-5, 9, 12, 13, 16, 32, 37,
52, 53, 58, 61, 63, 69, 71; §9 2026-10-26).** A link on a page draws the way its markdown title asks (`storage.md`, the
link-title grammar; `LinkGrammar` in `LinkView.swift`, one fixture with the backend), and a link that asks for nothing
draws by context (`LinkGrammar.drawn`, the fixture's `drawn` cases): **inside a sentence a mention, alone on its line a
bookmark, never an embed** — the owner pointed at his own editor (research-hub, TipTap) as the look to match. In the
article (`WikiArticle`/`WikiInline`): a **mention** — a plain link in a sentence, `"mention"`, or a block view written
inside a sentence — reads as the site's icon (15 pt, the tab-icon corner, `MentionIcon`; the icon only where the page's
icon route serves it, `LinkFact.icon`, else a tertiary globe — a `Text` cannot hold the ring monogram), the site in
`textTertiary` (a `WikiInline.SitePart` run carrying the link's URL), then the title in the primary ink and the row
face's medium weight, underlined in the tertiary tone (`WikiInline.MentionTitle`; both restyled when the row is drawn,
`themed`, so a cached article follows the theme; the icon goes in at draw time, `WikiInline.composed`, so the line stays
one selectable, wrapping `Text`); a link the person chose as **URL** (`"url"`) reads as its words, accent and underlined;
a bare URL or `<URL>` is a live link that reads as its address (`example.com/guide` — `LinkViewTests` shows Foundation
links it); a view word is never shown. A link alone on its line that draws as a block — a plain link alone in a paragraph
or on any bullet (Sleep's own `## Links` shape `- [T](url) — note` among them; #475 did only `## Links`), or a link naming
a block view — is a row of its own (`WikiRow.Kind.link`, `WikiArticle.blockLink`; nothing is written to the page) drawn by
`LinkBlockView`: **bookmark** → `BookmarkCard`, research-hub's measured card: 10 pt corner (`cornerRadius`), the ring,
`bgFocus`, the stored picture left at full height (220 × 124 pt) when ≥ 440 pt wide and on top when narrower; words padded
11/14/12 with 5 pt gaps — title 14 medium, two lines of description at 12, then mark · address · one date ("Read Oct 2",
else "Saved Oct 2", else "Not read yet") at 12 tertiary; **embed** (only when chosen, and only for what can be embedded,
`LinkEmbed`) → `LinkEmbedView`: a video with a provider's own player (`VideoRef.kind == .embed`) shows its stored still
behind a play button and loads the player URL `VideoRef` derives in place only on that click, never autoplaying (G162,
R11); a PDF (a `.pdf` path or an arXiv `/pdf/` link) is a card with the document's mark, its words and "PDF", nothing
fetched; an `"embed"` on anything else keeps research-hub's old reading, a screenshot; **screenshot** → `CaptureCard`
(16:10, the caption below the picture never over it: "Captured Oct 14, 2026 · 3 months ago", or "Saved to Looks Oct 14 ·
today" while a saved look stands in, "· nearest to Oct 14" for a pinned day with none that day; ⤢ opens the lightbox with
the date line); **captures** → `CaptureStrip`; **look** → `LookSwatch` (the crop, `LooksPaletteStrip`, site · "Saved to
Looks Oct 14"). Each degrades one step and says so: "No capture of this page yet", "No captures of this page yet", "No
saved look of this page yet" (DR-32). ⧗ Site exploration's dated captures (the screenshot from a capture, the gallery,
"Changed since you saved it", a gone site, the Reader's "How it looked when you saved it", ⌘K's site mark) wait for that
pipeline; until then `captures[]` is empty and a look's screenshot of the same URL stands in. Every fact comes from `GET
/entities/{id}/links` through `LinkFactsCache` (in memory, not a Store domain); the app fetches nothing of the web to draw
a card: a click opens the saved item's page when the backend matched the URL to one, else the browser, and ⌘-click
always opens the browser (`LinkOpen`). **Each link's view menu** — never only on hover: a card carries a ⋯ menu in its
corner (`LinkViewMenu`, compact, on the card's own fill), a right-click on a card or on any line with links opens the same
choices (`LinkViewMenuItems`; titled by each link's words when the line has several), and the line's 🔗 in the gutter
shows on hover *or* while it holds keyboard focus (it stays in the focus order) and opens `LinkLinePopover`: each link's
bookmark card, then "Show as · Bookmark ▾", ↗ and Copy link (DR-53); VoiceOver reaches it as *Links on this line*
(`LineLinksAction`). The menu is one native inline picker, so the view the link draws as now is checked
(`LinkCardModel.current`): **Mention** and **URL** always; **Bookmark** for a link alone on its line; **Embed** ("Embed
video" for a video) only alone on its line and only when `LinkEmbed` finds something; then Screenshot, Captures and Look
only where Cicada has a picture, a capture or a saved look (`LinkCardModel.offered`). Choosing one is `POST
/entities/{id}/edits` with the link's token as `old` and the same link with its view word as `new` (`LinkCardModel.token`
— the choice is always written, even where it matches today's default, so a later change of the default never undoes
it), `all` and `pinned`, committed under the person with the reason "Shown as a bookmark." / "Shown as a plain link."
(owner ruling 4: the choice is memory, in git, visible to every agent; undo is the page's history), and the card re-reads
the page (`GraphViewModel.reloadEntity`) so the link redraws in its new view at once — before, it said "Saved" and kept
the old view until the page was reopened. `PageLinkRow` (Where
this comes
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
other party's left in a `chatBubbleOtherFill` bubble with the resting ring (owner 2026-10-20: both sides bubbled; each
bubble hugs its words and leaves 48 pt on its far side; a long message's pieces read as one bubble, its ring drawn open
where they meet) — the side read from each turn's written marker, not its role, because a relayed
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
built layout is memoised per document, target, unfolded set, jump and citations (`LayoutMemo`). Everything else keeps the document view. **What made it a conversation (2026-10-20, `turn_extras`; DR-11, DR-38, DR-40, DR-44, DR-60):** a turn's
`extras` ride its message (`ReaderChat.Extras`, `Piece.part`): a reply's line above the first piece — "Replying to Sam:
“…”", a `TextButton` that scrolls its target to the top in one frame, or "Replying to an earlier message" in words when
the target is not in this sitting; "Forwarded from …" there too; under the last piece, attachments as `Tag`s ("Image ·
stove.jpg · 1.3 MB", "Generated image", "Ran code 2 times") and reactions as `Tag`s, one per emoji with a count, who
reacted on hover (`.help`, "You and Sam reacted 😂") and in VoiceOver; "Edited" in words. A Messages turn's
"[image: …]" words leave the bubble when its chips say them (`ReaderChat.withoutAttachmentNames`; an attachment-only
message is its chips alone). An unsent message is a centred line where it was ("You unsent a message"). Thumbnails are
not drawn yet: every attachment is a chip with its kind and name. An episode saved before extras has none and reads as
it always did. **A cited passage never looks selected (owner 2026-10-20, DESIGN_RULES §9):** a message holding a cited
span carries a quiet "Cited" marker beside its bubble, in the room the bubble leaves (`ReaderCitedMarker`: a 2 pt bar,
the accent for the landed span and `quoteRule` for another cited one, `ReaderChat.citedMark`), said first by VoiceOver
("Cited here. …" / "Also cited here. …", `ReaderChat.accessibilityLabel`); the words keep only the neutral tint and
the current span's underline. A navigator step or a "Noted" row re-lands by its trigger (`ReaderLandingMotion`, the
event read through `LooksZoom.trigger(for:)`): a pointer's hides the wash while the column moves, shows it once landed
(in one step — the passage's marks are attributes of its string and never fade, see below) and rings the landed bubble briefly
(`citedEmphasis`, held `rowHighlightHold`, faded `rowHighlightFade`); a key's (⌥↑ / ⌥↓, ⏎) lands in one frame with
the wash already there and no ring (DR-60); a VoiceOver press on the chevrons or a row lands as a key does, whatever
event came last (`ReaderJumpAsk`, through `IconButton`'s `accessibilityPress` / `AssistivePress`). `ReaderBubblesTests`. A turn is
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

**Settings → Privacy & data (owner, 2026-10-14; G182 phase 3, EmbeddingGemma 2 owner 2026-10-09, G133, G195 frame).**
A section in the Cicada group between Privacy & data and Sleep (`SettingsSection.searchFiles`, a new case in 2026-10-14): sidebar
*Search & memory* (*Search & files* until B1), page title *What Cicada can look through* (`SettingsSection.pageTitle`; the header shows it, the
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
- No *Advanced* (settings defaults, owner 2026-10-22). The *Search version* picker, the larger version's account sheet
  and *Rebuild search* left the app: *Understand what you mean* is the one choice, a version already chosen keeps being
  used, and the index rebuilds itself. On the command line: `cicada index use <model>`, `cicada index install <model>`
  (the larger version's account key), `cicada index rebuild`. A memory built with the larger version elsewhere says so
  and offers *Turn on* for the sharper version, so the row is never a dead end. `SearchModelLogic` keeps the picker's
  rules (a pick is never the consent; the size is said first) pure and tested, unread by the page but `pollInterval`.
A failed re-read on the default view is the page's own sentence, never the backend's diagnostic; *Turn on* is dimmed
with the reason while any download runs (the Looks shortcut included), never an enabled click that answers 409.
`SearchFilesTests.testDefaultVisibleWordsAreNeverTechnical` holds every default-visible string (`Copy.SearchFiles.
defaultVisible` and every state the two rows can render) free of model, embedding, index, vector, token, runtime and
checksum; the hidden Settings-search keywords keep the technical words so "embeddings", "index" or "search version"
still land on *Understand what you mean* (`SettingsIndex`). The backend
writes its catalog labels, steps and errors in the same words (`api/tests/test_search_words_are_plain.py`). Folder
channels index on this page, and a saved folder row opens it (`ChannelActions.settingsSection`). *How things fade* (Memory's card until B1) closes the page under the `page:memory` anchor. Not yet (G195): the search-only depth, kinds per folder, reading N of M files and
the idle/on-power pause — none is rendered until something computes it.

---
