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

    // MARK: - PR15 triage: 53 vs 54 columns for a non-Monday range start

    private func days(from start: String, count: Int) -> [CalendarCell] {
        let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"; f.timeZone = TimeZone(identifier: "UTC")
        let startDate = f.date(from: start)!
        var cal = Calendar(identifier: .iso8601)
        cal.timeZone = TimeZone(identifier: "UTC")!
        return (0..<count).map { i in
            cell(f.string(from: cal.date(byAdding: .day, value: i, to: startDate)!))
        }
    }

    /// The default dashboard range (`weeks=53` → exactly 371 days, see
    /// `api/routers/consumption.py`) is an exact multiple of 7. The old
    /// algorithm padded a leading AND a trailing partial week; for an
    /// already-exact-multiple-of-7 input those two combine into one whole
    /// extra week — 54 columns instead of 53 — on every day of the year
    /// except the one where "371 days ago" happens to land on a Monday.
    func test53WeeksAlwaysProduces53ColumnsRegardlessOfStartWeekday() {
        // 2026-08-06 is a Thursday.
        XCTAssertEqual(CalendarLayout.weekdayIndex("2026-08-06"), 3)
        let cols = CalendarLayout.columns(days(from: "2026-08-06", count: 371))
        XCTAssertEqual(cols.count, 53, "a non-Monday start must not spill into a 54th column")
    }

    func test53WeeksStartingOnAMondayIsUnaffected() {
        // 2026-08-03 is a Monday.
        XCTAssertEqual(CalendarLayout.weekdayIndex("2026-08-03"), 0)
        let cols = CalendarLayout.columns(days(from: "2026-08-03", count: 371))
        XCTAssertEqual(cols.count, 53)
    }

    /// Trimming the leading partial week must never trim the trailing end —
    /// the most recent (today's) day always survives.
    func test53WeeksKeepsTheMostRecentDayEvenWhenTrimmingTheLeadingPartialWeek() {
        let input = days(from: "2026-08-06", count: 371)
        let cols = CalendarLayout.columns(input)
        let lastDate = input.last!.date
        XCTAssertTrue(cols.last!.compactMap { $0 }.contains { $0.date == lastDate })
    }

    /// A handful of other weekday starts, all pinned to 53 — not just Thursday.
    func test53WeeksHoldsForEveryOtherWeekdayStart() {
        // 2026-08-04 Tue, 2026-08-05 Wed, 2026-08-07 Fri, 2026-08-08 Sat, 2026-08-09 Sun.
        for start in ["2026-08-04", "2026-08-05", "2026-08-07", "2026-08-08", "2026-08-09"] {
            let cols = CalendarLayout.columns(days(from: start, count: 371))
            XCTAssertEqual(cols.count, 53, "start \(start) must still produce 53 columns")
        }
    }
}
