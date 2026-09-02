import XCTest
@testable import CicadaApp

/// PR #29 round 2 — `GraphViewModel.pushEntity` commits to the "go deeper"
/// trail only once a destination is actually ACCEPTED: a graph stub (pushed
/// on the spot, the responsive path) or a fetched full entity. A wikilink to
/// an id the bank doesn't have used to push history FIRST and fail the fetch
/// SECOND, leaving a Back control that pointed at the card the user never
/// left. Driven through the real `Store` + `FakeSyncAPI` so the async fetch
/// path is the one production takes.
@MainActor
final class GraphNavigationTests: XCTestCase {

    private func makePair(api: FakeSyncAPI) -> (vm: GraphViewModel, store: Store) {
        let cache = SnapshotCache(
            root: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        )
        let store = Store(cache: cache, api: api)
        return (GraphViewModel(store: store), store)
    }

    private func fullEntity(id: String, name: String) throws -> Entity {
        try JSONDecoder().decode(Entity.self, from: Data("""
        {"id":"\(id)","name":"\(name)","type":"project","status":"active","confidence":0.9,
         "created":"2026-01-01","lastReferenced":"2026-01-02","decayRate":0.05,
         "markdownContent":"# \(name)"}
        """.utf8))
    }

    /// A VM whose graph holds stubs `a` and `b`, with `a`'s card open and no
    /// trail behind it — the state a wikilink tap starts from.
    private func loadedViewModel(api: FakeSyncAPI) async -> GraphViewModel {
        api.replies[.graph] = .value(GraphResponse(nodes: [
            GraphNode(id: "a", name: "A", type: .concept),
            GraphNode(id: "b", name: "B", type: .concept),
        ]))
        let (vm, _) = makePair(api: api)
        await vm.loadGraph()
        vm.selectEntity(id: "a")
        return vm
    }

    /// `pushEntity` resolves a non-stub id through `store.entity` on a Task;
    /// wait for the fake API to have answered `fetches` lookups in total,
    /// then give the VM's continuation a beat to apply (or drop) the result.
    private func settle(_ api: FakeSyncAPI, fetches: Int,
                        file: StaticString = #filePath, line: UInt = #line) async throws {
        let deadline = Date().addingTimeInterval(3)
        while api.entityFetches < fetches {
            if Date() > deadline {
                XCTFail("timed out waiting for \(fetches) entity fetches (saw \(api.entityFetches))",
                        file: file, line: line)
                return
            }
            try await Task.sleep(nanoseconds: 2_000_000)
        }
        try await Task.sleep(nanoseconds: 20_000_000)
    }

    // MARK: - The reviewer's case: a link to an id the bank doesn't have

    func test_pushEntity_unknownID_leavesHistoryAndSelectionUntouched() async throws {
        let api = FakeSyncAPI()
        let vm = await loadedViewModel(api: api)
        XCTAssertEqual(vm.selectedEntity?.id, "a")
        XCTAssertFalse(vm.canGoBack)

        // Not a graph stub, and the API 404s it (`api.entities` is empty).
        vm.pushEntity(id: "ghost")
        // Fetch 1 is `a`'s own full-body load from `selectEntity`; fetch 2
        // is the `ghost` lookup.
        try await settle(api, fetches: 2)

        XCTAssertFalse(vm.canGoBack,
                       "a destination that never arrived must not create a Back target")
        XCTAssertNil(vm.backTargetName)
        XCTAssertEqual(vm.selectedEntity?.id, "a",
                       "the card must stay on the entity the user was reading")
    }

    // MARK: - The two accepted paths

    func test_pushEntity_graphStub_pushesImmediately() async throws {
        let api = FakeSyncAPI()
        let vm = await loadedViewModel(api: api)

        vm.pushEntity(id: "b")

        // Synchronous — the responsive path must not wait on any fetch.
        XCTAssertTrue(vm.canGoBack)
        XCTAssertEqual(vm.backTargetName, "A")
        XCTAssertEqual(vm.selectedEntity?.id, "b")

        vm.goBackEntity()
        XCTAssertEqual(vm.selectedEntity?.id, "a")
        XCTAssertFalse(vm.canGoBack)
    }

    func test_pushEntity_fetchedEntity_commitsHistoryWhenItArrives() async throws {
        let api = FakeSyncAPI()
        api.entities["ghost"] = try fullEntity(id: "ghost", name: "Ghost")
        let vm = await loadedViewModel(api: api)

        vm.pushEntity(id: "ghost")
        // The Task hasn't had a chance to run yet: nothing is accepted until
        // the body lands.
        XCTAssertFalse(vm.canGoBack)
        XCTAssertEqual(vm.selectedEntity?.id, "a")

        try await settle(api, fetches: 2)

        XCTAssertTrue(vm.canGoBack)
        XCTAssertEqual(vm.backTargetName, "A")
        XCTAssertEqual(vm.selectedEntity?.id, "ghost")

        vm.goBackEntity()
        XCTAssertEqual(vm.selectedEntity?.id, "a")
        XCTAssertFalse(vm.canGoBack)
    }

    // MARK: - A late arrival after the user moved on

    func test_pushEntity_fetchedEntity_isDroppedIfTheUserMovedOn() async throws {
        let api = FakeSyncAPI()
        api.entities["ghost"] = try fullEntity(id: "ghost", name: "Ghost")
        let vm = await loadedViewModel(api: api)

        vm.pushEntity(id: "ghost")
        // Before the fetch resolves, a fresh pick from outside the card.
        vm.selectEntity(id: "b")
        try await settle(api, fetches: 3)

        XCTAssertEqual(vm.selectedEntity?.id, "b",
                       "a late arrival must not yank the user off the card they moved to")
        XCTAssertFalse(vm.canGoBack, "a fresh pick resets the trail; the late arrival must not re-seed it")
    }
}
