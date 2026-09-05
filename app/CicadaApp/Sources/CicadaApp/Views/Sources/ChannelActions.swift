import Foundation

/// The two actions a channel source's card and its full page can both run
/// (Track D — "the card and the page share one implementation", so tapping
/// Sync now from the grid and from `ChannelSourceView` do the identical
/// thing). `sync` delegates to `BrowserImportActions.syncChannel` — the
/// existing browser-file read-and-post path stays exactly where it is (the
/// app reads `~/Library`, the launchd backend never does; R-D4). `poll` is
/// `ChannelSourceView`'s former private `pollNow`, moved here byte-for-byte:
/// its gate message is what a user-initiated poll shows when
/// `CICADA_ALLOW_FEED_FETCH` is off, and the card's toast and the page's
/// feedback line must read identically.
@MainActor
enum ChannelActions {
    static func sync(_ channelId: String, store: Store) async throws -> String {
        try await BrowserImportActions.syncChannel(channelId, store: store)
    }

    /// A user-initiated poll still honours the backend's fetch gate: the
    /// result says so plainly instead of reporting "0 new" as if it had run.
    static func poll(_ channelId: String) async throws -> String {
        let disabled = "Live fetch is disabled on this backend — set CICADA_ALLOW_FEED_FETCH=1 and restart."
        if channelId == "calendar" {
            let r = try await APIClient.shared.pollCalendars()
            return r.skippedNoNetwork > 0 ? disabled : "\(r.new) new event(s)"
        }
        let r = try await APIClient.shared.pollFeeds()
        return r.skippedNoNetwork > 0 ? disabled : "\(r.new) new item(s)"
    }
}
