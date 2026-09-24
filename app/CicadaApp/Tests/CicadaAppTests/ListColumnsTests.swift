import XCTest
@testable import CicadaApp

/// R-DL6 / R-DL7 — the browse pages' open-row reducer, and which pages draw the Reader themselves.
final class ListColumnsTests: XCTestCase {
    func testNeighbourIsClampedAndStartsAtAnEnd() {
        var c = ListColumns<String>()
        XCTAssertEqual(c.neighbour(1, in: ["a", "b", "c"]), "a")
        XCTAssertEqual(c.neighbour(-1, in: ["a", "b", "c"]), "c")
        XCTAssertNil(c.neighbour(1, in: []))
        c.open("b")
        XCTAssertEqual(c.neighbour(1, in: ["a", "b", "c"]), "c")
        XCTAssertEqual(c.neighbour(-5, in: ["a", "b", "c"]), "a")
        XCTAssertEqual(c.neighbour(1, in: ["x", "y"]), "x", "a row the list no longer shows starts over")
    }

    /// A row that leaves the data closes the detail; one a filter merely hides stays open.
    func testReconcileClosesOnlyWhatLeftTheData() {
        var c = ListColumns<String>()
        c.open("b")
        c.reconcile(present: ["a", "b"])
        XCTAssertEqual(c.openId, "b")
        c.reconcile(present: ["a"])
        XCTAssertNil(c.openId)
    }

    func testEscapeClosesTheRightmostThing() {
        var c = ListColumns<String>()
        XCTAssertEqual(c.escape(readerOpen: false), .none)
        XCTAssertEqual(c.escape(readerOpen: true), .closeReader)
        c.open("a")
        XCTAssertEqual(c.escape(readerOpen: false), .closeDetail)
        XCTAssertEqual(c.escape(readerOpen: true), .closeReader)
    }

    func testRowHeightsAreTheRolesOwn() {
        XCTAssertEqual(ListRowSurface.height(.wide), RowMetrics.oneLine)
        XCTAssertEqual(ListRowSurface.height(.wide, twoLineAtRest: true), RowMetrics.twoLine)
        XCTAssertEqual(ListRowSurface.height(.triage), RowMetrics.twoLine)
        XCTAssertEqual(ListRowSurface.height(.titles), RowMetrics.titleOnly)
    }

    /// R-DL7 — grows with each page's task; the shell draws the Reader for every other page.
    func testWhichPagesDrawTheReaderThemselves() {
        XCTAssertEqual(AppTab.allCases.filter(\.hostsOwnReader), [.clusters, .feed, .inbox])
    }
}
