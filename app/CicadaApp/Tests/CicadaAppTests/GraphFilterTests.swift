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
}
