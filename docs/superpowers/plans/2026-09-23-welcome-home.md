# Welcome and Home (Track I, part b) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A person who has never heard the word "episode" opens Cicada and sees **one** screen: a
painted meadow, "Hello, Ada. / *Here's what Cicada found on this Mac.*", a short checklist of the
AI apps and browsers that are really here (the ticks are the consent), a place to drop a chat
export, the four ways a memory can be read — each saying how it is paid for, none of them blocking —
and one muted green pill, **Start remembering**, with a line under it that says exactly what it will
do. Start saves the name, lands on a new **Home** page (⌘1: "What would you like / *to remember?*",
a search field, then Today / Needs you / Last read — every number once, each a link to the page that
owns it), and continues there as a **Getting started** card whose rows fill in live, whose first
read is one click, and whose last question asks — honestly, ruling 4 shown — whether Cicada should
keep reading on its own. A person still waiting on an export can ask to be reminded; the reminder
works with notifications off, because the Feed, the menu bar and the card say it too.

**Architecture:** App only — no backend change, no new endpoint, no new Store domain, no ETag recipe
touched. Every decision is a pure function with a table test (`HomeFigures`, `LinkPaste`,
`HomeBandLayout`, `WelcomeName`/`WelcomeTicks`/`WelcomeLayout`/`EngineChoiceLine`,
`GettingStartedState`, `GettingStartedProgress`, `FirstReadStep`, `ScheduleChoice`, `ExportWaits`);
the one side-effecting sequence — what Start does — is `SetupRunner` executing part a's
`OnboardingFlow.plan` through an injected `SetupEffects`, so its order and its failure rules are
tested without a window. Views are thin renderers over those. Part a's pieces are consumed, never
forked: `LocalInventory`, `FoundPolicy`, `FoundRow`, `AgentConnect`, `ScheduleHonesty`,
`EngineReadiness`, `OnboardingFlow`, `HomeLayout`, `MeadowPill`, `IntakeRouter`; the palette's
`FindPanelBody` is Home's field.

**Tech Stack:** SwiftUI + XCTest (`app/CicadaApp`, Swift 5 language mode, macOS 14 floor),
`UserNotifications` (Task 5 only), markdown docs.

**Binding sources.** Spec `docs/superpowers/specs/2026-09-23-round3-meadow-reach-provenance-design.md`
decisions **12–15**. Design `docs/superpowers/specs/2026-09-23-round3-design-onboarding-intake-home.md`
§4 (Welcome, Getting started, consent), §5.3 and §5.5 (honesty, reminders), §6 (G108 Home),
§7 (components), §8 (data sources), §10–§11 (rulings, owner decisions answered by default),
§12 **T8–T11** (this plan; T12 is the orchestrator's live pass), §14 (not verified). Part a:
`docs/superpowers/plans/2026-09-23-intake-onboarding-a.md` (its R-IA rulings hold; R-IA4 hands F2
to this plan). The palette: `docs/superpowers/plans/2026-09-23-find-palette.md` hand-off 2.
Backlog rows edited here: **G108** (ruled), **G117**, **G54**, plus one line on **G125** (R10's
second narrow amendment). Standing rulings: no prices or token counts anywhere in the app
(2026-09-03), **ruling 4** (a scheduled cycle never spends Claude or ChatGPT plan quota), the privacy
rule, portability, Meadow R-M2/R-M4/R-M5/R-M6, G107 (no duration estimates), G125 R10.

**Owner, 2026-09-23 (the brief):** "i want you to also work on the onboarding. Make it seamless" and
"friendlier towards the general public … nature and technology in harmony" (reference: a sky/meadow
landing page, a serif headline with an italic second line, a muted green pill). **Display font
note:** the owner rejected the ornate display serif; Track F1 is switching `CicadaTheme.displayFont`
to SF Pro Display behind the same API. Every headline here calls `CicadaTheme.displayFont(size:italic:)`
and nothing else — never a named font — so the switch lands here with no edit.

---

## What the code actually does today (verified against `dev` @ `a27e2ca`)

App paths are relative to `app/CicadaApp/Sources/CicadaApp/`; tests to `app/CicadaApp/Tests/CicadaAppTests/`.
Line numbers drift as tasks land — re-read the cited code before editing.

**Navigation.** `Views/Sidebar/SidebarView.swift:13-48` — `AppTab` has six cases, Graph first;
`restored(from:)` (`:23-32`) maps nil/empty/unknown to `.graph`; `icon` (`:34-43`) is an exhaustive
switch; the ⌘ slot is the index in `allCases` (`:134-135`). `ContentView.swift:6` defaults
`selectedTab = .graph`, `:10` the `@AppStorage("cicada.selectedTab")` default, `:110` restores on
appear. `otherTabContent` (`:339-368`) is the other exhaustive switch; the graph stays mounted
under every tab (`:327-337`, the G109 lesson). `SidebarTabTests.swift:9-11, 37-41, 50-57` pin six
rows, Graph-as-fallback and "⌘1–6". `Search/PaletteActions.swift:26-29` lists "Go to <tab> ⌘n" from
`allCases`, so it follows automatically.

**The palette (G136, merged PR #80).** `Views/Find/FindPanelBody.swift:8-14` — `Placement { palette,
page }`, "exposed on its own so the upcoming Home page … hosts the same search field in-page"; the
body is field + divider + rows/Ask + footer, always (`:19-37`); Esc runs `model.escape()` and closes
only when it returns true (`:34`); the field focuses on appear (`:35-36`); ⏎ is `model.submit()`
(`:51`); the placeholder is fixed (`:45`). `Search/FindPaletteModel.swift:30-33` builds its own
`AskViewModel`; `remember` (`:171-179`) writes the `.quickRecents` cache. `ContentView.swift:794-806`
`FindIndexTask` rebuilds the one instant index. `Support/FindCommands.swift:77-90` `PaletteToggle`:
ignore under first run, close when open and plain, else open. `ContentView.swift:208-219` consumes
the request. Only the palette's model is in the environment (`CicadaApp.swift:112, 131`).

**Onboarding today.** `ContentView.swift:143-145` presents `FirstRunSheet` as a `.sheet`;
`evaluateFirstRun` (`:196-206`) and `FirstRunGate` (`Support/FirstRunGate.swift:38-45`, "unknown is
never empty") decide; `router.pendingFirstRun` (`:171-175`, `Support/AppRouter.swift:86-89`) is
Settings → General's "Run setup again" (`Views/Settings/SettingsGeneralView.swift:105-121`, which
resets `OnboardingState` first). `Views/Onboarding/FirstRunSheet.swift` — four steps; **F2** lives at
`:77` (`IntegrationsView(onHandOff: finish)` marks the bank onboarded before the Sleep step);
`tryDemoBank` (`:150-161`); `finish` marks the LIVE bank (`:184-187`). `OwnerIdentityStep.swift:56-68`
prefills from `GET /settings/owner`. `OnboardingSleepStep.swift:13-26` `OnboardingSchedule` (the
promise ruling 4 made false). Three `.red` literals: `FirstRunSheet.swift:111`,
`OwnerIdentityStep.swift:45`, `OnboardingSleepStep.swift:85`. `IntegrationsView`'s `onHandOff`
(`Views/Settings/IntegrationsView.swift:13-18`, called `:198`) has `FirstRunSheet` as its only
non-default caller. Copy: `Theme/Copy.swift:424-457` (`onboardingChannelCaption`,
`onboardingTryDemoBank`, `onboardingCreatingDemoBank`, `onboardingRunNightly`,
`onboardingStepTitle`). Tests pinning them: `OnboardingStepTests.swift`, `OnboardingScheduleTests.swift`,
`SettingsSectionTests.swift:64-82` (FirstRunSheet frame lines), `CopyConstantsTests.swift:79-83`.
`PUT /settings/owner` writes `handle`/`email` from the request, so **omitting them clears them**
(`api/routers/settings.py:31-59`; client `Services/APIClient.swift:2027-2034` omits nil keys).

**Part a, consumed here.** `Support/FoundPolicy.swift` (`defaultOn`, `order`, `startSummary` — no
count → "your bookmarks"); `Support/OnboardingFlow.swift` (`plan(name:pickedEngine:ticked:mode:)`,
`shouldContinue`, `demoSteps`); `Support/LocalInventory.swift` (`items`, `wiring`, `isChecking`,
`refresh`, `live(watcher:)`; Safari blocked vs absent by the errno of an `open` that reads nothing);
`Support/AgentConnect.swift` (the allowlist, `CICADA_CAPTURE=off`); `Support/ScheduleHonesty.swift`
(`engineLine`, `enabledModes`, `preservedMode`); `Support/EngineReadiness.swift`;
`Support/HomeLayout.swift` (`showsWaitingInToday`); `Theme/MeadowPill.swift`;
`Views/Common/FoundRow.swift` (no tick yet, `:21-31`); `Views/Intake/OnThisMacStrip.swift:93-128`
(the one turn-on implementation, private); `Support/IntakeRouter.swift` — `IntakeOrigin` already
names `.welcome`, `.home`, `.reminder`, `.onboardingRow` (`:8-22`); the observed state and
`sniffedPreview` (`:189-204`); `present` (`:221-226`), `accept` (`:230-247`), `sniff` (`:269-294`),
`commit(urls:from:)` (`:374-393`, chat files only — a saved file would 400 at `/intake/import`,
R-IA32); `Views/Intake/IntakePanel.swift:268-305` `VendorExportRow` (private), used at `:54`;
`chooseFile()` (`:98-106`). `Models/Intake.swift:170-189` `ChatVendor`.

**Engine picker (Track E, on dev).** `Views/Settings/EngineCard.swift` commits every click through
`SleepEngineViewModel.set` (`:108-114`, `:229-236`), shows Auto + four candidates, model field,
overage toggle and both previews; `Views/Settings/EngineOption.swift:18-38` decides selectability
and state captions — no cost-model line exists anywhere. `ViewModels/SleepEngineViewModel.swift:30-40`
`set` never throws; it sets `errorMessage`. **An untouched chooser is not `auto`:** with no
`CICADA_LLM_MODE` and no pref, `GET /sleep/engine` reports `mode: "byok"`, `source: "default"`
(`api/services/sleep_engine_prefs.py:43-57` `_configured_choice`; `engine_select.py:147-162`
`configured_mode`; the module docstring's rung 4, `:21-24`: "byok (the shipped default, i.e.
nobody chose)").
`EngineReadiness.resolve` reads `preview.manual`, so it reports what that default really resolves
to. (Part a's `EngineReadiness` docstring says "stays `auto`" — a stale note this plan does not
repeat.)

**Art (M1).** `Views/Meadow/MeadowArt.swift:24-25` — `heroDay` ("the onboarding hero — bundled here,
drawn by the onboarding track"), 2400×1400 JPEG with a `-dark` sibling (a moonlit meadow); clouds and
grass sprites; `Views/Meadow/MeadowBackdrop.swift` (`MeadowSky`, `DriftingCloud` ≤ 8 pt drift,
`GrassEdge`). `MeadowPlacementLintTests.swift:10-14`: a painted component may be named only inside
`Views/Meadow/` or an allowlisted file — so both bands are composed **in `Views/Meadow/`** and the
data-bearing pages never name a needle.

**Home's data exists.** `store.sourcesOverview` rows carry `activity` keyed by UTC day
(`Models/SourceOverview.swift:32-38`); `sparklinePoints(activity:days:today:)`
(`Views/Sources/ActivitySeries.swift:51-58`, the UTC window is private there). `store.visibleInbox`
(`Sync/Store.swift:55`). `store.status` → `StatusSnapshot.episodes.unprocessed`, `lastSleepAt`
(`MenuBar/BookwormState.swift:109-131`); `deriveBookwormState` (`:166`). `sleepVM.history` /
`historyLoaded` / `loadHistory()` (`ViewModels/SleepViewModel.swift:26, 33, 281`), not disk-cached;
`SleepHistoryEntry` (`Services/APIClient.swift:863-883`: `date`, `filesChanged`, `kind`,
`entitiesCreated/Updated`). `SleepStatusResponse` (`:684-737`: `stage` counts completed stages,
`episodesTotal`, `episodesQueued`, `debt.hasRunBefore`, `readByOrigin`/`queueByOrigin`).
`triggerManually` (`:312`), `updateSchedule` (`:350`). `router.pendingInboxItem`
(`Support/AppRouter.swift:99`) is how the palette lands on an inbox card.

**Reminders.** Nothing imports `UserNotifications` (grep). `Support/DockOpenQueue.swift:25-33` is the
only `NSApplicationDelegate`. `MenuBarManager.swift:195-251` rebuilds the whole `NSMenu`;
`statusItem?.menu = menu`, no delegate. `Views/Feed/FeedView.swift:29-31` mounts
`ConnectedChannelsStrip` above the search row. The app's bundle id is set by `bundle.sh:77`; under
`swift test` there is no `.app` bundle, and `UNUserNotificationCenter.current()` raises when the
process has no bundle proxy.

**Baselines on `dev` @ `a27e2ca`:** backend **2225 passed** (brief, 2026-09-06; part a measured
2273), Swift **1012 executed, 0 failures** (part a measured 1141 on its branch; PR #80 added more),
graph JS green. **Re-measure on this base before blaming a diff** — this plan changes no Python.

---

## Global Constraints

- Work ONLY in `<worktree>` = `<repo>/.worktrees/ib` (branch `feat/welcome-home`, based on `dev` @
  `a27e2ca`). Every shell command is `cd <worktree> && <cmd>` with the ABSOLUTE path (zoxide hijacks
  a relative `cd`; ignore its stderr warning). No unquoted `--include=*.ext` (zsh globs it) — use
  `rg` or quote it.
- NEVER read `<repo>/memory` (any bank), `~/.cicada`, `~/Library/Safari` or `~/.claude/projects`.
  Test fixtures are synthetic (`alpha-project`, `bob-example`, `example.com`, `Ada Example`).
- Swift: `cd <worktree>/app/CicadaApp && swift build 2>&1 | tail -5` must succeed and
  `swift test 2>&1 | tail -20` must report **0 failures**. A focused run while iterating:
  `swift test --filter <TestClass> 2>&1 | tail -20`. Graph JS: `cd <worktree> && node --test
  app/CicadaApp/Tests/graph/*.test.js`. Python (Task 6 only, as a guard — no Python changes):
  `cd <worktree> && api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider` → 0 failures;
  if `test_agent_provenance.py::test_a_decay_only_change_lands_in_its_own_cicada_authored_commit`
  is the ONLY red, re-run it alone and report both results. SourceKit diagnostics naming OTHER
  worktrees are noise.
- NEVER run `make dev`, `make install-app`, `swift run`, or launch/kill the Cicada app or the launchd
  backend — the owner's installed app is live; the orchestrator installs and live-checks at the end.
- Never `git add -A`; stage named files only. Never commit `memory/`, `logs/`,
  `.claude/settings.json`, `api/.venv`, or `*-report.md`. No push, no new branches or worktrees, no
  subagents. Ignore Devin/PR comments.
- **Do not touch** `Views/Sleep/**` (Track Z), `Views/Capture/OriginIconography.swift`,
  `Views/Common/LogoImage.swift`, `Views/Common/OriginMark.swift` (Track L — consume only), any file
  under `api/`, `mcp/` or `install.sh`.
- **No LLM at capture; no new engine call anywhere in this plan** except the person's own *Read now*
  (`sleepVM.triggerManually()`, G125 R10's second narrow amendment, R-IB19). Home's field hosts the
  palette's existing Ask mode unchanged (⌘⏎ / the Ask row call `/ask`, the person's own act); no
  test ever activates it (the `FindPaletteTests` header rule).
- **Nothing is spawned but part a's `AgentConnect`** (its allowlist pinned to this checkout, every
  child with `CICADA_CAPTURE=off` and the provider keys scrubbed); the Welcome and Getting started
  reach it only through `FoundTurnOn`, and only after the person's tick and Start (spec decision 14,
  D-1). The backend never writes a harness root.
- **Fonts** through `CicadaTheme.font(size:weight:design:)` or the named tokens; display type only via
  `CicadaTheme.displayFont(size:italic:)` at ≥ 22 pt; never `.custom(` or a font name.
  **Durations** only in `Theme/CicadaMotion.swift` (`MotionLiteralLintTests`). **Glass** only in
  `Theme/LiquidGlass.swift` (`LiquidGlassLintTests`) — this plan adds none. **Colours** only as theme
  tokens (`ThemeTokenTests` bans the state hexes; `.red` is banned under `Views/` by the new
  `NoRedLiteralLintTests`, Task 4 — design §13). **Counts** through `UsageFormat.count(_:locale:)`
  (`CountLiteralLintTests`, whose scope this track extends to `Views/Home/` and `Views/Onboarding/`). **Marks** through `OriginIconography.logoName(for:)` →
  `LogoImage.platformTile` / `OriginMark` / `VendorMark`, never recoloured. **Painted art** only
  under `Views/Meadow/` (`MeadowPlacementLintTests`); text never directly on paint.
- **No prices, no token counts, no duration estimates, no percentage of plan quota** on any surface
  (2026-09-03, G107). A cost *model* in words ("Uses your plan") is the G117 2026-09-04 ruling and is
  required.
- **Reduce Motion:** every animation is a `CicadaMotion` value (nil under Reduce Motion); symbol
  effects carry `.symbolEffectsRemoved(reduceMotion)`; drifting art is `DriftingCloud`'s own pause.
- **Portability and privacy:** no owner name, no author-machine path in code, plans, commits or PR
  bodies; the Mac account name is read at runtime (`NSFullUserName()`), never written anywhere but
  the owner PUT the person confirms with Start.
- **ETag ship-together:** no payload changes and no Store domain is added; if a task finds itself
  wanting one, stop and say so.
- **Copy** lives in the new `Theme/Copy+Welcome.swift` (`extension Copy`), so this track never edits
  the lines sibling tracks append to `Copy.swift`; labels ≤ 60 characters and never "claim" (a new
  `CopyConstantsTests` case, Task 1).
- Docstrings explain **why**, citing the G-row, the design section (§…, F…, W…, H…) or this plan's
  ruling (R-IB…). Match the density of the files touched.
- Every commit ends with the line `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

---

## Rulings (binding)

The design's §10 rulings and part a's R-IA1…R-IA33 hold as written. Everything below is a choice
the brief or the design left open, decided here with its reason, so no task re-opens it.

- **R-IB1 — Task order: Home, the machinery, Getting started, the Welcome, reminders, docs.** Start
  lands on Home and continues in its Getting started card, so both must exist before the Welcome
  swaps in; built the other way round, a Start would report its rows to nothing. Tasks 2 and 3 are
  dormant until Task 4 records a bank (no bank has a Getting started record before then), so every
  commit is shippable. F2 (R-IA4) dies in Task 4 with `FirstRunSheet`; the track merges as one PR,
  so spec decision 15's "ship first" is met at merge, before any new onboarding UI reaches `dev`.
- **R-IB2 — `AppTab.home` is the first case (⌘1); raw values never move.** `restored(from:)`: nil,
  empty or an unknown value → `.home` (a fresh install, spec decision 12); a stored `"Graph"` →
  `.graph` by its raw value (nobody who lives in the graph is moved); the retired mappings are
  unchanged (`"Connections"`/`"Connect"` still land on Graph, where they always did). D-3b
  (always open on Home) is **no**: relaunch restores the last tab.
- **R-IB3 — Home is rebuilt on a tab switch; its field text is not.** The graph stays mounted
  because a `WKWebView` re-layout is expensive (G109); Home is a cheap SwiftUI tree, so it is not.
  Its query and mode live in the Home field's own model, held by the app, so the text survives
  ⌘2 → ⌘1. Scroll position is not kept (amends design §6.4 — a card list that fits a window has
  little to scroll, and keeping a view alive only for that is the cost G109 paid for a reason).
- **R-IB4 — Home's field is a second `FindPaletteModel` sharing the one `AskViewModel`, with no
  recents.** The palette's hand-off allowed "the environment's model or a second instance"; one
  shared model would let a ⌘K on the Feed (`present` resets the query) wipe what the person left
  typed on Home. The second instance takes the palette's `ask` (R-SU7: one Ask history, one
  `.askHistory` writer) and `keepsRecents: false`: recents are the palette's empty state, Home's
  empty state is its cards, and two writers of `.quickRecents` would clobber each other's list. The
  instant index is built once (`FindIndexTask`) and installed into both.
- **R-IB5 — On Home, ⌘K focuses Home's field; everywhere else the overlay opens as today.**
  `PaletteToggle.outcome(…, homeVisible:)` gains `.focusHome(prefill:mode:)`; an overlay already open
  still closes on a plain ⌘K; first run still ignores it.
- **R-IB6 — `FindPanelBody` in `.page` placement shows only the field until there is something to
  show** (`showsBody(placement:query:mode:)`: the palette always; the page while the trimmed query is
  non-empty or the mode is Ask — design H2 "the first keystroke replaces the cards"). Three
  additive parameters, defaults preserving the palette byte for byte: `prompt` (Home's placeholder),
  `focusRequest` (an `Int` whose change focuses the field — ⌘K and ⌘1), `submitOverride` (⏎ saves a
  pasted link, R-IB7). Esc on the page runs `model.escape()` and never closes anything.
- **R-IB7 — A pasted link is saved from Home only.** `LinkPaste.url(in:)` accepts exactly one
  `http(s)` token with a host and nothing around it; Home shows "Save this link · example.com" above
  the results, ⏎ or the row's button calls `APIClient.saveURL`, then a toast and
  `store.refresh([.sources, .sourcesOverview])`. The palette is unchanged (the `+` sheet's *Paste a
  link* tile and the menu bar's *Save clipboard URL* already exist there).
- **R-IB8 — Home adds no drop target of its own.** The window-level drop (R-IA24) already covers
  Home and raises the one intake; a nested target would only split the veil. `IntakeOrigin.home`
  stays unused.
- **R-IB9 — Home's numbers, each once, each a link (design §6.3).** TODAY: the sum of today's UTC
  bucket over `store.sourcesOverview` (noun **captured**, hover "Captured since 00:00 UTC"), the top
  three origins by today's count as marks that open their source (`router.routeToSourceDetail`),
  `—` with "Loading…" until the snapshot exists (R-A14). The waiting line (`store.status` unprocessed,
  worm 24 pt on this content row, `deriveBookwormState`) links to the Sleep page — **never a
  Consolidate** (G125 R10 in steady state) — and is omitted while Getting started shows its read row
  (`HomeLayout.showsWaitingInToday`). NEEDS YOU: the first three of `store.visibleInbox` in its own
  order, kind glyph + question + the harness mark from `cause.harness`, a click lands on that card
  (`router.pendingInboxItem`), "All N ›" when there are more. LAST READ: the newest `kind == "sleep"`
  history entry (a decay or inbox commit is not a read), `—` "Loading…" until history loads,
  "Nothing read yet" after; its line states the day and only the counts that happened; chips are its
  `entities/*.md` files that still exist in `store.graph`, first three + "+N", each revealing its
  node.
- **R-IB10 — Home's band art: procedural sky + one cloud, composed in `Views/Meadow/`.**
  `HomeSkyBand` draws `MeadowSky` and one `DriftingCloud` in the outer quarter; the headline sits on
  the gradient (procedural, not paint) in the middle half, and `HomeBandLayout` proves at every
  width 480–1800 pt and zoom 0.8–1.4 that the cloud, drift included, never crosses it; under 640
  scaled points the cloud is dropped rather than the headline squeezed. No grass on Home (the band
  is a header, not a landing page) and no `backgroundExtensionEffect` (unverified against the G109
  frame budget; M2's to try).
- **R-IB11 — The Welcome: a full-window overlay; the hero painting as its band; every word on the
  card.** `ContentView` replaces the `.sheet` with an `.overlay` over the whole split view, so the
  transition to Home *reveals* the page underneath (design §4.1.1). The band is `hero-day`
  (`-dark` in dark mode) scaled to fill, anchored at the bottom so the grass shows, confined to the
  top ~36 % (`WelcomeLayout`). The checklist card is `surface` and rises `scaled(96)` into the grass;
  **the headline block is the card's own first section**, so no text ever sits on paint and none on
  glass (the card is content, R-M5 — glass stays chrome). No drifting sprite over the hero (its
  clouds are painted; a moving sprite over them would double them). The pixel worm is in the pinned
  footer on plain `background`, never on the grass (R9 §5.3). The Welcome → Home transition is a
  crossfade (`CicadaMotion.morph`); `matchedGeometryEffect` across an overlay and a
  `NavigationSplitView` detail is exactly §14 item 11's stutter risk, so it is not attempted.
- **R-IB12 — Nothing is read before the tick — so the Welcome shows no bookmark count.** CLAUDE.md
  (T1): "A browser is read only after the person turned it on — … onboarding's tick." Design
  §4.1.3's count came from posting the bookmark file's bytes to `?preview=true`, which is reading it
  before consent; the brief's rail ("consent before any read (bookmarks, agent wiring)") settles it.
  The browser row says "Your bookmarks, and new ones as you save them", `startSummary` says "brings
  in your bookmarks" (part a already handles a missing count), and the real number arrives as the
  row's sync line after Start. What detection does touch is part a's, unchanged: bundle ids, an
  `open` that reads nothing (readable vs blocked), and `GET /agents/wiring`'s read-only status
  (`claude mcp get`, the settings file through `registry.status`) — a status, never a transcript and
  never a write. Every write and every read of content waits for Start.
- **R-IB13 — The engine choice: one seam, `EngineChoice`, over `EngineCard(style: .compact)`.** The
  brief names `EngineCard` and a later `EngineChooser` (Track O): `Views/Onboarding/EngineChoice.swift`
  is the one call site onboarding surfaces use, and swapping its body is the whole migration.
  `.compact` shows the four real candidates (Auto hidden — onboarding asks for one concrete engine
  a new person can name; the Auto ladder stays a Settings → Sleep choice. An untouched chooser keeps
  the install's configured default, `byok` unless a pref or `CICADA_LLM_MODE` says otherwise —
  `sleep_engine_prefs.py:43-57` — and `EngineReadiness` says whether that default can run), each
  card with its **cost-model line** (`EngineOption.costModel`:
  "Uses your plan" / "Free, on this Mac. Slower." / "Billed per use by your provider" — words, never
  a price) and its state caption, a ring on the pick or else on the engine that can run
  (`EngineReadiness`) with "Will read", and one honesty line (`EngineChoiceLine`) plus "Plans and keys
  send what Cicada reads to that provider." It hides the model field, the overage toggle and the two
  preview lines (Settings keeps them). With a `pick` binding (the Welcome) a click only moves the
  ring and Start writes it (§4.1.7 step 2, only if clicked); without one (Getting started) a click
  commits, as Settings does. Signing in stays in Plans & keys behind the existing `signInHint` link:
  `ConnectionLoginFlow` is Track O's, and a second sign-in implementation here is the fork §3.8
  forbids. The ChatGPT card shows (Track E shipped `codex`), with its own state caption.
- **R-IB14 — Start is `SetupRunner` executing `OnboardingFlow.plan`.** The owner PUT runs alone and
  first and carries the loaded `handle`/`email` back (the route clears what is omitted — and when the
  Welcome's own load of them failed, the PUT re-reads them first rather than send nothing); its failure
  stops everything and shows an inline `danger` line (W15). An engine-save failure is not global: it
  becomes one line on Getting started's *Who reads* row. The sequential steps (owner, engine, mark
  the LIVE bank, record, show Home) finish before any row starts, so Start costs one round trip; the
  rows then run concurrently, each reporting into `SetupRunner.rows`, and a failure stays on its row
  (§4.1.7 item 6). The runner is app-lifetime, so a Welcome that has already faded out keeps
  reporting to Home.
- **R-IB15 — While the Welcome shows, every arrival lands on it, and nothing imports before Start.**
  `IntakeRouter.welcomeActive` (set by `ContentView`) makes `accept` from any origin — window drop,
  Dock, menu bar, File → Import — sniff and stage a ticked row on the Welcome (W11) instead of
  raising the overlay that would sit hidden underneath, and makes `present` ask the Welcome to open
  its file panel. A staged drop commits at Start through `commit(_ preview:from:)`, which sends chat
  files to `/intake/import` and saved files to `/sources/upload` (R-IA32), with one Store refresh;
  it leaves the staged list only when it committed without a failure, so Getting started's *Retry*
  on that row can commit it again. Raising the Welcome (`welcomeActive` false → true) clears drops
  left from an earlier Welcome and **adopts** an overlay sniff already under way — a Dock open on a
  cold launch reaches the router before the gate has resolved the bank — so no preview is ever
  stranded under the Welcome.
- **R-IB16 — The secondary exits.** *Set up later* saves the name (G117 R1; without one it reads
  "Set up later (add your name first)" and focuses the field), marks the bank, records an empty
  checklist and lands on Home, where Getting started lists what was found under *Also found* with
  Turn on. *Try the demo instead* runs `OnboardingFlow.demoSteps` then shows **Home** (the front door
  is the same for everyone, and the demo's populated Today and Needs you are themselves the tour);
  a demo failure keeps the Welcome up with its reason. **Rerun** (Settings → General → Run setup
  again): rows already on read On and cannot be ticked, Start reads *Save changes*, the demo link is
  hidden, *Close* and Esc dismiss; on first run Esc does nothing (a stray Esc must not skip setup).
- **R-IB17 — `GettingStartedState`, per bank, in `UserDefaults`** (`cicada.gettingStarted.<bank>.*`,
  the `OnboardingState` pattern): `enabled` (ordered `FoundItemID` keys), `settled`, `hidden`,
  `scheduleAsked`. The card exists only for a bank the Welcome ran on — an install onboarded before
  this track never sees it — until *Show setup checklist* (Settings → General, beside *Run setup
  again*) records it on demand. Recording again unions and un-hides. A dropped file is never
  persisted (its row is this session's result, not a standing connection).
- **R-IB18 — Row state after a relaunch comes from the machine, not from memory.** A row's state is
  the runner's (this session) or else derived: an agent is On when `LocalInventory` says
  `alreadyOn`, a browser when the watcher says it is enabled, Claude Desktop when its config has
  Cicada (else "Finish in Settings → Agents"), Cursor when it has been *settled* (Cursor owns its
  config, so the opened confirm is all Cicada can know). ✕ settles any row (a dropped export's row,
  which only this session knows, is forgotten instead — `SetupRunner.forget`), and a settled row reads
  On even over this session's runner state (a ✕ on a row that failed a minute ago must still let
  the card finish). **Done** = every row On (or settled) + `hasRunBefore` + the schedule answered;
  the card then says "You're set up." for the session and hides itself persistently. *Hide* ends
  the session's "You're set up." too.
- **R-IB19 — The first read, and G125 R10's second narrow amendment.** `FirstReadStep` is the design
  §4.2 table as a total function (nothing yet · N waiting · reading · finished · capped · failed), each
  with its line (the text twin), its worm and its one action. *Read now* (and *Read the next N*,
  *Try again*) exists **only inside the Getting started card**, is a user trigger subtitled with
  `preview.manual`'s engine like Consolidate, and is disabled with "Choose who reads first" while
  `EngineReadiness == .needsChoice` (the *Who reads* row sits right above it). Home's steady state
  is a link. No duration estimate anywhere (G107). It wears the `MeadowPill` the intake done card's
  *Read now* wears (R-IA16) — D-4's narrow meadow amendment extended to that one action's second
  host, since design §5.2 folds the done card into this row during onboarding; the card's other
  buttons stay plain.
- **R-IB20 — The schedule question asks only a person still on `manual`.** A schedule set in
  Settings is an answer (and an `interval` is thereby never downgraded — Track P R4). "Still on
  `manual`" means the *fetched* schedule: `SleepViewModel.schedule` starts as a placeholder
  `manual`, so the question waits for `sleepVM.scheduleLoaded` (added in Task 3) — unknown is never
  an answer, and a write built on the placeholder would overwrite a real `interval`. Options
  *When I ask* / *After imports* / *Every night at 3:00*, enabled by `ScheduleHonesty.enabledModes`
  (ruling 4 visible: with plans only and no key, only *When I ask*), the line under them
  `ScheduleHonesty.engineLine`; the one writer is `sleepVM.updateSchedule`; *Not now* answers it.
  The evening-reminder checkbox is **not** built (see Not in scope).
- **R-IB21 — Retirements.** `FirstRunSheet`, `OwnerIdentityStep`, `OnboardingSleepStep` (with
  `OnboardingStep`, `OnboardingSchedule`, their three `.red` literals and five `Copy` members),
  `IntegrationsView.onHandOff` (its only caller goes), and their tests. With the last `.red` gone,
  design §13's `NoRedLiteralLintTests` lands in the same commit so none comes back. `ScheduleToggle` stays —
  it is Track Z's (`Views/Sleep/ScheduleToggle.swift`), and its tests already pin 3:00.
- **R-IB22 — Export reminders.** One `ExportWait {vendor, bank, requestedAt, remindAt}` per bank ×
  vendor in `UserDefaults` `cicada.exportWaits` (a per-viewer convenience, never memory); delays *In 3
  hours* / *Tomorrow at 9:00* / *In 2 days*. Notification permission is requested **only** when the
  person chooses a delay; the wait is recorded whatever the answer. A tap opens the one intake idle
  (`present(from: .reminder(vendor))`) and never starts anything. `UNUserNotificationCenter` is
  touched only inside a real `.app` bundle (`ReminderAvailability`), so `swift test` never meets it.
  Text twins that need no permission: the Getting started chat row, a Feed waiting strip (itself a
  drop target) and a disabled menu-bar line refreshed as the menu opens. A wait clears on a sniff of
  the same vendor in the active bank, on ✕, or after 14 days. No network, ever.
- **R-IB23 — Notes & voice rows are not on the Welcome.** Obsidian and Wispr Flow shipped (PR #77),
  but each needs its own consent step (a folder pick; the dictation opt-in and other voices, G95),
  and Settings → Integrations already hosts both as standing connections (G126).
  `FoundGroup.notesAndVoice` stays unused; a row that can only say "go elsewhere" is what the design
  calls a row that leads nowhere.
- **R-IB24 — No backend change.** Every endpoint this plan calls exists (`GET/PUT /settings/owner`,
  `GET/PUT /sleep/engine`, `POST /banks/demo`, `POST /sleep/trigger`, `PUT /sleep/schedule`,
  `GET /agents/wiring`, `/intake/*`, `/sources/save`, `/sources/sync-bookmarks`, `/sources/upload`).

---

## File map

| File | Task | Responsibility |
|---|---|---|
| `app/…/Views/Sidebar/SidebarView.swift` | 1 | `AppTab.home` first; `restored` → Home; icon `house` |
| `app/…/Theme/ZoomKeyRouter.swift` | 1 | comment only: "⌘1–6" → "⌘1–7" (`:31`) |
| `app/…/ContentView.swift` | 1, 4 | default Home; `.home` content; ⌘K → Home's field; index into both models (1); the Welcome overlay, modes, drop routing, `welcomeActive` (4) |
| `app/…/Support/FindCommands.swift` | 1 | `PaletteToggle.Outcome.focusHome`, `homeVisible:` |
| `app/…/Search/FindPaletteModel.swift` | 1 | `init(store:ask:keepsRecents:)`; `remember` guard |
| `app/…/Views/Find/FindPanelBody.swift` | 1 | `.page`: `showsBody`, `prompt`, `focusRequest`, `submitOverride` |
| `app/…/Support/HomeSearch.swift` (new) | 1 | Home's field model + focus nonce |
| `app/…/Support/HomeFigures.swift`, `Support/LinkPaste.swift` (new) | 1 | Home's numbers; the pasted-link rule |
| `app/…/Views/Meadow/HomeSkyBand.swift` (new) | 1 | band art + `HomeBandLayout` |
| `app/…/Views/Home/HomeView.swift`, `Views/Home/HomeSections.swift` (new) | 1, 3 | the page; Today / Needs you / Last read (1); the card slot (3) |
| `app/…/Theme/Copy+Welcome.swift` (new) | 1–5 | every string of this track + `welcomeHomeLabels` / `welcomeHomeSentences` |
| `app/…/CicadaApp.swift` | 1, 3, 5 | `HomeSearch` (1); `SetupRunner`, shared `LocalInventory` (3); `ExportWaitStore`, reminder wiring (5) |
| `app/…/Support/SetupRunner.swift` (new) | 2 | `SetupEffects`, `FoundTurnOnResult`, `SetupRunner` |
| `app/…/Support/FoundTurnOn.swift` (new) | 2 | the one turn-on, extracted from `OnThisMacStrip` |
| `app/…/Support/GettingStartedState.swift` (new) | 2 | `FoundItemID.key`, the per-bank record |
| `app/…/Support/WelcomeLogic.swift` (new) | 2 | `WelcomeName`, `WelcomeTicks`, `WelcomeLayout`, `EngineChoiceLine` |
| `app/…/Views/Settings/EngineOption.swift` | 2 | `costModel`, `compactCandidates`, `compactCaption`, `ringed` |
| `app/…/Support/IntakeRouter.swift` | 2, 5 | Welcome staging, `commit(_ preview:)` (2); `onVendorSniffed` (5) |
| `app/…/Views/Intake/OnThisMacStrip.swift` | 2 | calls `FoundTurnOn` |
| `app/…/Support/GettingStartedProgress.swift` (new) | 3 | rows, also found, done; `FirstReadStep`; `ScheduleChoice` |
| `app/…/Support/LiveSetupEffects.swift` (new) | 3 | the real `SetupEffects` |
| `app/…/Views/Home/GettingStartedCard.swift` (new) | 3, 5 | the card (3); the chat row's waits (5) |
| `app/…/Views/Onboarding/EngineChoice.swift` (new) | 3 | the engine seam |
| `app/…/Views/Settings/EngineCard.swift` | 3 | `Style.compact`, `pick:` |
| `app/…/Views/Settings/SettingsGeneralView.swift` | 3 | *Show setup checklist* |
| `app/…/ViewModels/SleepViewModel.swift` | 3 | `scheduleLoaded` (R-IB20: the question never runs on the placeholder schedule) |
| `app/…/Views/Onboarding/WelcomeView.swift`, `Views/Onboarding/WelcomeChecklist.swift` (new) | 4, 5 | the Welcome (4); *Ask for one* (5) |
| `app/…/Views/Meadow/WelcomeHero.swift` (new) | 4 | the hero band |
| `app/…/Views/Common/FoundRow.swift` | 4 | the tick |
| `app/…/Views/Settings/IntegrationsView.swift`, `Theme/Copy.swift` | 4 | drop `onHandOff`; drop the onboarding strings |
| `app/…/Views/Onboarding/FirstRunSheet.swift`, `OwnerIdentityStep.swift`, `OnboardingSleepStep.swift` | 4 | **deleted** |
| `app/…/Support/ExportWaits.swift`, `Support/Reminders.swift` (new) | 5 | waits, delays, lines, store; scheduler, availability, tap queue |
| `app/…/Views/Intake/ExportAskRow.swift` (new), `Views/Intake/IntakePanel.swift` | 5 | `VendorExportRow` made shared + *Remind me* |
| `app/…/Views/Feed/ExportWaitStrip.swift` (new), `Views/Feed/FeedView.swift` | 5 | the Feed twin |
| `app/…/MenuBarManager.swift`, `Support/DockOpenQueue.swift` | 5 | the menu-bar twin; the notification delegate |
| Tests (new) | 1–5 | `HomeFiguresTests`, `LinkPasteTests`, `HomeBandLayoutTests`, `HomeSearchTests`, `GettingStartedStateTests`, `WelcomeLogicTests`, `SetupRunnerTests`, `FoundTurnOnTests`, `GettingStartedProgressTests`, `NoRedLiteralLintTests`, `ExportWaitsTests` |
| Tests (edited) | 1–5 | `SidebarTabTests`, `FindPaletteTests`, `CopyConstantsTests`, `CountLiteralLintTests` (scope), `IntakeRouterTests`, `EngineOptionTests`, `FoundRowTests`, `SettingsSectionTests`, `FixWaveTests` (comment), `AppRouterTests` (comment) |
| Tests (deleted) | 4 | `OnboardingStepTests.swift`, `OnboardingScheduleTests.swift` |
| Docs | 6 | `CLAUDE.md`; `docs/goals/memory-evolution.md` rows G108, G117, G54, G125; `docs/goals/TODO.md` |

---

### Task 1 (T9a): Home at ⌘1 — the front door, search first

Spec decision 12 and design §6. Home becomes the first tab with the palette's own field, then
Today / Needs you / Last read. Onboarding is untouched in this commit (the sheet still runs), so the
branch ships as "a new first tab".

**Files:**
- Modify: `app/…/Views/Sidebar/SidebarView.swift:3-48` (doc + `AppTab`), `:82-83`, `:117` (comments),
  `app/…/Theme/ZoomKeyRouter.swift:31` (comment)
- Modify: `app/…/ContentView.swift:6, 10, 208-219, 339-368, 794-806`
- Modify: `app/…/Support/FindCommands.swift:73-90`
- Modify: `app/…/Search/FindPaletteModel.swift:23-33, 171-179`
- Modify: `app/…/Views/Find/FindPanelBody.swift:8-37, 39-77`
- Modify: `app/…/CicadaApp.swift:47-49, 112, 131`
- Create: `app/…/Support/HomeSearch.swift`, `app/…/Support/HomeFigures.swift`, `app/…/Support/LinkPaste.swift`
- Create: `app/…/Views/Meadow/HomeSkyBand.swift`
- Create: `app/…/Views/Home/HomeView.swift`, `app/…/Views/Home/HomeSections.swift`
- Create: `app/…/Theme/Copy+Welcome.swift`
- Test: `SidebarTabTests.swift` (edit), `FindPaletteTests.swift` (add), `CopyConstantsTests.swift` (add), `CountLiteralLintTests.swift` (scope); new `HomeFiguresTests.swift`, `LinkPasteTests.swift`, `HomeBandLayoutTests.swift`, `HomeSearchTests.swift`

**Interfaces:**
- Produces `AppTab.home`; `PaletteToggle.Outcome.focusHome(prefill:mode:)` and
  `outcome(for:isOpen:firstRunShowing:homeVisible:)` (default `false`);
  `FindPaletteModel.init(store:ask:keepsRecents:)`; `FindPanelBody(model:placement:open:close:prompt:focusRequest:submitOverride:)`
  and `static func showsBody(placement:query:mode:) -> Bool`; `HomeSearch` (`model`, `focusRequest`,
  `focus(prefill:mode:)`); `HomeFigures` (`today`, `needsYou`, `lastRead`, `lastReadLine`, `chips`);
  `LinkPaste` (`url(in:)`, `host(_:)`); `HomeBandLayout`; `HomeSkyBand`; `HomeView(open:selectedTab:)`
  with a `gettingStartedVisible` input Task 3 fills (`false` here).
- Consumes `sparklinePoints`, `store.sourcesOverview/visibleInbox/status/graph`, `sleepVM.history/
  historyLoaded/loadHistory/load`, `deriveBookwormState`, `router.pendingInboxItem`,
  `router.routeToSourceDetail`, `graphVM.revealEntity`, `APIClient.saveURL`, `HomeLayout.showsWaitingInToday`.

- [ ] **Step 1: Failing tests.**

  `SidebarTabTests.swift` — replace `testTheSidebarIsSixRowsInVisualOrder`, add `.home`'s raw value to
  `testSurvivingRawValuesAreUnchanged`, replace `testUnknownOrMissingSelectionsFallBackToGraph`, add one
  test, and update the count test:

```swift
    /// G108 ruled (spec decision 12): Home is the front door at ⌘1, Graph follows at ⌘2.
    func testTheSidebarIsSevenRowsInVisualOrder() {
        XCTAssertEqual(AppTab.allCases, [.home, .graph, .clusters, .feed, .sleep, .inbox, .sources])
    }

    func testUnknownOrMissingSelectionsFallBackToHome() {
        XCTAssertEqual(AppTab.restored(from: nil), .home, "a fresh install opens on the front door")
        XCTAssertEqual(AppTab.restored(from: ""), .home)
        XCTAssertEqual(AppTab.restored(from: "Nudges"), .home)
    }

    /// Relaunch restores the last tab, so nobody who lives in the graph is moved (D-3b: no).
    func testAStoredGraphSelectionStaysOnGraph() {
        XCTAssertEqual(AppTab.restored(from: "Graph"), .graph)
    }

    /// ⌘1–7 follow the visual order, and every row has an icon.
    func testEveryTabHasAShortcutSlotAndAnIcon() {
        XCTAssertEqual(AppTab.allCases.count, 7)
        XCTAssertEqual(AppTab.allCases.firstIndex(of: .home), 0, "⌘1 is Home")
        XCTAssertEqual(AppTab.allCases.firstIndex(of: .graph), 1, "⌘2 is Graph")
        for (index, tab) in AppTab.allCases.enumerated() {
            XCTAssertLessThan(index, 9, "\(tab.rawValue) has no ⌘ slot")
            XCTAssertFalse(tab.icon.isEmpty, tab.rawValue)
            XCTAssertEqual(tab.title, tab.rawValue, "the label and the identity must agree")
        }
    }
```

  (and in `testSurvivingRawValuesAreUnchanged` add `XCTAssertEqual(AppTab.home.rawValue, "Home")`;
  update the file's doc comment "six rows" → "seven rows". `testRetiredTabsFallBackToWhereTheirContentWent`
  is unchanged — `"Connections"`/`"Connect"` still land on Graph.)

  `FindPaletteTests.swift` — beside the existing `PaletteToggle` cases (`:114-123`):

```swift
    /// Track I part b (R-IB5) — on Home, ⌘K focuses Home's own field; the overlay never opens over it.
    func testCommandKOnHomeFocusesItsFieldInsteadOfTheOverlay() {
        XCTAssertEqual(PaletteToggle.outcome(for: PaletteRequest(), isOpen: false, firstRunShowing: false, homeVisible: true),
                       .focusHome(prefill: "", mode: .find))
        XCTAssertEqual(PaletteToggle.outcome(for: PaletteRequest(prefill: "alpha", mode: .ask), isOpen: false,
                                             firstRunShowing: false, homeVisible: true),
                       .focusHome(prefill: "alpha", mode: .ask))
        XCTAssertEqual(PaletteToggle.outcome(for: PaletteRequest(), isOpen: true, firstRunShowing: false, homeVisible: true),
                       .close, "an overlay opened elsewhere, then ⌘1, still closes on ⌘K")
        XCTAssertEqual(PaletteToggle.outcome(for: PaletteRequest(), isOpen: false, firstRunShowing: true, homeVisible: true),
                       .ignore)
    }
```

  `HomeSearchTests.swift` (new):

```swift
import XCTest
@testable import CicadaApp

/// Track I part b (R-IB4, R-IB6) — Home's field is the palette's body with its
/// own model: the one Ask, no recents, the cards until the first keystroke.
@MainActor
final class HomeSearchTests: XCTestCase {
    private func store() -> Store {
        Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)),
              api: FakeSyncAPI())
    }

    func testHomeShowsResultsOnlyWhileSomethingIsTypedOrAsked() {
        XCTAssertTrue(FindPanelBody.showsBody(placement: .palette, query: "", mode: .find))
        XCTAssertFalse(FindPanelBody.showsBody(placement: .page, query: "  ", mode: .find),
                       "Home's cards stay until the first keystroke (H2)")
        XCTAssertTrue(FindPanelBody.showsBody(placement: .page, query: "alpha", mode: .find))
        XCTAssertTrue(FindPanelBody.showsBody(placement: .page, query: "", mode: .ask))
    }

    func testHomesFieldSharesTheOneAskButNeverWritesThePalettesRecents() async throws {
        let store = store()
        let palette = FindPaletteModel(store: store)
        let home = FindPaletteModel(store: store, ask: palette.ask, keepsRecents: false)
        XCTAssertTrue(home.ask === palette.ask, "one AskViewModel for the app (R-SU7)")
        home.install(QuickIndex.build(FindFixtures.inputs()))
        home.setQuery("alpha")
        let first = try XCTUnwrap(home.selection)
        // Activating the Ask row would call /ask and spend — the top hit here is the entity.
        XCTAssertNotEqual(first.kind, .ask)
        guard first.kind != .ask else { return }
        _ = home.activate(first)
        XCTAssertTrue(home.recents.isEmpty)
        let saved = await store.cache.load(.quickRecents, bank: store.bank, as: [FindRowKey].self)
        XCTAssertNil(saved, "two writers of .quickRecents would clobber each other's list")
    }

    func testFocusCarriesAPrefillAndAMode() {
        let search = HomeSearch(model: FindPaletteModel(store: store(), keepsRecents: false))
        search.focus(prefill: "bob-example", mode: .find)
        XCTAssertEqual(search.model.query, "bob-example")
        XCTAssertEqual(search.focusRequest, 1)
        search.focus(prefill: "", mode: .ask)
        XCTAssertEqual(search.model.mode, .ask)
        XCTAssertEqual(search.focusRequest, 2)
    }
}
```

  `HomeFiguresTests.swift` (new):

```swift
import XCTest
@testable import CicadaApp

/// Track I part b T9 (design §6.3, R-IB9) — every number on Home, as a pure
/// function of what the Store already holds. Placeholders only.
final class HomeFiguresTests: XCTestCase {
    private let today = ISO8601DateFormatter().date(from: "2026-09-23T12:00:00Z")!

    private func row(_ id: String, _ label: String, mark: String, today n: Int, yesterday y: Int = 0) -> SourceOverview {
        SourceOverview(id: id, label: label, kind: .harness, mark: mark,
                       activity: ["2026-09-23": n, "2026-09-22": y].filter { $0.value > 0 })
    }

    func testTodaySumsOnlyTodaysUTCBucketAndNamesTheTopThree() {
        let t = HomeFigures.today([
            row("harness:claude-code", "Claude Code", mark: "claude-code", today: 6, yesterday: 40),
            row("chrome-bookmarks", "Chrome", mark: "chrome-bookmark", today: 5),
            row("chat-export:chatgpt", "ChatGPT export", mark: "chatgpt-export", today: 2),
            row("rss", "RSS", mark: "rss", today: 1),
            row("telegram", "Telegram", mark: "telegram", today: 0),
        ], today: today)
        XCTAssertEqual(t.captured, 14, "yesterday's 40 never leaks into today")
        XCTAssertEqual(t.origins.map(\.sourceId), ["harness:claude-code", "chrome-bookmarks", "chat-export:chatgpt"])
    }

    func testTodayIsUnknownUntilTheSnapshotLoads() {
        XCTAssertNil(HomeFigures.today(nil, today: today).captured, "never a guessed 0 (R-A14)")
        XCTAssertEqual(HomeFigures.today([], today: today).captured, 0)
    }

    func testNeedsYouShowsTheFirstThreeInTheInboxsOwnOrder() {
        let items = (1...5).map { FindFixtures.inbox("inbox-00\($0)", question: "Still tracking alpha-project \($0)?") }
        let n = HomeFigures.needsYou(items)
        XCTAssertEqual(n.shown.map(\.id), ["inbox-001", "inbox-002", "inbox-003"])
        XCTAssertEqual(n.total, 5)
    }

    private func entry(_ hash: String, kind: String = "sleep", files: [String] = [],
                       created: Int = 0, updated: Int = 0) throws -> SleepHistoryEntry {
        let object: [String: Any] = ["commitHash": hash, "date": "2026-09-22", "message": "Sleep cycle", "kind": kind,
                                     "filesChanged": files, "entitiesCreated": created, "entitiesUpdated": updated]
        return try JSONDecoder().decode(SleepHistoryEntry.self, from: JSONSerialization.data(withJSONObject: object))
    }

    func testLastReadIsTheNewestSleepCommitNeverADecayOrInboxOne() throws {
        let decay = try entry("d1", kind: "decay"), sleep = try entry("s1"), older = try entry("s0")
        XCTAssertEqual(HomeFigures.lastRead([decay, sleep, older], loaded: true), .entry(sleep))
        XCTAssertEqual(HomeFigures.lastRead([decay], loaded: true), .never)
        XCTAssertEqual(HomeFigures.lastRead([], loaded: false), .loading, "history is not disk-cached — '—' until it lands")
    }

    func testLastReadLineStatesTheDayAndOnlyTheCountsThatHappened() throws {
        let en = Locale(identifier: "en_US")
        XCTAssertEqual(HomeFigures.lastReadLine(try entry("s1", created: 9, updated: 1_024), locale: en),
                       "Sep 22 · 9 new · 1,024 updated")
        XCTAssertEqual(HomeFigures.lastReadLine(try entry("s2", updated: 3), locale: en), "Sep 22 · 3 updated")
        XCTAssertEqual(HomeFigures.lastReadLine(try entry("s3"), locale: en), "Sep 22 · nothing changed")
    }

    func testChipsAreEntityPagesThatStillExistInTheGraph() throws {
        let e = try entry("s1", files: ["entities/alpha-project.md", "entities/bob-example.md", "inbox/inbox-001.md",
                                        "entities/gone-page.md", "entities/alpha-project.md",
                                        "entities/gamma.md", "entities/delta.md"])
        let nodes = [FindFixtures.node("alpha-project", "alpha-project"),
                     FindFixtures.node("bob-example", "bob-example", type: .person),
                     FindFixtures.node("gamma", "gamma-example"), FindFixtures.node("delta", "delta-example")]
        let chips = HomeFigures.chips(e, nodes: nodes)
        XCTAssertEqual(chips.shown.map(\.id), ["alpha-project", "bob-example", "gamma"])
        XCTAssertEqual(chips.more, 1, "a deleted page is never a chip, and a repeat counts once")
    }
}
```

  `LinkPasteTests.swift` (new):

```swift
import XCTest
@testable import CicadaApp

/// R-IB7 — a paste is a link only when it is one http(s) URL and nothing else.
final class LinkPasteTests: XCTestCase {
    func testOnlyASingleHTTPURLIsALink() {
        XCTAssertEqual(LinkPaste.url(in: "  https://example.com/a?b=1 \n")?.absoluteString, "https://example.com/a?b=1")
        XCTAssertNotNil(LinkPaste.url(in: "http://example.com"))
        XCTAssertNil(LinkPaste.url(in: "alpha-project"), "a search is not a link")
        XCTAssertNil(LinkPaste.url(in: "see https://example.com"), "words around a URL are a search")
        XCTAssertNil(LinkPaste.url(in: "file:///etc/hosts"))
        XCTAssertNil(LinkPaste.url(in: "javascript:alert(1)"))
        XCTAssertNil(LinkPaste.url(in: "https://"))
    }

    func testTheHostDropsALeadingWww() {
        XCTAssertEqual(LinkPaste.host(URL(string: "https://www.example.com/x")!), "example.com")
    }
}
```

  `HomeBandLayoutTests.swift` (new):

```swift
import XCTest
@testable import CicadaApp

/// R-IB10 — text never on paint: the drifting cloud stays in the outer quarter
/// and never crosses the headline, at any width or zoom.
final class HomeBandLayoutTests: XCTestCase {
    func testTheCloudNeverCrossesTheHeadlineAtAnyWidthOrZoom() {
        for width in stride(from: CGFloat(480), through: 1800, by: 40) {
            for scale in stride(from: CGFloat(0.8), through: 1.4001, by: 0.1) {
                let head = HomeBandLayout.headlineFrame(width: width, scale: scale)
                XCTAssertLessThanOrEqual(head.maxY, HomeBandLayout.bandHeight * scale, "width \(width) scale \(scale)")
                guard let cloud = HomeBandLayout.cloudFrame(width: width, scale: scale) else { continue }
                let drifted = cloud.insetBy(dx: -CicadaMotion.ambientMaxAmplitude, dy: 0)
                XCTAssertFalse(drifted.intersects(head), "width \(width) scale \(scale)")
                XCTAssertGreaterThanOrEqual(cloud.minX, width * 0.75, "the cloud stays in the outer quarter")
            }
        }
    }

    func testANarrowBandDropsTheCloudRatherThanSqueezeTheHeadline() {
        XCTAssertNil(HomeBandLayout.cloudFrame(width: 560, scale: 1))
        XCTAssertNotNil(HomeBandLayout.cloudFrame(width: 900, scale: 1))
    }
}
```

  `CopyConstantsTests.swift` — add (the lists grow in later tasks):

```swift
    /// Track I part b — Welcome, Getting started, Home and reminder labels are short,
    /// never say "claim", and never state a price or a token count (2026-09-03).
    func testWelcomeAndHomeCopyIsShortPlainAndPriceless() {
        XCTAssertGreaterThan(Copy.welcomeHomeLabels.count, 10, "a lint over nothing passes vacuously")
        for label in Copy.welcomeHomeLabels {
            XCTAssertLessThanOrEqual(label.count, 60, label)
        }
        for text in Copy.welcomeHomeLabels + Copy.welcomeHomeSentences {
            XCTAssertFalse(text.lowercased().contains("claim"), text)
            XCTAssertFalse(text.contains("$"), text)
            XCTAssertFalse(text.lowercased().contains("token"), text)
        }
    }
```

  `CountLiteralLintTests.swift:28-33` — the lint is scoped (R-S18) and Home is a page of numbers, so
  add `"/Views/Home/"` to `scope` and make its doc comment say "the places Track S and Track I own"
  instead of "four paths" (`testTheScopeActuallyCoversAllFourPaths` then also pins that `Views/Home/`
  has inhabitants — it will once Step 5 lands).

  Run `cd <worktree>/app/CicadaApp && swift build 2>&1 | tail -5` → fails to compile (the new
  symbols do not exist). That is the red.

- [ ] **Step 2: `AppTab`.** In `SidebarView.swift`: the doc comment says "seven primary views" and
  cites G108 (ruled 2026-09-23, spec decision 12: Home is the front door at ⌘1; a stored selection is
  still restored, so an existing user reopens where they were). Add `case home = "Home"` **first**;
  `restored(from:)` returns `.home` for nil/empty and in `default:` (its doc: "Anything
  unrecognised falls back to Home"); `icon` gains `case .home: "house"`. No code else in the file
  moves (`sidebarButton` already derives ⌘n from `allCases`); only the two comments that count the
  rows are brought up to date — `:82` "Six rows do not need…" → "Seven rows…", `:117` "⌘1–⌘6" →
  "⌘1–⌘7" — and `Theme/ZoomKeyRouter.swift:31`'s "(⌘1–6, ⌘K, …)" → "(⌘1–7, ⌘K, …)".

- [ ] **Step 3: The pure pieces.**

  `Support/LinkPaste.swift`:

```swift
import Foundation

/// R-IB7 — Home's field saves a link only when the whole paste IS one link.
/// Words around a URL are a search; `file:`/`javascript:` are never saved.
enum LinkPaste {
    static func url(in text: String) -> URL? {
        let t = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !t.isEmpty, !t.contains(where: \.isWhitespace), let url = URL(string: t),
              let scheme = url.scheme?.lowercased(), scheme == "http" || scheme == "https",
              let host = url.host, !host.isEmpty else { return nil }
        return url
    }

    static func host(_ url: URL) -> String {
        let host = url.host ?? ""
        return host.hasPrefix("www.") ? String(host.dropFirst(4)) : host
    }
}
```

  `Support/HomeFigures.swift`:

```swift
import Foundation

struct HomeOriginChip: Equatable {
    let sourceId: String
    let mark: String
    let label: String
    let count: Int
}

struct HomeToday: Equatable {
    /// nil until `sourcesOverview` has loaded — shown as "—", never a guessed 0 (R-A14).
    let captured: Int?
    let origins: [HomeOriginChip]
}

enum HomeLastRead: Equatable {
    case loading, never
    case entry(SleepHistoryEntry)
}

struct HomeNeedsYou {
    let shown: [InboxItem]
    let total: Int
}

struct HomeChip: Equatable {
    let id: String
    let name: String
}

struct HomeChips: Equatable {
    let shown: [HomeChip]
    let more: Int
}

/// Track I part b T9 (design §6.3, R-IB9) — Home's numbers, each shown once and
/// each a link to the page that owns it. Pure over what the Store already holds,
/// so "every number once" and "never a guess" are table-tested, not eyeballed.
enum HomeFigures {
    static let originLimit = 3
    static let needsYouLimit = 3
    static let chipLimit = 3

    /// Today's UTC bucket (the key `source_overview` writes) summed over every
    /// row; the three busiest origins become marks. Noun: captured (Sources v2).
    static func today(_ rows: [SourceOverview]?, today: Date) -> HomeToday {
        guard let rows else { return HomeToday(captured: nil, origins: []) }
        let counted = rows.map { (row: $0, n: sparklinePoints(activity: $0.activity, days: 1, today: today).last ?? 0) }
        let top = counted.filter { $0.n > 0 }
            .sorted { $0.n != $1.n ? $0.n > $1.n
                                   : $0.row.label.localizedCaseInsensitiveCompare($1.row.label) == .orderedAscending }
            .prefix(originLimit)
            .map { HomeOriginChip(sourceId: $0.row.id, mark: $0.row.mark, label: $0.row.label, count: $0.n) }
        return HomeToday(captured: counted.reduce(0) { $0 + $1.n }, origins: Array(top))
    }

    static func needsYou(_ inbox: [InboxItem]) -> HomeNeedsYou {
        HomeNeedsYou(shown: Array(inbox.prefix(needsYouLimit)), total: inbox.count)
    }

    /// A decay split or an inbox commit is not a read (G85): only `kind == "sleep"`.
    static func lastRead(_ history: [SleepHistoryEntry], loaded: Bool) -> HomeLastRead {
        if let e = history.first(where: { $0.kind == "sleep" }) { return .entry(e) }
        return loaded ? .never : .loading
    }

    static func lastReadLine(_ e: SleepHistoryEntry, locale: Locale = .autoupdatingCurrent) -> String {
        var parts = [day(e.date, locale: locale) ?? String(e.date.prefix(10))]
        if e.entitiesCreated > 0 { parts.append("\(UsageFormat.count(e.entitiesCreated, locale: locale)) new") }
        if e.entitiesUpdated > 0 { parts.append("\(UsageFormat.count(e.entitiesUpdated, locale: locale)) updated") }
        if parts.count == 1 { parts.append(Copy.homeNothingChanged) }
        return parts.joined(separator: " · ")
    }

    /// The commit's `entities/<id>.md` files that still name a node — a page
    /// deleted since the read is never a chip, and a repeat counts once.
    static func chips(_ e: SleepHistoryEntry, nodes: [GraphNode]) -> HomeChips {
        var names: [String: String] = [:]
        for node in nodes where names[node.id] == nil { names[node.id] = node.name }
        var seen = Set<String>()
        var known: [HomeChip] = []
        for path in e.filesChanged where path.hasPrefix("entities/") && path.hasSuffix(".md") {
            let id = String(path.dropFirst("entities/".count).dropLast(3))
            guard let name = names[id], seen.insert(id).inserted else { continue }
            known.append(HomeChip(id: id, name: name))
        }
        return HomeChips(shown: Array(known.prefix(chipLimit)), more: max(0, known.count - chipLimit))
    }

    /// The day part of the history row's `date` (a `yyyy-MM-dd…` string), read
    /// in UTC and shown as the viewer's short month-day.
    static func day(_ raw: String, locale: Locale) -> String? {
        let parse = DateFormatter()
        parse.locale = Locale(identifier: "en_US_POSIX")
        parse.timeZone = TimeZone(identifier: "UTC")
        parse.dateFormat = "yyyy-MM-dd"
        guard let date = parse.date(from: String(raw.prefix(10))) else { return nil }
        let out = DateFormatter()
        out.locale = locale
        out.timeZone = TimeZone(identifier: "UTC")
        out.setLocalizedDateFormatFromTemplate("MMMd")
        return out.string(from: date)
    }
}
```

  `Support/HomeSearch.swift`:

```swift
import Foundation
import Observation

/// Track I part b (R-IB4, R-IB5) — Home's field: its own `FindPaletteModel`
/// (so a ⌘K elsewhere never wipes what was left typed here), sharing the app's
/// one Ask, keeping no recents. `focusRequest` is a nonce `FindPanelBody`
/// watches — ⌘K on Home and ⌘1 both focus the field through it.
@MainActor
@Observable
final class HomeSearch {
    let model: FindPaletteModel
    private(set) var focusRequest = 0

    init(model: FindPaletteModel) { self.model = model }

    func focus(prefill: String = "", mode: FindMode = .find) {
        if !prefill.isEmpty {
            model.setMode(.find)
            model.setQuery(prefill)
        }
        if mode == .ask { model.setMode(.ask) }
        focusRequest &+= 1
    }
}
```

  `Views/Meadow/HomeSkyBand.swift` (inside the Meadow allowlist, R-IB10):

```swift
import SwiftUI

/// Where Home's band art may sit, as geometry (HomeBandLayoutTests): the
/// headline in the middle half, one cloud in the outer quarter with room for
/// its drift, no cloud at all when the band is too narrow to keep them apart.
enum HomeBandLayout {
    static let bandHeight: CGFloat = 168
    static let cloudWidth: CGFloat = 180
    static let minWidthForCloud: CGFloat = 640
    static let headlineSize: CGFloat = 34
    static let edge: CGFloat = 16

    static func headlineFrame(width: CGFloat, scale: CGFloat) -> CGRect {
        let fraction: CGFloat = width >= minWidthForCloud * scale ? 0.5 : 0.8
        let w = width * fraction - 2 * edge * scale
        let h = 2 * headlineSize * scale * 1.25
        return CGRect(x: (width - w) / 2, y: (bandHeight * scale - h) / 2, width: w, height: h)
    }

    static func cloudFrame(width: CGFloat, scale: CGFloat) -> CGRect? {
        guard width >= minWidthForCloud * scale else { return nil }
        let w = min(cloudWidth * scale, width * 0.25 - edge * scale)
        return CGRect(x: width - w - edge * scale, y: 12 * scale, width: w, height: w / 2)
    }
}

/// Home's header band (design §6.2, R9 §7 amended +1): a procedural sky and one
/// painted cloud. Carries no number and no text of its own — HomeView draws the
/// headline over the gradient at `HomeBandLayout.headlineFrame`.
struct HomeSkyBand: View {
    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .topLeading) {
                MeadowSky()
                if let cloud = HomeBandLayout.cloudFrame(width: geo.size.width, scale: CicadaTheme.uiScale) {
                    DriftingCloud(art: .cloud2, width: cloud.width)
                        .position(x: cloud.midX, y: cloud.midY)
                }
            }
        }
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }
}
```

  (`CicadaTheme.uiScale` is the `Double` behind `scaled(_:)`; pass `CGFloat(CicadaTheme.uiScale)` if
  the compiler asks — SE-0307 converts implicitly.)

- [ ] **Step 4: The palette pieces.**
  - `FindPaletteModel`: replace `init(store:)` with
    `init(store: Store, ask: AskViewModel? = nil, keepsRecents: Bool = true)` (`self.ask = ask ??
    AskViewModel(store: store)`), add `@ObservationIgnored private let keepsRecents: Bool`, and make
    `remember` start with `guard keepsRecents else { return }`. Docstring: R-IB4.
  - `PaletteToggle`: add `case focusHome(prefill: String, mode: FindMode)` and the `homeVisible: Bool =
    false` parameter; after the `isOpen && plain` close, `if homeVisible && !isOpen { return
    .focusHome(prefill: request.prefill, mode: request.mode) }`.
  - `FindPanelBody`: add `var prompt: String? = nil`, `var focusRequest: Int = 0`,
    `var submitOverride: (() -> Bool)? = nil` after `close` (memberwise order: `model, placement,
    open, close, prompt, focusRequest, submitOverride`), and

```swift
    /// R-IB6 — the palette always shows its rows; a page shows only its field until
    /// there is something to show (the first keystroke, or Ask).
    static func showsBody(placement: Placement, query: String, mode: FindMode) -> Bool {
        placement == .palette || mode == .ask || !query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }
```

    Wrap `Divider`, the rows/Ask `Group` and `footer` in `if Self.showsBody(placement: placement,
    query: model.query, mode: model.mode) { … }`; the field's placeholder in Find mode is
    `prompt ?? "Search your memory"` (the accessibility label stays "Search your memory");
    `.onSubmit { if submitOverride?() == true { return }; if let destination = model.submit() { run(destination) } }`;
    add `.onChange(of: focusRequest) { _, _ in fieldFocused = true }` beside `.task`. The palette
    passes none of the three, so it renders exactly as before.

- [ ] **Step 5: The page.** `Theme/Copy+Welcome.swift` (new) opens with a docstring (part a's
  R-IA19 reason: one file, so sibling tracks appending to `Copy.swift` never share lines; plain words; `welcomeHomeLabels` ≤ 60 characters,
  `welcomeHomeSentences` longer) and holds, for this task:

```swift
extension Copy {
    // MARK: Home (Task 1, design §6)
    static let homeHeadline = "What would you like"
    static let homeHeadlineItalic = "to remember?"
    static let homeFieldPrompt = "Search, paste a link, or drop a file"
    static let homeToday = "Today"
    static let homeNeedsYou = "Needs you"
    static let homeLastRead = "Last read"
    static let homeCapturedHelp = "Captured since 00:00 UTC"
    static let homeLoading = "Loading…"
    static let homeNothingCapturedToday = "Nothing captured yet today"
    static let homeNothingWaiting = "Nothing waiting to be read"
    static let homeNothingNeedsYou = "Nothing needs you right now."
    static let homeNothingReadYet = "Nothing read yet"
    static let homeNothingChanged = "nothing changed"
    static let homeOpenSleep = "Sleep ›"
    static let homeSaveLink = "Save this link"
    static func homeCapturedToday(_ n: Int, locale: Locale = .autoupdatingCurrent) -> String {
        "\(UsageFormat.count(n, locale: locale)) captured today"
    }
    static func homeWaiting(_ n: Int, locale: Locale = .autoupdatingCurrent) -> String {
        "\(UsageFormat.count(n, locale: locale)) waiting to be read"
    }
    static func homeAllInbox(_ n: Int, locale: Locale = .autoupdatingCurrent) -> String { "All \(UsageFormat.count(n, locale: locale)) ›" }
    static func homeMoreChips(_ n: Int, locale: Locale = .autoupdatingCurrent) -> String { "+\(UsageFormat.count(n, locale: locale))" }
    static func homeSaveLinkRow(_ host: String) -> String { "\(homeSaveLink) · \(host)" }
    static func homeLinkSaved(_ host: String) -> String { "Saved \(host)" }

    /// Buttons, titles and one-line captions — ≤ 60 characters (CopyConstantsTests).
    static let welcomeHomeLabels: [String] = [
        homeHeadline, homeHeadlineItalic, homeFieldPrompt, homeToday, homeNeedsYou, homeLastRead,
        homeCapturedHelp, homeLoading, homeNothingCapturedToday, homeNothingWaiting, homeNothingNeedsYou,
        homeNothingReadYet, homeNothingChanged, homeOpenSleep, homeSaveLink,
    ]
    /// Longer sentences — the vocabulary rule only.
    static let welcomeHomeSentences: [String] = []
}
```

  `Views/Home/HomeView.swift` — `struct HomeView: View { let open: (FindDestination) -> Void;
  @Binding var selectedTab: AppTab; var gettingStartedVisible = false }` (Task 3 replaces the
  constant). Reads `HomeSearch`, `Store`, `SleepViewModel`, `AppRouter`, `GraphViewModel`,
  `accessibilityReduceMotion`. Body, top to bottom, on `CicadaTheme.background`:
  1. The band: `ZStack { HomeSkyBand(); headline }` at `.frame(height: CicadaTheme.scaled(HomeBandLayout.bandHeight))`,
     where `headline` is a `GeometryReader` placing a two-line `VStack` —
     `Text(Copy.homeHeadline).font(CicadaTheme.displayFont(size: HomeBandLayout.headlineSize))` over
     `Text(Copy.homeHeadlineItalic).font(CicadaTheme.displayFont(size: HomeBandLayout.headlineSize, italic: true))`,
     `foregroundStyle(CicadaTheme.textPrimary)`, centred, `lineLimit(1)`, `minimumScaleFactor(0.6)` —
     at `HomeBandLayout.headlineFrame(width:scale:)`; `.accessibilityElement(children: .combine)`,
     `.accessibilityAddTraits(.isHeader)`.
  2. The field column, `frame(maxWidth: CicadaTheme.scaled(720))`, horizontal padding `spacingXL`:
     when `LinkPaste.url(in: search.model.query)` is non-nil, a row (link glyph · `Copy.homeSaveLinkRow(LinkPaste.host(url))` · `⏎`)
     whose button calls `save(url)`; then
     `FindPanelBody(model: search.model, placement: .page, open: open, prompt: Copy.homeFieldPrompt,
     focusRequest: search.focusRequest, submitOverride: { if let url = LinkPaste.url(in: search.model.query) { save(url); return true }; return false })`
     on `.glassCard(cornerRadius: CicadaTheme.radiusLarge)` (a standard material — content, R-M5),
     `.frame(maxHeight: showsResults ? .infinity : nil)` where
     `showsResults = FindPanelBody.showsBody(placement: .page, query: search.model.query, mode: search.model.mode)`.
  3. When `!showsResults`: a `ScrollView` of the sections (`HomeSections.swift`), max width 720 scaled,
     `.transition(.opacity)`; the column animates on `showsResults` with `CicadaMotion.morph(reduceMotion:)`.
  4. `.task { if sleepVM.status == nil { await sleepVM.load() } else { await sleepVM.loadHistory() } }`
     (history is not disk-cached, design §6.3). H1 (⌘1 focuses the field) needs nothing more:
     `FindPanelBody`'s own `.task` focuses its field every time Home appears.
  5. `save(url)`: `Task { do { _ = try await APIClient.shared.saveURL(url.absoluteString); store.toast =
     Copy.homeLinkSaved(LinkPaste.host(url)); search.model.setQuery(""); await store.refresh([.sources, .sourcesOverview]) }
     catch { store.toast = AddSourceSheet.friendlyError(error) } }`.

  `Views/Home/HomeSections.swift` — three views `HomeView.swift` composes (internal, not `private`:
  they are used from the other file), each a `surface` card
  (`.padding(CicadaTheme.spacingLG).background(CicadaTheme.surface, in: RoundedRectangle(cornerRadius: CicadaTheme.radiusLarge))`),
  a caption-style section title (`Copy.homeToday` / `homeNeedsYou` / `homeLastRead`, uppercased,
  `CicadaTheme.font(size: 10, weight: .semibold, design: .monospaced)`, `textTertiary`, tracking 1.2 —
  the Settings card title style), rows with a `surfaceHover` fill on hover (`CicadaMotion.hover`, never
  a lift — dense rows, R9 §3.2), each row a real `Button` (VoiceOver, H6). One `today = Date()` per
  `HomeView` body evaluation, passed down.
  - **TodaySection** — `HomeFigures.today(store.sourcesOverview.value, today:)`: `captured == nil` → "—"
    with `.help(Copy.homeLoading)`; `0` → `Copy.homeNothingCapturedToday`; else
    `Copy.homeCapturedToday(n)` with `.help(Copy.homeCapturedHelp)` and the origin chips as
    `OriginMark(origin: chip.mark, size: CicadaTheme.scaled(16))` buttons →
    `router.routeToSourceDetail(chip.sourceId)`, each `.help("\(chip.label) · \(Copy.homeCapturedToday(chip.count))")`
    and `.markHover(hovering:)` on its own hover state. Then, **only when
    `HomeLayout.showsWaitingInToday(gettingStartedVisible: gettingStartedVisible, hasRunBefore: hasRunBefore)`**,
    the waiting row: `BookwormView(state: worm, pointSize: 24)` (worm = `store.status.value.map { deriveBookwormState($0, justFinishedAt: nil) } ?? .awake`),
    `store.status.value?.episodes.unprocessed` → "—" / `Copy.homeNothingWaiting` / `Copy.homeWaiting(n)`,
    and a `Copy.homeOpenSleep` button → `selectedTab = .sleep` (a link — never `triggerManually`).
    `hasRunBefore = sleepVM.status?.debt.hasRunBefore ?? (store.status.value?.lastSleepAt != nil)`.
  - **NeedsYouSection** — `HomeFigures.needsYou(store.visibleInbox)`: empty → `Copy.homeNothingNeedsYou`;
    else one row per shown item: `Image(systemName: item.kind.icon)`, `Text(item.question ?? item.title).lineLimit(1)`,
    `Spacer`, `OriginMark(origin: harness, size: 14)` when `item.cause?.harness` is non-nil; action
    `router.pendingInboxItem = item.id; selectedTab = .inbox` (the palette's own route); then
    `Copy.homeAllInbox(total)` → `selectedTab = .inbox` when `total > 3`.
  - **LastReadSection** — `HomeFigures.lastRead(sleepVM.history, loaded: sleepVM.historyLoaded)`:
    `.loading` → "—" `.help(Copy.homeLoading)`; `.never` → `Copy.homeNothingReadYet`; `.entry(e)` →
    `HomeFigures.lastReadLine(e)`, the chips from `HomeFigures.chips(e, nodes: store.graph.value?.nodes ?? [])`
    as capsule buttons → `selectedTab = .graph; graphVM.revealEntity(id: chip.id)`, `Copy.homeMoreChips(more)`
    when `more > 0`, and `Copy.homeOpenSleep` → `.sleep`.

- [ ] **Step 6: Wire it.**
  - `CicadaApp.swift`: `@State private var homeSearch: HomeSearch`; in `init()` build the palette
    model once (`let find = FindPaletteModel(store: store)`), then `_findModel = State(initialValue: find)`
    and `_homeSearch = State(initialValue: HomeSearch(model: FindPaletteModel(store: store, ask: find.ask, keepsRecents: false)))`;
    `.environment(homeSearch)` beside `.environment(findModel)`.
  - `ContentView.swift`: `:6` `@State private var selectedTab: AppTab = .home`; `:10` default
    `AppTab.home.rawValue`; `@Environment(HomeSearch.self) private var homeSearch`;
    `otherTabContent` gains `case .home: HomeView(open: openFind, selectedTab: $selectedTab)`;
    `consumePaletteRequest` passes `homeVisible: selectedTab == .home` and handles
    `case .focusHome(let prefill, let mode): homeSearch.focus(prefill: prefill, mode: mode)`.
  - `FindIndexTask` (`:794-806`): `@Environment(HomeSearch.self) private var home`; the task body is
    `await find.rebuildIndex(); home.model.install(find.index)` — one build, two readers (R-IB4).

- [ ] **Step 7: Verify.** `cd <worktree>/app/CicadaApp && swift build 2>&1 | tail -5` → success;
  `swift test --filter "SidebarTabTests|FindPaletteTests|HomeSearchTests|HomeFiguresTests|LinkPasteTests|HomeBandLayoutTests|CopyConstantsTests" 2>&1 | tail -20` → green;
  then the full `swift test 2>&1 | tail -20` → **0 failures** (the placement, motion, font, count and
  theme-token lints included — Home names no painted component, spells no duration, and formats
  every number through `UsageFormat`).

- [ ] **Step 8: Commit** — stage the files above by name:
  `feat(home): Home is the front door at ⌘1 — search first, then Today, Needs you and Last read (G108, Track I T9a)`.

---

### Task 2 (T8 logic): What Start does — the runner, the turn-on, the record, the Welcome's rules

Nothing visible changes: this commit adds the tested machinery Tasks 3 and 4 render, extracts
part a's one turn-on so the `+` strip, the Welcome and Getting started share it, and teaches the
router to stage for the Welcome.

**Files:**
- Create: `app/…/Support/SetupRunner.swift`, `app/…/Support/FoundTurnOn.swift`,
  `app/…/Support/GettingStartedState.swift`, `app/…/Support/WelcomeLogic.swift`
- Modify: `app/…/Views/Intake/OnThisMacStrip.swift:9-13, 57-60, 93-128`
- Modify: `app/…/Support/IntakeRouter.swift:189-204, 221-247, 374-393`
- Modify: `app/…/Views/Settings/EngineOption.swift` (append)
- Modify: `app/…/Theme/Copy+Welcome.swift` (append)
- Test: new `SetupRunnerTests.swift`, `FoundTurnOnTests.swift`, `GettingStartedStateTests.swift`,
  `WelcomeLogicTests.swift`; `IntakeRouterTests.swift`, `EngineOptionTests.swift` (add)

**Interfaces:**
- Produces `FoundItemID.key` / `init?(key:)`; `GettingStartedRecord`, `GettingStartedState`
  (`load`, `record`, `settle`, `setHidden`, `setScheduleAsked`); `FoundTurnOnResult`,
  `FoundTurnOnDeps` (+ `.live(inventory:watcher:intake:)`), `FoundTurnOn.run`; `SetupEffects`,
  `SetupRunner` (`phase`, `rows`, `refused`, `detail`, `titles`, `origins`, `engineError`,
  `sawDoneThisSession`, `checklistRevision`, `checklistChanged()`, `forget(_:)`,
  `run(_:titles:origins:effects:)`, `turnOn(_:effects:)`, `demoPlan`, `workingText`); `WelcomeName`, `WelcomeTicks`, `WelcomeLayout`, `EngineChoiceLine`;
  `EngineOption.costModel/compactCandidates/compactCaption/ringed`; `IntakeRouter.welcomeActive`,
  `welcomeDrops`, `welcomeDropError`, `welcomeChooseRequest`, `removeWelcomeDrop`,
  `commitWelcomeDrop`, `commit(_ preview:from:)`, `WelcomeDrop`.
- Consumes `OnboardingFlow`, `FoundPolicy`, `AgentConnect`, `AgentSetupCatalog`,
  `BrowserWatcher.syncNow`, `LocalInventory`, `IntakePreview.aggregate`, `IntakeSummary`,
  `ScheduleHonesty.engineLine`, `EngineReadiness`.

- [ ] **Step 1: Failing tests.**

  `GettingStartedStateTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// Track I part b (R-IB17) — the Getting started record, per bank, in defaults.
final class GettingStartedStateTests: XCTestCase {
    private var defaults: UserDefaults!
    override func setUp() { defaults = UserDefaults(suiteName: "gs-\(UUID().uuidString)") }

    func testFoundItemIDsRoundTripThroughTheirKey() {
        for id in [FoundItemID.agent("claude-code"), .browser("chrome-bookmarks"), .app("md.obsidian"), .dropped("a:b")] {
            XCTAssertEqual(FoundItemID(key: id.key), id)
        }
        XCTAssertNil(FoundItemID(key: "nonsense"))
        XCTAssertNil(FoundItemID(key: "agent:"))
    }

    func testABankTheWelcomeNeverRanOnHasNoChecklist() {
        XCTAssertNil(GettingStartedState.load(bank: "default", defaults: defaults),
                     "an install onboarded before this track never sees the card")
    }

    func testRecordUnionsKeepsOrderAndNeverPersistsADroppedFile() {
        GettingStartedState.record(bank: "default", enabled: [.agent("claude-code"), .dropped("x")], defaults: defaults)
        GettingStartedState.record(bank: "default", enabled: [.browser("chrome-bookmarks"), .agent("claude-code")], defaults: defaults)
        XCTAssertEqual(GettingStartedState.load(bank: "default", defaults: defaults)?.enabled,
                       [.agent("claude-code"), .browser("chrome-bookmarks")])
        GettingStartedState.settle(.dropped("x"), bank: "default", defaults: defaults)
        XCTAssertEqual(GettingStartedState.load(bank: "default", defaults: defaults)?.settled, [],
                       "a dismissed drop is forgotten by the runner, never written down")
    }

    func testRecordingAgainReShowsAHiddenCard() {
        GettingStartedState.record(bank: "b", enabled: [], defaults: defaults)
        GettingStartedState.setHidden(true, bank: "b", defaults: defaults)
        XCTAssertEqual(GettingStartedState.load(bank: "b", defaults: defaults)?.hidden, true)
        GettingStartedState.record(bank: "b", enabled: [.agent("codex")], defaults: defaults)
        XCTAssertEqual(GettingStartedState.load(bank: "b", defaults: defaults)?.hidden, false)
    }

    func testStateIsPerBank() {
        GettingStartedState.record(bank: "a", enabled: [.agent("codex")], defaults: defaults)
        GettingStartedState.settle(.agent("cursor"), bank: "a", defaults: defaults)
        GettingStartedState.setScheduleAsked(bank: "a", defaults: defaults)
        XCTAssertNil(GettingStartedState.load(bank: "b", defaults: defaults))
        let a = GettingStartedState.load(bank: "a", defaults: defaults)
        XCTAssertEqual(a?.settled, [.agent("cursor")])
        XCTAssertEqual(a?.scheduleAsked, true)
    }
}
```

  `WelcomeLogicTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// Track I part b (design §4.1, R-IB11–R-IB13) — the Welcome's rules without a window.
final class WelcomeLogicTests: XCTestCase {
    func testTheSavedNameWinsThenTheMacAccountName() {
        XCTAssertEqual(WelcomeName.initial(saved: "Ada Example", fullUserName: "Someone Else"), "Ada Example")
        XCTAssertEqual(WelcomeName.initial(saved: "  ", fullUserName: "Ada Example"), "Ada Example")
        XCTAssertEqual(WelcomeName.initial(saved: nil, fullUserName: ""), "")
        XCTAssertEqual(WelcomeName.firstWord("Ada Example"), "Ada")
        XCTAssertEqual(WelcomeName.firstWord("  "), "")
    }

    private func item(_ id: FoundItemID, _ readiness: FoundItem.Readiness = .ready, opens: Bool = false,
                      group: FoundGroup = .agents) -> FoundItem {
        FoundItem(id: id, group: group, title: id.key, isPresent: true, content: .ownIntentionalAct,
                  readiness: readiness, opensAnotherApp: opens)
    }

    func testTicksStartAtThePolicyAndThenBelongToThePerson() {
        let cc = item(.agent("claude-code")), cursor = item(.agent("cursor"), opens: true)
        let chrome = item(.browser("chrome-bookmarks"), group: .browsers)
        var ticks = WelcomeTicks.reconcile(items: [cc, cursor, chrome], current: [], touched: [], allowRequested: [])
        XCTAssertEqual(ticks, [.agent("claude-code"), .browser("chrome-bookmarks")], "D-2: own acts, no prompt, no other app")
        ticks.remove(.agent("claude-code"))
        ticks = WelcomeTicks.reconcile(items: [cc, cursor, chrome], current: ticks,
                                       touched: [.agent("claude-code")], allowRequested: [])
        XCTAssertFalse(ticks.contains(.agent("claude-code")), "a re-probe never re-ticks what the person unticked")
    }

    func testAPermissionGrantedFromTheRowTicksIt() {
        let id = FoundItemID.browser("safari-bookmarks")
        let blocked = item(id, .needsPermission, group: .browsers)
        XCTAssertFalse(WelcomeTicks.reconcile(items: [blocked], current: [], touched: [], allowRequested: []).contains(id))
        let granted = item(id, .ready, group: .browsers)
        XCTAssertTrue(WelcomeTicks.reconcile(items: [granted], current: [], touched: [id], allowRequested: [id]).contains(id),
                      "W5: the click on Allow… stated the intent")
    }

    func testAnAlreadyOnOrFailedRowIsNeverTicked() {
        let ids: Set<FoundItemID> = [.agent("codex"), .agent("claude-code")]
        XCTAssertTrue(WelcomeTicks.reconcile(items: [item(.agent("codex"), .alreadyOn), item(.agent("claude-code"), .failed("x"))],
                                             current: ids, touched: ids, allowRequested: []).isEmpty,
                      "nothing to run, or nothing that can run")
    }

    func testTheCardScrollsInsideAPinnedFooterAtEveryZoom() {
        for scale in stride(from: CGFloat(0.8), through: 1.4001, by: 0.1) {
            for (w, h) in [(CGFloat(900), CGFloat(600)), (1200, 800), (1600, 1000)] {
                let band = WelcomeLayout.bandHeight(windowHeight: h, scale: scale)
                let top = WelcomeLayout.cardTop(windowHeight: h, scale: scale)
                XCTAssertLessThanOrEqual(band, h * WelcomeLayout.maxBandFraction)
                XCTAssertGreaterThan(top, 0)
                XCTAssertLessThan(top, band, "the card rises into the meadow, so the headline sits on the card")
                XCTAssertGreaterThanOrEqual(WelcomeLayout.cardViewport(windowHeight: h, scale: scale), 160 * scale,
                                            "\(w)×\(h) at \(scale)")
                XCTAssertLessThanOrEqual(WelcomeLayout.cardWidth(windowWidth: w, scale: scale), w - 32 * scale)
            }
        }
    }

    func testTheEngineLineNeverPromisesWhatAnUntouchedChooserWontDo() {
        let inputs = HonestyInputs(schedule: ScheduleConfig(mode: "manual", hour: 3, minute: 0), preview: nil,
                                   hasKey: false, ollamaReady: false, claudeConnected: false)
        XCTAssertEqual(EngineChoiceLine.text(pickLabel: "Ollama", readiness: .needsChoice, inputs: inputs),
                       Copy.welcomePickSaved("Ollama"))
        XCTAssertEqual(EngineChoiceLine.text(pickLabel: nil, readiness: .needsChoice, inputs: inputs), Copy.welcomeNotChosen)
        XCTAssertEqual(EngineChoiceLine.text(pickLabel: nil, readiness: .ready(candidate: "agent"), inputs: inputs),
                       ScheduleHonesty.engineLine(inputs))
    }
}
```

  `SetupRunnerTests.swift`:

```swift
import XCTest
@testable import CicadaApp

@MainActor
final class FakeSetupEffects: SetupEffects {
    var calls: [String] = []
    var ownerFails = false
    var engineFails = false
    var demoFails = false
    var results: [FoundItemID: FoundTurnOnResult] = [:]

    func saveOwner(_ name: String) async throws {
        calls.append("saveOwner:\(name)")
        if ownerFails { throw APIError.serverUnreachable }
    }
    func saveEngine(_ candidateId: String) async throws {
        calls.append("saveEngine:\(candidateId)")
        if engineFails { throw APIError.serverUnreachable }
    }
    func markOnboarded() { calls.append("markOnboarded") }
    func recordGettingStarted(_ ids: [FoundItemID]) { calls.append("record:" + ids.map(\.key).joined(separator: ",")) }
    func showHome() { calls.append("showHome") }
    func close() { calls.append("close") }
    func createDemoBank() async throws {
        calls.append("createDemoBank")
        if demoFails { throw APIError.serverUnreachable }
    }
    func turnOn(_ id: FoundItemID) async -> FoundTurnOnResult {
        calls.append("turnOn:\(id.key)")
        return results[id] ?? .on(nil)
    }
    func settle(_ id: FoundItemID) { calls.append("settle:\(id.key)") }
}

/// Track I part b (design §4.1.7, R-IB14) — what Start does, in order, and
/// which failures stop it.
@MainActor
final class SetupRunnerTests: XCTestCase {
    func testAFailedOwnerSaveRunsNothingAfterIt() async {
        let fx = FakeSetupEffects()
        fx.ownerFails = true
        let runner = SetupRunner()
        await runner.run(OnboardingFlow.plan(name: "Ada", pickedEngine: "agent", ticked: [.agent("codex")], mode: .firstRun),
                         effects: fx)
        XCTAssertEqual(fx.calls, ["saveOwner:Ada"], "the observer every later write carries (G117 R1)")
        guard case .failed = runner.phase else { return XCTFail("\(runner.phase)") }
        XCTAssertTrue(runner.rows.isEmpty)
    }

    func testStartRunsInOrderAndReachesHomeBeforeAnyRowRuns() async {
        let fx = FakeSetupEffects()
        let runner = SetupRunner()
        await runner.run(OnboardingFlow.plan(name: "Ada", pickedEngine: "agent",
                                             ticked: [.agent("claude-code"), .browser("chrome-bookmarks")], mode: .firstRun),
                         effects: fx)
        XCTAssertEqual(Array(fx.calls.prefix(5)),
                       ["saveOwner:Ada", "saveEngine:agent", "markOnboarded",
                        "record:agent:claude-code,browser:chrome-bookmarks", "showHome"])
        XCTAssertEqual(Set(fx.calls.dropFirst(5)), ["turnOn:agent:claude-code", "turnOn:browser:chrome-bookmarks"])
        XCTAssertEqual(runner.rows[.agent("claude-code")], .on)
        XCTAssertEqual(runner.phase, .started)
    }

    func testAFailureStaysOnItsRow() async {
        let fx = FakeSetupEffects()
        fx.results = [.agent("codex"): .failed(Copy.foundInvalidSettings), .agent("claude-code"): .refused(["claude mcp add …"])]
        let runner = SetupRunner()
        await runner.run(OnboardingFlow.plan(name: "Ada", pickedEngine: nil,
                                             ticked: [.agent("codex"), .agent("claude-code"), .browser("chrome-bookmarks")],
                                             mode: .firstRun),
                         effects: fx)
        XCTAssertEqual(runner.rows[.agent("codex")], .failed(Copy.foundInvalidSettings))
        XCTAssertNil(runner.rows[.agent("claude-code")])
        XCTAssertEqual(runner.refused[.agent("claude-code")], ["claude mcp add …"])
        XCTAssertEqual(runner.rows[.browser("chrome-bookmarks")], .on)
        XCTAssertEqual(runner.phase, .started, "a row's failure is never global (§4.1.7 item 6)")
    }

    func testAnEngineSaveFailureIsSaidOnHomeNotOnTheWelcome() async {
        let fx = FakeSetupEffects()
        fx.engineFails = true
        let runner = SetupRunner()
        await runner.run(OnboardingFlow.plan(name: "Ada", pickedEngine: "local", ticked: [], mode: .firstRun), effects: fx)
        XCTAssertTrue(fx.calls.contains("showHome"))
        XCTAssertEqual(runner.engineError, Copy.gsEngineFailed)
    }

    func testTheDemoMarksOnlyAfterTheBankExists() async {
        let failing = FakeSetupEffects()
        failing.demoFails = true
        await SetupRunner().run(SetupRunner.demoPlan, effects: failing)
        XCTAssertEqual(failing.calls, ["createDemoBank"])
        let ok = FakeSetupEffects()
        await SetupRunner().run(SetupRunner.demoPlan, effects: ok)
        XCTAssertEqual(ok.calls, ["createDemoBank", "markOnboarded", "showHome"])
    }

    func testCursorIsSettledOnceItsOwnConfirmIsOpen() async {
        let fx = FakeSetupEffects()
        fx.results = [.agent("cursor"): .openedApp]
        let runner = SetupRunner()
        await runner.turnOn(.agent("cursor"), effects: fx)
        XCTAssertEqual(runner.rows[.agent("cursor")], .on)
        XCTAssertEqual(fx.calls, ["turnOn:agent:cursor", "settle:agent:cursor"])
    }
}
```

  `FoundTurnOnTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// Track I part b — the one turn-on (extracted from `OnThisMacStrip`, part a
/// T7) that the `+` strip, the Welcome's Start and Getting started share.
@MainActor
final class FoundTurnOnTests: XCTestCase {
    private func wiring() -> AgentWiringResponse {
        AgentWiringResponse(agents: [AgentWiring(id: "codex", installed: true, binary: "/bin/codex", recall: "off",
                                                 autosave: "off",
                                                 connect: [AgentWiringStep(step: "mcp", display: "d0", argv: ["a"], touches: [])],
                                                 detail: nil)],
                            python: "/R/api/.venv/bin/python", repo: "/R", memory: "/M")
    }

    private func deps(wiring: AgentWiringResponse? = nil, connect: AgentConnectOutcome = .done,
                      sync: Result<String, Error> = .success("412 bookmarks saved"),
                      readiness: FoundItem.Readiness? = .ready,
                      opened: @escaping (URL) -> Void = { _ in }, drop: IntakeOutcome? = nil) -> FoundTurnOnDeps {
        FoundTurnOnDeps(wiring: { wiring }, installRoot: URL(fileURLWithPath: "/R"),
                        connect: { _, _, _ in connect }, syncBrowser: { _ in try sync.get() },
                        readiness: { _ in readiness }, open: opened, commitDrop: { _ in drop }, refresh: {})
    }

    func testAnAgentRunsItsStepsAndReportsOn() async {
        let r = await FoundTurnOn.run(.agent("codex"), deps: deps(wiring: wiring()))
        XCTAssertEqual(r, .on(nil))
    }

    func testARefusalHandsBackTheLinesAndAnExitThreeIsItsSentence() async {
        let refused = await FoundTurnOn.run(.agent("codex"), deps: deps(wiring: wiring(), connect: .refused(["d0"])))
        XCTAssertEqual(refused, .refused(["d0"]))
        let invalid = await FoundTurnOn.run(.agent("codex"),
                                            deps: deps(wiring: wiring(), connect: .failed(Copy.foundInvalidSettings)))
        XCTAssertEqual(invalid, .failed(Copy.foundInvalidSettings))
    }

    func testNoWiringMeansTheBackendIsDownNotThatTheAgentIsOff() async {
        let r = await FoundTurnOn.run(.agent("codex"), deps: deps(wiring: nil))
        XCTAssertEqual(r, .failed(Copy.foundBackendDown))
    }

    func testABlockedBrowserOpensFullDiskAccessAndReadsNothing() async {
        var opened: [URL] = []
        let r = await FoundTurnOn.run(.browser("safari-bookmarks"),
                                      deps: deps(readiness: .needsPermission, opened: { opened.append($0) }))
        XCTAssertEqual(r, .needsPermission)
        XCTAssertEqual(opened, [BrowserFileError.fullDiskAccessURL])
    }

    func testABrowserSyncReturnsItsOwnLine() async {
        let r = await FoundTurnOn.run(.browser("chrome-bookmarks"), deps: deps())
        XCTAssertEqual(r, .on("412 bookmarks saved"))
    }

    func testCursorOpensItsDeepLinkAndClaudeDesktopFinishesInSettings() async {
        var opened: [URL] = []
        let cursor = await FoundTurnOn.run(.agent("cursor"), deps: deps(wiring: wiring(), opened: { opened.append($0) }))
        XCTAssertEqual(cursor, .openedApp)
        XCTAssertEqual(opened.first?.scheme, "cursor")
        let desktop = await FoundTurnOn.run(.agent("claude-desktop"), deps: deps())
        XCTAssertEqual(desktop, .finishInSettings(.agents))
    }

    func testADroppedExportIsCommittedAndSaysWhatCameIn() async {
        var outcome = IntakeOutcome(vendor: "chatgpt", origin: "chatgpt-export")
        outcome.created = 3
        let r = await FoundTurnOn.run(.dropped("x"), deps: deps(drop: outcome))
        XCTAssertEqual(r, .on(IntakeSummary.headline(outcome)))
    }
}
```

  `IntakeRouterTests.swift` — add (uses the file's own `file`, `chat`, `eventually`):

```swift
    /// R-IB15 — while the Welcome shows, every arrival is staged on it; nothing imports before Start.
    func testWhileTheWelcomeShowsEveryArrivalIsStagedAndNothingImports() async throws {
        let api = FakeIntakeAPI()
        api.sniffs = ["conversations.json": chat("chatgpt", new: 4)]
        let router = IntakeRouter(api: api)
        router.welcomeActive = true
        router.accept(urls: [try file("conversations.json")], from: .dock)
        try await eventually("a staged row") { router.welcomeDrops.count == 1 }
        XCTAssertFalse(router.isOverlayPresented, "the Welcome is the host; no overlay hidden under it")
        XCTAssertEqual(router.phase, .idle)
        XCTAssertTrue(api.importedBanks.isEmpty, "nothing imports before Start (principle 2)")
        XCTAssertEqual(router.welcomeDrops.first?.preview.delta.new, 4)
        XCTAssertEqual(router.inFlight, 0)
    }

    func testPresentWhileTheWelcomeShowsAsksItToChooseAFile() {
        let router = IntakeRouter(api: FakeIntakeAPI())
        router.welcomeActive = true
        router.present(from: .fileMenu)
        XCTAssertEqual(router.welcomeChooseRequest, 1)
        XCTAssertFalse(router.isOverlayPresented)
    }

    func testAStagedDropCommitsChatAndSavedFilesThroughTheirOwnRoutes() async throws {
        let api = FakeIntakeAPI()
        api.sniffs = ["conversations.json": chat("claude"),
                      "bookmarks.html": IntakeSniff(recognized: true, kind: "saved", counts: IntakeCounts(items: 2))]
        api.imports = ["conversations.json": IntakeImportResponse(episodesStaged: 1)]
        let router = IntakeRouter(api: api)
        router.welcomeActive = true
        router.accept(urls: [try file("conversations.json"), try file("bookmarks.html")], from: .welcome)
        try await eventually("staged") { router.welcomeDrops.count == 1 }
        let outcome = await router.commitWelcomeDrop(router.welcomeDrops[0].id)
        XCTAssertEqual(outcome?.created, 1)
        XCTAssertEqual(outcome?.savedCreated, 2, "saved content commits through /sources/upload (R-IA32)")
        XCTAssertTrue(router.welcomeDrops.isEmpty)
    }

    /// R-IB15 — a commit that failed keeps its drop staged, so Getting started's Retry has
    /// something to commit (a forgotten drop would fail "The import didn't finish." forever).
    func testAFailedStagedCommitStaysForRetry() async throws {
        let api = FakeIntakeAPI()
        api.sniffs = ["conversations.json": chat("claude")]
        api.failImport = ["conversations.json"]
        let router = IntakeRouter(api: api)
        router.welcomeActive = true
        router.accept(urls: [try file("conversations.json")], from: .welcome)
        try await eventually("staged") { router.welcomeDrops.count == 1 }
        let outcome = await router.commitWelcomeDrop(router.welcomeDrops[0].id)
        XCTAssertEqual(outcome?.failures.count, 1)
        XCTAssertEqual(router.welcomeDrops.count, 1)
    }

    /// R-IB15 — a Dock open that reached the overlay before the gate raised the Welcome is
    /// moved onto the Welcome, never left as a preview hidden underneath it.
    func testRaisingTheWelcomeAdoptsASniffAlreadyOnTheOverlay() async throws {
        let api = FakeIntakeAPI()
        api.sniffs = ["conversations.json": chat("chatgpt", new: 3)]
        let router = IntakeRouter(api: api)
        router.accept(urls: [try file("conversations.json")], from: .dock)
        XCTAssertTrue(router.isOverlayPresented)
        router.welcomeActive = true
        XCTAssertFalse(router.isOverlayPresented, "nothing hidden under the Welcome")
        try await eventually("adopted") { router.welcomeDrops.count == 1 }
        XCTAssertEqual(router.phase, .idle)
        XCTAssertTrue(api.importedBanks.isEmpty, "adopting is staging, never importing")
    }
```

  `EngineOptionTests.swift` — add (uses the file's `card` helper):

```swift
    /// G117 (owner 2026-09-04) — each option states its cost model before it is chosen; never a price.
    func testEveryCompactCardStatesItsCostModelAndNeverAPrice() throws {
        for id in ["agent", "codex", "local", "byok"] {
            let line = try XCTUnwrap(EngineOption.costModel(for: id), id)
            XCTAssertFalse(line.contains("$"), line)
            XCTAssertNil(line.rangeOfCharacter(from: .decimalDigits), "a cost model, not a price: \(line)")
        }
        XCTAssertNil(EngineOption.costModel(for: "auto"))
    }

    func testTheCompactRowHidesAutoBecauseUntouchedMeansAuto() {
        XCTAssertEqual(EngineOption.compactCandidates([card("auto"), card("agent"), card("byok")]).map(\.id), ["agent", "byok"])
    }

    func testTheRingFollowsThePickThenAnEngineThatCanRun() {
        XCTAssertEqual(EngineOption.ringed(pick: "local", readiness: .ready(candidate: "agent")), "local")
        XCTAssertEqual(EngineOption.ringed(pick: nil, readiness: .ready(candidate: "agent")), "agent")
        XCTAssertNil(EngineOption.ringed(pick: nil, readiness: .needsChoice))
    }

    func testAKeyCardSaysWhetherAKeyExists() {
        XCTAssertEqual(EngineOption.compactCaption(for: card("byok"), hasKey: false), Copy.engineAddKey)
        XCTAssertEqual(EngineOption.compactCaption(for: card("byok"), hasKey: true), Copy.engineKeySaved)
        XCTAssertEqual(EngineOption.compactCaption(for: card("codex"), hasKey: false), "Signed in")
    }
```

  Red: `swift build` fails on the missing symbols.

- [ ] **Step 2: `Support/GettingStartedState.swift`.**

```swift
import Foundation

/// A found item's stable spelling for defaults (`cicada.gettingStarted.<bank>.enabled`).
extension FoundItemID {
    var key: String {
        switch self {
        case .agent(let id): "agent:\(id)"
        case .browser(let id): "browser:\(id)"
        case .app(let id): "app:\(id)"
        case .dropped(let id): "dropped:\(id)"
        }
    }

    init?(key: String) {
        let parts = key.split(separator: ":", maxSplits: 1).map(String.init)
        guard parts.count == 2, !parts[1].isEmpty else { return nil }
        switch parts[0] {
        case "agent": self = .agent(parts[1])
        case "browser": self = .browser(parts[1])
        case "app": self = .app(parts[1])
        case "dropped": self = .dropped(parts[1])
        default: return nil
        }
    }
}

struct GettingStartedRecord: Equatable {
    var enabled: [FoundItemID] = []
    var settled: Set<FoundItemID> = []
    var hidden = false
    var scheduleAsked = false
}

/// Track I part b (R-IB17) — the Getting started card's memory, per bank, in
/// `UserDefaults` (the `OnboardingState` pattern: a dynamic key cannot be an
/// `@AppStorage`). Absent `enabled` means the Welcome never ran on this bank, so
/// an install onboarded before this track never sees a card it did not ask for.
/// A dropped file is never persisted — its row is this session's result, not a
/// standing connection.
enum GettingStartedState {
    static func key(_ bank: String, _ field: String) -> String { "cicada.gettingStarted.\(bank).\(field)" }

    static func load(bank: String, defaults: UserDefaults = .standard) -> GettingStartedRecord? {
        guard let keys = defaults.stringArray(forKey: key(bank, "enabled")) else { return nil }
        return GettingStartedRecord(
            enabled: keys.compactMap(FoundItemID.init(key:)),
            settled: Set((defaults.stringArray(forKey: key(bank, "settled")) ?? []).compactMap(FoundItemID.init(key:))),
            hidden: defaults.bool(forKey: key(bank, "hidden")),
            scheduleAsked: defaults.bool(forKey: key(bank, "scheduleAsked")))
    }

    /// Unions, keeps first-seen order, and un-hides: a rerun that turns more on
    /// must show the card again.
    static func record(bank: String, enabled: [FoundItemID], defaults: UserDefaults = .standard) {
        var keys = defaults.stringArray(forKey: key(bank, "enabled")) ?? []
        for id in enabled {
            if case .dropped = id { continue }
            if !keys.contains(id.key) { keys.append(id.key) }
        }
        defaults.set(keys, forKey: key(bank, "enabled"))
        defaults.set(false, forKey: key(bank, "hidden"))
    }

    /// A drop is this session's result, so its ✕ is `SetupRunner.forget`, never a record.
    static func settle(_ id: FoundItemID, bank: String, defaults: UserDefaults = .standard) {
        if case .dropped = id { return }
        var keys = defaults.stringArray(forKey: key(bank, "settled")) ?? []
        if !keys.contains(id.key) { keys.append(id.key) }
        defaults.set(keys, forKey: key(bank, "settled"))
    }

    static func setHidden(_ hidden: Bool, bank: String, defaults: UserDefaults = .standard) {
        defaults.set(hidden, forKey: key(bank, "hidden"))
    }

    static func setScheduleAsked(bank: String, defaults: UserDefaults = .standard) {
        defaults.set(true, forKey: key(bank, "scheduleAsked"))
    }
}
```

- [ ] **Step 3: `Support/WelcomeLogic.swift`.**

```swift
import Foundation

/// Design §4.1.5 — the name is required (G117 R1: it is the observer), prefilled
/// from what the person already told Cicada, else the Mac account (no Contacts prompt).
enum WelcomeName {
    static func initial(saved: String?, fullUserName: String) -> String {
        let saved = (saved ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        return saved.isEmpty ? fullUserName.trimmingCharacters(in: .whitespacesAndNewlines) : saved
    }

    static func firstWord(_ name: String) -> String {
        name.trimmingCharacters(in: .whitespacesAndNewlines).split(separator: " ").first.map(String.init) ?? ""
    }
}

/// Design §4.1.4 / W4 / W5 — the ticks are the consent. Untouched rows follow
/// `FoundPolicy.defaultOn`; a row the person touched keeps their answer through
/// every re-probe; a permission granted from the row's own Allow… ticks it.
/// A row with nothing to run (already on) or nothing that can run (failed,
/// checking, still blocked) is never ticked.
enum WelcomeTicks {
    static func canTick(_ item: FoundItem) -> Bool { item.isPresent && item.readiness == .ready }

    static func reconcile(items: [FoundItem], current: Set<FoundItemID>, touched: Set<FoundItemID>,
                          allowRequested: Set<FoundItemID>) -> Set<FoundItemID> {
        var out = Set<FoundItemID>()
        for item in items where canTick(item) {
            if allowRequested.contains(item.id) { out.insert(item.id); continue }
            if touched.contains(item.id) {
                if current.contains(item.id) { out.insert(item.id) }
            } else if FoundPolicy.defaultOn(item) {
                out.insert(item.id)
            }
        }
        return out
    }
}

/// R-IB11 — the Welcome's geometry: the hero band (≈ 36 % of the window, never
/// under 240 scaled points unless that would pass 45 %), the card rising 96
/// scaled points into the meadow, and a footer pinned OUTSIDE the card's scroll
/// view (the G130 lesson `FirstRunSheet` learned: the one way forward must never
/// be the first thing to clip at 1.4×).
enum WelcomeLayout {
    static let bandFraction: CGFloat = 0.36
    static let maxBandFraction: CGFloat = 0.45
    static let minBand: CGFloat = 240
    static let overlap: CGFloat = 96
    static let cardMaxWidth: CGFloat = 680
    static let footerHeight: CGFloat = 128
    static let gutter: CGFloat = 16

    static func bandHeight(windowHeight h: CGFloat, scale: CGFloat) -> CGFloat {
        min(max(h * bandFraction, minBand * scale), h * maxBandFraction)
    }

    static func cardTop(windowHeight h: CGFloat, scale: CGFloat) -> CGFloat {
        bandHeight(windowHeight: h, scale: scale) - overlap * scale
    }

    static func cardViewport(windowHeight h: CGFloat, scale: CGFloat) -> CGFloat {
        h - cardTop(windowHeight: h, scale: scale) - footerHeight * scale
    }

    static func cardWidth(windowWidth w: CGFloat, scale: CGFloat) -> CGFloat {
        min(cardMaxWidth * scale, w - 2 * gutter * scale)
    }
}

/// R-IB13 — the one line under the engine cards. The server's preview cannot
/// know a local pick, so a pick says only that Start will save it; an untouched
/// chooser with nothing that can run says so; otherwise ScheduleHonesty speaks.
enum EngineChoiceLine {
    static func text(pickLabel: String?, readiness: EngineReadiness, inputs: HonestyInputs) -> String {
        if let pickLabel { return Copy.welcomePickSaved(pickLabel) }
        if readiness == .needsChoice { return Copy.welcomeNotChosen }
        return ScheduleHonesty.engineLine(inputs)
    }
}
```

- [ ] **Step 4: `Support/FoundTurnOn.swift`.** Move `OnThisMacStrip.turnOn`'s decisions here verbatim in
  meaning (the Cursor deep link through `AgentSetupCatalog`, the empty-`repo` guard, `AgentConnect`
  with the probe's binaries, Full Disk Access for a blocked browser, `watcher.syncNow`), plus the two
  new ids:

```swift
import AppKit
import Foundation

enum FoundTurnOnResult: Equatable {
    /// On; the line is the row's new detail (a sync's own result), or nil for the default.
    case on(String?)
    /// Not run: these are the commands, to inspect (AgentConnectPolicy refused them).
    case refused([String])
    case failed(String)
    /// Full Disk Access opened; the row ticks itself when the grant lands (W5).
    case needsPermission
    /// Cursor asks the person itself; nothing more for Cicada to know.
    case openedApp
    case finishInSettings(SettingsSection)
}

/// Everything a turn-on touches, injected (FoundTurnOnTests), all main-actor
/// because the live ones read `LocalInventory`, `BrowserWatcher` and the router.
struct FoundTurnOnDeps {
    var wiring: @MainActor () -> AgentWiringResponse?
    var installRoot: URL
    var connect: @MainActor ([AgentWiringStep], URL, Set<String>) async -> AgentConnectOutcome
    var syncBrowser: @MainActor (String) async throws -> String
    var readiness: @MainActor (FoundItemID) -> FoundItem.Readiness?
    var open: @MainActor (URL) -> Void
    var commitDrop: @MainActor (String) async -> IntakeOutcome?
    var refresh: @MainActor () async -> Void

    @MainActor
    static func live(inventory: LocalInventory, watcher: BrowserWatcher, intake: IntakeRouter) -> FoundTurnOnDeps {
        FoundTurnOnDeps(
            wiring: { inventory.wiring },
            installRoot: BackendProcess.installRoot(),
            connect: { steps, root, binaries in await AgentConnect.run(steps, installRoot: root, binaries: binaries) },
            syncBrowser: { try await watcher.syncNow($0) },
            readiness: { id in inventory.items.first { $0.id == id }?.readiness },
            open: { NSWorkspace.shared.open($0) },
            commitDrop: { await intake.commitWelcomeDrop($0) },
            refresh: { await inventory.refresh() })
    }
}

/// Track I part b — the ONE turn-on (part a's `OnThisMacStrip.turnOn`, hoisted):
/// the `+` strip, the Welcome's Start and Getting started's Turn on / Retry all
/// run this, so an agent is wired, a browser consented and an export committed
/// the same way from every host (design §3.8: one component, many hosts).
@MainActor
enum FoundTurnOn {
    static func run(_ id: FoundItemID, deps: FoundTurnOnDeps) async -> FoundTurnOnResult {
        switch id {
        case .agent("cursor"):
            // An empty `repo` (a trimmed payload decodes to "") must not build a
            // deep link against "/api/.venv/bin/python" (part a final review).
            let wiring = deps.wiring()
            let repo = wiring.map(\.repo).flatMap { $0.isEmpty ? nil : $0 } ?? deps.installRoot.path
            guard let url = AgentSetupCatalog.all(home: repo, memoryRoot: wiring?.memory)
                .first(where: { $0.id == "cursor" })?.deeplink?.url else { return .failed(Copy.intakeFailed) }
            deps.open(url)
            return .openedApp
        case .agent("claude-desktop"):
            return .finishInSettings(.agents)
        case .agent(let agentId):
            guard let wiring = deps.wiring(), let agent = wiring.agents.first(where: { $0.id == agentId }) else {
                return .failed(Copy.foundBackendDown)
            }
            if agent.connect.isEmpty {
                return agent.recall == "on" && agent.autosave == "on" ? .on(nil) : .failed(Copy.foundCouldNotCheck)
            }
            let outcome = await deps.connect(agent.connect, deps.installRoot, Set(wiring.agents.compactMap(\.binary)))
            await deps.refresh()
            switch outcome {
            case .done: return .on(nil)
            case .refused(let lines): return .refused(lines)
            case .failed(let why): return .failed(why)
            }
        case .browser(let channel):
            if deps.readiness(id) == .needsPermission {
                deps.open(BrowserFileError.fullDiskAccessURL)
                return .needsPermission
            }
            do {
                let line = try await deps.syncBrowser(channel)
                await deps.refresh()
                return .on(line)
            } catch {
                return .failed(AddSourceSheet.friendlyError(error))
            }
        case .dropped(let dropId):
            guard let outcome = await deps.commitDrop(dropId) else { return .failed(Copy.intakeFailed) }
            if outcome.total == 0, let first = outcome.failures.first { return .failed(first) }
            return .on(IntakeSummary.headline(outcome))
        case .app:
            return .finishInSettings(.integrations)
        }
    }
}
```

  (`AddSourceSheet.friendlyError` is a static on a view, so main-actor; `FoundTurnOn` is
  `@MainActor`, as `IntakeRouter` — which already calls it — is. An `IntakeOutcome` with
  `total == 0` and no failures — "Nothing new came in." — reads as On, which is right: the export is
  in.)

  Then `OnThisMacStrip.swift`: add `@Environment(IntakeRouter.self) private var intake`; replace the
  private `turnOn(_:agent:wiring:)` with one that sets `states[item.id] = .working(SetupRunner.workingText(item.id))`
  (except Cursor, which opens at once), clears `refused[item.id]`, runs
  `FoundTurnOn.run(item.id, deps: .live(inventory: inventory, watcher: watcher, intake: intake))`, and maps:
  `.on`, `.openedApp`, `.finishInSettings`, `.needsPermission` → `states[item.id] = nil`;
  `.refused(lines)` → `states[item.id] = nil; refused[item.id] = lines`; `.failed(why)` →
  `states[item.id] = .failed(why)`. The row's `action:` closure becomes
  `{ Task { await turnOn(item) } }`. Behaviour is unchanged but for one honest difference: a click on
  an agent while `/agents/wiring` has not answered used to do nothing (`guard let agent, let wiring
  else { return }`, `:102`) and now says `Copy.foundBackendDown` on the row. Part a's
  `LocalInventoryTests` and the strip's live check still hold.

- [ ] **Step 5: `Support/SetupRunner.swift`.**

```swift
import Foundation
import Observation

/// What a Start step does in the world — injected so the order and the
/// failure rules are tested without a window (SetupRunnerTests).
@MainActor
protocol SetupEffects {
    func saveOwner(_ name: String) async throws
    func saveEngine(_ candidateId: String) async throws
    func markOnboarded()
    func recordGettingStarted(_ ids: [FoundItemID])
    func showHome()
    func close()
    func createDemoBank() async throws
    func turnOn(_ id: FoundItemID) async -> FoundTurnOnResult
    func settle(_ id: FoundItemID)
}

/// Track I part b (design §4.1.7, R-IB14) — executes part a's `OnboardingFlow`
/// plan. The owner PUT runs alone and first: it is the observer every later
/// write carries (G117 R1), so its failure stops everything. The sequential
/// steps end on Home before any row runs (Start costs one round trip); the rows
/// then run side by side, each reporting here, and a failure stays on its row.
/// App-lifetime, so a Welcome that has faded out keeps reporting to Home's
/// Getting started card.
@MainActor
@Observable
final class SetupRunner {
    enum Phase: Equatable { case idle, starting, failed(String), started }

    static let demoPlan: [StartStep] = OnboardingFlow.demoSteps + [.showHome]

    private(set) var phase: Phase = .idle
    private(set) var rows: [FoundItemID: FoundRowState] = [:]
    private(set) var refused: [FoundItemID: [String]] = [:]
    private(set) var detail: [FoundItemID: String] = [:]
    /// A dropped export's title ("ChatGPT history") and origin ("chatgpt-export",
    /// for its real mark), captured at Start — the router forgets the drop once
    /// it is committed.
    private(set) var titles: [FoundItemID: String] = [:]
    private(set) var origins: [FoundItemID: String] = [:]
    private(set) var engineError: String?
    /// "You're set up." shows for the rest of the session once, then the card hides.
    var sawDoneThisSession = false
    /// Bumped after every `GettingStartedState` write, so Home and the card —
    /// which read the record straight from defaults in `body` (four keys) —
    /// re-render when it changes. Defaults are not observable; this is.
    private(set) var checklistRevision = 0

    func checklistChanged() { checklistRevision &+= 1 }

    /// ✕ on a dropped export's row: it lives only in this session's state, so
    /// dismissing it is forgetting it (R-IB17 — a drop is never persisted).
    func forget(_ id: FoundItemID) {
        rows[id] = nil
        refused[id] = nil
        detail[id] = nil
    }

    func run(_ plan: [StartStep], titles: [FoundItemID: String] = [:], origins: [FoundItemID: String] = [:],
             effects: SetupEffects) async {
        phase = .starting
        engineError = nil
        self.titles.merge(titles) { _, new in new }
        self.origins.merge(origins) { _, new in new }
        var turnOns: [FoundItemID] = []
        for step in plan {
            switch step {
            case .saveOwner(let name):
                do { try await effects.saveOwner(name) } catch { phase = .failed(Self.describe(error)); return }
            case .saveEngine(let id):
                do { try await effects.saveEngine(id) } catch { engineError = Copy.gsEngineFailed }
            case .markOnboarded:
                effects.markOnboarded()
            case .recordGettingStarted(let ids):
                effects.recordGettingStarted(ids)
            case .showHome:
                effects.showHome()
            case .close:
                effects.close()
            case .createDemoBank:
                do { try await effects.createDemoBank() } catch {
                    phase = .failed(Copy.welcomeDemoFailed(Self.describe(error)))
                    return
                }
            case .turnOn(let id):
                turnOns.append(id)
            }
        }
        for id in turnOns { rows[id] = .working(Self.workingText(id)) }
        phase = .started
        let tasks = turnOns.map { id in Task { @MainActor in await self.turnOn(id, effects: effects) } }
        for task in tasks { await task.value }
    }

    /// One row — Start's children and Getting started's Turn on / Retry alike.
    func turnOn(_ id: FoundItemID, effects: SetupEffects) async {
        rows[id] = .working(Self.workingText(id))
        refused[id] = nil
        switch await effects.turnOn(id) {
        case .on(let line):
            rows[id] = .on
            if let line { detail[id] = line }
        case .refused(let lines):
            rows[id] = nil
            refused[id] = lines
        case .failed(let why):
            rows[id] = .failed(why)
        case .needsPermission:
            rows[id] = .needsAction(Copy.foundAllow)
        case .openedApp:
            rows[id] = .on
            effects.settle(id)
        case .finishInSettings:
            rows[id] = nil
        }
    }

    static func workingText(_ id: FoundItemID) -> String {
        switch id {
        case .browser: Copy.foundSavingBookmarks
        case .dropped: Copy.gsBringingIn
        default: Copy.foundConnecting
        }
    }

    static func describe(_ error: Error) -> String {
        (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
    }
}
```

- [ ] **Step 6: The router stages for the Welcome (R-IB15).** In `IntakeRouter.swift`:

```swift
/// One file set dropped on the Welcome, sniffed and waiting for Start.
struct WelcomeDrop: Identifiable, Equatable {
    let id: String
    let preview: IntakePreview
}
```

  Add, beside `sniffedPreview`:

```swift
    /// Track I part b (R-IB15) — `ContentView` sets this while the Welcome shows:
    /// every arrival (window, Dock, menu bar, File → Import) is sniffed and staged
    /// as a ticked row there, never raised as an overlay hidden underneath, and
    /// nothing imports until Start commits it. Raising it clears an earlier
    /// Welcome's leftovers and adopts a sniff already on the overlay: a Dock open
    /// on a cold launch reaches `accept` before the gate has resolved the bank.
    var welcomeActive = false {
        didSet {
            guard welcomeActive, !oldValue else { return }
            welcomeDrops = []
            welcomeDropError = nil
            let adoptable: Bool
            switch phase {
            case .reading, .preview: adoptable = host == .overlay
            default: adoptable = false
            }
            guard adoptable, !files.isEmpty else { return }
            let pending = files
            cancel()                      // the generation drops the overlay's answer
            isOverlayPresented = false
            stageForWelcome(pending)
        }
    }
    private(set) var welcomeDrops: [WelcomeDrop] = []
    private(set) var welcomeDropError: String?
    /// ⌘⇧I and the menu bar while the Welcome shows: it opens its own file panel.
    private(set) var welcomeChooseRequest = 0
```

  `present(from:)` starts with `if welcomeActive { welcomeChooseRequest &+= 1; return }`; `accept`
  (after its `isImporting` guard) with `if welcomeActive { stageForWelcome(urls); return }`. Then:

```swift
    private func stageForWelcome(_ urls: [URL]) {
        let expanded = Self.expand(urls)
        welcomeDropError = nil
        guard !expanded.files.isEmpty else { welcomeDropError = Copy.intakeNothingReadable; return }
        Task { [weak self] in
            guard let self else { return }
            var results: [IntakeFileSniff] = []
            for url in expanded.files {
                do {
                    let s = try await self.tracked { try await self.api.sniffIntake(fileURL: url, bank: nil) }
                    results.append(IntakeFileSniff(url: url, sniff: s))
                } catch {
                    results.append(IntakeFileSniff(url: url, error: AddSourceSheet.friendlyError(error)))
                }
            }
            switch IntakePreview.aggregate(results, capped: expanded.capped) {
            case .preview(let p): self.welcomeDrops.append(WelcomeDrop(id: UUID().uuidString, preview: p))
            case .failed(let reason): self.welcomeDropError = reason
            default: break
            }
        }
    }

    func removeWelcomeDrop(_ id: String) { welcomeDrops.removeAll { $0.id == id } }

    /// Start's path for a staged drop: commit it, then forget it — unless a file
    /// failed, so Getting started's Retry can commit it again (a re-commit of the
    /// files that did land reads as unchanged, G20).
    func commitWelcomeDrop(_ id: String) async -> IntakeOutcome? {
        guard let drop = welcomeDrops.first(where: { $0.id == id }) else { return nil }
        let outcome = await commit(drop.preview, from: .welcome)
        if outcome.failures.isEmpty { removeWelcomeDrop(id) }
        return outcome
    }

    /// Chat files through `/intake/import` (a background job followed to its end),
    /// saved files through `/sources/upload` — the route that previewed them
    /// (R-IA32) — then one Store refresh. The counter owns the flag throughout.
    func commit(_ preview: IntakePreview, from origin: IntakeOrigin) async -> IntakeOutcome {
        var outcome = IntakeOutcome(vendor: preview.vendor, origin: preview.origin)
        for url in preview.chatFiles {
            do {
                let r = try await tracked { try await api.importIntake(fileURL: url, bank: nil) }
                if let job = r.job {
                    let status = try await follow(job, gen: -1)
                    outcome.add(created: status.created, updated: status.updated, unchanged: status.skipped, response: r)
                } else {
                    outcome.add(created: r.episodesStaged, updated: r.episodesUpdated, unchanged: r.duplicatesSkipped, response: r)
                }
            } catch {
                outcome.failures.append("\(url.lastPathComponent): \(AddSourceSheet.friendlyError(error))")
            }
        }
        for url in preview.savedFiles {
            do {
                let r = try await tracked { try await api.uploadSaved(fileURL: url) }
                outcome.savedCreated += r.episodesCreated
                outcome.unchanged += r.duplicatesSkipped
            } catch {
                outcome.failures.append("\(url.lastPathComponent): \(AddSourceSheet.friendlyError(error))")
            }
        }
        await store?.refresh([.channels, .status, .sources, .sourcesOverview, .graph, .banks])
        return outcome
    }
```

  and make the existing `commit(urls:from:)` delegate:
  `await commit(IntakePreview(chatFiles: Self.expand(urls).files), from: origin)` (identical behaviour
  for its chat-only callers).

- [ ] **Step 7: `EngineOption` and copy.** Append to `EngineOption`:

```swift
    /// G117 (owner 2026-09-04): each option states how it is paid for BEFORE it
    /// is chosen — a cost model in words, never a price (2026-09-03).
    static func costModel(for candidateId: String) -> String? {
        switch candidateId {
        case "agent", "codex": Copy.costModelPlan
        case "local": Copy.costModelLocal
        case "byok": Copy.costModelKey
        default: nil
        }
    }

    /// R-IB13 — onboarding offers the four engines a new person can name; the
    /// Auto ladder stays a Settings → Sleep choice. Leaving the row untouched
    /// keeps the install's configured default (`byok` unless a pref or
    /// `CICADA_LLM_MODE` says otherwise), which `EngineReadiness` reports honestly.
    static func compactCandidates(_ candidates: [SleepEngineCandidate]) -> [SleepEngineCandidate] {
        candidates.filter { $0.id != "auto" }
    }

    /// The key card's state comes from `Store.connections`, never from the byok
    /// candidate, which is `connected: true` even with no key (F6).
    static func compactCaption(for candidate: SleepEngineCandidate, hasKey: Bool) -> String {
        candidate.id == "byok" ? (hasKey ? Copy.engineKeySaved : Copy.engineAddKey) : caption(for: candidate)
    }

    /// The ring: the person's pick, else the engine a manual read would really use.
    static func ringed(pick: String?, readiness: EngineReadiness) -> String? {
        if let pick { return pick }
        if case .ready(let id) = readiness { return id }
        return nil
    }
```

  Append to `Copy+Welcome.swift` (and add each label to `welcomeHomeLabels`):

```swift
    // MARK: Who reads (Task 2, R-IB13)
    static let costModelPlan = "Uses your plan"
    static let costModelLocal = "Free, on this Mac. Slower."
    static let costModelKey = "Billed per use by your provider"
    static let engineKeySaved = "Key saved"
    static let engineAddKey = "Add a key in \(plansAndKeys)"
    static let welcomeNotChosen = "Not chosen yet. Cicada asks before its first read."
    static let welcomeWillRead = "Will read"
    static let welcomeProviderLine = "Plans and keys send what Cicada reads to that provider."
    static func welcomePickSaved(_ label: String) -> String { "\(label) · saved when you press Start" }
    static func welcomeDemoFailed(_ why: String) -> String { "Couldn't create the demo memory: \(why)" }

    // MARK: Getting started (Tasks 2–3)
    static let gsBringingIn = "Bringing it in…"
    static let gsEngineFailed = "Couldn't save who reads. Choose again below."
```

  (`engineAddKey` interpolates `plansAndKeys` so `testNoViewRetypesAPointerLiteral` stays green.)

- [ ] **Step 8: Verify.** `swift build 2>&1 | tail -5`; `swift test --filter
  "GettingStartedStateTests|WelcomeLogicTests|SetupRunnerTests|FoundTurnOnTests|IntakeRouterTests|EngineOptionTests|LocalInventoryTests|CopyConstantsTests" 2>&1 | tail -20`
  → green; full `swift test 2>&1 | tail -20` → **0 failures**.

- [ ] **Step 9: Commit** —
  `feat(onboarding): what Start does, tested — SetupRunner, the one turn-on, the per-bank checklist, Welcome staging (Track I T8, G117)`.

---

### Task 3 (T9b): Getting started — the continuation on Home

Design §4.2. The card renders `SetupRunner` + `GettingStartedState` + the machine's own state, runs
the first read, and asks the schedule question once. It is dormant until a bank has a record (Task 4
records one; *Show setup checklist* records one on demand).

**Files:**
- Create: `app/…/Support/GettingStartedProgress.swift`, `app/…/Support/LiveSetupEffects.swift`,
  `app/…/Views/Home/GettingStartedCard.swift`, `app/…/Views/Onboarding/EngineChoice.swift`
- Modify: `app/…/Views/Settings/EngineCard.swift:19-114, 251-305`
- Modify: `app/…/Views/Home/HomeView.swift`, `app/…/Views/Home/HomeSections.swift`
- Modify: `app/…/CicadaApp.swift` (`SetupRunner`, shared `LocalInventory`)
- Modify: `app/…/Views/Settings/SettingsGeneralView.swift:105-121`
- Modify: `app/…/ViewModels/SleepViewModel.swift:21, 253, 352` (`scheduleLoaded`, R-IB20)
- Modify: `app/…/Theme/Copy+Welcome.swift` (append)
- Test: new `GettingStartedProgressTests.swift`

**Interfaces:**
- Produces `GettingStartedRow`, `GettingStartedInputs`, `GettingStartedProgress` (`rows`,
  `alsoFound`, `isDone`, `visible`); `FirstReadInputs`, `FirstReadStep` (`of`, `line`, `worm`,
  `action`), `FirstReadAction`; `ScheduleChoice` (`asks`, `config(for:current:)`);
  `LiveSetupEffects`; `GettingStartedCard`; `EngineChoice(pick:)`; `EngineCard(style:pick:)`.
- Consumes Task 2's runner, state, turn-on and `EngineOption` additions; `ScheduleHonesty`,
  `EngineReadiness`, `HonestyInputs.from`, `activeStage`, `sleepVM`, `SleepEngineViewModel`.

- [ ] **Step 1: Failing tests** — `GettingStartedProgressTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// Track I part b (design §4.2, R-IB18–R-IB20) — the card as pure functions.
final class GettingStartedProgressTests: XCTestCase {
    private let en = Locale(identifier: "en_US")

    private func item(_ id: FoundItemID, _ readiness: FoundItem.Readiness, group: FoundGroup = .agents) -> FoundItem {
        FoundItem(id: id, group: group, title: id.key, isPresent: true, content: .ownIntentionalAct,
                  readiness: readiness, opensAnotherApp: false)
    }

    private func inputs(_ enabled: [FoundItemID], items: [FoundItem] = [], runner: [FoundItemID: FoundRowState] = [:],
                        browserOn: Set<String> = [], settled: Set<FoundItemID> = []) -> GettingStartedInputs {
        GettingStartedInputs(record: GettingStartedRecord(enabled: enabled, settled: settled), items: items,
                             runnerRows: runner, browserOn: browserOn, wiringLoaded: true)
    }

    func testAfterARelaunchRowsComeFromTheMachineNotFromMemory() {
        let rows = GettingStartedProgress.rows(inputs(
            [.agent("claude-code"), .agent("codex"), .browser("chrome-bookmarks"), .browser("safari-bookmarks")],
            items: [item(.agent("claude-code"), .alreadyOn), item(.agent("codex"), .ready),
                    item(.browser("chrome-bookmarks"), .ready, group: .browsers),
                    item(.browser("safari-bookmarks"), .needsPermission, group: .browsers)],
            browserOn: ["chrome-bookmarks"]))
        XCTAssertEqual(rows.map(\.state), [.on, .off, .on, .needsAction(Copy.foundAllow)])
    }

    func testARunningRowOutranksWhatTheProbeLastSaid() {
        let rows = GettingStartedProgress.rows(inputs([.agent("codex")], items: [item(.agent("codex"), .alreadyOn)],
                                                      runner: [.agent("codex"): .working(Copy.foundConnecting)]))
        XCTAssertEqual(rows.first?.state, .working(Copy.foundConnecting))
    }

    func testClaudeDesktopFinishesInSettingsAndCursorOnceSettled() {
        let rows = GettingStartedProgress.rows(inputs([.agent("claude-desktop"), .agent("cursor")],
                                                      items: [item(.agent("claude-desktop"), .ready)],
                                                      settled: [.agent("cursor")]))
        XCTAssertEqual(rows[0].state, .needsAction(Copy.foundClaudeDesktopDetail))
        XCTAssertEqual(rows[0].settingsLink, .agents)
        XCTAssertEqual(rows[1].state, .on, "Cursor owns its config; the opened confirm is all Cicada can know")
    }

    func testADismissedRowIsSettledEvenOverAFailureThisSession() {
        let rows = GettingStartedProgress.rows(inputs([.agent("codex")], items: [item(.agent("codex"), .ready)],
                                                      runner: [.agent("codex"): .failed("x")],
                                                      settled: [.agent("codex")]))
        XCTAssertEqual(rows.first?.state, .on, "✕ settles any row (R-IB18)")
    }

    func testADroppedExportThisSessionIsARowAfterTheEnabledOnes() {
        let rows = GettingStartedProgress.rows(inputs([.agent("codex")], items: [item(.agent("codex"), .alreadyOn)],
                                                      runner: [.dropped("d1"): .on]))
        XCTAssertEqual(rows.map(\.id), [.agent("codex"), .dropped("d1")])
    }

    func testAlsoFoundIsWhatIsHereButNotYetOn() {
        let found = GettingStartedProgress.alsoFound(inputs([.agent("codex")],
            items: [item(.agent("codex"), .ready), item(.agent("claude-code"), .alreadyOn),
                    item(.browser("chrome-bookmarks"), .ready, group: .browsers)]))
        XCTAssertEqual(found.map(\.id), [.browser("chrome-bookmarks")])
    }

    func testDoneNeedsEveryRowOnTheFirstReadAndTheScheduleAnswer() {
        let on = [GettingStartedRow(id: .agent("codex"), title: "Codex", detail: "", state: .on)]
        let off = [GettingStartedRow(id: .agent("codex"), title: "Codex", detail: "", state: .off)]
        XCTAssertTrue(GettingStartedProgress.isDone(rows: on, hasRunBefore: true, scheduleAnswered: true))
        XCTAssertFalse(GettingStartedProgress.isDone(rows: off, hasRunBefore: true, scheduleAnswered: true))
        XCTAssertFalse(GettingStartedProgress.isDone(rows: on, hasRunBefore: false, scheduleAnswered: true))
        XCTAssertFalse(GettingStartedProgress.isDone(rows: on, hasRunBefore: true, scheduleAnswered: false))
    }

    func testTheCardShowsOnlyForARecordedUnhiddenBank() {
        XCTAssertFalse(GettingStartedProgress.visible(record: nil))
        XCTAssertTrue(GettingStartedProgress.visible(record: GettingStartedRecord()))
        XCTAssertFalse(GettingStartedProgress.visible(record: GettingStartedRecord(hidden: true)))
    }

    // MARK: The first read (design §4.2's table)

    private func read(_ edit: (inout FirstReadInputs) -> Void) -> FirstReadStep {
        var i = FirstReadInputs()
        edit(&i)
        return FirstReadStep.of(i)
    }

    func testTheFirstReadTable() {
        XCTAssertEqual(read { $0.unprocessed = 0 }, .nothingYet)
        XCTAssertEqual(read { $0.unprocessed = nil }, .nothingYet, "unknown is never a number")
        XCTAssertEqual(read { $0.unprocessed = 61 }, .waiting(61))
        XCTAssertEqual(read { $0.running = true; $0.stage = 0; $0.read = 12; $0.total = 61 },
                       .running(read: 12, total: 61, stage: 1), "R-Z14: the wire counts completed stages")
        XCTAssertEqual(read { $0.hasRunBefore = true; $0.pages = 146; $0.unprocessed = 0 }, .finished(pages: 146))
        XCTAssertEqual(read { $0.hasRunBefore = true; $0.episodesTotal = 50; $0.episodesQueued = 379; $0.unprocessed = 329 },
                       .capped(read: 50, left: 329))
        XCTAssertEqual(read { $0.error = "No engine could run. Add a key." }, .failed("No engine could run."))
    }

    func testEveryStepHasItsTextTwinAndNeverAGuess() {
        XCTAssertEqual(FirstReadStep.running(read: 0, total: 0, stage: 2).line(locale: en), Copy.gsReading,
                       "past Stage 1 there is no per-item count — never 'Read 0 of 0'")
        XCTAssertEqual(FirstReadStep.running(read: 12, total: 1_061, stage: 1).line(locale: en), "Reading · Read 12 of 1,061")
        XCTAssertEqual(FirstReadStep.waiting(61).line(locale: en), "61 waiting to be read.")
        XCTAssertEqual(FirstReadStep.finished(pages: 146).line(locale: en), "Your memory has 146 pages now.")
        XCTAssertEqual(FirstReadStep.finished(pages: nil).line(locale: en), Copy.gsFinishedNoCount)
        XCTAssertEqual(FirstReadStep.capped(read: 50, left: 329).line(locale: en), "Read 50 this round. 329 still waiting.")
    }

    func testTheWormAndTheOneActionFollowTheStep() {
        XCTAssertEqual(FirstReadStep.waiting(3).worm, .reading)
        XCTAssertEqual(FirstReadStep.running(read: 1, total: 3, stage: 2).worm, .sleeping(stage: 2))
        XCTAssertEqual(FirstReadStep.failed("x").worm, .error)
        XCTAssertEqual(FirstReadStep.waiting(3).action, .readNow)
        XCTAssertEqual(FirstReadStep.running(read: 1, total: 3, stage: 1).action, .watchSleep)
        XCTAssertEqual(FirstReadStep.finished(pages: 2).action, .openGraph)
        XCTAssertEqual(FirstReadStep.capped(read: 50, left: 9).action, .readNext(50))
        XCTAssertNil(FirstReadStep.nothingYet.action)
    }

    // MARK: The schedule question (R-IB20)

    func testOnlyAPersonStillOnManualIsAsked() {
        XCTAssertTrue(ScheduleChoice.asks(ScheduleConfig(mode: "manual", hour: 3, minute: 0)))
        for mode in ["daily", "interval", "after_import"] {
            XCTAssertFalse(ScheduleChoice.asks(ScheduleConfig(mode: mode, hour: 3, minute: 0)),
                           "\(mode) was set in Settings — an answer, never downgraded (Track P R4)")
        }
    }

    func testEachAnswerWritesOnlyWhatItSays() {
        let current = ScheduleConfig(mode: "manual", hour: 9, minute: 15, intervalHours: 4)
        let nightly = ScheduleChoice.config(for: .daily, current: current)
        XCTAssertEqual([nightly.mode, "\(nightly.hour):\(nightly.minute)"], ["daily", "3:0"])
        XCTAssertEqual(ScheduleChoice.config(for: .afterImport, current: current).mode, "after_import")
        XCTAssertEqual(ScheduleChoice.config(for: .manual, current: current), current)
    }
}
```

  Red: `swift build` fails.

- [ ] **Step 2: `Support/GettingStartedProgress.swift`.**

```swift
import Foundation

struct GettingStartedRow: Equatable, Identifiable {
    let id: FoundItemID
    let title: String
    let detail: String
    let state: FoundRowState
    var settingsLink: SettingsSection? = nil
}

struct GettingStartedInputs {
    var record: GettingStartedRecord
    var items: [FoundItem] = []
    var runnerRows: [FoundItemID: FoundRowState] = [:]
    var runnerDetail: [FoundItemID: String] = [:]
    var titles: [FoundItemID: String] = [:]
    var browserOn: Set<String> = []
    /// `/agents/wiring` answered at least once — an agent missing from a real
    /// answer is gone, one missing because nothing answered is waiting.
    var wiringLoaded = false
}

/// Track I part b (design §4.2, R-IB18) — the card's rows: this session's
/// runner state first, else what the machine says now (never a remembered
/// "on" that is no longer true).
enum GettingStartedProgress {
    static let fallbackTitles = ["agent:claude-code": "Claude Code", "agent:codex": "Codex", "agent:cursor": "Cursor",
                                 "agent:claude-desktop": "Claude", "browser:chrome-bookmarks": "Chrome",
                                 "browser:safari-bookmarks": "Safari"]

    static func rows(_ i: GettingStartedInputs) -> [GettingStartedRow] {
        let dropped = i.runnerRows.keys.filter { if case .dropped = $0 { return true }; return false }
            .sorted { $0.key < $1.key }
        return (i.record.enabled + dropped).map { id in
            let item = i.items.first { $0.id == id }
            let derived = derivedState(id, item: item, i)
            // R-IB18: ✕ settles a row even over this session's runner state, or a
            // row that failed a minute ago could never let the card finish.
            let runner = i.record.settled.contains(id) ? nil : i.runnerRows[id]
            let state = runner ?? derived.state
            return GettingStartedRow(id: id, title: item?.title ?? i.titles[id] ?? fallbackTitles[id.key] ?? id.key,
                                     detail: i.runnerDetail[id] ?? detail(id, state: state),
                                     state: state, settingsLink: runner == nil ? derived.link : nil)
        }
    }

    static func derivedState(_ id: FoundItemID, item: FoundItem?,
                             _ i: GettingStartedInputs) -> (state: FoundRowState, link: SettingsSection?) {
        if i.record.settled.contains(id) { return (.on, nil) }
        switch id {
        case .agent("claude-desktop"):
            return item?.readiness == .alreadyOn ? (.on, nil) : (.needsAction(Copy.foundClaudeDesktopDetail), .agents)
        case .agent("cursor"):
            return (.off, nil)
        case .agent:
            guard let item else { return i.wiringLoaded ? (.failed(Copy.gsAgentGone), nil) : (.working(Copy.foundBackendDown), nil) }
            switch item.readiness {
            case .alreadyOn: return (.on, nil)
            case .failed(let why): return (.failed(why), nil)
            default: return (.off, nil)
            }
        case .browser(let channel):
            if i.browserOn.contains(channel) { return (.on, nil) }
            return item?.readiness == .needsPermission ? (.needsAction(Copy.foundAllow), nil) : (.off, nil)
        case .dropped:
            return (.on, nil)
        case .app:
            return (.needsAction(Copy.gsFinishInIntegrations), .integrations)
        }
    }

    static func detail(_ id: FoundItemID, state: FoundRowState) -> String {
        switch id {
        case .agent("cursor"): Copy.foundCursorDetail
        case .agent("claude-desktop"): Copy.foundClaudeDesktopDetail
        case .agent: state == .on ? Copy.gsAgentOn : Copy.foundAgentDetail
        case .browser: Copy.foundBrowserDetail
        case .dropped, .app: ""
        }
    }

    /// Present, not turned on, not already on — offered with Turn on (design §4.2 "Also found").
    static func alsoFound(_ i: GettingStartedInputs) -> [FoundItem] {
        let enabled = Set(i.record.enabled)
        return i.items.filter { !enabled.contains($0.id) && $0.readiness != .alreadyOn && !i.record.settled.contains($0.id) }
    }

    static func isDone(rows: [GettingStartedRow], hasRunBefore: Bool, scheduleAnswered: Bool) -> Bool {
        rows.allSatisfy { $0.state == .on } && hasRunBefore && scheduleAnswered
    }

    static func visible(record: GettingStartedRecord?) -> Bool {
        guard let record else { return false }
        return !record.hidden
    }
}

struct FirstReadInputs: Equatable {
    var running = false
    var stage = 0
    var error: String? = nil
    var unprocessed: Int? = nil
    var read = 0
    var total = 0
    var episodesTotal = 0
    var episodesQueued = 0
    var hasRunBefore = false
    var pages: Int? = nil
}

enum FirstReadAction: Equatable { case readNow, watchSleep, openGraph, readNext(Int), tryAgain }

/// Track I part b (design §4.2 "the first read: the payoff", R-IB19) — one total
/// function over the status: each state has one line (the text twin), one worm
/// and at most one action. Never a duration (G107); a meter only with its noun.
enum FirstReadStep: Equatable {
    case nothingYet
    case waiting(Int)
    case running(read: Int, total: Int, stage: Int)
    case finished(pages: Int?)
    case capped(read: Int, left: Int)
    case failed(String)

    static func of(_ i: FirstReadInputs) -> FirstReadStep {
        if i.running { return .running(read: i.read, total: i.total, stage: activeStage(completed: i.stage)) }
        if let e = i.error?.trimmingCharacters(in: .whitespacesAndNewlines), !e.isEmpty { return .failed(firstSentence(e)) }
        if i.hasRunBefore {
            if i.episodesQueued > i.episodesTotal, let left = i.unprocessed, left > 0 {
                return .capped(read: i.episodesTotal, left: left)
            }
            return .finished(pages: i.pages)
        }
        guard let n = i.unprocessed, n > 0 else { return .nothingYet }
        return .waiting(n)
    }

    static func firstSentence(_ s: String) -> String {
        guard let r = s.range(of: ". ") else { return s }
        return String(s[..<r.lowerBound]) + "."
    }

    var worm: BookwormState {
        switch self {
        case .nothingYet: .awake
        case .waiting: .reading
        case .running(_, _, let stage): .sleeping(stage: stage)
        case .finished, .capped: .happy
        case .failed: .error
        }
    }

    var action: FirstReadAction? {
        switch self {
        case .nothingYet: nil
        case .waiting: .readNow
        case .running: .watchSleep
        case .finished: .openGraph
        case .capped(let read, _): .readNext(read)
        case .failed: .tryAgain
        }
    }

    func line(locale: Locale = .autoupdatingCurrent) -> String {
        switch self {
        case .nothingYet: Copy.gsNothingYet
        case .waiting(let n): Copy.gsWaiting(n, locale: locale)
        case .running(let read, let total, _): total > 0 ? Copy.gsRunning(read: read, total: total, locale: locale) : Copy.gsReading
        case .finished(let pages): pages.map { Copy.gsFinished(pages: $0, locale: locale) } ?? Copy.gsFinishedNoCount
        case .capped(let read, let left): Copy.gsCapped(read: read, left: left, locale: locale)
        case .failed(let why): why
        }
    }
}

/// R-IB20 — the schedule question, asked only of a person still on `manual`;
/// every answer writes exactly what it says, keeping everything else.
enum ScheduleChoice {
    static func asks(_ schedule: ScheduleConfig) -> Bool { schedule.mode == ScheduleMode.manual.rawValue }

    static func config(for mode: ScheduleMode, current: ScheduleConfig) -> ScheduleConfig {
        var next = current
        next.mode = mode.rawValue
        if mode == .daily { next.hour = 3; next.minute = 0 }
        return next
    }
}
```

  (`ScheduleConfig` has `var` fields and is `Equatable` — `Services/APIClient.swift:822-834`.)

  Then `ViewModels/SleepViewModel.swift` (R-IB20): beside `schedule` (`:21`) add

```swift
    /// R-IB20 — `schedule` starts as a placeholder `manual`; this turns true
    /// only once the real one arrived (`load()`) or was written
    /// (`updateSchedule`). Getting started's schedule question waits for it:
    /// asked on the placeholder, an answer would overwrite a real `interval`.
    private(set) var scheduleLoaded = false
```

  and set it to `true` next to the two assignments that make `schedule` real: `:253`
  (`if token == loadToken { schedule = sc; scheduleLoaded = true }`) and `:352` (after
  `schedule = try await putSchedule(new)`). Nothing else in the file changes.

- [ ] **Step 3: Copy** — append to `Copy+Welcome.swift` (labels into `welcomeHomeLabels`, the two long
  sentences into `welcomeHomeSentences`):

```swift
    static let gsTitle = "Getting started"
    static let gsHide = "Hide"
    static let gsDone = "You're set up."
    static let gsAgentOn = "New sessions are remembered"
    static let gsAgentGone = "Not found on this Mac any more"
    /// A pointer names its destination exactly as Settings spells it (G68 §2.8).
    static let gsFinishInIntegrations = "Finish in \(settings) → \(integrations)"
    static let gsChatHistory = "Your chat history"
    static let gsChatDrop = "Drop an export here, or choose a file"
    static let gsReading = "Reading what came in"
    static let gsNothingYet = "Nothing to read yet. Drop an export, or chat with a connected app."
    static let gsFinishedNoCount = "Your first read is done."
    static let gsLeaveWhileReading = "You can leave this page. The bookworm keeps reading."
    static let gsWatchOnSleep = "Watch on the Sleep page"
    static let gsOpenGraph = "Open the graph"
    static let gsTryAgain = "Try again"
    static let gsScheduleQuestion = "Keep reading on its own?"
    static let gsWhenIAsk = "When I ask"
    static let gsAfterImports = "After imports"
    static let gsNightly = "Every night at 3:00"
    static let gsNotNow = "Not now"
    static let gsAlsoFound = "Also found"
    static let gsDismiss = "Dismiss"
    static let gsShowChecklist = "Show setup checklist"
    static func gsWaiting(_ n: Int, locale: Locale = .autoupdatingCurrent) -> String {
        "\(UsageFormat.count(n, locale: locale)) waiting to be read."
    }
    static func gsRunning(read: Int, total: Int, locale: Locale = .autoupdatingCurrent) -> String {
        "Reading · Read \(UsageFormat.count(read, locale: locale)) of \(UsageFormat.count(total, locale: locale))"
    }
    static func gsFinished(pages: Int, locale: Locale = .autoupdatingCurrent) -> String {
        "Your memory has \(UsageFormat.count(pages, locale: locale)) pages now."
    }
    static func gsCapped(read: Int, left: Int, locale: Locale = .autoupdatingCurrent) -> String {
        "Read \(UsageFormat.count(read, locale: locale)) this round. \(UsageFormat.count(left, locale: locale)) still waiting."
    }
    static func gsReadNext(_ n: Int, locale: Locale = .autoupdatingCurrent) -> String { "Read the next \(UsageFormat.count(n, locale: locale))" }
```

  (`gsNothingYet` and `gsLeaveWhileReading` go into `welcomeHomeSentences`.)

- [ ] **Step 4: `EngineCard(style:pick:)` and the seam.** In `EngineCard.swift` add
  `enum Style { case full, compact }`, `var style: Style = .full`, `var pick: Binding<String?>? = nil`;
  `hasKey` is `EngineReadiness.hasKey(store.connections.value ?? [])` through the `store` the card
  already reads. `.full` renders exactly as today. `.compact`:
  - no "ENGINE" label and no `.glassCard()` (it sits inside a host card), no `.padding`;
  - the grid over `EngineOption.compactCandidates(response.candidates)`; each `EngineOptionCard` gets
    `costModel: EngineOption.costModel(for: candidate.id)` and
    `caption: EngineOption.compactCaption(for: candidate, hasKey: EngineReadiness.hasKey(store.connections.value ?? []))`,
    drawn as label / cost model (`textSecondary`) / caption (`textTertiary`); `isSelected` is
    `candidate.id == EngineOption.ringed(pick: pick?.wrappedValue, readiness: readiness)` where
    `readiness = EngineReadiness.resolve(candidates:connections:preview:)`; the selected card shows
    `Copy.welcomeWillRead` under its caption and `.accessibilityAddTraits(.isSelected)` (W8); the
    grid is `.accessibilityElement(children: .contain)` labelled "Sleep engine";
  - `select`: when `pick` is non-nil and the candidate is selectable, `pick?.wrappedValue = candidate.id`
    and nothing is written (R-IB13) — the existing `candidate.id != selectedMode` early return is
    skipped in this branch, because a click on the already-saved engine is still a pick the ring must
    show; when nil, today's `select` (its guard, then `commit`);
  - under the grid: the existing `signInHint` + Plans & keys link, then
    `EngineChoiceLine.text(pickLabel: pick?.wrappedValue.flatMap { id in response.candidates.first { $0.id == id }?.label }, readiness:, inputs: HonestyInputs.from(schedule: sleepVM.schedule, response: response, connections: store.connections.value ?? []))`
    and `Copy.welcomeProviderLine`, both `captionFont` / `textTertiary`;
  - no model field, overage toggle or preview section.
  `EngineOptionCard` gains `var costModel: String? = nil`, `var caption: String? = nil`,
  `var showsWillRead = false` — declared **before** `let onSelect`, so `.full`'s existing trailing
  closure call is untouched — (defaults keep `.full` byte-for-byte: `caption ?? EngineOption.caption(for:)`
  in the text and the accessibility label), and its hover stays the fill it has. `.compact` needs `@Environment(SleepViewModel.self)` for the schedule; `.full` does not read it.

  `Views/Onboarding/EngineChoice.swift`:

```swift
import SwiftUI

/// R-IB13 — "who reads what you save" on every onboarding surface goes through
/// this one view. Track O's `EngineChooser(style: .compact)` replaces the body
/// and nothing else changes. With `pick` (the Welcome) a click only rings the
/// card and Start writes it (§4.1.7 step 2, only if the person clicked); without
/// it (Getting started) a click commits, as Settings → Sleep does.
struct EngineChoice: View {
    var pick: Binding<String?>? = nil

    var body: some View {
        EngineCard(style: .compact, pick: pick)
    }
}
```

- [ ] **Step 5: `Support/LiveSetupEffects.swift`.**

```swift
import Foundation

enum SetupError: LocalizedError {
    case engine(String)
    var errorDescription: String? { if case .engine(let why) = self { return why }; return nil }
}

/// The real `SetupEffects` (R-IB14). The owner PUT carries the loaded handle and
/// email back, because `PUT /settings/owner` writes what it is given and clears
/// what is omitted (`api/routers/settings.py:31-59`). `markOnboarded` and every
/// per-bank write read `store.bank` at execution — the LIVE bank, the lesson
/// `FirstRunSheet.finish` carried (a demo switch happens mid-plan).
@MainActor
struct LiveSetupEffects: SetupEffects {
    let store: Store
    let engineVM: SleepEngineViewModel
    let deps: FoundTurnOnDeps
    var owner: OwnerSettings? = nil
    /// `@MainActor` so a main-actor method reference (`runner.checklistChanged`)
    /// converts without losing its isolation.
    var onShowHome: @MainActor () -> Void = {}
    var onClose: @MainActor () -> Void = {}
    /// `SetupRunner.checklistChanged` — every record write re-renders Home.
    var onChecklistChanged: @MainActor () -> Void = {}

    /// The route writes what it is given and CLEARS what is omitted, so a Welcome
    /// whose own GET failed re-reads handle and email here rather than wipe them;
    /// if that read fails too, the backend is down and the PUT fails with it.
    func saveOwner(_ name: String) async throws {
        let current = owner ?? (try? await APIClient.shared.fetchOwnerSettings())
        _ = try await APIClient.shared.updateOwnerSettings(name: name, handle: current?.handle, email: current?.email)
    }

    func saveEngine(_ candidateId: String) async throws {
        let model = engineVM.response?.candidates.first { $0.id == candidateId }?.models.first
        engineVM.errorMessage = nil
        await engineVM.set(mode: candidateId, model: model, disambiguationModel: nil)
        if let why = engineVM.errorMessage { throw SetupError.engine(why) }
        await store.refresh([.connections])
    }

    func markOnboarded() { OnboardingState.markOnboarded(bank: store.bank) }

    func recordGettingStarted(_ ids: [FoundItemID]) {
        GettingStartedState.record(bank: store.bank, enabled: ids)
        onChecklistChanged()
    }

    func showHome() { onShowHome() }
    func close() { onClose() }

    func createDemoBank() async throws {
        _ = try await APIClient.shared.createDemoBank()
        await store.refresh([.banks])
    }

    func turnOn(_ id: FoundItemID) async -> FoundTurnOnResult { await FoundTurnOn.run(id, deps: deps) }

    func settle(_ id: FoundItemID) {
        GettingStartedState.settle(id, bank: store.bank)
        onChecklistChanged()
    }
}
```

- [ ] **Step 6: The card.** `Views/Home/GettingStartedCard.swift` — reads `Store`, `SetupRunner`,
  `LocalInventory`, `BrowserWatcher`, `IntakeRouter`, `SleepViewModel`, `SleepEngineViewModel`,
  `GraphViewModel`, `AccessibilityReduceMotion`; `@Binding var selectedTab: AppTab`. The record is read
  in `body` — `let _ = runner.checklistRevision; let record = GettingStartedState.load(bank: store.bank)`
  (four defaults keys; the revision is what makes a write re-render) — and every write the card makes
  (`setHidden`, `setScheduleAsked`, `settle`, `record`) is followed by `runner.checklistChanged()`.
  The card renders nothing unless `GettingStartedProgress.visible(record:) || runner.sawDoneThisSession`.
  Three values every section below reads, computed once in `body`:
  `readiness = EngineReadiness.resolve(candidates: engineVM.response?.candidates ?? [], connections:
  store.connections.value ?? [], preview: engineVM.response?.preview)`;
  `honesty = HonestyInputs.from(schedule: sleepVM.schedule, response: engineVM.response, connections:
  store.connections.value ?? [])`; and `hasRunBefore` as in Task 1.
  On a `surface` card (`radiusLarge`, `spacingLG` padding), top to bottom:
  1. Header: `Text(Copy.gsTitle)` (`headingFont`, `.accessibilityAddTraits(.isHeader)`; an
     `@AccessibilityFocusState` on it is set once when the card first appears while
     `runner.phase == .started` — W14's "focus moves to the Getting started heading") and a
     `Copy.gsHide` button → `GettingStartedState.setHidden(true, bank:)`, `runner.sawDoneThisSession
     = false` (Hide also ends the session's "You're set up.") and `runner.checklistChanged()`.
  2. Rows: `GettingStartedProgress.rows(inputs)` with `inputs = GettingStartedInputs(record:, items:
     inventory.items, runnerRows: runner.rows, runnerDetail: runner.detail, titles: runner.titles,
     browserOn: Set(BrowserWatchPolicy.watched.map(\.channel).filter(watcher.isEnabled)), wiringLoaded: inventory.wiring != nil)`.
     Each is an `HStack` of the same `FoundRow` the strip uses —
     `FoundRow(mark: mark(row.id), title: row.title, detail: row.detail, state: row.state,
     action: { Task { await runner.turnOn(row.id, effects: effects) } }, settingsLink: row.settingsLink)`
     (arguments in `FoundRow`'s declaration order: `action` before `settingsLink`) — and, after it, a
     small `xmark` button labelled `Copy.gsDismiss` → `effects.settle(row.id)` (which bumps
     `runner.checklistChanged()`), or `runner.forget(row.id)` for a `.dropped` row (a drop is never
     recorded, R-IB17); `FoundRow` itself has no trailing slot. `mark(_:)` is
     `OnThisMacStrip.mark(id)` except for a `.dropped` row, whose mark is the export's real one:
     `.logo(OriginIconography.logoName(for: runner.origins[id] ?? "") ?? "")` (an unknown origin
     falls to the SF fallback). Refused lines render under the row exactly as `OnThisMacStrip`
     renders them (`Copy.foundRefused` + the lines, no copy button).
     `runner.engineError`, when set, shows once under the rows in `CicadaTheme.danger`.
  3. The chat-history row, only while no `.dropped` row exists — a plain row, not a `FoundRow` (it is
     an invitation, not a connection with a state): the three `VendorMark(vendor:size:)`s,
     `Copy.gsChatHistory`, `Copy.gsChatDrop`, and a `Copy.intakeChooseFile` button →
     `intake.present(from: .onboardingRow)` (the one intake's overlay). Task 5 adds the waits.
  4. *Who reads* — only when `readiness == .needsChoice`: `EngineChoice()` (commits on click).
  5. A divider, then the first read, while `!GettingStartedProgress.isDone(...)`:
     `step = FirstReadStep.of(FirstReadInputs(running: sleepVM.isRunning || store.status.value?.sleep.status == "running",
     stage: sleepVM.status?.stage ?? 0, error: sleepVM.status?.error, unprocessed: store.status.value?.episodes.unprocessed
     ?? sleepVM.status?.debt.unprocessedCount, read: (sleepVM.status?.readByOrigin ?? [:]).values.reduce(0, +),
     total: (sleepVM.status?.queueByOrigin ?? [:]).values.reduce(0, +), episodesTotal: sleepVM.status?.episodesTotal ?? 0,
     episodesQueued: sleepVM.status?.episodesQueued ?? 0, hasRunBefore: hasRunBefore,
     pages: store.graph.value.map { $0.nodes.filter { !$0.isHub && !$0.isFacet }.count }))`;
     row = `BookwormView(state: step.worm, pointSize: 24)` + `Text(step.line())` + the action:
     `.readNow` → a `MeadowPill(title: Copy.intakeReadNow)` **disabled with `Copy.intakeChooseWhoReads`
     beside it while `readiness == .needsChoice`**, subtitled `Copy.engineLabel(preview.manual.engine)`
     when `engineVM.response?.preview` exists; its action is the card's one private helper
     `read() { Task { await sleepVM.triggerManually(); await store.refresh([.status, .channels]) } }`
     (R-IB19 — G125 R10's second narrow amendment; the one trigger on Home, and only inside this
     card); `.readNext(n)` → `read()`, labelled `Copy.gsReadNext(n)`; `.tryAgain` → `read()`,
     `Copy.gsTryAgain`, plus an `EngineChoice()` disclosure. All three go through `read()`, so the
     Step 8 grep finds exactly one `triggerManually` line. `.watchSleep` → `selectedTab = .sleep`
     (`Copy.gsWatchOnSleep`) and `Copy.gsLeaveWhileReading` under it; `.openGraph` →
     `selectedTab = .graph` (`Copy.gsOpenGraph`).
  6. The schedule question, when `hasRunBefore && sleepVM.scheduleLoaded && !record.scheduleAsked &&
     ScheduleChoice.asks(sleepVM.schedule)` (R-IB20 — never on the placeholder schedule):
     `Text(Copy.gsScheduleQuestion)`; three buttons styled as a radio group (`.accessibilityAddTraits(.isSelected)`
     on the current mode) for `.manual` / `.afterImport` / `.daily` with `Copy.gsWhenIAsk` /
     `gsAfterImports` / `gsNightly`, each `.disabled(!ScheduleHonesty.enabledModes(honesty).contains(mode))`;
     choosing one → `Task { if await sleepVM.updateSchedule(ScheduleChoice.config(for: mode, current: sleepVM.schedule)) { GettingStartedState.setScheduleAsked(bank: store.bank); runner.checklistChanged() } }`;
     `Text(ScheduleHonesty.engineLine(honesty))`; a `Copy.gsNotNow` button → `setScheduleAsked` +
     `runner.checklistChanged()`.
     `scheduleAnswered = record.scheduleAsked || (sleepVM.scheduleLoaded && !ScheduleChoice.asks(sleepVM.schedule))`.
  7. *Also found*: when `GettingStartedProgress.alsoFound(inputs)` is non-empty, `Copy.gsAlsoFound`
     and one `FoundRow` each (state `.off`, or `.needsAction(Copy.foundAllow)` when blocked) whose action
     is `effects.recordGettingStarted([item.id]); Task { await runner.turnOn(item.id, effects: effects) }`.
  8. Done: when `GettingStartedProgress.isDone(...)` or `runner.sawDoneThisSession`, the card body is
     only `Text(Copy.gsDone)` + Hide. The first time it is done — `.onChange(of: isDone, initial: true)`,
     never inside `body` — set `runner.sawDoneThisSession = true`, `GettingStartedState.setHidden(true,
     bank: store.bank)` and `runner.checklistChanged()`: "You're set up." stays for this session and the
     card is gone next launch (R-IB18). *Read now* here is a `MeadowPill` because the intake done
     card's *Read now* already is one (R-IA16): the same action wears the same pill (R-IB19).
  `effects` = `LiveSetupEffects(store:, engineVM:, deps: .live(inventory:, watcher:, intake:),
  onChecklistChanged: runner.checklistChanged)`.
  `.task { if engineVM.response == nil { await engineVM.load() }; await inventory.refresh() }` and
  `.onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in Task { await inventory.refresh() } }`
  (a Full Disk Access grant lands; W5; the file imports `AppKit` for `NSApplication`, as
  `OnThisMacStrip` does). Every appearance/disappearance of a section animates with
  `CicadaMotion.settle(reduceMotion:)`.

- [ ] **Step 7: Mount it.** `CicadaApp.swift`: `@State private var setupRunner = SetupRunner()` and
  `@State private var inventory: LocalInventory` (`_inventory = State(initialValue: LocalInventory(probes: LocalInventory.live(watcher: lights)))`
  in `init()`), both `.environment(...)` on the main window (the `+` strip keeps its own instance —
  it builds one per appearance in its `.task`, `OnThisMacStrip.swift:32-36`). `HomeView`: gains
  `@Environment(SetupRunner.self) private var runner`; its `gettingStartedVisible` parameter goes;
  instead `body` reads `let _ = runner.checklistRevision` and computes
  `gettingStartedVisible = GettingStartedProgress.visible(record: GettingStartedState.load(bank: store.bank)) || runner.sawDoneThisSession`;
  `GettingStartedCard(selectedTab: $selectedTab)` sits between the field and TODAY (only while the
  cards show, R-IB6), and TODAY receives the flag (the waiting clause — each number once). Its
  `.task` becomes `if sleepVM.status == nil || !sleepVM.scheduleLoaded { await sleepVM.load() } else
  { await sleepVM.loadHistory() }` — a load whose schedule fetch failed is retried here, or the
  schedule question would never be asked (R-IB20).
  `SettingsGeneralView.onboardingCard`: add a `Copy.gsShowChecklist` button under *Run setup again* —
  `GettingStartedState.record(bank: store.bank, enabled: []); runner.checklistChanged(); router.pendingTab = .home; router.activateMainWindow()`
  (so the Settings scene also gets `.environment(setupRunner)`) — with a one-line docstring (R-IB17:
  re-openable, the design's "Show setup checklist" row until Track O moves it into Settings v3).

- [ ] **Step 8: Verify.** `swift build`; `swift test --filter "GettingStartedProgressTests|EngineCardTests|EngineOptionTests|CopyConstantsTests|MotionLiteralLintTests|FixWaveTests|SleepViewModelTests" 2>&1 | tail -20`;
  full `swift test` → **0 failures**. `rg -n "triggerManually" app/CicadaApp/Sources/CicadaApp/Views/Home`
  → exactly one line, in `GettingStartedCard.swift` (Home's steady state has no trigger, R-IB9).

- [ ] **Step 9: Commit** —
  `feat(home): Getting started — live rows, the first read, and the schedule asked honestly (Track I T9b, G117, G125 R10 amendment 2)`.

---

### Task 4 (T8): The Welcome — one screen, the ticks are the consent

Design §4.1. Swaps the sheet for the full-window Welcome, retires the four-step sheet and F2, and
lands Start on Home's Getting started.

**Files:**
- Create: `app/…/Views/Onboarding/WelcomeView.swift`, `app/…/Views/Onboarding/WelcomeChecklist.swift`,
  `app/…/Views/Meadow/WelcomeHero.swift`
- Modify: `app/…/Views/Common/FoundRow.swift:21-101`
- Modify: `app/…/ContentView.swift:12-22, 87-93, 109-112, 143-145, 171-175, 186-206`
- Modify: `app/…/Views/Settings/IntegrationsView.swift:13-18, 196-199`
- Modify: `app/…/Theme/Copy.swift:424-457` (delete the onboarding members), `Theme/Copy+Welcome.swift` (append)
- Delete: `app/…/Views/Onboarding/FirstRunSheet.swift`, `OwnerIdentityStep.swift`, `OnboardingSleepStep.swift`
- Delete: `app/CicadaApp/Tests/CicadaAppTests/OnboardingStepTests.swift`, `OnboardingScheduleTests.swift`
- Modify tests: `SettingsSectionTests.swift:64-82`, `CopyConstantsTests.swift:75-83`, `FoundRowTests.swift`,
  `CountLiteralLintTests.swift:28-33` (scope), `FixWaveTests.swift:48` (comment), `AppRouterTests.swift:38-43` (comment)
- Create test: `app/CicadaApp/Tests/CicadaAppTests/NoRedLiteralLintTests.swift` (design §13)

**Interfaces:**
- Produces `WelcomeView(mode:dropTargeted:onShowHome:onClose:)`, `WelcomeHero`,
  `FoundRow(tick:)` + `FoundRow.tickLabel(title:detail:ticked:)`, `FoundTickStyle`.
- Consumes everything in Tasks 2–3, `FoundPolicy.startSummary`, `OnboardingFlow.plan/canStart`,
  `MeadowPill`, `BookwormView`, `EngineChoice(pick:)`, `IntakeRouter.welcome*`, `VendorMark`.

- [ ] **Step 1: Failing tests.** `FoundRowTests.swift` — add:

```swift
    /// W4 — a ticked row reads its tick, not its machine state: the tick is the consent.
    func testATickReadsAsOnOrOff() {
        XCTAssertEqual(FoundRow.tickLabel(title: "Chrome", detail: Copy.foundBrowserDetail, ticked: true),
                       "Chrome. \(Copy.foundBrowserDetail). On.")
        XCTAssertEqual(FoundRow.tickLabel(title: "Codex", detail: Copy.foundAgentDetail, ticked: false),
                       "Codex. \(Copy.foundAgentDetail). Off.")
    }
```

  `CopyConstantsTests.swift` — **delete** `testTheOnboardingToggleLabelNamesTheScheduleItWrites`
  (`:75-83`; `ScheduleToggleTests.test_toggled_writesOnlyManualOrDailyAtThree_andNeverDowngrades`
  already pins the 3:00 write) and add:

```swift
    /// R-IB21 — the retired sheet's copy is gone with it; the Welcome says Start's
    /// consequence in words a new person reads (design §4.1.2).
    func testTheWelcomeNamesItsOneActionAndItsSecondaryExits() {
        XCTAssertEqual(Copy.welcomeStart, "Start remembering")
        XCTAssertTrue(Copy.welcomeHomeLabels.contains(Copy.welcomeSetUpLater))
        XCTAssertTrue(Copy.welcomeHomeLabels.contains(Copy.welcomeTryDemo))
        XCTAssertFalse(Copy.welcomeSubline.lowercased().contains("episode"))
    }
```

  `SettingsSectionTests.swift:64-82` — drop the three `FirstRunSheet` assertions (`:74`, `:80`, `:81`)
  and rewrite the doc comment for `SettingsScene` alone (drop "and `FirstRunSheet`" and the sentence
  about "the sheet's footer"; the Welcome has no fixed frame — `WelcomeLogicTests` pins its geometry
  and its pinned footer). `CountLiteralLintTests.scope` gains `"/Views/Onboarding/"` (the Welcome's
  start line and rows carry counts).

  `NoRedLiteralLintTests.swift` (new — design §13; it is green only once Step 8 deletes the last
  three literals, so it is part of this task's red):

```swift
import XCTest
@testable import CicadaApp

/// Track I part b (design §13, R-IB21) — an error is `CicadaTheme.danger`, a theme
/// token with a light and a dark value; `.red` is one system red in both themes.
/// The three that existed left with the retired first-run sheet; this keeps the
/// next one out. Same walker and comment rule as `MeadowPlacementLintTests`.
final class NoRedLiteralLintTests: XCTestCase {
    static let needles = [".foregroundStyle(.red)", ".foregroundColor(.red)", "Color.red"]

    func testNoViewPaintsTheSystemRed() throws {
        let views = try ThemeTokenTests.swiftSources().filter { $0.path.contains("/Views/") }
        XCTAssertFalse(views.isEmpty, "found no Views sources — the lint would pass vacuously")
        var offenders: [String] = []
        for file in views {
            let text = try String(contentsOf: file, encoding: .utf8)
            for (index, line) in text.components(separatedBy: .newlines).enumerated() {
                let code = line.trimmingCharacters(in: .whitespaces)
                guard !code.hasPrefix("//") else { continue }
                if Self.needles.contains(where: { code.contains($0) }) {
                    offenders.append("\(file.lastPathComponent):\(index + 1)")
                }
            }
        }
        XCTAssertEqual(offenders, [], "use CicadaTheme.danger (design §13)")
    }
}
```

  Red: `swift build` fails (`tickLabel`, `welcomeStart` … missing).

- [ ] **Step 2: `FoundRow` gains a tick.** Add `var tick: Binding<Bool>? = nil` (last parameter).
  When present: a leading `if let tick { Toggle(isOn: tick) { EmptyView() }.toggleStyle(FoundTickStyle()).labelsHidden() }`;
  the whole row's `accessibilityLabel` becomes `Self.tickLabel(title:detail:ticked:)`; the trailing
  button is shown only for `.needsAction` (Allow…) and `.failed` (Retry) — an `.off` row's consent is
  its tick, and nothing runs before Start. `.on` rows (already on) never show a tick (rerun: "On",
  disabled). Add:

```swift
    static func tickLabel(title: String, detail: String, ticked: Bool) -> String {
        "\(title). \(detail). \(ticked ? Copy.foundOn : Copy.foundOff)."
    }
```

  and, in the same file:

```swift
/// W4 — the tick: `checkmark.circle.fill` in the accent (a UI state, never a
/// nature token — R-M2 keeps meadow for washes and the one pill), a bounce on
/// change that Reduce Motion removes.
struct FoundTickStyle: ToggleStyle {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    func makeBody(configuration: Configuration) -> some View {
        Button { configuration.isOn.toggle() } label: {
            Image(systemName: configuration.isOn ? "checkmark.circle.fill" : "circle")
                .font(CicadaTheme.font(size: 16))
                .foregroundStyle(configuration.isOn ? CicadaTheme.accent : CicadaTheme.textTertiary)
                .symbolEffect(.bounce, value: configuration.isOn)
                .symbolEffectsRemoved(reduceMotion)
        }
        .buttonStyle(.cicadaPlain)
    }
}
```

- [ ] **Step 3: The hero.** `Views/Meadow/WelcomeHero.swift`:

```swift
import SwiftUI

/// The Welcome's band (R-IB11): the bundled onboarding hero, `-dark` in dark
/// mode (`ArtImage` picks it), filling the band and anchored at the bottom so
/// the meadow shows. No words: the headline lives on the card that rises into
/// the grass, so no text ever sits on paint. No drifting sprite — the hero's
/// clouds are painted, and a moving one over them would double them.
struct WelcomeHero: View {
    var body: some View {
        GeometryReader { geo in
            if let image = MeadowArt.image(for: .heroDay, mode: CicadaTheme.mode) {
                Image(nsImage: image)
                    .resizable()
                    .interpolation(.high)
                    .scaledToFill()
                    .frame(width: geo.size.width, height: geo.size.height, alignment: .bottom)
                    .clipped()
            } else {
                MeadowSky()
            }
        }
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }
}
```

- [ ] **Step 4: Copy** — append to `Copy+Welcome.swift` (labels to `welcomeHomeLabels`, `welcomeSubline`
  to `welcomeHomeSentences`):

```swift
    // MARK: The Welcome (Task 4, design §4.1)
    static let welcomeHelloNoName = "Hello."
    static let welcomeFound = "Here's what Cicada found on this Mac."
    static let welcomeSubline = "One memory for every AI you use. It lives on this Mac, in plain files you own."
    static let welcomeYourName = "Your name"
    static let welcomeAddName = "Add your name to start"
    static let welcomeYourAIApps = "Your AI apps"
    static let welcomeYourBrowsers = "Your browsers"
    static let welcomeYourChatHistory = "Your chat history"
    static let welcomeWhoReads = "Who reads what you save"
    static let welcomeNothingFound = "Nothing to bring over automatically. That's fine."
    static let welcomeDropExport = "Drop a Claude, ChatGPT or Gemini export here"
    static let welcomeStart = "Start remembering"
    static let welcomeSaveChanges = "Save changes"
    static let welcomeStarting = "Starting…"
    static let welcomeTryDemo = "Try the demo instead"
    static let welcomeSetUpLater = "Set up later"
    static let welcomeSetUpLaterNeedsName = "Set up later (add your name first)"
    static let welcomeClose = "Close"
    static let welcomeAllowed = "Allowed. Safari bookmarks will come along."
    static func welcomeHello(_ first: String) -> String { "Hello, \(first)." }
    static func welcomeNotYou(_ first: String) -> String { "Not \(first)? Change" }
    static func welcomeSettingUp(_ n: Int, locale: Locale = .autoupdatingCurrent) -> String {
        n == 1 ? "Cicada is setting up 1 thing." : "Cicada is setting up \(UsageFormat.count(n, locale: locale)) things."
    }
```

- [ ] **Step 5: `WelcomeView`.** `struct WelcomeView: View { let mode: OnboardingMode; let dropTargeted:
  Bool; let onShowHome: () -> Void; let onClose: () -> Void }` (mode is `.firstRun` or `.rerun`;
  `.setUpLater` is only ever a plan mode). Environment: `Store`, `SetupRunner`, `LocalInventory`,
  `BrowserWatcher`, `IntakeRouter`, `SleepEngineViewModel`, `SleepViewModel`, reduce motion.
  State: `name`, `owner: OwnerSettings?`, `editingName`, `@FocusState nameFocused`, `ticked`,
  `touched`, `allowRequested`, `droppedTicked: Set<String>`, `pick: String?`, `starting`,
  `ownerError: String?`, `revealed`.
  - **Layout** (R-IB11, `WelcomeLayout`): `GeometryReader` → `ZStack(alignment: .top)` of
    `CicadaTheme.background.ignoresSafeArea()`, `WelcomeHero().frame(height: band)`, and a `VStack(spacing: 0)`
    of `Color.clear.frame(height: cardTop)`, a `ScrollView { card }` `.frame(width: cardWidth)` (the card
    scrolls inside itself, `.scrollBounceBehavior(.basedOnSize)`), and the **footer outside the scroll
    view** at `.frame(height: CicadaTheme.scaled(WelcomeLayout.footerHeight))`. `scale = CicadaTheme.uiScale`.
  - **The card** (`CicadaTheme.surface` in a `RoundedRectangle(cornerRadius: CicadaTheme.radiusLarge)`,
    `spacingXL` padding, the same soft shadow shape the toast uses at `ContentView.swift:309`), top to
    bottom:
    1. The headline block: `Text(firstWord.isEmpty ? Copy.welcomeHelloNoName : Copy.welcomeHello(firstWord)).font(CicadaTheme.displayFont(size: 40))`
       (`.accessibilityAddTraits(.isHeader)`, focus lands here on appear — W1) or, while `editingName`,
       a `TextField(Copy.welcomeYourName, text: $name)` in `CicadaTheme.font(size: 22)`, `.focused($nameFocused)`,
       `.onSubmit { if OnboardingFlow.canStart(name: name) { editingName = false } }`, labelled
       `Copy.welcomeYourName`; then `Text(Copy.welcomeFound).font(CicadaTheme.displayFont(size: 28, italic: true))`;
       `Text(Copy.welcomeSubline)` (`bodyFont`, `textSecondary`); and, when a first word exists and not
       editing, a `Copy.welcomeNotYou(firstWord)` link-style button → `editingName = true; nameFocused = true`
       (W7). `ownerError`, when set, directly under in `captionFont` / `CicadaTheme.danger` (W15).
    2. `WelcomeChecklist` (Step 6).
  - **The footer** (on `background`, centred): `HStack { BookwormView(state: store.intakeInFlight ? .reading : .awake, pointSize: 48); VStack { … } }`
    — the worm on plain ground, never on the grass (R9 §5.3):
    `MeadowPill(title: starting ? Copy.welcomeStarting : (mode == .rerun ? Copy.welcomeSaveChanges : Copy.welcomeStart), isBusy: starting, action: start)`
    `.keyboardShortcut(.defaultAction)` `.disabled(!OnboardingFlow.canStart(name: name))`; under it
    `Text(OnboardingFlow.canStart(name: name) ? FoundPolicy.startSummary(tickedItems) : Copy.welcomeAddName)`
    (`captionFont`, `textSecondary` — Start's text twin), where `tickedItems` is
    `FoundPolicy.order(inventory.items).filter { ticked.contains($0.id) }` followed by the ticked
    staged drops' `FoundItem`s (Step 6) — exactly the set Start runs, so the line never promises a
    row Start skips; then the secondary row: first run →
    `Copy.welcomeTryDemo` · (`OnboardingFlow.canStart(name:) ? Copy.welcomeSetUpLater : Copy.welcomeSetUpLaterNeedsName`);
    rerun → `Copy.welcomeClose` only. All plain `textTertiary` buttons.
  - **Start** (W14): `let plan = OnboardingFlow.plan(name: name, pickedEngine: pick, ticked: startIDs, mode: mode)`
    where `let drops = intake.welcomeDrops.filter { droppedTicked.contains($0.id) }` and `startIDs` is
    `FoundPolicy.order(inventory.items).map(\.id).filter(ticked.contains) + drops.map { FoundItemID.dropped($0.id) }`;
    `titles` maps each `.dropped($0.id)` to `IntakeSummary.previewTitle($0.preview)` and `origins` maps it
    to `$0.preview.origin ?? ""` (the row's real mark on Home); `starting = true`;
    `AccessibilityNotification.Announcement(Copy.welcomeSettingUp(startIDs.count)).post()`;
    `Task { await runner.run(plan, titles: titles, origins: origins, effects: effects); starting = false; if case .failed(let why) = runner.phase { ownerError = why } }`.
    `effects = LiveSetupEffects(store:, engineVM:, deps: .live(inventory:, watcher:, intake:), owner: owner, onShowHome: onShowHome, onClose: onClose, onChecklistChanged: runner.checklistChanged)`.
  - **Set up later** (R-IB16): without a name → `editingName = true; nameFocused = true` and nothing else;
    with one → `runner.run(OnboardingFlow.plan(name:, pickedEngine: nil, ticked: [], mode: .setUpLater), effects:)`.
  - **Try the demo instead**: `runner.run(SetupRunner.demoPlan, effects:)`; on `.failed(why)` show
    `why` in the `ownerError` slot and stay.
  - **Esc**: `.onExitCommand { if mode == .rerun { onClose() } }` (first run: nothing).
  - **Load** (`.task`): `await inventory.refresh()`; `owner = try? await APIClient.shared.fetchOwnerSettings()`;
    `name = WelcomeName.initial(saved: owner?.name, fullUserName: NSFullUserName())`;
    `editingName = !OnboardingFlow.canStart(name: name)`; `if engineVM.response == nil { await engineVM.load() }`;
    `ticked = WelcomeTicks.reconcile(items: inventory.items, current: ticked, touched: touched, allowRequested: allowRequested)`;
    `revealed = true`. Re-reconcile on `.onChange(of: inventory.items)`; re-probe on
    `NSApplication.didBecomeActiveNotification` (W5); when a row in `allowRequested` becomes `.ready`,
    post `AccessibilityNotification.Announcement(Copy.welcomeAllowed)`. New `intake.welcomeDrops` ids
    are inserted into `droppedTicked` (`.onChange(of: intake.welcomeDrops.map(\.id))` — the drop was
    the act, W11).
  - **Transition**: the view itself `.transition(.opacity)`; `ContentView` animates it with
    `CicadaMotion.morph(reduceMotion:)`.

- [ ] **Step 6: `WelcomeChecklist`** (same folder; parameters are bindings into the Welcome's state).
  Sections, each titled like Home's (caption caps, `textTertiary`), each row revealed with
  `.opacity(revealed ? 1 : 0).animation(CicadaMotion.reveal(index: i, reduceMotion:), value: revealed)` (W1):
  - `Copy.welcomeYourAIApps` — `FoundPolicy.order(inventory.items)` of `group == .agents`; each a
    `FoundRow(mark: OnThisMacStrip.mark(item.id), title: item.title, detail: OnThisMacStrip.detail(item.id),
    state: rowState(item), disclosure: disclosure(item), action: allowOrRetry(item), tick: tickBinding(item))`
    where `tickBinding` is nil for an item `WelcomeTicks.canTick` refuses, and sets `touched` on change;
    `rowState` maps readiness the way `OnThisMacStrip.row` does (`.alreadyOn` → `.on`, `.needsPermission`
    → `.needsAction(Copy.foundAllow)`, `.failed` → `.failed`, else `.off`); the disclosure is the strip's
    (`connect[].display`, "Changes <touches>", `Copy.foundPastStays`) — W6. While
    `inventory.isChecking && items.isEmpty` → `Copy.foundCheckingApps`; when the probe answered nothing
    (`!isChecking && wiring == nil`) → `Copy.foundBackendDown`.
  - `Copy.welcomeYourBrowsers` — `group == .browsers`, same row; *Allow…* → `allowRequested.insert(id);
    touched.insert(id); NSWorkspace.shared.open(BrowserFileError.fullDiskAccessURL)` (W5 — the row ticks
    itself when the grant lands). **No count** (R-IB12).
  - Both empty → `Copy.welcomeNothingFound` and the chat zone gets more height.
  - `Copy.welcomeYourChatHistory` — a dashed-border drop zone (`CicadaTheme.border`, 1 pt dash; while
    `dropTargeted`: `CicadaTheme.meadow` 2 pt over `CicadaTheme.meadowWash` — W10, a wash, not data)
    holding the three `VendorMark(vendor:size:)`s, `Copy.welcomeDropExport`, and a `Copy.intakeChooseFile`
    button that runs the same `NSOpenPanel` configuration as `IntakePanel.chooseFile()`
    (`Views/Intake/IntakePanel.swift:98-106`) and hands the URLs to
    `intake.accept(urls:from: .welcome)` (staged, because `welcomeActive`). The Welcome also opens that
    panel on `.onChange(of: intake.welcomeChooseRequest)` (⌘⇧I, the menu bar). Staged drops render as
    `FoundRow(mark: .logo(OriginIconography.logoName(for: drop.preview.origin ?? "") ?? ""), title:
    IntakeSummary.previewTitle(drop.preview), detail: IntakeSummary.countsLine(drop.preview), state: .off,
    tick: <droppedTicked binding>)`, each in an `HStack` with a small `xmark` button after it →
    `intake.removeWelcomeDrop(id)` (`FoundRow` has no trailing slot); `intake.welcomeDropError`
    shows in `danger` under the zone. Their `FoundItem`s for `startSummary` are
    `FoundItem(id: .dropped(id), group: .chatHistory, title:, isPresent: true, content: .ownIntentionalAct,
    readiness: .ready, opensAnotherApp: false, count: drop.preview.importCount,
    countNoun: drop.preview.chatFiles.isEmpty ? "saved item" : IntakeSummary.noun(vendor: drop.preview.vendor, count: 1))`
    — a saved-links file is counted as saved items, never as "conversations".
  - `Copy.welcomeWhoReads` — `EngineChoice(pick: $pick)`.

- [ ] **Step 7: `ContentView`.** Rewrite the G117 comment block (`:12-22`) for the Welcome (spec
  decision 14; the gate and "unknown is never empty" unchanged). Add
  `@State private var welcomeMode: OnboardingMode = .firstRun`. **Delete** `.sheet(isPresented:
  $showFirstRun) { FirstRunSheet(…) }` (`:143-145`) and add the Welcome layer **between** the
  `IntakeLayer` overlay (`:89`) and `.onDrop` (`:90`) — not where the sheet was. A modifier's drop
  region is the view it wraps: an overlay stacked after `.onDrop` sits outside that region and would
  take a drag over the Welcome without delivering it, and the Welcome's chat zone relies on the one
  window-level drop (R-IB8, R-IB15). The palette overlay (`:148`) stays above it; the palette ignores
  ⌘K under first run anyway (`PaletteToggle`).

```swift
        .overlay { IntakeLayer(dropTargeted: dropTargeted && !showFirstRun) }
        // Track I part b (spec decision 14, R-IB11) — the Welcome is a full-window
        // layer, not a sheet: the split view underneath is already on Home, so
        // Start reveals it. It sits above the intake layer, which stays unused
        // while it shows (R-IB15), and INSIDE the window's one drop target below.
        .overlay {
            if showFirstRun {
                WelcomeView(mode: welcomeMode, dropTargeted: dropTargeted,
                            onShowHome: {
                                withAnimation(CicadaMotion.morph(reduceMotion: reduceMotion)) {
                                    selectedTab = .home
                                    showFirstRun = false
                                }
                            },
                            onClose: {
                                withAnimation(CicadaMotion.morph(reduceMotion: reduceMotion)) { showFirstRun = false }
                            })
                    .transition(.opacity)
            }
        }
        .onDrop(of: [.fileURL], isTargeted: $dropTargeted) { providers in
            IntakeDrop.load(providers) { intake.accept(urls: $0, from: showFirstRun ? .welcome : .windowDrop) }
            return true
        }
```

  and, beside the other `.onChange` handlers,
  `.onChange(of: showFirstRun) { _, showing in intake.welcomeActive = showing }`. `evaluateFirstRun` sets
  `welcomeMode = .firstRun` before raising it; the `pendingFirstRun` handler sets `welcomeMode = .rerun`
  first; `.onAppear` also sets `intake.welcomeActive = showFirstRun`. Update the `evaluateFirstRun`
  docstring's "dismissal belongs to `FirstRunSheet`'s own completion" → "to the Welcome's Start, Set up
  later, demo and (rerun) Close".

- [ ] **Step 8: Retire (R-IB21).** `git rm` the three onboarding views and the two test files;
  delete the whole `// MARK: - First-run sheet (G117)` section of `Copy.swift` (`:424-457`:
  `onboardingChannelCaption`, `onboardingTryDemoBank`, `onboardingCreatingDemoBank`,
  `onboardingRunNightly`, `onboardingStepTitle` and their doc comments — read the block first; keep
  the `// MARK: - Empty states` section that follows);
  `IntegrationsView`: delete `var onHandOff` and its doc (`:13-18`) and the `onHandOff()` call (`:198`)
  — its only caller is gone and Settings' own hand-off already activates the window (R7);
  `FixWaveTests.swift:48` comment: replace `Views/Onboarding/OnboardingSleepStep.swift` with
  `Views/Home/GettingStartedCard.swift`; `AppRouterTests.swift:38-43` comment: "`FirstRunSheet` embeds
  `IntegrationsView` whole" → "the retired first-run sheet embedded `IntegrationsView` whole". Then:

```bash
cd <worktree> && rg -n "FirstRunSheet|OwnerIdentityStep|OnboardingSleepStep|OnboardingStep\b|OnboardingSchedule\b|onboardingStepTitle|onboardingChannelCaption|onboardingTryDemoBank|onboardingCreatingDemoBank|onboardingRunNightly|onHandOff" app/CicadaApp/Sources app/CicadaApp/Tests
```

  → only history comments remain (`Support/OnboardingFlow.swift:21`, `Support/ScheduleHonesty.swift:33`,
  `Views/Sleep/ScheduleToggle.swift:4` — Track Z's file, left alone — and the two rewritten test
  comments); no code reference. `rg -n "\.red\b" app/CicadaApp/Sources/CicadaApp/Views` → nothing
  new (the three onboarding literals left with their files).

- [ ] **Step 9: Verify.** `swift build 2>&1 | tail -5`; full `swift test 2>&1 | tail -20` → **0 failures**
  (the Meadow placement lint passes: `WelcomeView` names `WelcomeHero`, which lives in `Views/Meadow/`;
  the motion lint passes: no `duration:` outside the theme).

- [ ] **Step 10: Commit** —
  `feat(onboarding): one Welcome — found on this Mac, the ticks as consent, Start into Home; the four-step sheet and F2 retired (Track I T8, G117, spec decision 14)`.

---

### Task 5 (T10): Export reminders — with or without notifications

Design §5.5, R-IB22.

**Files:**
- Create: `app/…/Support/ExportWaits.swift`, `app/…/Support/Reminders.swift`,
  `app/…/Views/Intake/ExportAskRow.swift`, `app/…/Views/Feed/ExportWaitStrip.swift`
- Modify: `app/…/Views/Intake/IntakePanel.swift:49-56, 268-305` (the private row moves out)
- Modify: `app/…/Support/IntakeRouter.swift` (`onVendorSniffed`)
- Modify: `app/…/Views/Onboarding/WelcomeChecklist.swift`, `app/…/Views/Home/GettingStartedCard.swift`
- Modify: `app/…/Views/Feed/FeedView.swift:29-31`
- Modify: `app/…/MenuBarManager.swift:48-59, 195-251`, `app/…/Support/DockOpenQueue.swift:25-33`
- Modify: `app/…/CicadaApp.swift`, `app/…/Theme/Copy+Welcome.swift` (append)
- Test: new `ExportWaitsTests.swift`; `IntakeRouterTests.swift` (add)

**Interfaces:**
- Produces `ExportWait`, `ReminderDelay`, `ExportWaits` (pure: `adding`, `clearing`, `pruned`,
  `active`, `stripLine`, `menuLine`, `rowLine`), `ExportWaitStore` (`waits`, `remind`, `clear`,
  `remove`), `ReminderScheduling`, `LiveReminderScheduler`, `ReminderAvailability`,
  `ReminderTapQueue`, `ExportAskRow`, `ExportAskMenu`, `ExportWaitStrip`,
  `IntakeRouter.onVendorSniffed`, `MenuBarManager.exportWaitLines`.

- [ ] **Step 1: Failing tests** — `ExportWaitsTests.swift`:

```swift
import XCTest
@testable import CicadaApp

final class FakeReminders: ReminderScheduling {
    let grant: Bool
    var permissionAsks = 0
    var scheduled: [String] = []
    var cancelled: [String] = []
    init(grant: Bool) { self.grant = grant }
    func requestPermission() async -> Bool { permissionAsks += 1; return grant }
    func schedule(_ wait: ExportWait) async { scheduled.append(wait.id) }
    func cancel(_ wait: ExportWait) { cancelled.append(wait.id) }
}

/// Track I part b (design §5.5, R-IB22) — a reminder is a per-viewer
/// convenience whose text twins work with notifications off.
@MainActor
final class ExportWaitsTests: XCTestCase {
    private let now = ISO8601DateFormatter().date(from: "2026-09-23T10:00:00Z")!
    private let en = Locale(identifier: "en_US")

    private func wait(_ vendor: String = "chatgpt", bank: String = "default", hoursAgo: Double = 2,
                      remindIn: Double = 21) -> ExportWait {
        ExportWait(vendor: vendor, bank: bank, requestedAt: now.addingTimeInterval(-hoursAgo * 3600),
                   remindAt: now.addingTimeInterval(remindIn * 3600))
    }

    private func suite() -> UserDefaults { UserDefaults(suiteName: "waits-\(UUID().uuidString)")! }

    func testOneWaitPerVendorPerBank() {
        let waits = ExportWaits.adding(wait(hoursAgo: 1), to: [wait(hoursAgo: 5), wait("claude")])
        XCTAssertEqual(waits.filter { $0.vendor == "chatgpt" }.count, 1)
        XCTAssertEqual(waits.count, 2)
    }

    func testAWaitExpiresAfterFourteenDaysAndBelongsToItsBank() {
        let old = wait(hoursAgo: 14 * 24 + 1), fresh = wait("claude", hoursAgo: 13 * 24)
        XCTAssertEqual(ExportWaits.pruned([old, fresh], now: now), [fresh])
        XCTAssertTrue(ExportWaits.active([wait(bank: "default")], bank: "beta-bank", now: now).isEmpty)
    }

    func testTheTwinsSayWhoAndWhen() {
        let w = wait()
        XCTAssertEqual(ExportWaits.stripLine(w, now: now, locale: en), "Waiting for your ChatGPT export · requested 2 hours ago")
        XCTAssertEqual(ExportWaits.menuLine(w, now: now, locale: en), "Waiting for ChatGPT export, requested 2 hours ago")
        XCTAssertEqual(ExportWaits.rowLine(w, now: now, locale: en), "Requested 2 hours ago · reminder in 21 hours")
    }

    func testTheDelaysAreWhatTheyMenuSays() {
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = TimeZone(identifier: "UTC")!
        let morning = ReminderDelay.tomorrowMorning.remindAt(from: now, calendar: cal)
        XCTAssertEqual(cal.component(.hour, from: morning), 9)
        XCTAssertEqual(cal.component(.day, from: morning), 24)
        XCTAssertEqual(ReminderDelay.threeHours.remindAt(from: now, calendar: cal), now.addingTimeInterval(3 * 3600))
        XCTAssertEqual(ReminderDelay.twoDays.remindAt(from: now, calendar: cal), now.addingTimeInterval(2 * 86_400))
    }

    func testPermissionIsAskedOnlyAtRemindAndADenialStillRecordsTheWait() async {
        let fake = FakeReminders(grant: false)
        let store = ExportWaitStore(defaults: suite(), scheduler: fake, now: { self.now })
        XCTAssertEqual(fake.permissionAsks, 0, "never asked before the person chose Remind me")
        let granted = await store.remind(vendor: "chatgpt", bank: "default", delay: .threeHours)
        XCTAssertFalse(granted)
        XCTAssertEqual(store.waits.map(\.vendor), ["chatgpt"], "the twins carry it")
        XCTAssertEqual(fake.permissionAsks, 1)
        XCTAssertTrue(fake.scheduled.isEmpty)
    }

    func testClearingAWaitCancelsItsNotificationAndItSurvivesARelaunch() async {
        let defaults = suite()
        let fake = FakeReminders(grant: true)
        let first = ExportWaitStore(defaults: defaults, scheduler: fake, now: { self.now })
        _ = await first.remind(vendor: "claude", bank: "default", delay: .twoDays)
        XCTAssertEqual(fake.scheduled, ["default|claude"])
        let relaunched = ExportWaitStore(defaults: defaults, scheduler: fake, now: { self.now })
        XCTAssertEqual(relaunched.waits.map(\.vendor), ["claude"])
        relaunched.clear(vendor: "claude", bank: "default")
        XCTAssertTrue(relaunched.waits.isEmpty)
        XCTAssertEqual(fake.cancelled, ["default|claude"])
    }

    func testTheNotificationCenterIsOnlyTouchedInsideARealAppBundle() {
        XCTAssertFalse(ReminderAvailability.isAvailable(bundleIdentifier: nil, bundlePath: "/x/CicadaApp"))
        XCTAssertFalse(ReminderAvailability.isAvailable(bundleIdentifier: "com.apple.dt.xctest.tool", bundlePath: "/x/xctest"))
        XCTAssertTrue(ReminderAvailability.isAvailable(bundleIdentifier: "com.example.cicada", bundlePath: "/Applications/Cicada.app"))
    }
}
```

  `IntakeRouterTests.swift` — add:

```swift
    /// R-IB22 — a sniff of the export someone was waiting for clears that wait.
    func testASniffedExportReportsItsVendor() async throws {
        let api = FakeIntakeAPI()
        api.sniffs = ["conversations.json": chat("chatgpt")]
        let router = IntakeRouter(api: api)
        var sniffed: [String] = []
        router.onVendorSniffed = { sniffed.append($0) }
        router.accept(urls: [try file("conversations.json")], from: .windowDrop)
        try await eventually("the preview") { self.isPreview(router) }
        XCTAssertEqual(sniffed, ["chatgpt"])
    }
```

  Red: `swift build` fails.

- [ ] **Step 2: `Support/ExportWaits.swift`.**

```swift
import Foundation
import Observation

/// Someone asked a vendor for their export and wants a nudge when it should
/// have arrived. A per-viewer convenience in defaults — never memory, never a
/// bank, never the network (nothing is fetched to learn that an email came).
struct ExportWait: Codable, Equatable, Identifiable {
    let vendor: String
    let bank: String
    let requestedAt: Date
    let remindAt: Date
    var id: String { "\(bank)|\(vendor)" }
}

enum ReminderDelay: String, CaseIterable, Identifiable {
    case threeHours, tomorrowMorning, twoDays
    var id: String { rawValue }

    var label: String {
        switch self {
        case .threeHours: Copy.reminderInThreeHours
        case .tomorrowMorning: Copy.reminderTomorrowMorning
        case .twoDays: Copy.reminderInTwoDays
        }
    }

    func remindAt(from now: Date, calendar: Calendar = .autoupdatingCurrent) -> Date {
        switch self {
        case .threeHours: return now.addingTimeInterval(3 * 3600)
        case .twoDays: return now.addingTimeInterval(2 * 86_400)
        case .tomorrowMorning:
            let tomorrow = calendar.date(byAdding: .day, value: 1, to: calendar.startOfDay(for: now)) ?? now
            return calendar.date(bySettingHour: 9, minute: 0, second: 0, of: tomorrow) ?? tomorrow
        }
    }
}

/// Track I part b (design §5.5, R-IB22) — the pure half: one wait per bank ×
/// vendor, gone after 14 days, and the three sentences the twins show.
enum ExportWaits {
    static let defaultsKey = "cicada.exportWaits"
    static let maxAge: TimeInterval = 14 * 86_400

    static func adding(_ w: ExportWait, to waits: [ExportWait]) -> [ExportWait] { waits.filter { $0.id != w.id } + [w] }
    static func clearing(vendor: String, bank: String, in waits: [ExportWait]) -> [ExportWait] {
        waits.filter { !($0.vendor == vendor && $0.bank == bank) }
    }
    static func pruned(_ waits: [ExportWait], now: Date) -> [ExportWait] {
        waits.filter { now.timeIntervalSince($0.requestedAt) < maxAge }
    }
    static func active(_ waits: [ExportWait], bank: String, now: Date) -> [ExportWait] {
        pruned(waits, now: now).filter { $0.bank == bank }.sorted { $0.requestedAt < $1.requestedAt }
    }

    static func vendorTitle(_ vendor: String) -> String { ChatVendor(rawValue: vendor)?.title ?? vendor }

    static func relative(_ date: Date, now: Date, locale: Locale) -> String {
        let f = RelativeDateTimeFormatter()
        f.locale = locale
        f.unitsStyle = .full
        return f.localizedString(for: date, relativeTo: now)
    }

    static func stripLine(_ w: ExportWait, now: Date, locale: Locale = .autoupdatingCurrent) -> String {
        "Waiting for your \(vendorTitle(w.vendor)) export · requested \(relative(w.requestedAt, now: now, locale: locale))"
    }
    static func menuLine(_ w: ExportWait, now: Date, locale: Locale = .autoupdatingCurrent) -> String {
        "Waiting for \(vendorTitle(w.vendor)) export, requested \(relative(w.requestedAt, now: now, locale: locale))"
    }
    static func rowLine(_ w: ExportWait, now: Date, locale: Locale = .autoupdatingCurrent) -> String {
        let requested = "Requested \(relative(w.requestedAt, now: now, locale: locale))"
        return w.remindAt > now ? "\(requested) · reminder \(relative(w.remindAt, now: now, locale: locale))" : requested
    }
}

/// The waits, persisted, and the one place a reminder is scheduled. The
/// notification permission is requested here and only here — from the person's
/// own "Remind me" — and a denial still records the wait, because the Feed,
/// the menu bar and Getting started say it without any permission.
@MainActor
@Observable
final class ExportWaitStore {
    private(set) var waits: [ExportWait]
    @ObservationIgnored private let defaults: UserDefaults
    @ObservationIgnored private let scheduler: ReminderScheduling
    @ObservationIgnored private let now: () -> Date

    init(defaults: UserDefaults = .standard, scheduler: ReminderScheduling = LiveReminderScheduler(),
         now: @escaping () -> Date = Date.init) {
        self.defaults = defaults
        self.scheduler = scheduler
        self.now = now
        let stored = (defaults.data(forKey: ExportWaits.defaultsKey))
            .flatMap { try? JSONDecoder().decode([ExportWait].self, from: $0) } ?? []
        waits = ExportWaits.pruned(stored, now: now())
        persist()
    }

    func active(bank: String) -> [ExportWait] { ExportWaits.active(waits, bank: bank, now: now()) }

    @discardableResult
    func remind(vendor: String, bank: String, delay: ReminderDelay) async -> Bool {
        let at = now()
        let wait = ExportWait(vendor: vendor, bank: bank, requestedAt: at, remindAt: delay.remindAt(from: at))
        waits = ExportWaits.adding(wait, to: waits)
        persist()
        guard await scheduler.requestPermission() else { return false }
        await scheduler.schedule(wait)
        return true
    }

    func clear(vendor: String, bank: String) {
        for w in waits where w.vendor == vendor && w.bank == bank { scheduler.cancel(w) }
        waits = ExportWaits.clearing(vendor: vendor, bank: bank, in: waits)
        persist()
    }

    func remove(_ wait: ExportWait) { clear(vendor: wait.vendor, bank: wait.bank) }

    private func persist() {
        defaults.set(try? JSONEncoder().encode(waits), forKey: ExportWaits.defaultsKey)
    }
}
```

- [ ] **Step 3: `Support/Reminders.swift`.**

```swift
import AppKit
import UserNotifications

/// Main-actor, like the store that calls it: the fake's counters and the live
/// scheduler's notification centre are then touched from one isolation domain,
/// never across an `await` from the main actor into a nonisolated method.
@MainActor
protocol ReminderScheduling {
    func requestPermission() async -> Bool
    func schedule(_ wait: ExportWait) async
    func cancel(_ wait: ExportWait)
}

/// `UNUserNotificationCenter.current()` raises in a process with no app bundle
/// (`swift test`, a bare `swift run`), so it is touched only inside a real `.app`.
enum ReminderAvailability {
    static func isAvailable(bundleIdentifier: String?, bundlePath: String) -> Bool {
        bundleIdentifier != nil && bundlePath.hasSuffix(".app")
    }
    static var current: Bool {
        isAvailable(bundleIdentifier: Bundle.main.bundleIdentifier, bundlePath: Bundle.main.bundlePath)
    }
}

/// One-shot local notifications; nothing fetched, nothing sent (design §5.5).
struct LiveReminderScheduler: ReminderScheduling {
    static let userInfoVendor = "vendor"

    func requestPermission() async -> Bool {
        guard ReminderAvailability.current else { return false }
        return (try? await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound])) ?? false
    }

    func schedule(_ wait: ExportWait) async {
        guard ReminderAvailability.current else { return }
        let content = UNMutableNotificationContent()
        content.title = Copy.reminderTitle(ExportWaits.vendorTitle(wait.vendor))
        content.body = Copy.reminderBody
        content.userInfo = [Self.userInfoVendor: wait.vendor]
        let parts = Calendar.autoupdatingCurrent.dateComponents([.year, .month, .day, .hour, .minute], from: wait.remindAt)
        let request = UNNotificationRequest(identifier: Self.identifier(wait), content: content,
                                            trigger: UNCalendarNotificationTrigger(dateMatching: parts, repeats: false))
        try? await UNUserNotificationCenter.current().add(request)
    }

    func cancel(_ wait: ExportWait) {
        guard ReminderAvailability.current else { return }
        UNUserNotificationCenter.current().removePendingNotificationRequests(withIdentifiers: [Self.identifier(wait)])
    }

    static func identifier(_ wait: ExportWait) -> String { "cicada.exportWait.\(wait.id)" }
}

/// A tapped reminder, held until the router attaches (the `DockOpenQueue` shape).
@MainActor
final class ReminderTapQueue {
    private var pending: [ChatVendor] = []
    private var handler: ((ChatVendor) -> Void)?

    func receive(_ vendor: ChatVendor) { if let handler { handler(vendor) } else { pending.append(vendor) } }

    func attach(_ handler: @escaping (ChatVendor) -> Void) {
        self.handler = handler
        let queued = pending
        pending = []
        queued.forEach(handler)
    }
}
```

  `CicadaAppDelegate` (`Support/DockOpenQueue.swift`) gains `let reminderTaps = ReminderTapQueue()`,
  conforms to `UNUserNotificationCenterDelegate`, sets `UNUserNotificationCenter.current().delegate = self`
  in `applicationDidFinishLaunching(_:)` **only when `ReminderAvailability.current`**, and implements
  `nonisolated func userNotificationCenter(_:didReceive:withCompletionHandler:)` (read
  `userInfo["vendor"]`, `Task { @MainActor in if let v = ChatVendor(rawValue: vendor) { self.reminderTaps.receive(v) } }`,
  then `completionHandler()`) and `nonisolated func userNotificationCenter(_:willPresent:withCompletionHandler:)`
  → `completionHandler([.banner, .sound])`. A tap only opens the intake — never a cycle (G125 R10).

- [ ] **Step 4: The asking row and the twins.**
  - `Views/Intake/ExportAskRow.swift`: move `VendorExportRow` out of `IntakePanel.swift` as
    `ExportAskRow(vendor:startsOpen:)` (same body; it reads `@Environment(ExportWaitStore.self) waits`
    and `@Environment(Store.self) store` and keeps `@State denied = false` — every host is on the main
    window, which carries both) and add, after *Open export page*, a `Menu` labelled
    `Label(Copy.reminderRemindMe, systemImage: "bell")` listing `ReminderDelay.allCases` →
    `Task { denied = !(await waits.remind(vendor: vendor.rawValue, bank: store.bank, delay: d)) }`,
    with `Copy.reminderNotificationsOff` shown under the row while `denied`. Also define
    `ExportAskMenu(vendor:)` — one `Menu` per vendor labelled with its `VendorMark` + title, holding
    *Open export page* and the delays — for the Welcome's compact zone. `IntakePanel` uses
    `ExportAskRow` where it used `VendorExportRow` (`:54`).
  - `WelcomeChecklist`: under the drop zone, `Copy.welcomeAskForOne` followed by the three
    `ExportAskMenu`s; below them, each active wait's `ExportWaits.rowLine` (W12's text twin).
  - `GettingStartedCard`: the chat-history row lists `waits.active(bank: store.bank)` — each
    `VendorMark(origin: ChatVendor(rawValue: w.vendor)?.origin, size:)` + `ExportWaits.rowLine(w, now: now)`
    + a *Choose a file…* → `intake.present(from: origin(w))` + ✕ → `waits.remove(w)` — and, with none,
    the `ExportAskRow`s beneath the drop line. `ExportWait.vendor` is the raw string, so the one helper
    `origin(_ w:) -> IntakeOrigin` is `ChatVendor(rawValue: w.vendor).map { .reminder($0) } ?? .onboardingRow`
    (the strip below uses the same mapping, with `.windowDrop` as its fallback).
  - `Views/Feed/ExportWaitStrip.swift`: for each active wait of the active bank, one row
    (`VendorMark`, `ExportWaits.stripLine`, `Copy.reminderDropHere` in `accent`, ✕), inside a
    `TimelineView(.periodic(from: .now, by: 60))` so "2 hours ago" stays true; the row is a drop target
    (`.onDrop(of: [.fileURL]) { IntakeDrop.load($0) { intake.accept(urls: $0, from: origin(w)) }; return true }`).
    Mount it in `FeedView` directly under `ConnectedChannelsStrip` (`:29-31`) with the same padding.
  - `MenuBarManager`: `@ObservationIgnored var exportWaitLines: () -> [String] = { [] }` (set by the
    app; the manager is `@Observable`, and a closure is not state to observe); in
    `rebuildMenu` insert, after "Next sleep", one disabled item per line tagged `Self.exportWaitTag`
    (`= 9_101`); set `menu.delegate = self`; and

```swift
extension MenuBarManager: NSMenuDelegate {
    /// "requested 2 hours ago" must be true when the menu opens, not when it was
    /// last rebuilt — AppKit calls this just before showing the menu.
    nonisolated func menuNeedsUpdate(_ menu: NSMenu) {
        MainActor.assumeIsolated { self.refreshExportWaitItems(in: menu) }
    }
}
```

    with `refreshExportWaitItems` removing the tagged items and re-inserting the current lines at the
    index after "Next sleep".
  - `IntakeRouter`: `@ObservationIgnored var onVendorSniffed: ((String) -> Void)?`, called in `sniff()`
    and `stageForWelcome` whenever the aggregate is `.preview(p)` with `p.vendor != nil`.
  - `CicadaApp.swift`: `@State private var exportWaits = ExportWaitStore()` in the main window's
    environment; in `.onAppear`: `intakeRouter.onVendorSniffed = { [exportWaits, store] v in exportWaits.clear(vendor: v, bank: store.bank) }`;
    `appDelegate.reminderTaps.attach { [intakeRouter] vendor in NSApplication.shared.activate(ignoringOtherApps: true); intakeRouter.present(from: .reminder(vendor)) }`;
    `menuBarManager.exportWaitLines = { [exportWaits, store] in exportWaits.active(bank: store.bank).map { ExportWaits.menuLine($0, now: Date()) } }`.
  - Copy (`Copy+Welcome.swift`, labels to `welcomeHomeLabels`, `reminderNotificationsOff` and
    `reminderTitle` sample to sentences):

```swift
    // MARK: Reminders (Task 5, design §5.5)
    static let reminderRemindMe = "Remind me"
    static let reminderInThreeHours = "In 3 hours"
    static let reminderTomorrowMorning = "Tomorrow at 9:00"
    static let reminderInTwoDays = "In 2 days"
    static let reminderBody = "Drop the .zip on Cicada."
    static let reminderDropHere = "Drop it here"
    static let welcomeAskForOne = "No export yet? Ask for one"
    static let reminderNotificationsOff = "Notifications are off, so the reminder waits here and in the menu bar."
    static func reminderTitle(_ vendor: String) -> String { "Your \(vendor) export should be in your email." }
```

- [ ] **Step 5: Verify.** `swift build`; `swift test --filter "ExportWaitsTests|IntakeRouterTests|IntakePreviewTests|CopyConstantsTests" 2>&1 | tail -20`;
  full `swift test` → **0 failures** (no test ever reaches `UNUserNotificationCenter`: the store under
  test takes `FakeReminders`, and the live scheduler returns early outside an `.app`).

- [ ] **Step 6: Commit** —
  `feat(intake): export reminders — asked for only at Remind me, told in the Feed, the menu bar and Getting started either way (Track I T10)`.

---

### Task 6 (T11): Docs — the ruling, the rails, where the next reader looks

**Files:** `CLAUDE.md`; `docs/goals/memory-evolution.md` (rows G108, G117, G54, G125);
`docs/goals/TODO.md`.

- [ ] **Step 1: `CLAUDE.md`, Companion App.**
  - Replace `**Navigation.** Six sidebar rows (⌘1–6): Graph, Clusters, Feed, Sleep, Inbox, Sources.`
    with `**Navigation.** Seven sidebar rows (⌘1–7): Home, Graph, Clusters, Feed, Sleep, Inbox, Sources
    (G108, ruled 2026-09-23). Relaunch restores the last tab: nothing stored, or a value no build knows,
    opens Home, and a stored Graph stays on Graph.`
  - After the **One intake** paragraph, add:

    > **Home (G108, Track I part b).** The front door at ⌘1: "What would you like / *to remember?*" over a
    > procedural sky with one cloud (art composed in `Views/Meadow/`, never under a number), then the
    > palette's own `FindPanelBody` in `.page` placement — a second `FindPaletteModel` sharing the one
    > Ask and keeping no recents; ⌘K on Home focuses it, a pasted `http(s)` link offers *Save this link*.
    > Below it: Getting started (while it lasts), then Today (captured today, UTC, with the three busiest
    > marks), Needs you (the inbox's first three) and Last read (the newest Sleep commit and its pages) —
    > each number once, each a link to the page that owns it; the waiting count is a link to Sleep, never a
    > Consolidate.
    >
    > **Onboarding (G117, Track I part b).** One full-window Welcome, shown by the unchanged
    > `FirstRunGate` (unknown is never empty): the hero meadow as its band, the headline on the card that
    > rises into it, what Cicada found on this Mac as a checklist whose ticks are the consent (own acts, no
    > new permission prompt, no other app — `FoundPolicy`), a chat-export drop zone that stages rows and
    > imports nothing before Start, the engine cards with each one's cost model (`EngineChoice`, never
    > blocking — an untouched choice keeps the install's configured engine, and Getting started asks
    > "who reads" only if that cannot run), and one meadow pill whose text twin says exactly what it
    > will do. A browser's bookmarks are neither counted nor read before its tick. Start is `SetupRunner`:
    > the owner PUT first and alone, then Home, then every ticked row side by side, each failure on its
    > own row. Getting started continues on Home — rows from the machine's own state, the first read
    > (*Read now*, G125 R10's second narrow amendment, only inside the card), and "Keep reading on its
    > own?" asked once of a person still on `manual`, its options gated by ruling 4. *Set up later*,
    > *Try the demo instead* and Settings → General's *Run setup again* / *Show setup checklist* remain.
    > Export reminders (`ExportWaits`) ask for notification permission only when the person chooses a
    > delay; the Feed strip, the menu bar and the card say the same with notifications off.

  - Meadow paragraph: after "enforced by an allowlist lint." add "The Welcome's hero band
    (`WelcomeHero`) and Home's sky band (`HomeSkyBand`) are composed inside `Views/Meadow/`, so the
    pages that carry text and numbers never name a painted component."
- [ ] **Step 2: Backlog rows.** In `docs/goals/memory-evolution.md`:
  - **G108** (line 670): in the body replace `**Not yet decided; do not build either half without a
    ruling.**` with `**Ruled 2026-09-23 — see the status cell.**`, and replace the status cell `| 🔲 |`
    with `| ✅ **Ruled 2026-09-23 (spec decision 12), built by Track I part b:** (a) **Home is the
    front door** — `AppTab.home` at ⌘1, search first (the palette's own body), then Getting started,
    Today, Needs you and Last read, each number once and each a link to its page; Graph follows at ⌘2;
    relaunch restores the last tab (`restored(from:)`: nothing stored or unknown → Home, a stored Graph →
    Graph), so nobody who lives in the graph is moved. (b) Navigation is **historical** (browser-style
    back/forward), built with **G106** where following links makes it load-bearing; this track added no
    history stack. |`
  - **G117** (line 679): append to the status cell, before its closing `|`: ` **Track I part b
    (2026-09-23):** one full-window Welcome replaces the four-step sheet — found-on-this-Mac rows whose
    ticks are the consent, the name prefilled and still required, the engine cards with their cost models
    visible and never blocking, a line under Start that says what it does; Start (`SetupRunner`) saves the
    owner first and alone and lands on Home's Getting started (live rows, the first read, the schedule
    asked honestly). F2 retired with `FirstRunSheet`; `OwnerIdentityStep`, `OnboardingSleepStep` and
    `OnboardingSchedule` retired. Bookmarks are neither read nor counted before their tick (R-IB12).
    Open: in-card sign-in and the Settings → You row (Track O), notes & voice rows on the Welcome, the
    Claude Desktop JSON merge (T13), the evening reminder.`
  - **G54** (line 606): in the body, before the final `| 🔲 |`, append ` **Track I part b
    (2026-09-23):** still deferred (design §10, "G54 interview deferred — keep"). Its place is known: the
    Welcome's "Nothing to bring over automatically" state and an empty Getting started are where a person
    with nothing to import would be offered the interview.`
  - **G125** (line 686): in the status cell replace `Part b adds Getting started's.` with `**Amendment 2
    of 2 (Track I part b):** Getting started's *Read now* (and its *Read the next N* / *Try again*) — a
    user trigger subtitled with `preview.manual`'s engine, disabled until an engine can run, and present
    only inside the Getting started card; Home's steady-state waiting count is a link to Sleep.`
- [ ] **Step 3: `TODO.md`.** Replace the sentence "Part b (T8 Welcome, T9 Home + ⌘1–7, T10 reminders,
  T11 docs, T12 live pass) is next." (it wraps across `TODO.md:42-43`) with `**Part b** (\`feat/welcome-home\`): the one-screen Welcome (the four-step
  sheet and F2 retired), Home at ⌘1 with Getting started, and export reminders with text twins; T12 (the
  live pass and screenshots) is the orchestrator's. Measured on the branch: Swift **<N> executed, 0
  failures**, backend **<M> passed** (unchanged — no Python in this track).` — `<N>` and `<M>` are
  the counts Step 4's runs print: run Step 4's two suites first, then write this sentence with the
  real numbers (never the angle brackets), then finish Step 4's remaining checks.
- [ ] **Step 4: Verify.** `cd <worktree>/app/CicadaApp && swift build 2>&1 | tail -5` and `swift test 2>&1 |
  tail -20` → 0 failures (quote the executed count); `cd <worktree> && api/.venv/bin/python -m pytest
  api/tests -q -p no:cacheprovider` → 0 failures (quote the count; the order-dependent rule applies);
  `cd <worktree> && node --test app/CicadaApp/Tests/graph/*.test.js` → green. Privacy check:
  `git diff dev -- CLAUDE.md docs/` contains no person's name, no bank title, no URL other than
  `example.com`, no absolute path.
- [ ] **Step 5: Commit** — `docs(G108/G117): Home ruled and built; the one-screen Welcome; CLAUDE.md navigation and onboarding; G54, G125 notes`.

---

## Not in scope

Named so a reviewer reads an absence as a decision, not an oversight.

- **T12, the live pass and screenshots** — the orchestrator's (below).
- **Track O's pieces:** `EngineChooser` (the `EngineChoice` seam swaps to it), `ConnectionLoginFlow`
  (in-card sign-in — Plans & keys' link stands in, R-IB13), Settings → You (handle and email; the Welcome
  edits the name only and passes the others through), the Settings v3 home of *Show setup checklist*.
- **The evening reminder** (design §5.5's `EveningReminder` and the schedule question's checkbox): the
  brief's T10 names the export reminders; a second, daily notification kind would widen the one
  permission the person granted for one export, and `ScheduleHonesty.offerEveningReminder` waits for it.
- **Home's "Use your memory from your phone" suggestion** (Track R): not in the brief's Home list; it
  needs its own per-bank prompt memory.
- **Notes & voice rows on the Welcome** (R-IB23) and **Hermes / Gemini CLI registration** (R-IA15).
- **The Claude Desktop JSON merge** (T13) and **the Downloads watch** (D-6 / T14).
- **The skill copy on any onboarding surface** (G72 / R5 D2).
- **G108(b), a history stack** — built with G106.
- **A bookmark count on the Welcome** (R-IB12) and **the F1b gate race reproduction** (needs a clean
  defaults domain — a throwaway macOS user).
- **`matchedGeometryEffect` for Welcome → Home** (R-IB11) and **`backgroundExtensionEffect` on Home's
  band** (R-IB10) — M2's to try against the G109 frame budget.
- **Home keeping its scroll position** (R-IB3) and **Home's own drop target** (R-IB8).
- **Any backend, MCP or `install.sh` change**, any new Store domain or ETag, any `Views/Sleep/**` edit.
- **The G54 onboarding interview** — still deferred; its place is recorded on the row.
- **Always opening on Home at launch** (D-3b: no).

---

## Verification the orchestrator runs at the end

1. `cd <worktree>/app/CicadaApp && swift build 2>&1 | tail -5` → success; `swift test 2>&1 | tail -20`
   → **0 failures** (re-measure `dev`'s executed count first; this track adds eleven test files and
   deletes two).
   `cd <worktree> && node --test app/CicadaApp/Tests/graph/*.test.js` → green.
   `cd <worktree> && api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider` → 0 failures
   (no Python changed; the order-dependent rule applies).
2. **Lints that must bite:** add `GrassEdge()` to `Views/Home/HomeView.swift` →
   `MeadowPlacementLintTests` fails; add `.animation(.easeIn(duration: 0.2), value: 1)` to
   `Views/Onboarding/WelcomeView.swift` → `MotionLiteralLintTests` fails; add
   `Text("\(n) waiting")` to `Views/Home/HomeSections.swift` → `CountLiteralLintTests` fails; add
   the literal `"Keep your claims"` to the `welcomeHomeLabels` array → `CopyConstantsTests` fails; add
   `.foregroundStyle(.red)` to `Views/Home/GettingStartedCard.swift` → `NoRedLiteralLintTests` fails.
   Revert each, confirm green.
3. `rg -n "FirstRunSheet|OwnerIdentityStep|OnboardingSleepStep|OnboardingSchedule\b|onHandOff" app/CicadaApp/Sources`
   → history comments only. `rg -n "triggerManually" app/CicadaApp/Sources/CicadaApp/Views/Home` → one
   line (`GettingStartedCard.swift`). `rg -n "UNUserNotificationCenter" app/CicadaApp/Sources` → only
   `Support/Reminders.swift` and `Support/DockOpenQueue.swift`.
4. **Live, after installing — on a throwaway memory, never the owner's bank.** Create an empty memory
   (e.g. `welcome-check`) and switch to it: the gate opens the **Welcome** (full window, hero band, the
   card rising into the meadow). Check light and dark, 1.0× and 1.4× (the card scrolls, the footer stays
   pinned), Reduce Motion (rows appear at once, no bounce) and VoiceOver (the headline first; each row
   reads "<title>. <detail>. On/Off."). The name is prefilled; "Not <name>? Change" edits it; clearing it
   disables Start with "Add your name to start". Claude Code reads **On** (install.sh wired it) with no
   tick; expand a disclosure and compare the commands with `install.sh:277-321`. **On the owner's
   machine, untick every agent and browser** — ticking writes `~/.codex` or enables a machine-global
   browser watch, and a live check is not consent. Write the synthetic fixtures with
   `cd <worktree> && api/.venv/bin/python api/tests/_intake_fixtures.py <scratchpad>/intake`, then drag
   `<scratchpad>/intake/claude-export.zip` onto the window: a ticked "Claude history" row
   appears on the card, no overlay opens, nothing imports. ⌘⇧I opens the Welcome's own file panel. The
   engine cards each show a cost-model line and no price; clicking one rings it and the line reads
   "… · saved when you press Start". Press **Start**: Home appears, Getting started shows the dropped row
   going "Bringing it in…" → its headline; "N waiting to be read." with **Read now** subtitled by the
   manual engine. **Do not press Read now** without the owner's go-ahead (it spends a plan read on a
   throwaway bank). ⌘1 focuses the field; typing "alpha" swaps the cards for results; Esc restores them;
   pasting `https://example.com` offers "Save this link · example.com". ⌘2 is Graph; quit and relaunch →
   the last tab returns.
5. **Reminders:** in Getting started (or `+` → Chat exports), *Remind me → In 3 hours*: the macOS
   notification prompt appears **now and only now**. Deny it (or allow it) — either way the Feed shows
   "Waiting for your ChatGPT export · requested …", the menu-bar menu shows the disabled line, and the
   card shows "Requested … · reminder in 3 hours". Drop the ChatGPT fixture: the wait clears in all three.
   If §14 item 3 fails (no prompt in the ad-hoc-signed build), record it on G117 — the twins carry it.
6. **Rerun and the exits:** Settings → General → *Run setup again* opens the Welcome in rerun mode (*Save
   changes*, *Close*, Esc closes, no demo link). On another fresh memory, *Set up later* (with a name)
   lands on Home with *Also found*; on a third, *Try the demo instead* lands on the demo's Home.
   *Show setup checklist* brings the card back.
7. **Screenshots from the `demo` bank only** — the Welcome light and dark (via *Run setup again* on the
   demo), Home, Getting started. Afterwards switch back to the owner's memory and tell the owner the
   throwaway memories exist (there is no delete route yet — G87).
8. **The PR body states:** no backend change, no new Store domain, no ETag recipe touched; no price, token
   count or duration estimate on any surface; the notification permission is requested only from
   *Remind me*; bookmarks are neither read nor counted before their tick; G125 R10's second narrow
   amendment (Getting started's *Read now*); F2 retired with `FirstRunSheet`; the `EngineChoice` seam for
   Track O.

---

## Cross-track seams (what each sibling needs to know)

| Track | Seam |
|---|---|
| O (Settings v3) | Replace `EngineChoice`'s body with `EngineChooser(style: .compact, …)` (the `pick` binding means "select, don't write"); put `ConnectionLoginFlow` under the cards; move *Show setup checklist* and *Run setup again* into the new General; Settings → You takes handle/email (the Welcome passes them through untouched). |
| S (search) | `FindPanelBody` gained three defaulted parameters and `showsBody`; `FindPaletteModel` gained `init(store:ask:keepsRecents:)`; `PaletteToggle` gained `homeVisible:` / `.focusHome`. The palette's own behaviour is byte-identical; the server tier (S4) reaches Home automatically through the shared index and model API. |
| F1 (display face) | Every headline here is `CicadaTheme.displayFont(size:italic:)`; the switch needs no edit in this track. |
| Z (mascot page) | `IntakeRouter.accept(urls:from: .sleepRoom)` stages on the Welcome while it shows (it never does on the Sleep page in practice). No `Views/Sleep` file was touched. |
| M2 (Meadow pass) | `HomeSkyBand` / `WelcomeHero` are the two new Meadow compositions; `backgroundExtensionEffect` and a Welcome → Home morph are yours to try against the G109 frame budget. |
| R (remote) | Home's "use your memory from your phone" suggestion is not built; it would sit under Last read, shown after the first read while remote is off. |
