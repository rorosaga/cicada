import XCTest
@testable import CicadaApp

/// Ruling 70, requirement 2 — one order everywhere. The server's score orders the list (`orderIndex`); every queue in the
/// app reads that order and never the stored `priority`. These tests give each queue a list whose priorities OPPOSE the
/// served order and assert the served order wins: a page's own queue ("A question · 1 of N"), Home's lead and rows, the
/// catch-up's list, the Inbox columns, the palette's tie-break and `Store.visibleInbox`. Synthetic items, placeholder names.
@MainActor
final class QuestionOrderEverywhereTests: XCTestCase {
    /// `priority` is what an older client would sort by; `index` is the server's place for the question.
    private func item(_ id: String, page: String = "alpha-project", priority: Double, index: Int?, kind: String = "conflict",
                      extra: String = "") throws -> InboxItem {
        let order = index.map { #","orderIndex":\#($0)"# } ?? ""
        return try JSONDecoder().decode(InboxItem.self, from: Data(#"""
        {"id":"\#(id)","kind":"\#(kind)","requiredInput":"choice","title":"t \#(id)","priority":\#(priority),
         "createdDate":"2026-10-20","entityId":"\#(page)","entityName":"Alpha Project","entityType":"project",
         "allowDefer":true,"allowOther":true,
         "options":[{"key":"a","label":"Org Gamma"},{"key":"neither","label":"Not anymore"}],
         "spokenQuestion":"Plain \#(id)?","spokenReason":"Because \#(id)."\#(order)\#(extra)}
        """#.utf8))
    }

    /// Three questions on one page and one elsewhere, served in an order the priorities contradict end to end:
    /// the question the server asks first has the LOWEST priority.
    private func served() throws -> [InboxItem] {
        [try item("first", priority: 0.1, index: 0), try item("second", priority: 0.5, index: 1),
         try item("other", page: "beta-notes", priority: 0.99, index: 2), try item("third", priority: 0.9, index: 3)]
    }

    func testAPagesQueueFollowsTheServedOrderWhenPrioritiesOpposeIt() throws {
        let ids = HomeQuestions.onPage(try served(), entityId: "alpha-project").map(\.id)
        XCTAssertEqual(ids, ["first", "second", "third"], "'A question · 1 of 3' starts at the question the server asks first")
        XCTAssertEqual(EntityOpenQuestion.first(in: try served(), entityId: "alpha-project")?.id, "first")
    }

    func testHomesLeadAndRowsFollowTheServedOrderWhenPrioritiesOpposeIt() throws {
        let figures = HomeQuestions.figures(try served(), now: .now)
        XCTAssertEqual(figures.rows.map(\.id), ["first", "other"], "one row per page, the page's lead is its first served question")
        XCTAssertEqual(figures.rows[0].onPage, 3)
        XCTAssertEqual(figures.catchUp, ["first", "second", "other", "third"], "the catch-up's list is the served list")
    }

    func testTheStoresVisibleListKeepsTheServedOrderAndSoDoEveryQueueBuiltOnIt() throws {
        let store = Store(cache: SnapshotCache(
            root: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)), api: FakeSyncAPI())
        store.inbox.value = try served()
        XCTAssertEqual(store.visibleInbox.map(\.id), ["first", "second", "other", "third"])
        XCTAssertEqual(HomeQuestions.onPage(store.visibleInbox, entityId: "alpha-project").first?.id, "first")
        XCTAssertEqual(HomeQuestions.figures(store.visibleInbox, now: .now).rows.first?.id, "first")
    }

    func testTheInboxColumnsAndGroupsFollowTheServedOrderToo() throws {
        let items = try served().shuffled()
        XCTAssertTrue(InboxColumns.usesServedOrder(items))
        XCTAssertEqual(InboxColumns.ordered(items).map(\.id), ["first", "second", "other", "third"])
        XCTAssertEqual(InboxColumns.visible(items, filter: nil).map(\.id), ["first", "second", "other", "third"])
    }

    func testThePalettesTieBreakIsTheServedOrderAndAnOlderServersListKeepsPriority() throws {
        let tie = { (docs: [QuickIndex.Doc]) in docs.sorted { $0.row.tieBreak > $1.row.tieBreak }.map(\.row.key.id) }
        XCTAssertEqual(tie(QuickIndex.inboxDocs(try served())), ["first", "second", "other", "third"])
        // One question without a place sends the whole list to the older rule, as `InboxColumns` does.
        let old = [try item("low", priority: 0.1, index: 0), try item("high", priority: 0.9, index: nil)]
        XCTAssertEqual(tie(QuickIndex.inboxDocs(old)), ["high", "low"])
    }
}
