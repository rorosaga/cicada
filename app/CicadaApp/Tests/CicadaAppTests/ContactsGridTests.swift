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
        let reader = ContactsReader(store: FakeContactStore(), api: FakeContactsAPI(),
                                    defaults: UserDefaults(suiteName: "contacts-grid-\(UUID())")!, bank: { "alpha" })
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
