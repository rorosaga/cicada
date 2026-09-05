import XCTest
@testable import CicadaApp

/// G71 §4.1 — the `+` sheet is a platform catalog: one tile per platform, each
/// carrying the route it takes (Connect vs Import file vs Sync vs Subscribe)
/// and the live connected state from `GET /sources/channels`.
final class ImportCatalogTests: XCTestCase {

    // MARK: - Routes

    func testTheTwoDirectApiPlatformsTakeTheConnectRoute() {
        XCTAssertEqual(AddSourceTile.pinterest.route, .connect)
        XCTAssertEqual(AddSourceTile.reddit.route, .connect)
        XCTAssertEqual(ImportRoute.connect.badge, "Connect")
    }

    func testEveryExportPlatformTakesTheImportFileRoute() {
        for tile in [AddSourceTile.instagram, .youtube, .tiktok, .linkedin,
                     .chatExport, .bookmarksFile] {
            XCTAssertEqual(tile.route, .importFile, "\(tile.rawValue)")
        }
        XCTAssertEqual(ImportRoute.importFile.badge, "Import file")
    }

    func testLocalAndSubscriptionRoutesKeepTheirOwnVerbs() {
        XCTAssertEqual(AddSourceTile.safari.route, .sync)
        XCTAssertEqual(AddSourceTile.chrome.route, .sync)
        XCTAssertEqual(AddSourceTile.appleNotes.route, .sync)
        XCTAssertEqual(AddSourceTile.rssFeed.route, .subscribe)
        XCTAssertEqual(AddSourceTile.calendar.route, .subscribe)
        XCTAssertEqual(AddSourceTile.pasteLink.route, .paste)
        XCTAssertEqual(ImportRoute.sync.badge, "Sync")
        XCTAssertEqual(ImportRoute.subscribe.badge, "Subscribe")
        XCTAssertEqual(ImportRoute.paste.badge, "Save")
    }

    /// The X tile is Connect-shaped (a direct API is the eventual plan), but
    /// its connector is a later backend task — G51 controller ruling #2.
    func testXIsAConnectRouteTileToo() {
        XCTAssertEqual(AddSourceTile.x.route, .connect)
    }

    // MARK: - Tile state from channels

    private func channel(_ id: String, connected: Bool, detail: String? = nil,
                         lastError: String? = nil) -> SourceChannel {
        SourceChannel(id: id, label: id, connected: connected, count: 1,
                      lastSync: "2026-08-30T10:00:00Z", detail: detail,
                      lastError: lastError, actions: [])
    }

    func testAnUnconnectedTileShowsItsRouteBadgeAndNoDetail() {
        let state = AddSourceTile.tileState(.pinterest, channels: [])
        XCTAssertEqual(state.badge, "Connect")
        XCTAssertFalse(state.connected)
        XCTAssertNil(state.detail)
    }

    func testAConnectedTileShowsTheChannelDetail() {
        let state = AddSourceTile.tileState(
            .pinterest,
            channels: [channel("pinterest", connected: true, detail: "40 pins · synced 2026-08-30")]
        )
        XCTAssertTrue(state.connected)
        XCTAssertEqual(state.detail, "40 pins · synced 2026-08-30")
    }

    func testAFailingChannelIsNotAdvertisedAsHealthy() {
        let state = AddSourceTile.tileState(
            .reddit,
            channels: [channel("reddit", connected: true,
                               detail: "Last sync failed · RuntimeError: 429",
                               lastError: "RuntimeError: 429")]
        )
        XCTAssertEqual(state.badge, "Needs attention")
        XCTAssertEqual(state.detail, "Last sync failed · RuntimeError: 429")
    }

    func testATileSpanningTwoChannelsIsConnectedWhenEitherIs() {
        let state = AddSourceTile.tileState(
            .chatExport,
            channels: [channel("chat-export:claude", connected: false),
                       channel("chat-export:chatgpt", connected: true, detail: "3 conversations")]
        )
        XCTAssertTrue(state.connected)
        XCTAssertEqual(state.detail, "3 conversations")
    }

    /// Task 14 wired `x.py` into `ADAPTERS`, and Task 13 gave the tile
    /// `channelIds: ["x"]` to match — X now resolves against a live backend
    /// channel exactly like Pinterest and Reddit, never "Coming soon".
    func testXIsNowConnectableLikePinterestAndReddit() {
        let state = AddSourceTile.tileState(.x, channels: [])
        XCTAssertEqual(state.badge, "Connect")
        XCTAssertFalse(state.connected)
        XCTAssertNil(state.detail)
    }

    /// M1 (final review): X's channel row carries its pay-per-use cost note
    /// as `detail` even while disconnected — `channel_registry
    /// ._connector_channel`'s `price_note` "stands in for it entirely when
    /// there is otherwise none" — the tile must surface it too, not just a
    /// connected one's synced-count detail.
    func testAnUnconnectedPayPerUseTileStillShowsItsCostNote() {
        let state = AddSourceTile.tileState(
            .x, channels: [channel("x", connected: false, detail: "~$0.001/read · pay-per-use")]
        )
        XCTAssertFalse(state.connected)
        XCTAssertEqual(state.detail, "~$0.001/read · pay-per-use")
    }

    func testXShowsConnectedWhenItsChannelIsLive() {
        let state = AddSourceTile.tileState(
            .x, channels: [channel("x", connected: true, detail: "12 bookmarks · synced 2026-08-30")]
        )
        XCTAssertTrue(state.connected)
        XCTAssertEqual(state.detail, "12 bookmarks · synced 2026-08-30")
    }

    // MARK: - Coverage

    func testEveryPlatformInTheSpecHasATile() {
        let ids = Set(AddSourceTile.allCases.map(\.rawValue))
        for expected in ["instagram", "youtube", "pinterest", "reddit", "tiktok",
                         "linkedin", "x", "safari", "chrome", "appleNotes", "rssFeed",
                         "calendar", "telegram", "pasteLink", "bookmarksFile"] {
            XCTAssertTrue(ids.contains(expected), "missing tile: \(expected)")
        }
    }

    func testTheRetiredCombinedTileIsGone() {
        XCTAssertNil(AddSourceTile(rawValue: "savedContent"))
        // R6 — the combined two-browser bookmarks tile split into one tile
        // per browser; the catalog has no room for a shared row.
        XCTAssertNil(AddSourceTile(rawValue: "browserBookmarks"))
    }

    /// R4/R6 — each browser tile owns exactly its own channel rows, and the
    /// two Safari rows both "Manage…" from the Safari tile.
    func testBrowserTilesOwnTheirSplitChannels() {
        XCTAssertEqual(AddSourceTile.safari.channelIds, ["safari-bookmarks", "safari-tabs"])
        XCTAssertEqual(AddSourceTile.chrome.channelIds, ["chrome-bookmarks"])
        XCTAssertEqual(AddSourceTile.forChannel("safari-tabs"), .safari)
        XCTAssertEqual(AddSourceTile.forChannel("safari-bookmarks"), .safari)
        XCTAssertEqual(AddSourceTile.forChannel("chrome-bookmarks"), .chrome)
        XCTAssertNil(AddSourceTile.forChannel("bookmarks"), "the legacy combined id is a backend read-time fallback, never a tile")
    }

    // MARK: - Logos (Task 13)

    /// Every tile that declares a brand-mark name must have a bundled PNG to
    /// back it up — a mapping with no matching `Resources/logos/*.png` would
    /// silently fall back to a generic SF Symbol at runtime (`LogoImage`'s own
    /// decode-tolerant path swallows the miss), so this is the only place that
    /// miss becomes a loud test failure instead.
    func testEveryDeclaredLogoNameResolvesToABundledImage() {
        for tile in AddSourceTile.allCases {
            guard let name = tile.logoName else { continue }
            XCTAssertTrue(
                LogoImage.exists(name: name),
                "\(tile.rawValue) declares logo \"\(name)\" but no bundled Resources/logos/\(name).png exists"
            )
        }
    }

    /// The eight platforms Task 13 fetched real brand marks for. Locks the
    /// catalog against a future edit accidentally dropping a tile back to nil
    /// (which `testEveryDeclaredLogoNameResolvesToABundledImage` alone
    /// wouldn't catch — `nil` trivially "passes" that loop).
    func testTheEightBrandedPlatformsAllDeclareALogo() {
        let expected: [AddSourceTile: String] = [
            .instagram: "instagram", .youtube: "youtube", .pinterest: "pinterest",
            .reddit: "reddit", .tiktok: "tiktok", .linkedin: "linkedin",
            .x: "x", .telegram: "telegram",
        ]
        for (tile, name) in expected {
            XCTAssertEqual(tile.logoName, name, tile.rawValue)
        }
    }

    /// Chat export (two vendors), a local file pick, a pasted link and the
    /// calendar keep their SF Symbol — no single brand mark exists for any of
    /// them (R3: the Commons calendar icon is *Google* Calendar, and this row
    /// is any ICS publisher). Safari and Apple Notes are nil for a different
    /// reason: R-L3 forbids redistributing Apple's marks, so they resolve
    /// through `appBundleId` instead.
    func testTilesWithNoSingleBrandMarkDeclareNoLogo() {
        for tile in [AddSourceTile.chatExport, .bookmarksFile, .pasteLink, .calendar,
                     .safari, .appleNotes] {
            XCTAssertNil(tile.logoName, tile.rawValue)
        }
        XCTAssertEqual(AddSourceTile.chrome.logoName, "chrome")
        XCTAssertEqual(AddSourceTile.rssFeed.logoName, "rss")
    }

    // MARK: - Installed app icons (R-L1, Track L)

    /// R-L1 — the browsers and Apple Notes wear the installed app's icon in
    /// the catalog too, so the `+` sheet, Integrations and the Sleep desk
    /// cannot disagree about what Safari looks like. The MAP is asserted,
    /// never the resolution: the suite must pass on a machine with no Chrome
    /// (R6).
    func testBrowserAndAppleTilesDeclareTheirBundleId() {
        XCTAssertEqual(AddSourceTile.safari.appBundleId, "com.apple.Safari")
        XCTAssertEqual(AddSourceTile.chrome.appBundleId, "com.google.Chrome")
        XCTAssertEqual(AddSourceTile.appleNotes.appBundleId, "com.apple.Notes")
        XCTAssertNil(AddSourceTile.telegram.appBundleId)
    }
}
