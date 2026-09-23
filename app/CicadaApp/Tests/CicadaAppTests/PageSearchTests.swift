import XCTest
@testable import CicadaApp

/// G136 S5 — a source's conversations and the Inbox, on the shared field.
@MainActor
final class PageSearchTests: XCTestCase {
    func testTheTitleFilterFoldsAndKeepsNewestFirst() {
        let rows = [ConversationSummary(conversationId: "a", title: "Zürich planning"),
                    ConversationSummary(conversationId: "b", title: "Graph physics"),
                    ConversationSummary(conversationId: "c", title: "zurich retro")]
        XCTAssertEqual(ConversationFilter.apply(rows, query: "zurich").map(\.id), ["a", "c"])
        XCTAssertEqual(ConversationFilter.apply(rows, query: "graph phys").map(\.id), ["b"])
        XCTAssertEqual(ConversationFilter.apply(rows, query: "").map(\.id), ["a", "b", "c"])
    }

    func testOnlyACappedPageWidensToTheServer() {
        XCTAssertFalse(ConversationSearch.needsServer(loaded: 199, query: "planning"))
        XCTAssertTrue(ConversationSearch.needsServer(loaded: 200, query: "planning"))
        XCTAssertFalse(ConversationSearch.needsServer(loaded: 200, query: "p"), "one character stays local")
        let local = [ConversationSummary(conversationId: "a", title: "x")]
        let server = [ConversationSummary(conversationId: "a", title: "x"), ConversationSummary(conversationId: "z", title: "x")]
        XCTAssertEqual(ConversationSearch.merge(local: local, server: server).map(\.id), ["a", "z"])
    }

    func testTheViewModelAsksTheServerOnlyPastTheCap() async {
        let api = FakeSyncAPI()
        api.recentConversations = (0..<200).map { ConversationSummary(conversationId: "c\($0)", title: "row \($0)") }
            + [ConversationSummary(conversationId: "old", title: "planning notes")]
        let vm = ConversationsViewModel(api: api)
        await vm.load(limit: ConversationSearch.cap)
        XCTAssertEqual(vm.conversations.count, 200, "the fake honours the cap like the server")
        await vm.searchBeyondCap(query: "planning")
        XCTAssertEqual(vm.beyondCap.map(\.id), ["old"])
        XCTAssertEqual(api.recentQueries.last, "planning")
        XCTAssertEqual(vm.beyondCap(for: "planning").map(\.id), ["old"])
        XCTAssertTrue(vm.beyondCap(for: "planning x").isEmpty, "a stale widening never sits under a newer query")
        let small = FakeSyncAPI()
        small.recentConversations = [ConversationSummary(conversationId: "a", title: "planning")]
        let vm2 = ConversationsViewModel(api: small)
        await vm2.load(limit: ConversationSearch.cap)
        await vm2.searchBeyondCap(query: "planning")
        XCTAssertTrue(vm2.beyondCap.isEmpty)
        XCTAssertEqual(small.recentQueries, [nil], "below the cap the local filter already saw everything")
    }
}
