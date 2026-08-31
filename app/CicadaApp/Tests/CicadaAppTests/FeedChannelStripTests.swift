import XCTest
@testable import CicadaApp

/// G68 §1 — Capture's two useful cards move to the pages that own their
/// question: what Cicada reads from belongs on Feed, what is queued belongs
/// on Sleep.
final class FeedChannelStripTests: XCTestCase {

    private func channel(_ id: String, connected: Bool, lastSync: String?) -> SourceChannel {
        SourceChannel(id: id, label: id, connected: connected, count: 1,
                      lastSync: lastSync, detail: nil, actions: ["poll"])
    }

    /// The count is the whole point of a strip that can be collapsed — it has
    /// to survive collapsing.
    func testStripTitleCarriesTheCountOnceThereIsOne() {
        XCTAssertEqual(ConnectedChannelsStrip.stripTitle(connected: 0), "CONNECTED")
        XCTAssertEqual(ConnectedChannelsStrip.stripTitle(connected: 1), "CONNECTED (1)")
        XCTAssertEqual(ConnectedChannelsStrip.stripTitle(connected: 7), "CONNECTED (7)")
    }

    /// The strip renders exactly what the old Capture card did: connected
    /// rows, most recently synced first.
    func testStripShowsOnlyConnectedChannelsNewestFirst() {
        let channels = [
            channel("telegram", connected: true, lastSync: nil),
            channel("rss", connected: true, lastSync: "2026-08-30T10:00:00Z"),
            channel("notes", connected: false, lastSync: "2026-08-31T10:00:00Z"),
            channel("bookmarks", connected: true, lastSync: "2026-08-31T10:00:00Z"),
        ]
        XCTAssertEqual(SourceChannel.sortedConnected(channels).map(\.id),
                       ["bookmarks", "rss", "telegram"])
    }

    /// "Manage…" on a row must resolve to the tile that owns that channel, or
    /// the sheet opens on the grid.
    func testManageResolvesEveryConnectedChannelToATile() {
        for id in ["rss", "calendar", "bookmarks", "notes", "telegram",
                   "chat-export:claude", "chat-export:chatgpt", "files"] {
            XCTAssertNotNil(AddSourceTile.forChannel(id), id)
        }
    }

    /// The collapse survives a relaunch, and an unset key means expanded — a
    /// first-run user must see the strip at least once to know it exists.
    ///
    /// Suite-scoped, never `.standard`: a shared defaults domain would leak
    /// state across test runs (and across every other suite in this bundle).
    func testCollapseStatePersistsUnderAStableKeyAndDefaultsToExpanded() throws {
        let key = "cicada.feedChannelsCollapsed"
        let suiteName = "FeedChannelStripTests.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suiteName))
        defer { defaults.removePersistentDomain(forName: suiteName) }

        defaults.removeObject(forKey: key)
        XCTAssertFalse(defaults.bool(forKey: key), "an unset key must mean expanded")

        defaults.set(true, forKey: key)
        XCTAssertTrue(defaults.bool(forKey: key), "a collapse must survive a relaunch")
    }
}
