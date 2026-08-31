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

    // MARK: - Review round 1 (Task 7): pad, never drop, for a non-Monday range start

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
    /// `api/routers/consumption.py`) starting on a Monday needs no leading
    /// pad at all, so it comes out to exactly `ceil(371/7) = 53` columns.
    func test53WeeksStartingOnAMondayIsUnaffected() {
        // 2026-08-03 is a Monday.
        XCTAssertEqual(CalendarLayout.weekdayIndex("2026-08-03"), 0)
        let cols = CalendarLayout.columns(days(from: "2026-08-03", count: 371))
        XCTAssertEqual(cols.count, 53)
    }

    /// A previous fix forced exactly 53 columns for the 371-day range by
    /// dropping the handful of oldest days before the next Monday whenever
    /// the range didn't start on one — silent data loss on 6 days out of 7.
    /// The correct fix pads the first column with leading empty cells
    /// instead (GitHub does the same): every one of the 371 days must still
    /// be rendered, and the column count is honestly 54 here — a 371-day
    /// span starting mid-week genuinely covers 54 distinct Monday…Sunday
    /// weeks, and no day is sacrificed to hide that.
    func test371DaysFromANonMondayStartRendersEveryDayWithNoDataLoss() {
        // 2026-08-05 is a Wednesday → weekdayIndex 2 → 2 leading nils.
        XCTAssertEqual(CalendarLayout.weekdayIndex("2026-08-05"), 2)
        let input = days(from: "2026-08-05", count: 371)
        let cols = CalendarLayout.columns(input)

        XCTAssertEqual(cols.count, 54, "a genuinely mid-week 371-day span needs 54 columns, not a data-dropping 53")

        let rendered = Set(cols.flatMap { $0.compactMap { $0?.date } })
        XCTAssertEqual(rendered.count, 371, "every one of the 371 days must still be rendered")
        XCTAssertEqual(rendered, Set(input.map(\.date)), "no day may be silently dropped")

        XCTAssertNil(cols[0][0]); XCTAssertNil(cols[0][1], "the first column pads with leading empty cells")
        XCTAssertEqual(cols[0][2]?.date, input.first?.date, "the first real day still lands on its correct weekday row")
    }

    /// Not just Wednesday — every non-Monday weekday start renders all 371
    /// days, never trading data for a rounder column count.
    func testEveryNonMondayWeekdayStartRendersAllDaysWithNoLoss() {
        // 2026-08-04 Tue, 2026-08-06 Thu, 2026-08-07 Fri, 2026-08-08 Sat, 2026-08-09 Sun.
        for start in ["2026-08-04", "2026-08-06", "2026-08-07", "2026-08-08", "2026-08-09"] {
            let input = days(from: start, count: 371)
            let cols = CalendarLayout.columns(input)
            let rendered = Set(cols.flatMap { $0.compactMap { $0?.date } })
            XCTAssertEqual(rendered.count, 371, "start \(start) must render every day")
            XCTAssertEqual(cols.count, 54, "start \(start) must not force a lossy 53")
        }
    }
}
