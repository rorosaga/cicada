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
    func syncLocalContacts(_ payload: ContactsSyncPayload) async throws -> ContactsSyncResult {
        payloads.append(payload)
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

    private func defaults() -> UserDefaults { UserDefaults(suiteName: "contacts-\(UUID())")! }

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

    func testDeniedSaysSoAndReadsNothing() async {
        let store = FakeContactStore()
        store.grant = false
        let api = FakeContactsAPI()
        let r = reader(store, api, defaults())
        await r.connect()
        XCTAssertEqual(r.status, .denied)
        XCTAssertFalse(r.enabled)
        XCTAssertEqual(api.payloads.count, 0)
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
        let dynamic = SettingsIndex.dynamicEntries(channels: [SourceChannel(id: "contacts-local", label: "Contacts")],
                                                   harnessRows: [], exportOnly: [], connections: [], agents: [])
        XCTAssertFalse(dynamic.contains { $0.id == .channel("contacts-local") })
        XCTAssertTrue(SettingsIndex.staticEntries.contains { $0.id == .contactsApp && $0.section == .integrations })
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
