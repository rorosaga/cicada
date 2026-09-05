# App-wide zoom, slice 1b — the literal-font migration (G130) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every literal `.font(.system(size: N…))` / `Font.system(size: N…)` in `app/CicadaApp/Sources/` goes through `CicadaTheme.font(size:…)` (shipped in PR #54), so ⌘+ / ⌘− reach the ~330 sizes that the theme tokens do not, and a source lint keeps literals out for good. Same numbers, same weights, same designs — a mechanical rewrite, verified by the compiler and the full suite.

**Architecture — what slice 1a already built (PR #54, merged into `dev` before this track's base commit) vs. what this slice (1b) does:** `ThemeStore` (the `@Observable` object behind `CicadaTheme.mode`, PR #49) already has `uiScale`; `CicadaTheme`'s font and spacing tokens are already computed from it, so every reader already repaints on a change with no `.id()` anywhere (the PR #49 lesson); `CicadaTheme.font(size:weight:design:)` already exists; the View-menu `CommandGroup`, the ⌘⇧= key monitor, the Settings *General* tab and `BookwormView`'s point-size snap are all already shipped. **None of that is this plan's work — verify it exists (§ "What the code actually does today" below), don't rebuild it.** What slice 1b actually does is Task 1 alone: a `CicadaTheme.font(size:weight:design:)` helper call replaces every *remaining* literal `.system(size:)` / `Font.system(size:)` in `Sources/` outside `Theme/CicadaTheme.swift` (a mechanical migration + a source lint that no literal survives), plus Task 2's doc updates.

**Tech Stack:** SwiftUI + AppKit + XCTest (`app/CicadaApp`). No backend.

**Spec:** `docs/superpowers/specs/2026-09-05-study-desk-zoom-settings-sources-design.md` § Track B; backlog row **G130** (`grep -n '^| G130 ' docs/goals/memory-evolution.md`) — its four rails: no backend, persisted value survives relaunch, ⌘0 always returns to 1.0, scaled layouts must not clip, ⌘1–6 keep working.

## What the code actually does today (verify on the track's base commit — line numbers drift)

**Slice 1a (PR #54) is already merged into this track's base (`b5a02ff`) — the plan's earlier drafts described the pre-1a state; that state no longer exists. Confirmed on the base commit:**

- `app/CicadaApp/Sources/CicadaApp/Theme/CicadaTheme.swift`: `ThemeStore` (`@Observable final class`, `static let shared`, `scaleKey = "cicada.uiScale"`, `uiScale: Double` clamped `0.8...1.4` and read from `UserDefaults` in `init`, `mode` for color scheme as before) — **already exists, do not add it**. `CicadaTheme.uiScale` get/set (idempotent — the setter at ~line 201 returns early when the clamped value is unchanged), `zoomIn()`/`zoomOut()`/`resetZoom()` (~lines 207–209). Typography is already derived: `static var titleFont: Font { font(size: 20, weight: .semibold) }` (~line 240), `headingFont` 16 medium, `bodyFont` 13, `captionFont` 11, `monoFont` 12 monospaced — all `static var`, not `static let`. Spacing likewise: `static var spacingXS: CGFloat { scaled(4) }` (~line 247) through `spacingXXL` 32. `cornerRadius`/`cornerRadiusSmall` (12/8) stay `static let` — unscaled, per R2. `CicadaTheme.font(size:weight:design:)` (~line 233) is the helper Task 1 calls into; it is the ONLY place in `Sources/` allowed to contain a literal `.system(size:` (the file is excluded from the lint by name).
- `Tests/CicadaAppTests/ThemeReactivityTests.swift` — the observation-tracking pattern (`withObservationTracking { _ = CicadaTheme.background } onChange: { … }`) to mirror if a new reactivity test is ever needed (Task 1 doesn't need one — it's a source lint, not a behavior test).
- `Tests/CicadaAppTests/SettingsEntryPointTests.swift` — the `sourceFiles()` enumeration helper (walks `Sources/CicadaApp` from `#filePath`, filters `.swift`) that `FontLiteralLintTests` reuses verbatim; it already has a passing `testTheAppStillCarriesTheZoomCommandGroup` covering the View-menu `CommandGroup`, so Task 1 does not need to re-verify that.
- `CicadaApp.swift`: already has a `CommandGroup(after: .sidebar)` (~line 199) for *Zoom In* ⌘=/*Zoom Out* ⌘−/*Actual Size* ⌘0, and an `NSEvent.addLocalMonitorForEvents(matching: .keyDown)` installed in `.onAppear` (~line 111) that routes ⌘⇧= through `Theme/ZoomKeyRouter.swift`'s pure `ZoomKeyRouter.action(...)`. **Already shipped — R5 is satisfied, nothing to build here.**
- `Views/Settings/SettingsScene.swift`: already has a *General* tab (Appearance + the Text-size slider, R8) ahead of `ConnectView` (Agents), `ConnectionsView` (Plans & keys), `SettingsSleepView` (Schedule). **Already shipped.**
- `Views/Common/BookwormView.swift`: already renders at `BookwormRenderer.snappedPointSize(pointSize * CicadaTheme.uiScale)` (~line 48), `pointSize: CGFloat = 96`; `BookwormRenderer.cachedImage(state:frameIndex:pointSize:)` keys its cache on `Int(pointSize)`. **Already shipped — R6 is satisfied.**
- **Literal fonts (measured fresh on `b5a02ff`, app/CicadaApp/):** `grep -rn '\.system(size:' Sources --include='*.swift' | grep -v Theme/CicadaTheme.swift | wc -l` → **315** hits in **48** files (sizes 7…52, not the smaller range an earlier draft of this plan cited — recount on the day, other tracks land literals of their own in between). `grep -rn 'Font\.system(size:' Sources --include='*.swift' | grep -v Theme/CicadaTheme.swift | wc -l` → **0** (slice 1a's own `font()` helper is the only remaining `Font.system(size:` call site, and it lives inside the excluded file). `grep -rnE '\.frame\(width: ?[0-9]' Sources --include='*.swift' | wc -l` → **100** literal-width frames (**122** counting non-literal `.frame(width:` too), left alone per R7.
- `Sidebar` shortcuts: `SidebarView.sidebarButton` binds ⌘1–⌘6 view-locally; `AskButton` (in `ContentView.swift`) ⌘K; `GraphSearchField` (also in `ContentView.swift`, not a separate `GraphView.swift` binding) ⌘F; `FeedView` ⌘N; `SourceDetailView`/`EntityDetailCard` ⌘[. Unaffected by this slice — informational only.

## Global Constraints

- Work ONLY in `<worktree>/` (branch `feat/font-migration`, based on `dev` @ `b5a02ff`). Absolute paths; `cd <worktree> && …` for every command.
- NEVER read the bank (`memory/`), `~/.cicada`, `~/Library`, `~/.claude/projects`.
- Swift: `cd <worktree>/app/CicadaApp && swift build 2>&1 | tail -5`; `swift test 2>&1 | tail -20` → 0 failures. NEVER `make dev`/`install-app`/`swift run`/launch the app.
- Named files only in `git add`; never `memory/`, `logs/`, `.claude/`, `api/.venv`, `*-report.md`. No push, no subagents.
- **No `.id()` on the root or on any container to force a repaint** — the store's observation is the mechanism (PR #49).
- The graph `WKWebView`, its d3 zoom, and `GraphContainerView`'s own zoom controls are untouched.
- Docstrings explain WHY (cite G130 / PR #49).

## Rulings (binding)

**R1, R2, R4–R8 are already satisfied by slice 1a's shipped code (PR #54) — read them as the constraints Task 1's migration must not violate, not as work items. Only R3 is this plan's own deliverable.**

- **R1 — one scale, clamped, stepped.** `uiScale ∈ [0.8, 1.4]`, persisted under `cicada.uiScale`, changed in 0.1 steps (`zoomIn`/`zoomOut` round to one decimal so 0.1 + 0.2 arithmetic never drifts). `1.0` is today's layout exactly: `scaled(x) == x` at 1.0.
- **R2 — tokens derive, call sites don't change.** The five font tokens and six spacing tokens become `static var` computed from the scale; the 293 `CicadaTheme.*Font` and 571 `CicadaTheme.spacing*` call sites are untouched. Corner radii and stroke widths stay fixed (a border is not text).
- **R3 — literals migrate mechanically, and a lint keeps them out (Task 1 below — this plan IS that follow-up track).** Every `.font(.system(size: N…))` and `Font.system(size: N…)` in `Sources/` (outside `Theme/CicadaTheme.swift`) becomes `CicadaTheme.font(size: N…)` — same numbers, same weights, same designs. A source-lint test (the `SettingsEntryPointTests` pattern) fails on any surviving literal. `Image(systemName:)` symbol fonts migrate too — an icon beside scaled text must scale with it.
- **R4 — the setter is idempotent and never called from a `body`.** `CicadaTheme.uiScale = x` returns early when unchanged (the PR #49 invalidation-loop trap). Only commands, the key monitor and the Settings slider write it.
- **R5 — the menu owns ⌘= / ⌘− / ⌘0; a local monitor owns ⌘⇧= ("+").** SwiftUI cannot give one menu item two key equivalents and two "Zoom In" rows would read as a bug, so the View menu shows *Zoom In ⌘=*, *Zoom Out ⌘−*, *Actual Size ⌘0*; an `NSEvent.addLocalMonitorForEvents(matching: .keyDown)` installed once in `CicadaApp.onAppear` routes ⌘⇧= to `zoomIn()` through the pure `ZoomKeyRouter.action(characters:modifiers:)`, which is what the test covers. The monitor returns `nil` only for the events it handled.
- **R6 — the mascot snaps.** `BookwormView` renders at `BookwormRenderer.snappedPointSize(pointSize * CicadaTheme.uiScale)` = `max(24, 24 · round(x / 24))`; cells stay integer, the cache key stays an `Int`.
- **R7 — slice 1 leaves fixed frames alone.** The 1.4 cap plus `lineLimit(1)`/`fixedSize(horizontal: false, vertical: true)` habits keep text inside them; anything that visibly clips at 1.4 on the demo bank is a follow-up line on the G130 row, not a reason to touch the ~100 literal-width frames.
- **R8 — the Settings slider is a "General" tab for now.** `SettingsScene` gains a first tab *General* (`gearshape`) holding Appearance (Dark/Light, the same `cicada.colorScheme` key the sidebar toggle writes) and *Text size* (a `Slider` 0.8…1.4, step 0.1, with "Actual size" reset). Track C turns the tab into the General section of its sidebar.

### Task 1: The literal migration and the lint

**Files:** every `Sources/**/*.swift` with a literal (48 files as of this plan's base commit `b5a02ff` — this task itself runs later, after more branches merge, so recount rather than trust this number); `Tests/CicadaAppTests/FontLiteralLintTests.swift` (new).

- [ ] **Failing lint test** (write first): enumerate `Sources/CicadaApp/**/*.swift` except `Theme/CicadaTheme.swift`; assert no file contains `.system(size:` or `Font.system(size:`; the failure message names the file and line. It fails on ~315 hits as of this plan's base commit (recount on the day: other tracks land literals of their own in between). Mirror `SettingsEntryPointTests.swift`'s `sourceFiles()` helper for the enumeration (same package, same `#filePath`-relative walk) rather than re-deriving the path math:

```swift
import XCTest
@testable import CicadaApp

/// G130 R3: every literal `.system(size:)` / `Font.system(size:)` in the app
/// went through the mechanical migration onto `CicadaTheme.font(size:...)` so
/// ⌘+/⌘−/⌘0 (G130 slice 1a, PR #54) reach it. A source lint, not a behavior
/// test, because the defect is "a literal exists in the diff" — nothing a
/// rendered view's output would tell you apart from a scale bug.
final class FontLiteralLintTests: XCTestCase {
    /// `Theme/CicadaTheme.swift` is the one file allowed to contain a literal
    /// — it's where `CicadaTheme.font(size:...)` itself calls `.system(size:)`.
    private static let excludedFile = "Theme/CicadaTheme.swift"

    private func sourceFiles() throws -> [URL] {
        // …/Tests/CicadaAppTests/<this file> → …/Sources/CicadaApp
        let sources = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()   // CicadaAppTests
            .deletingLastPathComponent()   // Tests
            .deletingLastPathComponent()   // CicadaApp (package root)
            .appendingPathComponent("Sources/CicadaApp")
        let all = FileManager.default.enumerator(at: sources, includingPropertiesForKeys: nil)?
            .compactMap { $0 as? URL }
            .filter { $0.pathExtension == "swift" }
            .filter { !$0.path.hasSuffix(Self.excludedFile) } ?? []
        XCTAssertFalse(all.isEmpty, "found no sources under \(sources.path) — the lint would pass vacuously")
        return all
    }

    func testNoLiteralSystemFontSizeSurvives() throws {
        let needles = [".system(size:", "Font.system(size:"]
        for file in try sourceFiles() {
            let text = try String(contentsOf: file, encoding: .utf8)
            for (index, line) in text.components(separatedBy: .newlines).enumerated() {
                for needle in needles where line.contains(needle) {
                    XCTFail(
                        "\(file.lastPathComponent):\(index + 1) still has a literal \(needle) — "
                        + "route it through CicadaTheme.font(size:weight:design:) instead (G130 R3)."
                    )
                }
            }
        }
    }
}
```

- [ ] **Migrate mechanically** (from `app/CicadaApp`):

```sh
grep -rl '\.system(size:' Sources --include='*.swift' | grep -v 'Theme/CicadaTheme.swift' | xargs sed -i '' -e 's/\.font(\.system(size:/.font(CicadaTheme.font(size:/g' -e 's/Font\.system(size:/CicadaTheme.font(size:/g'
grep -rn '\.system(size:' Sources --include='*.swift' | grep -v 'Theme/CicadaTheme.swift'
```

Fix by hand whatever the second grep still lists — the sed only rewrites `.font(.system(size:` and `Font.system(size:`, so a literal reached through a typed `Font` property's default value has neither prefix and survives both passes. Two real ones on this base commit: `Views/Sleep/SleepView.swift:282` (`captionFont: .system(size: 20, weight: .semibold, design: .monospaced)`, a named argument) and `Views/Common/BookwormView.swift:22` (`var captionFont: Font = .system(size: 13, weight: .semibold, design: .monospaced)`, a stored-property default) — both take `.system(size:` → `CicadaTheme.font(size:` with nothing else to change, since `CicadaTheme.font(...)` returns a `Font` and both sites are already `Font`-typed. Build after each hand fix; the compiler catches any mis-edit. Spot-check five files for identical numbers.

- [ ] Build, run the whole suite (0 failures), commit `refactor(app): every literal font size goes through CicadaTheme.font so zoom reaches it (G130 R3)` — stage the touched files by name (`git add $(grep -rl 'CicadaTheme.font(size:' Sources --include='*.swift') Tests/CicadaAppTests/FontLiteralLintTests.swift`).


### Task 2: Docs

Four edits, all in this worktree's `docs/` and `CLAUDE.md` (grep the anchor text first — these are exact strings on the base commit `b5a02ff`, not just descriptions):

- [ ] **`CLAUDE.md`**, end of the "**View menu (G130 slice 1a).**" paragraph (`grep -n 'View menu (G130' CLAUDE.md`): append one sentence after "...alongside Agents, Plans & keys and Schedule." — the new sentence: "Slice 1b (PR #TBD) finished the job: every literal `.font(.system(size:))` / `Font.system(size:)` in `Sources/` now goes through `CicadaTheme.font(size:...)`, and `FontLiteralLintTests` fails the build on a new one."

- [ ] **`docs/goals/memory-evolution.md`**, the G130 row (`grep -n '^| G130 ' docs/goals/memory-evolution.md`): replace the sentence beginning "**Slice 1b remains open** — the mechanical `.system(size:)` → `CicadaTheme.font(size:)` migration across ~46 files plus the source-lint that keeps literals out, its own follow-up PR." with "**Slice 1b shipped (2026-09-05, PR #TBD)** — the mechanical `.system(size:)` → `CicadaTheme.font(size:)` migration across the ~48 files that still had one, plus `FontLiteralLintTests` keeping new literals out." and update the row's trailing triage cell from "🛠️ slice 1a shipped; slice 1b + slice 2 open" to "🛠️ slice 1a + 1b shipped; slice 2 open".

- [ ] **`docs/goals/TODO.md`**, the `## ✅ Shipped` G130 bullet (`grep -n 'G130 slice 1a' docs/goals/TODO.md`): it currently ends "...the graph canvas keeps its own zoom (slice 2 stays open on a measured need; slice 1b, the literal-font migration + lint, is its own follow-up)" — replace with "...the graph canvas keeps its own zoom (slice 2 stays open on a measured need); **slice 1b (2026-09-05, PR #TBD)** did the mechanical literal-font migration plus a source lint (`FontLiteralLintTests`) that keeps new ones out". Retitle the bullet's lead-in from "G130 slice 1a app-wide zoom" to "G130 slice 1a+1b app-wide zoom" and add the second PR number alongside #54.

- [ ] **`docs/goals/TODO.md`**, the `### Small & cheap — grab when passing` section: it still carries a `- **G130** app-wide zoom...` bullet (`grep -n '^- \*\*G130\*\*' docs/goals/TODO.md`) written before slice 1a landed — it claims "the app defines no `.commands` at all" and "Slice 1: a persisted `uiScale`...", both long since shipped. Delete that whole bullet; the `## ✅ Shipped` entry (previous edit) is now the only G130 mention outside the backlog row, and a stale duplicate saying the opposite of what's true is worse than no mention.

Commit `docs: font-literal migration shipped (G130 slice 1b)`.

## Verification the orchestrator runs
`swift test` 0 failures; `grep -rn '\.system(size:' app/CicadaApp/Sources --include='*.swift' | grep -v Theme/CicadaTheme.swift` → empty; `make dev`; ⌘+ three times → every caption and mono label grows with the tokens.
