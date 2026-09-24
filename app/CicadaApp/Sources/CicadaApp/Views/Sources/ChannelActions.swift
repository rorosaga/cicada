import Foundation

/// The two actions a channel source's card and its full page can both run
/// (Track D — "the card and the page share one implementation", so tapping
/// Sync now from the grid and from `ChannelSourceView` do the identical
/// thing). `sync` routes on `syncRoute(for:)`: the browser rows keep their
/// read-and-post path in `BrowserImportActions` (the app reads `~/Library`,
/// the launchd backend never does; R-D4), and a folder or Wispr Flow row goes
/// to the `LocalSourceWatcher` that owns its bookmark, manifest and cursor.
/// A watched browser goes through `BrowserWatcher.syncNow` (Track I T1).
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
        /// Round-4 G142: the Calendar app, read on this Mac by `CalendarReader` (EventKit) and posted whole.
        case calendarLocal
        /// Round 4 (G160): Chrome's open tab groups, read on this Mac by `TabGroupWatcher` behind its own switch.
        case tabGroups
    }

    /// The browser rows whose files the app reads and posts (R1): iCloud tabs, then every supported browser's
    /// bookmarks from `BrowserInventory` (round 4, C9) — one catalog, so a browser added there is routed here too.
    static let browserFileChannels: Set<String> = Set(["safari-tabs"] + BrowserInventory.catalog.compactMap(\.bookmarksChannel))
    /// `api/services/connectors/__init__.py::ADAPTERS`.
    static let connectorChannels: Set<String> = ["pinterest", "reddit", "x"]
    static let folderPrefix = "folder:"
    /// Round-4 G142 (C6): the backend lists `calendar-local` with `sync`; the app is the only reader of EventKit.
    static let calendarLocalChannel = "calendar-local"

    static func syncRoute(for channelId: String) -> SyncRoute? {
        if browserFileChannels.contains(channelId) { return .browserFile }
        if connectorChannels.contains(channelId) { return .connector }
        if channelId == "notes" { return .notes }
        if channelId == LocalSourceWatcher.wisprChannel { return .wisprFlow }
        if channelId == calendarLocalChannel { return .calendarLocal }
        if channelId == TabGroupWatcher.channel { return .tabGroups }
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
        case .folder, .wisprFlow, .tabGroups: true
        default: false
        }
    }

    /// Track I T1 (R-IA2): a Sync now on a watched browser IS the consent, so it
    /// goes through `BrowserWatcher.syncNow` — one sync, recorded, watch live.
    /// Before, it went around the watcher: the browser stayed un-consented as
    /// far as the watch knew, and the watcher re-read the whole file on its
    /// next event. `watcher` is optional only so a caller without one still
    /// syncs; every view caller passes the environment's.
    ///
    /// Round 4 (R-SR11): a sync the person stopped with the row's × comes back as
    /// `Copy.syncStopped` — said as a stop, never as an error.
    static func sync(_ channelId: String, store: Store, watcher: BrowserWatcher? = nil,
                     local: LocalSourceWatcher, calendar: CalendarReader? = nil,
                     tabGroups: TabGroupWatcher? = nil) async throws -> String {
        do {
            return try await route(channelId, store: store, watcher: watcher, local: local, calendar: calendar,
                                   tabGroups: tabGroups)
        } catch let error where SyncCancellation.isCancellation(error) {
            return Copy.syncStopped   // R-SR11: a stop is said as a stop, never as an error
        }
    }

    private static func route(_ channelId: String, store: Store, watcher: BrowserWatcher?,
                              local: LocalSourceWatcher, calendar: CalendarReader?,
                              tabGroups: TabGroupWatcher?) async throws -> String {
        switch syncRoute(for: channelId) {
        case .browserFile:
            if let watcher, BrowserWatcher.isWatched(channelId) {
                return try await watcher.syncNow(channelId)
            }
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
        case .calendarLocal:
            // The backend never reads EventKit (the ~/Library rail): Sync now runs the app's reader, and only
            // after the person connected Calendar — never a silent first read from a Sources card.
            guard let calendar, calendar.isEnabled else {
                throw BrowserImportActions.ImportActionError.failed(Copy.calendarConnectFirst)
            }
            await calendar.syncNow()
            switch calendar.status {
            case .failed(let why): throw BrowserImportActions.ImportActionError.failed(why)
            case .denied: throw BrowserImportActions.ImportActionError.failed(Copy.calendarConnectFirst)
            case .synced(_, let events): return Copy.calendarSyncedSummary(events)
            default: return Copy.calendarSyncedSummary(nil)
            }
        case .tabGroups:
            // Never a first read from a card: the switch in Integrations is the consent (R-SR3).
            guard let tabGroups, tabGroups.enabled else {
                throw BrowserImportActions.ImportActionError.failed(Copy.tabGroupsTurnOnFirst)
            }
            return try await tabGroups.syncNow()
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
