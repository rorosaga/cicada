import XCTest
@testable import CicadaApp

/// Covers `GraphViewModel`'s push pipeline (§5.6) — which snapshots go out as a
/// full `updateGraph` payload and which as an `updateGraphDelta` one. The
/// webview is not involved: the test drives `schedulePush` directly and reads
/// the prepared `pendingPushJSON` / `pendingPushIsDelta` the way
/// `GraphView.updateNSView` does.
private func decodeEntity(_ json: String) throws -> Entity {
    try JSONDecoder().decode(Entity.self, from: Data(json.utf8))
}

@MainActor
final class GraphPushTests: XCTestCase {

    private func makeViewModel() -> GraphViewModel {
        makePair(api: FakeSyncAPI()).vm
    }

    private func makePair(api: FakeSyncAPI) -> (vm: GraphViewModel, store: Store) {
        let cache = SnapshotCache(
            root: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        )
        let store = Store(cache: cache, api: api)
        return (GraphViewModel(store: store), store)
    }

    private func node(_ id: String, hash: String) -> GraphNode {
        GraphNode(id: id, name: id, type: .concept, contentHash: hash)
    }

    /// `schedulePush` prepares off the main actor, so wait for the payload to
    /// come back before asserting on it.
    private func awaitPush(_ vm: GraphViewModel, _ message: String,
                           file: StaticString = #filePath, line: UInt = #line) async throws {
        let deadline = Date().addingTimeInterval(3)
        while vm.pendingPushJSON == nil {
            if Date() > deadline {
                XCTFail("timed out waiting for a prepared push: \(message)", file: file, line: line)
                return
            }
            try await Task.sleep(nanoseconds: 2_000_000)
        }
    }

    /// The bank-switch sequence: the Store nils the graph snapshot (blank push),
    /// then the new bank's snapshot lands. That second push MUST be full — a
    /// delta against the empty snapshot is all-`added` and carries no `nodes`
    /// key, which used to leave the canvas empty.
    func test_pushAfterBlank_isFull_thenSubsequentPushesAreDeltas() async throws {
        let vm = makeViewModel()
        let bankB = GraphResponse(nodes: [node("a", hash: "111111111111"),
                                          node("b", hash: "222222222222")],
                                  links: [GraphEdge(source: "a", target: "b", label: "rel")])

        // 1. Bank switch: the store cleared the graph.
        vm.schedulePush(GraphResponse())
        try await awaitPush(vm, "blank")
        XCTAssertFalse(vm.pendingPushIsDelta, "a blank must go over the full path")
        vm.clearPendingPush()

        // 2. The new bank's first snapshot — must still be full.
        vm.schedulePush(bankB)
        try await awaitPush(vm, "first snapshot after the blank")
        XCTAssertFalse(vm.pendingPushIsDelta,
                       "the push after a blank must be full, not an all-added delta")
        let json = try XCTUnwrap(vm.pendingPushJSON)
        let obj = try XCTUnwrap(
            JSONSerialization.jsonObject(with: Data(json.utf8)) as? [String: Any]
        )
        XCTAssertEqual((obj["nodes"] as? [[String: Any]])?.count, 2,
                       "a full payload must carry a `nodes` key graph.js can swap in")
        vm.clearPendingPush()

        // 3. Only now do subsequent changes ride as deltas.
        let bankBEdited = GraphResponse(nodes: [node("a", hash: "999999999999"),
                                                node("b", hash: "222222222222")],
                                        links: bankB.links)
        vm.schedulePush(bankBEdited)
        try await awaitPush(vm, "edit after the bank settled")
        XCTAssertTrue(vm.pendingPushIsDelta, "a change on a known snapshot is a delta")
        let deltaObj = try XCTUnwrap(
            JSONSerialization.jsonObject(with: Data(XCTUnwrap(vm.pendingPushJSON).utf8)) as? [String: Any]
        )
        XCTAssertEqual((deltaObj["updated"] as? [[String: Any]])?.count, 1)
        XCTAssertEqual((deltaObj["added"] as? [[String: Any]])?.count, 0)
    }

    /// The very first push of the app's life is full (there is no prior
    /// snapshot to diff against).
    func test_firstPushIsFull() async throws {
        let vm = makeViewModel()
        vm.schedulePush(GraphResponse(nodes: [node("a", hash: "111111111111")]))
        try await awaitPush(vm, "first push")
        XCTAssertFalse(vm.pendingPushIsDelta)
    }

    /// A push prepared while the previous one is still unconsumed falls back to
    /// full, so the unconsumed payload's changes can't be dropped.
    func test_unconsumedPayloadForcesTheNextPushFull() async throws {
        let vm = makeViewModel()
        let a = GraphResponse(nodes: [node("a", hash: "111111111111")])
        vm.schedulePush(a)
        try await awaitPush(vm, "first")
        vm.clearPendingPush()

        vm.schedulePush(GraphResponse(nodes: [node("a", hash: "222222222222")]))
        try await awaitPush(vm, "second")
        XCTAssertTrue(vm.pendingPushIsDelta)
        // Deliberately do NOT consume it.
        vm.schedulePush(GraphResponse(nodes: [node("a", hash: "333333333333")]))
        // The payload is already non-nil, so wait for the flag to flip instead.
        let deadline = Date().addingTimeInterval(3)
        while vm.pendingPushIsDelta && Date() < deadline {
            try await Task.sleep(nanoseconds: 2_000_000)
        }
        XCTAssertFalse(vm.pendingPushIsDelta,
                       "a push landing on an unconsumed payload must be a full replace")
    }

    // MARK: - Final review fix (3)

    /// A node listed in a delta's `updated` is a node whose page changed, so
    /// the Store's memoised full body for it is stale. `Store.invalidateEntity`
    /// used to have zero callers — the detail card kept showing the old body
    /// until the app was relaunched.
    func test_deltaUpdatedIDs_invalidateTheCachedEntityBody() async throws {
        let api = FakeSyncAPI()
        let body: Entity = try decodeEntity("""
        {"id":"a","name":"A","type":"project","status":"active","confidence":0.9,
         "created":"2026-01-01","lastReferenced":"2026-01-02","decayRate":0.05,
         "markdownContent":"# old"}
        """)
        api.entities["a"] = body
        api.entities["b"] = body
        let (vm, store) = makePair(api: api)

        // First (full) push, then warm the body cache for both nodes.
        vm.schedulePush(GraphResponse(nodes: [node("a", hash: "111111111111"),
                                              node("b", hash: "aaaaaaaaaaaa")]))
        try await awaitPush(vm, "first")
        vm.clearPendingPush()
        _ = await store.entity("a")
        _ = await store.entity("b")
        XCTAssertNotNil(store.entities["a"])
        XCTAssertNotNil(store.entities["b"])

        // `a`'s hash moved, `b`'s did not → only `a` is invalidated.
        vm.schedulePush(GraphResponse(nodes: [node("a", hash: "222222222222"),
                                              node("b", hash: "aaaaaaaaaaaa")]))
        try await awaitPush(vm, "delta")
        XCTAssertTrue(vm.pendingPushIsDelta)
        XCTAssertNil(store.entities["a"], "an updated node's cached body must be dropped")
        XCTAssertNotNil(store.entities["b"], "an untouched node must keep its cached body")
    }

    /// A full push replaces the whole snapshot (first load, bank switch), and
    /// carries no per-node update list — drop every cached body.
    func test_fullPush_clearsTheWholeEntityCache() async throws {
        let api = FakeSyncAPI()
        api.entities["a"] = try decodeEntity("""
        {"id":"a","name":"A","type":"project","status":"active","confidence":0.9,
         "created":"2026-01-01","lastReferenced":"2026-01-02","decayRate":0.05,
         "markdownContent":"# old"}
        """)
        let (vm, store) = makePair(api: api)

        _ = await store.entity("a")
        XCTAssertNotNil(store.entities["a"])

        // The first push of a session is full (and so is the one after a
        // bank-switch blank) — nothing tells us which bodies survived.
        vm.schedulePush(GraphResponse(nodes: [node("a", hash: "111111111111")]))
        try await awaitPush(vm, "full")
        XCTAssertFalse(vm.pendingPushIsDelta)
        XCTAssertTrue(store.entities.isEmpty, "a full push must clear every cached body")
    }
}
