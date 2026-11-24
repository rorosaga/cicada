import XCTest
@testable import CicadaApp

/// G245 (ruling 79 (b), owner 2026-11-24) — X's Following: a stream kind of its own (without it an older build reads
/// `.other` and draws nothing), the tabs of a page that has it, the lenient wire shape, the words of a row, and a list that
/// lives in memory and is gone at once when the person forgets it.
@MainActor
final class FollowedAccountsTests: XCTestCase {
    private func stream(_ id: String, _ label: String, _ kind: StreamKind, count: Int?, on: Bool = true) -> ResolvedStream {
        ResolvedStream(source: "x", stream: SourceStream(id: id, label: label, kind: kind, state: on ? .on : .off, count: count),
                       word: on ? .read : .off, fix: nil, reader: nil)
    }

    func testFollowingIsAKindOfItsOwnAndNeverAListOfPosts() {
        XCTAssertEqual(StreamKind(rawValue: "following"), .following)
        XCTAssertEqual(StreamKind.following.rawValue, "following")
        XCTAssertFalse(StreamKind.following.isList, "the accounts are not cards of posts")
        XCTAssertEqual(StreamKind(rawValue: "somethingNew"), .other("somethingNew"))
    }

    func testAnXPageWithFollowingHasTheListsTabAndAFollowingTabThatOpensOnWhatHoldsSomething() {
        let both = [stream("x.bookmarks", "Bookmarks", .saved, count: 4), stream("x.following", "Following", .following, count: 842)]
        XCTAssertEqual(SourceStreamItems.peopleTabs(both).map(\.label), ["Bookmarks", "Following"])
        XCTAssertEqual(SourceStreamItems.peopleSelection(nil, streams: both), "x.following")
        XCTAssertEqual(SourceStreamItems.peopleSelection("x.bookmarks", streams: both), SourceStreamItems.listsTab)
        let empty = [stream("x.bookmarks", "Bookmarks", .saved, count: 4), stream("x.following", "Following", .following, count: nil)]
        XCTAssertEqual(SourceStreamItems.peopleSelection(nil, streams: empty), SourceStreamItems.listsTab,
                       "the lists hold something and Following nothing yet: the tab that holds something")
        let none = [stream("x.following", "Following", .following, count: nil)]
        XCTAssertEqual(SourceStreamItems.peopleSelection(nil, streams: none), "x.following", "nothing else holds anything")
        let off = [stream("x.bookmarks", "Bookmarks", .saved, count: 4), stream("x.following", "Following", .following, count: nil, on: false)]
        XCTAssertEqual(SourceStreamItems.peopleTabs(off).map(\.label), ["Bookmarks", "Following"], "off, it still has its tab and says so")
        XCTAssertEqual(SourceStreamRow.line(both[1].stream), Copy.Streams.followingFor, "what it is for, since its name does not say")
        XCTAssertNil(SourceStreamItems.peopleSelection(nil, streams: [stream("x.bookmarks", "Bookmarks", .saved, count: 3)]))
    }

    func testTheWireShapeIsLenientAndTheRowSaysItsNameThenItsHandle() throws {
        let json = #"""
        {"rows": [{"id": "a1", "name": "Erin Example", "handle": "erin_example", "url": "https://x.com/erin_example",
                   "day": "2026-11-24", "page": "erin-example", "proposed": false, "extra": [1, 2]},
                  {"id": "b2", "name": 7, "handle": "bare"}, {"name": "no id"}],
         "total": 3, "offset": 0, "next": 50, "kept": "many"}
        """#.data(using: .utf8)!
        let page = try JSONDecoder().decode(FollowedAccountsPage.self, from: json)
        XCTAssertEqual(page.rows.count, 2, "a row with no id is dropped, not the page")
        XCTAssertEqual(page.rows[0].page, "erin-example")
        XCTAssertEqual(page.rows[1].name, "", "a malformed field drops that field alone")
        XCTAssertEqual(page.rows[1].title, "@bare")
        XCTAssertEqual(page.next, 50)
        XCTAssertEqual(page.kept, 3, "a malformed count falls back to the total")
        XCTAssertEqual(FollowedAccountsText.handleLine(page.rows[0]), "@erin_example")
        XCTAssertNil(FollowedAccountsText.handleLine(FollowedAccount(id: "c", name: "Erin_Example", handle: "erin_example")),
                     "a name that is the handle says it once")
    }

    func testAProfileLinkIsOpenedOnlyWhenItIsAWebAddressWithAHost() {
        XCTAssertNotNil(FollowedAccountsText.profile(FollowedAccount(id: "a", name: "A", url: "https://x.com/a")))
        XCTAssertNil(FollowedAccountsText.profile(FollowedAccount(id: "a", name: "A", url: "javascript:alert(1)")))
        XCTAssertNil(FollowedAccountsText.profile(FollowedAccount(id: "a", name: "A", url: "https:///nohost")))
        XCTAssertNil(FollowedAccountsText.profile(FollowedAccount(id: "a", name: "A", url: nil)))
    }

    func testTheDayIsWhenFollowingBeganAndEmptyStatesNameWhatIsMissing() {
        let row = FollowedAccount(id: "a", name: "A", day: "2026-11-14")
        let today = ISODay("2026-11-24")!
        let since = FollowedAccountsText.since(row, today: today, locale: Locale(identifier: "en_US"))
        XCTAssertEqual(since?.text, "since Nov 14")
        XCTAssertNil(FollowedAccountsText.since(FollowedAccount(id: "b", name: "B"), today: today))
        XCTAssertEqual(FollowedAccountsText.empty(streamOn: false, searching: false), .off)
        XCTAssertEqual(FollowedAccountsText.empty(streamOn: true, searching: false), .waiting)
        XCTAssertEqual(FollowedAccountsText.empty(streamOn: true, searching: true), .noMatch)
    }

    func testTheModelHoldsRowsInMemoryPagesThemAndForgetsAtOnce() async {
        let model = FollowedAccountsModel()
        func page(_ ids: [String], next: Int?, total: Int) -> FollowedAccountsPage {
            FollowedAccountsPage(rows: ids.map { FollowedAccount(id: $0, name: $0.uppercased()) }, total: total, next: next, kept: total)
        }
        await model.load(query: "", using: { _, offset, _ in
            XCTAssertEqual(offset, 0)
            return page(["a", "b"], next: 2, total: 3)
        })
        XCTAssertEqual(model.rows.map(\.id), ["a", "b"])
        XCTAssertTrue(model.hasMore)
        await model.more(using: { _, offset, _ in
            XCTAssertEqual(offset, 2)
            return page(["b", "c"], next: nil, total: 3)
        })
        XCTAssertEqual(model.rows.map(\.id), ["a", "b", "c"], "a row already in hand is not shown twice")
        XCTAssertFalse(model.hasMore)
        await model.load(query: "", kept: 0, using: { _, _, _ in throw APIError.serverUnreachable })
        XCTAssertTrue(model.rows.isEmpty, "forgotten means gone from the screen")
        XCTAssertEqual(model.phase, .loaded, "an empty list, not an error about names that are gone")
        await model.load(query: "", kept: 1, using: { _, _, _ in page(["d"], next: nil, total: 1) })
        await model.load(query: "", kept: 1, using: { _, _, _ in throw APIError.serverUnreachable })
        XCTAssertEqual(model.rows.map(\.id), ["d"], "a read that fails leaves what is kept")
    }
}
