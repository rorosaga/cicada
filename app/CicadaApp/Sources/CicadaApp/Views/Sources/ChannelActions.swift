import Foundation

/// The two actions a channel source's card and its full page can both run
/// (Track D — "the card and the page share one implementation", so tapping
/// Sync now from the grid and from `ChannelSourceView` do the identical
/// thing). `sync` routes on `syncRoute(for:)`: the browser rows keep their
/// read-and-post path in `BrowserImportActions` (the app reads `~/Library`,
/// the launchd backend never does; R-D4), and a folder or Wispr Flow row goes
/// to the `LocalSourceWatcher` that owns its bookmark, manifest and cursor.
/// `poll` is `ChannelSourceView`'s former private `pollNow`, moved here
/// byte-for-byte: its gate message is what a user-initiated poll shows when
/// `CICADA_ALLOW_FEED_FETCH` is off, and the card's toast and the page's
/// feedback line must read identically.
@MainActor
enum ChannelActions {
    /// Which implementation a channel's "Sync now" runs.
    ///
    /// L final review (finding 1): the backend gives `folder:<id>` and
    /// `wispr-flow` the action `sync`, but every surface outside Settings →
    /// Integrations sent it to `BrowserImportActions.syncChannel`, whose
    /// `default:` threw "Unknown channel folder:…" — an internal id in the
    /// person's face on the source page and the Feed strip, and a silent no-op
    /// on the card. `notes` and the three connectors fell through the same
    /// way. One pure table now answers "who syncs this id", and
    /// `ChannelSyncRoutingTests` holds every id the registry can emit with
    /// `sync` to having an answer.
    enum SyncRoute: Equatable {
        case browserFile
        case notes
        case connector
        case folder(id: String)
        case wisprFlow
    }

    /// The browser rows whose files the app reads and posts (R1).
    static let browserFileChannels: Set<String> = ["safari-tabs", "safari-bookmarks", "chrome-bookmarks"]
    /// `api/services/connectors/__init__.py::ADAPTERS`.
    static let connectorChannels: Set<String> = ["pinterest", "reddit", "x"]
    static let folderPrefix = "folder:"

    static func syncRoute(for channelId: String) -> SyncRoute? {
        if browserFileChannels.contains(channelId) { return .browserFile }
        if connectorChannels.contains(channelId) { return .connector }
        if channelId == "notes" { return .notes }
        if channelId == LocalSourceWatcher.wisprChannel { return .wisprFlow }
        if channelId.hasPrefix(folderPrefix), channelId.count > folderPrefix.count {
            return .folder(id: String(channelId.dropFirst(folderPrefix.count)))
        }
        return nil
    }

    /// Whether this row's settings live in Settings → Integrations rather than
    /// behind a Feed `+` tile — a folder or Wispr Flow has no `AddSourceTile`,
    /// so "Manage…" on the Feed strip used to open the generic add-source
    /// sheet (L final review, finding 1).
    static func managesInIntegrations(_ channelId: String) -> Bool {
        switch syncRoute(for: channelId) {
        case .folder, .wisprFlow: true
        default: false
        }
    }

    static func sync(_ channelId: String, store: Store, local: LocalSourceWatcher) async throws -> String {
        switch syncRoute(for: channelId) {
        case .browserFile:
            return try await BrowserImportActions.syncChannel(channelId, store: store)
        case .notes:
            // Notes syncs server-side: osascript runs where the backend does.
            let r = try await APIClient.shared.syncNotes()
            return "\(r.new) new · \(r.skipped) unchanged"
        case .connector:
            return ConnectorSetupState.syncSummary(try await APIClient.shared.syncConnector(channelId))
        case .folder(let id):
            return try await local.syncNow(folderId: id)
        case .wisprFlow:
            return try await local.syncWisprNowReporting()
        case nil:
            throw BrowserImportActions.ImportActionError.failed("This source can't be synced from here.")
        }
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
