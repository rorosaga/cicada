import SwiftUI
import XCTest
@testable import CicadaApp

/// G125 v3 Task 7 — the right column's "Memory sources" panel: a pure
/// projection of the `sourcesOverview` domain the Store already holds (R-A10 —
/// **no new fetch**), and the two marks it draws over `SourceOverview.activity`
/// (Task 1's sparse UTC-day histogram).
///
/// Every case is a function over value types; no view is stood up, which is how
/// the rest of `Views/Sleep/` is tested.
final class MemorySourcesTests: XCTestCase {

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

    // MARK: memorySourceRows

    private func source(_ id: String, episodes: Int, activity: [String: Int] = [:]) -> SourceOverview {
        SourceOverview(id: id, label: id.capitalized, kind: .harness, mark: id,
                       episodes: episodes, activity: activity)
    }

    /// A source with no captures is not a memory source yet — the panel says
    /// where memory came FROM, so a row with no evidence is dropped rather
    /// than drawn as a zero (R2's "a row is shown only when it has evidence").
    func test_memorySourceRows_dropsSourcesWithNoCaptures() {
        let rows = memorySourceRows(overview: [source("alpha", episodes: 0),
                                               source("bravo", episodes: 4)],
                                    today: utcDay(2026, 9, 5))
        XCTAssertEqual(rows.map(\.id), ["bravo"])
    }

    /// Recent captures first (the panel's question is "what is feeding memory
    /// NOW"), then lifetime captures, then id so the order is stable across
    /// refreshes rather than reshuffling on every 200.
    func test_memorySourceRows_sortsByRecentThenLifetimeThenId() {
        let today = utcDay(2026, 9, 5)
        let rows = memorySourceRows(
            overview: [
                source("alpha", episodes: 10, activity: ["2026-09-05": 5]),
                source("bravo", episodes: 100, activity: ["2026-09-05": 5]),
                source("charlie", episodes: 3, activity: ["2026-09-04": 9]),
                source("delta", episodes: 100, activity: ["2026-09-05": 5]),
            ],
            today: today)
        // charlie (9 recent) → bravo/delta (5 recent, 100 lifetime, id order)
        // → alpha (5 recent, 10 lifetime).
        XCTAssertEqual(rows.map(\.id), ["charlie", "bravo", "delta", "alpha"])
    }

    /// Six is the cap: the right column is a glance at what feeds memory, and
    /// the full list is one click away behind "All sources".
    func test_memorySourceRows_capsAtSix() {
        let overview = (1...9).map { source("s\($0)", episodes: $0) }
        XCTAssertEqual(memorySourceRows(overview: overview, today: utcDay(2026, 9, 5)).count, 6)
    }

    /// P17 — two lists, two nouns: the queue card says `waiting`, this one says
    /// `captured`, and the noun is ON the row, never only in a tooltip.
    func test_memorySourceRows_countLineNamesCapturedNotWaiting() {
        let rows = memorySourceRows(overview: [source("alpha", episodes: 312)],
                                    today: utcDay(2026, 9, 5))
        XCTAssertEqual(rows.first?.countLine, "312 captured")
        XCTAssertTrue(rows.first?.countLine.hasSuffix("captured") == true)
        XCTAssertFalse(rows.first?.countLine.contains("waiting") == true)
    }

    /// The row carries the series it draws, at the window it was asked for —
    /// the view never reaches back into the payload for a second reading.
    func test_memorySourceRows_carryTheirOwnSeries() {
        let rows = memorySourceRows(overview: [source("alpha", episodes: 4, activity: ["2026-09-05": 4])],
                                    today: utcDay(2026, 9, 5), sparkDays: 10)
        XCTAssertEqual(rows.first?.points.count, 10)
        XCTAssertEqual(rows.first?.dots.count, 4)
        XCTAssertEqual(rows.first?.points.last, 4)
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
