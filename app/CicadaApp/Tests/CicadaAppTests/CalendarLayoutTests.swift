import XCTest
@testable import CicadaApp

final class CalendarLayoutTests: XCTestCase {
    private func cell(_ date: String, level: Int = 0) -> CalendarCell {
        CalendarCell(date: date, level: level, memoryWrites: 0, events: 0, tokens: 0)
    }

    func testPadsFirstWeekToMonday() {
        // 2026-08-27 is a Thursday → 3 nil pads (Mon, Tue, Wed) before it.
        let cols = CalendarLayout.columns([cell("2026-08-27"), cell("2026-08-28")])
        XCTAssertEqual(cols.count, 1)
        XCTAssertEqual(cols[0].count, 7)
        XCTAssertNil(cols[0][0]); XCTAssertNil(cols[0][2])
        XCTAssertEqual(cols[0][3]?.date, "2026-08-27")
        XCTAssertEqual(cols[0][4]?.date, "2026-08-28")
        XCTAssertNil(cols[0][6])
    }

    func testSplitsIntoWeeks() {
        let days = (0..<14).map { i -> CalendarCell in
            let d = Calendar(identifier: .iso8601).date(byAdding: .day, value: i, to: ISO8601DateFormatter().date(from: "2026-08-03T00:00:00Z")!)!
            let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"; f.timeZone = TimeZone(identifier: "UTC")
            return cell(f.string(from: d))
        }
        let cols = CalendarLayout.columns(days) // 2026-08-03 is a Monday
        XCTAssertEqual(cols.count, 2)
        XCTAssertEqual(cols[0][0]?.date, "2026-08-03")
        XCTAssertEqual(cols[1][6]?.date, "2026-08-16")
    }

    /// Jul30's first column (weekday offset 3) fills with Jul30/31 + Aug1/2,
    /// so Aug's first column lands right next to Jul's (index 1 vs. 0) — this
    /// fixture is itself the "AugSep" smudge case `minLabelSpacing` (below)
    /// exists to suppress, so only the earlier label survives.
    func testMonthLabelsAtFirstColumnOfEachMonth() {
        let cols = CalendarLayout.columns([cell("2026-07-30"), cell("2026-07-31"), cell("2026-08-01"), cell("2026-08-02"), cell("2026-08-03"), cell("2026-08-04")])
        let labels = CalendarLayout.monthLabels(cols)
        XCTAssertEqual(labels.map(\.label), ["Jul"])
        XCTAssertEqual(labels.map(\.column), [0])
    }

    /// Two months whose first columns are adjacent used to print both labels
    /// on top of each other — the "AugSep" smudge. Keep the earlier one.
    func testAdjacentMonthLabelsAreThinnedOut() {
        let columns: [[CalendarCell?]] = [
            [cell("2026-08-24")] + Array(repeating: nil, count: 6),
            [cell("2026-09-01")] + Array(repeating: nil, count: 6),
            [cell("2026-09-08")] + Array(repeating: nil, count: 6),
        ]
        let labels = CalendarLayout.monthLabels(columns)
        XCTAssertEqual(labels.map(\.label), ["Aug"])
    }

    /// A month that starts far enough along still gets its own label.
    func testWellSpacedMonthLabelsAreAllKept() {
        var columns: [[CalendarCell?]] = []
        for week in 0..<8 {
            let day = week < 4 ? "2026-08-0\(week + 1)" : "2026-09-0\(week - 3)"
            columns.append([cell(day)] + Array(repeating: nil, count: 6))
        }
        XCTAssertEqual(CalendarLayout.monthLabels(columns).map(\.label), ["Aug", "Sep"])
    }
}
