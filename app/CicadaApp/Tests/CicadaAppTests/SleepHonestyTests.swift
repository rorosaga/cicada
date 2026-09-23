import XCTest
@testable import CicadaApp

/// Track Z, Z0 — the honesty fixes (design §13.1–§13.3) and the hoists later
/// tasks read. Every case asserts an exact value.
final class SleepHonestyTests: XCTestCase {

    private func status(_ json: String) throws -> SleepStatusResponse {
        try JSONDecoder().decode(SleepStatusResponse.self, from: Data(json.utf8))
    }

    // MARK: R-Z14 — one stage translation

    /// `SleepStatusResponse.stage` counts COMPLETED stages (`sleep_cycle.py`
    /// sets 1 only after Stage 1 returns), so a running cycle is in
    /// `completed + 1`, clamped to the five.
    func test_activeStage_isOneAheadOfTheCompletedCount() {
        XCTAssertEqual(activeStage(completed: 0), 1, "Read runs before anything has completed")
        XCTAssertEqual(activeStage(completed: 1), 2, "Sort runs once Read has returned")
        XCTAssertEqual(activeStage(completed: 4), 5)
        XCTAssertEqual(activeStage(completed: 5), 5, "the tail after File still reads as File")
        XCTAssertEqual(activeStage(completed: -3), 1)
        XCTAssertEqual(activeStage(completed: 9), 5)
    }

    /// The page mood, the menu bar, onboarding and the strip must name the
    /// SAME stage for one reading — the defect was that three of them said
    /// "stage 1" while the strip lit Sort.
    func test_theMoodTheMenuBarAndTheStripAgreeWhileSortRuns() throws {
        let running = try status(#"{"status":"running","stage":1}"#)
        XCTAssertEqual(deriveSleepPageMood(status: running, debt: nil, justFinishedAt: nil), .sleeping(stage: 2))
        let snapshot = StatusSnapshot(
            sleep: .init(status: "running", stage: 1, totalStages: 5, cycleId: nil, error: nil),
            inbox: .init(total: 0, byKind: [:]),
            episodes: .init(unprocessed: 0, lastIngestedAt: nil),
            lastSleepAt: nil, nextSleepAt: nil)
        XCTAssertEqual(deriveBookwormState(snapshot, justFinishedAt: nil), .sleeping(stage: 2))
        let pips = stageStripState(stage: 1, isRunning: true, cancelled: false, error: false, read: 0, total: 0)
        XCTAssertEqual(pips, [.done, .active(fill: nil), .pending, .pending, .pending])
        XCTAssertEqual(pips.firstIndex(of: .active(fill: nil)), activeStage(completed: 1) - 1)
    }

    // MARK: §13.3 — honest stage lines

    /// Stage 3 used to announce a contradiction and stage 4 a habit on EVERY
    /// cycle, whether or not one existed. The lines now say what the stage
    /// does, not what it found.
    func test_theBubbleNeverAssertsAFindingItHasNotMeasured() {
        XCTAssertEqual(sleepBubbleText(.sleeping(stage: 3), BubbleContext()), "Checking for contradictions.")
        XCTAssertEqual(sleepBubbleText(.sleeping(stage: 4), BubbleContext()), "Looking for habits.")
    }

    // MARK: Hoist — the next run (was StudyListCard.nextRunText)

    private let utc = TimeZone(identifier: "UTC")!
    private let posix = Locale(identifier: "en_US_POSIX")

    func test_nextRunSentence_namesTheDateTheBackendReported() {
        let daily = ScheduleConfig(mode: "daily", hour: 3, minute: 0)
        XCTAssertEqual(nextRunWhen(daily, nextSleepAt: "2026-09-24T03:00:00Z", locale: posix, timeZone: utc),
                       "Sep 24, 3:00 AM")
        XCTAssertEqual(nextRunSentence(daily, nextSleepAt: "2026-09-24T03:00:00Z", locale: posix, timeZone: utc),
                       "Next run Sep 24, 3:00 AM")
    }

    /// A manual bank has no next run, whatever the snapshot carries — the
    /// schedule is the truth (`ScheduleConfig.mode`).
    func test_nextRunSentence_manualNeverNamesADate() {
        let manual = ScheduleConfig(mode: "manual", hour: 3, minute: 0)
        XCTAssertEqual(nextRunSentence(manual, nextSleepAt: "2026-09-24T03:00:00Z", locale: posix, timeZone: utc),
                       Copy.nextRunManual)
        XCTAssertNil(nextRunWhen(manual, nextSleepAt: "2026-09-24T03:00:00Z", locale: posix, timeZone: utc))
    }

    /// Unknown is a dash (R-A14) — except after-import, whose rule is a sentence.
    func test_nextRunSentence_unknownDateIsADashOrTheImportRule() {
        XCTAssertEqual(nextRunSentence(ScheduleConfig(mode: "interval", hour: 3, minute: 0), nextSleepAt: nil,
                                       locale: posix, timeZone: utc), "Next run —")
        XCTAssertEqual(nextRunSentence(ScheduleConfig(mode: "after_import", hour: 3, minute: 0), nextSleepAt: nil,
                                       locale: posix, timeZone: utc), "Next run after the next import")
    }

    // MARK: Hoist — one source's queue (was StudyListCard.episodesForOrigin)

    private func episode(_ id: String, origin: String, at timestamp: String) throws -> EpisodeQueueItem {
        try JSONDecoder().decode(EpisodeQueueItem.self, from: Data("""
        {"id":"\(id)","timestamp":"\(timestamp)","source":"mcp","origin":"\(origin)","preview":"","processed":false}
        """.utf8))
    }

    func test_episodesForOrigin_isThatOriginNewestFirstWithUnparseableLast() throws {
        let all = [try episode("old", origin: "claude-code", at: "2026-09-01T00:00:00Z"),
                   try episode("other", origin: "rss", at: "2026-09-05T00:00:00Z"),
                   try episode("bad", origin: "claude-code", at: "not a date"),
                   try episode("new", origin: "claude-code", at: "2026-09-03T00:00:00Z")]
        XCTAssertEqual(episodesForOrigin("claude-code", in: all).map(\.id), ["new", "old", "bad"])
        XCTAssertTrue(episodesForOrigin("telegram", in: all).isEmpty)
    }
}
