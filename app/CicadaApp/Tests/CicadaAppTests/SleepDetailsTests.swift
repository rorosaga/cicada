import XCTest
@testable import CicadaApp

/// Track Z, Z3 — the page's second surface (R-Z6, spec decision 16) and the
/// strip's news-only rule.
final class SleepDetailsTests: XCTestCase {

    /// Decision 16: closed by default, remembered per viewer.
    func test_detailsIsClosedByDefaultAndRememberedUnderOneKey() {
        XCTAssertEqual(SleepDetails.openKey, "cicada.sleep.detailsOpen")
        XCTAssertFalse(SleepDetails.defaultOpen)
    }

    /// Last cycle appears only when there is something to say about it.
    func test_lastCycleShowsOnlyWithNews() {
        XCTAssertFalse(lastCycleSectionIsVisible(pageError: nil, cancelled: false, capped: false, indexWarning: nil))
        XCTAssertTrue(lastCycleSectionIsVisible(pageError: "boom", cancelled: false, capped: false, indexWarning: nil))
        XCTAssertTrue(lastCycleSectionIsVisible(pageError: nil, cancelled: true, capped: false, indexWarning: nil))
        XCTAssertTrue(lastCycleSectionIsVisible(pageError: nil, cancelled: false, capped: true, indexWarning: nil))
        XCTAssertTrue(lastCycleSectionIsVisible(pageError: nil, cancelled: false, capped: false, indexWarning: "w"))
    }

    /// R-Z6 — the strip is the running instrument and the frozen record of a
    /// cancel or failure (P15); an idle, successful page has nothing for it to say.
    func test_theStripShowsOnlyWhileRunningOrFrozen() {
        XCTAssertFalse(stageStripIsVisible(isRunning: false, cancelled: false, failed: false))
        XCTAssertTrue(stageStripIsVisible(isRunning: true, cancelled: false, failed: false))
        XCTAssertTrue(stageStripIsVisible(isRunning: false, cancelled: true, failed: false))
        XCTAssertTrue(stageStripIsVisible(isRunning: false, cancelled: false, failed: true))
    }

    func test_everySectionHasItsOwnAnchor() {
        let ids = DetailsSection.allCases.map(\.anchorID)
        XCTAssertEqual(ids, ["details.lastCycle", "details.waiting", "details.readout", "details.pastNights"])
        XCTAssertEqual(Set(ids).count, ids.count)
    }

    /// What left the page stays gone: the second column, the duplicate worm
    /// at the strip's end, and the Memory sources card (Sources v2 draws the
    /// same projection).
    func test_whatLeftThePageStaysGone() throws {
        var text = ""
        for file in try SleepNumbersLintTests.sleepSources() {
            text += try String(contentsOf: file, encoding: .utf8)
        }
        XCTAssertFalse(text.contains("MemorySourcesCard("))
        XCTAssertFalse(text.contains("sleepLayout(width:"))
        XCTAssertFalse(text.contains("caughtUpWorm"))
        XCTAssertFalse(try SleepNumbersLintTests.sleepSources().contains { $0.lastPathComponent == "MemorySourcesCard.swift" })
    }
}
