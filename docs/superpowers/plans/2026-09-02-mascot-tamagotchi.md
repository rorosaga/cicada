# G107 Pixel Bookworm Mascot + Single Menu-Bar Tamagotchi — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 16×16 monochrome template glyph with one code-defined, colour, 24×24 pixel bookworm whose every state is always moving (≥ 2 frames each), show exactly ONE animated Tamagotchi in the macOS menu bar with the inbox count baked into the sprite (the duplicated `button.title` text badge goes away), and put the same character on every in-app surface — including the Sleep page, above its bracket status line, which stays as the caption.

**Architecture:** Five commits on `feat/mascot`. (1) The asset class: a nine-colour palette + per-state frame sets composed from string-grid fragments in `BookwormSprites.swift`, and a colour nearest-neighbour `BookwormRenderer` with one image cache keyed `state|frame|count|stage|pointSize`. (2) A seventh state, `error`, for `sleep.error != nil`. (3) The menu bar: one `NSStatusItem` image, timer for every state, no title. (4) The page mascot: `BookwormView` on a `TimelineView`, caption support, Reduce Motion, five call sites rewired. (5) Docs: G107 row, CLAUDE.md, TODO.md.

**Tech Stack:** SwiftUI + AppKit + XCTest (`app/CicadaApp`, Swift Package, macOS 14+). No Python, no API, no MCP changes.

**Spec:** the owner's brief of 2026-09-02 (quoted in the G107 row after Task 5) and `docs/goals/memory-evolution.md` row **G107** (asset-class analysis). The owner's ask supersedes G107's interim "text in brackets until real art exists" ruling; the bracket text survives as a caption, not as the mascot.

## Global Constraints

- Work ONLY in `<worktree>/` (branch `feat/mascot`, base `dev @ bad8461`). Every shell command is `cd <worktree>/ && <cmd>` with absolute paths (`zoxide` hijacks relative `cd`; ignore its stderr warning). No `grep --include=*.ext` (zsh globbing).
- NEVER read `<repo>/memory` (any bank), `~/.cicada`, `~/Library/Safari`, `~/.claude/projects`. No task here needs them.
- Swift: `cd <worktree>/app/CicadaApp && swift build 2>&1 | tail -5` must succeed and `swift test 2>&1 | tail -20` must report 0 failures after every task. Baseline at `bad8461`: 530 tests, 0 failures. SourceKit diagnostics naming OTHER worktrees are noise.
- NEVER run `make dev`, `make install-app`, `swift run`, or launch/kill the Cicada app — the owner's installed app is live; the orchestrator installs at the end.
- Never `git add -A`; stage named files only. Never commit `memory/`, `logs/`, `.claude/settings.json`, `api/.venv`, `*-report.md`. No push, no new branches/worktrees, no subagents. Ignore Devin/PR comments.
- Privacy rule (CLAUDE.md, standing): nothing personal in the plan, commits, docs. Nothing here touches bank data.
- Docstrings explain WHY and cite the G-row or ruling that motivated a rule (house density).
- Line numbers below were verified at `bad8461`; they drift by a few lines as tasks land — read the cited region before editing.

## Rulings (binding — do not re-derive)

- **R1 — Nine palette entries, not eight.** The brief lists eight roles (body, belly, outline, eye, blush, accent, zZ, ? mark) and then adds an `error` state with red eyes. Red is not derivable from any of the eight without losing either blush (pink) or the amber `?`, so the palette is exactly nine: `o` outline `#2B2140`, `b` body `#6FCF6A`, `l` belly `#B8EBA6`, `w` eye white `#FFFFFF`, `r` blush `#F28BAE`, `a` accent (glasses rim, book cover) `#E0A93A`, `z` zZ + sweat `#8896FF`, `q` `?` mark + sparkle + badge pill `#FFCB57`, `e` error red `#EF4444`. `.` is transparent. Pupils reuse `o`. The test asserts the palette is exactly these nine keys.
- **R2 — Overlays are baked by `frames(for:)`.** `BookwormSprites.frames(for:)` returns fully composed frames: the `.curious(count:)` badge and the `.sleeping(stage:)` progress dots are merged in there, from the state's own associated values. Consumers never OR overlays themselves (the old renderer's `overlays:` seam existed only because the 16×16 sprites were count-agnostic). One function, one truth, and the count is "baked into the sprite" as the brief asks.
- **R3 — Menu-bar point size is 18.** 24 cells at 0.75 pt → an 18 pt image, the size the current icon uses and the standard status-item height; a 24 pt image (1 pt per cell) fills the whole 24 pt menu bar and is clipped on notch-less Macs' 22 pt status buttons. Non-integer cells (1.5 device px at 2×) are accepted on the menu bar only — the previous template glyph already ran 16 cells at 18 pt (2.25 px cells) and read fine. Every page size is a multiple of 24 (48, 96, 120) so page pixels are integer and crisp.
- **R4 — Colour art is not tinted.** `BookwormView` loses its `tint:` parameter and `.renderingMode(.template)`. `UploadOverlay`'s drag-over accent tint on the worm is dropped; the drop zone's border already turns accent on `isDragOver` (`UploadOverlay.swift:204`), so the affordance survives.
- **R5 — One image cache, on the renderer.** `BookwormRenderer.cachedImage(state:frameIndex:pointSize:)` (lock-guarded, callable from the main actor and from a `TimelineView` closure alike) is the only cache; key `spriteKey|frame|Int(pointSize)` where `spriteKey` = `caseName` + clamped count / stage. `MenuBarManager`'s private `imageCache` is deleted in Task 3. Frames (string grids) are recomputed per call — four 24×24 merges per tick at ≤ 4 Hz is microseconds; images are never re-rendered per tick.
- **R6 — Error precedence.** `sleeping > error > digesting > hungry > curious > happy > awake`. `Store.pushStatus` sets `justFinishedAt` on ANY running→idle edge (`Sync/Store.swift:392`), so without this order a failed cycle would chew for six seconds before showing red eyes. `error` shows for as long as `/status.sleep.error` is set — the backend clears it at the next cycle start (`sleep_cycle.py:636`) — which is honest: the last cycle failed until one succeeds.
- **R7 — Reduce Motion holds frame 0.** Pages read `@Environment(\.accessibilityReduceMotion)`; the menu bar reads `NSWorkspace.shared.accessibilityDisplayShouldReduceMotion` and re-transitions on `NSWorkspace.accessibilityDisplayOptionsDidChangeNotification` — observed on `NSWorkspace.shared.notificationCenter`, which is where AppKit posts it (not `NotificationCenter.default`). No other settings toggle.
- **R8 — Intervals.** awake 0.5 s, sleeping 0.6, digesting 0.3, happy 0.4, curious 0.6, hungry 0.7, error 0.5 — all inside the brief's 250–800 ms band; the test asserts the band.
- **R9 — The Sleep page keeps its 24 pt monospaced bracket line** as the mascot's caption, same text (`sleepDebtBracketText`), same colour (`sleepDebtBracketColor`), now under a 120 pt worm. `error` adds one bracket string `[ last cycle failed ]` in `CicadaTheme.danger` — a failure IS an alarm; `hungry` still tops out at `.warning` (existing test keeps guarding that).

---

## File map

| File | Responsibility |
|---|---|
| `app/CicadaApp/Sources/CicadaApp/MenuBar/BookwormSprites.swift` | REWRITE: `BookwormPalette`, `PixelGrid` helpers, fragments, `frames(for:)`, `badgeOverlay`, `stageDots` |
| `app/CicadaApp/Sources/CicadaApp/MenuBar/BookwormRenderer.swift` | REWRITE: colour nearest-neighbour `image(grid:pointSize:)`, `cachedImage`, `cacheKey` |
| `app/CicadaApp/Sources/CicadaApp/MenuBar/BookwormState.swift` | `spriteKey`, `badgeCount`, `stageNumber` (T1); `.error` + precedence (T2) |
| `app/CicadaApp/Sources/CicadaApp/MenuBarManager.swift` | one animated item, no title, timer for every state, Reduce Motion (T3) |
| `app/CicadaApp/Sources/CicadaApp/Views/Common/BookwormView.swift` | strip template/tint (T1); `TimelineView` + caption + Reduce Motion (T4) |
| `app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepMood.swift` | `.error` bracket text/colour (T2); `deriveSleepPageMood` error branch (T2) |
| `app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepView.swift` | mascot above the caption in `moodCard` (T4) |
| `app/CicadaApp/Sources/CicadaApp/Views/Feed/FeedView.swift`, `Views/Connect/ConnectView.swift`, `Views/Common/UploadOverlay.swift`, `Views/Inbox/InboxListView.swift` | call sites (T1: tint dropped, Inbox + Connect at final sizes; T4: Feed + Upload sizes) |
| `app/CicadaApp/Tests/CicadaAppTests/BookwormSpriteTests.swift` (new), `BookwormRendererTests.swift` (new), `BookwormStateTests.swift` (new), `BookwormViewTests.swift` (new) | tests |
| `app/CicadaApp/Tests/CicadaAppTests/SleepMoodTests.swift` | + error bracket cases (T2) |
| `CLAUDE.md`, `docs/goals/memory-evolution.md`, `docs/goals/TODO.md` | docs (T5) |

---

### Task 1: The asset class — 24×24 palette sprites + colour renderer

**Files:**
- Rewrite: `app/CicadaApp/Sources/CicadaApp/MenuBar/BookwormSprites.swift` (whole file, currently 308 lines of 16×16 `#` grids)
- Rewrite: `app/CicadaApp/Sources/CicadaApp/MenuBar/BookwormRenderer.swift` (whole file, 67 lines, template renderer)
- Modify: `app/CicadaApp/Sources/CicadaApp/MenuBar/BookwormState.swift:44-57` (add `spriteKey`, `badgeCount`, `stageNumber` after `caseName`)
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Common/BookwormView.swift:12-46` (drop `tint`, template mode, rename fallback)
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Common/UploadOverlay.swift:96-100` (drop the `tint:` argument)
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Inbox/InboxListView.swift:116-119` (static template image → `BookwormView`)
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Connect/ConnectView.swift:303-304` (explicit 48 pt, drop the 44 pt frame)
- Test: `app/CicadaApp/Tests/CicadaAppTests/BookwormSpriteTests.swift` (new), `app/CicadaApp/Tests/CicadaAppTests/BookwormRendererTests.swift` (new)

**Interfaces:**
- Produces: `typealias PixelGrid = [String]`; `enum BookwormPalette { static let colors: [Character: UInt32]; static let transparent: Character }`; `BookwormSprites.size == 24`, `BookwormSprites.frames(for:) -> (frames: [PixelGrid], interval: TimeInterval)` (overlays baked, R2), `BookwormSprites.awakeBase`, `badgeOverlay(_:)`, `stageDots(_:)`, the grid helpers `blank/merge/shift/shiftRows/replaceRows/glyph`; `BookwormRenderer.image(grid:overlays:pointSize:) -> NSImage` (colour, `isTemplate == false`; `overlays:` kept ONLY so `MenuBarManager` compiles until Task 3), `BookwormRenderer.cacheKey(state:frameIndex:pointSize:)`, `BookwormRenderer.cachedImage(state:frameIndex:pointSize:)` (lock-guarded, R5); `BookwormState.spriteKey/badgeCount/stageNumber`.
- Keeps compiling: `MenuBarManager.swift:159,168,178,357,360,362` still call `stageDots`, `badgeOverlay`, `image(grid:overlays:pointSize:)` — the double-merge is idempotent (same OR-merge argument the old zZz comment made), fixed properly in Task 3.

**The character (frame 0 of `awake`, the canonical reference — every other frame is a variation of these fragments):**

```
........................
........................
........oooooooo........
......oobbbbbbbboo......
.....obbbbbbbbbbbbo.....
....obaaaaaaaaaaaaabo...
....obawwwwabawwwwabo...
....obawoowabawoowabo...
....obawoowabawoowabo...
....obaaaaaabaaaaaabo...
....obbrrbbbbbbbbrrbo...
.....obbbobbbbbbobbo....
......obbboooooobbo.....
.......obbbbbbbbbbo.....
........obbllbbbbo......
........obbllbbbbo......
.......obbbllbbbbo......
......obbbllbbbbo.......
.....obbbllbbbbo........
....obbbllbbbbo.........
...obbbbbbbbbo..........
..obbbbbbbboo...........
...ooooooo..............
........................
```

Rows 0–1 are overlay air (zZ, `?`, sparkle); rows 2–12 the head (glasses rows 5–9, mouth rows 10–12); rows 13–22 the body curling down-left (the belly stripe `l` is the reading light); row 23 is the sleep-stage dot row; the bottom-right (rows 16–22, cols 14–22) is the badge pill, which the body never enters.

- [ ] **Step 1: Write the failing sprite tests**

```swift
// app/CicadaApp/Tests/CicadaAppTests/BookwormSpriteTests.swift
import XCTest
@testable import CicadaApp

/// G107: the bookworm is one code-defined 24×24 palette sprite set. These
/// tests are the contract the brief set: every frame is exactly 24×24, every
/// character is a palette index (or transparent), every state has ≥ 2 frames
/// that actually differ (it is always moving), and every interval sits in the
/// 250–800 ms band. Overlays (badge, stage dots) are baked by `frames(for:)`
/// (ruling R2), so they are asserted on the frames themselves.
final class BookwormSpriteTests: XCTestCase {

    /// Every state the renderer can be asked for, with both a one- and a
    /// two-digit count and both ends of the stage range. Task 2 appends
    /// `.error` here.
    static var states: [BookwormState] {
        [.awake, .sleeping(stage: 1), .sleeping(stage: 5), .digesting, .happy,
         .curious(count: 1), .curious(count: 47), .curious(count: 250), .hungry]
    }

    private var allowed: Set<Character> {
        Set(BookwormPalette.colors.keys).union([BookwormPalette.transparent])
    }

    func testPaletteIsExactlyTheNineRoles() {
        XCTAssertEqual(Set(BookwormPalette.colors.keys), ["o", "b", "l", "w", "r", "a", "z", "q", "e"])
        XCTAssertEqual(BookwormPalette.transparent, ".")
        XCTAssertEqual(BookwormSprites.size, 24)
    }

    func testEveryFrameIs24x24AndInPalette() {
        for state in Self.states {
            let (frames, _) = BookwormSprites.frames(for: state)
            for (i, frame) in frames.enumerated() {
                XCTAssertEqual(frame.count, 24, "\(state.caseName) frame \(i) row count")
                for (r, row) in frame.enumerated() {
                    XCTAssertEqual(row.count, 24, "\(state.caseName) frame \(i) row \(r) width")
                    for ch in row where !allowed.contains(ch) {
                        XCTFail("\(state.caseName) frame \(i) row \(r): '\(ch)' is not a palette index")
                    }
                }
            }
        }
    }

    func testEveryStateHasAtLeastTwoFramesThatDiffer() {
        for state in Self.states {
            let (frames, _) = BookwormSprites.frames(for: state)
            XCTAssertGreaterThanOrEqual(frames.count, 2, state.caseName)
            XCTAssertTrue(frames.contains { $0 != frames[0] }, "\(state.caseName) never moves")
        }
    }

    func testEveryIntervalIsInsideTheBand() {
        for state in Self.states {
            let (_, interval) = BookwormSprites.frames(for: state)
            XCTAssertGreaterThanOrEqual(interval, 0.25, state.caseName)
            XCTAssertLessThanOrEqual(interval, 0.8, state.caseName)
        }
    }

    /// The glasses rim (row 5, cols 0…20 — the head's span; cols 21…23 are
    /// overlay air where a z or a sweat drop may sit) is the character's
    /// signature; it must be the same in the untilted first frame of every
    /// state so the worm stays recognisable across moods.
    func testGlassesRimIsIdenticalAcrossStates() {
        let rim = String(BookwormSprites.awakeBase[5].prefix(21))
        XCTAssertEqual(rim, "....obaaaaaaaaaaaaabo")
        for state in [BookwormState.happy, .digesting, .hungry, .curious(count: 3), .sleeping(stage: 2)] {
            XCTAssertEqual(String(BookwormSprites.frames(for: state).frames[0][5].prefix(21)), rim, state.caseName)
        }
    }

    func testAwakeBaseIsTheCanonicalFrame() {
        XCTAssertEqual(BookwormSprites.frames(for: .awake).frames[0], BookwormSprites.awakeBase)
        XCTAssertEqual(BookwormSprites.awakeBase[7], "....obawoowabawoowabo...")   // pupils
        XCTAssertEqual(BookwormSprites.awakeBase[10], "....obbrrbbbbbbbbrrbo...")  // blush
    }

    // MARK: badge

    func testBadgeDigitsLandInsideThePill() {
        let b = BookwormSprites.badgeOverlay(47)
        // Two digits: pill is 9 wide, right edge col 22 → cols 14…22, rows 16…22.
        XCTAssertEqual(b[16], "..............qqqqqqqqq.")
        XCTAssertEqual(b[22], "..............qqqqqqqqq.")
        let row17 = Array(b[17])
        XCTAssertEqual(String(row17[15...17]), "oqo", "'4' top row")
        XCTAssertEqual(String(row17[19...21]), "ooo", "'7' top row")
        // One digit: pill is 5 wide → cols 18…22.
        XCTAssertEqual(BookwormSprites.badgeOverlay(7)[16], "..................qqqqq.")
    }

    func testBadgeClampsTo1Through99() {
        XCTAssertEqual(BookwormSprites.badgeOverlay(250), BookwormSprites.badgeOverlay(99))
        XCTAssertEqual(BookwormSprites.badgeOverlay(0), BookwormSprites.badgeOverlay(1))
        XCTAssertEqual(BookwormSprites.badgeOverlay(-4), BookwormSprites.badgeOverlay(1))
    }

    func testCuriousFramesCarryTheCount() {
        for frame in BookwormSprites.frames(for: .curious(count: 47)).frames {
            XCTAssertEqual(String(Array(frame[17])[19...21]), "ooo", "count baked into every frame")
        }
        // The head tilt never reaches the badge column.
        XCTAssertEqual(BookwormSprites.frames(for: .curious(count: 47)).frames[1][16].suffix(10),
                       BookwormSprites.frames(for: .curious(count: 47)).frames[0][16].suffix(10))
    }

    // MARK: stage dots

    func testStageDotsFillLeftToRightOnTheBottomRow() {
        XCTAssertEqual(BookwormSprites.stageDots(3)[23], "...a...a...a...o...o....")
        XCTAssertEqual(BookwormSprites.stageDots(0)[23], "...o...o...o...o...o....")
        XCTAssertEqual(BookwormSprites.stageDots(9)[23], "...a...a...a...a...a....")
        for frame in BookwormSprites.frames(for: .sleeping(stage: 2)).frames {
            XCTAssertEqual(frame[23], "...a...a...o...o...o....")
        }
    }

    // MARK: helpers

    func testShiftAndMergeNeverChangeDimensions() {
        let g = BookwormSprites.awakeBase
        for grid in [BookwormSprites.shift(g, dx: 1), BookwormSprites.shift(g, dy: -1),
                     BookwormSprites.shift(g, dx: -2, dy: 2), BookwormSprites.merge(g, BookwormSprites.badgeOverlay(9)),
                     BookwormSprites.shiftRows(g, 2..<13, dx: 1)] {
            XCTAssertEqual(grid.count, 24)
            XCTAssertTrue(grid.allSatisfy { $0.count == 24 })
        }
        XCTAssertEqual(BookwormSprites.shift(g, dy: 1)[3], g[2])
        XCTAssertEqual(BookwormSprites.shift(g, dx: 1)[5], "." + g[5].dropLast())
    }
}
```

```swift
// app/CicadaApp/Tests/CicadaAppTests/BookwormRendererTests.swift
import AppKit
import XCTest
@testable import CicadaApp

/// G107: the renderer draws palette colour (not a template) with hard pixel
/// edges, and caches one image per (state, frame, count, stage, size) so a
/// timer tick never re-rasterizes.
@MainActor
final class BookwormRendererTests: XCTestCase {

    /// Draw the image into a bitmap and read one sprite cell's RAW RGBA
    /// bytes. `getPixel`, not `colorAt(…).usingColorSpace(.sRGB)`: the TIFF
    /// rep is tagged calibrated-RGB, and converting that back to sRGB shifts
    /// every component by ~15% (measured 0x6F → 127) although the bytes are
    /// exact. The bitmap may come back at 1× or 2× depending on the host;
    /// sample the centre of the cell at whatever scale we got. Rows are
    /// top-down (verified: row 7 col 8 reads the pupil, row 16 col 8 body).
    private func cell(_ image: NSImage, col: Int, row: Int) throws -> [Int] {
        let rep = try XCTUnwrap(NSBitmapImageRep(data: try XCTUnwrap(image.tiffRepresentation)))
        XCTAssertEqual(rep.bitsPerSample, 8)
        XCTAssertEqual(rep.samplesPerPixel, 4, "RGBA — the sprite has transparent cells")
        let scale = rep.pixelsWide / BookwormSprites.size
        XCTAssertGreaterThanOrEqual(scale, 1)
        var px = [Int](repeating: 0, count: rep.samplesPerPixel)
        rep.getPixel(&px, atX: col * scale + scale / 2, y: row * scale + scale / 2)
        return px
    }

    private func assertColor(_ px: [Int], hex: UInt32, _ what: String) {
        XCTAssertEqual(px[0], Int((hex >> 16) & 0xFF), accuracy: 3, what)
        XCTAssertEqual(px[1], Int((hex >> 8) & 0xFF), accuracy: 3, what)
        XCTAssertEqual(px[2], Int(hex & 0xFF), accuracy: 3, what)
        XCTAssertEqual(px[3], 255, what)
    }

    func testImageIsColourNotTemplateAtTheRequestedSize() {
        let img = BookwormRenderer.image(grid: BookwormSprites.awakeBase, pointSize: 96)
        XCTAssertFalse(img.isTemplate)
        XCTAssertEqual(img.size, NSSize(width: 96, height: 96))
    }

    func testPixelsCarryPaletteColours() throws {
        let img = BookwormRenderer.image(grid: BookwormSprites.awakeBase, pointSize: 24)
        assertColor(try cell(img, col: 10, row: 10), hex: 0x6FCF6A, "body")
        assertColor(try cell(img, col: 7, row: 6), hex: 0xFFFFFF, "lens white")
        assertColor(try cell(img, col: 8, row: 7), hex: 0x2B2140, "pupil = outline")
        assertColor(try cell(img, col: 7, row: 10), hex: 0xF28BAE, "blush")
        XCTAssertEqual(try cell(img, col: 0, row: 0)[3], 0, "corner is transparent")
        XCTAssertEqual(try cell(img, col: 23, row: 23)[3], 0)
    }

    func testCacheKeyDistinguishesCountStageFrameAndSize() {
        XCTAssertEqual(BookwormRenderer.cacheKey(state: .awake, frameIndex: 0, pointSize: 18), "awake|0|18")
        XCTAssertEqual(BookwormRenderer.cacheKey(state: .curious(count: 47), frameIndex: 2, pointSize: 96), "curious|47|2|96")
        XCTAssertEqual(BookwormRenderer.cacheKey(state: .curious(count: 250), frameIndex: 0, pointSize: 18), "curious|99|0|18")
        XCTAssertEqual(BookwormRenderer.cacheKey(state: .sleeping(stage: 3), frameIndex: 1, pointSize: 18), "sleeping|3|1|18")
        XCTAssertNotEqual(BookwormRenderer.cacheKey(state: .curious(count: 3), frameIndex: 0, pointSize: 18),
                          BookwormRenderer.cacheKey(state: .curious(count: 4), frameIndex: 0, pointSize: 18))
    }

    func testCachedImageReturnsTheSameObjectForTheSameKey() {
        let a = BookwormRenderer.cachedImage(state: .hungry, frameIndex: 1, pointSize: 96)
        let b = BookwormRenderer.cachedImage(state: .hungry, frameIndex: 1, pointSize: 96)
        XCTAssertTrue(a === b)
        XCTAssertFalse(a === BookwormRenderer.cachedImage(state: .hungry, frameIndex: 2, pointSize: 96))
    }

    func testCachedImageWrapsFrameIndex() {
        let count = BookwormSprites.frames(for: .awake).frames.count
        XCTAssertTrue(BookwormRenderer.cachedImage(state: .awake, frameIndex: 0, pointSize: 48)
                      === BookwormRenderer.cachedImage(state: .awake, frameIndex: count, pointSize: 48))
    }
}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd <worktree>/app/CicadaApp && swift build --build-tests 2>&1 | grep -E "error:" | head -20`
Expected: compile errors — `BookwormPalette`, `BookwormSprites.size`, `awakeBase`, `shift`, `cacheKey`, `cachedImage` do not exist.

- [ ] **Step 3: Rewrite `BookwormSprites.swift`**

Replace the whole file with:

```swift
import Foundation

/// A sprite frame: 24 rows of 24 characters, one character per palette index
/// (`BookwormPalette.colors`) or `.` for transparent. Grids are authored as
/// strings in code — no image pipeline, no asset catalog — so the mascot is
/// as portable as the rest of the bank (CLAUDE.md: portability is the point).
typealias PixelGrid = [String]

/// The mascot's nine colours (ruling R1 of the 2026-09-02 mascot plan). The
/// brief named eight roles; `error` red is the ninth because it cannot be
/// borrowed from blush or amber without losing one of them. Pupils reuse `o`.
enum BookwormPalette {
    static let transparent: Character = "."
    static let colors: [Character: UInt32] = [
        "o": 0x2B2140,  // outline + pupils — dark plum, survives light AND dark menu bars
        "b": 0x6FCF6A,  // body green
        "l": 0xB8EBA6,  // belly / reading-light stripe
        "w": 0xFFFFFF,  // lens white
        "r": 0xF28BAE,  // blush
        "a": 0xE0A93A,  // accent: glasses rim, book cover (= CicadaTheme hub gold)
        "z": 0x8896FF,  // zZ + sweat drop (= CicadaTheme dark accent)
        "q": 0xFFCB57,  // ? mark, sparkle, badge pill (= CicadaTheme pendingPulse)
        "e": 0xEF4444,  // error red pupils
    ]
}

/// Code-defined 24×24 pixel bookworm — G107's "real art". One character,
/// seven moods, every mood ≥ 2 frames so it is always moving (the owner's
/// 2026-09-02 ask). Frames are COMPOSED from shared fragments (head top,
/// glasses, mouth, body) plus small overlay glyphs, so the silhouette is
/// identical across states by construction and the head/glasses row is
/// asserted equal in `BookwormSpriteTests`.
///
/// `frames(for:)` bakes the `.curious` count badge and the `.sleeping` stage
/// dots into the frames it returns (ruling R2): consumers never merge
/// overlays themselves, which is what lets the menu bar show ONE image with
/// the count inside it instead of an icon plus a text title.
enum BookwormSprites {
    static let size = 24
    private static let transparent = BookwormPalette.transparent

    // MARK: - Grid helpers (pure; tested)

    static func blank() -> PixelGrid {
        Array(repeating: String(repeating: transparent, count: size), count: size)
    }

    /// Row `r` of `grid`, padded/truncated to exactly `size` characters —
    /// ragged authoring (trailing spaces stripped by an editor) must never
    /// crash indexing, the same rule the 16×16 renderer had.
    private static func padded(_ grid: PixelGrid, _ r: Int) -> String {
        guard r < grid.count else { return String(repeating: transparent, count: size) }
        let row = grid[r]
        if row.count == size { return row }
        if row.count > size { return String(row.prefix(size)) }
        return row + String(repeating: transparent, count: size - row.count)
    }

    /// Paints every non-transparent cell of `overlay` onto `base`.
    static func merge(_ base: PixelGrid, _ overlay: PixelGrid) -> PixelGrid {
        (0..<size).map { r in
            var row = Array(padded(base, r))
            let over = Array(padded(overlay, r))
            for c in 0..<size where over[c] != transparent { row[c] = over[c] }
            return String(row)
        }
    }

    private static func shiftRow(_ row: String, _ dx: Int) -> String {
        if dx > 0 { return String(repeating: transparent, count: dx) + String(row.prefix(size - dx)) }
        if dx < 0 { return String(row.dropFirst(-dx)) + String(repeating: transparent, count: -dx) }
        return row
    }

    /// Whole-sprite translation (a bob is `dy: 1`, a bounce `dy: -1`). Cells
    /// pushed off the edge are dropped.
    static func shift(_ grid: PixelGrid, dx: Int = 0, dy: Int = 0) -> PixelGrid {
        var out = blank()
        for r in 0..<size {
            let rr = r + dy
            guard rr >= 0, rr < size else { continue }
            out[rr] = shiftRow(padded(grid, r), dx)
        }
        return out
    }

    /// Horizontal shift of a band of rows only — a head tilt keeps the body
    /// still.
    static func shiftRows(_ grid: PixelGrid, _ rows: Range<Int>, dx: Int) -> PixelGrid {
        var out = (0..<size).map { padded(grid, $0) }
        for r in rows { out[r] = shiftRow(padded(grid, r), dx) }
        return out
    }

    static func replaceRows(_ grid: PixelGrid, at start: Int, with rows: PixelGrid) -> PixelGrid {
        var out = grid
        for (i, row) in rows.enumerated() { out[start + i] = row }
        return out
    }

    /// A small glyph placed at (`top`, `left`) on an otherwise blank grid,
    /// clipped at the edges.
    static func glyph(_ shape: [String], top: Int, left: Int) -> PixelGrid {
        var out = blank()
        for (i, row) in shape.enumerated() {
            let r = top + i
            guard r >= 0, r < size else { continue }
            var line = Array(out[r])
            for (j, ch) in row.enumerated() where ch != transparent {
                let c = left + j
                if c >= 0, c < size { line[c] = ch }
            }
            out[r] = String(line)
        }
        return out
    }

    // MARK: - Fragments (rows 2–4 head top, 5–9 glasses, 10–12 mouth, 13–22 body)

    private static let headTop: PixelGrid = [
        "........oooooooo........",  // 2
        "......oobbbbbbbboo......",  // 3
        ".....obbbbbbbbbbbbo.....",  // 4
    ]

    enum Lid { case open, closed, half }

    /// Rows 5–9: two closed rims joined by a bridge on the top row, lenses
    /// four cells wide. `pupil` is `o` normally and `e` for the error state.
    static func eyes(pupil: Character = "o", lid: Lid = .open) -> PixelGrid {
        func lens(_ inside: String) -> String { "a" + inside + "a" }
        func row(_ l: String, _ r: String) -> String { "....ob" + l + "b" + r + "bo..." }
        let white = lens("wwww")
        let shut = lens("oooo")
        let look = lens("w" + String(pupil) + String(pupil) + "w")
        let rimTop = "....ob" + "aaaaaa" + "a" + "aaaaaa" + "bo..."     // 5 — the bridge joins the rims
        let rimBottom = "....ob" + "aaaaaa" + "b" + "aaaaaa" + "bo..."  // 9
        let middle: [String]
        switch lid {
        case .open:   middle = [row(white, white), row(look, look), row(look, look)]
        case .closed: middle = [row(white, white), row(white, white), row(shut, shut)]
        case .half:   middle = [row(shut, shut), row(look, look), row(white, white)]
        }
        return [rimTop] + middle + [rimBottom]
    }

    private static let mouthSmile: PixelGrid = [
        "....obbrrbbbbbbbbrrbo...",  // 10 blush
        ".....obbbobbbbbbobbo....",  // 11 smile corners
        "......obbboooooobbo.....",  // 12 smile + chin
    ]
    private static let mouthGrin: PixelGrid = [
        "....obbrrbbbbbbbbrrbo...",
        ".....obbboooooooobbo....",  // 11 wide grin
        "......obbbowwwwobbo.....",  // 12 teeth
    ]
    private static let mouthNeutral: PixelGrid = [
        "....obbbbbbbbbbbbbbbo...",
        ".....obbbbbbbbbbbbbo....",
        "......obbbooooobbbo.....",  // 12 flat line
    ]
    private static let mouthFrown: PixelGrid = [
        "....obbbbbbbbbbbbbbbo...",
        ".....obbbboooooobbbo....",  // 11 bowl
        "......obbobbbbbbobbo....",  // 12 corners down
    ]
    private static let mouthOpen: PixelGrid = [
        "....obbrrbbbbbbbbrrbo...",
        ".....obbbboooooobbbo....",  // 11 open
        "......obbboaaaaobbo.....",  // 12 book cover between the lips
    ]
    private static let mouthChew: PixelGrid = [
        "....obbrrbbbbbbbbrrbo...",
        ".....obbbbooooooobbo....",  // 11 closed on the book
        "......obbbboaaaobbo.....",  // 12 a bite taken
    ]

    private static let body: PixelGrid = [
        ".......obbbbbbbbbbo.....",  // 13 neck
        "........obbllbbbbo......",  // 14
        "........obbllbbbbo......",  // 15
        ".......obbbllbbbbo......",  // 16
        "......obbbllbbbbo.......",  // 17
        ".....obbbllbbbbo........",  // 18
        "....obbbllbbbbo.........",  // 19
        "...obbbbbbbbbo..........",  // 20 tail
        "..obbbbbbbboo...........",  // 21
        "...ooooooo..............",  // 22
    ]
    /// Chest rise: the belly stripe one cell wider on rows 14–16.
    private static let bodyBreath: PixelGrid = [
        ".......obbbbbbbbbbo.....",
        "........oblllbbbbo......",
        "........oblllbbbbo......",
        ".......obblllbbbbo......",
        "......obbbllbbbbo.......",
        ".....obbbllbbbbo........",
        "....obbbllbbbbo.........",
        "...obbbbbbbbbo..........",
        "..obbbbbbbboo...........",
        "...ooooooo..............",
    ]

    private static func compose(_ eyeRows: PixelGrid, _ mouth: PixelGrid, body: PixelGrid = body) -> PixelGrid {
        var g = blank()
        g = replaceRows(g, at: 2, with: headTop)
        g = replaceRows(g, at: 5, with: eyeRows)
        g = replaceRows(g, at: 10, with: mouth)
        g = replaceRows(g, at: 13, with: body)
        return g
    }

    // MARK: - Overlay glyphs

    private static let zSmall = ["zzz", "..z", ".z.", "zzz"]
    private static let zBig = ["zzzzz", "...z.", "..z..", ".z...", "zzzzz"]
    private static let questionMark = [".qqq.", "q...q", "....q", "...q.", "..q..", ".....", "..q.."]
    private static let sparkle = ["..q..", ".qqq.", "qqqqq", ".qqq.", "..q.."]
    private static let sparkleSmall = ["..q..", ".q.q.", "..q.."]
    private static let drop = [".z.", "zzz", "zzz"]
    private static let dropSmall = [".z.", "zzz"]
    private static let book = ["aaaaa", "awwwa", "awwwa", "aaaaa"]
    private static let bookBitten = ["aaaa.", "awwa.", "awwa.", "aaaa."]

    /// 3×5 mini-font for the badge count, drawn in outline colour on the
    /// amber pill.
    static let digits: [Character: [String]] = [
        "0": ["ooo", "o.o", "o.o", "o.o", "ooo"],
        "1": [".o.", "oo.", ".o.", ".o.", "ooo"],
        "2": ["ooo", "..o", "ooo", "o..", "ooo"],
        "3": ["ooo", "..o", "ooo", "..o", "ooo"],
        "4": ["o.o", "o.o", "ooo", "..o", "..o"],
        "5": ["ooo", "o..", "ooo", "..o", "ooo"],
        "6": ["ooo", "o..", "ooo", "o.o", "ooo"],
        "7": ["ooo", "..o", "..o", "..o", "..o"],
        "8": ["ooo", "o.o", "ooo", "o.o", "ooo"],
        "9": ["ooo", "o.o", "ooo", "..o", "ooo"],
    ]

    /// The inbox count as a pixel numeral INSIDE the sprite: an amber pill in
    /// the bottom-right corner (right edge col 22, rows 16–22 — the body curls
    /// left, so nothing else lives there), clamped to 1…99. This is what
    /// replaced the menu bar's duplicate `button.title` text badge.
    static func badgeOverlay(_ count: Int) -> PixelGrid {
        let text = String(max(1, min(99, count)))
        let width = 3 * text.count + (text.count - 1) + 2   // digits + 1px gaps + 1px pad each side
        let left = 23 - width
        var out = glyph(Array(repeating: String(repeating: "q", count: width), count: 7), top: 16, left: left)
        var x = left + 1
        for ch in text {
            out = merge(out, glyph(digits[ch] ?? [], top: 17, left: x))
            x += 4
        }
        return out
    }

    /// Sleep-stage progress: five dots on the bottom row, `stage` of them lit
    /// in accent, the rest in outline so the row reads as a track.
    static func stageDots(_ stage: Int) -> PixelGrid {
        let filled = max(0, min(5, stage))
        var row = Array(String(repeating: transparent, count: size))
        for (i, c) in [3, 7, 11, 15, 19].enumerated() { row[c] = i < filled ? "a" : "o" }
        var out = blank()
        out[23] = String(row)
        return out
    }

    // MARK: - Base frames

    /// Awake idle, eyes open, smile. The canonical frame (see the plan's reference grid).
    static let awakeBase: PixelGrid = compose(eyes(), mouthSmile)
    private static let awakeBlink: PixelGrid = compose(eyes(lid: .closed), mouthSmile)
    private static let sleepBase: PixelGrid = compose(eyes(lid: .closed), mouthNeutral)
    private static let sleepBreath: PixelGrid = compose(eyes(lid: .closed), mouthNeutral, body: bodyBreath)
    private static let happyBase: PixelGrid = compose(eyes(), mouthGrin)
    private static let curiousBase: PixelGrid = compose(eyes(), mouthNeutral)
    private static let curiousTilt: PixelGrid = shiftRows(curiousBase, 2..<13, dx: 1)
    private static let hungryBase: PixelGrid = compose(eyes(lid: .half), mouthFrown)

    // MARK: - Animation lookup

    /// Ordered frames + per-frame interval for a state, overlays baked in
    /// (R2). Every state returns ≥ 2 frames that differ, so a consumer's
    /// timer always has something to show; intervals sit in 250–800 ms (R8).
    static func frames(for state: BookwormState) -> (frames: [PixelGrid], interval: TimeInterval) {
        switch state {
        case .awake:
            // Idle bob (one cell down) and a blink.
            return ([awakeBase, shift(awakeBase, dy: 1), awakeBase, awakeBlink], 0.5)
        case .sleeping(let stage):
            // Eyes shut; a z drifts up-right and grows; the belly rises on the middle frame.
            let dots = stageDots(stage)
            return ([
                merge(merge(sleepBase, glyph(zSmall, top: 2, left: 21)), dots),
                merge(merge(sleepBreath, glyph(zSmall, top: 1, left: 20)), dots),
                merge(merge(sleepBase, glyph(zBig, top: 0, left: 19)), dots),
            ], 0.6)
        case .digesting:
            // Chewing on a book held at the right cheek; the book loses a corner.
            return ([
                merge(compose(eyes(), mouthOpen), glyph(book, top: 10, left: 17)),
                merge(compose(eyes(), mouthChew), glyph(book, top: 10, left: 17)),
                merge(compose(eyes(lid: .closed), mouthChew), glyph(bookBitten, top: 10, left: 17)),
                merge(compose(eyes(), mouthOpen), glyph(bookBitten, top: 10, left: 17)),
            ], 0.3)
        case .happy:
            // Bounce (one cell up) with sparkles trading corners.
            return ([
                merge(happyBase, glyph(sparkleSmall, top: 2, left: 1)),
                merge(shift(happyBase, dy: -1), merge(glyph(sparkle, top: 0, left: 18), glyph(sparkleSmall, top: 5, left: 1))),
                merge(happyBase, glyph(sparkleSmall, top: 1, left: 19)),
                shift(happyBase, dy: -1),
            ], 0.4)
        case .curious(let count):
            // Head tilt with a ? that lifts; the count rides in the pill on every frame.
            let badge = badgeOverlay(count)
            return ([
                merge(merge(curiousBase, glyph(questionMark, top: 0, left: 19)), badge),
                merge(merge(curiousTilt, glyph(questionMark, top: 0, left: 19)), badge),
                merge(merge(curiousTilt, glyph(questionMark, top: 1, left: 19)), badge),
            ], 0.6)
        case .hungry:
            // Half-lidded droop (one cell down) with a sweat drop sliding down the temple.
            return ([
                merge(hungryBase, glyph(dropSmall, top: 3, left: 21)),
                merge(shift(hungryBase, dy: 1), glyph(drop, top: 5, left: 21)),
                merge(shift(hungryBase, dy: 1), glyph(drop, top: 8, left: 21)),
            ], 0.7)
        }
    }
}
```

- [ ] **Step 4: Rewrite `BookwormRenderer.swift`**

```swift
import AppKit

/// Rasterizes a `PixelGrid` into a COLOUR `NSImage` with nearest-neighbour
/// cells. Colour, not template (G107): a template image is tinted uniformly
/// by the system and so cannot show mood; the 1-px `o` outline is what makes
/// the silhouette survive both the light and the dark menu bar without
/// tinting. Page consumers request sizes that are multiples of 24 so cells
/// are integer points (ruling R3); the menu bar runs 18 pt.
enum BookwormRenderer {
    static let gridSize = BookwormSprites.size

    private static let colors: [Character: NSColor] = BookwormPalette.colors.mapValues { hex in
        NSColor(srgbRed: CGFloat((hex >> 16) & 0xFF) / 255,
                green: CGFloat((hex >> 8) & 0xFF) / 255,
                blue: CGFloat(hex & 0xFF) / 255,
                alpha: 1)
    }

    /// Render one grid at `pointSize` × `pointSize`. `overlays` are OR-merged
    /// first; the parameter exists only for `MenuBarManager`'s pre-Task-3
    /// call sites — `BookwormSprites.frames(for:)` already bakes every overlay
    /// (R2), so new callers pass none.
    static func image(grid: PixelGrid, overlays: [PixelGrid] = [], pointSize: CGFloat) -> NSImage {
        let merged = overlays.reduce(grid) { BookwormSprites.merge($0, $1) }
        let rows: [[Character]] = (0..<gridSize).map { r in
            r < merged.count ? Array(merged[r].padding(toLength: gridSize, withPad: ".", startingAt: 0)) : Array(repeating: ".", count: gridSize)
        }
        let cell = pointSize / CGFloat(gridSize)
        let image = NSImage(size: NSSize(width: pointSize, height: pointSize), flipped: false) { _ in
            guard let ctx = NSGraphicsContext.current else { return false }
            // Hard edges: a pixel is a pixel at every scale.
            ctx.shouldAntialias = false
            ctx.imageInterpolation = .none
            for (r, line) in rows.enumerated() {
                for (c, ch) in line.enumerated() {
                    guard let color = colors[ch] else { continue }   // "." and unknowns stay clear
                    color.setFill()
                    // Grid row 0 is the top; AppKit's origin is bottom-left.
                    let x = CGFloat(c) * cell
                    let y = CGFloat(gridSize - 1 - r) * cell
                    NSBezierPath(rect: NSRect(x: x, y: y, width: cell, height: cell)).fill()
                }
            }
            return true
        }
        image.isTemplate = false
        return image
    }

    // MARK: - Cache (ruling R5: one cache, keyed state|frame|count|stage|size)

    /// Stable key: `caseName`, then the count (clamped to the badge's 99) or
    /// the stage when the state carries one, then frame and size. Two
    /// `.curious` states that differ only in count MUST get different keys
    /// because the count is drawn into the frame.
    static func cacheKey(state: BookwormState, frameIndex: Int, pointSize: CGFloat) -> String {
        "\(state.spriteKey)|\(frameIndex)|\(Int(pointSize))"
    }

    /// Lock-guarded rather than actor-isolated so BOTH consumers can call it
    /// from where they already are: `MenuBarManager` (main actor) and
    /// `BookwormView`'s `TimelineView` content closure, whose isolation the
    /// SDK does not spell out. An `NSLock` around a dictionary is the whole
    /// cost; `NSImage` is immutable once built.
    private static let lock = NSLock()
    nonisolated(unsafe) private static var cache: [String: NSImage] = [:]

    /// The rendered frame for `state`, drawn at most once per key. A timer
    /// tick is a dictionary hit, never a rasterization — that is what keeps
    /// the always-moving menu bar at negligible CPU.
    static func cachedImage(state: BookwormState, frameIndex: Int, pointSize: CGFloat) -> NSImage {
        let (frames, _) = BookwormSprites.frames(for: state)
        let idx = frames.isEmpty ? 0 : ((frameIndex % frames.count) + frames.count) % frames.count
        let key = cacheKey(state: state, frameIndex: idx, pointSize: pointSize)
        lock.lock()
        let hit = cache[key]
        lock.unlock()
        if let hit { return hit }
        let grid = frames.isEmpty ? BookwormSprites.awakeBase : frames[idx]
        let img = image(grid: grid, pointSize: pointSize)
        lock.lock()
        // 7 states × ≤ 4 frames × ≤ 99 counts × a few sizes is still small,
        // but bound it so a long-running app can never grow it unboundedly.
        if cache.count > 512 { cache.removeAll() }
        // A racing second render of the same key just wins by being last; both
        // images are pixel-identical, so nothing observable depends on which.
        cache[key] = img
        lock.unlock()
        return img
    }
}
```

`cachedImage` calls `frames(for:)` on every call (to wrap the index); that is four string merges — acceptable per R5. If the executor prefers, compute the count from a tiny `BookwormSprites.frameCount(for:)` — but then keep both in sync; the plan chooses the single source.

- [ ] **Step 5: Add `spriteKey`, `badgeCount`, `stageNumber` to `BookwormState`**

In `BookwormState.swift`, after the `caseName` property (line 57, before the closing brace of the enum), add:

```swift
    /// The inbox count the badge draws (1…99) — `0` for every other state.
    var badgeCount: Int {
        if case .curious(let n) = self { return max(1, min(99, n)) }
        return 0
    }

    /// The 1…5 stage the sleeping frames light up — `0` for every other state.
    var stageNumber: Int {
        if case .sleeping(let s) = self { return max(0, min(5, s)) }
        return 0
    }

    /// Identity of the FRAME SET, as opposed to `caseName` (identity of the
    /// animation loop): `.curious` bakes its count and `.sleeping` its stage
    /// into the frames (R2), so they are part of the key the renderer caches
    /// by (R5). `curious|47`, `sleeping|3`, `awake`.
    var spriteKey: String {
        switch self {
        case .curious: "\(caseName)|\(badgeCount)"
        case .sleeping: "\(caseName)|\(stageNumber)"
        default: caseName
        }
    }
```

- [ ] **Step 6: Minimal call-site edits so colour is honest immediately**

1. `BookwormView.swift` — replace lines 12–46 (the struct up to the end of `body`) so the view has no `tint`, no template mode, and the fallback uses the new name. The timer plumbing (lines 48–62) stays until Task 4:

```swift
struct BookwormView: View {
    let state: BookwormState
    var pointSize: CGFloat = 96

    @State private var frameIndex = 0
    @State private var timer: Timer?

    private var frames: [PixelGrid] {
        BookwormSprites.frames(for: state).frames
    }

    private var interval: TimeInterval {
        BookwormSprites.frames(for: state).interval
    }

    private var currentGrid: PixelGrid {
        let f = frames
        guard !f.isEmpty else { return BookwormSprites.awakeBase }
        return f[min(frameIndex, f.count - 1)]
    }

    var body: some View {
        // Colour art (G107): no template mode, no tint — the palette is the mood.
        Image(nsImage: BookwormRenderer.image(grid: currentGrid, pointSize: pointSize))
            .interpolation(.none)
            .frame(width: pointSize, height: pointSize)
            .onAppear { startTimer() }
            .onDisappear { stopTimer() }
            .onChange(of: state.spriteKey) { _, _ in
                frameIndex = 0
                startTimer()
            }
    }
```

   Update the file's header doc comment (lines 3–11) to say it renders the colour 24×24 sprites and that Task 4 of the G107 plan moves it to a `TimelineView`; drop the sentence about `InboxListView`'s static frame.

2. `UploadOverlay.swift:96-100` — replace the call with:

```swift
                BookwormView(state: mascotState, pointSize: 72)
```
   and update the comment above it (lines 92–95): the worm is colour now, so there is no drag tint; the drop border at line 204 carries `isDragOver` (R4).

3. `InboxListView.swift:116-119` — replace the four `Image(nsImage: …)…foregroundStyle` lines with:

```swift
            BookwormView(state: .happy, pointSize: 96)
```

4. `ConnectView.swift:303-304` — today it is `BookwormView(state: .happy)` (the old 64 pt default) clipped by `.frame(width: 44, height: 44)`. The new default is 96 and the view now frames itself at `pointSize`, and SwiftUI does not clip an oversized child, so this commit would draw a 96 pt worm spilling out of a 44 pt slot. Replace both lines with:

```swift
            BookwormView(state: .happy, pointSize: 48)
```

   (48 = 2 pt cells, R3; the intro card's text column sits beside it.) Task 4 only verifies this line.

- [ ] **Step 7: Build and run the suite**

Run: `cd <worktree>/app/CicadaApp && swift build 2>&1 | tail -5 && swift test 2>&1 | tail -20`
Expected: build OK; all tests pass (530 baseline + the new ones). The sprite, renderer, state and view code in this plan, plus these exact test files, were compiled and run green in a scratch SwiftPM package against this machine's toolchain (Swift 6.2.1, `-swift-version 5`, macOS 14 target) before the plan was written — the raw-byte sampling in `BookwormRendererTests.cell` is the version that passes; the `colorAt`/`usingColorSpace` version does not. The plan critic re-ran that check independently on 2026-09-02: the sprite/renderer/state/view sources and the four new test files, assembled verbatim from this plan's code blocks (with Task 2's `.error` case and Task 3's two appended tests included), build and pass 28/28 in a scratch package on this toolchain.

- [ ] **Step 8: Commit**

```bash
cd <worktree>/ && git add app/CicadaApp/Sources/CicadaApp/MenuBar/BookwormSprites.swift app/CicadaApp/Sources/CicadaApp/MenuBar/BookwormRenderer.swift app/CicadaApp/Sources/CicadaApp/MenuBar/BookwormState.swift app/CicadaApp/Sources/CicadaApp/Views/Common/BookwormView.swift app/CicadaApp/Sources/CicadaApp/Views/Common/UploadOverlay.swift app/CicadaApp/Sources/CicadaApp/Views/Inbox/InboxListView.swift app/CicadaApp/Sources/CicadaApp/Views/Connect/ConnectView.swift app/CicadaApp/Tests/CicadaAppTests/BookwormSpriteTests.swift app/CicadaApp/Tests/CicadaAppTests/BookwormRendererTests.swift && git commit -m "feat(app): 24x24 palette bookworm sprite set + colour nearest-neighbour renderer (G107)

Nine-colour code-defined sprites composed from shared fragments; every state
has 2-4 frames that differ, intervals 0.3-0.7 s, the curious count and the
sleep stage baked into the frames. Renderer draws colour (not template) with
hard edges and caches per state|frame|count|stage|size.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj"
```

---

### Task 2: The `error` state — red eyes when the last Sleep cycle failed

**Files:**
- Modify: `app/CicadaApp/Sources/CicadaApp/MenuBar/BookwormState.swift:6-58` (enum) and `:107-126` (`deriveBookwormState`)
- Modify: `app/CicadaApp/Sources/CicadaApp/MenuBar/BookwormSprites.swift` (`frames(for:)` gains `.error`; two base frames)
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepMood.swift:70-96` (`deriveSleepPageMood`), `:107-124` (`sleepDebtBracketText`), `:130-138` (`sleepDebtBracketColor`)
- Modify: `app/CicadaApp/Tests/CicadaAppTests/BookwormSpriteTests.swift` (`states` gains `.error`), `SleepMoodTests.swift:184-231` (two cases)
- Test: `app/CicadaApp/Tests/CicadaAppTests/BookwormStateTests.swift` (new)

**Interfaces:**
- Produces: `BookwormState.error` (`title` "Error", `detail` "last sleep cycle failed", `caseName` "error"); `deriveBookwormState` precedence `sleeping > error > digesting > hungry > curious > happy` (R6); `deriveSleepPageMood` returns `.error` when `status.error` is non-empty and the cycle is not running; `sleepDebtBracketText(.error, …) == "[ last cycle failed ]"`, `sleepDebtBracketColor(.error) == CicadaTheme.danger` (R9).
- Consumes: `StatusSnapshot.sleep.error` (`BookwormState.swift:71`), `SleepStatusResponse.error` (`Services/APIClient.swift:621`). Every path under `app/CicadaApp/Sources/CicadaApp/` unless written in full.

- [ ] **Step 1: Write the failing tests**

```swift
// app/CicadaApp/Tests/CicadaAppTests/BookwormStateTests.swift
import XCTest
@testable import CicadaApp

/// G107: the menu-bar state machine gains `error` (the last Sleep cycle
/// failed) and the precedence that keeps it honest — a failed cycle shows red
/// eyes at once, not after six seconds of chewing (ruling R6).
final class BookwormStateTests: XCTestCase {

    private func snapshot(
        status: String = "idle", stage: Int = 0, error: String? = nil,
        inboxTotal: Int = 0, lastIngestedAt: String? = nil
    ) -> StatusSnapshot {
        StatusSnapshot(
            sleep: .init(status: status, stage: stage, totalStages: 5, cycleId: nil, error: error),
            inbox: .init(total: inboxTotal, byKind: [:]),
            episodes: .init(unprocessed: 0, lastIngestedAt: lastIngestedAt),
            lastSleepAt: nil, nextSleepAt: nil
        )
    }

    private let now = Date(timeIntervalSince1970: 1_800_000_000)
    private var fresh: String { ISO8601DateFormatter().string(from: now.addingTimeInterval(-3600)) }

    func testErrorOutranksDigestingHungryCuriousAndHappy() {
        let s = snapshot(error: "RuntimeError: boom", inboxTotal: 5)
        XCTAssertEqual(deriveBookwormState(s, justFinishedAt: now.addingTimeInterval(-1), now: now), .error)
        XCTAssertEqual(deriveBookwormState(s, justFinishedAt: nil, now: now), .error)
    }

    func testRunningCycleOutranksError() {
        let s = snapshot(status: "running", stage: 2, error: "stale error from the previous cycle")
        XCTAssertEqual(deriveBookwormState(s, justFinishedAt: nil, now: now), .sleeping(stage: 2))
    }

    func testEmptyErrorStringIsNotAnError() {
        let s = snapshot(error: "", lastIngestedAt: fresh)
        XCTAssertEqual(deriveBookwormState(s, justFinishedAt: nil, now: now), .happy)
    }

    func testExistingPrecedenceIsUnchangedWithoutAnError() {
        XCTAssertEqual(deriveBookwormState(snapshot(status: "running", stage: 9), justFinishedAt: nil, now: now), .sleeping(stage: 5))
        XCTAssertEqual(deriveBookwormState(snapshot(lastIngestedAt: fresh), justFinishedAt: now.addingTimeInterval(-2), now: now), .digesting)
        XCTAssertEqual(deriveBookwormState(snapshot(inboxTotal: 3), justFinishedAt: nil, now: now), .hungry)
        XCTAssertEqual(deriveBookwormState(snapshot(inboxTotal: 3, lastIngestedAt: fresh), justFinishedAt: nil, now: now), .curious(count: 3))
        XCTAssertEqual(deriveBookwormState(snapshot(lastIngestedAt: fresh), justFinishedAt: nil, now: now), .happy)
    }

    func testErrorCopyAndIdentity() {
        XCTAssertEqual(BookwormState.error.title, "Error")
        XCTAssertEqual(BookwormState.error.detail, "last sleep cycle failed")
        XCTAssertEqual(BookwormState.error.caseName, "error")
        XCTAssertEqual(BookwormState.error.spriteKey, "error")
        XCTAssertEqual(BookwormState.error.badgeCount, 0)
    }

    func testErrorFramesHaveRedPupilsAndMove() {
        let (frames, interval) = BookwormSprites.frames(for: .error)
        XCTAssertEqual(frames.count, 2)
        XCTAssertNotEqual(frames[0], frames[1])
        XCTAssertEqual(frames[0][7], "....obaweewabaweewabo...")
        XCTAssertTrue(frames[1].joined().contains("e"), "the glitch frame keeps the red eyes")
        XCTAssertEqual(interval, 0.5, accuracy: 0.001)
    }
}
```

Append to `BookwormSpriteTests.states` the element `.error` (so the 24×24/palette/motion/band assertions cover it), and add to `SleepMoodTests.swift` after `test_bracketText_hungry_withNilDebt` (line 221):

```swift
    func test_bracketText_error() {
        XCTAssertEqual(sleepDebtBracketText(.error, debt: nil), "[ last cycle failed ]")
    }

    func test_bracketColor_errorIsDanger() {
        XCTAssertEqual(sleepDebtBracketColor(.error), CicadaTheme.danger)
    }

    func test_mood_errorWhenLastCycleFailedAndIdle() throws {
        let failed = try status(status: "idle", unprocessedCount: 4, restedPct: 60, error: "RuntimeError: boom")
        XCTAssertEqual(deriveSleepPageMood(status: failed, debt: debtView(unprocessedCount: 4, restedPct: 60), justFinishedAt: nil), .error)
        XCTAssertEqual(deriveSleepPageMood(status: failed, debt: nil, justFinishedAt: Date()), .error, "error beats digesting")
        let running = try status(status: "running", stage: 2, error: "stale error from the previous cycle")
        XCTAssertEqual(deriveSleepPageMood(status: running, debt: nil, justFinishedAt: nil), .sleeping(stage: 2), "a running cycle outranks a stale error")
    }
```

The `error:` argument does not exist on the fixture yet. `SleepStatusResponse` (`Services/APIClient.swift:616`) has a hand-written `init(from:)` (the "absent on an older backend" defaults), so fixtures are JSON strings, never `JSONEncoder` round-trips — extend the existing helper at `SleepMoodTests.swift:13-31` in place:

1. Add `error: String? = nil` as the last parameter of `private func status(...)` (after `progressPct: Int? = nil`).
2. Next to `let progressJSON = …` (line 21) add `let errorJSON = error.map { "\"\($0)\"" } ?? "null"`.
3. In the JSON literal (line 23) change `"error":null,` to `"error":\(errorJSON),`.

Every existing call site passes no `error:`, so nothing else changes.

- [ ] **Step 2: Run to verify failure**

Run: `cd <worktree>/app/CicadaApp && swift build --build-tests 2>&1 | grep -E "error:" | head`
Expected: `type 'BookwormState' has no member 'error'`.

- [ ] **Step 3: Add the case**

`BookwormState.swift` — after `case hungry` (line 19) add:

```swift
    /// The last Sleep cycle failed (`/status.sleep.error` is set). Red pupils
    /// and a glitch frame. Outranks everything but a running cycle (R6): the
    /// Store stamps `justFinishedAt` on ANY running→idle edge, so without
    /// this order a failed cycle would chew for six seconds first. Clears when
    /// the backend clears the error, i.e. when the next cycle starts.
    case error
```

Add `case .error: "Error"` to `title`, `case .error: "last sleep cycle failed"` to `detail`, `case .error: "error"` to `caseName`. In `deriveBookwormState`, after the `running` check (line 117) and before `justFinishedAt`:

```swift
    if let err = s.sleep.error, !err.isEmpty {
        return .error
    }
```

Update the doc comment's precedence line to `sleeping > error > digesting > hungry > curious > happy > awake`.

- [ ] **Step 4: Frames**

In `BookwormSprites.swift`, next to `hungryBase`:

```swift
    private static let errorBase: PixelGrid = compose(eyes(pupil: "e"), mouthNeutral)
    /// Static: glasses nudged right, body nudged left — a one-cell tear.
    private static let errorGlitch: PixelGrid = shiftRows(shiftRows(errorBase, 5..<10, dx: 1), 13..<23, dx: -1)
```

and in `frames(for:)`:

```swift
        case .error:
            return ([errorBase, errorGlitch], 0.5)
```

- [ ] **Step 5: Sleep page mood + bracket**

`SleepMood.swift` `deriveSleepPageMood` — after the `running` branch (line 79):

```swift
    if let err = status.error, !err.isEmpty {
        return .error   // R6: the failure is the news, not the six-second chew
    }
```

Update its doc-comment precedence line the same way. `sleepDebtBracketText` gains `case .error: return "[ last cycle failed ]"`; `sleepDebtBracketColor` gains `case .error: CicadaTheme.danger` and its doc comment gets one sentence: "`error` is the one state allowed `.danger` — a failed cycle is an alarm, a backlog is not."

- [ ] **Step 6: Build, test, commit**

Run: `cd <worktree>/app/CicadaApp && swift build 2>&1 | tail -5 && swift test 2>&1 | tail -20`
Expected: 0 failures. Every exhaustive `switch` over `BookwormState` is in the files this task edits (`BookwormState.swift` ×3, `BookwormSprites.swift`, `SleepMood.swift` ×2 — verified by `grep -rn "case \.hungry" app/CicadaApp/Sources`), so nothing else needs a case.

```bash
cd <worktree>/ && git add app/CicadaApp/Sources/CicadaApp/MenuBar/BookwormState.swift app/CicadaApp/Sources/CicadaApp/MenuBar/BookwormSprites.swift app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepMood.swift app/CicadaApp/Tests/CicadaAppTests/BookwormStateTests.swift app/CicadaApp/Tests/CicadaAppTests/BookwormSpriteTests.swift app/CicadaApp/Tests/CicadaAppTests/SleepMoodTests.swift && git commit -m "feat(app): bookworm error state — red eyes while the last Sleep cycle's error stands (G107)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj"
```

---

### Task 3: Menu bar — exactly one animated item, count baked in, no title

**Files:**
- Modify: `app/CicadaApp/Sources/CicadaApp/MenuBarManager.swift:13-21` (drop `imageCache`), `:39-42` (`setup`), `:119-143` (`transition`/`tick`), `:145-191` (`renderCurrentFrame`), `:342-366` (debug harness)
- Modify: `app/CicadaApp/Sources/CicadaApp/MenuBar/BookwormRenderer.swift` (delete the `overlays:` parameter — its last caller goes away here)
- Test: `app/CicadaApp/Tests/CicadaAppTests/BookwormRendererTests.swift` (one added case), `app/CicadaApp/Tests/CicadaAppTests/BookwormStateTests.swift` (one added case)

**Interfaces:**
- Produces: `MenuBarManager.spritePointSize: CGFloat = 18` (R3); `nonisolated static func MenuBarManager.animates(_ state: BookwormState, reduceMotion: Bool) -> Bool` (pure: `!reduceMotion && frames.count > 1`).
- Removes: `button.title` writes (lines 184–190), `BookwormSprites.badgeOverlay`/`stageDots` overlay calls in the manager, the manager's own cache.
- Unchanged: `rebuildMenu`, quick actions, `apply`/`applySleep`/`noteCycleFinished`, the `StatusSnapshot → BookwormState` mapping (Task 2 already extended it).

- [ ] **Step 1: Write the failing tests**

Append to `BookwormStateTests`:

```swift
    func testMenuBarAnimatesEveryStateUnlessReduceMotion() {
        for state in BookwormSpriteTests.states {
            XCTAssertTrue(MenuBarManager.animates(state, reduceMotion: false), state.caseName)
            XCTAssertFalse(MenuBarManager.animates(state, reduceMotion: true), state.caseName)
        }
        XCTAssertEqual(MenuBarManager.spritePointSize, 18)
    }
```

Append to `BookwormRendererTests`:

```swift
    func testMenuBarSizedFramesAreCachedPerCountAndStage() {
        let a = BookwormRenderer.cachedImage(state: .curious(count: 3), frameIndex: 0, pointSize: MenuBarManager.spritePointSize)
        let b = BookwormRenderer.cachedImage(state: .curious(count: 4), frameIndex: 0, pointSize: MenuBarManager.spritePointSize)
        XCTAssertFalse(a === b, "a count change must re-render — the count is in the pixels")
        XCTAssertEqual(a.size, NSSize(width: 18, height: 18))
        XCTAssertFalse(a.isTemplate)
    }
```

- [ ] **Step 2: Run to verify failure**

Run: `cd <worktree>/app/CicadaApp && swift build --build-tests 2>&1 | grep -E "error:" | head`
Expected: `type 'MenuBarManager' has no member 'animates'` / `'spritePointSize'`.

- [ ] **Step 3: Rewrite the animation section of `MenuBarManager`**

1. Lines 20–21: delete the `imageCache` declaration and its comment (R5 — the renderer owns the cache).
2. Add, right after `private(set) var state: BookwormState = .awake` (line 11):

```swift
    /// 24 cells at 0.75 pt (ruling R3): the standard status-item image height,
    /// and what the previous template glyph used. A 24 pt image would fill the
    /// whole menu bar and clip on a 22 pt status button.
    nonisolated static let spritePointSize: CGFloat = 18

    /// Every state has ≥ 2 frames (BookwormSpriteTests), so the frame timer
    /// runs for every state — except under Reduce Motion, which holds frame 0
    /// (ruling R7). Pure so the rule is testable without an `NSStatusItem`.
    nonisolated static func animates(_ state: BookwormState, reduceMotion: Bool) -> Bool {
        !reduceMotion && BookwormSprites.frames(for: state).frames.count > 1
    }

    private var reduceMotion: Bool {
        NSWorkspace.shared.accessibilityDisplayShouldReduceMotion
    }
```

3. `setup(...)` (lines 39–42): change `imagePosition = .imageLeading` to `.imageOnly` and, after `rebuildMenu()`, add:

```swift
        // Re-evaluate the timer when the user toggles Reduce Motion (R7).
        // NOT `NotificationCenter.default`: AppKit posts this one to the
        // workspace's own centre (SDK `NSAccessibility.h`: "Notification posted
        // to the NSWorkspace notification center"), so an observer on the
        // default centre never fires. The token is kept (the block-based API
        // is not `@discardableResult`) for the manager's app-long lifetime.
        reduceMotionObserver = NSWorkspace.shared.notificationCenter.addObserver(
            forName: NSWorkspace.accessibilityDisplayOptionsDidChangeNotification,
            object: nil, queue: .main
        ) { [weak self] _ in
            MainActor.assumeIsolated { guard let self else { return }; self.transition(to: self.state) }
        }
```

   and, beside `private var frameTimer: Timer?` (line 14), declare `private var reduceMotionObserver: NSObjectProtocol?`.

4. `transition(to:)` (lines 119–136): replace the body from `let (frames, interval)` to the end with:

```swift
        let (_, interval) = BookwormSprites.frames(for: newState)
        // All states are multi-frame now (G107: "always moving"); the only
        // reason not to tick is Reduce Motion.
        guard Self.animates(newState, reduceMotion: reduceMotion) else { return }
        let timer = Timer.scheduledTimer(withTimeInterval: interval, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated { self?.tick() }
        }
        timer.tolerance = interval * 0.3   // let the OS coalesce wakeups -> cheaper
        RunLoop.main.add(timer, forMode: .common)
        frameTimer = timer
```

5. `renderCurrentFrame()` (lines 145–191): replace the whole body with:

```swift
        guard let button = statusItem?.button else { return }
        let (frames, _) = BookwormSprites.frames(for: state)
        guard !frames.isEmpty else { return }
        let idx = frameIndex % frames.count
        // ONE image, count and stage already in the pixels (R2); a tick is a
        // cache hit (R5). No `title`: the number used to be drawn twice —
        // once as pixels, once as text — and the owner asked for one worm.
        button.image = BookwormRenderer.cachedImage(state: state, frameIndex: idx, pointSize: Self.spritePointSize)
        button.imagePosition = .imageOnly
        button.title = ""
```

   (`button.title = ""` is set once so a build that previously wrote `" 47"` cannot leave stale text — `NSStatusBarButton` keeps its last title across image swaps.)

6. Debug harness (lines 342–366): replace the `map` body with:

```swift
        return states.map { st in
            (st.caseName, BookwormRenderer.image(grid: BookwormSprites.frames(for: st).frames[0], pointSize: spritePointSize))
        }
```
   and add `.error` to its `states` array.

7. Update the class doc comment (lines 4–7) with one sentence: "The status item is a single colour sprite (G107) — no text title; the inbox count is drawn into the frame."

- [ ] **Step 4: Drop `overlays:` from the renderer**

In `BookwormRenderer.image`, remove the `overlays: [PixelGrid] = []` parameter and the `let merged = overlays.reduce…` line (use `grid` directly), and delete the sentence in its doc comment about `MenuBarManager`'s pre-Task-3 call sites. Verify no caller remains: `cd <worktree>/ && grep -rn "overlays:" app/CicadaApp/Sources` → no output.

- [ ] **Step 5: Build, test, commit**

Run: `cd <worktree>/app/CicadaApp && swift build 2>&1 | tail -5 && swift test 2>&1 | tail -20`
Expected: 0 failures. Also: `grep -n "button.title" app/CicadaApp/Sources/CicadaApp/MenuBarManager.swift` shows exactly the one `button.title = ""` line; `grep -n "badgeOverlay\|stageDots" app/CicadaApp/Sources/CicadaApp/MenuBarManager.swift` shows nothing.

```bash
cd <worktree>/ && git add app/CicadaApp/Sources/CicadaApp/MenuBarManager.swift app/CicadaApp/Sources/CicadaApp/MenuBar/BookwormRenderer.swift app/CicadaApp/Tests/CicadaAppTests/BookwormRendererTests.swift app/CicadaApp/Tests/CicadaAppTests/BookwormStateTests.swift && git commit -m "feat(app): menu bar shows one animated bookworm with the count in the sprite — drop the duplicate text badge (G107)

Timer runs for every state (all are multi-frame), holds frame 0 under Reduce
Motion; frames come from the renderer's cache keyed state|frame|count|stage|size.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj"
```

---

### Task 4: Page mascot — `BookwormView` on a `TimelineView`, caption, Reduce Motion, five surfaces

**Files:**
- Rewrite: `app/CicadaApp/Sources/CicadaApp/Views/Common/BookwormView.swift` (whole file)
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepView.swift:222-246` (`moodCard` + its doc comment)
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Feed/FeedView.swift:204-207`, `Views/Common/UploadOverlay.swift` (the `BookwormView(...)` call from Task 1 Step 6); verify only: `Views/Connect/ConnectView.swift` (48 from Task 1) and `Views/Inbox/InboxListView.swift` (96 from Task 1)
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepMood.swift:98-106` (doc comment: no longer "interim")
- Test: `app/CicadaApp/Tests/CicadaAppTests/BookwormViewTests.swift` (new)

**Interfaces:**
- Produces: `BookwormView(state:pointSize:caption:captionFont:captionColor:alignment:)`; `nonisolated static func BookwormView.frameIndex(at:interval:count:reduceMotion:) -> Int` (pure); `static let BookwormView.timelineOrigin = Date(timeIntervalSinceReferenceDate: 0)`.
- Consumes: `BookwormRenderer.cachedImage` (R5), `@Environment(\.accessibilityReduceMotion)` (R7), `sleepDebtBracketText`/`sleepDebtBracketColor` (R9).

- [ ] **Step 1: Write the failing tests**

```swift
// app/CicadaApp/Tests/CicadaAppTests/BookwormViewTests.swift
import XCTest
@testable import CicadaApp

/// G107: the page mascot's frame is a pure function of the clock, so a
/// `TimelineView` tick needs no stored state, two mascots on screen stay in
/// step, and Reduce Motion is a single early return (ruling R7).
final class BookwormViewTests: XCTestCase {

    private func at(_ seconds: TimeInterval) -> Date { Date(timeIntervalSinceReferenceDate: seconds) }

    func testFrameAdvancesOncePerIntervalAndWraps() {
        XCTAssertEqual(BookwormView.frameIndex(at: at(0), interval: 0.5, count: 4, reduceMotion: false), 0)
        XCTAssertEqual(BookwormView.frameIndex(at: at(0.49), interval: 0.5, count: 4, reduceMotion: false), 0)
        XCTAssertEqual(BookwormView.frameIndex(at: at(0.5), interval: 0.5, count: 4, reduceMotion: false), 1)
        XCTAssertEqual(BookwormView.frameIndex(at: at(1.75), interval: 0.5, count: 4, reduceMotion: false), 3)
        XCTAssertEqual(BookwormView.frameIndex(at: at(2.0), interval: 0.5, count: 4, reduceMotion: false), 0)
    }

    func testReduceMotionHoldsFrameZero() {
        XCTAssertEqual(BookwormView.frameIndex(at: at(1.75), interval: 0.5, count: 4, reduceMotion: true), 0)
    }

    func testDegenerateInputsNeverCrash() {
        XCTAssertEqual(BookwormView.frameIndex(at: at(3), interval: 0.5, count: 0, reduceMotion: false), 0)
        XCTAssertEqual(BookwormView.frameIndex(at: at(3), interval: 0, count: 4, reduceMotion: false), 0)
        XCTAssertEqual(BookwormView.frameIndex(at: at(-1.2), interval: 0.5, count: 4, reduceMotion: false), 1)
    }

    /// Page sizes are multiples of 24 so every sprite cell is an integer
    /// number of points (ruling R3) — the sizes the call sites use.
    func testPageSizesAreWholeCells() {
        for size in [48, 96, 120] as [CGFloat] {
            XCTAssertEqual(size.truncatingRemainder(dividingBy: 24), 0, "\(size)")
        }
    }
}
```

- [ ] **Step 2: Run to verify failure**

Run: `cd <worktree>/app/CicadaApp && swift build --build-tests 2>&1 | grep -E "error:" | head`
Expected: `type 'BookwormView' has no member 'frameIndex'`.

- [ ] **Step 3: Rewrite `BookwormView.swift`**

```swift
import SwiftUI

/// The in-app bookworm (G107): the same 24×24 colour frames the menu bar
/// shows, at page size, always moving. Frame selection is a pure function of
/// the clock (`frameIndex(at:…)`) driven by a `TimelineView`, so there is no
/// `Timer` to leak, no `@State` to reset on a state change, and two worms on
/// one screen tick in step. Reduce Motion holds frame 0 (ruling R7).
///
/// `caption` is the optional bracket line under the worm — the Sleep page's
/// `[ 47 episodes behind ]` text survives there as a caption rather than as
/// the mascot (the 2026-09-02 ask that superseded G107's interim ruling).
struct BookwormView: View {
    let state: BookwormState
    /// Multiples of 24 keep cells integer (R3): 48 (inline), 96 (empty states), 120 (Sleep).
    var pointSize: CGFloat = 96
    var caption: String? = nil
    var captionFont: Font = .system(size: 13, weight: .semibold, design: .monospaced)
    var captionColor: Color = CicadaTheme.textTertiary
    var alignment: HorizontalAlignment = .center

    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    /// A fixed origin so the schedule's phase never depends on when a
    /// particular view appeared.
    static let timelineOrigin = Date(timeIntervalSinceReferenceDate: 0)

    /// Which frame to show at `date`. Pure; tested. Negative or degenerate
    /// inputs clamp to frame 0 rather than trapping.
    static func frameIndex(at date: Date, interval: TimeInterval, count: Int, reduceMotion: Bool) -> Int {
        guard count > 0, interval > 0, !reduceMotion else { return 0 }
        let ticks = Int((date.timeIntervalSinceReferenceDate / interval).rounded(.down))
        return ((ticks % count) + count) % count
    }

    var body: some View {
        let (frames, interval) = BookwormSprites.frames(for: state)
        VStack(alignment: alignment, spacing: CicadaTheme.spacingSM) {
            TimelineView(.periodic(from: Self.timelineOrigin, by: interval)) { context in
                let idx = Self.frameIndex(at: context.date, interval: interval, count: frames.count, reduceMotion: reduceMotion)
                Image(nsImage: BookwormRenderer.cachedImage(state: state, frameIndex: idx, pointSize: pointSize))
                    .interpolation(.none)
                    .frame(width: pointSize, height: pointSize)
                    .accessibilityLabel("\(state.title) — \(state.detail)")
            }
            if let caption {
                Text(caption)
                    .font(captionFont)
                    .foregroundStyle(captionColor)
            }
        }
    }
}
```

- [ ] **Step 4: Sleep page — mascot above the bracket line**

`SleepView.swift` `moodCard` (lines 232–246): replace the `Text(sleepDebtBracketText(…))…` two-modifier block with:

```swift
            BookwormView(
                state: mood,
                pointSize: 120,
                caption: sleepDebtBracketText(mood, debt: debt),
                captionFont: .system(size: 24, weight: .semibold, design: .monospaced),
                captionColor: sleepDebtBracketColor(mood),
                alignment: .leading
            )
```

Rewrite the doc comment above it (lines 224–231): the card is now the mascot (G107 art, 120 pt, `deriveSleepPageMood`) with the bracket status line as its caption, plus the Rested % reading — keep the SSE-first / REST-fallback sentence verbatim.

`SleepMood.swift:98-106`: retitle the MARK to `// MARK: - Bracket caption (G107: rendered under the page mascot)` and replace the paragraph so it says the bracket text is the caption `BookwormView` shows beneath the 24×24 colour sprite on the Sleep page; it was the whole mascot from 2026-09-01 until the art shipped on 2026-09-02, and it still reuses the SAME `BookwormState` `deriveSleepPageMood` produces.

- [ ] **Step 5: The other surfaces**

1. `FeedView.swift:204-207`: `BookwormView(state: .awake, pointSize: 96)`; the comment above it: "The animated mascot greets the empty ingestion area — the same colour sprites as the menu bar, the Inbox 'all caught up' worm and the upload overlay."
2. `ConnectView.swift`: already `BookwormView(state: .happy, pointSize: 48)` with no `.frame` from Task 1 — verify, no edit.
3. `UploadOverlay.swift` (the Task 1 call): `BookwormView(state: mascotState, pointSize: 96)` and change the `.frame(height: 72)` that follows it to `.frame(height: 96)`.
4. `InboxListView.swift`: already `BookwormView(state: .happy, pointSize: 96)` — verify, no edit.

- [ ] **Step 6: Build, test, commit**

Run: `cd <worktree>/app/CicadaApp && swift build 2>&1 | tail -5 && swift test 2>&1 | tail -20`
Expected: 0 failures. Then `cd <worktree>/ && grep -rn "BookwormView(" app/CicadaApp/Sources | grep -v "struct BookwormView"` → exactly five call sites (Feed, Connect, UploadOverlay, InboxList, SleepView), every `pointSize` one of 48/96/120, and `grep -rn "Timer" app/CicadaApp/Sources/CicadaApp/Views/Common/BookwormView.swift` → no output.

```bash
cd <worktree>/ && git add app/CicadaApp/Sources/CicadaApp/Views/Common/BookwormView.swift app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepView.swift app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepMood.swift app/CicadaApp/Sources/CicadaApp/Views/Feed/FeedView.swift app/CicadaApp/Sources/CicadaApp/Views/Common/UploadOverlay.swift app/CicadaApp/Tests/CicadaAppTests/BookwormViewTests.swift && git commit -m "feat(app): page mascot on a TimelineView — Sleep page gets the worm above its bracket caption; Feed/Connect/Import/Inbox at whole-cell sizes (G107)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj"
```

---

### Task 5: Docs — G107 row, CLAUDE.md, TODO.md

**Files:**
- Modify: `docs/goals/memory-evolution.md:669` (the G107 row — one 4 KB line; edit with a targeted `python - <<'PY'` string replace, never by retyping)
- Modify: `CLAUDE.md:545` (the "Sync engine" paragraph — one sentence appended)
- Modify: `docs/goals/TODO.md:162` (`_Last synced`), `:181-184` (Shipped → App line; `G15 avatars` closes it on 184), `:297-299` (Wave C item 12a), and the "Where things stand" (line 7) / "Pick up here" (line 114) header sections

**Interfaces:** none — prose only. Everything asserted below must be true of the branch as committed by Tasks 1–4; if a name changed, follow the code.

- [ ] **Step 1: Backlog row**

```bash
cd <worktree>/ && api/.venv/bin/python - <<'PY'
from pathlib import Path
p = Path("docs/goals/memory-evolution.md")
s = p.read_text()
old_tail = "and **G54** (an onboarding companion has the same asset need). | 🔲 |"
assert s.count(old_tail) == 1, "G107 row tail not found exactly once"
new_tail = ("and **G54** (an onboarding companion has the same asset need). "
            "**Interim ruling superseded 2026-09-02 (Rodrigo: \"work on doing a pixel bookworm mascot with animations so in every "
            "state it's always moving … I want just one Tamagotchi-like avatar of the bookworm that moves and shows the status\").** "
            "**Shipped 2026-09-02 (`feat/mascot`, PR #TBD):** one code-defined 24×24 palette sprite set (`MenuBar/BookwormSprites.swift`, "
            "nine colours — outline, body, belly, eye, blush, accent, zZ, ?/badge, error red — composed from shared head/glasses/mouth/body "
            "fragments so the silhouette is identical across moods); every state ≥ 2 frames that differ (awake bob+blink, sleeping zZ drift + "
            "chest rise, digesting chews a book, curious tilts with a pulsing ? and the count as a pixel numeral in a pill, hungry droops with "
            "a sweat drop, happy bounces with sparkles, and a new **`error`** state — red pupils + glitch frame — for `sleep.error != nil`, "
            "outranking everything but a running cycle); intervals 0.3–0.7 s. `BookwormRenderer` draws COLOUR (not template) nearest-neighbour "
            "with one cache keyed state|frame|count|stage|size. The **menu bar is one animated item** — the `button.title` text badge that "
            "duplicated the count is gone, the count lives in the sprite, the timer runs for every state, Reduce Motion holds frame 0. "
            "`BookwormView` renders the same frames on a `TimelineView` at whole-cell sizes (48/96/120) on Feed, Connect, Inbox, the import "
            "overlay and the Sleep page, where the bracket status line stays as the **caption** under a 120 pt worm. Not built, on purpose: "
            "sound, drag, feeding mechanics, any toggle beyond Reduce Motion. Per-cycle time estimates stay deferred on G74's trigger. | ✅ |")
p.write_text(s.replace(old_tail, new_tail))
print("ok")
PY
```

- [ ] **Step 2: CLAUDE.md**

At the end of the "Sync engine" paragraph (`CLAUDE.md:545`, after "…before the user commits to an import."), append this one sentence:

"The bookworm mascot (G107) is one code-defined 24×24 palette sprite set (`MenuBar/BookwormSprites.swift`, nine colours, every state ≥ 2 frames so it is always moving, `error` for a failed cycle) rendered nearest-neighbour in colour by `BookwormRenderer` — the menu bar shows exactly one animated item with the inbox count baked into the sprite, and the same frames drive `BookwormView` on Feed, Connect, Inbox, the import overlay and the Sleep page (where the bracket status line is the caption), holding frame 0 under Reduce Motion."

- [ ] **Step 3: TODO.md**

1. Line 162: `_Last synced: 2026-09-02 (PRs #21–#34 merged; G107 pixel mascot on feat/mascot, PR #TBD; inbox redesign folded as G115/G116)._`
2. Shipped → **App** line (181–184): append ` · G107 pixel mascot + single menu-bar Tamagotchi` after `G15 avatars` (end of line 184).
3. Delete Wave C item `12a. **G107** …` (the three lines 297–299). Leave `12c` as is (the list uses explicit labels).
4. `## Where things stand` (line 7 — retitle its date to `(2026-09-02)`): add one short paragraph directly after the G109 phase-1 paragraph, i.e. after the line ending `that is the "explosion on return").` (line 54) and before `**Live environment (verified):**`: "**G107 pixel mascot (2026-09-02, `feat/mascot`, PR #TBD).** The bracket-text interim is superseded: a nine-colour 24×24 sprite set, every state always moving, `error` state added, the menu bar shows one animated worm with the count in the sprite (no more text badge), and `BookwormView` on a `TimelineView` at whole-cell sizes on five surfaces. `swift test` green (four new test files, 31 new cases); the visual pass — menu bar light/dark, Sleep page, Reduce Motion — is the install step, not yet done at the time of this commit." A handoff that claims an eyeball nobody made is the stale header CLAUDE.md warns about; the orchestrator rewords it after the install.
5. `## Pick up here`: no new numbered item — the work is shipped; add "(G107 shipped 2026-09-02 — see Where things stand)" to the end of the first paragraph.

- [ ] **Step 4: Verify nothing stale remains**

Run: `cd <worktree>/ && grep -n "interim" app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepMood.swift app/CicadaApp/Sources/CicadaApp/Views/Sleep/SleepView.swift; grep -n "16×16\|16x16\|template" app/CicadaApp/Sources/CicadaApp/Views/Common/BookwormView.swift app/CicadaApp/Sources/CicadaApp/MenuBar/BookwormSprites.swift`
Expected: no output from the first grep; the second may match only the renderer's "not template" sentence quoted in `BookwormSprites`' header, if any.

- [ ] **Step 5: Commit**

```bash
cd <worktree>/ && git add CLAUDE.md docs/goals/memory-evolution.md docs/goals/TODO.md && git commit -m "docs(G107): pixel mascot shipped — bracket-text ruling superseded 2026-09-02; CLAUDE.md companion-app sentence; TODO handoff

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj"
```

---

## Not in scope

- Sound, drag/throw interactions, feeding mechanics, a settings toggle beyond Reduce Motion (the brief's exclusions).
- A frame cache for the string grids (R5: images are cached; grids are microseconds).
- Per-cycle time estimates on the Sleep page (G107's own deferral, on G74's trigger).
- Any change to `Store`, `SleepViewModel`, the API, the MCP server, or the `StatusSnapshot` wire shape — `sleep.error` already crosses the wire.
- Menu-bar dropdown contents and quick actions (`MenuBarManager.rebuildMenu`, lines 195–245) — preserved verbatim.
- The onboarding companion (G54) and the output packet (G77) — they can reuse `BookwormView` later; nothing here anticipates them.

## Verification the orchestrator runs at the end

1. `cd <worktree>/app/CicadaApp && swift build 2>&1 | tail -5 && swift test 2>&1 | tail -20` → build OK, `Executed 561 tests, with 0 failures` (530 baseline + 31 new: 11 sprite, 6 renderer, 7 state, 4 view, 3 SleepMood).
2. `cd <worktree>/ && git log --oneline dev..feat/mascot` → five commits, in the order of Tasks 1–5; `git status --porcelain` shows nothing staged or modified except untracked scratch (never `api/.venv`, never `*-report.md`).
3. `grep -n "button.title" app/CicadaApp/Sources/CicadaApp/MenuBarManager.swift` → one line, `button.title = ""`.
4. Then the orchestrator (not this branch's tasks) runs `make dev` and looks at: the menu bar — one colour worm, moving in every state, a two-digit count inside an amber pill when the inbox is non-empty, no text beside it, legible on both light and dark menu bars; the Sleep page — the 120 pt worm above the bracket line, both changing together when a cycle runs; Feed empty state / Connect intro / Inbox empty / import overlay — crisp pixels, no blur; System Settings → Accessibility → Reduce Motion on → every worm holds still.

## Self-review notes (for the executor, not a task)

- Task 1 must land the `BookwormView`/`UploadOverlay`/`InboxListView` edits in the SAME commit as the renderer, or a colour image drawn in `.template` mode ships as a flat tinted silhouette.
- Task 2 adds a case to an enum with six exhaustive `switch`es across three files; the compiler lists every one — do not add a `default:`.
- `NSStatusBarButton` remembers its last `title`; Task 3's `button.title = ""` is deliberate belt-and-braces, not dead code.
- `BookwormView.frameIndex` uses `timeIntervalSinceReferenceDate`; the `TimelineView` schedule uses the same origin, so the frame shown at a tick is the frame the pure function names for that tick.
- No task reads or writes `memory/`; every test fixture is synthetic (`StatusSnapshot` values, JSON literals).
