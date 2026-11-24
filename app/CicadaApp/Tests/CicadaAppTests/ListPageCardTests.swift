import XCTest
@testable import CicadaApp

/// G246 (ruling 81) — the page of one list of saved posts: the block decodes from the backend's own
/// `api/tests/fixtures/list_block.json` (`test_list_pages.py` builds the same file), the card says each fact once, an empty
/// list draws nothing, and find opens a list's page (the one media page the palette takes from the graph).
final class ListPageCardTests: XCTestCase {
    private static func fixture(_ key: String) throws -> PageBlocks.ListBlock {
        let root = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()   // CicadaAppTests
            .deletingLastPathComponent()   // Tests
            .deletingLastPathComponent()   // CicadaApp (package root)
            .deletingLastPathComponent()   // app
            .deletingLastPathComponent()   // repo root
        let file = root.appendingPathComponent("api/tests/fixtures/list_block.json")
        let object = try JSONSerialization.jsonObject(with: Data(contentsOf: file)) as? [String: Any]
        let lists = try XCTUnwrap(object?["lists"] as? [String: Any])
        return try JSONDecoder().decode(PageBlocks.ListBlock.self,
                                        from: JSONSerialization.data(withJSONObject: try XCTUnwrap(lists[key])))
    }

    func testTheBackendsBlockDecodesWholeAndNamesTheCardsListKey() throws {
        let whole = try Self.fixture("list-x-bookmarks")
        XCTAssertEqual(whole.count, 3)
        XCTAssertEqual(whole.newest, "2026-11-09")
        XCTAssertEqual(whole.source, "x-bookmarks")
        XCTAssertNil(whole.folder)
        XCTAssertNil(whole.why)
        XCTAssertEqual(whole.listKey, SourceListKey.make("x", stream: "x.bookmarks"))
        let folder = try Self.fixture("list-x-bookmarks-folder")
        XCTAssertEqual(folder.folder, "Trips")
        XCTAssertEqual(folder.why?.text, "ideas for next spring")
        XCTAssertEqual(SourceListKey.streamParts(folder.listKey)?.folder, "Trips")
        XCTAssertEqual(SourceListKey.streamParts(folder.listKey)?.stream, "x.bookmarks")
    }

    func testABackendWithNoListBlockDecodesAsNone() throws {
        let b = try JSONDecoder().decode(PageBlocks.self, from: Data(#"{"shape":"blocks-7","order":[]}"#.utf8))
        XCTAssertNil(b.list)
        let with = try JSONDecoder().decode(
            PageBlocks.self, from: Data(#"{"shape":"blocks-8","order":["list"],"list":{"stream":"x.likes","count":2}}"#.utf8))
        XCTAssertEqual(with.list?.stream, "x.likes")
        XCTAssertEqual(with.list?.count, 2)
        let broken = try JSONDecoder().decode(PageBlocks.self, from: Data(#"{"shape":"blocks-8","list":{"count":"many"}}"#.utf8))
        XCTAssertNil(broken.list, "a malformed block is nil, never a failed card")
    }

    func testTheStatsLineSaysEachFactOnceAndNeverInventsADay() throws {
        let today = try XCTUnwrap(ISODay("2026-11-24"))
        var list = PageBlocks.ListBlock(stream: "x.bookmarks", count: 204, newest: "2026-11-23")
        XCTAssertEqual(ListPageCard.stats(list, today: today, locale: Locale(identifier: "en_US")), "204 saved · newest yesterday")
        list.lastReadAt = "2026-11-20T08:00:00Z"
        XCTAssertEqual(ListPageCard.stats(list, today: today, locale: Locale(identifier: "en_US")), "204 saved · newest yesterday · last read Friday")
        list.newest = nil
        list.lastReadAt = nil
        XCTAssertEqual(ListPageCard.stats(list, today: today, locale: Locale(identifier: "en_US")), "204 saved", "no day the list has not reached is invented")
        list.newest = "2026-09-09"
        XCTAssertEqual(ListPageCard.stats(list, today: today, locale: Locale(identifier: "en_US")), "204 saved · newest Sep 9")
    }

    func testTheLineIsTheFirstSentenceTheListSaysAboutItself() {
        XCTAssertEqual(ListPageCard.about("Posts you bookmarked on X.\n"), "Posts you bookmarked on X.")
        XCTAssertEqual(ListPageCard.about("\n## Summary\n\nPosts in “Trips”, a folder of your bookmarks on X.\n"),
                       "Posts in “Trips”, a folder of your bookmarks on X.")
        XCTAssertEqual(ListPageCard.about(""), "")
    }

    func testAListWithNothingInItIsNotDrawnAndShowsFiveRowsAtMost() {
        XCTAssertFalse(ListPageCard.isDrawn(PageBlocks.ListBlock(stream: "x.bookmarks", count: 0)))
        XCTAssertTrue(ListPageCard.isDrawn(PageBlocks.ListBlock(stream: "x.bookmarks", count: 1)))
        XCTAssertEqual(ListPageCard.cap, 5, "DR-81: an open section holds at most five rows, then All N")
    }

    func testFindOpensAListsPageAndNoOtherMediaPage() {
        let list = GraphNode(id: "list-x-bookmarks", name: "X: Bookmarks", type: .media, mediaKind: "list",
                             origin: "x-bookmarks")
        let saved = GraphNode(id: "media-alpha", name: "Alpha paper notes", type: .media, mediaKind: "link")
        let docs = QuickIndex.entityDocs([list, saved])
        XCTAssertEqual(docs.map(\.row.key.id), ["list-x-bookmarks"])
        XCTAssertEqual(docs.first?.row.badge, "List")
        XCTAssertEqual(docs.first?.row.destination, .entity(id: "list-x-bookmarks"))
        if case .origin(let mark)? = docs.first?.row.mark { XCTAssertEqual(mark, "x-bookmarks") } else {
            XCTFail("a list wears its site's real mark (DR-52)")
        }
    }

    func testAListPageKeepsItsBlockInTheCardAndSkipsTheWhyItMattersSlot() {
        var media = MediaBlock(url: "", mediaType: "list")
        media.kind = "list"
        XCTAssertFalse(PageInShort.isDrawn(relevance: nil, media: media), "a list says what it is in its own head")
        XCTAssertTrue(media.isList)
    }
}
