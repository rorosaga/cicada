import SwiftUI

/// The nine primary views (Looks went on 2026-10-20: a look lives on the page of the thing it shows; Agents took its ⌘9 on 2026-10-22). Raw values are this tab's **stable identity** —
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
/// The Sleep redesign (owner, 2026-10-16, ⌘ map A) retired the Feed: what came in is Sleep's Saved tab now, and
/// Skills took the Feed's cell — ⌘4 — so no other shortcut moved. "Feed" (and "Capture", which led to it) restore
/// to Sleep.
///
/// DR-53 — outline glyphs; the rail is `NavRail`.
enum AppTab: String, CaseIterable {
    case home = "Home"
    case graph = "Graph"
    case clusters = "Clusters"
    /// The Skills page (owner, 2026-10-15) — ⌘4 since the Sleep redesign (owner, 2026-10-16, ⌘ map A): it took the
    /// retired Feed's cell, so nothing else moves (DR-22). Its raw value never moved, so a stored selection restores.
    case skills = "Skills"
    case sleep = "Sleep"
    case inbox = "Inbox"
    case sources = "Sources"
    /// G141 PJ-5 — the eighth page, ⌘8 (owner ruling 2026-09-23: the first free cell after Sources, so no existing
    /// shortcut moves; DESIGN_RULES §9, DR-22). A new raw value, so `restored(from:)` needs no mapping.
    case projects = "Projects"
    /// Ruling 36 D6 / G217 — the ninth page, ⌘9: every agent that reads and writes Cicada, by provider umbrella (it was
    /// the Agents page). Appended so no existing shortcut moves (DR-22). A new raw value; a saved Settings
    /// `"agents"` section lands here through `SettingsSection.retired`.
    case agents = "Agents"
    /// G218 (owner 2026-10-26) — activity traces' own page: the day's timeline and its screenshots behind Touch ID.
    /// Appended, the tenth page, so no shortcut moves (DR-22) and it has no ⌘ digit (`RailItem.keyDigit`). Shown only
    /// while traces are on or were ever on (`TracesPageVisibility`); otherwise Sources keeps the switch.
    case traces = "Traces"

    /// Decodes a persisted selection, mapping every retired tab to whichever
    /// page inherited its content. Anything unrecognised falls back to Home.
    static func restored(from raw: String?) -> AppTab {
        guard let raw, !raw.isEmpty else { return .home }
        if let tab = AppTab(rawValue: raw) { return tab }
        switch raw {
        case "Feed", "Capture": return .sleep   // the Sleep redesign (2026-10-16): the Feed is Sleep's Saved tab
        case "Activity", "Contributors", "Usage": return .sources   // G124: Activity → Sources
        // Looks on pages (owner 2026-10-20): the board went; its looks live on their pages, and Clusters filters to
        // the pages that have them.
        case "Looks": return .clusters
        case "Connections", "Connect": return .graph   // now Settings tabs (⌘,)
        default: return .home
        }
    }

    var icon: String {
        switch self {
        case .home: "house"
        case .graph: "point.3.connected.trianglepath.dotted"
        case .clusters: "circle.grid.2x2"
        case .sleep: "moon"
        case .inbox: "tray"
        case .sources: "tray.2"
        case .projects: "point.topleft.down.to.point.bottomright.curvepath"
        case .skills: "puzzlepiece.extension"
        case .agents: "powerplug"   // looks pass 2026-10-23: `cable.connector` is a solid glyph among outlines (DR-53)
        case .traces: "timeline.selection"
        }
    }

    /// The label the user sees. Identical to `rawValue` since G68 — the two
    /// renamed pages (Plans & keys, Agents) are Settings tabs now, not rows.
    var title: String { rawValue }
}

extension AppTab {
    /// DR-31 / R-DL7 — pages that draw the Reader as their own rightmost progressive column; `ShellReaderHost` draws
    /// it for every other page. Grows as each list page's D track lands, and Projects (G141 PJ-5). Sleep since the
    /// Feed folded into it (2026-10-16): a saved item's detail sits beside its list, the Reader beside both.
    var hostsOwnReader: Bool {
        switch self {
        case .inbox, .clusters, .sleep, .sources, .projects, .skills: true
        default: false
        }
    }
}

/// Pages that can be hidden without deleting them (owner 2026-10-26). One switch per page; code and data stay.
enum PageSwitches {
    /// Owner 2026-10-26: "The Projects page really doesn't convince me. Hide it for now — some detected projects
    /// aren't even mine." Off until the redesign (G141's row in docs/goals/memory-evolution.md). Turning it back on is
    /// this one value: the rail, ⌘K, a project's ⌘K row, the tour and every hand-off read it. Back on with the
    /// redesign (ruling 45, 2026-10-27): the list is the person's own, everything detected is suggested.
    static let projectsPage = true
    /// Ruling 48 (2), owner 2026-10-28 — the Inbox left the rail (its questions live on Home and on each page). DR-73's
    /// flag for this screen: `true` brings its cell and ⌘6 back; nothing else reads it.
    static let inboxOnRail = false
}

extension AppTab {
    /// The rail's cells and ⌘K's "Go to" rows, in `allCases` order — so a hidden page leaves its ⌘ digit unused
    /// rather than moving another page's (DR-22).
    static func shown(tracesPage: Bool, projectsPage: Bool = PageSwitches.projectsPage) -> [AppTab] {
        allCases.filter { $0.onRail && $0.landing(tracesPage: tracesPage, projectsPage: projectsPage) == $0 }
    }

    /// Ruling 48 (2), owner 2026-10-28 — the Inbox left the rail: its questions live on Home and on each page, and the
    /// full grouped list is a Home sub-view ("All N questions", Esc back). The page stays a destination — ⌘K, the menu
    /// bar, a notification and Home's own links still land on it — but it draws no cell, and ⌘6 is left unused (DR-22:
    /// no other digit moves).
    var onRail: Bool { self != .inbox || PageSwitches.inboxOnRail }

    /// The rail cell that reads as selected while this page shows: the Inbox is Home's sub-view, so Home's cell.
    var railCell: AppTab { onRail ? self : .home }

    /// Where a selection of this page lands: itself, or — for a hidden page — the page that holds its content now
    /// (Projects → Clusters, where project pages still are; Traces → Sources, where its switch is).
    func landing(tracesPage: Bool, projectsPage: Bool = PageSwitches.projectsPage) -> AppTab {
        switch self {
        case .projects where !projectsPage: .clusters
        case .traces where !tracesPage: .sources
        default: self
        }
    }
}

/// G218 (owner 2026-10-26) — whether the Traces page is on the rail: while traces are on, or once they were ever
/// turned on (consent given, or a day kept). A Wipe forgets it with everything else. Mirrored per viewer into
/// `UserDefaults` (`key`) by `ContentView` once the recorder has its answer, so the rail and ⌘K read it at launch
/// without waiting for the backend; losing it only hides the page until the recorder answers again.
enum TracesPageVisibility {
    static let key = "cicada.traces.pageShown"

    static func shown(settings: TraceSettings, status: TraceStoreStatus) -> Bool {
        settings.enabled || settings.consentedAt != nil || status.days > 0
    }

    static var stored: Bool { UserDefaults.standard.bool(forKey: key) }
}
