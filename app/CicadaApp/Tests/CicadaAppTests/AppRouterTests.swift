import XCTest
@testable import CicadaApp

/// G126 R9 — the Feed hand-off. `AppRouter` is a small `@Observable
/// @MainActor` class, not a `NotificationCenter` post: "Import in Feed →"
/// on an Integrations row stages a tile AND switches the tab together
/// (`routeToFeedAddSource`), and `consumeAddSource()` reads-then-clears in
/// one call so a caller can never re-consume a stale tile.
@MainActor
final class AppRouterTests: XCTestCase {

    func testRouteToFeedStagesTileAndTab() {
        let router = AppRouter()
        router.routeToFeedAddSource(.instagram)
        XCTAssertEqual(router.pendingTab, .feed)
        XCTAssertEqual(router.pendingAddSource, .instagram)
    }

    func testConsumeClearsAfterOneRead() {
        let router = AppRouter()
        router.routeToFeedAddSource(.youtube)
        XCTAssertEqual(router.consumeAddSource(), .youtube)
        XCTAssertNil(router.pendingAddSource)
        XCTAssertNil(router.consumeAddSource())
    }

    /// recent-work #8 — both Settings → main-window hand-offs only mutated a
    /// flag. `ContentView` consumes it on the MAIN window, but nothing
    /// activated the app or ordered that window front, so Settings stayed key
    /// and the button read as broken. Worse inside onboarding, where
    /// `FirstRunSheet` embeds `IntegrationsView` whole: the hand-off fired
    /// from inside a modal sheet that never dismissed.
    ///
    /// Which window is "main" is a pure predicate so it can be tested at all —
    /// an NSWindow cannot be stood up in this suite, and the app's existing
    /// `windows.first(where: { $0.canBecomeKey })` (`CicadaApp.swift:162`)
    /// happily returns the Settings window.
    func testIsMainWindowRejectsTheSettingsWindowAndAnythingUnkeyable() {
        XCTAssertTrue(AppRouter.isMainWindow(identifier: "SwiftUI-Window-1", title: "Cicada", canBecomeKey: true))
        XCTAssertFalse(AppRouter.isMainWindow(identifier: "com_apple_SwiftUI_Settings_window", title: "Settings", canBecomeKey: true))
        XCTAssertFalse(AppRouter.isMainWindow(identifier: nil, title: "Settings", canBecomeKey: true))
        XCTAssertFalse(AppRouter.isMainWindow(identifier: "SwiftUI-Window-1", title: "Cicada", canBecomeKey: false))
    }

    /// `requestFirstRun` exists so BOTH hand-offs go through the router and
    /// neither view can forget to bring the window forward (R7).
    func testRequestFirstRunStagesTheSheet() {
        let router = AppRouter()
        XCTAssertFalse(router.pendingFirstRun)
        router.requestFirstRun()
        XCTAssertTrue(router.pendingFirstRun)
    }
}
