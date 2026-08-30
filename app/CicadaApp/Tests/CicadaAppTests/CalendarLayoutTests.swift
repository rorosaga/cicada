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

    func testMonthLabelsAtFirstColumnOfEachMonth() {
        let cols = CalendarLayout.columns([cell("2026-07-30"), cell("2026-07-31"), cell("2026-08-01"), cell("2026-08-02"), cell("2026-08-03"), cell("2026-08-04")])
        let labels = CalendarLayout.monthLabels(cols)
        XCTAssertEqual(labels.map(\.label), ["Jul", "Aug"])
        XCTAssertEqual(labels.map(\.column), [0, 1])
    }
}
