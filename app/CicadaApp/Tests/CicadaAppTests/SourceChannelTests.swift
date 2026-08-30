import XCTest
@testable import CicadaApp

/// `GET /sources/channels` decoding + the Capture page's row ordering (G62).
final class SourceChannelTests: XCTestCase {

    private static let json = """
    {"channels":[
      {"id":"rss","label":"RSS feeds","connected":true,"count":3,
       "lastSync":"2026-08-30T08:12:00Z","detail":"3 feeds · polled 2026-08-30",
       "actions":["poll","manage"]},
      {"id":"calendar","label":"Calendars","connected":false,"count":0,
       "lastSync":null,"detail":null,"actions":["poll","manage"]},
      {"id":"bookmarks","label":"Chrome & Safari bookmarks","connected":true,"count":412,
       "lastSync":"2026-08-29T10:00:00Z","detail":"412 bookmarks · synced 2026-08-29",
       "actions":["sync"]},
      {"id":"telegram","label":"Telegram bot","connected":true,
       "detail":"Bot configured · 18 captures","actions":[]}
    ]}
    """

    private func decoded() throws -> [SourceChannel] {
        try JSONDecoder().decode(SourceChannelsResponse.self, from: Data(Self.json.utf8)).channels
    }

    func testDecodesEveryField() throws {
        let byId = Dictionary(uniqueKeysWithValues: try decoded().map { ($0.id, $0) })
        let rss = try XCTUnwrap(byId["rss"])
        XCTAssertEqual(rss.label, "RSS feeds")
        XCTAssertTrue(rss.connected)
        XCTAssertEqual(rss.count, 3)
        XCTAssertEqual(rss.lastSync, "2026-08-30T08:12:00Z")
        XCTAssertEqual(rss.detail, "3 feeds · polled 2026-08-30")
        XCTAssertEqual(rss.actions, ["poll", "manage"])
    }

    /// A backend that omits the optional fields (older build, or a channel with
    /// no state) must still decode — never drop the row.
    func testDecodesToleratesMissingOptionalFields() throws {
        let byId = Dictionary(uniqueKeysWithValues: try decoded().map { ($0.id, $0) })
        let telegram = try XCTUnwrap(byId["telegram"])
        XCTAssertEqual(telegram.count, 0)
        XCTAssertNil(telegram.lastSync)
        XCTAssertTrue(telegram.actions.isEmpty)
    }

    /// The Connected list shows only connected channels, newest sync first,
    /// with a null lastSync sorting last and ties broken by label.
    func testSortedConnectedDropsDisconnectedAndOrdersByLastSyncDesc() throws {
        let sorted = SourceChannel.sortedConnected(try decoded())
        XCTAssertEqual(sorted.map(\.id), ["rss", "bookmarks", "telegram"])
    }

    func testChannelsRoundTripThroughTheSnapshotCache() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let cache = SnapshotCache(root: root)
        let channels = try decoded()
        await cache.save(channels, etag: "\"c1\"", domain: .channels, bank: "work")
        await cache.flush()
        let hit = await cache.load(.channels, bank: "work", as: [SourceChannel].self)
        XCTAssertEqual(hit?.value.map(\.id), channels.map(\.id))
        XCTAssertEqual(hit?.etag, "\"c1\"")
    }
}

/// The "+" sheet must be able to explain every channel the backend can report
/// as connected — a channel with no tile is a dead end for the user (the row
/// appears, "Manage…" opens nothing).
final class AddSourceCatalogTests: XCTestCase {

    /// Mirrors api/services/channel_registry.py::CHANNEL_IDS.
    private static let backendChannelIds: Set<String> = [
        "chat-export:claude", "chat-export:chatgpt", "bookmarks", "notes",
        "rss", "calendar", "telegram", "files",
    ]

    func testEveryBackendChannelHasATile() {
        let covered = Set(AddSourceTile.allCases.flatMap(\.channelIds))
        XCTAssertEqual(Self.backendChannelIds.subtracting(covered), [],
                       "backend channels with no tile in the + sheet")
    }

    func testEveryTileHasTitleAndBlurb() {
        for tile in AddSourceTile.allCases {
            XCTAssertFalse(tile.title.isEmpty, tile.rawValue)
            XCTAssertFalse(tile.blurb.isEmpty, tile.rawValue)
            XCTAssertFalse(tile.icon.isEmpty, tile.rawValue)
        }
    }

    func testChannelIdsAreUniqueAcrossTiles() {
        let ids = AddSourceTile.allCases.flatMap(\.channelIds)
        XCTAssertEqual(Set(ids).count, ids.count, "two tiles claim the same channel")
    }
}
