# Sources page redesign — Track D implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Sources page (G124, shipped PR #47) shows a flat, unsorted grid of bare-SF-Symbol
cards and a connected/not-connected dot that never says *what a browser watch is actually doing*.
This track — Track D of the 2026-09-05 five-track design
(`docs/superpowers/specs/2026-09-05-study-desk-zoom-settings-sources-design.md`) — makes the grid
**logo-first and grouped by kind**, gives a watched channel's card the same status light its
channel-state page already has, adds a **hover quick action** (Sync now / Poll now) so a person
never has to open a page to run the one thing they came to do, and gives the per-source page a
**one-sentence "what Cicada reads from this"** plus a **queue strip** ("N waiting for Sleep" +
Consolidate now, and what has already been folded in) so a source's page answers "is this working"
without a chart — the 2026-09-03 no-graphs-for-sources ruling holds here too.

**Architecture:** APP-ONLY. Every wire model (`SourceOverview`, `EpisodeQueueItem`,
`SourceChannel`) and every endpoint (`/sources/overview`, `/sleep/episodes`, `/sources/channels`)
this track reads already ships on `dev` — nothing here adds a field, a route, or an ETag. The work
is five pure functions (`SourceSections.group`, `SourceCard.quickAction`,
`SourceCard.accessibilityLabel`, `SourceBlurb.text`, `SourceOverview.ownedQueue` +
`SourceQueueLabels`), one extracted action layer (`ChannelActions`, shared by the card and the
detail page so "Sync now" means the same thing in both places), one small additive change to a
shared component (`PageHeader` gains an optional, default-`nil` leading slot), and the views that
wire all of it together. A parallel track edits `api/models/schemas.py` and `api/routers/sleep.py`
for Track A (the study desk) — **this plan never opens either file**.

**Tech Stack:** SwiftUI + XCTest (`app/CicadaApp`). No Python, no bank, no network.

**Spec:** `docs/superpowers/specs/2026-09-05-study-desk-zoom-settings-sources-design.md` § Track D
is the brief. `docs/goals/memory-evolution.md` row **G124** (rulings R1–R17, shipped shape
`docs/superpowers/plans/2026-09-03-g124-sources-page.md`) is what Track D extends — read there
first for why the catalog, `origins`, `harness`, `countLines` and `ownedItems` are shaped the way
they are; this plan does not re-derive them.

## Global Constraints

- Work ONLY in `/Users/rorosaga/Documents/roros_lab/cicada/.worktrees/sources` (branch
  `feat/sources-redesign`, based on `dev` @ `96df878`). Every shell command is
  `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/sources && <cmd>` with the ABSOLUTE
  path (`zoxide` hijacks relative `cd`; ignore its stderr banner). No unquoted
  `grep --include=*.ext` (zsh globbing breaks it) — quote it or grep a directory instead.
- **NEVER read** `/Users/rorosaga/Documents/roros_lab/cicada/memory` (any bank), `~/.cicada`,
  `~/Library`, or `~/.claude/projects` — real personal data. This track touches no fixtures that
  read the filesystem at all; every test here is a pure Swift value test.
- Swift: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/sources/app/CicadaApp && swift build 2>&1 | tail -5`
  must succeed and `swift test 2>&1 | tail -20` must report **0 failures**. SourceKit diagnostics
  naming OTHER worktrees are noise. **NEVER** run `make dev`, `make install-app`, `swift run`, or
  launch/kill the Cicada app — the owner's installed app is live; the orchestrator installs at the
  end.
- Never `git add -A`; stage named files only (`git add -- <path> <path>`). Never commit `memory/`,
  `logs/`, `.claude/`, `api/.venv`, `*-report.md`. No push, no new branches/worktrees, no PR, no
  subagents. Ignore Devin/PR comments.
- **This track is APP-ONLY.** It never opens `api/models/schemas.py` or `api/routers/sleep.py` (a
  parallel track owns them for Track A) and adds no endpoint, no field, no ETag change. Every
  count this plan renders already exists on a `Store` snapshot the app already fetches.
- **Rails from CLAUDE.md this track touches:** no prices or token counts anywhere in the app (the
  2026-09-03 ruling; `SourceBlurb` sentences are checked for a bare `$` in the test); every
  wire-model field this plan reads is already optional-with-a-default (Swift decode tolerance) —
  nothing here changes a decoder; `Copy.swift`/`CopyConstantsTests` are untouched (no new Copy
  constants — the two action labels stay the literal strings `"Sync now"`/`"Poll now"` the code
  already uses in `ChannelSourceView`); browser files are read app-side only, never by the
  launchd backend — `ChannelActions.sync` delegates to the existing `BrowserImportActions
  .syncChannel`, so that boundary is untouched.
- Cicada docstrings explain WHY, citing the G-row or review that motivated a rule. Match that
  density.
- Read code at the cited `file:line` before editing — line numbers are from the base commit
  `96df878` and drift as tasks land within this same plan.

## Rulings (binding — decided here so no task stalls; each carries its reason)

- **R-D1 — `PageHeader` gains one optional, default-`nil` `leading: AnyView?` slot rather than a
  second generic parameter or a bespoke header rebuilt inside `SourceDetailView`.** `AnyView?`
  (not a second `some View` generic) keeps the existing `Trailing == EmptyView` convenience `init`
  source-compatible with zero changes, and `nil` (not `AnyView(EmptyView())`) means the `HStack`
  never inserts a spacing gap in front of a title that has no leading view — every one of the six
  other `PageHeader(...)` call sites (`SettingsSleepView`, `InboxListView`, `ConnectionsView`,
  `FeedView`, `TopicsView`, `ConnectView`) renders byte-identical to before this change. A bespoke
  header duplicated in `SourceDetailView` was rejected: it would duplicate `PageHeader`'s padding
  and font tokens and drift from the other six pages' header the next time either changes.
- **R-D2 — the quick-action button is a sibling of the card's open-page `Button`, in a `ZStack`,
  never nested inside its label.** Two overlapping `Button`s hit-test independently in SwiftUI —
  the frontmost (last-declared, or the one `ZStack` draws on top) wins a tap in the overlap region
  — so putting the action button in a `ZStack` overlay on top of (not inside) the card's own
  `Button` guarantees a tap on the small action button can never also fire `onOpen`. This is a
  structural guarantee (verified by reading the view tree, matching the brief's "test by
  construction" — the codebase has no view-inspection test library, confirmed:
  `grep -n "ViewInspector" app/CicadaApp/Package.swift` is empty), not a runtime test.
- **R-D3 — quick-action precedence is sync-over-poll, decided once in `SourceCard.quickAction`.**
  No row in `api/services/source_overview.CATALOG` carries both actions today (browsers/OAuth
  connectors get `sync` [+ `disconnect`]; feeds/calendars get `poll` [+ `manage`] —
  `api/services/channel_registry.py:82,107,171`), so the precedence never actually triggers on
  live data; deciding it once here (rather than leaving two `if`s to silently render both buttons
  side by side, cramping the small card) means a future channel that somehow advertises both still
  renders one clean action instead of two crammed ones.
- **R-D4 — `ChannelActions.sync` is a thin delegator to the existing
  `BrowserImportActions.syncChannel`, not a re-homed copy of it.** That function is already the
  one shared browser-file-read-and-post implementation (`BrowserImportPanels.swift:14-40`); moving
  its body would touch the Safari-import R1 boundary (the app reads `~/Library`, the backend never
  does) for no reason. `ChannelActions.poll` IS a move (not a delegation) of `ChannelSourceView`'s
  former private `pollNow` — there was no existing shared function to delegate to, and the brief
  requires the gate message stay byte-identical, which a straight move guarantees better than a
  rewrite would.
- **R-D5 — a quick action's failure is swallowed on the card (best-effort), not surfaced inline.**
  The compact card has no room for an error line without pushing the grid's row heights around on
  every card whenever one fails; the same action's real feedback (success text, the gate message,
  a red error line) is one click away via the identical action on `ChannelSourceView`, which keeps
  its full feedback UI unchanged. The card still refreshes the four domains
  (`.channels, .sources, .sourcesOverview, .status`) after every attempt — success or failure —
  so a failed sync's `lastError` still reaches the card's own "Needs attention" line on the next
  paint.
- **R-D6 — `BrowserStatusLight`'s `compact` mode is reused exactly as it exists today, including
  its `.blocked`-state `FullDiskAccessHint`.** The brief asks for
  `BrowserStatusLight(state:error:compact: true)` verbatim; `.blocked` is a rare state (the app
  lacks Full Disk Access for one specific browser file) and showing the fix immediately on the
  card — rather than only after opening the page — matches the existing rail that "the one state
  with something to do carries the fix beside it" (`BrowserStatusLight.swift`'s own doc comment).
  No new compact-without-hint variant is introduced.
- **R-D7 — the queue strip's Consolidate button duplicates (does not import) `SleepQueueCard`'s
  capsule styling.** `SleepQueueCard.swift` is Track A's file and is being rebuilt into the study
  desk in a track running in parallel on its own worktree; importing a symbol from it here would
  create a merge collision between two independently-reviewed branches over a file neither track
  otherwise needs to touch. The two capsules are ~15 lines of `Capsule()`/`CicadaTheme.accent`
  styling — cheap to duplicate, expensive to coordinate a shared extraction across two in-flight
  worktrees for.
- **R-D8 — `ownedQueue` has NO legacy-unstamped fallback, even for the `files` row.** `ownedItems`
  (G124, unchanged) adopts a nil-origin *media page* into `files` because a link saved before the
  origin stamp shipped truly has no other home. `EpisodeQueueItem.origin`, by contrast, defaults to
  the **literal string `"unknown"`** on an older backend (`APIClient.swift:751`) — not empty, not
  nil — so there is no ambiguous "was never stamped" case to rescue: an `"unknown"`-origin queued
  episode is either a real gap in a writer (already tracked as a G124 follow-up on the backlog row)
  or genuinely unidentifiable, and silently counting it into `files`' "N waiting for Sleep" would
  overstate that row and understate the real problem. Exact-origins-only, disclosed in the
  function's doc comment.
- **R-D9 — `SourceSections`, `SourceQueueLabels`/`SourceOverview.ownedQueue`, and `SourceBlurb`
  are placed beside the model or beside their own view file, matching the house pattern already in
  this directory** (`ConversationFilter`/`SourceItemsGrouping` live in `Models/SourceOverview.swift`
  beside the struct they operate on; `groupEpisodesByOrigin`/`OriginBucket` live beside the view
  that renders them in `SleepDebtBreakdown.swift`). `SourceSections.group` and `ownedQueue` go in
  `Models/SourceOverview.swift`; `SourceQueueLabels` goes beside `SourceQueueStrip` in its own new
  file; `SourceBlurb` gets its own new file (no existing file it belongs beside).
- **R-D10 — task order is grid → card actions → header → queue strip → docs**, matching the
  brief's own numbering. Each task's diff to a shared file (`SourceDetailView.swift` is touched by
  tasks 3 and 4) is additive to the previous task's version, so every commit in the sequence
  builds and tests green on its own — there is no forward reference to a symbol a later task
  introduces.

---

## File map

| File | Responsibility |
|---|---|
| `Models/SourceOverview.swift` | + `SourceSections.group` (Task 1), + `ownedQueue(from:)` (Task 4) |
| `Views/Sources/SourceCardGrid.swift` | grouped-by-kind grid (Task 1); `SourceCardTile` (hover + quick action) and `SourceCard`'s `quickAction`/`accessibilityLabel`/status-light (Task 2) |
| `Views/Sources/ChannelActions.swift` (new, Task 2) | `sync`/`poll` — shared by the card and `ChannelSourceView` |
| `Views/Sources/ChannelSourceView.swift` | Task 2: its two action closures now call `ChannelActions`; its private `pollNow` is deleted |
| `Views/Sources/SourceBlurb.swift` (new, Task 3) | per-source "what Cicada reads from this" sentence |
| `Views/Sources/SourceDetailView.swift` | Task 3: header gains the mark + blurb; Task 4: renders `SourceQueueStrip` |
| `Views/Sources/SourceQueueStrip.swift` (new, Task 4) | `SourceQueueLabels` (pure) + `SourceQueueStrip` (view) |
| `Views/Common/PageHeader.swift` | Task 3: optional `leading: AnyView?` slot |
| `Tests/CicadaAppTests/SourcesPageTests.swift` | every new pure-function test, appended task by task |
| `docs/goals/memory-evolution.md`, `docs/goals/TODO.md` | Task 5: Track D shipped notes |

---

### Task 1: Grouped grid by kind + real marks on the cards

**Files:**
- Modify: `app/CicadaApp/Sources/CicadaApp/Models/SourceOverview.swift` (append `SourceSections`
  after `SourceItemsGrouping`, :183-194)
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sources/SourceCardGrid.swift` (full rewrite — 82
  lines)
- Test: `app/CicadaApp/Tests/CicadaAppTests/SourcesPageTests.swift` (append)

**Interfaces:**
- `SourceSections.group(_ rows: [SourceOverview]) -> [(kind: SourceKind, title: String, rows: [SourceOverview])]`
  — pure; order = `SourceKind.order` with empty kinds skipped, within-kind order = `gridOrder`.

- [ ] **Step 1: Write the failing tests** — append to `SourcesPageTests.swift`, immediately
  before the `final class SourcesPageTests: XCTestCase { ... }` body's closing `}` (every method
  below, including any private helper, is a member of that class — not top-level code):

```swift
    // MARK: - Track D: grouped grid (2026-09-05 sources redesign)

    func testSourceSectionsGroupsByKindOrderAndSkipsEmptyKinds() {
        let a = SourceOverview(id: "rss", label: "RSS", kind: .feed, lastActivityAt: "2026-09-02T00:00:00+00:00")
        let b = SourceOverview(id: "harness:cursor", label: "Cursor", kind: .harness, lastActivityAt: "2026-08-01T00:00:00+00:00")
        let c = SourceOverview(id: "harness:claude-code", label: "Claude Code", kind: .harness, lastActivityAt: "2026-09-01T00:00:00+00:00")
        let d = SourceOverview(id: "telegram", label: "Telegram", kind: .messaging)
        let sections = SourceSections.group([a, b, c, d])
        XCTAssertEqual(sections.map(\.kind), [.harness, .feed, .messaging],
                        "no browser/social/import rows in the input -> those headers never appear")
        XCTAssertEqual(sections.map(\.title), ["CHAT & AGENTS", "FEEDS & CALENDARS", "MESSAGING"])
        XCTAssertEqual(sections[0].rows.map(\.id), ["harness:claude-code", "harness:cursor"],
                        "within-kind order is still gridOrder — newest activity first")
    }

    func testSourceSectionsEveryKindGetsANonEmptyHeader() {
        for kind in SourceKind.allCases {
            let row = SourceOverview(id: "x-\(kind.rawValue)", label: "X", kind: kind, episodes: 1)
            XCTAssertFalse(SourceSections.group([row]).first!.title.isEmpty, "\(kind) must render a header")
        }
    }

    func testSourceSectionsOnEmptyInputIsEmpty() {
        XCTAssertTrue(SourceSections.group([]).isEmpty)
    }
```

- [ ] **Step 2: Run the tests to confirm they fail**

```
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/sources/app/CicadaApp && swift build 2>&1 | tail -20
```
Expected: a compile error — `SourceSections` does not exist yet.

- [ ] **Step 3: `SourceSections`** — append to the end of `Models/SourceOverview.swift` (after
  `SourceItemsGrouping`, :194):

```swift

/// Section headers for the Sources grid (Track D — "in a grid, grouped by
/// kind, no horizontal scroll"). Pure: given the rows a page already has, in
/// what order and under what caption they render. `SourceKind.order` decides
/// section order (mirrors the backend's `KIND_ORDER`, with `.unknown` last
/// for a kind a newer backend invents); a kind with no rows never prints an
/// empty header (R2's "a row is shown only when it has evidence" extends
/// naturally to "a section is shown only when it has a row"). Within a
/// section the order is `gridOrder`'s own — re-derived here rather than
/// assumed, so a caller that hands in an unsorted list still gets a
/// correctly ordered grid.
enum SourceSections {
    private static let titles: [SourceKind: String] = [
        .harness: "CHAT & AGENTS",
        .browser: "BROWSERS",
        .social: "SOCIAL & SAVED",
        .feed: "FEEDS & CALENDARS",
        .messaging: "MESSAGING",
        .import: "FILES & IMPORTS",
        .unknown: "OTHER",
    ]

    static func group(_ rows: [SourceOverview]) -> [(kind: SourceKind, title: String, rows: [SourceOverview])] {
        let ordered = SourceOverview.gridOrder(rows)
        return SourceKind.order.compactMap { kind in
            let inKind = ordered.filter { $0.kind == kind }
            guard !inKind.isEmpty else { return nil }
            return (kind: kind, title: titles[kind] ?? kind.rawValue.uppercased(), rows: inKind)
        }
    }
}
```

- [ ] **Step 4: The grouped grid + real marks** — replace the full contents of
  `Views/Sources/SourceCardGrid.swift`:

```swift
import SwiftUI

/// The grid of source cards (G124 — "in a grid, no horizontal scroll"),
/// grouped into sections by kind (Track D) so seventeen-odd sources read as
/// a handful of short, labelled groups instead of one long shuffled list.
/// Never-loaded → loading; loaded-but-empty → the one call to action (R2: a
/// row is shown only when it has evidence, and the Feed's `+` catalog is
/// where a person adds a source); otherwise one section per non-empty kind.
struct SourceCardGrid: View {
    let rows: [SourceOverview]
    let hasLoaded: Bool
    let isRefreshing: Bool
    let onOpen: (SourceOverview) -> Void

    private let columns = [GridItem(.adaptive(minimum: 220, maximum: 320), spacing: CicadaTheme.spacingMD)]

    var body: some View {
        Group {
            if !hasLoaded {
                HStack(spacing: CicadaTheme.spacingSM) {
                    ProgressView().controlSize(.small)
                    Text("Reading your sources…").font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textTertiary)
                }
                .frame(maxWidth: .infinity, alignment: .center)
            } else if rows.isEmpty {
                Text("Nothing has fed this memory yet. Add a source from the Feed's + button.")
                    .font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textTertiary)
            } else {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                    ForEach(SourceSections.group(rows), id: \.kind) { section in
                        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                            Text(section.title)
                                .font(.system(size: 10, weight: .semibold, design: .monospaced))
                                .foregroundStyle(CicadaTheme.textTertiary)
                                .tracking(1.2)
                            LazyVGrid(columns: columns, alignment: .leading, spacing: CicadaTheme.spacingMD) {
                                ForEach(section.rows) { row in
                                    Button { onOpen(row) } label: { SourceCard(source: row) }
                                        .buttonStyle(.cicadaPlain)
                                        .accessibilityLabel("\(row.label), \(row.countLines.joined(separator: ", "))")
                                }
                            }
                        }
                    }
                }
            }
        }
        .padding(.horizontal, CicadaTheme.spacingXL)
    }
}

/// One card: mark, label, the counts that apply, last activity, state. The
/// mark reuses `OriginMark` (Track D) — the same bundled-logo → drawn-glyph →
/// SF-Symbol precedence the Sleep queue and the import catalog already draw,
/// so a source's card, its queue row and its catalog tile show the identical
/// mark instead of the card alone falling back to a bare SF Symbol.
struct SourceCard: View {
    let source: SourceOverview

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack(spacing: CicadaTheme.spacingSM) {
                OriginMark(origin: source.mark, size: 20)
                    .frame(width: 24, height: 24)
                    .background(OriginIconography.color(for: source.mark).opacity(0.12))
                    .clipShape(RoundedRectangle(cornerRadius: 6))
                Text(source.label).font(CicadaTheme.headingFont).foregroundStyle(CicadaTheme.textPrimary).lineLimit(1)
                Spacer()
                Circle().fill(source.connected ? CicadaTheme.success : CicadaTheme.textTertiary.opacity(0.4))
                    .frame(width: 7, height: 7)
                    .help(source.connected ? "Connected" : "Not connected")
            }
            ForEach(source.countLines, id: \.self) { line in
                Text(line).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
            }
            if let relative = relativeLastActivity {
                Text("Last \(relative)").font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
            }
            if let error = source.lastError, !error.isEmpty {
                Text("Needs attention").font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.danger).help(error)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(CicadaTheme.spacingMD)
        .glassCard()
        .contentShape(Rectangle())
    }

    private var relativeLastActivity: String? {
        guard let date = source.lastActivityDate else { return nil }
        let fmt = RelativeDateTimeFormatter(); fmt.unitsStyle = .abbreviated
        return fmt.localizedString(for: date, relativeTo: .now)
    }
}
```

(This step changes only the icon in the card's leading tile — `Image(systemName:
OriginIconography.symbol(for:))` → `OriginMark(origin:size:)` in the same 24pt tinted tile — and
wraps the existing flat `LazyVGrid` in `SourceSections.group(rows)`. Everything else is
byte-identical to the version on `dev`.)

- [ ] **Step 5: Run the tests until green**

```
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/sources/app/CicadaApp && swift build 2>&1 | tail -5 && swift test 2>&1 | tail -20
```
Expected: build succeeds, 0 failures.

- [ ] **Step 6: Commit**

```
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/sources && git add -- app/CicadaApp/Sources/CicadaApp/Models/SourceOverview.swift app/CicadaApp/Sources/CicadaApp/Views/Sources/SourceCardGrid.swift app/CicadaApp/Tests/CicadaAppTests/SourcesPageTests.swift && git commit -q -m "feat(app): Sources grid groups by kind and draws real marks (G124 Track D)

SourceSections.group orders rows the way the backend's KIND_ORDER already
does, skipping any kind with no evidence (R2 extended to sections); each
card's tile draws OriginMark instead of a bare SF Symbol, matching the Sleep
queue and the import catalog.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RHX6oujZ79siqkHAqkP7CC"
```

---

### Task 2: Status light + hover quick action on the card

**Files:**
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Sources/ChannelActions.swift`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sources/ChannelSourceView.swift` (:65-70, delete
  :106-116)
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sources/SourceCardGrid.swift` (full rewrite again)
- Test: `app/CicadaApp/Tests/CicadaAppTests/SourcesPageTests.swift` (append)

**Interfaces:**
- `ChannelActions.sync(_ channelId: String, store: Store) async throws -> String`
- `ChannelActions.poll(_ channelId: String) async throws -> String`
- `SourceCard.quickAction(for: SourceOverview) -> String?` (pure)
- `SourceCard.accessibilityLabel(for: SourceOverview, watchState: BrowserWatchState?) -> String` (pure)

- [ ] **Step 1: Write the failing tests** — append to `SourcesPageTests.swift`, immediately
  before the `final class SourcesPageTests: XCTestCase { ... }` body's closing `}` (every method
  below, including any private helper, is a member of that class — not top-level code):

```swift
    // MARK: - Track D: status light + quick action

    func testQuickActionPrefersSyncOverPollAndIsNilOtherwise() {
        XCTAssertEqual(SourceCard.quickAction(for: SourceOverview(id: "safari-bookmarks", label: "Safari", kind: .browser, actions: ["sync"])), "Sync now")
        XCTAssertEqual(SourceCard.quickAction(for: SourceOverview(id: "rss", label: "RSS", kind: .feed, actions: ["poll", "manage"])), "Poll now")
        XCTAssertNil(SourceCard.quickAction(for: SourceOverview(id: "x", label: "X", kind: .social, actions: ["connect"])))
        XCTAssertNil(SourceCard.quickAction(for: SourceOverview(id: "harness:claude-code", label: "Claude Code", kind: .harness)),
                     "a harness row has no channel actions at all")
    }

    func testCardAccessibilityLabelAppendsTheStateTitleOnlyWhenALightIsShown() {
        let row = SourceOverview(id: "safari-bookmarks", label: "Safari bookmarks", kind: .browser, items: 3)
        XCTAssertEqual(SourceCard.accessibilityLabel(for: row, watchState: nil), "Safari bookmarks, 3 items")
        XCTAssertEqual(SourceCard.accessibilityLabel(for: row, watchState: .watching), "Safari bookmarks, 3 items, Watching")
        XCTAssertEqual(SourceCard.accessibilityLabel(for: row, watchState: .blocked), "Safari bookmarks, 3 items, Can't read")
    }
```

- [ ] **Step 2: Run the tests to confirm they fail**

```
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/sources/app/CicadaApp && swift build 2>&1 | tail -20
```
Expected: compile error — `SourceCard.quickAction`/`accessibilityLabel` don't exist yet.

- [ ] **Step 3: `ChannelActions`** — create `Views/Sources/ChannelActions.swift`:

```swift
import Foundation

/// The two actions a channel source's card and its full page can both run
/// (Track D — "the card and the page share one implementation", so tapping
/// Sync now from the grid and from `ChannelSourceView` do the identical
/// thing). `sync` delegates to `BrowserImportActions.syncChannel` — the
/// existing browser-file read-and-post path stays exactly where it is (the
/// app reads `~/Library`, the launchd backend never does; R-D4). `poll` is
/// `ChannelSourceView`'s former private `pollNow`, moved here byte-for-byte:
/// its gate message is what a user-initiated poll shows when
/// `CICADA_ALLOW_FEED_FETCH` is off, and the card's toast and the page's
/// feedback line must read identically.
@MainActor
enum ChannelActions {
    static func sync(_ channelId: String, store: Store) async throws -> String {
        try await BrowserImportActions.syncChannel(channelId, store: store)
    }

    /// A user-initiated poll still honours the backend's fetch gate: the
    /// result says so plainly instead of reporting "0 new" as if it had run.
    static func poll(_ channelId: String) async throws -> String {
        let disabled = "Live fetch is disabled on this backend — set CICADA_ALLOW_FEED_FETCH=1 and restart."
        if channelId == "calendar" {
            let r = try await APIClient.shared.pollCalendars()
            return r.skippedNoNetwork > 0 ? disabled : "\(r.new) new event(s)"
        }
        let r = try await APIClient.shared.pollFeeds()
        return r.skippedNoNetwork > 0 ? disabled : "\(r.new) new item(s)"
    }
}
```

- [ ] **Step 4: `ChannelSourceView` calls the shared actions** — in `ChannelSourceView.swift`,
  replace the two action lines at :65-70:

```swift
                if channel.actions.contains("sync") {
                    actionButton("Sync now") { try await ChannelActions.sync(channel.id, store: store) }
                }
                if channel.actions.contains("poll") {
                    actionButton("Poll now") { try await ChannelActions.poll(channel.id) }
                }
```

and delete the now-unused private `pollNow(_:)` method (the block at :106-116, from `/// A
user-initiated poll…` through its closing brace).

- [ ] **Step 5: The card's status light + hover quick action** — replace the full contents of
  `Views/Sources/SourceCardGrid.swift` again:

```swift
import SwiftUI

/// The grid of source cards (G124 — "in a grid, no horizontal scroll"),
/// grouped into sections by kind (Track D) so seventeen-odd sources read as
/// a handful of short, labelled groups instead of one long shuffled list.
/// Never-loaded → loading; loaded-but-empty → the one call to action (R2: a
/// row is shown only when it has evidence, and the Feed's `+` catalog is
/// where a person adds a source); otherwise one section per non-empty kind.
struct SourceCardGrid: View {
    let rows: [SourceOverview]
    let hasLoaded: Bool
    let isRefreshing: Bool
    let onOpen: (SourceOverview) -> Void

    private let columns = [GridItem(.adaptive(minimum: 220, maximum: 320), spacing: CicadaTheme.spacingMD)]

    var body: some View {
        Group {
            if !hasLoaded {
                HStack(spacing: CicadaTheme.spacingSM) {
                    ProgressView().controlSize(.small)
                    Text("Reading your sources…").font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textTertiary)
                }
                .frame(maxWidth: .infinity, alignment: .center)
            } else if rows.isEmpty {
                Text("Nothing has fed this memory yet. Add a source from the Feed's + button.")
                    .font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textTertiary)
            } else {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                    ForEach(SourceSections.group(rows), id: \.kind) { section in
                        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                            Text(section.title)
                                .font(.system(size: 10, weight: .semibold, design: .monospaced))
                                .foregroundStyle(CicadaTheme.textTertiary)
                                .tracking(1.2)
                            LazyVGrid(columns: columns, alignment: .leading, spacing: CicadaTheme.spacingMD) {
                                ForEach(section.rows) { row in
                                    SourceCardTile(source: row, onOpen: { onOpen(row) })
                                }
                            }
                        }
                    }
                }
            }
        }
        .padding(.horizontal, CicadaTheme.spacingXL)
    }
}

/// One card plus its hover-revealed quick action, as sibling views in a
/// `ZStack` rather than a button nested inside a button (R-D2: the two hit
/// test independently, so tapping the small action can never also open the
/// page). Owns its own `hovering`/`busy` state — one instance per row, so a
/// spinner on one card never bleeds into its neighbours.
private struct SourceCardTile: View {
    let source: SourceOverview
    let onOpen: () -> Void

    @Environment(Store.self) private var store
    @Environment(BrowserWatcher.self) private var watcher
    @State private var hovering = false
    @State private var busy = false

    private var watchState: BrowserWatchState? {
        source.channelId.flatMap { watcher.state(for: $0) }
    }
    private var watchError: BrowserFileError? {
        source.channelId.flatMap { watcher.error(for: $0) }
    }

    var body: some View {
        ZStack(alignment: .topTrailing) {
            Button(action: onOpen) {
                SourceCard(source: source, watchState: watchState, watchError: watchError)
            }
            .buttonStyle(.cicadaPlain)
            .accessibilityLabel(SourceCard.accessibilityLabel(for: source, watchState: watchState))

            if hovering, let action = SourceCard.quickAction(for: source) {
                quickActionButton(action)
                    .padding(CicadaTheme.spacingSM)
            }
        }
        .onHover { hovering = $0 }
    }

    private func quickActionButton(_ title: String) -> some View {
        Button(title) {
            guard let channelId = source.channelId else { return }
            Task {
                busy = true
                // R-D5: best-effort. The card has no room for an error line;
                // the identical action's failure (and `lastError`) is one
                // click away on the detail page.
                _ = try? await (title == "Poll now" ? ChannelActions.poll(channelId)
                                                     : ChannelActions.sync(channelId, store: store))
                busy = false
                await store.refresh([.channels, .sources, .sourcesOverview, .status])
            }
        }
        .buttonStyle(.bordered).controlSize(.mini).disabled(busy)
        .accessibilityLabel(title)
    }
}

/// One card: mark, label, the counts that apply, last activity, state. The
/// mark reuses `OriginMark` (Track D) — the same bundled-logo → drawn-glyph →
/// SF-Symbol precedence the Sleep queue and the import catalog already draw.
/// `watchState`/`watchError` are passed in rather than read from the
/// environment here, so the card stays a plain, previewable value view —
/// `SourceCardTile` is the one place that talks to `BrowserWatcher`.
struct SourceCard: View {
    let source: SourceOverview
    var watchState: BrowserWatchState? = nil
    var watchError: BrowserFileError? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack(spacing: CicadaTheme.spacingSM) {
                OriginMark(origin: source.mark, size: 20)
                    .frame(width: 24, height: 24)
                    .background(OriginIconography.color(for: source.mark).opacity(0.12))
                    .clipShape(RoundedRectangle(cornerRadius: 6))
                Text(source.label).font(CicadaTheme.headingFont).foregroundStyle(CicadaTheme.textPrimary).lineLimit(1)
                Spacer()
                // G129's status light where a watch exists; the plain dot
                // everywhere else — unchanged from before G129 (R-D6: the
                // light is reused exactly as it renders on ChannelSourceView,
                // .blocked's FullDiskAccessHint included).
                if let watchState {
                    BrowserStatusLight(state: watchState, error: watchError, compact: true)
                } else {
                    Circle().fill(source.connected ? CicadaTheme.success : CicadaTheme.textTertiary.opacity(0.4))
                        .frame(width: 7, height: 7)
                        .help(source.connected ? "Connected" : "Not connected")
                }
            }
            ForEach(source.countLines, id: \.self) { line in
                Text(line).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
            }
            if let relative = relativeLastActivity {
                Text("Last \(relative)").font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
            }
            if let error = source.lastError, !error.isEmpty {
                Text("Needs attention").font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.danger).help(error)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(CicadaTheme.spacingMD)
        .glassCard()
        .contentShape(Rectangle())
    }

    private var relativeLastActivity: String? {
        guard let date = source.lastActivityDate else { return nil }
        let fmt = RelativeDateTimeFormatter(); fmt.unitsStyle = .abbreviated
        return fmt.localizedString(for: date, relativeTo: .now)
    }

    /// Which quick action, if any, a hover reveals — sync wins when a row
    /// somehow advertises both (R-D3: no catalog row does today).
    static func quickAction(for source: SourceOverview) -> String? {
        if source.actions.contains("sync") { return "Sync now" }
        if source.actions.contains("poll") { return "Poll now" }
        return nil
    }

    /// The card's accessibility label, with the status light's own title
    /// appended when one is shown — the rail is "keep the accessibility
    /// label and GAIN the state title", not replace one with the other.
    static func accessibilityLabel(for source: SourceOverview, watchState: BrowserWatchState?) -> String {
        var label = "\(source.label), \(source.countLines.joined(separator: ", "))"
        if let watchState { label += ", \(BrowserStatusLight.title(for: watchState))" }
        return label
    }
}
```

- [ ] **Step 6: Run the tests until green**

```
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/sources/app/CicadaApp && swift build 2>&1 | tail -5 && swift test 2>&1 | tail -20
```
Expected: build succeeds, 0 failures.

- [ ] **Step 7: Commit**

```
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/sources && git add -- app/CicadaApp/Sources/CicadaApp/Views/Sources/ChannelActions.swift app/CicadaApp/Sources/CicadaApp/Views/Sources/ChannelSourceView.swift app/CicadaApp/Sources/CicadaApp/Views/Sources/SourceCardGrid.swift app/CicadaApp/Tests/CicadaAppTests/SourcesPageTests.swift && git commit -q -m "feat(app): status light + hover quick action on the source card (G124 Track D)

A watched channel's card now shows the same BrowserStatusLight its own page
does (compact), instead of a dot that only ever says connected/not; a hover
reveals Sync now / Poll now as a sibling of the open-page button (R-D2, never
nested in it) via ChannelActions — the same implementation ChannelSourceView
now calls too, so the two surfaces can never disagree about what 'Sync now'
does.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RHX6oujZ79siqkHAqkP7CC"
```

---

### Task 3: The per-source page header — mark + "what Cicada reads from this"

**Files:**
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Common/PageHeader.swift` (full file, 33 lines)
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Sources/SourceBlurb.swift`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sources/SourceDetailView.swift` (full file, 31
  lines)
- Test: `app/CicadaApp/Tests/CicadaAppTests/SourcesPageTests.swift` (append)

**Interfaces:**
- `PageHeader<Trailing>.leading: AnyView?` (new, default `nil`)
- `SourceBlurb.text(for: SourceOverview) -> String` (pure)

- [ ] **Step 1: Write the failing tests** — append to `SourcesPageTests.swift`, immediately
  before the `final class SourcesPageTests: XCTestCase { ... }` body's closing `}` (every method
  below, including any private helper, is a member of that class — not top-level code):

```swift
    // MARK: - Track D: per-source blurb

    func testSourceBlurbCoversEveryCatalogIdWithAShortSentence() {
        // Every id api/services/source_overview.CATALOG declares today.
        let catalogIds = [
            "chat-export:claude", "chat-export:chatgpt", "chat-export:gemini",
            "chrome-bookmarks", "safari-bookmarks", "safari-tabs",
            "pinterest", "reddit", "x", "instagram", "youtube", "linkedin", "tiktok",
            "rss", "calendar", "telegram", "notes", "files",
        ]
        for id in catalogIds {
            let row = SourceOverview(id: id, label: id, kind: .harness)  // kind is irrelevant once the id matches
            let text = SourceBlurb.text(for: row)
            XCTAssertFalse(text.isEmpty, "\(id) has no blurb")
            XCTAssertLessThanOrEqual(text.count, 110, "\(id)'s blurb is too long for a subtitle line: \(text)")
            XCTAssertFalse(text.contains("$"), "no prices in the app (G124 ruling)")
        }
    }

    func testSourceBlurbFallsBackToTheKindSentenceForAnUnrecognizedId() {
        let mystery = SourceOverview(id: "origin:mystery-app", label: "mystery-app", kind: .import)
        XCTAssertEqual(SourceBlurb.text(for: mystery), "Links or files you added through mystery-app.")
        let cursor = SourceOverview(id: "harness:cursor", label: "Cursor", kind: .harness)
        XCTAssertEqual(SourceBlurb.text(for: cursor), "Conversations captured from Cursor, one episode per session.")
    }
```

- [ ] **Step 2: Run the tests to confirm they fail**

```
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/sources/app/CicadaApp && swift build 2>&1 | tail -20
```
Expected: compile error — `SourceBlurb` doesn't exist yet.

- [ ] **Step 3: `PageHeader` gains an optional leading slot** — replace the full contents of
  `Views/Common/PageHeader.swift`:

```swift
import SwiftUI

/// Shared page header (Linear/Notion convention): a title, an optional one-line
/// subtitle, and an optional right-aligned trailing action. Promotes the
/// ad-hoc header that SleepView established into one reusable component so every
/// primary screen (Graph, Clusters, Feed, Sleep, Inbox, Contributors) lays out
/// identically: `spacingXL` outer padding, `titleFont` title in `textPrimary`,
/// `bodyFont` subtitle in `textSecondary`.
struct PageHeader<Trailing: View>: View {
    let title: String
    var subtitle: String? = nil
    /// An optional leading slot before the title (Track D: the per-source
    /// page's origin mark). `nil` by default so every other page's header
    /// renders byte-identical to before this existed — `AnyView?` rather than
    /// a second generic parameter keeps every existing call site, including
    /// the `Trailing == EmptyView` convenience init below, source compatible
    /// with no changes, and `nil` (not an empty view) means the HStack below
    /// never inserts a spacing gap in front of a title that has no mark.
    var leading: AnyView? = nil
    @ViewBuilder var trailing: () -> Trailing

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingMD) {
            if let leading { leading }
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                Text(title)
                    .font(CicadaTheme.titleFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                if let subtitle {
                    Text(subtitle)
                        .font(CicadaTheme.bodyFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .lineLimit(1)
                }
            }
            Spacer(minLength: CicadaTheme.spacingMD)
            trailing()
        }
        .padding(.horizontal, CicadaTheme.spacingXL)
        .padding(.top, CicadaTheme.spacingXL)
        .padding(.bottom, CicadaTheme.spacingLG)
    }
}

extension PageHeader where Trailing == EmptyView {
    init(title: String, subtitle: String? = nil) {
        self.title = title
        self.subtitle = subtitle
        self.trailing = { EmptyView() }
    }
}
```

- [ ] **Step 4: `SourceBlurb`** — create `Views/Sources/SourceBlurb.swift`:

```swift
import Foundation

/// One honest sentence of what Cicada reads from a source — no price, no
/// token count (the 2026-09-03 ruling), just what shows up in memory when
/// this source is connected. Keyed by `source.id` for the eighteen rows
/// `api/services/source_overview.CATALOG` declares today; a harness or
/// origin the catalog has never heard of (the `harness:<name>` and
/// `origin:<id>` open families, G124 R1) falls back to one sentence per
/// kind, built from the row's own label so it still reads as a specific
/// sentence rather than a generic placeholder.
enum SourceBlurb {
    static func text(for source: SourceOverview) -> String {
        byId[source.id] ?? fallback(kind: source.kind, label: source.label)
    }

    private static func fallback(kind: SourceKind, label: String) -> String {
        switch kind {
        case .harness:
            return "Conversations captured from \(label), one episode per session."
        case .browser:
            return "Bookmarks and tabs from \(label), synced as you browse."
        case .social:
            return "Items you saved on \(label), as links with their titles and boards."
        case .feed:
            return "New items from \(label), the feeds and calendars you subscribed to."
        case .messaging:
            return "Messages you send to \(label), as notes."
        case .import, .unknown:
            return "Links or files you added through \(label)."
        }
    }

    // Every id below is one `source_overview.CATALOG` declares (verified
    // against api/services/source_overview.py at plan time). A gap here
    // would silently fall through to the kind fallback above rather than
    // fail loud — SourcesPageTests asserts every catalog id by name so a
    // future catalog addition without a matching blurb still passes here
    // (the kind fallback is a legitimate answer), but never regresses one
    // that already had a specific sentence.
    private static let byId: [String: String] = [
        "chat-export:claude": "Claude conversations you exported and imported, one episode per thread.",
        "chat-export:chatgpt": "ChatGPT conversations you exported and imported, one episode per thread.",
        "chat-export:gemini": "Gemini conversations you exported from Takeout, one episode per thread.",
        "chrome-bookmarks": "Bookmarks you save in Chrome, synced as you add them.",
        "safari-bookmarks": "Bookmarks you save in Safari, synced as you add them.",
        "safari-tabs": "Your open Safari tabs across devices, via iCloud.",
        "pinterest": "Pins you save on Pinterest, as links with their boards.",
        "reddit": "Posts and comments you save on Reddit, as links with their titles.",
        "x": "Posts you bookmark on X, as links with their text.",
        "instagram": "Posts you save on Instagram, as links with their captions.",
        "youtube": "Videos in the YouTube playlists you follow.",
        "linkedin": "Posts you save on LinkedIn, as links with their titles.",
        "tiktok": "Videos you save on TikTok, as links with their captions.",
        "rss": "New posts from the feeds you subscribed to.",
        "calendar": "Events from the calendars you subscribed to.",
        "telegram": "Messages you send the bot, as notes.",
        "notes": "Notes you write in Apple Notes.",
        "files": "Links you pasted or files you dropped.",
    ]
}
```

- [ ] **Step 5: `SourceDetailView`'s header** — replace the full contents of
  `Views/Sources/SourceDetailView.swift`:

```swift
import SwiftUI

/// One source's page (G124). A harness shows its conversations; every other
/// kind shows its channel state, folder counts and items. Back is a chevron
/// and ⌘[ (R15) — the same key the entity card uses on the Graph tab, which
/// is never mounted at the same time as this view.
///
/// The header (Track D) leads with the source's own mark and one honest
/// sentence of what Cicada reads from it (`SourceBlurb`) instead of the raw
/// count line — the counts move to the queue strip's "consolidated so far"
/// line (added in the next task).
struct SourceDetailView: View {
    let source: SourceOverview
    let onBack: () -> Void
    var onSelectEntity: ((String) -> Void)?

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            PageHeader(title: source.label, subtitle: SourceBlurb.text(for: source),
                       leading: AnyView(OriginMark(origin: source.mark, size: 28))) {
                Button(action: onBack) {
                    Label("Sources", systemImage: "chevron.left").labelStyle(.titleAndIcon)
                }
                .buttonStyle(.cicadaGlass(cornerRadius: CicadaTheme.cornerRadiusSmall))
                .keyboardShortcut("[", modifiers: .command)
                .help("Back to all sources (⌘[)")
                .accessibilityLabel("Back to all sources")
            }
            switch source.kind {
            case .harness:
                HarnessConversationsView(source: source, onSelectEntity: onSelectEntity)
            default:
                ChannelSourceView(source: source)
            }
        }
    }
}
```

- [ ] **Step 6: Run the tests until green**

```
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/sources/app/CicadaApp && swift build 2>&1 | tail -5 && swift test 2>&1 | tail -20
```
Expected: build succeeds, 0 failures.

- [ ] **Step 7: Commit**

```
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/sources && git add -- app/CicadaApp/Sources/CicadaApp/Views/Common/PageHeader.swift app/CicadaApp/Sources/CicadaApp/Views/Sources/SourceBlurb.swift app/CicadaApp/Sources/CicadaApp/Views/Sources/SourceDetailView.swift app/CicadaApp/Tests/CicadaAppTests/SourcesPageTests.swift && git commit -q -m "feat(app): per-source page opens with its mark + what Cicada reads from it (G124 Track D)

PageHeader gains an optional, default-nil leading slot (R-D1 — every other
page's header is unaffected) so the per-source page can lead with OriginMark;
under the title, SourceBlurb.text replaces the raw count-line subtitle with
one honest sentence of what this source feeds into memory, keyed to every id
api/services/source_overview.CATALOG declares, with a per-kind fallback for
the two open harness:/origin: families.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RHX6oujZ79siqkHAqkP7CC"
```

---

### Task 4: The queue strip — "N waiting for Sleep" + consolidated so far

**Files:**
- Modify: `app/CicadaApp/Sources/CicadaApp/Models/SourceOverview.swift` (append `ownedQueue`
  inside the `SourceOverview` struct, near `ownedItems`)
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Sources/SourceQueueStrip.swift`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sources/SourceDetailView.swift` (full file again)
- Test: `app/CicadaApp/Tests/CicadaAppTests/SourcesPageTests.swift` (append)

**Interfaces:**
- `SourceOverview.ownedQueue(from: [EpisodeQueueItem]) -> [EpisodeQueueItem]` (pure)
- `SourceQueueLabels.waiting(_ count: Int) -> String` (pure)
- `SourceQueueLabels.consolidatedSoFar(for: SourceOverview) -> String?` (pure)

- [ ] **Step 1: Write the failing tests** — append to `SourcesPageTests.swift`, immediately
  before the `final class SourcesPageTests: XCTestCase { ... }` body's closing `}` (every method
  below, including any private helper, is a member of that class — not top-level code):

```swift
    // MARK: - Track D: the queue strip

    private func queueItem(_ id: String, origin: String) throws -> EpisodeQueueItem {
        try JSONDecoder().decode(EpisodeQueueItem.self, from:
            #"{"id":"\#(id)","timestamp":"2026-09-01T00:00:00Z","source":"x","origin":"\#(origin)","preview":"","processed":false}"#.data(using: .utf8)!)
    }

    func testOwnedQueueMatchesAHarnessByIdPlusTheLegacyMcpAliasForClaudeCodeOnly() throws {
        let all = [try queueItem("1", origin: "claude-code"), try queueItem("2", origin: "mcp"),
                   try queueItem("3", origin: "cursor"), try queueItem("4", origin: "safari-bookmark")]
        let claudeCode = SourceOverview(id: "harness:claude-code", label: "Claude Code", kind: .harness, harness: "claude-code")
        XCTAssertEqual(claudeCode.ownedQueue(from: all).map(\.id), ["1", "2"], "the legacy mcp id belongs to claude-code only")
        let cursor = SourceOverview(id: "harness:cursor", label: "Cursor", kind: .harness, harness: "cursor")
        XCTAssertEqual(cursor.ownedQueue(from: all).map(\.id), ["3"], "cursor never adopts a bare mcp episode")
    }

    func testOwnedQueueMatchesACatalogRowByItsExactOriginsOnlyWithNoUnstampedFallback() throws {
        let all = [try queueItem("1", origin: "safari-bookmark"), try queueItem("2", origin: "saved-link"),
                   try queueItem("3", origin: "unknown")]
        let safari = SourceOverview(id: "safari-bookmarks", label: "Safari bookmarks", kind: .browser, origins: ["safari-bookmark"])
        XCTAssertEqual(safari.ownedQueue(from: all).map(\.id), ["1"])
        let files = SourceOverview(id: "files", label: "Files & links", kind: .import, origins: ["saved-link"])
        XCTAssertEqual(files.ownedQueue(from: all).map(\.id), ["2"],
                        "R-D8: exact origins only — files does NOT also adopt \"unknown\", unlike ownedItems' nil-origin rule")
    }

    func testSourceQueueLabelsWaitingAndConsolidatedSoFar() {
        XCTAssertEqual(SourceQueueLabels.waiting(0), "Nothing waiting for Sleep")
        XCTAssertEqual(SourceQueueLabels.waiting(12), "12 waiting for Sleep")

        let harness = SourceOverview(id: "harness:claude-code", label: "Claude Code", kind: .harness, conversations: 3, entities: 5)
        XCTAssertEqual(SourceQueueLabels.consolidatedSoFar(for: harness), "Consolidated so far: 3 conversations → 5 entities")

        let one = SourceOverview(id: "harness:cursor", label: "Cursor", kind: .harness, conversations: 1, entities: 1)
        XCTAssertEqual(SourceQueueLabels.consolidatedSoFar(for: one), "Consolidated so far: 1 conversation → 1 entity")

        let channel = SourceOverview(id: "safari-bookmarks", label: "Safari", kind: .browser, episodes: 40, entities: 12)
        XCTAssertEqual(SourceQueueLabels.consolidatedSoFar(for: channel), "Consolidated so far: 40 captures → 12 entities")

        let empty = SourceOverview(id: "rss", label: "RSS", kind: .feed)
        XCTAssertNil(SourceQueueLabels.consolidatedSoFar(for: empty), "hidden when both counts are 0")
    }
```

- [ ] **Step 2: Run the tests to confirm they fail**

```
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/sources/app/CicadaApp && swift build 2>&1 | tail -20
```
Expected: compile error — `ownedQueue`/`SourceQueueLabels` don't exist yet.

- [ ] **Step 3: `ownedQueue`** — inside the `SourceOverview` struct in `Models/SourceOverview.swift`,
  add this method directly after `ownedItems(from:)` (:50-58):

```swift

    /// Which queued episodes belong to this source, for the per-source
    /// page's queue strip (Track D). A harness owns items stamped with its
    /// own harness id, plus the legacy `mcp` origin when this row IS
    /// `claude-code` — every MCP-tool-initiated episode (as opposed to a
    /// hook-captured one) carries `origin: mcp` regardless of harness
    /// (`mcp/server.py`), and `claude-code` is the one harness old enough to
    /// have episodes from before the hook stamped `origin: <harness>`
    /// directly (`OriginIconography.label`'s own comment). Every other row
    /// owns items whose origin is one of its own `origins` — EXACT, with no
    /// legacy-unstamped fallback (R-D8): unlike `ownedItems`, which also
    /// adopts a nil-origin media page for `files`, `EpisodeQueueItem.origin`
    /// defaults to the literal `"unknown"` on an older backend, and an
    /// unknown queued episode is not evidence for any one source.
    func ownedQueue(from all: [EpisodeQueueItem]) -> [EpisodeQueueItem] {
        if let harness {
            return all.filter { $0.origin == harness || (harness == "claude-code" && $0.origin == "mcp") }
        }
        let mine = Set(origins)
        return all.filter { mine.contains($0.origin) }
    }
```

- [ ] **Step 4: `SourceQueueStrip`** — create `Views/Sources/SourceQueueStrip.swift`:

```swift
import SwiftUI

/// Pure labels for the per-source queue strip (Track D), tested without a
/// view: "N waiting for Sleep", and the "consolidated so far" line, which
/// counts conversations for a harness and captures for everything else —
/// the same distinction `SourceOverview.countLines` already draws.
enum SourceQueueLabels {
    static func waiting(_ count: Int) -> String {
        count == 0 ? "Nothing waiting for Sleep" : "\(count) waiting for Sleep"
    }

    /// `nil` when there's nothing to report yet ("hidden when both are 0") —
    /// a fresh source with an empty queue and no history shouldn't print
    /// "0 captures → 0 entities".
    static func consolidatedSoFar(for source: SourceOverview) -> String? {
        let (n, unit): (Int, String) = source.kind == .harness
            ? (source.conversations, "conversation")
            : (source.episodes, "capture")
        guard n > 0 || source.entities > 0 else { return nil }
        let left = "\(n) \(unit)\(n == 1 ? "" : "s")"
        let right = "\(source.entities) \(source.entities == 1 ? "entity" : "entities")"
        return "Consolidated so far: \(left) → \(right)"
    }
}

/// "N waiting for Sleep" + Consolidate now, and what has already been folded
/// in — the per-source page's queue strip (Track D). A pure projection over
/// `SleepViewModel.queuedEpisodes` (filtered to this source by
/// `SourceOverview.ownedQueue`) and the overview row's own counts; starts no
/// fetches of its own — `SourceDetailView` calls `sleepVM.load()` once so
/// `queuedEpisodes` is populated even when a person opens Sources without
/// ever visiting Sleep first this session.
struct SourceQueueStrip: View {
    let source: SourceOverview

    @Environment(SleepViewModel.self) private var sleepVM
    @Environment(Store.self) private var store

    private var owned: [EpisodeQueueItem] { source.ownedQueue(from: sleepVM.queuedEpisodes) }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            HStack(spacing: CicadaTheme.spacingMD) {
                Text(SourceQueueLabels.waiting(owned.count))
                    .font(CicadaTheme.headingFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                Spacer()
                consolidateButton
            }
            if let line = SourceQueueLabels.consolidatedSoFar(for: source) {
                Text(line)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
        }
        .padding(CicadaTheme.spacingMD)
        .glassCard()
        .padding(.horizontal, CicadaTheme.spacingXL)
        .padding(.top, CicadaTheme.spacingSM)
    }

    /// The same capsule the Sleep page's queue card uses — moon icon, accent
    /// when there's something to do, grey and disabled when idle and empty.
    /// Duplicated rather than imported (R-D7): `SleepQueueCard` is Track A's
    /// file, being rebuilt into the study desk on a parallel worktree right
    /// now, and sharing a symbol across two in-flight branches over a file
    /// neither otherwise touches is exactly the merge collision
    /// `working-method.md` keeps tracks apart to avoid.
    private var consolidateButton: some View {
        Button {
            Task {
                await sleepVM.triggerManually()
                await store.refresh([.status, .channels, .sourcesOverview])
            }
        } label: {
            HStack(spacing: CicadaTheme.spacingXS) {
                if sleepVM.isRunning {
                    ProgressView().controlSize(.small).frame(width: 12, height: 12)
                } else {
                    Image(systemName: "moon.fill").font(.system(size: 12))
                }
                Text(sleepVM.isRunning ? Copy.consolidating : Copy.consolidateNow)
                    .font(.system(size: 12, weight: .semibold))
            }
            .foregroundStyle(owned.isEmpty && !sleepVM.isRunning ? CicadaTheme.textTertiary : .white)
            .padding(.horizontal, CicadaTheme.spacingLG)
            .padding(.vertical, CicadaTheme.spacingSM)
            .background(owned.isEmpty && !sleepVM.isRunning ? CicadaTheme.surfaceElevated : CicadaTheme.accent.opacity(0.9))
            .clipShape(Capsule())
        }
        .buttonStyle(.cicadaPlain)
        .disabled(sleepVM.isRunning || owned.isEmpty)
        .help(owned.isEmpty ? "Nothing queued right now" : "Run the Sleep cycle now")
        .accessibilityLabel(Copy.consolidateNow)
    }
}
```

- [ ] **Step 5: Wire it into `SourceDetailView`** — replace the full contents of
  `Views/Sources/SourceDetailView.swift`:

```swift
import SwiftUI

/// One source's page (G124). A harness shows its conversations; every other
/// kind shows its channel state, folder counts and items. Back is a chevron
/// and ⌘[ (R15) — the same key the entity card uses on the Graph tab, which
/// is never mounted at the same time as this view.
///
/// The header (Track D) leads with the source's own mark and one honest
/// sentence of what Cicada reads from it (`SourceBlurb`); the queue strip
/// right under it says what's waiting and what has already been folded in.
struct SourceDetailView: View {
    let source: SourceOverview
    let onBack: () -> Void
    var onSelectEntity: ((String) -> Void)?

    @Environment(SleepViewModel.self) private var sleepVM
    @State private var loadedOnce = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            PageHeader(title: source.label, subtitle: SourceBlurb.text(for: source),
                       leading: AnyView(OriginMark(origin: source.mark, size: 28))) {
                Button(action: onBack) {
                    Label("Sources", systemImage: "chevron.left").labelStyle(.titleAndIcon)
                }
                .buttonStyle(.cicadaGlass(cornerRadius: CicadaTheme.cornerRadiusSmall))
                .keyboardShortcut("[", modifiers: .command)
                .help("Back to all sources (⌘[)")
                .accessibilityLabel("Back to all sources")
            }
            SourceQueueStrip(source: source)
            switch source.kind {
            case .harness:
                HarnessConversationsView(source: source, onSelectEntity: onSelectEntity)
            default:
                ChannelSourceView(source: source)
            }
        }
        // sleepVM.queuedEpisodes must be populated for the strip above even
        // when Sources is opened without ever visiting Sleep first this
        // session — mirrors SleepView's own `loadedOnce` guard.
        .task {
            if !loadedOnce {
                loadedOnce = true
                await sleepVM.load()
            }
        }
    }
}
```

- [ ] **Step 6: Run the tests until green**

```
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/sources/app/CicadaApp && swift build 2>&1 | tail -5 && swift test 2>&1 | tail -20
```
Expected: build succeeds, 0 failures.

- [ ] **Step 7: Commit**

```
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/sources && git add -- app/CicadaApp/Sources/CicadaApp/Models/SourceOverview.swift app/CicadaApp/Sources/CicadaApp/Views/Sources/SourceQueueStrip.swift app/CicadaApp/Sources/CicadaApp/Views/Sources/SourceDetailView.swift app/CicadaApp/Tests/CicadaAppTests/SourcesPageTests.swift && git commit -q -m "feat(app): the per-source page shows its own queue + Consolidate now (G124 Track D)

SourceOverview.ownedQueue filters SleepViewModel.queuedEpisodes to this
source's episodes (harness id + the legacy mcp alias for claude-code only;
exact origins otherwise, no unstamped fallback — R-D8), rendered as a strip
under the header: 'N waiting for Sleep' + Consolidate now, and a
'Consolidated so far' line from the overview row's own counts. sleepVM.load()
is now called once from the detail page so the strip has data even when
Sleep was never opened this session.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RHX6oujZ79siqkHAqkP7CC"
```

---

### Task 5: Docs

**Files:**
- Modify: `docs/goals/memory-evolution.md` (the G124 row, its status column)
- Modify: `docs/goals/TODO.md` (the ✅ Shipped list's G124 entry)

- [ ] **Step 1: G124 row** — in `docs/goals/memory-evolution.md`, in the G124 row's status column,
  find the closing text `harness marks are OriginIconography glyphs — no brand assets.)` and
  extend it in place (same parenthetical, one more sentence before the closing `)`):

```
harness marks are OriginIconography glyphs — no brand assets. **Track D shipped (2026-09-05, PR
#TBD):** grouped-by-kind grid, G129 status lights + hover quick actions on the card, per-source
blurb sentences and a queue strip (Consolidate now + consolidated-so-far) on the per-source
page.)
```

- [ ] **Step 2: TODO.md Shipped entry** — in `docs/goals/TODO.md`, in the **Provenance** bullet
  under `## ✅ Shipped`, find `per-source pages with Resume, contributors calendar per model,
  Advanced counts; prices/tokens out of the app` and extend it:

```
per-source pages with Resume, contributors calendar per model, Advanced counts; prices/tokens out
of the app; **Track D (2026-09-05, PR #TBD)** — grouped-by-kind grid with real logos, G129 status
lights + hover quick actions, per-source blurbs, and a queue strip with Consolidate now
```

- [ ] **Step 3: Privacy check** — before committing, confirm neither edit names a person, a bank
  entity, or a URL from the live bank (the standing 2026-09-02 privacy rule):

```
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/sources && git diff -- docs/goals/memory-evolution.md docs/goals/TODO.md
```
Expected: both hunks are generic feature/architecture language only — no names, no bank content.

- [ ] **Step 4: Commit**

```
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/sources && git add -- docs/goals/memory-evolution.md docs/goals/TODO.md && git commit -q -m "docs: record the G124 Track D shipped shape

Grouped-by-kind grid, G129 status lights + hover quick actions on the card,
per-source blurbs and the queue strip — recorded on the G124 row and in
TODO.md's Shipped list.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RHX6oujZ79siqkHAqkP7CC"
```

---

## Not in scope

- **Any backend change.** No new endpoint, no new field, no ETag change — `api/models/schemas.py`
  and `api/routers/sleep.py` are never opened (a parallel track owns them for Track A).
- **G120's attention card** and **G113 slice 4's feedback tile** — both remain the named slots
  already on the G124 row / `AdvancedStatsView.feedbackTileSlot`; this plan does not touch
  `AdvancedStatsView.swift`.
- **New source adapters** — no new catalog entry, no new connector.
- **The Feed's `+` sheet** — unchanged; it stays the place to add a source (R2).
- **Contributors and Advanced sections of `SourcesPageView`** — unchanged.
- **`SleepQueueCard.swift` / `SleepDebtBreakdown.swift`** (Track A's files) — never opened; the
  queue strip's capsule is a deliberate, small duplication (R-D7), not a shared extraction.
- **G108's sidebar-order decision, G109's graph work, Settings (Track C), app zoom (Track B)** —
  each its own track.

## Verification (run by the orchestrator at the end)

```
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/sources/app/CicadaApp && swift build 2>&1 | tail -5 && swift test 2>&1 | tail -30
```
Expected: build succeeds, **0 test failures**.

```
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/sources && git status --porcelain -uall
```
Expected: clean (everything from the five tasks committed; no stray `*-report.md`, no `api/.venv`
changes, `memory/` untouched).

```
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/sources && git diff --stat 96df878..HEAD -- api/ mcp/
```
Expected: **empty** — confirms this track never touched the backend or the MCP server (the
APP-ONLY constraint).

```
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/sources && grep -rn '\$[0-9]\|costUsd\|token' app/CicadaApp/Sources/CicadaApp/Views/Sources/ app/CicadaApp/Sources/CicadaApp/Views/Common/PageHeader.swift
```
Expected: no matches (no price/token surface introduced — the 2026-09-03 ruling).

Owner-present check (not blocking a merge, but worth a look before the PR is called done): open
Sources in the live app and confirm the grid reads as labelled sections with real logos, hovering
a browser/feed card reveals its quick action without needing to open the page, and a per-source
page shows its blurb sentence and queue strip above the existing channel state.
