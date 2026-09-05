import XCTest
@testable import CicadaApp

/// G84a regression: `GraphFilter`'s default `minDegree` and graph.js's own
/// built-in `filters.minDegree` default used to disagree (Swift 0, JS 1),
/// which only showed up on the very first cold paint — before
/// `Coordinator.pushGraphData()` (`GraphView.swift`) had a chance to push
/// `applyFilters`, the canvas ran on JS's stricter default and silently
/// dropped every zero-degree node. The JS side of this contract is asserted
/// by `Tests/graph/graph-mindegree-default.test.js` (a plain node script,
/// not part of `swift test` — see that file's header comment); this test
/// pins the Swift half so the two can't drift apart again without a failing
/// test on at least one side.
final class GraphFilterTests: XCTestCase {

    func test_defaultMinDegree_showsIsolatedNodes() {
        // 0 = show isolated nodes; must mirror graph.js's `filters.minDegree`
        // default in Resources/graph/graph.js.
        XCTAssertEqual(GraphFilter().minDegree, 0)
    }

    func test_defaultFilter_jsPayload_carriesTheAgreedMinDegree() {
        let payload = GraphFilter().jsPayload
        XCTAssertEqual(payload["minDegree"] as? Int, 0,
                        "the very first applyFilters push must re-assert minDegree 0, " +
                        "not rely on graph.js's own default")
    }

    /// G117 R2 — `setObserver("__owner__")` must select every observer that
    /// is neither the reserved `"agent"` keyword nor an `"external:"`-prefixed
    /// one, whatever slug onboarding resolved the owner to (a legacy
    /// `"rodrigo"`, the fresh-bank keyword `"owner"`, or a name-derived slug
    /// like `"bob-example"`). This mirrors the existing `"external"` branch
    /// immediately above it in `GraphViewModel.setObserver` — same
    /// not-agent/not-external rule, read off the live roster instead of a
    /// hardcoded literal.
    @MainActor
    func testOwnerSentinelSelectsEveryNonAgentNonExternalObserver() async throws {
        let cache = SnapshotCache(
            root: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        )
        let store = Store(cache: cache, api: FakeSyncAPI())
        let vm = GraphViewModel(store: store)

        let node: (String, [String]) -> GraphNode = { id, obs in
            GraphNode(id: id, name: id, type: .concept, observers: obs)
        }
        store.graph.value = GraphResponse(
            nodes: [node("a", ["owner"]), node("b", ["bob-example"]),
                    node("c", ["agent"]), node("d", ["external:site"])],
            observers: ["owner", "bob-example", "agent", "external:site"]
        )
        store.graph.loadedAt = Date()

        let deadline = Date().addingTimeInterval(3)
        while vm.observerRoster.isEmpty {
            if Date() > deadline { XCTFail("observerRoster never synced from the store"); return }
            try await Task.sleep(nanoseconds: 2_000_000)
        }

        vm.setObserver("__owner__")
        XCTAssertEqual(vm.filter.observers, Set(["owner", "bob-example"]))
    }
}
