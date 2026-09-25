import XCTest
@testable import CicadaApp

/// DS-3a R-DG25 — one reader of what graph.js posts, one writer of what Swift calls. The JS half is
/// `Tests/graph/graph-canvas-bridge.test.js`; this is the Swift half of the same bridge.
final class GraphBridgeTests: XCTestCase {
    private func json(_ object: [String: Any]) -> String {
        String(data: try! JSONSerialization.data(withJSONObject: object), encoding: .utf8)!
    }

    func testEveryMessageGraphJsPostsParses() {
        XCTAssertEqual(GraphMessage.parse(json(["type": "graphReady"])), .graphReady)
        XCTAssertEqual(GraphMessage.parse(json(["type": "backgroundClicked"])), .backgroundClicked)
        XCTAssertEqual(GraphMessage.parse(json(["type": "escape"])), .escape)
        XCTAssertEqual(GraphMessage.parse(json(["type": "focusCleared"])), .focusCleared)
        XCTAssertEqual(GraphMessage.parse(json(["type": "nodeClicked", "id": "alpha-project"])), .nodeClicked("alpha-project"))
        XCTAssertEqual(GraphMessage.parse(json(["type": "hubExpanded", "id": "hub-1"])), .hubExpanded("hub-1"))
        XCTAssertEqual(GraphMessage.parse(json(["type": "nodeFocused", "id": "alpha-project", "hops": 2])),
                       .nodeFocused("alpha-project"))
    }

    func testAMalformedOrUnknownMessageIsIgnored() {
        XCTAssertNil(GraphMessage.parse(42))
        XCTAssertNil(GraphMessage.parse("not json"))
        XCTAssertNil(GraphMessage.parse(json(["id": "alpha-project"])))
        XCTAssertNil(GraphMessage.parse(json(["type": "nodeClicked"])), "a click without an id selects nothing")
        XCTAssertNil(GraphMessage.parse(json(["type": "somethingNew"])))
    }

    func testAJsErrorKeepsItsLocation() {
        XCTAssertEqual(GraphMessage.parse(json(["type": "jsError", "message": "boom", "source": "graph.js",
                                                "line": 12, "col": 3, "stack": ""])),
                       .jsError("boom @ graph.js:12:3"))
    }

    /// The old `setFocus('\(id)', 1)` broke on an id with a quote; every id is now a JSON literal.
    func testCallsQuoteTheirIds() {
        XCTAssertEqual(GraphJS.setSelectedNode(nil), "setSelectedNode(null)")
        XCTAssertEqual(GraphJS.setSelectedNode("alpha-project"), #"setSelectedNode("alpha-project")"#)
        XCTAssertEqual(GraphJS.setFocus("bob's", hops: 1), #"setFocus("bob's", 1)"#)
        XCTAssertEqual(GraphJS.revealNode(#"a"b"#), #"revealNode("a\"b")"#)
    }

    /// Two Esc presses in a row are two changes `onChange` sees.
    @MainActor
    func testACanvasEventIsCounted() {
        let store = Store(cache: SnapshotCache(
            root: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        ), api: FakeSyncAPI())
        let vm = GraphViewModel(store: store)
        vm.receive(.escape)
        vm.receive(.escape)
        XCTAssertEqual(vm.canvasEvent, .escape)
        XCTAssertEqual(vm.canvasEventCount, 2)
    }
}
