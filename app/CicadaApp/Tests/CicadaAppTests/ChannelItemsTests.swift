import XCTest
@testable import CicadaApp

/// A `ChannelItemsAPI` that answers from a queue and records what each call asked for.
@MainActor
final class FakeChannelItemsAPI: ChannelItemsAPI {
    struct Call: Equatable { let channel: String; let offset: Int; let limit: Int; let etag: String? }

    var replies: [Result<Conditional<ChannelItemsPage>, any Error>] = []
    private(set) var calls: [Call] = []

    func fetchChannelItems(channel: String, offset: Int, limit: Int, etag: String?) async throws
        -> Conditional<ChannelItemsPage> {
        calls.append(Call(channel: channel, offset: offset, limit: limit, etag: etag))
        guard !replies.isEmpty else { throw APIError.serverUnreachable }
        return try replies.removeFirst().get()
    }
}

/// G161 — what came in, by name: the wire, the pure rules, the in-memory cache and where a row opens.
@MainActor
final class ChannelItemsTests: XCTestCase {
    private let us = Locale(identifier: "en_US")

    private func item(_ n: Int, kind: ChannelItem.Kind = .episode) -> ChannelItem {
        ChannelItem(kind: kind, id: "id-\(n)", title: "Item \(n)", day: "2026-09-\(String(format: "%02d", n % 28 + 1))")
    }

    private func page(_ range: Range<Int>, total: Int, offset: Int = 0) -> ChannelItemsPage {
        ChannelItemsPage(channel: "notes", total: total, offset: offset, items: range.map { item($0) })
    }

    private func fresh(_ p: ChannelItemsPage, _ etag: String) -> Result<Conditional<ChannelItemsPage>, any Error> {
        .success(Conditional(value: p, etag: etag, notModified: false))
    }

    // MARK: The wire

    func testThePageDecodesLenientlyAndAnUnknownKindOpensNothing() throws {
        let json = """
        {"channel": "notes", "total": 3, "offset": 0, "limit": 50, "items": [
          {"kind": "episode", "id": "ep_2026-09-01_001", "title": "Garden plan", "day": "2026-09-01"},
          {"kind": "media", "id": "media-one", "title": "One", "day": null},
          {"kind": "hologram", "id": "x"}
        ]}
        """
        let decoded = try JSONDecoder().decode(ChannelItemsPage.self, from: Data(json.utf8))
        XCTAssertEqual(decoded.total, 3)
        XCTAssertEqual(decoded.items.map(\.kind), [.episode, .media, .unknown])
        XCTAssertNil(decoded.items[1].day)
        XCTAssertEqual(decoded.items[2].title, "")
        XCTAssertNil(CapturedItemRoute.of(decoded.items[2], interactive: true))
    }

    func testAPageWithNoTotalCountsItsItems() throws {
        let decoded = try JSONDecoder().decode(ChannelItemsPage.self,
                                               from: Data(#"{"items": [{"id": "a", "kind": "page"}]}"#.utf8))
        XCTAssertEqual(decoded.total, 1)
    }

    func testTheChannelIdIsEncodedInThePath() {
        XCTAssertEqual(APIClient.channelItemsPath("chat-export:claude", offset: 20, limit: 20),
                       "/sources/channels/chat-export:claude/items?offset=20&limit=20")
        XCTAssertEqual(APIClient.channelItemsPath("folder:a/b?c#d", offset: -1, limit: 0),
                       "/sources/channels/folder:a%2Fb%3Fc%23d/items?offset=0&limit=1")
    }

    // MARK: Where a row opens

    func testEachKindOpensWhereItLives() {
        XCTAssertEqual(CapturedItemRoute.of(ChannelItem(kind: .episode, id: "ep_1", title: "Chat"), interactive: true),
                       .reader(episode: "ep_1", title: "Chat"))
        XCTAssertEqual(CapturedItemRoute.of(ChannelItem(kind: .media, id: "media-1", title: "Link"), interactive: true),
                       .feed(mediaEntityId: "media-1"))
        XCTAssertEqual(CapturedItemRoute.of(ChannelItem(kind: .page, id: "bob-example", title: "Bob"), interactive: true),
                       .entity("bob-example"))
    }

    func testAPreviewOpensNothing() {
        for kind in [ChannelItem.Kind.episode, .media, .page] {
            XCTAssertNil(CapturedItemRoute.of(ChannelItem(kind: kind, id: "x", title: "X"), interactive: false))
        }
        XCTAssertNil(CapturedItemRoute.of(ChannelItem(kind: .episode, id: "", title: "X"), interactive: true))
    }

    // MARK: The pure rules

    func testTheListStartsCollapsedUnderItsOwnKey() {
        XCTAssertEqual(CapturedItems.openKey("notes"), "cicada.sources.capturedOpen.notes")
        XCTAssertNotEqual(CapturedItems.openKey("notes"), CapturedItems.openKey("calendar-local"))
        let defaults = UserDefaults(suiteName: "g161-\(UUID().uuidString)")!
        XCTAssertFalse(defaults.bool(forKey: CapturedItems.openKey("notes")), "collapsed until the viewer opens it")
        XCTAssertEqual(CapturedItems.pageSize, 20)
    }

    func testTheAgeIsCompactForThePastADateAheadAndTheFullDateAsHelp() throws {
        let today = ISODay(year: 2026, month: 9, day: 28)
        let past = try XCTUnwrap(CapturedItems.age(ChannelItem(kind: .episode, id: "a", title: "A", day: "2026-09-19"),
                                                   today: today, locale: us))
        XCTAssertEqual(past.text, "9d")
        XCTAssertEqual(past.help, "Saturday, September 19, 2026")
        let ahead = try XCTUnwrap(CapturedItems.age(ChannelItem(kind: .episode, id: "b", title: "B", day: "2026-10-03"),
                                                    today: today, locale: us))
        XCTAssertEqual(ahead.text, "Oct 3", "a calendar event still ahead reads as its date, never 'today'")
        XCTAssertNil(CapturedItems.age(ChannelItem(kind: .page, id: "c", title: "C"), today: today))
    }

    func testARefreshCoversEveryRowShownUpToTheServersCap() {
        XCTAssertEqual(CapturedItems.refreshLimit(shown: 0), 20)
        XCTAssertEqual(CapturedItems.refreshLimit(shown: 20), 20)
        XCTAssertEqual(CapturedItems.refreshLimit(shown: 21), 40)
        XCTAssertEqual(CapturedItems.refreshLimit(shown: 900), 200)
    }

    func testTheUnitIsTheListsOwn() {
        XCTAssertEqual(CapturedItems.noun(channel: "notes", countNoun: "note").many, "notes")
        XCTAssertEqual(CapturedItems.noun(channel: "contacts-local", countNoun: "contact").many, "people")
        XCTAssertEqual(CapturedItems.noun(channel: "calendar", countNoun: "calendar").many, "events")
        XCTAssertEqual(CapturedItems.noun(channel: "pinterest", countNoun: nil).many, "items")
        XCTAssertEqual(Copy.capturedShown(20, of: 1_035, noun: ("note", "notes"), locale: us), "20 of 1,035 notes")
        XCTAssertEqual(Copy.capturedShown(1, of: 1, noun: ("person", "people"), locale: us), "1 of 1 person")
    }

    func testAnImportRowListsOnlyAChannelThatBroughtSomethingIn() {
        let notes = SourceChannel(id: "notes", label: "Apple Notes", connected: true, count: 229)
        let empty = SourceChannel(id: "calendar-local", label: "Apple Calendar")
        let entry = { (id: FoundItemID) in
            ImportEntry(id: id, category: .notesAndFiles, title: "T", origin: "o", meta: "m", idleLine: "i")
        }
        XCTAssertEqual(ImportRows.capturedChannel(entry(.app("notes")), channels: [notes, empty]), "notes")
        XCTAssertNil(ImportRows.capturedChannel(entry(.app("calendar-local")), channels: [notes, empty]))
        XCTAssertNil(ImportRows.capturedChannel(entry(.agent("codex")), channels: [notes, empty]))
    }

    // MARK: The cache

    func testTheFirstPageLoadsThenRevalidatesWithItsETag() async {
        let api = FakeChannelItemsAPI()
        api.replies = [fresh(page(0..<20, total: 45), "\"a\""),
                       .success(Conditional(value: nil, etag: "\"a\"", notModified: true))]
        let cache = ChannelItemsCache(api: api)
        XCTAssertEqual(cache.phase("notes"), .idle)
        await cache.refresh("notes")
        XCTAssertEqual(cache.list("notes")?.items.count, 20)
        XCTAssertEqual(cache.list("notes")?.total, 45)
        XCTAssertEqual(cache.list("notes")?.hasMore, true)
        XCTAssertEqual(cache.phase("notes"), .loaded)
        await cache.refresh("notes")
        XCTAssertEqual(api.calls.map(\.etag), [nil, "\"a\""], "the second read sends the tag it was given")
        XCTAssertEqual(cache.list("notes")?.items.count, 20, "a 304 keeps the list as it is")
    }

    func testShowMoreAppendsTheNextPageOnceAndTheNextRefreshAsksForEveryRowShown() async {
        let api = FakeChannelItemsAPI()
        api.replies = [fresh(page(0..<20, total: 45), "\"a\""),
                       // the next page overlaps one row the list already holds (a new item shifted the pages)
                       fresh(page(19..<39, total: 45, offset: 20), "\"b\""),
                       fresh(page(0..<39, total: 45), "\"c\"")]
        let cache = ChannelItemsCache(api: api)
        await cache.refresh("notes")
        await cache.loadMore("notes")
        XCTAssertEqual(cache.list("notes")?.items.count, 39, "a row already shown is never shown twice")
        XCTAssertEqual(api.calls[1], .init(channel: "notes", offset: 20, limit: 20, etag: nil))
        await cache.refresh("notes")
        XCTAssertEqual(api.calls[2], .init(channel: "notes", offset: 0, limit: 40, etag: nil),
                       "another limit is another body: no tag, every row shown")
    }

    func testAShortPageEndsTheList() async {
        let api = FakeChannelItemsAPI()
        api.replies = [fresh(page(0..<20, total: 30), "\"a\""), fresh(page(20..<25, total: 30, offset: 20), "\"b\"")]
        let cache = ChannelItemsCache(api: api)
        await cache.refresh("notes")
        await cache.loadMore("notes")
        XCTAssertEqual(cache.list("notes")?.hasMore, false, "no 'Show more' that could never load anything")
    }

    func testAFailureKeepsTheLastListAndSaysSoOnlyWithNothingToShow() async {
        let api = FakeChannelItemsAPI()
        api.replies = [.failure(APIError.serverUnreachable), fresh(page(0..<3, total: 3), "\"a\""),
                       .failure(APIError.serverUnreachable)]
        let cache = ChannelItemsCache(api: api)
        await cache.refresh("notes")
        XCTAssertEqual(cache.phase("notes"), .failed(Copy.capturedLoadFailed))
        await cache.refresh("notes")
        await cache.refresh("notes")
        XCTAssertEqual(cache.list("notes")?.items.count, 3, "never blank")
        XCTAssertEqual(cache.phase("notes"), .loaded)
    }

    func testAnUnknownChannelIsGoneAndABankSwitchForgetsEverything() async {
        let api = FakeChannelItemsAPI()
        api.replies = [fresh(page(0..<3, total: 3), "\"a\""), .failure(APIError.httpError(404, "Unknown channel")),
                       fresh(page(0..<2, total: 2), "\"b\"")]
        let cache = ChannelItemsCache(api: api)
        await cache.refresh("notes")
        await cache.refresh("notes")
        XCTAssertNil(cache.list("notes"))
        XCTAssertEqual(cache.phase("notes"), .gone)
        await cache.refresh("wispr-flow")
        cache.reset()
        XCTAssertNil(cache.list("wispr-flow"))
        XCTAssertEqual(cache.phase("wispr-flow"), .idle)
        api.replies = [fresh(page(0..<1, total: 1), "\"c\"")]
        await cache.refresh("wispr-flow")
        XCTAssertNil(api.calls.last?.etag, "a switched bank never revalidates another bank's tag")
    }
}
