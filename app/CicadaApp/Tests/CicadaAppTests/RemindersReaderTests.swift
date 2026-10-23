import XCTest
@testable import CicadaApp

/// EventKit's reminders, faked: what macOS answers, the lists and reminders it holds, a change feed the test drives,
/// and an optional gate that holds a read open so a test can press Disconnect in the middle of it. No macOS prompt is
/// ever raised.
final class FakeRemindersStore: RemindersStore, @unchecked Sendable {
    var accessValue: CalendarAccess = .notDetermined
    var grant = true
    var lists = [RemindersListInfo(id: "list-ideas", title: "Ideas", account: "iCloud"),
                 RemindersListInfo(id: "list-home", title: "Home", account: "iCloud")]
    var records = [
        ReminderRecord(id: "EXT-1", listId: "list-ideas", title: "Try alpha-project offline", notes: nil, url: nil,
                       created: "2026-09-20T09:15:00+02:00", lastModified: nil, completed: false, completedAt: nil,
                       due: "2026-11-02", dueAllDay: true, priority: 1),
        ReminderRecord(id: "EXT-2", listId: "list-home", title: "Water the plants", notes: nil, url: nil,
                       created: "2026-09-21T09:15:00+02:00", lastModified: nil, completed: true,
                       completedAt: "2026-10-01T10:00:00+02:00", due: nil, dueAllDay: false, priority: 0),
    ]
    private(set) var reads = 0
    private(set) var askedLists: [Set<String>] = []
    private(set) var askedSince: [Date] = []
    /// When set, `reminders(in:)` waits for `release()` — a read in flight.
    var holdReads = false
    private var held: CheckedContinuation<Void, Never>?
    private var feed: AsyncStream<Void>.Continuation?

    func access() -> CalendarAccess { accessValue }
    func requestAccess() async -> Bool {
        accessValue = grant ? .granted : .denied
        return grant
    }
    func lists() async -> [RemindersListInfo] { lists }
    func reminders(in lists: Set<String>, completedSince: Date) async -> [ReminderRecord] {
        reads += 1
        askedLists.append(lists)
        askedSince.append(completedSince)
        if holdReads { await withCheckedContinuation { held = $0 } }
        return records.filter { lists.contains($0.listId) }
    }
    func release() { held?.resume(); held = nil }
    var isHolding: Bool { held != nil }
    func changes() -> AsyncStream<Void> { AsyncStream { feed = $0 } }
    func change() { feed?.yield() }
}

@MainActor
final class FakeRemindersAPI: RemindersSyncAPI {
    var replies: [Result<RemindersSyncResult, any Error>] = []
    private(set) var payloads: [RemindersSyncPayload] = []
    /// When set, a post waits for `release()` — a sync answered after Disconnect.
    var holdPosts = false
    private var held: CheckedContinuation<Void, Never>?
    func syncLocalReminders(_ payload: RemindersSyncPayload) async throws -> RemindersSyncResult {
        payloads.append(payload)
        if holdPosts { await withCheckedContinuation { held = $0 } }
        return replies.isEmpty ? RemindersSyncResult(created: payload.reminders.count) : try replies.removeFirst().get()
    }
    func release() { held?.resume(); held = nil }
    var isHolding: Bool { held != nil }
}

/// G219 — the Reminders lists the person ticks, read only after Connect and a tick, posted in the route's shape, never
/// an empty read, never written back, and a read that finishes after Disconnect never turns it back on. Synthetic
/// lists and placeholders only.
@MainActor
final class RemindersReaderTests: XCTestCase {
    private let now = ISO8601DateFormatter().date(from: "2026-10-23T08:00:00Z")!

    private func defaults() -> UserDefaults { UserDefaults(suiteName: "reminders-\(UUID())")! }

    private func reader(_ store: FakeRemindersStore, _ api: FakeRemindersAPI, _ defaults: UserDefaults,
                        debounce: Duration = .seconds(10)) -> RemindersReader {
        RemindersReader(store: store, api: api, defaults: defaults, now: { [now] in now }, debounce: debounce)
    }

    private func eventually(_ what: String, timeout: Duration = .seconds(2), _ condition: () -> Bool) async throws {
        let clock = ContinuousClock()
        let deadline = clock.now.advanced(by: timeout)
        while !condition() {
            guard clock.now < deadline else { return XCTFail("timed out waiting for \(what)") }
            try await Task.sleep(for: .milliseconds(10))
        }
    }

    func testNothingIsReadBeforeConnect() async {
        let store = FakeRemindersStore()
        store.accessValue = .granted
        let api = FakeRemindersAPI()
        let r = reader(store, api, defaults())
        r.start()
        await Task.yield()
        XCTAssertEqual(store.reads, 0)
        XCTAssertEqual(api.payloads.count, 0)
        XCTAssertEqual(r.status, .off)
        XCTAssertFalse(r.isOn)
    }

    func testConnectReadsNothingUntilAListIsTicked() async {
        let store = FakeRemindersStore()
        let api = FakeRemindersAPI()
        let d = defaults()
        let r = reader(store, api, d)
        await r.connect()
        defer { r.disconnect() }
        XCTAssertTrue(d.bool(forKey: RemindersReader.enabledKey))
        XCTAssertEqual(r.status, .noLists, "nothing is pre-ticked")
        XCTAssertEqual(r.available.map(\.title), ["Home", "Ideas"], "the picker's rows, sorted")
        XCTAssertEqual(store.reads, 0)
        XCTAssertEqual(api.payloads.count, 0)
        XCTAssertFalse(r.isOn, "connected with no list ticked reads Off in the catalogue")
    }

    func testATickedListIsPostedWithItsOpenAndRecentlyCompletedReminders() async throws {
        let store = FakeRemindersStore()
        let api = FakeRemindersAPI()
        let r = reader(store, api, defaults())
        await r.connect()
        defer { r.disconnect() }
        await r.setTicked("list-ideas", true)
        let payload = try XCTUnwrap(api.payloads.last)
        XCTAssertEqual(payload.lists.map(\.id), ["list-ideas"], "only the ticked list is named")
        XCTAssertEqual(payload.reminders.map(\.id), ["EXT-1"])
        XCTAssertEqual(store.askedLists.last, ["list-ideas"])
        let since = try XCTUnwrap(store.askedSince.last)
        XCTAssertEqual(Calendar.current.dateComponents([.day], from: since, to: now).day, 90)
        XCTAssertEqual(payload.completedSince, RemindersMapper.iso(since))
        XCTAssertNotNil(payload.completedSince.range(of: #"(Z|[+-]\d\d:\d\d)$"#, options: .regularExpression))
        XCTAssertEqual(r.status, .synced(at: now, reminders: 1))
        XCTAssertTrue(r.isOn)
    }

    func testAListOthersAddToIsPostedAsShared() async throws {
        let store = FakeRemindersStore()
        let api = FakeRemindersAPI()
        let r = reader(store, api, defaults())
        await r.connect()
        defer { r.disconnect() }
        await r.setTicked("list-home", true)
        await r.setShared("list-home", true)
        let payload = try XCTUnwrap(api.payloads.last)
        XCTAssertEqual(payload.lists.first?.shared, true)
        let json = String(data: try JSONEncoder().encode(payload), encoding: .utf8) ?? ""
        XCTAssertTrue(json.contains("\"completedSince\"") && json.contains("\"listId\"")
                      && json.contains("\"completedAt\"") && json.contains("\"dueAllDay\""), "camelCase on the wire")
    }

    func testUntickingTheLastListStopsReadingAndPostsNothing() async {
        let store = FakeRemindersStore()
        let api = FakeRemindersAPI()
        let r = reader(store, api, defaults())
        await r.connect()
        defer { r.disconnect() }
        await r.setTicked("list-ideas", true)
        XCTAssertEqual(api.payloads.count, 1)
        await r.setTicked("list-ideas", false)
        XCTAssertEqual(api.payloads.count, 1, "an empty tick posts nothing — nothing is tombstoned")
        XCTAssertEqual(r.status, .noLists)
        XCTAssertFalse(r.isOn)
    }

    func testADeniedPromptStaysOff() async {
        let store = FakeRemindersStore()
        store.grant = false
        let api = FakeRemindersAPI()
        let d = defaults()
        let r = reader(store, api, d)
        await r.connect()
        XCTAssertEqual(r.status, .denied)
        XCTAssertFalse(d.bool(forKey: RemindersReader.enabledKey))
        XCTAssertEqual(store.reads, 0)
        XCTAssertEqual(api.payloads.count, 0)
    }

    func testAReadWithNoListsIsNeverPosted() async {
        let store = FakeRemindersStore()
        let api = FakeRemindersAPI()
        let d = defaults()
        d.set(["list-ideas"], forKey: RemindersReader.listsKey)
        let r = reader(store, api, d)
        store.lists = []          // EventKit not ready: no list at all
        await r.connect()
        defer { r.disconnect() }
        XCTAssertEqual(api.payloads.count, 0, "it would tombstone every reminder of the named lists")
        XCTAssertEqual(r.status, .failed(Copy.remindersNotReady))
    }

    func testDisconnectStopsEveryTriggerAndDeletesNothing() async throws {
        let store = FakeRemindersStore()
        let api = FakeRemindersAPI()
        let r = reader(store, api, defaults(), debounce: .milliseconds(20))
        await r.connect()
        await r.setTicked("list-ideas", true)
        XCTAssertEqual(api.payloads.count, 1)
        r.disconnect()
        store.change()
        await r.syncNow()
        try await Task.sleep(for: .milliseconds(120))
        XCTAssertEqual(api.payloads.count, 1, "no trigger survives Disconnect")
        XCTAssertEqual(r.status, .off)
    }

    /// The Disconnect race: the read was still reading EventKit when the person pressed Disconnect — it never posts.
    func testAReadInFlightAtDisconnectNeverPosts() async throws {
        let store = FakeRemindersStore()
        let api = FakeRemindersAPI()
        let d = defaults()
        d.set(["list-ideas"], forKey: RemindersReader.listsKey)
        let r = reader(store, api, d)
        store.holdReads = true
        let connecting = Task { await r.connect() }
        try await eventually("the read to start") { store.isHolding }
        r.disconnect()
        store.release()
        await connecting.value
        XCTAssertEqual(api.payloads.count, 0)
        XCTAssertEqual(r.status, .off)
        XCTAssertFalse(r.isOn)
    }

    /// The Disconnect race, later: the post was answered after Disconnect — it never turns the row back on.
    func testAPostAnsweredAfterDisconnectNeverTurnsItBackOn() async throws {
        let store = FakeRemindersStore()
        let api = FakeRemindersAPI()
        let d = defaults()
        d.set(["list-ideas"], forKey: RemindersReader.listsKey)
        let r = reader(store, api, d)
        api.holdPosts = true
        let connecting = Task { await r.connect() }
        try await eventually("the post to start") { api.isHolding }
        r.disconnect()
        api.release()
        await connecting.value
        XCTAssertEqual(r.status, .off)
        XCTAssertFalse(d.bool(forKey: RemindersReader.enabledKey))
    }

    func testChangesAreDebounced() async throws {
        let store = FakeRemindersStore()
        let api = FakeRemindersAPI()
        let r = reader(store, api, defaults(), debounce: .milliseconds(50))
        await r.connect()
        defer { r.disconnect() }
        await r.setTicked("list-ideas", true)
        XCTAssertEqual(api.payloads.count, 1)
        store.change(); store.change(); store.change()
        try await eventually("one debounced read") { api.payloads.count == 2 }
        try await Task.sleep(for: .milliseconds(120))
        XCTAssertEqual(api.payloads.count, 2)
    }

    func testARefusalIsShownInTheServersWords() async {
        let store = FakeRemindersStore()
        let api = FakeRemindersAPI()
        let refusal = "Cicada has its demo memory open. It only holds made-up examples."
        api.replies = [.failure(APIError.httpError(409, #"{"detail":"\#(refusal)"}"#))]
        let r = reader(store, api, defaults())
        await r.connect()
        defer { r.disconnect() }
        await r.setTicked("list-ideas", true)
        XCTAssertEqual(r.status, .failed(refusal))
        XCTAssertEqual(RemindersReader.failureMessage(APIError.httpError(404, "")), Copy.remindersNeedsUpdate)
        XCTAssertEqual(RemindersReader.failureMessage(URLError(.cannotConnectToHost)), Copy.calendarBackendDown)
    }

    func testTheMapperKeepsTheContract() {
        XCTAssertEqual(RemindersMapper.id(externalId: "EXT-1", itemId: "LOCAL-1"), "EXT-1")
        XCTAssertEqual(RemindersMapper.id(externalId: "", itemId: "LOCAL-1"), "LOCAL-1")
        let day = RemindersMapper.due(DateComponents(year: 2026, month: 11, day: 2))
        XCTAssertEqual(day.0, "2026-11-02")
        XCTAssertTrue(day.1, "a due date with no time is a bare day")
        let madrid = TimeZone(identifier: "Europe/Madrid")!
        let timed = RemindersMapper.due(DateComponents(timeZone: madrid, year: 2026, month: 11, day: 2, hour: 9))
        XCTAssertEqual(timed.0, "2026-11-02T09:00:00+01:00")
        XCTAssertFalse(timed.1)
        XCTAssertNil(RemindersMapper.due(nil).0)
        let rec = FakeRemindersStore().records
        XCTAssertEqual(RemindersMapper.ticked(rec + rec, lists: ["list-ideas"]).map(\.id), ["EXT-1"],
                       "only ticked lists, one record per id")
    }

    func testThePlistAsksForRemindersAccessInPlainWords() throws {
        let bundleScript = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("bundle.sh")
        let text = try String(contentsOf: bundleScript, encoding: .utf8)
        for key in ["NSRemindersFullAccessUsageDescription", "NSRemindersUsageDescription"] {
            XCTAssertEqual(text.components(separatedBy: "<key>\(key)</key>").count - 1, 1, key)
            XCTAssertNotNil(text.range(of: "<key>\(key)</key><string>[^<]{20,}</string>", options: .regularExpression),
                            "\(key) says why, in words")
        }
        XCTAssertTrue(Copy.remindersOff.contains("full access"), "the row says it before the prompt")
    }

    func testTheRowSaysWhereThingsStand() {
        let us = Locale(identifier: "en_US")
        XCTAssertEqual(RemindersRowText.line(.off, channel: nil, now: now, locale: us), Copy.remindersOff)
        XCTAssertEqual(RemindersRowText.line(.noLists, channel: nil, now: now, locale: us), Copy.remindersNoLists)
        XCTAssertEqual(RemindersRowText.line(.synced(at: now.addingTimeInterval(-120), reminders: 1204), channel: nil,
                                             now: now, locale: us),
                       "Synced 2 minutes ago · 1,204 reminders")
        let broken = SourceChannel(id: "reminders-local", label: "Apple Reminders", lastError: "The last sync failed.")
        XCTAssertEqual(RemindersRowText.line(.synced(at: now, reminders: 3), channel: broken, now: now, locale: us),
                       "The last sync failed.")
        XCTAssertTrue(RemindersRowText.isProblem(.failed("x"), channel: nil))
        XCTAssertFalse(RemindersRowText.isProblem(.noLists, channel: nil))
    }

    func testTheCatalogueRowIsHonest() {
        let entry = SourceCatalog.fixed.first { $0.id == "reminders-local" }!
        XCTAssertEqual(entry.group, .thisMac)
        let synced = SourceChannel(id: "reminders-local", label: "Apple Reminders", connected: true)
        XCTAssertEqual(SourceCatalog.status(for: entry, channels: [synced], overview: [], readableSites: [],
                                            localReaders: ["reminders-local": true]), .connected)
        XCTAssertEqual(SourceCatalog.status(for: entry, channels: [synced], overview: [], readableSites: [],
                                            localReaders: ["reminders-local": false]), .off,
                       "disconnected here, or no list ticked: Off whatever synced before")
        XCTAssertEqual(ChannelActions.syncRoute(for: "reminders-local"), .remindersLocal)
        XCTAssertEqual(OriginIconography.appBundleId(for: "reminders-local"), "com.apple.reminders")
        XCTAssertEqual(IntegrationCategory.of(channelId: "reminders-local"), .feedsAndCalendars)
    }

    func testNotionIsAnExportRowAndItsPreviewSpeaksInPages() {
        let entry = SourceCatalog.fixed.first { $0.id == "notion" }!
        XCTAssertEqual(entry.group, .exports)
        let imported = SourceChannel(id: "notion", label: "Notion export", connected: true, count: 5)
        XCTAssertEqual(SourceCatalog.status(for: entry, channels: [imported], overview: [], readableSites: []),
                       .connected)
        XCTAssertEqual(SourceCatalog.status(for: entry, channels: [], overview: [], readableSites: []), .off)
        var p = IntakePreview()
        p.chatFiles = [URL(fileURLWithPath: "/tmp/Export.zip")]
        p.vendor = "notion"
        p.counts = IntakeCounts(pages: 2, rows: 3)
        XCTAssertEqual(IntakeSummary.previewTitle(p), "Notion pages")
        XCTAssertEqual(IntakeSummary.countsLine(p, locale: Locale(identifier: "en_US")), "2 pages · 3 database rows")
        XCTAssertEqual(IntakeSummary.noun(vendor: "notion", count: 5), "pages")
        XCTAssertEqual(IntakeSummary.sourcesName(origin: "notion-export"), "Notion")
        let decoded = try? JSONDecoder().decode(IntakeCounts.self, from: Data(#"{"pages":2,"rows":3}"#.utf8))
        XCTAssertEqual(decoded, IntakeCounts(pages: 2, rows: 3))
    }
}
