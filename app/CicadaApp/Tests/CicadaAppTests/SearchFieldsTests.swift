import XCTest
@testable import CicadaApp

/// G136 S5 — the one in-page field and what three pages search with it.
@MainActor
final class SearchFieldsTests: XCTestCase {
    private func store() -> Store {
        Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)),
              api: FakeSyncAPI())
    }

    func testEscapeClearsThenLeavesAndTheHintShowsOnlyWhenIdle() {
        XCTAssertEqual(CicadaSearchField.escape(textIsEmpty: false), .clear)
        XCTAssertEqual(CicadaSearchField.escape(textIsEmpty: true), .blur)
        XCTAssertTrue(CicadaSearchField.showsFindHint(text: "", focused: false))
        XCTAssertFalse(CicadaSearchField.showsFindHint(text: "", focused: true))
        XCTAssertFalse(CicadaSearchField.showsFindHint(text: "a", focused: false))
    }

    func testTheSearchAllRowCarriesTheWordsTrimmed() {
        XCTAssertEqual(SearchAllMemoryRow.title("  alpha "), "Search all of memory for “alpha” (⌘K)")
        XCTAssertEqual(SearchAllMemoryRow.trimmed("  alpha "), "alpha")
    }

    func testTheGraphTypeaheadFindsATagAndBoldsTheName() async throws {
        let store = store()
        let vm = GraphViewModel(store: store)
        store.graph.value = GraphResponse(nodes: [FindFixtures.node("alpha-project", "alpha-project", tags: ["robotics"], degree: 1),
                                                  FindFixtures.node("bob-example", "bob-example", type: .person)])
        store.graph.loadedAt = Date()
        let deadline = Date().addingTimeInterval(3)
        while vm.nodes.isEmpty {
            if Date() > deadline { return XCTFail("nodes never synced from the store") }
            try await Task.sleep(nanoseconds: 2_000_000)
        }
        XCTAssertEqual(vm.searchHits("robo").map(\.node.id), ["alpha-project"], "a tag is a search field now")
        XCTAssertEqual(vm.searchHits("alp").first?.ranges, [[0, 3]])
        XCTAssertEqual(vm.searchMatches("bob").map(\.id), ["bob-example"])
        XCTAssertEqual(vm.clusterSearchIndex().rank("robotics").map(\.id), ["alpha-project"])
    }

    func testClustersRankNameThenTagThenBody() {
        func entity(_ id: String, _ name: String, tags: [String] = [], body: String = "") -> Entity {
            Entity(id: id, name: name, type: .concept, status: .active, confidence: 0.5, created: "",
                   lastReferenced: "", decayRate: 0, sourceEpisodes: [], tags: tags, related: [], version: 0,
                   markdownContent: body, history: [])
        }
        let index = ClusterSearchIndex([entity("a", "Zeta notes", body: "about alpha retrieval"),
                                        entity("b", "Alpha project"), entity("c", "Omega", tags: ["alpha"])])
        XCTAssertEqual(index.rank("alpha").map(\.id), ["b", "c", "a"])
        XCTAssertEqual(ClusterSearchIndex.titleRanges("Alpha project", query: "alp"), [[0, 3]])
        XCTAssertTrue(index.rank("zzz").isEmpty)
    }

    func testTheFeedFiltersWithTheOneFieldListAndKeepsItsSort() {
        let store = store()
        let vm = FeedViewModel(store: store)
        store.sources = Snapshot(value: [FindFixtures.media("m-a", title: "First", description: "about retrieval"),
                                         FindFixtures.media("m-b", title: "Second retrieval")], loadedAt: Date())
        vm.searchText = "retrieval"
        XCTAssertEqual(vm.filteredItems.map(\.mediaEntityId), ["m-a", "m-b"], "R-SU20: the Feed's order, not a rank")
        vm.searchText = "zzz"
        XCTAssertTrue(vm.filteredItems.isEmpty)
        store.sources = Snapshot(value: [FindFixtures.media("m-c", title: "Third retrieval")],
                                 loadedAt: Date().addingTimeInterval(1))
        vm.searchText = "retrieval"
        XCTAssertEqual(vm.filteredItems.map(\.mediaEntityId), ["m-c"], "a new snapshot is folded again, never served stale")
    }

    /// G133 (Track F) — a paper is found by its byline through the one field list.
    func testAPaperIsFoundByAuthorArxivIdAndDoi() throws {
        let json = #"{"mediaEntityId": "media-paper-alpha", "url": "https://example.com/paper", "title": "Paper Alpha", "mediaType": "bookmark", "savedAt": "2026-09-01", "tags": [], "relevance": 0.5, "kind": "paper", "paper": {"authors": ["Ada Example"], "arxivId": "2401.00001", "doi": "10.9999/abc"}}"#
        let paper = try JSONDecoder().decode(MediaFeedItem.self, from: Data(json.utf8))
        for query in ["ada", "2401.00001", "10.9999"] {
            XCTAssertTrue(FeedSearch.matches(paper, query: query), query)
        }
        XCTAssertFalse(FeedSearch.matches(paper, query: "zebra"))
    }
}
