# Direction D, part 3b — Home, the Sleep page's quick engine menu, and the Settings-panel fixes (Track DS-3b) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Three surfaces move to Direction D without losing anything they do today.

- **Home (⌘1, G108)** becomes the approved D-Home mock: the painted hero as a 120 pt band that fades into
  the window, the headline on the window under it (never on paint), the palette's own field in a 640 pt
  block, then Getting started (while it lasts), Today, Needs you and Last read as labelled blocks of 36 pt
  rows in one 760 pt column. Every number appears once and links to its page. There is no Consolidate on
  Home (G125 R10).
- **Sleep** keeps its study room exactly as it is and gains the owner's request of 2026-09-23 — *"in the
  mascot page there should be a quick and easy way to change which model to use for consolidation"*: a
  neutral button beside Consolidate that names what a cycle you start would run and opens a menu of the
  five engines with their real marks, the chosen engine's model, and **both** preview lines, so ruling 4
  stays visible. It reads and writes the same `GET/PUT /sleep/engine` through the same view model as
  Settings → Engines. Details moves to D's list grammar: section labels over rows, no cards, and
  "Rested 0%" as a sentence instead of 24 empty boxes.
- **The Settings panel** gets four owner-reported fixes: the add-folder sheet has real labels and plain
  words (a subfolder checklist instead of `archive/**`); the Integrations harness rows wear their real
  marks; every Manage / Connect surface is a sheet that cannot open off-screen; and every Settings row is
  findable from ⌘K and opens where it lives through the one `AppRouter.openSettings` door.

**Architecture:** Every decision is a pure function or value with a table test, and the views render it:
- `HomeBandLayout.imageOffsetY` and `HomeLayout.needsYouSlots` (Home);
- `EngineQuickMenuModel`, `EngineWrite`, `SleepEnginePreviewSource` and `EngineMark.source` (the menu);
- `LastCycleRow.rows`, `HeroMeter.sentence`, `readoutRows` and `EpisodeRowText` (Details);
- `AgentFolders` and `IntegrationHarnessRows.markOrigin` (Settings);
- `QuickIndex.settingsDocs` and `SettingsSearchLanding` (⌘K and the panel's field).

The track makes **no backend change**: no new endpoint, field, ETag component, Store domain or pref.

**Tech Stack:** SwiftUI + XCTest (`app/CicadaApp`, macOS 14 floor, built on the macOS 26 SDK). `ImageRenderer` is
used for the one layout-fit test.

**Binding sources:**

- `docs/design/DESIGN_RULES.md` — binding for every DR id. This track applies §3 (tokens), §4 (DR-15…DR-21),
  §5.2 (the room), §5.4 (DR-33), §6 (DR-40…DR-53), §7 (DR-54, DR-58, DR-59), §8 (DR-60…DR-70), the §9 rulings and
  §10's Home, Sleep and Settings paragraphs.
- The owner-approved mocks `D-Home.dc.html`, `D-Sleep.dc.html` and `D-Settings.dc.html` (canvas v7, the session
  scratchpad, not committed). Values are translated from their markup and `renderPage()`, never embedded. The mocks
  mark two things **"Proposed"**: Home's "Recently learned" rows and the save-link row inside the results. Neither
  is built here (see *Not in scope*).
- `docs/superpowers/specs/2026-09-23-round3-meadow-reach-provenance-design.md` — decisions 12 (Home is the front
  door), 16 (the mascot page), 17 (Settings v3) and 18 (the find palette), and Track Z's R-Z1…R-Z14, which stay
  binding for the room. The brief overrides the spec where it says so.
- CLAUDE.md rails: ruling 4 (a scheduled cycle never spends Claude or ChatGPT plan quota); G125 R10 (one
  Consolidate, on the Sleep page); the no-price ruling of 2026-09-03; the one-intake and one-bank-switcher rules;
  ETag ship-together (untouched); the privacy rule and portability.
- Backlog rows G108 (Home), G122 (the engine picker), G125 (the Sleep page), G126 (Integrations), G133 (watched
  folders), G136 (the find palette) and G139 (Settings v3), plus Track E's ruling 6 (`/sleep/engine` has no
  Store domain) and Track Z's R-A7 ("a guessed engine is worse than silence").

---

## What the code actually does today (verified against `feat/d-home-sleep-settings` @ `2517ca3`)

**Home.**
- `Views/Home/HomeView.swift:38-61` stacks a band, the field column and a `ScrollView` of cards in a `scaled(720)`
  column. `:77-100` — the band is a `ZStack` of `HomeSkyBand()` with the two-line headline **drawn over it**
  (`Copy.homeHeadline` "What would you like" + `Copy.homeHeadlineItalic` "to remember?", `displayFont(size: 34)`).
  `:110-117` — `FindPanelBody(… placement: .page …)` wrapped in `.glassCard(cornerRadius: CicadaTheme.radiusLarge)`.
  `:125-146` — the save-link row: an accent `link` glyph and a hand-drawn `"⏎"`.
- `Views/Meadow/HomeSkyBand.swift:6-25` — `HomeBandLayout` (band 168 pt, a headline frame, a cloud frame);
  `:30-44` — `HomeSkyBand` is a procedural `MeadowSky()` plus one `DriftingCloud`. The D-Home mock's band is the
  bundled painting `hero-day` / `hero-day-dark` (the mock's blobs have the manifest's sha256s
  `0606cf88…` / `8a94d12b…`), 120 px, `object-position: center 63%`, masked
  `linear-gradient(to bottom, #000 40%, transparent 100%)`, with the headline in its own row below.
- `Views/Home/HomeSections.swift:29-42` — `HomeCard`: a `SectionLabel` **inside** a padded `surface` card.
  `:46-67` — `HomeRowButton`. `:83-166` — Today (a captured line with up to three 16 pt marks, and the waiting line
  with a 24 pt worm and an accent "Sleep ›"). `:170-217` — Needs you draws its own row (kind glyph, question,
  harness mark), not the Inbox's. `:221-306` — Last read (a line, "Sleep ›", and hand-drawn capsule chips).
- `Views/Home/GettingStartedCard.swift:62-88` — the card is `surface` on a bare `RoundedRectangle(radiusLarge)`
  with a `Divider()` (`:80`); Hide (`:137-145`) and each row's × (`:176-189`) are hand-rolled; "Choose a file…"
  is `.buttonStyle(.bordered)` (`:242-243`, `:270-271`); two titles are 13 **semibold** (`:263`, `:367`).
- `Support/HomeLayout.swift:6-10` holds only `showsWaitingInToday`. `Support/HomeFigures.swift:29-32` — `HomeChip` is
  `id` + `name`; `:92-103` builds chips from graph nodes.
- DESIGN_RULES §10 (Home) says "Consolidate, as the page's one `PrimaryActionButton`" and a "560 pt field" — the
  first contradicts G125 R10 (a CLAUDE.md ruling), the second the approved mock (640).

**Sleep.**
- `Views/Sleep/SleepView.swift:584-636` — `roomCard`: `StudyRoom`, `RoomSentenceView`, `SleepControlRow`
  (`:619-621`), the whisper row, the strip. `:334-343` — `resolvePage` feeds `sleepVM.enginePreview` to
  `SleepPageModel.resolve`. `:271-276` — `.task` loads `sleepVM` only. `:510-530` — the header is
  `PageTitle(Copy.sleepPageTitle)` (pinned by `PageTitleTests.swift:15-17`).
- `Views/Sleep/SleepHero.swift:423-426` — `controlCaption(isRunning:manualEngine:)` prints "Runs on <engine>" beside
  Consolidate. `:436-501` — `SleepControlRow`. `:513-526` — `EngineMark` knows `claude-cli` and `ollama`; **`codex-cli`
  falls to the key glyph** (a DR-52 bug: the ChatGPT plan has a real mark).
- `Views/Sleep/LampPopover.swift:74` reads `sleepVM.enginePreview` directly.
- `ViewModels/SleepViewModel.swift:48-55, 263-265` — the page's own copy of `/sleep/engine`'s previews.
- `ViewModels/SleepEngineViewModel.swift:14-41` — `EngineChooser`'s model: a plain round trip on
  `APIClient.shared`, not injectable; `errorMessage` is set on a failure and **never cleared on a success**.
- `Views/Settings/EngineChooser.swift:107-113` (`select`), `:192-204` (model bindings), `:238-245` (`commit`) —
  the write rule lives inline. `:207-222` — the previews read "Next cycle you start" / "Nightly schedule", while
  `SettingsSleepView.swift:83-84` reads `Copy.whenYouStart` "When you start one" / `Copy.onTheSchedule`
  "On the schedule": **two wordings for one pair of facts**.
- `api/services/sleep_engine_prefs.py:97-157` — the five candidates, in the order Auto, Claude plan, ChatGPT plan,
  Ollama, API key; Auto's and the API key's `detail` are the plain sentences the menu needs
  ("Your Claude plan if it's signed in, else …", "Uses the model configured on the Plans & keys page.").
- `Views/Sleep/SleepDetails.swift:40-62` — Details is four `.glassCard()`s: `LastCycleSection` (`:75-210`, four
  banners on `danger` / `accent` / `warning` `opacity` fills — a DR-7 violation), `StudyListCard`
  (`StudyListCard.swift:169-188`), `SleepReadoutView` (`SleepHero.swift:246-402`: a 24-block meter under
  "Rested n%", three tiles with `String(n)` values, an "Engine" line), and `ConsolidationHistoryCard`
  (`ConsolidationHistoryCard.swift:181-208`). `EpisodeRow.swift:14-58` carries both a status dot and a mark (DR-48)
  and a raw `source` pill (DR-54).

**Settings.**
- `Views/Settings/LocalSourceRows.swift:181-250` — `AddFolderSheet`: three `TextField`s with placeholders and no
  labels ("Name", "Which project is this?", "Parts written by an agent" pre-filled with `archive/**`).
  `:293-352` — `FolderManagePanel` (the same glob field). `:80-86` and `:386-390` — the folder's Manage and Wispr
  Flow's panel open as `.popover(…, arrowEdge: .trailing)` **anchored to the whole row**, at the panel's right edge.
- `Views/Settings/IntegrationsView.swift:236-240` — a connector's Connect/Manage, the same trailing popover.
  `:340-368` — `IntegrationHarnessRow` draws an accent `bubble.left.and.bubble.right` in a tinted circle for every
  harness (Claude Code, Codex, "Other agents"). `:265-273`, `:383-391` — the no-logo fallbacks are tinted circles.
- `Models/IntegrationCategory.swift:73-84` — `IntegrationHarnessRows.rows`. `SourceOverview.harness` /
  `.mark` carry the harness id (`api/services/source_overview.py:132-147, 171-175`).
- `Search/QuickIndex.swift:197-206` — `settingsDocs()` is **one row per section**; no individual setting is
  findable from ⌘K. `Search/FindModels.swift:107` — `FindDestination.settings(SettingsSection)`.
  `Search/FindPaletteModel.swift:191-193` — ⏎ on a Settings row only sets a hint ("Click Open to see this in
  Settings."), a leftover of the `Settings{}` scene DS-1 removed; `Views/Find/FindRowView.swift:26-28, 36-49` and
  `Views/Find/FindPanelBody.swift:137-140, 196-200` draw the "Open" link and the hint; `ContentView.swift:364-365`
  ignores `.settings`.
- `Views/Settings/SettingsPanel.swift:44-53` builds the panel's index; `:210-223` — `openTopHit` and `land` are
  private to the view, so "typing lands on a row" has no test.
- `Views/Settings/SettingsIndex.swift:86-152` — `staticEntries` (every row, with keywords) and `pageEntries`.

**Baselines on this base:** Swift **1623 executed, 0 failures**.

---

## Global Constraints

**Where you work.**

- Work ONLY in `<worktree>` = `<repo>/.worktrees/ds3b`, on branch `feat/d-home-sleep-settings` (based on `dev` @
  `2517ca3`). `<repo>` is the repository root; the orchestrator's brief gives its absolute path, and every command
  below spells `<worktree>` out in full — substitute that absolute path. It is not written here because an
  author-machine path in a public repo is a portability defect (CLAUDE.md).
- Every shell command is `cd <worktree> && <cmd>` (or `cd <worktree>/app/CicadaApp && <cmd>`) with the ABSOLUTE
  path — zoxide hijacks a relative `cd`; ignore its stderr warning. Never write `grep --include=*.ext` (zsh globs
  it); use `rg`, or `grep -rn` with a path.

**What you never touch.**

- NEVER read `<repo>/memory` (any bank), `~/.cicada`, `~/Library/Safari` or `~/.claude/projects`. Fixtures are
  synthetic: `alpha-project`, `bob-example`, `example.com`, `research`, `archive`, `example-model`.
- **No backend change at all.** If a task finds it needs a field the server lacks, stop and say so.
- **The study room does not change.** Do not edit `StudyRoom.swift`, `DeskScene.swift`, `DeskSceneSprites.swift`,
  `DeskHotspots.swift`, `DeskPalette.swift`, `BookPile.swift`, `WindowWeather.swift`, `RoomSentence.swift`,
  `RoomModel.swift`, `RoomFeed.swift`, `WormAnswers.swift`, `SleepMood.swift`, `SleepStages.swift`,
  `SleepStageStrip.swift`, `SleepSkyBand.swift` or `SpinePopover.swift`. (`SpinePopover` renders `EpisodeRow`, so
  Task 3's row restyle reaches it by design — the D-Sleep mock's spine popover draws the same row.)
- Graph, Clusters, Feed, Sources, Inbox and Projects pages are other tracks'.

**How you verify.**

- Swift: `cd <worktree>/app/CicadaApp && swift build 2>&1 | tail -5` must succeed, and
  `swift test 2>&1 | tail -20` must report **0 failures** (≥ 1623 executed plus the new tests).
  `SleepViewModelTests` poll tests and the search-latency tests can flake under load — re-run them alone before
  calling one yours. SourceKit diagnostics naming OTHER worktrees are noise.
- Graph JS: `cd <worktree> && node --test app/CicadaApp/Tests/graph/*.test.js` (pass the glob). Untouched; stays green.
- NEVER run `make dev`, `make install-app` or `swift run`, and never launch or kill the Cicada app or the launchd
  backend. The owner's installed app is live; the orchestrator installs and live-checks at the end.

**Git.**

- Never `git add -A`. Stage named files only; use `git mv` for the one rename this plan names (Task 1).
- Never commit `memory/`, `logs/`, `.claude/settings.json`, `api/.venv` or `*-report.md`. No push, no new branches or
  worktrees, no subagents. Ignore Devin and PR comments.
- End every commit message with the attribution lines the session's system reminder names. Each commit's subject
  cites the DR ids it applies.

**Tokens, type and motion.**

- Colours only from `CicadaTheme`. Every size through `CicadaTheme.font(size:weight:)` or a named token
  (`bodyFont` 13, `detailBodyFont` 14, `rowFont` 13 medium, `metaFont` 12, `metaMediumFont` 12 medium,
  `headingFont` 17 semibold); every dimension through `CicadaTheme.scaled(_:)` (DR-70). `FontLiteralLintTests` fails
  a literal `.system(size:)`; `labelFont` is read only by `SectionLabel` (`SectionLabelLintTests`). Semibold is for
  DR-16's short list only.
- Every rounded rectangle through `CicadaTheme.shape(_:)` (DR-12); depth is `.ringed(in:)` / `.glassCard()`, never a
  shadow (`ElevationLintTests`). The accent's six uses are DR-5's: links use `accentText`.
- Every duration lives in `CicadaMotion` / `SleepMotion` (`MotionLiteralLintTests`,
  `SleepNumbersLintTests.testTheSleepFolderDeclaresNoLiteralAnimationDuration`). A keyboard action never animates
  (DR-60).
- Row heights come from `RowMetrics` (DR-34). This plan adds `RowMetrics.menuItem` (30) and `RowMetrics.keyValue`
  (32), both the mocks' values.

**Copy.**

- Plain, friendly, sentence case; no "!", no bare "%", no price, token count or "$" (DR-59, 2026-09-03).
- A named service wears its real mark through `OriginMark` / `LogoImage` (DR-52); a mark is never recoloured and
  never sits on a tinted tile.
- Ids, harness slugs and paths appear only in `.help`, an accessibility label or a copy action (DR-54). The one
  exception already allowlisted: a watched folder's path in `LocalSourceRows.swift` (`MonospaceLintTests`).
- New words live in `Theme/Copy+HomeSleep.swift` (Task 2 creates it), except Home's, which stay in
  `Theme/Copy+Welcome.swift` beside the strings they sit with; every new label joins that file's lint list.

**Docstrings** explain WHY, citing the DR id, this plan's ruling (R-HS*), or the G row. Match the density of the file
you touch. Line numbers above are from `2517ca3` and drift as tasks land: read the cited code before editing.

**Test snippets.** "Append to `XTests.swift`" means inside that file's existing test class, before its closing
brace. The package is Swift 5 language mode (`swift-tools-version: 5.10`). A test that builds a `Store`, an
`ImageRenderer` or a `SleepEngineViewModel` is `@MainActor`, as the snippets mark.

---

## Rulings (binding)

Decisions this plan takes where the brief, the mocks or the rules left a choice, each with its reason, so no task
re-opens them. **§9** marks a departure that gets a dated line in DESIGN_RULES §9 (Task 6).

**Home**

- **R-HS1 — No `cicada.design.focus` flag (DR-73).** R-DS1 and R-DI1's reasons hold unchanged. Comparison is the
  orchestrator's installed build against this branch on the demo bank.
- **R-HS2 — §9 — Home is the D-Home mock.** The band is the bundled `hero-day` painting (its `-dark` sibling at
  night, `MeadowArt.image`), 120 pt, the meadow line kept in view (`object-position: center 63%` →
  `HomeBandLayout.imageOffsetY`) and faded into `bgBase` from 40 % down. The headline is one line —
  "What would you like to remember?" — in `PageTitle` (the room pages keep it, DR-17) on the row **under** the band:
  text never sits on paint (DR-13, DR-50). The italic second line and the drifting cloud retire (the hero's clouds
  are painted — `WelcomeHero`'s reason). Under Increase Contrast the band steps back to
  `MeadowRules.increasedContrastCeiling`. The field is 640 pt, the mock's value; §10's "560 pt" loses to the approved
  mock.
- **R-HS3 — §9 — No Consolidate on Home.** G125 R10 (one Consolidate, on the Sleep page) is a CLAUDE.md ruling, and
  DESIGN_RULES §1 says a rule that contradicts one is what gets fixed. The waiting count stays a link to the Sleep
  page. §10's Home paragraph is corrected to what ships (Task 6).
- **R-HS4 — Needs you renders the Inbox's own STATE 0 row.** `InboxRow(style: .wide)` — kind glyph, question, entity,
  the source in a person's words with its mark, the age — so Home's three questions are the Inbox's rows by
  construction (P5, DR-38), with the same slot floors (R-DI26) computed from Home's column
  (`HomeLayout.needsYouSlots`). A row lands in STATE 1 through the existing `router.pendingInboxItem` hand-off.
- **R-HS5 — Getting started keeps its content and logic; only its material moves.** Track I's rulings (R-IB13…R-IB20)
  are untouched. The card becomes C's focus-card material (`bgFocus`, `radiusLarge`, a resting ring, 24/28 padding),
  its `Divider()` goes (DR-11), Hide is a `TextButton`, a row's × an `IconButton`, "Choose a file…" a compact
  `NeutralButton` (DR-40), and its two 13-semibold titles become medium (DR-16).
- **R-HS6 — Home's blocks are labelled `glassCard` groups of 36 pt rows.** `SectionLabel` above, one `bgFocus` block
  with a resting ring and a 4 pt inset (`glassCard()` is exactly that material), rows at `RowMetrics.oneLine`. Last
  read's chips become `Tag`s with the entity type's dot (DR-44) that open the graph. Links are one new component,
  `InlineLink` (`accentText`, 12 medium — DR-5 use 5), which the Sleep menu reuses.

**Sleep — the quick engine menu**

- **R-HS7 — One source of truth.** The menu reads and writes `SleepEngineViewModel` — the object `EngineChooser` uses —
  over the same `GET/PUT /sleep/engine`. No second pref, no Store domain (Track E's ruling 6). The write rule
  (`EngineWrite`: a tap on another selectable engine writes it with its first model; the same engine, or a plan that
  is not signed in, writes nothing) is extracted from `EngineChooser.select` so both surfaces share it, and both
  refresh `.connections` after a write (R-E24).
- **R-HS8 — The button names what a cycle you start would run.** Its label is `preview.manual` — the card's own name
  for that engine plus the model ("Claude plan · sonnet") — prefixed "Auto ·" while Auto is the choice. This is the
  fact the retired "Runs on …" caption stated (ruling 4 at the moment of choice). Until the preview is known there is
  no button: a guessed engine is worse than silence (R-A7).
- **R-HS9 — §9 — The idle caption retires into the button; the button stays while a cycle runs.** "Runs on …" beside
  Consolidate would say the button's words twice (DR-38). While running, Cancel's caption ("Stops at the next safe
  point — nothing is lost.") stays, and the button stays, because a change applies to the next cycle (G80).
- **R-HS10 — §9 — The menu is a `NeutralButton` + popover, and the model is a native menu `Picker`.** A popover
  carries marks, both previews and a model picker that a native `Menu` cannot. The mock's model text tabs are not
  used: model rosters are the plan's own `model/list` or `ollama list`, of any length (R-E17), and DR-45's text tabs
  are single-select filters that deselect on a second tap. The free-text model id stays in Settings → Engines.
- **R-HS11 — §9 — Both previews, always, with one wording app-wide.** "When you start a cycle" and
  "Scheduled cycles" — in the menu, in `EngineChooser` and in Settings → Sleep (three places, two wordings before).
  The ruling sentence (`Copy.scheduledNeverSpendsPlans`) shows when the two engines differ (EngineChooser's rule).
- **R-HS12 — The page's engine lines read one source.** `SleepEnginePreviewSource.current(chooser:page:)`: the
  chooser's response when it has one (the echo of the newest write, from this menu or from Settings), else the
  page's own load. The caption, the lamp's engine line and the answers follow a switch at once.
- **R-HS13 — `EngineMark` wears the ChatGPT plan's mark for `codex-cli`** (DR-52), through
  `EngineOption.previewMark`, the card's own mark.
- **R-HS14 — The Sleep page keeps its `PageTitle` header.** DR-17 names Sleep as a room page that keeps it,
  `PageTitleTests` pins it, and the brief keeps the room; the mock's 12 pt eyebrow is a list page's header (DR-25),
  which §5.2 does not give a room.

**Sleep — Details**

- **R-HS15 — §9 — Details in D's list grammar.** Each section is a `SectionLabel` over rows, no card (DR-37), 28 pt
  between sections (the mock). Last cycle's four banners become glyph rows with no fill: a failure and a warning wear
  the `warning` glyph, a cancel and a cap `textTertiary` (DR-7: `danger` is for destructive actions only). "Rested n%"
  becomes a sentence (§10, Sleep): "Fully rested — nothing is waiting." / "Rested n% — the backlog is overdue." /
  "Rested n% — based on how much is waiting, and for how long." / "Read a of b so far." — the breakdown stays on hover.
  The three tiles and the engine line become four key–value rows ("In memory", "Feeding it", "Last cycle took",
  "Last engine" with its mark), counts through `UsageFormat` (DR-21 — the tiles printed `String(n)`). `EpisodeRow`
  drops its status dot (DR-48: one glyph) and its raw source pill (DR-38, DR-54); an untitled episode reads
  "Untitled", its id on hover. The micro-fill behind a reading count is `textSecondary` on `bgBadge`, not the accent.

**Settings**

- **R-HS16 — §9 — Settings raises sheets, never popovers.** The panel is modal and inset only 40 pt, so a popover
  anchored to a row at its edge can open past the screen (owner-reported: Manage). A folder's Manage, Wispr Flow's
  panel and a connector's Connect/Manage become sheets in one frame, `SettingsSheet` (a title, a close × on
  `.cancelAction`, 440 pt). A lint holds `Views/Settings/` to no `.popover(`.
- **R-HS17 — "Written by an agent" is a subfolder checklist.** One checkbox per top-level subfolder — "Files in
  research (and its subfolders)" — plus "Choose a subfolder…" for one deeper down. The wire stays a glob
  (`<folder>/**`, which `FolderGlob` — the backend matcher's twin — matches for everything below); nobody types one.
  A saved rule that is not one folder survives verbatim as "Files matching <rule>", so a round trip never drops a
  rule. A subfolder named `archive` is pre-ticked only when the folder has one — exactly the old default glob's
  effect. The app reads the folder (G133: the backend never opens it); hidden folders are skipped.
- **R-HS18 — Harness rows wear their real marks.** A harness with a Track L mark (installed icon → bundled PNG) wears
  it bare at 28 pt (`OriginMark`, clipped to its own curvature as Track L requires of an opaque raster such as
  `claude-code`); "Other agents" has no vendor and wears a neutral `ellipsis.bubble` — never a "?", never a bubble in a
  tinted circle. The channel and export-only fallbacks drop their tinted circles too (DR-52).
- **R-HS19 — ⌘K indexes Settings' pages and every static row, from `SettingsIndex`.** One index, one ranker
  (`QuickMatch`), one set of keywords: ⌘K and the panel's field find a setting by the same words. The dynamic per-item
  rows (channels, harnesses, export-only tiles, connections, agents, recommended skills) stay in the panel: channels and
  harnesses are already the palette's Sources group under the same names (DR-38), and the others are not palette
  inputs. Cicada's own two skills are *static* rows (`skill:cicada`, `skill:cicada-librarian` in `staticEntries`), so
  they are in ⌘K like every other static row.
- **R-HS20 — §9 — ⏎ on a Settings row opens it** through `AppRouter.openSettings(_:row:)`, landing on the row.
  R-SU12's "explain, don't open" existed because a closure could not open the `Settings{}` scene; DS-1 removed the
  scene. The hint, the row's "Open" link and its special accessibility container go.
- **R-HS21 — Keys.** A section row keeps its palette key (`section.rawValue`), so a recent survives; a setting row is
  keyed by its row id. A test holds that no row id equals a section's raw value.
- **R-HS22 — "Typing lands on a row" is tested through its seams.** `SettingsPanel`'s ⏎ and landing move into a pure
  `SettingsSearchLanding`, driven in a test with the real `SettingsFocus`; `SettingsRowLintTests` already proves every
  indexed row carries its anchor. The scroll and the wash are the orchestrator's live check (a headless `swift test`
  cannot query a hosted view's accessibility tree).

---

## File map

| File | Task | Responsibility |
|---|---|---|
| `app/…/Views/Meadow/HomeHeroBand.swift` (`git mv` from `HomeSkyBand.swift`) | 1 | `HomeBandLayout` (120 pt, `imageOffsetY`), `HomeHeroBand` — paint only |
| `app/…/Views/Home/HomeView.swift` | 1 | band → headline row → field block → blocks; page width for Needs you |
| `app/…/Views/Home/HomeSections.swift` | 1 | `HomeBlock`, `HomeLine`; Today, Needs you (`InboxRow`), Last read (`Tag` chips) |
| `app/…/Views/Home/GettingStartedCard.swift` | 1 | material, Hide, ×, Choose a file…, weights |
| `app/…/Views/Common/InlineLink.swift` (new) | 1 | the one accent text link (DR-5 use 5) |
| `app/…/Support/HomeLayout.swift`, `Support/HomeFigures.swift` | 1 | column constants, `needsYouSlots`; `HomeChip.type` |
| `app/…/Theme/Copy+Welcome.swift` | 1 | one-line headline, `homeShowOnGraph` |
| `app/…/Theme/Copy+HomeSleep.swift` (new) | 2–5 | DS-3b words and their lint list |
| `app/…/Theme/Copy.swift`, `Theme/Copy+Settings.swift` | 2, 3 | retire `runsOn(engine:)` and `whenYouStart` / `onTheSchedule` (2); the tiles' nouns (3) |
| `app/…/Views/Sleep/EngineQuickMenu.swift` (new) | 2 | `EngineQuickMenuModel`, `SleepEnginePreviewSource`, `EngineQuickMenuButton`, `EngineQuickMenu` |
| `app/…/ViewModels/SleepEngineViewModel.swift` | 2 | injectable, `isSaving`, `writeFailed`, `apply(_:)` |
| `app/…/Views/Settings/EngineOption.swift`, `EngineChooser.swift`, `SettingsSleepView.swift` | 2 | `EngineWrite`, `candidateId(forEngine:)`; one write rule; one preview wording |
| `app/…/Views/Sleep/SleepHero.swift`, `SleepView.swift`, `LampPopover.swift`, `ViewModels/SleepViewModel.swift` (comments) | 2 | the control row, `EngineMark.source`, one preview source |
| `app/…/Views/Common/NeutralButton.swift`, `Views/Common/ProgressiveColumns.swift` | 2 | `leading`, `trailingSystemImage`, `lineLimit(1)`; `RowMetrics.menuItem`, `.keyValue` |
| `app/…/Views/Sleep/SleepDetails.swift`, `StudyListCard.swift`, `ConsolidationHistoryCard.swift`, `EpisodeRow.swift`, `SleepHero.swift`, `SleepView.swift` | 3 | Details in list grammar |
| `app/…/Services/LocalSources/AgentFolders.swift` (new) | 4 | the subfolder ↔ glob rule, folder listing |
| `app/…/Views/Settings/SettingsSheet.swift` (new) | 4 | the one sheet frame |
| `app/…/Views/Settings/LocalSourceRows.swift`, `IntegrationsView.swift`, `Services/LocalSources/LocalSourceWatcher.swift`, `Models/IntegrationCategory.swift` | 4 | labels, picker, sheets, marks |
| `app/…/Search/QuickIndex.swift`, `Search/FindModels.swift`, `Search/FindPaletteModel.swift`, `Search/FindMerge.swift`, `Views/Find/FindRowView.swift`, `Views/Find/FindPanelBody.swift`, `ContentView.swift` | 5 | Settings rows in ⌘K; ⏎ opens through the door |
| `app/…/Views/Settings/SettingsIndex.swift`, `SettingsPanel.swift` | 5 | `SettingsSearchLanding` |
| Tests (new) | 1–5 | `HomeSleepCopyTests`, `EngineQuickMenuTests`, `AgentFoldersTests`, `SettingsSheetLintTests`, `SettingsSearchLandingTests` |
| Tests (edited) | 1–5 | `HomeBandLayoutTests`, `HomeLayoutTests`, `HomeFiguresTests`, `RoomSentenceTests`, `SleepHeroTests`, `SleepDetailsTests`, `SelectionTintLintTests`, `IntegrationsViewTests`, `QuickIndexTests`, `FindPaletteTests`, `PaletteMergeTests` |
| Docs | 6 | `CLAUDE.md`, `docs/design/DESIGN_RULES.md` (§9, §10), `docs/goals/TODO.md`, `docs/goals/memory-evolution.md` |

(`app/…` = `app/CicadaApp/Sources/CicadaApp`.)

---

### Task 1: Home in Direction D — the painted band, the headline under it, labelled blocks, Needs you as the Inbox's rows (DR-13, DR-16, DR-17, DR-20, DR-21, DR-34, DR-36, DR-37, DR-38, DR-40, DR-44, DR-48, DR-50, DR-52, DR-70; G108, G125 R10; R-HS2…R-HS6)

The branch stays shippable: Home keeps every behaviour (the field, the save-link row, Getting started, Today, Needs you,
Last read, every link), only its drawing and one row definition move.

**Files:**
- Rename: `app/…/Views/Meadow/HomeSkyBand.swift` → `app/…/Views/Meadow/HomeHeroBand.swift` (`git mv`, then rewrite)
- Modify: `app/…/Views/Home/HomeView.swift`, `app/…/Views/Home/HomeSections.swift`,
  `app/…/Views/Home/GettingStartedCard.swift`, `app/…/Support/HomeLayout.swift`, `app/…/Support/HomeFigures.swift:29-32, 92-103`,
  `app/…/Theme/Copy+Welcome.swift:15-16, 157-158`
- Create: `app/…/Views/Common/InlineLink.swift`
- Test: `Tests/CicadaAppTests/HomeBandLayoutTests.swift` (rewrite), `HomeLayoutTests.swift` (append),
  `HomeFiguresTests.swift` (append)

**Interfaces:**
- Produces `HomeBandLayout.bandHeight` (120), `.focusY` (0.63), `.fadeStart` (0.4),
  `.imageOffsetY(imageSize:bandSize:)`; `HomeHeroBand`; `HomeLayout.columnWidth` (760), `.fieldWidth` (640),
  `.headlineTop` (8), `.headlineBottom` (20), `.bottomPadding` (64), `.labelGap` (6), `.blockGap` (24), `.gutter` (40),
  `.blockInset` (4), `.needsYouSlots(pageWidth:scale:)`; `HomeBlock`, `HomeLine`; `InlineLink(title:help:action:)`;
  `HomeChip.type`; `Copy.homeShowOnGraph(_:)`.
- Consumes `MeadowArt.image(for:mode:)`, `MeadowRules.increasedContrastCeiling`, `PageTitle`, `FindPanelBody`,
  `InboxRow`, `InboxRowSlots.of(listUnits:)`, `RowMetrics.oneLine`, `Tag`, `TextButton`, `IconButton`, `NeutralButton`,
  `CicadaTheme.entityColor(for:)`.

- [ ] **Step 1: Failing tests.** Rewrite `HomeBandLayoutTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// R-HS2 — Home's band is the D-Home mock: the painted hero, 120 pt, the meadow line in view,
/// and nothing over it (DR-13, DR-50: text never sits on paint).
final class HomeBandLayoutTests: XCTestCase {
    func testTheBandIsTheMocksHeightAndFade() {
        XCTAssertEqual(HomeBandLayout.bandHeight, 120)
        XCTAssertEqual(HomeBandLayout.focusY, 0.63, accuracy: 0.0001, "object-position: center 63%")
        XCTAssertEqual(HomeBandLayout.fadeStart, 0.4, accuracy: 0.0001, "mask: #000 40% → transparent")
    }

    /// The painting is 1200 × 700 pt (2400 × 1400 px at 2×). Filled into the band, it moves exactly as
    /// CSS `object-fit: cover; object-position: center 63%` moves it: the painting's 63 % line meets
    /// the band's 63 % line, i.e. the centred painting shifts up by 13 % of its overflow — and so never
    /// far enough for the band to show past its edge.
    func testTheImageOffsetIsObjectPositionSixtyThreeAndNeverUncoversTheBand() {
        let hero = CGSize(width: 1200, height: 700)
        // 1000 wide: filled 583.33 tall, overflow 463.33, × 0.13.
        XCTAssertEqual(HomeBandLayout.imageOffsetY(imageSize: hero, bandSize: CGSize(width: 1000, height: 120)),
                       -60.2333, accuracy: 0.001)
        XCTAssertEqual(HomeBandLayout.imageOffsetY(imageSize: hero, bandSize: CGSize(width: 400, height: 120)),
                       -14.7333, accuracy: 0.001)
        XCTAssertEqual(HomeBandLayout.imageOffsetY(imageSize: hero, bandSize: CGSize(width: 3000, height: 120)),
                       -211.9, accuracy: 0.001)
        // A band the filled painting exactly covers: no overflow, no shift, never a gap.
        XCTAssertEqual(HomeBandLayout.imageOffsetY(imageSize: hero, bandSize: CGSize(width: 100, height: 300)),
                       0, accuracy: 0.001)
        XCTAssertEqual(HomeBandLayout.imageOffsetY(imageSize: .zero, bandSize: CGSize(width: 100, height: 120)), 0)
        for width in stride(from: CGFloat(320), through: 2400, by: 40) {
            for scale in stride(from: CGFloat(0.8), through: 1.4001, by: 0.1) {
                let band = CGSize(width: width, height: HomeBandLayout.bandHeight * scale)
                let fill = max(band.width / hero.width, band.height / hero.height)
                let slack = (hero.height * fill - band.height) / 2
                let offset = HomeBandLayout.imageOffsetY(imageSize: hero, bandSize: band)
                XCTAssertLessThanOrEqual(abs(offset), slack + 0.001, "width \(width) scale \(scale)")
            }
        }
    }

    /// DR-13 / DR-50 — the band is paint only, and nothing is drawn over it: the headline is the
    /// next row down, so no `Text(` lives in the band's file and Home stacks rather than overlays.
    func testNoWordIsDrawnOnThePaint() throws {
        let files = try ThemeTokenTests.swiftSources()
        let band = try XCTUnwrap(files.first { $0.path.hasSuffix("Views/Meadow/HomeHeroBand.swift") })
        let bandText = try String(contentsOf: band, encoding: .utf8)
        XCTAssertFalse(bandText.contains("Text("), "the band carries no word (DR-13)")
        XCTAssertFalse(bandText.contains("DriftingCloud("), "the hero's clouds are painted (R-HS2)")
        let home = try XCTUnwrap(files.first { $0.path.hasSuffix("Views/Home/HomeView.swift") })
        let homeText = try String(contentsOf: home, encoding: .utf8)
        XCTAssertFalse(homeText.contains("ZStack"), "nothing on Home is layered over the band")
        let bandLine = try XCTUnwrap(homeText.range(of: "HomeHeroBand()"))
        let titleLine = try XCTUnwrap(homeText.range(of: "PageTitle(Copy.homeHeadline)"))
        XCTAssertLessThan(bandLine.lowerBound, titleLine.lowerBound, "the headline is the row under the band")
    }
}
```

Append to `HomeLayoutTests.swift`:

```swift
    /// R-HS2, R-HS6 — the D-Home mock's column, field and gaps.
    func testTheColumnAndTheFieldAreTheMocks() {
        XCTAssertEqual(HomeLayout.columnWidth, 760, "DR-36 — a text column is at most 760 pt")
        XCTAssertEqual(HomeLayout.fieldWidth, 640, "the approved mock's field (§10's 560 lost to it, R-HS2)")
        XCTAssertEqual(HomeLayout.blockGap, 24)
        XCTAssertEqual(HomeLayout.labelGap, 6)
    }

    /// R-HS4 — Needs you's rows are the Inbox's STATE 0 rows, so their slots follow R-DI26's floors,
    /// measured in units from Home's own column (760 less the 4 pt inset, or the page less its gutters).
    func testNeedsYouDropsSlotsAtTheInboxsFloors() {
        XCTAssertEqual(HomeLayout.needsYouSlots(pageWidth: 1384, scale: 1.0), InboxRowSlots(entity: true, source: true))
        XCTAssertEqual(HomeLayout.needsYouSlots(pageWidth: 1144, scale: 1.4), InboxRowSlots(entity: true, source: true))
        XCTAssertEqual(HomeLayout.needsYouSlots(pageWidth: 992, scale: 1.4), InboxRowSlots(entity: false, source: true))
        XCTAssertEqual(HomeLayout.needsYouSlots(pageWidth: 600, scale: 1.4), InboxRowSlots(entity: false, source: false))
        XCTAssertEqual(HomeLayout.needsYouSlots(pageWidth: 0, scale: 0), InboxRowSlots(entity: false, source: false),
                       "a zero width never traps")
    }

    /// G125 R10, R-HS3 — Home links to the Sleep page and never starts a cycle.
    func testHomeNeverStartsACycle() throws {
        let files = try ThemeTokenTests.swiftSources()
        for suffix in ["Views/Home/HomeView.swift", "Views/Home/HomeSections.swift"] {
            let file = try XCTUnwrap(files.first { $0.path.hasSuffix(suffix) })
            let text = try String(contentsOf: file, encoding: .utf8)
            for needle in ["triggerManually", "Copy.consolidateNow", "PrimaryActionButton("] {
                XCTAssertFalse(text.contains(needle), "\(suffix) — \(needle)")
            }
        }
    }
```

Append to `HomeFiguresTests.swift` (its own `entry(_:files:)` helper and `FindFixtures.node`, as
`testChipsAreEntityPagesThatStillExistInTheGraph` uses them):

```swift
    /// R-HS6 — a Last read chip carries its page's type, for the `Tag`'s dot (DR-44).
    func testAChipCarriesItsPagesType() throws {
        let e = try entry("s1", files: ["entities/bob-example.md", "entities/alpha-project.md"])
        let nodes = [FindFixtures.node("alpha-project", "alpha-project"),
                     FindFixtures.node("bob-example", "bob-example", type: .person)]
        XCTAssertEqual(HomeFigures.chips(e, nodes: nodes).shown.first?.type, .person)
    }
```

Run: `cd <worktree>/app/CicadaApp && swift test --filter 'HomeBandLayoutTests|HomeLayoutTests|HomeFiguresTests' 2>&1 | tail -20`
→ compile failure (the new names do not exist). That is the red.

- [ ] **Step 2: The band.** `git mv app/CicadaApp/Sources/CicadaApp/Views/Meadow/HomeSkyBand.swift app/CicadaApp/Sources/CicadaApp/Views/Meadow/HomeHeroBand.swift`,
  then replace its contents:

```swift
import SwiftUI

/// Where Home's painting sits in its band (R-HS2), as pure geometry (`HomeBandLayoutTests`).
enum HomeBandLayout {
    /// The D-Home mock's band.
    static let bandHeight: CGFloat = 120
    /// `object-position: center 63%` — the painting's meadow line, not its empty sky.
    static let focusY: CGFloat = 0.63
    /// `mask-image: linear-gradient(to bottom, #000 40%, transparent 100%)` — the painting fades
    /// into `bgBase`, so the headline row below it sits on the window, never on paint (DR-50).
    static let fadeStart: CGFloat = 0.4

    /// How far to move the filled painting, translated from the mock's CSS: `object-position:
    /// center 63%` puts the painting's 63 % line on the band's 63 % line, so the centred painting
    /// (`.scaledToFill()` centres it) moves by `(focusY − 0.5)` of its overflow. That fraction is
    /// under a half, so the band can never show past the painting's edge — no clamp is needed.
    /// This is the one number that turns "centre" into "centre 63 %".
    static func imageOffsetY(imageSize: CGSize, bandSize: CGSize) -> CGFloat {
        guard imageSize.width > 0, imageSize.height > 0, bandSize.width > 0, bandSize.height > 0 else { return 0 }
        let fill = max(bandSize.width / imageSize.width, bandSize.height / imageSize.height)
        let overflow = max(0, imageSize.height * fill - bandSize.height)
        return -overflow * (focusY - 0.5)
    }
}

/// Home's band (DS-3b, D-Home; DR-13): the bundled onboarding hero — `-dark` at night through
/// `MeadowArt.image`, which reading `CicadaTheme.mode` here subscribes to — filled into 120 pt
/// with its meadow in view and faded into `bgBase` below. **Paint only:** no word and no number
/// sits on it (DR-13, DR-50); Home's headline is the next row down. No drifting cloud — the
/// hero's clouds are painted, and a moving one over them would double them (`WelcomeHero`'s
/// reason). Under Increase Contrast it steps back like every Meadow decoration (R9 §7). A bundle
/// that lost the file draws nothing, and the band is just the window.
///
/// It replaced the procedural sky band (one cloud under a two-line headline drawn over it).
struct HomeHeroBand: View {
    @Environment(\.colorSchemeContrast) private var contrast

    var body: some View {
        GeometryReader { geo in
            if let image = MeadowArt.image(for: .heroDay, mode: CicadaTheme.mode) {
                Image(nsImage: image)
                    .resizable()
                    .interpolation(.high)
                    .scaledToFill()
                    .frame(width: geo.size.width, height: geo.size.height)
                    .offset(y: HomeBandLayout.imageOffsetY(imageSize: image.size, bandSize: geo.size))
                    .frame(width: geo.size.width, height: geo.size.height)
                    .clipped()
                    .mask(LinearGradient(stops: [.init(color: .black, location: HomeBandLayout.fadeStart),
                                                 .init(color: .clear, location: 1)],
                                         startPoint: .top, endPoint: .bottom))
                    .opacity(contrast == .increased ? MeadowRules.increasedContrastCeiling : 1)
            }
        }
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }
}
```

- [ ] **Step 3: Layout, figures, copy, the link.**
  - `Support/HomeLayout.swift`: keep `showsWaitingInToday` and add, above it, with a docstring citing R-HS2/R-HS4/R-HS6:

```swift
    /// D-Home (R-HS2, R-HS6): one 760 pt column (DR-36), the field 640 pt inside it (the approved
    /// mock; §10's 560 lost to it), the headline 8 / 20 pt off its neighbours, 24 pt between blocks,
    /// 6 pt from a label to its block, and 64 pt under the last one.
    static let columnWidth: CGFloat = 760
    static let fieldWidth: CGFloat = 640
    static let headlineTop: CGFloat = 8
    static let headlineBottom: CGFloat = 20
    static let blockGap: CGFloat = 24
    static let labelGap: CGFloat = 6
    static let bottomPadding: CGFloat = 64
    static let gutter: CGFloat = 40
    static let blockInset: CGFloat = 4

    /// R-HS4 — Needs you draws the Inbox's own STATE 0 row, so its entity and source slots drop at
    /// the Inbox's floors (R-DI26), measured in units: the column, or the page less its two gutters
    /// when the window is narrower, less the block's inset on each side.
    static func needsYouSlots(pageWidth: CGFloat, scale: CGFloat) -> InboxRowSlots {
        guard pageWidth > 0, scale > 0 else { return InboxRowSlots(entity: false, source: false) }
        let units = pageWidth / scale
        let column = min(columnWidth, units - 2 * gutter)
        return InboxRowSlots.of(listUnits: column - 2 * blockInset)
    }
```

  - `Support/HomeFigures.swift`: `HomeChip` gains `let type: EntityType` (after `name`). In `chips(_:nodes:)` keep a
    `[String: GraphNode]` instead of `[String: String]` and build `HomeChip(id: id, name: node.name, type: node.type)`;
    the rest of the function is unchanged (a deleted page is never a chip, a repeat counts once).
  - `Theme/Copy+Welcome.swift:15-16`: `homeHeadline` becomes `"What would you like to remember?"` (R-HS2); delete
    `homeHeadlineItalic` and remove it from `welcomeHomeLabels` (`:158`). Add, beside the other Home strings, and add it
    to `welcomeHomeLabels` as `homeShowOnGraph("alpha-project")`:

```swift
    /// A Last read chip's hover (DR-69): where the click goes.
    static func homeShowOnGraph(_ name: String) -> String { "Show \(name) on the graph" }
```

  - Create `Views/Common/InlineLink.swift`:

```swift
import SwiftUI

/// DR-5 use 5 — a link: 12 medium in `accentText`, no fill, the label's own words (a "›" when it
/// goes to another page). One definition for Home's "Sleep ›" / "All 6 ›" and the Sleep menu's
/// "More in Settings → Engines ›", so a link is never an ad-hoc `Button` tinted by hand.
/// `accentText` (not the accent) is what clears 4.5:1 in light mode (DR-6).
struct InlineLink: View {
    let title: String
    var help: String? = nil
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Text(title)
                .font(CicadaTheme.metaMediumFont)
                .monospacedDigit()
                .foregroundStyle(CicadaTheme.accentText)
        }
        .buttonStyle(.cicadaPlain)
        .help(help ?? title)
    }
}
```

- [ ] **Step 4: `HomeView`.** Replace `body` (`:28-70`), `band` (`:77-100`) and `fieldColumn` (`:104-122`); keep `open`,
  the environment, `saveLinkRow`'s behaviour and `save(_:)`. The `.task` block is copied unchanged. Update the type's
  docstring's first paragraph to say it is drawn in D (D-Home), with no Consolidate (G125 R10, R-HS3); keep its
  R-IB3 and R-IB8 paragraphs.

```swift
    var body: some View {
        let showsResults = FindPanelBody.showsBody(placement: .page, query: search.model.query,
                                                   mode: search.model.mode)
        // One clock per evaluation, so every section agrees on which UTC day "today" is.
        let today = Date()
        let _ = runner.checklistRevision
        // While the card's read row shows, TODAY omits its own waiting clause
        // (`HomeLayout`, every number once).
        let gettingStartedVisible = GettingStartedProgress.visible(record: GettingStartedState.load(bank: store.bank))
            || runner.sawDoneThisSession
        GeometryReader { geo in
            VStack(spacing: 0) {
                // DR-13 — paint only: no word, no number and nothing over it (`HomeBandLayoutTests`).
                HomeHeroBand()
                    .frame(height: CicadaTheme.scaled(HomeBandLayout.bandHeight))
                VStack(spacing: 0) {
                    // R-HS2 — the headline is the row under the band, on the window (DR-50), in the
                    // room pages' title (DR-17): one line, the mock's words.
                    PageTitle(Copy.homeHeadline)
                        .multilineTextAlignment(.center)
                        .accessibilityAddTraits(.isHeader)
                        .padding(.top, CicadaTheme.scaled(HomeLayout.headlineTop))
                        .padding(.bottom, CicadaTheme.scaled(HomeLayout.headlineBottom))
                    fieldColumn(showsResults: showsResults)
                        .frame(maxWidth: CicadaTheme.scaled(HomeLayout.fieldWidth))
                    if !showsResults {
                        ScrollView {
                            VStack(alignment: .leading, spacing: CicadaTheme.scaled(HomeLayout.blockGap)) {
                                // Between the field and TODAY, and only while the blocks show
                                // (R-IB6): the first keystroke replaces it too.
                                GettingStartedCard(selectedTab: $selectedTab)
                                HomeSections(today: today, gettingStartedVisible: gettingStartedVisible,
                                             needsYouSlots: HomeLayout.needsYouSlots(
                                                 pageWidth: geo.size.width, scale: CGFloat(CicadaTheme.uiScale)),
                                             selectedTab: $selectedTab)
                            }
                            .frame(maxWidth: CicadaTheme.scaled(HomeLayout.columnWidth))
                            .padding(.top, CicadaTheme.spacingCard)
                            .padding(.bottom, CicadaTheme.scaled(HomeLayout.bottomPadding))
                            .frame(maxWidth: .infinity)
                        }
                        .scrollIndicators(.automatic)
                        .transition(.opacity)
                    }
                }
                .padding(.horizontal, CicadaTheme.spacingGutter)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
                .animation(CicadaMotion.morph(reduceMotion: reduceMotion), value: showsResults)
            }
            .frame(width: geo.size.width, height: geo.size.height)
        }
        .background(CicadaTheme.bgBase)
        // (the existing `.task { … }` block, unchanged)
    }

    // MARK: The field

    /// The palette's own body in `.page` placement (R-IB6), unchanged, in D's grouped-block
    /// material: `bgFocus`, `cornerRadius`, a resting ring (`glassCard()` — the mock's 10 pt block).
    @ViewBuilder
    private func fieldColumn(showsResults: Bool) -> some View {
        VStack(spacing: CicadaTheme.spacingSM) {
            if let url = LinkPaste.url(in: search.model.query) {
                saveLinkRow(url)
            }
            FindPanelBody(model: search.model, placement: .page, open: open,
                          prompt: Copy.homeFieldPrompt, focusRequest: search.focusRequest,
                          submitOverride: {
                              guard let url = LinkPaste.url(in: search.model.query) else { return false }
                              save(url)
                              return true
                          })
                .glassCard()
                .frame(maxHeight: showsResults ? .infinity : nil)
        }
        .frame(maxHeight: showsResults ? .infinity : nil, alignment: .top)
    }
```

  In `saveLinkRow(_:)` (`:125-146`): the `link` glyph becomes `.foregroundStyle(CicadaTheme.textTertiary)` (DR-5 has no
  "decorative glyph" use); the title `.font(CicadaTheme.rowFont)`; the hand-drawn `Text(verbatim: "⏎")` becomes
  `KeyHint("⏎")` (DR-49); the padding becomes `.padding(.horizontal, CicadaTheme.scaled(10))` with
  `.frame(minHeight: CicadaTheme.scaled(RowMetrics.oneLine))`; the background becomes `.glassCard()`.

- [ ] **Step 5: `HomeSections`.** Replace the file's body below `HomeSections` with D's grammar. `HomeSections` gains
  `let needsYouSlots: InboxRowSlots` (after `gettingStartedVisible`) and passes it to `NeedsYouSection`, and its
  `VStack` spacing becomes `CicadaTheme.scaled(HomeLayout.blockGap)`. Its docstring gains: "in Direction D's list
  grammar (DS-3b): a `SectionLabel` over one grouped block, 36 pt rows, links in `accentText` (R-HS6)". Delete
  `HomeCard` and `HomeRowButton` (no other file uses them — `rg -n 'HomeCard|HomeRowButton' app/CicadaApp` prints only
  this file). Add:

```swift
/// DR-20, DR-37 — a Home section: its `SectionLabel` above one grouped block (`glassCard()`:
/// `bgFocus`, `cornerRadius`, a resting ring), 4 pt inside so a row's hover fill sits concentric
/// (DR-12). It replaced the old Home card, whose label sat inside a padded `surface` card (P1,
/// R-HS6). (Never name the retired type here: Step 7's sweep greps for it.)
struct HomeBlock<Content: View>: View {
    let title: String
    @ViewBuilder let content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.scaled(HomeLayout.labelGap)) {
            SectionLabel(title)
                .padding(.horizontal, CicadaTheme.scaled(10))
            VStack(alignment: .leading, spacing: 0) { content }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(CicadaTheme.scaled(HomeLayout.blockInset))
                .glassCard()
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// One line in a block (DR-34): the list row's 36 pt from `RowMetrics`, 10 pt in.
struct HomeLine<Content: View>: View {
    @ViewBuilder let content: Content

    var body: some View {
        HStack(spacing: CicadaTheme.scaled(10)) { content }
            .padding(.horizontal, CicadaTheme.scaled(10))
            .frame(maxWidth: .infinity, minHeight: CicadaTheme.scaled(RowMetrics.oneLine), alignment: .leading)
    }
}
```

  Keep `HomeUnknown`. Rewrite the three sections' `body`s over `HomeBlock` / `HomeLine`, keeping every figure, route and
  accessibility label they have today:
  - **Today:** `HomeBlock(title: Copy.homeToday)`. The captured line is a `HomeLine`: the count (`bodyFont`,
    `.monospacedDigit()`, `textPrimary`, `.help(Copy.homeCapturedHelp)`), a `Spacer`, then each origin as a
    `Button { router.routeToSourceDetail(chip.sourceId) }` whose label is
    `OriginMark(origin: chip.mark, size: CicadaTheme.scaled(16))` in a `scaled(28)` square with
    `.contentShape(Rectangle())` and `.markHover()` (DR-52's rows nod with `markHover`), keeping today's `.help` and
    `.accessibilityLabel`. "Nothing captured yet today" is `bodyFont` in `textSecondary`. The waiting line is a
    `HomeLine`: `BookwormView(state: worm, pointSize: 24)` (the pixel lattice's size, unchanged), the waiting words
    (`bodyFont`, `.monospacedDigit()`), a `Spacer`, and `InlineLink(title: Copy.homeOpenSleep) { selectedTab = .sleep }`
    — a link to the page that owns the queue, never a trigger (G125 R10).
  - **Needs you:** `HomeBlock(title: Copy.homeNeedsYou)`. Empty → a `HomeLine` with `Copy.homeNothingNeedsYou`
    (`bodyFont`, `textSecondary`). Otherwise, with `let now = Date.now` (DR-58: an age is computed when read):

```swift
                ForEach(figures.shown) { item in
                    // R-HS4 — the Inbox's own STATE 0 row, so a question reads here exactly as it does
                    // there; the palette's hand-off (`pendingInboxItem`) lands it in STATE 1.
                    InboxRow(item: item, style: .wide, slots: needsYouSlots, selected: false, now: now) {
                        router.pendingInboxItem = item.id
                        selectedTab = .inbox
                    }
                }
                if figures.total > HomeFigures.needsYouLimit {
                    HomeLine {
                        InlineLink(title: Copy.homeAllInbox(figures.total)) { selectedTab = .inbox }
                    }
                }
```

    `NeedsYouSection` gains `let needsYouSlots: InboxRowSlots`, declared before its `@Binding var selectedTab`, and
    `HomeSections.body` calls it as `NeedsYouSection(needsYouSlots: needsYouSlots, selectedTab: $selectedTab)`.
  - **Last read:** `HomeBlock(title: Copy.homeLastRead)`. `.loading` → `HomeLine { HomeUnknown() }`; `.never` →
    `HomeLine` with `Copy.homeNothingReadYet` in `textSecondary`; `.earlier(let at)` → `HomeLine` with the day
    (`bodyFont`, `.monospacedDigit()`) or `HomeUnknown()`, a `Spacer`, and `InlineLink(title: Copy.homeOpenSleep)`;
    `.entry(let entry)` → `read(entry)`:

```swift
    private func read(_ entry: SleepHistoryEntry) -> some View {
        let chips = HomeFigures.chips(entry, nodes: store.graph.value?.nodes ?? [])
        return VStack(alignment: .leading, spacing: 0) {
            HomeLine {
                Text(HomeFigures.lastReadLine(entry))
                    .font(CicadaTheme.bodyFont)
                    .monospacedDigit()
                    .foregroundStyle(CicadaTheme.textPrimary)
                Spacer(minLength: CicadaTheme.spacingSM)
                InlineLink(title: Copy.homeOpenSleep) { selectedTab = .sleep }
            }
            if !chips.shown.isEmpty {
                // DR-44 — the one pill, with the page type's dot inside it; a click opens the graph.
                HStack(spacing: CicadaTheme.scaled(6)) {
                    ForEach(chips.shown, id: \.id) { chip in
                        Button {
                            selectedTab = .graph
                            graphVM.revealEntity(id: chip.id)
                        } label: {
                            Tag(text: chip.name, dot: CicadaTheme.entityColor(for: chip.type))
                        }
                        .buttonStyle(.cicadaPlain)
                        .help(Copy.homeShowOnGraph(chip.name))
                    }
                    if chips.more > 0 {
                        Text(Copy.homeMoreChips(chips.more))
                            .font(CicadaTheme.metaFont)
                            .monospacedDigit()
                            .foregroundStyle(CicadaTheme.textTertiary)
                    }
                }
                .padding(.horizontal, CicadaTheme.scaled(10))
                .padding(.vertical, CicadaTheme.spacingSM)
            }
        }
    }
```

- [ ] **Step 6: Getting started's material (R-HS5).** In `GettingStartedCard.swift`:
  - `:86-88`: `.padding(CicadaTheme.spacingLG)` and the `surface` background become
    `.padding(EdgeInsets(top: CicadaTheme.spacingXL, leading: CicadaTheme.spacingCard, bottom: CicadaTheme.spacingCard, trailing: CicadaTheme.spacingCard))`,
    `.background(CicadaTheme.bgFocus, in: CicadaTheme.shape(CicadaTheme.radiusLarge))` and
    `.ringed(in: CicadaTheme.shape(CicadaTheme.radiusLarge))` — the focus card's material (DR-9, DR-10, §3.5).
  - `:80`: delete `Divider()` (DR-11); the `VStack`'s spacing is the group gap.
  - `:137-145`: Hide becomes `TextButton(title: Copy.gsHide) { … the same three lines … }`.
  - `:176-189`: `dismissButton` becomes
    `IconButton(systemName: "xmark", help: Copy.gsDismiss, accessibilityLabel: "\(Copy.gsDismiss), \(row.title)") { … the same branch … }`.
    Apply the same to the export-wait row's × (`:244-253`) with `Copy.reminderDismiss`.
  - `:242-243` and `:270-271`: "Choose a file…" becomes
    `NeutralButton(title: Copy.intakeChooseFile, size: .compact) { … the same `intake.present(…)` call … }`.
  - `:263` and `:367`: `weight: .semibold` → `weight: .medium` (DR-16 reserves semibold).
  Nothing else in the card moves.

- [ ] **Step 7: Green and sweep.** Run the filtered tests (green), then
  `cd <worktree>/app/CicadaApp && swift build 2>&1 | tail -5` and `swift test 2>&1 | tail -20` (0 failures).
  `rg -n 'HomeSkyBand|homeHeadlineItalic|HomeCard\b|HomeRowButton|headlineFrame|cloudFrame' <worktree>/app/CicadaApp`
  prints nothing (on `2517ca3` the only readers are `HomeView.swift` and `HomeBandLayoutTests.swift`, both rewritten
  above; if a doc comment still names one, reword it). CLAUDE.md's `HomeSkyBand` mention is Task 6's.

- [ ] **Step 8: Commit.** Stage the files above only (the rename is staged by `git mv`). Message:
  `feat(ds3b, g108): Home in Direction D — the painted band with the headline under it, labelled blocks of 36 pt rows, Needs you as the Inbox's own rows, no Consolidate (DR-13, DR-16, DR-17, DR-20, DR-21, DR-34, DR-36, DR-37, DR-38, DR-40, DR-44, DR-48, DR-50, DR-52, DR-70)`

---

### Task 2: The Sleep page's quick engine and model menu — one source of truth, both previews (DR-5, DR-38, DR-40, DR-41, DR-48, DR-52, DR-59, DR-69; G122, G125; ruling 4; R-HS7…R-HS14)

**Files:**
- Create: `app/…/Views/Sleep/EngineQuickMenu.swift`, `app/…/Theme/Copy+HomeSleep.swift`
- Modify: `app/…/ViewModels/SleepEngineViewModel.swift`, `app/…/Views/Settings/EngineOption.swift`,
  `app/…/Views/Settings/EngineChooser.swift:107-113, 192-245`, `app/…/Views/Settings/SettingsSleepView.swift:83-84`,
  `app/…/Theme/Copy+Settings.swift:48-49` (delete `whenYouStart`, `onTheSchedule`), `app/…/Theme/Copy.swift:80-88, 160-164`,
  `app/…/Views/Sleep/SleepHero.swift:418-526`, `app/…/Views/Sleep/SleepView.swift:168-176, 271-276, 334-343, 619-621`,
  `app/…/Views/Sleep/LampPopover.swift:74`, `app/…/Views/Common/NeutralButton.swift`,
  `app/…/Views/Common/ProgressiveColumns.swift:180-187`, `app/…/ViewModels/SleepViewModel.swift:48-55, 230-234`
  (comments only)
- Test: `Tests/CicadaAppTests/EngineQuickMenuTests.swift` (new), `HomeSleepCopyTests.swift` (new),
  `RoomSentenceTests.swift:277-281`, `SelectionTintLintTests.swift:7-8`

**Interfaces:**
- Produces `EngineWrite(mode:model:)`, `.choosing(_:current:)`, `.model(_:mode:current:)`;
  `EngineOption.candidateId(forEngine:)`; `SleepEngineViewModel(fetch:update:)`, `.isSaving`, `.writeFailed`,
  `.apply(_:)`; `EngineQuickMenuModel` (`Row`, `Preview`, `.buttonLabel(_:)`, `.from(_:)`);
  `SleepEnginePreviewSource.current(chooser:page:)`; `EngineQuickMenuButton`; `EngineQuickMenu`;
  `EngineMark.Source` + `.source(for:)`; `controlCaption(isRunning:)`; `NeutralButton.leading`, `.trailingSystemImage`;
  `RowMetrics.menuItem`; `Copy.EngineMenu.*`; `Copy.homeSleepLabels`.
- Consumes `GET/PUT /sleep/engine` through `APIClient.fetchSleepEngine` / `updateSleepEngine` only;
  `EngineOption.isSelectable/caption/logoName/symbol/previewMark`; `OllamaGuideState`; `CommandBox`;
  `LogoImage.platformTile`; `InlineLink` (Task 1); `AppRouter.openSettings(_:row:)`.

- [ ] **Step 1: Failing tests.** Create `EngineQuickMenuTests.swift`:

```swift
import SwiftUI
import XCTest
@testable import CicadaApp

/// The owner's quick switch (2026-09-23) — R-HS7…R-HS13. Every string it shows and every write it
/// makes is decided here, from synthetic `/sleep/engine` bodies; nothing reaches `APIClient.shared`.
@MainActor
final class EngineQuickMenuTests: XCTestCase {
    override func tearDown() {
        CicadaTheme.uiScale = 1.0
        CicadaTheme.mode = .dark
        super.tearDown()
    }

    private static let autoDetail = "Your Claude plan if it's signed in, else your ChatGPT plan, else Ollama if it's running, else your API key."
    private static let keyDetail = "Uses the model configured on the Plans & keys page."

    private func response(mode: String, model: String = "sonnet", codexSignedIn: Bool = true,
                          manual: (String, String) = ("claude-cli", "sonnet"),
                          scheduled: (String, String) = ("litellm", "example-model"),
                          localModels: [String] = [], localAvailable: Bool = false) -> SleepEngineResponse {
        SleepEngineResponse(
            mode: mode, model: model, disambiguationModel: "", source: "prefs",
            candidates: [
                SleepEngineCandidate(id: "auto", label: "Auto", available: true, connected: false, models: [],
                                     detail: Self.autoDetail),
                SleepEngineCandidate(id: "agent", label: "Claude plan", available: true, connected: true,
                                     models: ["sonnet", "haiku", "opus"], detail: nil),
                SleepEngineCandidate(id: "codex", label: "ChatGPT plan", available: true, connected: codexSignedIn,
                                     models: codexSignedIn ? ["example-codex-model"] : [], detail: nil),
                SleepEngineCandidate(id: "local", label: "Ollama", available: localAvailable,
                                     connected: localAvailable, models: localModels, detail: nil),
                SleepEngineCandidate(id: "byok", label: "API key", available: true, connected: true, models: [],
                                     detail: Self.keyDetail),
            ],
            preview: SleepEnginePreviews(manual: SleepEnginePreview(engine: manual.0, model: manual.1, why: "chosen"),
                                         scheduled: SleepEnginePreview(engine: scheduled.0, model: scheduled.1,
                                                                       why: "ruling 4")))
    }

    // MARK: The button (R-HS8)

    func testTheButtonNamesWhatACycleYouStartWouldRun() {
        XCTAssertEqual(EngineQuickMenuModel.buttonLabel(response(mode: "auto")), "Auto · Claude plan · sonnet")
        XCTAssertEqual(EngineQuickMenuModel.buttonLabel(response(mode: "agent", model: "haiku",
                                                                 manual: ("claude-cli", "haiku"))),
                       "Claude plan · haiku")
        XCTAssertEqual(EngineQuickMenuModel.buttonLabel(response(mode: "byok", manual: ("litellm", "example-model"))),
                       "API key · example-model")
        XCTAssertEqual(EngineQuickMenuModel.buttonLabel(response(mode: "codex", manual: ("codex-cli", "default model"))),
                       "ChatGPT plan · default model")
        XCTAssertNil(EngineQuickMenuModel.buttonLabel(nil), "R-A7 — a guessed engine is worse than silence")
        let noPreview = SleepEngineResponse(mode: "auto", model: "", disambiguationModel: "", source: "default",
                                            candidates: [], preview: nil)
        XCTAssertNil(EngineQuickMenuModel.buttonLabel(noPreview))
    }

    // MARK: The rows (R-HS7, DR-52)

    func testTheRowsAreTheFiveEnginesInTheServersOrderWithTheirMarks() {
        let model = EngineQuickMenuModel.from(response(mode: "agent"))
        XCTAssertEqual(model.rows.map(\.id), ["auto", "agent", "codex", "local", "byok"])
        XCTAssertEqual(model.rows.filter(\.isSelected).map(\.id), ["agent"])
        XCTAssertNotNil(model.rows.first { $0.id == "agent" }?.logo, "the Claude plan wears its real mark")
        XCTAssertNotNil(model.rows.first { $0.id == "codex" }?.logo, "the ChatGPT plan wears its real mark")
        XCTAssertEqual(model.rows.first { $0.id == "auto" }?.symbol, "sparkles")
        XCTAssertEqual(model.rows.first { $0.id == "byok" }?.symbol, "key.fill")
        XCTAssertEqual(model.rows.first { $0.id == "auto" }?.caption, "Picks for you")
    }

    /// R-E25 — a signed-out plan stays listed and says why; the current pick is never locked out.
    func testASignedOutPlanStaysListedAndSaysWhy() {
        let out = EngineQuickMenuModel.from(response(mode: "agent", codexSignedIn: false))
        let codex = out.rows.first { $0.id == "codex" }
        XCTAssertEqual(codex?.isSelectable, false)
        XCTAssertEqual(codex?.help, Copy.EngineMenu.signInFirst("ChatGPT plan"))
        let current = EngineQuickMenuModel.from(response(mode: "codex", codexSignedIn: false))
        XCTAssertEqual(current.rows.first { $0.id == "codex" }?.isSelectable, true)
    }

    // MARK: The model section (R-HS10)

    func testTheModelSectionFollowsTheChosenEngine() {
        let agent = EngineQuickMenuModel.from(response(mode: "agent"))
        XCTAssertEqual(agent.models, ["sonnet", "haiku", "opus"])
        XCTAssertEqual(agent.selectedModel, "sonnet")
        XCTAssertEqual(agent.modelLabel, Copy.EngineMenu.model)
        XCTAssertNil(agent.note)

        let auto = EngineQuickMenuModel.from(response(mode: "auto"))
        XCTAssertEqual(auto.models, [])
        XCTAssertEqual(auto.modelLabel, Copy.EngineMenu.howAutoPicks)
        XCTAssertEqual(auto.note, Self.autoDetail, "the backend's own words for the ladder")

        let key = EngineQuickMenuModel.from(response(mode: "byok", manual: ("litellm", "example-model")))
        XCTAssertEqual(key.note, Self.keyDetail)
        XCTAssertTrue(key.showsPlansAndKeysLink)

        let local = EngineQuickMenuModel.from(response(mode: "local", manual: ("ollama", "")))
        XCTAssertEqual(local.command, "brew install ollama", "the one command that fixes the current state")
        let ready = EngineQuickMenuModel.from(response(mode: "local", model: "example-local",
                                                       manual: ("ollama", "example-local"),
                                                       localModels: ["example-local"], localAvailable: true))
        XCTAssertNil(ready.command)
        XCTAssertEqual(ready.models, ["example-local"])
    }

    // MARK: Ruling 4 stays visible (R-HS11)

    func testBothPreviewsAlwaysShowAndTheRulingOnlyWhenTheyDiffer() {
        let differ = EngineQuickMenuModel.from(response(mode: "agent"))
        XCTAssertEqual(differ.previews.map(\.label), [Copy.EngineMenu.whenYouStart, Copy.EngineMenu.scheduledCycles])
        XCTAssertEqual(differ.previews.map(\.text),
                       ["\(Copy.engineLabel("claude-cli")) · sonnet", "\(Copy.engineLabel("litellm")) · example-model"])
        XCTAssertTrue(differ.showsRuling)
        let same = EngineQuickMenuModel.from(response(mode: "byok", manual: ("litellm", "example-model")))
        XCTAssertEqual(same.previews.count, 2, "both lines, always")
        XCTAssertFalse(same.showsRuling)
    }

    // MARK: One write rule (R-HS7)

    func testATapWritesThroughTheOneRule() {
        let r = response(mode: "auto")
        let byId = Dictionary(uniqueKeysWithValues: r.candidates.map { ($0.id, $0) })
        XCTAssertEqual(EngineWrite.choosing(byId["agent"]!, current: "auto"), EngineWrite(mode: "agent", model: "sonnet"))
        XCTAssertEqual(EngineWrite.choosing(byId["byok"]!, current: "auto"), EngineWrite(mode: "byok", model: nil))
        XCTAssertNil(EngineWrite.choosing(byId["auto"]!, current: "auto"), "the current engine writes nothing")
        let out = Dictionary(uniqueKeysWithValues: response(mode: "agent", codexSignedIn: false).candidates.map { ($0.id, $0) })
        XCTAssertNil(EngineWrite.choosing(out["codex"]!, current: "agent"), "a signed-out plan writes nothing")
        XCTAssertEqual(EngineWrite.model("haiku", mode: "agent", current: "sonnet"), EngineWrite(mode: "agent", model: "haiku"))
        XCTAssertNil(EngineWrite.model("sonnet", mode: "agent", current: "sonnet"))
        XCTAssertNil(EngineWrite.model("  ", mode: "agent", current: "sonnet"))
    }

    /// R-HS12 — the page reads the chooser's echo first, so a switch anywhere shows at once.
    func testThePageReadsTheChoosersPreviewFirst() {
        let chooser = response(mode: "agent")
        let page = SleepEnginePreviews(manual: SleepEnginePreview(engine: "litellm", model: "old", why: ""),
                                       scheduled: SleepEnginePreview(engine: "litellm", model: "old", why: ""))
        XCTAssertEqual(SleepEnginePreviewSource.current(chooser: chooser, page: page), chooser.preview)
        XCTAssertEqual(SleepEnginePreviewSource.current(chooser: nil, page: page), page)
        XCTAssertNil(SleepEnginePreviewSource.current(chooser: nil, page: nil))
    }

    /// A failed write says so in words and changes nothing; the next good one clears it
    /// (the old model never cleared `errorMessage`).
    func testAFailedWriteSaysSoAndTheNextOneClearsIt() async {
        struct Refused: Error {}
        var fail = true
        // Built here, on the main actor: the closures below are nonisolated, as the real ones are.
        let start = response(mode: "auto")
        let after = response(mode: "agent", model: "haiku", manual: ("claude-cli", "haiku"))
        let vm = SleepEngineViewModel(fetch: { start }, update: { _, _, _, _ in
            if fail { throw Refused() }
            return after
        })
        await vm.load()
        await vm.apply(EngineWrite(mode: "agent", model: "haiku"))
        XCTAssertTrue(vm.writeFailed)
        XCTAssertEqual(vm.response?.mode, "auto", "nothing changed")
        XCTAssertFalse(vm.isSaving)
        fail = false
        await vm.apply(EngineWrite(mode: "agent", model: "haiku"))
        XCTAssertFalse(vm.writeFailed)
        XCTAssertNil(vm.errorMessage)
        XCTAssertEqual(vm.response?.mode, "agent")
    }

    // MARK: Marks (R-HS13)

    func testEveryEngineWearsItsVendorsMark() {
        XCTAssertEqual(EngineMark.source(for: "claude-cli"), .origin("claude-code"))
        if case .logo = EngineMark.source(for: "codex-cli") {} else {
            XCTFail("the ChatGPT plan has a real mark — never the key (DR-52)")
        }
        XCTAssertEqual(EngineMark.source(for: "ollama"), .logo("ollama"))
        XCTAssertEqual(EngineMark.source(for: "litellm"), .symbol("key"))
    }

    // MARK: No price, ever (2026-09-03)

    func testNoPriceOrTokenAnywhereInTheMenu() {
        for r in [response(mode: "auto"), response(mode: "agent", codexSignedIn: false),
                  response(mode: "byok", manual: ("litellm", "example-model")), response(mode: "local")] {
            let m = EngineQuickMenuModel.from(r)
            let words = m.rows.flatMap { [$0.label, $0.caption, $0.help] } + m.previews.flatMap { [$0.label, $0.text] }
                + [m.modelLabel, m.note ?? "", EngineQuickMenuModel.buttonLabel(r) ?? ""]
            for w in words {
                for banned in ["$", "token", "price", "cost", "%"] {
                    XCTAssertFalse(w.lowercased().contains(banned), "\"\(w)\" contains \"\(banned)\"")
                }
            }
        }
    }

    // MARK: It fits its column (DR-70)

    /// Nothing in the menu is rigid: offered its width at every zoom and in both themes, it never asks
    /// for more (a rigid child — a long model tag, a fixed frame — is how a popover grows past its
    /// design). The menu is measured UNFRAMED, as `InboxFocusCardFitTests` measures the focus card:
    /// `EngineQuickMenuButton` applies the fixed width when it presents it, so a fixed frame here
    /// would make this assertion true by construction.
    func testTheMenuFitsItsWidthAtEveryZoomAndTheme() throws {
        // `LogoImage` (the rows' marks, `EngineMark`) reads the Store from the environment.
        let store = Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)), api: FakeSyncAPI())
        let long = "example-local-model-with-a-very-long-tag:8b-instruct-q4"
        let r = response(mode: "local", model: long, manual: ("ollama", long), localModels: [long], localAvailable: true)
        for mode in [AppColorScheme.dark, .light] {
            CicadaTheme.mode = mode
            for scale in [0.8, 1.0, 1.4] {
                CicadaTheme.uiScale = scale
                let width = EngineQuickMenu.width * CGFloat(scale)
                let renderer = ImageRenderer(content: EngineQuickMenu(model: .from(r), choose: { _ in },
                                                                      pickModel: { _ in }, openSettings: { _, _ in })
                    .environment(store))
                renderer.proposedSize = ProposedViewSize(width: width, height: nil)
                let size = try XCTUnwrap(renderer.nsImage).size
                XCTAssertLessThanOrEqual(size.width, width + 0.5, "\(mode) × \(scale) wants \(size.width)")
                XCTAssertGreaterThan(size.height, 80, "\(mode) × \(scale) rendered nothing")
            }
        }
    }

    // MARK: One write path (R-HS7)

    func testTheSleepPageWritesTheEngineOnlyThroughTheChoosersModel() throws {
        for file in try ThemeTokenTests.swiftSources() where file.path.contains("/Views/Sleep/") {
            let text = try String(contentsOf: file, encoding: .utf8)
            XCTAssertFalse(text.contains("updateSleepEngine("), "\(file.lastPathComponent) writes around the model")
            XCTAssertFalse(text.contains("\"/sleep/engine\""), file.lastPathComponent)
        }
        let menu = try XCTUnwrap(ThemeTokenTests.swiftSources().first { $0.path.hasSuffix("Views/Sleep/EngineQuickMenu.swift") })
        XCTAssertTrue(try String(contentsOf: menu, encoding: .utf8).contains("engineVM.apply("))
    }
}
```

Create `HomeSleepCopyTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// DR-59 over DS-3b's words: short labels, plain, sentence case, no "!", no bare "%", and no price,
/// token or "$" (the 2026-09-03 ruling). A new string joins `Copy.homeSleepLabels` or this lint
/// does not see it.
final class HomeSleepCopyTests: XCTestCase {
    func testDSThreeBCopyIsShortPlainAndPriceless() {
        XCTAssertGreaterThan(Copy.homeSleepLabels.count, 8, "a lint over nothing passes vacuously")
        for label in Copy.homeSleepLabels {
            XCTAssertLessThanOrEqual(label.count, 60, label)
            XCTAssertFalse(label.contains("!"), label)
            XCTAssertFalse(label.contains("$"), label)
            XCTAssertFalse(label.lowercased().contains("token"), label)
            XCTAssertFalse(label.contains("**"), "\(label) — no glob jargon (R-HS17)")
            XCTAssertEqual(label.first.map { String($0) }, label.first.map { String($0).uppercased() },
                           "\(label) — sentence case starts with a capital")
        }
    }
}
```

`RoomSentenceTests.swift:275-281` (the test and its two-line doc comment, which described the retired engine caption)
becomes:

```swift
    /// R-HS9 — the caption is what Cancel does while a cycle runs, and nothing otherwise: the
    /// engine menu beside the control names what a click would run.
    func test_controlCaption() {
        XCTAssertNil(controlCaption(isRunning: false), "R-HS9 — the engine menu names the engine")
        XCTAssertEqual(controlCaption(isRunning: true), Copy.cancelCaption)
    }
```

`SelectionTintLintTests.swift:7-8`: append `"Views/Sleep/EngineQuickMenu.swift"` to `scoped` (a chosen engine is a
check and a neutral fill, never the accent — DR-5).

Run: `cd <worktree>/app/CicadaApp && swift test --filter 'EngineQuickMenuTests|HomeSleepCopyTests|RoomSentenceTests|SelectionTintLintTests' 2>&1 | tail -20`
→ compile failure. That is the red.

- [ ] **Step 2: The words.** Create `Theme/Copy+HomeSleep.swift`:

```swift
import Foundation

/// Direction D, part 3b (DS-3b): the Sleep page's quick engine menu, Details, the Settings sheets
/// and the ⌘K Settings rows. Their own file for Track I's R-IA19 reason — sibling tracks append to
/// `Copy.swift`, and one file per track means two tracks never edit the same lines. Plain words, no
/// "!", no bare "%", no price or token count (DR-59, 2026-09-03); `HomeSleepCopyTests` holds every
/// string in `homeSleepLabels` to that.
extension Copy {
    /// The owner's quick switch (2026-09-23; R-HS7…R-HS11).
    enum EngineMenu {
        static let title = "Engine for the cycles you start"
        static let buttonHelp = "Engine and model for the cycles you start"
        static func buttonAccessibility(_ label: String) -> String { "\(title): \(label)" }
        static let model = "Model"
        static let howAutoPicks = "How Auto picks"
        /// R-HS11 — the one pair of preview labels, app-wide (the menu, Settings → Engines,
        /// Settings → Sleep). Three places said it two ways before.
        static let whenYouStart = "When you start a cycle"
        static let scheduledCycles = "Scheduled cycles"
        static let writeFailed = "Couldn't change the engine — nothing changed."
        static let moreInSettings = "More in Settings → Engines ›"
        static let plansAndKeys = "Plans & keys ›"
        static let autoPrefix = "Auto"
        static func signInFirst(_ label: String) -> String { "Sign in on Plans & keys to use your \(label)" }
    }

    /// Every DS-3b label `HomeSleepCopyTests` holds to DR-59. Later tasks append here.
    static let homeSleepLabels: [String] = [
        EngineMenu.title, EngineMenu.buttonHelp, EngineMenu.model, EngineMenu.howAutoPicks,
        EngineMenu.whenYouStart, EngineMenu.scheduledCycles, EngineMenu.writeFailed, EngineMenu.moreInSettings,
        EngineMenu.plansAndKeys, EngineMenu.signInFirst("ChatGPT plan"),
    ]
}
```

  Delete `Copy.whenYouStart` and `Copy.onTheSchedule` (`Copy+Settings.swift:48-49`).

- [ ] **Step 3: One write rule, one view model.**
  - `EngineOption.swift`: add `candidateId(forEngine:)` to `EngineOption` (below `previewMark`), and `EngineWrite`
    below the enum:

```swift
    /// The card a preview's engine belongs to — `previewMark`'s inverse — so a line that names what
    /// will run uses the card's own label ("Claude plan"), never a fresh coinage (R-HS8).
    static func candidateId(forEngine engine: String) -> String? {
        switch engine {
        case "claude-cli": "agent"
        case "codex-cli": "codex"
        case "ollama": "local"
        case "litellm": "byok"
        default: nil
        }
    }
```

```swift
/// R-HS7 — what a tap writes, as one rule shared by `EngineChooser`'s cards and the Sleep page's
/// quick menu, so the two surfaces can never write different things for the same tap.
struct EngineWrite: Equatable {
    let mode: String
    let model: String?

    /// A tap on another selectable engine writes it with its first model — the plan's own default
    /// first (R-E17); `nil` when it lists none (an API key's model lives on Plans & keys). A tap on
    /// the current engine, or on a plan that is not signed in (R-E25), writes nothing.
    static func choosing(_ candidate: SleepEngineCandidate, current: String) -> EngineWrite? {
        guard candidate.id != current, EngineOption.isSelectable(candidate, selectedMode: current) else { return nil }
        let first = candidate.models.first ?? ""
        return EngineWrite(mode: candidate.id, model: first.isEmpty ? nil : first)
    }

    /// A model pick on the chosen engine. The same model again, or a blank one, writes nothing.
    static func model(_ model: String, mode: String, current: String) -> EngineWrite? {
        let trimmed = model.trimmingCharacters(in: .whitespaces)
        guard !trimmed.isEmpty, trimmed != current else { return nil }
        return EngineWrite(mode: mode, model: trimmed)
    }
}
```

  - Replace `SleepEngineViewModel.swift`'s class body (keep and extend the docstring: injectable for the tests, the same
    shape as `SleepViewModel`'s `fetch…` closures; `writeFailed` is the menu's "nothing changed" line; a success clears
    `errorMessage`, which the old model never did — `LiveSetupEffects.saveEngine` still clears it first and reads it
    after, unchanged):

```swift
@Observable
@MainActor
final class SleepEngineViewModel {
    typealias Fetch = () async throws -> SleepEngineResponse
    typealias Update = (_ mode: String, _ model: String?, _ disambiguationModel: String?,
                        _ allowOverage: Bool?) async throws -> SleepEngineResponse

    var response: SleepEngineResponse?
    var errorMessage: String?
    /// A write is on the wire: the quick menu's rows wait, so two taps never race (R-HS7).
    private(set) var isSaving = false
    /// The last write failed and nothing changed — said in words, never a silent revert.
    private(set) var writeFailed = false

    private let fetch: Fetch
    private let update: Update

    init(fetch: @escaping Fetch = { try await APIClient.shared.fetchSleepEngine() },
         update: @escaping Update = { mode, model, disambiguation, overage in
             try await APIClient.shared.updateSleepEngine(mode: mode, model: model,
                                                           disambiguationModel: disambiguation,
                                                           allowOverage: overage)
         }) {
        self.fetch = fetch
        self.update = update
    }

    func load() async {
        do {
            response = try await fetch()
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    /// `allowOverage` (R-E13) defaults to nil — "leave the stored opt-in alone" — so a mode or model
    /// change never touches it by accident.
    func set(mode: String, model: String?, disambiguationModel: String?, allowOverage: Bool? = nil) async {
        isSaving = true
        defer { isSaving = false }
        do {
            response = try await update(mode, model, disambiguationModel, allowOverage)
            errorMessage = nil
            writeFailed = false
        } catch {
            errorMessage = error.localizedDescription
            writeFailed = true
        }
    }

    /// R-HS7 — the one door both surfaces write through.
    func apply(_ write: EngineWrite) async {
        await set(mode: write.mode, model: write.model, disambiguationModel: nil)
    }
}
```

  - `EngineChooser.swift`: `select(_:)` becomes

```swift
    private func select(_ candidate: SleepEngineCandidate) {
        guard let write = EngineWrite.choosing(candidate, current: selectedMode) else { return }
        selectedMode = write.mode
        selectedModel = write.model ?? ""
        commit(write)
    }
```

    `modelBinding(for:)`'s setter becomes
    `let write = EngineWrite.model(newValue, mode: candidate.id, current: selectedModel); selectedModel = newValue; if let write { commit(write) }`;
    the free-text field's `.onSubmit` becomes `commit(EngineWrite(mode: candidate.id, model: selectedModel))`;
    `commit(mode:model:)` becomes `commit(_ write: EngineWrite)` calling `await vm.apply(write)` then
    `await store.refresh([.connections])` (R-E24, unchanged). `previewSection`'s two labels become
    `Copy.EngineMenu.whenYouStart` / `Copy.EngineMenu.scheduledCycles` (R-HS11). Say so in `previewSection`'s comment.
  - `SettingsSleepView.swift:83-84`: the same two labels.

- [ ] **Step 4: The shared controls.**
  - `NeutralButton.swift`: add, right after `systemImage`, `var leading: AnyView? = nil` (a mark before the title — the
    engine menu's; `AnyView?` so every existing call site stays source-compatible, `PageHeader.leading`'s precedent) and
    `var trailingSystemImage: String? = nil` (a disclosure glyph after it). In the label's `HStack`: `leading` first, then
    the existing `systemImage`, then `Text(title).lineLimit(1).truncationMode(.tail)` (a fixed-height button never
    wraps), the key hint, then `Image(systemName: trailingSystemImage).font(CicadaTheme.icon(.inline)).foregroundStyle(CicadaTheme.textTertiary)`
    when set. Nothing else changes.
  - `ProgressiveColumns.swift:180-187` (`RowMetrics`): add
    `static let menuItem: CGFloat = 30   // a menu's item: the D-Sleep mock's engine rows (DR-34)`.

- [ ] **Step 5: The menu.** Create `Views/Sleep/EngineQuickMenu.swift`:

```swift
import SwiftUI

// The owner's request (2026-09-23): "in the mascot page there should be a quick and easy way to
// change which model to use for consolidation." DESIGN_RULES §10 (Sleep), §9 2026-09-23.

/// Every decision the quick menu makes, as a value (`EngineQuickMenuTests`), so its views render.
///
/// **One source of truth (R-HS7).** It is built from `SleepEngineViewModel.response` — the object
/// `EngineChooser` (Settings → Engines) reads, over the same `GET/PUT /sleep/engine` — and a tap
/// writes through the same rule (`EngineWrite`). No second pref, no Store domain (Track E's
/// ruling 6), and no price or token: the wire models it reads carry none (2026-09-03).
struct EngineQuickMenuModel: Equatable {
    /// One engine: its card's label and state caption (`EngineOption`, R-E25), its real mark
    /// (DR-52), and whether a tap can choose it — a signed-out plan stays listed and says why.
    struct Row: Equatable, Identifiable {
        let id: String
        let label: String
        let caption: String
        let logo: String?
        let symbol: String
        let isSelected: Bool
        let isSelectable: Bool
        let help: String
    }

    /// One of the two ruling-4 lines (R-HS11).
    struct Preview: Equatable {
        let label: String
        let engine: String
        let text: String
    }

    let rows: [Row]
    let modelLabel: String
    let models: [String]
    let selectedModel: String
    let note: String?
    let showsPlansAndKeysLink: Bool
    let command: String?
    let previews: [Preview]
    let showsRuling: Bool

    /// What the button says (R-HS8): the engine and model a cycle you start would run — the manual
    /// preview, in the card's own name — prefixed "Auto ·" while Auto is the choice. The retired
    /// "Runs on …" caption stated the same fact. `nil` until the preview is known (R-A7).
    static func buttonLabel(_ response: SleepEngineResponse?) -> String? {
        guard let response, let manual = response.preview?.manual else { return nil }
        let name = EngineOption.candidateId(forEngine: manual.engine)
            .flatMap { id in response.candidates.first { $0.id == id }?.label }
            ?? Copy.engineLabel(manual.engine)
        let runs = "\(name) · \(manual.model)"
        return response.mode == "auto" ? "\(Copy.EngineMenu.autoPrefix) · \(runs)" : runs
    }

    static func from(_ response: SleepEngineResponse) -> EngineQuickMenuModel {
        let current = response.mode
        let rows = response.candidates.map { candidate -> Row in
            let caption = EngineOption.caption(for: candidate)
            let selectable = EngineOption.isSelectable(candidate, selectedMode: current)
            return Row(id: candidate.id, label: candidate.label, caption: caption,
                       logo: EngineOption.logoName(for: candidate.id), symbol: EngineOption.symbol(for: candidate.id),
                       isSelected: candidate.id == current, isSelectable: selectable,
                       help: selectable ? "\(candidate.label) — \(caption)" : Copy.EngineMenu.signInFirst(candidate.label))
        }
        let chosen = response.candidates.first { $0.id == current }
        // R-HS10 — a model list only where the engine has one to pick from; Auto and the API key say
        // in the backend's own words how their model is decided.
        let pickable = ["agent", "codex", "local"].contains(current)
        let note: String? = (current == "auto" || current == "byok") ? chosen?.detail : nil
        let command = chosen.flatMap { $0.id == "local" ? OllamaGuideState.from(candidate: $0).command : nil }
        let previews: [Preview] = response.preview.map { p in
            [Preview(label: Copy.EngineMenu.whenYouStart, engine: p.manual.engine,
                     text: "\(Copy.engineLabel(p.manual.engine)) · \(p.manual.model)"),
             Preview(label: Copy.EngineMenu.scheduledCycles, engine: p.scheduled.engine,
                     text: "\(Copy.engineLabel(p.scheduled.engine)) · \(p.scheduled.model)")]
        } ?? []
        return EngineQuickMenuModel(
            rows: rows,
            modelLabel: current == "auto" ? Copy.EngineMenu.howAutoPicks : Copy.EngineMenu.model,
            models: pickable ? (chosen?.models ?? []) : [],
            selectedModel: response.model,
            note: note,
            showsPlansAndKeysLink: current == "byok",
            command: command,
            previews: previews,
            showsRuling: response.preview.map { $0.manual.engine != $0.scheduled.engine } ?? false)
    }
}

/// R-HS12 — one source for every engine line on the Sleep page: the chooser's response when it has
/// one (the echo of the newest write, from this menu or from Settings → Engines), else the page's
/// own load. Before this, a switch in Settings left the caption on the old engine until the next visit.
enum SleepEnginePreviewSource {
    static func current(chooser: SleepEngineResponse?, page: SleepEnginePreviews?) -> SleepEnginePreviews? {
        chooser?.preview ?? page
    }
}

/// The button beside Consolidate (R-HS8…R-HS10): a `NeutralButton` (DR-40) wearing the running
/// engine's mark, its name and model, and a disclosure glyph; it opens the menu below it. It owns
/// the menu's open state and the writes; `EngineQuickMenu` is a pure renderer.
struct EngineQuickMenuButton: View {
    @Environment(SleepEngineViewModel.self) private var engineVM
    @Environment(Store.self) private var store
    @Environment(AppRouter.self) private var router
    @State private var open = false

    var body: some View {
        if let response = engineVM.response, let label = EngineQuickMenuModel.buttonLabel(response) {
            NeutralButton(title: label,
                          leading: AnyView(EngineMark(engine: response.preview?.manual.engine ?? "",
                                                      size: CicadaTheme.scaled(14))),
                          trailingSystemImage: "chevron.down",
                          help: Copy.EngineMenu.buttonHelp) { open.toggle() }
                .frame(maxWidth: CicadaTheme.scaled(EngineQuickMenu.buttonMaxWidth))
                .accessibilityLabel(Copy.EngineMenu.buttonAccessibility(label))
                .popover(isPresented: $open, arrowEdge: .bottom) {
                    // The fixed width lives HERE, not in the menu, so `EngineQuickMenuTests`
                    // can measure the menu unframed and catch a rigid child (DR-70).
                    EngineQuickMenu(model: .from(response), isSaving: engineVM.isSaving,
                                    writeFailed: engineVM.writeFailed,
                                    choose: choose, pickModel: pickModel, openSettings: openSettings)
                        .frame(width: CicadaTheme.scaled(EngineQuickMenu.width), alignment: .leading)
                }
        }
    }

    private func choose(_ id: String) {
        guard let response = engineVM.response,
              let candidate = response.candidates.first(where: { $0.id == id }),
              let write = EngineWrite.choosing(candidate, current: response.mode) else { return }
        apply(write)
    }

    private func pickModel(_ model: String) {
        guard let response = engineVM.response,
              let write = EngineWrite.model(model, mode: response.mode, current: response.model) else { return }
        apply(write)
    }

    private func apply(_ write: EngineWrite) {
        Task { @MainActor in
            await engineVM.apply(write)
            // R-E24 — the Plans & keys line follows the chosen engine, as after EngineChooser's write.
            await store.refresh([.connections])
        }
    }

    /// The popover is its own window: it closes before the panel opens, or it would float over it.
    private func openSettings(_ section: SettingsSection, _ row: SettingsRowID?) {
        open = false
        router.openSettings(section, row: row)
    }
}

/// The menu (the D-Sleep mock's `role="menu"`): the five engines, the chosen one's model, a
/// write failure in words, both ruling-4 lines, and a way to the full chooser. A pure renderer of
/// `EngineQuickMenuModel`; selection is a check and a neutral fill, never the accent (DR-5). It
/// fills the width it is offered; the popover offers `width` (`EngineQuickMenuButton`).
struct EngineQuickMenu: View {
    static let width: CGFloat = 360
    static let buttonMaxWidth: CGFloat = 300

    let model: EngineQuickMenuModel
    var isSaving = false
    var writeFailed = false
    let choose: (String) -> Void
    let pickModel: (String) -> Void
    let openSettings: (SettingsSection, SettingsRowID?) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            SectionLabel(Copy.EngineMenu.title)
                .padding(.horizontal, CicadaTheme.spacingSM)
                .padding(.top, CicadaTheme.spacingSM)
                .padding(.bottom, CicadaTheme.spacingXS)
            ForEach(model.rows) { row in
                EngineMenuRow(row: row, isSaving: isSaving) { choose(row.id) }
            }
            modelSection
            if writeFailed {
                Text(Copy.EngineMenu.writeFailed)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .padding(.horizontal, CicadaTheme.spacingSM)
                    .padding(.top, CicadaTheme.spacingXS)
            }
            previewsSection
            HStack {
                Spacer(minLength: 0)
                InlineLink(title: Copy.EngineMenu.moreInSettings) { openSettings(.engines, .engineChoice) }
            }
            .padding(.horizontal, CicadaTheme.spacingSM)
            .padding(.vertical, CicadaTheme.spacingXS)
        }
        .padding(CicadaTheme.scaled(6))
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(CicadaTheme.bgMenu)
    }

    @ViewBuilder
    private var modelSection: some View {
        if !model.models.isEmpty || model.note != nil || model.command != nil {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                HStack(spacing: CicadaTheme.spacingSM) {
                    SectionLabel(model.modelLabel)
                    Spacer(minLength: CicadaTheme.spacingSM)
                    if !model.models.isEmpty {
                        // R-HS10 — a native menu picker: rosters are the plan's own list, any length.
                        Picker(model.modelLabel, selection: Binding(get: { model.selectedModel },
                                                                    set: { pickModel($0) })) {
                            ForEach(model.models, id: \.self) { Text($0).tag($0) }
                        }
                        .labelsHidden()
                        .pickerStyle(.menu)
                        // If the fit test shows the pop-up keeping its intrinsic width for a long
                        // tag, pin it with `.frame(width:)` at the same 220 — never widen the menu.
                        .frame(maxWidth: CicadaTheme.scaled(220), alignment: .trailing)
                        .disabled(isSaving)
                    }
                }
                if let note = model.note {
                    Text(note)
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                if model.showsPlansAndKeysLink {
                    InlineLink(title: Copy.EngineMenu.plansAndKeys) { openSettings(.plansAndKeys, nil) }
                }
                if let command = model.command {
                    CommandBox(command: command)
                }
            }
            .padding(.horizontal, CicadaTheme.spacingSM)
            .padding(.top, CicadaTheme.spacingSM)
        }
    }

    /// Ruling 4, visible (R-HS11): both lines always, each with its engine's mark; the sentence
    /// only when a scheduled cycle would run on something else.
    @ViewBuilder
    private var previewsSection: some View {
        if !model.previews.isEmpty {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                ForEach(model.previews, id: \.label) { preview in
                    VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                        SectionLabel(preview.label)
                        HStack(spacing: CicadaTheme.scaled(6)) {
                            EngineMark(engine: preview.engine, size: CicadaTheme.scaled(12))
                            Text(preview.text)
                                .font(CicadaTheme.metaFont)
                                .foregroundStyle(CicadaTheme.textSecondary)
                                .lineLimit(1)
                                .truncationMode(.tail)
                        }
                    }
                    .accessibilityElement(children: .combine)
                }
                if model.showsRuling {
                    Text(Copy.scheduledNeverSpendsPlans)
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .padding(.horizontal, CicadaTheme.spacingSM)
            .padding(.top, CicadaTheme.scaled(10))
            .padding(.bottom, CicadaTheme.spacingXS)
        }
    }
}

/// One engine (DR-48): its real mark (DR-52), the card's label, its state caption and a check on
/// the chosen one. A plan that is not signed in stays listed, dimmed, and says why in `.help`
/// (DR-41). Tertiary text on a fill steps to `textTertiaryOnFill` (DR-2).
private struct EngineMenuRow: View {
    let row: EngineQuickMenuModel.Row
    let isSaving: Bool
    let action: () -> Void
    @State private var hovering = false

    var body: some View {
        Button(action: action) {
            HStack(spacing: CicadaTheme.scaled(10)) {
                mark.frame(width: CicadaTheme.scaled(16), height: CicadaTheme.scaled(16))
                Text(row.label)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1)
                Spacer(minLength: CicadaTheme.spacingSM)
                Text(row.caption)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(row.isSelected || hovering ? CicadaTheme.textTertiaryOnFill : CicadaTheme.textTertiary)
                    .lineLimit(1)
                Image(systemName: "checkmark")
                    .font(CicadaTheme.icon(.inline))
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .opacity(row.isSelected ? 1 : 0)
                    .frame(width: CicadaTheme.scaled(14))
                    .accessibilityHidden(true)
            }
            .padding(.horizontal, CicadaTheme.spacingSM)
            .frame(height: CicadaTheme.scaled(RowMetrics.menuItem))
            .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall)
                .fill(row.isSelected ? CicadaTheme.bgSelected
                                     : (hovering && row.isSelectable ? CicadaTheme.bgHover : Color.clear)))
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .disabled(!row.isSelectable || isSaving)
        .opacity(row.isSelectable ? 1 : NeutralButton.disabledOpacity)
        .help(row.help)
        .onHover { hovering = $0 }
        .accessibilityLabel("\(row.label), \(row.caption)")
        .accessibilityAddTraits(row.isSelected ? [.isSelected] : [])
    }

    /// The bare mark at 16 pt, as the preview lines' `EngineMark` draws it — not a `platformTile`,
    /// whose 0.6 inset would shrink it to under 10 pt. Clipped to the tile ratio's curvature
    /// (Track L: an opaque raster is never recut, the surface clips it; a no-op for every mark
    /// whose corners are already transparent).
    @ViewBuilder
    private var mark: some View {
        if let logo = row.logo {
            LogoImage(name: logo, size: CicadaTheme.scaled(16))
                .clipShape(CicadaTheme.shape(CicadaTheme.scaled(16) * 0.2))
        } else {
            Image(systemName: row.symbol)
                .font(CicadaTheme.icon(.list))
                .foregroundStyle(CicadaTheme.textTertiary)
        }
    }
}
```

- [ ] **Step 6: Wire it into the page.**
  - `SleepHero.swift:418-426`: replace `controlCaption` (and its docstring) with

```swift
/// While a cycle runs, what Cancel does; otherwise nothing — the engine menu beside the control
/// names what a click would run (R-HS9), the fact the retired "Runs on …" caption stated, so
/// printing both would say it twice (DR-38).
func controlCaption(isRunning: Bool) -> String? {
    isRunning ? Copy.cancelCaption : nil
}
```

  - `SleepControlRow` (`:436-455`): drop the `manualEngine` property; the body becomes

```swift
    var body: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            if sleepVM.isRunning { cancelButton } else { consolidateButton }
            // The owner's quick switch (R-HS8, R-HS9). It stays while a cycle runs: a change
            // applies to the next one (G80).
            EngineQuickMenuButton()
            if let caption = controlCaption(isRunning: sleepVM.isRunning) {
                Text(caption)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
        }
        .frame(maxWidth: .infinity)
    }
```

    Update the type's docstring's last paragraph: the caption beside it is Cancel's while running; the engine is the
    menu's (R-HS9).
  - `EngineMark` (`:510-530`, with its doc comment): add `Source` and `source(for:)` and render through them:

```swift
    /// Which mark an engine wears (R-HS13): the Claude plan runs Claude Code's own binary, the ChatGPT
    /// plan wears its card's mark (`EngineOption.previewMark`), Ollama its own, and an API key — which
    /// has no vendor — a key. `codex-cli` drew the key before DS-3b (DR-52).
    enum Source: Equatable {
        case origin(String)
        case logo(String)
        case symbol(String)
    }

    static func source(for engine: String) -> Source {
        switch engine {
        case "claude-cli": .origin("claude-code")
        case "codex-cli": EngineOption.previewMark(engine: engine).map(Source.logo) ?? .symbol("key")
        case "ollama": .logo("ollama")
        default: .symbol("key")
        }
    }
```

    and `body` switches on `Self.source(for: engine)`: `.origin` → `OriginMark(origin:size:)`, `.logo` →
    `LogoImage(name:size:)`, `.symbol` → today's key glyph with that name.
  - `Copy.swift:158-164`: delete `runsOn(engine:)` and its doc comment (no reader remains — `rg -n 'runsOn\('
    app/CicadaApp` prints nothing) and, in `scheduledRunsOn`'s docstring (`:78-85`), replace "the Consolidate button's
    own subtitle (`runsOn(engine:)`)" with "the engine menu beside Consolidate (R-HS8)".
  - `SleepView.swift`: add `@Environment(SleepEngineViewModel.self) private var engineVM` beside `sleepVM`; in
    `resolvePage` (`:337`) pass
    `enginePreview: SleepEnginePreviewSource.current(chooser: engineVM.response, page: sleepVM.enginePreview)`; in
    `.task` (`:271-276`) after `await sleepVM.load()` add `await engineVM.load()` — unconditionally, with a comment:
    the chooser's response may have been loaded long before (Home's Getting started loads it at launch), and R-HS12
    reads it FIRST, so a stale one would hold the button, the lamp and the answers on an old engine; the GET is
    engine-free and `EngineChooser` re-syncs from `vm.response` (`onChange`), so a reload never stomps a choice. The
    `SleepControlRow` call (`:619-621`) drops `manualEngine:`.
  - `ViewModels/SleepViewModel.swift`: two comments still say `preview.manual` is "the Consolidate button's subtitle" —
    `enginePreview`'s docstring (`:48-55`) and the fifth-fetch comment (`:230-234`). Say instead that the engine menu
    beside Consolidate names it (R-HS8) and that this copy is the page's fallback source when the chooser has none
    (R-HS12). Comments only; no code in this file changes.
  - `LampPopover.swift`: add the same environment value and pass
    `SleepEnginePreviewSource.current(chooser: engineVM.response, page: sleepVM.enginePreview)` to `lampEngineLine`
    (`:74`).

- [ ] **Step 7: Green.** Run the filtered tests (green), then the full suite (0 failures). If
  `EngineCardTests`/`EnginesPageTests` read the retired labels, update them to `Copy.EngineMenu.*` — never the other
  way round.

- [ ] **Step 8: Commit.** Stage the files above only. Message:
  `feat(ds3b, g122, g125): the Sleep page's quick engine and model menu — the running engine's name and mark beside Consolidate, the five engines, the model, both previews; one write rule with Settings → Engines (DR-5, DR-38, DR-40, DR-41, DR-48, DR-52, DR-59, DR-69)`

---

### Task 3: Details in D's list grammar — labels over rows, no cards, "Rested" as a sentence (DR-2, DR-5, DR-7, DR-11, DR-16, DR-20, DR-21, DR-34, DR-35, DR-37, DR-47, DR-48, DR-52, DR-54, DR-58, DR-59; G125; R-HS15)

**Files:**
- Modify: `app/…/Views/Sleep/SleepDetails.swift`, `app/…/Views/Sleep/StudyListCard.swift:169-346`,
  `app/…/Views/Sleep/ConsolidationHistoryCard.swift:176-384`, `app/…/Views/Sleep/EpisodeRow.swift`,
  `app/…/Views/Sleep/SleepHero.swift:119-402`, `app/…/Views/Sleep/SleepView.swift:676-703`,
  `app/…/Views/Common/ProgressiveColumns.swift` (`RowMetrics.keyValue`), `app/…/Theme/Copy+HomeSleep.swift`,
  `app/…/Theme/Copy.swift:166-176, 190` (delete the tiles' nouns `entitiesInMemory`, `sourcesFeeding`, `lastCycle` — their
  one reader was `heroTiles`)
- Test: `Tests/CicadaAppTests/SleepDetailsTests.swift` (append), `SleepHeroTests.swift:208-250` (heroTiles →
  readoutRows; append meter sentences)

**Interfaces:**
- Produces `SleepDetailsSection(title:content:)`, `LastCycleRow` (`Kind`, `.rows(pageError:cancelled:capped:indexWarning:status:locale:)`),
  `HeroMeter.sentence(unprocessed:mood:)`, `ReadoutRow`, `readoutRows(entityCount:sourceCount:lastDurationMs:lastEngine:engineDetail:locale:)`,
  `EpisodeRowText.time(_:)` / `.meta(timestamp:processed:)`, `RowMetrics.keyValue`, `Copy.SleepDetailsWords.*`.
- Removes `HeroTile`, `heroTiles(…)` (replaced by `readoutRows`), the tiles' nouns (`Copy.entitiesInMemory`,
  `Copy.sourcesFeeding`, `Copy.lastCycle`) and `SleepHistoryPresentation.engineSymbol` — each left with no reader.
- Consumes `lastCycleSectionIsVisible` (unchanged), `heroMeter`, `heroMeterHelp`, `SleepHistoryPresentation`,
  `EngineMark` (Task 2), `UsageFormat.count`.

- [ ] **Step 1: Failing tests.** Append to `SleepDetailsTests.swift`:

```swift
    /// R-HS15 — Last cycle's four banners are rows in words, in the order the page always told them;
    /// a failure and a warning need the person (the `warning` glyph), a cancel and a cap do not.
    func test_lastCycleRowsSayWhatHappenedInWords() throws {
        let status = try JSONDecoder().decode(SleepStatusResponse.self, from: Data(Self.cappedStatusJSON.utf8))
        let rows = LastCycleRow.rows(pageError: "The local backend didn't answer.", cancelled: true, capped: true,
                                     indexWarning: "The vector index wasn't rebuilt.", status: status,
                                     locale: Locale(identifier: "en_US"))
        XCTAssertEqual(rows.map(\.kind), [.failed, .cancelled, .capped, .warning])
        XCTAssertEqual(rows.map(\.title), ["Sleep cycle error", "Cancelled", "Episode cap reached (2)",
                                           "Completed with warnings"])
        XCTAssertEqual(rows[1].text, "Stopped cleanly before any writes — nothing was lost.")
        XCTAssertEqual(rows[2].text, "2 of 3 processed — the rest stay queued for the next cycle.")
        XCTAssertEqual(rows.map(\.needsYou), [true, false, false, true])
    }

    func test_lastCycleRowsAppearExactlyWhenTheSectionDoes() throws {
        let status = try JSONDecoder().decode(SleepStatusResponse.self, from: Data(Self.cappedStatusJSON.utf8))
        for error in [nil, "boom"] as [String?] {
            for cancelled in [false, true] {
                for capped in [false, true] {
                    for warning in [nil, "", "w"] as [String?] {
                        let rows = LastCycleRow.rows(pageError: error, cancelled: cancelled, capped: capped,
                                                     indexWarning: warning, status: status)
                        XCTAssertEqual(!rows.isEmpty, lastCycleSectionIsVisible(pageError: error, cancelled: cancelled,
                                                                                capped: capped, indexWarning: warning))
                    }
                }
            }
        }
    }

    /// DR-37, DR-7 — Details carries no card and no tinted fill: labels over rows.
    func test_detailsIsRowsNotCards() throws {
        for name in ["SleepDetails.swift", "StudyListCard.swift", "ConsolidationHistoryCard.swift", "EpisodeRow.swift"] {
            let file = try XCTUnwrap(SleepNumbersLintTests.sleepSources().first { $0.lastPathComponent == name })
            let text = try String(contentsOf: file, encoding: .utf8)
            XCTAssertFalse(text.contains(".glassCard("), "\(name) — no card (DR-37)")
            for tint in ["danger.opacity(", "accent.opacity(", "warning.opacity(", "surfaceHover.opacity("] {
                XCTAssertFalse(text.contains(tint), "\(name) — \(tint) (DR-7)")
            }
        }
        let hero = try XCTUnwrap(SleepNumbersLintTests.sleepSources().first { $0.lastPathComponent == "SleepHero.swift" })
        let heroText = try String(contentsOf: hero, encoding: .utf8)
        XCTAssertEqual(heroText.components(separatedBy: ".glassCard(").count - 1, 0,
                       "the readout left its card too")
    }

    /// DR-48, DR-54 — an episode row's meta line: its time, and "read" once Sleep read it.
    func test_episodeRowMetaIsTheTimeAndWhetherItWasRead() {
        XCTAssertEqual(EpisodeRowText.time(""), "—")
        XCTAssertEqual(EpisodeRowText.time("not a date at all, longer than sixteen"), "not a date at al",
                       "the raw start (16 characters), never a blank")
        XCTAssertTrue(EpisodeRowText.meta(timestamp: "2026-08-30T14:02:00Z", processed: true).hasSuffix(" · read"))
        XCTAssertFalse(EpisodeRowText.meta(timestamp: "2026-08-30T14:02:00Z", processed: false).contains("read"))
    }

    private static let cappedStatusJSON = """
    {"status": "idle", "stage": 5, "episodesTotal": 2, "episodesQueued": 3, "episodeCap": 2, "cancelled": false}
    """
```

  `SleepStatusResponse.init(from:)` (`Services/APIClient.swift:755-782`) requires only `status` and defaults every other
  key, so this camelCase body decodes with a plain `JSONDecoder` (as `SleepPageModelTests.status(_:)` does).

  In `SleepHeroTests.swift`, replace the four `heroTiles` tests (`:208-250`) with:

```swift
    // MARK: readoutRows — R-A6's measured values as rows (R-HS15)

    func test_readoutRowsAreFourAndMeasured() {
        let en = Locale(identifier: "en_US")
        let rows = readoutRows(entityCount: 1_904, sourceCount: 6, lastDurationMs: 252_000, lastEngine: "claude-cli",
                               engineDetail: nil, locale: en)
        XCTAssertEqual(rows.map(\.key), ["In memory", "Feeding it", "Last cycle took", "Last engine"])
        XCTAssertEqual(rows.map(\.value), ["1,904 entities", "6 sources", "4 m 12 s", Copy.engineLabel("claude-cli")])
        XCTAssertTrue(rows.allSatisfy { $0.reason == nil }, "a real value carries no dash reason")
        XCTAssertEqual(rows.last?.engine, "claude-cli", "the engine row wears its mark (DR-52)")
        // de_DE, not es_ES: CLDR gives es_ES `minimumGroupingDigits = 2`, so Spanish leaves a
        // four-digit count ungrouped ("1904") — `SourcesV2Tests` records the same choice.
        XCTAssertEqual(readoutRows(entityCount: 1_904, sourceCount: 1, lastDurationMs: nil, lastEngine: nil,
                                   engineDetail: nil, locale: Locale(identifier: "de_DE")).first?.value,
                       "1.904 entities", "DR-21 — the reader's locale, never String(n)")
    }

    func test_readoutRowsUseADashWithAReasonForEveryUnknown() {
        for row in readoutRows(entityCount: nil, sourceCount: nil, lastDurationMs: nil, lastEngine: nil, engineDetail: nil) {
            XCTAssertEqual(row.value, "—", "\(row.key) invented a value it does not have")
            XCTAssertFalse((row.reason ?? "").isEmpty, "\(row.key): every dash names why")
        }
    }

    func test_readoutRowsPluraliseAndNeverForecast() {
        let one = readoutRows(entityCount: 1, sourceCount: 1, lastDurationMs: 900, lastEngine: "ollama",
                              engineDetail: "example-local", locale: Locale(identifier: "en_US"))
        XCTAssertEqual(one.map(\.value), ["1 entity", "1 source", "0 s", "\(Copy.engineLabel("ollama")) · example-local"])
        for row in one {
            let text = "\(row.key) \(row.value) \(row.reason ?? "")".lowercased()
            for banned in ["cluster", "insight", "estimate", "~", "$", "token"] {
                XCTAssertFalse(text.contains(banned), "\"\(text)\" contains \"\(banned)\"")
            }
        }
    }

    // MARK: The meter is a sentence (DESIGN_RULES §10, Sleep; R-HS15)

    func test_theRestedMeterIsASentence() {
        XCTAssertEqual(HeroMeter.rested(pct: 100).sentence(unprocessed: 0, mood: .happy),
                       "Fully rested — nothing is waiting.")
        XCTAssertEqual(HeroMeter.rested(pct: 0).sentence(unprocessed: 40, mood: .hungry),
                       "Rested 0% — the backlog is overdue.")
        XCTAssertEqual(HeroMeter.rested(pct: 40).sentence(unprocessed: 3, mood: .reading),
                       "Rested 40% — based on how much is waiting, and for how long.")
        XCTAssertEqual(HeroMeter.reading(read: 2, total: 3).sentence(unprocessed: 3, mood: .sleeping(stage: 1)),
                       "Read 2 of 3 so far.")
        for meter in [HeroMeter.rested(pct: 12), .rested(pct: 100), .reading(read: 1, total: 9)] {
            let s = meter.sentence(unprocessed: 5, mood: .awake)
            XCTAssertTrue(s.hasSuffix("."), s)
            XCTAssertTrue(s.hasPrefix("Rested") || s.hasPrefix("Read") || s.hasPrefix("Fully"), "\(s) — the noun first (R-A5)")
        }
    }
```

  Run: `cd <worktree>/app/CicadaApp && swift test --filter 'SleepDetailsTests|SleepHeroTests' 2>&1 | tail -20` → compile
  failure. That is the red.

- [ ] **Step 2: The words and the token.** Append to `Copy+HomeSleep.swift`, and add every label below to
  `homeSleepLabels` (the functions with sample arguments):

```swift
    /// Details (R-HS15): Last cycle's rows, the readout's keys, and the untitled episode.
    enum SleepDetailsWords {
        static let failedTitle = "Sleep cycle error"
        static let cancelledTitle = "Cancelled"
        static let cancelledText = "Stopped cleanly before any writes — nothing was lost."
        static func capTitle(_ cap: Int, locale: Locale = .autoupdatingCurrent) -> String {
            "Episode cap reached (\(UsageFormat.count(cap, locale: locale)))"
        }
        static func capText(processed: Int, queued: Int, locale: Locale = .autoupdatingCurrent) -> String {
            "\(UsageFormat.count(processed, locale: locale)) of \(UsageFormat.count(queued, locale: locale)) processed — the rest stay queued for the next cycle."
        }
        static let warningTitle = "Completed with warnings"
        static let inMemory = "In memory"
        static let feedingIt = "Feeding it"
        static let lastCycleTook = "Last cycle took"
        static let lastEngine = "Last engine"
        /// The engine row's dash reason. Not "Sleep hasn't run": `lastEngine` is also nil while the
        /// status is still loading and on an older backend, and a dash's reason is never a guess (R-A14).
        static let noEngineYet = "No cycle has reported its engine yet."
        static let untitled = "Untitled"
    }
```

  (`capText` is a sentence that passes 60 characters once its counts have four digits, so it stays off
  `homeSleepLabels`; list the other eleven, `capTitle` as `capTitle(2)`.) `ProgressiveColumns.swift` `RowMetrics`: add
  `static let keyValue: CGFloat = 32   // a key–value row: the D-Sleep mock's readout (DR-34)`.

- [ ] **Step 3: `SleepDetails.swift`.** Keep `lastCycleSectionIsVisible` and `SleepDetails`' fields and anchors;
  its `VStack` spacing becomes `CicadaTheme.spacingCard` (the mock's 28 between sections). Add
  `SleepDetailsSection` and `LastCycleRow`, and replace `LastCycleSection`'s body and its four banner functions
  (`:82-209`) with rows:

```swift
/// DR-20, DR-37, DR-47 — one Details section in D's list grammar (R-HS15): its `SectionLabel` over
/// rows, no card. Details was four glass cards with their labels inside; §10 (Sleep) asks for "rows
/// and section labels, no bordered cards".
struct SleepDetailsSection<Content: View>: View {
    let title: String
    @ViewBuilder let content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.scaled(6)) {
            SectionLabel(title)
                .padding(.horizontal, CicadaTheme.scaled(10))
            content
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// One line of Details › Last cycle (R-HS15): what happened, in the words the banners said, and a
/// glyph that says whether it needs the person — a failure or a warning in `warning`, a cancel or a
/// cap in `textTertiary`. The filled banners (`danger`/`accent`/`warning` at 10–12 %) retired: DR-7
/// keeps `danger` for destructive actions, and a row never sits on a tint.
struct LastCycleRow: Equatable, Identifiable {
    enum Kind: String, Equatable { case failed, cancelled, capped, warning }

    let kind: Kind
    let title: String
    let text: String
    var id: String { kind.rawValue }
    var needsYou: Bool { kind == .failed || kind == .warning }
    var glyph: String {
        switch kind {
        case .failed, .warning: "exclamationmark.triangle"
        case .cancelled: "stop.circle"
        case .capped: "tray.and.arrow.down"
        }
    }

    /// The four conditions `lastCycleSectionIsVisible` reads, in the page's order. The cap's numbers
    /// come from the status itself, as the banner's did (L1/L4).
    static func rows(pageError: String?, cancelled: Bool, capped: Bool, indexWarning: String?,
                     status: SleepStatusResponse?, locale: Locale = .autoupdatingCurrent) -> [LastCycleRow] {
        var rows: [LastCycleRow] = []
        if let pageError {
            rows.append(LastCycleRow(kind: .failed, title: Copy.SleepDetailsWords.failedTitle, text: pageError))
        }
        if cancelled {
            rows.append(LastCycleRow(kind: .cancelled, title: Copy.SleepDetailsWords.cancelledTitle,
                                     text: Copy.SleepDetailsWords.cancelledText))
        }
        if capped, let s = status {
            rows.append(LastCycleRow(kind: .capped, title: Copy.SleepDetailsWords.capTitle(s.episodeCap, locale: locale),
                                     text: Copy.SleepDetailsWords.capText(processed: s.episodesTotal,
                                                                          queued: s.episodesQueued, locale: locale)))
        }
        if let warning = indexWarning, !warning.isEmpty {
            rows.append(LastCycleRow(kind: .warning, title: Copy.SleepDetailsWords.warningTitle, text: warning))
        }
        return rows
    }
}
```

  `LastCycleSection.body` becomes `SleepDetailsSection(title: "Last cycle") { ForEach(LastCycleRow.rows(…)) { row in … } }`
  where each row is an `HStack(alignment: .top, spacing: scaled(10))` of the glyph (`icon(.list)`, `warning` when
  `needsYou` else `textTertiary`, `.padding(.top, scaled(2))`, `.accessibilityHidden(true)`), then a `VStack` of the
  title (`rowFont`, `textPrimary`) and the text (`bodyFont`, `textSecondary`, `.fixedSize(horizontal: false, vertical: true)`),
  padded `.horizontal scaled(10)` / `.vertical spacingSM`, `.accessibilityElement(children: .combine)`, and
  `.accessibilityAddTraits(row.needsYou ? .isStaticText : [])`. Keep the section's docstring and add R-HS15.

- [ ] **Step 4: What's waiting (`StudyListCard.swift`).**
  - `body` (`:169-188`): `SleepDetailsSection(title: "What's waiting") { content; <the error line> }` — drop
    `.padding(spacingLG)` and `.glassCard()`; the error line becomes `metaFont` in `textSecondary`, padded 10.
  - `content`: the loading and empty states are one 36 pt line (`.frame(minHeight: scaled(RowMetrics.oneLine))`, padded
    10). The failed state's glyph becomes `warning`, its Retry a compact `NeutralButton(title: "Retry", size: .compact)`
    with `.accessibilityLabel("Retry loading the queue")`. The rows' `LazyVStack` spacing becomes 0; an expanded origin's
    episodes are indented `scaled(35)` (the mock's 45 less the row's own 10).
  - `rowView` (`:239-279`): one 36 pt row — chevron (`icon(.inline)`, `textTertiary`), `OriginMark(origin:size: scaled(14))`,
    the label (`rowFont`, `textPrimary`), "oldest 3w" inline (`metaFont`, `textTertiary`), a `Spacer`, the trailing
    state — padded 10, `.frame(minHeight: scaled(RowMetrics.oneLine))`, the hover fill `bgHover` in
    `CicadaTheme.shape(cornerRadiusSmall)` (unchanged behaviour: `room?.hoveredOrigin`).
  - `countText` (`:325-329`): `metaFont`, `.monospacedDigit()`, `textSecondary` (no `.rounded` face). `trailing`'s
    (`:304-323`) counts go through `UsageFormat.count` — `countText(UsageFormat.count(count))` for waiting and
    `"\(UsageFormat.count(read)) / \(UsageFormat.count(total))"` for reading.
  - `microFill` (`:334-346`): the track `CicadaTheme.bgBadge`, the fill `CicadaTheme.textSecondary` (DR-5: progress is
    not an accent use; the stage strip already fills in the text ladder).

- [ ] **Step 5: Readout (`SleepHero.swift`).**
  - `HeroMeter` (`:119-151`): add, with the docstring below, and keep `label`, `fraction`, `filledBlocks` and
    `blockCount` (their tests stay):

```swift
    /// DESIGN_RULES §10 (Sleep): "'Rested 0%' becomes a sentence instead of 26 empty boxes" (R-HS15).
    /// The noun stays first (R-A5); the rest says what the number means from facts the page already
    /// holds — the queue's count and the mood — never a guess. The volume/age split stays on hover
    /// (`heroMeterHelp`).
    func sentence(unprocessed: Int, mood: BookwormState) -> String {
        switch self {
        case .reading(let read, let total):
            return "Read \(UsageFormat.count(read)) of \(UsageFormat.count(total)) so far."
        case .rested(let pct):
            if unprocessed == 0 { return "Fully rested — nothing is waiting." }
            if case .hungry = mood { return "Rested \(pct)% — the backlog is overdue." }
            return "Rested \(pct)% — based on how much is waiting, and for how long."
        }
    }
```

  - Replace `HeroTile` and `heroTiles` (`:179-226`) with:

```swift
/// Details › Readout as rows (R-HS15): R-A6's measured values — present tense, never a forecast —
/// and the last cycle's engine, each a key on the left and its value on the right, `—` with its
/// reason on hover for anything unknown (R-A14/P18). Counts go through `UsageFormat` (DR-21: the
/// tiles printed `String(n)`, so a German reader saw 1904, not 1.904). Every input is a Store domain
/// or `SleepPageModel` (P6).
struct ReadoutRow: Equatable, Identifiable {
    let id: String
    let key: String
    let value: String
    let reason: String?
    /// The engine the value names, for its mark (DR-52); nil on every other row.
    let engine: String?
}

func readoutRows(entityCount: Int?, sourceCount: Int?, lastDurationMs: Int?, lastEngine: String?,
                 engineDetail: String?, locale: Locale = .autoupdatingCurrent) -> [ReadoutRow] {
    let entities = entityCount.map { "\(UsageFormat.count($0, locale: locale)) \($0 == 1 ? "entity" : "entities")" }
    let sources = sourceCount.map { "\(UsageFormat.count($0, locale: locale)) \($0 == 1 ? "source" : "sources")" }
    let engine = lastEngine.map { id in
        ([Copy.engineLabel(id)] + [engineDetail].compactMap { $0 }.filter { !$0.isEmpty }).joined(separator: " · ")
    }
    return [
        ReadoutRow(id: "entities", key: Copy.SleepDetailsWords.inMemory, value: entities ?? "—",
                   reason: entityCount == nil ? Copy.bankListNotLoaded : nil, engine: nil),
        ReadoutRow(id: "sources", key: Copy.SleepDetailsWords.feedingIt, value: sources ?? "—",
                   reason: sourceCount == nil ? Copy.sourceOverviewNotLoaded : nil, engine: nil),
        ReadoutRow(id: "lastCycle", key: Copy.SleepDetailsWords.lastCycleTook,
                   value: SleepHistoryPresentation.durationText(ms: lastDurationMs),
                   reason: lastDurationMs == nil ? Copy.noTimingRecorded : nil, engine: nil),
        ReadoutRow(id: "engine", key: Copy.SleepDetailsWords.lastEngine, value: engine ?? "—",
                   reason: lastEngine == nil ? Copy.SleepDetailsWords.noEngineYet : nil, engine: lastEngine),
    ]
}
```

  - `SleepReadoutView.body` (`:267-283`) becomes `SleepDetailsSection(title: "Readout") { … }`: when
    `heroMeter(mood: mood, debt: debt, read: read, total: total)` returns a meter, its
    `meter.sentence(unprocessed: debt?.unprocessedCount ?? 0, mood: mood)` (`detailBodyFont`, `textSecondary`,
    `.help(heroMeterHelp(meter, debt: debt) ?? "")`, padded 10 / top 6 / bottom 8, `.accessibilityLabel` = the sentence
    plus the breakdown joined with " — ", as the meter's label is today) — a `.rested` meter only exists when `debt`
    does, so the `?? 0` never speaks — else `noBaselineLine` (padded 10); then `ForEach(readoutRows(entityCount:
    activeBankEntityCount, sourceCount: feedingSourceCount, lastDurationMs: lastDurationMs, lastEngine: lastEngine,
    engineDetail: engineDetail)) { readoutRow($0) }`. Delete `meterView`, `tilesRow` and `engineLine` (their facts are
    the sentence and the rows now); keep `noBaselineLine` and the two count properties. Delete `Copy.entitiesInMemory`,
    `Copy.sourcesFeeding` (with their shared doc comment) and `Copy.lastCycle` from `Theme/Copy.swift` (`:166-176`,
    `:190`): `heroTiles` was their only reader. `readoutRow`:

```swift
    /// A key–value row (DR-34: `RowMetrics.keyValue`): the key in `textTertiary`, the engine's mark
    /// when the row names one, the value in 13 medium, tabular.
    private func readoutRow(_ row: ReadoutRow) -> some View {
        HStack(spacing: CicadaTheme.spacingMD) {
            Text(row.key)
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .frame(width: CicadaTheme.scaled(150), alignment: .leading)
            if let engine = row.engine { EngineMark(engine: engine, size: CicadaTheme.scaled(12)) }
            Text(row.value)
                .font(CicadaTheme.rowFont)
                .monospacedDigit()
                .foregroundStyle(CicadaTheme.textPrimary)
                .lineLimit(2)
            Spacer(minLength: 0)
        }
        .padding(.horizontal, CicadaTheme.scaled(10))
        .frame(minHeight: CicadaTheme.scaled(RowMetrics.keyValue))
        .help(row.reason ?? "")
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(row.key), \(row.value)\(row.reason.map { " — \($0)" } ?? "")")
    }
```

  `SleepMotion.settle`'s use by the deleted `meterView` goes with it; if `reduceMotion` is then unused in
  `SleepReadoutView`, delete that property.

- [ ] **Step 6: Past nights (`ConsolidationHistoryCard.swift`).** `body` becomes
  `SleepDetailsSection(title: "Past nights") { … }` with "Nothing consolidated yet." as one 36 pt line and the rows in a
  `LazyVStack(spacing: 0)`. Extract today's `row(_:)` into `private struct PastNightRow: View` (it needs its own
  `@State hovering`) drawn as one row of at least 36 pt: the date (`metaFont`, `textSecondary`, tabular, width
  `scaled(48)`), the time (`metaFont`, `textTertiary`, tabular, width `scaled(60)`) side by side (the mock), the headline
  (`ViewThatFits`, unchanged, `bodyFont`), then — whenever `SleepHistoryPresentation.enginePill(entry)` is non-nil (it
  is also set for an author-only commit with no engine) — the pill's words (`metaFont`, `textTertiary`, one line,
  `maxWidth scaled(250)`), preceded by `EngineMark(engine:size: scaled(12))` only when `entry.engine` is set; the
  duration (`metaFont`, `textTertiary`, tabular, width `scaled(52)`, trailing, `.help` unchanged), and the chevron
  (`icon(.inline)`, `textTertiary`, width `scaled(28)`); padded leading 10 / trailing 4, hover `bgHover`. The row keeps
  its `Button { onToggle(entry.commitHash) }` and `.accessibilityLabel(ConsolidationHistoryCard.rowAccessibilityLabel(entry))`
  (so `PastNightRow` takes `entry`, `isExpanded` and `onToggle`). The expanded detail is indented `scaled(142)` leading
  and `scaled(40)` trailing (the mock); its entity buttons use `accentText` (DR-5 use 5); its counts (`"\(count)"`, the
  conversations line and the inbox line) go through `UsageFormat.count`. The decay row keeps its muted tone. Delete
  `SleepHistoryPresentation.engineSymbol` (`:153-160`): the pill's cpu/key glyph was its only reader, and `EngineMark`
  replaces it (DR-52 — an engine wears its real mark). The rest of `SleepHistoryPresentation` is unchanged.

- [ ] **Step 7: `EpisodeRow.swift`.** Replace the body; keep the timestamp parsing as `EpisodeRowText`:

```swift
/// A queued or read episode's words, pure (`SleepDetailsTests`).
enum EpisodeRowText {
    /// "Nov 3, 2026 14:02" — the year kept (a queue can span years after a bulk import); "—" for an
    /// empty stamp; the raw start of anything that does not parse, rather than a blank.
    static func time(_ raw: String) -> String {
        guard !raw.isEmpty else { return "—" }
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = formatter.date(from: raw) { return display.string(from: date) }
        formatter.formatOptions = [.withInternetDateTime]
        if let date = formatter.date(from: raw) { return display.string(from: date) }
        return String(raw.prefix(16))
    }

    /// The meta line: the time, and "read" once Sleep read it — the fact the status dot carried.
    static func meta(timestamp: String, processed: Bool) -> String {
        processed ? "\(time(timestamp)) · read" : time(timestamp)
    }

    private static let display: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "MMM d, yyyy HH:mm"
        return f
    }()
}

/// One queued or read episode (DR-48): the source's real mark (DR-52), the title, a meta line and a
/// two-line preview. A row carries one glyph, so the status dot left — "read" is in the meta line.
/// The source pill left too: the origin row above it and the spine's header already name the source
/// (DR-38), and a raw origin slug never sits at body weight (DR-54); the id is on hover. Hover is a
/// fill, never a lift.
struct EpisodeRow: View {
    let item: EpisodeQueueItem
    @State private var hovering = false

    var body: some View {
        HStack(alignment: .top, spacing: CicadaTheme.scaled(10)) {
            OriginMark(origin: item.origin, size: CicadaTheme.scaled(14))
                .padding(.top, CicadaTheme.scaled(2))
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                Text(item.title ?? Copy.SleepDetailsWords.untitled)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(item.processed ? CicadaTheme.textTertiary : CicadaTheme.textSecondary)
                    .lineLimit(1)
                Text(EpisodeRowText.meta(timestamp: item.timestamp, processed: item.processed))
                    .font(CicadaTheme.metaFont)
                    .monospacedDigit()
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .lineLimit(1)
                if !item.preview.isEmpty {
                    Text(item.preview)
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .lineLimit(2)
                }
            }
            Spacer(minLength: 0)
        }
        .padding(.horizontal, CicadaTheme.scaled(10))
        .padding(.vertical, CicadaTheme.spacingSM)
        .frame(minHeight: CicadaTheme.scaled(RowMetrics.twoLine), alignment: .topLeading)
        .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall)
            .fill(hovering ? CicadaTheme.bgHover : Color.clear))
        .onHover { hovering = $0 }
        .help(item.id)
    }
}
```

- [ ] **Step 8: The Details row** (`DetailsDisclosureRow`, `SleepView.swift:686-691`): the title's
  `CicadaTheme.font(size: 13, weight: .semibold)` (`:691`) → `CicadaTheme.rowFont` (13 medium, DR-16); the chevron's
  `CicadaTheme.font(size: 10, weight: .semibold)` (`:687`) → `CicadaTheme.icon(.inline)`.

- [ ] **Step 9: Green.** Filtered tests, then the full suite: `SleepNumbersLintTests` (the `%` nouns, "Rested" in
  `SleepHero.swift` only, no literal durations), `FixWaveTests`, `SleepMeadowTests` (one `PrimaryActionButton` under
  `Views/Sleep`), `SectionLabelLintTests` (still more than ten literal labels app-wide) and `SleepDetailsTests` must all
  stay green. `rg -n 'heroTiles|HeroTile\b|entitiesInMemory|sourcesFeeding|engineSymbol' <worktree>/app/CicadaApp`
  prints nothing.

- [ ] **Step 10: Commit.** Stage the files above only. Message:
  `feat(ds3b, g125): Sleep Details in D's list grammar — labels over rows, no cards, Rested as a sentence, the readout as key–value rows, one glyph per episode (DR-2, DR-5, DR-7, DR-11, DR-16, DR-20, DR-21, DR-34, DR-35, DR-37, DR-47, DR-48, DR-52, DR-54)`

---

### Task 4: The Settings panel's Integrations fixes — labelled add-folder sheet, a subfolder picker, real harness marks, sheets that stay on screen (DR-33, DR-40, DR-52, DR-54, DR-59; G126, G133; R-HS16…R-HS18)

**Files:**
- Create: `app/…/Services/LocalSources/AgentFolders.swift`, `app/…/Views/Settings/SettingsSheet.swift`
- Modify: `app/…/Views/Settings/LocalSourceRows.swift:50-462`, `app/…/Views/Settings/IntegrationsView.swift:198-409`,
  `app/…/Services/LocalSources/LocalSourceWatcher.swift` (two methods), `app/…/Models/IntegrationCategory.swift:73-84`,
  `app/…/Theme/Copy+HomeSleep.swift`
- Test: `Tests/CicadaAppTests/AgentFoldersTests.swift` (new), `SettingsSheetLintTests.swift` (new),
  `IntegrationsViewTests.swift` (append)

**Interfaces:**
- Produces `AgentFolderRow` (`Kind`, `glob`, `title`), `AgentFolders` (`defaultOn`, `glob(forSubfolder:)`,
  `subfolder(fromGlob:)`, `initialRows(subfolders:)`, `rows(subfolders:globs:)`, `globs(_:)`, `adding(_:to:)`,
  `relativePath(of:under:)`, `subfolders(in:fileManager:)`); `SettingsSheet(title:onClose:content:)`;
  `AgentFolderPicker`; `LocalSourceWatcher.subfolders(of:)`, `.root(of:)`;
  `IntegrationHarnessRows.markOrigin(for:)`, `.otherAgentsSymbol`; `Copy.Folders.*`, `Copy.sheetClose`.
- Consumes `FolderGlob.matches(_:_:)`, `FolderRegistration.agentGlobs`, `LocalSourceWatcher.addFolder/preview/
  startWatching/removeFolder/updateAgentGlobs/setWispr` (unchanged), `OriginIconography.logoName/appBundleId`,
  `OriginMark`, `IconButton`, `TextButton`.

- [ ] **Step 1: Failing tests.** Create `AgentFoldersTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// R-HS17 — "Written by an agent" in plain words. The wire stays a glob; the rule between a
/// checkbox and a glob is held to `FolderGlob`, the backend matcher's twin (G133).
final class AgentFoldersTests: XCTestCase {
    func testAFolderIsTheWholeSubtreeBelowIt() {
        let glob = AgentFolders.glob(forSubfolder: "research")
        XCTAssertEqual(glob, "research/**")
        XCTAssertTrue(FolderGlob.matches(glob, "research/plan.md"))
        XCTAssertTrue(FolderGlob.matches(glob, "research/2026/sweep.md"))
        XCTAssertFalse(FolderGlob.matches(glob, "researcher/plan.md"))
        XCTAssertFalse(FolderGlob.matches(glob, "notes/research/plan.md"))
        XCTAssertEqual(AgentFolders.glob(forSubfolder: "/research/deep/"), "research/deep/**", "trimmed of slashes")
    }

    func testOnlyAOneFolderRuleReadsBackAsAFolder() {
        XCTAssertEqual(AgentFolders.subfolder(fromGlob: "research/**"), "research")
        XCTAssertEqual(AgentFolders.subfolder(fromGlob: "research/deep/**"), "research/deep")
        for rule in ["**/*.md", "*.draft.md", "research/*", "docs/?.md", "/**", "**"] {
            XCTAssertNil(AgentFolders.subfolder(fromGlob: rule), rule)
        }
    }

    /// A new folder: one row per subfolder, "archive" ticked only when it exists — the old default
    /// glob's effect, exactly (it matched nothing without an archive folder).
    func testANewFolderPreTicksArchiveOnlyWhenItExists() {
        let rows = AgentFolders.initialRows(subfolders: ["archive", "drafts", "research"])
        XCTAssertEqual(rows.map(\.title), ["Files in archive (and its subfolders)", "Files in drafts (and its subfolders)",
                                           "Files in research (and its subfolders)"])
        XCTAssertEqual(AgentFolders.globs(rows), ["archive/**"])
        XCTAssertEqual(AgentFolders.globs(AgentFolders.initialRows(subfolders: ["drafts"])), [])
        XCTAssertTrue(rows.allSatisfy { !$0.title.contains("**") }, "no glob jargon on screen")
    }

    /// Manage: every saved rule survives a round trip — a folder that moved or sits deeper keeps
    /// its row, and a rule that is not one folder stays verbatim.
    func testASavedRuleIsNeverDropped() {
        let globs = ["research/**", "deep/inside/**", "*.draft.md"]
        let rows = AgentFolders.rows(subfolders: ["drafts", "research"], globs: globs)
        XCTAssertEqual(rows.map(\.title), ["Files in drafts (and its subfolders)", "Files in research (and its subfolders)",
                                           "Files in deep/inside (and its subfolders)", "Files matching *.draft.md"])
        XCTAssertEqual(rows.map(\.isOn), [false, true, true, true])
        XCTAssertEqual(Set(AgentFolders.globs(rows)), Set(globs))
    }

    func testAPickedSubfolderIsTickedOrAdded() {
        let rows = AgentFolders.initialRows(subfolders: ["drafts"])
        XCTAssertEqual(AgentFolders.globs(AgentFolders.adding("drafts", to: rows)), ["drafts/**"])
        let added = AgentFolders.adding("drafts/agent-sweeps", to: rows)
        XCTAssertEqual(added.count, 2)
        XCTAssertEqual(AgentFolders.globs(added), ["drafts/agent-sweeps/**"])
    }

    func testAPickMustBeInsideTheFolder() {
        let root = URL(fileURLWithPath: "/tmp/example-notes")
        XCTAssertEqual(AgentFolders.relativePath(of: root.appendingPathComponent("research/deep"), under: root),
                       "research/deep")
        XCTAssertNil(AgentFolders.relativePath(of: root, under: root), "the folder itself is not a subfolder")
        XCTAssertNil(AgentFolders.relativePath(of: URL(fileURLWithPath: "/tmp/elsewhere"), under: root))
        XCTAssertNil(AgentFolders.relativePath(of: URL(fileURLWithPath: "/tmp/example-notes-2/x"), under: root))
    }

    /// The app reads the folder (G133): directories only, hidden ones skipped, in Finder's order.
    func testTheFolderIsListedByTheApp() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        for dir in ["research", "Archive", ".git", "drafts"] {
            try FileManager.default.createDirectory(at: root.appendingPathComponent(dir), withIntermediateDirectories: true)
        }
        try Data("x".utf8).write(to: root.appendingPathComponent("notes.md"))
        defer { try? FileManager.default.removeItem(at: root) }
        XCTAssertEqual(AgentFolders.subfolders(in: root), ["Archive", "drafts", "research"])
        XCTAssertEqual(AgentFolders.subfolders(in: root.appendingPathComponent("missing")), [])
    }
}
```

  Create `SettingsSheetLintTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// R-HS16 — Settings raises sheets, never popovers. The panel is modal and inset 40 pt, so a
/// popover anchored to a row near its edge could open past the screen (owner-reported: Manage).
/// AppKit centres a sheet on its window.
final class SettingsSheetLintTests: XCTestCase {
    private func source(_ suffix: String) throws -> String {
        let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first { $0.path.hasSuffix(suffix) }, suffix)
        return try String(contentsOf: file, encoding: .utf8)
    }

    func testNothingUnderSettingsRaisesAPopover() throws {
        var offenders: [String] = []
        for file in try ThemeTokenTests.swiftSources() where file.path.contains("/Views/Settings/") {
            let lines = try String(contentsOf: file, encoding: .utf8).components(separatedBy: .newlines)
            for (i, line) in lines.enumerated()
            where !line.trimmingCharacters(in: .whitespaces).hasPrefix("//") && line.contains(".popover(") {
                offenders.append("\(file.lastPathComponent):\(i + 1)")
            }
        }
        XCTAssertEqual(offenders, [])
    }

    func testEveryManageAndConnectIsASettingsSheet() throws {
        for suffix in ["Views/Settings/LocalSourceRows.swift", "Views/Settings/IntegrationsView.swift"] {
            let text = try source(suffix)
            XCTAssertTrue(text.contains(".sheet("), suffix)
            XCTAssertTrue(text.contains("SettingsSheet("), suffix)
        }
    }

    /// The owner's report: labels, not placeholders, and no glob typed by hand.
    func testTheAddFolderSheetHasLabelsAndNoGlobField() throws {
        let text = try source("Views/Settings/LocalSourceRows.swift")
        XCTAssertFalse(text.contains("\"archive/**\""), "the default is a pre-ticked folder, not a typed glob")
        XCTAssertFalse(text.contains("TextField(\"Parts written by an agent\""))
        XCTAssertTrue(text.contains("AgentFolderPicker("))
        XCTAssertTrue(text.contains("LabeledField("))
    }
}
```

  Append to `IntegrationsViewTests.swift`:

```swift
    /// DR-52, R-HS18 — a harness row wears its app's real mark; "Other agents" has no vendor and
    /// wears a neutral glyph, never a "?" and never a chat bubble in a tinted circle.
    func testHarnessRowsWearTheirRealMarks() {
        func row(_ harness: String) -> SourceOverview {
            SourceOverview(id: "harness:\(harness)", label: harness, kind: .harness, mark: harness, harness: harness)
        }
        XCTAssertEqual(IntegrationHarnessRows.markOrigin(for: row("claude-code")), "claude-code")
        XCTAssertEqual(IntegrationHarnessRows.markOrigin(for: row("codex")), "codex")
        XCTAssertEqual(IntegrationHarnessRows.markOrigin(for: row("cursor")), "cursor")
        XCTAssertNil(IntegrationHarnessRows.markOrigin(for: row("unknown")))
        XCTAssertNotEqual(IntegrationHarnessRows.otherAgentsSymbol, "questionmark.circle")
        XCTAssertNotEqual(IntegrationHarnessRows.otherAgentsSymbol, "bubble.left.and.bubble.right")
    }
```

  (`SourceOverview.init` — `Models/SourceOverview.swift:40-50` — takes `mark:` before `harness:`, every other argument
  defaulted.)

  Run: `cd <worktree>/app/CicadaApp && swift test --filter 'AgentFoldersTests|SettingsSheetLintTests|IntegrationsViewTests' 2>&1 | tail -20`
  → compile failure / lint red. That is the red.

- [ ] **Step 2: The words.** Append to `Copy+HomeSleep.swift`, and add each label to `homeSleepLabels` (functions with
  "research" / "*.draft.md" / "example-notes" as arguments; `writtenByAnAgentHelp`, `noSubfolders` and `manageHelp` are
  sentences over 60 characters — leave those three out of the list):

```swift
    /// The add-folder and Manage sheets (the owner's report; R-HS17).
    enum Folders {
        static let addTitle = "Add a folder"
        static let name = "Name"
        static let project = "Project"
        static let projectHelp = "Notes from this folder are kept under this project."
        static let writtenByAnAgent = "Written by an agent"
        static let writtenByAnAgentHelp =
            "Research an agent wrote for you is kept and searchable, but never counted as your own words."
        static func filesIn(_ folder: String) -> String { "Files in \(folder) (and its subfolders)" }
        static func filesMatching(_ rule: String) -> String { "Files matching \(rule)" }
        static let noSubfolders = "No subfolders here — everything in this folder counts as yours."
        static let chooseSubfolder = "Choose a subfolder…"
        static func pickInside(_ folder: String) -> String { "Pick a folder inside \(folder)." }
        static let manageHelp = "Changing this re-reads the folder so every file is credited to the right author."
    }
    /// A Settings sheet's close × (R-HS16).
    static let sheetClose = "Close"
```

  (`filesMatching` renders a saved rule verbatim — the one place a glob can appear, and only if the person typed one
  before DS-3b; `HomeSleepCopyTests`' `**` check runs over the listed sample, `"*.draft.md"`.)

- [ ] **Step 3: `AgentFolders.swift`.**

```swift
import Foundation

/// One line of the "Written by an agent" checklist (R-HS17).
struct AgentFolderRow: Identifiable, Equatable {
    enum Kind: Equatable {
        /// A subfolder, relative to the watched folder: everything below it.
        case folder(String)
        /// A saved rule that is not one folder, kept verbatim so a round trip never drops it.
        case other(String)
    }

    let kind: Kind
    var isOn: Bool

    var glob: String {
        switch kind {
        case .folder(let path): AgentFolders.glob(forSubfolder: path)
        case .other(let rule): rule
        }
    }

    var id: String { glob }

    var title: String {
        switch kind {
        case .folder(let path): Copy.Folders.filesIn(path)
        case .other(let rule): Copy.Folders.filesMatching(rule)
        }
    }
}

/// "Written by an agent" as folders, not globs (the owner's report; R-HS17, G133 R-F2). The wire is
/// unchanged — `FolderAuthorshipRule(glob:authorship: "agent")` — and `<folder>/**` is the glob
/// `FolderGlob` (the backend matcher's twin) matches for everything below that folder. The app reads
/// the folder to list it; the backend never opens it (G133).
enum AgentFolders {
    /// The old default glob was `archive/**`: it is a pre-ticked row when the folder has one, and
    /// nothing when it does not — exactly what the glob matched.
    static let defaultOn: Set<String> = ["archive"]

    static func glob(forSubfolder path: String) -> String {
        path.trimmingCharacters(in: CharacterSet(charactersIn: "/")) + "/**"
    }

    /// The inverse, for Manage: `research/**` → `research`; nil for anything that is not one folder.
    static func subfolder(fromGlob glob: String) -> String? {
        guard glob.hasSuffix("/**") else { return nil }
        let path = String(glob.dropLast(3))
        guard !path.isEmpty, !path.hasPrefix("/"), !path.contains("*"), !path.contains("?") else { return nil }
        return path
    }

    static func initialRows(subfolders: [String]) -> [AgentFolderRow] {
        subfolders.map { AgentFolderRow(kind: .folder($0), isOn: defaultOn.contains($0)) }
    }

    /// Manage's rows: one per subfolder on disk, ticked when a rule names it; then a row for each
    /// saved folder rule not on that list (deeper, or moved); then every other rule, verbatim.
    static func rows(subfolders: [String], globs: [String]) -> [AgentFolderRow] {
        let named = Set(globs.compactMap(subfolder(fromGlob:)))
        var rows = subfolders.map { AgentFolderRow(kind: .folder($0), isOn: named.contains($0)) }
        let listed = Set(subfolders)
        for rule in globs {
            if let path = subfolder(fromGlob: rule) {
                if !listed.contains(path) { rows.append(AgentFolderRow(kind: .folder(path), isOn: true)) }
            } else {
                rows.append(AgentFolderRow(kind: .other(rule), isOn: true))
            }
        }
        return rows
    }

    static func globs(_ rows: [AgentFolderRow]) -> [String] {
        rows.filter(\.isOn).map(\.glob)
    }

    /// "Choose a subfolder…": tick it if listed, else add it ticked.
    static func adding(_ path: String, to rows: [AgentFolderRow]) -> [AgentFolderRow] {
        var out = rows
        if let i = out.firstIndex(where: { $0.kind == .folder(path) }) {
            out[i].isOn = true
        } else {
            out.append(AgentFolderRow(kind: .folder(path), isOn: true))
        }
        return out
    }

    /// A picked folder, relative to the watched one — nil for the folder itself or anything outside it.
    static func relativePath(of url: URL, under root: URL) -> String? {
        let base = root.standardizedFileURL.resolvingSymlinksInPath().pathComponents
        let path = url.standardizedFileURL.resolvingSymlinksInPath().pathComponents
        guard path.count > base.count, Array(path.prefix(base.count)) == base else { return nil }
        return path.dropFirst(base.count).joined(separator: "/")
    }

    /// The watched folder's top-level subfolders, hidden ones skipped, in Finder's order.
    static func subfolders(in root: URL, fileManager: FileManager = .default) -> [String] {
        guard let items = try? fileManager.contentsOfDirectory(at: root, includingPropertiesForKeys: [.isDirectoryKey],
                                                               options: [.skipsHiddenFiles]) else { return [] }
        return items
            .filter { (try? $0.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) == true }
            .map(\.lastPathComponent)
            .sorted { $0.localizedStandardCompare($1) == .orderedAscending }
    }
}
```

  `LocalSourceWatcher.swift` — add beside `isOnThisMac` (`:137-138`):

```swift
    /// Where a registered folder is on this Mac, for Manage's "Choose a subfolder…" (R-HS17).
    func root(of folder: FolderRegistration) -> URL? { resolveRoot(folder.id) }

    /// A watched folder's top-level subfolders, for Manage's checklist (R-HS17). The app reads the
    /// folder — the backend never opens it (G133) — through its security-scoped bookmark; names only.
    func subfolders(of folder: FolderRegistration) -> [String] {
        guard let root = resolveRoot(folder.id) else { return [] }
        let scoped = root.startAccessingSecurityScopedResource()
        defer { if scoped { root.stopAccessingSecurityScopedResource() } }
        return AgentFolders.subfolders(in: root)
    }
```

- [ ] **Step 4: `SettingsSheet.swift`.**

```swift
import SwiftUI

/// One frame for every sheet the Settings panel raises (R-HS16): a title, a close × on
/// `.cancelAction` (Esc, in the sheet's own window — the panel's × is in the main window and never
/// sees it), the body, 440 pt wide. A sheet, never a popover: the panel is modal and inset 40 pt, so
/// a popover anchored at its edge could open past the screen (the owner's report); AppKit centres a
/// sheet on its window. `SettingsSheetLintTests` holds `Views/Settings/` to that.
struct SettingsSheet<Content: View>: View {
    static var width: CGFloat { 440 }

    let title: String
    let onClose: () -> Void
    @ViewBuilder let content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
                Text(title)
                    .font(CicadaTheme.headingFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1)
                    .accessibilityAddTraits(.isHeader)
                Spacer(minLength: CicadaTheme.spacingSM)
                IconButton(systemName: "xmark", help: Copy.sheetClose, accessibilityLabel: Copy.sheetClose,
                           shortcut: .cancelAction, action: onClose)
            }
            content
        }
        .padding(CicadaTheme.spacingXL)
        .frame(width: CicadaTheme.scaled(Self.width), alignment: .leading)
        .background(CicadaTheme.bgBase)
    }
}
```

- [ ] **Step 5: `LocalSourceRows.swift`.**
  - Add a private `LabeledField` (a label above the field — 12 medium `textSecondary` — then the field with
    `.accessibilityLabel(label)`, then a `metaFont` `textTertiary` helper line when there is one; docstring: the owner's
    report that the sheet had placeholders and no labels) and an internal `AgentFolderPicker(root: URL?, rows:
    Binding<[AgentFolderRow]>, message: Binding<String?>)`: a `LabeledField(label: Copy.Folders.writtenByAnAgent,
    help: Copy.Folders.writtenByAnAgentHelp)` holding `Copy.Folders.noSubfolders` when `rows` is empty, one
    `Toggle(row.title, isOn: $row.isOn).toggleStyle(.checkbox)` per row (`ForEach($rows)`), and — when `root` is set —
    `TextButton(title: Copy.Folders.chooseSubfolder) { choose(in: root) }`, where `choose(in:)` runs an `NSOpenPanel`
    (`canChooseDirectories = true`, `canChooseFiles = false`, `allowsMultipleSelection = false`,
    `canCreateDirectories = false`, `directoryURL = root`, `prompt = "Choose"`, `message = Copy.Folders.chooseSubfolder`)
    and then either sets `message = Copy.Folders.pickInside(root.lastPathComponent)` when
    `AgentFolders.relativePath(of:under:)` is nil, or clears it and sets `rows = AgentFolders.adding(path, to: rows)`.
  - `AddFolderSheet` (`:181-290`): replace `@State private var agentGlobs = "archive/**"` with
    `@State private var agentRows: [AgentFolderRow]`, initialised in `init` as
    `AgentFolders.initialRows(subfolders: AgentFolders.subfolders(in: url))` (comment: R-HS17, the app reads the folder).
    The body becomes `SettingsSheet(title: Copy.Folders.addTitle, onClose: { Task { await cancel() } }) { … }` holding:
    the path (unchanged mono, middle-truncated); `LabeledField(label: Copy.Folders.name) { TextField(Copy.Folders.name,
    text: $label, prompt: Text(url.lastPathComponent)) }`; `LabeledField(label: Copy.Folders.project, help:
    Copy.Folders.projectHelp) { TextField(Copy.Folders.project, text: $projectName) }`;
    `AgentFolderPicker(root: url, rows: $agentRows, message: $message).disabled(folder != nil)`; the preview lines and
    the message (unchanged); and a trailing
    `PrimaryActionButton(title: preview == nil ? "Look inside" : "Start watching") { Task { if preview == nil { await look() } else { await start() } } }`
    — the sheet's one prominent action (DR-40); the × is Cancel (it runs `cancel()`, which still removes a
    looked-inside registration), so the old "Cancel" button and the `HStack` it shared with Look inside go. `look()`
    and `start()` pass `agentGlobs: AgentFolders.globs(agentRows)`. Keep `.textFieldStyle(.roundedBorder)` and
    `.disabled(busy)` on the sheet; drop the sheet's own `.padding(CicadaTheme.spacingXL)` / `.frame(width: 440)` and its
    "Add a folder" `Text` — `SettingsSheet` owns the title, padding and width now. `PrimaryActionButton` takes no `async`
    closure — wrap it as shown.
  - `FolderChannelRow` (`:76-86`): Manage sets `showManage = true`; the `.popover` (and its `.padding` / `.frame(width:
    340)`) becomes `.sheet(isPresented: $showManage) { if let folder { FolderManagePanel(folder: folder) { showManage =
    false } } }`.
  - `FolderManagePanel` (`:293-352`) gains `let onDone: () -> Void` and `@State private var rows: [AgentFolderRow] = []`
    / `@State private var root: URL?` in place of `globs`. Its explicit `init(folder:)` (`:301-304`) existed only to seed
    `globs`: replace it with `init(folder: FolderRegistration, onDone: @escaping () -> Void)` that stores both (or delete
    it and let the memberwise init serve — every other stored property now has a default), so the trailing-closure call
    above compiles. Its body is
    `SettingsSheet(title: folder.label, onClose: onDone) { path; AgentFolderPicker(root: root, rows: $rows, message: $message); Text(Copy.Folders.manageHelp)…; message; buttons }`
    with `.onAppear { root = localSources.root(of: folder); rows = AgentFolders.rows(subfolders: localSources.subfolders(of: folder), globs: folder.agentGlobs) }`.
    Save writes `AgentFolders.globs(rows)` and calls `onDone()` on success; Stop watching's confirmation calls `onDone()`
    after `removeFolder`. The buttons keep their native styles (a Settings form, DR-45's note).
  - `WisprFlowRow` (`:379-390`): `.popover` (with its `.padding` / `.frame(width: 340)`) becomes
    `.sheet(isPresented: $showPanel) { WisprFlowPanel { showPanel = false } }`.
    `WisprFlowPanel` gains `let onDone: () -> Void`, drops its own "Wispr Flow" title (`:411-413`) for
    `SettingsSheet(title: "Wispr Flow", onClose: onDone)`, and calls `onDone()` after a successful save.
  - Delete `LocalSourceRowText.list`'s doc example `"archive/**, drafts/**"` wording: its comment becomes "comma or
    newline separated names" (it now only splits Wispr's meeting names).

- [ ] **Step 6: `IntegrationsView.swift` and the harness marks.**
  - `IntegrationCategory.swift`: add to `IntegrationHarnessRows`:

```swift
    /// DR-52, R-HS18 — the mark a harness row wears: its app's own (installed icon → bundled PNG,
    /// Track L), or nil when it has none — "Other agents" names no vendor, so it wears
    /// `otherAgentsSymbol`, never a "?" and never another app's mark.
    static func markOrigin(for row: SourceOverview) -> String? {
        let harness = row.harness ?? row.mark
        guard harness != "unknown", !harness.isEmpty,
              OriginIconography.logoName(for: harness) != nil || OriginIconography.appBundleId(for: harness) != nil
        else { return nil }
        return harness
    }

    static let otherAgentsSymbol = "ellipsis.bubble"
```

  - `IntegrationHarnessRow` (`:340-368`): the tinted-circle `ZStack` becomes
    `if let origin = IntegrationHarnessRows.markOrigin(for: source) { OriginMark(origin: origin, size: CicadaTheme.scaled(28)).clipShape(CicadaTheme.shape(CicadaTheme.scaled(28) * 0.2)) } else { Image(systemName: IntegrationHarnessRows.otherAgentsSymbol).font(CicadaTheme.font(size: 18)).foregroundStyle(CicadaTheme.textTertiary).frame(width: CicadaTheme.scaled(28), height: CicadaTheme.scaled(28)) }`.
    The clip is Track L's rule, not decoration: `claude-code` is an opaque square raster that is never recut, so every
    surface that draws it clips it to its own curvature (`PlatformTile`'s 0.2 ratio); it is a no-op for every mark
    whose corners are already transparent. No `.markHover()`: the row opens nothing, and under Reduce Motion the nod is
    an accent ring (DR-5).
  - `IntegrationChannelRow.mark` (`:264-274`) and `IntegrationExportOnlyRow` (`:382-392`): the tinted-circle fallback
    becomes the bare symbol — `Image(systemName: …).font(CicadaTheme.font(size: 18)).foregroundStyle(CicadaTheme.textSecondary).frame(width: CicadaTheme.scaled(28), height: CicadaTheme.scaled(28))`
    (DR-52: a mark never sits on a tinted tile).
  - DR-70 — every 28 pt mark on the rows this task edits scales with the chrome, so the page's marks stay one size at
    1.4×: the `LogoImage.platformTile(… size: 28 …)` calls in `IntegrationChannelRow.mark`, `IntegrationExportOnlyRow`,
    `FolderChannelRow`, `AddFolderRow` and `WisprFlowRow` become `size: CicadaTheme.scaled(28)`.
  - `IntegrationChannelRow` (`:215, 236-240`): rename `showConnectorPopover` → `showConnector`; the `.popover` becomes
    `.sheet(isPresented: $showConnector) { SettingsSheet(title: channel.label, onClose: { showConnector = false }) { ConnectorSetupPanel(connectorId: channel.id, vendors: tile?.vendors ?? [], vendor: $vendor) } }`.
    Its long docstring's "in a `.popover` attached to the row's `HStack`" becomes "in a `SettingsSheet` (R-HS16)".

- [ ] **Step 7: Green.** Filtered tests, then the full suite (`LocalSourcesSurfaceTests`, `SettingsRowLintTests`,
  `MonospaceLintTests` — `LocalSourceRows.swift` is already allowlisted for paths — must stay green).
  `rg -n '\.popover\(' <worktree>/app/CicadaApp/Sources/CicadaApp/Views/Settings` prints nothing.

- [ ] **Step 8: Commit.** Stage the files above only. Message:
  `feat(ds3b, g126, g133): Settings fixes — the add-folder sheet with labels and a subfolder picker instead of globs, real harness marks, every Manage and Connect a sheet that stays on screen (DR-33, DR-40, DR-52, DR-54, DR-59)`

---

### Task 5: Every setting is findable from ⌘K and opens where it lives; typing in Settings lands on a row (DR-33, DR-46, DR-60, DR-68; G136, G139; R-HS19…R-HS22)

**Files:**
- Modify: `app/…/Search/FindModels.swift:107`, `app/…/Search/QuickIndex.swift:197-206`,
  `app/…/Search/FindPaletteModel.swift:20, 75, 172-195`, `app/…/Search/FindMerge.swift:150-156`,
  `app/…/Views/Find/FindRowView.swift:26-49`, `app/…/Views/Find/FindPanelBody.swift:137-140, 194-205`,
  `app/…/ContentView.swift:364-365`, `app/…/Views/Settings/SettingsIndex.swift` (append `SettingsSearchLanding`),
  `app/…/Views/Settings/SettingsPanel.swift:210-223`, `app/…/Theme/Copy+HomeSleep.swift`
- Test: `Tests/CicadaAppTests/SettingsSearchLandingTests.swift` (new), `QuickIndexTests.swift`,
  `FindPaletteTests.swift:68-75`, `PaletteMergeTests.swift:176-179`

**Interfaces:**
- Produces `FindDestination.settings(SettingsSection, row: SettingsRowID?)`; `QuickIndex.settingsDocs()` over
  `SettingsIndex.pageEntries + staticEntries`; `SettingsSearchLanding.topHit(_:in:)`, `.announcement(section:row:in:)`;
  `Copy.PaletteSettings.detail(_:)`.
- Removes `FindPaletteModel.hint` and the palette's Settings "Open" link.
- Consumes `SettingsIndex`, `SettingsEntry.fields/anchor`, `SettingsFocus`, `AppRouter.openSettings(_:row:)`.

- [ ] **Step 1: Failing tests.** Create `SettingsSearchLandingTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// R-HS22 — typing in the Settings panel's field and pressing ⏎ lands on the row: the same seams
/// `SettingsPanel` calls, driven with the real `SettingsFocus`. (`SettingsRowLintTests` proves every
/// indexed row carries its anchor; the scroll and wash are the live check.)
@MainActor
final class SettingsSearchLandingTests: XCTestCase {
    private let entries = SettingsIndex.pageEntries + SettingsIndex.staticEntries

    func testReturnLandsOnTheTopHitsRow() throws {
        let hit = try XCTUnwrap(SettingsSearchLanding.topHit("text size", in: entries))
        XCTAssertEqual(hit.id, .textSize)
        XCTAssertEqual(hit.section, .general)

        let focus = SettingsFocus()
        focus.go(hit.section, row: hit.anchor)
        XCTAssertEqual(focus.request?.section, .general)
        XCTAssertEqual(focus.request?.row, .textSize)
        let name = SettingsSearchLanding.announcement(section: hit.section, row: hit.anchor, in: entries)
        XCTAssertEqual(name, "\(SettingsSection.general.title), \(hit.title)", "VoiceOver hears where it landed")
        focus.land(on: hit.anchor, announcing: name, reduceMotion: true)
        XCTAssertEqual(focus.highlighted, .textSize)
        XCTAssertEqual(focus.scrollTarget, .textSize)
        focus.consumeScroll()
        XCTAssertNil(focus.scrollTarget, "scrolled once")
    }

    func testARowWithNoAnchorLandsOnItsPage() throws {
        let hit = try XCTUnwrap(SettingsSearchLanding.topHit("tailscale", in: entries))
        XCTAssertEqual(hit.id, .remoteReach)
        XCTAssertEqual(hit.anchor, .page(.remote), "R-O12 — From anywhere lands on its header")
    }

    /// Typing a setting's own name surfaces it at the top of the results (the first three — two
    /// rows may share a word, and the panel shows every hit, grouped).
    func testEverySettingIsReachableByItsOwnName() {
        for entry in SettingsIndex.staticEntries {
            let top = SettingsIndex.search(entry.title, in: entries).prefix(3).map(\.entry.id)
            XCTAssertTrue(top.contains(entry.id), "\(entry.title) → \(top)")
        }
        XCTAssertNil(SettingsSearchLanding.topHit("zzz-nothing", in: entries))
        XCTAssertNil(SettingsSearchLanding.topHit("   ", in: entries))
    }
}
```

  Append to `QuickIndexTests.swift`:

```swift
    /// R-HS19 — every Settings page and every row is in ⌘K, from Settings' own index, and ⏎ lands on
    /// the row through the one door (R-HS20).
    func testEverySettingIsFoundFromCommandK() {
        let size = index.query("text size").rows.first { $0.group == .settings }
        XCTAssertEqual(size?.key, FindRowKey(kind: .setting, id: SettingsRowID.textSize.rawValue))
        XCTAssertEqual(size?.destination, .settings(.general, row: .textSize))
        XCTAssertEqual(size?.detail, Copy.PaletteSettings.detail(SettingsSection.general.title))
        XCTAssertEqual(index.query("extra usage").rows.first { $0.group == .settings }?.destination,
                       .settings(.engines, row: .engineOverage))
        XCTAssertEqual(index.query("tailscale").rows.first { $0.group == .settings }?.destination,
                       .settings(.remote, row: .page(.remote)))
        XCTAssertEqual(index.query("integrations").rows.first { $0.group == .settings }?.destination,
                       .settings(.integrations, row: nil), "a page lands on the page")
    }

    /// R-HS21 — a page keeps its old key (a recent survives); rows are keyed by row id; none collide.
    func testSettingsKeysAreStableAndUnique() {
        let docs = QuickIndex.settingsDocs()
        XCTAssertEqual(docs.count, SettingsIndex.pageEntries.count + SettingsIndex.staticEntries.count)
        XCTAssertEqual(Set(docs.map(\.row.key)).count, docs.count)
        let sections = Set(SettingsSection.allCases.map(\.rawValue))
        XCTAssertTrue(SettingsIndex.staticIDs.allSatisfy { !sections.contains($0.rawValue) },
                      "a row id equal to a section's raw value would shadow its page")
        XCTAssertTrue(docs.allSatisfy { !$0.row.key.id.contains(":") || $0.row.key.id.hasPrefix("skill:") },
                      "no per-item row (channel:, connection:, agent:) — R-HS19")
    }
```

  In the same file, `testSettingsActionsAndBanksReflectTheirState` asserts `rows.first` for "consolidate", "stop" and
  "dark"; Settings rows now precede Actions in group order, and "consolidate" / "dark" are Settings keywords. Change those
  three to read the action group — e.g. `index.query("consolidate").rows.first { $0.key.kind == .action }?.title` and
  `busy.query("dark").rows.first { $0.key.kind == .action }?.destination` — the assertion's meaning ("the palette's action
  reflects its state") is unchanged.

  `FindPaletteTests.swift:68-75` becomes:

```swift
    /// R-HS20 — ⏎ on a Settings row opens it through `AppRouter.openSettings` (the host runs the
    /// destination), and it is remembered like any row that navigates.
    func testASettingsRowOpensThroughTheOneDoor() {
        let m = model()
        m.setQuery("integrations")
        let key = FindRowKey(kind: .setting, id: SettingsSection.integrations.rawValue)
        XCTAssertEqual(m.activate(key), .settings(.integrations, row: nil))
        XCTAssertEqual(m.recents.first, key)
    }
```

  `PaletteMergeTests.swift:176-179` becomes:

```swift
    func testASettingsRowSaysItOpensSettings() {
        XCTAssertEqual(FindRowText.primaryVerb(.settings(.integrations, row: nil)), "Open in Settings",
                       "R-HS20 — ⏎ opens it (R-SU12's explain-only verb retired with the Settings scene)")
    }
```

  Append to `FindPaletteTests.swift` (the host's half, as a source check — `ContentView` is not unit-hostable):

```swift
    func testTheHostOpensSettingsThroughTheRouter() throws {
        let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first { $0.lastPathComponent == "ContentView.swift" })
        let text = try String(contentsOf: file, encoding: .utf8)
        XCTAssertTrue(text.contains("case .settings(let section, let row):"))
        XCTAssertTrue(text.contains("router.openSettings(section, row: row)"))
    }
```

  Run: `cd <worktree>/app/CicadaApp && swift test --filter 'SettingsSearchLandingTests|QuickIndexTests|FindPaletteTests|PaletteMergeTests' 2>&1 | tail -20`
  → compile failure. That is the red.

- [ ] **Step 2: The destination and the rows.**
  - `FindModels.swift:107`: `case settings(SettingsSection, row: SettingsRowID?)`. Update the enum's comment: `.settings`
    now comes back to the host like every navigating case (R-HS20); only `.ask` and `.askedBefore` stay in the palette.
  - `Copy+HomeSleep.swift`: add
    `enum PaletteSettings { static func detail(_ section: String) -> String { "\(Copy.settings) · \(section)" } }` and
    `PaletteSettings.detail("Engines")` to `homeSleepLabels`.
  - `QuickIndex.settingsDocs()` (`:197-206`):

```swift
    /// R-SU12, amended by DS-3b (R-HS19…R-HS21): every Settings page AND every row, from Settings'
    /// own index, so a setting is found from ⌘K by what it is called ("text size", "extra usage") and
    /// ranked by the same words the panel's field uses (`SettingsEntry.fields`, one `QuickMatch`).
    /// ⏎ lands on the row through the one door, `AppRouter.openSettings(_:row:)`. A page keeps its old
    /// key, `section.rawValue`, so a recent survives; a row is keyed by its row id. The dynamic per-item
    /// rows (channels, harnesses, connections, agents, recommended skills) stay in the panel: the Sources
    /// group already names channels and harnesses (DR-38), and the rest are not palette inputs.
    static func settingsDocs() -> [Doc] {
        (SettingsIndex.pageEntries + SettingsIndex.staticEntries).enumerated().map { i, entry in
            let isPage = entry.id == .page(entry.section)
            let row = FindRow(key: FindRowKey(kind: .setting, id: isPage ? entry.section.rawValue : entry.id.rawValue),
                              group: .settings, title: entry.title,
                              detail: isPage ? Copy.settings : Copy.PaletteSettings.detail(entry.section.title),
                              mark: .symbol(entry.section.icon), tieBreak: -Double(i),
                              destination: .settings(entry.section, row: isPage ? nil : entry.anchor))
            return Doc(row: row, fields: entry.fields + [QuickMatch.Field(Copy.settings, weight: QuickMatch.Weight.keyword)])
        }
    }
```

- [ ] **Step 3: ⏎ opens it.**
  - `FindPaletteModel.swift`: delete `hint` (`:20`), its reset in `setQuery` (`:75`) and the `.settings` case in
    `activate` (`:191-193`) — a Settings row now takes the `default:` path (remembered, returned). Update `activate`'s
    docstring ("the Settings hint" leaves the list).
  - `FindMerge.swift:154`: `case .settings: "Open in Settings"` and replace the R-SU12 comment above it with R-HS20's
    reason (the scene that no closure could open is gone since DS-1).
  - `FindRowView.swift`: delete the `if case .settings(let section) = row.destination { SettingsSectionLink(…) }` block
    (`:26-28`); delete the three-line comment above `.accessibilityElement` (`:37-39`) and make that modifier
    `.accessibilityElement(children: .ignore)` again (`:40`); delete the `opensSettings` property (`:46-49`). Keep
    `.onHover { hovered = $0 }` (`:36`) and every other modifier.
  - `FindPanelBody.swift`: delete the hint `Text` (`:137-140`); in `menu(for:)` (`:194-205`) delete the `.settings` branch
    and its comment, so every row's menu is the primary-verb `Button`.
  - `ContentView.swift:364-365`:

```swift
        case .settings(let section, let row):
            // R-HS20 — the one door (R-DS22). The palette has already closed itself; Home's field
            // (page placement) stays, under the panel.
            router.openSettings(section, row: row)
        case .ask, .askedBefore:
            break
```

    and update the function's docstring: only `.ask` and `.askedBefore` never arrive here.

- [ ] **Step 4: The panel's landing as values.** Append to `SettingsIndex.swift`:

```swift
/// G139's landing, as values (R-HS22): what ⏎ in the panel's field opens, and what VoiceOver hears
/// when it lands. `SettingsPanel.openTopHit` and `land(_:)` call these, so the test drives the same
/// code the field does.
enum SettingsSearchLanding {
    static func topHit(_ query: String, in entries: [SettingsEntry]) -> SettingsEntry? {
        SettingsIndex.search(query.trimmingCharacters(in: .whitespacesAndNewlines), in: entries).first?.entry
    }

    /// "Sleep, Runs", not just "Sleep".
    static func announcement(section: SettingsSection, row: SettingsRowID, in entries: [SettingsEntry]) -> String {
        SettingsIndex.entry(for: row, in: entries).map { "\(section.title), \($0.title)" } ?? section.title
    }
}
```

  `SettingsPanel.swift:210-223`: `openTopHit` becomes `if let top = SettingsSearchLanding.topHit(trimmedQuery, in: entries) { open(top) }`;
  `land(_:)`'s `name` becomes `SettingsSearchLanding.announcement(section: request.section, row: row, in: entries)`.
  `SettingsIndex.search(` stays in the file (the sidebar's `hits`), so `SettingsPanelTests.testTheSidebarKeepsG139`
  holds.

- [ ] **Step 5: Green.** Filtered tests, then the full suite. `rg -n 'model\.hint|Show how to open|Click Open to see' <worktree>/app/CicadaApp`
  prints nothing. `QuickIndexLatencyTests` must stay inside its budget (≈ 60 more docs; re-run it alone if it is the only red).

- [ ] **Step 6: Commit.** Stage the files above only. Message:
  `feat(ds3b, g136, g139): every setting is findable from ⌘K and opens on its row through AppRouter.openSettings; the panel's ⏎ and landing are values with a test (DR-33, DR-46, DR-60, DR-68)`

---

### Task 6: Docs — Home, the Sleep page and the Settings panel as Direction D ships them

**Files:**
- Modify: `CLAUDE.md`; `docs/design/DESIGN_RULES.md` (§9 appended lines; §10's Home and Sleep paragraphs; §9's closing
  paragraph's CLAUDE.md sentence); `docs/goals/TODO.md`; `docs/goals/memory-evolution.md`

- [ ] **Step 1: DESIGN_RULES §9.** Append one dated line (**2026-09-24**) per departure, in the file's voice, each citing
  its ruling id; old lines are never edited:
  - **R-HS2:** Home is the D-Home mock — the hero painting as a 120 pt band faded into `bgBase`, the one-line headline
    on the row under it, a 640 pt field (the approved mock over §10's 560), no drifting cloud.
  - **R-HS3:** no Consolidate on Home; §10's bullet contradicted G125 R10, so §10 is corrected (DESIGN_RULES §1: the rule
    is what gets fixed). "Recently learned" waits for a backend field (the claims a cycle wrote, with their spans).
  - **R-HS9:** the Sleep page's "Runs on …" caption retires into the engine button; the button stays while a cycle runs.
  - **R-HS10:** the engine menu is a `NeutralButton` + popover with a native menu `Picker` for the model, not text tabs.
  - **R-HS11:** one preview wording app-wide — "When you start a cycle" / "Scheduled cycles".
  - **R-HS15:** Details in list grammar; Last cycle's failure and warning glyphs in `warning` (DR-7), "Rested" as a
    sentence, readout rows with `UsageFormat` counts, one glyph per episode row.
  - **R-HS16:** Settings raises sheets, never popovers (the owner's off-screen Manage).
  - **R-HS20:** ⏎ on a Settings row in ⌘K opens it through `AppRouter.openSettings`; R-SU12's explain-only row retired
    with the `Settings{}` scene.
  - **R-HS1:** no design flag, as R-DS1.
  Replace the closing paragraph's sentence about which CLAUDE.md paragraphs describe D with one that adds, as of DS-3b,
  Home, the Sleep page's control row and Details, and the Settings panel's Integrations and search.
- [ ] **Step 2: DESIGN_RULES §10.** Rewrite the Home paragraph to what ships: search first under the painted band, the
  headline under it, a 640 pt field in the 760 pt column, then Getting started (while it lasts), Today, Needs you (the
  Inbox's STATE 0 rows, opening STATE 1) and Last read — each number once, each a link; **no Consolidate** (G125 R10).
  In the Sleep paragraph, the engine-menu bullet gains "a popover of the five engines with real marks, the chosen
  engine's model (a menu picker), both previews, and 'More in Settings → Engines ›'"; the Details bullet and the
  "Rested 0%" bullet say what shipped. The Settings paragraph adds "Manage and Connect open as sheets, never popovers".
- [ ] **Step 3: CLAUDE.md** (the file's voice; each paragraph describes what ships):
  - **Home (G108, Track I part b)** → rewrite as **Home (G108; Direction D, DS-3b)**: the painted `hero-day` band
    (`HomeHeroBand`, paint only, faded into the window), "What would you like to remember?" as a `PageTitle` on the row
    under it, the palette's own `FindPanelBody` in `.page` placement in a 640 pt block (a second `FindPaletteModel`
    sharing the one Ask, no recents; ⌘K on Home focuses it; a pasted link offers *Save this link*), then Getting started
    (while it lasts), Today, Needs you (the Inbox's own `InboxRow`s, landing in STATE 1) and Last read (the newest Sleep
    commit, its pages as `Tag`s) as labelled `glassCard` blocks of 36 pt rows in one 760 pt column — each number once,
    each a link (`InlineLink`) to the page that owns it; the waiting count links to Sleep, never a Consolidate.
  - **Settings → Engines** paragraph: "the Sleep page shows the two previews read-only with a link here" becomes "the
    Sleep page's quick engine menu (beside Consolidate) reads and writes the same `PUT /sleep/engine` through the same
    `SleepEngineViewModel` and the same write rule (`EngineWrite`), and shows both previews — 'When you start a cycle' /
    'Scheduled cycles', the one wording app-wide".
  - **Sleep page — the study room**: after "one Consolidate/Cancel control", add "with the engine menu beside it — a
    neutral button naming what a cycle you start would run (`preview.manual`, 'Auto ·' under Auto) that opens the five
    engines with their real marks, the chosen engine's model and both ruling-4 previews; the 'Runs on …' caption retired
    into it, and Cancel's caption shows while running". Replace "everything else under a single **Details** disclosure
    (Last cycle · What's waiting · Readout · Past nights)" with the same plus "in D's list grammar — section labels over
    rows, no cards; Last cycle's rows in words, 'Rested' as a sentence, the readout as key–value rows".
  - **Settings → Integrations (G126)**: add "harness rows wear their app's real mark ('Other agents' a neutral glyph);
    a folder's Manage, Wispr Flow and a connector's Connect/Manage open as sheets (`SettingsSheet`), never popovers; the
    add-folder sheet labels its fields and asks which subfolders an agent wrote as a checklist (`AgentFolders`), the wire
    still a `<folder>/**` glob".
  - **Find palette (G136)**: add "Settings' pages and every static row are in the palette from `SettingsIndex` (one
    index, one ranker); ⏎ lands on the row through `AppRouter.openSettings(_:row:)`".
  - **Graphite and Meadow**: `HomeSkyBand` → `HomeHeroBand`.
- [ ] **Step 4: TODO.md.** Under "## Where things stand", after the "**Round 3, Direction D — DS-2 …**" paragraph, add a
  DS-3b paragraph in its shape: `feat/d-home-sleep-settings`, plan `2026-09-24-d-home-sleep-settings.md` — what shipped
  (the four areas), the rulings (R-HS1…R-HS22), and the verified Swift counts. Under "## Pick up here", update the
  "**Direction D, next …**" paragraph: the remaining DS tracks (Graph and the entity card, Clusters, Feed, Sources,
  Projects). Under "### Small & cheap — grab when passing" (beside DS-2's R-DI21 demo-bank line), add the backend
  follow-up for Home's "Recently learned": the history detail (`GET /sleep/history/{commit}`) lists the pages a cycle
  changed but not the claims it wrote with their evidence spans; a claims list (ids + spans, no text in the commit)
  would let Home show them with their source lines. Placeholders only; no bank contents.
- [ ] **Step 5: memory-evolution.md** — edit the rows in place, one sentence each:
  - **G108:** "DS-3b (2026-09-24): Home in Direction D — the painted band, the headline under it, labelled blocks, Needs
    you as the Inbox's own rows, no Consolidate."
  - **G122:** "DS-3b: the Sleep page's quick engine menu writes the same `PUT /sleep/engine` through the chooser's model,
    with both previews."
  - **G125:** "DS-3b: Details in list grammar; 'Rested' is a sentence."
  - **G126:** "DS-3b: real harness marks; Manage and Connect are sheets."
  - **G133:** "DS-3b: 'Written by an agent' is a subfolder checklist, not a typed glob."
  - **G136 / G139:** "DS-3b: every Settings row is in ⌘K and ⏎ lands on it through `AppRouter.openSettings`."
- [ ] **Step 6: Commit.** Stage `CLAUDE.md`, `docs/design/DESIGN_RULES.md`, `docs/goals/TODO.md` and
  `docs/goals/memory-evolution.md` only. Message:
  `docs(ds3b): Home, the Sleep page's engine menu and Details, and the Settings panel as Direction D ships them; §9 rulings, §10 corrected (DR-17, DR-33, DR-37, DR-40, DR-52)`

---

## Not in scope

Named so a reviewer does not read an absence as an oversight.

- **Other pages:** Graph and the entity card, Clusters, Feed, Sources, Inbox, Projects — their DS tracks.
- **The study room:** art, sprites, hotspots, the sentence (`RoomSentence`, already the display face), Consolidate, the
  whisper line, the lamp's popover, the window's weather, the pile and the strip are unchanged. The page's `PageTitle`
  header stays (R-HS14).
- **Any backend change:** no endpoint, field, ETag component, Store domain or pref. In particular:
  - **Home's "Recently learned"** (marked Proposed in the mock) needs the claims a cycle wrote with their evidence spans;
    `GET /sleep/history/{commit}` returns page ids only. Reported as a backend follow-up (Task 6), not built.
  - The mock's other Proposed item — the save-link row inside the results — is not built; the row stays above the field.
- **The free-text model id and the extra-usage switch** stay in Settings → Engines (R-HS10); the menu links there.
- **`SleepViewModel`'s own `/sleep/engine` fetch** stays as the fallback source (R-HS12); collapsing it into
  `SleepEngineViewModel` is a later clean-up with its own tests.
- **Settings' per-item rows in ⌘K** (channels, harnesses, connections, agents, skills) — R-HS19.
- **A hosted-view accessibility test of the panel's scroll and wash** (R-HS22) — the live check covers it.
- **The Sources page's "Other agents" mark** (`SourceDisplayName` / the Sources grid) — the Sources track's.
- **The app-wide lints R-DS28 deferred** (`DividerLintTests`, `ContinuousCornerLintTests`, `KeyboardAnimationLintTests`,
  `EasingLintTests`, `PriceLintTests`); this track adds only its scoped lints.
- **The `cicada.design.focus` flag** (R-HS1).
- **Image-golden snapshots at 0.8× / 1.0× / 1.4× (DR-70).** The fit test and the pure layouts hold the geometry; the
  orchestrator's live check holds the look.

---

## Verification the orchestrator runs at the end

1. **Suites.**
   - `cd <worktree>/app/CicadaApp && swift build 2>&1 | tail -5` succeeds.
   - `swift test 2>&1 | tail -20` reports **0 failures** (≥ 1623 executed plus the new tests). Re-run
     `SleepViewModelTests` or the search-latency tests alone if they are the only red.
   - `cd <worktree> && node --test app/CicadaApp/Tests/graph/*.test.js` is green.
2. **Lints fail when they should.** Temporarily add `.popover(isPresented: .constant(false)) { EmptyView() }` to
   `SettingsSheet.swift` → `SettingsSheetLintTests` fails; add `CicadaTheme.accent` to `EngineQuickMenu.swift` →
   `SelectionTintLintTests` fails; add `Text("x")` to `HomeHeroBand.swift` → `HomeBandLayoutTests` fails. Revert each.
3. **Nothing retired survives.** `rg -n 'HomeSkyBand|homeHeadlineItalic|HomeCard\b|heroTiles|entitiesInMemory|engineSymbol|runsOn\(|model\.hint|Show how to open|"archive/\*\*"' app/CicadaApp/Sources`
   prints nothing; `rg -n '\.popover\(' app/CicadaApp/Sources/CicadaApp/Views/Settings` prints nothing.
4. **Live, on the demo bank, installed build** — 1440 × 900 and 1200 × 800, rail and labelled sidebar, 1.0× and 1.4×,
   dark and light:
   - **Home:** the painting shows its meadow and fades into the window; the headline sits under it on the window, never
     on paint; the field is a 640 pt block; typing replaces the blocks with results and Esc brings them back; a pasted
     `https://example.com/x` offers *Save this link*. Today's marks open their source; "Sleep ›" opens the Sleep page;
     a Needs you row opens that question in STATE 1 and "All N ›" opens the Inbox; a Last read chip opens the graph on
     that page. At 1200 labelled at 1.4× the Needs you rows drop their entity slot, not their question. Getting started
     (Settings → General → *Show setup checklist*) shows in the focus-card material with Hide, ×, and Choose a file….
     There is no Consolidate anywhere on Home.
   - **Sleep:** the room, the sentence, Consolidate and the whisper line look exactly as before. Beside Consolidate the
     engine button reads e.g. "Claude plan · sonnet" with its mark (or "Auto · …"); its menu lists Auto, Claude plan,
     ChatGPT plan, Ollama and API key with real marks and a check on the choice; a signed-out plan is dimmed with a
     "Sign in on Plans & keys…" hover; choosing another engine changes the button, the lamp popover's engine line and,
     after opening Settings → Engines, the chooser's selected card (one source of truth); the model picker switches the
     model; both "When you start a cycle" and "Scheduled cycles" lines always show, and the ruling sentence shows when
     they differ; "More in Settings → Engines ›" closes the menu and lands on the engine row. While a cycle runs the
     button stays and Cancel's caption shows. No price, token count or "$" anywhere. Details opens to labels over rows:
     no cards, "Rested …" as one sentence, the readout as four key–value rows with the engine's mark, Past nights as
     36 pt rows that expand.
   - **Settings:** Integrations → Chat & agents shows Claude Code, Codex and Cursor with their real marks, "Other agents"
     with the neutral glyph. *Add a folder of notes* → the sheet has labelled Name and Project fields and a "Written by
     an agent" checklist of the folder's subfolders ("Files in research (and its subfolders)") plus *Choose a
     subfolder…*; no `**` anywhere. A watched folder's Manage, Wispr Flow's panel, and a connector's Connect/Manage all
     open as sheets centred on the window, at 1200 with the panel at its inset and the window pushed to a screen edge.
     Typing "text size" in the panel's field and pressing ⏎ selects General, scrolls to Text size and washes it.
   - **⌘K:** "text size", "extra usage", "telemetry", "tailscale" each show a Settings row ("Settings · General"…); ⏎
     closes the palette and opens the panel on that row (washed). The same works from Home's field.
5. **PR body must state:** the DR ids applied and the §9 lines added; that the ETag recipes, `VersionVector.mapping`
   and every endpoint are **unchanged**, and no pref or Store domain was added; that no price, token count or `$`
   appears on any surface this PR touches; and the "Recently learned" backend follow-up.
