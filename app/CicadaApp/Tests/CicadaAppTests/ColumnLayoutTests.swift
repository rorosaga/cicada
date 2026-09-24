import XCTest
@testable import CicadaApp

/// §5.3 / DR-27 — the progressive columns' widths, pure. The table is DESIGN_RULES §5.3's, row for row;
/// the sweep holds DR-31's "never pushes content off-window" for every arrangement at every zoom.
final class ColumnLayoutTests: XCTestCase {
    private func nav(labelled: Bool, scale: CGFloat) -> CGFloat {
        ((labelled ? ShellMetrics.sidebarWidth : ShellMetrics.railWidth) * scale * 10).rounded() / 10
    }

    private func plan(_ window: CGFloat, labelled: Bool = false, scale: CGFloat = 1, list: Bool = true,
                      detail: Bool, reader: Bool) -> ColumnPlan {
        let n = nav(labelled: labelled, scale: scale)
        return ColumnLayout.plan(contentWidth: window - n, navWidth: n, scale: scale,
                                 hasList: list, hasDetail: detail, hasTrailing: reader)
    }

    func testTheDesignRulesTableAtOneX() {
        // window, labelled, S1 list, S1 question, S2 list, S2 question, S2 reader
        let table: [(CGFloat, Bool, CGFloat, CGFloat, CGFloat, CGFloat, CGFloat)] = [
            (1440, false, 328, 1056, 260, 704, 420),
            (1440, true, 328, 904, 260, 552, 420),
            (1200, false, 280, 864, 260, 524, 360),
            (1200, true, 280, 712, 0, 632, 360),
        ]
        for (w, labelled, l1, q1, l2, q2, r2) in table {
            let s1 = plan(w, labelled: labelled, detail: true, reader: false)
            XCTAssertEqual([s1.list, s1.detail, s1.trailing], [l1, q1, 0], "S1 \(w) labelled \(labelled)")
            XCTAssertEqual(s1.listStyle, .triage)
            XCTAssertEqual([s1.gutter, s1.cardPadding], [40, 28])
            let s2 = plan(w, labelled: labelled, detail: true, reader: true)
            XCTAssertEqual([s2.list, s2.detail, s2.trailing], [l2, q2, r2], "S2 \(w) labelled \(labelled)")
            XCTAssertEqual(s2.listStyle, l2 == 0 ? .hidden : .titles)
            XCTAssertEqual([s2.gutter, s2.cardPadding], [24, 24], "§5.3: the gutter and the card's padding drop to 24")
        }
    }

    func testStateZeroIsTheListAloneAtFullWidth() {
        let s0 = plan(1440, detail: false, reader: false)
        XCTAssertEqual([s0.list, s0.detail, s0.trailing], [1384, 0, 0])
        XCTAssertEqual(s0.listStyle, .wide)
    }

    /// R-DI8 — a Reader opened elsewhere sits beside the full list; the page never closes it.
    func testAReaderOpenedElsewhereSitsBesideTheWholeList() {
        let p = plan(1440, detail: false, reader: true)
        XCTAssertEqual([p.list, p.trailing], [964, 420])
        XCTAssertEqual(p.listStyle, .wide)
    }

    /// DR-70 / R-DI7 — widths are units: at 1.4× a 1440 window lays out like a ~1029 one.
    func testZoomNarrowsTheColumnsInUnits() {
        let s1 = plan(1440, scale: 1.4, detail: true, reader: false)
        XCTAssertEqual(s1.list, 392, "280 units")
        XCTAssertEqual(s1.detail, 1440 - 78.4 - 392, accuracy: 0.01)
        let s2 = plan(1440, scale: 1.4, detail: true, reader: true)
        XCTAssertEqual(s2.listStyle, .hidden, "DR-27 — the list goes before the question drops under 440")
        XCTAssertEqual(s2.trailing, 504, "360 units")
        XCTAssertEqual(s2.detail, 1440 - 78.4 - 504, accuracy: 0.01)
    }

    /// R-DI7 (§9) — when neither floor fits, the question and the Reader share the width 440 : 360.
    func testWhenNeitherFloorFitsTheTwoShareTheWidthAndNothingOverflows() {
        let s2 = plan(1200, labelled: true, scale: 1.4, detail: true, reader: true)
        let content: CGFloat = 1200 - 291.2
        XCTAssertEqual(s2.listStyle, .hidden)
        XCTAssertEqual(s2.detail + s2.trailing, content, accuracy: 0.01)
        XCTAssertEqual(s2.trailing / content, 360.0 / 800.0, accuracy: 0.01)
    }

    /// R-DI6 — the shell's host: the page is the detail, the Reader the trailing column.
    func testTheShellHostGivesThePageTheRest() {
        let p = plan(1200, list: false, detail: true, reader: true)
        XCTAssertEqual([p.list, p.detail, p.trailing], [0, 784, 360])
        let closed = plan(1200, list: false, detail: true, reader: false)
        XCTAssertEqual([closed.detail, closed.trailing], [1144, 0])
    }

    /// DR-31 — every arrangement sums to the content width, at every zoom, with either sidebar.
    func testEveryArrangementSumsToTheContentWidth() {
        let shapes: [(Bool, Bool, Bool)] = [(true, false, false), (true, true, false), (true, true, true),
                                            (true, false, true), (false, true, true), (false, true, false)]
        for scale: CGFloat in [0.8, 1.0, 1.2, 1.4] {
            for labelled in [false, true] {
                for window in stride(from: CGFloat(600), through: 2400, by: 37) {
                    let content = window - nav(labelled: labelled, scale: scale)
                    for (list, detail, reader) in shapes {
                        let p = plan(window, labelled: labelled, scale: scale, list: list, detail: detail, reader: reader)
                        XCTAssertEqual(p.list + p.detail + p.trailing, content, accuracy: 0.001,
                                       "\(window) \(scale) \(labelled) \(list)/\(detail)/\(reader)")
                        XCTAssertTrue([p.list, p.detail, p.trailing].allSatisfy { $0 >= 0 })
                    }
                }
            }
        }
    }
}
