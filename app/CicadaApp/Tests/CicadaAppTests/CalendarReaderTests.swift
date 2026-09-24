import XCTest
@testable import CicadaApp

/// EventKit, faked: what macOS answers, what the calendars hold, and a change feed the test drives.
final class FakeCalendarStore: CalendarStore, @unchecked Sendable {
    var accessValue: CalendarAccess = .notDetermined
    var grant = true
    var calendars = [CalendarInfo(id: "cal-1", title: "Work", account: "iCloud")]
    var events = [CalendarEventRecord(id: "EXT-1", calendarId: "cal-1", title: "alpha-project review",
                                      start: "2026-09-25T10:00:00+02:00", end: "2026-09-25T11:00:00+02:00",
                                      allDay: false, location: nil, notes: nil, url: nil,
                                      attendees: ["Bob Example"], organizer: nil, lastModified: nil)]
    private(set) var snapshots = 0
    private var feed: AsyncStream<Void>.Continuation?

    func access() -> CalendarAccess { accessValue }
    func requestAccess() async -> Bool {
        accessValue = grant ? .granted : .denied
        return grant
    }
    func snapshot(from: Date, to: Date) async -> (calendars: [CalendarInfo], events: [CalendarEventRecord]) {
        snapshots += 1
        return (calendars, events)
    }
    func changes() -> AsyncStream<Void> { AsyncStream { feed = $0 } }
    func change() { feed?.yield() }
}

/// C6's route, faked on the main actor (`FakeProjectsAPI`'s precedent): every payload recorded, answers from a queue
/// (one created event when the queue is empty). It has no delete to call — Disconnect never sends one.
@MainActor
final class FakeCalendarAPI: CalendarSyncAPI {
    var replies: [Result<CalendarSyncResult, any Error>] = []
    private(set) var payloads: [CalendarSyncPayload] = []
    func syncLocalCalendar(_ payload: CalendarSyncPayload) async throws -> CalendarSyncResult {
        payloads.append(payload)
        return replies.isEmpty ? CalendarSyncResult(created: 1) : try replies.removeFirst().get()
    }
}

/// Round-4 D2 (C6, R-FA11 … R-FA13) — the Calendar app's events, read only after Connect, posted in C6's shape, never
/// an empty read, and a refusal in the server's words. Synthetic calendars and people only.
@MainActor
final class CalendarReaderTests: XCTestCase {
    private let madrid = TimeZone(identifier: "Europe/Madrid")!
    private let now = ISO8601DateFormatter().date(from: "2026-09-24T08:00:00Z")!

    private func defaults() -> UserDefaults { UserDefaults(suiteName: "calendar-\(UUID())")! }

    private func reader(_ store: FakeCalendarStore, _ api: FakeCalendarAPI, _ defaults: UserDefaults,
                        debounce: Duration = .seconds(10)) -> CalendarReader {
        CalendarReader(store: store, api: api, defaults: defaults, now: { [now] in now }, debounce: debounce)
    }

    private func eventually(_ what: String, timeout: Duration = .seconds(2),
                            _ condition: () -> Bool) async throws {
        let clock = ContinuousClock()
        let deadline = clock.now.advanced(by: timeout)
        while !condition() {
            guard clock.now < deadline else { return XCTFail("timed out waiting for \(what)") }
            try await Task.sleep(for: .milliseconds(10))
        }
    }

    func testNothingIsReadBeforeConnect() async {
        let store = FakeCalendarStore()
        store.accessValue = .granted               // even with macOS's yes, the person's Connect decides (R-FA11)
        let api = FakeCalendarAPI()
        let r = reader(store, api, defaults())
        r.start()
        await Task.yield()
        XCTAssertEqual(store.snapshots, 0)
        XCTAssertEqual(api.payloads.count, 0)
        XCTAssertEqual(r.status, .off)
    }

    func testConnectAsksMacOSThenSyncsTheWindow() async throws {
        let store = FakeCalendarStore()
        let api = FakeCalendarAPI()
        let d = defaults()
        let r = reader(store, api, d)
        await r.connect()
        defer { r.disconnect() }
        XCTAssertTrue(d.bool(forKey: CalendarReader.enabledKey))
        let payload = try XCTUnwrap(api.payloads.first)
        let window = CalendarEventMapper.window(now: now)
        XCTAssertEqual(Calendar.current.dateComponents([.day], from: window.from, to: now).day, 30)
        XCTAssertEqual(Calendar.current.dateComponents([.day], from: now, to: window.to).day, 60)
        XCTAssertEqual(payload.window.from, CalendarEventMapper.iso(window.from, timeZone: .current))
        XCTAssertEqual(payload.window.to, CalendarEventMapper.iso(window.to, timeZone: .current))
        XCTAssertNotNil(payload.window.from.range(of: #"(Z|[+-]\d\d:\d\d)$"#, options: .regularExpression),
                        "ISO-8601 with its offset (C6)")
        XCTAssertEqual(payload.calendars, store.calendars)
        XCTAssertEqual(payload.events, store.events)
        XCTAssertEqual(r.status, .synced(at: now, events: 1))
    }

    func testADeniedPromptStaysOffAndSaysWhere() async {
        let store = FakeCalendarStore()
        store.grant = false
        let api = FakeCalendarAPI()
        let d = defaults()
        let r = reader(store, api, d)
        await r.connect()
        XCTAssertEqual(r.status, .denied)
        XCTAssertFalse(d.bool(forKey: CalendarReader.enabledKey))
        XCTAssertEqual(api.payloads.count, 0)
        XCTAssertEqual(store.snapshots, 0)
    }

    func testDisconnectStopsEveryTriggerAndDeletesNothing() async throws {
        let store = FakeCalendarStore()
        let api = FakeCalendarAPI()
        let r = reader(store, api, defaults(), debounce: .milliseconds(20))
        await r.connect()
        XCTAssertEqual(api.payloads.count, 1)
        r.disconnect()
        store.change()
        await r.syncNow()
        try await Task.sleep(for: .milliseconds(120))
        XCTAssertEqual(api.payloads.count, 1, "no trigger survives Disconnect")
        XCTAssertEqual(r.status, .off)
    }

    func testChangesAreDebounced() async throws {
        let store = FakeCalendarStore()
        let api = FakeCalendarAPI()
        let r = reader(store, api, defaults(), debounce: .milliseconds(50))
        await r.connect()
        defer { r.disconnect() }
        XCTAssertEqual(api.payloads.count, 1)
        store.change(); store.change(); store.change()
        try await eventually("the debounced sync") { api.payloads.count >= 2 }
        try await Task.sleep(for: .milliseconds(150))
        XCTAssertEqual(api.payloads.count, 2, "three changes inside the debounce are one sync")
    }

    /// R-FA11 — an empty read (EventKit not ready) is never posted: C6 would tombstone the whole window.
    func testAReadWithNoCalendarsIsNeverPosted() async {
        let store = FakeCalendarStore()
        store.calendars = []
        store.events = []
        let api = FakeCalendarAPI()
        let r = reader(store, api, defaults())
        await r.connect()
        defer { r.disconnect() }
        XCTAssertEqual(api.payloads.count, 0)
        XCTAssertEqual(r.status, .failed(Copy.calendarNotReady))
    }

    /// Access taken away in System Settings while Cicada runs: the next sync reads nothing and says where to look.
    func testRevokedAccessStopsTheNextSync() async {
        let store = FakeCalendarStore()
        let api = FakeCalendarAPI()
        let r = reader(store, api, defaults())
        await r.connect()
        defer { r.disconnect() }
        store.accessValue = .denied
        await r.syncNow()
        XCTAssertEqual(api.payloads.count, 1)
        XCTAssertEqual(r.status, .denied)
    }

    func testARefusalIsShownInTheServersWords() async {
        let store = FakeCalendarStore()
        let api = FakeCalendarAPI()
        let refusal = "Cicada has its demo memory open. It only holds made-up examples."
        api.replies = [.failure(APIError.httpError(409, #"{"detail":"\#(refusal)"}"#))]
        let r = reader(store, api, defaults())
        await r.connect()
        defer { r.disconnect() }
        XCTAssertEqual(r.status, .failed(refusal))
        XCTAssertEqual(CalendarReader.failureMessage(APIError.httpError(404, #"{"detail":"Not Found"}"#)),
                       Copy.calendarNeedsUpdate, "a backend without C6")
        XCTAssertEqual(CalendarReader.failureMessage(APIError.httpError(405, "")), Copy.calendarNeedsUpdate)
        XCTAssertEqual(CalendarReader.failureMessage(APIError.serverUnreachable), Copy.calendarBackendDown)
        XCTAssertEqual(CalendarReader.failureMessage(URLError(.cannotConnectToHost)), Copy.calendarBackendDown,
                       "APIClient passes a refused connection through as a URLError")
        XCTAssertEqual(CalendarReader.failureMessage(APIError.httpError(500, "boom")), Copy.calendarSyncFailed)
    }

    func testOneMeetingInTwoCalendarsIsPostedOnce() {
        func rec(_ id: String, _ cal: String) -> CalendarEventRecord {
            CalendarEventRecord(id: id, calendarId: cal, title: "alpha-project review",
                                start: "2026-09-25T10:00:00+02:00", end: "2026-09-25T11:00:00+02:00",
                                allDay: false, location: nil, notes: nil, url: nil,
                                attendees: nil, organizer: nil, lastModified: nil)
        }
        let out = CalendarEventMapper.firstById([rec("EXT-1", "cal-1"), rec("EXT-2", "cal-1"), rec("EXT-1", "cal-2")])
        XCTAssertEqual(out.map(\.id), ["EXT-1", "EXT-2"], "one id, one record: the backend stages by id")
        XCTAssertEqual(out.first?.calendarId, "cal-1", "the first seen is kept")
    }

    func testTheMapperKeepsTheContract() {
        var c = Calendar(identifier: .gregorian)
        c.timeZone = madrid
        let occurrence = c.date(from: DateComponents(year: 2026, month: 9, day: 24, hour: 10))!
        XCTAssertEqual(CalendarEventMapper.id(externalId: "EXT-1", itemId: "LOCAL-1", recurring: true,
                                              occurrence: occurrence, timeZone: madrid),
                       "EXT-1|2026-09-24T10:00:00+02:00")
        XCTAssertEqual(CalendarEventMapper.id(externalId: "EXT-1", itemId: "LOCAL-1", recurring: false,
                                              occurrence: occurrence, timeZone: madrid), "EXT-1")
        XCTAssertEqual(CalendarEventMapper.id(externalId: nil, itemId: "LOCAL-1", recurring: false,
                                              occurrence: occurrence, timeZone: madrid), "LOCAL-1")
        XCTAssertEqual(CalendarEventMapper.person(name: nil, url: URL(string: "mailto:bob-example@example.com")),
                       "bob-example@example.com")
        XCTAssertEqual(CalendarEventMapper.person(name: "Bob Example", url: URL(string: "mailto:bob-example@example.com")),
                       "Bob Example")
        XCTAssertNil(CalendarEventMapper.person(name: "  ", url: nil))
        XCTAssertEqual(CalendarEventMapper.notes(String(repeating: "a", count: 12_000))?.count, 10_000)
        XCTAssertNil(CalendarEventMapper.notes(""))
        XCTAssertTrue(CalendarEventMapper.iso(occurrence, timeZone: madrid).hasSuffix("+02:00"))
    }

    func testThePlistAsksForCalendarAccessInPlainWords() throws {
        let bundleScript = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()   // CicadaAppTests
            .deletingLastPathComponent()   // Tests
            .deletingLastPathComponent()   // CicadaApp
            .appendingPathComponent("bundle.sh")
        let text = try String(contentsOf: bundleScript, encoding: .utf8)
        for key in ["NSCalendarsFullAccessUsageDescription", "NSCalendarsUsageDescription"] {
            XCTAssertEqual(text.components(separatedBy: "<key>\(key)</key>").count - 1, 1, key)
            XCTAssertNotNil(text.range(of: "<key>\(key)</key><string>[^<]{20,}</string>", options: .regularExpression),
                            "\(key) says why, in words")
        }
    }

    /// R-FA13 — the row is the app's; the backend's `calendar-local` channel is never a second row or search entry.
    func testTheCalendarRowIsTheAppsAndTheChannelIsNotIndexedTwice() {
        XCTAssertEqual(IntegrationCategory.of(channelId: "calendar-local"), .feedsAndCalendars)
        let dynamic = SettingsIndex.dynamicEntries(channels: [SourceChannel(id: "calendar-local", label: "Calendar")],
                                                   harnessRows: [], exportOnly: [], connections: [], agents: [])
        XCTAssertFalse(dynamic.contains { $0.id == .channel("calendar-local") })
        XCTAssertTrue(SettingsIndex.staticEntries.contains { $0.id == .calendarApp && $0.section == .integrations })
        XCTAssertEqual(OriginIconography.appBundleId(for: "calendar-local"), "com.apple.iCal",
                       "the installed Calendar app's icon, never a committed Apple mark (DR-52)")
        XCTAssertEqual(OriginIconography.symbol(for: "calendar-local"), "calendar")
    }

    func testTheRowSaysWhereThingsStand() {
        let us = Locale(identifier: "en_US")
        XCTAssertEqual(CalendarRowText.line(.off, channel: nil, now: now, locale: us), Copy.calendarOff)
        XCTAssertEqual(CalendarRowText.line(.denied, channel: nil, now: now, locale: us), Copy.calendarDenied)
        XCTAssertEqual(CalendarRowText.line(.syncing, channel: nil, now: now, locale: us), Copy.calendarSyncing)
        XCTAssertEqual(CalendarRowText.line(.synced(at: now.addingTimeInterval(-120), events: 1204), channel: nil,
                                            now: now, locale: us),
                       "Synced 2 minutes ago · 1,204 events")
        XCTAssertEqual(CalendarRowText.line(.failed("x"), channel: nil, now: now, locale: us), "x")
        let broken = SourceChannel(id: "calendar-local", label: "Calendar", lastError: "The last sync failed.")
        XCTAssertEqual(CalendarRowText.line(.synced(at: now, events: 3), channel: broken, now: now, locale: us),
                       "The last sync failed.", "the backend's own error wins over a stale success")
    }
}
