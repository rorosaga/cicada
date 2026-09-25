# Track P — polish and truth (round 2, 2026-09-05) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every sentence the app shows is true of what it actually does, every control it draws still exists for a reason, and the graph — the product's front door — is readable in light mode. Seven commits: the toolbar audit by deletion, an onboarding schedule toggle that makes its own copy true, six one-liners the suite can finally see, a Feed that stops rendering what the person removed, `GET /state`'s next-run instant calibrated for all four schedule modes, no person's name inside an agent-facing string or an LLM prompt, and a themed graph canvas.

**Architecture:** No new endpoints, no new Store domains, no new adapters. Backend work is two read-path corrections (`GET /sources` filters, `GET /state` threads the inputs `/status` already computes) plus a string sweep with a lint. App work is defaults, pure helpers with unit tests, and one new JS entry point (`setTheme`) pushed over the bridge that already exists.

**Tech Stack:** Python 3 / FastAPI / Pydantic (`api/`), SwiftUI + XCTest (`app/CicadaApp`), plain-node scripts (`app/CicadaApp/Tests/graph`), markdown + git bank.

**Spec:** `docs/superpowers/specs/2026-09-05-round2-study-room-marks-video-design.md` § Track P (six numbered items + "Decisions taken without the owner"), lines 238–263. **The in-repo evidence is `docs/goals/TODO.md:134-140` ("Small polish left behind by the 2026-09-05 tracks")** plus the "What the code actually does today" section below, which restates every finding against a file:line you can open. The `recent-work #N` / `test gap N` tags used throughout are the orchestrator's own numbering from a session-local read — labels, not a document you need: **nothing in this plan requires a file outside this repo.** Rulings honoured: TODO.md ruling 4 (a scheduled cycle never spends plan quota), ruling 6/7 (G105 — capture is the harness's Stop hook, not a model's tool call), the G109 graph rules, the G124 no-prices ruling, ETag ship-together, the privacy rule for docs, and CLAUDE.md's portability rail.

---

## What the code actually does today (verified against `feat/polish-truth`, based on `dev` @ `53885a1`)

- **`TopBarControls`** (`app/CicadaApp/Sources/CicadaApp/Views/Common/TopBarControls.swift`, 156 lines): `showsSleep: Bool = true`, `showsUpload: Bool = true`, `help: HelpContent = .actions` (`:22-24`). The Sleep button switches to `.sleep` and fires `sleepVM.triggerManually()` (`:32-61`); Upload flips the caller's `showUploadOverlay` binding (`:64-81`); `?` opens `HelpPopoverContent` or `HowSleepWorksContent` (`:95-100`). `HelpPopoverContent` (`:108-155`) is two paragraphs: the Sleep one at `:127` claims "For day-to-day usage with Claude Desktop or other MCP clients, Cicada handles consolidation automatically" — false on both halves (see the scheduler below, and G105); the Upload one at `:145` describes the button this track deletes.
- **Call sites:** Graph — `ContentView.swift:219` (`@State showUploadOverlay`), `:247-250` (TopBarControls), `:319-325` (overlay + animation). Clusters — `TopicsView.swift:11`, `:59-62`, `:69-71`. Feed — `FeedView.swift:14`, `:64-67`, `:74-77`, `:83-87`; Feed *also* owns `addButton` (`:119-130`) and the only ⌘N registration (`:91-97`), both opening `AddSourceSheet`, **not** `UploadOverlay`. Sleep — `SleepView.swift:93-99` already passes `showsSleep: false, showsUpload: false, help: .howSleepWorks`. Inbox and Sources never rendered it.
- **`TopBarControlsTests.swift:14-19`** asserts the two flags default to `true` and `help` defaults to `.actions` — the regression net that must move with the defaults.
- **Schedule:** `_DEFAULT = ScheduleConfig(mode="manual", hour=3, minute=0)` (`api/services/sleep_scheduler.py:37`); `register_job` registers **nothing** for `manual` (`:128-131`). `PUT /sleep/schedule` (`api/routers/sleep.py:180-192`) saves and re-registers. Swift: `ScheduleConfig` (`Services/APIClient.swift:799-830`, `enabled` derived from `mode`), `APIClient.fetchSchedule/updateSchedule` (`:1897-1917`), `SleepViewModel.schedule` (`:21`) + `updateSchedule(_:)` (`:303-309`) + `load()` (`:170-215`, which fetches status, episodes and schedule together). `SettingsSleepView.swift:27-30` holds the mirrored `@State` (including `loadedOnce`), `:53-59` is the one-shot `.task { if !loadedOnce { loadedOnce = true; await sleepVM.load() } }` this task copies, `:60-62` re-syncs on `onChange(of: sleepVM.schedule)`, and the mode picker itself lives inside `scheduleCard` (`:76`+).
- **Onboarding:** `OnboardingSleepStep.swift` is 72 lines; its `statusLine` (`:66-71`) ends `"…or skip — it also runs on its own schedule."` It already holds `@Environment(SleepViewModel.self)` (`:18`) — the same shared instance the Sleep page uses. `FirstRunSheet.swift:33-51` pins `.frame(width: 780, height: 640)`; step `.channel` embeds `IntegrationsView()` whole (`:59-68`); `finish()` (`:172-175`) marks the LIVE bank and calls `onFinished`.
- **Integrations:** `IntegrationsView.swift:23-26` reads `store.channels.value ?? []` and `store.sourcesOverview.value ?? []` — no loading state, no error state, no empty state; `:33-43` renders a category only when it has rows. `IntegrationHarnessRows.rows(from:)` (`Models/IntegrationCategory.swift:64-68`) filters on `kind == .harness` alone, and `api/services/source_overview.py:50-51` gives the two `chat-export:*` rows `kind = "harness"` **and** a `channel` id (`:54`'s Gemini row carries `channel=None`, so it legitimately stays in the harness list) — so each chat export renders twice, the harness copy claiming "Captured automatically — no setup needed" (`IntegrationsView.swift:231`). `SourceOverview.channelId` already exists (`Models/SourceOverview.swift:28`, decoded at `:109`). `IntegrationsViewTests.swift:37-41` builds its fixture with `channelId` defaulted to `nil`, which is exactly why the suite cannot see this.
- **The three-state pattern to copy:** `ConnectedChannelsStrip.swift:40-53` — `enum LoadState { loading, failed(String), loaded(...) }` plus a pure `loadState(channels:isLoading:error:)`, driven by `store.domainErrors[.channels]` (`:79`) and `isLoading = store.channels.isEmpty && store.channels.isRefreshing` (`:27`). `Snapshot` exposes `value`, `isRefreshing`, `isEmpty` (`Sync/Snapshot.swift:3-9`); `SyncDomain` has both `.channels` and `.sourcesOverview` (`:11-25`).
- **Merge reject:** `InboxCardView.swift:362-367` fires `QuestionResolution(action: "reject")` with no `mergeTarget`, while the computed `existingName` (`:317-320` — the typed `mergeText`, else `item.mergeTargetHint ?? ""`) sits two rows above. `inbox_service.resolve` (`api/services/inbox_service.py:1384-1392`) takes `merge_target_hint` **or** `request.merge_target` and raises `400 "reject needs a merge target (hint or mergeTarget)"` when both are empty. `api/tests/test_merge_rejections.py:116-120` already proves the explicit-target path works server-side.
- **Settings window:** `SettingsScene.swift:19-20` holds `@AppStorage("cicada.settingsSection") sectionRaw` mirrored into `@State selection`; `:34` restores on `.onAppear` (once per view lifetime) and `:35` writes back on `.onChange(of: selection)` — the reverse direction is missing, so `EmptyStateView.swift:48-50`'s seed (written by a `.simultaneousGesture` before `SettingsLink` opens the window) is ignored whenever Settings is already open. `:33` pins `.frame(width: 900, height: 640)` while every token inside scales with `CicadaTheme.uiScale` (`Theme/CicadaTheme.swift:217`, `:247-252`).
- **Hand-offs:** `AppRouter` (`Support/AppRouter.swift`, 39 lines) only mutates flags — `routeToFeedAddSource` (`:26-29`) and `pendingFirstRun` (`:21`), set directly by `SettingsGeneralView.swift:111-114`. Nothing orders the main window front; the only `NSApplication.shared.activate` calls are the launch path (`CicadaApp.swift:69`) and the menu-bar item (`:161-163`), both of which pick a window with `windows.first(where: { $0.canBecomeKey })` (`:108`, `:154`, `:162`) — a predicate the Settings window also satisfies.
- **Feed visibility:** `api/routers/sources.py:480-584` (`list_sources`) walks the whole `url_index`, parses each media page, reads `status` at `:531` (the per-entry defaults it overrides are seeded at `:503-512`, above the `try`) and passes it straight through into `MediaSourceItem` (`api/models/schemas.py:1518`). It never reads `enrichment_status`, which `link_enrichment` stamps `"junk"` for consent/login interstitials (`api/services/link_enrichment.py:179`, `:886`) and which only two writers read back (`:670`, `link_recon.py:145`). G129 slice 2's `remove` archives the media entity (`inbox_service.py:962-966`) — and the row keeps rendering. `FeedViewModel.swift:60-68` filters on search text alone. The ETag recipe is `etag_for(memory_path, "sources", "episodes", "entities", extra=sort)` (`sources.py:494`) — `entities` already covers a status/enrichment flip on a media page, so no widening is needed.
- **`sleep.next_at`:** `api/routers/state.py:107` calls `sleep_scheduler.next_run_at(memory_path)` with neither `last_cycle_at` nor `newest_unprocessed_at`, and the comment above it discloses the gap. `next_run_at` (`sleep_scheduler.py:81-116`) needs both: `interval` anchors on `base = last_cycle_at or current` (`:110-112`) so an uncalibrated call always reads "N hours from now", and `after_import` returns `None` unless `newest_unprocessed_at` is passed (`:114-116`). `GET /status` does it correctly (`api/routers/status.py:88-101`): one `await sleep_debt.compute(...)`, `last_cycle_at` derived from `debt.hours_since_last_cycle`, `newest_unprocessed_at` straight off `SleepDebt` (`sleep_debt.py:75`, `:303`). `compute` is engine-free by its own docstring (`sleep_debt.py:273-278`: "no LLM, no subprocess beyond the one bounded `git log`"), and `state_dictionary._sleep_block` (`:261-273`) deliberately keeps `next_at` out of the file. `api/tests/test_state_wiring.py:202-211` asserts `data["sleep"]["next_at"] == sleep_scheduler.next_run_at(api_bank)` — the uncalibrated call, i.e. a regression net pointed backwards.
- **Owner-name literals in shipped, non-test code:** `mcp/server.py:244` (the `cicada_get_perspective` tool **description**, twice — a facet example plus a legacy-slug compat clause), `:250` and `:299` (`subject` argument examples), `:254`, `:293`, `:318` (three more compat clauses), `:317` (the `observer` **enum**, which is protocol), `:1759-1760` (a docstring example); `api/services/conflict_resolver.py:711` inside `_CONTRADICTION_PROMPT` (`:695-720`) — an **LLM prompt** primed with a real person's name; plus lower-stakes comment/docstring examples at `api/services/predicates.py:286`, `:312-313`, `api/services/entity_resolver.py:153-154`, `:734`, `api/services/logo_service.py:11`, `api/services/fact_sources.py:14`, `api/services/local_refs.py:70`. `api/services/owner_identity.py:41-42` already owns the legacy value as a named constant (`DEFAULT_OBSERVER` = the portable keyword, `LEGACY_OBSERVER` = the legacy slug — this plan does not type either literal, per R8) with a comment explaining it. Every Swift/JS occurrence is the lowercase **wire value** as an enum case (`Models/Claim.swift:10`, `graph.js:73`, `:95`), rendered as `Copy.you` — protocol, not a name.
- **Graph canvas:** `GraphView.swift:29-36` still carries `TODO(G26)`; `updateNSView` (`:44-59`) pushes `setPanToggle` / `setHoverSuppressed` guarded on `viewModel.isGraphReady` and a `lastX` field on the Coordinator. `Resources/graph/index.html:11` makes the canvas transparent (the SwiftUI background shows through), so only the *drawn* colours are hardcoded: contextless edges `#262A33` (`graph.js:82`, `:1249`), label shadow `rgba(0,0,0,0.85)` (`:1451`), node labels `#ECEDF2` (`:1477`), edge-label plate `rgba(14, 15, 20, 0.85)` + text `#C7CBD6` (`:1519`, `:1523`), hover plate `rgba(14, 15, 20, 0.92)` + text `#ECEDF2` (`:1545`, `:1547`), search ring `#FFFFFF` (`:1360`). Entry points are plain top-level functions (`setHoverSuppressed` `:228`, `setPanToggle` `:233`, `revealNode` `:1145`); `scheduleRedraw()` (`:1180`) repaints without touching the simulation. `CicadaTheme.Dark`/`.Light` give the exact twins (`CicadaTheme.swift:290-301`, `:408-419`): background `#0E0F14`/`#F5F6FA`, textPrimary `#ECEDF2`/`#14161C`, textSecondary `#9BA1AE`/`#51566A`, border `#262A33`/`#E3E5EC`, borderLight `#363B47`/`#CACDD9`, surface `#16171D`/`#FFFFFF`.
- **The JS harness:** `Tests/graph/graph-physics-harness.js:58-83` — `loadGraph()` runs the real `graph.js` in a `vm` context with a Proxy 2d context, and `get(expr)` evaluates an expression **in that same context**, which is how top-level `let`/`const` module state is read (`:79`). `node --test app/CicadaApp/Tests/graph/*.test.js` must report 0 failures (`docs/goals/working-method.md:40`).

## Global Constraints

- Work ONLY in `<worktree>` (branch `feat/polish-truth`, based on `dev` @ `53885a1`). Every shell command is `cd <worktree> && <cmd>` with absolute paths (`zoxide` hijacks relative `cd`; ignore its stderr warning). Never an unquoted `--include=*.ext` (zsh globbing breaks it) — quote it or use `rg`.
- NEVER read `<repo>/memory` (any bank), `~/.cicada`, `~/Library`, or `~/.claude/projects`. Fixtures are synthetic: `alpha-project`, `bob-example`, `example.com`, `ep_2026-09-01_001`, origins `claude-code` / `safari-tab`.
- Python: `api/.venv/bin/python -m pytest <files> -q -p no:cacheprovider`; the full suite `api/tests` must report **0 failures** (2119 passed on 2026-09-05). `test_agent_provenance.py::test_a_decay_only_change_lands_in_its_own_cicada_authored_commit` is order-dependent and pre-existing — if it is the ONLY red, re-run it alone and report both results.
- Swift: `cd .../polish/app/CicadaApp && swift build 2>&1 | tail -5` must succeed and `swift test 2>&1 | tail -20` must report **0 failures** (763 passed on 2026-09-05; SourceKit diagnostics naming OTHER worktrees are noise). JS: `node --test app/CicadaApp/Tests/graph/*.test.js`, 0 failures. NEVER run `make dev`, `make install-app`, `swift run`, or launch/kill the Cicada app — the owner's installed app is live; the orchestrator installs at the end.
- Never `git add -A`; stage named files only. Never commit `memory/`, `logs/`, `.claude/`, `api/.venv`, or `*-report.md`. No push, no new branches or worktrees, no subagents. Ignore Devin/PR comments.
- **Files owned by other tracks this round — do not edit:** `app/.../Views/Sleep/*` (Track A), `app/.../Views/Sources/*` (Track S), `OriginIconography.swift` / `LogoImage.swift` / `OriginMark` (Track L), `MediaPreview` / `HeroPreview` / `WebView` (Track V), and `app/.../Views/Feed/FeedView.swift` (Track V). Where a fix would normally touch one of those, this plan reaches it through a default or a shared component instead — see Rulings R1 and R7.
- **Sleep-safety:** every read path stays engine-free; no LLM at capture time; every scheduled path keeps `user_triggered=False` (ruling 4).
- **ETag ship-together:** the only ETagged payload this plan changes is `GET /sources`, whose recipe already covers `entities` — the component that moves when a media page's `status`/`enrichment_status` flips. Task 4 proves that with a test rather than asserting it. No client mapping changes.
- **Copy:** every user-visible sentence added goes through `Theme/Copy.swift`; every font goes through `CicadaTheme.font(size:)` (`FontLiteralLintTests` fails the build otherwise).
- **Privacy:** no owner name, no other person's name, no bank content in code, tests, docs, commit messages or PR bodies. Task 6 removes such literals *without ever typing one into a test file* — see R8.
- Docstrings explain WHY, citing the G-row / spec / review that motivated the rule. Match the density of the files touched.
- Line numbers above are from `53885a1` and drift as tasks land — read the cited code before editing.

## Rulings (binding, decided here so no task stalls)

- **R1 — the toolbar audit is executed by flipping `TopBarControls`'s defaults, not by editing five call sites.** `showsSleep` and `showsUpload` become `false`. Three reasons, in order: (a) `Views/Sleep/SleepView.swift` (Track A) and `Views/Feed/FeedView.swift` (Track V) call this component and are owned by other worktrees this round — a signature change would conflict at merge, a default flip cannot; (b) the default *is* the policy — a page added later inherits "`?` only", which is the rule the audit establishes; (c) the flags survive as a documented opt-in seam, so a future page that genuinely needs a Sleep button says so explicitly instead of inheriting one. Dead `showUploadOverlay` plumbing is removed from the two pages this track owns (Graph, Clusters); the Feed's copy is listed under "Not in scope" with its reason.
- **R2 — the `?` keeps its place, but stops describing buttons.** `HelpContent.actions` becomes `HelpContent.aboutCicada` and `HelpPopoverContent` becomes `AboutCicadaPopover`: two paragraphs, both true on every page that renders it — capture is the harness's own Stop hook (G105, no button, no tool call), consolidation is manual until a schedule is chosen, and a scheduled cycle never spends plan quota (ruling 4). The enum keeps exactly two cases, so `TopBarControlsTests.testHelpContentIsExactlyTwoCases` keeps its shape and `SleepView`'s `.howSleepWorks` call site is untouched.
- **R3 — onboarding gets the toggle, not softer copy.** The honest fix for "it also runs on its own schedule" is to *make it run*: a "Run nightly at 3:00" toggle over the existing `PUT /sleep/schedule` (`mode: "daily"`, `hour: 3`, `minute: 0`), off by default, writing `mode: "manual"` when switched back. The sentence under it is a pure function of the schedule the backend reports, so the copy can never drift from the behaviour again — that is test gap 7 closed at its root.
- **R4 — 03:00 local, and the toggle never invents a mode.** The toggle only ever moves between `manual` and `daily @ 03:00`. If the bank already carries `interval` or `after_import` (set in Settings → Sleep), the toggle renders **on** and its line names that mode instead, and flipping it off writes `manual` — onboarding never silently downgrades a schedule the person chose elsewhere.
- **R5 — the Feed filter is server-side and archived items are hidden, not deleted.** `list_sources` skips `status in {"archived", "dropped"}` and `enrichment_status == "junk"`. G129 slice 2's contract is unchanged (a `remove` archives, never deletes); this makes the answer visible. The client filter (`FeedViewModel`) is left alone — one rule, one place, and `SourceOverview.ownedItems` filters an already-filtered payload, so a source page's list agrees for free. The backend `source_overview.build_overview` **card count** is not re-derived here (Track S owns the Sources page's numbers; see "Not in scope").
- **R6 — `/state` reuses `/status`'s inputs, it does not invent its own.** `GET /state` makes the same single `await sleep_debt.compute(memory_path, settings)` call and derives `last_cycle_at` from `hours_since_last_cycle` exactly as `api/routers/status.py:92-97` does — one formula, two callers, no second bank scan and no divergence. `compute` is engine-free and internally cached, so the engine-free read-path rail holds. `next_at` stays per-request and is still never written to `_state.md` (R1 of G53).
- **R7 — `activateMainWindow()` lives on `AppRouter` and is called by the router's own hand-off methods, not by each view.** `routeToFeedAddSource` activates; a new `requestFirstRun()` sets `pendingFirstRun` and activates. Both hand-off sites then have exactly one call each and cannot forget. Which window is "main" is decided by a **pure, testable** predicate `AppRouter.isMainWindow(identifier:title:canBecomeKey:)` — `canBecomeKey`, and neither the identifier nor the title is the Settings window's — because an `NSWindow` cannot be built in this test suite but the predicate can be exercised directly. `IntegrationsView` gains `var onHandOff: () -> Void = {}`, fired after the router call; `FirstRunSheet` passes `finish`, so the hand-off inside the sheet dismisses it instead of routing behind a modal.
- **R8 — the portability lint asserts the pattern the fix introduces, and never types a name.** Three assertions, each reading the literal from `owner_identity.LEGACY_OBSERVER` at runtime: (1) the **title-cased** form appears nowhere under `api/` (excluding `api/tests/`) or `mcp/` — a capitalised given name is always a person, never a wire value; (2) no MCP tool `description` (tool-level or per-property) contains the lowercase form — the `observer` **enum** keeps it, the prose does not; (3) no module-level `*_PROMPT` constant in `api/services/` contains it — no LLM is primed with a person's name. The enum member stays (protocol compatibility, CLAUDE.md R12: a schema that rejects what a description names is a bug) but is built from `owner_identity.LEGACY_OBSERVER` so `mcp/server.py` holds no name literal of its own.
- **R9 — the placeholder is a literal, not an interpolation.** All three high-stakes strings take `the owner` / `owner`, never a value resolved from `owner_identity` at runtime. `mcp/server.py`'s `TOOLS` is a module constant built at import, before any bank is known, and a tool description must not vary per bank (one prose source, G75 R12); and interpolating a real name back into an LLM prompt would reintroduce exactly the priming problem on a shared or demo bank.
- **R10 — `setTheme` repaints, it never re-lays-out.** It swaps a palette table and calls `scheduleRedraw()`. It must never touch `simulation`, `alpha`, `alphaTarget` or `restart()` (G109: every custom force multiplies by alpha; the release path never bumps alpha — a theme flip is not even a release). An unknown mode falls back to `dark` rather than throwing mid-draw.
- **R11 — the canvas theme follows `@Environment(\.colorScheme)`, not a static read.** `CicadaApp.swift:104` sets `.preferredColorScheme` from the persisted `AppColorScheme`, so the SwiftUI environment value tracks `CicadaTheme.mode` exactly — and an environment change is what reliably re-runs `updateNSView` on an `NSViewRepresentable`, which a static `CicadaTheme.mode` read inside `updateNSView` would not.
- **R12 — every new *sentence* and every cross-page *pointer* is a `Copy` constant with a test; short in-view labels follow the file's existing convention.** That is the line `Copy.swift`'s own header already draws (pointers, page subtitles, shared action verbs) and the one `testNoViewRetypesAPointerLiteral` actually enforces. Concretely: `aboutCicadaCapture`, `aboutCicadaSleep`, `onboardingRunNightly` and `integrationsEmpty` go through `Copy` and each gets an assertion in `CopyConstantsTests`; the section headers and one-word row labels this plan adds (`"ABOUT CICADA"`, `"Capture"`, `"Sleep"`, `"Checking your integrations…"`) stay inline exactly as their neighbours already are (`HelpPopoverContent`'s `"ABOUT THESE ACTIONS"`, `ConnectedChannelsStrip`'s `"Checking your sources…"`) — a rule that made those into constants would be a different, larger change than this track.

---

## File map

| File | Task | Responsibility |
|---|---|---|
| `app/…/Views/Common/TopBarControls.swift` | 1 | defaults flip to `false`; `HelpContent.aboutCicada`; `AboutCicadaPopover` rewritten against G105 + ruling 4 |
| `app/…/ContentView.swift`, `app/…/Views/Topics/TopicsView.swift` | 1 | dead `showUploadOverlay` state + `UploadOverlay` presentation removed |
| `app/…/Tests/CicadaAppTests/TopBarControlsTests.swift` | 1 | defaults are now `false`; the popover case is `.aboutCicada` |
| `CLAUDE.md` | 1 | one line in the Navigation paragraph |
| `app/…/Views/Onboarding/OnboardingSleepStep.swift` | 2 | nightly toggle + a status line derived from the live `ScheduleConfig` |
| `app/…/Theme/Copy.swift` | 1, 2 | `aboutCicadaCapture`, `aboutCicadaSleep`, `onboardingRunNightly`, `onboardingScheduleOff/On` |
| `app/…/Tests/CicadaAppTests/OnboardingScheduleTests.swift` (new) | 2 | the copy is a pure function of the mode |
| `app/…/Models/IntegrationCategory.swift` | 3 | `rows(from:)` also requires `channelId == nil` |
| `app/…/Views/Settings/IntegrationsView.swift` | 3 | `LoadState` + skeleton/error/empty; `onHandOff` |
| `app/…/Views/Inbox/InboxCardView.swift`, `app/…/Views/Inbox/QuestionView.swift` | 3 | `MergeReject.resolution(existingName:)`; "Keep separate" sends it and disables when empty |
| `app/…/Views/Settings/SettingsScene.swift` | 3 | `.onChange(of: sectionRaw)`; `uiScale`-aware frame |
| `app/…/Views/Onboarding/FirstRunSheet.swift` | 3 | `uiScale`-aware frame; `IntegrationsView(onHandOff: finish)` |
| `app/…/Support/AppRouter.swift` | 3 | `activateMainWindow()`, `isMainWindow(...)`, `requestFirstRun()` |
| `app/…/Views/Settings/SettingsGeneralView.swift` | 3 | "Run setup again" → `router.requestFirstRun()` |
| `app/…/Tests/CicadaAppTests/IntegrationsViewTests.swift`, `AppRouterTests.swift`, `SettingsSectionTests.swift` (**exists** — add cases to it), `InboxMergeRejectTests.swift` (new) | 3 | one test per one-liner |
| `api/routers/sources.py` | 4 | `list_sources` hides archived/dropped + junk |
| `api/tests/test_feed_visibility.py` (new) | 4 | the filter and its ETag |
| `api/routers/state.py` | 5 | calibrated `next_at` |
| `api/tests/test_state_wiring.py` | 5 | the test stops encoding the bug |
| `mcp/server.py`, `api/services/conflict_resolver.py`, `predicates.py`, `entity_resolver.py`, `logo_service.py`, `fact_sources.py`, `local_refs.py` | 6 | placeholders |
| `api/tests/test_owner_name_portability.py` (new) | 6 | the R8 lint |
| `app/…/Resources/graph/graph.js` | 7 | `PALETTES`, `setTheme(mode)`, every drawn colour reads `PALETTE` (`CONTEXT_COLORS` `:63-70` and `OBSERVER_BADGE_COLORS` `:71-75` are IDENTITY colours and stay theme-independent) |
| `app/…/Views/Graph/GraphView.swift` | 7 | push `setTheme`; `TODO(G26)` deleted |
| `app/CicadaApp/Tests/graph/graph-theme.test.js` (new) | 7 | both palettes resolve every key; unknown mode falls back |
| `docs/goals/TODO.md` | 7 | the "small polish left behind" bullet loses what this branch closed |

---

### Task 1: The toolbar audit by deletion, and a `?` that is true

**Files:**
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Common/TopBarControls.swift:5-24, 96-100, 106-156`
- Modify: `app/CicadaApp/Sources/CicadaApp/ContentView.swift:219, 245-251, 317-325`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Topics/TopicsView.swift:11, 55-72`
- Modify: `app/CicadaApp/Sources/CicadaApp/Theme/Copy.swift`
- Modify: `CLAUDE.md` (the **Navigation** paragraph)
- Test: `app/CicadaApp/Tests/CicadaAppTests/TopBarControlsTests.swift:14-42`, `app/CicadaApp/Tests/CicadaAppTests/CopyConstantsTests.swift`

**Interfaces:**
- Produces: `TopBarControls.showsSleep = false`, `.showsUpload = false`, `help: HelpContent = .aboutCicada`; `enum HelpContent { case aboutCicada, howSleepWorks }`; `struct AboutCicadaPopover`; `Copy.aboutCicadaCapture`, `Copy.aboutCicadaSleep`.
- Consumes: unchanged — `SleepView.swift:93-99` still passes `showsSleep: false, showsUpload: false, help: .howSleepWorks` and compiles byte-for-byte.

- [ ] **Step 1: Failing tests**

Rewrite `TopBarControlsTests.swift`'s first two cases and add a copy assertion. **Also rewrite the class doc comment (`:5-11`)** — it currently ends "their defaults must keep showing both buttons with the original \"About these actions\" popover", which this task inverts; the new text should say the default is now "`?` only" and name R1's reason (`SleepView`/`FeedView` are owned by other tracks this round, so the signature stays source-compatible while the policy changes).

```swift
    /// Track P R1 — the audit resolved by REMOVING, and the removal is a
    /// default, not five edits: `Views/Sleep/SleepView.swift` (Track A) and
    /// `Views/Feed/FeedView.swift` (Track V) call this component from other
    /// worktrees this round, so the signature has to stay source-compatible
    /// while the policy changes. A page added later inherits "`?` only".
    func testFlagsDefaultToHidingBothButtonsAndTheAboutPopover() {
        let view = TopBarControls(selectedTab: .constant(.graph), showUploadOverlay: .constant(false))
        XCTAssertFalse(view.showsSleep, "Sleep starts on the Sleep page (G125 R10), never from a global button")
        XCTAssertFalse(view.showsUpload, "a one-shot import lives behind the Feed's + (G126 rule)")
        XCTAssertEqual(view.help, .aboutCicada)
    }

    /// The Sleep page's explicit call site is unchanged by the default flip —
    /// it still says what it means, and still asks for its own popover.
    func testSleepPageStillAsksForTheSleepExplainerExplicitly() {
        let view = TopBarControls(
            selectedTab: .constant(.sleep),
            showUploadOverlay: .constant(false),
            showsSleep: false,
            showsUpload: false,
            help: .howSleepWorks
        )
        XCTAssertEqual(view.help, .howSleepWorks)
    }

    /// Exhaustive switch — a compile-time guarantee that a THIRD case can't
    /// be added without every call site (and this test) being revisited.
    func testHelpContentIsExactlyTwoCases() {
        for content: HelpContent in [.aboutCicada, .howSleepWorks] {
            switch content {
            case .aboutCicada, .howSleepWorks: break
            }
        }
    }
```

Add to `CopyConstantsTests.swift`:

```swift
    /// Track P — the `?` popover is reachable from Graph, Clusters and Feed,
    /// so every sentence in it has to be true on all three. Two things it
    /// used to get wrong: capture was described as an MCP-client property
    /// (G105 replaced that with the harness's own Stop hook) and
    /// consolidation was described as automatic (a fresh install's schedule
    /// is `manual` — `api/services/sleep_scheduler.py::_DEFAULT`).
    func testTheAboutPopoverDoesNotClaimAutomaticConsolidationOrMCPCapture() {
        let sleep = Copy.aboutCicadaSleep
        XCTAssertFalse(sleep.lowercased().contains("automatically"))
        XCTAssertFalse(sleep.lowercased().contains("mcp client"))
        XCTAssertTrue(sleep.contains(Copy.settingsSleep), "it must point at the place a schedule is set")
        XCTAssertFalse(Copy.aboutCicadaCapture.lowercased().contains("mcp client"))
    }
```

Run (expect: compile failure on `.aboutCicada`, then two red):
```
cd <worktree>/app/CicadaApp && swift test --filter 'TopBarControlsTests|CopyConstantsTests' 2>&1 | tail -20
```

- [ ] **Step 2: Implement**

In `Theme/Copy.swift`, next to the other pointer constants (near `settingsSleep`, `:42`). Both new constants interpolate pointers declared LATER in the file (`settingsIntegrations`, `:46`) — that is fine and needs no reordering: `Copy` is an `enum` and its `static let`s are lazily initialised globals, so declaration order does not constrain them.

```swift
    // Track P — the `?` popover, shown on Graph, Clusters and Feed. One
    // paragraph per half of the Awake/Sleep split, each true on a DEFAULT
    // install: capture is the harness's own Stop hook (G105 — not a model
    // choosing to call a tool, not an MCP-client property), and nothing
    // consolidates until a schedule is chosen (`sleep_scheduler._DEFAULT`
    // is `manual`). The last clause is TODO.md ruling 4, stated rather than
    // hidden.
    static let aboutCicadaCapture =
        "Every Claude Code and Codex session is saved as it ends, by the harness's own hook — no button, no tool call. Bookmarks, feeds, calendars and chat exports arrive through \(settingsIntegrations) and the Feed's + button."
    static let aboutCicadaSleep =
        "Consolidation is not automatic. Sleep runs when you press Consolidate on the Sleep page, or on the schedule you pick in \(settingsSleep) — nightly, every few hours, or after an import. A scheduled cycle never spends your plan quota."
```

In `TopBarControls.swift`, replace the enum, the two defaults and the popover:

```swift
/// Which popover the `?` button opens. Track P: the audit removed the Sleep
/// and Upload buttons from every page (R1), so "About these actions" no
/// longer had any actions to describe — `.actions` became `.aboutCicada`,
/// one paragraph per half of Awake/Sleep, true on every page it renders on.
/// The Sleep page keeps its own page-specific explainer.
enum HelpContent: Equatable {
    case aboutCicada
    case howSleepWorks
}
```

```swift
    /// Track P R1 — the audit resolves by REMOVING: a cycle starts on the
    /// Sleep page (G125 R10 made that the one Consolidate control) and the
    /// menu-bar bookworm offers "Run Sleep" globally (`CicadaApp.swift:166`);
    /// a one-shot import lives behind the Feed's `+` and ⌘N (CLAUDE.md's
    /// Integrations rule). Both flags survive as an opt-in seam rather than
    /// being deleted, because `Views/Sleep/SleepView.swift` passes them
    /// explicitly and a page added later may earn one back — but the DEFAULT
    /// is now the policy.
    var showsSleep: Bool = false
    var showsUpload: Bool = false
    var help: HelpContent = .aboutCicada
```

`body`'s popover switch becomes `case .aboutCicada: AboutCicadaPopover()`. Rename `HelpPopoverContent` → `AboutCicadaPopover` and rewrite its two rows: header `Text("ABOUT CICADA")`, first row `Image(systemName: "antenna.radiowaves.left.and.right")` + `Text("Capture")` + `Text(Copy.aboutCicadaCapture)`, second row `Image(systemName: "moon.fill")` + `Text("Sleep")` + `Text(Copy.aboutCicadaSleep)`. Keep every existing font/spacing token exactly as it is (`CicadaTheme.font(size:)` throughout — `FontLiteralLintTests` enforces it).

In `ContentView.swift`: delete `@State private var showUploadOverlay = false` (`:219`), pass `showUploadOverlay: .constant(false)` in the `TopBarControls(...)` call, delete the `// Upload overlay` comment and its `if showUploadOverlay { UploadOverlay(...) }` block (`:318-322`) and the `.animation(..., value: showUploadOverlay)` line (`:325`). Update the `// Top-right: Ask + Sleep + Upload + Help buttons` comment to `// Top-right: Ask + Help (Track P: the audit removed Sleep/Upload — a cycle starts on the Sleep page, an import behind the Feed's +)`. Do the same three deletions in `TopicsView.swift`: the `@State` at `:11`, and the `// Upload overlay` comment plus its `if showUploadOverlay { UploadOverlay(...) }` block at `:68-72`.

In `CLAUDE.md`, append one sentence to the **Navigation** paragraph:

> A page's top-right control is the `?` alone — Track P's audit removed the global Sleep and Upload buttons, because a cycle starts from the Sleep page's one Consolidate control (G125 R10) or the menu-bar bookworm, and a one-shot import lives behind the Feed's `+` (the G126 rule above).

- [ ] **Step 3: Verify + commit**

```
cd <worktree>/app/CicadaApp && swift build 2>&1 | tail -5
cd <worktree>/app/CicadaApp && swift test 2>&1 | tail -20
cd <worktree> && rg -n "showUploadOverlay" app/CicadaApp/Sources | cat
```
The last command must show hits only in `TopBarControls.swift`, `FeedView.swift` and the two `.constant(false)` call sites.

```
cd <worktree> && git add app/CicadaApp/Sources/CicadaApp/Views/Common/TopBarControls.swift app/CicadaApp/Sources/CicadaApp/ContentView.swift app/CicadaApp/Sources/CicadaApp/Views/Topics/TopicsView.swift app/CicadaApp/Sources/CicadaApp/Theme/Copy.swift app/CicadaApp/Tests/CicadaAppTests/TopBarControlsTests.swift app/CicadaApp/Tests/CicadaAppTests/CopyConstantsTests.swift CLAUDE.md && git commit -m "$(cat <<'EOF'
feat(Track P): the toolbar audit resolves by deletion, and the `?` stops describing buttons that are gone

Sleep and Upload leave every page: a cycle starts from the Sleep page's one
Consolidate control (G125 R10) or the menu-bar bookworm, and a one-shot import
lives behind the Feed's + (the G126 rule). Executed as a default flip on
`TopBarControls` (R1) so `SleepView` and `FeedView` — owned by other tracks
this round — stay source-compatible.

`HelpContent.actions` becomes `.aboutCicada`: the old paragraph claimed
consolidation happens automatically for MCP clients, which is false twice over
— a fresh install's schedule is `manual`, and capture has been the harness's
own Stop hook since G105.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RHX6oujZ79siqkHAqkP7CC
EOF
)"
```

---

### Task 2: Onboarding offers a nightly schedule, and its sentence follows the schedule

**Files:**
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Onboarding/OnboardingSleepStep.swift` (whole file)
- Modify: `app/CicadaApp/Sources/CicadaApp/Theme/Copy.swift`
- Test: `app/CicadaApp/Tests/CicadaAppTests/OnboardingScheduleTests.swift` (new)

**Interfaces:**
- Produces: `enum OnboardingSchedule { static func isOn(_ cfg: ScheduleConfig) -> Bool; static func line(_ cfg: ScheduleConfig) -> String; static func toggled(on: Bool, current: ScheduleConfig) -> ScheduleConfig }` — pure, file-scope, unit-tested; `Copy.onboardingRunNightly`. (All three take the whole `ScheduleConfig`, which is what the tests and the implementation below both use — it is `Equatable` with `var` fields and a `ScheduleConfig(mode:hour:minute:intervalHours:)` init defaulting `intervalHours` to 6, so `var next = current; next.mode = …` compiles.)
- Consumes: `SleepViewModel.schedule` / `.load()` / `.updateSchedule(_:)` (`ViewModels/SleepViewModel.swift:21, 170, 303`), `ScheduleConfig` (`Services/APIClient.swift:799`). No new endpoint.

- [ ] **Step 1: Failing test** — `app/CicadaApp/Tests/CicadaAppTests/OnboardingScheduleTests.swift`

```swift
import XCTest
@testable import CicadaApp

/// Track P (recent-work #2, test gap 7) — the first-run sheet used to tell a
/// brand-new install that Sleep "also runs on its own schedule". It does not:
/// `api/services/sleep_scheduler.py::_DEFAULT` is `mode="manual"`, and
/// `register_job` registers NOTHING for manual — so the one sentence a new
/// person reads about automation was false, on the very first screen, which
/// inverts the "transparency over magic" principle.
///
/// The fix is a toggle, not softer copy (R3): the step writes the schedule it
/// describes. These tests pin the half that no UI is needed to exercise — the
/// line is a pure function of the mode the backend reports, so the copy can
/// never drift from the behaviour again.
final class OnboardingScheduleTests: XCTestCase {

    func testManualNeverClaimsASchedule() {
        let line = OnboardingSchedule.line(ScheduleConfig(mode: "manual", hour: 3, minute: 0))
        XCTAssertFalse(line.lowercased().contains("own schedule"))
        XCTAssertFalse(line.lowercased().contains("automatically"))
        XCTAssertTrue(line.lowercased().contains("only when you ask"))
    }

    func testDailyNamesTheHourItActuallyWrote() {
        XCTAssertTrue(OnboardingSchedule.line(ScheduleConfig(mode: "daily", hour: 3, minute: 0)).contains("3:00"))
        XCTAssertTrue(OnboardingSchedule.line(ScheduleConfig(mode: "daily", hour: 22, minute: 30)).contains("22:30"))
    }

    /// R4 — a schedule chosen in Settings is never silently downgraded to
    /// "nightly at 3": the toggle reads ON and the line names the real mode.
    func testIntervalAndAfterImportKeepTheirOwnWords() {
        XCTAssertTrue(OnboardingSchedule.isOn(ScheduleConfig(mode: "interval", hour: 3, minute: 0, intervalHours: 6)))
        XCTAssertTrue(OnboardingSchedule.line(ScheduleConfig(mode: "interval", hour: 3, minute: 0, intervalHours: 6)).contains("6 hours"))
        XCTAssertTrue(OnboardingSchedule.isOn(ScheduleConfig(mode: "after_import", hour: 3, minute: 0)))
        XCTAssertFalse(OnboardingSchedule.isOn(ScheduleConfig(mode: "manual", hour: 3, minute: 0)))
    }

    /// Turning it ON from a manual bank writes exactly `daily 03:00`; turning
    /// it OFF from ANY scheduled mode writes `manual` — the toggle only ever
    /// moves between those two, it never invents a third (R4).
    func testTogglingWritesOnlyManualOrDailyAtThree() {
        let on = OnboardingSchedule.toggled(on: true, current: ScheduleConfig(mode: "manual", hour: 3, minute: 0))
        XCTAssertEqual(on.mode, "daily"); XCTAssertEqual(on.hour, 3); XCTAssertEqual(on.minute, 0)
        let off = OnboardingSchedule.toggled(on: false, current: ScheduleConfig(mode: "interval", hour: 9, minute: 15, intervalHours: 4))
        XCTAssertEqual(off.mode, "manual")
        // The hour/minute a person set elsewhere survive an OFF write, so
        // re-enabling in Settings restores what they chose.
        XCTAssertEqual(off.hour, 9); XCTAssertEqual(off.minute, 15)
        // Already scheduled + toggled on again = unchanged, never rewritten
        // to 03:00 (R4).
        let keep = OnboardingSchedule.toggled(on: true, current: ScheduleConfig(mode: "after_import", hour: 3, minute: 0))
        XCTAssertEqual(keep.mode, "after_import")
    }
}
```

Run (expect: compile failure — `OnboardingSchedule` does not exist):
```
cd <worktree>/app/CicadaApp && swift test --filter OnboardingScheduleTests 2>&1 | tail -20
```

- [ ] **Step 2: Implement**

Add to `Theme/Copy.swift` beside the other onboarding constants (`:218-224`):

```swift
    /// Track P R3 — the first-run toggle's label. Says the exact schedule it
    /// writes (`daily`, 03:00), because the sentence beneath it is derived
    /// from what the backend reports and the two must agree on a fresh bank.
    /// On a bank that ALREADY carries `interval`/`after_import` the toggle
    /// reads ON and the derived line names THAT mode (R4) — the label is the
    /// name of the thing the toggle turns on, not a claim about the current
    /// schedule.
    static let onboardingRunNightly = "Run a Sleep cycle nightly at 3:00"
```

and the matching assertion in `CopyConstantsTests` (R12):

```swift
    /// Track P R3/R4 — the label must name the schedule `OnboardingSchedule.
    /// toggled(on: true, current: manual)` actually writes, or the toggle
    /// promises one thing and does another. `03:00` is
    /// `sleep_scheduler._DEFAULT`'s hour.
    func testTheOnboardingToggleLabelNamesTheScheduleItWrites() {
        XCTAssertTrue(Copy.onboardingRunNightly.contains("3:00"))
        XCTAssertEqual(OnboardingSchedule.toggled(on: true,
                                                  current: ScheduleConfig(mode: "manual", hour: 3, minute: 0)).hour, 3)
    }
```

Add to `OnboardingSleepStep.swift`, above the view:

```swift
/// Track P R3/R4 — the pure half of "does this install actually consolidate
/// on its own?", so the sentence the first-run sheet shows is a function of
/// the schedule the backend reports rather than a hand-written promise. The
/// shipped default is `manual` (`api/services/sleep_scheduler.py::_DEFAULT`,
/// whose `register_job` registers no job at all), which is why the old copy
/// — "it also runs on its own schedule" — was false on every new install.
enum OnboardingSchedule {
    static func isOn(_ cfg: ScheduleConfig) -> Bool { cfg.mode != "manual" }

    static func line(_ cfg: ScheduleConfig) -> String {
        switch cfg.mode {
        case "daily":
            return "Cicada will consolidate nightly at \(cfg.hour):\(String(format: "%02d", cfg.minute))."
        case "interval":
            return "Cicada will consolidate every \(cfg.intervalHours) hours."
        case "after_import":
            return "Cicada will consolidate a few minutes after new material arrives."
        default:
            return "Sleep runs only when you ask. Turn this on and Cicada consolidates while you sleep."
        }
    }

    /// The toggle moves between exactly two states (R4). Turning it ON from a
    /// bank that ALREADY carries `interval`/`after_import` returns that config
    /// unchanged — onboarding never downgrades a schedule chosen in
    /// `Settings → Sleep`. Turning it OFF preserves `hour`/`minute` so
    /// re-enabling there restores what the person picked.
    static func toggled(on: Bool, current: ScheduleConfig) -> ScheduleConfig {
        if !on {
            var next = current; next.mode = "manual"; return next
        }
        if isOn(current) { return current }
        var next = current; next.mode = "daily"; next.hour = 3; next.minute = 0
        return next
    }
}
```

In the view: add `@State private var loadedOnce = false`, a `.task { if !loadedOnce { loadedOnce = true; await sleepVM.load() } }` on the outer `VStack` (mirroring `SettingsSleepView.swift:53-59`), and between the status line and the "Run Sleep now" button:

```swift
            Toggle(Copy.onboardingRunNightly, isOn: Binding(
                get: { OnboardingSchedule.isOn(sleepVM.schedule) },
                set: { on in
                    Task { await sleepVM.updateSchedule(OnboardingSchedule.toggled(on: on, current: sleepVM.schedule)) }
                }
            ))
            .toggleStyle(.switch)
            .font(CicadaTheme.bodyFont)
            .foregroundStyle(CicadaTheme.textSecondary)
            .frame(maxWidth: 420, alignment: .leading)
```

Replace `statusLine`'s `else` branch with `OnboardingSchedule.line(sleepVM.schedule)`, and update the type's doc comment to record why the toggle is here (the false-promise finding, and that this is the same `PUT /sleep/schedule` Settings → Sleep drives, not a second writer).

- [ ] **Step 3: Verify + commit**

```
cd <worktree>/app/CicadaApp && swift test 2>&1 | tail -20
```

```
cd <worktree> && git add app/CicadaApp/Sources/CicadaApp/Views/Onboarding/OnboardingSleepStep.swift app/CicadaApp/Sources/CicadaApp/Theme/Copy.swift app/CicadaApp/Tests/CicadaAppTests/OnboardingScheduleTests.swift && git commit -m "$(cat <<'EOF'
feat(Track P): onboarding offers a nightly schedule instead of promising one

The first-run sheet told a new install that Sleep "also runs on its own
schedule". `sleep_scheduler._DEFAULT` is `manual` and `register_job` registers
nothing for it, so a person who finished the tour got a bank that never
consolidates — "transparency over magic" inverted on the first screen.

Adds a "Run a Sleep cycle nightly at 3:00" toggle over the existing
PUT /sleep/schedule, and derives the sentence under it from the schedule the
backend reports (`OnboardingSchedule.line`), so the copy cannot drift from the
behaviour again. A schedule already chosen in Settings → Sleep is named, never
downgraded (R4).

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RHX6oujZ79siqkHAqkP7CC
EOF
)"
```

---

### Task 3: Six one-liners the suite can finally see

Six independent app-side defects from the recent-work read (#5, #6, #8, #9, #11, #12), each one or two lines of production code and each closing a named test gap. One commit, six tests.

**Files:**
- (a) Modify: `app/CicadaApp/Sources/CicadaApp/Models/IntegrationCategory.swift:64-68`; Test: `app/CicadaApp/Tests/CicadaAppTests/IntegrationsViewTests.swift:37-41`
- (b) Modify: `app/CicadaApp/Sources/CicadaApp/Views/Inbox/QuestionView.swift` (add `MergeReject`), `Views/Inbox/InboxCardView.swift:362-367`; Test: `app/CicadaApp/Tests/CicadaAppTests/InboxMergeRejectTests.swift` (new)
- (c) Modify: `app/CicadaApp/Sources/CicadaApp/Views/Settings/SettingsScene.swift:33-35`; Test: `app/CicadaApp/Tests/CicadaAppTests/SettingsSectionTests.swift` — **this file already exists** (35 lines; `testRestoredFallsBackToGeneral` already covers `SettingsSection.restored(from:)`, so do NOT re-add that assertion). Add the two cases below to the existing class; do **not** mark it `@MainActor` — nothing it touches is actor-isolated (`CicadaTheme`/`ThemeStore` are not, and its sibling `ThemeScaleTests` writes `CicadaTheme.uiScale` from a plain `XCTestCase`).
- (d) Modify: `app/CicadaApp/Sources/CicadaApp/Support/AppRouter.swift`, `Views/Settings/IntegrationsView.swift:12-26, 72-76`, `Views/Settings/SettingsGeneralView.swift:111-114`, `Views/Onboarding/FirstRunSheet.swift:59-68`; Test: `app/CicadaApp/Tests/CicadaAppTests/AppRouterTests.swift`
- (e) Modify: `SettingsScene.swift:33`, `FirstRunSheet.swift:50`; Test: `SettingsSectionTests.swift` (existing — see (c))
- (f) Modify: `Views/Settings/IntegrationsView.swift`; Test: `IntegrationsViewTests.swift`

**Interfaces:**
- Produces: `IntegrationHarnessRows.rows(from:)` gains a `channelId == nil` predicate; `enum MergeReject { static func resolution(existingName:) -> QuestionResolution? }`; `AppRouter.activateMainWindow()`, `AppRouter.isMainWindow(identifier:title:canBecomeKey:)`, `AppRouter.requestFirstRun()`; `IntegrationsView.onHandOff: () -> Void = {}`; `IntegrationsView.LoadState` + `IntegrationsView.loadState(channels:overview:isLoading:error:)`.
- Consumes: `SourceOverview.channelId` (`Models/SourceOverview.swift:28`), `Store.domainErrors` / `Snapshot.isRefreshing` (`Sync/Store.swift:74`, `Sync/Snapshot.swift:3-9`), `CicadaTheme.scaled(_:)` (`Theme/CicadaTheme.swift:217`).

- [ ] **Step 1: Failing tests**

(a) + (f) — in `IntegrationsViewTests.swift`, replace `testHarnessRowsComeFromSourcesOverview` and add the load-state cases:

```swift
    /// Test gap 1 — the OLD fixture defaulted `channelId` to nil, which is
    /// the one shape that hides the bug. `api/services/source_overview.py:50`
    /// gives `chat-export:claude` BOTH `kind = "harness"` AND a channel id, so
    /// the page rendered "Claude export" as an informational harness row and
    /// "Claude chat export" as a real channel row — and the harness copy said
    /// "Captured automatically — no setup needed", which is false for a
    /// one-shot file drop.
    func testHarnessRowsDropAnythingThatIsAlsoAChannel() {
        let overview = [
            SourceOverview(id: "claude-code", label: "Claude Code", kind: .harness),
            SourceOverview(id: "chat-export:claude", label: "Claude export", kind: .harness,
                           channelId: "chat-export:claude"),
            SourceOverview(id: "chrome-bookmarks", label: "Chrome", kind: .browser),
        ]
        XCTAssertEqual(IntegrationHarnessRows.rows(from: overview).map(\.id), ["claude-code"])
    }

    /// recent-work #12 — Integrations is also onboarding STEP 3, so the worst
    /// case is a brand-new install on the step whose whole purpose is "connect
    /// one channel", staring at a PageHeader over blank space while the
    /// backend is still starting. Same three-state shape
    /// `ConnectedChannelsStrip.loadState` already uses.
    func testLoadStateDistinguishesLoadingFromFailedFromEmpty() {
        XCTAssertEqual(IntegrationsView.loadState(channels: nil, overview: nil, isLoading: true, error: nil), .loading)
        XCTAssertEqual(IntegrationsView.loadState(channels: nil, overview: nil, isLoading: false, error: nil), .loading,
                       "no snapshot, not refreshing, no error = the fetch has not started")
        XCTAssertEqual(IntegrationsView.loadState(channels: nil, overview: nil, isLoading: false, error: "Connection refused"),
                       .failed("Connection refused"))
        XCTAssertEqual(IntegrationsView.loadState(channels: [], overview: [], isLoading: false, error: nil), .empty)
        // A latched error never hides rows the app already has.
        XCTAssertEqual(
            IntegrationsView.loadState(channels: [SourceChannel(id: "rss", label: "RSS", connected: true)],
                                       overview: [], isLoading: false, error: "Connection refused"),
            .loaded
        )
    }
```

(b) — `app/CicadaApp/Tests/CicadaAppTests/InboxMergeRejectTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// Test gap 3 — the merge-reject contract was tested on the server
/// (`api/tests/test_merge_rejections.py:116-120` proves an explicit
/// `merge_target` works) and untested on the client, so a "Keep separate"
/// that sent NO target passed both suites while 400ing in the app.
///
/// `inbox_service.resolve` resolves the other side of the pair as
/// `merge_target_hint` OR `request.merge_target` and raises 400 when both are
/// empty — and the hint is absent exactly when the extractor wrote "Possible
/// duplicate" with no candidate (`clarification_manager.py:155-169` returns
/// None) or when the item was migrated (`inbox_migration.py:154-157` only sets
/// the key `if hint`). The name is sitting in the field two rows above the
/// button; the view just never sent it.
final class InboxMergeRejectTests: XCTestCase {

    func testRejectCarriesTheExistingEntityAsItsMergeTarget() {
        let r = MergeReject.resolution(existingName: "alpha-project")
        XCTAssertEqual(r?.action, "reject")
        XCTAssertEqual(r?.mergeTarget, "alpha-project")
        XCTAssertNil(r?.mergeSurvivor, "a reject decides nothing about which name survives")
    }

    func testWhitespaceIsTrimmedAndAnEmptyTargetProducesNoRequest() {
        XCTAssertEqual(MergeReject.resolution(existingName: "  alpha-project  ")?.mergeTarget, "alpha-project")
        XCTAssertNil(MergeReject.resolution(existingName: "   "),
                     "with no hint and nothing typed there is no pair to remember — disable, never 400")
        XCTAssertNil(MergeReject.resolution(existingName: ""))
    }
}
```

(c) + (e) — **append these two cases to the EXISTING `app/CicadaApp/Tests/CicadaAppTests/SettingsSectionTests.swift`** (keep its three current cases and its header comment; add a paragraph to that header recording #9 and #11). No new imports are needed — the file already has `import XCTest` / `@testable import CicadaApp`, and the class stays a plain `XCTestCase`.

```swift
    /// recent-work #9 — `EmptyStateView`'s "Open Integrations" seeds
    /// `UserDefaults["cicada.settingsSection"]` in a `.simultaneousGesture`
    /// and relies on `SettingsScene`'s `.onAppear` to read it. `onAppear`
    /// fires once per view lifetime, and Settings is a separate window that
    /// is very often ALREADY open — so the seed was written and never read,
    /// and the person landed on whatever section they last used.
    ///
    /// A source-text check, exactly like `testSettingsSceneUsesANavigationSplitView`
    /// above: `@AppStorage`'s KVO-driven republish is what makes this work at
    /// runtime, and there is no ViewInspector-free way to observe a SwiftUI
    /// `.onChange` from this suite — so the regression net is that the
    /// mirror stays SYMMETRIC (a write on `selection`, a read on
    /// `sectionRaw`), which is the thing that was missing.
    func testSettingsSceneMirrorsTheStoredSectionBackOntoSelection() throws {
        let url = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("Sources/CicadaApp/Views/Settings/SettingsScene.swift")
        let text = try String(contentsOf: url, encoding: .utf8)
        XCTAssertTrue(text.contains("onChange(of: selection)"), "the write half")
        XCTAssertTrue(text.contains("onChange(of: sectionRaw)"), "the read half — recent-work #9")
    }

    /// recent-work #11 — `SettingsScene` and `FirstRunSheet` pin fixed frames
    /// while every font and spacing token inside them scales with
    /// `CicadaTheme.uiScale` (G130). At the top of `ThemeStore.scaleRange`
    /// (1.4) the sheet's footer — which is NOT inside its ScrollView — is the
    /// first thing to clip.
    func testWindowFramesScaleWithUiScale() {
        let previous = CicadaTheme.uiScale
        defer { CicadaTheme.uiScale = previous }
        CicadaTheme.uiScale = 1.0
        XCTAssertEqual(SettingsScene.windowWidth, 900, accuracy: 0.5)
        XCTAssertEqual(FirstRunSheet.sheetWidth, 780, accuracy: 0.5)
        // 1.4 is `ThemeStore.scaleRange.upperBound`; the setter snaps to the
        // nearest 0.1 step and clamps, so this is a value it really holds.
        CicadaTheme.uiScale = 1.4
        XCTAssertEqual(SettingsScene.windowWidth, 1260, accuracy: 1.0)
        XCTAssertEqual(SettingsScene.windowHeight, 896, accuracy: 1.0)
        XCTAssertEqual(FirstRunSheet.sheetWidth, 1092, accuracy: 1.0)
        XCTAssertEqual(FirstRunSheet.sheetHeight, 896, accuracy: 1.0)
    }
```

(d) — add to `AppRouterTests.swift`:

```swift
    /// recent-work #8 — both Settings → main-window hand-offs only mutated a
    /// flag. `ContentView` consumes it on the MAIN window, but nothing
    /// activated the app or ordered that window front, so Settings stayed key
    /// and the button read as broken. Worse inside onboarding, where
    /// `FirstRunSheet` embeds `IntegrationsView` whole: the hand-off fired
    /// from inside a modal sheet that never dismissed.
    ///
    /// Which window is "main" is a pure predicate so it can be tested at all —
    /// an NSWindow cannot be stood up in this suite, and the app's existing
    /// `windows.first(where: { $0.canBecomeKey })` (`CicadaApp.swift:162`)
    /// happily returns the Settings window.
    func testIsMainWindowRejectsTheSettingsWindowAndAnythingUnkeyable() {
        XCTAssertTrue(AppRouter.isMainWindow(identifier: "SwiftUI-Window-1", title: "Cicada", canBecomeKey: true))
        XCTAssertFalse(AppRouter.isMainWindow(identifier: "com_apple_SwiftUI_Settings_window", title: "Settings", canBecomeKey: true))
        XCTAssertFalse(AppRouter.isMainWindow(identifier: nil, title: "Settings", canBecomeKey: true))
        XCTAssertFalse(AppRouter.isMainWindow(identifier: "SwiftUI-Window-1", title: "Cicada", canBecomeKey: false))
    }

    /// `requestFirstRun` exists so BOTH hand-offs go through the router and
    /// neither view can forget to bring the window forward (R7).
    func testRequestFirstRunStagesTheSheet() {
        let router = AppRouter()
        XCTAssertFalse(router.pendingFirstRun)
        router.requestFirstRun()
        XCTAssertTrue(router.pendingFirstRun)
    }
```

Run (expect: compile failures, then red):
```
cd <worktree>/app/CicadaApp && swift test --filter 'IntegrationsViewTests|InboxMergeRejectTests|SettingsSectionTests|AppRouterTests' 2>&1 | tail -25
```

- [ ] **Step 2: Implement**

(a) `IntegrationCategory.swift` — one predicate, with the reason:

```swift
    static func rows(from overview: [SourceOverview]) -> [SourceOverview] {
        // A row that HAS a channel id is already rendered by this page as a
        // real, connectable channel — `api/services/source_overview.py:50`
        // gives `chat-export:*` both `kind = "harness"` and a `channel`, so
        // taking `kind` alone printed every chat export twice, the second copy
        // captioned "Captured automatically — no setup needed" (false: an
        // export is a one-shot file drop). The informational rows this list is
        // for are the ones with nothing to connect: Claude Code, Cursor, Codex.
        overview.filter { $0.kind == .harness && $0.channelId == nil }
    }
```

(b) In `QuestionView.swift`, beside `QuestionResolution`:

```swift
/// "Keep separate" on a merge suggestion — a REMEMBERED verdict, not a
/// dismissal (G113 slice 3b: the backend records the pair in
/// `_merge_rejected.yaml` so neither `clarification_manager` nor the dedup
/// sweep proposes it again). `inbox_service.resolve` needs the other side of
/// the pair, taking `merge_target_hint` OR `mergeTarget`; the hint is absent
/// for a hintless "Possible duplicate" and for every migrated item, so the
/// view has to send what the person has in the target field. `nil` here means
/// "there is no pair yet" — the caller disables the button rather than firing
/// a request the backend must 400.
enum MergeReject {
    static func resolution(existingName: String) -> QuestionResolution? {
        let target = existingName.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !target.isEmpty else { return nil }
        return QuestionResolution(action: "reject", mergeTarget: target)
    }
}
```

`InboxCardView.swift:362-367` becomes:

```swift
                InboxActionButton(title: "Keep separate", icon: "xmark", color: CicadaTheme.textSecondary,
                                  disabled: MergeReject.resolution(existingName: existingName) == nil) {
                    if let resolution = MergeReject.resolution(existingName: existingName) { fire(resolution) }
                }
```
(keeping the existing G113 comment above it).

(c) `SettingsScene.swift` — add below `:35`:

```swift
        // recent-work #9 — `onAppear` fires once per view lifetime, and this
        // is a separate window that is usually ALREADY open when
        // `EmptyStateView`'s "Open Integrations" seeds the key. Mirroring the
        // stored value back onto `selection` makes the pair symmetric: the
        // `onChange(of: selection)` above writes, this one reads.
        .onChange(of: sectionRaw) { _, raw in selection = SettingsSection.restored(from: raw) }
```

(e) `SettingsScene.swift:33` and `FirstRunSheet.swift:50`, each with a static so the test can see it:

```swift
    /// G130 — every font and spacing token inside this window scales with
    /// `CicadaTheme.uiScale`, so a fixed frame clips at the top of
    /// `ThemeStore.scaleRange`. `minWidth`/`minHeight` rather than a hard
    /// `frame` so the person can still make it bigger.
    static var windowWidth: CGFloat { CicadaTheme.scaled(900) }
    static var windowHeight: CGFloat { CicadaTheme.scaled(640) }
```
`.frame(width: 900, height: 640)` → `.frame(minWidth: Self.windowWidth, minHeight: Self.windowHeight)`. Same shape in `FirstRunSheet` with `sheetWidth`/`sheetHeight` over `780`/`640` (the footer at `:94-129` is outside the ScrollView and clips first).

(d) `AppRouter.swift` — `import AppKit`, then:

```swift
    /// R7 — every Settings → main-window hand-off goes through the router, so
    /// no view can stage a flag and forget to bring the window forward. The
    /// app's existing "first window that can become key"
    /// (`CicadaApp.swift:162`) is not good enough here: the Settings window
    /// satisfies it, which is exactly the window we are trying to leave.
    func activateMainWindow() {
        // `AppRouterTests.testRouteToFeedStagesTileAndTab` and
        // `testConsumeClearsAfterOneRead` already call
        // `routeToFeedAddSource`, which now reaches this method — and
        // `NSApplication.shared` INSTANTIATES NSApp on first touch, which a
        // headless `swift test` process must never be made to do. Reading the
        // `NSApp` global does not create it, so this guard makes the method a
        // no-op in the suite while staying a straight-line call in the app,
        // where `CicadaApp.swift:69` has already brought NSApp up.
        guard let app = NSApp else { return }
        app.activate(ignoringOtherApps: true)
        let target = app.windows.first {
            Self.isMainWindow(identifier: $0.identifier?.rawValue, title: $0.title, canBecomeKey: $0.canBecomeKey)
        }
        target?.makeKeyAndOrderFront(nil)
    }

    /// Pure so it can be tested — an `NSWindow` cannot be stood up in the
    /// XCTest target. SwiftUI stamps its Settings scene's window with the
    /// `com_apple_SwiftUI_Settings_window` identifier and the localised title
    /// "Settings"; both are checked because neither is contractual.
    static func isMainWindow(identifier: String?, title: String, canBecomeKey: Bool) -> Bool {
        guard canBecomeKey else { return false }
        if (identifier ?? "").localizedCaseInsensitiveContains("settings") { return false }
        if title.localizedCaseInsensitiveCompare("settings") == .orderedSame { return false }
        return true
    }

    /// G117's "Run setup again" hand-off, paired with its activation for the
    /// same reason `routeToFeedAddSource` is.
    func requestFirstRun() {
        pendingFirstRun = true
        activateMainWindow()
    }
```
and `routeToFeedAddSource` gains `activateMainWindow()` as its last line.

`SettingsGeneralView.swift:113` becomes `router.requestFirstRun()`.

(f) `IntegrationsView.swift` — add the hand-off closure, the load state, and the three-state body:

```swift
    /// Fired after a row hands off to the main window. Default is a no-op
    /// (Settings → Integrations, where the window activation IS the whole
    /// hand-off); `FirstRunSheet` passes `finish` so a hand-off from inside
    /// onboarding dismisses the sheet instead of routing behind a modal
    /// (recent-work #8).
    var onHandOff: () -> Void = {}
```

```swift
    enum LoadState: Equatable { case loading, failed(String), empty, loaded }

    /// recent-work #12 — the same three-state shape
    /// `ConnectedChannelsStrip.loadState` uses, over the two domains this page
    /// reads. A latched error never hides rows the app already has: last
    /// known good beats a blank page (the Store's own "view models never
    /// blank" rule).
    static func loadState(channels: [SourceChannel]?, overview: [SourceOverview]?,
                          isLoading: Bool, error: String?) -> LoadState {
        if let channels, let overview {
            return channels.isEmpty && overview.isEmpty ? .empty : .loaded
        }
        if isLoading { return .loading }
        if let error { return .failed(error) }
        return .loading
    }

    private var isLoading: Bool {
        (store.channels.isEmpty && store.channels.isRefreshing)
            || (store.sourcesOverview.isEmpty && store.sourcesOverview.isRefreshing)
    }
    private var loadError: String? { store.domainErrors[.channels] ?? store.domainErrors[.sourcesOverview] }
```

In `body`, wrap the `ForEach(IntegrationCategory.allCases)` block in a switch on `Self.loadState(channels: store.channels.value, overview: store.sourcesOverview.value, isLoading: isLoading, error: loadError)`: `.loading` renders three `RoundedRectangle`-and-`ProgressView` placeholder rows plus `Text("Checking your integrations…")`; `.failed(let message)` renders the `exclamationmark.triangle` + message pair (copy the exact shape from `ConnectedChannelsStrip.swift:87-95`); `.empty` renders `Text(Copy.integrationsEmpty)`; `.loaded` renders today's category list. Add to `Theme/Copy.swift`, beside the other empty-state constants (near `emptyGraphMessage`):

```swift
    /// Settings → Integrations with BOTH domains loaded and both empty —
    /// which on a working install means the backend is not answering, since
    /// `channel_registry` always yields thirteen rows. Never shown while a
    /// fetch is in flight or an error is latched (`IntegrationsView.
    /// loadState`), so it can only ever mean "confirmed nothing".
    static let integrationsEmpty = "No integrations found — is the Cicada backend running?"
```

and its assertion in `CopyConstantsTests` (R12 — it is an empty-state message, not a page subtitle, so it does NOT belong in `testSubtitlesAreShortAndDoNotRepeatTheirTitle`'s pair list):

```swift
    /// Track P — the empty state must say what to DO, not just that there is
    /// nothing (the same bar `emptyGraphMessage` set for G117).
    func testIntegrationsEmptyStateNamesTheThingToCheck() {
        XCTAssertFalse(Copy.integrationsEmpty.isEmpty)
        XCTAssertTrue(Copy.integrationsEmpty.lowercased().contains("backend"))
    }
```

Finally, `IntegrationExportOnlyRow`'s action becomes `{ router.routeToFeedAddSource(tile); onHandOff() }`, and `FirstRunSheet.swift:65` becomes `IntegrationsView(onHandOff: finish)`.

- [ ] **Step 3: Verify + commit**

```
cd <worktree>/app/CicadaApp && swift build 2>&1 | tail -5
cd <worktree>/app/CicadaApp && swift test 2>&1 | tail -20
```

```
cd <worktree> && git add app/CicadaApp/Sources/CicadaApp/Models/IntegrationCategory.swift app/CicadaApp/Sources/CicadaApp/Views/Settings/IntegrationsView.swift app/CicadaApp/Sources/CicadaApp/Views/Settings/SettingsScene.swift app/CicadaApp/Sources/CicadaApp/Views/Settings/SettingsGeneralView.swift app/CicadaApp/Sources/CicadaApp/Views/Onboarding/FirstRunSheet.swift app/CicadaApp/Sources/CicadaApp/Views/Inbox/QuestionView.swift app/CicadaApp/Sources/CicadaApp/Views/Inbox/InboxCardView.swift app/CicadaApp/Sources/CicadaApp/Support/AppRouter.swift app/CicadaApp/Sources/CicadaApp/Theme/Copy.swift app/CicadaApp/Tests/CicadaAppTests/IntegrationsViewTests.swift app/CicadaApp/Tests/CicadaAppTests/InboxMergeRejectTests.swift app/CicadaApp/Tests/CicadaAppTests/SettingsSectionTests.swift app/CicadaApp/Tests/CicadaAppTests/AppRouterTests.swift && git commit -m "$(cat <<'EOF'
fix(Track P): six one-liners, each with the test that should have caught it

- Integrations listed every chat export twice, the duplicate captioned
  "captured automatically" — harness rows now require `channelId == nil`, and
  the fixture finally carries a channelId (test gap 1).
- "Keep separate" on a merge suggestion sent no target and 400d whenever the
  item had no hint; it now sends the entity the person already typed, and
  disables when there is no pair (test gap 3).
- Settings landed on the wrong section whenever the window was already open:
  `.onChange(of: sectionRaw)` makes the mirror symmetric.
- Both Settings → main-window hand-offs staged a flag and left you in
  Settings; `AppRouter.activateMainWindow()` runs at both, and the hand-off
  inside the first-run sheet now dismisses it.
- Settings and the first-run sheet pin frames that G130's uiScale grows past.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RHX6oujZ79siqkHAqkP7CC
EOF
)"
```

---

### Task 4: The Feed stops rendering what the person removed

**Files:**
- Modify: `api/routers/sources.py:480-584` (`list_sources`)
- Test: `api/tests/test_feed_visibility.py` (new)

**Interfaces:**
- Produces: `GET /sources` omits items whose media page is `status: archived|dropped` or `enrichment_status: junk`. `total` counts what is returned.
- Consumes: nothing new; the ETag recipe at `:494` is unchanged and already covers `entities`.

- [ ] **Step 1: Failing test** — `api/tests/test_feed_visibility.py`

```python
"""GET /sources hides what the person removed and what enrichment retired
(Track P, recent-work #4 and #14a; test gap 6).

G129 slice 2's `remove` ARCHIVES the media entity — `inbox_service.py:962`
sets `status: "archived"`, it never deletes — but `list_sources` passed
`status` straight through into `MediaSourceItem` and no client filtered it, so
the row was still there on the next render and the answer read as ignored.
`link_enrichment` likewise stamps `enrichment_status: "junk"` on consent and
login interstitials (`link_enrichment.py:886`) and the only readers were the
enrichment scan itself and `link_recon` — no read path filtered it, so a
retired interstitial kept a Feed row.

Hermetic: a synthetic bank, no network, no LLM.
"""
from __future__ import annotations

import json
import os
import time

from fastapi.testclient import TestClient

from api import config, main
from api.services import markdown_parser

BASE = {"type": "media", "confidence": 0.7, "created": "2026-09-01",
        "last_referenced": "2026-09-01", "tags": ["bookmark"]}


def _client(tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    (memory / "sources").mkdir()
    rows = {
        "h1": ("media-kept", "https://example.com/kept", "Kept"),
        "h2": ("media-removed", "https://example.com/removed", "Removed"),
        "h3": ("media-dropped", "https://example.com/dropped", "Dropped"),
        "h4": ("media-consent", "https://example.com/consent", "Before you continue"),
        "h5": ("media-orphan", "https://example.com/orphan", "No page at all"),
    }
    (memory / "sources" / "url_index.json").write_text(json.dumps({
        h: {"url": url, "title": title, "media_type": "bookmark",
            "media_entity_id": eid, "saved_at": f"2026-09-0{i + 1}T00:00:00+00:00"}
        for i, (h, (eid, url, title)) in enumerate(rows.items())
    }))
    for eid, status, extra in [
        ("media-kept", "active", {}),
        ("media-removed", "archived", {}),
        ("media-dropped", "dropped", {}),
        ("media-consent", "active", {"enrichment_status": "junk"}),
    ]:
        markdown_parser.write(
            memory / "entities" / f"{eid}.md",
            {**BASE, "name": eid, "status": status, **extra,
             "media": {"url": f"https://example.com/{eid}", "media_type": "bookmark"}},
            "## Summary\nSaved.",
        )
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    return TestClient(main.app), memory


def test_archived_dropped_and_junk_never_reach_the_feed(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    body = client.get("/sources").json()
    ids = [r["mediaEntityId"] for r in body["items"]]
    assert "media-kept" in ids
    assert "media-removed" not in ids, "a bookmark resolved as `remove` is archived — it must stop rendering"
    assert "media-dropped" not in ids
    assert "media-consent" not in ids, "a consent interstitial is retired, not content"
    # An index entry with no page at all is NOT a removal — nothing said to
    # hide it, and hiding it would silently drop every pre-enrichment save.
    assert "media-orphan" in ids
    assert body["total"] == len(body["items"]) == 2
    config.get_settings.cache_clear()


def test_the_existing_etag_already_covers_a_status_flip(tmp_path, monkeypatch):
    """ETag ship-together: `etag_for(..., "sources", "episodes", "entities")`
    already moves when a media page is edited in place, so hiding a row needs
    no widening — proven here rather than assumed."""
    client, memory = _client(tmp_path, monkeypatch)
    first = client.get("/sources")
    etag = first.headers["ETag"]
    assert client.get("/sources", headers={"If-None-Match": etag}).status_code == 304
    page = memory / "entities" / "media-kept.md"
    parsed = markdown_parser.parse(page)
    parsed.frontmatter["status"] = "archived"
    markdown_parser.write(page, parsed.frontmatter, parsed.body)
    # `entities` is a max-FILE-mtime component: a rewrite inside the same
    # coarse tick yields an identical ETag. Same bump `test_sources_about.py`
    # uses for the same reason — not a sleep.
    later = time.time() + 2
    os.utime(page, (later, later))
    after = client.get("/sources", headers={"If-None-Match": etag})
    assert after.status_code == 200
    assert [r["mediaEntityId"] for r in after.json()["items"]] == ["media-orphan"]
    config.get_settings.cache_clear()
```

Run (expect: both red):
```
cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_feed_visibility.py -q -p no:cacheprovider
```

**The mtime bump is not optional.** `etag_for(..., "entities", ...)` is a max-FILE-mtime component, and a rewrite inside the same coarse mtime tick produces an identical ETag — so copy `api/tests/test_sources_about.py:82-96`'s precedent EXACTLY: after `markdown_parser.write`, do

```python
    later = time.time() + 2
    os.utime(page, (later, later))
```

and add `import os` / `import time` to the new test module's imports (that file imports both for precisely this). A `time.sleep(0.01)` is NOT what the precedent does and is not reliable here.

- [ ] **Step 2: Implement** — three separate edits in `api/routers/sources.py`. Read the file first; the indentation below is load-bearing.

**(i)** Add the module constant immediately after `router = APIRouter()` (`:49`) — the module has no other top-level constants today, so this is the first one:

```python
# A media page in either state is a decision the person made (an inbox
# `remove`, G129 slice 2) or one the system already recorded (`dropped`,
# never resurfaced) — hidden from every read path, never deleted (CLAUDE.md's
# status lifecycle).
_HIDDEN_STATUSES = {"archived", "dropped"}
```

**(ii)** In `list_sources`, seed the new per-entry default beside the existing ones (`:503-512`, 8-space indent, ABOVE `if entity_path.exists():`) so the `except Exception: pass` path leaves the item visible — a page that fails to parse is not evidence of a removal:

```python
        status = "active"
        enrichment_status = ""          # NEW, beside the existing defaults
```

**(iii)** Read the field inside the existing `try` (16-space indent, right after `status = fm.get("status", "active")` at `:531`), then skip at the 8-space loop-body level, AFTER the whole `if entity_path.exists(): try/except` block and BEFORE `items.append(...)` (`:547`):

```python
                status = fm.get("status", "active")
                # Track P R5 — what the person removed, and what enrichment
                # retired, must stop rendering. G129 slice 2's `remove`
                # ARCHIVES the media entity (`inbox_service.py:962-966`) and
                # never deletes it, so the page is still on disk and this read
                # path was still emitting a row for it — the answer read as
                # ignored. `enrichment_status: "junk"` is `link_enrichment`'s
                # permanent verdict on a consent or login interstitial
                # (`:886`); until now its only readers were the enrichment
                # scan (`:670`) and `link_recon` (`:145`), so a retired page
                # kept a Feed row. Filtered HERE, on the one read path both
                # the Feed and a source page's item list use, so the two
                # agree.
                enrichment_status = str(fm.get("enrichment_status") or "")
```

```python
        # (8-space: loop body, after the parse block, before items.append)
        if status in _HIDDEN_STATUSES or enrichment_status == "junk":
            continue
```

`total` follows for free — `SourceListResponse(items=items, total=len(items))` (`:584`) counts what survived.

- [ ] **Step 3: Verify + commit**

```
cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_feed_visibility.py api/tests/test_sources.py api/tests/test_sources_about.py api/tests/test_source_overview.py api/tests/test_inbox_removal.py -q -p no:cacheprovider
cd <worktree> && api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider 2>&1 | tail -5
```

```
cd <worktree> && git add api/routers/sources.py api/tests/test_feed_visibility.py && git commit -m "$(cat <<'EOF'
fix(Track P): GET /sources hides archived, dropped and junk items

A bookmark answered "remove" in the inbox is archived, never deleted (G129
slice 2) — and `list_sources` passed `status` straight through, so the row was
still in the Feed on the next render and the answer read as ignored. The same
read path never looked at `enrichment_status`, so every consent and login
interstitial `link_enrichment` retired kept a row too.

Filtered on the one read path the Feed and a source page's item list share, so
the list and the page behind it cannot disagree. The ETag recipe is unchanged
— `entities` already moves on an in-place media-page edit, and the second test
proves it rather than assuming it.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RHX6oujZ79siqkHAqkP7CC
EOF
)"
```

---

### Task 5: `GET /state`'s next run is calibrated, and the test stops encoding the bug

**Files:**
- Modify: `api/routers/state.py:64-110`
- Modify: `api/tests/test_state_wiring.py:202-211`
- Test: same file, plus two new cases

**Interfaces:**
- Produces: `GET /state` `sleep.next_at` correct for all four modes.
- Consumes: `sleep_debt.compute` (`api/services/sleep_debt.py:273`), `sleep_scheduler.next_run_at(..., last_cycle_at=, newest_unprocessed_at=)` (`sleep_scheduler.py:81`). Unchanged: `_state.md` still never carries `next_at`; `handshake.py` still renders `queue_depth`/`last_at` only.

- [ ] **Step 1: Failing tests** — replace `test_get_state_adds_next_at_per_request_and_never_persists_it` and add two cases:

```python
def test_get_state_adds_next_at_per_request_and_never_persists_it(api_bank):
    from api.models.schemas import ScheduleConfig
    from api.services import sleep_scheduler

    sleep_scheduler.save_schedule(api_bank, ScheduleConfig(mode="daily", hour=3, minute=0))
    with TestClient(main.app) as client:
        data = client.get("/state").json()
    # `daily` needs no calibration inputs, so the bare call IS the right
    # answer here — unlike the two modes below, which is exactly why this
    # assertion used to hide the bug (test gap 4).
    assert data["sleep"]["next_at"] == sleep_scheduler.next_run_at(api_bank)
    assert data["sleep"]["next_at"].startswith("20")
    assert "next_at" not in (api_bank / "_state.md").read_text()


def test_interval_next_at_is_anchored_on_the_last_cycle_not_on_now(api_bank):
    """recent-work #15 — the uncalibrated call made `interval` read "N hours
    from now" on EVERY request, no matter when the last cycle ran, so an
    agent reading /state could never tell a schedule that just fired from one
    about to. `GET /status` already threads `last_cycle_at`; this makes the
    two agree (R6).

    `_bank` seeds one plain "seed" commit, so the fixture has NO cycle to
    anchor on and both calls would agree by accident. An aged, empty
    `Sleep cycle …` commit is what `sleep_debt._last_cycle_at` looks for
    (`--format=%aI`, subject `sleep cycle*`, `(decay)` excluded) — hence
    `--date`, which sets the AUTHOR date the scan reads.
    """
    from datetime import datetime, timedelta

    from api.models.schemas import ScheduleConfig
    from api.services import sleep_scheduler

    _git(api_bank, "commit", "-q", "--allow-empty", "--date", "2026-09-01T00:00:00+00:00",
         "-m", "Sleep cycle 2026-09-01")
    sleep_scheduler.save_schedule(api_bank, ScheduleConfig(mode="interval", hour=3, minute=0, interval_hours=6))
    with TestClient(main.app) as client:
        got = datetime.fromisoformat(client.get("/state").json()["sleep"]["next_at"])
    uncalibrated = datetime.fromisoformat(sleep_scheduler.next_run_at(api_bank))
    # Anchored on a cycle long past, `next_run_at` floors at `now`
    # (`max(candidate, current)`); the bare call anchors on `now` and returns
    # `now + 6 h`. Five hours of slack so a slow machine can't flake it.
    assert got < uncalibrated - timedelta(hours=5)


def test_after_import_next_at_is_an_instant_when_the_queue_is_not_empty(api_bank):
    """The uncalibrated call returns `None` for `after_import` — i.e. "no next
    run" — precisely when the settle probe is about to fire."""
    from api.services import episode_ids, markdown_parser, sleep_scheduler
    from api.models.schemas import ScheduleConfig

    markdown_parser.write(
        api_bank / "episodes" / "ep_2026-09-01_001.md",
        {"id": "ep_2026-09-01_001", "timestamp": episode_ids.utc_now_iso(),
         "processed": False, "origin": "claude-code", "title": "Alpha project sync"},
        "user: ship alpha-project",
    )
    sleep_scheduler.save_schedule(api_bank, ScheduleConfig(mode="after_import", hour=3, minute=0))
    assert sleep_scheduler.next_run_at(api_bank) is None
    with TestClient(main.app) as client:
        assert client.get("/state").json()["sleep"]["next_at"] is not None
```

Run (expect: the two new cases red):
```
cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_state_wiring.py -q -p no:cacheprovider
```

- [ ] **Step 2: Implement** — in `api/routers/state.py`, replace the disclosed-gap comment and the bare call:

```python
    # Per request, local clock — never in the file (see the module docstring).
    # R6: the SAME inputs `GET /status` computes (`api/routers/status.py:88`),
    # from the same single `sleep_debt.compute` call, so the primer's now-view
    # and the app's own "Next run" line cannot disagree. Without them
    # `interval` anchored on `now` and read "N hours from now" on every
    # request regardless of when the last cycle ran, and `after_import`
    # returned `null` — "no next run" — exactly when the settle probe was
    # about to fire. `compute` is engine-free and internally cached ("no LLM,
    # no subprocess beyond the one bounded `git log`"), so this read path
    # stays engine-free.
    debt = await sleep_debt.compute(memory_path, settings)
    last_cycle_at = (
        datetime.now() - timedelta(hours=debt.hours_since_last_cycle)
        if debt.hours_since_last_cycle is not None else None
    )
    state.setdefault("sleep", {})["next_at"] = sleep_scheduler.next_run_at(
        memory_path, last_cycle_at=last_cycle_at, newest_unprocessed_at=debt.newest_unprocessed_at,
    )
```

Add `from datetime import datetime, timedelta` and `sleep_debt` to the module's imports (`state.py:41-47`).

- [ ] **Step 3: Verify + commit**

```
cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_state_wiring.py api/tests/test_state_dictionary.py api/tests/test_handshake.py api/tests/test_sleep_schedule_modes.py -q -p no:cacheprovider
cd <worktree> && api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider 2>&1 | tail -5
```
(If `test_state_dictionary.py` / `test_handshake.py` / `test_sleep_schedule_modes.py` are named differently, find them with `ls api/tests | rg 'state|handshake|schedule'` and run those.)

```
cd <worktree> && git add api/routers/state.py api/tests/test_state_wiring.py && git commit -m "$(cat <<'EOF'
fix(Track P): /state's sleep.next_at is calibrated for interval and after_import

The bare `next_run_at(memory_path)` call made `interval` read "N hours from
now" on every request regardless of when the last cycle ran, and made
`after_import` read `null` — "no next run" — exactly when the settle probe was
about to fire. Only an agent reading /state directly ever saw it, which is
worse, not better: it is the one reader that cannot check the app's own line.

Threads the same `sleep_debt.compute` inputs GET /status already uses (R6), so
the two answers come from one formula. `test_state_wiring` asserted the
uncalibrated call — a regression net pointed backwards — and now encodes the
right behaviour, with a case per mode.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RHX6oujZ79siqkHAqkP7CC
EOF
)"
```

---

### Task 6: No person's name inside an agent-facing string or an LLM prompt

**Files:**
- Modify: `mcp/server.py:244, 250, 254, 293, 299, 311-318, 1755-1766`
- Modify: `api/services/conflict_resolver.py:695-720` (`_CONTRADICTION_PROMPT`)
- Modify (comments/docstrings only, zero behaviour): `api/services/predicates.py:284-315`, `api/services/entity_resolver.py:151-156, 732-735`, `api/services/logo_service.py:9-12`, `api/services/fact_sources.py:12-16`, `api/services/local_refs.py:66-72`
- Test: `api/tests/test_owner_name_portability.py` (new)

**Interfaces:**
- Produces: `mcp/server.py` imports `LEGACY_OBSERVER` from `api.services.owner_identity` and builds the `observer` enum from it; every example in a tool description or a prompt is `the owner` / `owner` / an already-synthetic placeholder.
- Consumes: `owner_identity.LEGACY_OBSERVER` (`api/services/owner_identity.py:42`) — the one documented home for the legacy wire value. `agentic_write.write_claim` already normalises it (`mcp/server.py:311` records this), so behaviour is unchanged.

- [ ] **Step 1: Failing test** — `api/tests/test_owner_name_portability.py`

```python
"""CLAUDE.md's portability rail, enforced (Track P R8; recent-work #13).

"No owner name, no author-machine path in shipped code" — G117 removed the
last hardcoded *observer* literal, but three display/prompt literals survived:
the `cicada_get_perspective` tool DESCRIPTION (sent to every agent on every
`initialize`), two `subject` argument examples, and — worst — an example
inside `conflict_resolver`'s contradiction PROMPT, which primes the extractor
with an unrelated person's name on somebody else's bank.

This module never types a name. Every assertion reads the literal from
`owner_identity.LEGACY_OBSERVER`, the one place the legacy wire value is
supposed to live, and asserts the SHAPE the fix introduced:

  1. the title-cased form appears nowhere in shipped `api/` or `mcp/` — a
     capitalised given name is always a person, never a protocol value;
  2. no MCP tool description contains the lowercase form — the `observer`
     ENUM keeps it (CLAUDE.md R12: a schema that rejects what a description
     names is a bug), the prose does not;
  3. no `*_PROMPT` constant in `api/services/` contains it — no LLM is primed
     with a person's name.
"""
from __future__ import annotations

import importlib
import inspect
import pkgutil
from pathlib import Path

import api.services as services_pkg
from api.services import owner_identity

REPO_ROOT = Path(__file__).resolve().parents[2]
SLUG = owner_identity.LEGACY_OBSERVER


def _shipped_python_files() -> list[Path]:
    """Everything that ships: `api/` minus its tests, plus `mcp/`. Test
    fixtures are excluded on purpose — they are synthetic bank data, not text
    an install ever renders, and `api/tests/*` uses the legacy slug freely as
    fixture entity data (see the plan's "Not in scope").

    Measured on `dev` @ `53885a1`: 134 files, 43,584 lines, < 0.02 s for the
    walk and the read together — cheap enough to run as a plain test."""
    files = [p for p in (REPO_ROOT / "api").rglob("*.py")
             if "tests" not in p.parts and ".venv" not in p.parts]
    files += list((REPO_ROOT / "mcp").rglob("*.py"))
    return files


def test_no_capitalised_owner_name_survives_in_shipped_code():
    needle = SLUG.capitalize()
    hits = [
        f"{p.relative_to(REPO_ROOT)}:{i}"
        for p in _shipped_python_files()
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if needle in line
    ]
    assert hits == [], f"a person's name in shipped code (portability rail): {hits}"


def test_no_mcp_tool_description_names_a_person():
    import mcp.server as server

    def _descriptions(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "description" and isinstance(value, str):
                    yield value
                else:
                    yield from _descriptions(value)
        elif isinstance(node, list):
            for item in node:
                yield from _descriptions(item)

    offenders = [d for d in _descriptions(server.TOOLS) if SLUG in d.lower()]
    assert offenders == [], "a tool description reaches every agent on initialize — keep it neutral"
    # The wire value itself is protocol and MUST stay reachable (R12).
    observer_schema = next(
        t["inputSchema"]["properties"]["observer"]
        for t in server.TOOLS if t["name"] == "cicada_write_claim"
    )
    assert SLUG in observer_schema["enum"], "the legacy observer stays accepted, it just stops being advertised"


def test_no_llm_prompt_is_primed_with_a_person():
    # Measured on `dev` @ `53885a1`: importing every `api.services` module
    # takes 1.4 s, none of them raise on import, and exactly seven module
    # constants match `*_PROMPT` — of which only `conflict_resolver.
    # _CONTRADICTION_PROMPT` carries the slug today. That is the one this
    # test exists to turn red.
    offenders = []
    for mod_info in pkgutil.iter_modules(services_pkg.__path__):
        module = importlib.import_module(f"api.services.{mod_info.name}")
        for name, value in vars(module).items():
            if name.endswith("_PROMPT") and isinstance(value, str) and SLUG in value.lower():
                offenders.append(f"api/services/{mod_info.name}.py::{name}")
    assert offenders == [], f"an LLM prompt primed with a person's name: {offenders}"


def test_the_legacy_observer_constant_is_still_the_one_home_for_it():
    """The fix moves the literal, it does not delete the compatibility
    promise: `resolve_observer` still returns it for a pre-G117 bank that
    already has that page."""
    assert SLUG and SLUG.islower()
    assert inspect.getsourcefile(owner_identity).endswith("owner_identity.py")
```

Run (expect: the first three red):
```
cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_owner_name_portability.py -q -p no:cacheprovider
```

- [ ] **Step 2: Implement**

In `mcp/server.py`, beside the existing hoisted imports (`:26-29`):

```python
# R8/R9 — the legacy observer value is protocol and must stay in the schema
# (CLAUDE.md R12: a description naming an argument the schema would reject is
# a bug), but it is a person's name, and the repo is public and the install is
# portable. Imported from its one documented home rather than retyped here, so
# `mcp/` holds no name literal of its own.
from api.services.owner_identity import LEGACY_OBSERVER  # noqa: E402
```

Then:
- `:244` — drop the compat clause and de-name the facet example: `"…optionally filtered by observer (who holds the belief: 'agent', 'owner', or 'external:<name>') and/or context (e.g. 'engineering', 'family', 'career'). Use when you need to know who believes what about a subject, or want only one facet of it (e.g. the engineering facet of the owner vs the family facet)."`
- `:250` — `"The subject entity id or name (e.g. 'owner', 'cicada')."`
- `:254`, `:293`, `:318` — delete the "still accepted for compatibility" sentences. An agent should send `owner`; the enum keeps accepting the legacy value for old callers, and advertising it only invites new ones.
- `:299` — `"The entity the claim is about (e.g. 'the owner', 'Cicada')."`
- `:317` — `"enum": ["owner", "agent", "external", LEGACY_OBSERVER],`. **Rewrite the comment above it (`:311-316`) rather than keeping it verbatim**: it currently quotes the slug, which would leave `mcp/server.py` holding a name literal of its own — exactly what this task's Interfaces line promises it will not. Say "the legacy observer value" and point at `owner_identity.LEGACY_OBSERVER`, then add the R9 reason (a module constant built at import, before any bank is known; a tool description must not vary per bank — G75 R12).
- `:1755-1766` — the docstring example becomes `Where does the owner work now?` / `entity_id=owner · predicate=works-at`.

In `conflict_resolver.py:711` — `"question": "ONE short question, in the user's voice, that resolves it (e.g. 'Where does the owner work now?')."` plus a one-line comment above the template recording R9 (a module constant built at import, and interpolating a real name would re-prime the extractor on a demo or shared bank).

The comment/docstring sweep uses the repo's own synthetic vocabulary — `Bob Example` / `bob-example` for a person, `alpha-project` for a project, `alex-mbp` for a hostname, `https://www.linkedin.com/in/bob-example` for the `fact_sources` yaml sample, and "common Spanish fillers a bank's data hits often" for `entity_resolver.py:734`. **Comments and docstrings only** — no code path changes, so no behavioural test is needed beyond the lint.

- [ ] **Step 3: Verify + commit**

```
cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_owner_name_portability.py api/tests/test_agentic_write.py api/tests/test_mcp_tools.py api/tests/test_conflict_resolver.py -q -p no:cacheprovider
cd <worktree> && api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider 2>&1 | tail -5
```
(Resolve the middle two names with `ls api/tests | rg 'mcp|conflict'` — run whatever exists; nothing may go unrun that imports `mcp.server` or `conflict_resolver`.)

```
cd <worktree> && git add mcp/server.py api/services/conflict_resolver.py api/services/predicates.py api/services/entity_resolver.py api/services/logo_service.py api/services/fact_sources.py api/services/local_refs.py api/tests/test_owner_name_portability.py && git commit -m "$(cat <<'EOF'
fix(Track P): no person's name in an agent-facing string or an LLM prompt

CLAUDE.md's portability rail says no owner name in shipped code. G117 removed
the last hardcoded observer literal — but a name survived in the
`cicada_get_perspective` tool DESCRIPTION (sent to every agent on every
initialize), in two `subject` argument examples, and inside
`conflict_resolver`'s contradiction PROMPT, where it primed the extractor with
an unrelated person on anyone else's bank.

All of them take a neutral placeholder. The legacy observer VALUE stays
accepted — it is protocol, and CLAUDE.md R12 forbids a schema that rejects
what a description names — but `mcp/server.py` now imports it from
`owner_identity` instead of retyping it, and stops advertising it.

`test_owner_name_portability.py` reads the literal from the constant and never
types it: no capitalised form anywhere in shipped `api/`/`mcp/`, none in any
tool description, none in any `*_PROMPT`.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RHX6oujZ79siqkHAqkP7CC
EOF
)"
```

---

### Task 7: The graph canvas gets the theme

**Files:**
- Modify: `app/CicadaApp/Sources/CicadaApp/Resources/graph/graph.js` — insert above `contextColor` (`:81`), then replace the literals at `:82`, `:1249`, `:1360`, `:1451`, `:1477`, `:1519`, `:1523`, `:1545`, `:1547`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Graph/GraphView.swift:16-59` (+ the Coordinator's `lastX` fields)
- Modify: `docs/goals/TODO.md` (the "Small polish left behind" paragraph)
- Test: `app/CicadaApp/Tests/graph/graph-theme.test.js` (new)

**Interfaces:**
- Produces: `PALETTES` (two tables, seven keys each), `PALETTE`, `setTheme(mode)`; `GraphView` pushes `setTheme("light"|"dark")` from `updateNSView`.
- Consumes: the `cicada` bridge and the `isGraphReady` gate already used for `setPanToggle` / `setHoverSuppressed` (`GraphView.swift:44-59`); `@Environment(\.colorScheme)`, which tracks `CicadaTheme.mode` because `CicadaApp.swift:104` sets `.preferredColorScheme` from it (R11).

- [ ] **Step 1: Failing test** — `app/CicadaApp/Tests/graph/graph-theme.test.js`

```javascript
// The graph canvas in light mode (Track P, recent-work #1). `graph.js` baked
// the dark palette into every drawn colour — node labels "#ECEDF2", tooltip
// grounds "rgba(14, 15, 20, …)", contextless edges "#262A33" — while the
// canvas itself is transparent (index.html:11) and PR #49/#60 shipped a real
// Light mode. Flip to Light and the product's front door had unreadable
// labels on near-black cards floating over a light window.
//
// Two invariants, both cheap: every key resolves in BOTH palettes (a half-
// filled table is a mid-draw `undefined` fillStyle, i.e. a silently black
// canvas), and an unknown mode falls back rather than throwing.
//
// G109 rule, restated: a theme change is a REPAINT. `setTheme` must never
// touch the simulation — no `alpha`, no `alphaTarget`, no `restart()`. The
// release path never bumps alpha, and a colour swap is not even a release.
const assert = require("assert");
const { loadGraph, synthetic, SIZES } = require("./graph-physics-harness");

const { sandbox, get, call } = loadGraph();
call("updateGraph", synthetic(SIZES.small));
const sim = get("simulation");
sim.stop();
for (let t = 0; t < 60; t++) sim.tick();

const palettes = get("PALETTES");
const modes = Object.keys(palettes);
assert.deepStrictEqual(modes.sort(), ["dark", "light"], "exactly two palettes");

const keys = Object.keys(palettes.dark).sort();
assert.ok(keys.length >= 7, `expected the full palette, got ${keys.join(",")}`);
for (const mode of modes) {
    assert.deepStrictEqual(Object.keys(palettes[mode]).sort(), keys, `${mode} is missing a key`);
    for (const k of keys) {
        const v = palettes[mode][k];
        assert.ok(typeof v === "string" && v.length > 0, `${mode}.${k} must be a colour string`);
        assert.ok(/^(#|rgba?\()/.test(v), `${mode}.${k} is not a CSS colour: ${v}`);
    }
}
assert.notDeepStrictEqual(palettes.dark, palettes.light, "the two palettes must actually differ");

// Default is dark (what the page loads with, before Swift pushes anything).
assert.strictEqual(get("PALETTE"), palettes.dark);

sandbox.setTheme("light");
assert.strictEqual(get("PALETTE"), palettes.light);
assert.strictEqual(get("themeMode"), "light");

// Unknown / null / undefined fall back to dark instead of throwing mid-draw.
sandbox.setTheme("solarized");
assert.strictEqual(get("PALETTE"), palettes.dark, "an unknown mode falls back to dark");
sandbox.setTheme(null);
assert.strictEqual(get("PALETTE"), palettes.dark);

// A contextless edge takes the palette's edge colour, in both modes.
sandbox.setTheme("light");
assert.strictEqual(get("contextColor(null)"), palettes.light.edge);
sandbox.setTheme("dark");
assert.strictEqual(get("contextColor(null)"), palettes.dark.edge);
// A CONTEXT-coloured edge is identity, not theme — unchanged by the flip.
const before = get("contextColor('engineering')");
sandbox.setTheme("light");
assert.strictEqual(get("contextColor('engineering')"), before);

// R10: repaint only. Alpha is untouched across a flip.
sandbox.setTheme("dark");
const alphaBefore = sim.alpha();
sandbox.setTheme("light");
sandbox.setTheme("dark");
assert.strictEqual(sim.alpha(), alphaBefore, "a theme change must never reheat the simulation");

console.log("All graph theme checks passed.");
```

Run (expect: red on `PALETTES` being undefined):
```
cd <worktree> && node --test app/CicadaApp/Tests/graph/graph-theme.test.js
```

- [ ] **Step 2: Implement** — in `graph.js`, above `contextColor` (`:81`, just after the `OBSERVER_BADGE_COLORS` table at `:71-75`):

```javascript
// Track P — the canvas is transparent (index.html), so only the DRAWN colours
// were dark-locked. Two tables, one key per drawn surface, each value the
// exact `CicadaTheme.Dark`/`.Light` twin so the chrome and the canvas agree.
// `labelShadow` is a HALO, not a drop shadow: on a light ground a black blur
// around dark text is what made light mode unreadable, so the light value is
// the background colour instead. `edge` takes `borderLight` in light mode —
// `border` (#E3E5EC) is invisible as a 1px line on #F5F6FA.
const PALETTES = {
    dark: {
        label:       "#ECEDF2",                    // = CicadaTheme.Dark.textPrimary
        labelShadow: "rgba(0, 0, 0, 0.85)",
        plate:       "rgba(14, 15, 20, 0.85)",     // = Dark.background
        plateStrong: "rgba(14, 15, 20, 0.92)",
        plateText:   "#C7CBD6",
        edge:        "#262A33",                    // = Dark.border
        nodeStroke:  "#FFFFFF",
    },
    light: {
        label:       "#14161C",                    // = CicadaTheme.Light.textPrimary
        labelShadow: "rgba(245, 246, 250, 0.95)",  // = Light.background, as a halo
        plate:       "rgba(255, 255, 255, 0.92)",  // = Light.surface
        plateStrong: "rgba(255, 255, 255, 0.96)",
        plateText:   "#51566A",                    // = Light.textSecondary
        edge:        "#CACDD9",                    // = Light.borderLight
        nodeStroke:  "#14161C",
    },
};
let themeMode = "dark";
let PALETTE = PALETTES.dark;

// Pushed from `GraphView.updateNSView` the same way setPanToggle /
// setHoverSuppressed are. R10: this is a REPAINT — it swaps a table and asks
// for a frame. It must never touch `simulation`, `alpha`, `alphaTarget` or
// `restart()` (G109: the release path never bumps alpha; a colour change is
// not even a release, and a re-layout would throw away every node position
// the person has dragged). An unknown mode falls back to dark rather than
// leaving `undefined` in a fillStyle, which paints a silently black canvas.
function setTheme(mode) {
    const next = PALETTES[String(mode)] ? String(mode) : "dark";
    if (next === themeMode) return;
    themeMode = next;
    PALETTE = PALETTES[next];
    scheduleRedraw();
}
```

Then replace each literal with its key: `:82` and `:1249` → `PALETTE.edge`; `:1360` → `PALETTE.nodeStroke`; `:1451` → `PALETTE.labelShadow`; `:1477` and `:1547` → `PALETTE.label`; `:1519` → `PALETTE.plate`; `:1523` → `PALETTE.plateText`; `:1545` → `PALETTE.plateStrong`. Delete the now-stale `// = CicadaTheme.textPrimary` trailing comments (the table carries them).

In `GraphView.swift`: delete the whole `TODO(G26)` comment (`:29-36`), add `@Environment(\.colorScheme) private var colorScheme` to the struct, add `var lastTheme: String?` to the Coordinator beside `lastPanMode`/`lastHoverSuppressed`, and add to `updateNSView` after the `setHoverSuppressed` block:

```swift
        // Track P R11 — the canvas follows the app's colour scheme.
        // `@Environment(\.colorScheme)` rather than a static `CicadaTheme.mode`
        // read: `CicadaApp.swift:104` sets `.preferredColorScheme` from the
        // persisted mode, so the environment value tracks it exactly — AND an
        // environment change is what reliably re-runs `updateNSView` on an
        // NSViewRepresentable, which reading an @Observable static in here
        // would not. Guarded on `isGraphReady` like every other push (before
        // that, graph.js has no `setTheme` yet) and latched on the
        // coordinator so an unrelated update never re-sends.
        let theme = colorScheme == .light ? "light" : "dark"
        if viewModel.isGraphReady, context.coordinator.lastTheme != theme {
            context.coordinator.lastTheme = theme
            webView.evaluateJavaScript("setTheme(\"\(theme)\")", completionHandler: nil)
        }
```

Finally, in `docs/goals/TODO.md`, rewrite the "**Small polish left behind by the 2026-09-05 tracks, none blocking:**" paragraph so it names only what is still open after this branch — the Integrations mark (`OriginMark` instead of the generic bubble symbol, Track L/S), and the Settings sidebar not being drivable by a synthetic `click at` — and add one sentence recording what Track P closed: the toolbar audit, the Integrations duplicate, the hintless merge-suggestion reject, and `/state`'s uncalibrated `next_at`. **Privacy rule: no names, no bank content, placeholders only.**

- [ ] **Step 3: Verify + commit**

```
cd <worktree> && node --test app/CicadaApp/Tests/graph/*.test.js
cd <worktree>/app/CicadaApp && swift build 2>&1 | tail -5
cd <worktree>/app/CicadaApp && swift test 2>&1 | tail -20
cd <worktree> && rg -n 'ECEDF2|C7CBD6|rgba\(14, 15, 20' app/CicadaApp/Sources/CicadaApp/Resources/graph/graph.js | cat
```
The last command must show hits only inside the `PALETTES` table.

```
cd <worktree> && git add app/CicadaApp/Sources/CicadaApp/Resources/graph/graph.js app/CicadaApp/Sources/CicadaApp/Views/Graph/GraphView.swift app/CicadaApp/Tests/graph/graph-theme.test.js docs/goals/TODO.md && git commit -m "$(cat <<'EOF'
feat(Track P): the graph canvas gets the theme (closes TODO(G26))

`graph.js` baked the dark palette into every drawn colour while the canvas
itself is transparent, so Light mode — shipped by PR #49's toggle and #60's
Appearance picker — painted near-white labels and near-black tooltip cards on
a light window. The product's front door was unreadable in half its modes.

Adds `setTheme(mode)` over two palette tables (label, label halo, plate, plate
text, edge, node stroke), pushed from `updateNSView` on
`@Environment(\.colorScheme)` — the value that tracks `CicadaTheme.mode` AND
actually re-runs an NSViewRepresentable's update.

R10/G109: a theme change is a repaint. `setTheme` swaps a table and schedules
a frame; it never touches alpha and never re-lays-out, so dragged node
positions survive a flip. The new node test asserts both palettes resolve
every key, that an unknown mode falls back rather than throwing mid-draw, and
that alpha is unchanged across a flip.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RHX6oujZ79siqkHAqkP7CC
EOF
)"
```

---

## Not in scope

Named here so nobody re-derives them mid-task:

- **G118 slice 2** (the provenance viewer) and **README screenshots / G90** — the orchestrator's, after the round.
- **The Sleep page** (`Views/Sleep/*`) — Track A. This plan's `TopBarControls` change is a default flip precisely so that file stays untouched (R1).
- **`Views/Feed/FeedView.swift`** — Track V. Consequence: the Feed's own `@State showUploadOverlay`, its `UploadOverlay` presentation and its `.onChange`/`.animation` become unreachable once the Upload button stops rendering. **Left for the orchestrator to sweep after Track V merges** — it is dead state, not a defect. `UploadOverlay.swift` itself stays (still the implementation behind the Feed's import path).
- **`OriginMark` on Integrations rows** (recent-work #7) — Track L owns the mark pipeline; Integrations joining channel rows to `row.mark` belongs with it, not here.
- **`source_overview.build_overview`'s card counts** — Track S owns the Sources page's numbers (R-S3/R-S5 re-source them entirely). Task 4 filters the item LIST, which is what the person sees; a card count that still includes an archived item is a Track S concern.
- **G86's real fix** (the title-slug collision in `media_ingestor.py:1454-1466` and UI grouping by `mediaEntityId`) — Task 4 ships only part (a), which recent-work calls "most of the felt improvement". The row stays open.
- **`api/tests/*` fixtures that use the legacy owner slug** as synthetic entity data (`test_agentic_write.py` and friends) — they are test fixtures, not shipped text, and the Task 6 lint excludes `api/tests/` on purpose. Renaming them is churn with no portability gain.
- **The remaining LOWERCASE mentions of the legacy slug in shipped comments/docstrings** — `api/services/agentic_write.py:12`, `:269`, `:361`; `api/services/claims.py:127`; `api/services/owner_identity.py:17`. Each is describing the *wire value* (what `write_claim` normalises, what the `observer` field may hold), which is protocol, not a person — and none of the three R8 assertions fires on them (they are not title-cased, not an MCP `description`, not a `*_PROMPT`). Left as-is deliberately: after Task 6 the ONLY shipped hits are these, so a future reader who greps and finds them has this row as the answer.
- **Retiring `LEGACY_OBSERVER` itself** — it is protocol compatibility for pre-G117 banks (`owner_identity.resolve_observer`'s rung 3). Task 6 moves the literal to one home; it does not remove the promise.
- **`ObserverFilterBar`'s labels** (G84(d) / G103) — a different row, and it needs the observer-in-the-UI decision, not a polish pass.

## Verification the orchestrator runs at the end

```
cd <worktree> && api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider 2>&1 | tail -5
cd <worktree>/app/CicadaApp && swift build 2>&1 | tail -5
cd <worktree>/app/CicadaApp && swift test 2>&1 | tail -20
cd <worktree> && node --test app/CicadaApp/Tests/graph/*.test.js
cd <worktree> && git log --oneline dev..HEAD | cat
cd <worktree> && git status --porcelain | cat
```

Expected: **0 backend failures** (2119+ passed; if `test_agent_provenance.py::test_a_decay_only_change_lands_in_its_own_cicada_authored_commit` is the ONLY red, re-run it alone and report both results — it is a known order dependency), **0 Swift failures** (763+ passed), **0 JS failures**, exactly **7 commits**, and a clean tree with nothing from `memory/`, `logs/`, `.claude/`, `api/.venv` or any `*-report.md` staged.

After install, in the live app:

1. **Light mode graph.** Settings → General → Appearance → Light. Node labels are dark on the light canvas, hover and edge-label plates are white cards with dark text, edges are visible. Flip back to Dark: identical to today. Drag a node, flip the theme mid-coast — the layout does not jump (R10).
2. **Integrations with the backend stopped.** Settings → Integrations shows a skeleton, then the actual error text — never a `PageHeader` over blank space. Same on first-run step 3.
3. **Integrations with the backend running.** Each chat export appears **once**, as a connectable channel row — never a second "captured automatically" copy.
4. **"Keep separate"** on a merge suggestion succeeds (no 400) and is disabled when the target field is empty and the item carries no hint.
5. **Toolbar.** Graph, Clusters and Feed show only `?` (plus Ask on Graph and `+` on Feed). The `?` popover says capture is automatic and consolidation is not. The Sleep page is unchanged.
6. **Onboarding.** Settings → General → "Run setup again" brings the main window forward and opens the sheet; step 4's toggle writes a schedule, and Settings → Sleep shows `daily 03:00` afterwards; the sentence under the toggle matches. Turning it off leaves `manual`.
7. **Hand-off.** "Import in Feed →" from Settings → Integrations brings the main window forward on the Feed with the sheet staged; from inside the first-run sheet it also dismisses the sheet.
8. **Feed.** A bookmark answered `remove` in the Inbox disappears from the Feed on the next render.
9. **Settings section.** With Settings already open, click "Open Integrations" from an empty state — Settings switches to Integrations rather than staying where it was. ⌘+ a few times: the Settings window and the first-run sheet grow with their contents; the sheet's Back/Next/Skip row never clips.
