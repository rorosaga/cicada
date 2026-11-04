import AppKit
import XCTest
@testable import CicadaApp

@MainActor
private final class FakeBookAPI: ChannelItemsAPI {
    var book = ContactsBook()
    var fails = false
    private(set) var reads = 0
    func fetchChannelItems(channel: String, offset: Int, limit: Int, etag: String?) async throws
        -> Conditional<ChannelItemsPage> { throw APIError.serverUnreachable }
    func fetchContactsBook() async throws -> ContactsBook {
        reads += 1
        if fails { throw APIError.serverUnreachable }
        return book
    }
}

@MainActor
private final class SlowBookAPI: ChannelItemsAPI {
    var book = ContactsBook()
    var error: (any Error)?
    var hold = false
    private(set) var waiting: CheckedContinuation<Void, Never>?
    func fetchChannelItems(channel: String, offset: Int, limit: Int, etag: String?) async throws
        -> Conditional<ChannelItemsPage> { throw APIError.serverUnreachable }
    func fetchContactsBook() async throws -> ContactsBook {
        if let error { throw error }
        let answer = book
        if hold { await withCheckedContinuation { waiting = $0 } }
        return answer
    }
    func release() { waiting?.resume(); waiting = nil }
}

/// G154 (owner 2026-11-04) — the Contacts page's faces: the wire shape, the one line, the in-memory search, the cache's
/// forget, and a thumbnail's address. Synthetic people only.
@MainActor
final class ContactsGridTests: XCTestCase {
    private func book(_ cards: [ContactsBookCard], inMemory: Int = 0) -> ContactsBook {
        var book = ContactsBook()
        book.total = cards.count
        book.inMemory = inMemory
        book.cards = cards
        return book
    }

    func testTheBookDecodesTheWireAndARowItCannotReadStaysAFace() throws {
        let json = #"{"total":2,"inMemory":1,"cards":[{"key":"aaaa","name":"Bób Example","entityId":"bob-example","photo":"abc"},{"key":"bbbb"}]}"#
        let book = try JSONDecoder().decode(ContactsBook.self, from: Data(json.utf8))
        XCTAssertEqual(book.total, 2)
        XCTAssertEqual(book.inMemory, 1)
        XCTAssertEqual(book.cards[0].entityId, "bob-example")
        XCTAssertEqual(book.cards[0].folded, "bob example")
        XCTAssertEqual(book.cards[1].name, "")
        XCTAssertNil(book.cards[1].entityId)
    }

    func testOneLineSaysHowManyAndHowManyInMemoryOnlyWhenAny() {
        let en = Locale(identifier: "en_US")
        XCTAssertEqual(Copy.SourceBrowser.contactsLine(total: 376, inMemory: 6, locale: en), "376 contacts · 6 in memory")
        XCTAssertEqual(Copy.SourceBrowser.contactsLine(total: 370, inMemory: 0, locale: en), "370 contacts")
        XCTAssertEqual(Copy.SourceBrowser.contactsLine(total: 1, inMemory: 1, locale: en), "1 contact · 1 in memory")
    }

    func testSearchFoldsEveryWordAndANamelessCardOnlyShowsWithNoQuery() {
        let cards = [ContactsBookCard(key: "a", name: "Ánn Example"), ContactsBookCard(key: "b", name: "Mononym"),
                     ContactsBookCard(key: "c", name: "")]
        XCTAssertEqual(ContactsBookSearch.filter(cards, query: "").count, 3)
        XCTAssertEqual(ContactsBookSearch.filter(cards, query: "  ").count, 3)
        XCTAssertEqual(ContactsBookSearch.filter(cards, query: "example ann").map(\.key), ["a"])
        XCTAssertEqual(ContactsBookSearch.filter(cards, query: "MONO").map(\.key), ["b"])
        XCTAssertEqual(ContactsBookSearch.filter(cards, query: "no name"), [])
    }

    func testANamelessCardIsTitledWithoutAnyOtherFact() {
        XCTAssertEqual(ContactsBookText.title(ContactsBookCard(key: "c", name: "")), "No name")
        XCTAssertEqual(ContactsBookText.title(ContactsBookCard(key: "a", name: "Mononym")), "Mononym")
    }

    func testAThumbnailIsAskedOnlyByTheHashesTheBackendMade() {
        XCTAssertEqual(SourcePictures.contactPhotoPath(key: "abc123", photo: "def456"),
                       "/sources/contacts-local/book/abc123/photo?v=def456")
        XCTAssertNil(SourcePictures.contactPhotoPath(key: "abc123", photo: nil))
        XCTAssertNil(SourcePictures.contactPhotoPath(key: "../x", photo: "def456"))
        XCTAssertNil(SourcePictures.contactPhotoPath(key: "abc123", photo: "a/b"))
    }

    func testAFailedReadKeepsWhatIsHeldAndSaysSoOnlyWithNothingHeld() async {
        let api = FakeBookAPI()
        let cache = ChannelItemsCache(api: api)
        api.fails = true
        await cache.refreshContactsBook()
        XCTAssertNil(cache.contactsBook)
        XCTAssertNotNil(cache.contactsBookFailure)
        api.fails = false
        api.book = book([ContactsBookCard(key: "a", name: "Ann Example")])
        await cache.refreshContactsBook()
        XCTAssertEqual(cache.contactsBook?.total, 1)
        XCTAssertNil(cache.contactsBookFailure)
        api.fails = true
        await cache.refreshContactsBook()
        XCTAssertEqual(cache.contactsBook?.total, 1, "never blank")
    }

    func testThePageNeverDrawsNothingWhileTheBookIsOnItsWay() {
        let empty = ContactsBook()
        let full = book([ContactsBookCard(key: "a", name: "Ann Example")])
        let of = ContactsGridPhase.of
        XCTAssertEqual(of(nil, nil, false, nil), .loading, "the first read")
        XCTAssertEqual(of(nil, nil, true, nil), .loading)
        XCTAssertEqual(of(nil, "down", false, nil), .failed("down"))
        XCTAssertEqual(of(nil, "down", true, nil), .loading, "a post under way will read again")
        XCTAssertEqual(of(empty, nil, true, nil), .loading, "connected and not yet posted: the owner's first launch")
        XCTAssertEqual(of(empty, nil, false, nil), .nothing, "stopped, or a truly empty address book")
        XCTAssertEqual(of(empty, nil, false, "no route"), .failed("no route"))
        XCTAssertEqual(of(empty, "down", false, nil), .failed("down"), "the read after the post failed: said in words")
        XCTAssertEqual(of(empty, "down", true, nil), .loading)
        XCTAssertEqual(of(full, "down", true, nil), .cards, "cards held always show")
    }

    func testACancelledReadIsNoFailureAndAnOlderAnswerNeverReplacesANewerOne() async {
        let api = SlowBookAPI()
        let cache = ChannelItemsCache(api: api)
        api.error = CancellationError()
        await cache.refreshContactsBook()
        XCTAssertNil(cache.contactsBookFailure, "a view went away; the page says nothing")
        api.error = URLError(.cancelled)
        await cache.refreshContactsBook()
        XCTAssertNil(cache.contactsBookFailure)
        api.error = nil

        api.hold = true
        let older = Task { await cache.refreshContactsBook() }   // sent first, empty, answers last
        while api.waiting == nil { await Task.yield() }
        api.hold = false
        api.book = book([ContactsBookCard(key: "a", name: "Ann Example")])
        await cache.refreshContactsBook()
        XCTAssertEqual(cache.contactsBook?.total, 1)
        api.release()
        await older.value
        XCTAssertEqual(cache.contactsBook?.total, 1, "the empty answer that raced the post is dropped")
    }

    func testAPostedBookIsReadOnlyIfAPageHasAsked() async {
        let api = FakeBookAPI()
        let cache = ChannelItemsCache(api: api)
        await cache.refreshContactsBookIfAsked()
        XCTAssertEqual(api.reads, 0, "no address book in memory for a page never opened")
        await cache.refreshContactsBook()
        await cache.refreshContactsBookIfAsked()
        XCTAssertEqual(api.reads, 2)
        // Disconnect, then Connect with the page open: the new book is read, with nothing else to prompt it.
        cache.forgetContactsBook()
        api.book = book([ContactsBookCard(key: "a", name: "Ann Example")])
        await cache.refreshContactsBookIfAsked()
        XCTAssertEqual(api.reads, 3)
        XCTAssertEqual(cache.contactsBook?.total, 1)
        cache.reset()
        await cache.refreshContactsBookIfAsked()
        XCTAssertEqual(api.reads, 3, "a bank switch starts over")
    }

    func testStoppingContactsLeavesNoNameInMemoryAndABankSwitchForgetsToo() async {
        let api = FakeBookAPI()
        let cache = ChannelItemsCache(api: api)
        api.book = book([ContactsBookCard(key: "a", name: "Ann Example")])
        await cache.refreshContactsBook()
        cache.forgetContactsBook()
        XCTAssertEqual(cache.contactsBook, ContactsBook(), "empty, not nil: no skeleton waits on it")
        await cache.refreshContactsBook()
        cache.reset()
        XCTAssertNil(cache.contactsBook)
    }

    func testTheReaderForgetsWhatTheAppHoldsWhenContactsStops() async {
        let suite = "contacts-grid-\(UUID())"
        addTeardownBlock { UserDefaults.standard.removePersistentDomain(forName: suite) }
        let reader = ContactsReader(store: FakeContactStore(), api: FakeContactsAPI(),
                                    defaults: UserDefaults(suiteName: suite)!, bank: { "alpha" })
        var forgot = 0
        reader.onForget = { forgot += 1 }
        reader.disconnect()
        XCTAssertEqual(forgot, 1)
        await reader.forgetTask?.value
    }

    func testForgettingPicturesDropsTheContactsOnesAndKeepsTheRest() async {
        let store = SourcePictureStore(fetch: { _ in nil })
        let image = NSImage(size: NSSize(width: 1, height: 1))
        let contact = SourcePictures.contactPhotoPrefix + "abc/photo?v=1"
        await store.prime(image, path: contact, bank: "alpha")
        await store.prime(image, path: "/sources/messages/chats/ab/photo?v=1", bank: "alpha")
        await store.forget(pathPrefix: SourcePictures.contactPhotoPrefix)
        let gone = await store.image(path: contact, bank: "alpha")
        let kept = await store.image(path: "/sources/messages/chats/ab/photo?v=1", bank: "alpha")
        XCTAssertNil(gone)
        XCTAssertNotNil(kept)
    }

    /// The search is what runs on every keystroke, so it stays off the disk and cheap at the sync's cap.
    func testSearchAtTheCapIsMeasuredNotGuessed() {
        let cards = (0..<20_000).map { ContactsBookCard(key: "\($0)", name: "Given\($0) Family\($0)") }
        let started = ContinuousClock.now
        let found = ContactsBookSearch.filter(cards, query: "family19999")
        let took = ContinuousClock.now - started
        XCTAssertEqual(found.count, 1)
        print("contacts search over 20000 cards took \(took)")
    }
}
