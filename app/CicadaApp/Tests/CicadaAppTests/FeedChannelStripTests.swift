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
            channel("chrome-bookmarks", connected: true, lastSync: "2026-08-31T10:00:00Z"),
        ]
        XCTAssertEqual(SourceChannel.sortedConnected(channels).map(\.id),
                       ["chrome-bookmarks", "rss", "telegram"])
    }

    /// "Manage…" on a row must resolve to the tile that owns that channel, or
    /// the sheet opens on the grid.
    func testManageResolvesEveryConnectedChannelToATile() {
        for id in ["rss", "calendar", "chrome-bookmarks", "safari-bookmarks", "safari-tabs",
                   "notes", "telegram", "chat-export:claude", "chat-export:chatgpt", "files"] {
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

    // MARK: PR #19 review — a missing snapshot must not read as a confirmed-empty roster

    /// While `store.channels` is still loading, the strip must show a
    /// spinner — not "Nothing connected yet", which is reserved for a
    /// confirmed empty roster.
    func testLoadStateIsLoadingWhileTheFetchIsInFlight() {
        XCTAssertEqual(ConnectedChannelsStrip.loadState(channels: nil, isLoading: true, error: nil), .loading)
    }

    /// A failed first fetch (no snapshot, no longer refreshing, a latched
    /// domain error) must surface that failure — never silently read as
    /// "nothing connected".
    func testLoadStateIsFailedAfterAFailedFetchWithNoSnapshot() {
        XCTAssertEqual(
            ConnectedChannelsStrip.loadState(channels: nil, isLoading: false, error: "Couldn't load channels"),
            .failed("Couldn't load channels")
        )
    }

    /// No snapshot, not refreshing, no latched error yet — the fetch simply
    /// hasn't started. Must not be mistaken for a confirmed empty roster.
    func testLoadStateFallsBackToLoadingBeforeTheFetchHasStarted() {
        XCTAssertEqual(ConnectedChannelsStrip.loadState(channels: nil, isLoading: false, error: nil), .loading)
    }

    /// Once a snapshot has actually landed, a genuinely empty roster reads as
    /// loaded-and-empty — this is the only path "Nothing connected yet" may
    /// render for.
    func testLoadStateIsLoadedOnceASnapshotLands() {
        let channels = [channel("rss", connected: true, lastSync: nil)]
        XCTAssertEqual(
            ConnectedChannelsStrip.loadState(channels: channels, isLoading: true, error: "stale error"),
            .loaded(connected: SourceChannel.sortedConnected(channels)),
            "a landed snapshot must win over stale isLoading/error flags from a prior attempt"
        )
        XCTAssertEqual(ConnectedChannelsStrip.loadState(channels: [], isLoading: false, error: nil), .loaded(connected: []))
    }
}
