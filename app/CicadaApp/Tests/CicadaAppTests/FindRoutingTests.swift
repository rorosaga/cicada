import XCTest
@testable import CicadaApp

/// G136 — the router hand-offs the palette stages. Each is read-then-clear,
/// like `consumeAddSource`, so an `onAppear` and an `onChange` that both see
/// one hand-off can never consume it twice.
@MainActor
final class FindRoutingTests: XCTestCase {
    func testAPaletteRequestIsReadThenCleared() {
        let router = AppRouter()
        router.requestPalette(prefill: "alpha")
        XCTAssertEqual(router.consumePalette()?.prefill, "alpha")
        XCTAssertNil(router.consumePalette())
    }

    func testInboxClustersAndConversationHandOffsAreReadThenCleared() {
        let router = AppRouter()
        router.pendingInboxItem = "inbox-001"
        router.pendingClustersEntity = "alpha-project"
        router.pendingConversationQuery = "planning notes"
        XCTAssertEqual(router.consumeInboxItem(), "inbox-001")
        XCTAssertNil(router.consumeInboxItem())
        XCTAssertEqual(router.consumeClustersEntity(), "alpha-project")
        XCTAssertNil(router.consumeClustersEntity())
        XCTAssertEqual(router.consumeConversationQuery(), "planning notes")
        XCTAssertNil(router.consumeConversationQuery())
    }

    func test_findPalette_sourceRowsStageTheSourcesTabAndTheCard() {
        let router = AppRouter()
        router.routeToSourceDetail("harness:claude-code")
        XCTAssertEqual(router.pendingTab, .sources)
        XCTAssertEqual(router.consumeSourceDetail(), "harness:claude-code")
        XCTAssertNil(router.consumeSourceDetail())
    }
}
