import XCTest
@testable import CicadaApp

/// G246 (ruling 81, plan Track 2b) — a list's page is reachable from its source: the stream row carries which page stands
/// for it, the Sources list's header opens it, and a row with no page of its own offers "Keep as a page" without a call.
/// The backend decides everything and names a page only once one exists (never while the posts-as-rows switch is off); the
/// app draws what it says and nothing at all otherwise. Synthetic data only.
@MainActor
final class SourceListPageLinkTests: XCTestCase {
    private func stream(_ id: String, label: String, count: Int = 3, folders: Int = 0, page: String? = nil,
                        folderPages: [String: String] = [:]) -> ResolvedStream {
        ResolvedStream(
            source: "x",
            stream: SourceStream(id: id, label: label, kind: .saved, state: .on, count: count, folderCount: folders,
                                 page: page, folderPages: folderPages),
            word: .read, fix: nil, reader: nil)
    }

    // MARK: The wire

    func testAStreamRowCarriesItsPageAndItsFolders() throws {
        let wire = #"{"id":"x.bookmarks","label":"Bookmarks","kind":"saved","how":"browser","state":"on","count":3,"#
            + #""page":"list-x-bookmarks","folderPages":{"Design ideas":"list-x-bookmarks--design-ideas-a1b2c3"}}"#
        let row = try JSONDecoder().decode(SourceStream.self, from: Data(wire.utf8))
        XCTAssertEqual(row.page, "list-x-bookmarks")
        XCTAssertEqual(row.folderPages, ["Design ideas": "list-x-bookmarks--design-ideas-a1b2c3"])
    }

    func testARowFromABackendThatSendsNoPageHasNoneAndASwitchedOffBackendSaysNothing() throws {
        let bare = try JSONDecoder().decode(SourceStream.self, from: Data(#"{"id":"x.bookmarks","label":"Bookmarks"}"#.utf8))
        XCTAssertNil(bare.page)
        XCTAssertEqual(bare.folderPages, [:])
        let blank = try JSONDecoder().decode(
            SourceStream.self, from: Data(#"{"id":"x.likes","label":"Likes","page":"","folderPages":{"":"a","Trips":""}}"#.utf8))
        XCTAssertNil(blank.page, "an empty answer is no page")
        XCTAssertEqual(blank.folderPages, [:])
        let wrong = try JSONDecoder().decode(
            SourceStream.self, from: Data(#"{"id":"x.likes","label":"Likes","page":4,"folderPages":"no"}"#.utf8))
        XCTAssertNil(wrong.page)
        XCTAssertEqual(wrong.folderPages, [:])
    }

    func testTheFixtureOfEveryExistingStreamStillDecodesWithNoPage() throws {
        let response = try SourceStreamsFixture.load()
        let all = response.sources.flatMap(\.streams)
        XCTAssertFalse(all.isEmpty)
        XCTAssertTrue(all.allSatisfy { $0.page == nil && $0.folderPages.isEmpty })
    }

    // MARK: The header's link

    func testAListWithOneStreamLinksItsPageAndNoTabIsNeeded() {
        let only = [stream("x.bookmarks", label: "Bookmarks", page: "list-x-bookmarks")]
        XCTAssertEqual(SourceStreamItems.pageLink(nil, folder: nil, streams: only),
                       SourceStreamItems.PageLink(id: "list-x-bookmarks", isFolder: false))
    }

    func testTheOpenTabsPageIsTheOneLinkedAndAllLinksNone() {
        let both = [stream("x.bookmarks", label: "Bookmarks", page: "list-x-bookmarks"),
                    stream("x.likes", label: "Likes", page: "list-x-likes")]
        XCTAssertNil(SourceStreamItems.pageLink(nil, folder: nil, streams: both), "All is no one list")
        XCTAssertEqual(SourceStreamItems.pageLink("x.likes", folder: nil, streams: both)?.id, "list-x-likes")
        XCTAssertEqual(SourceStreamItems.pageLink("x.bookmarks", folder: nil, streams: both)?.id, "list-x-bookmarks")
    }

    func testAChosenFolderLinksItsOwnPageAndAFolderWithNoneLinksNothing() {
        let kept = [stream("x.bookmarks", label: "Bookmarks", folders: 2, page: "list-x-bookmarks",
                           folderPages: ["Design ideas": "list-x-bookmarks--design-ideas-a1b2c3"])]
        XCTAssertEqual(SourceStreamItems.pageLink(nil, folder: "Design ideas", streams: kept),
                       SourceStreamItems.PageLink(id: "list-x-bookmarks--design-ideas-a1b2c3", isFolder: true))
        XCTAssertNil(SourceStreamItems.pageLink(nil, folder: "Trips", streams: kept), "a folder with no page: no link, never the list's")
        XCTAssertEqual(SourceStreamItems.pageLink(nil, folder: nil, streams: kept)?.isFolder, false)
        XCTAssertEqual(SourceStreamItems.pageLink(nil, folder: "", streams: kept)?.id, "list-x-bookmarks")
    }

    func testNoPageNamedMeansNoLinkWhateverElseIsOn() {
        // The switch is off, the list has nothing in it, or it is a list of works: the backend names no page.
        let dark = [stream("x.bookmarks", label: "Bookmarks", folders: 1), stream("x.likes", label: "Likes")]
        for tab in [nil, "x.bookmarks", "x.likes"] {
            XCTAssertNil(SourceStreamItems.pageLink(tab, folder: nil, streams: dark), tab ?? "All")
            XCTAssertNil(SourceStreamItems.pageLink(tab, folder: "Design ideas", streams: dark))
        }
        XCTAssertNil(SourceStreamItems.pageLink(nil, folder: nil, streams: []))
    }

    func testAStreamWithNothingInItIsNoTabAndHasNoLink() {
        let empty = [stream("x.bookmarks", label: "Bookmarks", count: 0, page: "list-x-bookmarks")]
        XCTAssertNil(SourceStreamItems.pageLink(nil, folder: nil, streams: empty), "nothing held is not drawn (DR-81)")
    }

    func testTheLinkSaysWhatItOpensInPlainWords() {
        let list = SourceStreamItems.PageLink(id: "a", isFolder: false)
        let folder = SourceStreamItems.PageLink(id: "b", isFolder: true)
        XCTAssertEqual([list.title, folder.title], ["List page", "Folder page"])
        for words in [list.title, list.help, folder.title, folder.help] {
            for jargon in ["Sleep", "episode", "stream", "HIDE", "claim", "G246", "ruling", "entity", "media"] {
                XCTAssertFalse(words.contains(jargon), "\(words) names an internal word")
            }
        }
    }

    // MARK: A row that may be kept

    func testARowWithNoWordOfferNothingAndTheWordsOfARowAndAKeptPostOfferTheirControl() throws {
        func item(_ keep: String?) throws -> ChannelItem {
            let body = keep.map { #","keep":"\#($0)""# } ?? ""
            return try JSONDecoder().decode(ChannelItem.self, from: Data(#"{"kind":"media","id":"media-a-post","title":"A post"\#(body)}"#.utf8))
        }
        XCTAssertFalse(SourceItemRow.offersKeep(try item(nil)), "an older backend, or the switch off: no control")
        XCTAssertTrue(SourceItemRow.offersKeep(try item("row")))
        XCTAssertTrue(SourceItemRow.offersKeep(try item("kept")))
        XCTAssertFalse(SourceItemRow.offersKeep(try item("page")), "something else holds its page")
        XCTAssertFalse(SourceItemRow.offersKeep(try item("none")))
        XCTAssertEqual(try item("row").keep, "row")
        let round = try JSONDecoder().decode(ChannelItem.self, from: try JSONEncoder().encode(try item("kept")))
        XCTAssertEqual(round.keep, "kept")
    }

    func testOnlyAMediaRowOffersItEvenIfSomethingSentTheWord() {
        var chat = ChannelItem(kind: .chat, id: "c", title: "A chat")
        chat.keep = "row"
        XCTAssertFalse(SourceItemRow.offersKeep(chat))
        var page = ChannelItem(kind: .page, id: "p", title: "A page")
        page.keep = "row"
        XCTAssertFalse(SourceItemRow.offersKeep(page))
    }

    func testARowsSeededStateOffersWhatTheBackendToldItWithoutAnyCall() {
        let row = KeepAsPage.seeded("row", page: "media-a-post")
        XCTAssertEqual(KeepAsPage.offer(row), .keep)
        XCTAssertEqual(row.mediaEntityId, "media-a-post")
        XCTAssertEqual(KeepAsPage.offer(KeepAsPage.seeded("kept", page: "media-a-post")), .back)
        for word in [nil, "", "page", "none", "unheard-of"] { XCTAssertNil(KeepAsPage.offer(KeepAsPage.seeded(word, page: "m")), word ?? "nil") }
    }

    func testPressingAKeepOnARowSendsItsPageAndTurnsIntoTheWayBackWithNoRead() async {
        var read = 0
        var sent: [(String, Bool)] = []
        let model = KeepAsPageModel(
            fetch: { _ in read += 1; return .none },
            send: { page, kept in
                sent.append((page, kept))
                return KeepAsPageReply(status: "kept", state: KeepAsPage.seeded("kept", page: page))
            })
        model.seed(KeepAsPage.seeded("row", page: "media-a-post"))
        XCTAssertEqual(model.offer, .keep)
        let reply = await model.press(url: "media-a-post")
        XCTAssertEqual(reply?.status, "kept")
        XCTAssertEqual(sent.map(\.0), ["media-a-post"])
        XCTAssertEqual(sent.map(\.1), [true])
        XCTAssertEqual(model.offer, .back)
        XCTAssertEqual(model.done, Copy.Keep.kept)
        XCTAssertEqual(read, 0, "a row reads nothing of its own: the list already said")
        // Seeding again (the list refreshed) never wipes what the click said.
        model.seed(KeepAsPage.seeded("kept", page: "media-a-post"))
        XCTAssertEqual(model.done, Copy.Keep.kept)
    }
}
