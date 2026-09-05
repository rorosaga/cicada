import XCTest
@testable import CicadaApp

/// G125 Task 7 — the consolidation history card's pure presentation layer:
/// how long a cycle took, its one-line summary, and its date, each a static
/// function so the exact wording is asserted without standing up a view.
final class SleepHistoryPresentationTests: XCTestCase {

    // MARK: durationText

    func testDurationTextIsAnEmDashWhenNoLedgerRowJoined() {
        XCTAssertEqual(SleepHistoryPresentation.durationText(ms: nil), "—")
    }

    func testDurationTextUnderAMinuteIsWholeSeconds() {
        XCTAssertEqual(SleepHistoryPresentation.durationText(ms: 4_200), "4 s")
    }

    func testDurationTextUnderAnHourIsMinutesAndSeconds() {
        XCTAssertEqual(SleepHistoryPresentation.durationText(ms: 252_000), "4 m 12 s")
    }

    func testDurationTextOverAnHourIsHoursAndMinutes() {
        XCTAssertEqual(SleepHistoryPresentation.durationText(ms: 3_700_000), "1 h 2 m")
    }

    // MARK: summaryLine

    private func entry(kind: String = "sleep", created: Int = 0, updated: Int = 0) throws -> SleepHistoryEntry {
        let json = """
        {"commitHash":"abc123","date":"2026-09-01","message":"Sleep cycle 2026-09-01",
         "filesChanged":[],"kind":"\(kind)","entitiesCreated":\(created),"entitiesUpdated":\(updated)}
        """
        return try JSONDecoder().decode(SleepHistoryEntry.self, from: Data(json.utf8))
    }

    func testSummaryLineNamesNewAndUpdatedCounts() throws {
        let e = try entry(created: 12, updated: 8)
        XCTAssertEqual(SleepHistoryPresentation.summaryLine(e), "+12 new · 8 updated")
    }

    func testSummaryLineForADecayCommitNamesItAPass() throws {
        // A G85-split decay commit touches entities too, but it is arithmetic,
        // not extraction — the summary must say so rather than claiming "new"/
        // "updated" work an LLM never did.
        let e = try entry(kind: "decay", created: 0, updated: 5)
        XCTAssertEqual(SleepHistoryPresentation.summaryLine(e), "decay pass")
    }

    // MARK: dateText

    func testDateTextFormatsTheGitShortDate() {
        XCTAssertEqual(SleepHistoryPresentation.dateText("2026-09-01"), "Sep 1")
    }

    func testDateTextFallsBackToTheRawStringWhenUnparseable() {
        XCTAssertEqual(SleepHistoryPresentation.dateText("not-a-date"), "not-a-date")
    }
}
