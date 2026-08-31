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
        XCTAssertEqual(AddSourceTile.browserBookmarks.route, .sync)
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

    /// X has no backend channel to resolve state against (its `channelIds` is
    /// deliberately empty), so it must never claim to be reachable via
    /// "Connect" — the flow behind that button leads nowhere until a later
    /// task wires the connector up.
    func testXReadsComingSoonRatherThanADeadConnectButton() {
        let state = AddSourceTile.tileState(.x, channels: [])
        XCTAssertEqual(state.badge, "Coming soon")
        XCTAssertFalse(state.connected)
        XCTAssertNil(state.detail)
    }

    /// Even a channels payload that unexpectedly carried an "x" row (a
    /// misconfigured backend, a copy-paste bug) can't flip this — X's tile
    /// has no channel id to match against, on purpose.
    func testXStaysComingSoonEvenIfAStrayXChannelAppears() {
        let state = AddSourceTile.tileState(.x, channels: [channel("x", connected: true)])
        XCTAssertEqual(state.badge, "Coming soon")
        XCTAssertFalse(state.connected)
    }

    // MARK: - Coverage

    func testEveryPlatformInTheSpecHasATile() {
        let ids = Set(AddSourceTile.allCases.map(\.rawValue))
        for expected in ["instagram", "youtube", "pinterest", "reddit", "tiktok",
                         "linkedin", "x", "browserBookmarks", "appleNotes", "rssFeed",
                         "calendar", "telegram", "pasteLink", "bookmarksFile"] {
            XCTAssertTrue(ids.contains(expected), "missing tile: \(expected)")
        }
    }

    func testTheRetiredCombinedTileIsGone() {
        XCTAssertNil(AddSourceTile(rawValue: "savedContent"))
    }
}
