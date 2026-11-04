import XCTest
@testable import CicadaApp

/// The address book, faked: what macOS answers, the cards, a history token and a change feed the test drives.
final class FakeContactStore: ContactStore, @unchecked Sendable {
    var accessValue: ContactsAccess = .notDetermined
    var grant = true
    var token: Data? = Data([1])
    var records = [ContactMapper.record(id: "C1:ABPerson", given: "Bob", family: "Example", organization: "Example Co",
                                        jobTitle: "", emails: 2, phones: 0, hasBirthday: true, thumbnail: nil)]
    private(set) var snapshots = 0
    private var feed: AsyncStream<Void>.Continuation?

    func access() -> ContactsAccess { accessValue }
    func requestAccess() async -> Bool { accessValue = grant ? .granted : .denied; return grant }
    func snapshot() async -> [ContactRecord] { snapshots += 1; return records }
    func historyToken() -> Data? { token }
    func changes() -> AsyncStream<Void> { AsyncStream { feed = $0 } }
    func change() { feed?.yield() }
}

@MainActor
final class FakeContactsAPI: ContactsSyncAPI {
    var hold = false
    var replies: [Result<ContactsSyncResult, any Error>] = []
    private(set) var payloads: [ContactsSyncPayload] = []
    /// The bank each post named (`BankScope.origin`, G183(d)).
    private(set) var banks: [String?] = []
    private(set) var forgets = 0
    /// The connection each forget ended (review of #393).
    private(set) var forgotConnections: [String?] = []
    func forgetWaitingContacts(connection: String?) async throws {
        forgets += 1
        forgotConnections.append(connection)
    }
    /// The Contacts page's faces (`contacts_book`).
    private(set) var books: [ContactsBookPayload] = []
    private(set) var bookForgets: [String?] = []
    /// Every call in order, to prove the faces do not wait on the sync.
    private(set) var calls: [String] = []
    var bookFails = false
    /// What each `PUT` answers next, in order, once `bookFails` is off.
    var bookReplies: [any Error] = []
    /// What `GET` answers: the backend's book, empty until a `PUT` lands unless a test holds one.
    var heldTotal = 0
    var fetchErrors: [any Error] = []
    private(set) var fetches = 0
    func putContactsBook(_ payload: ContactsBookPayload) async throws {
        calls.append("book")
        books.append(payload)
        if bookFails { throw APIError.httpError(404, "") }
        if !bookReplies.isEmpty { throw bookReplies.removeFirst() }
        heldTotal = payload.cards.count
    }
    func fetchContactsBook() async throws -> ContactsBook {
        fetches += 1
        if !fetchErrors.isEmpty { throw fetchErrors.removeFirst() }
        var book = ContactsBook()
        book.total = heldTotal
        return book
    }
    func forgetContactsBook(connection: String?) async throws { bookForgets.append(connection) }
    func syncLocalContacts(_ payload: ContactsSyncPayload) async throws -> ContactsSyncResult {
        calls.append("sync")
        payloads.append(payload)
        banks.append(BankScope.origin)
        if hold { try await Task.sleep(for: .seconds(30)) }
        return replies.isEmpty ? ContactsSyncResult(contacts: payload.contacts.count, matched: 1, people: 1)
                               : try replies.removeFirst().get()
    }
}

/// G154 (R-SR8, R-SR10, R-SR11) — nothing read before Connect, names and facts but never a value, never an empty
/// post, a refusal in the server's words, a stop never a failure. Synthetic people only.
@MainActor
final class ContactsReaderTests: XCTestCase {
    private let now = ISO8601DateFormatter().date(from: "2026-09-24T21:40:00Z")!

    /// A suite emptied afterwards: cfprefsd ignores a scratch home, so its file lands in the real Preferences folder.
    private func defaults() -> UserDefaults {
        let name = "contacts-\(UUID())"
        addTeardownBlock { UserDefaults.standard.removePersistentDomain(forName: name) }
        return UserDefaults(suiteName: name)!
    }

    private func reader(_ store: FakeContactStore, _ api: FakeContactsAPI, _ defaults: UserDefaults,
                        activity: SyncActivity? = nil, debounce: Duration = .seconds(30),
                        retryAfter: Duration = .seconds(60)) -> ContactsReader {
        ContactsReader(store: store, api: api, defaults: defaults, activity: activity, now: { [now] in now },
                       debounce: debounce, retryAfter: retryAfter, bank: { "alpha" })
    }

    private func eventually(_ what: String, _ condition: () -> Bool) async throws {
        let deadline = ContinuousClock.now + .seconds(3)
        while !condition() {
            guard ContinuousClock.now < deadline else { return XCTFail("timed out waiting for \(what)") }
            try await Task.sleep(for: .milliseconds(20))
        }
    }

    func testNothingIsReadBeforeConnect() async throws {
        let store = FakeContactStore()
        store.accessValue = .granted
        let r = reader(store, FakeContactsAPI(), defaults())
        r.start()
        try await Task.sleep(for: .milliseconds(60))
        XCTAssertEqual(store.snapshots, 0)
        XCTAssertEqual(r.status, .off)
    }

    func testConnectAsksOncePostsNamesAndFactsAndNeverAValue() async throws {
        let store = FakeContactStore()
        let api = FakeContactsAPI()
        let r = reader(store, api, defaults())
        await r.connect()
        XCTAssertEqual(r.status, .watching)
        let record = try XCTUnwrap(api.payloads.first?.contacts.first)
        XCTAssertEqual(record, ContactRecord(id: "C1:ABPerson", givenName: "Bob", familyName: "Example",
                                             hasOrganization: true, hasJobTitle: false, hasEmail: true, hasPhone: false,
                                             hasBirthday: true, photoB64: nil))
        let json = String(decoding: try JSONEncoder().encode(api.payloads[0]), as: UTF8.self)
        XCTAssertFalse(json.contains("Example Co"), "an employer's name never crosses the wire (R-SR8)")
        XCTAssertFalse(json.contains("photoB64"), "no photo, no key")
    }

    /// G154 (owner 2026-11-04): every card reaches the page's faces, a one-part name too, with its names and thumbnail
    /// only; first, because the sync can be refused while Sleep runs; and a failure there never fails the sync.
    func testTheFacesGetEveryCardNamesAndThumbnailOnlyBeforeTheSync() async throws {
        let store = FakeContactStore()
        store.records = [
            ContactMapper.record(id: "C1", given: "Bob", family: "Example", organization: "Example Co", jobTitle: "Lead",
                                 emails: 2, phones: 1, hasBirthday: true, thumbnail: Data([1, 2])),
            ContactMapper.record(id: "C2", given: "Mononym", family: "", organization: "", jobTitle: "", emails: 0,
                                 phones: 1, hasBirthday: false, thumbnail: nil),
        ]
        let api = FakeContactsAPI()
        let defaults = self.defaults()
        await reader(store, api, defaults).connect()
        XCTAssertEqual(api.calls, ["book", "sync"])
        let book = try XCTUnwrap(api.books.first)
        XCTAssertEqual(book.cards.map(\.id), ["C1", "C2"])
        XCTAssertEqual(book.connection, api.payloads.first?.connection)
        let wire = String(decoding: try JSONEncoder().encode(book), as: UTF8.self)
        for word in ["hasPhone", "hasEmail", "hasOrganization", "Example Co", "Lead", "isMe"] {
            XCTAssertFalse(wire.contains(word), word)
        }
        XCTAssertTrue(wire.contains("Mononym") && wire.contains("photoB64"))

        api.bookFails = true
        await reader(store, api, defaults).syncNow()
        XCTAssertEqual(api.payloads.count, 2, "a refused book never stops the sync")
    }

    /// The forget reaches this computer's own book as well as the waiting cards, under the connection that ended.
    func testStoppingForgetsTheFacesToo() async {
        let store = FakeContactStore()
        let api = FakeContactsAPI()
        let r = reader(store, api, defaults())
        await r.connect()
        let connection = api.payloads.first?.connection
        r.disconnect()
        await r.forgetTask?.value
        XCTAssertEqual(api.bookForgets, [connection])
        XCTAssertEqual(api.forgotConnections, [connection])
    }

    /// Review of #602: someone connected before the book existed. Their sync is under a day old and nothing changed, so
    /// no sync runs on launch; the backend holds no book, so the reader posts it, without a sync.
    func testALaunchWithinADayOfASyncPostsTheBookWhenTheBackendHasNone() async throws {
        let store = FakeContactStore()
        let defaults = self.defaults()
        let old = reader(store, FakeContactsAPI(), defaults)
        await old.connect()

        let api = FakeContactsAPI()
        let later = ContactsReader(store: store, api: api, defaults: defaults,
                                   now: { [now] in now.addingTimeInterval(3600) }, bank: { "alpha" })
        later.start()
        try await eventually("the book's post") { api.books.count == 1 }
        XCTAssertEqual(api.payloads.count, 0, "the sync's token is untouched: this is the book's own post")
        XCTAssertEqual(api.banks.count, 0)
        try await eventually("the post to settle") { !later.bookPending }
    }

    /// Set up as someone whose last sync and book are current, an hour ago.
    private func connected(_ store: FakeContactStore, _ defaults: UserDefaults) async {
        await reader(store, FakeContactsAPI(), defaults).connect()
    }

    private func relaunch(_ store: FakeContactStore, _ api: FakeContactsAPI, _ defaults: UserDefaults,
                          retryAfter: Duration = .seconds(60)) -> ContactsReader {
        ContactsReader(store: store, api: api, defaults: defaults, now: { [now] in now.addingTimeInterval(3600) },
                       retryAfter: retryAfter, bank: { "alpha" })
    }

    func testTheBookIsPendingFromTheFirstMomentOfALaunch() async throws {
        let store = FakeContactStore()
        let defaults = self.defaults()
        await connected(store, defaults)
        let later = relaunch(store, FakeContactsAPI(), defaults)
        later.start()
        XCTAssertTrue(later.bookPending, "true before any await: the page never paints nothing in that moment")
        try await eventually("the post") { !later.bookPending }
    }

    func testABookAlreadyHeldAtTheCurrentTokenPostsNothingAndReadsNoCards() async throws {
        let store = FakeContactStore()
        let defaults = self.defaults()
        await connected(store, defaults)
        let snapshots = store.snapshots
        let api = FakeContactsAPI()
        api.heldTotal = 5
        let later = relaunch(store, api, defaults)
        later.start()
        try await eventually("the check") { !later.bookPending }
        XCTAssertEqual(api.fetches, 1)
        XCTAssertEqual(api.books.count, 0)
        XCTAssertEqual(store.snapshots, snapshots, "no read of the address book for nothing")
    }

    /// A post that failed left an older book at the backend: the book's own token says so, though the sync's was stored.
    func testAPostThatFailedIsRetriedAndALaterLaunchChecksAgain() async throws {
        let store = FakeContactStore()
        let defaults = self.defaults()
        let first = FakeContactsAPI()
        first.bookReplies = [APIError.serverUnreachable]
        let r = reader(store, first, defaults, retryAfter: .seconds(30))
        await r.connect()
        XCTAssertEqual(first.payloads.count, 1, "the sync still ran, and stored its token")
        XCTAssertTrue(r.bookPending, "still on its way: the retry is waiting")

        let api = FakeContactsAPI()
        api.heldTotal = 5
        let later = relaunch(store, api, defaults)
        later.start()
        try await eventually("the older book replaced") { api.books.count == 1 }
        XCTAssertEqual(api.payloads.count, 0)
    }

    func testAFailedPostIsTriedAgainOnItsOwn() async throws {
        let store = FakeContactStore()
        let api = FakeContactsAPI()
        api.bookReplies = [APIError.serverUnreachable]
        var posted = 0
        let r = reader(store, api, defaults(), retryAfter: .milliseconds(10))
        r.onBookPosted = { posted += 1 }
        await r.connect()
        try await eventually("the retry's post") { api.books.count == 2 && !r.bookPending }
        XCTAssertEqual(posted, 1)
        XCTAssertNil(r.bookFailure)
        XCTAssertEqual(api.payloads.count, 1, "only the book is posted again")
    }

    func testABackendNotYetUpAtLaunchIsAskedAgain() async throws {
        let store = FakeContactStore()
        let defaults = self.defaults()
        await connected(store, defaults)
        let api = FakeContactsAPI()
        api.fetchErrors = [URLError(.cannotConnectToHost)]
        let later = relaunch(store, api, defaults, retryAfter: .milliseconds(10))
        later.start()
        try await eventually("the post after the retry") { api.books.count == 1 }
    }

    func testRetriesAreCappedAndThenSaidInWords() async throws {
        let store = FakeContactStore()
        let api = FakeContactsAPI()
        api.bookReplies = Array(repeating: APIError.serverUnreachable, count: 20)
        let r = reader(store, api, defaults(), retryAfter: .milliseconds(5))
        await r.connect()
        try await eventually("giving up") { !r.bookPending }
        XCTAssertEqual(api.books.count, ContactsReader.maxBookRetries + 1)
        XCTAssertNotNil(r.bookFailure)
    }

    func testARefusalOrAnOlderBackendIsNotRetried() async throws {
        for (error, says) in [(APIError.httpError(409, "demo"), false), (APIError.httpError(404, ""), true)] {
            let api = FakeContactsAPI()
            api.bookReplies = [error]
            let r = reader(FakeContactStore(), api, defaults(), retryAfter: .milliseconds(1))
            await r.connect()
            try await Task.sleep(for: .milliseconds(50))
            XCTAssertEqual(api.books.count, 1)
            XCTAssertFalse(r.bookPending)
            XCTAssertEqual(r.bookFailure != nil, says)
        }
    }

    func testATrulyEmptyAddressBookSettlesWithNoPost() async throws {
        let store = FakeContactStore()
        let defaults = self.defaults()
        await connected(store, defaults)
        store.records = []
        let api = FakeContactsAPI()
        let later = relaunch(store, api, defaults)
        later.start()
        try await eventually("the check") { !later.bookPending }
        XCTAssertEqual(api.books.count, 0)
        XCTAssertNil(later.bookFailure)
    }

    /// An empty book after a forget is not a reason to post: a stopped reader asks nothing.
    func testAStoppedReaderNeverAsksOrPostsAndStoppingEndsARetry() async throws {
        let store = FakeContactStore()
        let defaults = self.defaults()
        let api = FakeContactsAPI()
        api.bookReplies = [APIError.serverUnreachable]
        let r = reader(store, api, defaults, retryAfter: .milliseconds(20))
        await r.connect()
        r.disconnect()
        XCTAssertFalse(r.bookPending)
        await r.forgetTask?.value
        let posts = api.books.count
        try await Task.sleep(for: .milliseconds(60))
        XCTAssertEqual(api.books.count, posts, "the retry was stopped with it")

        let stopped = FakeContactsAPI()
        let later = relaunch(store, stopped, defaults)
        later.start()
        later.ensureBook()
        try await Task.sleep(for: .milliseconds(30))
        XCTAssertEqual(stopped.fetches, 0)
        XCTAssertEqual(stopped.books.count, 0)
        XCTAssertFalse(later.bookPending)
    }

    func testWhenTheBookIsPosted() {
        let a = Data([1]), b = Data([2])
        XCTAssertTrue(ContactsReader.shouldPostBook(held: 0, posted: a, token: a), "the backend holds none")
        XCTAssertTrue(ContactsReader.shouldPostBook(held: 3, posted: a, token: b), "older than the address book")
        XCTAssertTrue(ContactsReader.shouldPostBook(held: 3, posted: nil, token: a), "never posted from here")
        XCTAssertFalse(ContactsReader.shouldPostBook(held: 3, posted: a, token: a))
    }

    func testDeniedSaysSoAndReadsNothing() async {
        let store = FakeContactStore()
        store.grant = false
        let api = FakeContactsAPI()
        let r = reader(store, api, defaults())
        await r.connect()
        XCTAssertEqual(r.status, .denied)
        XCTAssertFalse(r.enabled)
        XCTAssertEqual(api.payloads.count, 0)
        await r.forgetTask?.value
        XCTAssertEqual(api.forgets, 1, "access refused: nothing kept from the address book waits")
    }

    /// Review of #391: Disconnect deletes the cards waiting for a first mention, and so does access taken away later.
    func testDisconnectAndLostAccessForgetTheWaitingCards() async {
        let store = FakeContactStore()
        let api = FakeContactsAPI()
        let r = reader(store, api, defaults())
        await r.connect()
        XCTAssertEqual(api.forgets, 0)
        r.disconnect()
        await r.forgetTask?.value
        XCTAssertEqual(api.forgets, 1)
        await r.connect()
        store.accessValue = .denied
        await r.syncNow()
        await r.forgetTask?.value
        XCTAssertEqual(r.status, .denied)
        XCTAssertEqual(api.forgets, 2)
    }

    /// Review of #393: each Connect mints a connection id, every sync carries it, and the forget names the one it ends —
    /// so the backend drops a sync of that connection still in flight. A reconnect is a new connection.
    func testSyncsCarryTheConnectionAndTheForgetEndsIt() async {
        let store = FakeContactStore()
        let api = FakeContactsAPI()
        let r = reader(store, api, defaults())
        await r.connect()
        let first = try? XCTUnwrap(api.payloads.first?.connection)
        XCTAssertNotNil(first)
        r.disconnect()
        await r.forgetTask?.value
        XCTAssertEqual(api.forgotConnections, [first])
        await r.connect()
        let second = api.payloads.last?.connection
        XCTAssertNotNil(second)
        XCTAssertNotEqual(second, first, "a reconnect is a new connection")
        let json = String(decoding: try! JSONEncoder().encode(ContactsSyncPayload(contacts: [])), as: UTF8.self)
        XCTAssertFalse(json.contains("connection"), "no id, no key")
    }

    func testSyncNowAfterAccessWasTakenAwaySaysSoInWords() async {
        let store = FakeContactStore()
        let api = FakeContactsAPI()
        let r = reader(store, api, defaults())
        await r.connect()
        store.accessValue = .denied   // turned off in System Settings while Cicada runs
        do {
            _ = try await r.syncNowReporting()
            XCTFail("a read without access must not report a sync")
        } catch {
            XCTAssertEqual(error.localizedDescription, Copy.contactsDenied, "never \"Stopped\" — nothing was running")
        }
        XCTAssertEqual(r.status, .denied)
        XCTAssertEqual(api.payloads.count, 1)
        XCTAssertEqual(ContactsReadError.empty.localizedDescription, Copy.contactsEmpty, "an empty book in words too")
    }

    func testAnEmptyReadIsNeverPosted() async {
        let store = FakeContactStore()
        store.records = []
        let api = FakeContactsAPI()
        let r = reader(store, api, defaults())
        await r.connect()
        XCTAssertEqual(r.status, .empty)
        XCTAssertEqual(api.payloads.count, 0, "an empty post would strip every Contacts source")
    }

    func testLaunchPostsOnlyWhenTheBookMovedOrADayPassed() {
        let hour: TimeInterval = 3600
        XCTAssertTrue(ContactsReader.shouldPostOnLaunch(token: Data([1]), stored: Data([1]), lastPost: nil, now: now, staleAfter: 24 * hour))
        XCTAssertFalse(ContactsReader.shouldPostOnLaunch(token: Data([1]), stored: Data([1]), lastPost: now.addingTimeInterval(-hour), now: now, staleAfter: 24 * hour))
        XCTAssertTrue(ContactsReader.shouldPostOnLaunch(token: Data([2]), stored: Data([1]), lastPost: now.addingTimeInterval(-hour), now: now, staleAfter: 24 * hour))
        XCTAssertTrue(ContactsReader.shouldPostOnLaunch(token: Data([1]), stored: Data([1]), lastPost: now.addingTimeInterval(-25 * hour), now: now, staleAfter: 24 * hour),
                      "a page Sleep created since may now match")
        XCTAssertTrue(ContactsReader.shouldPostOnLaunch(token: nil, stored: nil, lastPost: now.addingTimeInterval(-hour), now: now, staleAfter: 24 * hour))
    }

    func testAChangeIsDebouncedIntoOnePost() async throws {
        let store = FakeContactStore()
        let api = FakeContactsAPI()
        let r = reader(store, api, defaults(), debounce: .milliseconds(30))
        await r.connect()
        store.change(); store.change(); store.change()
        try await eventually("the debounced post") { api.payloads.count == 2 }
        try await Task.sleep(for: .milliseconds(120))
        XCTAssertEqual(api.payloads.count, 2)
    }

    func testARefusalIsSaidInTheServersWords() async {
        let api = FakeContactsAPI()
        api.replies = [.failure(APIError.httpError(409, #"{"detail":"Cicada is tidying up your memory right now — Contacts will sync again in a minute."}"#))]
        let r = reader(FakeContactStore(), api, defaults())
        await r.connect()
        XCTAssertEqual(r.status, .failed("Cicada is tidying up your memory right now — Contacts will sync again in a minute."))
    }

    /// Round-4 final review, finding 2: the Sleep refusal says "again in a minute", so the reader keeps that promise —
    /// one delayed retry per refusal, capped so a demo bank's 409 does not ask forever.
    func testASleepRefusalIsRetriedOnItsOwnAndTheRetriesAreCapped() async throws {
        let api = FakeContactsAPI()
        let refusal = APIError.httpError(409, #"{"detail":"Cicada is tidying up your memory right now."}"#)
        api.replies = [.failure(refusal)]
        let r = reader(FakeContactStore(), api, defaults(), retryAfter: .milliseconds(20))
        await r.connect()
        try await eventually("the retry") { api.payloads.count == 2 && r.status == .watching }

        let demo = FakeContactsAPI()
        demo.replies = Array(repeating: .failure(refusal), count: ContactsReader.maxRefusedRetries + 5)
        let d = reader(FakeContactStore(), demo, defaults(), retryAfter: .milliseconds(5))
        await d.connect()
        try await eventually("the capped retries") { demo.payloads.count == ContactsReader.maxRefusedRetries + 1 }
        try await Task.sleep(for: .milliseconds(100))
        XCTAssertEqual(demo.payloads.count, ContactsReader.maxRefusedRetries + 1)
    }

    func testStopEndsTheRunWithoutAFailure() async throws {
        let api = FakeContactsAPI()
        api.hold = true
        let activity = SyncActivity()
        let d = defaults()
        let r = reader(FakeContactStore(), api, d, activity: activity)
        let running = Task { await r.connect() }
        try await eventually("the run to register") { activity.run(for: ContactsReader.channel)?.cancellable == true }
        activity.cancel(ContactsReader.channel)
        await running.value
        XCTAssertEqual(r.status, .watching)
        XCTAssertNil(d.object(forKey: "cicada.contacts.alpha.lastPost"), "a stopped post records nothing")
    }

    func testDisconnectStopsAndDeletesNothing() async {
        let api = FakeContactsAPI()
        let r = reader(FakeContactStore(), api, defaults())
        await r.connect()
        r.disconnect()
        XCTAssertEqual(r.status, .off)
        XCTAssertFalse(r.enabled)
        XCTAssertEqual(api.payloads.count, 1, "no second call — Disconnect has nothing to send")
    }

    func testTheMapperKeepsOnlyASmallThumbnail() {
        let small = ContactMapper.record(id: "C2", given: " Carol ", family: "Example", organization: " ", jobTitle: "Lead",
                                         emails: 0, phones: 1, hasBirthday: false, thumbnail: Data(repeating: 1, count: 10))
        XCTAssertEqual(small.givenName, "Carol")
        XCTAssertFalse(small.hasOrganization, "a blank employer is no employer")
        XCTAssertTrue(small.hasJobTitle)
        XCTAssertTrue(small.hasPhone)
        XCTAssertNotNil(small.photoB64)
        let big = ContactMapper.record(id: "C3", given: "A", family: "B", organization: "", jobTitle: "", emails: 0,
                                       phones: 0, hasBirthday: false, thumbnail: Data(repeating: 1, count: 70 * 1024))
        XCTAssertNil(big.photoB64)
    }

    func testThePlistAsksForContactsAccessInPlainWords() throws {
        let bundleScript = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("bundle.sh")
        let text = try String(contentsOf: bundleScript, encoding: .utf8)
        XCTAssertEqual(text.components(separatedBy: "<key>NSContactsUsageDescription</key>").count - 1, 1)
        XCTAssertNotNil(text.range(of: "<key>NSContactsUsageDescription</key><string>[^<]{20,}</string>",
                                   options: .regularExpression))
    }

    func testTheRowIsTheAppsAndTheChannelIsNotIndexedTwice() {
        XCTAssertEqual(IntegrationCategory.of(channelId: "contacts-local"), .feedsAndCalendars)
        // D6: the row left Settings with Integrations for the Sources page; its anchor keeps that home.
        XCTAssertEqual(SettingsIndex.retiredRows[.contactsApp], .page(.sources))
        XCTAssertEqual(OriginIconography.appBundleId(for: "contacts-local"), "com.apple.AddressBook",
                       "the installed Contacts app's icon, never a committed Apple mark (DR-52)")
    }

    func testTheCardNamesAContactsSourceInWords() {
        let s = EntitySource(ref: "addressbook://C1:ABPerson", kind: "app", predicate: "works-at", addedBy: "cicada",
                             addedAt: "2026-09-24")
        let line = FactSourceWords.line(s, locale: Locale(identifier: "en_US"))
        XCTAssertEqual(line.ref, Copy.contactsCardRef)
        XCTAssertFalse(line.isLink)
        XCTAssertTrue(line.help.contains("addressbook://C1:ABPerson"), "the id stays reachable in the tooltip")
        XCTAssertEqual(line.readBy, Copy.Graph.anApp)
    }

    func testTheRowSaysOffThenWhatCameIn() {
        let off = ContactsRowText.model(.off, channel: nil, run: nil)
        XCTAssertEqual(off.line, Copy.contactsOff)
        XCTAssertEqual(off.status, .idle)
        let synced = SourceChannel(id: "contacts-local", label: "Contacts", connected: true, count: 214,
                                   lastSync: "2026-09-24T21:38:00Z", countNoun: "contact", actions: ["sync", "manage"],
                                   parts: [ChannelPart(key: "people", count: 18)])
        let watching = ContactsRowText.model(.watching, channel: synced, run: nil)
        XCTAssertEqual(watching.line, SourceRowText.countLine(synced))   // "214 contacts · matched to 18 people Cicada knows"
        XCTAssertEqual(watching.status, .synced(ISO8601DateFormatter().date(from: "2026-09-24T21:38:00Z")!))
        let failed = ContactsRowText.model(.failed("Cicada has its demo memory open."), channel: synced, run: nil)
        XCTAssertEqual(failed.status, .problem("Cicada has its demo memory open."))
    }
}
