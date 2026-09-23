import Foundation

/// The two actions a channel source's card and its full page can both run
/// (Track D — "the card and the page share one implementation", so tapping
/// Sync now from the grid and from `ChannelSourceView` do the identical
/// thing). `sync` delegates to `BrowserImportActions.syncChannel` — the
/// existing browser-file read-and-post path stays exactly where it is (the
/// app reads `~/Library`, the launchd backend never does; R-D4) — except for a
/// watched browser, which goes through `BrowserWatcher.syncNow` (Track I T1).
/// `poll` is
/// `ChannelSourceView`'s former private `pollNow`, moved here byte-for-byte:
/// its gate message is what a user-initiated poll shows when
/// `CICADA_ALLOW_FEED_FETCH` is off, and the card's toast and the page's
/// feedback line must read identically.
@MainActor
enum ChannelActions {
    /// Track I T1 (R-IA2): a Sync now on a watched browser IS the consent, so it
    /// goes through `BrowserWatcher.syncNow` — one sync, recorded, watch live.
    /// Before, it went around the watcher: the browser stayed un-consented as
    /// far as the watch knew, and the watcher re-read the whole file on its
    /// next event. Unwatched channels (iCloud tabs, Notes' own route) are
    /// unchanged. `watcher` is optional only so a caller without one still
    /// syncs; every view caller passes the environment's.
    static func sync(_ channelId: String, store: Store, watcher: BrowserWatcher?) async throws -> String {
        if let watcher, BrowserWatcher.isWatched(channelId) {
            return try await watcher.syncNow(channelId)
        }
        return try await BrowserImportActions.syncChannel(channelId, store: store)
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
