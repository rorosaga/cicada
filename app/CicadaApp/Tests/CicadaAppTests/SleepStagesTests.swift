import XCTest
@testable import CicadaApp

/// G125 v3 Task 5 — the five stages (spec R-A8, plan P15/P16); since 2026-11-26 the stage stepper is retired and the
/// run object (`SleepRunObject.swift`) says the one running step in a word.
///
/// Two contracts are worth a test and neither needs a view:
///
/// 1. **One array (P16).** The run object, the sentence and the `?` popover read the same five stages.
///    `HowSleepWorksContent` already declares itself the one prose source for the pipeline; a second hand-typed list
///    would be a fourth naming of it.
/// 2. **Reduce Motion holds the terminal frame (R-A13)**, and the breathing period is a named constant so the ≤ 1.2 s
///    budget is assertable rather than inferred from a magic number inside a view.
final class SleepStagesTests: XCTestCase {

    // MARK: - One array, five stages

    func test_sleepStages_areTheFiveShortLabels() {
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
            "Contradictions become questions on Home; old beliefs fade.",
            "Habits that recur become skills.",
            "Everything is written to the graph and committed with its provenance.",
        ])
        XCTAssertEqual(SleepStages.all.map(\.symbol), [
            "book", "arrow.triangle.merge", "questionmark.circle", "sparkles", "checkmark.seal",
        ])
    }

    // MARK: - The motion budget (R-A13)

    func test_pulsePeriod_isInsideTheMotionBudget() {
        XCTAssertLessThanOrEqual(SleepStages.pulsePeriod, 1.2)
        XCTAssertGreaterThan(SleepStages.pulsePeriod, 0)
    }

    /// The live dot breathes on its own layer: one whole breath is the named period (down over half, back up over
    /// half), it never fades out of sight, and Reduce Motion holds it lit — no breath at all (R-A13, DR-66).
    func test_theLiveDotBreathesOnTheNamedPeriodAndHoldsUnderReduceMotion() throws {
        XCTAssertNil(LiveDot.breath(reduceMotion: true), "Reduce Motion holds the lit frame")
        let breath = try XCTUnwrap(LiveDot.breath(reduceMotion: false))
        XCTAssertTrue(breath.autoreverses)
        XCTAssertEqual(breath.duration * 2, SleepStages.pulsePeriod, accuracy: 1e-9)
        XCTAssertEqual(breath.fromValue as? Double, 1.0)
        let floor = try XCTUnwrap(breath.toValue as? Double)
        XCTAssertGreaterThanOrEqual(floor, 0.5, "a dot that fades toward 0 reads as gone")
        XCTAssertLessThan(floor, 0.9, "the breath must visibly move")
    }

    /// The old strip breathed through a 0.1 s `TimelineView` — the pattern that lays the whole window out at the
    /// display rate (app.md, 2026-10-05). The run object's two live marks have none.
    func test_theLiveMarksDriveNoTimelineView() throws {
        for name in ["SleepLiveMark.swift", "SleepRunObject.swift"] {
            let file = try XCTUnwrap(SleepNumbersLintTests.sleepSources().first { $0.lastPathComponent == name })
            let code = try String(contentsOf: file, encoding: .utf8).components(separatedBy: .newlines)
                .filter { !$0.trimmingCharacters(in: .whitespaces).hasPrefix("//") && !$0.contains("///") }
            XCTAssertFalse(code.contains { $0.contains("TimelineView(") }, name)
        }
    }
}
