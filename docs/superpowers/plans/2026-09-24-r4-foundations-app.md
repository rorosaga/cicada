# Round 4 foundations — app (Track R4-A) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Before the owner's clean first run, the app half of round 4's foundations is in place and every piece is
named the way the later onboarding and animated-band tracks will build on it: (a) a project whose one happening cites
622 papers opens instantly; (b) Home's painting follows the owner's real day and night, with Settings → General →
Scene to pin it; (c) Cicada can open at login, keeps syncing with its window closed, and can install its own
background service; (d) the Calendar app's events flow in through EventKit; (e) every agent write reads
"Claude Code · Opus 5.5 · high effort"; (f) an agent can be connected by copying one prompt, and Claude desktop by one
click.

**Architecture:** Every decision is a **pure function with a table test** — the chip budget, the sun's position, the
scene preference, the login-item state, the background-agent policy and state, the calendar event mapping, the model
names, the Claude desktop config merge — and the views are thin renderers over them. Everything that touches the
system sits behind a protocol seam (`LoginItemControlling`, `AgentProcessRunning`, `CalendarStore`,
`CalendarSyncAPI`) so tests never touch launchd, EventKit or the network. No new Store domain, no new ETag, no
`VersionVector` mapping. Every new wire field decodes optional-with-default, so this branch runs against today's
backend and against the parallel backend track's (`feat/r4-foundations-back`). The only non-Swift code is one bash
script (the LaunchAgent step lifted out of `install.sh`), one maintainer script (the time-zone table) and their pytest
tests.

**Tech Stack:** SwiftUI + XCTest (`app/CicadaApp`), EventKit, ServiceManagement, bash 3.2 (macOS's `/bin/bash`),
Python 3 stdlib (the generator), pytest (`api/.venv`).

**Spec:** the round-4 brief and contracts (the orchestrator's session scratchpad `tracks/ROUND4.md` — **not
committed**, so everything this plan relies on is restated inline under *The contracts this track builds against*).
Decisions **D1–D7** bind; this track builds the app side of **C3–C7**. Backlog rows: **G143** and **G144** (new,
Task 7), **G142** (the backend track's row — not written here), **G76** (the in-app half of paste-prompt install),
**G88** (run like an installed app), **G105** (capture never depends on a model's choice), **G108/G117** (Home and
Welcome), **G118** (provenance), **G124** (no prices or tokens), **G126** (standing connections live in
Integrations), **G137** (Meadow), **G139** (Settings search), **G141** (Projects). Design target:
`docs/design/DESIGN_RULES.md` (Direction D); each commit cites the DR ids it applies.

**Owner's design note for this round:** "btw for good design checkout mobbin". Mobbin (mobbin.com) is a library of
real app screens and flows. Before building each new row (a login-item switch with an approval hint, a
background-service status row, a calendar Connect row, a copy-this-prompt box), look up how two or three well-made
macOS or iOS apps present the same flow there, if it is reachable from your session, and name the pattern you took
in the commit body. Where a reference and DESIGN_RULES disagree, DESIGN_RULES wins (DR-n ids bind; a departure needs
a dated §9 ruling in the same commit).

---

## The contracts this track builds against (restated from the round-4 brief)

- **D1** — model and reasoning effort are recorded per turn by the capture path that already reads the transcript
  (G105's one permitted read); an MCP write is joined to its turn at read. **An app with no capture hook (Claude
  desktop, ChatGPT, Cursor) says "model not shared by this app".**
- **D2** — calendars through EventKit, app-side: one standard prompt (`NSCalendarsFullAccessUsageDescription`,
  `requestFullAccessToEvents`), every account on the Mac, a rolling window, `EKEventStoreChanged` for updates, events
  POSTed to the backend. ICS URLs stay as they are.
- **D3** — background = the app stays resident: open at login via `SMAppService.mainApp` (status, register /
  unregister, `.requiresApproval` → `SMAppService.openSystemSettingsLoginItems()`); closing the window never quits
  (true today — `CicadaAppDelegate` does not implement `applicationShouldTerminateAfterLastWindowClosed`); the
  backend's LaunchAgent is offered from inside the app when missing, via an idempotent script extracted from
  `install.sh`'s plist step, run by the APP after the person's click and allowlisted like agent wiring;
  `BackendProcess` spawns `<venv python> -m uvicorn`. An ad-hoc-signed build may not persist a login item — say so
  when `status` never becomes `.enabled`, never pretend.
- **D4** — the Home painting follows the local clock (the owner overrides R-M2 / TODO ruling 10 **for the hero art
  only**): sunrise and sunset from the Mac's time zone (a bundled tz → coordinates table from IANA `zone1970.tab`,
  public domain) and the NOAA algorithm, no location permission; Settings → General → "Scene: Automatic · Always day
  · Always night" (`@AppStorage("cicada.heroScene")`, per viewer), independent of Appearance.
- **D5** — `GET /agents/setup?harness=<id>` returns a prompt the person pastes into Claude Code / Codex / Gemini CLI
  so the agent installs Cicada itself; Cursor gets its deep link; Claude desktop gets a config merge the app performs
  (backup first, merge never replace, unparseable → untouched) + "Quit and reopen Claude".
- **D6** — big projects never beachball: the timeline wire caps an item's participants (first 12 in order +
  `participantsTotal`), the `now` block too; the app draws at most 8 chips + "+N more" (expands that one row), and the
  Lately list is lazy.
- **D7** — portability and privacy rails unchanged: no owner name, no author-machine path, synthetic fixtures.
- **C3** — the claim wire gains `authorModel: str | null`, `authorEffort: str | null`; each evidence span of kind
  `assistant` gains `model?` / `effort?`.
- **C4** — `GET /entities/{id}/provenance` contributors of kind `harness` gain `models: [{model, effort?, beliefs}]`;
  `GET /episodes/{id}/text` gains `agent: {model?, effort?}` (the most recent agent turn's) and each assistant
  `turns[]` entry gains `model?` / `effort?`. Effort is one of `minimal|low|medium|high|xhigh|max`.
- **C5** — `GET /agents/setup?harness=<claude-code|codex|gemini-cli|cursor|claude-desktop>` →
  `{harness, kind: "prompt"|"deeplink"|"config-merge"|"remote", title, prompt?, argv?: [[str]], display?: [str],
  deeplink?, config?: {path, key, value}, note?}`; 404 for an unknown harness; engine-free; no ETag.
- **C6** — `POST /sources/calendar-local/sync`, body `{window: {from, to}, calendars: [{id, title, account?}],
  events: [{id, calendarId, title, start, end, allDay, location?, notes?, url?, attendees?: [str], organizer?: str,
  lastModified?}]}` (ISO-8601 with offsets; `id` = `calendarItemExternalIdentifier` + `|` + occurrence start for a
  recurring event) → `{created, updated, unchanged, tombstoned, bank}`; 409 into a demo bank
  (`refuse_capture_into_demo`); `GET /sources/channels` lists a `calendar-local` channel (mark: the installed Calendar
  app, never a committed Apple mark).
- **C7** — the app-side names later tracks build on: `SceneClock` (pure, `phase(at:timeZone:) -> SkyPhase`, sunrise /
  sunset), `HeroScenePreference` (automatic / day / night), `SceneStore` (observable current scene, re-evaluated at
  the next boundary and on `NSSystemTimeZoneDidChange` / wake), `LoginItemService` (SMAppService.mainApp with a
  testable seam), `BackendAgentService` (the LaunchAgent's status + install via the script), `CalendarReader`
  (EventKit behind a testable store seam). **Never change a contract's shape — flag it instead.**

---

## What the code actually does today (verified against `feat/r4-foundations-app` @ `ecb59c7`)

**Projects (D6).**
- `Models/Project.swift:199-244` — `ProjectItem` decodes `participants` in full; there is no `participantsTotal`.
- `Views/Projects/ProjectSentence.swift:62-98` — `StorySentence` draws **every** participant as a `ParticipantChip`
  inside one `SentenceFlowLayout`, which measures every subview (`:28-29`); each chip carries its own `@State hovering`
  and `.onHover` (`:108, :134`). A happening citing 622 papers is 622 measured, hover-tracked buttons in one row.
- `Views/Projects/ProjectStory.swift:25-78` — `tokens(_:participants:)` links each participant at its first
  occurrence and returns the ones the sentence never names as `extra`; `:88-95` `groups(_:today:)` buckets Lately.
- `Views/Projects/ProjectSections.swift:123-231` — `ProjectLatelySection` (doc comment `:123-125`, struct `:126-231`):
  a plain `VStack` of group `VStack`s of every row, so every row of a long story is built on open. It owns
  `@State conversations = ConversationsViewModel()` (`:141`) for Resume.
- `Views/Projects/ProjectSections.swift:77-80` — Now's thread row draws `StorySentence` with the matching item's full
  participant list, so a long-running happening in Now has the same cost.
- `Views/Projects/ProjectDetailColumn.swift:104-106` — `ProjectState.state(...)` runs **inside `body`**, on the main
  actor, on every evaluation; `:125` builds `ProjectSource.docIndex(t)` there too; `:112-126` the story is a
  `ScrollView { VStack { … } }` (not lazy); `:148-149` Lately's collapsed meta counts `t.items` in `body`.
  `:107` `BandLayout.make` also runs in `body`; it scales with the band's marks (one per item or milestone), never
  with participants, and it depends on the measured `bandWidth` — it stays where it is (R-FA2).
- `Services/APIClient.swift:995` — `actor APIClient`; `Services/ProjectsAPI.swift:11-20` decodes both Projects reads
  through `getConditional` inside that actor, so **decoding is already off the main actor**.
- `Views/Projects/ProjectsCache.swift:97-123` — `store`, `add`, `remove`, `confirm`; nothing counts revisions.

**Meadow hero (D4).**
- `Views/Meadow/HomeHeroBand.swift:40` and `Views/Meadow/WelcomeHero.swift:14` —
  `MeadowArt.image(for: .heroDay, mode: CicadaTheme.mode)`: the painting follows the **theme**.
- `Views/Meadow/MeadowArt.swift:34-60` — `fileName(for:mode:)` picks `-dark` for `.dark`; the `-dark` sibling is
  "painted as dusk or night" (`:8-10`).
- `Theme/CicadaTheme.swift:276-285` — `SkyPhase { day, dusk, night }`, `current` follows the theme.
- `Views/Home/HomeView.swift:43` calls `HomeHeroBand()` and `Views/Onboarding/WelcomeView.swift:64` calls
  `WelcomeHero()` with no arguments; `Tests/CicadaAppTests/HomeBandLayoutTests.swift:52` greps for `HomeHeroBand()`.
- `Theme/CicadaTheme.swift:33-111` — `ThemeStore`: `@Observable` singleton, `observeSystemAppearance()` registered
  once at app scope (`CicadaApp.swift:114`), never from `init` (a headless test never listens to the real system).
- **The table's source, measured:** `/usr/share/zoneinfo` on macOS ships `zone.tab` but **not** `zone1970.tab`, so the
  generator downloads IANA's tzdata. With `zone1970.tab` + `zone.tab` + every `Link` line (tzdata 2026d), **442 of the
  443** `TimeZone.knownTimeZoneIdentifiers` on this macOS resolve; the one miss is `GMT`. `zone1970.tab` alone misses
  zones it folds into another (e.g. `Europe/Oslo` is a row of `Europe/Berlin`). Re-measured by the plan critic by
  running this plan's own generator on tzdata 2026d: 549 zones, a 17.8 KB file, 442/443 known identifiers (miss:
  `GMT`); this plan's `SceneClock` then reproduces every expected time in `SceneClockTests` within 3 seconds.

**Settings → General (D3, D4).**
- `Views/Settings/SettingsGeneralView.swift:36-84` — one `SettingsGroupCard`: Appearance, Text size, Setup.
- `Views/Settings/SettingsRowID.swift:13-16` — the General ids; `Views/Settings/SettingsIndex.swift:71-83`
  (`staticIDs`), `:86-90` (General entries), `:230-254` (`SettingsLiveValue`); `Views/Settings/SettingsPanel.swift:46`
  (entries), `:58-65` (live inputs). `SettingsRowLintTests.swift:10-22` requires every static id to be rendered
  exactly once as `SettingsRow(.<id>,` or `.settingsRow(.<id>)` under `Views/Settings/`, `Views/Connect/` or
  `Views/Connections/`. `SettingsIndexTests.testEveryStaticRowIsIndexedExactlyOnce` compares `staticIDs` and
  `staticEntries` as SETS, but both lists are kept in page order (the index's tie-break), so a new id goes at the same
  place in both. No static entry is in `.integrations` today. `SettingsIndexTests.testRankingFixtures` pins the top hit
  for "zoom", "phone", "dark", "engines", "tele", "backup" — a new entry's keywords must not steal one.

**Background (D3).**
- `Services/BackendProcess.swift:66-73` — spawns `/usr/bin/env <root>/api/.venv/bin/uvicorn …`: the venv console
  script whose shebang breaks when the repo moves — exactly what `install.sh:44-47` forbids for the plist.
- `install.sh:325-386` — step 6 writes `com.cicada.backend.plist` inline (`write_plist`, `:336-366`; the dry-run
  branch `:367-372`), bootout-then-bootstraps it (`:373-375`) and waits for `/healthz` (`:376-385`), all inside a
  "backend already healthy → skip" guard (`if` at `:327`, `else` at `:329`, `fi` at `:386`). No other copy of the plist
  exists.
- `app/CicadaApp/login_item.sh` + `Makefile:80-84` — the only login-item path: an AppleScript System Events entry.
  Nothing in the app imports `ServiceManagement`.
- `Support/AgentConnect.swift:80-107` — `AgentConnectPolicy.isAllowed` pins argv to the app's own checkout;
  `:113-148` `AgentConnect.run` runs through `AgentProcessRunning` with `CICADA_CAPTURE=off` and the scrubbed keys;
  `LiveAgentProcessRunner` (`:15-48`) is `Process`, never a shell. The background agent reuses both seams.
  `AgentConnect.failureMessage`'s fallback is `Copy.intakeFailed` ("The import didn't finish.") — import words, so
  nothing new may reuse it for a non-import failure.
- `Support/FoundTurnOn.swift:80` — the one existing caller of `AgentConnect.run` passes
  `binaries: Set(wiring.agents.compactMap(\.binary))`: the binaries the backend RESOLVED, never a step's own argv[0].
- `Services/APIClient.swift:118-139, 1605` — `fetchHealth().memoryRoot` is the live backend's configured memory root.
- `Services/APIClient.swift:2171-2238` — `get` / `postData` pass a `URLSession` failure through as a `URLError`
  (connection refused is `URLError`, not `APIError.serverUnreachable`); only a non-2xx answer becomes
  `APIError.httpError(code, body)`.

**Calendar (D2).**
- Nothing in the app imports `EventKit`; `app/CicadaApp/bundle.sh:71-103` writes the Info.plist with no calendar
  usage key. `PlatformFloorTests.swift` is the precedent for a test that reads `bundle.sh`.
- `Services/LocalSources/LocalSourceWatcher.swift:60-170` — the app-reads / backend-parses pattern: a protocol API
  seam (`LocalSourcesAPI`), debounce + floor, `start(store:)` from `CicadaApp.swift:225`, reload on a bank switch
  (`CicadaApp.swift:187-189`).
- `Models/IntegrationCategory.swift:43-65` — `of(channelId:)` sends an unknown id to `.filesAndImports`;
  `Views/Settings/IntegrationsView.swift:118-127` (`extraRowCount`), `:171-176` (a channel with its own row is skipped
  by id — Wispr Flow's precedent), `Views/Settings/LocalSourceRows.swift:450-493` (`WisprFlowRow`, the model for a
  row the app owns).
- `Views/Capture/OriginIconography.swift:251-262` — `appBundleId(for:)`; no calendar entry. `symbol(for:)` (`:118`)
  maps `"calendar"` to the `calendar` glyph and falls back to `tray` for an unknown id;
  `ConnectedChannelRow.origin(forChannel:)` (`Views/Capture/ConnectedChannelRow.swift:271`) returns an unlisted
  channel id as its own origin, so `calendar-local` reaches these switches as `"calendar-local"`.
- `api/services/demo_guard.py:43-45` — the 409 detail (`REFUSAL`) is written for the person;
  `ProjectWriteFailure.detail(_:)` (`Sync/ProjectMutations.swift:127-133`) parses FastAPI's `{"detail": "…"}` —
  reuse it, never a second parser. `IntegrationsViewTests.testEveryChannelIdHasACategory` (`:23-37`) lists every
  channel id with its category; `IntegrationCategory`'s doc says the switch and that list change together.

**Who wrote what (C3, C4).**
- `Models/Claim.swift:118-172` — no `authorModel` / `authorEffort`. `Models/Evidence.swift:49-83` — `Evidence` has no
  `model` / `effort`; `:149-188` `EpisodeTurn` and `:222-285` `EpisodeText` have no model fields.
  `Models/Provenance.swift:72-102` — `ProvenanceContributor` has no `models`.
- `Views/Provenance/EvidenceChipModel.swift:135-160` — the chip reads "<agent> replied · Sep 3";
  `Views/Provenance/EvidenceChip.swift:195-200` — the hover's header line; `Views/Provenance/ReaderModel.swift:17-21`
  says "Never the MODEL: conversation `model` is reserved-null" (D1 lifts it), `:62-65` the turn speaker, `:396-410`
  the Reader's meta line; `Views/Provenance/WhereThisCameFromSection.swift:127-151` the contributor chip;
  `Views/Provenance/ProvenanceSummary.swift:87-93` its count line; `Models/EntityPresentation.swift:242-250`
  `BeliefWords.help` — "<observer> · [<context> ·] <author> at <confidence>" through `Copy.Graph.writtenBy(_:confidence:)`
  (`"\(author) at 0.85"`; there is no "Written by" prefix), pinned by `EntityContentTests.testABeliefsHelpAndAge`.
  `Claim`, `Evidence`, `EpisodeTurn`, `EpisodeText` and `ProvenanceContributor` decode with `try c.decodeIfPresent`,
  which THROWS on a mistyped value — the new keys use `try?` instead (see Task 5).

**Agents (D5).**
- `Views/Connect/ConnectView.swift:46-192` — `AgentSetupCatalog.all(home:memoryRoot:)` builds every harness's commands
  from the app's own checkout and the live memory root; `:66-70` the Cursor deeplink; `:142-155` Claude desktop is a
  "merge this JSON by hand" step. `:345-363` the deeplink is a brand-tinted capsule (a tinted pill, DR-44).
  `Views/Settings/SettingsPanel.swift:188` hosts `ConnectView()` as Settings → Agents.
- `Models/AgentWiring.swift` + `Services/APIClient.swift:2577-2579` — `GET /agents/wiring` already decodes;
  `FoundRow`'s "Turn on" is the only UI that runs `AgentConnect.run` today.

**Baselines on this base:** backend **3775 passed, 1 skipped**; Swift **2003 tests, 0 failures**; graph JS **8/8**.

**What the plan critic compiled and ran (2026-09-24, scratch copies only — nothing in this worktree was built or
edited but this file).** Task 1's wire, budget, sentence, `TextButton(inline:)`, `ProjectDerived`, the cache revision
and their tests, applied to a copy of `app/CicadaApp`: builds, 48 Projects tests and every `*Lint*` suite pass (Steps
9–10's column rewrite was not applied, so `testTheColumnDerivesOffMainAndIsLazy` is unproven). Task 2's generator + its
pytest (3 passed) on real tzdata 2026d; `SceneClock` / `SceneStore` / `HeroScenePreference` + `SceneClockTests` minus
the two cases that need `MeadowArt` (10 passed). Task 3's script + pytest with `install.sh` edited per Step 3 (7
passed, `bash -n` clean); `LoginItemService` / `BackendAgentService` / `spawnCommand` + `BackgroundServicesTests` (10
passed). Task 4's models + reader + `CalendarRowText` + `CalendarReaderTests` minus the bundle-path and Settings-index
cases (10 passed). Task 5's `ModelNames` against the Step 1 table. Task 6's `ClaudeDesktopConfig`, `AgentSetupPrompt`,
`AgentQuickSetup.actions` + `AgentQuickSetupTests` (8 passed; the symlink case fails against a plain write). Prose
steps (views, EventKit, Task 5's display edits, docs) are unproven — build them against the tests named.

---

## Global Constraints

- Work ONLY in `<worktree>` — the `r4-app` worktree the orchestrator named (branch `feat/r4-foundations-app`, based on
  `dev` @ `ecb59c7`); its absolute path is in the task brief, not here (portability rule). Every shell command is
  `cd <worktree> && <cmd>` with the ABSOLUTE path (zoxide hijacks a relative `cd`; ignore its stderr warning). Never
  an unquoted `--include=*.ext` (zsh globs it).
- NEVER read `<repo>/memory` (any bank), `~/.cicada`, `~/Library/Safari`, `~/Library/LaunchAgents` of the real user,
  `~/Library/Application Support/Claude` or `~/.claude/projects`. Tests use temp directories and fakes only; fixtures
  are synthetic (`alpha-project`, `bob-example`, `paper-example-N`, `example.com`).
- Python: `cd <worktree> && api/.venv/bin/python -m pytest <files> -q -p no:cacheprovider`; the full `api/tests` suite
  must report 0 failures (3775 passed, 1 skipped on this base). `test_agent_provenance.py::test_a_decay_only_change_
  lands_in_its_own_cicada_authored_commit` is order-dependent — if it is the ONLY red, re-run it alone.
- Swift: `cd <worktree>/app/CicadaApp && swift build 2>&1 | tail -5` must succeed and `swift test 2>&1 | tail -20` must
  report 0 failures (2003 on this base). `SleepViewModelTests` poll tests and search-latency tests can flake under
  load — re-run them alone before calling them yours. Graph JS: `cd <worktree> && node --test
  app/CicadaApp/Tests/graph/*.test.js` (8/8). SourceKit diagnostics naming OTHER worktrees are noise.
- NEVER run `make dev`, `make install-app`, `make login-item`, `swift run`, `./install.sh`, the new
  `scripts/install-backend-agent.sh` against the real `$HOME`, `launchctl` (except through a test's fake on PATH), or
  launch / kill the Cicada app or the launchd backend. The orchestrator installs and live-checks at the end.
- Never `git add -A`; stage named files only. Never commit `memory/`, `logs/`, `.claude/settings.json`, `api/.venv`,
  or `*-report.md`. No push, no new branches or worktrees, no subagents. Ignore Devin/PR comments. End every commit
  message with the attribution lines your session's system reminder gives.
- **Rails:** no LLM at capture time (the calendar POST is staged by the backend's `episode_staging`); secrets only in
  `~/.cicada/secrets.env` (this track stores none); the app reads `~/Library`, the backend parses bytes (EventKit is
  the app's read); an app that runs a command does so only after the person's click, with the exact command shown
  first, `CICADA_CAPTURE=off`, argv pinned to its own checkout (spec decision 14, D-1); no owner name or
  author-machine path in code, tests, docs, plans or commits.
- **App copy** is plain and friendly for a non-technical person. **No prices, no token counts** anywhere (the
  2026-09-03 ruling, DR-59; DR-59's `PriceLintTests` is listed in DESIGN_RULES but NOT written yet — the live check is
  `EngineQuickMenuTests.testNoPriceOrTokenAnywhereInTheMenu`, so keep "$", "token", "price" and "cost" out of every new
  `Copy` string by hand). Every number through `UsageFormat.count` (DR-21,
  `CountLiteralLintTests`). Wherever a service is named, its real mark through `OriginMark` / `LogoImage` (DR-52).
- **Tokens, not literals:** fonts through `CicadaTheme.font(size:weight:)` or a named token (`FontLiteralLintTests`);
  dimensions through `CicadaTheme.scaled(_:)`; durations only in `CicadaMotion` / `SleepMotion` (DR-61); no bare
  `RoundedRectangle(cornerRadius:` outside `Theme/` (DR-12); keyboard actions never animate (DR-60, `Instant.run`).
- **Decode tolerance:** every new wire field is optional-with-default and a test decodes a payload that omits it.
- Docstrings explain **why**, citing the G-row, decision (D1–D7), contract (C3–C7) or ruling (R-FA*) that motivated
  the rule. Match the density of the files touched.
- Line numbers above are from `ecb59c7` and drift as tasks land — read the cited code before editing.

---

## Rulings (binding)

The round-4 decisions D1–D7 and contracts C3–C7 hold as written. Everything below is a choice this plan takes where
the brief left one, with the reason, so no task re-opens it.

- **R-FA1 — the chip budget counts pages in reading order, and never the owner.** At most **8** page chips per
  sentence (`ProjectStory.chipBudget`): inline links first (where the sentence names them), then the trailing chips.
  The owner's "you" chip is the sentence's own word and opens nothing, so it never counts. An inline link past the 8th
  reads as the words it is (the sentence stays whole). "+N more" counts every participant not drawn as a chip **plus**
  the ones the wire held back (`participantsTotal − participants.count`). Expanded, the row shows every chip the wire
  sent, then — when the server held some back — a meta line "610 more not listed here" (not a button: there is
  nothing more to fetch; Around this project lists pages by group), and a "Show fewer" `TextButton`. The expanded flag
  is the row's own `@State`, so it opens that row only. The one chip line gets `TextButton`'s new `inline` variant (22
  pt, the chip's height), because a 32 pt button would stretch the sentence's line (DR-40 keeps the kind; only the
  height matches the row it sits in).
- **R-FA2 — decoding is already off the main actor; derivation moves off it too.** `ProjectsAPI` decodes inside
  `actor APIClient` (verified above) — no change. `ProjectState.state`, Lately's grouping, the happenings count and
  the evidence doc index move into `ProjectDerived.build`, run through `Task.detached(priority: .userInitiated)` and
  keyed by `(projectId, today, cache revision)`. `ProjectState` itself does not scale with participants (it reads
  threads, milestones and moment days), but this plan's rule is that nothing proportional to a story's length or its
  participants is derived in `body`. The one exception kept on purpose is `BandLayout.make`: it depends on the band's
  measured width (a `@State` that changes with the window), scales with the band's marks and never with
  participants, and moving it would re-derive on every resize. The column keeps the last derived value for the same
  project while a new one is built (never blank, the Store's last-known-good rule), and shows the reading skeleton
  only before the first one.
- **R-FA3 — Lately is lazy by being flat.** The story's scroll content becomes one `LazyVStack(alignment: .leading,
  spacing: 0)` whose children include **every Lately group label and row directly** (`ProjectStory.latelyEntries`),
  not a `VStack` nested inside it, so SwiftUI builds only the rows on screen. Spacing that the old nested `VStack`s
  gave moves to each entry's top padding (same values). The `ForEach` identity of a row **is** its scroll id
  (`ProjectKey.item(id).id`), the standard lazy `ScrollViewReader.scrollTo` pattern, so a band pick still lands.
- **R-FA4 — three phases, two paintings.** `SceneClock` answers `.day` from sunrise to sunset (the sun's upper limb
  at the horizon, NOAA's 90.833° zenith), `.dusk` in civil twilight (down to 6° below) at either end of the day, and
  `.night` otherwise. The hero paints `hero-day` for `.day` and its `-dark` sibling for `.dusk` and `.night` — that
  sibling is "painted as dusk or night" (`MeadowArt.swift:8-10`). `.dusk` is kept distinct so the later animated
  band has a transition to draw. Every other painting, the empty states and the Sleep room keep following the theme.
- **R-FA5 — coordinates from tzdb, never from the person.** `scripts/gen-tz-coordinates.py` builds
  `Resources/scene/tz-coordinates.json` from `zone1970.tab`, then `zone.tab`, then every `Link` line (the three
  together resolve every macOS identifier but `GMT`, measured above), rounded to 2 decimals (~1 km; far under a
  minute of sun). tzdb's tables are public domain; the JSON records `source` and `version` (a JSON file cannot hold
  a comment). A zone with no coordinates (`GMT`, a raw offset) keeps a plain clock: day 07:00–19:00 local, dusk 30
  minutes either side (`SunTimes.estimated == true`). CoreLocation is never imported. **The sun is computed for the
  UTC day whose solar noon falls on the LOCAL day asked about**, not simply the UTC day with the same date: a zone far
  from its meridian (Pacific/Kiritimati is UTC+14 at 157° W) otherwise gets the NEXT day's sunrise and reads night at
  local noon — measured by the plan critic on this macOS with tzdata 2026d: 8 zones (Apia, Chatham, Enderbury,
  Fakaofo, Kanton, Kiritimati, Tongatapu, Wallis) were wrong at 13:00 on the equinox without it, 0 with it.
- **R-FA6 — the store holds the clock; the preference stays in defaults.** `SceneStore.phase` is the clock's answer
  only. The person's choice lives in `@AppStorage("cicada.heroScene")`, read by the hero views and the Settings row,
  and `HeroScenePreference.scene(clock:)` resolves the two — so a Settings flip repaints with no store method call.
  The store re-evaluates at the next boundary **or within the hour, whichever comes first** (a clock change or a
  missed notification heals itself), on `NSSystemTimeZoneDidChange`, and on `NSWorkspace.didWakeNotification`. It
  starts once from `CicadaApp.init`, like `ThemeStore.observeSystemAppearance`, never from its own `init`.
- **R-FA7 — login item: the person's intent is remembered so the state can be honest.** `LoginItemService` wraps
  `SMAppService.mainApp` behind `LoginItemControlling`. It persists what the person asked for
  (`cicada.loginItem.requested`); when that says on and macOS says not registered / not found, the row says macOS
  did not keep it (and that an unsigned copy may need adding by hand) instead of showing a plain "off". A switch-off
  the person made in System Settings while Cicada ran (`.on` → `.notRegistered` between two refreshes) clears the
  intent, and the reverse holds too: macOS answering `.enabled` while the intent says off (allowed from System
  Settings) records the intent as on, so the switch never reads off beside an "on" sentence. The switch shows the
  intent (`requested`), the sentence under it shows macOS's answer. `login_item.sh` / `make login-item` stay as the
  developer path; CLAUDE.md names the app's switch as the supported one. Cicada opens its window at login exactly as a
  manual launch does (open question 1).
- **R-FA8 — one plist, one script; the app hands launchd the port.** `scripts/install-backend-agent.sh` always writes
  the plist and boots the agent out, then in (idempotent; three tries at bootstrap, a second apart — launchd can
  refuse a bootstrap that races its own bootout). `install.sh` keeps its "a backend already answers /healthz → skip"
  guard **around** the call. The app runs exactly `["/bin/bash", "<installRoot>/scripts/install-backend-agent.sh"]`
  (`BackendAgentPolicy.isAllowed`, pinned to `BackendProcess.installRoot()`), with `CICADA_REPO`, `CICADA_MEMORY_PATH`
  = the live backend's `memoryRoot` (else `<installRoot>/memory`, what `BackendProcess` serves), `CICADA_CAPTURE=off`,
  `AgentConnect.scrubbedKeys` removed and `/usr/bin:/bin:/usr/sbin:/sbin` as PATH. On success it stops **its own**
  child uvicorn (only one it spawned — never a developer's), so the agent's KeepAlive can bind :8000. Known and
  accepted: the agent's first uvicorn starts while that child still holds :8000, exits, and launchd's KeepAlive
  retries it after its default 10 s throttle — so the backend is away for up to ~10 s after Install (the SyncEngine's
  reconnect covers it; nothing is lost, a capture POST in that gap fails as it would during any restart). A failure
  message is the script's own words (exit 3, 4) or its first stderr line, else `Copy.backgroundInstallFailed` — never
  `AgentConnect`'s fallback, which is the import sentence.
- **R-FA9 — the status probe is read-only.** `launchctl print gui/<uid>/com.cicada.backend` through the same
  `AgentProcessRunning` seam: exit 0 → running; any other exit with the plist present → installed but stopped;
  without the plist → missing; 124 (timeout) or 127 (could not start) → unknown. Plus a `FileManager` existence check
  of `~/Library/LaunchAgents/com.cicada.backend.plist` — the app reads `~/Library`, the backend never does. Exit 0
  means launchd holds the agent (loaded, KeepAlive on), not that uvicorn answered this second; the row's "On" says
  exactly that — memory keeps working in the background — and the SyncEngine's own connection state is the live
  signal. The runner discards stdout, so the probe never parses `launchctl print`'s text.
- **R-FA10 — `BackendProcess` runs install.sh's command.** `<root>/api/.venv/bin/python -m uvicorn api.main:app --host
  127.0.0.1 --port 8000`, the interpreter as `executableURL` (no `/usr/bin/env`), from one pure
  `BackendProcess.spawnCommand(installRoot:)`.
- **R-FA11 — the calendar is read only after Connect.** `cicada.calendar.enabled` (per Mac, the
  `cicada.browserWatch.enabled.<channel>` precedent) is false until the person clicks Connect **and** macOS grants full
  access. Disconnect sets it false and stops every trigger; nothing is deleted and no DELETE is sent — saved events
  stay in memory. Window: 30 days back … 60 days ahead of the sync. Triggers: launch, `EKEventStoreChanged` (debounced
  10 s), every 3 hours while the app runs, a bank switch, Sync now. Notes are capped app-side at 10,000 characters to
  bound the payload; the backend's scrub-then-2,000 cap is the rule that matters. An attendee or organizer is sent as
  their display name, else the email without `mailto:`. **An empty read is never posted:** C6 tombstones every saved
  event the window no longer holds, so a snapshot with no calendars at all (EventKit not ready yet, or access revoked
  mid-read) would mark the whole window deleted; the sync re-checks access first and skips a calendar-less snapshot
  with a "not ready" line. A trigger that lands while a sync is in flight runs once more after it (never dropped, never
  two in flight), and a sync that finishes after Disconnect leaves the row off.
- **R-FA12 — a refusal in the server's words.** A 409 shows `detail` through `ProjectWriteFailure.detail` (the demo
  refusal is written for the person); a 404/405 (a backend without C6) says "This version of Cicada's background
  service can't read calendars yet — update Cicada."; unreachable — a `URLError` from `URLSession` (connection refused,
  timed out) or `APIError.serverUnreachable` — says Cicada's background service isn't answering.
- **R-FA13 — the Calendar row is the app's.** One static Settings id, `.calendarApp`, on `CalendarRow` in the "Feeds &
  calendars" section. The backend's `calendar-local` channel (C6) is rendered **by that row** (its `lastError`, which
  wins over a stale "Synced" line), never also as an `IntegrationChannelRow` or a second search entry. Title "Calendar on this Mac" so it never
  reads as the ICS row, whose channel id is `calendar`.
- **R-FA14 — the model rides the agent's label.** One pure `ModelNames`: `claude-opus-5-5` → "Opus 5.5",
  `claude-sonnet-5` → "Sonnet 5", `gpt-5.5-codex` → "GPT-5.5 Codex", an unknown id as-is; effort in words ("high
  effort", `xhigh` → "extra-high effort"). An assistant chip whose span carries a model reads "Claude Code · Opus 5.5 ·
  high effort · Sep 3" — the agent line replaces "<agent> replied" (DR-57 amendment, a §9 ruling in Task 5); without a
  model it is byte-for-byte today's. The hover header, the Reader's meta line and its turn labels say the same line; the
  author part of a belief's `.help` becomes "Claude Code · Opus 5.5 · high effort at 0.85" (`BeliefWords.help` has no
  "Written by" — it is "<observer> · <author> at <confidence>"). Only `claude-code` and `codex` capture
  (their Stop hook reads the transcript); any other harness with no model says "model not shared by this app"; a
  capturing harness with no model (a write from before D1) adds nothing — never a guess.
- **R-FA15 — agents: the app opens and writes only what it computed itself.** Copy setup prompt shows
  `GET /agents/setup`'s `prompt` verbatim in a read-only box, then copies it (claude-code, codex, gemini-cli); when
  the endpoint 404s (today's backend) the section is simply absent. "Connect for me" is `AgentConnect.run` over
  `/agents/wiring`'s steps (the Found row's Turn on), shown with each step's exact `display` first, with
  `binaries: Set(wiring.agents.compactMap(\.binary))` — the binaries the backend resolved, exactly
  `FoundTurnOn.swift:80`'s argument; never the steps' own argv[0]s, which would let any `…/claude` path through the
  policy's binary check. After it runs, the wiring is fetched again so a now-wired agent drops the action. Open in Cursor
  opens `AgentSetupCatalog`'s own deeplink, never a URL off the wire (`AgentConnectPolicy`'s precedent). Set up Claude
  merges `ClaudeDesktopConfig.server(...)` — built from the same `python` / `mcp/server.py` / memory root as the
  catalog — into `ClaudeDesktopConfig.configURL()`; the wire's `config` is never trusted for a path or a value. A
  missing Claude folder → "Open Claude once, then try again" (nothing created); an identical entry → no write and no
  backup; key order may change (`JSONSerialization`), and the backup keeps the original bytes. A config kept as a
  symlink (a dotfiles repo) is written through the link (`resolvingSymlinksInPath()`), never replaced by a plain file.
- **R-FA16 — TODO.md is the orchestrator's.** This branch does not edit `docs/goals/TODO.md`: the round's handoff is
  written once at round close (round 3's #99 precedent), which avoids a three-way conflict with the backend track.
  G143 and G144 go straight after G141; the backend track adds G142 at the same spot — a trivial ordering conflict the
  orchestrator resolves as G142, G143, G144.

---

## File map

| Path | Task | Change |
|---|---|---|
| `app/CicadaApp/Sources/CicadaApp/Models/Project.swift` | 1 | `ProjectItem.participantsTotal` |
| `…/Views/Projects/ProjectStory.swift` | 1 | `chipBudget`, `StoryChips`, `chips(…)`, `LatelyEntry`, `latelyEntries`, `Group: Sendable` |
| `…/Views/Projects/ProjectSentence.swift` | 1 | `StorySentence(total:)` + per-row expand |
| `…/Views/Projects/ProjectSections.swift` | 1 | `ProjectLatelySection` → `ProjectLatelyRow` + `ProjectLatelyLabel` + `ProjectLatelyFoot`; Now passes `total:` |
| `…/Views/Projects/ProjectDerived.swift` (new) | 1 | off-main derivation |
| `…/Views/Projects/ProjectDetailColumn.swift` | 1 | `.task(id: deriveKey)`, one `LazyVStack` |
| `…/Views/Projects/ProjectsCache.swift` | 1 | `revision(_:)` |
| `…/Views/Common/TextButton.swift` | 1 | `inline` variant |
| `…/Views/Provenance/EvidenceChipModel.swift` | 1 | `EvidenceDocIndex: Sendable` |
| `…/Theme/Copy+Projects.swift` | 1 | five strings (`moreParticipants`, `moreParticipantsHelp`, `notListed`, `notListedHelp`, `fewerParticipants`) |
| `app/CicadaApp/Tests/CicadaAppTests/ProjectBigStoryTests.swift` (new) | 1 | |
| `scripts/gen-tz-coordinates.py` (new) | 2 | maintainer generator |
| `…/Resources/scene/tz-coordinates.json` (new, generated) | 2 | |
| `…/Theme/SceneClock.swift` (new) | 2 | `GeoPoint`, `TimeZoneCoordinates`, `SceneClock`, `HeroScenePreference` |
| `…/Theme/SceneStore.swift` (new) | 2 | |
| `…/Views/Meadow/MeadowArt.swift`, `HomeHeroBand.swift`, `WelcomeHero.swift` | 2 | hero by scene |
| `…/Views/Settings/SettingsGeneralView.swift`, `SettingsRowID.swift`, `SettingsIndex.swift`, `SettingsPanel.swift` | 2, 3 | Scene; login; background rows |
| `…/Theme/Copy+Settings.swift` | 2, 3, 4, 6 | strings |
| `…/CicadaApp.swift` | 2, 3, 4 | start the store; hold + inject the services |
| `docs/design/DESIGN_RULES.md` | 2, 5, 6 | three §9 rulings |
| `api/tests/test_gen_tz_coordinates.py` (new) | 2 | |
| `app/CicadaApp/Tests/CicadaAppTests/SceneClockTests.swift` (new) | 2 | |
| `scripts/install-backend-agent.sh` (new) | 3 | the plist step |
| `install.sh` | 3 | step 6 calls the script |
| `api/tests/test_install_backend_agent.py` (new) | 3 | bash-level test |
| `…/Services/BackendProcess.swift` | 3 | `spawnCommand`, `stopSpawnedChild` |
| `…/Services/LoginItemService.swift` (new) | 3 | |
| `…/Services/BackendAgentService.swift` (new) | 3 | |
| `app/CicadaApp/Tests/CicadaAppTests/BackgroundServicesTests.swift` (new) | 3 | |
| `…/Services/Calendar/CalendarReader.swift`, `CalendarModels.swift`, `EventKitCalendarStore.swift` (new) | 4 | |
| `…/Services/APIClient.swift` | 4, 6 | `syncLocalCalendar`, `fetchAgentSetup` |
| `app/CicadaApp/bundle.sh` | 4 | two usage keys |
| `…/Models/IntegrationCategory.swift`, `…/Views/Settings/IntegrationsView.swift`, `…/Views/Settings/CalendarRow.swift` (new) | 4 | |
| `…/Views/Capture/OriginIconography.swift` | 4 | `calendar-local` label, symbol, bundle id, `allKnownOrigins` |
| `app/CicadaApp/Tests/CicadaAppTests/CalendarReaderTests.swift` (new) | 4 | |
| `…/Models/ModelNames.swift` (new) | 5 | |
| `…/Models/Claim.swift`, `Evidence.swift`, `Provenance.swift` | 5 | decode C3/C4 |
| `…/Views/Provenance/EvidenceChipModel.swift`, `EvidenceChip.swift`, `ReaderModel.swift`, `ProvenanceSummary.swift`, `WhereThisCameFromSection.swift`; `…/Models/EntityPresentation.swift`; `…/Theme/Copy+Provenance.swift` | 5 | display |
| `app/CicadaApp/Tests/CicadaAppTests/ModelNamesTests.swift` (new) | 5 | |
| `…/Models/AgentSetupPrompt.swift`, `…/Support/ClaudeDesktopConfig.swift` (new) | 6 | |
| `…/Views/Connect/ConnectView.swift`, `…/Views/Connect/AgentQuickSetup.swift` (new) | 6 | |
| `app/CicadaApp/Tests/CicadaAppTests/AgentQuickSetupTests.swift` (new) | 6 | |
| `CLAUDE.md`, `docs/goals/memory-evolution.md` | 7 | docs |
| Existing test files extended (never replaced) | 1–5 | `ProjectsCacheTests.swift` (1), `SettingsIndexTests.swift` (2, 3, 4), `IntegrationsViewTests.swift` (4), `EvidenceChipLabelTests.swift`, `ProvenanceSummaryTests.swift`, `EntityContentTests.swift` (5) |

`…` = `app/CicadaApp/Sources/CicadaApp`.

Order: Task 1 → 2 → 3 → 4 → 5 → 6 → 7. Tasks 2 and 3 both edit Settings → General and the Settings index, and Tasks 2,
3 and 4 all edit `CicadaApp.swift`, so they run in that order; every task leaves the branch building and green.

---

### Task 1: A big project opens instantly (D6)

**Files:** see the file map rows marked 1.

**Interfaces:**
- Produces `ProjectItem.participantsTotal: Int?`; `ProjectStory.chipBudget`; `StoryChips { tokens, extra, more,
  notSent, canExpand }`; `ProjectStory.chips(_:participants:total:expanded:)`; `ProjectStory.LatelyEntry` +
  `latelyEntries(_:)`; `ProjectDerived { key, state, groups, happenings, docIndex }` with `build(_:key:)` and
  `make(_:key:) async`; `ProjectsCache.revision(_:)`; `TextButton(inline:)`.
- Consumes `ProjectStory.tokens`, `ProjectStory.groups`, `ProjectState.state`, `ProjectSource.docIndex`,
  `ProjectsCache.display`.

- [ ] **Step 1: Failing tests** — create `app/CicadaApp/Tests/CicadaAppTests/ProjectBigStoryTests.swift`. Do **not**
  edit `Tests/fixtures/projects-demo.json` (the backend track owns it this round); build the big item in the test.

```swift
import XCTest
@testable import CicadaApp

/// Round-4 D6 — a happening that cites hundreds of pages draws at most eight chips and a "+N more" that opens that
/// row only; the story's derivation runs off the main actor; the Lately list is lazy. Synthetic participants only.
@MainActor
final class ProjectBigStoryTests: XCTestCase {
    private func participants(_ n: Int, from start: Int = 0) -> [[String: Any]] {
        (start..<(start + n)).map { ["id": "paper-example-\($0)", "name": "Paper example \($0)", "type": "media"] }
    }

    private func item(text: String = "Read the alpha-project reading list", sent: [[String: Any]],
                      total: Int? = nil) throws -> ProjectItem {
        var object: [String: Any] = ["kind": "happening", "id": "clm_big", "day": "2026-09-22", "text": text,
                                     "participants": sent]
        if let total { object["participantsTotal"] = total }
        return try JSONDecoder().decode(ProjectItem.self, from: JSONSerialization.data(withJSONObject: object))
    }

    func testTheTotalDecodesLenientlyAndIsOptional() throws {
        XCTAssertNil(try item(sent: participants(2)).participantsTotal, "today's backend sends no total")
        XCTAssertEqual(try item(sent: participants(12), total: 622).participantsTotal, 622)
        let mistyped = try JSONDecoder().decode(ProjectItem.self, from: Data(#"""
            {"kind":"happening","id":"x","text":"t","participantsTotal":"many"}
            """#.utf8))
        XCTAssertNil(mistyped.participantsTotal, "a mistyped total is dropped, never a failed payload")
    }

    func testSixHundredParticipantsDrawEightChipsAndFoldTheRest() throws {
        let big = try item(sent: participants(600))
        let chips = ProjectStory.chips(big.text, participants: big.participants, total: big.participantsTotal,
                                       expanded: false)
        XCTAssertEqual(chips.extra.count, ProjectStory.chipBudget)
        XCTAssertEqual(ProjectStory.chipBudget, 8)
        XCTAssertEqual(chips.more, 592)
        XCTAssertEqual(chips.notSent, 0)
        XCTAssertTrue(chips.canExpand)
    }

    func testExpandingOneRowShowsEveryChipTheWireSent() throws {
        let big = try item(sent: participants(600))
        let open = ProjectStory.chips(big.text, participants: big.participants, total: nil, expanded: true)
        XCTAssertEqual(open.extra.count, 600)
        XCTAssertEqual(open.more, 0)
        XCTAssertFalse(open.canExpand)
    }

    /// D6's cap: the server sends the first 12 and says how many there were.
    func testTheParticipantsTheServerHeldBackCountTowardMoreButCannotExpand() throws {
        let capped = try item(sent: participants(12), total: 622)
        let closed = ProjectStory.chips(capped.text, participants: capped.participants, total: 622, expanded: false)
        XCTAssertEqual(closed.extra.count, 8)
        XCTAssertEqual(closed.more, 614)
        XCTAssertEqual(closed.notSent, 610)
        XCTAssertTrue(closed.canExpand)
        let open = ProjectStory.chips(capped.text, participants: capped.participants, total: 622, expanded: true)
        XCTAssertEqual(open.extra.count, 12)
        XCTAssertEqual(open.more, 610, "expanded, only the held-back ones stay unlisted")
        XCTAssertFalse(open.canExpand)
    }

    /// R-FA1 — inline links count first, past the budget they read as words, and the owner never counts.
    func testInlineLinksCountFirstAndTheOwnerNever() throws {
        let names = (0..<10).map { "Paper example \($0)" }
        let text = "Bob read " + names.joined(separator: ", ")
        var sent = participants(10)
        sent.insert(["id": "bob-example", "name": "Bob Example", "surface": "Bob", "isOwner": true, "type": "person"],
                    at: 0)
        let it = try item(text: text, sent: sent)
        let chips = ProjectStory.chips(it.text, participants: it.participants, total: nil, expanded: false)
        XCTAssertEqual(chips.tokens.filter { $0.kind == .page }.count, 8)
        XCTAssertEqual(chips.tokens.filter { $0.kind == .owner }.count, 1)
        XCTAssertTrue(chips.tokens.contains { $0.kind == .word && $0.text.hasPrefix("Paper example 8") })
        XCTAssertTrue(chips.extra.isEmpty)
        XCTAssertEqual(chips.more, 2)
    }

    /// R-FA2 — the detached build gives exactly what the synchronous one does, over a big synthetic story.
    func testTheOffMainDerivationEqualsTheSynchronousOne() async throws {
        var t = try ProjectFixtures.timeline("rover-arm-project")
        t.items.append(try item(sent: participants(600)))
        let key = ProjectDerived.Key(projectId: t.project.id, today: ProjectFixtures.today, revision: 1)
        let detached = await ProjectDerived.make(t, key: key)
        XCTAssertEqual(detached, ProjectDerived.build(t, key: key))
        XCTAssertEqual(detached.state, ProjectState.state(ProjectState.Input(t), today: ProjectFixtures.today))
        XCTAssertEqual(detached.happenings, t.items.filter { $0.kind != "created" }.count)
    }

    /// R-FA3 — a flat list of entries: each group label, then its rows; the first label sits closer to its header.
    func testLatelyIsOneFlatListOfLabelsAndRows() throws {
        let t = try ProjectFixtures.timeline("rover-arm-project")
        let groups = ProjectStory.groups(t.items, today: ProjectFixtures.today)
        let entries = ProjectStory.latelyEntries(groups)
        XCTAssertEqual(entries.count, groups.count + groups.map(\.items.count).reduce(0, +))
        guard case .label(_, let first)? = entries.first else { return XCTFail("a label leads") }
        XCTAssertTrue(first)
        XCTAssertEqual(Set(entries.map(\.id)).count, entries.count, "ids are unique — they are scroll ids")
        let firstItem = try XCTUnwrap(groups.first?.items.first)
        XCTAssertTrue(entries.contains { $0.id == ProjectKey.item(firstItem.id).id })
    }

    /// R-FA2 / R-FA3 as source checks: the column no longer derives in `body`, and its story is lazy.
    func testTheColumnDerivesOffMainAndIsLazy() throws {
        let files = try ThemeTokenTests.swiftSources()
        func text(_ suffix: String) throws -> String {
            try String(contentsOf: XCTUnwrap(files.first { $0.path.hasSuffix(suffix) }), encoding: .utf8)
        }
        let column = try text("Views/Projects/ProjectDetailColumn.swift")
        XCTAssertFalse(column.contains("ProjectState.state("), "derivation lives in ProjectDerived (R-FA2)")
        XCTAssertTrue(column.contains("LazyVStack"), "the story is lazy (R-FA3)")
        XCTAssertFalse(try text("Views/Projects/ProjectSections.swift").contains("struct ProjectLatelySection"))
    }
}
```

  Add to `ProjectsCacheTests` (same file's fakes): a fresh answer bumps `revision(id)`; a 304 does not; `add` and
  `remove(overlayId:)` bump it; after `reset()` a fresh answer's revision never equals one handed out before it (a
  global counter, R-FA2).

```swift
    func testTheRevisionMovesOnlyWhenWhatTheColumnShowsCanChange() async throws {
        let t = try ProjectFixtures.timeline("rover-arm-project")
        let api = FakeProjectsAPI()
        api.timelineReplies[t.project.id] = [fresh(t, "e1"), notModified("e1"), fresh(t, "e2")]
        let cache = ProjectsCache(api: api)
        let r0 = cache.revision(t.project.id)
        await cache.refreshTimeline(t.project.id)
        let r1 = cache.revision(t.project.id)
        XCTAssertNotEqual(r0, r1)
        await cache.refreshTimeline(t.project.id)
        XCTAssertEqual(cache.revision(t.project.id), r1, "a 304 changes nothing")
        let overlay = ProjectOverlay(id: UUID(), projectId: t.project.id, change: .milestoneAdded(name: "x", target: nil),
                                     day: ProjectFixtures.today)
        cache.add(overlay)
        let r2 = cache.revision(t.project.id)
        XCTAssertNotEqual(r2, r1)
        cache.remove(overlayId: overlay.id)
        let r3 = cache.revision(t.project.id)
        XCTAssertNotEqual(r3, r2)
        cache.reset()
        XCTAssertEqual(cache.revision(t.project.id), 0)
        await cache.refreshTimeline(t.project.id)
        XCTAssertFalse([r1, r2, r3].contains(cache.revision(t.project.id)), "never reused across a bank switch")
    }
```

- [ ] **Step 2: Run, watch it fail** — `cd <worktree>/app/CicadaApp && swift test --filter
  'ProjectBigStoryTests|ProjectsCacheTests' 2>&1 | tail -20` (compile errors: the new names do not exist).

- [ ] **Step 3: The wire.** `Models/Project.swift` `ProjectItem`: add `var participantsTotal: Int?` after
  `participants`, `participantsTotal` in `CodingKeys`, and `participantsTotal = c.lenient(.participantsTotal)` in
  `init(from:)`. One-line doc: "D6 — how many participants the happening has when the server sent only the first 12
  (D6's cap); nil from a backend that sends them all."

- [ ] **Step 4: The budget** — append to `Views/Projects/ProjectStory.swift`, and mark `ProjectStory.Group` as
  `Sendable` (`struct Group: Identifiable, Equatable, Sendable`):

```swift
/// Round-4 D6 (R-FA1) — what one sentence draws: its tokens (a page link past the budget reads as the words it is),
/// the trailing chips, and how many participants stay folded behind "+N more".
struct StoryChips: Equatable {
    let tokens: [StoryToken]
    let extra: [ProjectParticipant]
    /// Participants not drawn as a chip: folded here, plus the ones the server never sent.
    let more: Int
    /// Participants the server held back (`participantsTotal − participants.count`). Expanding cannot show them.
    let notSent: Int
    var canExpand: Bool { more > notSent }
}

extension ProjectStory {
    /// D6 — at most this many page chips per sentence. The owner's "you" is the sentence's own word and never counts.
    static let chipBudget = 8

    static func chips(_ text: String, participants: [ProjectParticipant], total: Int?, expanded: Bool) -> StoryChips {
        let parts = tokens(text, participants: participants)
        let notSent = max(0, (total ?? participants.count) - participants.count)
        guard !expanded else { return StoryChips(tokens: parts.tokens, extra: parts.extra, more: notSent, notSent: notSent) }
        var pages = 0
        var demoted = 0
        let capped = parts.tokens.map { token -> StoryToken in
            guard token.kind == .page else { return token }
            pages += 1
            guard pages > chipBudget else { return token }
            demoted += 1
            return StoryToken(id: token.id, kind: .word, text: token.text + token.trailing, trailing: "",
                              spaceBefore: token.spaceBefore, participant: nil)
        }
        let extra = Array(parts.extra.prefix(max(0, chipBudget - min(pages, chipBudget))))
        return StoryChips(tokens: capped, extra: extra, more: demoted + parts.extra.count - extra.count + notSent,
                          notSent: notSent)
    }

    /// R-FA3 — Lately as one flat list, so every row is a direct child of the column's lazy stack.
    enum LatelyEntry: Identifiable, Equatable {
        case label(RelativeDay.Group, first: Bool)
        case item(ProjectItem)

        /// A row's id IS its scroll id (`ProjectKey.item`), so `ScrollViewReader.scrollTo` finds rows not yet built.
        var id: String {
            switch self {
            case .label(let group, _): "lately.label.\(group)"
            case .item(let item): ProjectKey.item(item.id).id
            }
        }
    }

    static func latelyEntries(_ groups: [Group]) -> [LatelyEntry] {
        groups.enumerated().flatMap { index, group in
            [LatelyEntry.label(group.group, first: index == 0)] + group.items.map { LatelyEntry.item($0) }
        }
    }
}
```

  `ProjectStory.swift` stays Foundation-only (it is the story's pure words); the spacing lives beside the views, in
  `ProjectSections.swift`:

```swift
extension ProjectStory.LatelyEntry {
    /// R-FA3 — the gaps the nested stacks used to give: header → first label `spacingSM`, between groups
    /// `spacingMD`, between rows `spacingXS`.
    var topPadding: CGFloat {
        switch self {
        case .label(_, let first): first ? CicadaTheme.spacingSM : CicadaTheme.spacingMD
        case .item: CicadaTheme.spacingXS
        }
    }
}
```

- [ ] **Step 5: `TextButton(inline:)`** — `Views/Common/TextButton.swift`: add `var inline = false`; when true the
  label is `CicadaTheme.font(size: 12, weight: .medium)`, horizontal padding `CicadaTheme.scaled(6)` and height
  `CicadaTheme.scaled(22)` (a participant chip's height, `ProjectSentence.swift:129`). Doc: "R-FA1 — a text button
  that sits inside a sentence line of chips; 32 pt would stretch the line." Existing call sites are unchanged.

- [ ] **Step 6: The sentence** — `Views/Projects/ProjectSentence.swift` `StorySentence`: add `var total: Int? = nil`
  declared right after `participants` (the memberwise init takes labels in declaration order, so every call reads
  `StorySentence(text:participants:total:lead:openEntity:)`; the two existing calls that pass no `total` still compile)
  and `@State private var expanded = false` (a private `@State` with a default keeps the memberwise init callable from
  `ProjectSections.swift` — checked); replace `let parts = ProjectStory.tokens(...)` with
  `let parts = ProjectStory.chips(text, participants: participants, total: total, expanded: expanded)` and, after the
  `extra` `ForEach`, inside the same `SentenceFlowLayout`:

```swift
            if parts.canExpand, !expanded {
                TextButton(title: Copy.Projects.moreParticipants(parts.more), help: Copy.Projects.moreParticipantsHelp,
                           inline: true) { Instant.run { expanded = true } }
                    .layoutValue(key: SpaceBefore.self, value: true)
            } else if parts.notSent > 0 {
                Text(Copy.Projects.notListed(parts.notSent))
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .help(Copy.Projects.notListedHelp)
                    .layoutValue(key: SpaceBefore.self, value: true)
            }
            if expanded {
                TextButton(title: Copy.Projects.fewerParticipants, inline: true) { Instant.run { expanded = false } }
                    .layoutValue(key: SpaceBefore.self, value: true)
            }
```

  `TextButton`'s init order is `(title:keyHint:help:inline:action:)` — keep `inline` after `help` and before the
  trailing closure. `Copy.Projects` gains `moreParticipants(_ n:)` → `"+\(UsageFormat.count(n)) more"`,
  `moreParticipantsHelp = "Show everyone this sentence names"`, `notListed(_ n:)` →
  `"\(UsageFormat.count(n)) more not listed here"`, `notListedHelp = "The rest are under Around this project"`,
  `fewerParticipants = "Show fewer"`. Now's thread row (`ProjectSections.swift:77-80`) passes
  `total: item?.participantsTotal`.

- [ ] **Step 7: The derivation** — create `Views/Projects/ProjectDerived.swift`:

```swift
import Foundation

/// Round-4 D6 (R-FA2) — everything the detail column derives from one timeline on one day, built OFF the main actor:
/// the project's state, Lately's groups and count, and the chips' document index. Decoding already runs inside
/// `actor APIClient` (`ProjectsAPI`); this moves the rest out of `body`, where it ran on every evaluation, so a
/// story's size never blocks the main actor.
struct ProjectDerived: Equatable, Sendable {
    struct Key: Hashable, Sendable {
        let projectId: String
        let today: ISODay
        let revision: Int
    }

    let key: Key
    let state: ProjectState.Output
    let groups: [ProjectStory.Group]
    let happenings: Int
    let docIndex: EvidenceDocIndex

    static func build(_ t: ProjectTimeline, key: Key) -> ProjectDerived {
        ProjectDerived(key: key,
                       state: ProjectState.state(ProjectState.Input(t), today: key.today),
                       groups: ProjectStory.groups(t.items, today: key.today),
                       happenings: t.items.filter { $0.kind != "created" }.count,
                       docIndex: ProjectSource.docIndex(t))
    }

    /// Detached, so it never inherits the caller's main actor.
    static func make(_ t: ProjectTimeline, key: Key) async -> ProjectDerived {
        await Task.detached(priority: .userInitiated) { build(t, key: key) }.value
    }
}
```

  Mark `EvidenceDocIndex` and `EvidenceDocMeta` `Sendable` (`EvidenceChipModel.swift:14, 20`). If the compiler
  reports `ProjectStory.groups`, `ProjectSource.docIndex` or `RelativeDay.group` as main-actor isolated, mark those
  pure statics `nonisolated` — do not wrap them in `MainActor.run`.

- [ ] **Step 8: The cache's revision** — `Views/Projects/ProjectsCache.swift`:

```swift
    /// R-FA2 — changes whenever what `display(id)` returns may change (a fresh answer, a 404, an overlay added or
    /// removed), and only then, so the column re-derives off the main actor exactly when it must. One global
    /// counter, never reset, so a revision handed out before a bank switch can never match one after it.
    private(set) var revisions: [String: Int] = [:]
    @ObservationIgnored private var nextRevision = 1

    func revision(_ id: String) -> Int { revisions[id] ?? 0 }

    private func bump(_ id: String) {
        revisions[id] = nextRevision
        nextRevision &+= 1
    }
```

  Call `bump(id)` in `store(_:etag:for:)` (and `bump(old)` for each id its capacity loop evicts — `display(old)` turns
  nil), in the 404 branch of `refreshTimeline`, in `add(_:)` (the overlay's `projectId`), and in `remove(overlayId:)`
  for every key whose list changed. `confirm(_:)` does not bump: a confirmed overlay paints the same until the next fresh
  answer, which bumps through `store`. `reset()` sets `revisions = [:]` and leaves `nextRevision` alone.

- [ ] **Step 9: The column** — `Views/Projects/ProjectDetailColumn.swift`:
  1. Add `@State private var derived: ProjectDerived?`, `@State private var conversations = ConversationsViewModel()`
     (moved from `ProjectLatelySection`), and
     `private var deriveKey: ProjectDerived.Key { .init(projectId: projectId, today: today, revision: cache.revision(projectId)) }`.
  2. Add, beside the existing `.task(id: projectId)`:

```swift
        // R-FA2 — derive off the main actor, only when the project, the day or the cached payload moved.
        .task(id: deriveKey) {
            guard let t = cache.display(projectId) else { return }
            let value = await ProjectDerived.make(t, key: deriveKey)
            guard !Task.isCancelled else { return }
            derived = value
        }
```

  3. In `body`, `if let t = cache.display(projectId)` becomes: with `let d = derived, d.key.projectId == projectId`,
     call `content(t, d)`; with a timeline but no derived value yet, draw `header(...)` and
     `ListSkeleton(message: Copy.Projects.reading)` (the same skeleton a first open shows); otherwise the existing
     phase switch. An older derived value for the SAME project keeps painting while the new one builds (R-FA2).
  4. `content(_ t:, _ d:)` reads `d.state` wherever it computed `state` (`:106`, including the `BandLayout.make` call at
     `:107`, which stays in `body` — R-FA2), `d.docIndex` for `.environment(\.evidenceDocIndex, …)` (`:125`), and
     `d.happenings` for Lately's collapsed meta (`:148-149`). `sections(_:state:)` (`:137-179`) is folded into the
     lazy stack below and deleted.
  5. Replace the story's `ScrollView { VStack(alignment: .leading, spacing: CicadaTheme.scaled(26)) { … } }` with
     `ScrollView { LazyVStack(alignment: .leading, spacing: 0) { … } }`, keeping the same frame, padding and
     `.environment` modifiers. Its children, in order: the Log field (no top padding); `section(.now, …)` with
     `.padding(.top, CicadaTheme.scaled(26))`; Lately's `ProjectSectionHeader` with `.padding(.top, CicadaTheme.scaled(26))`;
     when Lately is open, `ForEach(ProjectStory.latelyEntries(d.groups)) { entry in latelyEntry(entry, t: t, d: d).padding(.top, entry.topPadding) }`
     and, when `ProjectStory.createdLine(t.items, today: today)` is non-nil, `ProjectLatelyFoot(text:)` with
     `.padding(.top, CicadaTheme.spacingMD)`; `section(.plan, …)` with `.padding(.top, CicadaTheme.scaled(26))` and its
     existing `.id("section.plan")`; Around the same way. `latelyEntry` switches: `.label(group, _)` →
     `ProjectLatelyLabel(group: group)`; `.item(item)` → `ProjectLatelyRow(...)` with the arguments
     `ProjectLatelySection` received plus `conversations`.
- [ ] **Step 10: The rows** — `Views/Projects/ProjectSections.swift`: replace `ProjectLatelySection` (`:123-231`) with
  three types, moving code **verbatim** (only `self.` receivers change): `ProjectLatelyLabel` (the
  `SectionLabel(RelativeDay.title(group)).padding(.horizontal, CicadaTheme.spacingMD)` line),
  `ProjectLatelyRow` (today's `row(_:)` + `actions(_:)`, taking `item`, `timeline`, `state`, `today`, `selection`,
  `readerEpisode`, `names`, `pick`, `openEntity`, `showSource`, `closeReader`, `withdraw`, `writesBlocked`,
  `conversations: ConversationsViewModel`; `StorySentence` now gets `total: item.participantsTotal`), and
  `ProjectLatelyFoot` (the created line). Keep the doc comment, reworded: "Lately (the brief) … one row, a direct
  child of the column's lazy stack (R-FA3)".
- [ ] **Step 11: Green** — `swift test --filter 'ProjectBigStoryTests|ProjectsCacheTests|ProjectStoryTests|ProjectBandTests|ProjectWritesTests|ProjectsListTests' 2>&1 | tail -20`,
  then `swift build 2>&1 | tail -5` and the full `swift test 2>&1 | tail -20` (0 failures).
- [ ] **Step 12: Commit** — stage the files above by name.

```
feat(projects): a big project opens instantly — 8 chips + "+N more", off-main derivation, lazy Lately (D6)

A happening that cites hundreds of papers drew one hover-tracked chip per participant in one measured
layout, and the column derived its state in body. Now a sentence draws at most 8 page chips (the owner
never counts) and a "+N more" that opens that row only; the server's participantsTotal counts toward it;
ProjectDerived runs off the main actor keyed by the cache's revision; Lately's rows are direct children
of one LazyVStack. Decoding already ran on the APIClient actor.

DR-40 (TextButton inline), DR-48, DR-60 (Instant.run), DR-21 (UsageFormat)
```

---

### Task 2: Home's painting follows the clock (D4, G144)

**Files:** see the file map rows marked 2.

**Interfaces:**
- Produces `GeoPoint`; `TimeZoneCoordinates.bundled` / `load(from:)` / `point(for:in:)`; `SceneClock.SunTimes`
  (`horizon`, `twilight: Crossing`, `estimated`), `SceneClock.sun(on:timeZone:table:)`, `sun(on:timeZone:at:)`,
  `phase(at:timeZone:table:)`, `phase(at:sun:)`, `nextBoundary(after:timeZone:table:)`; `HeroScenePreference`
  (`defaultsKey`, `stored(_:)`, `scene(clock:)`, `label`); `SceneStore` (`shared`, `phase`, `start()`, `refresh()`,
  `delayUntilNextCheck()`); `MeadowArt.heroMode(for:)`; `SettingsRowID.heroScene`.
- Consumes `CicadaTheme.SkyPhase`, `Bundle.cicadaResource`, `MeadowArt.image(for:mode:)`, `PillPicker`.

- [ ] **Step 1: The generator + its test (Python first).** Create `scripts/gen-tz-coordinates.py` (executable,
  stdlib only):

```python
#!/usr/bin/env python3
"""Generate the app's time zone → coordinates table (round-4 D4, G144).

The Home painting follows sunrise and sunset in the Mac's time zone, with no
location permission: SceneClock needs one point per zone, and IANA's tz
database already names one — the zone's principal location.

Provenance: IANA tzdb (https://www.iana.org/time-zones). zone1970.tab and
zone.tab each begin "This file is in the public domain"; the Link lines come
from the same distribution. Order of precedence (R-FA5): zone1970.tab, then
zone.tab (a zone zone1970 folds into another, e.g. Europe/Oslo), then Link
lines resolved to a zone that has a point. Together they cover every
identifier macOS knows but GMT (measured on tzdata 2026d: 442 of 443).

Usage (run it with api/.venv/bin/python — the download path needs tarfile's
"data" extraction filter, Python 3.12 or a late 3.9-3.11 patch release):
  scripts/gen-tz-coordinates.py                   # downloads tzdata-latest.tar.gz
  scripts/gen-tz-coordinates.py --tzdata DIR      # an unpacked tzdata directory
  scripts/gen-tz-coordinates.py --out PATH        # default: the app's resource
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
import tarfile
import urllib.request
from pathlib import Path

TZDATA_URL = "https://data.iana.org/time-zones/tzdata-latest.tar.gz"
REGION_FILES = ("africa", "antarctica", "asia", "australasia", "europe", "northamerica",
                "southamerica", "etcetera", "backward", "backzone")
DEFAULT_OUT = (Path(__file__).resolve().parent.parent
               / "app/CicadaApp/Sources/CicadaApp/Resources/scene/tz-coordinates.json")
_ISO6709 = re.compile(r"^([+-])(\d{2})(\d{2})(\d{2})?([+-])(\d{3})(\d{2})(\d{2})?$")


def parse_iso6709(value: str) -> tuple[float, float]:
    """±DDMM[SS]±DDDMM[SS] → (latitude, longitude) in decimal degrees."""
    m = _ISO6709.match(value)
    if not m:
        raise ValueError(f"not ISO 6709: {value!r}")
    s1, d1, m1, x1, s2, d2, m2, x2 = m.groups()
    lat = int(d1) + int(m1) / 60 + int(x1 or 0) / 3600
    lon = int(d2) + int(m2) / 60 + int(x2 or 0) / 3600
    return (lat if s1 == "+" else -lat, lon if s2 == "+" else -lon)


def read_tab(path: Path) -> dict[str, tuple[float, float]]:
    out: dict[str, tuple[float, float]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        cols = line.split("\t")
        out[cols[2]] = parse_iso6709(cols[1])
    return out


def read_links(tzdata: Path) -> dict[str, str]:
    links: dict[str, str] = {}
    for name in REGION_FILES:
        path = tzdata / name
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            parts = line.split("#", 1)[0].split()
            if len(parts) >= 3 and parts[0] == "Link":
                links.setdefault(parts[2], parts[1])
    return links


def build(tzdata: Path) -> dict[str, list[float]]:
    table = read_tab(tzdata / "zone.tab")
    table.update(read_tab(tzdata / "zone1970.tab"))   # zone1970 wins where both name a zone
    links = read_links(tzdata)
    for alias, target in links.items():
        hops = 0                                       # a link may point at another link; follow up to five
        while target not in table and target in links and hops < 5:
            target, hops = links[target], hops + 1
        if alias not in table and target in table:
            table[alias] = table[target]
    return {zone: [round(lat, 2), round(lon, 2)] for zone, (lat, lon) in sorted(table.items())}


def fetch(dest: Path) -> Path:
    with urllib.request.urlopen(TZDATA_URL, timeout=30) as response:
        data = response.read()
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        tar.extractall(dest, filter="data")
    return dest


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tzdata", type=Path)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    if args.tzdata is None:
        import tempfile
        args.tzdata = fetch(Path(tempfile.mkdtemp(prefix="tzdata-")))
    version = (args.tzdata / "version").read_text(encoding="utf-8").strip() if (args.tzdata / "version").exists() else "unknown"
    payload = {"source": "IANA tzdb zone1970.tab + zone.tab + Link lines (public domain); scripts/gen-tz-coordinates.py",
               "version": version, "zones": build(args.tzdata)}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"wrote {len(payload['zones'])} zones (tzdata {version}) to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

  Write the test FIRST — `api/tests/test_gen_tz_coordinates.py` — and run it red (no script yet), then add the script
  above and run it green: `api/.venv/bin/python -m pytest api/tests/test_gen_tz_coordinates.py -q -p no:cacheprovider`
  (3 passed; the plan critic ran this exact file against the script above).

```python
"""Round-4 D4 (G144) — scripts/gen-tz-coordinates.py, the generator of the app's time zone → coordinates table.

Every case runs over a synthetic tzdata directory in tmp_path: the network is never touched, and no real zone's
coordinates are asserted beyond the generator's own arithmetic.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "gen-tz-coordinates.py"


def _generator():
    # The file name has hyphens (a script, not a module), so it is loaded by path.
    spec = importlib.util.spec_from_file_location("gen_tz_coordinates", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tzdata(tmp_path: Path) -> Path:
    d = tmp_path / "tzdata"
    d.mkdir()
    (d / "zone1970.tab").write_text(
        "# This file is in the public domain.\n"
        "DE,NO\t+5230+01322\tEurope/Berlin\n"
        "US\t+404251-0740023\tAmerica/New_York\tEastern (most areas)\n",
        encoding="utf-8",
    )
    (d / "zone.tab").write_text(
        "# This file is in the public domain.\n"
        "NO\t+5955+01045\tEurope/Oslo\n"
        "DE\t+5000+01000\tEurope/Berlin\n",
        encoding="utf-8",
    )
    (d / "backward").write_text(
        "Link\tEurope/Berlin\tArctic/Example\n"
        "Link\tArctic/Example\tAntarctica/Example\t# a link to a link\n"
        "Link\tNowhere/Unknown\tEtc/Orphan\n",
        encoding="utf-8",
    )
    (d / "version").write_text("2099z\n", encoding="utf-8")
    return d


def test_iso6709_degrees_minutes_and_seconds():
    gen = _generator()
    lat, lon = gen.parse_iso6709("+404251-0740023")
    assert lat == pytest.approx(40.7142, abs=1e-4)
    assert lon == pytest.approx(-74.0064, abs=1e-4)
    lat, lon = gen.parse_iso6709("-7750+16636")
    assert lat == pytest.approx(-77.8333, abs=1e-4)
    assert lon == pytest.approx(166.6, abs=1e-4)
    with pytest.raises(ValueError):
        gen.parse_iso6709("40N74W")


def test_zone1970_wins_then_zone_tab_fills_then_links_resolve(tmp_path):
    zones = _generator().build(_tzdata(tmp_path))
    assert zones["Europe/Berlin"] == [52.5, 13.37], "zone1970.tab wins where both tables name a zone"
    assert zones["Europe/Oslo"] == [59.92, 10.75], "zone.tab fills a zone zone1970.tab folds into another"
    assert zones["Arctic/Example"] == zones["Europe/Berlin"]
    assert zones["Antarctica/Example"] == zones["Europe/Berlin"], "a link to a link resolves"
    assert "Etc/Orphan" not in zones, "a link to nothing is left out, never guessed"
    assert zones["America/New_York"] == [40.71, -74.01], "rounded to 2 decimals (R-FA5)"


def test_main_writes_the_resource_with_its_source_and_version(tmp_path):
    out = tmp_path / "scene" / "tz-coordinates.json"
    assert _generator().main(["--tzdata", str(_tzdata(tmp_path)), "--out", str(out)]) == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["version"] == "2099z"
    assert "public domain" in payload["source"]
    assert payload["zones"]["Europe/Oslo"] == [59.92, 10.75]
```

- [ ] **Step 2: Generate the table** — `cd <worktree> && api/.venv/bin/python scripts/gen-tz-coordinates.py` (the venv's
  Python 3.12: `tarfile.extractall(filter="data")` needs 3.12, or a 3.9.17+/3.10.12+/3.11.4+ backport, and macOS's own
  `/usr/bin/python3` is 3.9.6). It must print ≥ 440 zones (tzdata 2026d gives 549). **If the download fails, stop and
  report it** — never hand-write coordinates. Stage `app/CicadaApp/Sources/CicadaApp/Resources/scene/tz-coordinates.json`
  (~18 KB on 2026d). `Package.swift`'s `.copy("Resources")` and `bundle.sh`'s re-nesting (it copies the whole resource
  bundle) pick up the new `scene/` directory with no change.

- [ ] **Step 3: Failing Swift tests** — `app/CicadaApp/Tests/CicadaAppTests/SceneClockTests.swift`. The expected
  times are the published sunrise/sunset for the zone's tzdb point (checked against NOAA's equations in Python while
  writing this plan: New York 05:25:02 / 20:30:39 EDT, Tokyo 04:25:38 / 19:00:02 JST, Madrid 08:34:18 / 17:51:18
  CET), held to ±5 minutes:

```swift
import XCTest
@testable import CicadaApp

/// Round-4 D4 (G144) — the Home painting's clock: NOAA's sun over each time zone's tzdb point, no location.
final class SceneClockTests: XCTestCase {
    private func date(_ y: Int, _ m: Int, _ d: Int, _ h: Int, _ min: Int, _ zone: String) -> Date {
        var c = Calendar(identifier: .gregorian)
        c.timeZone = TimeZone(identifier: zone)!
        return c.date(from: DateComponents(year: y, month: m, day: d, hour: h, minute: min))!
    }

    private func assertNear(_ actual: Date?, _ expected: Date, file: StaticString = #filePath, line: UInt = #line) {
        guard let actual else { return XCTFail("no time", file: file, line: line) }
        XCTAssertLessThanOrEqual(abs(actual.timeIntervalSince(expected)), 5 * 60, "\(actual) vs \(expected)",
                                 file: file, line: line)
    }

    private func riseSet(_ zone: String, _ y: Int, _ m: Int, _ d: Int) throws -> (Date, Date) {
        let tz = try XCTUnwrap(TimeZone(identifier: zone))
        let sun = SceneClock.sun(on: date(y, m, d, 12, 0, zone), timeZone: tz)
        guard case let .times(rise, set) = sun.horizon else { throw XCTSkip("no crossing") }
        XCTAssertFalse(sun.estimated, "\(zone) has a tzdb point")
        return (rise, set)
    }

    func testKnownSunrisesAndSunsetsWithinFiveMinutes() throws {
        let ny = try riseSet("America/New_York", 2026, 6, 21)
        assertNear(ny.0, date(2026, 6, 21, 5, 25, "America/New_York"))
        assertNear(ny.1, date(2026, 6, 21, 20, 31, "America/New_York"))
        let tokyo = try riseSet("Asia/Tokyo", 2026, 6, 21)
        assertNear(tokyo.0, date(2026, 6, 21, 4, 25, "Asia/Tokyo"))
        assertNear(tokyo.1, date(2026, 6, 21, 19, 0, "Asia/Tokyo"))
        let madrid = try riseSet("Europe/Madrid", 2026, 12, 21)
        assertNear(madrid.0, date(2026, 12, 21, 8, 34, "Europe/Madrid"))
        assertNear(madrid.1, date(2026, 12, 21, 17, 51, "Europe/Madrid"))
    }

    func testThePhasesOfOneDay() {
        let ny = TimeZone(identifier: "America/New_York")!
        XCTAssertEqual(SceneClock.phase(at: date(2026, 6, 21, 12, 0, "America/New_York"), timeZone: ny), .day)
        XCTAssertEqual(SceneClock.phase(at: date(2026, 6, 21, 20, 50, "America/New_York"), timeZone: ny), .dusk)
        XCTAssertEqual(SceneClock.phase(at: date(2026, 6, 21, 23, 0, "America/New_York"), timeZone: ny), .night)
        XCTAssertEqual(SceneClock.phase(at: date(2026, 6, 21, 5, 5, "America/New_York"), timeZone: ny), .dusk,
                       "dawn's twilight is the dusk phase — SkyPhase has no dawn (R-FA4)")
    }

    func testPolarDayAndNightFallBackSanely() {
        let svalbard = TimeZone(identifier: "Arctic/Longyearbyen")!
        XCTAssertEqual(SceneClock.phase(at: date(2026, 6, 21, 0, 30, "Arctic/Longyearbyen"), timeZone: svalbard), .day)
        XCTAssertEqual(SceneClock.phase(at: date(2026, 12, 21, 12, 0, "Arctic/Longyearbyen"), timeZone: svalbard), .night)
        let mcmurdo = TimeZone(identifier: "Antarctica/McMurdo")!
        XCTAssertEqual(SceneClock.phase(at: date(2026, 6, 21, 12, 0, "Antarctica/McMurdo"), timeZone: mcmurdo), .night)
        let now = date(2026, 6, 21, 12, 0, "Arctic/Longyearbyen")
        let next = SceneClock.nextBoundary(after: now, timeZone: svalbard)
        XCTAssertGreaterThan(next, now)
        XCTAssertLessThanOrEqual(next.timeIntervalSince(now), 24 * 3600, "with no crossing, the next local midnight")
    }

    /// R-FA5 — a zone far from its meridian gets ITS day's sun, not the next day's (Kiritimati is UTC+14 at 157° W).
    func testAZoneAcrossTheDateLineGetsItsOwnDay() throws {
        let zone = "Pacific/Kiritimati"
        let tz = try XCTUnwrap(TimeZone(identifier: zone))
        XCTAssertEqual(SceneClock.phase(at: date(2026, 6, 21, 12, 0, zone), timeZone: tz), .day)
        XCTAssertEqual(SceneClock.phase(at: date(2026, 6, 21, 3, 0, zone), timeZone: tz), .night)
        let (rise, _) = try riseSet(zone, 2026, 6, 21)
        var c = Calendar(identifier: .gregorian)
        c.timeZone = tz
        XCTAssertTrue(c.isDate(rise, inSameDayAs: date(2026, 6, 21, 12, 0, zone)), "the sunrise of the day asked about")
    }

    /// Every zone this Mac can be set to is day at 13:00 and night at 01:00 on the September equinox — no zone is
    /// polar then. Before R-FA5's day choice, 8 Pacific zones read night at 13:00.
    func testEveryZoneIsDayAtOneAndNightAtOneOnTheEquinox() {
        var wrong: [String] = []
        for zone in TimeZone.knownTimeZoneIdentifiers {
            guard let tz = TimeZone(identifier: zone) else { continue }
            let afternoon = SceneClock.phase(at: date(2026, 9, 23, 13, 0, zone), timeZone: tz)
            let night = SceneClock.phase(at: date(2026, 9, 23, 1, 0, zone), timeZone: tz)
            if afternoon != .day || night != .night { wrong.append("\(zone): \(afternoon)/\(night)") }
        }
        XCTAssertEqual(wrong, [])
    }

    /// At a pole the formula divides by cos(latitude); the clamp keeps it an answer, never NaN.
    func testAPointAtThePoleStillAnswers() {
        let utc = TimeZone(identifier: "UTC")!
        let pole = GeoPoint(latitude: 90, longitude: 0)
        XCTAssertEqual(SceneClock.sun(on: date(2026, 6, 21, 12, 0, "UTC"), timeZone: utc, at: pole).horizon, .alwaysAbove)
        XCTAssertEqual(SceneClock.sun(on: date(2026, 12, 21, 12, 0, "UTC"), timeZone: utc, at: pole).horizon, .alwaysBelow)
    }

    func testAZoneWithNoPointKeepsAPlainClock() {
        let gmt = TimeZone(identifier: "GMT")!
        XCTAssertTrue(SceneClock.sun(on: date(2026, 9, 24, 12, 0, "GMT"), timeZone: gmt).estimated)
        XCTAssertEqual(SceneClock.phase(at: date(2026, 9, 24, 12, 0, "GMT"), timeZone: gmt), .day)
        XCTAssertEqual(SceneClock.phase(at: date(2026, 9, 24, 6, 45, "GMT"), timeZone: gmt), .dusk)
        XCTAssertEqual(SceneClock.phase(at: date(2026, 9, 24, 2, 0, "GMT"), timeZone: gmt), .night)
    }

    /// R-FA5 — the bundled table covers every zone this Mac can be set to, but GMT/UTC.
    func testTheBundledTableCoversEveryKnownZone() {
        XCTAssertGreaterThan(TimeZoneCoordinates.bundled.count, 400)
        let missing = TimeZone.knownTimeZoneIdentifiers.filter {
            !["GMT", "UTC"].contains($0) && TimeZoneCoordinates.point(for: $0) == nil
        }
        XCTAssertEqual(missing, [], "re-run scripts/gen-tz-coordinates.py")
    }

    func testThePreferenceOverridesTheClock() {
        XCTAssertEqual(HeroScenePreference.stored(nil), .automatic)
        XCTAssertEqual(HeroScenePreference.stored("sunset"), .automatic, "an unknown value is Automatic")
        XCTAssertEqual(HeroScenePreference.stored("night"), .night)
        XCTAssertEqual(HeroScenePreference.automatic.scene(clock: .dusk), .dusk)
        XCTAssertEqual(HeroScenePreference.day.scene(clock: .night), .day)
        XCTAssertEqual(HeroScenePreference.night.scene(clock: .day), .night)
        XCTAssertEqual(HeroScenePreference.defaultsKey, "cicada.heroScene")
    }

    /// R-FA4 — day paints hero-day; dusk and night its -dark sibling, whatever the theme.
    func testTheHeroPicksItsPaintingByTheScene() {
        XCTAssertEqual(MeadowArt.fileName(for: .heroDay, mode: MeadowArt.heroMode(for: .day)), "hero-day")
        XCTAssertEqual(MeadowArt.fileName(for: .heroDay, mode: MeadowArt.heroMode(for: .dusk)), "hero-day-dark")
        XCTAssertEqual(MeadowArt.fileName(for: .heroDay, mode: MeadowArt.heroMode(for: .night)), "hero-day-dark")
    }

    /// R-FA6 — the store looks again at the next boundary, or within the hour.
    @MainActor
    func testTheStoreRechecksAtTheNextBoundaryOrWithinTheHour() {
        let ny = TimeZone(identifier: "America/New_York")!
        let justBeforeSunset = date(2026, 6, 21, 20, 20, "America/New_York")
        let store = SceneStore(now: { justBeforeSunset }, timeZone: { ny })
        XCTAssertEqual(store.phase, .day)
        XCTAssertLessThan(store.delayUntilNextCheck(), 20 * 60)
        let noon = date(2026, 6, 21, 12, 0, "America/New_York")
        XCTAssertEqual(SceneStore(now: { noon }, timeZone: { ny }).delayUntilNextCheck(), SceneClock.maxRecheck)
    }

    /// The hero follows the scene, never the theme (source check, the HomeBandLayoutTests precedent).
    func testTheHeroViewsDoNotReadTheThemeForThePainting() throws {
        let files = try ThemeTokenTests.swiftSources()
        for suffix in ["Views/Meadow/HomeHeroBand.swift", "Views/Meadow/WelcomeHero.swift"] {
            let text = try String(contentsOf: XCTUnwrap(files.first { $0.path.hasSuffix(suffix) }), encoding: .utf8)
            XCTAssertFalse(text.contains("mode: CicadaTheme.mode"), suffix)
            XCTAssertTrue(text.contains("MeadowArt.heroMode(for:"), suffix)
        }
    }
}
```

  Also add to `SettingsIndexTests.testLiveValues`: `SettingsLiveValue.text(for: .heroScene, inputs)` with
  `inputs.heroScene = .night` is "Always night".

- [ ] **Step 4: Implement `Theme/SceneClock.swift`:**

```swift
import Foundation

/// A place on Earth, in decimal degrees (north and east positive).
struct GeoPoint: Equatable, Sendable {
    let latitude: Double
    let longitude: Double
}

/// Round-4 D4 (R-FA5) — each time zone's principal location, from the table `scripts/gen-tz-coordinates.py` builds out
/// of IANA tzdb (public domain; its `source` and `version` travel in the JSON). Loaded once; `[:]` if the bundle lost
/// the file, which only costs the painting its accuracy (the plain-clock fallback), never a crash.
enum TimeZoneCoordinates {
    static let directory = "scene"
    static let resource = "tz-coordinates"

    static let bundled: [String: GeoPoint] = load(from: .cicadaResources)

    private struct Payload: Decodable { let zones: [String: [Double]] }

    static func load(from bundle: Bundle) -> [String: GeoPoint] {
        guard let url = bundle.cicadaResource(resource, ext: "json", in: directory),
              let data = try? Data(contentsOf: url),
              let payload = try? JSONDecoder().decode(Payload.self, from: data) else { return [:] }
        return payload.zones.compactMapValues { $0.count == 2 ? GeoPoint(latitude: $0[0], longitude: $0[1]) : nil }
    }

    static func point(for identifier: String, in table: [String: GeoPoint] = bundled) -> GeoPoint? { table[identifier] }
}

/// Round-4 D4 (G144, C7) — whether it is day, dusk or night where this Mac's clock says it is, from the time zone
/// alone: NOAA's general solar-position equations (the NOAA Solar Calculator's) over the zone's tzdb point. No location
/// permission and no network: a time zone is something the Mac already knows, and a painting needs the minute, not the
/// street. Pure; `SceneClockTests`.
enum SceneClock {
    /// When the sun crosses one altitude on one day, or that it never does.
    enum Crossing: Equatable, Sendable {
        case times(rise: Date, set: Date)
        case alwaysAbove
        case alwaysBelow
    }

    struct SunTimes: Equatable, Sendable {
        /// The upper limb at the horizon with refraction (sunrise / sunset).
        let horizon: Crossing
        /// Six degrees below (civil dawn / dusk).
        let twilight: Crossing
        /// True for R-FA5's plain clock: the zone had no point.
        let estimated: Bool
    }

    static let sunriseZenith = 90.833
    static let civilZenith = 96.0
    static let fallbackSunriseHour = 7
    static let fallbackSunsetHour = 19
    static let fallbackTwilight: TimeInterval = 30 * 60
    /// R-FA6 — the store never waits longer than this before looking again.
    static let maxRecheck: TimeInterval = 3600

    static func phase(at date: Date, timeZone: TimeZone,
                      table: [String: GeoPoint] = TimeZoneCoordinates.bundled) -> CicadaTheme.SkyPhase {
        phase(at: date, sun: sun(on: date, timeZone: timeZone, table: table))
    }

    /// R-FA4 — day between the horizon crossings, dusk in civil twilight at either end, night otherwise.
    static func phase(at date: Date, sun s: SunTimes) -> CicadaTheme.SkyPhase {
        switch s.horizon {
        case .alwaysAbove: return .day
        case let .times(rise, set) where date >= rise && date < set: return .day
        default: break
        }
        switch s.twilight {
        case .alwaysAbove: return .dusk
        case let .times(dawn, dusk) where date >= dawn && date < dusk: return .dusk
        default: return .night
        }
    }

    static func sun(on date: Date, timeZone: TimeZone,
                    table: [String: GeoPoint] = TimeZoneCoordinates.bundled) -> SunTimes {
        guard let point = TimeZoneCoordinates.point(for: timeZone.identifier, in: table) else {
            return plainClock(on: date, timeZone: timeZone)
        }
        return sun(on: date, timeZone: timeZone, at: point)
    }

    /// The sun for the LOCAL calendar day `date` falls on, at `p`.
    static func sun(on date: Date, timeZone: TimeZone, at p: GeoPoint) -> SunTimes {
        var local = Calendar(identifier: .gregorian)
        local.timeZone = timeZone
        let ymd = local.dateComponents([.year, .month, .day], from: date)
        var utc = Calendar(identifier: .gregorian)
        utc.timeZone = TimeZone(identifier: "UTC")!
        guard let base = utc.date(from: DateComponents(year: ymd.year, month: ymd.month, day: ymd.day)) else {
            return plainClock(on: date, timeZone: timeZone)
        }
        // Clamped so cos(latitude) never reaches 0 — at a pole the formula divides by it.
        let lat = min(max(p.latitude, -89.9), 89.9) * .pi / 180
        // R-FA5 — the UTC day whose solar noon falls on the LOCAL day asked about. A zone far from its meridian
        // (Pacific/Kiritimati is UTC+14 at 157° W) has its solar noon on another UTC date, and taking the same-dated
        // UTC day would hand it tomorrow's sunrise: night at local noon.
        for shift in [0.0, -1.0, 1.0] {
            let midnightUTC = base.addingTimeInterval(shift * 86_400)
            let solar = Solar(julianDay: midnightUTC.timeIntervalSince1970 / 86_400 + 2_440_587.5 + 0.5)
            let noonMinutes = 720 - 4 * p.longitude - solar.equationOfTime
            guard local.isDate(midnightUTC.addingTimeInterval(noonMinutes * 60), inSameDayAs: date) else { continue }
            let dec = solar.declination * .pi / 180
            func crossing(_ zenith: Double) -> Crossing {
                let arg = cos(zenith * .pi / 180) / (cos(lat) * cos(dec)) - tan(lat) * tan(dec)
                if arg > 1 { return .alwaysBelow }
                if arg < -1 { return .alwaysAbove }
                let halfDayMinutes = 4 * acos(arg) * 180 / .pi
                return .times(rise: midnightUTC.addingTimeInterval((noonMinutes - halfDayMinutes) * 60),
                              set: midnightUTC.addingTimeInterval((noonMinutes + halfDayMinutes) * 60))
            }
            return SunTimes(horizon: crossing(sunriseZenith), twilight: crossing(civilZenith), estimated: false)
        }
        return plainClock(on: date, timeZone: timeZone)
    }

    /// The next moment the phase can change: the soonest crossing after `date` today or tomorrow, else (a polar day or
    /// night) the next local midnight.
    static func nextBoundary(after date: Date, timeZone: TimeZone,
                             table: [String: GeoPoint] = TimeZoneCoordinates.bundled) -> Date {
        var local = Calendar(identifier: .gregorian)
        local.timeZone = timeZone
        let tomorrow = local.date(byAdding: .day, value: 1, to: local.startOfDay(for: date)) ?? date.addingTimeInterval(86_400)
        let candidates = [date, tomorrow].flatMap { day -> [Date] in
            let s = sun(on: day, timeZone: timeZone, table: table)
            return [s.horizon, s.twilight].flatMap { c -> [Date] in
                if case let .times(a, b) = c { return [a, b] }
                return []
            }
        }
        return candidates.filter { $0 > date }.min() ?? tomorrow
    }

    /// R-FA5 — a zone with no point: day 07:00–19:00 local, dusk 30 minutes either side.
    private static func plainClock(on date: Date, timeZone: TimeZone) -> SunTimes {
        var local = Calendar(identifier: .gregorian)
        local.timeZone = timeZone
        let start = local.startOfDay(for: date)
        let rise = local.date(bySettingHour: fallbackSunriseHour, minute: 0, second: 0, of: start) ?? start
        let set = local.date(bySettingHour: fallbackSunsetHour, minute: 0, second: 0, of: start) ?? start
        return SunTimes(horizon: .times(rise: rise, set: set),
                        twilight: .times(rise: rise.addingTimeInterval(-fallbackTwilight),
                                         set: set.addingTimeInterval(fallbackTwilight)),
                        estimated: true)
    }

    /// NOAA's general solar-position terms for one Julian day (degrees and minutes).
    private struct Solar {
        let declination: Double
        let equationOfTime: Double

        init(julianDay jd: Double) {
            let t = (jd - 2_451_545) / 36_525
            let l0 = (280.46646 + t * (36_000.76983 + t * 0.0003032)).truncatingRemainder(dividingBy: 360)
            let m = 357.52911 + t * (35_999.05029 - 0.0001537 * t)
            let e = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)
            func r(_ d: Double) -> Double { d * .pi / 180 }
            let c = sin(r(m)) * (1.914602 - t * (0.004817 + 0.000014 * t))
                + sin(r(2 * m)) * (0.019993 - 0.000101 * t) + sin(r(3 * m)) * 0.000289
            let omega = 125.04 - 1934.136 * t
            let lambda = l0 + c - 0.00569 - 0.00478 * sin(r(omega))
            let e0 = 23 + (26 + (21.448 - t * (46.815 + t * (0.00059 - t * 0.001813))) / 60) / 60
            let eps = e0 + 0.00256 * cos(r(omega))
            declination = asin(sin(r(eps)) * sin(r(lambda))) * 180 / .pi
            let y = pow(tan(r(eps / 2)), 2)
            equationOfTime = 4 * (y * sin(2 * r(l0)) - 2 * e * sin(r(m)) + 4 * e * y * sin(r(m)) * cos(2 * r(l0))
                - 0.5 * y * y * sin(4 * r(l0)) - 1.25 * e * e * sin(2 * r(m))) * 180 / .pi
        }
    }
}

/// Round-4 D4 (R-FA6, C7) — Settings → General → Scene, per viewer, independent of Appearance.
enum HeroScenePreference: String, CaseIterable, Identifiable {
    case automatic, day, night

    static let defaultsKey = "cicada.heroScene"
    var id: String { rawValue }

    var label: String {
        switch self {
        case .automatic: Copy.sceneAutomatic
        case .day: Copy.sceneAlwaysDay
        case .night: Copy.sceneAlwaysNight
        }
    }

    /// Absent or unknown → Automatic.
    static func stored(_ raw: String?) -> HeroScenePreference { raw.flatMap(Self.init(rawValue:)) ?? .automatic }

    func scene(clock: CicadaTheme.SkyPhase) -> CicadaTheme.SkyPhase {
        switch self {
        case .automatic: clock
        case .day: .day
        case .night: .night
        }
    }
}
```

- [ ] **Step 5: `Theme/SceneStore.swift`:**

```swift
import AppKit
import Observation

/// Round-4 D4 (R-FA6, C7) — the clock's current scene, observable, so Home's band and the Welcome's hero repaint when
/// the sun crosses a line. It holds the CLOCK only; the person's Scene choice stays in `@AppStorage` and
/// `HeroScenePreference.scene(clock:)` resolves the two. It looks again at the next boundary or within the hour,
/// whichever is first, and at once on a time-zone change or a wake — `ThemeStore.observeSystemAppearance`'s shape:
/// started once at app scope, never from `init`, so a test's store never listens to the real system.
@MainActor
@Observable
final class SceneStore {
    static let shared = SceneStore()

    private(set) var phase: CicadaTheme.SkyPhase

    @ObservationIgnored private let now: () -> Date
    @ObservationIgnored private let timeZone: () -> TimeZone
    @ObservationIgnored private let table: [String: GeoPoint]
    @ObservationIgnored private var tick: Task<Void, Never>?
    @ObservationIgnored private var observers: [(NotificationCenter, NSObjectProtocol)] = []

    init(now: @escaping () -> Date = Date.init, timeZone: @escaping () -> TimeZone = { .autoupdatingCurrent },
         table: [String: GeoPoint] = TimeZoneCoordinates.bundled) {
        self.now = now
        self.timeZone = timeZone
        self.table = table
        phase = SceneClock.phase(at: now(), timeZone: timeZone(), table: table)
    }

    func start() {
        guard observers.isEmpty else { return }
        let local = NotificationCenter.default
        observers.append((local, local.addObserver(forName: .NSSystemTimeZoneDidChange, object: nil, queue: .main) { [weak self] _ in
            NSTimeZone.resetSystemTimeZone()
            MainActor.assumeIsolated { self?.refresh() }
        }))
        let workspace = NSWorkspace.shared.notificationCenter
        observers.append((workspace, workspace.addObserver(forName: NSWorkspace.didWakeNotification, object: nil, queue: .main) { [weak self] _ in
            MainActor.assumeIsolated { self?.refresh() }
        }))
        schedule()
    }

    func refresh() {
        let next = SceneClock.phase(at: now(), timeZone: timeZone(), table: table)
        if next != phase { phase = next }
        schedule()
    }

    /// Seconds until the next look: the next crossing, capped at an hour, never under a second.
    func delayUntilNextCheck() -> TimeInterval {
        let current = now()
        let boundary = SceneClock.nextBoundary(after: current, timeZone: timeZone(), table: table)
        return min(max(boundary.timeIntervalSince(current), 1), SceneClock.maxRecheck)
    }

    private func schedule() {
        tick?.cancel()
        let delay = delayUntilNextCheck()
        tick = Task { [weak self] in
            try? await Task.sleep(for: .seconds(delay))
            guard !Task.isCancelled else { return }
            self?.refresh()
        }
    }
}
```

  (The test that expects exactly `SceneClock.maxRecheck` at noon is right because the next New York crossing after
  noon on the solstice is ~8.5 h away.)

- [ ] **Step 6: The hero** — `Views/Meadow/MeadowArt.swift`: add

```swift
    /// Round-4 D4 (R-FA4) — the hero follows the scene, not the theme: day paints the day file, dusk and night its
    /// `-dark` sibling ("painted as dusk or night"). Every other painting keeps following the theme.
    static func heroMode(for scene: CicadaTheme.SkyPhase) -> AppColorScheme { scene == .day ? .light : .dark }
```

  In `HomeHeroBand` and `WelcomeHero` add
  `@AppStorage(HeroScenePreference.defaultsKey) private var sceneRaw = HeroScenePreference.automatic.rawValue` and
  `private var scene: CicadaTheme.SkyPhase { HeroScenePreference.stored(sceneRaw).scene(clock: SceneStore.shared.phase) }`,
  and replace `mode: CicadaTheme.mode` with `mode: MeadowArt.heroMode(for: scene)`. Reword the doc comments:
  `HomeHeroBand`'s (`HomeHeroBand.swift:26-27`) "`-dark` at night through `MeadowArt.image`, which reading
  `CicadaTheme.mode` here subscribes to" and `WelcomeHero`'s (`WelcomeHero.swift:3-5`) "`-dark` in dark mode
  (`MeadowArt.image` picks it; reading `CicadaTheme.mode` here subscribes the view, so a theme flip swaps the
  painting)" both become "`-dark` at dusk and night by the clock (`SceneStore`, reading it here subscribes) and
  Settings → General → Scene — never the theme (round-4 D4, DESIGN_RULES §9 2026-09-24)". In `MeadowArt`'s type doc
  (`MeadowArt.swift:8-10`), "and the dark theme always gets it" gains "— except the hero, which follows the clock
  (`heroMode(for:)`, round-4 D4)". Both hero views keep their no-argument init (`HomeBandLayoutTests.swift:52`) and
  draw no word (`:47`).

- [ ] **Step 7: Settings → General → Scene.**
  - `SettingsRowID.swift` General block: `static let heroScene = SettingsRowID("heroScene")`.
  - `SettingsIndex.swift`: `staticIDs` → `.appearance, .heroScene, .textSize, .runSetup,`; after the Appearance entry:
    `SettingsEntry(.heroScene, .general, Copy.scene, keywords: ["painting", "picture", "home", "sky", "day", "night", "sunrise", "sunset"], detail: Copy.sceneDetail),`;
    `SettingsLiveValue.Inputs` gains `var heroScene: HeroScenePreference = .automatic` and `text(for:)` gains
    `case .heroScene: return inputs.heroScene.label`.
  - `SettingsPanel.swift`: `@AppStorage(HeroScenePreference.defaultsKey) private var heroSceneRaw = HeroScenePreference.automatic.rawValue`
    and `inputs.heroScene = .stored(heroSceneRaw)` in `liveInputs`.
  - `SettingsGeneralView.swift`: the same `@AppStorage`, a `Binding<HeroScenePreference>` like `appearance`, and after
    the Appearance row: `SettingsDivider()` then
    `SettingsRow(.heroScene, title: Copy.scene, detail: Copy.sceneDetail) { PillPicker(title: Copy.scene, selection: heroScene, options: HeroScenePreference.allCases.map { PillOption(value: $0, label: $0.label) }) }`.
    Update the view's doc comment (Scene is independent of Appearance: a dark window can show a day painting).
  - `Copy+Settings.swift` after `appearanceDark`: `scene = "Scene"`, `sceneDetail = "Home's painting follows sunrise
    and sunset in your Mac's time zone. No location is used."`, `sceneAutomatic = "Automatic"`, `sceneAlwaysDay =
    "Always day"`, `sceneAlwaysNight = "Always night"`.
- [ ] **Step 8: Start the store** — `CicadaApp.swift:114`, after `ThemeStore.shared.observeSystemAppearance()`:
  `SceneStore.shared.start()` with a one-line comment ("round-4 D4 — the hero's clock, app scope like the appearance
  observer").
- [ ] **Step 9: The §9 ruling** — append to `docs/design/DESIGN_RULES.md` §9 (a new line; old lines are never edited):

```markdown
- **2026-09-24: The Home band and the Welcome hero follow the clock, not the theme (owner, round-4 D4; G144; DR-13, DR-50).** The hero paints `hero-day` from sunrise to sunset in the Mac's time zone and its `-dark` sibling, painted as dusk or night, at dusk and at night, whatever Appearance says; Settings → General → Scene offers Automatic, Always day and Always night. This overrides R-M2's "the dark theme always gets the `-dark` painting" for the hero alone: every other painting, the empty states and the Sleep room still follow the theme. It does not touch TODO ruling 10 — `SkyBand.ships` stays off. Text never sits on the paint (DR-13, DR-50), so no contrast pair changes.
```

- [ ] **Step 10: Green + commit** — `swift test --filter 'SceneClockTests|HomeBandLayoutTests|MeadowTests|ArtAssetTests|SettingsIndexTests|SettingsRowLintTests|MeadowPlacementLintTests' 2>&1 | tail -20`,
  the Python test, `swift build`, the full `swift test`. Commit:

```
feat(meadow): Home's painting follows the clock — SceneClock, SceneStore, Settings → General → Scene (D4, G144)

Sunrise and sunset from the Mac's time zone (NOAA's equations over IANA tzdb's zone points, bundled by
scripts/gen-tz-coordinates.py — public domain, no location permission). Day paints hero-day, dusk and
night its -dark sibling; Automatic · Always day · Always night per viewer. Re-evaluates at the next
crossing or within the hour, on a time-zone change and on wake. DESIGN_RULES §9 records the owner's
override of R-M2 for the hero only; SkyBand.ships stays off.

DR-13, DR-50 (paint only), DR-16 (tokens), DR-45 (Scene is Appearance's `PillPicker`, a Settings form control — not a tab row)
```

---

### Task 3: Open at login and a background service the app can install (D3, G143)

**Files:** see the file map rows marked 3.

**Interfaces:**
- Produces `scripts/install-backend-agent.sh`; `BackendProcess.spawnCommand(installRoot:) -> (executable: URL,
  arguments: [String])`, `BackendProcess.stopSpawnedChild()`; `LoginItemStatus`, `LoginItemControlling`,
  `MainAppLoginItem`, `LoginItemState` (`derive(status:requested:error:)`, `detail`, `offersSettings`),
  `LoginItemService`; `BackendAgentState`, `BackendAgentPolicy` (`label`, `installArgv`, `isAllowed`, `probeArgv`,
  `state(probeStatus:plistExists:)`, `environment(base:installRoot:memoryRoot:)`, `display(installRoot:)`),
  `BackendAgentService`; `SettingsRowID.openAtLogin`, `.backgroundService`.
- Consumes `AgentProcessRunning` / `LiveAgentProcessRunner`, `AgentConnect.scrubbedKeys`,
  `BackendProcess.installRoot()`, `APIClient.fetchHealth()`.

- [ ] **Step 1: Failing bash-level test** — `api/tests/test_install_backend_agent.py`:

```python
"""Round-4 D3 (G143) — scripts/install-backend-agent.sh, the one source of the backend's LaunchAgent plist.

Run with a temp HOME, a temp repo whose path has a space and an ampersand, and a fake `launchctl` first on PATH
that logs its argv — the real launchd and the real ~/Library are never touched.
"""
from __future__ import annotations

import os
import plistlib
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "install-backend-agent.sh"
LABEL = "com.cicada.backend"


def _fake_launchctl(bin_dir: Path, log: Path, *, bootout_status: int = 113, bootstrap_failures: int = 0) -> None:
    counter = bin_dir / "bootstrap-count"
    counter.write_text("0")
    script = bin_dir / "launchctl"
    script.write_text(f"""#!/bin/bash
echo "$@" >> "{log}"
if [ "$1" = "bootout" ]; then exit {bootout_status}; fi
if [ "$1" = "bootstrap" ]; then
  n=$(( $(cat "{counter}") + 1 )); echo "$n" > "{counter}"
  if [ "$n" -le {bootstrap_failures} ]; then exit 5; fi
fi
exit 0
""")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)


def _setup(tmp_path: Path, *, venv: bool = True, **fake) -> tuple[dict, Path, Path, Path]:
    home = tmp_path / "home"
    repo = tmp_path / "repo dir & co"
    bin_dir = tmp_path / "bin"
    for d in (home, repo, bin_dir):
        d.mkdir(parents=True)
    if venv:
        py = repo / "api" / ".venv" / "bin" / "python"
        py.parent.mkdir(parents=True)
        py.write_text("#!/bin/sh\nexit 0\n")
        py.chmod(0o755)
    log = tmp_path / "launchctl.log"
    _fake_launchctl(bin_dir, log, **fake)
    agents = home / "Library" / "LaunchAgents"
    env = {"HOME": str(home), "PATH": f"{bin_dir}:/usr/bin:/bin", "CICADA_REPO": str(repo),
           "CICADA_MEMORY_PATH": str(tmp_path / "memory"), "LAUNCH_AGENTS_DIR": str(agents)}
    return env, repo, agents / f"{LABEL}.plist", log


def _run(env: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["/bin/bash", str(SCRIPT), *args], env=env, capture_output=True, text=True, timeout=30)


def test_it_writes_the_plist_install_sh_wrote_and_bootstraps_it(tmp_path):
    env, repo, plist_path, log = _setup(tmp_path)
    done = _run(env)
    assert done.returncode == 0, done.stderr
    plist = plistlib.loads(plist_path.read_bytes())
    py = str(repo / "api" / ".venv" / "bin" / "python")
    assert plist["Label"] == LABEL
    assert plist["ProgramArguments"] == [py, "-m", "uvicorn", "api.main:app", "--host", "127.0.0.1", "--port", "8000"]
    assert plist["WorkingDirectory"] == str(repo)
    assert plist["EnvironmentVariables"]["CICADA_MEMORY_PATH"] == env["CICADA_MEMORY_PATH"]
    assert plist["EnvironmentVariables"]["CICADA_ALLOW_FEED_FETCH"] == "1"
    assert plist["EnvironmentVariables"]["PYTHONPATH"] == str(repo)
    assert plist["RunAtLoad"] is True and plist["KeepAlive"] is True
    assert (repo / "logs").is_dir()
    uid = os.getuid()
    assert log.read_text().splitlines() == [f"bootout gui/{uid}/{LABEL}", f"bootstrap gui/{uid} {plist_path}"]


def test_it_is_idempotent(tmp_path):
    env, _, plist_path, log = _setup(tmp_path)
    assert _run(env).returncode == 0
    first = plist_path.read_bytes()
    assert _run(env).returncode == 0
    assert plist_path.read_bytes() == first
    assert sum(line.startswith("bootstrap") for line in log.read_text().splitlines()) == 2


def test_a_bootstrap_that_races_its_bootout_is_retried(tmp_path):
    env, _, _, log = _setup(tmp_path, bootstrap_failures=1)
    assert _run(env).returncode == 0
    assert sum(line.startswith("bootstrap") for line in log.read_text().splitlines()) == 2


def test_a_bootstrap_launchd_keeps_refusing_fails_loudly(tmp_path):
    env, _, _, _ = _setup(tmp_path, bootstrap_failures=9)
    done = _run(env)
    assert done.returncode == 4
    assert "backend.err.log" in done.stderr


def test_a_missing_venv_refuses_before_writing_anything(tmp_path):
    env, _, plist_path, log = _setup(tmp_path, venv=False)
    done = _run(env)
    assert done.returncode == 3
    assert not plist_path.exists()
    assert not log.exists() or log.read_text() == ""


def test_dry_run_writes_nothing(tmp_path):
    env, _, plist_path, log = _setup(tmp_path)
    done = _run(env, "--dry-run")
    assert done.returncode == 0
    assert not plist_path.exists()
    assert not log.exists() or log.read_text() == ""
    assert "bootstrap" in done.stdout


def test_install_sh_has_no_second_copy_of_the_plist():
    install = (ROOT / "install.sh").read_text()
    assert "scripts/install-backend-agent.sh" in install
    assert "<key>ProgramArguments</key>" not in install
    assert SCRIPT.read_text().count("<key>ProgramArguments</key>") == 1
```

  Run `api/.venv/bin/python -m pytest api/tests/test_install_backend_agent.py -q -p no:cacheprovider` → red (no
  script).

- [ ] **Step 2: The script** — create `scripts/install-backend-agent.sh` (`chmod +x`; bash 3.2 — no associative
  arrays, no `mapfile`, no empty `"${arr[@]}"` under `set -u`):

```bash
#!/usr/bin/env bash
#
# Install (or re-install) Cicada's background service: the launchd agent
# com.cicada.backend that keeps the backend alive whether or not the app is
# open (round-4 D3, G143).
#
# The one source of the plist. install.sh step 6 calls this after its own
# "a backend already answers /healthz -> skip" guard; the app runs it only
# after the person clicks Install in Settings -> General, as exactly
# ["/bin/bash", "<its checkout>/scripts/install-backend-agent.sh"]
# (BackendAgentPolicy), with CICADA_CAPTURE=off. Idempotent: the plist is
# rewritten from the same inputs, then the agent is booted out and in.
#
# The plist runs `$VENV_PY -m uvicorn`, never $VENV/bin/uvicorn: a venv console
# script hardcodes its interpreter in the shebang, so moving the repo breaks it
# (launchd then fails with EX_CONFIG and an empty log).
#
# Usage: scripts/install-backend-agent.sh [--dry-run]
# Env (defaults are the real locations):
#   CICADA_REPO          repo root         (default: this script's parent dir)
#   CICADA_MEMORY_PATH   memory dir        (default: ~/cicada/memory)
#   LAUNCH_AGENTS_DIR    LaunchAgents dir  (default: ~/Library/LaunchAgents)
#   CICADA_PORT          port              (default: 8000)
# Exit: 0 installed · 2 bad flag · 3 no Python environment · 4 launchd refused
set -euo pipefail

REPO="${CICADA_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
MEMORY_PATH="${CICADA_MEMORY_PATH:-$HOME/cicada/memory}"
LAUNCH_AGENTS_DIR="${LAUNCH_AGENTS_DIR:-$HOME/Library/LaunchAgents}"
PORT="${CICADA_PORT:-8000}"
VENV_PY="$REPO/api/.venv/bin/python"
PLIST_LABEL="com.cicada.backend"
PLIST_PATH="$LAUNCH_AGENTS_DIR/$PLIST_LABEL.plist"
DOMAIN="gui/$(id -u)"

DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    *) echo "Unknown flag: $arg" >&2; exit 2 ;;
  esac
done

# A path with & < > must not break the XML.
xml() { printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'; }

if [ "$DRY_RUN" -eq 1 ]; then
  echo "\$ write $PLIST_PATH (RunAtLoad+KeepAlive, $VENV_PY -m uvicorn :$PORT)"
  echo "\$ launchctl bootout $DOMAIN/$PLIST_LABEL"
  echo "\$ launchctl bootstrap $DOMAIN $PLIST_PATH"
  exit 0
fi

if [ ! -x "$VENV_PY" ]; then
  echo "Cicada's Python environment is missing at $VENV_PY — run ./install.sh first." >&2
  exit 3
fi

mkdir -p "$LAUNCH_AGENTS_DIR" "$REPO/logs"
# CICADA_ALLOW_FEED_FETCH=1 is the opt-in for the nightly RSS + ICS refresh (G114 R5).
cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$PLIST_LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$(xml "$VENV_PY")</string>
    <string>-m</string><string>uvicorn</string>
    <string>api.main:app</string>
    <string>--host</string><string>127.0.0.1</string>
    <string>--port</string><string>$PORT</string>
  </array>
  <key>WorkingDirectory</key><string>$(xml "$REPO")</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>CICADA_MEMORY_PATH</key><string>$(xml "$MEMORY_PATH")</string>
    <key>PATH</key><string>$(xml "$HOME")/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    <key>CICADA_ALLOW_FEED_FETCH</key><string>1</string>
    <key>PYTHONPATH</key><string>$(xml "$REPO")</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$(xml "$REPO")/logs/backend.out.log</string>
  <key>StandardErrorPath</key><string>$(xml "$REPO")/logs/backend.err.log</string>
</dict>
</plist>
EOF

launchctl bootout "$DOMAIN/$PLIST_LABEL" 2>/dev/null || true
# launchd can refuse a bootstrap that races its own bootout; three tries, a second apart.
for attempt in 1 2 3; do
  if launchctl bootstrap "$DOMAIN" "$PLIST_PATH" 2>/dev/null; then
    echo "Installed $PLIST_LABEL ($PLIST_PATH)"
    exit 0
  fi
  if [ "$attempt" -lt 3 ]; then sleep 1; fi
done
echo "launchd would not start $PLIST_LABEL — see $REPO/logs/backend.err.log" >&2
exit 4
```

- [ ] **Step 3: `install.sh` calls it** — replace `install.sh:330-385` (from `step "Writing launchd plist …"` through the
  dry-run `ok` of the health wait; the guard's `if` at `:327`, its `else` at `:329` and its `fi` at `:386` stay) with:

```bash
  step "Installing the background service (scripts/install-backend-agent.sh)"
  if [ "$DRY_RUN" -eq 1 ]; then
    CICADA_REPO="$REPO" CICADA_MEMORY_PATH="$MEMORY_PATH" LAUNCH_AGENTS_DIR="$LAUNCH_AGENTS_DIR" CICADA_PORT="$PORT" \
      bash "$REPO/scripts/install-backend-agent.sh" --dry-run
    ok "launchd bootstrap (dry-run)"
  else
    CICADA_REPO="$REPO" CICADA_MEMORY_PATH="$MEMORY_PATH" LAUNCH_AGENTS_DIR="$LAUNCH_AGENTS_DIR" CICADA_PORT="$PORT" \
      bash "$REPO/scripts/install-backend-agent.sh"
    step "Waiting for backend /healthz ..."
    for _ in $(seq 1 10); do
      backend_healthy && break
      sleep 1
    done
    if backend_healthy; then ok "Backend is up on :$PORT"; else warn "Backend not yet healthy — check $REPO/logs/backend.err.log"; fi
  fi
```

  Keep the `NOTE:` comment at `install.sh:44-47` (it now points at the script: "…the plist
  (scripts/install-backend-agent.sh) runs `$VENV_PY -m uvicorn`…"). The uninstall path is unchanged. Run
  `bash -n install.sh scripts/install-backend-agent.sh` and the pytest file → green; also run the existing
  `api/tests/test_agent_wiring.py test_healthz_memory_root.py test_owner_name_portability.py test_hooks_registry.py`.

- [ ] **Step 4: Failing Swift tests** — `app/CicadaApp/Tests/CicadaAppTests/BackgroundServicesTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// A login-item seam that records calls and answers what the test says.
final class FakeLoginItem: LoginItemControlling, @unchecked Sendable {
    var current: LoginItemStatus = .notRegistered
    var afterRegister: LoginItemStatus = .enabled
    var registerError: Error?
    private(set) var calls: [String] = []
    func status() -> LoginItemStatus { current }
    func register() throws {
        calls.append("register")
        if let registerError { throw registerError }
        current = afterRegister
    }
    func unregister() throws { calls.append("unregister"); current = .notRegistered }
    func openSystemSettingsLoginItems() { calls.append("settings") }
}

/// Answers `launchctl print` and the install script from a table, recording argv and environment.
final class FakeRunner: AgentProcessRunning, @unchecked Sendable {
    var answers: [String: Int32] = [:]
    private(set) var runs: [(argv: [String], env: [String: String])] = []
    func run(_ argv: [String], environment: [String: String], timeout: Duration) async -> AgentProcessResult {
        runs.append((argv, environment))
        return AgentProcessResult(status: answers[argv.joined(separator: " ")] ?? 0, stderr: "")
    }
}

/// Round-4 D3 (G143) — open at login and the background service, as pure rules plus fakes.
@MainActor
final class BackgroundServicesTests: XCTestCase {
    private let root = URL(fileURLWithPath: "/x/cicada")

    func testTheBackendSpawnsInstallShsCommand() {
        let command = BackendProcess.spawnCommand(installRoot: root)
        XCTAssertEqual(command.executable.path, "/x/cicada/api/.venv/bin/python")
        XCTAssertEqual(command.arguments, ["-m", "uvicorn", "api.main:app", "--host", "127.0.0.1", "--port", "8000"])
    }

    func testLoginItemStatesAreHonest() {
        XCTAssertEqual(LoginItemState.derive(status: .enabled, requested: true), .on)
        XCTAssertEqual(LoginItemState.derive(status: .requiresApproval, requested: true), .needsApproval)
        XCTAssertEqual(LoginItemState.derive(status: .notRegistered, requested: false), .off)
        guard case .notKept = LoginItemState.derive(status: .notRegistered, requested: true) else {
            return XCTFail("asked for, not kept: say so (D3)")
        }
        guard case .notKept = LoginItemState.derive(status: .notFound, requested: true) else { return XCTFail() }
        guard case .notKept = LoginItemState.derive(status: .enabled, requested: true, error: "x") else { return XCTFail() }
    }

    func testTurningOnRegistersAndAnUnsignedBuildSaysSo() {
        let control = FakeLoginItem()
        control.afterRegister = .notRegistered          // an ad-hoc build macOS will not keep
        let defaults = UserDefaults(suiteName: "login-\(UUID())")!
        let service = LoginItemService(control: control, defaults: defaults)
        service.setEnabled(true)
        XCTAssertEqual(control.calls, ["register"])
        XCTAssertTrue(defaults.bool(forKey: LoginItemService.requestedKey))
        guard case .notKept = service.state else { return XCTFail("never pretend") }
        XCTAssertTrue(service.state.offersSettings)
    }

    /// R-FA7 — allowed from System Settings while the intent said off: the switch reads on, like the sentence.
    func testALoginItemAllowedElsewhereReadsAsOn() {
        let control = FakeLoginItem()
        control.current = .enabled
        let defaults = UserDefaults(suiteName: "login-\(UUID())")!
        let service = LoginItemService(control: control, defaults: defaults)
        XCTAssertEqual(service.state, .on)
        XCTAssertTrue(service.requested)
        XCTAssertTrue(defaults.bool(forKey: LoginItemService.requestedKey))
        XCTAssertEqual(control.calls, [], "reading the state registers nothing")
    }

    func testASwitchOffInSystemSettingsClearsTheIntent() {
        let control = FakeLoginItem()
        let defaults = UserDefaults(suiteName: "login-\(UUID())")!
        let service = LoginItemService(control: control, defaults: defaults)
        service.setEnabled(true)
        XCTAssertEqual(service.state, .on)
        control.current = .notRegistered                // the person turned it off in System Settings
        service.refresh()
        XCTAssertEqual(service.state, .off)
        XCTAssertFalse(defaults.bool(forKey: LoginItemService.requestedKey))
    }

    func testTheInstallArgvIsPinnedToThisCheckout() {
        XCTAssertEqual(BackendAgentPolicy.installArgv(installRoot: root),
                       ["/bin/bash", "/x/cicada/scripts/install-backend-agent.sh"])
        XCTAssertTrue(BackendAgentPolicy.isAllowed(["/bin/bash", "/x/cicada/scripts/install-backend-agent.sh"], installRoot: root))
        XCTAssertFalse(BackendAgentPolicy.isAllowed(["/bin/bash", "/y/cicada/scripts/install-backend-agent.sh"], installRoot: root))
        XCTAssertFalse(BackendAgentPolicy.isAllowed(["/bin/bash", "/x/cicada/scripts/install-backend-agent.sh", "--x"], installRoot: root))
        XCTAssertFalse(BackendAgentPolicy.isAllowed(["/bin/sh", "/x/cicada/scripts/install-backend-agent.sh"], installRoot: root))
    }

    func testTheInstallEnvironmentIsScrubbedAndNeverCaptured() {
        let env = BackendAgentPolicy.environment(base: ["ANTHROPIC_API_KEY": "k", "HOME": "/h"], installRoot: root,
                                                 memoryRoot: "/m/memory")
        XCTAssertEqual(env["CICADA_CAPTURE"], "off")
        XCTAssertEqual(env["CICADA_REPO"], "/x/cicada")
        XCTAssertEqual(env["CICADA_MEMORY_PATH"], "/m/memory")
        XCTAssertNil(env["ANTHROPIC_API_KEY"])
        XCTAssertTrue(env["PATH"]?.contains("/usr/bin") ?? false)
        XCTAssertEqual(BackendAgentPolicy.environment(base: [:], installRoot: root, memoryRoot: nil)["CICADA_MEMORY_PATH"],
                       "/x/cicada/memory", "no live root: the memory BackendProcess serves (R-FA8)")
    }

    func testTheProbeReadsLaunchdWithoutChangingIt() {
        XCTAssertEqual(BackendAgentPolicy.probeArgv(uid: 501), ["/bin/launchctl", "print", "gui/501/com.cicada.backend"])
        XCTAssertEqual(BackendAgentPolicy.state(probeStatus: 0, plistExists: true), .running)
        XCTAssertEqual(BackendAgentPolicy.state(probeStatus: 113, plistExists: true), .stopped)
        XCTAssertEqual(BackendAgentPolicy.state(probeStatus: 113, plistExists: false), .missing)
        XCTAssertEqual(BackendAgentPolicy.state(probeStatus: 124, plistExists: true), .unknown)
        XCTAssertEqual(BackendAgentPolicy.state(probeStatus: 127, plistExists: false), .unknown)
    }

    func testInstallRunsTheScriptThenHandsLaunchdThePort() async throws {
        let runner = FakeRunner()
        let plist = FileManager.default.temporaryDirectory.appendingPathComponent("agent-\(UUID()).plist")
        var handedOff = false
        let service = BackendAgentService(runner: runner, installRoot: root, plistURL: plist, uid: 501,
                                          memoryRoot: { "/m/memory" }, onInstalled: { handedOff = true })
        runner.answers["/bin/launchctl print gui/501/com.cicada.backend"] = 113
        await service.refresh()
        XCTAssertEqual(service.state, .missing)
        runner.answers["/bin/launchctl print gui/501/com.cicada.backend"] = 0
        try Data().write(to: plist)
        await service.install()
        XCTAssertEqual(runner.runs.first { $0.argv.first == "/bin/bash" }?.argv, BackendAgentPolicy.installArgv(installRoot: root))
        XCTAssertTrue(handedOff)
        XCTAssertEqual(service.state, .running)
        try? FileManager.default.removeItem(at: plist)
    }

    func testAFailedInstallSaysWhy() async {
        let runner = FakeRunner()
        runner.answers["/bin/bash /x/cicada/scripts/install-backend-agent.sh"] = 3
        let service = BackendAgentService(runner: runner, installRoot: root,
                                          plistURL: URL(fileURLWithPath: "/nonexistent/agent.plist"), uid: 501,
                                          memoryRoot: { nil }, onInstalled: {})
        await service.install()
        XCTAssertEqual(service.state, .failed(Copy.backgroundNoPython), "the script's exit 3, in words")
        XCTAssertEqual(BackendAgentPolicy.failureMessage(status: 4, stderr: ""), Copy.backgroundLaunchdRefused)
        XCTAssertEqual(BackendAgentPolicy.failureMessage(status: 1, stderr: "\n  boom\nmore"), "boom")
        XCTAssertEqual(BackendAgentPolicy.failureMessage(status: 1, stderr: " \n"), Copy.backgroundInstallFailed,
                       "no words from the script: our own sentence, never the import one")
    }
}
```

- [ ] **Step 5: `BackendProcess`** — add

```swift
    /// Round-4 D3 (R-FA10) — install.sh's own command: `python -m uvicorn`, the interpreter itself as the executable.
    /// The venv's `uvicorn` console script hardcodes its interpreter in the shebang, so moving the repo broke it.
    static func spawnCommand(installRoot: URL) -> (executable: URL, arguments: [String]) {
        (installRoot.appendingPathComponent("api/.venv/bin/python"),
         ["-m", "uvicorn", "api.main:app", "--host", "127.0.0.1", "--port", "8000"])
    }

    /// R-FA8 — after the background service is installed, give launchd the port: stop only the child THIS app
    /// spawned (never a developer's uvicorn that happened to hold :8000).
    func stopSpawnedChild() {
        guard process != nil else { return }
        stop()
    }
```

  and in `start()` replace `:67-73` with `let command = Self.spawnCommand(installRoot: apiPath.deletingLastPathComponent())`,
  `proc.executableURL = command.executable`, `proc.arguments = command.arguments`.

- [ ] **Step 6: `Services/LoginItemService.swift`:**

```swift
import Foundation
import Observation
import ServiceManagement

/// `SMAppService.Status`, as the four answers Cicada acts on (any future case reads as not registered).
enum LoginItemStatus: Equatable, Sendable { case notRegistered, enabled, requiresApproval, notFound }

/// Round-4 D3 (C7) — the one seam over `SMAppService.mainApp`, so a test never touches the real login items.
protocol LoginItemControlling: Sendable {
    func status() -> LoginItemStatus
    func register() throws
    func unregister() throws
    func openSystemSettingsLoginItems()
}

struct MainAppLoginItem: LoginItemControlling {
    func status() -> LoginItemStatus {
        switch SMAppService.mainApp.status {
        case .enabled: .enabled
        case .requiresApproval: .requiresApproval
        case .notFound: .notFound
        default: .notRegistered
        }
    }
    func register() throws { try SMAppService.mainApp.register() }
    func unregister() throws { try SMAppService.mainApp.unregister() }
    func openSystemSettingsLoginItems() { SMAppService.openSystemSettingsLoginItems() }
}

/// What the Settings row says (R-FA7). `notKept` is D3's honesty: the person asked, macOS did not keep it — an
/// ad-hoc-signed build may never reach `.enabled`, and the row must not pretend it did.
enum LoginItemState: Equatable {
    case off, on, needsApproval
    case notKept(String)

    static func derive(status: LoginItemStatus, requested: Bool, error: String? = nil) -> LoginItemState {
        if requested, let error { return .notKept(error) }
        switch status {
        case .enabled: return .on
        case .requiresApproval: return .needsApproval
        case .notRegistered, .notFound: return requested ? .notKept(Copy.loginItemNotKept) : .off
        }
    }

    var detail: String {
        switch self {
        case .off: Copy.loginItemOff
        case .on: Copy.loginItemOn
        case .needsApproval: Copy.loginItemNeedsApproval
        case .notKept(let why): why
        }
    }

    var offersSettings: Bool {
        switch self {
        case .needsApproval, .notKept: true
        case .off, .on: false
        }
    }
}

@MainActor
@Observable
final class LoginItemService {
    static let requestedKey = "cicada.loginItem.requested"

    private(set) var state: LoginItemState = .off
    private(set) var requested: Bool

    @ObservationIgnored private let control: LoginItemControlling
    @ObservationIgnored private let defaults: UserDefaults
    @ObservationIgnored private var lastError: String?

    init(control: LoginItemControlling = MainAppLoginItem(), defaults: UserDefaults = .standard) {
        self.control = control
        self.defaults = defaults
        requested = defaults.bool(forKey: Self.requestedKey)
        let status = control.status()
        if status == .enabled, !requested {
            requested = true
            defaults.set(true, forKey: Self.requestedKey)
        }
        state = .derive(status: status, requested: requested)
    }

    /// Re-read macOS's answer — on appear and whenever the app becomes active (the person may have just used System
    /// Settings). A switch-off made there while Cicada ran clears the intent rather than reading as "not kept".
    func refresh() {
        let status = control.status()
        if state == .on, status == .notRegistered { remember(false) }
        // Allowed from System Settings while the intent said off: the person's answer is on (R-FA7).
        if status == .enabled, !requested { remember(true) }
        state = .derive(status: status, requested: requested, error: lastError)
    }

    func setEnabled(_ on: Bool) {
        remember(on)
        lastError = nil
        do {
            if on { try control.register() } else { try control.unregister() }
        } catch {
            // Unregistering something never registered throws; only a failed turn-on is news.
            if on { lastError = Copy.loginItemFailed(error.localizedDescription) }
        }
        refresh()
    }

    func openSystemSettings() { control.openSystemSettingsLoginItems() }

    private func remember(_ on: Bool) {
        requested = on
        defaults.set(on, forKey: Self.requestedKey)
    }
}
```

- [ ] **Step 7: `Services/BackendAgentService.swift`:**

```swift
import Foundation
import Observation

/// What Settings → General says about the background service (R-FA9).
enum BackendAgentState: Equatable {
    case checking, running, stopped, missing, unknown, installing
    case failed(String)
}

/// Round-4 D3 (R-FA8, R-FA9) — the only command the app runs for the background service, pinned to the checkout the
/// app was built from (the `AgentConnectPolicy` rule), and the read-only probe beside it.
enum BackendAgentPolicy {
    static let label = "com.cicada.backend"
    static let probeTimeout: Duration = .seconds(2)
    static let installTimeout: Duration = .seconds(30)

    static func scriptPath(installRoot: URL) -> String {
        installRoot.standardizedFileURL.path + "/scripts/install-backend-agent.sh"
    }

    static func installArgv(installRoot: URL) -> [String] { ["/bin/bash", scriptPath(installRoot: installRoot)] }

    /// What the row shows before Install, so the person sees exactly what will run (spec decision 14, D-1).
    static func display(installRoot: URL) -> String { installArgv(installRoot: installRoot).joined(separator: " ") }

    static func isAllowed(_ argv: [String], installRoot: URL) -> Bool {
        argv == installArgv(installRoot: installRoot) && !argv[1].contains("/../")
    }

    static func probeArgv(uid: uid_t) -> [String] { ["/bin/launchctl", "print", "gui/\(uid)/\(label)"] }

    /// 124 = timed out, 127 = could not start (`LiveAgentProcessRunner`'s conventions).
    static func state(probeStatus: Int32, plistExists: Bool) -> BackendAgentState {
        if probeStatus == 124 || probeStatus == 127 { return .unknown }
        if probeStatus == 0 { return .running }
        return plistExists ? .stopped : .missing
    }

    /// The script's own exit codes in words (3: no Python environment, 4: launchd refused); anything else, the
    /// script's first stderr line. Not `AgentConnect.failureMessage`, whose 3 means an unparseable settings file.
    static func failureMessage(status: Int32, stderr: String) -> String {
        switch status {
        case 3: return Copy.backgroundNoPython
        case 4: return Copy.backgroundLaunchdRefused
        default:
            let first = stderr.split(separator: "\n").map { $0.trimmingCharacters(in: .whitespaces) }.first { !$0.isEmpty }
            // Never `Copy.intakeFailed` (AgentConnect's fallback): that is the import sentence.
            return first ?? Copy.backgroundInstallFailed
        }
    }

    static func environment(base: [String: String], installRoot: URL, memoryRoot: String?) -> [String: String] {
        var env = base
        for key in AgentConnect.scrubbedKeys { env.removeValue(forKey: key) }
        env["CICADA_CAPTURE"] = "off"
        env["CICADA_REPO"] = installRoot.standardizedFileURL.path
        env["CICADA_MEMORY_PATH"] = memoryRoot?.isEmpty == false ? memoryRoot
            : installRoot.appendingPathComponent("memory").standardizedFileURL.path
        env["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"
        return env
    }
}

@MainActor
@Observable
final class BackendAgentService {
    private(set) var state: BackendAgentState = .checking

    @ObservationIgnored private let runner: AgentProcessRunning
    @ObservationIgnored let installRoot: URL
    @ObservationIgnored private let plistURL: URL
    @ObservationIgnored private let uid: uid_t
    @ObservationIgnored private let memoryRoot: () async -> String?
    @ObservationIgnored private let onInstalled: () -> Void

    init(runner: AgentProcessRunning = LiveAgentProcessRunner(),
         installRoot: URL = BackendProcess.installRoot(),
         plistURL: URL = FileManager.default.homeDirectoryForCurrentUser
             .appendingPathComponent("Library/LaunchAgents/\(BackendAgentPolicy.label).plist"),
         uid: uid_t = getuid(),
         memoryRoot: @escaping () async -> String? = { try? await APIClient.shared.fetchHealth().memoryRoot },
         onInstalled: @escaping () -> Void = {}) {
        self.runner = runner
        self.installRoot = installRoot
        self.plistURL = plistURL
        self.uid = uid
        self.memoryRoot = memoryRoot
        self.onInstalled = onInstalled
    }

    var display: String { BackendAgentPolicy.display(installRoot: installRoot) }

    func refresh() async {
        if state == .installing { return }
        let probe = await runner.run(BackendAgentPolicy.probeArgv(uid: uid), environment: ["PATH": "/usr/bin:/bin"],
                                     timeout: BackendAgentPolicy.probeTimeout)
        state = BackendAgentPolicy.state(probeStatus: probe.status,
                                         plistExists: FileManager.default.fileExists(atPath: plistURL.path))
    }

    /// Only ever from the person's click on Install.
    func install() async {
        let argv = BackendAgentPolicy.installArgv(installRoot: installRoot)
        guard BackendAgentPolicy.isAllowed(argv, installRoot: installRoot) else {
            state = .failed(Copy.backgroundRefused)
            return
        }
        state = .installing
        let env = BackendAgentPolicy.environment(base: ProcessInfo.processInfo.environment, installRoot: installRoot,
                                                 memoryRoot: await memoryRoot())
        let result = await runner.run(argv, environment: env, timeout: BackendAgentPolicy.installTimeout)
        guard result.status == 0 else {
            state = .failed(BackendAgentPolicy.failureMessage(status: result.status, stderr: result.stderr))
            return
        }
        onInstalled()
        state = .checking
        await refresh()
    }
}
```

- [ ] **Step 8: Settings rows** — `SettingsRowID.swift` General: `openAtLogin`, `backgroundService`;
  `SettingsIndex.staticIDs` → `.appearance, .heroScene, .textSize, .runSetup, .openAtLogin, .backgroundService,`; two
  entries in `staticEntries`' General block, right after the `.runSetup` entry (page order, as in `staticIDs`):
  `SettingsEntry(.openAtLogin, .general, Copy.openAtLogin, keywords: ["login", "startup", "start", "launch", "boot"])`,
  `SettingsEntry(.backgroundService, .general, Copy.keepMemoryWorking, keywords: ["background", "launchd", "service", "closed", "always on", "sync"])`
  (none of these keywords is a `testRankingFixtures` query).
  `SettingsGeneralView`: `@Environment(LoginItemService.self) private var loginItems`,
  `@Environment(BackendAgentService.self) private var backendAgent`, and a second group:

```swift
            SettingsGroupCard(header: Copy.backgroundGroup) {
                SettingsRow(.openAtLogin, title: Copy.openAtLogin, detail: loginItems.state.detail) {
                    Toggle(Copy.openAtLogin, isOn: Binding(get: { loginItems.requested },
                                                           set: { loginItems.setEnabled($0) }))
                        .toggleStyle(.switch)
                        .labelsHidden()
                } below: {
                    if loginItems.state.offersSettings {
                        TextButton(title: Copy.openLoginItems, help: Copy.openLoginItemsHelp) { loginItems.openSystemSettings() }
                    }
                }
                SettingsDivider()
                SettingsRow(.backgroundService, title: Copy.keepMemoryWorking, detail: Copy.backgroundDetail(backendAgent.state)) {
                    switch backendAgent.state {
                    case .missing, .stopped, .failed:
                        NeutralButton(title: Copy.backgroundInstall, size: .compact, help: Copy.backgroundInstallHelp) {
                            Task { await backendAgent.install() }
                        }
                    case .unknown:
                        NeutralButton(title: Copy.foundRetry, size: .compact) { Task { await backendAgent.refresh() } }
                    case .checking, .installing:
                        ProgressView().controlSize(.small)
                    case .running:
                        EmptyView()
                    }
                } below: {
                    switch backendAgent.state {
                    case .missing, .stopped, .failed: CommandBox(command: backendAgent.display)
                    default: EmptyView()
                    }
                }
            }
            .task { loginItems.refresh(); await backendAgent.refresh() }
            .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in
                loginItems.refresh()
            }
```

  Copy (`Copy+Settings.swift`): `backgroundGroup = "In the background"`, `openAtLogin = "Open Cicada at login"`,
  `loginItemOff = "Cicada opens only when you open it."`, `loginItemOn = "Cicada opens when you log in, and keeps
  working with its window closed."`, `loginItemNeedsApproval = "Almost there — allow Cicada in System Settings →
  General → Login Items."`, `loginItemNotKept = "macOS isn't opening Cicada at login. If you didn't turn it off
  there, this copy of Cicada may need adding by hand in Login Items."`, `loginItemFailed(_ why:)` → `"macOS didn't
  accept this: \(why)"`, `openLoginItems = "Open Login Items"`, `openLoginItemsHelp = "Opens System Settings →
  General → Login Items"`, `keepMemoryWorking = "Keep memory working when Cicada is closed"`,
  `backgroundDetail(_ state: BackendAgentState)` → running "On — Cicada's memory keeps working in the background.",
  stopped "Installed, but not running. Install again to restart it.", missing "Off — memory only updates while
  Cicada is open.", checking/installing "Checking…" / "Installing…", unknown "Couldn't check the background
  service.", failed(why) → why; `backgroundInstall = "Install"`, `backgroundInstallHelp = "Runs the command below
  from your Cicada folder"`, `backgroundNoPython = "Cicada's Python environment is missing — run the one-time install
  under Agents first."`, `backgroundLaunchdRefused = "macOS wouldn't start the background service. The log in your
  Cicada folder says why."`, `backgroundRefused = "Cicada only runs its own install script."`,
  `backgroundInstallFailed = "Cicada couldn't set up the background service. Try again in a moment."`.
- [ ] **Step 9: Wire the services** — `CicadaApp.swift`: `@State private var loginItems = LoginItemService()` and
  `@State private var backendAgent: BackendAgentService` built in `init` after `backend`… (`backend` is `@State`
  initialised inline — build it as a local `let backend = BackendProcess()` in `init`, assign `_backend`, and pass
  `onInstalled: { [backend] in backend.stopSpawnedChild() }`). Inject both with `.environment(...)` beside
  `.environment(localSources)`.
- [ ] **Step 10: Green + commit** — the pytest file, `swift test --filter 'BackgroundServicesTests|SettingsIndexTests|SettingsRowLintTests|SettingsSearchLandingTests' 2>&1 | tail -20`,
  `swift build`, full `swift test`, full `api/tests`. Commit:

```
feat(background): open at login + a background service the app can install (D3, G143)

LoginItemService over SMAppService.mainApp behind a seam, remembering the person's intent so an unsigned
build that macOS never enables says so. scripts/install-backend-agent.sh is now the one source of the
com.cicada.backend plist (install.sh step 6 calls it behind its healthy-skip guard); the app runs it only
after a click, argv pinned to its checkout, CICADA_CAPTURE=off, then hands launchd the port. The status is
a read-only `launchctl print`. BackendProcess spawns `python -m uvicorn` (install.sh's rule).

DR-40 (NeutralButton, TextButton), DR-19 (CommandBox), DR-59
```

---

### Task 4: Apple Calendar flows in (D2, C6)

**Files:** see the file map rows marked 4.

**Interfaces:**
- Produces `CalendarAccess`, `CalendarInfo`, `CalendarEventRecord`, `CalendarSyncPayload`, `CalendarSyncResult`,
  `CalendarStore` (protocol), `CalendarSyncAPI` (protocol), `EventKitCalendarStore`, `CalendarEventMapper`,
  `CalendarReader` (`Status`, `enabledKey`, `start()`, `connect()`, `disconnect()`, `syncNow()`, `bankChanged()`),
  `CalendarRowText`, `CalendarRow`, `SettingsRowID.calendarApp`, `APIClient.syncLocalCalendar(_:)`.
- Consumes C6's wire; `LogoImage.platformTile`; `OriginIconography.appBundleId`; `ProjectWriteFailure.detail`;
  `NeutralButton`; `Copy.cancelAction`.

- [ ] **Step 1: Failing tests** — `app/CicadaApp/Tests/CicadaAppTests/CalendarReaderTests.swift`. The plan critic
  compiled Steps 2 and 4's code and Step 6's `CalendarRowText` with this file in a scratch package (stubs for the app's
  own types) and ran it: the ten cases that need neither `bundle.sh` nor the Settings index pass; those two
  (`testThePlistAsksForCalendarAccessInPlainWords`, `testTheCalendarRowIsTheAppsAndTheChannelIsNotIndexedTwice`) need
  the whole app and are checked by the real `swift test`.

```swift
import XCTest
@testable import CicadaApp

/// EventKit, faked: what macOS answers, what the calendars hold, and a change feed the test drives.
final class FakeCalendarStore: CalendarStore, @unchecked Sendable {
    var accessValue: CalendarAccess = .notDetermined
    var grant = true
    var calendars = [CalendarInfo(id: "cal-1", title: "Work", account: "iCloud")]
    var events = [CalendarEventRecord(id: "EXT-1", calendarId: "cal-1", title: "alpha-project review",
                                      start: "2026-09-25T10:00:00+02:00", end: "2026-09-25T11:00:00+02:00",
                                      allDay: false, location: nil, notes: nil, url: nil,
                                      attendees: ["Bob Example"], organizer: nil, lastModified: nil)]
    private(set) var snapshots = 0
    private var feed: AsyncStream<Void>.Continuation?

    func access() -> CalendarAccess { accessValue }
    func requestAccess() async -> Bool {
        accessValue = grant ? .granted : .denied
        return grant
    }
    func snapshot(from: Date, to: Date) async -> (calendars: [CalendarInfo], events: [CalendarEventRecord]) {
        snapshots += 1
        return (calendars, events)
    }
    func changes() -> AsyncStream<Void> { AsyncStream { feed = $0 } }
    func change() { feed?.yield() }
}

/// C6's route, faked on the main actor (`FakeProjectsAPI`'s precedent): every payload recorded, answers from a queue
/// (one created event when the queue is empty). It has no delete to call — Disconnect never sends one.
@MainActor
final class FakeCalendarAPI: CalendarSyncAPI {
    var replies: [Result<CalendarSyncResult, any Error>] = []
    private(set) var payloads: [CalendarSyncPayload] = []
    func syncLocalCalendar(_ payload: CalendarSyncPayload) async throws -> CalendarSyncResult {
        payloads.append(payload)
        return replies.isEmpty ? CalendarSyncResult(created: 1) : try replies.removeFirst().get()
    }
}

/// Round-4 D2 (C6, R-FA11 … R-FA13) — the Calendar app's events, read only after Connect, posted in C6's shape, never
/// an empty read, and a refusal in the server's words. Synthetic calendars and people only.
@MainActor
final class CalendarReaderTests: XCTestCase {
    private let madrid = TimeZone(identifier: "Europe/Madrid")!
    private let now = ISO8601DateFormatter().date(from: "2026-09-24T08:00:00Z")!

    private func defaults() -> UserDefaults { UserDefaults(suiteName: "calendar-\(UUID())")! }

    private func reader(_ store: FakeCalendarStore, _ api: FakeCalendarAPI, _ defaults: UserDefaults,
                        debounce: Duration = .seconds(10)) -> CalendarReader {
        CalendarReader(store: store, api: api, defaults: defaults, now: { [now] in now }, debounce: debounce)
    }

    private func eventually(_ what: String, timeout: Duration = .seconds(2),
                            _ condition: () -> Bool) async throws {
        let clock = ContinuousClock()
        let deadline = clock.now.advanced(by: timeout)
        while !condition() {
            guard clock.now < deadline else { return XCTFail("timed out waiting for \(what)") }
            try await Task.sleep(for: .milliseconds(10))
        }
    }

    func testNothingIsReadBeforeConnect() async {
        let store = FakeCalendarStore()
        store.accessValue = .granted               // even with macOS's yes, the person's Connect decides (R-FA11)
        let api = FakeCalendarAPI()
        let r = reader(store, api, defaults())
        r.start()
        await Task.yield()
        XCTAssertEqual(store.snapshots, 0)
        XCTAssertEqual(api.payloads.count, 0)
        XCTAssertEqual(r.status, .off)
    }

    func testConnectAsksMacOSThenSyncsTheWindow() async throws {
        let store = FakeCalendarStore()
        let api = FakeCalendarAPI()
        let d = defaults()
        let r = reader(store, api, d)
        await r.connect()
        defer { r.disconnect() }
        XCTAssertTrue(d.bool(forKey: CalendarReader.enabledKey))
        let payload = try XCTUnwrap(api.payloads.first)
        let window = CalendarEventMapper.window(now: now)
        XCTAssertEqual(Calendar.current.dateComponents([.day], from: window.from, to: now).day, 30)
        XCTAssertEqual(Calendar.current.dateComponents([.day], from: now, to: window.to).day, 60)
        XCTAssertEqual(payload.window.from, CalendarEventMapper.iso(window.from, timeZone: .current))
        XCTAssertEqual(payload.window.to, CalendarEventMapper.iso(window.to, timeZone: .current))
        XCTAssertNotNil(payload.window.from.range(of: #"(Z|[+-]\d\d:\d\d)$"#, options: .regularExpression),
                        "ISO-8601 with its offset (C6)")
        XCTAssertEqual(payload.calendars, store.calendars)
        XCTAssertEqual(payload.events, store.events)
        XCTAssertEqual(r.status, .synced(at: now, events: 1))
    }

    func testADeniedPromptStaysOffAndSaysWhere() async {
        let store = FakeCalendarStore()
        store.grant = false
        let api = FakeCalendarAPI()
        let d = defaults()
        let r = reader(store, api, d)
        await r.connect()
        XCTAssertEqual(r.status, .denied)
        XCTAssertFalse(d.bool(forKey: CalendarReader.enabledKey))
        XCTAssertEqual(api.payloads.count, 0)
        XCTAssertEqual(store.snapshots, 0)
    }

    func testDisconnectStopsEveryTriggerAndDeletesNothing() async throws {
        let store = FakeCalendarStore()
        let api = FakeCalendarAPI()
        let r = reader(store, api, defaults(), debounce: .milliseconds(20))
        await r.connect()
        XCTAssertEqual(api.payloads.count, 1)
        r.disconnect()
        store.change()
        await r.syncNow()
        try await Task.sleep(for: .milliseconds(120))
        XCTAssertEqual(api.payloads.count, 1, "no trigger survives Disconnect")
        XCTAssertEqual(r.status, .off)
    }

    func testChangesAreDebounced() async throws {
        let store = FakeCalendarStore()
        let api = FakeCalendarAPI()
        let r = reader(store, api, defaults(), debounce: .milliseconds(50))
        await r.connect()
        defer { r.disconnect() }
        XCTAssertEqual(api.payloads.count, 1)
        store.change(); store.change(); store.change()
        try await eventually("the debounced sync") { api.payloads.count >= 2 }
        try await Task.sleep(for: .milliseconds(150))
        XCTAssertEqual(api.payloads.count, 2, "three changes inside the debounce are one sync")
    }

    /// R-FA11 — an empty read (EventKit not ready) is never posted: C6 would tombstone the whole window.
    func testAReadWithNoCalendarsIsNeverPosted() async {
        let store = FakeCalendarStore()
        store.calendars = []
        store.events = []
        let api = FakeCalendarAPI()
        let r = reader(store, api, defaults())
        await r.connect()
        defer { r.disconnect() }
        XCTAssertEqual(api.payloads.count, 0)
        XCTAssertEqual(r.status, .failed(Copy.calendarNotReady))
    }

    /// Access taken away in System Settings while Cicada runs: the next sync reads nothing and says where to look.
    func testRevokedAccessStopsTheNextSync() async {
        let store = FakeCalendarStore()
        let api = FakeCalendarAPI()
        let r = reader(store, api, defaults())
        await r.connect()
        defer { r.disconnect() }
        store.accessValue = .denied
        await r.syncNow()
        XCTAssertEqual(api.payloads.count, 1)
        XCTAssertEqual(r.status, .denied)
    }

    func testARefusalIsShownInTheServersWords() async {
        let store = FakeCalendarStore()
        let api = FakeCalendarAPI()
        let refusal = "Cicada has its demo memory open. It only holds made-up examples."
        api.replies = [.failure(APIError.httpError(409, #"{"detail":"\#(refusal)"}"#))]
        let r = reader(store, api, defaults())
        await r.connect()
        defer { r.disconnect() }
        XCTAssertEqual(r.status, .failed(refusal))
        XCTAssertEqual(CalendarReader.failureMessage(APIError.httpError(404, #"{"detail":"Not Found"}"#)),
                       Copy.calendarNeedsUpdate, "a backend without C6")
        XCTAssertEqual(CalendarReader.failureMessage(APIError.httpError(405, "")), Copy.calendarNeedsUpdate)
        XCTAssertEqual(CalendarReader.failureMessage(APIError.serverUnreachable), Copy.calendarBackendDown)
        XCTAssertEqual(CalendarReader.failureMessage(URLError(.cannotConnectToHost)), Copy.calendarBackendDown,
                       "APIClient passes a refused connection through as a URLError")
        XCTAssertEqual(CalendarReader.failureMessage(APIError.httpError(500, "boom")), Copy.calendarSyncFailed)
    }

    func testTheMapperKeepsTheContract() {
        var c = Calendar(identifier: .gregorian)
        c.timeZone = madrid
        let occurrence = c.date(from: DateComponents(year: 2026, month: 9, day: 24, hour: 10))!
        XCTAssertEqual(CalendarEventMapper.id(externalId: "EXT-1", itemId: "LOCAL-1", recurring: true,
                                              occurrence: occurrence, timeZone: madrid),
                       "EXT-1|2026-09-24T10:00:00+02:00")
        XCTAssertEqual(CalendarEventMapper.id(externalId: "EXT-1", itemId: "LOCAL-1", recurring: false,
                                              occurrence: occurrence, timeZone: madrid), "EXT-1")
        XCTAssertEqual(CalendarEventMapper.id(externalId: nil, itemId: "LOCAL-1", recurring: false,
                                              occurrence: occurrence, timeZone: madrid), "LOCAL-1")
        XCTAssertEqual(CalendarEventMapper.person(name: nil, url: URL(string: "mailto:bob-example@example.com")),
                       "bob-example@example.com")
        XCTAssertEqual(CalendarEventMapper.person(name: "Bob Example", url: URL(string: "mailto:bob-example@example.com")),
                       "Bob Example")
        XCTAssertNil(CalendarEventMapper.person(name: "  ", url: nil))
        XCTAssertEqual(CalendarEventMapper.notes(String(repeating: "a", count: 12_000))?.count, 10_000)
        XCTAssertNil(CalendarEventMapper.notes(""))
        XCTAssertTrue(CalendarEventMapper.iso(occurrence, timeZone: madrid).hasSuffix("+02:00"))
    }

    func testThePlistAsksForCalendarAccessInPlainWords() throws {
        let bundleScript = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()   // CicadaAppTests
            .deletingLastPathComponent()   // Tests
            .deletingLastPathComponent()   // CicadaApp
            .appendingPathComponent("bundle.sh")
        let text = try String(contentsOf: bundleScript, encoding: .utf8)
        for key in ["NSCalendarsFullAccessUsageDescription", "NSCalendarsUsageDescription"] {
            XCTAssertEqual(text.components(separatedBy: "<key>\(key)</key>").count - 1, 1, key)
            XCTAssertNotNil(text.range(of: "<key>\(key)</key><string>[^<]{20,}</string>", options: .regularExpression),
                            "\(key) says why, in words")
        }
    }

    /// R-FA13 — the row is the app's; the backend's `calendar-local` channel is never a second row or search entry.
    func testTheCalendarRowIsTheAppsAndTheChannelIsNotIndexedTwice() {
        XCTAssertEqual(IntegrationCategory.of(channelId: "calendar-local"), .feedsAndCalendars)
        let dynamic = SettingsIndex.dynamicEntries(channels: [SourceChannel(id: "calendar-local", label: "Calendar")],
                                                   harnessRows: [], exportOnly: [], connections: [], agents: [])
        XCTAssertFalse(dynamic.contains { $0.id == .channel("calendar-local") })
        XCTAssertTrue(SettingsIndex.staticEntries.contains { $0.id == .calendarApp && $0.section == .integrations })
        XCTAssertEqual(OriginIconography.appBundleId(for: "calendar-local"), "com.apple.iCal",
                       "the installed Calendar app's icon, never a committed Apple mark (DR-52)")
        XCTAssertEqual(OriginIconography.symbol(for: "calendar-local"), "calendar")
    }

    func testTheRowSaysWhereThingsStand() {
        let us = Locale(identifier: "en_US")
        XCTAssertEqual(CalendarRowText.line(.off, channel: nil, now: now, locale: us), Copy.calendarOff)
        XCTAssertEqual(CalendarRowText.line(.denied, channel: nil, now: now, locale: us), Copy.calendarDenied)
        XCTAssertEqual(CalendarRowText.line(.syncing, channel: nil, now: now, locale: us), Copy.calendarSyncing)
        XCTAssertEqual(CalendarRowText.line(.synced(at: now.addingTimeInterval(-120), events: 1204), channel: nil,
                                            now: now, locale: us),
                       "Synced 2 minutes ago · 1,204 events")
        XCTAssertEqual(CalendarRowText.line(.failed("x"), channel: nil, now: now, locale: us), "x")
        let broken = SourceChannel(id: "calendar-local", label: "Calendar", lastError: "The last sync failed.")
        XCTAssertEqual(CalendarRowText.line(.synced(at: now, events: 3), channel: broken, now: now, locale: us),
                       "The last sync failed.", "the backend's own error wins over a stale success")
    }
}
```

- [ ] **Step 2: Models + mapper** — `Services/Calendar/CalendarModels.swift`:

```swift
import Foundation

/// Round-4 D2 (C6) — what the app sends `POST /sources/calendar-local/sync`. Encodable in C6's exact shape; every
/// time is ISO-8601 with its offset. The app reads the calendars (EventKit, the ~/Library rail); the backend stages,
/// scrubs and tombstones.
struct CalendarInfo: Encodable, Equatable, Sendable {
    let id: String
    let title: String
    let account: String?
}

struct CalendarEventRecord: Encodable, Equatable, Sendable {
    let id: String
    let calendarId: String
    let title: String
    let start: String
    let end: String
    let allDay: Bool
    let location: String?
    let notes: String?
    let url: String?
    let attendees: [String]?
    let organizer: String?
    let lastModified: String?
}

struct CalendarSyncPayload: Encodable, Equatable, Sendable {
    struct Window: Encodable, Equatable, Sendable {
        let from: String
        let to: String
    }
    let window: Window
    let calendars: [CalendarInfo]
    let events: [CalendarEventRecord]
}

/// C6's answer; lenient, so a backend one field ahead or behind never fails the sync.
struct CalendarSyncResult: Decodable, Equatable, Sendable {
    var created = 0
    var updated = 0
    var unchanged = 0
    var tombstoned = 0
    var bank = ""

    init(created: Int = 0, updated: Int = 0, unchanged: Int = 0, tombstoned: Int = 0, bank: String = "") {
        self.created = created; self.updated = updated; self.unchanged = unchanged
        self.tombstoned = tombstoned; self.bank = bank
    }

    enum CodingKeys: String, CodingKey { case created, updated, unchanged, tombstoned, bank }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        created = c.lenient(.created, 0)
        updated = c.lenient(.updated, 0)
        unchanged = c.lenient(.unchanged, 0)
        tombstoned = c.lenient(.tombstoned, 0)
        bank = c.lenient(.bank, "")
    }
}

enum CalendarAccess: Equatable, Sendable { case notDetermined, granted, denied, restricted, writeOnly }

/// The seam over EventKit (C7), so a test never asks macOS for anything.
protocol CalendarStore: AnyObject, Sendable {
    func access() -> CalendarAccess
    func requestAccess() async -> Bool
    /// Every calendar and every event between the two dates, already mapped.
    func snapshot(from: Date, to: Date) async -> (calendars: [CalendarInfo], events: [CalendarEventRecord])
    func changes() -> AsyncStream<Void>
}

protocol CalendarSyncAPI: Sendable {
    func syncLocalCalendar(_ payload: CalendarSyncPayload) async throws -> CalendarSyncResult
}

/// Pure pieces of the EventKit mapping (R-FA11).
enum CalendarEventMapper {
    static let notesCap = 10_000
    static let daysBack = 30
    static let daysAhead = 60

    static func window(now: Date, calendar: Calendar = .current) -> (from: Date, to: Date) {
        (calendar.date(byAdding: .day, value: -daysBack, to: now) ?? now,
         calendar.date(byAdding: .day, value: daysAhead, to: now) ?? now)
    }

    static func iso(_ date: Date, timeZone: TimeZone) -> String {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        f.timeZone = timeZone
        return f.string(from: date)
    }

    /// C6 — `calendarItemExternalIdentifier`, plus `|` and the occurrence's start for a recurring event (every
    /// occurrence shares the external id); the local identifier only when the external one is missing.
    static func id(externalId: String?, itemId: String, recurring: Bool, occurrence: Date, timeZone: TimeZone) -> String {
        let base = (externalId?.isEmpty == false ? externalId : nil) ?? itemId
        return recurring ? "\(base)|\(iso(occurrence, timeZone: timeZone))" : base
    }

    /// A person as the calendar names them: their display name, else their address without `mailto:`.
    static func person(name: String?, url: URL?) -> String? {
        if let name = name?.trimmingCharacters(in: .whitespacesAndNewlines), !name.isEmpty { return name }
        guard let url else { return nil }
        let raw = url.absoluteString
        let address = raw.lowercased().hasPrefix("mailto:") ? String(raw.dropFirst("mailto:".count)) : raw
        return address.isEmpty ? nil : address
    }

    static func notes(_ raw: String?) -> String? {
        guard let raw, !raw.isEmpty else { return nil }
        return raw.count > notesCap ? String(raw.prefix(notesCap)) : raw
    }
}
```

- [ ] **Step 3: EventKit** — `Services/Calendar/EventKitCalendarStore.swift` (`import EventKit`), a
  `final class EventKitCalendarStore: CalendarStore, @unchecked Sendable` owning one `EKEventStore`:
  `access()` maps `EKEventStore.authorizationStatus(for: .event)` (`.fullAccess` → `.granted`, `.writeOnly`,
  `.denied`, `.restricted`, `.notDetermined`; `@unknown default` → `.denied`); `requestAccess()` is
  `(try? await store.requestFullAccessToEvents()) ?? false`; `snapshot(from:to:)` runs
  `store.predicateForEvents(withStart:end:calendars: nil)` + `store.events(matching:)` inside
  `Task.detached(priority: .utility)` (a large window is slow; never on the main actor), maps each `EKCalendar` to
  `CalendarInfo(id: calendarIdentifier, title: title, account: source?.title)` and each `EKEvent` through
  `CalendarEventMapper` (`timeZone: event.timeZone ?? .current`; `recurring: event.hasRecurrenceRules`;
  `occurrence: event.occurrenceDate ?? event.startDate`; attendees `event.attendees?.compactMap { person(name: $0.name, url: $0.url) }`;
  organizer the same; `url?.absoluteString`; `lastModifiedDate` through `iso`); `changes()` wraps
  `NotificationCenter.default.notifications(named: .EKEventStoreChanged, object: store)` in an `AsyncStream`.
  Doc: why app-side (the ~/Library rail; the backend has no calendar access and needs none), and that nothing is
  written back (read-only access is all Cicada uses, though macOS only offers full access for reading).
- [ ] **Step 4: The reader** — `Services/Calendar/CalendarReader.swift`:

```swift
import Foundation
import Observation

/// Round-4 D2 (C7) — the Calendar app's events, read by the APP through EventKit and posted to the backend, which
/// stages them like every other source. Never read before the person clicks Connect and macOS says yes (R-FA11);
/// then on launch, on a calendar change (debounced), every few hours while Cicada runs, after a bank switch, and on
/// Sync now. Disconnect stops all of it and deletes nothing.
@MainActor
@Observable
final class CalendarReader {
    enum Status: Equatable {
        case off, denied, syncing
        case synced(at: Date, events: Int)
        case failed(String)
    }

    static let enabledKey = "cicada.calendar.enabled"

    private(set) var status: Status = .off
    var isEnabled: Bool { defaults.bool(forKey: Self.enabledKey) }

    @ObservationIgnored private let store: CalendarStore
    @ObservationIgnored private let api: CalendarSyncAPI
    @ObservationIgnored private let defaults: UserDefaults
    @ObservationIgnored private let now: () -> Date
    @ObservationIgnored private let debounce: Duration
    @ObservationIgnored private let period: Duration
    @ObservationIgnored private var watch: Task<Void, Never>?
    @ObservationIgnored private var periodic: Task<Void, Never>?
    @ObservationIgnored private var pending: Task<Void, Never>?
    @ObservationIgnored private var inFlight = false
    /// A trigger that landed while a sync was in flight: run once more after it (R-FA11), never two at once.
    @ObservationIgnored private var again = false

    init(store: CalendarStore = EventKitCalendarStore(), api: CalendarSyncAPI = APIClient.shared,
         defaults: UserDefaults = .standard, now: @escaping () -> Date = Date.init,
         debounce: Duration = .seconds(10), period: Duration = .seconds(3 * 60 * 60)) {
        self.store = store; self.api = api; self.defaults = defaults; self.now = now
        self.debounce = debounce; self.period = period
    }

    /// On launch: arm and catch up, only if the person connected before and macOS still says yes.
    func start() {
        guard isEnabled else { status = .off; return }
        guard store.access() == .granted else { status = .denied; return }
        arm()
        Task { await sync() }
    }

    func connect() async {
        guard await store.requestAccess(), store.access() == .granted else {
            defaults.set(false, forKey: Self.enabledKey)
            status = .denied
            return
        }
        defaults.set(true, forKey: Self.enabledKey)
        arm()
        await sync()
    }

    func disconnect() {
        defaults.set(false, forKey: Self.enabledKey)
        watch?.cancel(); periodic?.cancel(); pending?.cancel()
        watch = nil; periodic = nil; pending = nil
        again = false
        status = .off
    }

    func syncNow() async { guard isEnabled else { return }; await sync() }

    /// A bank switch: the new memory gets the calendar too (409 if it is the demo, said in words).
    func bankChanged() async { await syncNow() }

    private func arm() {
        guard watch == nil else { return }
        let stream = store.changes()
        watch = Task { [weak self] in
            for await _ in stream { self?.scheduleDebounced() }
        }
        periodic = Task { [weak self, period] in
            while !Task.isCancelled {
                try? await Task.sleep(for: period)
                guard !Task.isCancelled else { return }
                await self?.syncNow()
            }
        }
    }

    private func scheduleDebounced() {
        guard isEnabled else { return }
        pending?.cancel()
        pending = Task { [weak self, debounce] in
            try? await Task.sleep(for: debounce)
            guard !Task.isCancelled else { return }
            await self?.syncNow()
        }
    }

    private func sync() async {
        guard !inFlight else { again = true; return }
        inFlight = true
        defer { inFlight = false }
        repeat {
            again = false
            // Access can be taken away in System Settings while Cicada runs; a read without it comes back empty.
            guard store.access() == .granted else { status = .denied; return }
            status = .syncing
            let window = CalendarEventMapper.window(now: now())
            let snapshot = await store.snapshot(from: window.from, to: window.to)
            // R-FA11 — C6 tombstones every saved event the window no longer holds, so a read with no calendars at
            // all (EventKit not ready, access gone mid-read) is never posted: it would mark the whole window deleted.
            guard !snapshot.calendars.isEmpty else { status = .failed(Copy.calendarNotReady); return }
            let payload = CalendarSyncPayload(
                window: .init(from: CalendarEventMapper.iso(window.from, timeZone: .current),
                              to: CalendarEventMapper.iso(window.to, timeZone: .current)),
                calendars: snapshot.calendars, events: snapshot.events)
            do {
                let result = try await api.syncLocalCalendar(payload)
                guard isEnabled else { status = .off; return }   // Disconnect landed while this one was posting
                status = .synced(at: now(), events: result.created + result.updated + result.unchanged)
            } catch {
                guard isEnabled else { status = .off; return }
                status = .failed(Self.failureMessage(error))
                return
            }
        } while again && isEnabled
    }

    /// R-FA12 — a 409's detail is written for the person (the demo refusal, `ProjectWriteFailure.detail` — the one
    /// FastAPI-detail parser); a backend without C6 answers 404/405; a backend that is not up at all fails in
    /// `URLSession` itself (`URLError`: connection refused, timed out), which `APIClient` passes through unwrapped.
    static func failureMessage(_ error: Error) -> String {
        if error is URLError { return Copy.calendarBackendDown }
        guard let api = error as? APIError else { return Copy.calendarSyncFailed }
        switch api {
        case .httpError(409, let body): return ProjectWriteFailure.detail(body) ?? Copy.calendarSyncFailed
        case .httpError(404, _), .httpError(405, _): return Copy.calendarNeedsUpdate
        case .serverUnreachable: return Copy.calendarBackendDown
        default: return Copy.calendarSyncFailed
        }
    }
}
```

  `APIClient.swift`, beside `postWisprFlow` (`:1759`): `func syncLocalCalendar(_ payload: CalendarSyncPayload) async
  throws -> CalendarSyncResult { try await postData("/sources/calendar-local/sync", json: try JSONEncoder().encode(payload)) }`
  and, in the Calendar file, `extension APIClient: CalendarSyncAPI {}`.
- [ ] **Step 5: Info.plist** — `app/CicadaApp/bundle.sh`, inside the `<dict>` after `NSPrincipalClass`:

```xml
  <key>NSCalendarsFullAccessUsageDescription</key><string>Cicada reads your calendar events so your meetings and plans become part of your memory. Nothing leaves this Mac.</string>
  <key>NSCalendarsUsageDescription</key><string>Cicada reads your calendar events so your meetings and plans become part of your memory. Nothing leaves this Mac.</string>
```

  (The legacy key covers a macOS that predates full access; the floor is 14, where the full-access key is the one
  asked. Both are harmless.)
- [ ] **Step 6: The row** — `Views/Settings/CalendarRow.swift`. The pure line first (the plan critic ran it against
  `testTheRowSaysWhereThingsStand`):

```swift
/// R-FA13 — the Calendar row's one line, pure (`CalendarReaderTests`). The time in full words, computed when read
/// (DR-58; never "2mo ago"), every count through `UsageFormat.count` (DR-21), and the backend's own `lastError` for the
/// `calendar-local` channel over a stale success.
enum CalendarRowText {
    static func line(_ status: CalendarReader.Status, channel: SourceChannel?, now: Date,
                     locale: Locale = .autoupdatingCurrent) -> String {
        switch status {
        case .off: return Copy.calendarOff
        case .denied: return Copy.calendarDenied
        case .syncing: return Copy.calendarSyncing
        case .failed(let why): return why
        case .synced(let at, let events):
            if let error = channel?.lastError, !error.isEmpty { return error }
            let relative = RelativeDateTimeFormatter()
            relative.unitsStyle = .full
            relative.dateTimeStyle = .named     // "now", never "in 0 seconds"
            relative.locale = locale
            return Copy.calendarSynced(relative.localizedString(for: at, relativeTo: now), events: events, locale: locale)
        }
    }
}
```

  Then `struct CalendarRow: View` (`let channel: SourceChannel?`, `@Environment(CalendarReader.self) private var reader`,
  `@State private var confirmStop = false`), laid out like `WisprFlowRow` (`LocalSourceRows.swift:449-493`: an `HStack`
  of mark, a title-over-line `VStack`, `Spacer`, the actions; the same paddings): mark
  `LogoImage.platformTile(name: "", bundleId: OriginIconography.appBundleId(for: "calendar-local"), size:
  CicadaTheme.scaled(28), systemFallback: OriginIconography.symbol(for: "calendar-local"))` (the installed Calendar
  app's icon — never a committed Apple mark, DR-52); title `Copy.calendarAppTitle` in
  `CicadaTheme.font(size: 13, weight: .medium)`; the line from
  `CalendarRowText.line(reader.status, channel: channel, now: Date())` in `captionFont`, `danger` when `.failed` or the
  channel has a `lastError`, else `textSecondary`. The actions are DR-40's `NeutralButton(size: .compact)` — this row is
  new, so it follows DESIGN_RULES rather than its pre-D siblings' `.bordered` (DR-40: "none is hand-rolled"):
  `.off` → Connect (`Task { await reader.connect() }`); `.denied` → Open Privacy Settings (opens
  `x-apple.systempreferences:com.apple.preference.security?Privacy_Calendars` through `NSWorkspace`) **and** Connect
  (after the person turns access on there, Connect asks again and — with access now given — syncs; nothing re-reads on
  its own); `.syncing` → Sync now with `isDisabled: true` + Disconnect; `.synced`/`.failed` → Sync now + Disconnect.
  Disconnect sets `confirmStop` and sits behind a `.confirmationDialog(Copy.calendarStopTitle, isPresented:
  $confirmStop)` whose `Button(Copy.calendarStop, role: .destructive) { reader.disconnect() }`, `Button(Copy.cancelAction,
  role: .cancel) {}` (`Copy+Settings.swift:141`) and message `Text(Copy.calendarStopDetail)` follow `LocalSourceRows.swift:436`'s precedent (DR-40: a
  disconnect behind a confirmation; the dialog's destructive role carries the danger colour). `.settingsRow(.calendarApp)`
  on the row, exactly once (`SettingsRowLintTests`). No popover (`SettingsSheetLintTests`).
  Copy (`Copy+Settings.swift`): `calendarAppTitle = "Calendar on this Mac"`, `calendarOff = "Not connected — Connect asks
  macOS to share your calendars. Nothing leaves this Mac."`, `calendarDenied = "Calendar access is off for Cicada — turn
  it on in System Settings → Privacy & Security → Calendars, then Connect again."`, `calendarSyncing = "Syncing…"`,
  `calendarSynced(_ when: String, events: Int, locale: Locale = .autoupdatingCurrent)` →
  `"Synced \(when) · \(events == 1 ? "1 event" : "\(UsageFormat.count(events, locale: locale)) events")"`,
  `calendarNeedsUpdate = "This version of Cicada's background service can't read calendars yet — update Cicada."`,
  `calendarBackendDown = "Cicada's background service isn't answering."`, `calendarSyncFailed = "Couldn't sync your
  calendars. Cicada will try again."`, `calendarNotReady = "Your calendars aren't ready to read yet — Cicada will try
  again."`, `calendarConnect = "Connect"`, `calendarSyncNow = "Sync now"`, `calendarDisconnect = "Disconnect"`,
  `openPrivacySettings = "Open Privacy Settings"`, `calendarStopTitle = "Stop reading your calendars?"`,
  `calendarStopDetail = "Events already in your memory stay there."`, `calendarStop = "Stop reading"`.
- [ ] **Step 7: Integrations** — `IntegrationCategory.of`: `case "rss", "calendar", "calendar-local": return
  .feedsAndCalendars` (update the doc's channel count sentence). `IntegrationsView`: `extraRowCount` gains
  `case .feedsAndCalendars: 1`; the rows `ForEach` skips `"calendar-local"` like Wispr Flow; after the rows,
  `if category == .feedsAndCalendars { CalendarRow(channel: rows.first { $0.id == "calendar-local" }) }`.
  `IntegrationsViewTests.testEveryChannelIdHasACategory`'s list gains `("calendar-local", .feedsAndCalendars)` (the
  switch and that list change together). `SettingsRowID`: `static let calendarApp = SettingsRowID("calendarApp")` (a new
  `// Integrations (round-4 D2)` block). `SettingsIndex.staticIDs` gains `.calendarApp` after `.sleepEngine` and before
  `.agentsInstall` (Integrations sits between Sleep and Agents in the sidebar), and `staticEntries` gains, at the same
  place under a `// Integrations` comment, `SettingsEntry(.calendarApp, .integrations, Copy.calendarAppTitle, keywords:
  ["calendar", "events", "meetings", "icloud", "google calendar", "exchange", "schedule"])` — the first static entry of
  that section. `dynamicEntries` maps `channels.filter { $0.id != "calendar-local" }` (R-FA13).
  `SettingsRowLintTests` requires the row to live under `Views/Settings/` — it does. `OriginIconography`: `label(for:)`
  `case "calendar-local": "Calendar"`, `symbol(for:)` `case "calendar", "calendar-local": "calendar"` (else it falls to
  `tray` on the Sources grid, where `origin(forChannel:)` passes the id through), `appBundleId(for:)`
  `case "calendar-local": "com.apple.iCal"`, and `"calendar-local"` in `allKnownOrigins` with a comment that the backend
  track stamps it (C6, R-FA13). `logoName(for:)` stays nil for it: Apple's marks are never committed (Track L).
- [ ] **Step 8: Wire** — `CicadaApp.swift`: `@State private var calendarReader = CalendarReader()`; inject with
  `.environment(calendarReader)` beside `.environment(localSources)`; in `.onAppear` after
  `localSources.start(store: store)`: `calendarReader.start()` (`.onAppear` fires again when the window is reopened —
  `arm()` is guarded, so that costs one catch-up sync and nothing more); in the existing `.onChange(of: store.bank)`:
  `Task { await calendarReader.bankChanged() }` beside `localSources.reload()`.
- [ ] **Step 9: Green + commit** — `swift test --filter 'CalendarReaderTests|IntegrationsViewTests|SettingsIndexTests|SettingsRowLintTests|OriginIconographyTests|PlatformFloorTests' 2>&1 | tail -20`,
  `swift build`, full `swift test`. Commit:

```
feat(calendar): the Calendar app's events flow in through EventKit (D2, C6)

CalendarReader reads every calendar on the Mac (30 days back, 60 ahead) only after Connect and macOS's
full-access prompt, and posts C6's payload on launch, on EKEventStoreChanged (debounced), every 3 hours,
after a bank switch and on Sync now. Disconnect stops it and deletes nothing. A demo bank's 409 is shown
in the server's own words; a backend without the route says to update. Settings → Integrations → Feeds &
calendars gains "Calendar on this Mac" with the installed Calendar app's icon.

DR-52 (installed-app mark), DR-40 (confirmation on disconnect), DR-21 (UsageFormat), DR-59
```

---

### Task 5: Every agent write shows who wrote it (C3, C4)

**Files:** see the file map rows marked 5.

**Interfaces:**
- Produces `ModelNames` (`capturingHarnesses`, `display(_:)`, `effort(_:)`, `line(model:effort:)`,
  `agentLine(agent:harness:model:effort:)`); `Claim.authorModel`, `.authorEffort`; `Evidence.model`, `.effort`;
  `EpisodeTurn.model`, `.effort`; `EpisodeText.agent: EpisodeAgent?`; `ProvenanceContributor.models:
  [ContributorModel]`; `EvidenceChipModel.model` / `.effort` (computed); `EvidenceLabel.label(_:meta:)`;
  `ProvenanceSummary.modelsLine(_:)`, `modelsHelp(_:)`; `Copy.Provenance.modelNotShared`.
- Consumes C3/C4 fields (all optional); `EvidenceSpeaker.agentName`, `OriginIconography.label`.

- [ ] **Step 1: Failing tests** — `app/CicadaApp/Tests/CicadaAppTests/ModelNamesTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// Round-4 C3/C4 (D1, R-FA14) — a model id as a person reads it, and every surface that names who wrote a belief.
final class ModelNamesTests: XCTestCase {
    func testModelIdsReadAsPeopleSayThem() {
        let table: [(String, String)] = [
            ("claude-opus-5-5", "Opus 5.5"), ("claude-sonnet-5", "Sonnet 5"), ("gpt-5.5-codex", "GPT-5.5 Codex"),
            ("claude-opus-5-5[1m]", "Opus 5.5"), ("claude-sonnet-4-5-20250929", "Sonnet 4.5"),
            ("claude-3-5-sonnet-20241022", "Sonnet 3.5"), ("claude-haiku-4-5", "Haiku 4.5"),
            ("gpt-4o-mini", "GPT-4o mini"), ("gemini-2.5-pro", "Gemini 2.5 Pro"),
            ("o3", "o3"), ("llama3.1:8b", "llama3.1:8b"), ("claude-mystery-x", "claude-mystery-x"), ("", ""),
        ]
        for (raw, expected) in table { XCTAssertEqual(ModelNames.display(raw), expected, raw) }
    }

    func testEffortInWords() {
        XCTAssertEqual(ModelNames.effort("high"), "high effort")
        XCTAssertEqual(ModelNames.effort("XHIGH"), "extra-high effort")
        XCTAssertEqual(ModelNames.effort("max"), "max effort")
        XCTAssertNil(ModelNames.effort("turbo"), "an unknown level says nothing rather than a guess")
        XCTAssertNil(ModelNames.effort(nil))
    }

    func testTheAgentLine() {
        XCTAssertEqual(ModelNames.agentLine(agent: "Claude Code", harness: "claude-code", model: "claude-opus-5-5", effort: "high"),
                       "Claude Code · Opus 5.5 · high effort")
        XCTAssertEqual(ModelNames.agentLine(agent: "Claude Desktop", harness: "claude-desktop", model: nil, effort: nil),
                       "Claude Desktop · model not shared by this app", "D1 — an app with no capture says so")
        XCTAssertEqual(ModelNames.agentLine(agent: "Claude Code", harness: "claude-code", model: nil, effort: nil),
                       "Claude Code", "a capturing harness before D1: nothing added, never a guess")
        XCTAssertNil(ModelNames.agentLine(agent: nil, harness: nil, model: nil, effort: nil))
    }

    func testTheNewFieldsDecodeAndAreOptional() throws {
        let ev = try JSONDecoder().decode(Evidence.self, from: Data(#"""
            {"episode":"ep_2026-09-24_001","start":0,"end":5,"kind":"assistant","hash":"h","model":"claude-opus-5-5","effort":"high"}
            """#.utf8))
        XCTAssertEqual(ev.model, "claude-opus-5-5")
        XCTAssertEqual(ev.effort, "high")
        let legacy = try JSONDecoder().decode(Evidence.self, from: Data(#"{"episode":"ep_x","start":0,"end":1,"kind":"user"}"#.utf8))
        XCTAssertNil(legacy.model)
        let claim = try JSONDecoder().decode(Claim.self, from: Data(#"""
            {"id":"clm_1","authoredBy":"claude-code","authorKind":"harness","authorModel":"claude-opus-5-5","authorEffort":"xhigh"}
            """#.utf8))
        XCTAssertEqual(claim.authorModel, "claude-opus-5-5")
        XCTAssertEqual(claim.authorEffort, "xhigh")
        XCTAssertNil(try JSONDecoder().decode(Claim.self, from: Data(#"{"id":"clm_2"}"#.utf8)).authorModel)
        let doc = try JSONDecoder().decode(EpisodeText.self, from: Data(#"""
            {"episode":"ep_1","text":"assistant: hi","harness":"claude-code","agent":{"model":"claude-opus-5-5","effort":"high"},
             "turns":[{"index":0,"start":0,"contentStart":11,"end":13,"role":"assistant","model":"claude-opus-5-5","effort":"high"}]}
            """#.utf8))
        XCTAssertEqual(doc.agent?.model, "claude-opus-5-5")
        XCTAssertEqual(doc.turns.first?.effort, "high")
        let contributor = try JSONDecoder().decode(ProvenanceContributor.self, from: Data(#"""
            {"author":"claude-code","kind":"harness","claims":3,"models":[{"model":"claude-opus-5-5","effort":"high","beliefs":2},{"model":"claude-sonnet-5","beliefs":1}]}
            """#.utf8))
        XCTAssertEqual(contributor.models.map(\.model), ["claude-opus-5-5", "claude-sonnet-5"])
        XCTAssertEqual(try JSONDecoder().decode(ProvenanceContributor.self, from: Data(#"{"author":"a"}"#.utf8)).models, [])
    }
}
```

  Extend `EvidenceChipLabelTests`: an assistant `Evidence` with `model: "claude-opus-5-5", effort: "high"` and meta
  `harness: "claude-code"` → `chipText` == "Claude Code · Opus 5.5 · high effort · Sep 24" (episode
  `ep_2026-09-24_001`, `en_US`, UTC); the same span with no model → today's "Claude Code replied · Sep 24"; a `user`
  span with a model (impossible on the wire, but defensive) → "You said · Sep 24"; an assistant span with a model and
  NO doc meta → "The agent · Opus 5.5 · high effort · Sep 24". Add to `ModelNamesTests` (one file for the new reads):
  `ReaderHeader.meta(doc)` for the decoded `doc` above starts "Claude Code · Opus 5.5 · high effort · " (that doc has no
  date, so it reads "Claude Code · Opus 5.5 · high effort · 1 turn"); `EvidenceSpeaker.turnSpeaker(doc.turns[0],
  harness: doc.harness, origin: doc.origin)` == "Claude Code · Opus 5.5 · high effort"; a `claude-desktop` doc with no
  `agent` → meta starts "Claude Desktop · model not shared by this app"; a `claude-code` doc with no `agent` → meta
  starts "Claude Code · " and never contains "not shared". Extend `ProvenanceSummaryTests`: `modelsLine` for the decoded
  contributor == "Opus 5.5 · high effort, Sonnet 5"; three models → the two with most beliefs + ", +1 more"; a
  `harness` contributor `claude-desktop` with no models → "model not shared by this app"; a `claude-code` harness
  contributor with no models → nil (a write from before D1: nothing added); a `model` or `user` contributor → nil.
  Extend `EntityContentTests` (where `testABeliefsHelpAndAge` pins `BeliefWords.help` today): for a claim decoded from
  `{"id":"clm_1","authoredBy":"claude-code","authorKind":"harness","authorModel":"claude-opus-5-5","authorEffort":"xhigh"}`
  (no observer → "Cicada", no confidence → 0),
  `BeliefWords.help(claim) == "Cicada · Claude Code · Opus 5.5 · extra-high effort at 0.00"`, and the existing
  expectation "Cicada · Engineering · gpt-5.4-mini at 0.85" is unchanged (no model fields → byte-for-byte today's).

- [ ] **Step 2: `Models/ModelNames.swift`:**

```swift
import Foundation

/// Round-4 C3/C4 (D1, R-FA14) — a model id as a person reads it and an effort level in words, for every surface
/// that names who wrote a belief. D1 lifted G49's reservation for harness writes: capture records the model and
/// effort of each agent turn, and a write is joined to its turn at read. Pure; `ModelNamesTests`.
enum ModelNames {
    /// Harnesses whose Stop hook reads the transcript (G105), so their turns can carry a model. Any other app that
    /// writes through MCP never tells Cicada its model — D1's "model not shared by this app".
    static let capturingHarnesses: Set<String> = ["claude-code", "codex"]

    private static let claudeFamilies = ["opus": "Opus", "sonnet": "Sonnet", "haiku": "Haiku"]
    private static let words = ["codex": "Codex", "mini": "mini", "nano": "nano", "pro": "Pro", "max": "Max",
                                "turbo": "Turbo", "flash": "Flash", "lite": "Lite"]

    /// "claude-opus-5-5" → "Opus 5.5"; an id this does not recognise is shown exactly as sent — its own honest name.
    static func display(_ raw: String) -> String {
        var id = raw.trimmingCharacters(in: .whitespaces)
        if let bracket = id.firstIndex(of: "[") { id = String(id[..<bracket]) }   // "[1m]", a context-size tag
        var parts = id.lowercased().split(separator: "-").map(String.init)
        if let last = parts.last, last.count == 8, last.allSatisfy(\.isNumber) { parts.removeLast() }   // a date stamp
        guard let head = parts.first else { return raw }
        let rest = Array(parts.dropFirst())
        switch head {
        case "claude": return claude(rest) ?? raw
        case "gpt": return gpt(rest) ?? raw
        case "gemini": return gemini(rest) ?? raw
        default: return raw
        }
    }

    private static func isNumber(_ s: String) -> Bool { !s.isEmpty && s.allSatisfy(\.isNumber) }

    private static func claude(_ p: [String]) -> String? {
        if let first = p.first, let family = claudeFamilies[first] {            // claude-opus-5-5
            let version = Array(p.dropFirst())
            guard !version.isEmpty, version.allSatisfy(isNumber) else { return nil }
            return "\(family) \(version.joined(separator: "."))"
        }
        if let last = p.last, let family = claudeFamilies[last], p.count > 1,  // claude-3-5-sonnet
           p.dropLast().allSatisfy(isNumber) {
            return "\(family) \(p.dropLast().joined(separator: "."))"
        }
        return nil
    }

    private static func gpt(_ p: [String]) -> String? { versioned("GPT-", p) }          // gpt-5.5-codex, gpt-4o-mini
    private static func gemini(_ p: [String]) -> String? { versioned("Gemini ", p) }    // gemini-2.5-pro

    /// A version that starts with a digit, then only words this table knows; anything else is not ours to rename.
    private static func versioned(_ prefix: String, _ p: [String]) -> String? {
        guard let version = p.first, version.first?.isNumber == true else { return nil }
        var out = prefix + version
        for w in p.dropFirst() {
            guard let word = words[w] else { return nil }
            out += " \(word)"
        }
        return out
    }

    /// C1's effort enum in words; anything else says nothing.
    static func effort(_ raw: String?) -> String? {
        switch raw?.lowercased() {
        case "minimal": "minimal effort"
        case "low": "low effort"
        case "medium": "medium effort"
        case "high": "high effort"
        case "xhigh": "extra-high effort"
        case "max": "max effort"
        default: nil
        }
    }

    /// "Opus 5.5 · high effort", "Opus 5.5", or nil with no model.
    static func line(model: String?, effort: String?) -> String? {
        guard let model, !model.isEmpty else { return nil }
        return [display(model), self.effort(effort)].compactMap { $0 }.joined(separator: " · ")
    }

    /// "Claude Code · Opus 5.5 · high effort". With no model: an app that never tells adds "model not shared by this
    /// app"; a capturing harness (a write from before D1) adds nothing — never a guess.
    static func agentLine(agent: String?, harness: String?, model: String?, effort: String?) -> String? {
        let modelLine = line(model: model, effort: effort)
        var parts = [agent, modelLine].compactMap { $0 }.filter { !$0.isEmpty }
        if modelLine == nil, let harness, !harness.isEmpty, !["unknown", "mcp"].contains(harness),
           !capturingHarnesses.contains(harness), agent != nil {
            parts.append(Copy.Provenance.modelNotShared)
        }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }
}
```

  `Copy.Provenance.modelNotShared = "model not shared by this app"`.

- [ ] **Step 3: Decode (C3/C4)** — all optional, all absent-tolerant:
  - Every new key below decodes as `(try? c.decodeIfPresent(String.self, forKey: .model)) ?? nil` — `try?`, not the
    `try` these types use for their existing keys, because `try` throws on a mistyped value and would fail the WHOLE
    claim, span or document over one optional field from a backend a shape ahead (the global decode-tolerance rule).
    Each type's synthesized `encode(to:)` picks the new keys up through `CodingKeys` (a nil optional is omitted), so the
    Store's on-disk snapshot cache stays readable both ways.
  - `Claim`: `let authorModel: String?`, `let authorEffort: String?` after `authorProvider`, in `CodingKeys`. Doc:
    "round-4 C3 — the model and effort of the agent turn a harness write happened in, joined at read; nil for a Sleep
    claim (its model is `authoredBy`), a person's, or a write from before D1".
  - `Evidence`: `let model: String?`, `let effort: String?` (init params defaulting to nil; `CodingKeys`; decode).
  - `EpisodeTurn`: `model`, `effort` the same way. `EpisodeText`: `struct EpisodeAgent: Codable, Hashable { let model:
    String?; let effort: String? }` and `let agent: EpisodeAgent?` (init param `agent: EpisodeAgent? = nil`).
  - `ProvenanceContributor`: `struct ContributorModel: Codable, Hashable { let model: String; let effort: String?;
    let beliefs: Int }` (lenient: `model` "" / `beliefs` 0 defaults) and `let models: [ContributorModel]` defaulting to
    `[]` (init param `models: [ContributorModel] = []`).
- [ ] **Step 4: Display.**
  - `EvidenceChipModel` (one stored `source`): computed `var model: String?` and `var effort: String?` — `ev.model` /
    `ev.effort` for `.stored(ev)`, nil for `.mention`. `EvidenceLabel` gains one
    `static func label(_ chip: EvidenceChipModel, meta: EvidenceDocMeta?) -> String`: when `chip.kind == .assistant` and
    `ModelNames.line(model: chip.model, effort: chip.effort)` is non-nil, it is
    `ModelNames.agentLine(agent: agent(meta) ?? Copy.Provenance.theAgent, harness: nil, model: chip.model, effort:
    chip.effort) ?? speaker(kind: chip.kind, agent: agent(meta))` (the fallback never fires — there is a model line —
    but nothing is force-unwrapped); otherwise today's `speaker(kind: chip.kind, agent: agent(meta))`.
    `chipText` and `accessibility(...)` both start from `label(chip, meta:)`; the day suffix is unchanged.
  - `EvidenceChip.headerLine` (`EvidenceChip.swift:195-200`): for an assistant chip, let
    `line = ModelNames.agentLine(agent: EvidenceLabel.agent(meta) ?? (model.model == nil ? nil : Copy.Provenance.theAgent),
    harness: meta?.harness, model: model.model, effort: model.effort)`; when `line` is non-nil and says more than the
    agent's bare name (`line != EvidenceLabel.agent(meta)` — a model, or "model not shared by this app"), it is the first
    part; otherwise today's `EvidenceLabel.speaker(...)`, so a pre-D1 Claude Code chip's hover still reads "Claude Code
    replied". The hover is where "model not shared by this app" lives; the chip itself never says it.
  - `ReaderModel.swift`: remove the "Never the MODEL … reserved-null" sentence from `agentName`'s doc (D1 lifted it;
    `agentName` itself still returns the app's name); `turnSpeaker`'s assistant case returns
    `ModelNames.agentLine(agent: agentName(...) ?? Copy.Provenance.theAgent, harness: nil, model: turn.model, effort: turn.effort)
    ?? Copy.Provenance.theAgent`; `ReaderHeader.meta` replaces the bare agent with
    `ModelNames.agentLine(agent: agent, harness: doc.harness, model: doc.agent?.model, effort: doc.agent?.effort)`.
  - `ProvenanceSummary.modelsLine(_ c:) -> String?`: `harness` kind only; models sorted by `beliefs` descending then
    id; the first two through `ModelNames.line`, joined ", ", then ", +\(UsageFormat.count(n)) more"; with none and a
    non-capturing harness, `Copy.Provenance.modelNotShared`; else nil. `WhereThisCameFromSection.contributorChip`
    shows it as a third `Text` line (`CicadaTheme.font(size: 10)`, `textTertiary`, `lineLimit(1)`), and its `.help` keeps
    today's sentence and, when `c.models` is non-empty, appends one line per model from a pure
    `ProvenanceSummary.modelsHelp(_:)` — "Opus 5.5 · high effort — 2 beliefs" (`ModelNames.line` +
    `Copy.Provenance.beliefs`); add that case to the `ProvenanceSummaryTests` extension.
  - `BeliefWords.help`: the author part becomes
    `[ContributorIdentity.displayName(author: claim.authoredBy, kind: kind), ModelNames.line(model: claim.authorModel, effort: claim.authorEffort)].compactMap { $0 }.joined(separator: " · ")`.
- [ ] **Step 5: The §9 ruling** — append to `docs/design/DESIGN_RULES.md` §9:

```markdown
- **2026-09-24: An agent's chip names its model when capture recorded one (round-4 D1, C3; DR-57).** "<agent> replied" becomes the agent line — "Claude Code · Opus 5.5 · high effort · Sep 24" — when the span's turn carries a model; without one the chip is unchanged. The model is a fact about who spoke, so it rides the label rather than a second chip. The hover's header, the Reader's meta line and its turn labels say the same line (`ModelNames`); an app with no capture says "model not shared by this app" in the hover, never a guess.
```

- [ ] **Step 6: Green + commit** — `swift test --filter 'ModelNamesTests|EvidenceChipLabelTests|EvidenceDecodeTests|ReaderTurnsTests|ProvenanceSummaryTests|ProvenanceAPITests|EntityContentTests' 2>&1 | tail -20`
  (all seven suites exist at `ecb59c7`), `swift build`, full `swift test`. Commit:

```
feat(provenance): every agent write says who wrote it — "Claude Code · Opus 5.5 · high effort" (C3, C4, D1)

Decodes authorModel/authorEffort, span model/effort, the Reader's agent and turn models, and the
provenance contributors' models — all optional, so today's backend renders exactly as before. One pure
ModelNames turns ids into names and effort into words; chips, their hover, the Reader's meta and turn
labels, "Where this came from" and a belief's help all use it. An app with no capture says "model not
shared by this app".

DR-57 (§9 amendment), DR-54, DR-21
```

---

### Task 6: Connect an agent by copying one prompt; Claude desktop in one click (D5)

**Files:** see the file map rows marked 6.

**Interfaces:**
- Produces `AgentSetupPrompt` (C5's shape, lenient), `APIClient.fetchAgentSetup(harness:)`,
  `ClaudeDesktopConfig` (`configURL(home:)`, `server(python:script:memory:)`, `merge(existing:server:)`,
  `apply(server:at:fileManager:)`, `Merge`, `Reason`, `Outcome`), `AgentQuickSetup` (pure `actions(catalogId:
  setup:wiring:)` + the view), `AgentSetupCatalog.setupHarnesses`.
- Consumes `AgentSetupCatalog`, `AgentConnect.run`, `fetchAgentWiring()`, `BackendProcess.installRoot()`,
  `LiveMemoryRootProbe`.

- [ ] **Step 1: Failing tests** — `app/CicadaApp/Tests/CicadaAppTests/AgentQuickSetupTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// Round-4 D5 (C5, R-FA15) — copy one prompt, open Cursor, or merge Claude desktop's config — never replacing it.
final class AgentQuickSetupTests: XCTestCase {
    private let server = ClaudeDesktopConfig.server(python: "/x/cicada/api/.venv/bin/python",
                                                    script: "/x/cicada/mcp/server.py", memory: "/x/cicada/memory")

    private func object(_ data: Data) throws -> [String: Any] {
        try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
    }

    func testNoFileBecomesAFileWithOnlyCicada() throws {
        guard case .write(let data) = ClaudeDesktopConfig.merge(existing: nil, server: server) else { return XCTFail() }
        let servers = try XCTUnwrap(try object(data)["mcpServers"] as? [String: Any])
        XCTAssertEqual(Array(servers.keys), ["cicada"])
    }

    func testAMergeKeepsEveryOtherServerAndSetting() throws {
        let existing = Data(#"{"globalShortcut":"Cmd+Space","mcpServers":{"alpha-project":{"command":"/bin/echo"}}}"#.utf8)
        guard case .write(let data) = ClaudeDesktopConfig.merge(existing: existing, server: server) else { return XCTFail() }
        let root = try object(data)
        XCTAssertEqual(root["globalShortcut"] as? String, "Cmd+Space")
        let servers = try XCTUnwrap(root["mcpServers"] as? [String: Any])
        XCTAssertNotNil(servers["alpha-project"])
        XCTAssertEqual((servers["cicada"] as? [String: Any])?["command"] as? String, "/x/cicada/api/.venv/bin/python")
    }

    func testAnOlderCicadaEntryIsReplacedAndAnIdenticalOneIsLeftAlone() throws {
        let older = Data(#"{"mcpServers":{"cicada":{"command":"/old/python","args":["/old/server.py"]}}}"#.utf8)
        guard case .write = ClaudeDesktopConfig.merge(existing: older, server: server) else { return XCTFail() }
        guard case .write(let written) = ClaudeDesktopConfig.merge(existing: nil, server: server) else { return XCTFail() }
        XCTAssertEqual(ClaudeDesktopConfig.merge(existing: written, server: server), .unchanged)
    }

    func testAFileCicadaCannotReadIsLeftUntouched() {
        XCTAssertEqual(ClaudeDesktopConfig.merge(existing: Data("{ not json".utf8), server: server), .unparseable(.notJSON))
        XCTAssertEqual(ClaudeDesktopConfig.merge(existing: Data("[1,2]".utf8), server: server), .unparseable(.notAnObject))
        XCTAssertEqual(ClaudeDesktopConfig.merge(existing: Data(#"{"mcpServers":"x"}"#.utf8), server: server),
                       .unparseable(.serversNotAnObject))
        guard case .write = ClaudeDesktopConfig.merge(existing: Data("  \n".utf8), server: server) else {
            return XCTFail("an empty file is an empty config")
        }
    }

    func testApplyBacksUpFirstAndNeverCreatesClaudesFolder() throws {
        let home = FileManager.default.temporaryDirectory.appendingPathComponent("claude-\(UUID())")
        defer { try? FileManager.default.removeItem(at: home) }
        let url = ClaudeDesktopConfig.configURL(home: home)
        XCTAssertEqual(ClaudeDesktopConfig.apply(server: server, at: url), .claudeNotSetUp)
        XCTAssertFalse(FileManager.default.fileExists(atPath: url.deletingLastPathComponent().path))
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        let original = Data(#"{"mcpServers":{"alpha-project":{"command":"/bin/echo"}}}"#.utf8)
        try original.write(to: url)
        XCTAssertEqual(ClaudeDesktopConfig.apply(server: server, at: url), .done)
        XCTAssertEqual(try Data(contentsOf: URL(fileURLWithPath: url.path + ClaudeDesktopConfig.backupSuffix)), original)
        XCTAssertEqual(ClaudeDesktopConfig.apply(server: server, at: url), .alreadySetUp)
        XCTAssertEqual(try Data(contentsOf: URL(fileURLWithPath: url.path + ClaudeDesktopConfig.backupSuffix)), original,
                       "a no-op never overwrites the backup of the person's own file")
        try Data("{ broken".utf8).write(to: url)
        XCTAssertEqual(ClaudeDesktopConfig.apply(server: server, at: url), .leftUntouched(.notJSON))
        XCTAssertEqual(try Data(contentsOf: url), Data("{ broken".utf8))
    }

    /// R-FA15 — a config kept as a symlink (a dotfiles repo) is written through the link, never replaced by a file.
    func testASymlinkedConfigStaysALink() throws {
        let home = FileManager.default.temporaryDirectory.appendingPathComponent("claude-\(UUID())")
        defer { try? FileManager.default.removeItem(at: home) }
        let url = ClaudeDesktopConfig.configURL(home: home)
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        let real = home.appendingPathComponent("dotfiles/claude_desktop_config.json")
        try FileManager.default.createDirectory(at: real.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data(#"{"mcpServers":{}}"#.utf8).write(to: real)
        try FileManager.default.createSymbolicLink(at: url, withDestinationURL: real)
        XCTAssertEqual(ClaudeDesktopConfig.apply(server: server, at: url), .done)
        XCTAssertNotNil(try? FileManager.default.destinationOfSymbolicLink(atPath: url.path), "still a link")
        let servers = try XCTUnwrap(try object(Data(contentsOf: real))["mcpServers"] as? [String: Any])
        XCTAssertNotNil(servers["cicada"], "the person's own file got the entry")
    }

    func testTheSetupWireDecodesLeniently() throws {
        let prompt = try JSONDecoder().decode(AgentSetupPrompt.self, from: Data(#"""
            {"harness":"codex","kind":"prompt","title":"Codex","prompt":"Please run …","argv":[["codex","mcp","add","cicada"]],
             "display":["codex mcp add cicada"]}
            """#.utf8))
        XCTAssertEqual(prompt.kind, "prompt")
        XCTAssertEqual(prompt.display, ["codex mcp add cicada"])
        let bare = try JSONDecoder().decode(AgentSetupPrompt.self, from: Data(#"{"harness":"cursor"}"#.utf8))
        XCTAssertNil(bare.prompt)
        XCTAssertEqual(bare.argv, [])
    }

    func testEachHarnessGetsItsOwnActions() throws {
        let prompt = try JSONDecoder().decode(AgentSetupPrompt.self, from: Data(#"{"harness":"claude-code","kind":"prompt","prompt":"Hi"}"#.utf8))
        let step = AgentWiringStep(step: "mcp", display: "claude mcp add cicada …", argv: ["/bin/claude"], touches: [])
        let wired = AgentWiring(id: "claude-code", installed: true, binary: "/bin/claude", recall: "off", autosave: "off",
                                connect: [step], detail: nil)
        XCTAssertEqual(AgentQuickSetup.actions(catalogId: "claude-code", setup: prompt, wiring: wired),
                       [.connectForMe([step]), .copyPrompt("Hi")])
        XCTAssertEqual(AgentQuickSetup.actions(catalogId: "claude-code", setup: nil, wiring: nil), [],
                       "today's backend: no prompt, no wiring — nothing new to show")
        XCTAssertEqual(AgentQuickSetup.actions(catalogId: "cursor", setup: nil, wiring: nil), [.openCursor])
        XCTAssertEqual(AgentQuickSetup.actions(catalogId: "claude-desktop", setup: nil, wiring: nil), [.setUpClaude])
        XCTAssertEqual(AgentQuickSetup.actions(catalogId: "hermes", setup: prompt, wiring: nil), [])
        XCTAssertEqual(AgentSetupCatalog.setupHarnesses, ["claude-code", "codex", "gemini-cli", "cursor", "claude-desktop"])
    }
}
```

- [ ] **Step 2: `Support/ClaudeDesktopConfig.swift`** (a pure merge + one IO function):

```swift
import Foundation

/// Round-4 D5 (R-FA15) — "Set up Claude": merge Cicada's MCP server into Claude desktop's config. MERGE, never
/// replace: every other server and setting stays; a file Cicada cannot read is left exactly as it was; the file is
/// backed up before the first write that changes it. The app writes only what it computed itself — the same
/// python / server / memory root as `AgentSetupCatalog` — into the path it computed itself; `GET /agents/setup`'s
/// `config` is never trusted for either.
enum ClaudeDesktopConfig {
    static let key = "cicada"
    static let backupSuffix = ".cicada-backup"

    static func configURL(home: URL = FileManager.default.homeDirectoryForCurrentUser) -> URL {
        home.appendingPathComponent("Library/Application Support/Claude/claude_desktop_config.json")
    }

    static func server(python: String, script: String, memory: String) -> [String: Any] {
        ["command": python, "args": [script], "env": ["CICADA_MEMORY_PATH": memory]]
    }

    enum Reason: Equatable { case notJSON, notAnObject, serversNotAnObject }
    enum Merge: Equatable { case write(Data), unchanged, unparseable(Reason) }
    enum Outcome: Equatable { case done, alreadySetUp, claudeNotSetUp, leftUntouched(Reason), failed(String) }

    static func merge(existing: Data?, server: [String: Any]) -> Merge {
        var root: [String: Any] = [:]
        if let existing, !String(decoding: existing, as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            guard let parsed = try? JSONSerialization.jsonObject(with: existing) else { return .unparseable(.notJSON) }
            guard let object = parsed as? [String: Any] else { return .unparseable(.notAnObject) }
            root = object
        }
        var servers: [String: Any] = [:]
        if let raw = root["mcpServers"] {
            guard let object = raw as? [String: Any] else { return .unparseable(.serversNotAnObject) }
            servers = object
        }
        if let current = servers[key] as? [String: Any], NSDictionary(dictionary: current).isEqual(to: server) {
            return .unchanged
        }
        servers[key] = server
        root["mcpServers"] = servers
        guard let data = try? JSONSerialization.data(withJSONObject: root, options: [.prettyPrinted, .withoutEscapingSlashes])
        else { return .unparseable(.notJSON) }
        return .write(data)
    }

    /// Never creates Claude's folder: a Mac where Claude desktop never ran has nothing to set up yet.
    static func apply(server: [String: Any], at url: URL, fileManager: FileManager = .default) -> Outcome {
        var isDirectory: ObjCBool = false
        guard fileManager.fileExists(atPath: url.deletingLastPathComponent().path, isDirectory: &isDirectory),
              isDirectory.boolValue else { return .claudeNotSetUp }
        let existing = fileManager.contents(atPath: url.path)
        switch merge(existing: existing, server: server) {
        case .unchanged: return .alreadySetUp
        case .unparseable(let why): return .leftUntouched(why)
        case .write(let data):
            do {
                if let existing { try existing.write(to: URL(fileURLWithPath: url.path + backupSuffix), options: .atomic) }
                // Through a symlink, never over it: an atomic write replaces the path it is given, and a config kept
                // in a dotfiles repo is a link the person made (R-FA15, "merge never replace").
                try data.write(to: url.resolvingSymlinksInPath(), options: .atomic)
                return .done
            } catch {
                return .failed(error.localizedDescription)
            }
        }
    }
}
```

- [ ] **Step 3: The wire** — `Models/AgentSetupPrompt.swift` (the plan critic ran `testTheSetupWireDecodesLeniently`
  against exactly this):

```swift
import Foundation

/// Round-4 D5 (C5) — `GET /agents/setup?harness=<id>`, decoded leniently (R-PP2's house rule): a backend one field
/// ahead or behind never fails the Agents page. `config.value` is deliberately NOT decoded — the app writes only the
/// Claude desktop entry it computed itself (R-FA15), so nothing off the wire can reach a file.
struct AgentSetupPrompt: Decodable, Equatable {
    struct Config: Decodable, Equatable {
        let path: String
        let key: String
    }

    var harness: String
    var kind: String
    var title: String
    var prompt: String?
    var argv: [[String]]
    var display: [String]
    var deeplink: String?
    var config: Config?
    var note: String?

    enum CodingKeys: String, CodingKey { case harness, kind, title, prompt, argv, display, deeplink, config, note }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        harness = c.lenient(.harness, "")
        kind = c.lenient(.kind, "")
        title = c.lenient(.title, "")
        prompt = c.lenient(.prompt)
        argv = c.lenient(.argv, [])
        display = c.lenient(.display, [])
        deeplink = c.lenient(.deeplink)
        config = c.lenient(.config)
        note = c.lenient(.note)
    }
}
```

  `APIClient.swift`, beside `fetchAgentWiring` (`:2579`):
  `func fetchAgentSetup(harness: String) async throws -> AgentSetupPrompt { try await get("/agents/setup?harness=\(harness.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? harness)") }`.
- [ ] **Step 4: The actions** — `Views/Connect/AgentQuickSetup.swift` (`import SwiftUI`; SwiftUI re-exports AppKit
  here, so `NSPasteboard` / `NSWorkspace` need no second import — `GraphView.swift`'s precedent):

```swift
/// Round-4 D5 (R-FA15) — the one-click paths on an agent's row, decided purely: Connect for me (Cicada runs the
/// wiring commands after the click, the Found row's Turn on), Copy setup prompt (the agent runs them itself),
/// Open in Cursor (the catalog's own deeplink), Set up Claude (a config merge the app performs).
enum AgentQuickAction: Equatable {
    case connectForMe([AgentWiringStep])
    case copyPrompt(String)
    case openCursor
    case setUpClaude
}

enum AgentQuickSetup {
    static func actions(catalogId: String, setup: AgentSetupPrompt?, wiring: AgentWiring?) -> [AgentQuickAction] {
        var out: [AgentQuickAction] = []
        if let wiring, wiring.id == catalogId, wiring.installed, !wiring.connect.isEmpty,
           !(wiring.recall == "on" && wiring.autosave == "on") {
            out.append(.connectForMe(wiring.connect))
        }
        if AgentSetupCatalog.setupHarnesses.contains(catalogId), setup?.kind == "prompt",
           let prompt = setup?.prompt, !prompt.isEmpty {
            out.append(.copyPrompt(prompt))
        }
        if catalogId == "cursor" { out.append(.openCursor) }
        if catalogId == "claude-desktop" { out.append(.setUpClaude) }
        return out
    }
}
```

  `AgentSetupCatalog.setupHarnesses = ["claude-code", "codex", "gemini-cli", "cursor", "claude-desktop"]` (C5's list).
  The view `AgentQuickSetupView(agent:, actions:, binaries:, home:, memoryRoot:, onConnected:)` draws, above the
  existing steps of an OPEN row (its own `@State` for a running flag, the last outcome's caption and `copied`):
  - `.connectForMe(steps)`: each step's `display` in a `CommandBox`, then `NeutralButton(title: Copy.agentConnectForMe,
    isDisabled: running)` → `AgentConnect.run(steps, installRoot: BackendProcess.installRoot(), binaries: binaries)`,
    where `binaries` is `Set(wiring.agents.compactMap(\.binary))` from the ONE `/agents/wiring` response ConnectView
    holds — `FoundTurnOn.swift:80`'s argument, the binaries the backend resolved; never the steps' own argv[0]s, which
    would let any `…/claude` through the policy's binary check. The outcome in a caption (`.done` →
    `Copy.agentConnected`, then `onConnected()` so ConnectView fetches the wiring again and a now-wired agent drops the
    action; `.refused(lines)` → `Copy.agentRefused`; `.failed(why)` → why).
  - `.copyPrompt(text)`: a read-only box (`Text(text)` in `CicadaTheme.bodyFont`, `.textSelection(.enabled)`, on
    `bgFocus` with `.ringed(in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))`, max height `CicadaTheme.scaled(180)`
    in a `ScrollView`), then `NeutralButton(title: copied ? Copy.agentCopied : Copy.agentCopyPrompt, systemImage:
    copied ? "checkmark" : "doc.on.doc")` that writes `NSPasteboard.general` and shows "Copied" for 1.5 s (the
    `CommandBox` precedent), with the caption `Copy.agentPromptHow(agent.name)` ("Paste this into <name> — it runs the
    commands the prompt names itself and changes nothing else.").
  - `.openCursor`: `if let deeplink = agent.deeplink { NeutralButton(title: Copy.agentOpenInCursor) {
    NSWorkspace.shared.open(deeplink.url) } }` — the catalog's own deeplink, never force-unwrapped
    (`AgentSetupCatalog` builds it from `URL(string:)`, which can be nil). Remove the brand-tinted capsule
    (`ConnectView.swift:348-363`).
  - `.setUpClaude`: `NeutralButton(title: Copy.agentSetUpClaude)` → `ClaudeDesktopConfig.apply(server:
    ClaudeDesktopConfig.server(python: home + "/api/.venv/bin/python", script: home + "/mcp/server.py", memory:
    memoryRoot ?? home + "/memory"), at: ClaudeDesktopConfig.configURL())`, the outcome in a caption: `.done` →
    `Copy.agentClaudeDone` ("Done — quit and reopen Claude to finish."); `.alreadySetUp` → "Claude is already set up
    — quit and reopen it if the tools don't show."; `.claudeNotSetUp` → "Open Claude once, then try again.";
    `.leftUntouched` → "Cicada couldn't read Claude's settings file, so it left it untouched. Add the snippet below by
    hand."; `.failed(why)` → why. Keep the existing manual JSON step below it.
- [ ] **Step 5: ConnectView** — `ConnectView` gains `@State private var wiring: AgentWiringResponse?` and
  `@State private var setups: [String: AgentSetupPrompt] = [:]`. `.task(id: store.isConnected)` becomes
  `{ await refreshWiring(); await refreshLiveMemoryRoot() }` with
  `private func refreshWiring() async { if let w = try? await APIClient.shared.fetchAgentWiring() { wiring = w } }`
  (a failure keeps the last answer — never blank). `.onChange(of: openAgent)`: when the new id is in
  `AgentSetupCatalog.setupHarnesses` and `setups[id] == nil`, `setups[id] = try? await
  APIClient.shared.fetchAgentSetup(harness: id)` in a `Task` (a failure — including today's 404 — leaves no entry, so
  nothing new shows). `AgentSetupRow` gains `actions: [AgentQuickAction]`, `binaries: Set<String>`, `home`,
  `memoryRoot` and `onConnected`, passed as
  `AgentQuickSetup.actions(catalogId: agent.id, setup: setups[agent.id], wiring: wiring?.agents.first { $0.id == agent.id })`,
  `Set(wiring?.agents.compactMap(\.binary) ?? [])`, `home`, `probe.liveRoot`, `{ Task { await refreshWiring() } }`, and
  renders `AgentQuickSetupView` first in its open state. Copy (`Copy+Settings.swift`): `agentConnectForMe = "Connect for
  me"`, `agentConnected = "Connected — new sessions pick Cicada up."`, `agentRefused = "Cicada didn't run these:
  they aren't the commands it expects. Copy them from below instead."`, `agentCopyPrompt = "Copy setup prompt"`,
  `agentCopied = "Copied"`, `agentPromptHow(_ name:)`, `agentOpenInCursor = "Open in Cursor"`, `agentSetUpClaude =
  "Set up Claude"`, and the four Claude outcomes.
- [ ] **Step 6: The §9 ruling** — append to `docs/design/DESIGN_RULES.md` §9:

```markdown
- **2026-09-24: Settings → Agents' one-click actions are `NeutralButton`s (round-4 D5; DR-40, DR-44).** Connect for me, Copy setup prompt, Open in Cursor and Set up Claude. The brand-tinted capsule that carried Cursor's deeplink was a tinted pill (DR-44) and goes; the setup prompt sits in a read-only box, in the body face, before it can be copied, so the person reads what their agent will run.
```

- [ ] **Step 7: Green + commit** — `swift test --filter 'AgentQuickSetupTests|AgentsPageTests|AgentConnectTests|AgentWiringCatalogTests|AgentSetupCatalogEscapingTests|AgentSetupCatalogMemoryRootTests|SettingsIndexTests' 2>&1 | tail -20`,
  `swift build`, full `swift test`. Commit:

```
feat(agents): copy one setup prompt, open Cursor, or set up Claude desktop in one click (D5, C5, G76)

Settings → Agents shows GET /agents/setup's prompt verbatim in a read-only box before it copies it, beside
Connect for me (AgentConnect over /agents/wiring, the exact commands shown first). Cursor opens the
catalog's own deeplink. Set up Claude merges Cicada's server into claude_desktop_config.json — backup
first, merge never replace, an unreadable file left untouched — then says to quit and reopen Claude.
Against a backend without the endpoint nothing new appears.

DR-40, DR-44 (§9), DR-19
```

---

### Task 7: Docs — where the next reader will look (G143, G144)

**Files:** `CLAUDE.md`, `docs/goals/memory-evolution.md`. **Privacy rule:** no personal data — no names of other
people, no bank content, no machine paths; the owner's own ideas may be quoted.

- [ ] **Step 1: `CLAUDE.md`** (edit in place; keep each paragraph's density). Leave alone the "Conversation identity
  (G48)" paragraph ("A conversation row's `model` is **reserved — always null** …") and the `Cicada-Author:` bullet's
  "G49 keeps the model reserved": D1 lifts that on the capture and read side, which the backend track builds and
  documents (C1–C4) — two tracks rewriting the same sentence is a conflict the orchestrator does not need.
  - **Awake rails**, the "A local source is read by the app and parsed by the backend" bullet: append "The Calendar app
    (round-4 D2): `CalendarReader` reads every calendar on the Mac through EventKit, only after Connect and macOS's
    full-access prompt, 30 days back to 60 ahead, and posts `POST /sources/calendar-local/sync` on launch, on
    `EKEventStoreChanged` (debounced), every 3 hours, after a bank switch and on Sync now; Disconnect stops it and
    deletes nothing. ICS subscriptions are unchanged."
  - **Home (G108; Direction D, DS-3b)**: "the painted `hero-day` band" becomes "the painted `hero-day` band — its
    `-dark` sibling at dusk and night by the clock (`SceneClock`: NOAA's sun over the Mac's time zone's tzdb point, no
    location; `SceneStore` re-checks at each crossing, on a time-zone change and on wake) and Settings → General →
    Scene (Automatic · Always day · Always night), never the theme (G144; DESIGN_RULES §9 2026-09-24)". Same note in
    **Onboarding** for the Welcome's hero.
  - **Navigation / Settings** paragraph ("General's appearance offers System…"): add "General also holds Scene, Open
    Cicada at login (`LoginItemService` over `SMAppService.mainApp`; an unsigned build that macOS does not keep says
    so) and Keep memory working when Cicada is closed (`BackendAgentService`: a read-only `launchctl print`, and
    Install runs `scripts/install-backend-agent.sh` from the app's own checkout after the click, `CICADA_CAPTURE=off`,
    then hands launchd the port)."
  - **Installation & Setup**: "`scripts/install-backend-agent.sh` is the one source of the `com.cicada.backend` plist;
    `install.sh` step 6 calls it behind its healthy-skip guard, and the app runs it from Settings → General (G143).
    `BackendProcess` spawns `python -m uvicorn`, never the venv's `uvicorn` script. `make login-item` is the old
    developer path; the app's switch is the supported one."
  - **Agent wiring (Track I T3/T7)**: append "Settings → Agents (round-4 D5) adds, per harness, Connect for me (the
    same `AgentConnect.run`), Copy setup prompt (`GET /agents/setup`'s prompt shown verbatim, then copied — the agent
    runs the install itself), Open in Cursor (the catalog's own deeplink) and Set up Claude (`ClaudeDesktopConfig`
    merges `mcpServers.cicada` into Claude desktop's config: backup first, merge never replace, an unreadable file
    left untouched; the app computes the path and the value itself)."
  - **Provenance viewer (G118 slice 2)**: after "the label says who spoke", add "— an agent's chip names its model when
    capture recorded one ("Claude Code · Opus 5.5 · high effort", `ModelNames`; round-4 C3/C4), as do the hover, the
    Reader's meta line and turn labels, "Where this came from" and a belief's help; an app with no capture says
    "model not shared by this app"".
  - **Projects (G141 PJ-5, Direction D)** "The story" bullet: "Lately (… every participant a chip …)" becomes "every
    participant a chip, at most eight per sentence with a '+N more' that opens that row (round-4 D6; the server sends
    the first 12 and `participantsTotal`)"; add to the page's first sentence that the story is derived off the main
    actor (`ProjectDerived`) and Lately is one lazy list.
- [ ] **Step 2: `docs/goals/memory-evolution.md`** — two NEW rows straight after G141 (`:705`), four columns
  (ID | Item | Notes | Status). Do not add G142 (the backend track's).

```markdown
| G143 | **Open at login and a background service the app can install** (Rodrigo 2026-09-24, round-4 brief, paraphrased: everything should keep syncing while the app is open or in the background, so Cicada must be allowed to run in the background) | **What was there (verified at `ecb59c7`).** The only login-item path was `make login-item`'s System Events script (`app/CicadaApp/login_item.sh`); the app imported no `ServiceManagement`. The backend's LaunchAgent plist lived only inside `install.sh` step 6, so an app-only install had no way to get one. `BackendProcess` spawned the venv's `uvicorn` console script through `/usr/bin/env` — the shebang that breaks when the repo moves, which `install.sh`'s own note forbids for the plist. **What shipped (round-4 D3).** `LoginItemService` over `SMAppService.mainApp` behind a seam; it remembers what the person asked for, so an ad-hoc-signed build whose status never reaches `.enabled` says macOS did not keep it rather than showing "off". `scripts/install-backend-agent.sh` is the one source of the plist (idempotent: rewrite, boot out, bootstrap with three tries); `install.sh` calls it behind its healthy-skip guard; the app runs it from Settings → General after the click, argv pinned to its own checkout, `CICADA_CAPTURE=off`, then stops only the child uvicorn it spawned so launchd's KeepAlive binds the port. Status is a read-only `launchctl print`. `BackendProcess` spawns `python -m uvicorn`. **Open:** whether Cicada should start quietly in the menu bar at login instead of opening its window (owner); a signed build to confirm the login item persists; retiring `make login-item` once it does. → relates **G88**, **G76**, **G117**. | 🛠️ built (feat/r4-foundations-app) |
| G144 | **The Home painting follows the clock (scene preference)** (Rodrigo 2026-09-24, round-4 brief, paraphrased: the Home painting should be night when it is night for him and day when it is day, with a Settings choice to always show one) | **What was there.** `HomeHeroBand` and `WelcomeHero` chose `hero-day` or its `-dark` sibling by the THEME (`MeadowArt.image(for:mode: CicadaTheme.mode)`), so a person on a dark theme saw night at noon. **What shipped (round-4 D4).** `SceneClock` computes sunrise, sunset and civil twilight from NOAA's solar-position equations over the Mac's time zone's principal location, from a bundled table `scripts/gen-tz-coordinates.py` builds out of IANA tzdb (`zone1970.tab` + `zone.tab` + Link lines, public domain — measured: every macOS zone but `GMT` resolves; a zone with no point keeps a plain 07:00–19:00 clock). No location permission, no network. Day paints `hero-day`, dusk and night the `-dark` sibling; `SceneStore` re-checks at the next crossing or within the hour, on a time-zone change and on wake; Settings → General → Scene (Automatic · Always day · Always night, per viewer) is independent of Appearance. The owner's override of R-M2 for the hero alone is a dated DESIGN_RULES §9 ruling; `SkyBand.ships` (TODO ruling 10) is untouched. **Next:** the animated band (a later track) builds on `SceneStore.phase` and the `.dusk` phase kept for its transition. → relates **G137**, **G108**, **G117**. | 🛠️ built (feat/r4-foundations-app) |
```

- [ ] **Step 3: Check** — `grep -n "^| G14[34] " docs/goals/memory-evolution.md` shows each once; grep both files for
  any absolute user path or a person's name other than the owner's (none).
- [ ] **Step 4: Commit** — stage `CLAUDE.md` and `docs/goals/memory-evolution.md` by name:

```
docs: round-4 foundations (app) — scene by clock, background story, calendar, agents setup, who-wrote-it (G143, G144)
```

---

## Not in scope

- The new onboarding pages (Welcome with animation, Import, Collaboration), the animated Home painting, the Clusters
  redesign and the entity card redesign — later tracks, after the owner picks a design direction. This track only
  builds the named pieces they will use (C7).
- Any backend Python beyond `scripts/install-backend-agent.sh`'s and `scripts/gen-tz-coordinates.py`'s tests: the
  participants cap and `PROJECT_SHAPE` bump, `participantsTotal`, per-turn model capture (C1), `recorded_ts` (C2), the
  derived author fields (C3/C4), `GET /agents/setup` (C5), the calendar route and its channel (C6) are the backend
  track's (`feat/r4-foundations-back`). This branch decodes all of them leniently and works against today's backend.
- Editing `app/CicadaApp/Tests/fixtures/projects-demo.json` (the backend track regenerates it this round).
- `docs/goals/TODO.md` (R-FA16) and the G142 row.
- Retiring `login_item.sh` / `make login-item`; starting hidden at login (open question 1); code signing.
- Writing to calendars, reminders, or anything but reading events; a location permission; CoreLocation.
- Trusting `GET /agents/setup`'s `deeplink` or `config` for anything the app opens or writes (R-FA15).
- Uninstalling the background service from the app (`install.sh --uninstall` stays the path).

---

## Verification the orchestrator runs at the end

1. **Suites.** `cd <worktree> && api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider` → 0 failures
   (3775 + this track's new tests passed, 1 skipped); `cd <worktree>/app/CicadaApp && swift build 2>&1 | tail -5` and
   `swift test 2>&1 | tail -20` → 0 failures (2003 + new); `node --test app/CicadaApp/Tests/graph/*.test.js` → 8/8.
   `bash -n install.sh scripts/install-backend-agent.sh`; `./install.sh --dry-run` prints the script's dry-run lines
   and touches nothing.
2. **Hygiene.** `git log --stat dev..HEAD` shows only the file map's paths; no `memory/`, `logs/`, `.claude/`, venv or
   report files; `grep -rn "/Users/" $(git diff --name-only dev..HEAD)` finds nothing but test temp-dir code built from
   `FileManager.temporaryDirectory`; the regenerated `tz-coordinates.json` is ~18 KB (549 zones on tzdata 2026d) and records its tzdata version.
3. **Live, on the installed build, on the demo bank** (the orchestrator installs; `scripts/dev/` for clicks):
   - Projects (⌘8): open the demo's biggest project — no beachball; a happening with many participants shows 8 chips
     + "+N more"; clicking it opens that row only; "Show fewer" folds it; a band pick on an old Lately row scrolls it
     into view (R-FA3's `scrollTo` through the lazy stack).
   - Home at ⌘1: the band shows the day painting in daylight with a dark theme; Settings → General → Scene → Always
     night swaps it at once; ⌘K "scene" lands on the row. The Welcome (Run setup again) shows the same painting.
   - Settings → General: Open Cicada at login — flip on; on this ad-hoc build expect either "Almost there…" with Open
     Login Items, or the honest "macOS isn't opening Cicada at login…" line — never a silent "off". Keep memory
     working: with the launchd agent loaded it reads "On"; do NOT click Install on the owner's machine unless the
     owner asks (it rewrites his live plist — safe and idempotent, but his call).
   - Settings → Integrations → Feeds & calendars: "Calendar on this Mac" with the Calendar app's icon; Connect raises
     macOS's prompt; with the demo bank active a sync says the demo refusal in words; switching to a real bank syncs
     (against a backend without C6: the "update Cicada" line).
   - Provenance: an entity card with a Claude Code-authored belief (after the backend track lands) shows "Claude Code ·
     Opus 5.5 · high effort · <day>" on the chip, the same line in the hover and the Reader's meta; a Claude desktop
     conversation's hover says "model not shared by this app". Before the backend track lands: chips read exactly as
     today.
   - Settings → Agents: Claude Code / Codex / Gemini CLI rows show the prompt box + Copy setup prompt (after the
     backend track lands; absent before); Cursor shows Open in Cursor as a neutral button; Claude Desktop → Set up
     Claude on a scratch HOME only — never against the owner's real Claude config without asking.
4. **Screenshots** at 1440 × 900 and 1200 × 800, light and dark (DR-71), of Settings → General, the Calendar row, an
   open Agents row, and a Projects row with "+N more", for the PR body.

---

## Open questions (owner only)

1. **At login, should Cicada open its window, or start quietly with only the menu-bar worm?** This track opens it
   exactly as a manual launch does (R-FA7), because a hidden launch changes how the main window is created — a design
   call for the onboarding track.
