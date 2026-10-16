import XCTest
@testable import CicadaApp

/// R-DL17, carried into the Sleep redesign (2026-10-16) — the Feed's header bug was removed by construction, and its
/// list now lives under the room as Sleep's Saved tab; this pins the construction. A hosted-window test would see the
/// titlebar, but a headless `swift test` process must never create NSApp (`AppRouter.activateMainWindow`).
final class FeedLayoutPinTests: XCTestCase {
    private func source(_ path: String) throws -> String {
        let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first { $0.path.hasSuffix(path) }, path)
        return try String(contentsOf: file, encoding: .utf8)
    }

    func testTheFeedPageRetiredIntoSleep() throws {
        XCTAssertNil(try ThemeTokenTests.swiftSources().first { $0.path.hasSuffix("Views/Feed/FeedPage.swift") },
                     "the Feed is Sleep's Saved tab")
        XCTAssertFalse(AppTab.allCases.map(\.rawValue).contains("Feed"))
    }

    /// No page-title band, no strips above the list, and the tab row is the list's pinned header (sticky when the room
    /// scrolls away) or, beside an open item, the eyebrow.
    func testTheTabRowIsTheListsOnlyFixedBand() throws {
        let page = try source("Views/Sleep/SleepView.swift")
        XCTAssertTrue(page.contains("ProgressiveColumns("))
        XCTAssertFalse(page.contains("PageHeader("), "DR-25 — no page-title band")
        XCTAssertFalse(page.contains("PageTitle("), "the Sleep Cycle title retired")
        XCTAssertTrue(page.contains("pinnedViews: [.sectionHeaders]"), "the tab row sticks under the titlebar")
        XCTAssertFalse(page.contains("ConnectedChannelsStrip"), "Connected lives on Sources")
        // Home's Getting started shows waits only until it graduates, so Saved keeps the Feed's strip (R-IB22).
        XCTAssertEqual(page.components(separatedBy: "ExportWaitStrip()").count - 1, 1, "export waits head Saved")
        XCTAssertFalse(page.contains(".glassCard()"), "the room left its card")
        let rows = try source("Views/Feed/FeedRows.swift")
        XCTAssertFalse(rows.contains("ConnectedChannelsStrip("))
    }

    func testThePlusIsInTheTabRowWithItsShortcut() throws {
        let row = try source("Views/Sleep/SleepTabRow.swift")
        XCTAssertTrue(row.contains(#"IconButton(systemName: "plus""#))
        XCTAssertTrue(row.contains(#"KeyboardShortcut("n", modifiers: .command)"#))
        let page = try source("Views/Sleep/SleepView.swift")
        XCTAssertFalse(page.contains(".opacity(0)"), "no hidden zero-size button")
        XCTAssertEqual(page.components(separatedBy: "AddSourceSheet(").count - 1, 1)
    }
}
