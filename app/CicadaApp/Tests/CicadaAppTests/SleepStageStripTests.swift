import XCTest
@testable import CicadaApp

/// G125 v3 Task 5 — the stage strip (spec R-A8, plan P15/P16).
///
/// The strip replaced `moodDetailLine`'s `"Stage N of 5"` text and its bare
/// `ProgressView`, so what used to be one sentence is now the page's live
/// instrument. Three contracts are worth a test and none of them needs a view:
///
/// 1. **One array (P16).** The strip and the `?` popover read the same five
///    stages. `HowSleepWorksContent` already declares itself the one prose
///    source for the pipeline; a second hand-typed list in the strip would be
///    a fourth naming of it.
/// 2. **Only Read carries a fill (P15).** Stages 2–5 have no per-episode unit
///    — `sleep_cycle.progress_pct` returns `None` past stage 0 — so giving
///    them a fraction would be inventing one. And a cancel or a failure
///    **freezes** the strip where it stopped; it never resets to all-pending,
///    which would erase the work the cycle actually did.
/// 3. **Reduce Motion holds the terminal frame (R-A13)**, and the breathing
///    period is a named constant so the ≤ 1.2 s budget is assertable rather
///    than inferred from a magic number inside a view.
final class SleepStageStripTests: XCTestCase {

    // MARK: - One array, five stages

    func test_sleepStages_areTheFiveShortLabelsTheStripDraws() {
        XCTAssertEqual(SleepStages.all.count, 5)
        XCTAssertEqual(SleepStages.all.map(\.number), [1, 2, 3, 4, 5])
        XCTAssertEqual(SleepStages.all.map(\.shortLabel),
                       ["Read", "Sort", "Decide", "Notice", "File"])
        // Ids are stable and unique — they are cache-key and ForEach identity.
        XCTAssertEqual(Set(SleepStages.all.map(\.id)).count, 5)
    }

    /// **The popover cannot drift (P16).** `HowSleepWorksContent`'s rows are a
    /// `private static let` and a test cannot read them, so the pin is written
    /// against `SleepStages.all` with the five titles, the five detail strings
    /// and the five SF Symbols typed here as literals, character-for-character
    /// from the popover as it shipped. Task 5 only HOISTED that copy; if a
    /// later edit rewords a stage, this fails rather than silently giving the
    /// pipeline a fourth description.
    func test_theStageCopyIsTheSamePopoverCopy_byteForByte() {
        XCTAssertEqual(SleepStages.all.map(\.title), [
            "Stage 1 · Read",
            "Stage 2 · Sort",
            "Stage 3 · Decide",
            "Stage 4 · Notice",
            "Stage 5 · File",
        ])
        XCTAssertEqual(SleepStages.all.map(\.detail), [
            "Each episode is read once for people, projects, tools and ideas.",
            "New mentions are matched against what you already have.",
            "Contradictions become questions in your Inbox; old beliefs fade.",
            "Habits that recur become skills.",
            "Everything is written to the graph and committed with its provenance.",
        ])
        XCTAssertEqual(SleepStages.all.map(\.symbol), [
            "book", "arrow.triangle.merge", "questionmark.circle", "sparkles", "checkmark.seal",
        ])
    }

    // MARK: - stageStripState

    /// `status.stage` is the number of COMPLETED stages (`sleep_cycle.py` sets
    /// it to 1 only after Stage 1 returns), so a running cycle at `stage: 0`
    /// is Stage 1 in flight.
    func test_running_fillsOnlyTheReadPip() {
        let pips = stageStripState(stage: 0, isRunning: true, cancelled: false, error: false,
                                   read: 138, total: 203)
        XCTAssertEqual(pips.count, 5)
        XCTAssertEqual(pips, [.active(fill: 138.0 / 203.0), .pending, .pending, .pending, .pending])
    }

    /// P15: stages 2–5 have no per-episode unit, so the active pip past Read
    /// carries `nil` — never a fabricated fraction, and never Read's own.
    func test_running_pastStageOne_hasNoFillAtAll() {
        let pips = stageStripState(stage: 2, isRunning: true, cancelled: false, error: false,
                                   read: 138, total: 203)
        XCTAssertEqual(pips.count, 5)
        XCTAssertEqual(pips, [.done, .done, .active(fill: nil), .pending, .pending])
    }

    /// A running Stage 1 with no episode totals yet (the very first ticks of a
    /// cycle) draws the pip active but empty rather than dividing by zero.
    func test_running_withNoTotals_drawsAnUnfilledActivePip() {
        let pips = stageStripState(stage: 0, isRunning: true, cancelled: false, error: false,
                                   read: 0, total: 0)
        XCTAssertEqual(pips, [.active(fill: nil), .pending, .pending, .pending, .pending])
    }

    func test_idle_afterACompleteCycle_isFiveDone() {
        XCTAssertEqual(
            stageStripState(stage: 5, isRunning: false, cancelled: false, error: false,
                            read: 0, total: 0),
            [.done, .done, .done, .done, .done])
    }

    func test_idle_beforeAnythingRan_isFivePending() {
        XCTAssertEqual(
            stageStripState(stage: 0, isRunning: false, cancelled: false, error: false,
                            read: 0, total: 0),
            [.pending, .pending, .pending, .pending, .pending])
    }

    /// P15 — a cancel FREEZES the strip at the stage it reached. The two
    /// stages that really ran keep their ✓; the rest are skipped, not pending,
    /// because nothing is coming to run them.
    func test_cancelled_freezesWhereItStopped() {
        XCTAssertEqual(
            stageStripState(stage: 2, isRunning: false, cancelled: true, error: false,
                            read: 0, total: 0),
            [.done, .done, .skipped, .skipped, .skipped])
    }

    /// A failure marks the stage it died IN, not the one after it: `stage: 1`
    /// means Stage 1 finished and Stage 2 was running when the cycle failed.
    func test_error_marksTheStageItDiedIn() {
        XCTAssertEqual(
            stageStripState(stage: 1, isRunning: false, cancelled: false, error: true,
                            read: 0, total: 0),
            [.done, .failed, .skipped, .skipped, .skipped])
    }

    /// A cycle that failed after Stage 5 already wrote everything has no pip
    /// left to fail on — the strip must stay in range rather than trapping.
    func test_error_afterTheLastStage_staysInRange() {
        XCTAssertEqual(
            stageStripState(stage: 5, isRunning: false, cancelled: false, error: true,
                            read: 0, total: 0),
            [.done, .done, .done, .done, .done])
    }

    /// Every state is describable in words — the pips are not the only readout
    /// (R-A15: every art bit has a text twin, here for VoiceOver).
    func test_everyPipStateHasAWord() {
        XCTAssertEqual(StagePip.done.accessibilityWord, "done")
        XCTAssertEqual(StagePip.active(fill: nil).accessibilityWord, "in progress")
        XCTAssertEqual(StagePip.active(fill: 0.5).accessibilityWord, "in progress")
        XCTAssertEqual(StagePip.pending.accessibilityWord, "not started")
        XCTAssertEqual(StagePip.skipped.accessibilityWord, "not reached")
        XCTAssertEqual(StagePip.failed.accessibilityWord, "failed")
    }

    // MARK: - The caught-up worm

    /// R-A8's right end: the `.happy` worm shows only when there is nothing to
    /// count — the strip's own "and there is nothing waiting" mark. Any state
    /// with a numeral keeps the numeral instead.
    func test_theCaughtUpWorm_showsOnlyWhenHappyAndCountless() {
        XCTAssertTrue(stageStripShowsCaughtUpWorm(mood: .happy, debt: nil))
        XCTAssertFalse(stageStripShowsCaughtUpWorm(mood: .reading, debt: nil))
        XCTAssertFalse(stageStripShowsCaughtUpWorm(mood: .sleeping(stage: 2), debt: nil))
        XCTAssertFalse(stageStripShowsCaughtUpWorm(mood: .curious(count: 3), debt: nil))
        XCTAssertFalse(stageStripShowsCaughtUpWorm(mood: .error, debt: nil))
    }

    // MARK: - The motion budget (R-A13)

    func test_pulsePeriod_isInsideTheMotionBudget() {
        XCTAssertLessThanOrEqual(SleepStages.pulsePeriod, 1.2)
        XCTAssertGreaterThan(SleepStages.pulsePeriod, 0)
    }

    /// Reduce Motion holds the terminal frame — one constant value, not a
    /// slower breath (R-A13).
    func test_reduceMotion_holdsOneFrame() {
        let held = stagePulse(at: Date(timeIntervalSinceReferenceDate: 0), reduceMotion: true)
        for t in [0.37, 5.0, 123.456, 999.5] {
            XCTAssertEqual(stagePulse(at: Date(timeIntervalSinceReferenceDate: t), reduceMotion: true),
                           held, accuracy: 1e-12)
        }
    }

    /// The pulse is periodic in `pulsePeriod` by construction, so the named
    /// constant IS the breath — a view cannot quietly slow it down by driving
    /// it from a different interval.
    ///
    /// The sampled dates are small `timeIntervalSinceReferenceDate` values on
    /// purpose: at a real wall-clock magnitude (~8×10⁸ s) one ULP of a
    /// `Double` is already ~10⁻⁷ s, so `t + period` cannot round-trip through
    /// `truncatingRemainder` to 1e-9. That is a property of binary floating
    /// point, not of the pulse.
    func test_thePulseRepeatsOnItsNamedPeriod() {
        for t in [0.0, 0.37, 5.0, 123.456] {
            let a = stagePulse(at: Date(timeIntervalSinceReferenceDate: t), reduceMotion: false)
            let b = stagePulse(at: Date(timeIntervalSinceReferenceDate: t + SleepStages.pulsePeriod),
                               reduceMotion: false)
            XCTAssertEqual(a, b, accuracy: 1e-9, "the pulse must repeat on SleepStages.pulsePeriod")
        }
    }

    /// It has to actually move, and it has to stay inside a range that never
    /// makes a live pip invisible (a pip that fades to 0 reads as "gone").
    func test_thePulseBreathes_withinASafeRange() {
        let samples = stride(from: 0.0, to: SleepStages.pulsePeriod, by: SleepStages.pulsePeriod / 16)
            .map { stagePulse(at: Date(timeIntervalSinceReferenceDate: $0), reduceMotion: false) }
        XCTAssertGreaterThan(samples.max()! - samples.min()!, 0.1, "the pulse must visibly move")
        for v in samples {
            XCTAssertGreaterThanOrEqual(v, 0.5)
            XCTAssertLessThanOrEqual(v, 1.0)
        }
    }
}

/// The strip's five 16×16 icons. Same contract as `DeskSceneSpritesTests`,
/// one grid size down: a grid that is no longer square renders padded rather
/// than trapping, and a character outside `DeskPalette` renders as a
/// transparent hole with no error anywhere.
///
/// The hue budget is the one rule specific to this size: at 16 cells an icon
/// with four hues turns to mud on a page that draws it 32 pt wide.
final class StageIconTests: XCTestCase {

    private var allowed: Set<Character> {
        Set(DeskPalette.colors.keys).union([DeskPalette.transparent])
    }

    func testEveryStageIconIs16x16AndInTheDeskPalette() {
        XCTAssertEqual(SleepStages.all.count, 5)
        for stage in SleepStages.all {
            let grid = StageIconSprites.grid(for: stage)
            XCTAssertEqual(grid.count, StageIconSprites.size, "\(stage.id) row count")
            for (r, row) in grid.enumerated() {
                XCTAssertEqual(row.count, StageIconSprites.size, "\(stage.id) row \(r) width")
                for ch in row where !allowed.contains(ch) {
                    XCTFail("\(stage.id) row \(r): '\(ch)' is not a DeskPalette index")
                }
            }
        }
    }

    func testEveryStageIconUsesAtMostThreeHues() {
        for stage in SleepStages.all {
            let hues = Set(StageIconSprites.grid(for: stage).joined()
                .filter { $0 != DeskPalette.transparent })
            XCTAssertFalse(hues.isEmpty, "\(stage.id) draws nothing at all")
            XCTAssertLessThanOrEqual(hues.count, 3, "\(stage.id) uses \(hues.count) hues")
        }
    }

    /// Five distinct drawings — a copy-pasted icon would make two stages
    /// indistinguishable at a glance, which is the whole point of the strip.
    func testTheFiveIconsAreDistinct() {
        let grids = SleepStages.all.map { StageIconSprites.grid(for: $0).joined() }
        XCTAssertEqual(Set(grids).count, 5)
    }
}
