# Meadow foundation (Track M1, G137) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the app the "Meadow" visual system every other round-3 track builds on: nature is
the ground and glass is the chrome. This track re-tunes the neutrals into a warm "day meadow" and a
blue-green "night meadow" without moving a single data hue. It adds nature tokens and procedural
skies. It bundles one display serif (Instrument Serif, OFL) beside New York italic for quoted words.
It turns 47 hand-spelled animation durations into one Reduce-Motion-aware vocabulary, with hover
modifiers for icons and for things that open. It adds a single `liquidGlass` modifier gated on
macOS 26 and a primary-action style. It ships a painted art set with a provenance manifest and
`-dark` siblings, plus the components that draw it. Lints make each of those rules fail the build
rather than live in a comment. The foundation lands in exactly three places: the sidebar (system
glass on macOS 26, glyphs that react to the pointer), `PageHeader` (the serif title) and
`EmptyStateView` (grass corners, one drifting cloud behind the bookworm, words on a card). Every
other page is left for the M2 pass.

**Architecture:** Every rule is a **token, a pure function, or a source lint**, and every view is a
thin renderer over them, matching the house pattern of `SleepMotion`/`SleepNumbersLintTests` and
`LogoImage`/`LogoAssetTests`. New code goes into five new homes: `Theme/CicadaMotion.swift`,
`Theme/CicadaFonts.swift`, `Theme/LiquidGlass.swift`, `Views/Meadow/` and `Resources/{fonts,art}/`.
Colours and the one custom font stay in `Theme/CicadaTheme.swift`, where the existing lints already
look. There is no backend change, no new endpoint, no ETag, no Store domain and no wire field.

**Tech Stack:** SwiftUI + XCTest (`app/CicadaApp`, package floor macOS 14, built with the macOS 26.1
SDK), `node:test` for `graph.js`, and Python 3 + Pillow for a one-off art processing script that
stays in the session scratchpad and is never committed.

**Spec:** `docs/superpowers/specs/2026-09-23-round3-meadow-reach-provenance-design.md`, Decision 6
and § *Track M1: Meadow foundation*, rulings **R-M1 … R-M7** (binding). The research this rests on
(R9, Liquid Glass + nature design; R6 §1 and §2.12–2.14, design audit) sits in the session
scratchpad and is **not** in this repo. Every fact this plan takes from it is restated inline with
its measurement, so this file stands alone. R9's tables and type-checked snippets are the concrete
design. Where this plan departs from one, the ruling says so. Backlog: this track opens **G137**.
Standing rulings apply: no prices or tokens anywhere in the app (2026-09-03), ETag ship-together
(untouched here), privacy in docs, and portability.

---

## What the code actually does today (verified against `feat/meadow-foundation` @ `f2d31ef`)

**Baselines on this base (measured by the planner):** Swift **1012 executed, 0 failures**; graph
node tests **7 pass, 0 fail**.

**Theme** (`app/CicadaApp/Sources/CicadaApp/Theme/CicadaTheme.swift`):
- `:1-2` imports `Observation` and `SwiftUI` only. `:97-130` defines the neutral accessors
  (`background` … `codeBackground`), each `mode == .dark ? Dark.x : Light.x`. `:233-244` holds
  `font(size:weight:design:)` and the five SF type tokens. `:254-256` has two unscaled radii (12 / 8).
- `:281-393` is the `Dark` palette, whose header says "The app's original hand-tuned palette,
  unchanged": `background 0x0E0F14` (violet cast), `accent 0x8896FF`, `codeBackground 0x0A0B0F`.
  `:395-401` is the **misleading comment**: it claims the light entity hues "keep ~4.5:1+ contrast on
  a near-white surface". Measured with the WCAG 2.x formula on the new `#F4F6F1`, only person 4.82,
  project 4.97 and directory 4.91 clear 4.5. location 4.49, media 4.02, deadline 3.83, hub 3.76,
  tool 3.44, concept 3.33 and company 3.32 clear only the 3:1 non-text bar. skill (`0xB48A00`) is
  **2.93** and clears neither. The old `#F5F6FA` gives nearly identical numbers (every one within
  0.04; only location crosses a bar, at 4.52 there), so the comment was already wrong. The same
  promise is repeated in the `// MARK: - Entity Type Colors` comment at `:143-147` ("so each still
  clears ~4.5:1 on a near-white surface"). `:403-495` is the `Light` palette (`background
  0xF5F6FA`, `accent 0x5A62E0`). The dark entity hues still clear 6.2:1 or more on the new
  `#0D1216`, so the Dark `entityColor` comment (`:315-317`) stays true.
- `:513-541`: `GlassCard` is `surface.opacity(0.6)` over `.ultraThinMaterial`, a **material** card
  with 43 call sites. `:560-575`: `CicadaPlainButtonStyle`, with `pressAnimationDuration = 0.12` at
  `:566` and `.animation(.easeOut(duration: Self.pressAnimationDuration), …)` at `:573`.
  `:601-612`: `CicadaGlassButtonStyle` does the same at `:610`.
- Colours are defined outside the theme too. `CicadaApp.swift:252-262` `syncWindowChrome`
  hand-copies the old neutrals as `NSColor(red: 14/255, green: 15/255, blue: 20/255…)` at `:257` and
  `NSColor(red: 245/255, …250/255…)` at `:260`. It is the only `NSColor(red:` in `Sources/`
  (`MenuBar/PixelRenderer.swift:44` uses `NSColor(srgbRed:` for sprite hexes, which is a different
  thing).
- Literal copies of the dark accent `0x8896FF` are used as **identity** colours:
  `inboxColor(.clarification/.normalization)` (`:374, :382`), `graph.js:72`
  `OBSERVER_BADGE_COLORS.agent`, `MenuBar/BookwormSprites.swift:29` (the mascot's zZ, with the
  comment "(= CicadaTheme dark accent)"), `OriginIconography.swift:141,155` and
  `ConnectedChannelRow.swift:229`.

**Graph canvas** (`Resources/graph/`):
- `index.html:11`: `html, body { background: transparent; }`. **graph.js paints no canvas
  background of its own.** The SwiftUI detail column's `.background(CicadaTheme.background)`
  (`ContentView.swift:46`) shows through.
- `graph.js:88-107` `PALETTES` holds the only neutrals graph.js draws: the label ink, the label
  plate, the halo, the contextless edge and the node stroke. Each is a hand-copied twin of a theme
  token and most carry a `// = Dark.x` / `// = Light.x` comment. `:19` and `:83` quote the old
  hexes in comments. `:20-34` `typeColors` "MUST stay byte-identical to CicadaTheme.entityColor",
  which **nothing tests today**.
- `Tests/graph/graph-theme.test.js:24-38` checks that both palettes have every key and differ. It
  does not pin a value.

**Motion.** There are **47** literal-duration sites in **13 files** outside `Views/Sleep/`. None of
them honours Reduce Motion. The complete list, with each site's enclosing type:
- `ContentView.swift` 111, 130, 219, 229 (`ContentView`); 342 (`GraphContainerView`); 549 (`ZoomButton`)
- `Ask/AskPanel.swift` 34 (`AskPanel`)
- `Theme/CicadaTheme.swift` 573 (`CicadaPlainButtonStyle`); 610 (`CicadaGlassButtonStyle`)
- `Views/Sidebar/SidebarView.swift` 119 (`SidebarView`); 189, 190 (`SidebarRow`); 215 (`ThemeToggleButton`); 258 (`SettingsGearButton`)
- `Views/Capture/ConnectedChannelRow.swift` 171 (`ConnectedChannelRow`)
- `Views/Inbox/InboxCardView.swift` 53, 54, 101, 112, 118, 194, 227, 498, 503 (`InboxCardView`); 550 (`InboxActionButton`)
- `Views/Inbox/InboxListView.swift` 57 (`InboxListView`); 231, 232 (`KindChip`)
- `Views/Common/CommandBox.swift` 54 (`CommandBox`)
- `Views/Common/TopBarControls.swift` 49, 80, 99 (`TopBarControls`)
- `Views/Common/UploadOverlay.swift` 67, 207, 443 (`UploadOverlay`)
- `Views/Feed/ConnectedChannelsStrip.swift` 58 (`ConnectedChannelsStrip`)
- `Views/Feed/FeedView.swift` 102 (`FeedView`); 342 (`FeedRow`)
- `Views/Topics/TopicsView.swift` 22, 43 (`TopicsView`); 161, 167, 273, 316 (`TopicsListView`); 399 (`TypeSectionHeader`); 466 (`TypeChip`); 678 (`TopicRowListItem`)

None of those 13 files mentions `reduceMotion` today, so there are no name clashes.
`Views/Sleep/SleepMotion.swift:22-52` is the precedent: every function returns `nil` under Reduce
Motion. `Tests/CicadaAppTests/SleepNumbersLintTests.swift:103-114` bans any `duration:` under
`Views/Sleep/` except in `SleepMotion.swift`. `Views/Sleep/SleepView.swift:189` mentions `duration:`
only inside a `///` comment. The app has **no** `symbolEffect`, `#available`, `glassEffect`,
`.custom(` font, `colorSchemeContrast`, `accessibilityReduceTransparency` or `controlActiveState`
anywhere in `Sources/`.

**Chrome.**
- `Views/Sidebar/SidebarView.swift:101`: `.background(CicadaTheme.background)` paints an opaque
  fill over the column that macOS 26 renders as a floating Liquid Glass sidebar.
- `:158-161`: the tab glyph is a static `Image(systemName: tab.icon)`.
- `:170-178`: the inbox badge is `.foregroundStyle(.white)` on `CicadaTheme.accent.opacity(0.8)`.
  Measured: white is about **3.9:1** on today's `#8896FF` at 80% over the dark sidebar, 2.67:1 on
  it opaque, and **2.53:1** on the new opaque dark accent. That is below 4.5 in every case.
- `:204` and `:240`: the theme-toggle and gear glyphs are static too.
- `Views/Common/PageHeader.swift:26-28`: the title is `CicadaTheme.titleFont` (SF 20 semibold). It
  has ten call sites: Inbox, Clusters, Feed, Sources, the source detail page and five Settings
  sections.
- `Ask/AskPanel.swift:53-54`: a 560×460 `.sheet` whose whole body is one opaque
  `.background(CicadaTheme.surface)`, with a `ScrollView` of answers filling it.
- `bundle.sh:80`: `LSMinimumSystemVersion 13.0`, while `Package.swift:6` builds for
  `.macOS(.v14)`.

**Empty states.** `Views/Common/EmptyStateView.swift:24-40` is a bookworm (`.happy`, 96 pt), a
`headingFont` title and a `textTertiary` message placed directly on the page, plus one action. The
action is either `SettingsSectionLink` (`:31-32`) or a `.cicadaPlain` accent text button
(`:33-35`). It is called at four sites: `ContentView.swift:256` (Graph, drawn over the empty
canvas), `InboxListView.swift:120` (no action), `SourceCardGrid.swift:53` (inside a `ScrollView`)
and `FeedView.swift:241`. **All three sites that have an action pass `settingsSection:`**. The
closure branch has no caller today. `SleepQueueCardV3Tests.swift:140-154` pins that
`SettingsSectionLink.swift` is the only file that writes the settings-section seed, and that
`EmptyStateView.swift` never mentions the key, **comments included**.

**Resources.**
- `Package.swift:10` has `.copy("Resources")`.
- `Utilities/ResourceBundle.swift:31-62`: every lookup goes through
  `Bundle.cicadaResource(_:ext:in:)` with a **bare** directory name. `bundle.sh` re-nests the
  resource bundle, so `"Resources/x"` resolves under `swift test` but never in a shipped app. That
  was the PR #70 bug.
- `LogoAssetTests.swift:144-173` is the both-layouts test pattern this plan copies.
- `Resources/` is 4.4 MB today. `logos/logos.manifest.json` is the provenance-manifest precedent.

**Upstream font, verified by the planner (2026-09-23):**
`https://raw.githubusercontent.com/google/fonts/main/ofl/instrumentserif/` serves
`InstrumentSerif-Regular.ttf` (68 KB, sha256 `498efd46…ffbb88`), `InstrumentSerif-Italic.ttf`
(70 KB, `08939b8b…327385`) and `OFL.txt` (`129ed761…865521`). `METADATA.pb` gives upstream commit
`65c0ef22…`, licence OFL, and no Reserved Font Name. The following were measured with CoreText:
- The PostScript names are exactly `InstrumentSerif-Regular` / `InstrumentSerif-Italic`.
- A second `CTFontManagerRegisterFontsForURL(.process)` of the same file returns `false` with
  error code **105** (`kCTFontManagerErrorAlreadyRegistered`).
- `NSFont(name:size:)` resolves after registration and not before.
- Width check: Instrument Serif 28 pt sets "Integrations" at 114 pt against 110 for SF 20
  semibold, "Plans & keys" at 119 against 115, "Welcome to Cicada" at 175 against 176, and "Chrome
  bookmarks" at 189 against 179. That is the same width within ±6%.

**Toolchain:** Swift 6.2.1 with the macOS 26.1 SDK, host macOS 26.6.2. The planner type-checked
every new API shape in this plan at `-target arm64-apple-macos14.0` with exit 0. That covers the
`CicadaMotion` functions, `@Environment` inside a `ButtonStyle`, `IconHover` with
`symbolEffectsRemoved`, `.wiggle` behind `#available(macOS 15, *)` and `.bounce`, the gated
`glassEffect`/`GlassEffectContainer`/`.glassProminent`, `primaryActionStyle()` on a `SettingsLink`,
a `TimelineView(.animation(minimumInterval:paused:))` reading `controlActiveState`,
`resizable(capInsets:resizingMode: .tile)`, the CoreText registration and CryptoKit `SHA256`. An
ungated `.glassEffect()` fails with "only available in macOS 26.0 or newer", which is the negative
control. `NSBitmapImageRep.colorAt(x:y:)` has **y = 0 at the top row** of a decoded PNG (measured).

---

## Global Constraints

- `<worktree>` is the absolute path of the `feat/meadow-foundation` worktree, and `<repo>` is the
  main checkout it hangs off. `<art-src>` is the round-3 art directory and `<scratch>` the session
  scratchpad. `<installed app>` is the
  `Cicada.app` the orchestrator's final install produces. The orchestrator's brief gives all
  of them. They are deliberately not written here because this file is committed and the privacy
  rule bars author-machine paths.
- Work ONLY in `<worktree>`. Every shell command is `cd <worktree>… && <cmd>` with the ABSOLUTE
  path, because zoxide hijacks a relative `cd` (ignore its stderr warning). Never use
  `grep --include=*.ext`, because zsh globs it.
- NEVER read any bank under `<repo>/memory`, `~/.cicada`, `~/Library/Safari` or `~/.claude/projects`.
  Fixtures are synthetic.
- Swift: `cd <worktree>/app/CicadaApp && swift build 2>&1 | tail -5` must succeed and
  `swift test 2>&1 | tail -20` must report **0 failures** (1012 executed on this base, plus this
  track's new tests). Graph: `cd <worktree> && node --test app/CicadaApp/Tests/graph/*.test.js`
  (pass the glob). SourceKit diagnostics that name other worktrees are noise.
- NEVER run `make dev`, `make install-app` or `swift run`, and never launch or kill the Cicada app
  or the launchd backend. The owner's installed app is live, and the orchestrator installs and
  checks it at the end.
- Never `git add -A`: stage named files only. Never commit `memory/`, `logs/`,
  `.claude/settings.json`, `api/.venv` or `*-report.md`. Do not push, create branches or worktrees,
  or dispatch subagents. Ignore Devin/PR comments.
- **Tokens, not literals.** Every new colour hex lives in `Theme/CicadaTheme.swift`. Every font
  goes through `CicadaTheme.font(size:…)`, `displayFont` or `quoteFont`. Every dimension that
  should follow ⌘+/⌘− goes through `CicadaTheme.scaled(_:)`. Every duration lives in
  `CicadaMotion` (or `SleepMotion`). The lints this plan adds make each of these a build failure.
- **Sleep-safety and backend rails are untouched.** No backend file changes. **Portability:** no
  owner name and no author-machine path in shipped code, the manifest, docs, commits or the PR
  body.
- **App copy** is plain and friendly, with no jargon, prices or token counts. This track adds no
  service names to the UI, so no marks are needed. Where M2 names a service, it uses
  `OriginIconography`/`LogoImage`.
- Docstrings explain **why** and cite the G-row, ruling or measurement that motivated the rule,
  at the density of the files touched. **A doc comment must not contain a lint's needle unless
  that lint skips comment lines.** This plan's new lints skip `//` lines. The existing
  `.system(size:` lint does not.
- Line numbers above are from `f2d31ef` and drift as tasks land. Read the cited code before
  editing.
- Commit messages are named per task. End each with the attribution trailer your session's
  instructions give.

---

## Rulings (binding)

The spec's **R-M1 … R-M7** hold as written. The rulings below are decisions this plan takes where
the brief left a choice, each with its reason, so no task re-opens them.

- **R-M8: The accent moves with R9's table, and its old hex lives on only as frozen identity.**
  R9 §5.1 lists the accent among the re-tuned values (dark `#8C9CFF`, light `#4A5BD6`), and the
  brief binds that table. The measured reason for the move: the old light accent `#5A62E0` is
  **4.53:1** on the new `#F4F6F1`, one rounding step from failing AA, while `#4A5BD6` is **5.13:1**.
  The dark one is 7.46:1. `statusColor(.active)` and `heatRamp` *are* the accent by definition and
  follow it. The literal `0x8896FF`/`0x5A62E0` copies are **identity** colours: the clarification
  inbox hue, graph.js's `agent` observer badge, the mascot's zZ, and the share-sheet/saved-link/files
  tints. They stay byte-identical, because "data hues unchanged" (R-M1) includes them. Only the two
  comments that claim "= accent" are corrected (`graph.js:72`, `BookwormSprites.swift:29`).
- **R-M9: "The canvas background" is the SwiftUI detail background plus graph.js's painted twins,
  and a test reads the twin comments as a contract.** graph.js paints no background
  (`index.html:11`), so the canvas follows `CicadaTheme.background` for free. What graph.js *does*
  paint in a neutral is updated to the new values: label, plate, plateStrong, halo, plateText, edge
  and nodeStroke. Every one of them now carries a `// = Dark.x` / `// = Light.x` comment.
  `GraphPaletteTwinTests` parses those comments and fails if a twin drifts from its token. The same
  file pins `typeColors` to `CicadaTheme.entityColor` in dark mode. The "MUST stay byte-identical"
  comment has never been tested, and this is the retune that could break it. Dark `plateText`
  `#C7CBD6` is not a token twin (11.6:1 on the new plate) and stays as it is.
- **R-M10: One AppKit colour seam.** `CicadaTheme.windowBackground(for:)` returns the mode's
  `background` as an `NSColor`. `syncWindowChrome` calls it instead of hand-copying RGB, and
  `ThemeTokenTests` bans `NSColor(red:` outside the theme file. The copy is the reason the window
  and the page would have disagreed the moment the neutrals moved.
- **R-M11: `onAccent` is the ink for text on an accent fill, and the badge fill goes opaque.**
  The dark value is the background ink (`#0D1216`, 7.46:1 on the dark accent). The light value is
  white (5.59:1 on the light accent). The sidebar badge's `accent.opacity(0.8)` becomes plain
  `accent`: at 80% over glass the contrast is whatever the glass samples, and the measured number
  only holds on an opaque fill. `PrimaryActionButton`'s label uses the same token.
- **R-M12: The motion vocabulary is named by curve, and the migration is a table.** `CicadaMotion`
  offers `press` (easeOut 0.12), `hover` (easeInOut 0.15), `snap` (spring 0.2), `standard` (spring
  0.25), `panel` (spring 0.3), `expand` (spring 0.3 with bounce 0.15), `lift` (snappy 0.18),
  `settle` (easeInOut 0.35) and `morph` (smooth 0.35). All are ≤ `maxDuration` 0.4, and all return
  `nil` under Reduce Motion. The existing literals map onto it mechanically:
  - `.spring(duration: 0.25)` → `standard`.
  - `.spring(duration: 0.3, bounce: 0.15)` → `expand`.
  - `.spring(duration: 0.3)` → `panel`.
  - `.spring(duration: 0.2)` → `hover` when its value is `isHovered`, and `snap` otherwise.
  - `.spring(duration: 0.15)`, `.easeInOut(duration: 0.12)`, `.easeInOut(duration: 0.15)` and
    `.easeInOut(duration: 0.2)` → `hover`.
  - `.easeInOut(duration: 0.18)` → `snap`.
  - The press sites → `press`.

  Every timing moves by ≤ 50 ms. The **behaviour** change is deliberate: under Reduce Motion
  those 47 animations now jump to their end state, which is what R-M4 asks for. The lint's needle
  is any `duration:` in a non-comment line outside the two motion files, the same needle the Sleep
  lint has always used. The one escape hatch is a trailing `// motion-lint:ok — <reason>`, for a
  non-animation `duration:` label a future model might have. The planner dry-ran the substitution
  table on a copy of `Sources/`: it rewrites exactly **45** sites (17 `hover`, 11 `standard`, 9
  `panel`, 5 `snap`, 3 `expand`) and leaves only the two theme press sites, which are edited by
  hand. It is re-runnable, so a wave-1 branch that conflicts can re-apply it after merge.
- **R-M13: `iconHover` enforces Reduce Motion by not firing, not only by
  `symbolEffectsRemoved`.** R9 §9 flags the "symbol effects dampen automatically" claim as
  unverified. `symbolEffectsRemoved` removes *inherited* effects, and the direction of that is
  easy to get backwards. So the trigger counter simply never changes under Reduce Motion
  (`IconHover.nextBump`, tested), and `symbolEffectsRemoved(reduceMotion)` sits inside the effects
  as a second guard. There are two shapes of hover:
  - `iconHover()` tracks the glyph's own hover.
  - `iconHover(hovering:selected:)` is for a glyph inside a bigger hover target, such as a sidebar
    row. It wiggles on entry (macOS 15+, and bounces on 14) and bounces once when `selected`
    turns true.

  The two sidebar footer glyphs (gear, sun/moon) get it too: the owner asked for "animations to
  the icons as i hover over them", and they are icons in the one surface this track reskins.
- **R-M14: `hoverLift` caps its motion and keeps a cue that survives Reduce Motion.** The scale
  is at most 1.02 and the lift at most 2 pt, so text never looks soft mid-animation (R9 §3.2). The
  shadow deepens on hover even under Reduce Motion, when scale and lift are off. In M1 it goes on
  one thing only: the empty state's action, because it opens something. It never goes on dense
  rows (R9).
- **R-M15: Fonts register through CoreText from `Bundle.cicadaResources`' bare `fonts` directory
  in `App.init`.** `ATSApplicationFontsPath` would need `bundle.sh` to copy the TTFs into a second
  place.
  - `CicadaFonts.registerBundled(in:)` never throws. It returns the PostScript names that were
    found **in that bundle** and resolve afterwards. Error 105 (already registered) counts as
    success.
  - `displayFont(size:italic:)` is the **only** `.custom(` in the app (lint). It is scaled by
    `uiScale` and clamped to `displayMinimumSize` 22, so a misuse degrades to legible. A second
    lint fails on a literal `displayFont(size: N)` with N < 22.
  - `quoteFont` is New York italic (`design: .serif`): it ships with macOS, costs zero bytes and is
    optically sized for text.
  - `OFL.txt` ships beside the fonts inside the app bundle, which is what the OFL requires, with
    `FONTS.md` as the human-readable attribution. An About/Acknowledgements line is left to the
    Settings v3 track.
- **R-M16: The `PageHeader` title is `displayFont(size: 28)`, and the empty-state title is
  `displayFont(size: 26)`.** 28 pt sets the same width as the SF 20 semibold it replaces, within
  ±6% (measured above), so every call site keeps its line. The header gets about 13 pt taller: the
  ascender plus descender is 36.4 pt against 23.6. The narrowest host at 1.0× is the Settings
  detail column, 680 pt (`SettingsScene.windowWidth` 900 minus the 220 pt sidebar maximum). The
  longest static title, "Plans & keys", needs 119 pt there, and the ratio holds at 1.4× because
  both sides scale. The dynamic source-detail title is checked live by the orchestrator.
- **R-M17: The ⌘K Ask panel is not touched (except for its one motion literal).** Its content is
  one full-bleed opaque `surface` whose `ScrollView` fills the panel. Glass could only show behind
  the header strip without becoming glass on glass. Track S rebuilds ⌘K as a find palette in wave
  2 (spec Decision 7), and glass lands there once, in that design.
- **R-M18: The primary action has one style and one link.** `primaryActionStyle()` is
  `.glassProminent` on macOS 26 and `.borderedProminent` before, tinted `accent`, with the label in
  `onAccent`. `PrimaryActionButton` wraps it. `SettingsSectionLink` gains `prominent: Bool = false`:
  the default renders byte-identically for the Sleep page's schedule link, and the seed write stays
  in that one file. The empty state is the first consumer, because its one action *is* the page's
  one prominent action when the page is empty (Decision 6).
- **R-M19: The glass lint's needle list covers every glass API, and `LiquidGlassGroup` exists
  now.** The needles are `.glassEffect(`, `GlassEffectContainer`, `glassEffectID(`,
  `glassEffectUnion(`, `.glassProminent`, `.buttonStyle(.glass)`, `.buttonStyle(.glass(` and
  `.backgroundExtensionEffect(`. They are allowed only in `Theme/LiquidGlass.swift`, and comment
  lines are skipped. `LiquidGlassGroup` (`GlassEffectContainer` on 26, plain content before) ships
  in M1 so that M2's graph controls never need to edit the lint. `GlassCard` keeps its name and stays
  a material card, with a doc line saying so (R-M5).
- **R-M20: Art processing is fixed, and a missing input BLOCKS rather than being invented.**
  - **Sizes.** Every file is authored at 2× its largest drawn size. Clouds are capped at 800 px on
    the longest side and grass corners at 640 px. The grass edge is ≤ 240 px tall and ≤ 2400 px
    wide. The hero is capped at 2400 px.
  - **Formats and pairs.** The hero ships as **JPEG q82** because it is opaque: `hero-day.jpg` and
    `hero-day-dark.jpg`, about 200 KB each against about 1.9 MB as PNG (measured on a work-in-progress
    file). Everything else is PNG with alpha. A dark sibling is resized to exactly its light twin's
    pixel size, so a theme flip never moves the layout. An aspect mismatch over 2% BLOCKS.
  - **Budget.** RGBA PNGs are quantized to 256 colours (FASTOCTREE with Floyd–Steinberg, which
    keeps alpha, as measured) **only while the total exceeds the 4 MiB cap**, largest first. The
    target is R9's 2.5 MB aim, and the cap is 4 MiB.
  - **The script** stays in `<scratch>`: the art is generated once, and a committed script with no
    inputs in the repo would be dead code. The `processing` field records exactly what it did to
    each file.
  - **Manifest.** Each entry carries id, file, variant, role, pairsWith, generator, prompt, date,
    licence, processing and sha256. The licence line is "MIT, as this repository (see LICENSE).
    Generated for Cicada; no third-party artwork or brand marks." The generator defaults to "OpenAI
    image generation through the Codex CLI (codex exec)" only when a jsonl line names none, because
    both generation scripts show that tool.
  - **BLOCKED.** A missing input file, a missing prompt, or a prompt carrying a URL or handle
    BLOCKS the task.
- **R-M21: Art placement is a lint, not a comment.** `MeadowPlacementLintTests` allows the
  components to be named only under `Views/Meadow/` and in an explicit allowlist, which in M1 is
  just `Views/Common/EmptyStateView.swift`. Adding a file is a reviewed act, the same shape as the
  Sleep lint's noun list. The rule text ("never on the graph, a list, a grid, a form or a number;
  text never directly on paint") heads `MeadowBackdrop.swift`.
- **R-M22: Drift and opacity rules.** A cloud's drift pauses under Reduce Motion **and whenever
  the window is not key** (`controlActiveState != .key`). R-M6 says "inactive windows", and a
  window you are not looking at is inactive from the reader's side. Cloud opacity is 0.85 in light
  mode and 0.4 in dark (R9's "moon cloud ≤ 40%"). Grass is 1.0. Under Increase Contrast, all art is
  capped at 0.3 (R9 §7). These are pure `MeadowRules` functions pinned by `MeadowTests`, so tuning
  one after the live check is a one-line change.
- **R-M23: In the empty state, the words go on a card and the worm stays in front.** The title,
  message and action sit on a `surface` card with `radiusLarge` and a hairline border, so a grass
  corner reaching under them in a short window is behind a card, not behind a sentence. The
  message moves from `textTertiary` to `textSecondary` (7.78:1 on white): it is a sentence a person
  reads, not decoration. The cloud is wider than the worm (it reads as sky) but at most twice as
  wide (it never reads as a second character), and sits behind the worm's head. The pixel worm
  (`.interpolation(.none)`) and the painted cloud (`.high`) share a frame by the owner's brief. R9
  §5.3's "don't mix" is about the Sleep room's lattice.
- **R-M24: `bundle.sh` promises 14.0.** `PlatformFloorTests` holds the plist floor equal to the
  `Package.swift` floor, so the `#available` gates and the plist cannot disagree again.
- **R-M25: G137 goes directly after the G132 row** at `memory-evolution.md:694`, in the same
  table. Other round-3 tracks may add G133–G136 on their own branches. Merge order resolves that,
  and ids are never renumbered.

---

## File map

| File | Responsibility |
|---|---|
| `app/…/Theme/CicadaTheme.swift` | Meadow neutrals, `onAccent`, nature tokens, `SkyPhase` + `skyGradient`, `radiusXS`/`radiusLarge`, `windowBackground(for:)`, the two corrected contrast comments (T1); button styles on `CicadaMotion.press` (T2); `displayMinimumSize`, `displayFont`, `quoteFont` (T3); `GlassCard` doc line (T4) |
| `app/…/Theme/CicadaMotion.swift` (new) | `CicadaMotion`, `HoverLift`, `IconHover`, `hoverLift()`, `iconHover(hovering:selected:)` (T2) |
| `app/…/Theme/CicadaFonts.swift` (new) | `CicadaFonts` names + `registerBundled(in:)` (T3) |
| `app/…/Theme/LiquidGlass.swift` (new) | `GlassLevel`, `LiquidGlass` rules, `liquidGlass(_:in:)`, `LiquidGlassGroup`, `primaryActionStyle()`, `PrimaryActionButton`, `sidebarChromeBackground()` (T4) |
| `app/…/Views/Meadow/MeadowArt.swift` (new) | `MeadowArt`, `MeadowRules`, `ArtImage` (T5) |
| `app/…/Views/Meadow/MeadowBackdrop.swift` (new) | `MeadowSky`, `DriftingCloud`, `GrassCorners`, `GrassEdge`, `MeadowBackdrop` (T5) |
| `app/…/Resources/fonts/` (new) | `InstrumentSerif-Regular.ttf`, `InstrumentSerif-Italic.ttf`, `OFL.txt`, `FONTS.md` (T3) |
| `app/…/Resources/art/` (new) | 14 paintings + `art.manifest.json` (T5) |
| `app/…/CicadaApp.swift` | `windowBackground(for:)` (T1); `CicadaFonts.registerBundled()` in `init` (T3) |
| `app/…/Resources/graph/graph.js` | twin values + comments, identity comment (T1) |
| `app/…/MenuBar/BookwormSprites.swift` | comment only (T1) |
| 12 view files (list in T2) | literal durations → `CicadaMotion` + `@Environment(\.accessibilityReduceMotion)` (T2) |
| `app/…/Views/Common/PageHeader.swift` | display serif title (T3) |
| `app/…/Views/Sidebar/SidebarView.swift` | glass-through background, `iconHover` on glyphs, `onAccent` badge (T4) |
| `app/CicadaApp/bundle.sh` | `LSMinimumSystemVersion 14.0` (T4) |
| `app/…/Views/Common/EmptyStateView.swift` | grass corners, cloud, display title, card, prominent lifting action, `EmptyStateLayout` (T6) |
| `app/…/Views/Common/SettingsSectionLink.swift` | `prominent:` (T6) |
| Tests (Swift, new) | `GraphPaletteTwinTests`, `CicadaMotionTests`, `MotionLiteralLintTests`, `CicadaFontsTests`, `LiquidGlassLintTests`, `SidebarChromeTests`, `PlatformFloorTests`, `ArtAssetTests`, `MeadowTests`, `MeadowPlacementLintTests` |
| Tests (Swift, edited) | `ThemeTokenTests`, `FontLiteralLintTests`, `EmptyStateViewTests`; comments in `LogoAssetTests:8`, `LogoImageTests:44` |
| Tests (JS, edited) | `app/CicadaApp/Tests/graph/graph-theme.test.js` |
| Docs | `docs/goals/memory-evolution.md` (G137), `CLAUDE.md` (Companion App), `docs/goals/TODO.md` (T7) |

`app/…` = `app/CicadaApp/Sources/CicadaApp`.

**What M1 hands to wave 2** (and the only API those tracks should need): the tokens (`sky`… `soil`,
`skyGradient`, `onAccent`, radii); `displayFont`/`quoteFont`; `CicadaMotion.*`, `hoverLift()`,
`iconHover(…)`; `liquidGlass(_:in:)`, `LiquidGlassGroup`, `primaryActionStyle()`,
`PrimaryActionButton`; `MeadowArt`, `ArtImage`, `MeadowSky`, `DriftingCloud`, `GrassCorners`,
`GrassEdge`, `MeadowBackdrop`. A wave-2 surface that draws art adds its file to
`MeadowPlacementLintTests.allowed` in its own diff.

---

### Task 1: Day-meadow and night-meadow neutrals, nature tokens, sky gradients (R-M1, R-M2)

Every colour decision becomes a token pinned by a table test, and every place that hand-copied a
neutral (the window, graph.js) is tied to the token by a test. No view changes.

**Files:**
- Modify: `app/…/Theme/CicadaTheme.swift` (`:1-2` imports, `:97-130` accessors, `:143-147` entity-colour comment, `:254-256` radii, `:281-495` palettes + comments)
- Modify: `app/…/CicadaApp.swift:252-262`
- Modify: `app/…/Resources/graph/graph.js:19, :72, :76-107`
- Modify: `app/…/MenuBar/BookwormSprites.swift:29` (comment)
- Modify: `app/CicadaApp/Tests/CicadaAppTests/ThemeTokenTests.swift`
- Create: `app/CicadaApp/Tests/CicadaAppTests/GraphPaletteTwinTests.swift`
- Modify: `app/CicadaApp/Tests/graph/graph-theme.test.js` (after `:38`)
- Modify: `app/CicadaApp/Tests/CicadaAppTests/LogoAssetTests.swift:8`, `LogoImageTests.swift:44` (comments: `#23252E` → `#20292F`)

**Interfaces:**
- Produces: `CicadaTheme.onAccent`, `.sky`, `.skyWash`, `.meadow`, `.meadowWash`, `.dandelion`, `.dandelionFill`, `.cloud`, `.bark`, `.soil`; `CicadaTheme.SkyPhase` (`day|dusk|night`, `static var current`); `CicadaTheme.skyGradient(_:) -> [Color]`; `CicadaTheme.radiusXS` (4), `.radiusLarge` (18); `CicadaTheme.windowBackground(for: AppColorScheme) -> NSColor`.
- Consumes: nothing new.

- [ ] **Step 1: Failing tests.** Append the following to `ThemeTokenTests` (inside the class,
  after `swiftSources()`):

```swift
    // MARK: - G137 Meadow (spec R-M1/R-M2; plan R-M8 … R-M11)

    /// WCAG 2.x contrast between two opaque colours — the formula R9 §5.1's
    /// table was computed with, so the bars below are the table's own numbers.
    static func contrast(_ a: Color, _ b: Color) -> Double {
        func luminance(_ c: Color) -> Double {
            guard let ns = NSColor(c).usingColorSpace(.sRGB) else { return 0 }
            func channel(_ v: CGFloat) -> Double {
                let v = Double(v)
                return v <= 0.03928 ? v / 12.92 : pow((v + 0.055) / 1.055, 2.4)
            }
            return 0.2126 * channel(ns.redComponent) + 0.7152 * channel(ns.greenComponent)
                + 0.0722 * channel(ns.blueComponent)
        }
        let (x, y) = (luminance(a), luminance(b))
        return (max(x, y) + 0.05) / (min(x, y) + 0.05)
    }

    /// `fg` at `alpha` over an opaque `bg` — where a 35 % highlighter wash
    /// actually lands under a word.
    static func blend(_ fg: Color, over bg: Color, alpha: Double) -> Color {
        let f = NSColor(fg).usingColorSpace(.sRGB)!, b = NSColor(bg).usingColorSpace(.sRGB)!
        func mix(_ x: CGFloat, _ y: CGFloat) -> Double { Double(x) * alpha + Double(y) * (1 - alpha) }
        return Color(.sRGB, red: mix(f.redComponent, b.redComponent),
                     green: mix(f.greenComponent, b.greenComponent),
                     blue: mix(f.blueComponent, b.blueComponent))
    }

    private struct Row {
        let name: String
        let read: () -> Color
        let dark: UInt32
        let light: UInt32
    }

    /// Every Meadow token, both modes, exactly as the spec's table spells it.
    /// Changing one is a design decision: edit this table in the same commit,
    /// on purpose.
    func testMeadowTokensAreTheRulingsValues() {
        let rows: [Row] = [
            Row(name: "background", read: { CicadaTheme.background }, dark: 0x0D1216, light: 0xF4F6F1),
            Row(name: "surface", read: { CicadaTheme.surface }, dark: 0x141A1F, light: 0xFFFFFF),
            Row(name: "surfaceHover", read: { CicadaTheme.surfaceHover }, dark: 0x1A2227, light: 0xECF0E8),
            Row(name: "surfaceElevated", read: { CicadaTheme.surfaceElevated }, dark: 0x20292F, light: 0xFFFFFF),
            Row(name: "border", read: { CicadaTheme.border }, dark: 0x25303A, light: 0xDFE4D9),
            Row(name: "borderLight", read: { CicadaTheme.borderLight }, dark: 0x35424D, light: 0xC5CCBC),
            Row(name: "textPrimary", read: { CicadaTheme.textPrimary }, dark: 0xE8EEE9, light: 0x1B1F1A),
            Row(name: "textSecondary", read: { CicadaTheme.textSecondary }, dark: 0x9CA8A0, light: 0x4C5548),
            Row(name: "textTertiary", read: { CicadaTheme.textTertiary }, dark: 0x6E7A73, light: 0x767E70),
            Row(name: "accent", read: { CicadaTheme.accent }, dark: 0x8C9CFF, light: 0x4A5BD6),
            Row(name: "onAccent", read: { CicadaTheme.onAccent }, dark: 0x0D1216, light: 0xFFFFFF),
            Row(name: "codeBackground", read: { CicadaTheme.codeBackground }, dark: 0x0A0E11, light: 0xE8ECE3),
            Row(name: "sky", read: { CicadaTheme.sky }, dark: 0x8EC3F0, light: 0x3571B0),
            Row(name: "skyWash", read: { CicadaTheme.skyWash }, dark: 0x1A2B3D, light: 0xD7E8F5),
            Row(name: "meadow", read: { CicadaTheme.meadow }, dark: 0x7FC98A, light: 0x37753D),
            Row(name: "meadowWash", read: { CicadaTheme.meadowWash }, dark: 0x1B2B22, light: 0xDCEBD6),
            Row(name: "dandelion", read: { CicadaTheme.dandelion }, dark: 0xF6CF5A, light: 0x8A6400),
            Row(name: "dandelionFill", read: { CicadaTheme.dandelionFill }, dark: 0xD9A92E, light: 0xF5C542),
            Row(name: "cloud", read: { CicadaTheme.cloud }, dark: 0xC9D3DE, light: 0xFFFFFF),
            Row(name: "bark", read: { CicadaTheme.bark }, dark: 0xB89C86, light: 0x6B5344),
            Row(name: "soil", read: { CicadaTheme.soil }, dark: 0x2A221E, light: 0x3B2F2A),
        ]
        for row in rows {
            let got = token(row.name, row.read)
            XCTAssertEqual(got.dark, rgb(Color(hex: row.dark)), "\(row.name) (dark)")
            XCTAssertEqual(got.light, rgb(Color(hex: row.light)), "\(row.name) (light)")
            XCTAssertNotEqual(got.dark, got.light, "\(row.name) is the same colour in both modes")
        }
        XCTAssertEqual(CicadaTheme.radiusXS, 4)
        XCTAssertEqual(CicadaTheme.radiusLarge, 18)
    }

    /// The contrast table (R9 §5.1) as bars, both modes. Measured values on
    /// this base: textPrimary 15.99 / 15.35, textSecondary 7.64 / 7.15,
    /// accent 7.46 / 5.13, onAccent-on-accent 7.46 / 5.59, highlighter wash
    /// 7.18 / 14.1 (dark / light).
    func testTheMeadowContrastBarsHold() {
        for mode in [AppColorScheme.dark, .light] {
            CicadaTheme.mode = mode
            let bg = CicadaTheme.background
            let m = mode.rawValue
            XCTAssertGreaterThanOrEqual(Self.contrast(CicadaTheme.textPrimary, bg), 15, "\(m) textPrimary")
            XCTAssertGreaterThanOrEqual(Self.contrast(CicadaTheme.textSecondary, bg), 7, "\(m) textSecondary")
            XCTAssertGreaterThanOrEqual(Self.contrast(CicadaTheme.accent, bg), 5, "\(m) accent")
            XCTAssertGreaterThanOrEqual(Self.contrast(CicadaTheme.onAccent, CicadaTheme.accent), 4.5,
                                        "\(m) onAccent on accent")
            let textSafe: [(String, Color)] = [("sky", CicadaTheme.sky), ("meadow", CicadaTheme.meadow),
                                               ("dandelion", CicadaTheme.dandelion), ("bark", CicadaTheme.bark)]
            for (name, color) in textSafe {
                XCTAssertGreaterThanOrEqual(Self.contrast(color, bg), 4.5, "\(m) \(name) is sold as text-safe")
            }
            let wash = Self.blend(CicadaTheme.dandelionFill, over: CicadaTheme.surface, alpha: 0.35)
            XCTAssertGreaterThanOrEqual(Self.contrast(CicadaTheme.textPrimary, wash), 7, "\(m) highlighter wash")
        }
    }

    /// Keeps the Light-palette comment honest: it used to promise ~4.5:1 for
    /// every light entity hue, and skill measured 2.93. Deepening a hue is a
    /// data-colour decision graph.js must match — do it, then move it here.
    func testLightEntityHueContrastIsWhatTheThemeCommentSays() {
        CicadaTheme.mode = .light
        let bg = CicadaTheme.background
        func c(_ t: EntityType) -> Double { Self.contrast(CicadaTheme.entityColor(for: t), bg) }
        for t in [EntityType.person, .project, .directory] {
            XCTAssertGreaterThanOrEqual(c(t), 4.5, "\(t.rawValue) is documented as text-safe")
        }
        for t in [EntityType.location, .media, .deadline, .hub, .tool, .concept, .company] {
            XCTAssertTrue((3.0..<4.5).contains(c(t)), "\(t.rawValue) \(c(t)) is documented as non-text only")
        }
        XCTAssertLessThan(c(.skill), 3.0, "skill is documented as clearing neither bar")
    }

    func testSkyGradientsAreTheRulingsStopsAndKeepTextLegible() {
        XCTAssertEqual(CicadaTheme.skyGradient(.day).map { rgb($0) },
                       [0xB9D7F0, 0xE9F2F6].map { rgb(Color(hex: $0)) })
        XCTAssertEqual(CicadaTheme.skyGradient(.dusk).map { rgb($0) },
                       [0x1C2344, 0x3A3A6A, 0x7A5E7E].map { rgb(Color(hex: $0)) })
        XCTAssertEqual(CicadaTheme.skyGradient(.night).map { rgb($0) },
                       [0x0A0F1E, 0x172538].map { rgb(Color(hex: $0)) })
        CicadaTheme.mode = .light
        XCTAssertEqual(CicadaTheme.SkyPhase.current, .day)
        XCTAssertGreaterThanOrEqual(Self.contrast(CicadaTheme.textPrimary, CicadaTheme.skyGradient(.day)[0]), 11)
        CicadaTheme.mode = .dark
        XCTAssertEqual(CicadaTheme.SkyPhase.current, .night)
        XCTAssertGreaterThanOrEqual(Self.contrast(CicadaTheme.textPrimary, CicadaTheme.skyGradient(.dusk)[2]), 4.5)
        XCTAssertGreaterThanOrEqual(Self.contrast(CicadaTheme.textPrimary, CicadaTheme.skyGradient(.night)[1]), 13)
    }

    func testTheWindowBackgroundIsTheBackgroundToken() {
        for mode in [AppColorScheme.dark, .light] {
            CicadaTheme.mode = mode
            let window = CicadaTheme.windowBackground(for: mode).usingColorSpace(.sRGB)!
            XCTAssertEqual([window.redComponent, window.greenComponent, window.blueComponent],
                           rgb(CicadaTheme.background), mode.rawValue)
        }
    }

    /// The window's RGB was hand-copied from the old neutrals — the copy is
    /// what would have left a violet titlebar over a meadow page (R-M10).
    func testNoWindowColourIsHandCopied() throws {
        for file in try Self.swiftSources() where file.lastPathComponent != "CicadaTheme.swift" {
            XCTAssertFalse(try String(contentsOf: file, encoding: .utf8).contains("NSColor(red:"),
                           "\(file.lastPathComponent) hand-copies a colour into AppKit — "
                           + "read CicadaTheme.windowBackground(for:) (G137 R-M10)")
        }
    }
```

  Create `GraphPaletteTwinTests.swift`:

```swift
import AppKit
import SwiftUI
import XCTest
@testable import CicadaApp

/// G137 R-M9 — graph.js draws on a TRANSPARENT page (`index.html`) over the
/// SwiftUI `background`, so the only neutrals it owns are the ones it paints
/// itself: label ink, the plate behind a label, the halo, the contextless
/// edge, the node stroke. Each is a hand-copied twin of a theme token and
/// says so with a `// = Dark.x` / `// = Light.x` comment (Track P). The
/// Meadow retune is the first time every neutral moved at once, and a twin
/// that silently kept the old violet ink is exactly the drift a comment
/// cannot prevent — so this reads the comments as a contract.
final class GraphPaletteTwinTests: XCTestCase {
    override func tearDown() {
        CicadaTheme.mode = .dark
        super.tearDown()
    }

    private func graphJS() throws -> String {
        let url = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()   // CicadaAppTests
            .deletingLastPathComponent()   // Tests
            .deletingLastPathComponent()   // CicadaApp (package root)
            .appendingPathComponent("Sources/CicadaApp/Resources/graph/graph.js")
        return try String(contentsOf: url, encoding: .utf8)
    }

    /// `#RRGGBB` or `rgb(a)(r, g, b[, a])` → 0–255 channels.
    private func channels(css: String) -> [Int]? {
        if css.hasPrefix("#"), css.count == 7, let v = Int(css.dropFirst(), radix: 16) {
            return [(v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF]
        }
        guard css.hasPrefix("rgb") else { return nil }
        let inner = css.drop(while: { $0 != "(" }).dropFirst().prefix(while: { $0 != ")" })
        let ints = inner.split(separator: ",").prefix(3)
            .compactMap { Int($0.trimmingCharacters(in: .whitespaces)) }
        return ints.count == 3 ? ints : nil
    }

    private func channels(_ color: Color) -> [Int] {
        let ns = NSColor(color).usingColorSpace(.sRGB)!
        return [ns.redComponent, ns.greenComponent, ns.blueComponent].map { Int(($0 * 255).rounded()) }
    }

    private let tokens: [String: () -> Color] = [
        "background": { CicadaTheme.background }, "surface": { CicadaTheme.surface },
        "textPrimary": { CicadaTheme.textPrimary }, "textSecondary": { CicadaTheme.textSecondary },
        "border": { CicadaTheme.border }, "borderLight": { CicadaTheme.borderLight },
    ]

    func testEveryDeclaredPaletteTwinMatchesItsThemeToken() throws {
        let twin = try NSRegularExpression(
            pattern: #"^\s*\w+:\s*"([^"]+)",\s*// = (?:CicadaTheme\.)?(Dark|Light)\.(\w+)"#)
        var checked = 0
        for line in try graphJS().components(separatedBy: .newlines) {
            let ns = line as NSString
            guard let m = twin.firstMatch(in: line, range: NSRange(location: 0, length: ns.length)) else { continue }
            let css = ns.substring(with: m.range(at: 1))
            let mode: AppColorScheme = ns.substring(with: m.range(at: 2)) == "Dark" ? .dark : .light
            let name = ns.substring(with: m.range(at: 3))
            let read = try XCTUnwrap(tokens[name], "graph.js declares a twin of `\(name)`, which this test does not know")
            CicadaTheme.mode = mode
            XCTAssertEqual(channels(css: css), channels(read()),
                           "graph.js `\(line.trimmingCharacters(in: .whitespaces))` drifted from \(mode.rawValue).\(name)")
            checked += 1
        }
        XCTAssertGreaterThanOrEqual(checked, 11, "found \(checked) twins — the comment convention moved and this would pass vacuously")
    }

    /// `typeColors` "MUST stay byte-identical to CicadaTheme.entityColor(for:)"
    /// — untested until now, and data hues are the one thing the Meadow retune
    /// promises not to move (R-M1).
    func testGraphTypeColorsAreTheDarkEntityHues() throws {
        let js = try graphJS()
        let start = try XCTUnwrap(js.range(of: "const typeColors = {"))
        let end = try XCTUnwrap(js.range(of: "};", range: start.upperBound..<js.endIndex))
        let entry = try NSRegularExpression(pattern: #"^\s*(\w+):\s*"(#[0-9A-Fa-f]{6})""#)
        CicadaTheme.mode = .dark
        var checked = 0
        for line in js[start.upperBound..<end.lowerBound].components(separatedBy: .newlines) {
            let ns = line as NSString
            guard let m = entry.firstMatch(in: line, range: NSRange(location: 0, length: ns.length)),
                  let type = EntityType(rawValue: ns.substring(with: m.range(at: 1))) else { continue }
            XCTAssertEqual(channels(css: ns.substring(with: m.range(at: 2))), channels(CicadaTheme.entityColor(for: type)),
                           "graph.js typeColors.\(type.rawValue) drifted from CicadaTheme.entityColor")
            checked += 1
        }
        XCTAssertEqual(checked, EntityType.allCases.count, "graph.js typeColors should name every EntityType")
    }
}
```

  In `graph-theme.test.js`, after `:38` (`assert.notDeepStrictEqual(…)`), insert:

```js
// G137 — the Meadow retune moved every neutral: the plate is the night-meadow
// background (#0D1216) and the light label is the day-meadow text ink
// (#1B1F1A, Light.textPrimary — not the `soil` token). The Swift side
// (GraphPaletteTwinTests) holds every `// = Dark.x` twin to the theme; these
// two pins keep this file honest on its own.
assert.ok(palettes.dark.plate.startsWith("rgba(13, 18, 22,"),
          `the dark plate is not the night-meadow background: ${palettes.dark.plate}`);
assert.strictEqual(palettes.light.label, "#1B1F1A", "the light label is not Light.textPrimary");
```

  Run `cd <worktree>/app/CicadaApp && swift test --filter 'ThemeTokenTests|GraphPaletteTwinTests' 2>&1 | tail -20`.
  Expect a compile failure: `onAccent`, `sky`, `SkyPhase` and `windowBackground` do not exist.
  That is the red. `node --test` on `graph-theme.test.js` also fails on the new pins.

- [ ] **Step 2: Implement the theme.** In `CicadaTheme.swift`:
  1. Add `import AppKit` after `import Observation`.
  2. After `codeBackground` (`:130`), add:

```swift
    // MARK: - Text on the accent (G137, plan R-M11)
    /// Ink for text drawn ON an accent fill — the sidebar badge, a prominent
    /// button's label. The badge used a literal `.white`, which is 2.53:1 on
    /// this dark accent (and ~3.9:1 on the old one at 80 %); the background
    /// ink is 7.46:1 there, and white is 5.59:1 on the light accent
    /// (ThemeTokenTests pins both).
    static var onAccent: Color { mode == .dark ? Dark.onAccent : Light.onAccent }

    // MARK: - Meadow nature tokens (G137, spec R-M2)
    // Ambient ONLY: washes, art, onboarding / empty-state / header bands.
    // NEVER a data encoding — a sunnier meadow must never mean "more
    // memories" (R9 §7, G125's "art encodes state, never quantity"). The four
    // text-safe tokens (sky, meadow, dandelion, bark) clear 4.5:1 on
    // `background` in both modes; the washes, `dandelionFill`, `cloud` and
    // `soil` are fills and imagery, never text.
    static var sky: Color { mode == .dark ? Dark.sky : Light.sky }
    static var skyWash: Color { mode == .dark ? Dark.skyWash : Light.skyWash }
    static var meadow: Color { mode == .dark ? Dark.meadow : Light.meadow }
    static var meadowWash: Color { mode == .dark ? Dark.meadowWash : Light.meadowWash }
    static var dandelion: Color { mode == .dark ? Dark.dandelion : Light.dandelion }
    /// A highlighter behind words, used at 35 % — textPrimary over that wash
    /// is 7.18:1 in dark and 14.1:1 in light (ThemeTokenTests).
    static var dandelionFill: Color { mode == .dark ? Dark.dandelionFill : Light.dandelionFill }
    static var cloud: Color { mode == .dark ? Dark.cloud : Light.cloud }
    static var bark: Color { mode == .dark ? Dark.bark : Light.bark }
    static var soil: Color { mode == .dark ? Dark.soil : Light.soil }

    /// The three procedural skies (R-M2): zero bytes, so night costs nothing.
    /// Mode-INDEPENDENT on purpose — a caller may put a dusk band in a light
    /// window — with `current` as the default that follows the theme.
    enum SkyPhase: CaseIterable {
        case day, dusk, night

        /// Day in a light window, night in a dark one. Read in a `body`, this
        /// subscribes the view to the theme like every other token.
        static var current: SkyPhase { CicadaTheme.mode == .dark ? .night : .day }
    }

    /// Top-to-bottom stops. Text contrast on the extreme stops (measured):
    /// light ink on day's top 11.2:1, moonlit ink on dusk's horizon 4.78:1,
    /// on night ≥ 13:1.
    static func skyGradient(_ phase: SkyPhase) -> [Color] {
        switch phase {
        case .day: [Color(hex: 0xB9D7F0), Color(hex: 0xE9F2F6)]
        case .dusk: [Color(hex: 0x1C2344), Color(hex: 0x3A3A6A), Color(hex: 0x7A5E7E)]
        case .night: [Color(hex: 0x0A0F1E), Color(hex: 0x172538)]
        }
    }

    /// The window's AppKit background for `mode` — the one place `NSWindow`
    /// gets a theme colour (R-M10). Takes the mode explicitly because
    /// `syncWindowChrome` runs for the mode being switched TO.
    static func windowBackground(for mode: AppColorScheme) -> NSColor {
        NSColor(mode == .dark ? Dark.background : Light.background)
    }
```

  3. Replace the radii block (`:254-256`) with:

```swift
    // MARK: - Corner Radius
    static let cornerRadius: CGFloat = 12
    static let cornerRadiusSmall: CGFloat = 8
    /// G137: chips.
    static let radiusXS: CGFloat = 4
    /// G137: sheets, panels, the empty state's card, art panels.
    static let radiusLarge: CGFloat = 18
```

  4. Replace the Dark palette header comment (`:281-284`) with:

```swift
// MARK: - Dark Palette
// G137 "night meadow" (spec R-M1, R9 §5.1): the violet-cast near-black
// (#0E0F14) became a blue-green ink of the same luminance class, so the graph
// keeps its pop — the d3 page is transparent and every node sits directly on
// `background`. Same Radix-style 4-step elevation ramp. Entity, state,
// context, status and inbox hues are DATA and did not move; graph.js mirrors
// them (GraphPaletteTwinTests).
```

  5. In `enum Dark`, replace `background` … `codeBackground` (`:290-312`) with the lines below.
     Keep the `// Darkening the canvas…` comment above `background`, and keep the state hues
     (`success`, `warning`, `danger`, `info`) and their comment exactly as they are:

```swift
        static let background = Color(hex: 0x0D1216)
        static let surface = Color(hex: 0x141A1F)
        static let surfaceHover = Color(hex: 0x1A2227)
        static let surfaceElevated = Color(hex: 0x20292F)
        static let border = Color(hex: 0x25303A)
        static let borderLight = Color(hex: 0x35424D)

        // Measured on #0D1216 (ThemeTokenTests holds the bars): primary
        // 15.99:1 (AAA), secondary 7.64:1, tertiary 4.21:1 (decorative/large).
        static let textPrimary = Color(hex: 0xE8EEE9)
        static let textSecondary = Color(hex: 0x9CA8A0)
        static let textTertiary = Color(hex: 0x6E7A73)

        // Cornflower, 7.46:1 on background (plan R-M8). The pre-G137 #8896FF
        // survives only as frozen IDENTITY colours (the clarification inbox
        // hue, graph.js's agent badge, the mascot's zZ) — never re-point them.
        static let accent = Color(hex: 0x8C9CFF)
        static let onAccent = background

        // (success / warning / danger / info — unchanged, keep as they are)

        static let codeBackground = Color(hex: 0x0A0E11)

        // Nature (R-M2) — ambient only, never data.
        static let sky = Color(hex: 0x8EC3F0)
        static let skyWash = Color(hex: 0x1A2B3D)
        static let meadow = Color(hex: 0x7FC98A)
        static let meadowWash = Color(hex: 0x1B2B22)
        static let dandelion = Color(hex: 0xF6CF5A)
        static let dandelionFill = Color(hex: 0xD9A92E)
        static let cloud = Color(hex: 0xC9D3DE)
        static let bark = Color(hex: 0xB89C86)
        static let soil = Color(hex: 0x2A221E)
```

  The `// (success …)` line marks where the existing four state lines stay. Do not add that line.

  6. Replace the Light palette comment (`:395-401`) with the measured truth:

```swift
// MARK: - Light Palette
// G137 "day meadow" (spec R-M1): cloud-white surfaces on a faint green paper
// (#F4F6F1), green-black ink text, and the same deepened entity/status hues
// as before — data hues are untouched by the Meadow retune (graph.js mirrors
// them).
//
// Measured, not assumed (WCAG 2.x, on #F4F6F1; the old #F5F6FA was within
// 0.04 of every number, and there location sat at 4.52, just over the text
// bar). Only person 4.82, project 4.97 and directory 4.91 clear
// 4.5:1 and may be used as text. location 4.49, media 4.02, deadline 3.83,
// hub 3.76, tool 3.44, concept 3.33 and company 3.32 clear only the 3:1
// non-text bar — dots, rings and fills, not body text. skill (#B48A00) is
// 2.93 and clears neither: never text, never an indicator without a label.
// This comment used to promise ~4.5:1 for all of them.
// `ThemeTokenTests.testLightEntityHueContrastIsWhatTheThemeCommentSays` now
// holds it to the numbers. Deepening them is a separate data-colour decision
// graph.js must match.
```

  7. In `enum Light`, replace `background` … `codeBackground` (`:408-432`) in the same way. Keep
     the elevation-ramp comment above `background`, and keep the four state hues with their
     `// Same families, deepened into the Tailwind ~700 band…` comment exactly as they are:

```swift
        static let background = Color(hex: 0xF4F6F1)
        static let surface = Color(hex: 0xFFFFFF)
        static let surfaceHover = Color(hex: 0xECF0E8)
        static let surfaceElevated = Color(hex: 0xFFFFFF)
        static let border = Color(hex: 0xDFE4D9)
        static let borderLight = Color(hex: 0xC5CCBC)

        // Measured on #F4F6F1: primary 15.35:1 (AAA), secondary 7.15:1,
        // tertiary 3.87:1 (decorative/large only, as before).
        static let textPrimary = Color(hex: 0x1B1F1A)
        static let textSecondary = Color(hex: 0x4C5548)
        static let textTertiary = Color(hex: 0x767E70)

        // 5.13:1 on the day-meadow paper; the pre-G137 #5A62E0 measured
        // 4.53:1 there, one rounding step from failing AA (plan R-M8).
        static let accent = Color(hex: 0x4A5BD6)
        static let onAccent = Color(hex: 0xFFFFFF)

        // (success / warning / danger / info — unchanged, keep as they are)

        static let codeBackground = Color(hex: 0xE8ECE3)

        // Nature (R-M2) — ambient only, never data.
        static let sky = Color(hex: 0x3571B0)
        static let skyWash = Color(hex: 0xD7E8F5)
        static let meadow = Color(hex: 0x37753D)
        static let meadowWash = Color(hex: 0xDCEBD6)
        static let dandelion = Color(hex: 0x8A6400)
        static let dandelionFill = Color(hex: 0xF5C542)
        static let cloud = Color(hex: 0xFFFFFF)
        static let bark = Color(hex: 0x6B5344)
        static let soil = Color(hex: 0x3B2F2A)
```

  8. The `// MARK: - Entity Type Colors` comment above `entityColor(for:)` (`:143-147`) repeats
     the ~4.5:1 promise. Replace its four prose lines, keeping the MARK line, with:

```swift
    // Mirrors the `typeColors` map in graph.js so the SwiftUI chrome and the d3
    // canvas agree on hue per type (GraphPaletteTwinTests holds the dark
    // values). Light mode reuses the same hue family, deepened into the
    // Tailwind ~600 band; which of those clear 4.5:1 as text and which are
    // non-text only is measured in the Light palette's comment (G137).
```

- [ ] **Step 3: The window.** In `CicadaApp.swift` `syncWindowChrome` (`:252-262`), delete the two
  `window.backgroundColor = NSColor(red: …)` lines. After the `switch` (which now only sets
  `window.appearance`), add:

```swift
        // G137 R-M10: the one AppKit surface that paints a theme colour reads
        // the token — the hand-copied RGB that was here went stale the moment
        // the neutrals moved.
        window.backgroundColor = CicadaTheme.windowBackground(for: mode)
```

- [ ] **Step 4: graph.js twins.** Replace the `PALETTES` object (`:88-107`) with the block below.
  Change `:19`'s "on the darker #0E0F14 base" to "on the darker #0D1216 (G137 night meadow)
  base". In the Track P comment, change the `:83` sentence to "`border` (#DFE4D9) is invisible as a
  1px line on #F4F6F1." Change `:72`'s `// accent` to
  `// the pre-G137 accent, frozen — an observer's identity, not the theme (R-M8)`.

```js
const PALETTES = {
    dark: {
        label:       "#E8EEE9",                    // = CicadaTheme.Dark.textPrimary
        labelShadow: "rgba(0, 0, 0, 0.85)",
        plate:       "rgba(13, 18, 22, 0.85)",     // = Dark.background
        plateStrong: "rgba(13, 18, 22, 0.92)",     // = Dark.background
        plateText:   "#C7CBD6",
        edge:        "#25303A",                    // = Dark.border
        nodeStroke:  "#FFFFFF",
    },
    light: {
        label:       "#1B1F1A",                    // = CicadaTheme.Light.textPrimary
        labelShadow: "rgba(244, 246, 241, 0.95)",  // = Light.background, as a halo
        plate:       "rgba(255, 255, 255, 0.92)",  // = Light.surface
        plateStrong: "rgba(255, 255, 255, 0.96)",  // = Light.surface
        plateText:   "#4C5548",                    // = Light.textSecondary
        edge:        "#C5CCBC",                    // = Light.borderLight
        nodeStroke:  "#1B1F1A",                    // = Light.textPrimary
    },
};
```

  `BookwormSprites.swift:29`: change the comment to
  `// zZ + sweat drop (the pre-G137 dark accent — the mascot's palette is its own and did not move)`.
  `LogoAssetTests.swift:8` and `LogoImageTests.swift:44`: change `#23252E` to `#20292F`.

- [ ] **Step 5: Verify.** Run `swift build 2>&1 | tail -5`, then `swift test 2>&1 | tail -20`
  (0 failures), then `cd <worktree> && node --test app/CicadaApp/Tests/graph/*.test.js`
  (0 failures).
- [ ] **Step 6: Commit.** Stage the nine files above by name. Message:
  `feat(meadow): day- and night-meadow neutrals, nature tokens and sky gradients (G137 R-M1/R-M2)`.

---

### Task 2: One motion vocabulary, Reduce-Motion-aware everywhere, and the hover modifiers (R-M4)

**Files:**
- Create: `app/…/Theme/CicadaMotion.swift`
- Modify: `app/…/Theme/CicadaTheme.swift` (`CicadaPlainButtonStyle` `:560-575`, `CicadaGlassButtonStyle` `:601-612`)
- Modify (the R-M12 table; every path below is under `app/…`): `ContentView.swift`, `Ask/AskPanel.swift`, `Views/Sidebar/SidebarView.swift`, `Views/Capture/ConnectedChannelRow.swift`, `Views/Inbox/InboxCardView.swift`, `Views/Inbox/InboxListView.swift`, `Views/Common/CommandBox.swift`, `Views/Common/TopBarControls.swift`, `Views/Common/UploadOverlay.swift`, `Views/Feed/ConnectedChannelsStrip.swift`, `Views/Feed/FeedView.swift`, `Views/Topics/TopicsView.swift`
- Create: `app/CicadaApp/Tests/CicadaAppTests/CicadaMotionTests.swift`, `MotionLiteralLintTests.swift`

**Interfaces:**
- Produces: `CicadaMotion` (`maxDuration`, the nine `…Duration` constants, `expandBounce`, `ambientMaxAmplitude`, `ambientPeriodRange`, `ambientDefaultPeriod`, `ambientFrameInterval`, and `press/hover/snap/standard/panel/expand/lift/settle/morph(reduceMotion:) -> Animation?`); `HoverLift` (+ `Pose`, `pose(hovering:reduceMotion:scale:lift:)`, `maxScale`, `maxLift`); `IconHover` (+ `nextBump(_:entering:reduceMotion:)`); `View.hoverLift(scale:lift:)`, `View.iconHover(hovering:selected:)`.
- Removes: `CicadaPlainButtonStyle.pressAnimationDuration`. Grep shows no other reader; it becomes `CicadaMotion.pressDuration`.

- [ ] **Step 1: Failing tests.** `MotionLiteralLintTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// G137 R-M4 / plan R-M12 — `SleepNumbersLintTests`' motion guard, app-wide.
/// 47 literal durations in 13 files each skipped Reduce Motion; routed
/// through `CicadaMotion` they cannot. A source lint, because "a literal
/// exists in the diff" is not something a rendered view can tell you.
final class MotionLiteralLintTests: XCTestCase {
    /// The two files allowed to spell a duration.
    static let exempt = ["Theme/CicadaMotion.swift", "Views/Sleep/SleepMotion.swift"]
    /// For a `duration:` that is not an animation (a model's argument label):
    /// append `// motion-lint:ok — <reason>` to that line.
    static let escapeHatch = "// motion-lint:ok"

    func testNoDurationIsSpelledOutsideTheMotionVocabulary() throws {
        let files = try ThemeTokenTests.swiftSources()
        XCTAssertFalse(files.isEmpty, "found no sources — this lint would pass vacuously")
        var offenders: [String] = []
        for file in files where !Self.exempt.contains(where: { file.path.hasSuffix($0) }) {
            let text = try String(contentsOf: file, encoding: .utf8)
            for (index, line) in text.components(separatedBy: .newlines).enumerated() {
                let code = line.trimmingCharacters(in: .whitespaces)
                guard !code.hasPrefix("//"), code.contains("duration:"), !code.contains(Self.escapeHatch) else { continue }
                offenders.append("\(file.lastPathComponent):\(index + 1)")
            }
        }
        XCTAssertEqual(offenders, [], "these spell a duration outside CicadaMotion and so skip Reduce Motion (G137 R-M4)")
    }
}
```

  `CicadaMotionTests.swift`:

```swift
import SwiftUI
import XCTest
@testable import CicadaApp

/// G137 R-M4 — the motion vocabulary's budget, its Reduce Motion switch, and
/// the two hover modifiers' pure halves.
final class CicadaMotionTests: XCTestCase {
    private let transitions: [(String, (Bool) -> Animation?)] = [
        ("press", CicadaMotion.press), ("hover", CicadaMotion.hover), ("snap", CicadaMotion.snap),
        ("standard", CicadaMotion.standard), ("panel", CicadaMotion.panel), ("expand", CicadaMotion.expand),
        ("lift", CicadaMotion.lift), ("settle", CicadaMotion.settle), ("morph", CicadaMotion.morph),
    ]

    /// `nil` is SwiftUI for "jump to the new value" — the terminal frame.
    func testReduceMotionRemovesEveryTransition() {
        for (name, animation) in transitions {
            XCTAssertNil(animation(true), "\(name) still animates under Reduce Motion")
            XCTAssertNotNil(animation(false), name)
        }
    }

    func testEveryDurationIsInsideTheBudget() {
        let durations = [CicadaMotion.pressDuration, CicadaMotion.hoverDuration, CicadaMotion.snapDuration,
                         CicadaMotion.standardDuration, CicadaMotion.panelDuration, CicadaMotion.expandDuration,
                         CicadaMotion.liftDuration, CicadaMotion.settleDuration, CicadaMotion.morphDuration]
        for d in durations { XCTAssertLessThanOrEqual(d, CicadaMotion.maxDuration) }
        XCTAssertLessThanOrEqual(CicadaMotion.maxDuration, 0.4, "the same 400 ms ceiling SleepMotion holds")
        XCTAssertEqual(CicadaMotion.settleDuration, SleepMotion.settleDuration, "one settle, two pages")
    }

    /// R-M6: ≤ 8 pt, a 60–120 s period, no faster than 30 fps.
    func testTheAmbientBudget() {
        XCTAssertLessThanOrEqual(CicadaMotion.ambientMaxAmplitude, 8)
        XCTAssertEqual(CicadaMotion.ambientPeriodRange, 60...120)
        XCTAssertTrue(CicadaMotion.ambientPeriodRange.contains(CicadaMotion.ambientDefaultPeriod))
        XCTAssertGreaterThanOrEqual(CicadaMotion.ambientFrameInterval, 1.0 / 30.0)
    }

    /// R-M14: text never looks soft mid-animation, and the shadow is the cue
    /// that survives Reduce Motion.
    func testHoverLiftCapsItsMotionAndKeepsItsShadowUnderReduceMotion() {
        let greedy = HoverLift.pose(hovering: true, reduceMotion: false, scale: 1.2, lift: 9)
        XCTAssertEqual(greedy.scale, HoverLift.maxScale)
        XCTAssertEqual(greedy.lift, HoverLift.maxLift)
        let still = HoverLift.pose(hovering: true, reduceMotion: true, scale: 1.015, lift: 2)
        XCTAssertEqual(still.scale, 1)
        XCTAssertEqual(still.lift, 0)
        let rest = HoverLift.pose(hovering: false, reduceMotion: true, scale: 1.015, lift: 2)
        XCTAssertGreaterThan(still.shadowOpacity, rest.shadowOpacity, "hover must still read without motion")
        XCTAssertLessThanOrEqual(HoverLift.maxScale, 1.02)
        XCTAssertLessThanOrEqual(HoverLift.maxLift, 2)
    }

    /// R-M13: a glyph acknowledges the pointer ONCE, on entry, and never
    /// under Reduce Motion — enforced by not firing, not by hoping
    /// `symbolEffectsRemoved` reaches the effect.
    func testIconHoverBumpsOnEntryOnlyAndNeverUnderReduceMotion() {
        XCTAssertEqual(IconHover.nextBump(3, entering: true, reduceMotion: false), 4)
        XCTAssertEqual(IconHover.nextBump(3, entering: false, reduceMotion: false), 3)
        XCTAssertEqual(IconHover.nextBump(3, entering: true, reduceMotion: true), 3)
        XCTAssertEqual(IconHover.nextBump(Int.max, entering: true, reduceMotion: false), Int.min, "wraps, never traps")
    }
}
```

  Run `swift test --filter 'MotionLiteralLintTests|CicadaMotionTests' 2>&1 | tail -20`. Expect a
  compile failure because `CicadaMotion` does not exist. Once Step 2 compiles, the lint alone is
  red with 47 offenders. Record that count: it proves the lint bites.

- [ ] **Step 2: `CicadaMotion.swift`** (full file):

```swift
import SwiftUI

/// The app's motion vocabulary (G137, spec R-M4) — the one place outside
/// `SleepMotion` where an animation duration is spelled.
///
/// Before this file, 47 `.animation(…)` / `withAnimation(…)` sites in 13
/// files each spelled their own literal and not one of them honoured Reduce
/// Motion — only the Sleep page did, through `SleepMotion`. Every function
/// here returns `nil` under Reduce Motion, which is SwiftUI for "jump to the
/// new value": the terminal frame, the same rule `SleepMotion` states.
/// `MotionLiteralLintTests` fails the build on a `duration` label anywhere
/// else, so a new literal cannot quietly skip that switch.
///
/// Named by curve, documented by use — a new call site picks by what it is
/// doing, not by what number looked right:
///
/// - `press` — easeOut 0.12 s: a button's press dip (`CicadaPlainButtonStyle`).
/// - `hover` — easeInOut 0.15 s: pointer hover fills, and short state fades
///   (selected, copied, asking, drag-over).
/// - `snap` — spring 0.2 s: a small in-place change (a row showing more
///   lines, a resolving flag, a strip collapsing).
/// - `standard` — spring 0.25 s: switching tabs, toggling a group.
/// - `panel` — spring 0.3 s: a card, panel or overlay arriving or leaving; a
///   list reflowing.
/// - `expand` — spring 0.3 s, bounce 0.15: an inbox card opening with give.
/// - `lift` — snappy 0.18 s: `hoverLift()`.
/// - `settle` — easeInOut 0.35 s: a value-driven bar (= `SleepMotion.settle`).
/// - `morph` — smooth 0.35 s: glass or matched-geometry shapes changing form.
enum CicadaMotion {
    /// The ceiling every transition here sits under — the same 400 ms budget
    /// `SleepMotion.maxDuration` holds for the Sleep page.
    static let maxDuration: TimeInterval = 0.4

    /// Was `CicadaPlainButtonStyle.pressAnimationDuration` (G83).
    static let pressDuration: TimeInterval = 0.12
    static let hoverDuration: TimeInterval = 0.15
    static let snapDuration: TimeInterval = 0.2
    static let standardDuration: TimeInterval = 0.25
    static let panelDuration: TimeInterval = 0.3
    static let expandDuration: TimeInterval = 0.3
    static let expandBounce: Double = 0.15
    static let liftDuration: TimeInterval = 0.18
    static let settleDuration: TimeInterval = 0.35
    static let morphDuration: TimeInterval = 0.35

    /// Clouds drift, grass never moves (R-M6): at most 8 pt either way over a
    /// 60–120 s period — peripheral, never noticed as movement — at no more
    /// than 30 frames a second.
    static let ambientMaxAmplitude: CGFloat = 8
    static let ambientPeriodRange: ClosedRange<TimeInterval> = 60...120
    static let ambientDefaultPeriod: TimeInterval = 90
    static let ambientFrameInterval: TimeInterval = 1.0 / 30.0

    static func press(reduceMotion: Bool) -> Animation? { reduceMotion ? nil : .easeOut(duration: pressDuration) }
    static func hover(reduceMotion: Bool) -> Animation? { reduceMotion ? nil : .easeInOut(duration: hoverDuration) }
    static func snap(reduceMotion: Bool) -> Animation? { reduceMotion ? nil : .spring(duration: snapDuration) }
    static func standard(reduceMotion: Bool) -> Animation? { reduceMotion ? nil : .spring(duration: standardDuration) }
    static func panel(reduceMotion: Bool) -> Animation? { reduceMotion ? nil : .spring(duration: panelDuration) }
    static func expand(reduceMotion: Bool) -> Animation? {
        reduceMotion ? nil : .spring(duration: expandDuration, bounce: expandBounce)
    }
    static func lift(reduceMotion: Bool) -> Animation? { reduceMotion ? nil : .snappy(duration: liftDuration) }
    static func settle(reduceMotion: Bool) -> Animation? { reduceMotion ? nil : .easeInOut(duration: settleDuration) }
    static func morph(reduceMotion: Bool) -> Animation? { reduceMotion ? nil : .smooth(duration: morphDuration) }
}

// MARK: - Hover lift (R-M14)

/// For things that OPEN something — a card, a tile, an empty state's one
/// action. Never on dense rows (R9 §3.2: 20 jittering inbox rows), which keep
/// their `surfaceHover` fill change.
struct HoverLift: ViewModifier {
    /// Past ~1.02 text visibly softens mid-scale; past 2 pt it reads as a jump.
    static let maxScale: CGFloat = 1.02
    static let maxLift: CGFloat = 2

    var scale: CGFloat = 1.015
    var lift: CGFloat = 2

    @State private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    struct Pose: Equatable {
        var scale: CGFloat
        var lift: CGFloat
        var shadowOpacity: Double
        var shadowRadius: CGFloat
        var shadowY: CGFloat
    }

    /// Pure; tested. Scale and lift are motion and switch off under Reduce
    /// Motion; the deeper shadow is not motion and stays — so hover still
    /// reads for a person who asked for stillness.
    static func pose(hovering: Bool, reduceMotion: Bool, scale: CGFloat, lift: CGFloat) -> Pose {
        let moving = hovering && !reduceMotion
        return Pose(scale: moving ? min(scale, maxScale) : 1,
                    lift: moving ? min(lift, maxLift) : 0,
                    shadowOpacity: hovering ? 0.16 : 0.06,
                    shadowRadius: hovering ? 10 : 4,
                    shadowY: hovering ? 5 : 2)
    }

    func body(content: Content) -> some View {
        let pose = Self.pose(hovering: hovering, reduceMotion: reduceMotion, scale: scale, lift: lift)
        content
            .scaleEffect(pose.scale)
            .offset(y: -pose.lift)
            .shadow(color: .black.opacity(pose.shadowOpacity), radius: pose.shadowRadius, y: pose.shadowY)
            .animation(CicadaMotion.lift(reduceMotion: reduceMotion), value: hovering)
            .onHover { hovering = $0 }
    }
}

// MARK: - Icon hover (R-M13)

/// A glyph acknowledges the pointer once: a wiggle on macOS 15+ (`.wiggle`
/// is 15-only), a bounce on 14; and, when `selected` turns true, one bounce.
/// Never repeating — the one indefinite symbol motion in this app is a true
/// state (the Sleep pulse), not a hover.
///
/// Reduce Motion is enforced by never changing the trigger (`nextBump`), with
/// `symbolEffectsRemoved` inside the effects as a second guard: R9 could not
/// confirm symbol effects damp themselves, and `symbolEffectsRemoved` acts on
/// INHERITED effects, a direction that is easy to get backwards.
struct IconHover: ViewModifier {
    /// `nil`: track the glyph's own hover. Non-nil: the hover of a larger
    /// target the glyph sits in (a sidebar row).
    var hovering: Bool?
    var selected: Bool = false

    @State private var hoverBumps = 0
    @State private var selectBumps = 0
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    /// Pure; tested. Wrapping add, so a very long session never traps.
    static func nextBump(_ current: Int, entering: Bool, reduceMotion: Bool) -> Int {
        entering && !reduceMotion ? current &+ 1 : current
    }

    func body(content: Content) -> some View {
        wiggle(content.symbolEffectsRemoved(reduceMotion))
            .symbolEffect(.bounce.up.byLayer, options: .nonRepeating, value: selectBumps)
            .onHover { inside in
                guard hovering == nil else { return }
                hoverBumps = Self.nextBump(hoverBumps, entering: inside, reduceMotion: reduceMotion)
            }
            .onChange(of: hovering ?? false) { _, now in
                hoverBumps = Self.nextBump(hoverBumps, entering: now, reduceMotion: reduceMotion)
            }
            .onChange(of: selected) { _, now in
                selectBumps = Self.nextBump(selectBumps, entering: now, reduceMotion: reduceMotion)
            }
    }

    @ViewBuilder
    private func wiggle(_ view: some View) -> some View {
        if #available(macOS 15, *) {
            view.symbolEffect(.wiggle.byLayer, options: .nonRepeating, value: hoverBumps)
        } else {
            view.symbolEffect(.bounce.up.byLayer, options: .nonRepeating, value: hoverBumps)
        }
    }
}

extension View {
    /// See `HoverLift` — only on things that open something.
    func hoverLift(scale: CGFloat = 1.015, lift: CGFloat = 2) -> some View {
        modifier(HoverLift(scale: scale, lift: lift))
    }

    /// See `IconHover`. `iconHover()` follows the glyph's own hover;
    /// `iconHover(hovering: rowIsHovered, selected: isSelected)` a larger target's.
    func iconHover(hovering: Bool? = nil, selected: Bool = false) -> some View {
        modifier(IconHover(hovering: hovering, selected: selected))
    }
}
```

- [ ] **Step 3: The theme's two press sites.** Add
  `@Environment(\.accessibilityReduceMotion) private var reduceMotion` to both
  `CicadaPlainButtonStyle` and `CicadaGlassButtonStyle`. Replace the two `.animation(.easeOut(…))`
  lines with `.animation(CicadaMotion.press(reduceMotion: reduceMotion), value: configuration.isPressed)`.
  Delete `static let pressAnimationDuration` and its doc line.

- [ ] **Step 4: The 45-site migration (R-M12).** Run exactly:

```bash
cd <worktree>/app/CicadaApp/Sources/CicadaApp && sed -i '' \
 -e 's/\.spring(duration: 0\.3, bounce: 0\.15)/CicadaMotion.expand(reduceMotion: reduceMotion)/g' \
 -e 's/\.spring(duration: 0\.25)/CicadaMotion.standard(reduceMotion: reduceMotion)/g' \
 -e 's/\.spring(duration: 0\.3)/CicadaMotion.panel(reduceMotion: reduceMotion)/g' \
 -e 's/\.spring(duration: 0\.2), value: isHovered/CicadaMotion.hover(reduceMotion: reduceMotion), value: isHovered/g' \
 -e 's/\.spring(duration: 0\.2)/CicadaMotion.snap(reduceMotion: reduceMotion)/g' \
 -e 's/\.spring(duration: 0\.15)/CicadaMotion.hover(reduceMotion: reduceMotion)/g' \
 -e 's/\.easeInOut(duration: 0\.1[25])/CicadaMotion.hover(reduceMotion: reduceMotion)/g' \
 -e 's/\.easeInOut(duration: 0\.2)/CicadaMotion.hover(reduceMotion: reduceMotion)/g' \
 -e 's/\.easeInOut(duration: 0\.18)/CicadaMotion.snap(reduceMotion: reduceMotion)/g' \
 ContentView.swift Ask/AskPanel.swift Views/Sidebar/SidebarView.swift Views/Capture/ConnectedChannelRow.swift \
 Views/Inbox/InboxCardView.swift Views/Inbox/InboxListView.swift Views/Common/CommandBox.swift \
 Views/Common/TopBarControls.swift Views/Common/UploadOverlay.swift Views/Feed/ConnectedChannelsStrip.swift \
 Views/Feed/FeedView.swift Views/Topics/TopicsView.swift && grep -rn "CicadaMotion\." . | grep -v "Theme/" | wc -l
```

  Expect **45**: 17 `hover`, 11 `standard`, 9 `panel`, 5 `snap` and 3 `expand`. The
  `grep -v "Theme/"` matters. Without it the count is 48, because it also picks up the two press
  sites from Step 3 and the `CicadaMotion.lift` line inside `CicadaMotion.swift`. Then add
  `@Environment(\.accessibilityReduceMotion) private var reduceMotion`, next to the type's other
  property wrappers, to each of these 24 types:
  - ContentView.swift: `ContentView`, `GraphContainerView`, `ZoomButton`
  - AskPanel.swift: `AskPanel`
  - SidebarView.swift: `SidebarView`, `SidebarRow`, `ThemeToggleButton`, `SettingsGearButton`
  - ConnectedChannelRow.swift: `ConnectedChannelRow`
  - InboxCardView.swift: `InboxCardView`, `InboxActionButton`
  - InboxListView.swift: `InboxListView`, `KindChip`
  - CommandBox.swift: `CommandBox`
  - TopBarControls.swift: `TopBarControls`
  - UploadOverlay.swift: `UploadOverlay`
  - ConnectedChannelsStrip.swift: `ConnectedChannelsStrip`
  - FeedView.swift: `FeedView`, `FeedRow`
  - TopicsView.swift: `TopicsView`, `TopicsListView`, `TypeSectionHeader`, `TypeChip`, `TopicRowListItem`

  The compiler is the check: a missed type is "cannot find 'reduceMotion' in scope".
- [ ] **Step 5: Verify.** Run `swift build 2>&1 | tail -5`, then
  `swift test 2>&1 | tail -20` (0 failures; `MotionLiteralLintTests` green, and the Sleep lint
  still green). Then run
  `find <worktree>/app/CicadaApp/Sources/CicadaApp -name '*.swift' | xargs grep -n "duration:"`.
  It must print only `CicadaMotion.swift`, `SleepMotion.swift` and the `///` comment at
  `SleepView.swift:189`. Do not grep the whole folder: the vendored `graph/d3.v7.min.js` matches
  on one enormous line.
- [ ] **Step 6: Commit.** Stage `CicadaMotion.swift`, `CicadaTheme.swift`, the 12 view files and
  the 2 new tests. Message:
  `feat(meadow): one motion vocabulary, Reduce Motion everywhere, hover modifiers (G137 R-M4)`.

---

### Task 3: Instrument Serif bundled, `displayFont` / `quoteFont`, serif page titles (R-M3)

**Files:**
- Create: `app/…/Resources/fonts/InstrumentSerif-Regular.ttf`, `InstrumentSerif-Italic.ttf`, `OFL.txt`, `FONTS.md`
- Create: `app/…/Theme/CicadaFonts.swift`
- Modify: `app/…/Theme/CicadaTheme.swift` (typography block `:233-244`)
- Modify: `app/…/CicadaApp.swift` (`init`, `:62-69`)
- Modify: `app/…/Views/Common/PageHeader.swift:3-8, :26-28`
- Modify: `app/CicadaApp/Tests/CicadaAppTests/FontLiteralLintTests.swift`
- Create: `app/CicadaApp/Tests/CicadaAppTests/CicadaFontsTests.swift`

**Interfaces:**
- Produces: `CicadaFonts.displayRegular`, `.displayItalic`, `.all`, `.directory`, `registerBundled(in:) -> [String]`; `CicadaTheme.displayMinimumSize`, `displayFont(size:italic:)`, `quoteFont`, `quoteFont(size:)`.
- Consumes: `Bundle.cicadaResource(_:ext:in:)`, `CicadaTheme.scaled`, `CicadaTheme.font(size:weight:design:)`.

- [ ] **Step 1: Fetch the fonts** (public, unmodified):

```bash
cd <worktree>/app/CicadaApp/Sources/CicadaApp/Resources && mkdir -p fonts && \
for f in InstrumentSerif-Regular.ttf InstrumentSerif-Italic.ttf OFL.txt; do \
  curl -sSfL -o "fonts/$f" "https://raw.githubusercontent.com/google/fonts/main/ofl/instrumentserif/$f"; done && \
shasum -a 256 fonts/*
```

  The hashes the planner fetched on 2026-09-23 are the ones written into `FONTS.md` below. If
  `shasum` prints something different, upstream moved: replace that cell with what you fetched
  and say so in the commit body. The PostScript-name test below is what actually gates the
  change. Write `fonts/FONTS.md`:

```markdown
# Bundled fonts

**Instrument Serif** — the display face of the Meadow visual system (G137, spec R-M3): page
titles, onboarding headlines and empty-state titles at 22 pt and above. Never body text, never a
number.

| File | PostScript name | sha256 |
|---|---|---|
| `InstrumentSerif-Regular.ttf` | `InstrumentSerif-Regular` | `498efd461f6ddfcb7a111bf9a565709d2085d48201d501ead960d93e84ffbb88` |
| `InstrumentSerif-Italic.ttf` | `InstrumentSerif-Italic` | `08939b8bdf534afec24ae0ef5e03f948940cd9a8fe08e7fecbad040e62327385` |
| `OFL.txt` | — | `129ed7618959716959f2941fdd5b49e0ad6e6c1d78726761786a00253d865521` |

- **Copyright:** Copyright 2022 The Instrument Serif Project Authors
  (https://github.com/Instrument/instrument-serif).
- **Licence:** SIL Open Font License, Version 1.1. The full text is `OFL.txt` beside the fonts,
  and it ships inside the app bundle with them, which is what the OFL asks. No Reserved Font Name.
- **Source:** `google/fonts`, `ofl/instrumentserif/` on `main` (upstream commit
  `65c0ef225f386a3c7e87570a4aa9cc0262c2fd81` per its `METADATA.pb`), fetched 2026-09-23.
  Unmodified: no subsetting, no renaming.
- **Loading:** `CicadaFonts.registerBundled()` (`Theme/CicadaFonts.swift`) registers both faces
  with CoreText for this process at launch, from `Bundle.cicadaResources`' bare `fonts`
  directory. `CicadaTheme.displayFont(size:italic:)` is the only code that names them.
```

- [ ] **Step 2: Failing tests.** In `FontLiteralLintTests`, add:

```swift
    /// G137 R-M3: `CicadaTheme.displayFont(size:italic:)` is the one custom
    /// face. `.custom(` anywhere else would be a second one arriving
    /// unnoticed — unscaled by ⌘+/⌘−, unregistered, unlicensed. Comment lines
    /// are skipped so a doc may name the API.
    func testNoCustomFontOutsideTheTheme() throws {
        for file in try sourceFiles() {
            let text = try String(contentsOf: file, encoding: .utf8)
            for (index, line) in text.components(separatedBy: .newlines).enumerated() {
                let code = line.trimmingCharacters(in: .whitespaces)
                guard !code.hasPrefix("//"), code.contains(".custom(") else { continue }
                XCTFail("\(file.lastPathComponent):\(index + 1) builds a custom font — "
                        + "use CicadaTheme.displayFont(size:italic:) (G137 R-M3).")
            }
        }
    }

    /// Instrument Serif is a display cut; its hairlines break up under 22 pt.
    /// `displayFont` clamps, and this keeps a call site from asking.
    func testDisplayFontIsNeverAskedForLessThanItsFloor() throws {
        let pattern = try NSRegularExpression(pattern: #"displayFont\(size:\s*([0-9]+(?:\.[0-9]+)?)"#)
        var seen = 0
        for file in try sourceFiles() {
            let text = try String(contentsOf: file, encoding: .utf8)
            let ns = text as NSString
            for match in pattern.matches(in: text, range: NSRange(location: 0, length: ns.length)) {
                let size = Double(ns.substring(with: match.range(at: 1))) ?? 0
                XCTAssertGreaterThanOrEqual(size, Double(CicadaTheme.displayMinimumSize),
                                            "\(file.lastPathComponent) asks for a \(size) pt display face")
                seen += 1
            }
        }
        XCTAssertGreaterThan(seen, 0, "no displayFont call found — the regex no longer matches and this lint is vacuous")
    }
```

  `CicadaFontsTests.swift`:

```swift
import AppKit
import CoreText
import SwiftUI
import XCTest
@testable import CicadaApp

/// G137 R-M3 / plan R-M15 — the bundled display face resolves in every
/// layout the app ships in, registers idempotently, and degrades to the
/// system face (never to blank) when it is missing.
final class CicadaFontsTests: XCTestCase {
    override class func setUp() {
        super.setUp()
        CicadaFonts.registerBundled()
    }

    func testTheBundledFilesAreTheFacesTheThemeAsksFor() throws {
        for name in CicadaFonts.all {
            let url = try XCTUnwrap(Bundle.cicadaResources.cicadaResource(name, ext: "ttf", in: CicadaFonts.directory),
                                    "\(name).ttf is not bundled")
            let descriptors = CTFontManagerCreateFontDescriptorsFromURL(url as CFURL) as? [CTFontDescriptor] ?? []
            let names = descriptors.compactMap { CTFontDescriptorCopyAttribute($0, kCTFontNameAttribute) as? String }
            XCTAssertEqual(names, [name], "\(name).ttf carries PostScript name(s) \(names)")
        }
    }

    func testTheLicenceTravelsWithTheFonts() throws {
        let url = try XCTUnwrap(Bundle.cicadaResources.cicadaResource("OFL", ext: "txt", in: CicadaFonts.directory))
        let text = try String(contentsOf: url, encoding: .utf8)
        XCTAssertTrue(text.contains("SIL OPEN FONT LICENSE Version 1.1"))
        XCTAssertTrue(text.contains("Instrument Serif Project Authors"))
    }

    /// CoreText answers a second registration of the same file with 105
    /// (already registered, measured) — success here.
    func testRegistrationMakesBothFacesResolveAndIsIdempotent() {
        XCTAssertEqual(CicadaFonts.registerBundled(), CicadaFonts.all)
        XCTAssertEqual(CicadaFonts.registerBundled(), CicadaFonts.all)
        for name in CicadaFonts.all { XCTAssertNotNil(NSFont(name: name, size: 28), name) }
    }

    /// The PR #70 class: `bundle.sh` re-nests the resource bundle, so a
    /// lookup that only works in the flat `swift test` layout ships broken.
    /// Both layouts are built from bytes; a bundle with no fonts reports none.
    func testTheFontsDirectoryResolvesInBothBundleLayoutsAndAnEmptyBundleDegrades() throws {
        let ttf = try Data(contentsOf: XCTUnwrap(
            Bundle.cicadaResources.cicadaResource(CicadaFonts.displayRegular, ext: "ttf", in: CicadaFonts.directory)))
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("font-layouts-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: root) }
        let file = "\(CicadaFonts.displayRegular).ttf"
        let flat = root.appendingPathComponent("Flat.bundle")
        try write(ttf, to: flat.appendingPathComponent("Resources/fonts/\(file)"))
        let nested = root.appendingPathComponent("Nested.bundle")
        try write(ttf, to: nested.appendingPathComponent("Contents/Resources/fonts/\(file)"))
        try write(Data("""
        <?xml version="1.0" encoding="UTF-8"?>
        <plist version="1.0"><dict>
        <key>CFBundleIdentifier</key><string>com.rorosaga.cicada.resources.test</string>
        <key>CFBundlePackageType</key><string>BNDL</string>
        </dict></plist>
        """.utf8), to: nested.appendingPathComponent("Contents/Info.plist"))
        for url in [flat, nested] {
            let bundle = try XCTUnwrap(Bundle(url: url), url.lastPathComponent)
            XCTAssertNotNil(bundle.cicadaResource(CicadaFonts.displayRegular, ext: "ttf", in: CicadaFonts.directory),
                            "the display face is unreachable in the \(url.lastPathComponent) layout")
        }
        let empty = root.appendingPathComponent("Empty.bundle")
        try FileManager.default.createDirectory(at: empty.appendingPathComponent("Resources"),
                                                withIntermediateDirectories: true)
        XCTAssertEqual(CicadaFonts.registerBundled(in: try XCTUnwrap(Bundle(url: empty))), [],
                       "a bundle without fonts reports none — titles fall back to SF, never to blank")
    }

    func testDisplayFontIsTheBundledFaceClampedToItsFloor() {
        XCTAssertEqual(CicadaTheme.displayFont(size: 28),
                       Font.custom(CicadaFonts.displayRegular, size: CicadaTheme.scaled(28)))
        XCTAssertEqual(CicadaTheme.displayFont(size: 28, italic: true),
                       Font.custom(CicadaFonts.displayItalic, size: CicadaTheme.scaled(28)))
        XCTAssertEqual(CicadaTheme.displayFont(size: 12), CicadaTheme.displayFont(size: CicadaTheme.displayMinimumSize))
        XCTAssertEqual(CicadaTheme.quoteFont, CicadaTheme.font(size: 13, design: .serif).italic())
    }

    private func write(_ data: Data, to url: URL) throws {
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try data.write(to: url)
    }
}
```

  Run `swift test --filter 'FontLiteralLintTests|CicadaFontsTests' 2>&1 | tail -20`. Expect a
  compile failure because `CicadaFonts` and `displayFont` do not exist.

- [ ] **Step 3: `CicadaFonts.swift`** (full file):

```swift
import AppKit
import CoreText

/// The bundled display face (G137, spec R-M3): Instrument Serif, SIL OFL 1.1,
/// registered with CoreText for this process at launch (`CicadaApp.init`).
///
/// **Why CoreText, not `ATSApplicationFontsPath`.** The Info.plist key would
/// need `bundle.sh` to copy the TTFs into `Contents/Resources` — a second
/// place the fonts live and a second layout to get wrong. Registering from
/// `Bundle.cicadaResources` reads them where every other resource lives.
///
/// **Why the bare `"fonts"` directory.** `Bundle.cicadaResource(_:ext:in:)`'s
/// docstring has the measurement: `bundle.sh` re-nests the resource bundle for
/// `codesign`, consuming the `Resources` path component, so a
/// `"Resources/fonts"` lookup resolves under `swift test` and fails in every
/// shipped app — the PR #70 bug.
///
/// **A missing font is not an error.** SwiftUI falls back to the system face
/// for an unknown PostScript name, so a bundle that lost its fonts renders SF
/// titles, not blank ones. `registerBundled` therefore never throws; it
/// reports which faces it made available, and `CicadaFontsTests` holds it to
/// that in both bundle layouts. `CicadaTheme.displayFont` is the only code
/// that names these faces (`FontLiteralLintTests`).
enum CicadaFonts {
    static let displayRegular = "InstrumentSerif-Regular"
    static let displayItalic = "InstrumentSerif-Italic"
    static let all = [displayRegular, displayItalic]
    static let directory = "fonts"

    /// Registers every bundled display face in `bundle` (process scope) and
    /// returns the PostScript names that were FOUND in that bundle and
    /// resolve afterwards. Idempotent: a second registration of the same file
    /// fails with `kCTFontManagerErrorAlreadyRegistered` (105, measured), and
    /// the name still resolves, so it is reported.
    @discardableResult
    static func registerBundled(in bundle: Bundle = .cicadaResources) -> [String] {
        all.filter { name in
            guard let url = bundle.cicadaResource(name, ext: "ttf", in: directory) else { return false }
            var error: Unmanaged<CFError>?
            if !CTFontManagerRegisterFontsForURL(url as CFURL, .process, &error) {
                // 105 is benign. Anything else leaves the name unresolved and
                // the check below says so — the title degrades to SF.
                _ = error?.takeRetainedValue()
            }
            return NSFont(name: name, size: 12) != nil
        }
    }
}
```

- [ ] **Step 4: Theme tokens.** In `CicadaTheme.swift`, after `monoFont` (`:244`), add:

```swift
    // MARK: - Display + quote faces (G137, spec R-M3; plan R-M15)
    /// Instrument Serif is a display cut: its hairlines break up under ~22 pt.
    static let displayMinimumSize: CGFloat = 22

    /// Page titles, onboarding headlines, empty-state titles — never a
    /// number, never body text. Scaled by `uiScale` like every token, and
    /// clamped to `displayMinimumSize` so a misuse degrades to legible, not
    /// spindly (`FontLiteralLintTests` also fails a literal below it). The
    /// ONE custom-font call in the app: the lint bans it everywhere else, so
    /// a second face cannot arrive unnoticed. An unregistered face falls back
    /// to SF (see `CicadaFonts`).
    static func displayFont(size: CGFloat, italic: Bool = false) -> Font {
        .custom(italic ? CicadaFonts.displayItalic : CicadaFonts.displayRegular,
                size: scaled(max(size, displayMinimumSize)))
    }

    /// The person's own words — provenance excerpts and quoted snippets. New
    /// York italic ships with macOS (zero bundle cost) and is optically sized
    /// for text, where Instrument Serif is not.
    static var quoteFont: Font { quoteFont(size: 13) }
    static func quoteFont(size: CGFloat) -> Font { font(size: size, design: .serif).italic() }
```

- [ ] **Step 5: Register at launch.** In `CicadaApp.init()`, after
  `NSApplication.shared.activate(ignoringOtherApps: true)`, add:

```swift
        // G137 R-M3: before any view asks for `CicadaTheme.displayFont`.
        CicadaFonts.registerBundled()
```

- [ ] **Step 6: `PageHeader`.** Replace `:26-28`'s `.font(CicadaTheme.titleFont)` with
  `.font(CicadaTheme.displayFont(size: 28))`. In the doc comment, replace its last two lines
  (`:7-8`, from "/// identically:" through "`bodyFont` subtitle in `textSecondary`.") with the
  following. Lines `:3-6` stay as they are:

```swift
/// identically: `spacingXL` outer padding, a display-serif title in
/// `textPrimary` (G137 R-M16: Instrument Serif 28 pt sets the same width as
/// the SF 20 semibold it replaced, ±6% — "Integrations" 110 → 114 pt,
/// "Chrome bookmarks" 179 → 189 pt — so every call site keeps its line),
/// `bodyFont` subtitle in `textSecondary`.
```

- [ ] **Step 7: Verify.** Run `swift build 2>&1 | tail -5` and `swift test 2>&1 | tail -20`
  (0 failures).
- [ ] **Step 8: Commit.** Stage the four font files, `CicadaFonts.swift`, `CicadaTheme.swift`,
  `CicadaApp.swift`, `PageHeader.swift`, `FontLiteralLintTests.swift` and `CicadaFontsTests.swift`.
  Message: `feat(meadow): bundle Instrument Serif, displayFont/quoteFont, serif page titles (G137 R-M3)`.

---

### Task 4: `liquidGlass`, the primary action, the glass sidebar with hover glyphs, and the macOS 14 floor (R-M5, R-M7)

**Files:**
- Create: `app/…/Theme/LiquidGlass.swift`
- Modify: `app/…/Views/Sidebar/SidebarView.swift` (doc on `SidebarView`; `:101`; `:158-161`; `:170-178`; `:204`; `:240`)
- Modify: `app/…/Theme/CicadaTheme.swift` (`GlassCard` doc, `:513-515`)
- Modify: `app/CicadaApp/bundle.sh:68, :80`
- Create: `app/CicadaApp/Tests/CicadaAppTests/LiquidGlassLintTests.swift`, `SidebarChromeTests.swift`, `PlatformFloorTests.swift`

**Interfaces:**
- Produces: `GlassLevel` (`control | interactive | prominent | overImagery`); `LiquidGlass.Fallback` (`material | opaque`), `LiquidGlass.fallback(reduceTransparency:)`, `LiquidGlass.strongBorder(contrast:)`, `LiquidGlass.overImageryDim`; `View.liquidGlass(_:in:)`, `View.primaryActionStyle()`, `View.sidebarChromeBackground()`; `LiquidGlassGroup(spacing:content:)`; `PrimaryActionButton(title:systemImage:action:)`.
- Consumes: `CicadaTheme.accent/onAccent/surfaceElevated/border/textTertiary/background`, `iconHover`.

- [ ] **Step 1: Failing tests.** `LiquidGlassLintTests.swift`:

```swift
import SwiftUI
import XCTest
@testable import CicadaApp

/// G137 R-M5 / plan R-M19 — "use Liquid Glass sparingly" (HIG Materials) made
/// enforceable: every glass API lives in `Theme/LiquidGlass.swift`, behind
/// one macOS 26 gate, so a glass surface on a content card, a list row or the
/// graph cannot arrive in a diff without touching that file.
final class LiquidGlassLintTests: XCTestCase {
    static let home = "Theme/LiquidGlass.swift"
    static let needles = [".glassEffect(", "GlassEffectContainer", "glassEffectID(", "glassEffectUnion(",
                          ".glassProminent", ".buttonStyle(.glass)", ".buttonStyle(.glass(",
                          ".backgroundExtensionEffect("]

    func testGlassAPIsLiveInOneFile() throws {
        var offenders: [String] = []
        for file in try ThemeTokenTests.swiftSources() where !file.path.hasSuffix(Self.home) {
            let text = try String(contentsOf: file, encoding: .utf8)
            for (index, line) in text.components(separatedBy: .newlines).enumerated() {
                let code = line.trimmingCharacters(in: .whitespaces)
                guard !code.hasPrefix("//") else { continue }
                if Self.needles.contains(where: { code.contains($0) }) {
                    offenders.append("\(file.lastPathComponent):\(index + 1)")
                }
            }
        }
        XCTAssertEqual(offenders, [], "glass outside \(Self.home) — chrome only, through liquidGlass(_:in:) (G137 R-M5)")
    }

    func testTheHomeFileGatesGlassOnMacOS26() throws {
        let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first { $0.path.hasSuffix(Self.home) })
        let text = try String(contentsOf: file, encoding: .utf8)
        XCTAssertTrue(text.contains("#available(macOS 26, *)"), "the package floor is macOS 14 — glass must be gated")
        XCTAssertTrue(text.contains(".glassEffect("), "the lint would pass vacuously without the real call here")
    }

    /// The fallback branch is ours to get right (on 26 the system handles
    /// Reduce Transparency and Increase Contrast itself — WWDC25-219).
    func testTheFallbackGoesOpaqueUnderReduceTransparencyAndStrongUnderIncreasedContrast() {
        XCTAssertEqual(LiquidGlass.fallback(reduceTransparency: true), .opaque)
        XCTAssertEqual(LiquidGlass.fallback(reduceTransparency: false), .material)
        XCTAssertTrue(LiquidGlass.strongBorder(contrast: .increased))
        XCTAssertFalse(LiquidGlass.strongBorder(contrast: .standard))
        XCTAssertEqual(LiquidGlass.overImageryDim, 0.35, "Apple's recipe for clear glass over imagery")
    }
}
```

  `SidebarChromeTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// G137 — the sidebar is the chrome this track reskins. Source checks, the
/// house shape for layout rules a unit test cannot render and ask
/// (`SettingsEntryPointTests`).
final class SidebarChromeTests: XCTestCase {
    private func sidebar() throws -> String {
        let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first { $0.lastPathComponent == "SidebarView.swift" })
        return try String(contentsOf: file, encoding: .utf8)
    }

    /// WWDC25-323: "extra backgrounds … behind the bar items … interfere with
    /// the effect". The opaque fill covered macOS 26's floating glass sidebar.
    func testTheSidebarLetsTheSystemGlassThroughOnMacOS26() throws {
        let text = try sidebar()
        XCTAssertTrue(text.contains(".sidebarChromeBackground()"))
        XCTAssertFalse(text.contains(".background(CicadaTheme.background)"))
    }

    /// The owner: "Add animations to the icons as i hover over them."
    func testEveryTabGlyphAcknowledgesThePointerAndItsSelection() throws {
        XCTAssertTrue(try sidebar().contains(".iconHover(hovering: isHovered, selected: isSelected)"))
    }

    /// `.white` is 2.53:1 on the new dark accent (R-M11).
    func testTheBadgeInkIsAToken() throws {
        let text = try sidebar()
        XCTAssertFalse(text.contains(".foregroundStyle(.white)"))
        XCTAssertTrue(text.contains("CicadaTheme.onAccent"))
    }
}
```

  `PlatformFloorTests.swift`:

```swift
import XCTest

/// G137 R-M7 / plan R-M24 — the Info.plist `bundle.sh` writes promised macOS
/// 13 while `Package.swift` builds for 14, so the `#available` floor the glass
/// and symbol-effect gates assume was not the floor the app advertised. Held
/// equal here so the two cannot drift again.
final class PlatformFloorTests: XCTestCase {
    private var packageRoot: URL {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()   // CicadaAppTests
            .deletingLastPathComponent()   // Tests
            .deletingLastPathComponent()   // CicadaApp
    }

    private func firstCapture(_ pattern: String, in text: String) throws -> String? {
        let regex = try NSRegularExpression(pattern: pattern)
        let ns = text as NSString
        guard let m = regex.firstMatch(in: text, range: NSRange(location: 0, length: ns.length)) else { return nil }
        return ns.substring(with: m.range(at: 1))
    }

    func testTheInfoPlistPromisesTheFloorThePackageBuildsFor() throws {
        let package = try String(contentsOf: packageRoot.appendingPathComponent("Package.swift"), encoding: .utf8)
        let bundle = try String(contentsOf: packageRoot.appendingPathComponent("bundle.sh"), encoding: .utf8)
        let major = try XCTUnwrap(try firstCapture(#"\.macOS\(\.v(\d+)\)"#, in: package))
        let plist = try XCTUnwrap(try firstCapture(#"<key>LSMinimumSystemVersion</key><string>([0-9.]+)</string>"#, in: bundle))
        XCTAssertEqual(plist, "\(major).0")
    }
}
```

  Run `swift test --filter 'LiquidGlassLintTests|SidebarChromeTests|PlatformFloorTests' 2>&1 | tail -20`.
  Expect a compile failure because `LiquidGlass` does not exist.

- [ ] **Step 2: `LiquidGlass.swift`** (full file):

```swift
import SwiftUI

/// Liquid Glass, in exactly one file (G137, spec R-M5; plan R-M17 … R-M19).
///
/// **Chrome only.** HIG Materials: "Don't use Liquid Glass in the content
/// layer" — glass is for the sidebar, the toolbar, floating controls and ONE
/// prominent action per page. Content cards stay a standard material
/// (`GlassCard`, despite its name). Never glass on glass: what sits on a glass
/// surface uses fills and vibrancy (WWDC25-219). Never over the graph canvas
/// without the G109 frame-time check.
///
/// **Gated.** The package floor is macOS 14, so every glass API sits behind
/// `#available(macOS 26, *)` with a material fallback. On 26 the system
/// handles Reduce Transparency, Increase Contrast and Reduce Motion for glass
/// itself (WWDC25-219); the fallback branch is ours — opaque under Reduce
/// Transparency, a stronger border under Increase Contrast.
///
/// `LiquidGlassLintTests` fails the build on a glass API anywhere else.
enum GlassLevel: CaseIterable {
    /// A floating control surface (`Glass.regular`).
    case control
    /// A clickable one — reacts to the pointer (`.regular.interactive()`).
    case interactive
    /// The one emphasised surface, accent-tinted (tint only this — WWDC25-219).
    case prominent
    /// Clear glass over art, with Apple's 35 % dim beneath it. Never mixed
    /// with `.control` in one group.
    case overImagery
}

/// The decisions the fallback branch makes, as pure functions (tested).
enum LiquidGlass {
    enum Fallback: Equatable { case material, opaque }

    static func fallback(reduceTransparency: Bool) -> Fallback { reduceTransparency ? .opaque : .material }
    static func strongBorder(contrast: ColorSchemeContrast) -> Bool { contrast == .increased }
    /// HIG Materials: over bright content, "consider adding a dark dimming
    /// layer of 35% opacity" beneath clear glass.
    static let overImageryDim: Double = 0.35
}

private struct LiquidGlassModifier<S: Shape>: ViewModifier {
    let level: GlassLevel
    let shape: S
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    @Environment(\.colorSchemeContrast) private var contrast

    func body(content: Content) -> some View {
        if #available(macOS 26, *) {
            switch level {
            case .control: content.glassEffect(.regular, in: shape)
            case .interactive: content.glassEffect(.regular.interactive(), in: shape)
            case .prominent: content.glassEffect(.regular.tint(CicadaTheme.accent), in: shape)
            case .overImagery:
                content.glassEffect(.clear, in: shape)
                    .background(Color.black.opacity(LiquidGlass.overImageryDim), in: shape)
            }
        } else {
            content
                .background(fallbackFill, in: shape)
                .background(level == .overImagery ? Color.black.opacity(LiquidGlass.overImageryDim) : Color.clear,
                            in: shape)
                .overlay(shape.stroke(LiquidGlass.strongBorder(contrast: contrast)
                                      ? CicadaTheme.textTertiary : CicadaTheme.border, lineWidth: 1))
        }
    }

    private var fallbackFill: AnyShapeStyle {
        switch LiquidGlass.fallback(reduceTransparency: reduceTransparency) {
        case .opaque: AnyShapeStyle(CicadaTheme.surfaceElevated)
        case .material: AnyShapeStyle(Material.regularMaterial)
        }
    }
}

/// Neighbouring glass must share one container: glass cannot sample glass,
/// so siblings in different containers render inconsistently (WWDC25-323),
/// and one container is also the performance path. Plain content before 26.
struct LiquidGlassGroup<Content: View>: View {
    var spacing: CGFloat? = nil
    @ViewBuilder var content: () -> Content

    var body: some View {
        if #available(macOS 26, *) {
            GlassEffectContainer(spacing: spacing) { content() }
        } else {
            content()
        }
    }
}

/// The page's one prominent action (plan R-M18): `.glassProminent` on 26,
/// `.borderedProminent` before, accent-tinted, label in `onAccent`.
struct PrimaryActionButton: View {
    let title: String
    var systemImage: String? = nil
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Group {
                if let systemImage { Label(title, systemImage: systemImage) } else { Text(title) }
            }
            .foregroundStyle(CicadaTheme.onAccent)
        }
        .primaryActionStyle()
    }
}

/// Paints nothing on macOS 26, so the system's floating glass sidebar shows
/// (WWDC25-323: extra backgrounds interfere with it); the opaque theme
/// background before, exactly as the sidebar always looked there.
private struct SidebarChromeBackground: ViewModifier {
    func body(content: Content) -> some View {
        if #available(macOS 26, *) {
            content
        } else {
            content.background(CicadaTheme.background)
        }
    }
}

extension View {
    /// See `GlassLevel`. Chrome only; content cards use `glassCard()`.
    func liquidGlass<S: Shape>(_ level: GlassLevel = .control, in shape: S) -> some View {
        modifier(LiquidGlassModifier(level: level, shape: shape))
    }

    /// The prominent-action button style — for a `Button` or a `SettingsLink`
    /// (`SettingsSectionLink(prominent:)`). One per page. The caller's label
    /// uses `CicadaTheme.onAccent`.
    @ViewBuilder
    func primaryActionStyle() -> some View {
        if #available(macOS 26, *) {
            buttonStyle(.glassProminent).tint(CicadaTheme.accent)
        } else {
            buttonStyle(.borderedProminent).tint(CicadaTheme.accent)
        }
    }

    /// The sidebar column's background — see `SidebarChromeBackground`.
    func sidebarChromeBackground() -> some View { modifier(SidebarChromeBackground()) }
}
```

- [ ] **Step 3: The sidebar.** In `SidebarView.swift`:
  1. `:101`: `.background(CicadaTheme.background)` → `.sidebarChromeBackground()`.
  2. The `SidebarRow` glyph in the `else` branch (`Image(systemName: tab.icon)` through its
     `.frame(width: 24)`, not the `ProgressView`'s frame): append
     `.iconHover(hovering: isHovered, selected: isSelected)` as the next line.
  3. The badge: `.foregroundStyle(.white)` → `.foregroundStyle(CicadaTheme.onAccent)`, and
     `.background(CicadaTheme.accent.opacity(0.8))` → `.background(CicadaTheme.accent)`.
  4. `ThemeToggleButton`'s `Image(systemName: colorScheme == .dark ? …)`: append
     `.iconHover(hovering: isHovered)` directly after the `Image(...)` line.
  5. `SettingsGearButton`'s `Image(systemName: "gearshape")`: the same.
  6. `struct SidebarView` (`:50`) has no doc comment today. Add this one directly above it:

```swift
/// G137: on macOS 26 the column paints nothing (`sidebarChromeBackground()`)
/// so the system's Liquid Glass sidebar shows — the opaque fill it used to
/// paint is exactly the "extra background" WWDC25-323 says breaks the effect.
/// Each glyph acknowledges the pointer once (`iconHover`) and bounces when its
/// tab is chosen; the inbox badge is `onAccent` on an opaque accent, the pair
/// whose contrast is measured (R-M11).
```

- [ ] **Step 4: `GlassCard` says what it is.** Replace `// MARK: - Glass Card Modifier`
  (`:513`) with:

```swift
// MARK: - Glass Card Modifier
// A standard-MATERIAL content card, despite the name (G137 R-M5): the HIG
// keeps Liquid Glass out of the content layer, so the 43 `.glassCard()` sites
// stay what they are. Real glass lives in `Theme/LiquidGlass.swift`, in the
// chrome layer only.
```

- [ ] **Step 5: `bundle.sh`.** `:80` becomes
  `  <key>LSMinimumSystemVersion</key><string>14.0</string>`. Directly above
  `cat > "$APP/Contents/Info.plist" <<'PLIST'` (`:68`), add
  `# LSMinimumSystemVersion matches Package.swift's .macOS(.v14) floor (G137 R-M7; PlatformFloorTests holds the pair).`
- [ ] **Step 6: Verify.** Run `swift build 2>&1 | tail -5` and `swift test 2>&1 | tail -20`
  (0 failures). Then `bash -n <worktree>/app/CicadaApp/bundle.sh` (syntax only; do NOT run it).
- [ ] **Step 7: Commit.** Stage `LiquidGlass.swift`, `SidebarView.swift`, `CicadaTheme.swift`,
  `bundle.sh` and the 3 new tests. Message:
  `feat(meadow): liquidGlass + primary action, glass sidebar with hover glyphs, macOS 14 floor (G137 R-M5/R-M7)`.

---

### Task 5: The painted art, its provenance manifest, and the backdrop components (R-M6)

**Files:**
- Create: `app/…/Resources/art/` with `cloud-1.png`, `cloud-1-dark.png`, `cloud-2.png`, `cloud-2-dark.png`, `cloud-3.png`, `cloud-3-dark.png`, `grass-left.png`, `grass-left-dark.png`, `grass-right.png`, `grass-right-dark.png`, `grass-edge.png`, `grass-edge-dark.png`, `hero-day.jpg`, `hero-day-dark.jpg`, `art.manifest.json`
- Create: `app/…/Views/Meadow/MeadowArt.swift`, `app/…/Views/Meadow/MeadowBackdrop.swift`
- Create: `app/CicadaApp/Tests/CicadaAppTests/ArtAssetTests.swift`, `MeadowTests.swift`, `MeadowPlacementLintTests.swift`
- Scratch only, never staged: `<scratch>/m1/prepare_art.py`

**Interfaces:**
- Produces: `MeadowArt` (`cloud1/cloud2/cloud3/grassLeft/grassRight/grassEdge/heroDay`, `directory`, `darkSuffix`, `fileExtension`, `pixelsPerPoint`, `fileName(for:mode:)`, `url(for:mode:in:)`, `@MainActor image(for:mode:)`); `MeadowRules` (`cloudOpacity(mode:contrast:)`, `grassOpacity(contrast:)`, `isDriftPaused(reduceMotion:activeState:)`, `driftOffset(at:amplitude:period:reduceMotion:)`); views `ArtImage(art:)`, `MeadowSky(phase:)`, `DriftingCloud(art:width:amplitude:period:)`, `GrassCorners(height:)`, `GrassEdge()`, `MeadowBackdrop(style:)` with `.corners` / `.meadow(phase:)`.
- Consumes: `CicadaMotion.ambient*`, `CicadaTheme.mode/skyGradient/SkyPhase/scaled/spacing*`, `Bundle.cicadaResource`.

- [ ] **Step 0: Gate on the inputs.** Run:

```bash
cd <art-src> && for f in hero-day.png hero-day-dark.png cloud-1.png cloud-1-dark.png cloud-2.png cloud-2-dark.png \
  cloud-3.png cloud-3-dark.png grass-left.png grass-left-dark.png grass-right.png grass-right-dark.png \
  grass-edge.png grass-edge-dark.png manifest-day.jsonl manifest-night.jsonl; do [ -s "$f" ] || echo "MISSING $f"; done
```

  **Any `MISSING` line: stop this task and report BLOCKED with the list. Stage nothing.** The
  orchestrator is generating the art. Tasks 1–4 are already shippable on their own. **Task 6
  waits with this task**, because it draws `DriftingCloud` and `GrassCorners` from Step 4.
  **Task 7 waits too**, because its row and paragraph describe the art and the empty state as
  built.

- [ ] **Step 1: Process the art.** Run `mkdir -p <scratch>/m1`, write `<scratch>/m1/prepare_art.py`
  exactly as below, then run
  `python3 <scratch>/m1/prepare_art.py <art-src> <worktree>/app/CicadaApp/Sources/CicadaApp/Resources/art`.
  **Any output line starting `BLOCKED:` stops the task** in the same way (report it, stage
  nothing).

```python
#!/usr/bin/env python3
"""G137 Task 5 — one-off, never committed (plan R-M20).

Turns the generated round-3 Meadow set into the bundled art and its
provenance manifest. Usage: prepare_art.py <art-src> <art-dst>
Exits with a line starting "BLOCKED:" whenever provenance or budget cannot be
met honestly — it never invents a prompt.
"""
import datetime
import hashlib
import json
import os
import re
import sys

from PIL import Image

SRC, DST = sys.argv[1], sys.argv[2]
IDS = ["cloud-1", "cloud-2", "cloud-3", "grass-left", "grass-right", "grass-edge", "hero-day"]
BUDGET = 4 * 1024 * 1024
DEFAULT_GENERATOR = "OpenAI image generation through the Codex CLI (codex exec)"
LICENCE = ("MIT, as this repository (see LICENSE). Generated for Cicada; "
           "no third-party artwork or brand marks.")
CAP = {"cloud": 800, "grass-corner": 640, "hero": 2400}
EDGE_HEIGHT, EDGE_MAX_WIDTH = 240, 2400
NOTE = ("Painted Meadow art (G137, round-3 spec R-M6). Generated once; each entry says how "
        "a file was made and what was done to it after. ArtAssetTests holds this list to the "
        "bytes: regenerating or re-processing a file means a new entry here in the same commit.")


def role(asset_id):
    if asset_id.startswith("cloud-"):
        return "cloud"
    if asset_id in ("grass-left", "grass-right"):
        return "grass-corner"
    if asset_id == "grass-edge":
        return "grass-edge"
    return "hero"


def records():
    out = {}
    for name in ("manifest-day.jsonl", "manifest-night.jsonl"):
        with open(os.path.join(SRC, name), encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                rec = json.loads(raw)
                f = next((rec[k] for k in ("file", "out", "output", "name", "path") if rec.get(k)), None)
                if f:
                    out[os.path.basename(str(f))] = rec
    return out


def provenance(rec, src):
    rec = rec or {}
    prompt = rec.get("prompt") or rec.get("brief")
    if not prompt:
        sys.exit(f"BLOCKED: no prompt recorded for {os.path.basename(src)}")
    if re.search(r"https?://|www\.|@[A-Za-z0-9_]", str(prompt)):
        sys.exit(f"BLOCKED: the prompt for {os.path.basename(src)} carries a URL or handle (privacy rule)")
    gen = rec.get("generator") or rec.get("model") or rec.get("tool") or DEFAULT_GENERATOR
    date = str(rec.get("date") or rec.get("created") or rec.get("timestamp") or "")[:10]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        date = datetime.date.fromtimestamp(os.path.getmtime(src)).isoformat()
    return str(prompt).strip(), str(gen), date


def fit(im, r):
    w, h = im.size
    scale = min(EDGE_HEIGHT / h, EDGE_MAX_WIDTH / w) if r == "grass-edge" else CAP[r] / max(w, h)
    scale = min(scale, 1.0)  # never upscale: that is fake resolution
    return im if scale == 1.0 else im.resize((round(w * scale), round(h * scale)), Image.LANCZOS)


def sized(before, after, why):
    """The honest first clause of a `processing` line: what happened to the pixels.
    A file already inside its cap is recorded as kept, never as "resized"."""
    if before == after:
        return f"kept at its generated {after[0]}x{after[1]} px"
    return f"resized from {before[0]}x{before[1]} to {after[0]}x{after[1]} px (Lanczos) {why}"


def main():
    os.makedirs(DST, exist_ok=True)
    recs = records()
    entries = []
    for asset_id in IDS:
        r = role(asset_id)
        ext = "jpg" if r == "hero" else "png"
        light_src = os.path.join(SRC, f"{asset_id}.png")
        dark_src = os.path.join(SRC, f"{asset_id}-dark.png")
        light_raw = Image.open(light_src)
        light = fit(light_raw, r)
        dark_raw = Image.open(dark_src)
        if r == "hero":
            for im, name in ((light, asset_id), (dark_raw, f"{asset_id}-dark")):
                if "A" in im.getbands() and im.getchannel("A").getextrema()[0] < 250:
                    sys.exit(f"BLOCKED: {name} has transparency; the plan ships the hero as opaque JPEG")
        la = light.size[0] / light.size[1]
        da = dark_raw.size[0] / dark_raw.size[1]
        if abs(la - da) / la > 0.02:
            sys.exit(f"BLOCKED: {asset_id}-dark is not the shape of {asset_id} ({da:.3f} vs {la:.3f})")
        dark = dark_raw if dark_raw.size == light.size else dark_raw.resize(light.size, Image.LANCZOS)
        how = {"light": sized(light_raw.size, light.size, "to fit the cap"),
               "dark": sized(dark_raw.size, dark.size, "to its light twin's size")}
        for variant, im, src in (("light", light, light_src), ("dark", dark, dark_src)):
            fid = asset_id if variant == "light" else f"{asset_id}-dark"
            twin = f"{asset_id}-dark.{ext}" if variant == "light" else f"{asset_id}.{ext}"
            path = os.path.join(DST, f"{fid}.{ext}")
            if ext == "jpg":
                im.convert("RGB").save(path, "JPEG", quality=82, optimize=True, progressive=True)
                processing = f"{how[variant]}; JPEG quality 82 (opaque art, no alpha to keep)"
            else:
                im.convert("RGBA").save(path, "PNG", optimize=True)
                processing = f"{how[variant]}; PNG, optimize"
            prompt, gen, date = provenance(recs.get(os.path.basename(src)), src)
            entries.append({"id": fid, "file": f"{fid}.{ext}", "variant": variant, "role": r,
                            "pairsWith": twin, "generator": gen, "prompt": prompt, "date": date,
                            "licence": LICENCE, "processing": processing})
    size = lambda e: os.path.getsize(os.path.join(DST, e["file"]))
    total = sum(size(e) for e in entries)
    for e in sorted((e for e in entries if e["file"].endswith(".png")), key=size, reverse=True):
        if total <= BUDGET:
            break
        path = os.path.join(DST, e["file"])
        before = os.path.getsize(path)
        quantized = Image.open(path).convert("RGBA").quantize(
            colors=256, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.FLOYDSTEINBERG)
        quantized.save(path, "PNG", optimize=True)
        total += os.path.getsize(path) - before
        e["processing"] += "; quantized to 256 colours (FASTOCTREE, Floyd-Steinberg) to fit the 4 MiB budget"
    if total > BUDGET:
        sys.exit(f"BLOCKED: the art is {total} bytes after quantizing, over the {BUDGET}-byte budget")
    for e in entries:
        with open(os.path.join(DST, e["file"]), "rb") as fh:
            e["sha256"] = hashlib.sha256(fh.read()).hexdigest()
    manifest = {"note": NOTE, "assets": sorted(entries, key=lambda e: e["id"])}
    with open(os.path.join(DST, "art.manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    for e in manifest["assets"]:
        print(f'{e["file"]:24} {size(e):>9} B  {e["processing"]}')
    print(f"total {total} B of {BUDGET}")


main()
```

  Then **look at every output file** (the Read tool renders PNG and JPEG) and at
  `art.manifest.json`, and check four things:
  1. Each cloud and grass file is its subject on a transparent ground, not a painted rectangle.
  2. Each `-dark` file is a night painting, not the light one dimmed.
  3. Any file marked "quantized" shows no visible banding.
  4. No prompt names a person, a place from a bank, or anything personal (the privacy rule: the
     repo is public).

  If any check fails, report BLOCKED with the file names and stage nothing.

- [ ] **Step 2: Failing tests.** `ArtAssetTests.swift`:

```swift
import AppKit
import CryptoKit
import XCTest
@testable import CicadaApp

/// G137 R-M6 / plan R-M20 — the painted Meadow art ships with its provenance,
/// the way the brand marks do (`LogoAssetTests`, Track L). A memory app whose
/// thesis is provenance does not ship a painting it cannot account for.
final class ArtAssetTests: XCTestCase {

    struct Manifest: Decodable { let assets: [Entry] }
    struct Entry: Decodable {
        let id: String
        let file: String
        let variant: String
        let role: String
        let pairsWith: String
        let generator: String
        let prompt: String
        let date: String
        let licence: String
        let processing: String
        let sha256: String
    }

    static let roles: Set<String> = ["cloud", "grass-corner", "grass-edge", "hero"]
    /// Longest side in pixels: 2× the largest point size each role is drawn at (R-M20).
    static let longestSideCap: [String: Int] = ["cloud": 800, "grass-corner": 640, "hero": 2400]
    static let byteBudget = 4 * 1024 * 1024

    private func manifest() throws -> Manifest {
        let url = try XCTUnwrap(Bundle.cicadaResources.cicadaResource("art.manifest", ext: "json", in: MeadowArt.directory),
                                "art.manifest.json is not bundled")
        return try JSONDecoder().decode(Manifest.self, from: Data(contentsOf: url))
    }

    private func bundled() -> [URL] {
        let urls = ["png", "jpg"].flatMap { Bundle.cicadaResources.cicadaResources(ext: $0, in: MeadowArt.directory) }
        XCTAssertFalse(urls.isEmpty, "no bundled art — every assertion below would pass vacuously")
        return urls
    }

    private func url(_ file: String) throws -> URL {
        let ns = file as NSString
        return try XCTUnwrap(Bundle.cicadaResources.cicadaResource(ns.deletingPathExtension, ext: ns.pathExtension,
                                                                   in: MeadowArt.directory), "\(file) is not bundled")
    }

    private func rep(_ file: String) throws -> NSBitmapImageRep {
        try XCTUnwrap(NSBitmapImageRep(data: Data(contentsOf: url(file))), "\(file) did not decode")
    }

    func testTheManifestListsEveryBundledFileAndNothingElse() throws {
        XCTAssertEqual(Set(try manifest().assets.map(\.file)), Set(bundled().map(\.lastPathComponent)),
                       "a painting without a manifest entry has no provenance; an entry without a file is a lie")
    }

    func testEveryFileMatchesItsManifestHash() throws {
        for entry in try manifest().assets {
            let hex = SHA256.hash(data: try Data(contentsOf: url(entry.file))).map { String(format: "%02x", $0) }.joined()
            XCTAssertEqual(hex, entry.sha256, "\(entry.file) is not the bytes its manifest entry describes")
        }
    }

    func testEveryEntryCarriesItsProvenanceAndItsTwin() throws {
        let entries = try manifest().assets
        let byFile = Dictionary(uniqueKeysWithValues: entries.map { ($0.file, $0) })
        for e in entries {
            for (field, value) in [("generator", e.generator), ("prompt", e.prompt),
                                   ("licence", e.licence), ("processing", e.processing)] {
                XCTAssertFalse(value.trimmingCharacters(in: .whitespaces).isEmpty, "\(e.file) has no \(field)")
            }
            XCTAssertNotNil(e.date.range(of: #"^\d{4}-\d{2}-\d{2}$"#, options: .regularExpression), "\(e.file) date")
            XCTAssertNotNil(e.sha256.range(of: #"^[0-9a-f]{64}$"#, options: .regularExpression), "\(e.file) sha256")
            XCTAssertTrue(Self.roles.contains(e.role), "\(e.file) role \(e.role)")
            XCTAssertEqual(e.id, (e.file as NSString).deletingPathExtension)
            XCTAssertEqual(e.variant, e.id.hasSuffix(MeadowArt.darkSuffix) ? "dark" : "light", e.file)
            let twin = try XCTUnwrap(byFile[e.pairsWith], "\(e.file) pairs with \(e.pairsWith), which is not listed")
            XCTAssertNotEqual(twin.variant, e.variant, "\(e.file) and its twin are the same variant")
            XCTAssertEqual(twin.pairsWith, e.file, "\(e.file) ↔ \(e.pairsWith) is not a pair")
        }
    }

    /// Every light painting has a `-dark` sibling of the same pixel size — a
    /// theme flip must never move the layout.
    func testEveryPaintingHasADarkSiblingOfTheSameSize() throws {
        for e in try manifest().assets where e.variant == "light" {
            XCTAssertEqual(e.pairsWith, "\(e.id)\(MeadowArt.darkSuffix).\((e.file as NSString).pathExtension)")
            let light = try rep(e.file), dark = try rep(e.pairsWith)
            XCTAssertEqual(light.pixelsWide, dark.pixelsWide, e.file)
            XCTAssertEqual(light.pixelsHigh, dark.pixelsHigh, e.file)
        }
    }

    func testEveryArtCaseResolvesItsOwnPaintingInBothThemes() {
        for art in MeadowArt.allCases {
            for mode in AppColorScheme.allCases {
                XCTAssertEqual(MeadowArt.url(for: art, mode: mode)?.deletingPathExtension().lastPathComponent,
                               MeadowArt.fileName(for: art, mode: mode),
                               "\(art.rawValue) does not resolve its own \(mode.rawValue) painting")
            }
        }
    }

    /// A generator that returns a painted rectangle would put a slab of sky
    /// over the page. `y == 0` is the TOP row of a decoded PNG (measured).
    func testSpritesAreCutOutNotPlates() throws {
        for e in try manifest().assets where e.role != "hero" {
            let r = try rep(e.file)
            let (w, h) = (r.pixelsWide, r.pixelsHigh)
            // A cloud is clear at all four corners; grass grows up from the
            // bottom, so only its top corners are sky.
            let corners = e.role == "cloud" ? [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)] : [(0, 0), (w - 1, 0)]
            for (x, y) in corners {
                XCTAssertLessThan(r.colorAt(x: x, y: y)?.alphaComponent ?? 1, 0.5,
                                  "\(e.file) is opaque at (\(x),\(y)) — it would paint a rectangle over the page")
            }
        }
    }

    func testArtStaysInsideItsPixelAndByteBudget() throws {
        var total = 0
        for e in try manifest().assets {
            let r = try rep(e.file)
            if e.role == "grass-edge" {
                XCTAssertLessThanOrEqual(r.pixelsHigh, 240, e.file)
                XCTAssertLessThanOrEqual(r.pixelsWide, 2400, e.file)
            } else {
                XCTAssertLessThanOrEqual(max(r.pixelsWide, r.pixelsHigh), Self.longestSideCap[e.role] ?? 0, e.file)
            }
            total += try Data(contentsOf: url(e.file)).count
        }
        XCTAssertLessThanOrEqual(total, Self.byteBudget, "the Meadow art is \(total) bytes")
    }

    /// The PR #70 class, for art: both layouts built from bytes.
    func testArtResolvesInBothBundleLayouts() throws {
        let png = try Data(contentsOf: url("cloud-1.png"))
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("art-layouts-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: root) }
        let flat = root.appendingPathComponent("Flat.bundle")
        try write(png, to: flat.appendingPathComponent("Resources/art/probe.png"))
        let nested = root.appendingPathComponent("Nested.bundle")
        try write(png, to: nested.appendingPathComponent("Contents/Resources/art/probe.png"))
        try write(Data("""
        <?xml version="1.0" encoding="UTF-8"?>
        <plist version="1.0"><dict>
        <key>CFBundleIdentifier</key><string>com.rorosaga.cicada.resources.test</string>
        <key>CFBundlePackageType</key><string>BNDL</string>
        </dict></plist>
        """.utf8), to: nested.appendingPathComponent("Contents/Info.plist"))
        for bundleURL in [flat, nested] {
            let bundle = try XCTUnwrap(Bundle(url: bundleURL), bundleURL.lastPathComponent)
            XCTAssertNotNil(bundle.cicadaResource("probe", ext: "png", in: MeadowArt.directory),
                            "art is unreachable in the \(bundleURL.lastPathComponent) layout")
        }
    }

    private func write(_ data: Data, to url: URL) throws {
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try data.write(to: url)
    }
}
```

  `MeadowTests.swift`:

```swift
import SwiftUI
import XCTest
@testable import CicadaApp

/// G137 R-M6 / plan R-M22 — the Meadow views' rules, as pure functions.
final class MeadowTests: XCTestCase {
    func testCloudsDriftGentlyAndStandStillUnderReduceMotion() {
        for t in stride(from: 0.0, through: 240.0, by: 0.5) {
            XCTAssertLessThanOrEqual(abs(MeadowRules.driftOffset(at: t, amplitude: 40, period: 5, reduceMotion: false)),
                                     CicadaMotion.ambientMaxAmplitude + 1e-9, "amplitude is capped at 8 pt")
            XCTAssertEqual(MeadowRules.driftOffset(at: t, amplitude: 8, period: 90, reduceMotion: true), 0)
        }
        // A 5 s period is clamped up to 60 s: one second in it has barely
        // moved (0.84 pt), where an unclamped 5 s period would be at 7.6 pt.
        XCTAssertLessThan(abs(MeadowRules.driftOffset(at: 1, amplitude: 8, period: 5, reduceMotion: false)), 1)
    }

    func testDriftPausesUnderReduceMotionAndWheneverTheWindowIsNotKey() {
        XCTAssertFalse(MeadowRules.isDriftPaused(reduceMotion: false, activeState: .key))
        XCTAssertTrue(MeadowRules.isDriftPaused(reduceMotion: false, activeState: .active))
        XCTAssertTrue(MeadowRules.isDriftPaused(reduceMotion: false, activeState: .inactive))
        XCTAssertTrue(MeadowRules.isDriftPaused(reduceMotion: true, activeState: .key))
    }

    func testArtFadesUnderIncreasedContrastAndMoonCloudsStayFaint() {
        XCTAssertEqual(MeadowRules.cloudOpacity(mode: .light, contrast: .standard), 0.85)
        XCTAssertLessThanOrEqual(MeadowRules.cloudOpacity(mode: .dark, contrast: .standard), 0.4)
        for mode in AppColorScheme.allCases {
            XCTAssertLessThanOrEqual(MeadowRules.cloudOpacity(mode: mode, contrast: .increased), 0.3)
        }
        XCTAssertEqual(MeadowRules.grassOpacity(contrast: .standard), 1)
        XCTAssertLessThanOrEqual(MeadowRules.grassOpacity(contrast: .increased), 0.3)
    }

    func testTheDarkPaintingIsPickedUnderTheDarkTheme() {
        XCTAssertEqual(MeadowArt.fileName(for: .cloud1, mode: .light), "cloud-1")
        XCTAssertEqual(MeadowArt.fileName(for: .cloud1, mode: .dark), "cloud-1-dark")
        XCTAssertEqual(MeadowArt.heroDay.fileExtension, "jpg", "the hero is opaque: JPEG (R-M20)")
        XCTAssertEqual(MeadowArt.grassEdge.fileExtension, "png")
    }
}
```

  `MeadowPlacementLintTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// G137 R-M6 / plan R-M21 — "art never on the graph, a list, a grid, a form
/// or a number" as a build failure, not a doc comment. A painted component
/// may be named only inside `Views/Meadow/` and by the files listed here;
/// adding one is a design decision a reviewer sees in the diff (the same
/// deliberate-act shape as `SleepNumbersLintTests`' noun list).
final class MeadowPlacementLintTests: XCTestCase {
    static let allowed: [String] = [
        "Views/Common/EmptyStateView.swift",   // G137 M1: grass corners + one cloud behind the worm
    ]
    static let needles = ["MeadowBackdrop(", "DriftingCloud(", "GrassCorners(", "GrassEdge(",
                          "MeadowSky(", "ArtImage(", "MeadowArt.image("]

    func testPaintedArtIsDrawnOnlyWhereARulingAllowsIt() throws {
        var offenders: [String] = []
        for file in try ThemeTokenTests.swiftSources() {
            let path = file.path
            guard !path.contains("/Views/Meadow/"), !Self.allowed.contains(where: { path.hasSuffix($0) }) else { continue }
            let text = try String(contentsOf: file, encoding: .utf8)
            for (index, line) in text.components(separatedBy: .newlines).enumerated() {
                let code = line.trimmingCharacters(in: .whitespaces)
                guard !code.hasPrefix("//") else { continue }
                if Self.needles.contains(where: { code.contains($0) }) {
                    offenders.append("\(file.lastPathComponent):\(index + 1)")
                }
            }
        }
        XCTAssertEqual(offenders, [], "painted art outside its allowlist — never on data surfaces (G137 R-M6)")
    }

    func testTheAllowlistNamesRealFiles() throws {
        let paths = try ThemeTokenTests.swiftSources().map(\.path)
        for allowed in Self.allowed {
            XCTAssertTrue(paths.contains { $0.hasSuffix(allowed) }, "\(allowed) no longer exists — drop it")
        }
    }
}
```

  Run `swift test --filter 'ArtAssetTests|MeadowTests|MeadowPlacementLintTests' 2>&1 | tail -20`.
  Expect a compile failure because `MeadowArt` does not exist.

- [ ] **Step 3: `Views/Meadow/MeadowArt.swift`** (full file):

```swift
import AppKit
import SwiftUI

/// The painted Meadow art, by role (G137, spec R-M6) — every file under
/// `Resources/art/`, each listed with its provenance in `art.manifest.json`
/// and held to its bytes by `ArtAssetTests`.
///
/// **Every painting has a `-dark` sibling**, painted as dusk or night — never
/// the light file dimmed — and the dark theme always gets it, the way
/// `LogoImage` picks a `-dark` mark (R-L5). **Every file is authored at 2×**
/// the point size it is drawn at, so `image(for:mode:)` sizes the `NSImage`
/// in points and a tiled strip draws at its intended height.
///
/// Lookups go through `Bundle.cicadaResource(_:ext:in:)` with the bare `"art"`
/// directory: `bundle.sh` re-nests the resource bundle, and a spelled-out
/// `Resources/` prefix resolves only under `swift test` (PR #70).
enum MeadowArt: String, CaseIterable {
    case cloud1 = "cloud-1"
    case cloud2 = "cloud-2"
    case cloud3 = "cloud-3"
    case grassLeft = "grass-left"
    case grassRight = "grass-right"
    case grassEdge = "grass-edge"
    /// The onboarding hero — bundled here, drawn by the onboarding track.
    case heroDay = "hero-day"

    static let directory = "art"
    static let darkSuffix = "-dark"
    static let pixelsPerPoint: CGFloat = 2

    /// The hero is opaque and ships as JPEG (plan R-M20); every sprite needs alpha.
    var fileExtension: String { self == .heroDay ? "jpg" : "png" }

    static func fileName(for art: MeadowArt, mode: AppColorScheme) -> String {
        mode == .dark ? art.rawValue + darkSuffix : art.rawValue
    }

    /// The theme's painting, falling back to the light one — `ArtAssetTests`
    /// guarantees the sibling exists, so the fallback only guards a bundle
    /// that lost a file (a lighter painting, never a blank).
    static func url(for art: MeadowArt, mode: AppColorScheme, in bundle: Bundle = .cicadaResources) -> URL? {
        bundle.cicadaResource(fileName(for: art, mode: mode), ext: art.fileExtension, in: directory)
            ?? bundle.cicadaResource(art.rawValue, ext: art.fileExtension, in: directory)
    }

    @MainActor private static var cache: [String: NSImage] = [:]

    /// Loaded once per painting and sized in points at 2×, so a drifting
    /// cloud's 30 fps tick is a dictionary hit, never a decode.
    @MainActor
    static func image(for art: MeadowArt, mode: AppColorScheme) -> NSImage? {
        let key = fileName(for: art, mode: mode)
        if let hit = cache[key] { return hit }
        guard let url = url(for: art, mode: mode), let image = NSImage(contentsOf: url),
              let rep = image.representations.first else { return nil }
        image.size = NSSize(width: CGFloat(rep.pixelsWide) / pixelsPerPoint,
                            height: CGFloat(rep.pixelsHigh) / pixelsPerPoint)
        cache[key] = image
        return image
    }
}

/// The rules the Meadow views follow, as pure functions (MeadowTests), so a
/// number tuned after a live look is one line, not a hunt (plan R-M22).
enum MeadowRules {
    static let lightCloudOpacity = 0.85
    /// R9 §5.3: the moon cloud at ≤ 40 %.
    static let darkCloudOpacity = 0.4
    /// R9 §7: under Increase Contrast, decoration steps back to ≤ 30 %.
    static let increasedContrastCeiling = 0.3

    static func cloudOpacity(mode: AppColorScheme, contrast: ColorSchemeContrast) -> Double {
        let base = mode == .dark ? darkCloudOpacity : lightCloudOpacity
        return contrast == .increased ? min(base, increasedContrastCeiling) : base
    }

    static func grassOpacity(contrast: ColorSchemeContrast) -> Double {
        contrast == .increased ? increasedContrastCeiling : 1
    }

    /// R-M6 "paused … in inactive windows": a window you are not looking at
    /// (not key) does not spend frames on weather.
    static func isDriftPaused(reduceMotion: Bool, activeState: ControlActiveState) -> Bool {
        reduceMotion || activeState != .key
    }

    /// A slow sine, amplitude capped at `CicadaMotion.ambientMaxAmplitude`
    /// and period clamped into `ambientPeriodRange`; exactly 0 under Reduce
    /// Motion (the terminal frame is "at rest").
    static func driftOffset(at t: TimeInterval, amplitude: CGFloat, period: TimeInterval,
                            reduceMotion: Bool) -> CGFloat {
        guard !reduceMotion else { return 0 }
        let a = min(max(amplitude, 0), CicadaMotion.ambientMaxAmplitude)
        let p = min(max(period, CicadaMotion.ambientPeriodRange.lowerBound), CicadaMotion.ambientPeriodRange.upperBound)
        return a * CGFloat(sin(2 * Double.pi * t / p))
    }
}

/// One painting in the theme's variant, at `.high` interpolation (painterly
/// art tolerates scaling; the pixel bookworm never goes through here).
/// Reading `CicadaTheme.mode` in `body` subscribes the view, so a theme flip
/// swaps in the `-dark` painting — the `LogoImage` mechanism.
struct ArtImage: View {
    let art: MeadowArt

    var body: some View {
        if let image = MeadowArt.image(for: art, mode: CicadaTheme.mode) {
            Image(nsImage: image).resizable().interpolation(.high).scaledToFit()
        } else {
            Color.clear
        }
    }
}
```

- [ ] **Step 4: `Views/Meadow/MeadowBackdrop.swift`** (full file):

```swift
import SwiftUI

// ART NEVER GOES ON DATA (G137, round-3 spec Decision 6, R9 §7). Everything
// in this file is ambient: it may sit behind onboarding, an empty state, a
// non-data page header or an About panel — and NEVER on the graph canvas, a
// list, a grid, a table, a diff, a form, or anything that carries a number.
// Text never sits directly on paint: put it on a `surface` card, or on
// `.liquidGlass(.overImagery, in:)`. Art encodes no quantity (a sunnier
// meadow never means "more memories" — G125's rule). `MeadowPlacementLintTests`
// keeps the allowlist of files that may name these views.

/// A procedural sky (R-M2): zero bytes, so night costs nothing. A `nil`
/// phase follows the theme, read in `body` so a flip repaints it.
struct MeadowSky: View {
    var phase: CicadaTheme.SkyPhase? = nil

    var body: some View {
        LinearGradient(colors: CicadaTheme.skyGradient(phase ?? .current), startPoint: .top, endPoint: .bottom)
            .accessibilityHidden(true)
    }
}

/// One painted cloud drifting a few points side to side (R-M6): ≤ 8 pt, a
/// 60–120 s period, ≤ 30 fps, still under Reduce Motion and whenever the
/// window is not key. Decorative — hidden from VoiceOver, never hit-tested.
struct DriftingCloud: View {
    var art: MeadowArt = .cloud1
    let width: CGFloat
    var amplitude: CGFloat = CicadaMotion.ambientMaxAmplitude
    var period: TimeInterval = CicadaMotion.ambientDefaultPeriod

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.controlActiveState) private var activeState
    @Environment(\.colorSchemeContrast) private var contrast

    var body: some View {
        let paused = MeadowRules.isDriftPaused(reduceMotion: reduceMotion, activeState: activeState)
        TimelineView(.animation(minimumInterval: CicadaMotion.ambientFrameInterval, paused: paused)) { context in
            ArtImage(art: art)
                .frame(width: width)
                .offset(x: MeadowRules.driftOffset(at: context.date.timeIntervalSinceReferenceDate,
                                                   amplitude: amplitude, period: period, reduceMotion: reduceMotion))
        }
        .opacity(MeadowRules.cloudOpacity(mode: CicadaTheme.mode, contrast: contrast))
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }
}

/// Grass and dandelions in the two bottom corners. Grass never moves (R-M6).
/// `height` is in points at `uiScale == 1`; the view scales it.
struct GrassCorners: View {
    var height: CGFloat = 140
    @Environment(\.colorSchemeContrast) private var contrast

    var body: some View {
        HStack(alignment: .bottom, spacing: 0) {
            ArtImage(art: .grassLeft).frame(height: CicadaTheme.scaled(height))
            Spacer(minLength: 0)
            ArtImage(art: .grassRight).frame(height: CicadaTheme.scaled(height))
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottom)
        .opacity(MeadowRules.grassOpacity(contrast: contrast))
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }
}

/// A strip of grass tiled along a bottom edge, at the painting's own 2× point
/// height (a tile is drawn at native size, so it is never stretched).
struct GrassEdge: View {
    @Environment(\.colorSchemeContrast) private var contrast

    var body: some View {
        if let image = MeadowArt.image(for: .grassEdge, mode: CicadaTheme.mode) {
            Image(nsImage: image)
                .resizable(capInsets: EdgeInsets(), resizingMode: .tile)
                .frame(height: image.size.height)
                .frame(maxWidth: .infinity)
                .opacity(MeadowRules.grassOpacity(contrast: contrast))
                .allowsHitTesting(false)
                .accessibilityHidden(true)
        }
    }
}

/// The composed backdrop a non-data screen drops behind itself.
struct MeadowBackdrop: View {
    enum Style: Equatable {
        /// Grass in the two bottom corners, nothing else — an empty state.
        case corners
        /// Sky, two drifting clouds, grass along the bottom — onboarding, a
        /// header band, an About panel. `nil` phase follows the theme.
        case meadow(phase: CicadaTheme.SkyPhase? = nil)
    }

    let style: Style

    var body: some View {
        Group {
            switch style {
            case .corners:
                GrassCorners()
            case let .meadow(phase):
                ZStack(alignment: .bottom) {
                    MeadowSky(phase: phase)
                    VStack {
                        HStack(alignment: .top) {
                            DriftingCloud(art: .cloud1, width: CicadaTheme.scaled(220))
                                .padding(.leading, CicadaTheme.spacingXXL)
                            Spacer()
                            DriftingCloud(art: .cloud3, width: CicadaTheme.scaled(150), period: 110)
                                .padding(.trailing, CicadaTheme.spacingXXL)
                        }
                        .padding(.top, CicadaTheme.spacingXL)
                        Spacer()
                    }
                    GrassEdge()
                }
            }
        }
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }
}
```

- [ ] **Step 5: Verify.** Run `swift build 2>&1 | tail -5` and `swift test 2>&1 | tail -20`
  (0 failures; all three new suites green). Then run
  `du -ch <worktree>/app/CicadaApp/Sources/CicadaApp/Resources/art/* | tail -1` and quote the
  total in the commit body.
- [ ] **Step 6: Commit.** Stage the 14 art files, `art.manifest.json`, both `Views/Meadow/` files
  and the 3 new tests, all by name. Never stage `prepare_art.py`. Message:
  `feat(meadow): painted art with a provenance manifest, and the backdrop components (G137 R-M6)`.

---

### Task 6: The empty state wakes up in the meadow (R-M23)

**Files:**
- Modify: `app/…/Views/Common/EmptyStateView.swift` (whole body `:15-40` + doc)
- Modify: `app/…/Views/Common/SettingsSectionLink.swift:27-39`
- Modify: `app/CicadaApp/Tests/CicadaAppTests/EmptyStateViewTests.swift`

**Interfaces:**
- Produces: `EmptyStateLayout` (`wormPointSize`, `cloud`, `cloudWidth`, `cloudOffset`, `cornerHeight`); `SettingsSectionLink(section:label:prominent:)`.
- Consumes: `DriftingCloud`, `GrassCorners`, `displayFont`, `radiusLarge`, `PrimaryActionButton`, `primaryActionStyle()`, `hoverLift()`, `onAccent`.

- [ ] **Step 1: Failing tests.** Append to `EmptyStateViewTests`:

```swift
    /// G137 R-M23 — the bookworm carries the state; the cloud is weather.
    func testTheBookwormStaysTheFocalPoint() {
        XCTAssertGreaterThan(EmptyStateLayout.cloudWidth, EmptyStateLayout.wormPointSize,
                             "a cloud narrower than the worm reads as a speck, not sky")
        XCTAssertLessThanOrEqual(EmptyStateLayout.cloudWidth, 2 * EmptyStateLayout.wormPointSize,
                                 "a cloud more than twice the worm's width competes with it")
        XCTAssertLessThanOrEqual(abs(EmptyStateLayout.cloudOffset.width), EmptyStateLayout.wormPointSize / 2,
                                 "the cloud sits behind the worm, not beside it")
        XCTAssertLessThanOrEqual(EmptyStateLayout.cornerHeight, 160)
    }

    /// Text never sits directly on paint (R-M23). A source check, because
    /// "which layer is under this Text" is not something a test can render.
    func testTheWordsSitOnASurfaceCardUnderADisplayTitle() throws {
        let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first {
            $0.path.hasSuffix("Views/Common/EmptyStateView.swift")
        })
        let text = try String(contentsOf: file, encoding: .utf8)
        XCTAssertTrue(text.contains(".background(CicadaTheme.surface"), "the empty state's words lost their card")
        XCTAssertTrue(text.contains("displayFont(size: 26)"))
    }

    /// The Sleep page's schedule link must render exactly as before: quiet by
    /// default, and the quiet branch keeps the accent-text recipe it always
    /// had. The prominent branch reaches glass only through the one style.
    func testTheSettingsLinkIsQuietUnlessAskedToBeProminent() throws {
        XCTAssertFalse(SettingsSectionLink(section: .integrations, label: "Open").prominent)
        XCTAssertTrue(SettingsSectionLink(section: .integrations, label: "Open", prominent: true).prominent)
        let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first {
            $0.path.hasSuffix("Views/Common/SettingsSectionLink.swift")
        })
        let text = try String(contentsOf: file, encoding: .utf8)
        XCTAssertTrue(text.contains(".buttonStyle(.cicadaPlain)"), "the quiet link lost its plain style")
        XCTAssertTrue(text.contains(".foregroundStyle(CicadaTheme.accent)"), "the quiet link lost its accent text")
        XCTAssertTrue(text.contains(".primaryActionStyle()"), "the prominent link must go through primaryActionStyle()")
    }
```

  Run `swift test --filter EmptyStateViewTests 2>&1 | tail -20`. Expect a compile failure because
  `EmptyStateLayout` and `prominent` do not exist.

- [ ] **Step 2: `SettingsSectionLink`.** Replace the struct's members (`:28-39`, from
  `let section` through the closing brace of `body`) with the block below. Do not touch the doc
  comment above the struct:

```swift
    let section: SettingsSection
    let label: String
    /// G137 R-M18: an empty state's one action is the page's one prominent
    /// action — same link, same seed write, drawn through
    /// `primaryActionStyle()` instead of as accent text. Off by default, so
    /// every other caller (the Sleep page's schedule link) renders exactly
    /// as before.
    var prominent: Bool = false

    var body: some View {
        Group {
            if prominent {
                SettingsLink { Text(label).foregroundStyle(CicadaTheme.onAccent) }
                    .primaryActionStyle()
            } else {
                SettingsLink { Text(label) }
                    .buttonStyle(.cicadaPlain)
                    .foregroundStyle(CicadaTheme.accent)
            }
        }
        .simultaneousGesture(TapGesture().onEnded {
            UserDefaults.standard.set(section.rawValue, forKey: "cicada.settingsSection")
        })
        .accessibilityLabel("\(label), opens \(Copy.settings) — \(section.title)")
    }
```

- [ ] **Step 3: `EmptyStateView`.** Keep the existing doc comment verbatim, and add this paragraph
  at its end. It must not name the settings-section key, which
  `test_emptyStateViewNoLongerMentionsTheSettingsSectionKey` bans even in comments:

```swift
///
/// **G137 — the one surface the Meadow foundation lands on in M1.** Grass
/// grows in the two bottom corners and one cloud drifts behind the bookworm,
/// which stays the focal point because it carries the state (pixel art at
/// `.interpolation(.none)` beside a painting at `.high` — two languages in one
/// frame by the owner's brief, kept apart by size and opacity). The words sit
/// on a `surface` card, never directly on paint, so a grass corner reaching
/// under them in a short window is behind a card, not behind a sentence. The
/// title is the display serif; the one action is the page's one prominent
/// action, and it lifts on hover because it opens something.
```

  Replace everything from `var body: some View {` (`:24`) to the end of the file with the
  following. The four stored properties above it stay as they are:

```swift
    var body: some View {
        VStack(spacing: CicadaTheme.spacingLG) {
            ZStack {
                DriftingCloud(art: EmptyStateLayout.cloud, width: CicadaTheme.scaled(EmptyStateLayout.cloudWidth))
                    .offset(x: CicadaTheme.scaled(EmptyStateLayout.cloudOffset.width),
                            y: CicadaTheme.scaled(EmptyStateLayout.cloudOffset.height))
                BookwormView(state: .happy, pointSize: EmptyStateLayout.wormPointSize)
            }
            VStack(spacing: CicadaTheme.spacingSM) {
                Text(title)
                    .font(CicadaTheme.displayFont(size: 26))
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .multilineTextAlignment(.center)
                Text(message)
                    .font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textSecondary)
                    .multilineTextAlignment(.center).fixedSize(horizontal: false, vertical: true)
                if let section = settingsSection, let actionLabel {
                    SettingsSectionLink(section: section, label: actionLabel, prominent: true)
                        .hoverLift()
                        .padding(.top, CicadaTheme.spacingXS)
                } else if let actionLabel, let action {
                    PrimaryActionButton(title: actionLabel, action: action)
                        .hoverLift()
                        .padding(.top, CicadaTheme.spacingXS)
                }
            }
            .padding(CicadaTheme.spacingLG)
            .frame(maxWidth: .infinity)
            .background(CicadaTheme.surface,
                        in: RoundedRectangle(cornerRadius: CicadaTheme.radiusLarge, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: CicadaTheme.radiusLarge, style: .continuous)
                .stroke(CicadaTheme.border, lineWidth: 1))
        }
        .frame(maxWidth: 360)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background { GrassCorners(height: EmptyStateLayout.cornerHeight) }
        .clipped()
    }
}

/// The empty state's composition as numbers, so "the bookworm stays the
/// focal point" is a test (`EmptyStateViewTests`), not a hope. Points at
/// `uiScale == 1`; the view scales them.
enum EmptyStateLayout {
    /// A multiple of 24 keeps the sprite's cells integer (G107 R3).
    static let wormPointSize: CGFloat = 96
    static let cloud: MeadowArt = .cloud2
    /// Wider than the worm so it reads as sky; at most twice as wide so it
    /// never reads as a second character.
    static let cloudWidth: CGFloat = 180
    /// Up and to the left: the cloud peeks out from behind the worm's head.
    static let cloudOffset = CGSize(width: -36, height: -30)
    static let cornerHeight: CGFloat = 130
}
```
- [ ] **Step 4: Verify.** Run `swift build 2>&1 | tail -5` and `swift test 2>&1 | tail -20`
  (0 failures). These must stay green: `SleepQueueCardV3Tests` (one seed writer, no key in
  `EmptyStateView.swift`), `MeadowPlacementLintTests`, `LiquidGlassLintTests` (the
  `.glassProminent` reaches `SettingsSectionLink` only through `primaryActionStyle()`) and
  `FontLiteralLintTests`.
- [ ] **Step 5: Commit.** Stage the three files. Message:
  `feat(meadow): the empty state wakes up in the meadow — grass, a cloud, words on a card (G137)`.

---

### Task 7: Docs — the rules, where the next reader will look

**Files:**
- Modify: `docs/goals/memory-evolution.md`: insert row **G137** directly after the G132 row (`:694`), in the same table (R-M25)
- Modify: `CLAUDE.md`: a new paragraph between **Brand marks (Track L)** (`:512`) and **Video (Track V)** (`:527`) in the Companion App section
- Modify: `docs/goals/TODO.md`: one row in the "🔄 In progress" table (`:335-341`)

- [ ] **Step 1: The G137 row** (one table line, same four columns as G132):

```markdown
| G137 | **Meadow — a visual system where nature is the ground and glass is the chrome, friendlier to a general public** (Rodrigo 2026-09-23: "improve the design of the cicada app … friendlier towards the general public, and in a sense have more that nature and technology futuristic in harmony collaboration look … liquid glass and the nature like features … Add animations to the icons as i hover over them") | **What was there:** one theme file with a violet near-black and a cool near-white, SF only, no display face, no motion tokens — 47 literal animation durations across 13 files, none honouring Reduce Motion outside the Sleep page — zero symbol effects, a "glass" card that is a material over an opaque page, a sidebar painting an opaque fill over what macOS 26 renders as a glass sidebar, and an Info.plist promising macOS 13 to a package built for 14. **The rules** (round-3 spec Decision 6, R-M1…R-M7; plan `2026-09-23-meadow-foundation.md` R-M8…R-M25): (1) **glass only in the chrome layer** — sidebar, toolbar, floating controls, one prominent action per page — through one `liquidGlass(_:in:)` modifier gated on macOS 26 with a material fallback that goes opaque under Reduce Transparency; content cards stay a standard material; `LiquidGlassLintTests` keeps every glass API in one file; (2) **art only on non-data surfaces** — never the graph, a list, a grid, a form or a number, and text never directly on paint; every painting ships a `-dark` sibling and a manifest entry (generator, prompt, date, licence, sha256) held to its bytes by `ArtAssetTests`; `MeadowPlacementLintTests` keeps the allowlist of files that may draw it; clouds drift (≤ 8 pt, 60–120 s, paused under Reduce Motion and in a non-key window), grass never moves; (3) **font roles** — Instrument Serif (bundled, OFL) for display at ≥ 22 pt, New York italic for the person's quoted words, SF for everything else and every number; (4) **motion is a vocabulary** — `CicadaMotion`, nil under Reduce Motion, the only place outside `SleepMotion` a duration is spelled (`MotionLiteralLintTests`); `hoverLift()` for things that open, `iconHover()` for glyphs; (5) **neutrals moved, data did not** — a warm day meadow and a blue-green night meadow; entity, state and context hues are byte-identical, and graph.js's painted twins are held to the theme by `GraphPaletteTwinTests`. **M1 foundation built on `feat/meadow-foundation`:** tokens + nature tokens + sky gradients, the bundled display face, the motion vocabulary + the 47-site migration, the glass modifier + primary action, the glass sidebar with hover glyphs, the art set + components, `EmptyStateView` as the first surface, and `LSMinimumSystemVersion` 14.0. **Open:** the M2 pass (every remaining page, logos wherever a service is named, hover everywhere, glass on the graph's floating controls only after the G109 frame-time check); the light entity-hue contrast debt the corrected theme comment now states (skill 2.93:1) is a separate data-colour decision graph.js must match. → relates **G130** (every new token scales with `uiScale`), **G125** (art encodes state, never quantity; every art bit has a text twin), **G109** (no glass or art over the graph canvas without the frame-time check). | 🛠️ M1 foundation built; M2 open |
```

- [ ] **Step 2: `CLAUDE.md`**, one paragraph in the Companion App section's voice:

```markdown
**Meadow (round 3, G137).** The visual system: *nature is the ground, glass is the chrome.*
Neutrals are a warm "day meadow" (`#F4F6F1`) and a blue-green "night meadow" (`#0D1216`); the
nature tokens (`sky`, `meadow`, `dandelion`, `cloud`, `bark`, `soil`, their washes, and procedural
day/dusk/night skies) are for washes and art only, **never a data encoding** — entity, state and
context hues did not move and graph.js's painted twins are held to the theme by a test. **Liquid
Glass lives in the chrome layer only** (sidebar, toolbar, floating controls, one prominent action
per page) through `liquidGlass(_:in:)` in `Theme/LiquidGlass.swift`, gated on macOS 26 with a
material fallback (opaque under Reduce Transparency); a lint fails the build on any glass API
elsewhere, and `GlassCard` stays a standard material. **Painted art** (`Resources/art/`,
`art.manifest.json` with generator, prompt, date, licence and sha256; every file has a `-dark`
sibling) appears only on non-data surfaces — never the graph, a list, a grid, a form or a number,
and text never sits directly on paint — enforced by an allowlist lint. **Type:** Instrument Serif
(bundled OFL, registered at launch from `Bundle.cicadaResources`' bare `fonts` directory) through
`displayFont(size:italic:)` at ≥ 22 pt, New York italic through `quoteFont`, SF for everything else.
**Motion:** `CicadaMotion` (nil under Reduce Motion) is the only place outside `SleepMotion` a
duration is spelled; `hoverLift()` for things that open, `iconHover()` for glyphs.
```

- [ ] **Step 3: `TODO.md`.** Add this row at the top of the "🔄 In progress" table:

```markdown
| **G137 Meadow (round 3)** | **M1 foundation built** on `feat/meadow-foundation` — Meadow tokens, Instrument Serif, `CicadaMotion` + hover modifiers, `liquidGlass`, the art set + manifest, the glass sidebar, the empty state. Plan: `docs/superpowers/plans/2026-09-23-meadow-foundation.md`. | Orchestrator live check (both themes, 1.0×/1.4×, Reduce Motion / Transparency / Increase Contrast), merge to `dev`; then the M2 pass. |
```

- [ ] **Step 4: Privacy read-through.** The three edits must contain no bank content, no person's
  name other than the owner's own quoted words, and no author-machine path.
- [ ] **Step 5: Commit.** Stage the three docs files. Message:
  `docs: G137 Meadow — the rules, where the next reader will look`.

---

## Not in scope

These are named so a reviewer does not read an absence as an oversight.

- **Reskinning Graph, Clusters, Feed, Inbox, Sources, Settings, Sleep or Onboarding.** That is the
  M2 pass and the wave-2 tracks (I: onboarding hero, Z: the Sleep header band, O: Settings v3). Only
  the sidebar, `PageHeader` and `EmptyStateView` change look here. The 45 migrated motion sites
  change timing by ≤ 50 ms and now honour Reduce Motion, and nothing else about them changes.
- **Logos on other pages** (M2). This track names no service in new UI.
- **The ⌘K find palette and any glass on the Ask panel** (Track S, R-M17). Only its one motion
  literal moves.
- **Glass on the graph's floating controls.** That is M2, gated on the G109 p95 frame-time check.
  `LiquidGlassGroup` is ready for it. No `backgroundExtensionEffect` anywhere yet.
- **Migrating `.glassCard()` (43 sites) or `.cicadaGlass` (11 sites).** They are content-layer
  material cards and stay so (R-M5).
- **Adding `hoverLift` to the 17 existing `onHover` fill sites.** M2 decides per surface, and never
  on dense rows.
- **Deepening the light entity hues.** That is a data-colour decision graph.js must match. The
  comment now states the debt and a test holds it to the numbers.
- **A "System" appearance mode, the menu-bar sprite palette, the app icon, and an
  About/Acknowledgements pane.** The font licence ships inside the bundle. A pane belongs to Track O.
- **The other `.white` literals across the app.** Only the sidebar badge's goes here.
- **Drawing the onboarding hero.** It is bundled with its manifest entry and drawn by Track I.
- **Committing the art-processing script** (R-M20).

---

## Verification the orchestrator runs at the end

1. `cd <worktree>/app/CicadaApp && swift build 2>&1 | tail -5` succeeds, and
   `swift test 2>&1 | tail -20` shows **0 failures**, with **1057 executed**: the 1012 on this
   base plus this track's 45 new tests. Those are 10 new suites (GraphPaletteTwin 2, CicadaMotion 5,
   MotionLiteralLint 1, CicadaFonts 5, LiquidGlassLint 3, SidebarChrome 3, PlatformFloor 1,
   ArtAsset 8, Meadow 4, MeadowPlacementLint 2) and 3 extended ones (ThemeToken +6,
   FontLiteralLint +2, EmptyStateView +3). Quote the executed count.
2. `cd <worktree> && node --test app/CicadaApp/Tests/graph/*.test.js` shows **0 failures**.
3. **Negative controls.** A lint that has never failed is not known to work. Append these four
   file-scope lines to `Views/Inbox/InboxListView.swift`. They are string literals, so they
   compile everywhere, and each lint (not the compiler) is what must fail. A real ungated
   `.glassEffect()` would stop the build with "only available in macOS 26.0 or newer" before the
   lint ever ran. Then make the two resource edits below them:
   - `private let lintProbeGlass = ".glassEffect("` → `LiquidGlassLintTests`.
   - `private let lintProbeMotion = "duration: 0.2"` → `MotionLiteralLintTests`.
   - `private let lintProbeFont = ".custom("` → `FontLiteralLintTests`.
   - `private let lintProbeMeadow = "GrassCorners("` → `MeadowPlacementLintTests`.
   - One flipped byte in `Resources/art/cloud-1.png` → `ArtAssetTests` (hash).
   - `#FFFFFF` for the dark `label` twin in `graph.js` → `GraphPaletteTwinTests`.

   Run `swift test --filter 'LiquidGlassLintTests|MotionLiteralLintTests|FontLiteralLintTests|MeadowPlacementLintTests|GraphPaletteTwinTests|ArtAssetTests'`
   and see exactly those six tests fail. Revert all six edits
   (`git checkout -- <the three files>`), run the filter again, and see it green.
4. **The assembled bundle (the PR #70 class).** After `make install-app` (orchestrator only):
   - `ls <installed app>/Contents/MacOS/CicadaApp_CicadaApp.bundle/Contents/Resources/{fonts,art}`
     lists the TTFs, `OFL.txt` and the 14 paintings.
   - `plutil -p <installed app>/Contents/Info.plist | grep LSMinimumSystemVersion` shows `14.0`.
   - Page titles render in the serif, not SF. That is the evidence that registration worked in
     the nested layout.
5. **Live app, dark and light, 1.0× and 1.4× zoom, at a 1200 pt window:**
   - **Sidebar.** On macOS 26 it is the system glass (no opaque slab). A glyph wiggles once when
     its row is hovered and bounces when chosen. The inbox badge is legible.
   - **Window.** It matches the page, with no seam or violet cast at the titlebar.
   - **Serif titles.** Each one is unclipped and on one line on Clusters, Feed, Inbox, Sources, a
     source detail page, and every Settings section (General, Sleep, Integrations, Agents, Plans &
     keys).
   - **Empty states** (the demo bank or a fresh bank, plus an empty Inbox): grass in both bottom
     corners, one cloud drifting behind the worm (the worm is the focal point), the words on a
     card, and on Graph/Feed/Sources a prominent "Open Integrations"/"Add a source" pill that
     lifts on hover and opens Settings → Integrations.
   - **Graph.** Labels, plates and edges are legible on the new neutrals in both modes. No art or
     glass appears on the canvas once it has nodes.
6. **Accessibility toggles** (System Settings → Accessibility → Display):
   - **Reduce Motion:** no cloud drift, no glyph wiggle, tab and panel changes jump.
   - **Increase Contrast:** the art is faint (≤ 30%).
   - **Reduce Transparency:** on macOS 14/15, any `liquidGlass` surface is opaque. There is none
     on screen in M1; on 26 the system handles it.
   - **Unfocused window:** the cloud stops drifting while another window is key.
7. **The PR body must state:**
   - Data hues are unchanged, pinned by `GraphPaletteTwinTests` and the theme table.
   - The accent moved per R-M8, with its old hex frozen as identity.
   - There is no backend, ETag or wire change.
   - No price or token count appears anywhere.
   - The art's provenance manifest and licence line, and the font licence.
   - The motion behaviour change under Reduce Motion (R-M12).
   - `LSMinimumSystemVersion` went from 13.0 to 14.0.
