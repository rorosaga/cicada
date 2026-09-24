import XCTest
@testable import CicadaApp

/// Track I T6 (design §6.2) — every number appears once: while Getting started
/// shows "Read what came in", TODAY omits its waiting clause.
final class HomeLayoutTests: XCTestCase {
    func testTheWaitingNumberAppearsOnce() {
        XCTAssertFalse(HomeLayout.showsWaitingInToday(gettingStartedVisible: true, hasRunBefore: false))
        XCTAssertTrue(HomeLayout.showsWaitingInToday(gettingStartedVisible: true, hasRunBefore: true))
        XCTAssertTrue(HomeLayout.showsWaitingInToday(gettingStartedVisible: false, hasRunBefore: false))
    }

    /// R-HS2, R-HS6 — the D-Home mock's column, field and gaps.
    func testTheColumnAndTheFieldAreTheMocks() {
        XCTAssertEqual(HomeLayout.columnWidth, 760, "DR-36 — a text column is at most 760 pt")
        XCTAssertEqual(HomeLayout.fieldWidth, 640, "the approved mock's field (§10's 560 lost to it, R-HS2)")
        XCTAssertEqual(HomeLayout.blockGap, 24)
        XCTAssertEqual(HomeLayout.labelGap, 6)
    }

    /// R-HS4 — Needs you's rows are the Inbox's STATE 0 rows, so their slots follow R-DI26's floors,
    /// measured in units from Home's own column (760 less the 4 pt inset, or the page less its gutters).
    func testNeedsYouDropsSlotsAtTheInboxsFloors() {
        XCTAssertEqual(HomeLayout.needsYouSlots(pageWidth: 1384, scale: 1.0), InboxRowSlots(entity: true, source: true))
        XCTAssertEqual(HomeLayout.needsYouSlots(pageWidth: 1144, scale: 1.4), InboxRowSlots(entity: true, source: true))
        XCTAssertEqual(HomeLayout.needsYouSlots(pageWidth: 992, scale: 1.4), InboxRowSlots(entity: false, source: true))
        XCTAssertEqual(HomeLayout.needsYouSlots(pageWidth: 600, scale: 1.4), InboxRowSlots(entity: false, source: false))
        XCTAssertEqual(HomeLayout.needsYouSlots(pageWidth: 0, scale: 0), InboxRowSlots(entity: false, source: false),
                       "a zero width never traps")
    }

    /// G125 R10, R-HS3 — Home links to the Sleep page and never starts a cycle.
    func testHomeNeverStartsACycle() throws {
        let files = try ThemeTokenTests.swiftSources()
        for suffix in ["Views/Home/HomeView.swift", "Views/Home/HomeSections.swift"] {
            let file = try XCTUnwrap(files.first { $0.path.hasSuffix(suffix) })
            let text = try String(contentsOf: file, encoding: .utf8)
            for needle in ["triggerManually", "Copy.consolidateNow", "PrimaryActionButton("] {
                XCTAssertFalse(text.contains(needle), "\(suffix) — \(needle)")
            }
        }
    }
}
