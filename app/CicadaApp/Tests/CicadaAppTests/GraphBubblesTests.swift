import XCTest
@testable import CicadaApp

/// Owner 2026-11-25: one bubble per list of saved things. The wire shape, the delta that carries the bubbles only when
/// they changed, the payload graph.js reads, and the bridge's two messages. The canvas half is
/// `Tests/graph/graph-bubbles.test.js`.
final class GraphBubblesTests: XCTestCase {
    private func node(_ id: String, hash: String = "aaaaaaaaaaaa") -> GraphNode {
        GraphNode(id: id, name: id, type: .media, contentHash: hash)
    }

    private func bubble(_ members: [String], outside: [String] = []) -> GraphBubble {
        GraphBubble(id: "list:x-bookmarks", key: "x-bookmarks", name: "X: Bookmarks", site: "x", mark: "x-bookmarks",
                    kindNoun: "posts", members: members,
                    folders: [.init(key: "x-bookmarks-a", name: "Alpha", members: Array(members.prefix(2)))],
                    outside: outside)
    }

    func test_theWireDecodes_andAnOlderBackendMeansNoBubbles() throws {
        let json = """
        {"nodes": [], "links": [], "bubbles": [{"id": "list:x-bookmarks", "key": "x-bookmarks", "name": "X: Bookmarks",
          "site": "x", "mark": "x-bookmarks", "kindNoun": "posts", "count": 3, "pageId": null,
          "members": ["a", "b", "c"], "folders": [{"key": "f", "name": "Alpha", "members": ["a"]}], "outside": ["d"]}]}
        """
        let g = try JSONDecoder().decode(GraphResponse.self, from: Data(json.utf8))
        XCTAssertEqual(g.bubbles.count, 1)
        XCTAssertEqual(g.bubbles[0].members, ["a", "b", "c"])
        XCTAssertEqual(g.bubbles[0].folders.first?.name, "Alpha")
        XCTAssertEqual(g.bubbles[0].outside, ["d"])
        XCTAssertNil(g.bubbles[0].pageId)
        let old = try JSONDecoder().decode(GraphResponse.self, from: Data(#"{"nodes": [], "links": []}"#.utf8))
        XCTAssertTrue(old.bubbles.isEmpty)
        let broken = try JSONDecoder().decode(GraphResponse.self, from: Data(#"{"nodes": [], "links": [], "bubbles": [{"name": 1}]}"#.utf8))
        XCTAssertTrue(broken.bubbles.isEmpty, "a malformed bubble costs the bubbles, never the graph")
    }

    func test_aDeltaCarriesTheBubblesOnlyWhenTheyChanged() {
        let nodes = [node("a"), node("b"), node("c")]
        let old = GraphResponse(nodes: nodes, bubbles: [bubble(["a", "b", "c"])])
        XCTAssertNil(GraphDiff.diff(old: old, new: GraphResponse(nodes: nodes, bubbles: [bubble(["a", "b", "c"])])).bubbles)
        XCTAssertTrue(GraphDiff.diff(old: old, new: GraphResponse(nodes: nodes, bubbles: [bubble(["a", "b", "c"])])).isEmpty)
        let moved = GraphDiff.diff(old: old, new: GraphResponse(nodes: nodes, bubbles: [bubble(["a", "b"], outside: ["c"])]))
        XCTAssertEqual(moved.bubbles?.first?.outside, ["c"])
        XCTAssertFalse(moved.isEmpty, "a page leaving its bubble is a change to push, though no node hash moved")
        XCTAssertEqual(GraphDiff.diff(old: nil, new: old).bubbles?.count, 1, "a full push always carries them")
    }

    func test_thePayloadCarriesTheBubblesAndTheirMarks() throws {
        let full = GraphDelta(added: [node("a")], links: [], isFull: true, bubbles: [bubble(["a", "b", "c"])])
        let json = try XCTUnwrap(JSONSerialization.jsonObject(
            with: Data(GraphViewModel.encode(full, marks: ["x-bookmarks": "data:image/png;base64,AA", "other": "x"]).utf8))
            as? [String: Any])
        let rows = try XCTUnwrap(json["bubbles"] as? [[String: Any]])
        XCTAssertEqual(rows.first?["id"] as? String, "list:x-bookmarks")
        XCTAssertEqual(rows.first?["members"] as? [String], ["a", "b", "c"])
        XCTAssertEqual(rows.first?["kindNoun"] as? String, "posts")
        XCTAssertNil(rows.first?["pageId"], "absent, never null, when the list has no page")
        XCTAssertEqual(json["marks"] as? [String: String], ["x-bookmarks": "data:image/png;base64,AA"],
                       "only the marks its bubbles wear")
        let quiet = GraphDelta(updated: [node("a")], isFull: false)
        let delta = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(GraphViewModel.encode(quiet).utf8)) as? [String: Any])
        XCTAssertNil(delta["bubbles"], "a delta that did not change them leaves them alone")
    }

    func test_theBridgeParsesOpenAndClose() {
        XCTAssertEqual(GraphMessage.parse(#"{"type":"bubbleOpened","id":"list:x-bookmarks"}"#), .bubbleOpened("list:x-bookmarks"))
        XCTAssertEqual(GraphMessage.parse(#"{"type":"bubbleClosed"}"#), .bubbleClosed)
        XCTAssertNil(GraphMessage.parse(#"{"type":"bubbleOpened"}"#))
        XCTAssertEqual(GraphMessage.parse(#"{"type":"bubbleOutsideClicked"}"#), .bubbleOutsideClicked)
    }

    func test_whatAListHoldsIsSaidInWords() {
        XCTAssertEqual(Copy.Graph.bubbleHolds(3150, noun: "videos"), "\(3150.formatted()) videos", "the reader's own digits")
        XCTAssertEqual(Copy.Graph.bubbleHolds(1, noun: "repositories"), "1 repository")
        XCTAssertEqual(Copy.Graph.bubbleHolds(1, noun: "posts"), "1 post")
    }
}
