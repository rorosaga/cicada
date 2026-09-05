import XCTest
@testable import CicadaApp

/// G125 R11 — `SleepQueueCard.loadState` renamed to `StudyListCard.loadState`
/// (same four cases, byte-for-byte); `groupEpisodesByOrigin` /
/// `parseEpisodeTimestamp` (formerly `SleepDebtBreakdownTests`, moved to
/// `SleepQueueModel.swift` along with the view they used to back) fold in
/// here too — nothing dropped, only renamed. New: `studyRows` and its
/// `ageLabel` helper, the per-source countdown the study list renders (R3).
final class StudyListCardTests: XCTestCase {

    // MARK: loadState (moved from SleepQueueCardTests, unchanged)

    private func status(unprocessed: Int) -> StatusSnapshot {
        StatusSnapshot(
            sleep: .init(status: "idle", stage: 0, totalStages: 5, cycleId: nil, error: nil),
            inbox: .init(total: 0, byKind: [:]),
            episodes: .init(unprocessed: unprocessed, lastIngestedAt: nil),
            lastSleepAt: nil, nextSleepAt: nil)
    }

    func testLoadStateIsLoadingWhileTheFetchIsInFlight() {
        XCTAssertEqual(StudyListCard.loadState(status: nil, isLoading: true, error: nil), .loading)
    }

    func testLoadStateIsFailedAfterAFailedFetchWithNoSnapshot() {
        XCTAssertEqual(
            StudyListCard.loadState(status: nil, isLoading: false, error: "Couldn't load status"),
            .failed("Couldn't load status")
        )
    }

    func testLoadStateFallsBackToLoadingBeforeTheFetchHasStarted() {
        XCTAssertEqual(StudyListCard.loadState(status: nil, isLoading: false, error: nil), .loading)
    }

    func testLoadStateIsLoadedOnceASnapshotLands() {
        XCTAssertEqual(
            StudyListCard.loadState(status: status(unprocessed: 3), isLoading: true, error: "stale error"),
            .loaded(count: 3)
        )
        XCTAssertEqual(StudyListCard.loadState(status: status(unprocessed: 0), isLoading: false, error: nil), .loaded(count: 0))
    }

    // MARK: groupEpisodesByOrigin (moved from SleepDebtBreakdownTests)

    private func episode(id: String, origin: String, timestamp: String, chars: Int = 0) -> EpisodeQueueItem {
        let json = """
        {"id":"\(id)","timestamp":"\(timestamp)","source":"mcp","origin":"\(origin)",
         "title":null,"preview":"","chars":\(chars),"processed":false}
        """
        return try! JSONDecoder().decode(EpisodeQueueItem.self, from: Data(json.utf8))
    }

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

    // MARK: parseEpisodeTimestamp (moved from SleepDebtBreakdownTests)

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

    // MARK: ageLabel

    func test_ageLabel_underOneHourIsJustNow() {
        XCTAssertEqual(ageLabel(hours: 0), "just now")
        XCTAssertEqual(ageLabel(hours: 0.9), "just now")
    }

    func test_ageLabel_underFortyEightHoursIsHours() {
        XCTAssertEqual(ageLabel(hours: 5), "5h")
        XCTAssertEqual(ageLabel(hours: 47.9), "47h")
    }

    func test_ageLabel_fortyEightHoursAndOverIsDays() {
        XCTAssertEqual(ageLabel(hours: 48), "2d")
        XCTAssertEqual(ageLabel(hours: 72), "3d")
    }

    // MARK: studyRows

    func test_studyRows_ordersByCountDescending() {
        let now = ISO8601DateFormatter().date(from: "2026-09-08T12:00:00Z")!
        let queued = [
            episode(id: "1", origin: "telegram", timestamp: "2026-09-08T10:00:00Z"),
            episode(id: "2", origin: "claude-code", timestamp: "2026-09-08T10:00:00Z"),
            episode(id: "3", origin: "claude-code", timestamp: "2026-09-08T10:00:00Z"),
        ]
        let rows = studyRows(queued: queued, queueByOrigin: [:], readByOrigin: [:], running: false, now: now)
        XCTAssertEqual(rows.map(\.origin), ["claude-code", "telegram"])
        XCTAssertEqual(rows.map(\.count), [2, 1])
    }

    func test_studyRows_computesOldestAgeFromTheEarliestEpisodeInTheOrigin() {
        let now = ISO8601DateFormatter().date(from: "2026-09-08T12:00:00Z")!
        let queued = [
            episode(id: "1", origin: "claude-code", timestamp: "2026-09-08T09:00:00Z"),  // 3h
            episode(id: "2", origin: "claude-code", timestamp: "2026-09-05T12:00:00Z"),  // 3d, the oldest
        ]
        let rows = studyRows(queued: queued, queueByOrigin: [:], readByOrigin: [:], running: false, now: now)
        XCTAssertEqual(rows.first?.oldestAge, "3d")
    }

    func test_studyRows_notRunning_readAndTotalAreNil() {
        let queued = [episode(id: "1", origin: "claude-code", timestamp: "2026-09-08T09:00:00Z")]
        let rows = studyRows(queued: queued, queueByOrigin: ["claude-code": 5], readByOrigin: ["claude-code": 2], running: false)
        XCTAssertNil(rows.first?.read)
        XCTAssertNil(rows.first?.total)
    }

    func test_studyRows_running_carriesReadAndTotalFromTheDicts() {
        let queued = [episode(id: "1", origin: "claude-code", timestamp: "2026-09-08T09:00:00Z")]
        let rows = studyRows(queued: queued, queueByOrigin: ["claude-code": 5], readByOrigin: ["claude-code": 2], running: true)
        XCTAssertEqual(rows.first?.read, 2)
        XCTAssertEqual(rows.first?.total, 5)
    }

    /// A source present in the full queue but absent from THIS cycle's
    /// `queueByOrigin` (the cap left it out) gets `total 0` — the view's
    /// signal to render "next cycle" rather than a bogus "0 of 0".
    func test_studyRows_running_sourceLeftOutByTheCapGetsZeroTotal() {
        let queued = [episode(id: "1", origin: "safari-tab", timestamp: "2026-09-08T09:00:00Z")]
        let rows = studyRows(queued: queued, queueByOrigin: ["claude-code": 5], readByOrigin: ["claude-code": 2], running: true)
        XCTAssertEqual(rows.first?.total, 0)
        XCTAssertEqual(rows.first?.read, 0)
    }
}
