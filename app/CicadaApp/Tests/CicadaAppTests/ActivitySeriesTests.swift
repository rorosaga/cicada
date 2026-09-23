import SwiftUI
import XCTest
@testable import CicadaApp

/// The activity series behind every Sources card (R-S8): `sparklinePoints`,
/// `weekDots` and `sparklinePath` over `SourceOverview.activity`, Task 1's
/// sparse UTC-day histogram.
///
/// Moved from `MemorySourcesTests` with the functions themselves (Track Z Z3):
/// the Memory sources card left the Sleep page, so the series and their tests
/// now live beside their only callers in `Views/Sources/ActivitySeries.swift`.
/// The cases are verbatim; the `memorySourceRows` cases were deleted with the
/// function they tested.
///
/// Every case is a function over value types; no view is stood up.
final class ActivitySeriesTests: XCTestCase {

    /// The UTC calendar the whole feature is keyed on (P2): `activity`'s keys
    /// are UTC days, so the window that indexes them has to be too, or the
    /// entire series slides by a bucket for readers west of Greenwich.
    private func utcDay(_ year: Int, _ month: Int, _ day: Int) -> Date {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC")!
        var parts = DateComponents()
        parts.year = year; parts.month = month; parts.day = day; parts.hour = 12
        return calendar.date(from: parts)!
    }

    // MARK: sparklinePoints

    /// Dense, oldest first, zero-filled — never a sparse array a view has to
    /// special-case, and never shorter than the window it was asked for.
    func test_sparklinePoints_isDenseOldestFirstAndZeroFilled() {
        let today = utcDay(2026, 9, 5)
        let points = sparklinePoints(activity: ["2026-09-05": 3, "2026-09-03": 1],
                                     days: 7, today: today)
        XCTAssertEqual(points.count, 7)
        XCTAssertEqual(points, [0, 0, 0, 0, 1, 0, 3])
    }

    /// A key outside the window is ignored rather than folded into the edge
    /// bucket — an absolute date key means a 304'd payload renders a day SHORT,
    /// never a day SHIFTED (R-A16).
    func test_sparklinePoints_ignoresAKeyOutsideTheWindow() {
        let points = sparklinePoints(activity: ["2026-08-01": 40, "2026-09-05": 2],
                                     days: 7, today: utcDay(2026, 9, 5))
        XCTAssertEqual(points.reduce(0, +), 2)
    }

    func test_sparklinePoints_emptyActivityIsAllZerosNotAnEmptyArray() {
        let points = sparklinePoints(activity: [:], days: 30, today: utcDay(2026, 9, 5))
        XCTAssertEqual(points.count, 30)
        XCTAssertEqual(points.reduce(0, +), 0)
    }

    /// A malformed or absent window never yields a half-drawn series.
    func test_sparklinePoints_nonPositiveWindowIsEmpty() {
        XCTAssertEqual(sparklinePoints(activity: ["2026-09-05": 1], days: 0, today: utcDay(2026, 9, 5)), [])
    }

    // MARK: weekDots

    /// Four 7-day blocks, oldest first, summed from the same dense day series
    /// the sparkline uses — the two marks can never disagree about a day.
    func test_weekDots_sumsSevenDayBlocksOldestFirst() {
        let today = utcDay(2026, 9, 5)
        let activity = ["2026-08-09": 1,   // 27 days back — the oldest block
                        "2026-09-05": 2]   // today — the newest block
        XCTAssertEqual(weekDots(activity: activity, weeks: 4, today: today), [1, 0, 0, 2])
    }

    func test_weekDots_emptyActivityIsFourZeros() {
        XCTAssertEqual(weekDots(activity: [:], weeks: 4, today: utcDay(2026, 9, 5)), [0, 0, 0, 0])
    }

    // MARK: sparklinePath

    /// Fewer than two points is not a line — an empty `Path`, never a dot that
    /// reads as a datum.
    func test_sparklinePath_needsTwoPointsToDrawAnything() {
        let box = CGSize(width: 56, height: 14)
        XCTAssertTrue(sparklinePath([], in: box).isEmpty)
        XCTAssertTrue(sparklinePath([3], in: box).isEmpty)
        XCTAssertFalse(sparklinePath([0, 3], in: box).isEmpty)
    }

    /// An all-zero series still draws its baseline: "this source captured
    /// nothing in the window" is a fact worth seeing, and a blank cell would
    /// read as a rendering failure.
    func test_sparklinePath_allZerosDrawsAFlatLineNotNothing() {
        XCTAssertFalse(sparklinePath([0, 0, 0], in: CGSize(width: 56, height: 14)).isEmpty)
    }
}
