import XCTest
@testable import CicadaApp

final class FeedIdentityTests: XCTestCase {
    private func item(_ entity: String, _ url: String, relevance: Double = 0.57,
                      savedAt: String = "2026-07-13", contentSavedAt: String? = nil) -> MediaFeedItem {
        let contentSavedAtField = contentSavedAt.map { ", \"contentSavedAt\": \"\($0)\"" } ?? ""
        let json = """
        {"mediaEntityId": "\(entity)", "url": "\(url)", "title": "t",
         "mediaType": "bookmark", "savedAt": "\(savedAt)", "relevance": \(relevance), "tags": []\(contentSavedAtField)}
        """
        return try! JSONDecoder().decode(MediaFeedItem.self, from: Data(json.utf8))
    }

    /// 148 live bookmarks share one slugified entity id ("Before you continue
    /// to Google Search") — row identity must stay unique per saved URL or
    /// ForEach renders blank slots for every duplicate.
    func testRowIdentityIsUniquePerSavedUrlNotPerEntity() {
        let a = item("media-before-you-continue-to-google-search", "https://one.example")
        let b = item("media-before-you-continue-to-google-search", "https://two.example")
        XCTAssertNotEqual(a.id, b.id)
        XCTAssertEqual(a.id, item(a.mediaEntityId, "https://one.example").id) // stable
    }

    @MainActor
    func testScoresInformativeOnlyWhenRenderedPercentagesDiffer() {
        let store = Store(cache: SnapshotCache(
            root: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        ), api: FakeSyncAPI())
        let vm = FeedViewModel(store: store)
        // 0.5664 vs 0.5689 are distinct Doubles but both render "57%".
        store.sources = Snapshot(value: [item("a", "u1", relevance: 0.5664),
                                         item("b", "u2", relevance: 0.5689)])
        XCTAssertFalse(vm.scoresAreInformative)
        store.sources = Snapshot(value: [item("a", "u1", relevance: 0.31),
                                         item("b", "u2", relevance: 0.82)])
        XCTAssertTrue(vm.scoresAreInformative)
    }

    // G99d: recencyDate must prefer contentSavedAt (the recovered true save
    // date) over savedAt (the ingest timestamp), falling back to savedAt only
    // when no source date was recoverable.
    func testRecencyDatePrefersContentSavedAtOverIngestTimestamp() {
        let noTrueDate = item("a", "u1", savedAt: "2026-08-30T00:00:00Z")
        XCTAssertNil(noTrueDate.contentSavedAt)
        XCTAssertEqual(noTrueDate.recencyDate, ISO8601DateFormatter().date(from: "2026-08-30T00:00:00Z"))

        let withTrueDate = item("b", "u2", savedAt: "2026-08-30T00:00:00Z", contentSavedAt: "2023-01-01")
        let dayOnly = DateFormatter()
        dayOnly.dateFormat = "yyyy-MM-dd"
        dayOnly.timeZone = TimeZone(identifier: "UTC")
        XCTAssertEqual(withTrueDate.recencyDate, dayOnly.date(from: "2023-01-01"))
    }

    // Review finding: a bare contentSavedAt date and a full-timestamp savedAt
    // on the SAME calendar day must compare as real instants, not as raw
    // strings (where "2026-03-14" < "2026-03-14T09:22:00Z" by string length
    // alone). Documented rule: a bare date anchors to 00:00:00 UTC — the
    // START of that day — so the full-timestamp item (a later moment that
    // same day) sorts after it, deterministically.
    func testRecencyDateBareDateAndFullTimestampOnTheSameDaySortDeterministically() {
        let dated = item("dated", "u1", savedAt: "2026-03-14T09:22:00Z", contentSavedAt: "2026-03-14")
        let undated = item("undated", "u2", savedAt: "2026-03-14T09:22:00Z")

        // dated.recencyDate is 2026-03-14T00:00:00Z (start of day, from the
        // bare contentSavedAt); undated.recencyDate is the full 09:22
        // ingest timestamp — later the same day.
        XCTAssertLessThan(dated.recencyDate, undated.recencyDate)
    }

    @MainActor
    func testRecentSortPrefersContentSavedAtOverIngestTimestamp() {
        let store = Store(cache: SnapshotCache(
            root: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        ), api: FakeSyncAPI())
        let vm = FeedViewModel(store: store)
        vm.sort = .recent

        // "a" was ingested a moment before "b" but has no recoverable save
        // date; "b" was ingested after "a" yet its recovered true save date
        // is years older — it must sort AFTER "a" once fixed.
        let a = item("recent-ingest", "u1", savedAt: "2026-08-30T12:00:00Z")
        let b = item("old-true-date", "u2", savedAt: "2026-08-30T12:00:01Z", contentSavedAt: "2023-01-01")
        store.sources = Snapshot(value: [a, b])

        XCTAssertEqual(vm.items.map(\.mediaEntityId), ["recent-ingest", "old-true-date"])
    }
}
