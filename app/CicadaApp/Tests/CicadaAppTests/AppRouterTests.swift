import XCTest
@testable import CicadaApp

/// G126 R9 — the hand-offs. `AppRouter` is a small `@Observable @MainActor` class, not a `NotificationCenter` post:
/// a row naming a source stages that source's page AND switches the tab together (`routeToAddSource`, G245: the
/// tile's own entry, `pendingCatalogEntry`), and every consumer reads-then-clears in one call so a caller can never
/// re-consume a stale hand-off.
@MainActor
final class AppRouterTests: XCTestCase {
    func testHomeFailureDetailsStagesSleepAndConsumesSectionOnce() {
        let router = AppRouter()
        router.routeToSleepDetails(.lastCycle)
        XCTAssertEqual(router.pendingTab, .sleep)
        XCTAssertEqual(router.consumeSleepDetails(), .lastCycle)
        XCTAssertNil(router.consumeSleepDetails())
    }

    /// G245 (ruling 78): nothing is "added" any more, so a tile's hand-off opens that source's own page, staged with the
    /// tab switch; an export tile with no entry of its own lands on Chat exports.
    func testRouteToAddSourceOpensTheTilesOwnSourcePage() {
        let router = AppRouter()
        router.routeToAddSource(.instagram)
        XCTAssertEqual(router.pendingTab, .sources, "G217: a tile opens its entry in the one catalogue, the Sources page")
        XCTAssertEqual(router.pendingCatalogEntry, "instagram")
        let youtube = AppRouter()
        youtube.routeToAddSource(.youtube)
        XCTAssertEqual(youtube.pendingCatalogEntry, "youtube")
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
        router.openSettings(.intelligence)
        let first = router.pendingSettings
        router.openSettings(.intelligence)
        XCTAssertNotEqual(first, router.pendingSettings, "the nonce makes a second link re-land")
    }

    /// R-DS24 — anything that leaves the panel closes it.
    func testEveryHandOffToAPageClosesThePanel() {
        let hands: [(String, (AppRouter) -> Void)] = [
            ("import", { $0.routeToAddSource(.instagram) }), ("videos", { $0.routeToVideos(choose: true) }), ("source", { $0.routeToSourceDetail("rss") }),
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

    /// G162 — the video picker's hand-off lands on Sleep (its Videos tab), read-then-clear.
    func testRouteToVideosStagesSleepAndThePickerOnce() {
        let router = AppRouter()
        router.routeToVideos(choose: true)
        XCTAssertEqual(router.pendingTab, .sleep)
        XCTAssertTrue(router.consumeVideoChooser())
        XCTAssertFalse(router.consumeVideoChooser())
    }

    func testRouteToSavedItemStagesTheItemAndTheTab() {
        let router = AppRouter()
        router.routeToSavedItem("media-example")
        XCTAssertEqual(router.pendingTab, .sleep, "Sleep › Saved holds a saved item since 2026-10-16")
        XCTAssertEqual(router.consumeSavedItem(), "media-example")
        XCTAssertNil(router.consumeSavedItem(), "read-then-clear")
        router.routeToClustersEntity("alpha-project")
        XCTAssertEqual(router.pendingTab, .clusters)
        XCTAssertEqual(router.consumeClustersEntity(), "alpha-project")
    }

    /// G150 (R-B25) — a palette landing carries the item to the Projects page with its project, read-then-clear.
    func testABacklogLandingCarriesTheItemWithItsProject() {
        let router = AppRouter()
        router.routeToBacklogItem(project: "rover-arm-project", item: "RAP3")
        XCTAssertEqual(router.pendingTab, .projects)
        XCTAssertEqual(router.consumeProject(), "rover-arm-project")
        XCTAssertEqual(router.consumeBacklogItem(), "RAP3")
        XCTAssertNil(router.consumeBacklogItem(), "read-then-clear")
    }
}
