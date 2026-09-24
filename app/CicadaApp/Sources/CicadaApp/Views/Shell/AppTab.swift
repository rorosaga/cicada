import SwiftUI

/// The eight primary views. Raw values are this tab's **stable identity** —
/// the persisted selection (`cicada.selectedTab`) and the ⌘-slot order in
/// `allCases` — so a surviving tab's raw value must never move, even when its
/// label changes.
///
/// G108 (ruled 2026-09-23, spec decision 12): Home is the front door at ⌘1,
/// so a fresh install opens on it. A stored selection is still restored, so
/// an existing user reopens where they were — nobody who lives in the graph
/// is moved (R-IB2).
///
/// G68 retired five tabs: Capture merged into Feed, Contributors + Usage
/// merged into Activity, and Connections + Connect became Settings tabs
/// (⌘,). G124 then replaced Activity with Sources. All six retired raw values
/// still sit in some user's defaults, so decode through `restored(from:)` —
/// never `AppTab(rawValue:)!`.
///
/// DR-53 — outline glyphs; the rail is `NavRail`.
enum AppTab: String, CaseIterable {
    case home = "Home"
    case graph = "Graph"
    case clusters = "Clusters"
    case feed = "Feed"
    case sleep = "Sleep"
    case inbox = "Inbox"
    case sources = "Sources"
    /// G141 PJ-5 — the eighth page, ⌘8 (owner ruling 2026-09-23: the first free cell after Sources, so no existing
    /// shortcut moves; DESIGN_RULES §9, DR-22). A new raw value, so `restored(from:)` needs no mapping.
    case projects = "Projects"

    /// Decodes a persisted selection, mapping every retired tab to whichever
    /// page inherited its content. Anything unrecognised falls back to Home.
    static func restored(from raw: String?) -> AppTab {
        guard let raw, !raw.isEmpty else { return .home }
        if let tab = AppTab(rawValue: raw) { return tab }
        switch raw {
        case "Capture": return .feed
        case "Activity", "Contributors", "Usage": return .sources   // G124: Activity → Sources
        case "Connections", "Connect": return .graph   // now Settings tabs (⌘,)
        default: return .home
        }
    }

    var icon: String {
        switch self {
        case .home: "house"
        case .graph: "point.3.connected.trianglepath.dotted"
        case .clusters: "circle.grid.2x2"
        case .feed: "photo.stack"
        case .sleep: "moon"
        case .inbox: "tray"
        case .sources: "tray.2"
        case .projects: "point.topleft.down.to.point.bottomright.curvepath"
        }
    }

    /// The label the user sees. Identical to `rawValue` since G68 — the two
    /// renamed pages (Plans & keys, Agents) are Settings tabs now, not rows.
    var title: String { rawValue }
}

extension AppTab {
    /// DR-31 / R-DL7 — pages that draw the Reader as their own rightmost progressive column; `ShellReaderHost` draws
    /// it for every other page. Grows as each list page's D track lands, and Projects (G141 PJ-5).
    var hostsOwnReader: Bool {
        switch self {
        case .inbox, .clusters, .feed, .sources, .projects: true
        default: false
        }
    }
}
