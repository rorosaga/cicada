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

    /// Track Z §7.1 — a spine's "Open in Sources ›" stages the tab AND the
    /// source together, and the Sources page consumes it exactly once.
    func testRouteToSourceDetailStagesTheTabAndTheSourceOnce() {
        let router = AppRouter()
        router.routeToSourceDetail("harness:claude-code")
        XCTAssertEqual(router.pendingTab, .sources)
        XCTAssertEqual(router.consumeSourceDetail(), "harness:claude-code")
        XCTAssertNil(router.pendingSourceDetail)
        XCTAssertNil(router.consumeSourceDetail())
    }

    /// recent-work #8 — both Settings → main-window hand-offs only mutated a
    /// flag. `ContentView` consumes it on the MAIN window, but nothing
    /// activated the app or ordered that window front, so Settings stayed key
    /// and the button read as broken. Worse inside onboarding, where
    /// the retired first-run sheet embedded `IntegrationsView` whole: the
    /// hand-off fired from inside a modal sheet that never dismissed.
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
    /// G139 — Settings → You → "Show on graph" stages the tab and the entity
    /// together, and the entity is read-then-cleared like the Feed tile.
    func testRouteToEntityStagesTheGraphTabAndTheEntity() {
        let router = AppRouter()
        router.routeToEntity("alex-example")
        XCTAssertEqual(router.pendingTab, .graph)
        XCTAssertEqual(router.consumeRevealEntity(), "alex-example")
        XCTAssertNil(router.consumeRevealEntity(), "read-then-clear")
    }

    func testRequestFirstRunStagesTheSheet() {
        let router = AppRouter()
        XCTAssertFalse(router.pendingFirstRun)
        router.requestFirstRun()
        XCTAssertTrue(router.pendingFirstRun)
    }

    /// DR-33 / R-DS22 — one door into the panel; a request is read once.
    func testOpenSettingsStagesARequestAndOpensThePanel() {
        let router = AppRouter()
        router.openSettings(.sleep, row: .sleepRuns)
        XCTAssertTrue(router.settingsOpen)
        let request = router.consumeSettings()
        XCTAssertEqual(request?.section, .sleep)
        XCTAssertEqual(request?.row, .sleepRuns)
        XCTAssertNil(router.consumeSettings())
        XCTAssertTrue(router.settingsOpen, "consuming the request does not close the panel")
    }

    /// R-DS23 — a lingering menu-bar popover (an NSPanel) is never the main window, or ⌘,
    /// would "find" it instead of reopening the real one.
    func testAPanelIsNeverTheMainWindow() {
        XCTAssertFalse(AppRouter.isMainWindow(identifier: nil, title: "", canBecomeKey: true, isPanel: true))
        XCTAssertTrue(AppRouter.isMainWindow(identifier: nil, title: "", canBecomeKey: true))
    }

    func testTwoOpensOfOneSectionAreTwoRequests() {
        let router = AppRouter()
        router.openSettings(.integrations)
        let first = router.pendingSettings
        router.openSettings(.integrations)
        XCTAssertNotEqual(first, router.pendingSettings, "the nonce makes a second link re-land")
    }

    /// R-DS24 — anything that leaves the panel closes it.
    func testEveryHandOffToAPageClosesThePanel() {
        let hands: [(String, (AppRouter) -> Void)] = [
            ("feed", { $0.routeToFeedAddSource(.instagram) }), ("source", { $0.routeToSourceDetail("rss") }),
            ("entity", { $0.routeToEntity("alpha-project") }), ("setup", { $0.requestFirstRun() }),
        ]
        for (name, hand) in hands {
            let router = AppRouter()
            router.openSettings()
            hand(router)
            XCTAssertFalse(router.settingsOpen, name)
            XCTAssertNil(router.pendingSettings, name)
        }
    }
}
