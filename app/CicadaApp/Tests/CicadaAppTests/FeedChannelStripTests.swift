import XCTest
@testable import CicadaApp

/// G68 §1 — the connected-channel helpers the Feed's Connected strip used. The strip itself retired with the Feed
/// (2026-10-16: Sources holds every connected source and its Sync now); the two pure helpers stay true.
final class FeedChannelStripTests: XCTestCase {

    private func channel(_ id: String, connected: Bool, lastSync: String?) -> SourceChannel {
        SourceChannel(id: id, label: id, connected: connected, count: 1,
                      lastSync: lastSync, detail: nil, actions: ["poll"])
    }

    /// The strip renders exactly what the old Capture card did: connected
    /// rows, most recently synced first.
    func testStripShowsOnlyConnectedChannelsNewestFirst() {
        let channels = [
            channel("telegram", connected: true, lastSync: nil),
            channel("rss", connected: true, lastSync: "2026-08-30T10:00:00Z"),
            channel("notes", connected: false, lastSync: "2026-08-31T10:00:00Z"),
            channel("chrome-bookmarks", connected: true, lastSync: "2026-08-31T10:00:00Z"),
        ]
        XCTAssertEqual(SourceChannel.sortedConnected(channels).map(\.id),
                       ["chrome-bookmarks", "rss", "telegram"])
    }

    /// "Manage…" on a row must resolve to the tile that owns that channel, or
    /// the sheet opens on the grid.
    func testManageResolvesEveryConnectedChannelToATile() {
        for id in ["rss", "calendar", "chrome-bookmarks", "safari-bookmarks", "safari-tabs",
                   "notes", "telegram", "chat-export:claude", "chat-export:chatgpt", "chat-export:gemini",
                   "files"] {
            XCTAssertNotNil(AddSourceTile.forChannel(id), id)
        }
    }
}
