import XCTest
@testable import CicadaApp

/// R-DL13…R-DL16 — the Feed's kinds, words and landing, pure (and one view-model test on a real `Store`).
final class FeedListTests: XCTestCase {
    private func item(_ id: String, url: String = "https://example.com/a", type: String = "url", origin: String? = nil,
                      folder: String? = nil, kind: String? = nil, savedAt: String = "2026-09-13T10:00:00Z",
                      about: [String]? = nil, why: String? = nil, relevance: Double = 0.5) -> MediaFeedItem {
        var extra = ""
        if let origin { extra += #", "origin": "\#(origin)""# }
        if let folder { extra += #", "folder": "\#(folder)""# }
        if let kind { extra += #", "kind": "\#(kind)""# }
        if let about { extra += #", "about": [\#(about.map { "\"\($0)\"" }.joined(separator: ","))]"# }
        if let why { extra += #", "personalRelevance": "\#(why)""# }
        let json = #"{"mediaEntityId": "\#(id)", "url": "\#(url)", "title": "T \#(id)", "mediaType": "\#(type)", "savedAt": "\#(savedAt)", "relevance": \#(relevance), "tags": []\#(extra)}"#
        return try! JSONDecoder().decode(MediaFeedItem.self, from: Data(json.utf8))
    }

    func testKindsArePaperThenVideoThenBookmarkThenLink() {
        XCTAssertEqual(FeedKind.of(item("p", kind: "paper")), .paper)
        XCTAssertEqual(FeedKind.of(item("v", url: "https://vimeo.com/123456789")), .video)
        XCTAssertEqual(FeedKind.of(item("f", url: "https://example.com/media/clip.mp4", type: "video")), .video)
        XCTAssertEqual(FeedKind.of(item("b", type: "bookmark")), .bookmark)
        XCTAssertEqual(FeedKind.of(item("c", origin: "chrome-bookmark")), .bookmark)
        XCTAssertEqual(FeedKind.of(item("l")), .link)
    }

    func testKindTabsShowOnlyThePresentKindsWithCounts() {
        let tabs = FeedKind.tabs([item("l1"), item("l2"), item("b", type: "bookmark")])
        XCTAssertEqual(tabs.map(\.label), [Copy.Lists.all, "Links", "Bookmarks"])
        XCTAssertEqual(tabs.map(\.count), [3, 2, 1])
    }

    func testTheEyebrowSaysWhereYouAre() {
        let items = [item("a"), item("b"), item("c", type: "bookmark")]
        XCTAssertEqual(FeedEyebrow.text(total: 3, kind: nil, visible: items, openId: nil, searching: false), "Feed · 3 saved")
        XCTAssertEqual(FeedEyebrow.text(total: 3, kind: .bookmark, visible: [items[2]], openId: nil, searching: false),
                       "Feed · Bookmarks · 1 saved")
        XCTAssertEqual(FeedEyebrow.text(total: 3, kind: nil, visible: items, openId: items[1].id, searching: false),
                       "Feed · 2 of 3")
        XCTAssertEqual(FeedEyebrow.text(total: 3, kind: nil, visible: [items[0]], openId: nil, searching: true),
                       "Feed · 1 match")
        XCTAssertEqual(FeedEyebrow.text(total: 0, kind: nil, visible: [], openId: nil, searching: false), "Feed",
                       "R-DL18 — nothing indexed: the page says Feed, never '0 items'")
    }

    /// DR-54 / DR-55 — the app's name, the folder, the day; the id only in `.help`.
    func testSavedFromNamesTheSourceAPersonWouldName() {
        let us = Locale(identifier: "en_US"), utc = TimeZone(identifier: "UTC")!
        let saved = item("a", origin: "chrome-bookmark", folder: "Bookmarks bar")
        XCTAssertEqual(FeedSourceLine.text(saved, locale: us, timeZone: utc),
                       "\(OriginIconography.label(for: "chrome-bookmark")) · Bookmarks bar · Sep 13")
        XCTAssertEqual(FeedSourceLine.text(item("b"), locale: us, timeZone: utc), InboxSourceLine.noSource)
        XCTAssertEqual(FeedSourceLine.text(item("c", origin: "unknown"), locale: us, timeZone: utc), InboxSourceLine.noSource)
        XCTAssertNil(FeedSourceLine.markOrigin(item("c", origin: "unknown")))
    }

    /// R-DL15 — only what the page carries; only ids the graph holds.
    func testWhyItsSavedIsOnlyWhatThePageCarries() {
        let names = EntityNames(byId: ["alpha-project": "Alpha Project"])
        let saved = item("a", about: ["alpha-project", "gone-page"], why: "For the storage rewrite")
        XCTAssertEqual(FeedWhy.ownWords(saved), "For the storage rewrite")
        XCTAssertEqual(FeedWhy.about(saved, names: names).map(\.name), ["Alpha Project"])
        XCTAssertNil(FeedWhy.ownWords(item("b", why: "  ")))
        XCTAssertTrue(FeedWhy.about(item("b"), names: names).isEmpty)
    }

    func testARowNamesKindSiteAndDay() {
        let us = Locale(identifier: "en_US"), utc = TimeZone(identifier: "UTC")!
        let json = #"{"mediaEntityId": "a", "url": "https://example.com/a", "title": "A", "mediaType": "url", "site": "example.com", "savedAt": "2026-09-13T10:00:00Z", "tags": []}"#
        let saved = try! JSONDecoder().decode(MediaFeedItem.self, from: Data(json.utf8))
        XCTAssertEqual(FeedRowText.detail(saved, locale: us, timeZone: utc), "Link · example.com · saved Sep 13")
        let clip = #"{"mediaEntityId": "v", "url": "https://vimeo.com/123456789", "title": "V", "mediaType": "url", "site": "vimeo.com", "savedAt": "2026-09-13T10:00:00Z", "durationS": 192, "tags": []}"#
        let video = try! JSONDecoder().decode(MediaFeedItem.self, from: Data(clip.utf8))
        XCTAssertEqual(FeedRowText.detail(video, locale: us, timeZone: utc), "Video · vimeo.com · 3:12 · saved Sep 13",
                       "R17 — the duration a provider reported, which the retired row drew as a pill")
    }

    func testPageStatesInPrecedenceOrder() {
        XCTAssertEqual(FeedPageState.of(isLoading: true, error: nil, hasItems: false, visibleEmpty: true, searching: false), .loading)
        XCTAssertEqual(FeedPageState.of(isLoading: false, error: "timed out", hasItems: false, visibleEmpty: true, searching: false),
                       .failed("timed out"))
        XCTAssertEqual(FeedPageState.of(isLoading: false, error: nil, hasItems: false, visibleEmpty: true, searching: false), .empty)
        XCTAssertEqual(FeedPageState.of(isLoading: false, error: nil, hasItems: true, visibleEmpty: true, searching: true), .noMatch)
        XCTAssertEqual(FeedPageState.of(isLoading: true, error: nil, hasItems: true, visibleEmpty: false, searching: false), .list,
                       "never blank: a refresh over good data keeps the list")
    }

    /// R-DL16 — a landing opens the item in All; a kind tab that does not show it closes it; a vanished item closes.
    @MainActor
    func testLandingKindAndReconcile() {
        let store = Store(cache: SnapshotCache(
            root: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)), api: FakeSyncAPI())
        store.sources.value = [item("a"), item("b", type: "bookmark")]
        let vm = FeedViewModel(store: store)
        vm.setKind(.bookmark)
        XCTAssertTrue(vm.land(mediaEntityId: "a"))
        XCTAssertNil(vm.kind, "a landing shows every kind")
        XCTAssertEqual(vm.openItem?.mediaEntityId, "a")
        vm.setKind(.bookmark)
        XCTAssertNil(vm.openItem, "the tab does not show it")
        XCTAssertFalse(vm.land(mediaEntityId: "missing"))
        XCTAssertTrue(vm.land(mediaEntityId: "b"))
        store.sources.value = [item("a")]
        vm.reconcile()
        XCTAssertNil(vm.openItem)
    }
}
