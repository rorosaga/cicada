import AppKit
import Foundation

/// G126 R9 — the Feed hand-off. CLAUDE.md's Companion App section confirms
/// "The app has no NotificationCenter-based cross-window messaging today";
/// this is a small `@Observable` class injected via `.environment`, matching
/// how every other cross-view-model coordination in this app already works
/// (thin observed classes, not notifications), so an Integrations row's
/// "Import in Feed →" can switch the page to Feed AND stage that tile for the
/// `+` sheet without either view knowing about the other directly.
///
/// Settings is a panel in the main window now (DR-33); the hand-offs remain
/// because a panel page still routes to a page, and every hand-off closes the
/// panel (R-DS24).
@Observable
@MainActor
final class AppRouter {
    var pendingTab: AppTab?
    var pendingAddSource: AddSourceTile?
    /// G117 — Settings → General's "Run setup again" hand-off. The panel's
    /// pages cannot flip `showFirstRun` on `ContentView` themselves (same
    /// reason `pendingTab` exists for G126 R9's Feed hand-off), so they stage a
    /// flag here and `ContentView` is the one that actually presents the
    /// Welcome.
    var pendingFirstRun = false
    /// Track Z §7.1 — a Sleep spine's "Open in Sources ›". The source id rides
    /// with the tab switch, like the Feed hand-off, and `SourcesPageView`
    /// consumes it once it is on screen.
    var pendingSourceDetail: String?

    /// Sets both fields together — a `pendingAddSource` with no matching
    /// tab-switch would stage a sheet nobody ever sees, since `FeedPage`
    /// only consumes it once it's actually on screen.
    func routeToFeedAddSource(_ tile: AddSourceTile) {
        closeSettings()
        pendingTab = .feed
        pendingAddSource = tile
        activateMainWindow()
    }

    /// Sets both fields together, for the same reason `routeToFeedAddSource`
    /// does: a staged source with no tab switch would never be consumed.
    func routeToSourceDetail(_ sourceID: String) {
        closeSettings()
        pendingTab = .sources
        pendingSourceDetail = sourceID
        activateMainWindow()
    }

    /// R-DL16 — a saved item opened from the palette or a source's page lands in the Feed's detail column (DR-30's
    /// landing rule), by media entity id — the key both of them hold.
    var pendingFeedItem: String?

    func routeToFeedItem(_ mediaEntityId: String) {
        closeSettings()
        pendingTab = .feed
        pendingFeedItem = mediaEntityId
        activateMainWindow()
    }

    @discardableResult
    func consumeFeedItem() -> String? {
        defer { pendingFeedItem = nil }
        return pendingFeedItem
    }

    /// R-DL15 — a saved item's "About" name opens that page's card in Clusters; the tab and the entity move together,
    /// for `routeToFeedAddSource`'s reason.
    func routeToClustersEntity(_ id: String) {
        closeSettings()
        pendingTab = .clusters
        pendingClustersEntity = id
        activateMainWindow()
    }

    /// G141 PJ-5 (R-PP24) — a project opened from elsewhere (a ⌘K entity row) lands in the Projects page's detail
    /// column; the tab and the id move together, `routeToFeedItem`'s reason.
    var pendingProject: String?

    func routeToProject(_ id: String) {
        closeSettings()
        pendingTab = .projects
        pendingProject = id
        activateMainWindow()
    }

    /// Read-then-clear, for `consumeAddSource`'s double-firing reason (`onAppear` and `onChange` can both see it).
    @discardableResult
    func consumeProject() -> String? {
        defer { pendingProject = nil }
        return pendingProject
    }

    /// G150 (R-B25) — a backlog item opened from ⌘K: Projects, its project open, the item in the third column. The
    /// item is set before the project, so the page's `pendingProject` observer finds both.
    var pendingBacklogItem: String?

    func routeToBacklogItem(project: String, item: String) {
        pendingBacklogItem = item
        routeToProject(project)
    }

    /// Read-then-clear, `consumeProject`'s reason.
    @discardableResult
    func consumeBacklogItem() -> String? {
        defer { pendingBacklogItem = nil }
        return pendingBacklogItem
    }

    /// R-PP18 — a quiet thread's "How did it go? ›" opens its follow-up's card in the Inbox; the Inbox owns answering
    /// and its Undo (DR-42). The tab and the item move together.
    func routeToInboxItem(_ id: String) {
        closeSettings()
        pendingTab = .inbox
        pendingInboxItem = id
        activateMainWindow()
    }

    /// Track P R7 — every hand-off to a page goes through the router, so no
    /// view can stage a flag and forget to bring the window forward. Staging
    /// alone left the person looking at another window while the tab switched
    /// on one behind it, and the button read as broken.
    ///
    /// Returns whether a main window was found: ⌘, (R-DS23) opens one when
    /// the app is living in the menu bar with none open.
    @discardableResult
    func activateMainWindow() -> Bool {
        // `AppRouterTests.testRouteToFeedStagesTileAndTab` and
        // `testConsumeClearsAfterOneRead` already call
        // `routeToFeedAddSource`, which now reaches this method — and
        // `NSApplication.shared` INSTANTIATES NSApp on first touch, which a
        // headless `swift test` process must never be made to do. Reading the
        // `NSApp` global does not create it, so this guard makes the method a
        // no-op in the suite while staying a straight-line call in the app,
        // where the launch path has already brought NSApp up.
        guard let app = NSApp else { return false }
        app.activate(ignoringOtherApps: true)
        let target = app.windows.first {
            Self.isMainWindow(identifier: $0.identifier?.rawValue, title: $0.title,
                              canBecomeKey: $0.canBecomeKey, isPanel: $0 is NSPanel)
        }
        target?.makeKeyAndOrderFront(nil)
        return target != nil
    }

    /// SwiftUI's own `openWindow(id: CicadaApp.mainWindowID)`, handed over by `ShellCommands` — the one SwiftUI
    /// context that exists with no window open (R-DS23 already opens the window from there for ⌘,).
    @ObservationIgnored private var openMainWindowAction: (@MainActor () -> Void)?

    func adoptOpenMainWindow(_ action: @escaping @MainActor () -> Void) { openMainWindowAction = action }

    /// R-OB18 — the menu bar's Open Cicada, a Dock open and a reminder tap: the window forward, or a new one when a
    /// quiet login start (or the person) closed it. Marks the person's ask first, so a login record that lands late
    /// never closes the window they just asked for.
    /// `nil` means `LaunchState.shared`, resolved inside: a `.shared` default argument is evaluated in a
    /// nonisolated context, which Swift 6 refuses for a main-actor static.
    func showMainWindow(launch: LaunchState? = nil) {
        (launch ?? .shared).userAskedForWindow()
        if !activateMainWindow() { openMainWindowAction?() }
    }

    /// Pure so it can be tested — an `NSWindow` cannot be stood up in the
    /// XCTest target. SwiftUI stamped its old Settings scene's window with the
    /// `com_apple_SwiftUI_Settings_window` identifier and the localised title
    /// "Settings"; both are still refused because neither was contractual and
    /// the check costs nothing.
    ///
    /// No Settings window exists since DR-33. A menu-bar popover's window is an
    /// `NSPanel` that can linger in `NSApp.windows`, and it must never pass for
    /// the main window, or ⌘, would "find" it instead of reopening the window
    /// (R-DS23).
    static func isMainWindow(identifier: String?, title: String, canBecomeKey: Bool, isPanel: Bool = false) -> Bool {
        guard canBecomeKey, !isPanel else { return false }
        if (identifier ?? "").localizedCaseInsensitiveContains("settings") { return false }
        if title.localizedCaseInsensitiveCompare("settings") == .orderedSame { return false }
        return true
    }

    /// G117's "Run setup again" hand-off, paired with its activation for the
    /// same reason `routeToFeedAddSource` is: `ContentView` presents the sheet
    /// on the MAIN window, so staging the flag from Settings without ordering
    /// that window front shows the sheet behind the window you are looking at.
    func requestFirstRun() {
        closeSettings()
        pendingFirstRun = true
        activateMainWindow()
    }

    // MARK: DR-33 — the Settings panel (R-DS21 … R-DS24)

    /// Whether the panel covers the main window. `ContentView` draws it; the shell goes inert
    /// under it (R-DS21).
    var settingsOpen = false
    /// A section (and row) to land on, carried by a nonce so the same link twice re-lands.
    var pendingSettings: SettingsRequest?

    /// The ONE door into Settings (R-DS22): `SettingsSectionLink`, the rail's gear and ⌘, all
    /// call this. Returns whether a main window was found to show it in — ⌘, opens one when not.
    @discardableResult
    func openSettings(_ section: SettingsSection? = nil, row: SettingsRowID? = nil) -> Bool {
        pendingSettings = SettingsRequest(section: section, row: row)
        settingsOpen = true
        return activateMainWindow()
    }

    func closeSettings() {
        settingsOpen = false
        pendingSettings = nil
    }

    /// Read-then-clear, for the double-firing reason `consumeAddSource` states.
    @discardableResult
    func consumeSettings() -> SettingsRequest? {
        defer { pendingSettings = nil }
        return pendingSettings
    }

    // MARK: G136 — the find palette's hand-offs

    /// ⌘K (from any window, through `FindCommands`) and every "Search all of
    /// memory for …" row stage a request; `ContentView` opens or closes the
    /// palette (round-3 design §1.4). The request carries a nonce, so two ⌘K
    /// presses are two changes.
    var pendingPalette: PaletteRequest?
    /// A palette inbox row lands on its card, expanded (design §3.3).
    var pendingInboxItem: String?
    /// A palette entity row's ⌥⏎ opens it in Clusters (design §3.3).
    var pendingClustersEntity: String?
    /// Until the Reader lands (R-SU18), a conversation row opens its source's
    /// conversations filtered to its title; `HarnessConversationsView` reads this.
    var pendingConversationQuery: String?

    func requestPalette(prefill: String = "", mode: FindMode = .find) {
        pendingPalette = PaletteRequest(prefill: prefill, mode: mode)
        activateMainWindow()
    }

    @discardableResult
    func consumePalette() -> PaletteRequest? {
        defer { pendingPalette = nil }
        return pendingPalette
    }

    @discardableResult
    func consumeInboxItem() -> String? {
        defer { pendingInboxItem = nil }
        return pendingInboxItem
    }

    @discardableResult
    func consumeClustersEntity() -> String? {
        defer { pendingClustersEntity = nil }
        return pendingClustersEntity
    }

    @discardableResult
    func consumeConversationQuery() -> String? {
        defer { pendingConversationQuery = nil }
        return pendingConversationQuery
    }

    /// Reads then clears in one call so a caller (`FeedPage.onAppear` AND
    /// its `onChange(of: router.pendingAddSource)`, which can both fire for
    /// the same hand-off) can never re-consume a stale tile.
    @discardableResult
    func consumeAddSource() -> AddSourceTile? {
        defer { pendingAddSource = nil }
        return pendingAddSource
    }

    /// G139 — Settings → You → "Show on graph". Stages the entity with the
    /// tab switch, like the Feed hand-off; `ContentView` reveals it (G123).
    var pendingRevealEntity: String?

    func routeToEntity(_ id: String) {
        closeSettings()
        pendingTab = .graph
        pendingRevealEntity = id
        activateMainWindow()
    }

    /// Read-then-clear, for the reason `consumeAddSource` is.
    @discardableResult
    func consumeRevealEntity() -> String? {
        defer { pendingRevealEntity = nil }
        return pendingRevealEntity
    }

    /// Read-then-clear, for the same double-firing reason as `consumeAddSource`
    /// (`SourcesPageView.onAppear` and its `onChange` can both see one hand-off).
    @discardableResult
    func consumeSourceDetail() -> String? {
        defer { pendingSourceDetail = nil }
        return pendingSourceDetail
    }
}

/// A request to open Settings, optionally on a section and a row (R-DS22).
struct SettingsRequest: Equatable {
    var section: SettingsSection?
    var row: SettingsRowID?
    var nonce = UUID()
}
