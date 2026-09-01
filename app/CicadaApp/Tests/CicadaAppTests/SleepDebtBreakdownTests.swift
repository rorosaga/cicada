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
