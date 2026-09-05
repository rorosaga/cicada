import AppKit
import Foundation

/// G126 R9 — the Feed hand-off. CLAUDE.md's Companion App section confirms
/// "The app has no NotificationCenter-based cross-window messaging today";
/// this is a small `@Observable` class injected into both scenes via
/// `.environment`, matching how every other cross-view-model coordination in
/// this app already works (thin observed classes, not notifications), so an
/// Integrations row's "Import in Feed →" can switch the sidebar to Feed AND
/// stage that tile for the `+` sheet without either view knowing about the
/// other directly.
@Observable
@MainActor
final class AppRouter {
    var pendingTab: AppTab?
    var pendingAddSource: AddSourceTile?
    /// G117 — Settings → General's "Run setup again" hand-off. Settings is a
    /// separate window/scene from the main one (same reason `pendingTab`
    /// exists for G126 R9's Feed hand-off — Settings cannot just flip
    /// `showFirstRun` on `ContentView` itself), so it stages a flag here and
    /// `ContentView` is the one that actually presents the sheet.
    var pendingFirstRun = false

    /// Sets both fields together — a `pendingAddSource` with no matching
    /// tab-switch would stage a sheet nobody ever sees, since `FeedView`
    /// only consumes it once it's actually on screen.
    func routeToFeedAddSource(_ tile: AddSourceTile) {
        pendingTab = .feed
        pendingAddSource = tile
        activateMainWindow()
    }

    /// Track P R7 — every Settings → main-window hand-off goes through the
    /// router, so no view can stage a flag and forget to bring the window
    /// forward. Staging alone left the person looking at Settings while the
    /// tab switched on a window behind it, and the button read as broken.
    ///
    /// The app's existing "first window that can become key"
    /// (`CicadaApp.swift`'s menu-bar activation) is not good enough here: the
    /// Settings window satisfies it, and Settings is exactly the window we are
    /// trying to leave.
    func activateMainWindow() {
        // `AppRouterTests.testRouteToFeedStagesTileAndTab` and
        // `testConsumeClearsAfterOneRead` already call
        // `routeToFeedAddSource`, which now reaches this method — and
        // `NSApplication.shared` INSTANTIATES NSApp on first touch, which a
        // headless `swift test` process must never be made to do. Reading the
        // `NSApp` global does not create it, so this guard makes the method a
        // no-op in the suite while staying a straight-line call in the app,
        // where the launch path has already brought NSApp up.
        guard let app = NSApp else { return }
        app.activate(ignoringOtherApps: true)
        let target = app.windows.first {
            Self.isMainWindow(identifier: $0.identifier?.rawValue, title: $0.title, canBecomeKey: $0.canBecomeKey)
        }
        target?.makeKeyAndOrderFront(nil)
    }

    /// Pure so it can be tested — an `NSWindow` cannot be stood up in the
    /// XCTest target. SwiftUI stamps its Settings scene's window with the
    /// `com_apple_SwiftUI_Settings_window` identifier and the localised title
    /// "Settings"; both are checked because neither is contractual.
    static func isMainWindow(identifier: String?, title: String, canBecomeKey: Bool) -> Bool {
        guard canBecomeKey else { return false }
        if (identifier ?? "").localizedCaseInsensitiveContains("settings") { return false }
        if title.localizedCaseInsensitiveCompare("settings") == .orderedSame { return false }
        return true
    }

    /// G117's "Run setup again" hand-off, paired with its activation for the
    /// same reason `routeToFeedAddSource` is: `ContentView` presents the sheet
    /// on the MAIN window, so staging the flag from Settings without ordering
    /// that window front shows the sheet behind the window you are looking at.
    func requestFirstRun() {
        pendingFirstRun = true
        activateMainWindow()
    }

    /// Reads then clears in one call so a caller (`FeedView.onAppear` AND
    /// its `onChange(of: router.pendingAddSource)`, which can both fire for
    /// the same hand-off) can never re-consume a stale tile.
    @discardableResult
    func consumeAddSource() -> AddSourceTile? {
        defer { pendingAddSource = nil }
        return pendingAddSource
    }
}
