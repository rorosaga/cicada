import Foundation

/// How a platform actually gets into memory (G71 §4.1). The badge on each tile
/// is this, and nothing else — the user should be able to tell "I sign in here"
/// from "I drop a file here" without opening the tile.
enum ImportRoute: String {
    /// A direct API with credentials — Pinterest, Reddit.
    case connect
    /// A vendor data export the user downloads and drops.
    case importFile
    /// Read straight off this Mac — bookmarks, Apple Notes.
    case sync
    /// A URL Cicada re-checks — RSS, calendars.
    case subscribe
    /// One link, right now.
    case paste

    var badge: String {
        switch self {
        case .connect: return "Connect"
        case .importFile: return "Import file"
        case .sync: return "Sync"
        case .subscribe: return "Subscribe"
        case .paste: return "Save"
        }
    }
}

/// What one catalog tile renders, derived purely from the tile plus the current
/// channel snapshot — no view state, so it is unit-testable on its own.
///
/// Since the family layer landed in front of the tiles (Task 4, 2026-09-02
/// brief) this is read at two levels: the members grid renders it per tile
/// exactly as before, and the family tile above it counts `connected` over
/// its `ImportFamily.members` for its "n of m connected" footer. The state
/// itself is unchanged — a family has no channel of its own to resolve
/// against (R6), so it derives everything from its members.
struct ImportTileState: Equatable {
    let badge: String
    let connected: Bool
    let detail: String?
}

extension AddSourceTile {
    /// The channels this tile manages, resolved against a snapshot.
    private func channels(in channels: [SourceChannel]) -> [SourceChannel] {
        let ids = Set(channelIds)
        return channels.filter { ids.contains($0.id) }
    }

    /// The badge/connected/detail triple for one tile.
    ///
    /// A channel with a recorded `lastError` overrides the route badge with
    /// "Needs attention": a tile that still says "Connect" — or worse, shows a
    /// week-old success — while its nightly poll is 401-ing is the exact kind of
    /// quiet lie the transparency principle rules out.
    ///
    /// A Connect-route tile with no `channelIds` at all (none, currently —
    /// Pinterest, Reddit, and X all resolve against a live backend channel as
    /// of Task 14) has nothing to resolve state against, ever. Rather than
    /// show a "Connect" button that opens a flow leading nowhere, it would
    /// read "Coming soon" — driven by the same channels payload every other
    /// tile reads, just permanently absent from it. Kept here as the rail for
    /// whichever Connect-route tile lands next with its backend not yet wired.
    static func tileState(_ tile: AddSourceTile, channels: [SourceChannel]) -> ImportTileState {
        let mine = tile.channels(in: channels)
        if let failing = mine.first(where: { ($0.lastError ?? "").isEmpty == false }) {
            return ImportTileState(badge: "Needs attention", connected: failing.connected,
                                   detail: ChannelDetailLine.text(failing))
        }
        guard let live = mine.first(where: { $0.connected }) else {
            if tile.route == .connect, tile.channelIds.isEmpty {
                return ImportTileState(badge: "Coming soon", connected: false, detail: nil)
            }
            // M1 (final review): an UNconnected pay-per-use connector (X)
            // still carries a `detail` — its cost-honesty price note, set
            // even before the user connects
            // (channel_registry._connector_channel's `price_note` "stands in
            // for it entirely when there is otherwise none") — which must
            // reach the tile, not be discarded here.
            return ImportTileState(
                badge: tile.route.badge, connected: false,
                detail: mine.lazy.compactMap { ChannelDetailLine.text($0) }.first)
        }
        // R-S5 — the tile's line goes through the same composer as the Sources
        // page and the Feed row, or a connected connector would show
        // "synced 2026-08-30" with the count silently missing.
        return ImportTileState(badge: tile.route.badge, connected: true,
                               detail: ChannelDetailLine.text(live))
    }
}
