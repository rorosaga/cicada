import XCTest
@testable import CicadaApp

/// G106 amendment: the "what's waiting" breakdown's pure grouping functions
/// — by source and by age. Every case asserts exact values/order, not just
/// "didn't throw".
final class SleepDebtBreakdownTests: XCTestCase {

    private func episode(id: String, origin: String, timestamp: String) -> EpisodeQueueItem {
        let json = """
        {"id":"\(id)","timestamp":"\(timestamp)","source":"mcp","origin":"\(origin)",
         "title":null,"preview":"","processed":false}
        """
        return try! JSONDecoder().decode(EpisodeQueueItem.self, from: Data(json.utf8))
    }

    // MARK: groupEpisodesByOrigin

    func test_groupByOrigin_countsAndSortsLargestFirst() {
        let episodes = [
            episode(id: "1", origin: "claude-code", timestamp: "2026-09-01T00:00:00Z"),
            episode(id: "2", origin: "telegram", timestamp: "2026-09-01T00:00:00Z"),
            episode(id: "3", origin: "claude-code", timestamp: "2026-09-01T00:00:00Z"),
            episode(id: "4", origin: "claude-code", timestamp: "2026-09-01T00:00:00Z"),
        ]
        let buckets = groupEpisodesByOrigin(episodes)
        XCTAssertEqual(buckets.map(\.origin), ["claude-code", "telegram"])
        XCTAssertEqual(buckets.map(\.count), [3, 1])
    }

    func test_groupByOrigin_emptyInputIsEmptyOutput() {
        XCTAssertEqual(groupEpisodesByOrigin([]), [])
    }

    func test_groupByOrigin_tiesKeepFirstSeenOrder() {
        let episodes = [
            episode(id: "1", origin: "rss", timestamp: "t"),
            episode(id: "2", origin: "telegram", timestamp: "t"),
        ]
        let buckets = groupEpisodesByOrigin(episodes)
        XCTAssertEqual(buckets.map(\.origin), ["rss", "telegram"])
    }

    // MARK: parseEpisodeTimestamp

    func test_parseEpisodeTimestamp_acceptsFractionalSeconds() {
        XCTAssertNotNil(parseEpisodeTimestamp("2026-09-01T10:00:00.123Z"))
    }

    func test_parseEpisodeTimestamp_acceptsPlainISO8601() {
        XCTAssertNotNil(parseEpisodeTimestamp("2026-09-01T10:00:00Z"))
    }

    func test_parseEpisodeTimestamp_nilOnEmptyOrGarbage() {
        XCTAssertNil(parseEpisodeTimestamp(""))
        XCTAssertNil(parseEpisodeTimestamp("not a date"))
    }

    // MARK: parseEpisodeTimestamp — naive local time (Devin PR #27 round 1, finding 6)
    //
    // The bank's own MCP capture path writes naive LOCAL time
    // (`datetime.now().isoformat()`, no `Z`/offset) — the SAME both-shapes
    // reality the backend's `sleep_debt._parse_episode_timestamp` hit (M1).
    // `ISO8601DateFormatter`'s `.withInternetDateTime` REQUIRES a tz
    // designator and returns `nil` without one, so a naive value used to
    // fall straight through to `nil` and land in `.older` unconditionally
    // — disagreeing with the backend's own age math for the SAME episode.

    private func naiveLocalString(_ date: Date, includeFraction: Bool = false) -> String {
        let f = DateFormatter()
        f.dateFormat = includeFraction ? "yyyy-MM-dd'T'HH:mm:ss.SSSSSS" : "yyyy-MM-dd'T'HH:mm:ss"
        f.timeZone = .current
        f.locale = Locale(identifier: "en_US_POSIX")
        return f.string(from: date)
    }

    func test_parseEpisodeTimestamp_acceptsNaiveLocalTimestamp() throws {
        let now = Date()
        let raw = naiveLocalString(now)
        // `try XCTUnwrap`, not `XCTAssertNotNil` + `!` — a regression here
        // must fail just THIS test, not force-unwrap `nil` and crash the
        // whole process before the rest of the suite gets to run.
        let parsed = try XCTUnwrap(
            parseEpisodeTimestamp(raw), "a naive (no Z, no offset) timestamp must still parse"
        )
        XCTAssertEqual(parsed.timeIntervalSince1970, now.timeIntervalSince1970, accuracy: 1.0)
    }

    func test_parseEpisodeTimestamp_acceptsNaiveLocalTimestampWithFractionalSeconds() throws {
        let now = Date()
        let raw = naiveLocalString(now, includeFraction: true)
        let parsed = try XCTUnwrap(parseEpisodeTimestamp(raw))
        XCTAssertEqual(parsed.timeIntervalSince1970, now.timeIntervalSince1970, accuracy: 1.0)
    }

    // MARK: groupEpisodesByAge — naive timestamps near the 24h / 7-day boundaries

    func test_groupByAge_naiveTimestamp_justUnder24HoursIsToday() {
        let now = Date()
        let raw = naiveLocalString(now.addingTimeInterval(-23 * 3600))
        let buckets = groupEpisodesByAge([episode(id: "1", origin: "mcp", timestamp: raw)], now: now)
        XCTAssertEqual(buckets.first?.bucket, .today)
    }

    func test_groupByAge_naiveTimestamp_justOver24HoursIsThisWeek() {
        let now = Date()
        let raw = naiveLocalString(now.addingTimeInterval(-25 * 3600))
        let buckets = groupEpisodesByAge([episode(id: "1", origin: "mcp", timestamp: raw)], now: now)
        XCTAssertEqual(buckets.first?.bucket, .thisWeek)
    }

    func test_groupByAge_naiveTimestamp_justUnder7DaysIsThisWeek() {
        let now = Date()
        let raw = naiveLocalString(now.addingTimeInterval(-((24 * 7 - 1) * 3600)))
        let buckets = groupEpisodesByAge([episode(id: "1", origin: "mcp", timestamp: raw)], now: now)
        XCTAssertEqual(buckets.first?.bucket, .thisWeek)
    }

    func test_groupByAge_naiveTimestamp_justOver7DaysIsOlder() {
        let now = Date()
        let raw = naiveLocalString(now.addingTimeInterval(-((24 * 7 + 1) * 3600)))
        let buckets = groupEpisodesByAge([episode(id: "1", origin: "mcp", timestamp: raw)], now: now)
        XCTAssertEqual(buckets.first?.bucket, .older)
    }

    func test_groupByAge_naiveAndZSuffixedTimestampsAgreeForTheSameInstant() {
        // The two shapes the bank actually contains, side by side, for the
        // SAME real moment — both must land in the SAME bucket.
        let now = Date()
        let target = now.addingTimeInterval(-30 * 3600)   // -> this week either way
        let naiveRaw = naiveLocalString(target)
        let utcFormatter = DateFormatter()
        utcFormatter.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        utcFormatter.timeZone = TimeZone(identifier: "UTC")
        utcFormatter.locale = Locale(identifier: "en_US_POSIX")
        let zRaw = utcFormatter.string(from: target) + "Z"

        let buckets = groupEpisodesByAge([
            episode(id: "naive", origin: "mcp", timestamp: naiveRaw),
            episode(id: "z", origin: "claude-export", timestamp: zRaw),
        ], now: now)

        XCTAssertEqual(buckets.map(\.bucket), [.thisWeek])
        XCTAssertEqual(buckets.first?.count, 2, "both shapes must bucket identically for the same instant")
    }

    // MARK: groupEpisodesByAge

    func test_groupByAge_bucketsTodayThisWeekOlder() {
        let now = ISO8601DateFormatter().date(from: "2026-09-08T12:00:00Z")!
        let episodes = [
            episode(id: "1", origin: "mcp", timestamp: "2026-09-08T06:00:00Z"),  // 6h ago -> today
            episode(id: "2", origin: "mcp", timestamp: "2026-09-05T12:00:00Z"),  // 3d ago -> this week
            episode(id: "3", origin: "mcp", timestamp: "2026-08-01T12:00:00Z"),  // weeks ago -> older
        ]
        let buckets = groupEpisodesByAge(episodes, now: now)
        let byBucket = Dictionary(uniqueKeysWithValues: buckets.map { ($0.bucket, $0.count) })
        XCTAssertEqual(byBucket[.today], 1)
        XCTAssertEqual(byBucket[.thisWeek], 1)
        XCTAssertEqual(byBucket[.older], 1)
    }

    func test_groupByAge_omitsEmptyBuckets() {
        let now = ISO8601DateFormatter().date(from: "2026-09-08T12:00:00Z")!
        let episodes = [episode(id: "1", origin: "mcp", timestamp: "2026-09-08T06:00:00Z")]
        let buckets = groupEpisodesByAge(episodes, now: now)
        XCTAssertEqual(buckets.map(\.bucket), [.today])
    }

    func test_groupByAge_unparseableTimestampCountsAsOlderNotDropped() {
        let now = Date()
        let episodes = [episode(id: "1", origin: "mcp", timestamp: "garbage")]
        let buckets = groupEpisodesByAge(episodes, now: now)
        XCTAssertEqual(buckets.map(\.count).reduce(0, +), 1, "must not silently drop the episode")
        XCTAssertEqual(buckets.first?.bucket, .older)
    }

    func test_groupByAge_boundaryAt24Hours() {
        let now = ISO8601DateFormatter().date(from: "2026-09-08T12:00:00Z")!
        // Exactly 24h ago -> no longer "today" (h < 24 is the today cutoff).
        let episodes = [episode(id: "1", origin: "mcp", timestamp: "2026-09-07T12:00:00Z")]
        let buckets = groupEpisodesByAge(episodes, now: now)
        XCTAssertEqual(buckets.first?.bucket, .thisWeek)
    }

    func test_groupByAge_emptyInputIsEmptyOutput() {
        XCTAssertEqual(groupEpisodesByAge([], now: Date()), [])
    }
}
