import XCTest
@testable import CicadaApp

final class GraphDiffTests: XCTestCase {

    private func node(_ id: String, hash: String = "aaaaaaaaaaaa", name: String? = nil) -> GraphNode {
        GraphNode(id: id, name: name ?? id, type: .concept, contentHash: hash)
    }

    private func edge(_ s: String, _ t: String, _ label: String = "relates_to") -> GraphEdge {
        GraphEdge(source: s, target: t, label: label)
    }

    // MARK: - Full

    func test_nilOld_isFull_withEveryNodeAndLink() {
        let new = GraphResponse(nodes: [node("a"), node("b")], links: [edge("a", "b")])
        let d = GraphDiff.diff(old: nil, new: new)

        XCTAssertTrue(d.isFull)
        XCTAssertEqual(d.added.map(\.id), ["a", "b"])
        XCTAssertTrue(d.updated.isEmpty)
        XCTAssertTrue(d.removed.isEmpty)
        XCTAssertEqual(d.links?.count, 1)
        XCTAssertFalse(d.isEmpty)
    }

    // MARK: - Unchanged

    func test_identicalSnapshots_produceEmptyDelta_withNilLinks() {
        let nodes = [node("a"), node("b", hash: "bbbbbbbbbbbb")]
        let links = [edge("a", "b")]
        let old = GraphResponse(nodes: nodes, links: links)
        let new = GraphResponse(nodes: nodes, links: links)

        let d = GraphDiff.diff(old: old, new: new)

        XCTAssertFalse(d.isFull)
        XCTAssertTrue(d.added.isEmpty)
        XCTAssertTrue(d.updated.isEmpty)
        XCTAssertTrue(d.removed.isEmpty)
        XCTAssertNil(d.links, "links must be nil when the link set is unchanged")
        XCTAssertTrue(d.isEmpty)
    }

    func test_reorderedLinks_areNotAChange() {
        let nodes = [node("a"), node("b"), node("c")]
        let old = GraphResponse(nodes: nodes, links: [edge("a", "b"), edge("b", "c")])
        let new = GraphResponse(nodes: nodes, links: [edge("b", "c"), edge("a", "b")])

        XCTAssertNil(GraphDiff.diff(old: old, new: new).links)
    }

    // MARK: - Added / updated / removed

    func test_addedNode_isDetected() {
        let old = GraphResponse(nodes: [node("a")])
        let new = GraphResponse(nodes: [node("a"), node("b", hash: "bbbbbbbbbbbb")])

        let d = GraphDiff.diff(old: old, new: new)
        XCTAssertEqual(d.added.map(\.id), ["b"])
        XCTAssertTrue(d.updated.isEmpty)
        XCTAssertTrue(d.removed.isEmpty)
        XCTAssertFalse(d.isEmpty)
    }

    func test_changedContentHash_isAnUpdate_notAnAdd() {
        let old = GraphResponse(nodes: [node("a", hash: "111111111111"), node("b", hash: "222222222222")])
        let new = GraphResponse(nodes: [node("a", hash: "999999999999"), node("b", hash: "222222222222")])

        let d = GraphDiff.diff(old: old, new: new)
        XCTAssertTrue(d.added.isEmpty)
        XCTAssertEqual(d.updated.map(\.id), ["a"])
        XCTAssertEqual(d.updated.first?.contentHash, "999999999999")
        XCTAssertTrue(d.removed.isEmpty)
    }

    func test_sameHashDifferentName_isNotReportedAsUpdate() {
        // contentHash is the authority: the server computes it over
        // frontmatter + body, so an equal hash means an unchanged page.
        let old = GraphResponse(nodes: [node("a", hash: "111111111111", name: "Old")])
        let new = GraphResponse(nodes: [node("a", hash: "111111111111", name: "New")])

        XCTAssertTrue(GraphDiff.diff(old: old, new: new).updated.isEmpty)
    }

    func test_removedNode_isDetected() {
        let old = GraphResponse(nodes: [node("a"), node("b")], links: [edge("a", "b")])
        let new = GraphResponse(nodes: [node("a")], links: [])

        let d = GraphDiff.diff(old: old, new: new)
        XCTAssertEqual(d.removed, ["b"])
        XCTAssertTrue(d.added.isEmpty)
        XCTAssertTrue(d.updated.isEmpty)
        XCTAssertEqual(d.links?.count, 0, "link set shrank, so links must be replaced wholesale")
    }

    func test_changedLinkSet_shipsTheWholeNewLinkList() {
        let nodes = [node("a"), node("b"), node("c")]
        let old = GraphResponse(nodes: nodes, links: [edge("a", "b")])
        let new = GraphResponse(nodes: nodes, links: [edge("a", "b"), edge("b", "c")])

        let d = GraphDiff.diff(old: old, new: new)
        XCTAssertEqual(d.links?.count, 2)
        XCTAssertTrue(d.added.isEmpty)
    }

    func test_relabelledLink_countsAsAChange() {
        let nodes = [node("a"), node("b")]
        let old = GraphResponse(nodes: nodes, links: [edge("a", "b", "uses")])
        let new = GraphResponse(nodes: nodes, links: [edge("a", "b", "depends_on")])

        XCTAssertEqual(GraphDiff.diff(old: old, new: new).links?.count, 1)
    }

    // MARK: - Empty contentHash (older backend)

    func test_emptyHashOnEitherSide_isAlwaysAnUpdate() {
        // Old backend on both sides: everything degrades to "updated" rather
        // than silently comparing equal and dropping real edits.
        let bothEmpty = GraphDiff.diff(
            old: GraphResponse(nodes: [node("a", hash: "")]),
            new: GraphResponse(nodes: [node("a", hash: "")])
        )
        XCTAssertEqual(bothEmpty.updated.map(\.id), ["a"])

        let oldEmpty = GraphDiff.diff(
            old: GraphResponse(nodes: [node("a", hash: "")]),
            new: GraphResponse(nodes: [node("a", hash: "111111111111")])
        )
        XCTAssertEqual(oldEmpty.updated.map(\.id), ["a"])

        let newEmpty = GraphDiff.diff(
            old: GraphResponse(nodes: [node("a", hash: "111111111111")]),
            new: GraphResponse(nodes: [node("a", hash: "")])
        )
        XCTAssertEqual(newEmpty.updated.map(\.id), ["a"])
    }

    func test_decodeTolerance_missingSummaryAndHash() throws {
        let json = """
        {"id":"a","name":"A","type":"concept","status":"active","confidence":0.9}
        """.data(using: .utf8)!
        let n = try JSONDecoder().decode(GraphNode.self, from: json)
        XCTAssertNil(n.summary)
        XCTAssertEqual(n.contentHash, "")

        let json2 = """
        {"id":"a","name":"A","type":"concept","status":"active","confidence":0.9,
         "summary":"a short preview","contentHash":"abc123abc123"}
        """.data(using: .utf8)!
        let n2 = try JSONDecoder().decode(GraphNode.self, from: json2)
        XCTAssertEqual(n2.summary, "a short preview")
        XCTAssertEqual(n2.contentHash, "abc123abc123")
    }

    // MARK: - Encoding

    func test_encode_deltaPayloadShape() throws {
        let d = GraphDelta(added: [node("b")], updated: [node("a")], removed: ["c"],
                           links: [edge("a", "b")], isFull: false)
        let obj = try XCTUnwrap(
            JSONSerialization.jsonObject(with: Data(GraphViewModel.encode(d).utf8)) as? [String: Any]
        )
        XCTAssertEqual((obj["added"] as? [[String: Any]])?.count, 1)
        XCTAssertEqual((obj["updated"] as? [[String: Any]])?.count, 1)
        XCTAssertEqual(obj["removed"] as? [String], ["c"])
        XCTAssertEqual((obj["links"] as? [[String: Any]])?.count, 1)
        XCTAssertEqual(obj["isFull"] as? Bool, false)
        XCTAssertNil(obj["nodes"])
    }

    func test_encode_omitsLinksWhenUnchanged() throws {
        let d = GraphDelta(added: [], updated: [node("a")], removed: [], links: nil, isFull: false)
        let obj = try XCTUnwrap(
            JSONSerialization.jsonObject(with: Data(GraphViewModel.encode(d).utf8)) as? [String: Any]
        )
        XCTAssertNil(obj["links"], "an unchanged link set must not be re-sent")
    }

    func test_encode_fullPayloadUsesNodesAndLinks() throws {
        let d = GraphDiff.diff(old: nil, new: GraphResponse(nodes: [node("a")], links: [edge("a", "a")]))
        let obj = try XCTUnwrap(
            JSONSerialization.jsonObject(with: Data(GraphViewModel.encode(d).utf8)) as? [String: Any]
        )
        XCTAssertEqual((obj["nodes"] as? [[String: Any]])?.count, 1)
        XCTAssertEqual((obj["links"] as? [[String: Any]])?.count, 1)
        XCTAssertNil(obj["added"])
    }
}
