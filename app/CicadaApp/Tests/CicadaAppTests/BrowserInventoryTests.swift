import XCTest
@testable import CicadaApp

/// Round 4 C9 — every browser Cicada can really sync is detected by bundle id and wired end to end; the ones it
/// cannot are one line, never a row. No browser profile is read (the catalog is data; the probe is injected).
@MainActor
final class BrowserInventoryTests: XCTestCase {

    func testDetectListsOnlyInstalledBrowsersInCatalogOrderWithTheSupportedFlag() {
        let here: Set<String> = ["company.thebrowser.Browser", "com.apple.Safari", "com.brave.Browser", "org.mozilla.firefox"]
        let inventory = BrowserInventory.detect { here.contains($0) }
        XCTAssertEqual(inventory.installed.map(\.id), ["safari", "brave", "arc", "firefox"])
        XCTAssertEqual(inventory.supported.map(\.id), ["safari", "brave"])
        XCTAssertEqual(inventory.unsupported.map(\.id), ["arc", "firefox"])
    }

    func testTheBundleIdsAreTheVerifiedOnes() {
        let ids = Dictionary(uniqueKeysWithValues: BrowserInventory.catalog.map { ($0.id, $0.bundleId) })
        XCTAssertEqual(ids, [
            "chrome": "com.google.Chrome", "safari": "com.apple.Safari", "brave": "com.brave.Browser",
            "vivaldi": "com.vivaldi.Vivaldi", "comet": "ai.perplexity.comet", "dia": "company.thebrowser.dia",
            "arc": "company.thebrowser.Browser", "firefox": "org.mozilla.firefox", "edge": "com.microsoft.edgemac",
            "opera": "com.operasoftware.Opera",
        ])
    }

    /// Mirrors `api/services/bookmark_sync.py::CHROMIUM_BROWSERS` — a browser added there needs this list, a
    /// `BrowserFile` case and a catalog row together.
    func testTheChromiumFamilyMirrorsTheBackend() {
        XCTAssertEqual(BrowserInventory.chromiumIds, ["chrome", "brave", "vivaldi", "comet", "dia"])
    }

    func testEverySupportedBrowserIsWiredEndToEnd() {
        for spec in BrowserInventory.catalog where spec.supported {
            guard let channel = spec.bookmarksChannel else { return XCTFail("\(spec.id) has no channel") }
            let file = BrowserFile.bookmarks(forBrowser: spec.id)
            XCTAssertNotNil(file, spec.id)
            XCTAssertEqual(BrowserWatchPolicy.file(for: channel), file, "\(spec.id) is watched through its own file")
            XCTAssertEqual(OriginIconography.appBundleId(for: spec.origin), spec.bundleId, "\(spec.id) wears its own icon")
            XCTAssertEqual(ConnectedChannelRow.origin(forChannel: channel), spec.origin)
            XCTAssertEqual(IntegrationCategory.of(channelId: channel), .browsers)
            XCTAssertEqual(ChannelActions.syncRoute(for: channel), .browserFile)
        }
        for spec in BrowserInventory.catalog where !spec.supported {
            XCTAssertNil(spec.bookmarksChannel, "\(spec.id) must never get a row (decision 2)")
        }
    }

    func testTheProfilePathsAreTheDefaultOnes() {
        func path(_ id: String) -> String { BrowserFile.bookmarks(forBrowser: id)!.candidatePaths[0].path }
        XCTAssertTrue(path("brave").hasSuffix("Library/Application Support/BraveSoftware/Brave-Browser/Default/Bookmarks"))
        XCTAssertTrue(path("vivaldi").hasSuffix("Library/Application Support/Vivaldi/Default/Bookmarks"))
        XCTAssertTrue(path("comet").hasSuffix("Library/Application Support/Comet/Default/Bookmarks"))
        XCTAssertTrue(path("dia").hasSuffix("Library/Application Support/Dia/User Data/Default/Bookmarks"))
    }

    func testUnsupportedIsOneLine() {
        let arc = BrowserInventory.spec(id: "arc")!, firefox = BrowserInventory.spec(id: "firefox")!,
            edge = BrowserInventory.spec(id: "edge")!
        XCTAssertEqual(BrowserInventory.unsupportedLine([arc]), "Arc isn't supported yet")
        XCTAssertEqual(BrowserInventory.unsupportedLine([arc, firefox]), "Arc and Firefox aren't supported yet")
        XCTAssertEqual(BrowserInventory.unsupportedLine([arc, firefox, edge]), "Arc, Firefox and Edge aren't supported yet")
        XCTAssertNil(BrowserInventory.unsupportedLine([BrowserInventory.spec(id: "brave")!]))
        let shown = BrowserRows.shown(inventory: BrowserInventory(installed: [arc, BrowserInventory.spec(id: "brave")!]),
                                      channels: [])
        XCTAssertEqual(shown.map(\.id), ["brave"])
    }

    func testARowSaysWhatItReadsAndWhatToDo() {
        let safari = BrowserInventory.spec(id: "safari")!
        XCTAssertEqual(BrowserInventory.readsLine(safari), "Bookmarks · Reading List · Favorites · recently saved first")
        let off = BrowserRows.model(safari, channel: nil, watch: .off, run: nil)
        XCTAssertEqual(off.line, Copy.browserOffLine)
        XCTAssertEqual(off.status, .idle)
        XCTAssertEqual(BrowserRows.action(watch: .off), .turnOn)
        XCTAssertEqual(BrowserRows.action(watch: .blocked), .tryAgain)
        XCTAssertEqual(BrowserRows.action(watch: .absent), .none)
        XCTAssertEqual(BrowserRows.action(watch: .absent, engine: .chromium), .none)
        XCTAssertEqual(BrowserRows.action(watch: .watching), .syncNow)
        let synced = SourceChannel(id: "safari-bookmarks", label: "Safari bookmarks", connected: true, count: 412,
                                   lastSync: "2026-09-24T21:34:00Z", countNoun: "bookmark", actions: ["sync"],
                                   parts: [ChannelPart(key: "reading-list", count: 36), ChannelPart(key: "favorites", count: 12)])
        let model = BrowserRows.model(safari, channel: synced, watch: .watching, run: nil)
        XCTAssertEqual(model.line, "412 bookmarks · Reading List 36 · Favorites 12")
        XCTAssertEqual(model.origin, "safari-bookmark")
    }

    /// Task 3 review, round 1: without Full Disk Access macOS answers Safari's stat as "no such file". The absent
    /// Safari row must still have a button — its read is what reaches the Full Disk Access fix — and must not claim
    /// Safari has nothing in a "main profile".
    func testAnAbsentSafariStillOffersTurnOnAndDoesNotBlameItsProfile() {
        let safari = BrowserInventory.spec(id: "safari")!
        XCTAssertEqual(BrowserRows.action(watch: .absent, engine: safari.engine), .turnOn)
        let model = BrowserRows.model(safari, channel: nil, watch: .absent, run: nil)
        XCTAssertEqual(model.line, Copy.safariNothingYet)
        XCTAssertFalse(model.line?.contains("profile") ?? true)
        XCTAssertEqual(model.status, .idle)
        let brave = BrowserRows.model(BrowserInventory.spec(id: "brave")!, channel: nil, watch: .absent, run: nil)
        XCTAssertEqual(brave.line, Copy.browserNothingYet("Brave"))
    }

    // MARK: Safari's source page (R-SR13)

    private func item(_ id: String, folder: String?, saved: String?) throws -> MediaFeedItem {
        var json: [String: Any] = ["mediaEntityId": id, "url": "https://example.org/\(id)", "title": id,
                                   "mediaType": "bookmark", "savedAt": "2026-09-01T00:00:00Z", "tags": [],
                                   "status": "active", "relatedCount": 0, "relevance": 0, "origin": "safari-bookmark"]
        if let folder { json["folder"] = folder }
        if let saved { json["contentSavedAt"] = saved }
        return try JSONDecoder().decode(MediaFeedItem.self, from: JSONSerialization.data(withJSONObject: json))
    }

    func testSafarisPageIsRecentlySavedThenFavoritesThenTheRestWithNoRepeats() throws {
        let items = [
            try item("older", folder: "com.apple.ReadingList", saved: "2026-09-01"),
            try item("bar", folder: "BookmarksBar/AI", saved: nil),
            try item("newer", folder: "com.apple.ReadingList", saved: "2026-09-20"),
            try item("menu", folder: "BookmarksMenu", saved: nil),
        ]
        let groups = SafariSections.groups(items)
        XCTAssertEqual(groups.map(\.title), [Copy.safariRecentlySaved, Copy.safariFavorites, Copy.safariOtherBookmarks])
        XCTAssertEqual(groups[0].items.map(\.mediaEntityId), ["newer", "older"])
        XCTAssertEqual(groups[1].items.map(\.mediaEntityId), ["bar"])
        XCTAssertEqual(groups[2].items.map(\.mediaEntityId), ["menu"])
        XCTAssertEqual(SafariSections.displayFolder("BookmarksBar/AI"), "Favorites/AI")
        XCTAssertEqual(SafariSections.displayFolder("com.apple.ReadingList"), "Reading List")
        XCTAssertEqual(SafariSections.displayFolder("Bookmarks bar/Reading"), "Bookmarks bar/Reading", "Chrome is untouched")
    }

    func testTheSyncLineSaysSafarisCounts() {
        let result = BookmarkSyncResult(new: 3, skipped: 9, sources: [
            BookmarkSyncSourceSummary(origin: "safari-bookmark", channel: "safari-bookmarks", found: 12, new: 3,
                                      skipped: 9, readingList: 4, favorites: 2),
        ])
        XCTAssertEqual(BrowserImportSummary.bookmarks(result, locale: Locale(identifier: "en_US")),
                       "3 new · 9 already saved · Reading List 4 · Favorites 2")
    }
}
