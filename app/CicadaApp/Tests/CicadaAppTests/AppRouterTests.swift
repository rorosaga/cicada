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
}
