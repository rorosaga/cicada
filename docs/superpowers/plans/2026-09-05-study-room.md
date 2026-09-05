# The study room (Sleep page v3, Track A) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the Sleep page into the room the owner drew — a pixel study with a night window, a cushion, a mug, a plant and a desk lamp that is lit exactly when Sleep is scheduled; a hero count with a qualifier chip and a meter that never renders without its noun; a five-stage strip that is the live instrument of a running cycle; a queue card that says what is waiting and when it will be read; and a right column of memory sources and past consolidations. **Every pixel that moves names a field, and every digit names its source.** Engine-free throughout; no prices, no tokens, no estimates.

**Architecture:** The backend gains exactly one additive field (`SourceOverview.activity`, computed inside the loop `build_overview` already runs) and one format change (`--date=iso-strict` on both history reads, with the two call sites that parse that string fixed in the same commit). The app gains a generalized `PixelRenderer` under `BookwormRenderer` (which becomes a thin facade so all **four** `Bookworm*Tests` files — `BookwormRendererTests`, `BookwormSpriteTests`, `BookwormStateTests`, `BookwormViewTests` — pass byte-for-byte; there is no fifth), a `DeskPalette` and five 24×24 props composed on one cell lattice, and a set of pure derivations — `heroCount`, `heroQualifier`, `stageStripState`, `memorySourceRows`, `sparklinePoints`, `sleepLayout`, `deskSceneLayout` — each unit-tested with no view stood up, exactly as the rest of `Views/Sleep/` is written.

**Tech Stack:** Python 3.12 / FastAPI / Pydantic (`api/`), SwiftUI + XCTest (`app/CicadaApp`), markdown + git bank.

**Spec:** `docs/superpowers/specs/2026-09-05-round2-study-room-marks-video-design.md` § **Track A**, rulings **R-A1 … R-A16** (binding). Phase-1 research (`sleep-data`, `pixel-art`, `judges`) was **session-only and is NOT checked into this repo** — do not go looking for `phase1/*.md`. Everything those readers established that this plan depends on is restated inline below (the element → data map is the numbers budget; the sprite encoding, palette, nightcap band and window grid are spelled out in Tasks 2–3; both verified traps are P1/P3). Backlog rows: **G125** (the study desk this replaces), **G107** (mascot art + the estimate deferral), **G124** (the Sources overview payload), **G130** (uiScale snapping), **G113/G122** (engine previews). Standing rulings: TODO.md ruling 4 (a scheduled cycle never spends plan quota), the 2026-09-03 ruling (no prices/tokens in the app), ETag ship-together, the docs privacy rule.

---

## What the code actually does today (verified against `feat/study-room` @ `53885a1`)

**The page.** `Views/Sleep/SleepView.swift` (485 lines) is one 760 pt column: `headerRow` → `deskCard` → optional `errorBanner` → `StudyListCard` → `ConsolidationHistoryCard`, inside a `ScrollView` with `.frame(maxWidth: 760)` (`SleepView.swift:64-83`). Top-right is `TopBarControls(… showsSleep: false, showsUpload: false, help: .howSleepWorks)` (`:92-99`) — **Track P owns that file; this track does not touch it.**

- `deskCard` (`:249-320`) resolves `debt`/`progress`/`mood`/`origins`/`rows`/`books`/`bubbleCtx` once per body eval (the H1 comment at `:13-18` is why), then draws an `HStack(alignment:.bottom)` of `SpeechBubbleView` + `BookwormView(state:pointSize:120,caption:sleepDebtBracketText(...))` and `BookPileView(books:).frame(width:170,height:150)` (`:274-290`), followed by `moodDetailLine`, `engineLine`, `cancelledBanner`, `capBanner`, `warningBanner`. The card has **no fixed height** — it reflows as banners appear.
- `moodDetailLine` (`:328-359`): while `.sleeping(stage)` it renders `Text("Stage \(stage) of 5")` + a bare `ProgressView(value: sleepVM.progressFraction)` + `Text("Stage 1: \(progress)%")`; otherwise `Text("Rested \(rested)% — volume …%, age …%")` or the no-baseline line.
- `StudyListCard.swift` (301 lines): header `"ON THE DESK"` (`:50`), rows from `studyRows` with `OriginMark`, label, `oldest \(age)` and either the count or `read / total` + a 60 pt `ProgressView` (`:182-202`), then a divider and a footer holding `nextRunLine` + `consolidateButton(count:)` + `cancelButton` (`:59-68`, `:244-300`). `nextRunText` (`:232-242`) covers manual / a real date / `after_import` / `Next run —`.
- `ConsolidationHistoryCard.swift` (220 lines): `SleepHistoryPresentation.durationText/summaryLine/dateText/engineSymbol/authorLabel` (`:7-79`) + a row of date · engine symbol · summary · duration · chevron (`:123-162`) + an expanded detail (`:164-219`).
- `HowSleepWorks.swift`: six private `Row`s — `capture` plus `Stage 1 · Read`, `Stage 2 · Sort`, `Stage 3 · Decide`, `Stage 4 · Notice`, `Stage 5 · File` (`:17-36`), each with an SF Symbol, rendered at `:45-62`. Its own docstring (`:3-8`) declares it "not a second source of truth" for the pipeline.
- `SleepMood.swift`: `resolveSleepDebt` / `resolveProgressPct` / `resolveOriginCounts` (SSE-first, REST fallback, `:27-70`), `deriveSleepPageMood` (`:94-131`), `sleepDebtBracketText` (`:143-169`) and `sleepDebtBracketColor` (`:176-186`). **Twelve bracket strings across eleven test cases are asserted verbatim** in `SleepMoodTests.swift:224-273` (awake, sleeping, digesting, happy, curious ×2, hungry ×3, error, reading ×2).
- `SleepViewModel.swift` (385 lines): `status`, `episodes`, `schedule`, `history`, `details`, `expanded`; four injectable fetches (`fetchSleepStatus`, `requestCancel`, `fetchHistory`, `fetchDetail`, `:88-129`); `loadToken` staleness guard; a 1 s poll loop while running. **It does not fetch `/sleep/engine`.**
- `BookwormRenderer.swift` (99 lines): `gridSize` is hardcoded `BookwormSprites.size` (`:10`), `image(grid:pointSize:)` (`:32-56`), `snappedPointSize(_:)` = `max(24, 24 * (pointSize/24).rounded())` (`:18-20`), `cacheKey(state:frameIndex:pointSize:)` = `"\(state.spriteKey)|\(frameIndex)|\(Int(pointSize))"` (`:64-66`), one `NSLock`-guarded dict wiped wholesale past 512 entries (`:73-97`). `BookwormPalette.colors` is **exactly nine keys** and `BookwormSpriteTests.swift:24-28` fails on a tenth.
- `BookwormView.swift` (**`Views/Common/`, not `MenuBar/`**): `frameIndex(at:interval:count:reduceMotion:)` (`:37-41`, Reduce Motion → frame 0), `snappedPointSize(pointSize * CicadaTheme.uiScale)` (`:48`), `.interpolation(.none)` (`:53`).

**The data.**

- `SleepEventPayload` (`Sync/SyncAPI.swift:132-192`) declares `var progress: Double?` and decodes it with `try? c.decodeIfPresent(Double.self, forKey: .progress)` (`:180`). The backend sends a **string** (`state.progress`, the stage sentence, `sleep_cycle.py:960` → `sync.py:91`). The mismatch is swallowed: **the field has been `nil` in the app since it shipped.** No view reads it today.
- `source_overview.build_overview(memory_path, *, channels)` (`api/services/source_overview.py:126-215`) walks `bank_index.files(memory_path, "episodes")` once (`:137`), reading `fm["timestamp"]` at `:146` for `last_activity_at`. Frontmatter only, no body parse, no git, no network. `_new_state` (`:104-124`) builds the per-source dict.
- `GET /sources/overview` (`api/routers/sources.py:587-622`) ETags `etag_for(memory_path, "sources", "episodes", "entities", extra=f"overview|telegram:{…}|connectors:{…}")` (`:605-609`). `VersionVector.mapping` already routes `episodes` → `.sourcesOverview` (`Sync/VersionVector.swift:15`), so a new field computed from episodes needs **no** mapping change — the ship-together rule is satisfied by construction, and a test must pin that the recipe did not move.
- `git_service.get_sleep_history` runs `--date=short` (`:986`) and `get_sleep_cycle_detail` runs `--date=short` (`:1031`). **Verified trap:** both then call `date.fromisoformat(e.date)` (`:1018` and `:1046`) to bound the telemetry read, and on Python 3.12 `date.fromisoformat("2026-09-05T14:23:11+02:00")` raises `ValueError` (measured in `api/.venv`). Switching the format without slicing to `[:10]` there breaks both endpoints.
- **Verified beneficial side effect:** `/status.lastSleepAt` is `entry.date` (`api/routers/status.py:191`) and the app parses it with `StatusSnapshot.parseDate` (`MenuBar/BookwormState.swift:135-145`), which is two `ISO8601DateFormatter`s with `.withInternetDateTime` — neither parses a bare `yyyy-MM-dd`. Today that value is therefore **always unparseable** (the menu bar says "never", `MenuBarManager.swift:244`). `--date=iso-strict` makes it parse. No Python or Swift test pins the old shape (grepped).
- `SleepHistoryPresentation.dateText` (`ConsolidationHistoryCard.swift:47-58`) slices `iso.prefix(10)`, parses with `TimeZone("UTC")` and formats `"MMM d"` in UTC. Its comment claims `--date=short` is "anchored UTC" — **git renders both `--date=short` and `--date=iso-strict` in the commit's own zone**, so the comment is wrong today and the pinned UTC zone will shift the displayed hour once a time exists. `SleepHistoryPresentationTests.swift:53,57` assert `dateText("2026-09-01") == "Sep 1"` and `dateText("not-a-date") == "not-a-date"`.
- `SourceOverview` Swift model (`Models/SourceOverview.swift`, 246 lines: struct `:15-41`, `CodingKeys` `:89-92`, `init(from:)` `:95-113`): a memberwise init with defaults plus a hand-written `init(from:)` where every field after `id` is `decodeIfPresent … ?? default`. **Track S owns `Views/Sources/*`; this model file is the one place this track touches on that side.**
- `Store` (`Sync/Store.swift`): `sourcesOverview` (`:35`), `banks` (`:27`), `isConnected` (`:79`), `sleepEvent` (`:81`), `intakeInFlight` (`:90`); `Snapshot.loadedAt` (`Sync/Snapshot.swift:6`) is stamped on every hydrate and every successful refresh (`Store.swift:175,194,329,376`). `BanksResponse.banks` carries `MemoryBank.entityCount` (`Services/APIClient.swift:51,89-101`) and `store.bank` names the active one.
- `GET /sleep/engine` (`api/routers/sleep.py:194-199`) returns `SleepEngineResponse` with `preview.manual` and `preview.scheduled`, each `{engine, model, why}` (`api/models/schemas.py:1312-1345`). Swift mirror `Models/SleepEngine.swift:45-80`, with `preview` **optional**; `APIClient.fetchSleepEngine()` at `Services/APIClient.swift:1918-1922`. `SleepEngineViewModel` (37 lines) exists for Settings and is not wired to the Sleep page.
- `ScheduleConfig` has `mode` (`manual|daily|interval|after_import`), `hour`, `minute`, `intervalHours`. `sleep_scheduler`'s default is `mode="manual"` and `register_job` installs **no trigger** for manual — a fresh install never sleeps, and the page says so only in one tertiary footer caption.

**The lints and test seams that will bite.**

- `FontLiteralLintTests.swift:29-42` fails the build on any `.system(size:` / `Font.system(size:` outside `Theme/CicadaTheme.swift`.
- `ThemeTokenTests.swift:71-82` bans nine hexes (`0x22C55E, 0xEF4444, 0xF59E0B, 0x3B82F6, 0x4A9EFF, 0x8B5CF6, 0x3BD97A, 0x6B7280, 0x999999`) in every source file but the theme.
- `CopyConstantsTests.swift:33-50` requires every page subtitle ≤ 60 chars, not repeating its title, never containing "page".
- `FixWaveTests.swift:30-36` greps **only** `Views/Sleep/SleepView.swift` for `Copy.consolidateNow` / `sleepVM.triggerManually()`.
- `SettingsEntryPointTests.swift:30-41` bans the private `showSettingsWindow:` selector anywhere in `Sources/`; the proven way to open Settings on a section is `SettingsLink` + a `.simultaneousGesture` seeding `UserDefaults` key `"cicada.settingsSection"` (`Views/Common/EmptyStateView.swift:39-51`). **`AppRouter` has no `pendingSection` and cannot open the Settings scene** (`Support/AppRouter.swift`, 39 lines: `pendingTab`, `pendingAddSource`, `pendingFirstRun` only).
- `BookwormRendererTests.swift:52-58` asserts the exact cache-key strings; `BookwormViewTests.swift:40-45` asserts `snappedPointSize` rounding; `BookwormSpriteTests.swift:24-28,30-43,45-51,53-59,65-71,73-77` assert palette size, grid shape, frame counts, intervals, the row-5 glasses rim and the canonical `awake` frame.
- Baselines to re-measure, never assume: **backend 2119 passed, Swift 763 passed** at the end of 2026-09-05.

---

## Global Constraints

- Work ONLY in `/Users/rorosaga/Documents/roros_lab/cicada/.worktrees/study-room` (branch `feat/study-room`, based on `dev` @ `53885a1`). Every shell command is `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/study-room && <cmd>` with absolute paths (`zoxide` hijacks relative `cd`; ignore its stderr warning). Never an unquoted `--include=*.ext` (zsh globbing breaks it) — quote it or use `rg`.
- NEVER read `/Users/rorosaga/Documents/roros_lab/cicada/memory` (any bank), `~/.cicada`, `~/Library`, or `~/.claude/projects`. Fixtures are synthetic: `alpha-project`, `bob-example`, `example.com`, `ep_2026-09-01_001`, origins `claude-code` / `safari-tab` / `telegram`.
- Python: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/study-room && api/.venv/bin/python -m pytest <files> -q -p no:cacheprovider`; the full `api/tests` suite must report **0 failures**. `test_agent_provenance.py::test_a_decay_only_change_lands_in_its_own_cicada_authored_commit` is order-dependent and pre-existing — if it is the ONLY red, re-run it alone and report both results.
- Swift: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/study-room/app/CicadaApp && swift build 2>&1 | tail -5` must succeed and `swift test 2>&1 | tail -20` must report **0 failures** (SourceKit diagnostics naming OTHER worktrees are noise). NEVER run `make dev`, `make install-app`, `swift run`, or launch/kill the Cicada app — the owner's installed app is live; the orchestrator installs at the end.
- Never `git add -A`; stage named files only. Never commit `memory/`, `logs/`, `.claude/`, `api/.venv`, or `*-report.md`. Do not push, do not create branches or worktrees, do not dispatch subagents. Ignore Devin/PR comments.
- **Ownership fences (other tracks are live in parallel worktrees).** Do **not** edit `Views/Common/TopBarControls.swift` or `ContentView`'s toolbar (Track P). Do **not** edit `Views/Sources/*` (Track S) — the only Sources-side file this track touches is `Models/SourceOverview.swift`. Do **not** edit `Views/Capture/OriginIconography.swift`, `Views/Common/LogoImage.swift` or `OriginMark` (Track L) — call them, never change them.
- **Sleep-safety:** every new read path is engine-free; nothing on this page costs an LLM call; no capture-time processing is introduced.
- **ETag ship-together:** the one new payload field rides an existing ETag component and needs no `VersionVector` change — Task 1 ships a test that pins that.
- **Portability / privacy:** no owner name, no author-machine path in shipped code or docs; no bank content, episode title, URL or person's name in any doc, commit message or PR body.
- **Decode tolerance:** every new Swift wire field is optional-with-default and an older backend payload must still decode (tested).
- Docstrings explain WHY, citing the G-row / ruling / review that motivated the rule. Match the density of the files being touched.
- Line numbers above are from `53885a1` and drift as tasks land — read the cited code before editing it.

---

## Rulings (binding for this plan)

The spec's **R-A1 … R-A16** are binding as written. The rulings below are the decisions this plan takes where the spec or the brief left a choice; each carries its reason.

- **P1 — `activity` is keyed by a real UTC day, and the docstring says so.** The brief asks for "captures that UTC day". Banks hold three timestamp shapes (G114 aware `+00:00`, legacy naive-local, `Z`-suffixed imports — `sleep_debt._parse_episode_timestamp`'s M1 lesson at `sleep_debt.py:114-144`). `raw[:10]` calls a naive-local stamp a UTC day and is silently off by one for a subset of rows — the trap the engineering judge flagged. So a naive stamp gets the system zone attached (`datetime.astimezone()` with no argument does exactly that, which is what the writer that produced it meant) and *then* converts to UTC. Keys are absolute dates, never a rolling array, so a 304'd payload renders a day **short**, never a day **shifted** (R-A16).
- **P2 — the sparkline reads UTC days too.** `sparklinePoints` builds its window with `Calendar(identifier: .gregorian)` pinned to `TimeZone(identifier: "UTC")`, because the keys it indexes are UTC days. Mixing a local window against UTC keys would shift the whole series; at worst this labels the current bucket by UTC-today rather than local-today, which is a one-bucket edge effect on an undated sparkline and never a wrong series.
- **P3 — `date.fromisoformat(e.date[:10])`, in the same commit as `--date=iso-strict`.** Verified: on Python 3.12, `date.fromisoformat` rejects a datetime string. `git_service.py:1018` and `:1046` bound the telemetry ledger read by that value; unsliced, both endpoints raise once the format changes. The slice is correct for both shapes.
- **P4 — the history parser gets an injectable time zone; display is local.** `git` renders `--date=iso-strict` in the **commit's** zone, and the current parser pins UTC with a comment claiming the opposite (`ConsolidationHistoryCard.swift:43-58`). `dateText`/`timeText` take `timeZone: TimeZone = .current`, parse the offset for real, display in the reader's zone, and the wrong comment is corrected in the same commit. Tests inject a fixed zone so they never depend on the runner's locale. A legacy `yyyy-MM-dd` value still yields the old `"Sep 1"` and a `timeText` of `"—"` (R-A14) — `SleepHistoryPresentationTests`' two existing assertions pass unchanged.
- **P5 — "Change…" opens Settings through `SettingsLink`, not `AppRouter`.** The brief points at `AppRouter`, but `AppRouter` has no section field and cannot open the Settings scene: `SidebarView`'s own docstring records the private AppKit selector being *accepted and silently ignored* on macOS 26, and `SettingsEntryPointTests.testNoPrivateSettingsSelector` fails the build on it. The proven mechanism is `SettingsLink` + a `.simultaneousGesture` seeding `@AppStorage("cicada.settingsSection")` (`EmptyStateView.swift:39-51`). Task 6 extracts that into one small `SettingsSectionLink` view so the key is **written** in exactly one place, and `EmptyStateView` adopts it. **Measured, so the lint can be stated correctly:** the literal `"cicada.settingsSection"` appears in four source files today — `Views/Settings/SettingsScene.swift:19` (the `@AppStorage` READER, which must keep it), `Views/Settings/SettingsSection.swift:12` (a doc comment), and `Views/Common/EmptyStateView.swift:43,49` (a doc comment plus the WRITE). So a lint asserting "exactly one file contains the literal" is false and always will be — the rule that is true and worth pinning is *one writer*.
- **P6 — the three hero tiles read domains the Store already holds; no new fetch, no new endpoint.** `N entities in memory` comes from the **active bank's** `MemoryBank.entityCount` in `store.banks` (already ETagged and live) rather than a fresh `GET /healthz`, which is unauthenticated, un-ETagged and outside the Store. `N sources feeding it` is `store.sourcesOverview.value` rows with `episodes > 0` — the same list the right column projects, counted once. `Last cycle` is `sleepVM.history.first { $0.kind != "decay" }?.durationMs` through the existing `durationText(ms:)`. **No `hub_count`, no new `/healthz` field** — the brief settled that. *This is a deliberate, narrow deviation from R-A6's parenthetical, which names `/healthz`'s `entity_count`:* that field does exist (`api/routers/status.py:36,41`, a raw `.md` count) but the route is auth-free, un-ETagged and not a Store domain, so reading it would add a bespoke fetch and a second freshness model to a page whose whole design is last-known-good projections. The **readout is identical**; only its source moves to the domain the Store already holds and live-refreshes.
- **P7 — the meter is one bar with two exclusive meanings and never a bare `%`.** Idle: `Rested \(pct)%` from `debt.restedPct`, hidden entirely when `restedPct == nil` (no baseline). Running: `Read \(read) of \(total)` where `read`/`total` are the sums of `readByOrigin`/`queueByOrigin` **already resolved once per body eval** by `resolveOriginCounts` (H1) — not `progressPct`, so the label's two numbers and the bar's fraction come from one reading. A code comment states the rule; `SleepHeroTests` asserts the label is non-empty whenever the bar draws.
- **P8 — `sleepDebtBracketText` is re-composed, never rewritten.** `heroCount(_:debt:) -> Int?` (the numeral), `heroQualifier(_:debt:) -> String` (the short chip: `overdue` / `behind` / `caught up` / `first run` / `reading` / `sleeping` / `digesting` / `failed` / `awake`) and `bracketTail(_:debt:) -> String` (the long caption tail) are three pure functions over the same switch; `sleepDebtBracketText` becomes `"[ " + [count, tail].compactMap … .joined(separator: " ") + " ]"`, so `SleepMoodTests.swift:224-273`'s twelve asserted strings pass **byte-for-byte**. Three details the existing strings force, read off the current switch rather than guessed:
  - `heroCount(.curious(count: n), …) == n` — the numeral comes from the CASE's associated value, not from `debt` (`"[ 47 episodes behind ]"` is asserted with `debt: nil`).
  - `heroCount(.reading, debt:)` is `debt?.unprocessedCount ?? 0` and therefore **never `nil`** — `"[ 0 to read ]"` with a nil debt is asserted today (`SleepMoodTests` `test_bracketText_reading_withNilDebt`). The hero view is what decides not to draw a `0`; `heroCount` does not lie about it.
  - `bracketTail` owns the pluralisation, so it takes the same count `heroCount` returns; `heroQualifier` is a separate, shorter word and is NOT the tail (`.reading` with `hasRunBefore: true` → chip `behind`, tail `to read`; the chip reads `reading` only when the count is 0, which is the `intakeInFlight` case). The bracket text survives as the hero group's VoiceOver label — the sprite loses its visible caption, not its meaning.
- **P9 — `first run` is a real state, not a flourish.** `heroQualifier` returns `"first run"` when `debt?.hasRunBefore == false` and the count is > 0, ahead of `behind`/`overdue`: nothing has ever been consolidated in this bank, so calling the queue a *backlog* would be wrong.
- **P10 — no decorative books anywhere on the page.** The page's one volume encoding of the queue is `BookPileView`; a painted spine stack at the same pixel scale eighteen points away would ask the reader to tell a chart from wallpaper by taste. The desk scene therefore has **no `shelfBooks` prop** — the real `BookPileView` is placed on the desk beside the worm inside the scene's own layout (R-A2).
- **P11 — the scene encodes state, never quantity, and every art bit has a text twin.** The lamp is lit iff `schedule.mode != "manual"` and the schedule row states the same fact in words (R-A3). Nothing else in the scene is data-driven. The whole scene is `.accessibilityHidden(true)` and `.allowsHitTesting(false)`.
- **P12 — one snapped point size for the whole scene.** `scenePt = PixelRenderer.snappedPointSize(120 * CicadaTheme.uiScale, gridSize: 24)`, `cell = scenePt / 24`; every prop renders at `scenePt` and is positioned by an integer **cell** count. A prop that should look smaller is authored smaller inside its own 24×24 grid. Mixed point sizes would put two pixel scales in one picture, which reads as a bug at any zoom, and would break G130 R6's single snapping call.
- **P13 — `PixelRenderer` gets its own cache.** The worm's cache wipes wholesale past 512 entries (`BookwormRenderer.swift:92`); adding scene layers and stage icons to it would make the always-animating worm collateral damage on every wipe. A second `NSLock`-guarded `sceneCache` with namespaced keys (`"desk.window|lit|120"`, `"stage.read|32"`) keeps them independent.
- **P14 — the nightcap is baked into `sleeping` and `reading` frames only.** Mascot plan R2 says `frames(for:)` returns fully composed frames and consumers never OR overlays themselves; an accessory layer would reintroduce the seam R2 deleted, and a cap that is a function of the state is already covered by `spriteKey`'s cache key. Cap rows **0–4**, tassel on the **left** (cols ≈ 2–5) so it never enters the `sleeping` z-glyph corridor at rows 0–2 / cols 19–23. Palette keys `o`/`z`/`l`/`w` only — **no tenth key**, so `testPaletteIsExactlyTheNineRoles` stays green — and row 5 (the glasses rim) is untouched.
- **P15 — the stage strip substitutes into the meter's slot; it is not a sixth card.** It replaces `moodDetailLine`'s `"Stage N of 5"` text and its `ProgressView` (R-A8). Only **Read** carries a fill fraction; stages 2–5 have no per-episode unit (`sleep_cycle.progress_pct` returns `None` past stage 0) and must not be given a fake one. A cancel or a failure **freezes** the strip at the stage it reached — it never resets to all-pending.
- **P16 — `SleepStages.all` is the one array.** Both the strip and the `?` popover read it; `HowSleepWorks.swift:5-8` already declares itself the single prose source, and the reference image's Collect/Cluster/Extract/Strengthen would be a fourth naming of the pipeline. The popover's six rows keep their exact current strings (`Stage N · <label>` + detail); the strip renders the same five short labels — **Read · Sort · Decide · Notice · File**.
- **P17 — two lists, two nouns, and no number is drawn twice.** The queue says `waiting` (and `read of total` while running); Memory sources says `captured`. The noun is on the row, never only in a tooltip. The hero's three tiles are present-tense or measured — never a forecast, never "clusters", never an estimate (G107 is binding).
- **P18 — `—` is a value with a reason.** Every dash carries a `.help(…)` naming why the number is unknowable. Never a blank, never a zero standing in for an unknown.
- **P19 — the `%`-lint is narrow on purpose.** A grep asserting "the set of numeric interpolations equals the budget table" is falsified by the first number that arrives through a `Copy.` helper or `durationText(ms:)`. The lint this plan ships is the one a regex can hold: **no line in `Views/Sleep/` that renders a `%` inside a `Text(...)` may lack a noun from the allowed set.** The budget table below is the reviewable artefact; the lint is its cheap guard.
- **P20 — task count.** The brief asks for 8–10 tasks in its order and lists eight build items; item 2 (pixel infrastructure + the scene) is two independently shippable commits and item 7 (liveness/motion/copy/lint) and item 8 (docs) stay separate, giving **nine tasks**. Every task leaves both suites green and the branch shippable.

---

## The numbers budget (R-A15)

Every digit the page can draw, its Swift field, its wire origin, and the state it appears in. A number not on this table does not belong on the page.

| # | Readout | Swift field / function | Wire origin | State |
|---|---|---|---|---|
| 1 | Hero numeral, e.g. `205` | `heroCount(mood:debt:)` → `SleepDebtView.unprocessedCount` | SSE `sleep.unprocessedCount` → REST `/sleep/status.debt.unprocessedCount` (`sleep_debt.compute`) | idle + running |
| 2 | Meter label `Rested 12%` | `debt.restedPct` | same payload, `rested_pct` = `100 − max(volume, age)` | idle only; hidden when `nil` |
| 3 | Meter label `Read 138 of 203` | sums of `resolveOriginCounts().readByOrigin` / `.queueByOrigin` | SSE `readByOrigin` / `queueByOrigin` → REST `/sleep/status` | running only |
| 4 | Tile `N entities in memory` | active `MemoryBank.entityCount` in `store.banks` | `GET /banks` | always |
| 5 | Tile `N sources feeding it` | `store.sourcesOverview.value.filter { $0.episodes > 0 }.count` | `GET /sources/overview` | always |
| 6 | Tile `Last cycle · 4 m 12 s` | `durationText(ms: history.first{kind != "decay"}?.durationMs)` | `sleep_run` telemetry joined by commit hash | measured, else `—` |
| 7 | Read pip fill (no text) | `stageStripState(…).active(fill:)` from #3 | same as #3 | running, stage 1 only |
| 8 | Queue row count `188` | `StudyRow.count` | `GET /sleep/episodes` grouped by origin | idle |
| 9 | Queue row `12 of 188` | `StudyRow.read` / `.total` | SSE `readByOrigin` / `queueByOrigin` | running |
| 10 | Queue row `oldest 87d` | `StudyRow.oldestAge` ← `ageLabel(hours:)` | episode frontmatter `timestamp` | always |
| 11 | Schedule sentence `Every 6 h` / `Every day at 02:00` | `ScheduleConfig.intervalHours` / `.hour`/`.minute` | `GET /sleep/schedule` | always |
| 12 | Footer `Next run Sep 6, 2:00 AM` | `StatusSnapshot.nextSleepAt` | `/status.next_sleep_at`, computed per request | not manual |
| 13 | Sources row `312 captured` | `SourceOverview.episodes` | `GET /sources/overview` | always |
| 14 | Sources sparkline (no text) | `sparklinePoints(activity:days:today:)` | `SourceOverview.activity` (new, Task 1) | always |
| 15 | Sources week dots (no text) | `weekDots(activity:weeks:today:)` | same | always |
| 16 | History `Sep 5 · 9:41 AM` | `dateText` / `timeText` | `git log --date=iso-strict` (Task 1) | always; time `—` on a legacy value |
| 17 | History `+5 new · 929 updated` | `entitiesCreated` / `entitiesUpdated` | commit manifest, parsed server-side | non-decay rows |
| 18 | History `· 2 episodes` | `SleepHistoryEntry.episodes` | commit manifest | non-decay rows |
| 19 | History duration | `durationText(ms:)` | telemetry join | measured, else `—` |
| 20 | Liveness chip `as of 16:12` | `Snapshot.loadedAt` | client clock at last successful refresh | only while `!store.isConnected` |

**Refused, with the reason:** "N clusters" (nothing detects clusters; `Copy.clusterCount`'s own comment forbids the word), "N insights" (a forecast of what a cycle has not yet extracted), "~3 min est. time" (G107, binding), any per-cycle confidence score (no field anywhere), any price or token count (2026-09-03 ruling).

---

## File map

| File | Responsibility |
|---|---|
| `api/services/source_overview.py` | `ACTIVITY_DAYS`, `_activity_day(raw)`, `activity` bucketed inside the existing episode loop, `today` injected |
| `api/models/schemas.py` | `SourceOverview.activity: dict[str, int]` |
| `api/services/git_service.py` | `--date=iso-strict` ×2; `date.fromisoformat(… [:10])` ×2 |
| `api/tests/test_source_overview.py` | activity buckets + the ETag-recipe pin |
| `api/tests/test_sleep_history_detail.py` | the iso-strict date shape + the telemetry join still working |
| `app/…/Models/SourceOverview.swift` | `activity` decode with `[:]` default |
| `app/…/Sync/SyncAPI.swift` | `SleepEventPayload.progress: String?` |
| `app/…/MenuBar/PixelRenderer.swift` (new) | generalized `image` / `snappedPointSize` / `cachedImage` / `nsColors` + `sceneCache` |
| `app/…/MenuBar/BookwormRenderer.swift` | four thin forwarders |
| `app/…/MenuBar/BookwormSprites.swift` | the baked nightcap on `sleeping` + `reading` |
| `app/…/Views/Sleep/DeskPalette.swift` (new) | the scene's own palette |
| `app/…/Views/Sleep/DeskSceneSprites.swift` (new) | `window`, `cushion`, `mug`, `plant`, `lampLit`, `lampDark` |
| `app/…/Views/Sleep/DeskScene.swift` (new) | `deskSceneLayout(pointSize:)` + `DeskSceneView` |
| `app/…/Views/Sleep/SleepHero.swift` (new) | `heroCount`, `heroQualifier`, `bracketTail`, `heroTiles`, the meter, the one Consolidate control |
| `app/…/Views/Sleep/SleepStages.swift` (new) | `SleepStage`, `SleepStages.all`, `StageIconSprites`, `stageStripState`, `stagePulse` |
| `app/…/Views/Sleep/SleepStageStrip.swift` (new) | the strip view |
| `app/…/Views/Sleep/HowSleepWorks.swift` | reads `SleepStages.all` (copy unchanged) |
| `app/…/Views/Sleep/StudyListCard.swift` | "In the queue": micro-fill, ✓, schedule row, footer; the footer button leaves |
| `app/…/Views/Sleep/MemorySourcesCard.swift` (new) | `memorySourceRows`, `sparklinePoints`, `weekDots` + the panel |
| `app/…/Views/Sleep/ConsolidationHistoryCard.swift` | date + time, `N episodes`, the engine·author pill |
| `app/…/Views/Sleep/SleepView.swift` | `sleepLayout(width:)`, the two-column composition, liveness |
| `app/…/Views/Sleep/SleepMood.swift` | `sleepDebtBracketText` re-composed from Task 4's functions |
| `app/…/ViewModels/SleepViewModel.swift` | `enginePreview` + an injectable `fetchEngine` |
| `app/…/Views/Common/SettingsSectionLink.swift` (new) | the `SettingsLink` + section-seed pair, extracted once |
| `app/…/Views/Common/EmptyStateView.swift` | adopts `SettingsSectionLink` |
| `app/…/Theme/Copy.swift` | `sleepSubtitle` rewrite + the new Sleep strings |
| Tests (Swift) | `PixelRendererTests`, `DeskPaletteTests`, `DeskSceneSpritesTests`, `DeskSceneLayoutTests`, `SleepHeroTests`, `SleepStageStripTests`, `SleepQueueCardV3Tests`, `MemorySourcesTests`, `SleepLayoutTests`, `SleepNumbersLintTests`; edits to `BookwormSpriteTests`, `FixWaveTests`, `SleepHistoryPresentationTests`, `SleepHistoryDecodeTests`. **`SourcesPageTests` is deliberately NOT touched** — Track S may be editing it, and the one `SourceOverview` decode case this track owes rides in `SleepHistoryDecodeTests` (that file's own docstring already calls itself "decode tolerance for the models the Sleep page reads"). |
| Docs | `docs/goals/memory-evolution.md` (G125 v3 paragraph), `CLAUDE.md` (the Sleep page paragraph) |

---

### Task 1: Backend and wire truth — `activity`, `--date=iso-strict`, `progress: String?`

**Files:**
- Modify: `api/services/source_overview.py:24` (the `from datetime import …` line), `:105-124` (`_new_state`), `:126-216` (`build_overview`)
- Modify: `api/models/schemas.py:296-325` (`SourceOverview`; `Field` is already imported at `:4`)
- Modify: `api/services/git_service.py:986`, `:1018`, `:1031`, `:1046`
- Modify: `app/CicadaApp/Sources/CicadaApp/Models/SourceOverview.swift:15-41` (fields + memberwise init), `:89-92` (`CodingKeys`), `:95-113` (`init(from:)`)
- Modify: `app/CicadaApp/Sources/CicadaApp/Sync/SyncAPI.swift:132-192`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/ConsolidationHistoryCard.swift:42-58` (the `dateText` doc comment + function)
- Test: `api/tests/test_source_overview.py` (new cases), `api/tests/test_sleep_history_detail.py` (new case), `app/CicadaApp/Tests/CicadaAppTests/SleepHistoryDecodeTests.swift` (new cases), `app/CicadaApp/Tests/CicadaAppTests/SleepHistoryPresentationTests.swift` (new cases)

**Interfaces:**
- Produces: `SourceOverview.activity: dict[str, int]` (wire `activity`, `{}` default) — ISO **UTC** day → captures that day, sparse, last 30 days; `source_overview.build_overview(memory_path, *, channels, today: date | None = None)`; Swift `SourceOverview.activity: [String: Int]`; `SleepEventPayload.progress: String?`; `SleepHistoryPresentation.dateText(_:timeZone:)` / `.timeText(_:timeZone:)`.
- Consumes: `bank_index.files(…, "episodes")` frontmatter (already walked), the unchanged ETag recipe at `api/routers/sources.py:605-609`, `VersionVector.mapping["episodes"]` (unchanged).

- [ ] **Step 1: Failing tests**

```python
# api/tests/test_source_overview.py  — append (the `bank`/`client` fixtures and
# `_episode(memory, id, *, timestamp=…, origin=…)` already live in this file)
def test_activity_buckets_captures_by_day_inside_the_window(bank):
    """R-A16 — one sparse ISO-day histogram per source, computed in the loop
    `build_overview` already runs. Absolute date keys, never a rolling array:
    a 304'd payload must render a day SHORT, never a day SHIFTED.

    `today=2026-08-10` puts the fixture's window start at 2026-07-12, so the
    two Aug 4 Safari bookmarks land in one bucket and the Jul 1 episode is
    dropped — inclusion and the bound in one assertion.
    """
    from datetime import date
    rows = {r["id"]: r for r in source_overview.build_overview(
        bank, channels=[], today=date(2026, 8, 10))}
    assert rows["safari-bookmarks"]["activity"] == {"2026-08-04": 2}
    assert rows["harness:unknown"]["activity"] == {}      # the Jul 1 legacy mcp episode
    # A silent day has NO key — the series is sparse on the wire and densified
    # client-side, so a gap can never be read as a zero the backend asserted.
    assert "2026-08-05" not in rows["safari-bookmarks"]["activity"]


def test_activity_reads_a_naive_stamp_as_local_then_converts_to_utc():
    """The trap the design panel named: banks hold naive-local stamps
    (pre-G114) beside aware ones, so `raw[:10]` calls a local day a UTC day
    and is off by one, invisibly, for a subset of rows."""
    import os, time
    from api.services import source_overview as mod
    os.environ["TZ"] = "Pacific/Auckland"; time.tzset()          # UTC+12/+13
    try:
        assert mod._activity_day("2026-09-02T09:00:00") == "2026-09-01"
        assert mod._activity_day("2026-09-02T09:00:00+00:00") == "2026-09-02"
        assert mod._activity_day("2026-09-02T09:00:00Z") == "2026-09-02"
        assert mod._activity_day("") is None
        assert mod._activity_day("not-a-date") is None
    finally:
        os.environ.pop("TZ", None); time.tzset()


def test_overview_etag_recipe_is_unchanged_by_the_activity_field(client, bank):
    """ETag ship-together (R-A16): `activity` is computed from episodes, which
    the recipe already covers and `VersionVector.mapping` already routes to
    `.sourcesOverview` — so the recipe must NOT move, and no client mapping
    change is owed. Pinned behaviourally, not by grepping the source.

    (The connector tag is built from `ADAPTERS`, so read it off the response
    rather than retyping it: the point of this test is that adding `activity`
    changed nothing about the recipe's INPUTS, which the recomputation below
    proves by reproducing the same value from the same four arguments.)
    """
    from api.routers.sources import ADAPTERS
    from api.services import sync_service
    r = client.get("/sources/overview")
    assert r.status_code == 200
    assert "activity" in r.json()["sources"][0]
    tag = ",".join(f"{k}:{a.is_connected()}" for k, a in sorted(ADAPTERS.items()))
    expected = sync_service.etag_for(
        bank, "sources", "episodes", "entities",
        extra=f"overview|telegram:False|connectors:{tag}",
    )
    assert r.headers["etag"] == expected
    assert client.get("/sources/overview", headers={"If-None-Match": expected}).status_code == 304
```

```python
# api/tests/test_sleep_history_detail.py — append (this file's `bank` fixture
# builds a real git repo; its tests are sync and drive the coroutines with
# `asyncio.run`, so match that rather than introducing pytest-asyncio here)
def test_history_carries_a_time_of_day_and_still_joins_durations(bank):
    """R-A11 — `--date=iso-strict` gives the history rows a time of day.

    Both call sites that bound the telemetry read must slice to `[:10]`:
    unsliced, `date.fromisoformat("2026-09-01T…+02:00")` raises `ValueError`
    on py3.12 (verified in `api/.venv`) and BOTH endpoints 500 — the trap this
    test exists to catch, since a green history list would otherwise hide it
    until the ledger had a row to join.
    """
    import asyncio
    rows = asyncio.run(git_service.get_sleep_history(bank, limit=10))
    assert rows, "the fixture commits should match the Sleep-cycle grep"
    assert "T" in rows[0].date and len(rows[0].date) >= 19
    assert rows[0].duration_ms is None            # telemetry is off in the suite
    detail = asyncio.run(git_service.get_sleep_cycle_detail(bank, rows[1].commit_hash))
    assert detail is not None and "T" in detail.date
```

```swift
// app/CicadaApp/Tests/CicadaAppTests/SleepHistoryDecodeTests.swift — append
/// The backend sends `state.progress`, the stage SENTENCE (a String), but the
/// field was typed `Double?` and decoded with `try?`, so it has silently been
/// `nil` in the app since it shipped (sleep-data report §1).
func testSleepEventProgressDecodesTheStageSentence() throws {
    let json = #"{"status":"running","stage":1,"totalStages":5,"progress":"Stage 1/5: Extracting entities from 12 episodes…"}"#
    let p = try JSONDecoder().decode(SleepEventPayload.self, from: Data(json.utf8))
    XCTAssertEqual(p.progress, "Stage 1/5: Extracting entities from 12 episodes…")
}

/// An older backend that still sends a number must not fail the whole event.
func testSleepEventProgressToleratesANumericLegacyValue() throws {
    let json = #"{"status":"running","stage":1,"totalStages":5,"progress":42}"#
    let p = try JSONDecoder().decode(SleepEventPayload.self, from: Data(json.utf8))
    XCTAssertNil(p.progress)
    XCTAssertEqual(p.stage, 1)
}

/// A payload from before `activity` shipped must still decode (ship-together).
func testSourceOverviewDecodesWithoutActivity() throws {
    let json = #"{"id":"safari-tabs","label":"Safari iCloud tabs","kind":"browser","mark":"safari-tab","episodes":3}"#
    let row = try JSONDecoder().decode(SourceOverview.self, from: Data(json.utf8))
    XCTAssertEqual(row.activity, [:])
}
```

```swift
// app/CicadaApp/Tests/CicadaAppTests/SleepHistoryPresentationTests.swift — append
/// P4: git renders `--date=iso-strict` in the COMMIT's zone. The parser reads
/// the offset for real and displays in the reader's zone; the tests pin a zone
/// so they never depend on the runner's locale.
func testDateAndTimeReadAnIsoStrictStampInTheGivenZone() {
    let utc = TimeZone(identifier: "UTC")!
    XCTAssertEqual(SleepHistoryPresentation.dateText("2026-09-05T21:41:00+00:00", timeZone: utc), "Sep 5")
    XCTAssertEqual(SleepHistoryPresentation.timeText("2026-09-05T21:41:00+00:00", timeZone: utc), "9:41 PM")
    let plus2 = TimeZone(secondsFromGMT: 7200)!
    XCTAssertEqual(SleepHistoryPresentation.timeText("2026-09-05T21:41:00+00:00", timeZone: plus2), "11:41 PM")
}

/// A legacy `--date=short` value (a cached snapshot, or an older backend) has
/// no time — `—`, never a fabricated midnight (R-A14).
func testTimeTextIsADashForALegacyDateOnlyValue() {
    XCTAssertEqual(SleepHistoryPresentation.timeText("2026-09-01"), "—")
    XCTAssertEqual(SleepHistoryPresentation.timeText("not-a-date"), "—")
}
```

Run them — every one must fail for the right reason:
```
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/study-room && api/.venv/bin/python -m pytest api/tests/test_source_overview.py api/tests/test_sleep_history_detail.py -q -p no:cacheprovider
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/study-room/app/CicadaApp && swift test --filter SleepHistory 2>&1 | tail -20
```

- [ ] **Step 2: Implement**

`api/services/source_overview.py` — **replace** the existing `from datetime import datetime, timezone` at `:24` with the line below (do not add a second `from datetime` import), then add the constant and helper beside `KIND_ORDER`:

```python
from datetime import date as _date, datetime, timedelta, timezone

# R-A16: the Memory-sources sparkline's window. Bounded so the payload cannot
# grow with the age of the bank, and keyed by ABSOLUTE dates so a 304'd
# response renders a day short rather than a day shifted.
ACTIVITY_DAYS = 30


def _activity_day(raw: str) -> str | None:
    """The UTC calendar day an episode was captured, as ``YYYY-MM-DD``.

    Banks hold three timestamp shapes and they are deliberately never
    migrated: aware ``+00:00`` (G114 R2), legacy naive-LOCAL, and
    ``Z``-suffixed imports. ``raw[:10]`` would call a naive-local stamp a UTC
    day — off by one, invisibly, for exactly the rows nobody checks. A naive
    stamp means what the writer that produced it meant, LOCAL time, so
    ``astimezone()`` (no argument) attaches the system zone before the UTC
    conversion. Same rule, same reason, as
    ``sleep_debt._parse_episode_timestamp``'s M1 lesson (`sleep_debt.py:114`)
    — do not write a fourth parser.

    Measured in ``api/.venv`` (CPython 3.12.11): ``datetime.fromisoformat``
    accepts all three shapes, ``Z`` included (3.11+), so there is exactly one
    parse call here and no hand-rolled ``Z`` → ``+00:00`` rewrite.
    """
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt.astimezone(timezone.utc).date().isoformat()
```

In `_new_state`, add `"activity": {}` to the returned dict. In `build_overview`, take the window once before the episode loop and bucket inside it:

```python
def build_overview(memory_path: Path, *, channels: list[dict], today: _date | None = None) -> list[dict]:
    ...
    today = today or datetime.now(timezone.utc).date()
    window_start = (today - timedelta(days=ACTIVITY_DAYS - 1)).isoformat()
    window_end = today.isoformat()
    ...
    for f in bank_index.files(memory_path, "episodes"):
        ...
        ts = str(fm.get("timestamp") or "")
        # Computed in the loop that already reads this field for
        # `last_activity_at` — zero extra file reads, no body parse (R-A16).
        day = _activity_day(ts)
        if day is not None and window_start <= day <= window_end:
            state["activity"][day] = state["activity"].get(day, 0) + 1
```

No change is needed at the row-assembly site (`source_overview.py:206-216`): it already does
`rows.append({**state, …})`, so `activity` rides out with the rest of the state dict. No change is
needed in `api/routers/sources.py` either — `build_overview`'s new `today` argument defaults to
`None` and resolves to `datetime.now(timezone.utc).date()`, so the route's existing call is
untouched. **Known and accepted (P1):** `activity`'s window moves at UTC midnight while no ETag
component does, so a client holding a 304 keeps yesterday's window until the next real bank write —
a day short, never a day shifted, which is exactly why the keys are absolute dates.

`api/models/schemas.py`, on `SourceOverview`:

```python
    # R-A16 — captures per UTC calendar day for the last
    # ``source_overview.ACTIVITY_DAYS`` days, SPARSE (a silent day has no
    # key). Absolute date keys rather than a rolling array so a 304'd payload
    # renders a day short instead of a day shifted. Rides the existing
    # `episodes` ETag component; no `VersionVector` change is owed.
    activity: dict[str, int] = Field(default_factory=dict)
```

`api/services/git_service.py` — four edits, all in one commit (P3):
- `:986` `"--date=short"` → `"--date=iso-strict"`
- `:1018` `min(date.fromisoformat(e.date) for e in out)` → `min(date.fromisoformat(e.date[:10]) for e in out)`
- `:1031` `"--date=short"` → `"--date=iso-strict"`
- `:1046` `date.fromisoformat(detail.date)` → `date.fromisoformat(detail.date[:10])`

Add to `get_sleep_history`'s docstring: *"``--date=iso-strict`` (R-A11): the row needs a time of day. git renders it in the COMMIT's own zone, so the client parses the offset rather than assuming UTC; the telemetry-bound below slices to ``[:10]`` because ``date.fromisoformat`` rejects a datetime string."*

`Models/SourceOverview.swift`: add `let activity: [String: Int]`, a memberwise-init parameter `activity: [String: Int] = [:]`, the `CodingKeys` case, and `activity = try c.decodeIfPresent([String: Int].self, forKey: .activity) ?? [:]` with a one-line comment naming R-A16 and the ship-together rule.

`Sync/SyncAPI.swift`: change `var progress: Double?` → `var progress: String?`, the init parameter, and the decode line to `progress = try? c.decodeIfPresent(String.self, forKey: .progress)`, with a comment recording that the backend has always sent the stage sentence and the field was silently `nil`.

`ConsolidationHistoryCard.swift`: replace `dateText` with a shared parser plus two formatters:

```swift
    /// `date` arrives as git's `--date=iso-strict` (`2026-09-05T21:41:00+00:00`)
    /// since R-A11, and as the older `--date=short` (`yyyy-MM-dd`) from any
    /// snapshot cached before that. git renders BOTH in the COMMIT's own
    /// zone — the previous comment here claimed `--date=short` was "anchored
    /// UTC" and the formatter pinned UTC, which would shift the displayed
    /// hour the moment a time existed. The offset is parsed for real and the
    /// result displayed in the reader's zone; `timeZone` is injectable so the
    /// tests never depend on the runner's locale.
    static func parsed(_ iso: String) -> Date? {
        let withOffset = ISO8601DateFormatter()
        withOffset.formatOptions = [.withInternetDateTime]
        if let d = withOffset.date(from: iso) { return d }
        let dayOnly = DateFormatter()
        dayOnly.dateFormat = "yyyy-MM-dd"
        dayOnly.timeZone = TimeZone(identifier: "UTC")
        dayOnly.locale = Locale(identifier: "en_US_POSIX")
        return dayOnly.date(from: String(iso.prefix(10)))
    }

    static func dateText(_ iso: String, timeZone: TimeZone = .current) -> String {
        guard let date = parsed(iso) else { return iso }
        let f = DateFormatter()
        f.dateFormat = "MMM d"
        f.timeZone = iso.contains("T") ? timeZone : TimeZone(identifier: "UTC")
        f.locale = Locale(identifier: "en_US_POSIX")
        return f.string(from: date)
    }

    /// `—`, never a fabricated midnight, for a value that carries no time
    /// (R-A14): a legacy `--date=short` row genuinely does not know the hour.
    static func timeText(_ iso: String, timeZone: TimeZone = .current) -> String {
        guard iso.contains("T"), let date = parsed(iso) else { return "—" }
        let f = DateFormatter()
        f.dateFormat = "h:mm a"
        f.timeZone = timeZone
        f.locale = Locale(identifier: "en_US_POSIX")
        return f.string(from: date)
    }
```

- [ ] **Step 3: Verify + commit**

```
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/study-room && api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider 2>&1 | tail -5
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/study-room/app/CicadaApp && swift build 2>&1 | tail -5 && swift test 2>&1 | tail -20
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/study-room && git add api/services/source_overview.py api/models/schemas.py api/services/git_service.py api/tests/test_source_overview.py api/tests/test_sleep_history_detail.py app/CicadaApp/Sources/CicadaApp/Models/SourceOverview.swift app/CicadaApp/Sources/CicadaApp/Sync/SyncAPI.swift app/CicadaApp/Sources/CicadaApp/Views/Sleep/ConsolidationHistoryCard.swift app/CicadaApp/Tests/CicadaAppTests/SleepHistoryDecodeTests.swift app/CicadaApp/Tests/CicadaAppTests/SleepHistoryPresentationTests.swift && git commit
```

Commit message: `feat(G125 v3): per-source daily activity, a time of day on history rows, and the SSE progress sentence the app never decoded` — body naming R-A16/R-A11, P1/P3/P4, the unchanged ETag recipe, and the two verified traps (`date.fromisoformat` on an offset stamp; the UTC-pinned formatter).

---

### Task 2: `PixelRenderer` + `DeskPalette` + the `BookwormRenderer` facade

Pure infrastructure. **No visual change; all five existing `Bookworm*Tests` files pass unmodified.**

**Files:**
- Create: `app/CicadaApp/Sources/CicadaApp/MenuBar/PixelRenderer.swift`
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/DeskPalette.swift`
- Modify: `app/CicadaApp/Sources/CicadaApp/MenuBar/BookwormRenderer.swift` (whole file → forwarders)
- Test: `app/CicadaApp/Tests/CicadaAppTests/PixelRendererTests.swift` (new), `DeskPaletteTests.swift` (new)

**Interfaces:**
- Produces: `PixelRenderer.image(grid:gridSize:pointSize:palette:)`, `.snappedPointSize(_:gridSize:)`, `.cachedImage(key:grid:gridSize:pointSize:palette:)`, `.nsColors(_:)`; `DeskPalette.colors: [Character: UInt32]`, `DeskPalette.ns: [Character: NSColor]`.
- Consumes: nothing new. `BookwormRenderer.image/snappedPointSize/cacheKey/cachedImage` keep their exact signatures and behaviour.

- [ ] **Step 1: Failing tests** — `PixelRendererTests`:
  - `snappedPointSize(32, gridSize: 16) == 32`; `snappedPointSize(40, gridSize: 16) == 48`; `snappedPointSize(1, gridSize: 16) == 16` (floors at one whole cell, never 0); `snappedPointSize(120, gridSize: 24) == 120`; `snappedPointSize(132, gridSize: 24) == 144`.
  - `image(grid:gridSize:16,pointSize:32,palette:)` returns `NSSize(32,32)` and the sampled RGBA at a known cell matches the palette entry — copy the `cell(_:col:row:)` sampling helper verbatim from `BookwormRendererTests.swift:18-27` (it is `private func` on that class, so it must be copied, not called across files).
  - Row 0 of the grid draws at the TOP (AppKit's origin is bottom-left) — assert a one-cell grid whose only lit char is at row 0.
  - `cachedImage` returns the identical object for the same key and a different object for a different key, and the scene cache is independent: rendering 600 scene keys does not evict a `BookwormRenderer.cachedImage` result (P13).
  - `DeskPaletteTests`: the key set is exactly the documented one; every value is absent from `ThemeTokenTests`' nine banned hexes (assert directly, do not rely on the grep test); the keys are **disjoint** from `BookwormPalette.colors.keys`.

- [ ] **Step 2: Implement.** `PixelRenderer` carries the generalized versions of `BookwormRenderer.image`/`snappedPointSize` (`max(g, g * (pointSize / g).rounded())`, `g = gridSize`) plus its own `NSLock`-guarded `sceneCache` wiped past 512 entries. `BookwormRenderer` keeps `gridSize`, `snappedPointSize(_:)`, `image(grid:pointSize:)`, `cacheKey(state:frameIndex:pointSize:)` and `cachedImage(state:frameIndex:pointSize:)` as **thin forwarders** with `gridSize: 24` and the worm palette, and keeps its own cache so the worm's frames are never collateral damage of a scene render. `DeskPalette` uses the thirteen keys the pixel-art report verified against the banned list:

```swift
/// The desk scene's own palette — a SEPARATE type on purpose.
/// `BookwormSpriteTests.testPaletteIsExactlyTheNineRoles` fails on a tenth key
/// in `BookwormPalette`, so the scene cannot extend it. Three hues are
/// deliberately the same VALUES as the worm's `o`/`a`/`q` so the room and the
/// character read as one drawing. Checked against
/// `ThemeTokenTests.testNoStateHexOutsideTheTheme`'s banned list: no collision.
/// One NIGHT palette, mode-independent, for the same reason the worm palette
/// is (`BookwormSprites.swift:13-19`) and a stronger one here — this is the
/// Sleep page, and a night window is the metaphor, not a theme accident.
enum DeskPalette {
    static let transparent: Character = "."
    static let colors: [Character: UInt32] = [
        "d": 0x2B2140,  // deep outline / sill — the worm's `o` hue, on purpose
        "f": 0x4A3C6B,  // window frame + mullions, dusk plum
        "k": 0x1B1B38,  // night sky (glass)
        "m": 0xFFE18A,  // moonlight cream
        "n": 0xE0A93A,  // moon terminator — the worm's accent `a` hue
        "s": 0xFFCB57,  // star — the worm's sparkle `q` hue
        "c": 0x5B4B8A,  // cushion
        "p": 0x3A2F5C,  // cushion shadow
        "t": 0x8A5A3C,  // terracotta pot
        "g": 0x4FA85A,  // plant green
        "h": 0x7ED77F,  // plant highlight
        "i": 0x6E7B8F,  // mug steel / unlit lamp shade
        "u": 0xB8C4D4,  // mug highlight
    ]
    static let ns: [Character: NSColor] = PixelRenderer.nsColors(colors)
}
```

- [ ] **Step 3: Verify + commit.** `swift test 2>&1 | tail -20` — **all four `Bookworm*Tests` files (`BookwormRendererTests`, `BookwormSpriteTests`, `BookwormStateTests`, `BookwormViewTests`) must pass with no edits**; state that explicitly in the commit body. Commit `refactor(G125 v3): a grid-size- and palette-agnostic PixelRenderer under the Bookworm facade`.

---

### Task 3: The desk scene — five props, one lattice, the lamp that is the schedule, the nightcap

**Files:**
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/DeskSceneSprites.swift`, `DeskScene.swift`
- Modify: `app/CicadaApp/Sources/CicadaApp/MenuBar/BookwormSprites.swift` (`frames(for:)`, `.sleeping` + `.reading` only)
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepView.swift:249-320` (`deskCard` gains the scene and a fixed height)
- Test: `DeskSceneSpritesTests.swift` (new), `DeskSceneLayoutTests.swift` (new), `BookwormSpriteTests.swift` (nightcap cases)

**Interfaces:**
- Produces: `DeskProp` (`window|cushion|mug|plant|lamp`), `DeskSceneSprites.all: [DeskProp: PixelGrid]` + `lampLit`/`lampDark`, `deskSceneLayout(pointSize:) -> DeskSceneLayout`, `DeskSceneView(pointSize:lampLit:)`.
- Consumes: `PixelRenderer`, `DeskPalette`, `CicadaTheme.uiScale`, `BookPileView` (placed by the layout, **not** re-drawn).

- [ ] **Step 1: Failing tests**
  - `DeskSceneSpritesTests`, parameterized over every prop: each grid is exactly 24 rows × 24 chars; every character is in `DeskPalette.colors` or `.`; each prop's non-transparent bounding box sits inside its documented row band (`window` 2…22, `cushion` 19…23, `mug` 17…23, `plant` 10…23, `lamp` 4…23) — this catches a prop that drifts into the worm's cells on a later edit.
  - `DeskSceneLayoutTests`: `deskSceneLayout(pointSize: 120)` returns one entry per layer; z-order strictly ascending; **every offset is an exact integer multiple of `cell`**; no layer's box escapes the scene rect at `uiScale` 0.8 / 1.0 / 1.5; the worm's baseline cell equals the cushion's top cell; `pileFrame` does not intersect any prop's non-transparent bounding box (P10 — the real pile must not sit on top of painted furniture).
  - `BookwormSpriteTests` additions: cap cells present in **every** frame of `.sleeping(1)`, `.sleeping(5)` and `.reading`; **absent** from `.awake`, `.happy`, `.hungry`, `.curious(3)`, `.digesting`, `.error`; no cap cell ever occupies cols 19…23 on rows 0…2 (the z-drift corridor); row 5 cols 0…20 still identical across states; the palette is still exactly nine keys.

- [ ] **Step 2: Implement.** Author the five grids in the `PixelGrid` encoding `BookwormSprites` already uses (24 rows × 24 chars, `.` transparent; the typealias lives in `MenuBar/BookwormSprites.swift:7` and is module-internal, so the scene sprites use it directly). The window is the worked grid: rows 2–21 frame, mullions at cols 11–12 / rows 11–12, a **hand-drawn** seven-row crescent, `d` sill at row 22. Keep the reason in its docstring: *at seven cells a computed disc-minus-disc reads as a blob, so the shape is authored, not generated.* `lampLit` and `lampDark` differ only in the shade's fill (`m`/`s` vs `i`) — the cheapest possible state bit (P11).

`deskSceneLayout` is pure and returns integer cell offsets from the scene's bottom-leading origin, in a 40 × 24 cell box (200 × 120 pt at `uiScale == 1.0`):

```swift
/// The room, composed on ONE cell lattice (P12). Every prop is its own 24×24
/// grid rendered at the SAME snapped point size as the worm, positioned by an
/// integer CELL count — a prop that should look smaller is authored smaller
/// inside its grid, never rendered at a second point size, because two pixel
/// scales in one picture read as a bug at any zoom and would break G130 R6's
/// single `snappedPointSize` call. There is deliberately NO painted book
/// stack: the page's one volume encoding is `BookPileView`, and a decorative
/// spine stack at the same pixel scale would ask the reader to tell a chart
/// from wallpaper by taste (P10).
struct DeskLayer: Equatable { let prop: DeskProp; let cellX: Int; let cellY: Int; let z: Int }
struct DeskSceneLayout: Equatable {
    let cell: CGFloat            // pt per grid cell
    let size: CGSize             // the whole scene box
    let layers: [DeskLayer]      // back → front
    let wormOrigin: CGPoint      // bottom-leading, in points
    let pileFrame: CGRect        // where the REAL BookPileView goes
}
func deskSceneLayout(pointSize: CGFloat = 120, uiScale: Double = CicadaTheme.uiScale) -> DeskSceneLayout
```

`DeskSceneView` is a `ZStack(alignment: .bottomLeading)` of `Image(nsImage: PixelRenderer.cachedImage(key: "desk.<prop>|<variant>|<pt>", …))`, every one `.interpolation(.none)`, the whole stack `.allowsHitTesting(false)` and `.accessibilityHidden(true)` — the worm already carries the state label and `BookPileView` its own; six props read aloud would bury both. **No `TimelineView`** — the backdrop is static (R-A13: idle is still).

In `SleepView.deskCard`, wrap the existing content in a `ZStack(alignment: .bottomLeading)` with `DeskSceneView` at the back, place `BookwormView(state: mood, pointSize: 120, caption: nil)` and `BookPileView` at the layout's own coordinates, and pin **`.frame(height: heroHeight)`** on the hero so idle → running → idle never reflows (R-A2). The lamp takes `lampLit: sleepVM.schedule.mode != "manual"` (R-A3); its text twin arrives with the schedule row in Task 6 — until then the existing footer's `nextRunText` already returns `Copy.nextRunManual` (`"Manual only"`, `StudyListCard.swift:232-242`), so the branch stays honest at every commit.

The nightcap: inside `BookwormSprites.frames(for:)`, `merge` the cap into every frame of `.sleeping` and `.reading` using only `o`/`z`/`l`/`w` (P14), with a docstring recording why baking beats an accessory layer (mascot plan R2) and why the tassel is on the left. Three facts read off the current file so the cap lands safely:
  - Rows 0–1 are blank on every base frame and the head top is `headTop` at rows 2–4 (`BookwormSprites.swift:127-131`), so a cap occupying rows 0–4 replaces the head top and nothing else.
  - Neither `.sleeping` nor `.reading` applies a whole-sprite `shift`: `.sleeping` merges `sleepBase`/`sleepBreath` with a `z` glyph and `stageDots` (`:301-308`), and `.reading` uses `shiftRows(base, 6..<9, dx:)` (`:355-362`) — rows 6–9 only. So the cap can be merged last on each frame; it will not be dragged out of place.
  - `stageDots` writes row **23** only (`:267-274`), and the `z` glyphs sit at rows 0–2 / cols 19–23 (`glyph(zBig, top: 0, left: 19)`), which is why the tassel goes left (cols ≈ 2–5).

- [ ] **Step 3: Verify + commit.** `swift build` + `swift test`. Commit `feat(G125 v3): the study room — a night window, a cushion, a mug, a plant, and a lamp that is the schedule`.

---

### Task 4: The hero — count, qualifier chip, the meter that names its noun, three tiles, one Consolidate control

**Files:**
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepHero.swift`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepMood.swift:143-169`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepView.swift` (hero composition), `StudyListCard.swift:59-68,244-270` (the footer button leaves)
- Modify: `app/CicadaApp/Sources/CicadaApp/ViewModels/SleepViewModel.swift` (`enginePreview` + injectable `fetchEngine`)
- Modify: `app/CicadaApp/Sources/CicadaApp/Theme/Copy.swift`
- Test: `SleepHeroTests.swift` (new), `FixWaveTests.swift` (upgraded), `SleepViewModelTests.swift` (engine fetch)

**Interfaces:**
- Produces: `heroCount(_:debt:) -> Int?`, `heroQualifier(_:debt:) -> String`, `bracketTail(_:debt:) -> String`, `heroMeter(mood:debt:read:total:) -> HeroMeter?` (`.rested(pct:)` / `.reading(read:total:)`), `heroTiles(entityCount:sourceCount:lastDurationMs:) -> [HeroTile]`, `SleepViewModel.enginePreview: SleepEnginePreviews?`.
- Consumes: `resolveSleepDebt`/`resolveOriginCounts` (already resolved once per body eval), `store.banks`, `store.sourcesOverview`, `sleepVM.history`, `APIClient.fetchSleepEngine()`.

- [ ] **Step 1: Failing tests** — `SleepHeroTests`:
  - **The composition is byte-for-byte** — all twelve strings from `SleepMoodTests.swift:224-273`'s eleven `test_bracketText_*` cases (including `"[ 47 episodes behind ]"`/`"[ 1 episode behind ]"` with a nil debt, both `hungry` branches, and `"[ 0 to read ]"` with a nil debt) are re-asserted here, so the composition is pinned in its own file as well as in `SleepMoodTests`.
  - `heroCount`: `.reading` with `unprocessedCount: 12` → `12`; `.happy` → `nil`; `.sleeping(2)` → `nil`; `.hungry` with `0` → `nil`.
  - `heroQualifier`: `.happy` → `"caught up"`; `.hungry` with count > 0 → `"overdue"`; `.reading` with `hasRunBefore: true` → `"behind"`; `.reading` with `hasRunBefore: false` → `"first run"` (P9); `.error` → `"failed"`.
  - **R-A5's rule, as a test:** `heroMeter` returns `nil` when `restedPct == nil` and not running; whenever it returns non-`nil` its `label` is non-empty AND contains one of `Rested` / `Read`. A loop over a matrix of states asserts *"the bar never renders without its noun"*.
  - `heroMeter` while running returns `.reading(read: 138, total: 203)` from the origin-count sums, **not** from `progressPct`.
  - `heroTiles`: three tiles always; the duration tile is `"—"` with a non-empty `reason` when `lastDurationMs == nil` (R-A14/P18); no tile ever contains the substring `"cluster"`, `"insight"`, `"est"` or `"~"`.
  - `FixWaveTests` upgrade — **keep** `testSleepViewNoLongerDefinesItsOwnConsolidateButton` (it still guards `SleepView.swift`, which stays clean when the control moves to `SleepHero.swift`) and **add** the lint below beside it.

    **Amendment to R-A7, measured, and the reason it is required.** R-A7 asks for a *tree-wide* "exactly one file defines one". Grepped at `53885a1`, `sleepVM.triggerManually()` lives in **five** files: `Views/Sleep/StudyListCard.swift:247`, `Views/Common/TopBarControls.swift:39`, `Views/Sources/SourceQueueStrip.swift:83`, `Views/Onboarding/OnboardingSleepStep.swift:37` and `CicadaApp.swift:167`. The last four are *other surfaces'* triggers (the top bar, the Sources page's queue strip, onboarding, and the ⌘-key command) and three of them sit behind this plan's own ownership fences — Track P owns `TopBarControls.swift`, Track S owns `Views/Sources/*`. A tree-wide lint is therefore red on arrival and cannot be made green from inside this worktree. G125 R10 and R-A7 are about **the Sleep page**, so the lint is scoped to `Views/Sleep/` — which is exactly the failure the old lint missed (a control moved from `SleepView.swift` into a sibling Sleep file kept the grep green while defeating the rule).

```swift
/// R-A7 (upgrading G125 R10, scoped per the amendment above): "exactly ONE
/// Consolidate control on the Sleep page". The old lint grepped only
/// `SleepView.swift`, so moving the control into a sibling file under
/// `Views/Sleep/` kept it green while defeating the rule. This walks the
/// whole folder instead. It is deliberately NOT tree-wide: the top bar, the
/// Sources queue strip, onboarding and the ⌘-key command each own their own
/// trigger, and three of those files belong to other tracks.
func testExactlyOneSleepPageFileDefinesTheConsolidateControl() throws {
    // `ThemeTokenTests.swiftSources()` is a `static` internal helper over
    // `Sources/CicadaApp/**/*.swift`, resolved from `#filePath` — reuse it
    // rather than writing a fourth enumerator (FontLiteralLintTests and
    // SettingsEntryPointTests each already have their own private copy).
    let sleepFiles = try ThemeTokenTests.swiftSources()
        .filter { $0.path.contains("/Views/Sleep/") }
    XCTAssertFalse(sleepFiles.isEmpty, "found no Views/Sleep sources — the lint would pass vacuously")
    var defining: [String] = []
    for url in sleepFiles {
        // A `for … where` clause cannot throw, so the read is in the body.
        let text = try String(contentsOf: url, encoding: .utf8)
        if text.contains("sleepVM.triggerManually()") { defining.append(url.lastPathComponent) }
    }
    XCTAssertEqual(defining.sorted(), ["SleepHero.swift"],
                   "exactly one file under Views/Sleep may define the Consolidate control (R-A7)")
}
```

  - `SleepViewModelTests`: an injected `fetchEngine` populates `enginePreview`; a throwing one leaves it `nil` and does not set `errorMessage` (an absent preview is a missing subtitle, not a page error).

- [ ] **Step 2: Implement.** Add the four pure functions to `SleepHero.swift` and re-express `sleepDebtBracketText` in `SleepMood.swift` as their composition (P8), with a docstring stating that the nine asserted strings must survive. The hero view stacks, over the scene:

  1. `SpeechBubbleView(text: sleepBubbleText(mood, bubbleCtx))` — unchanged, still clock-free (R8).
  2. The numeral at `CicadaTheme.font(size: 44, weight: .semibold, design: .rounded)` with `Text("episodes waiting")` beneath, and the qualifier chip beside it in `sleepDebtBracketColor(mood)`.
  3. The **24-block segmented meter**: a fixed `HStack` of 24 rounded rects, `filled = Int((fraction * 24).rounded())`, with the label ALWAYS drawn above it. A code comment states R-A5 verbatim.
  4. Three tiles in a row (`heroTiles`), each `label` + `value`, each `—` carrying `.help(reason)`.
  5. The **one** Consolidate/Cancel control, with `enginePreview?.manual` as its subtitle (`Copy.runsOn(engine:)`, absent when nil) — the standing quota ruling shown at the moment of choice, never hidden.

  `StudyListCard`'s footer keeps `nextRunLine` and loses `consolidateButton`; `cancelButton` and `Copy.cancelSleepExplainer` move to the hero with it (Cancel must stay reachable while running — it is the only live control during a cycle). Add `Copy.episodesWaiting`, `Copy.runsOn(engine:)`, `Copy.entitiesInMemory(_:)`, `Copy.sourcesFeeding(_:)`, `Copy.lastCycle`, `Copy.noTimingRecorded` — all new; none of these six exists today (`Copy.consolidateNow`, `Copy.consolidating`, `Copy.cancelSleep`, `Copy.cancellingSleep`, `Copy.cancelSleepExplainer` and `Copy.nextRunManual` already do and are reused as-is).

  `SleepViewModel` gains `var enginePreview: SleepEnginePreviews?` and `private let fetchEngine: () async throws -> SleepEngineResponse` (defaulting to `APIClient.shared.fetchSleepEngine()`), loaded from `load()` as a fifth `async let` under the same `loadToken` guard, failing silently to `nil`.

- [ ] **Step 3: Verify + commit.** Both suites. Commit `feat(G125 v3): the hero readout — a promoted count, a meter that names its noun, three measured tiles, one Consolidate control`.

---

### Task 5: The stage strip — one array, five pixel icons, a strip that freezes where it stopped

**Files:**
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepStages.swift`, `SleepStageStrip.swift`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/HowSleepWorks.swift:17-36,45-62`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepView.swift:328-359` (`moodDetailLine` loses "Stage N of 5" + `ProgressView`)
- Test: `SleepStageStripTests.swift` (new)

**Interfaces:**
- Produces: `SleepStage { id, number, shortLabel, detail, symbol }`, `SleepStages.all: [SleepStage]`, `StageIconSprites.grid(for:) -> PixelGrid` (16×16), `StagePip`, `stageStripState(stage:isRunning:cancelled:error:read:total:) -> [StagePip]`, `stagePulse(at:reduceMotion:) -> Double`.
- Consumes: `PixelRenderer` at `gridSize: 16`, rendered at 32 pt; `DeskPalette`; `BookwormRenderer.cachedImage(state: .happy, frameIndex: 1, pointSize: BookwormRenderer.snappedPointSize(48 * CicadaTheme.uiScale))` for the caught-up worm at the strip's right end (existing frames, no new art, and the renderer is called directly rather than through `BookwormView` precisely to avoid a second `TimelineView` — which is why the snapping `BookwormView.swift:48` normally does has to be done here by hand, G130 R6).

- [ ] **Step 1: Failing tests**
  - `SleepStages.all` has exactly five entries whose `number`s are 1…5 and whose `shortLabel`s are `["Read","Sort","Decide","Notice","File"]`.
  - **The popover cannot drift:** `HowSleepWorksContent.rows` is a `private static let` (`HowSleepWorks.swift:17-36`) and a test cannot read it, so the pin is written against `SleepStages.all` with the five titles and five `detail` strings **typed as literals in the test**, character-for-character from `HowSleepWorks.swift:21-35` — `"Stage 1 · Read"` / `"Each episode is read once for people, projects, tools and ideas."` through `"Stage 5 · File"` / `"Everything is written to the graph and committed with its provenance."`, plus their SF Symbols `book` / `arrow.triangle.merge` / `questionmark.circle` / `sparkles` / `checkmark.seal`. That is what makes the refactor unable to silently reword the one prose source (P16).
  - `stageStripState`: running with `stage: 0` → `[.active(fill: 138/203), .pending, .pending, .pending, .pending]`; running with `stage: 2` → `[.done, .done, .active(fill: nil), .pending, .pending]` (**only Read carries a fill** — P15); idle with `stage: 5, error: false` → five `.done`; idle with `stage: 0` → five `.pending`; cancelled at `stage: 2` → `[.done, .done, .skipped, .skipped, .skipped]`; error at `stage: 1` → `[.done, .failed, .skipped, .skipped, .skipped]`. Every case asserts the array is exactly five long.
  - `stagePulse(at:reduceMotion: true)` is constant across four sampled dates (R-A13: Reduce Motion holds the terminal frame). The period is a named constant, `SleepStages.pulsePeriod`, so it is assertable rather than inferred: `XCTAssertLessThanOrEqual(SleepStages.pulsePeriod, 1.2)` and, for four sampled dates `t`, `stagePulse(at: t, reduceMotion: false) == stagePulse(at: t + SleepStages.pulsePeriod, reduceMotion: false)` (accuracy 1e-9).
  - `StageIconTests` (inside the same file): five 16×16 grids, every character in `DeskPalette` or `.`, each icon using ≤ 3 distinct non-transparent characters (a 16×16 icon with four hues turns to mud).

- [ ] **Step 2: Implement.** Hoist the popover's five stage rows into `SleepStages.all` (keeping `capture` as the popover's own leading row — it is not a stage) and have `HowSleepWorksContent` render `SleepStages.all` for rows 2–6 with its existing SF Symbols and **its existing strings unchanged**. Author the five 16×16 icons. `SleepStageStrip` draws pip · icon · label per stage with an arrow between, the Read pip filling to `read/total`, the active pip breathing through `stagePulse` routed via `@Environment(\.accessibilityReduceMotion)`, and the `.happy` worm at a snapped `48 * uiScale` on the right end when `heroCount == nil && mood == .happy`. `moodDetailLine` keeps only the idle "Rested … volume … age …" explainer line (the meter itself now lives in the hero). Concretely, in `SleepView.swift:328-357`: the whole `if case .sleeping(let stage) = mood { … }` branch is deleted — its `Text("Stage \(stage) of 5")`, its `ProgressView(value: sleepVM.progressFraction)` and its `Text("Stage 1: \(progress)%")` all go (R-A8) — and the guard becomes `if case .sleeping = mood { EmptyView() } else if let debt { … }` so the Rested line does **not** appear mid-cycle (it is the idle explainer, and the running readout is the strip + the hero meter). The now-unused `progress:` parameter is dropped from the signature and from its call site at `SleepView.swift:292`; `resolveProgressPct` keeps its other reader.

- [ ] **Step 3: Verify + commit.** Commit `feat(G125 v3): the stage strip is the live instrument — one SleepStages array behind both the strip and the popover`.

---

### Task 6: "In the queue" — micro-fill, ✓, the schedule sentence, the footer that names the scheduled engine

**Files:**
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/StudyListCard.swift`
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Common/SettingsSectionLink.swift`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Common/EmptyStateView.swift:39-51` (adopts it)
- Modify: `app/CicadaApp/Sources/CicadaApp/Theme/Copy.swift`
- Test: `SleepQueueCardV3Tests.swift` (new); `StudyListCardTests.swift` keeps its existing cases

**Interfaces:**
- Produces: `scheduleSentence(_ schedule: ScheduleConfig) -> String`, `scheduledEngineLine(preview:) -> String?`, `queueRowState(_ row: StudyRow) -> QueueRowState` (`.waiting(Int)` / `.reading(read:total:fill:)` / `.done` / `.nextCycle`), `SettingsSectionLink(section:label:)`.
- Consumes: `sleepVM.schedule`, `sleepVM.enginePreview` (Task 4), `store.status.value?.nextSleepAt`.

- [ ] **Step 1: Failing tests**
  - `scheduleSentence`: manual → `Copy.nextRunManual` (`"Manual only"`); daily 2:00 → `"Every day at 02:00"`; interval 6 → `"Every 6 h"`; interval 1 → `"Every hour"`; `after_import` → `"After imports settle"`. All four modes, none of them inventing a time.
  - `queueRowState`: idle (`row.read == nil || row.total == nil`) → `.waiting(188)`; running `read 12 / total 188` → `.reading(fill: 12/188)`; `read == total` → `.done` (the dimmed ✓); `total == 0` → `.nextCycle` (left out by the episode cap — `StudyListCard.swift:181-186`'s existing rule, preserved). **Precedence is asserted, not implied:** `total == 0` is tested BEFORE `read == total`, or `0 of 0` would render the ✓ instead of "next cycle"; a case with `read: 0, total: 0` pins it.
  - `scheduledEngineLine` returns `nil` when `preview.manual.engine == preview.scheduled.engine`, and a non-nil sentence naming the scheduled engine when they differ (R-A9) — **the asymmetry is shown, never silently applied**; `nil` preview → `nil` line, never a guess.
  - A source-text lint asserting `StudyListCard.swift` no longer contains `Copy.consolidateNow` or `sleepVM.triggerManually()` (the control left in Task 4).
  - A second source-text lint for P5, stated as **one writer**, not one mention: exactly one file under `Sources/CicadaApp` contains the write form `forKey: "cicada.settingsSection"`, and it is `SettingsSectionLink.swift`; `EmptyStateView.swift` no longer contains that literal at all. It must NOT assert "one file mentions the string" — `Views/Settings/SettingsScene.swift:19` holds the `@AppStorage("cicada.settingsSection")` READER and `Views/Settings/SettingsSection.swift:12` mentions it in a doc comment, and both stay.

- [ ] **Step 2: Implement.** Header `"IN THE QUEUE"`. Rows gain a 3 pt micro-fill drawn *behind* the count while running (replacing the 60 pt `ProgressView` — no spinner where a real count exists) and dim to tertiary with a `checkmark` at `read == total`. Below the rows, a schedule row: a `moon.zzz` mark, `scheduleSentence(...)` and a `SettingsSectionLink(section: .sleep, label: Copy.changeEllipsis)` — this is the lamp's mandatory text twin (P11/R-A3). `SettingsSection.sleep` exists (`Views/Settings/SettingsSection.swift:19`); **`Copy.changeEllipsis` does not** — add it (`static let changeEllipsis = "Change…"`) next to the existing `Copy.changeInSettingsSleep` (`Copy.swift:53`), which stays for its own callers. The footer keeps `nextRunText` and adds `scheduledEngineLine` **only when the two previews differ**. `SettingsSectionLink` is the `SettingsLink` + `.simultaneousGesture` pair lifted verbatim out of `EmptyStateView` with its full docstring (P5), and `EmptyStateView` then calls it.

- [ ] **Step 3: Verify + commit.** Commit `feat(G125 v3): "In the queue" — a live micro-fill, a schedule sentence, and the scheduled engine named only when it differs`.

---

### Task 7: The right column — Memory sources and Recent consolidations, and the two-column layout

**Files:**
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/MemorySourcesCard.swift`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/ConsolidationHistoryCard.swift:123-162`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepView.swift:57-104`
- Test: `MemorySourcesTests.swift` (new), `SleepLayoutTests.swift` (new)

**Interfaces:**
- Produces: `MemorySourceRow`, `memorySourceRows(overview:today:limit:sparkDays:) -> [MemorySourceRow]`, `sparklinePoints(activity:days:today:) -> [Int]`, `weekDots(activity:weeks:today:) -> [Int]`, `sparklinePath(_ points: [Int], in: CGSize) -> Path`, `SleepLayout { isTwoColumn: Bool, maxContentWidth: CGFloat, leftFraction: Double }`, `sleepLayout(width:) -> SleepLayout`.
- Consumes: `store.sourcesOverview.value` (**a projection — no new fetch**, R-A10), `SourceOverview.activity` (Task 1), `OriginMark` (Track L's, called not edited), `sleepVM.history`.

- [ ] **Step 1: Failing tests**
  - `sparklinePoints` returns a **dense** array of length `days`, oldest first, zero-filled for silent days, indexed by UTC day (P2 — the calendar is pinned to UTC because the keys are); a key outside the window is ignored; an empty `activity` gives all zeros, never an empty array a view has to special-case.
  - `weekDots(activity:weeks: 4, today:)` sums each of the last four 7-day blocks, oldest first.
  - `memorySourceRows`: drops rows with `episodes == 0`; sorts by 14-day captures descending, then `episodes`, then `id` (stable); caps at 6; **the noun is `captured`, never `waiting`** — assert the row's count line ends in `captured` (P17/R-A10).
  - `sleepLayout(width: 1200)` is two columns; `sleepLayout(width: 999)` is stacked; `sleepLayout(width: 1000)` is two columns (the boundary is named, not guessed).
  - **`maxContentWidth` is part of the layout, not a leftover literal.** `SleepView.body` pins `.frame(maxWidth: 760)` today (`SleepView.swift:81`), which no two-column arrangement can fit inside; `sleepLayout` therefore returns the cap — `760` when stacked (unchanged behaviour below 1000 pt) and a wider two-column cap above it — and the view reads `layout.maxContentWidth` instead of the literal. Asserted: `sleepLayout(width: 999).maxContentWidth == 760` and `sleepLayout(width: 1200).maxContentWidth > 1000`.
  - `SleepHistoryPresentation` row assembly: a non-decay entry renders `"\(episodes) episodes → +\(created) new · \(updated) updated"`; a decay entry still renders `"decay pass"` and claims no extraction credit (the existing G85 precedent).

- [ ] **Step 2: Implement.** `MemorySourcesCard` renders `OriginMark` · label · a sparkline (`Path`, 1 pt stroke, no axes, no numbers) · `N captured` · four week-dots, plus an "All sources →" row that sets `selectedTab = .sources`. `ConsolidationHistoryCard`'s row becomes: date · time · summary · the **engine · author pill** in the reference's badge slot (`entry.engine.map(Copy.engineLabel)` — `Copy.engineLabel(_ id: String)` at `Copy.swift:71` takes a NON-optional while `SleepHistoryEntry.engine` is `String?` (`APIClient.swift:845`), and a decay or state-snapshot commit legitimately has none, so an absent engine drops the pill's left half rather than inventing one — plus `SleepHistoryPresentation.authorLabel`, both already parsed) · duration or `—` · chevron; the existing expand-on-click detail is untouched. `SleepView.body` wraps its content in a `GeometryReader`, asks `sleepLayout(width:)`, applies `layout.maxContentWidth` in place of the literal `760`, and either lays the two columns side by side (left = `layout.leftFraction` ≈ 2/3) or stacks the right column under the left.

- [ ] **Step 3: Verify + commit.** Commit `feat(G125 v3): the right column — memory sources with a real sparkline, consolidations with an engine·author pill`.

---

### Task 8: Liveness, the motion budget, the subtitle, and the `%`-noun lint

**Files:**
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepView.swift`
- Modify: `app/CicadaApp/Sources/CicadaApp/Theme/Copy.swift:128` (`sleepSubtitle`) + a new `Copy.asOf(_:)`
- Test: `SleepNumbersLintTests.swift` (new); `SleepLayoutTests.swift` (liveness cases); `CopyConstantsTests` runs unchanged

**Interfaces:**
- Produces: `sleepLiveness(isConnected:loadedAt:isError:now:) -> Liveness` (`.live` / `.stale(asOf: Date)`), `Copy.asOf(_:)` (new). `now` is injected rather than read from the clock so the function stays pure and testable (the R8 rule the bubble already follows); it is what a later staleness threshold would use, and with today's rules the result does not depend on it — say so in the docstring rather than leaving a reader wondering.
- Consumes: `store.isConnected`, `store.status.loadedAt` / `store.sourcesOverview.loadedAt`.

- [ ] **Step 1: Failing tests**
  - `sleepLiveness`: connected → `.live`; disconnected with a `loadedAt` → `.stale(asOf:)`; disconnected **with an error present** → `.live` (R-A12: the error state is exempt — news stays at full contrast); disconnected with no `loadedAt` → `.live` (nothing to date; never a fabricated timestamp).
  - `SleepNumbersLintTests` (P19), modelled on `FontLiteralLintTests`:

```swift
/// R-A15, narrowed to what a regex can actually hold: the broad "the set of
/// numeric interpolations equals the budget table" form is refused — numbers
/// arrive through `Copy.` helpers and `durationText(ms:)` and would falsify
/// it on the first refactor. This asserts the one thing the reference image
/// got wrong: a percentage on this page always names what it is a percentage
/// OF. The budget table in the plan is the reviewable artefact; this is its
/// guard.
func testNoBarePercentReachesATextInTheSleepFolder() throws {
    let nouns = ["Rested", "Read", "volume", "age", "Stage"]
    // `sleepSources()` is this file's own small helper: reuse
    // `ThemeTokenTests.swiftSources()` (a `static`, internal enumerator over
    // `Sources/CicadaApp/**/*.swift`, resolved from `#filePath`) and keep the
    // `/Views/Sleep/` entries. Assert it is non-empty, or the lint passes
    // vacuously — the same guard `FontLiteralLintTests.sourceFiles()` carries.
    for file in try Self.sleepSources() {
        let text = try String(contentsOf: file, encoding: .utf8)
        for (i, line) in text.components(separatedBy: .newlines).enumerated() {
            let code = line.trimmingCharacters(in: .whitespaces)
            guard !code.hasPrefix("//"), !code.hasPrefix("///") else { continue }
            guard code.contains("Text("), code.contains("%") else { continue }
            XCTAssertTrue(nouns.contains { code.contains($0) },
                          "\(file.lastPathComponent):\(i + 1) renders a % with no noun (R-A5/R-A15)")
        }
    }
}
```

  - `CopyConstantsTests.testSubtitlesAreShortAndDoNotRepeatTheirTitle` must still pass with the new subtitle (35 chars, no "Sleep", no "page").

- [ ] **Step 2: Implement.** `Copy.sleepSubtitle = "Fold what's waiting into the graph."` — the queue's oldest item is months old on a real bank, so "today's episodes" was the one false string on the page. Apply the liveness treatment: one `.saturation(0.85)` step over the page's cards plus an `as of HH:MM` chip when `.stale`, with the error banner explicitly outside the desaturated group. Write the motion budget into `SleepView` as a code comment block (R-A13): *idle is still — only the worm's frame loop moves; nothing animates longer than 400 ms except the ≤ 1.2 s stage pulse; Reduce Motion holds every animation at its terminal frame through the existing `frameIndex(…reduceMotion:)` path; no spinner where a real count exists.* Audit the page for a violation of each and fix it in this commit.

- [ ] **Step 3: Verify + commit.** Commit `feat(G125 v3): liveness, the motion budget, an honest subtitle, and a lint that keeps every percent's noun`.

---

### Task 9: Docs

**Files:**
- Modify: `docs/goals/memory-evolution.md` (the **G125** row)
- Modify: `CLAUDE.md` (the "Sleep page — the study desk (G125)" paragraph)
- **`docs/goals/TODO.md` gets nothing** — the orchestrator updates the handoff.

- [ ] **Step 1.** Append a `**v3 (2026-09-05 evening)**` paragraph to the G125 row: what shipped (the room, the hero, the strip, the queue card, the right column), the **amendment to R1** stated out loud — *one volume encoding per surface: the book pile encodes queued text, a sparkline encodes captures per day, and no number is drawn twice* — and the rulings that are now binding (R-A1…R-A16 plus this plan's P1–P20 in one line each where they add something the spec does not), **including the two places the plan amended a spec ruling for a measured reason**: R-A7's tree-wide Consolidate lint is scoped to `Views/Sleep/` (four other surfaces legitimately own their own trigger, three of them behind other tracks' fences), and R-A9's "Change…" link opens Settings through `SettingsLink` + the `cicada.settingsSection` seed rather than `AppRouter`, which has no section field and cannot open the Settings scene. Cite the two verified traps as evidence, since they cost measurement: `date.fromisoformat` rejecting an offset datetime, and the naive-local timestamp shape that makes `raw[:10]` an off-by-one UTC day. **Privacy rule:** no bank content, no origin counts from the live bank, no titles — placeholders only.

- [ ] **Step 2.** Rewrite CLAUDE.md's Sleep-page paragraph in **≤ 12 lines** to describe v3: the pixel room whose lamp is the schedule and whose art encodes state and never quantity; the hero count + qualifier chip + a meter that never renders without its noun; the five-stage strip read from one `SleepStages.all` shared with the `?` popover; "In the queue" with the schedule sentence and the scheduled-engine line shown only when it differs; the right column of memory sources (`captured`, never the queue's `waiting`) and consolidations with an engine·author pill; `—` as a value with a reason; and the standing refusals (no clusters, no insights, no estimate, no price).

- [ ] **Step 3: Verify + commit.** Re-read both edits against the privacy rule before staging. Commit `docs: the study room (G125 v3) — the rulings, the R1 amendment, and the two traps that cost measurement`.

---

## Not in scope

- A time-of-day sky (`skyPhase`, sun/dawn/dusk window variants) — a later slice, with its own rails (art only; state outranks the clock).
- **G127** mascot identity. The nightcap is the only character-specific art here and is deliberately sequenced last so a mascot flip costs one `merge()` call.
- The Sources page and every file under `Views/Sources/` (Track S) — this track touches `Models/SourceOverview.swift` only.
- `Views/Common/TopBarControls.swift`, the `?` button's placement, and `ContentView`'s toolbar (Track P).
- `OriginIconography`, `LogoImage`, `OriginMark` and the real-marks work (Track L) — called, never edited.
- The in-app video renderer (Track V).
- The `?` popover's **copy**: it is refactored to read `SleepStages.all` and its strings are pinned by test; not one word changes.
- A `hub_count` on `/healthz`, a "clusters" or "insights" number, any per-cycle confidence score, any time estimate, any price or token readout.
- The `d3`/graph subsystem, `graph.js`, and every Python service outside `source_overview.py` / `git_service.py`.
- Backfilling `activity` for anything older than 30 days, or persisting it anywhere — it is derived on every request from frontmatter the index already holds.

---

## Verification the orchestrator runs at the end

1. **Both suites, from this worktree.**
   ```
   cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/study-room && api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider 2>&1 | tail -5
   cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/study-room/app/CicadaApp && swift build 2>&1 | tail -5 && swift test 2>&1 | tail -20
   ```
   Both must report **0 failures**. If `test_agent_provenance.py::test_a_decay_only_change_lands_in_its_own_cicada_authored_commit` is the ONLY red, re-run it alone and report both results.
2. **`make dev`**, then the live page at **1200, 950 and 800 pt** of content width — two columns above 1000, stacked below, no horizontal scroll, no card reflow between idle and running.
3. **Zoom 1.0 and 1.4** (⌘0 / ⌘+ ×2): the scene stays on one lattice with crisp cells at both, and the hero height scales without clipping.
4. **Light and dark**: the night palette is mode-independent by design; the card chrome, text and dividers must all come from theme tokens and read correctly in both.
5. **A manual cycle: start it, then Cancel.** The strip must advance, then **freeze at the stage it reached** — never reset to all-pending — and the meter must read `Read a of b` throughout, never a bare `%`.
6. **Stop the backend.** The page desaturates one step and shows the `as of HH:MM` chip; an error banner, if any, stays at full contrast.
7. **Reduce Motion on** (System Settings → Accessibility → Display): the worm holds frame 0, the stage pulse holds its terminal frame, nothing else moves.
8. **Read the diff** for: a second Consolidate control, a bare `%`, a painted book anywhere, a number drawn twice, a `.system(size:)` literal, a banned hex, an owner name or machine path in the docs.
