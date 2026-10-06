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

    /// Owner 2026-10-06 — "i dont like how the boxes get clipped with the portion of the search bar." The field sat
    /// outside the blocks' scroll view, whose top edge ran flush under it, so a scrolled card was cut mid-border. One
    /// scroll view now carries the headline, the field and the blocks, and the first block sits one block gap under the
    /// field (never the focus card's 28 pt padding).
    func testTheFieldAndTheBlocksScrollTogether() throws {
        let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first { $0.path.hasSuffix("Views/Home/HomeView.swift") })
        let text = try String(contentsOf: file, encoding: .utf8)
        XCTAssertEqual(text.components(separatedBy: "ScrollView {").count - 1, 1, "one scroll view for the page")
        let scroll = try XCTUnwrap(text.range(of: "ScrollView {"))
        let title = try XCTUnwrap(text.range(of: "PageTitle(Copy.homeHeadline)"))
        let field = try XCTUnwrap(text.range(of: "fieldColumn(showsResults:"))
        let blocks = try XCTUnwrap(text.range(of: "GettingStartedCard(selectedTab:"))
        XCTAssertLessThan(scroll.lowerBound, title.lowerBound, "the headline scrolls with the page")
        XCTAssertLessThan(scroll.lowerBound, field.lowerBound, "the field scrolls with the page, so nothing is cut under it")
        XCTAssertLessThan(field.lowerBound, blocks.lowerBound)
        XCTAssertFalse(text.contains(".padding(.top, CicadaTheme.spacingCard)"), "the field-to-first-block gap is the block gap")
        XCTAssertTrue(text.contains("HomeLayout.fieldToFirstBlock"))
        XCTAssertEqual(HomeLayout.fieldToFirstBlock, HomeLayout.blockGap)
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
