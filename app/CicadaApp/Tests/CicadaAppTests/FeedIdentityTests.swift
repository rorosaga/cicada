import XCTest
@testable import CicadaApp

final class FeedIdentityTests: XCTestCase {
    private func item(_ entity: String, _ url: String, relevance: Double = 0.57,
                      savedAt: String = "2026-07-13") -> MediaFeedItem {
        let json = """
        {"mediaEntityId": "\(entity)", "url": "\(url)", "title": "t",
         "mediaType": "bookmark", "savedAt": "\(savedAt)", "relevance": \(relevance), "tags": []}
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
}
