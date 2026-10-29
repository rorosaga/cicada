import XCTest
@testable import CicadaApp

// G218 — the traces UI's pure parts, on fakes only: no real permission is read, System Settings is never opened,
// LocalAuthentication is never asked, and no Apple Event is sent.

private final class TracesUIProbe: TracePermissionProbe, @unchecked Sendable {
    var answers: [TracePermission: Bool] = [:]
    private(set) var asked: [TracePermission] = []
    func granted(_ permission: TracePermission) -> Bool {
        asked.append(permission)
        return answers[permission] ?? false
    }
}

@MainActor
private final class TracesUIOpener: PermissionSettingsOpener {
    private(set) var opened: [URL] = []
    func open(_ url: URL) { opened.append(url) }
}

@MainActor
private final class TracesUIClock: PermissionPollClock {
    private(set) var tick: (@MainActor () -> Void)?
    private(set) var intervals: [TimeInterval] = []
    private(set) var cancelled = 0

    final class Token: PermissionPollToken {
        let onCancel: () -> Void
        init(onCancel: @escaping () -> Void) { self.onCancel = onCancel }
        func cancel() { onCancel() }
    }

    func every(_ interval: TimeInterval, _ tick: @escaping @MainActor () -> Void) -> PermissionPollToken {
        intervals.append(interval)
        self.tick = tick
        return Token { [weak self] in self?.cancelled += 1; self?.tick = nil }
    }

    func fire() { tick?() }
}

private final class TracesUIAuthenticator: TraceAuthenticator, @unchecked Sendable {
    var answer: Bool
    private(set) var reasons: [String] = []
    init(answer: Bool) { self.answer = answer }
    func authenticate(reason: String) async -> Bool {
        reasons.append(reason)
        return answer
    }
}

private final class TracesUIAsker: TraceBrowserAsking, @unchecked Sendable {
    private(set) var asked: [String] = []
    var answer = true
    func ask(bundleId: String) -> Bool { asked.append(bundleId); return answer }
    func granted(bundleId: String) -> Bool { false }
}

/// Only the browser's reads; every write fails the test.
private final class TracesUIBackend: TraceBackend, @unchecked Sendable {
    var timeline = TraceTimeline(day: "2026-10-23", spans: [], frames: [], unreadable: 0)
    private(set) var imageFetches: [String] = []
    private(set) var textFetches: [String] = []
    private(set) var timelineDays: [String] = []

    func traceTimeline(day: String) async throws -> TraceTimeline { timelineDays.append(day); return timeline }
    func traceSearch(_ query: String) async throws -> [TraceSearchHit] { [] }
    func traceFrameImage(id: String) async throws -> Data { imageFetches.append(id); return Data([0xFF, 0xD8]) }
    func traceFrameText(id: String) async throws -> TraceFrameText {
        textFetches.append(id)
        return TraceFrameText(id: id, at: "2026-10-23T15:20:00+02:00", app: "Example", text: "words")
    }

    private func unexpected() -> Never { fatalError("the browser only reads") }
    func traceSettings() async throws -> TraceSettingsAnswer { unexpected() }
    func traceTurnOn(consentVersion: Int, displayedVersion: Int) async throws -> TraceSettingsAnswer { unexpected() }
    func traceTurnOff() async throws -> TraceSettingsAnswer { unexpected() }
    func traceUpdate(_ patch: [String: TracePatchValue]) async throws -> TraceSettingsAnswer { unexpected() }
    func tracePause(until: String?) async throws -> TraceSettingsAnswer { unexpected() }
    func traceSync(_ spans: [TraceSpan]) async throws -> TraceSyncResult { unexpected() }
    func traceAddFrame(_ frame: TraceFramePost) async throws { unexpected() }
    func traceForget(minutes: Int) async throws { unexpected() }
    func traceWipe() async throws -> TraceSettingsAnswer { unexpected() }
    var cards: [TraceDayCard] = []
    private(set) var deletes: [(day: String, spans: [String], frames: [String], all: Bool)] = []
    func traceDayCards() async throws -> [TraceDayCard] { cards }
    func traceDelete(day: String, spans: [String], frames: [String], all: Bool) async throws -> TraceDeleted {
        deletes.append((day, spans, frames, all))
        return TraceDeleted(spans: spans.count, frames: frames.count)
    }
    func tracePreview(day: String?) async throws -> TraceDigestPreview { unexpected() }
    func traceAdded() async throws -> TraceAdded { unexpected() }
    func traceRemoveFromMemory() async throws -> TraceRemoval { unexpected() }
    func traceUndoRemoval(id: String) async throws -> Int { unexpected() }
}

// MARK: - PermissionDragHelperModel

@MainActor
final class TracesUIPermissionHelperTests: XCTestCase {
    private func make(_ kind: TracePermission, granted: Bool = false)
        -> (PermissionDragHelperModel, TracesUIProbe, TracesUIOpener, TracesUIClock) {
        let probe = TracesUIProbe()
        probe.answers[kind] = granted
        let opener = TracesUIOpener()
        let clock = TracesUIClock()
        return (PermissionDragHelperModel(kind: kind, probe: probe, opener: opener, clock: clock), probe, opener, clock)
    }

    func testOpenGoesToTheExactListForEachKind() {
        let expected: [TracePermission: String] = [
            .screenRecording: "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
            .accessibility: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
            .fullDiskAccess: "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles",
        ]
        for (kind, url) in expected {
            let (model, _, opener, _) = make(kind)
            model.start()
            model.open()
            XCTAssertEqual(opener.opened.map(\.absoluteString), [url], "\(kind)")
            XCTAssertEqual(model.phase, .opened)
        }
    }

    func testPollingTicksAndClosesOnceGranted() {
        let (model, probe, _, clock) = make(.screenRecording)
        var ticks = 0
        var finishes = 0
        model.onGranted = { ticks += 1 }
        model.onFinish = { finishes += 1 }
        model.start()
        model.open()
        XCTAssertEqual(clock.intervals, [CicadaTiming.permissionPoll], "one gentle poll, started once")
        clock.fire()
        XCTAssertEqual(ticks, 0)
        probe.answers[.screenRecording] = true
        clock.fire()
        XCTAssertEqual(model.phase, .granted)
        XCTAssertEqual(ticks, 1)
        XCTAssertEqual(finishes, 1)
        XCTAssertEqual(clock.cancelled, 1, "the poll stops")
        model.tick()
        XCTAssertEqual(ticks, 1, "a step ticks once")
    }

    func testAlreadyAllowedTicksAtOnceAndNeverOpensSettings() {
        let (model, _, opener, clock) = make(.accessibility, granted: true)
        var ticks = 0
        model.onGranted = { ticks += 1 }
        model.start()
        XCTAssertEqual(model.phase, .granted)
        XCTAssertEqual(ticks, 1)
        XCTAssertTrue(opener.opened.isEmpty)
        XCTAssertTrue(clock.intervals.isEmpty)
    }

    func testTheHelperOnlyEverReadsByPreflight() {
        let (model, probe, _, clock) = make(.accessibility)
        model.start()
        model.open()
        clock.fire()
        clock.fire()
        // The probe has one method, `granted` — a preflight; nothing that asks exists to be called.
        XCTAssertEqual(probe.asked, [.accessibility, .accessibility, .accessibility])
    }

    func testCancelClosesWithoutATick() {
        let (model, _, _, clock) = make(.screenRecording)
        var ticks = 0
        var finishes = 0
        model.onGranted = { ticks += 1 }
        model.onFinish = { finishes += 1 }
        model.start()
        model.cancel()
        XCTAssertEqual(model.phase, .cancelled)
        XCTAssertEqual(ticks, 0)
        XCTAssertEqual(finishes, 1)
        XCTAssertEqual(clock.cancelled, 1)
    }

    func testTheWordsPerKind() {
        XCTAssertEqual(Copy.Traces.need(.screenRecording),
                       "I need screen recording. Drag me into the Screen Recording list.")
        XCTAssertEqual(Copy.Traces.nearMiss(.screenRecording),
                       "Drag into 'Screen & System Audio Recording', not the audio-only list.")
        XCTAssertTrue(Copy.Traces.need(.accessibility).contains("Accessibility"))
        XCTAssertTrue(Copy.Traces.nearMiss(.accessibility).contains("Accessibility"))
        let (model, _, _, _) = make(.accessibility)
        XCTAssertEqual(model.hint, Copy.Traces.nearMiss(.accessibility))
        XCTAssertEqual(model.need, Copy.Traces.need(.accessibility))
    }

    /// The helper's source never names a prompting API outside its comments.
    func testTheHelperNeverCallsAPromptingAPI() throws {
        let file = try XCTUnwrap(try ThemeTokenTests.swiftSources().first { $0.lastPathComponent == "PermissionDragHelper.swift" })
        let code = try String(contentsOf: file, encoding: .utf8).components(separatedBy: .newlines)
            .filter { !$0.trimmingCharacters(in: .whitespaces).hasPrefix("//") }.joined(separator: "\n")
        for banned in ["CGRequestScreenCaptureAccess", "AXIsProcessTrustedWithOptions", "kAXTrustedCheckOptionPrompt",
                       "SCShareableContent", "AEDeterminePermissionToAutomateTarget"] {
            XCTAssertFalse(code.contains(banned), banned)
        }
    }
}

// MARK: - The consent sheet's words

final class TracesUIConsentCopyTests: XCTestCase {
    func testTheSheetSaysWhatWhereHowLongIntoMemoryAndHowToWipe() {
        let what = Copy.Traces.what.joined(separator: " ")
        XCTAssertTrue(what.contains("app in front"))
        XCTAssertTrue(what.contains("never for chat and mail apps"))
        XCTAssertTrue(what.contains("never private windows"))
        XCTAssertTrue(what.contains("read on this Mac"))
        XCTAssertTrue(what.contains("paused") && what.contains("locked") && what.contains("password"))
        XCTAssertTrue(Copy.Traces.where_.contains("Only on this Mac"))
        XCTAssertTrue(Copy.Traces.where_.contains("encrypted"))
        XCTAssertTrue(Copy.Traces.where_.contains("outside your memory"))
        XCTAssertTrue(Copy.Traces.where_.contains("remote agents"))
        XCTAssertTrue(Copy.Traces.howLong.contains("30 days") && Copy.Traces.howLong.contains("7 days"))
        XCTAssertTrue(Copy.Traces.intoMemory.contains("watch history"))
        XCTAssertTrue(Copy.Traces.intoMemory.contains("any site"))
        XCTAssertTrue(what.contains("every screen"))
        XCTAssertTrue(Copy.Traces.intoMemory.contains("only if you turn it on"))
        XCTAssertTrue(Copy.Traces.wipeHow.contains("Wipe all traces"))
        XCTAssertTrue(Copy.Traces.wipeHow.contains("menu bar"))
        XCTAssertTrue(Copy.Traces.honestLimit.contains("Anything running as you"))
    }

    func testTheWipeConfirmationSaysWhatGoesAndWhatStays() {
        XCTAssertTrue(Copy.Traces.wipeMessage.contains("key"))
        XCTAssertTrue(Copy.Traces.wipeMessage.contains("turns traces off"))
        XCTAssertTrue(Copy.Traces.wipeMessage.contains("stays in your memory"))
    }

    /// Provider-neutral (owner 2026-09-30): Sleep's engine is never named.
    func testTheLearnSwitchNamesNoProvider() {
        for name in ["Claude", "ChatGPT", "OpenAI", "Codex", "Ollama", "OpenRouter", "Gemini"] {
            XCTAssertFalse(Copy.Traces.learnHelp.contains(name), name)
        }
        XCTAssertTrue(Copy.Traces.learnHelp.contains("plan's usage"))
        XCTAssertTrue(Copy.Traces.learnHelp.contains("key's spend"))
    }
}

// MARK: - The catalogue

final class TracesUICatalogTests: XCTestCase {
    private func row(readers: [String: Bool]) -> SourceCatalogRow? {
        let entries = SourceCatalog.entries(browsers: [], wisprPresent: false, overview: [])
        return SourceCatalog.rows(entries: entries, channels: [], overview: [], readableSites: [], localReaders: readers)
            .first { $0.id == SourceCatalog.tracesId }
    }

    /// Traces sits right after This Mac's chat sources (Messages, WhatsApp, any later one that chooses chats), which
    /// stay together — not pinned to Messages, so a new chat source joins the group without moving Traces.
    func testTracesIsAThisMacEntryAfterTheChatSources() throws {
        let fixed = SourceCatalog.fixed
        let ids = fixed.map(\.id)
        let traces = try XCTUnwrap(fixed.first { $0.id == SourceCatalog.tracesId })
        XCTAssertEqual(traces.group, .thisMac)
        XCTAssertEqual(traces.title, Copy.Traces.title)
        let chats = fixed.indices.filter {
            fixed[$0].group == .thisMac && fixed[$0].verb == .connect(Copy.Catalog.chooseChats)
        }
        XCTAssertTrue(chats.contains(try XCTUnwrap(ids.firstIndex(of: "imessage"))))
        XCTAssertTrue(chats.contains(try XCTUnwrap(ids.firstIndex(of: WhatsAppWatcher.channel))))
        let first = try XCTUnwrap(chats.first), last = try XCTUnwrap(chats.last)
        XCTAssertEqual(Array(chats), Array(first...last), "the chat sources sit together")
        XCTAssertEqual(ids.firstIndex(of: SourceCatalog.tracesId), last + 1, "Traces follows the last chat source")
    }

    func testConnectedOnlyWhileRecording() {
        XCTAssertEqual(row(readers: [SourceCatalog.tracesId: true])?.status, .connected)
        XCTAssertEqual(row(readers: [SourceCatalog.tracesId: false])?.status, .off, "paused, off or on a server")
        XCTAssertEqual(row(readers: [:])?.status, .off)
    }

    func testTheMenuSaysWhetherTracesRecord() {
        XCTAssertEqual(MenuBarManager.traceHeader(.recording), Copy.Traces.menuRecording)
        XCTAssertEqual(MenuBarManager.traceHeader(.paused(until: "3:40 PM")), "Traces paused until 3:40 PM")
        XCTAssertEqual(MenuBarManager.traceHeader(.paused(until: nil)), Copy.Traces.menuPausedUntilResumed)
    }

    func testThePausedLine() throws {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = try XCTUnwrap(TimeZone(identifier: "UTC"))
        let locale = Locale(identifier: "en_US_POSIX")
        let now = try XCTUnwrap(TraceClock.parse("2026-10-23T14:00:00Z"))
        let later = TracesControlsLogic.pausedWhen("2026-10-23T15:40:00Z", now: now, calendar: calendar, locale: locale)
        XCTAssertEqual(later?.replacingOccurrences(of: "\u{202F}", with: " "), "3:40 PM")
        XCTAssertEqual(TracesControlsLogic.pausedWhen("2026-10-24T00:00:00Z", now: now, calendar: calendar,
                                                      locale: locale), "tomorrow")
        XCTAssertNil(TracesControlsLogic.pausedWhen(TraceSettings.untilResumed, now: now))
        var settings = TraceSettings()
        settings.pausedUntil = TraceSettings.untilResumed
        XCTAssertEqual(TracesControlsLogic.stateLine(.paused, settings: settings, now: now), Copy.Traces.pausedUntilResumed)
        XCTAssertEqual(TracesControlsLogic.stateLine(.recording, settings: settings, now: now), Copy.Traces.recording)
    }

    func testListEditsMatchTheBackendsRules() {
        XCTAssertTrue(TracesControlsLogic.validBundle("com.example.App"))
        XCTAssertFalse(TracesControlsLogic.validBundle("not an app"))
        XCTAssertEqual(TracesControlsLogic.normalizeHost("https://www.bank.example/login"), "bank.example")
        XCTAssertEqual(TracesControlsLogic.normalizeHost("Health.Example"), "health.example")
        XCTAssertNil(TracesControlsLogic.normalizeHost("localhost"))
        XCTAssertEqual(TracesControlsLogic.adding("b", to: ["c", "a", "b"]), ["a", "b", "c"])
    }

    func testOnlyListedBrowsersWithAnInstalledBundleAreOffered() {
        var lists = TracePolicyLists()
        lists.urlBrowsers = ["chrome": ["com.google.Chrome", "com.google.Chrome.beta"], "brave": ["com.brave.Browser"]]
        let offered = TracesControlsLogic.browsers(lists) { $0 == "com.google.Chrome.beta" }
        XCTAssertEqual(offered.map(\.name), ["chrome"])
        XCTAssertEqual(offered.map(\.bundleId), ["com.google.Chrome.beta"])
    }

    @MainActor
    func testTurningABrowserOnAsksThatBrowserThenSaves() async throws {
        let asker = TracesUIAsker()
        var patches: [[String: TracePatchValue]] = []
        let allowed = try await TracesControlsLogic.setBrowser("brave", on: true, bundleId: "com.brave.Browser",
                                                               current: ["chrome"], asker: asker) { patches.append($0) }
        XCTAssertEqual(asker.asked, ["com.brave.Browser"])
        XCTAssertEqual(allowed, true)
        XCTAssertEqual(patches, [["browsers": .strings(["brave", "chrome"])]])
        let off = try await TracesControlsLogic.setBrowser("brave", on: false, bundleId: "com.brave.Browser",
                                                           current: ["brave", "chrome"], asker: asker) { patches.append($0) }
        XCTAssertNil(off)
        XCTAssertEqual(asker.asked.count, 1, "turning off never asks")
        XCTAssertEqual(patches.last, ["browsers": .strings(["chrome"])])
    }
}

// MARK: - The browser

@MainActor
final class TracesUIBrowserModelTests: XCTestCase {
    private let frame = TraceFrameMeta(id: "f1", at: "2026-10-23T15:20:00+02:00", bundleId: "com.example.App",
                                       app: "Example", width: 640, height: 400, spanId: nil, hasText: true)

    func testNoScreenshotIsFetchedBeforeASuccessfulUnlock() async {
        let backend = TracesUIBackend()
        let auth = TracesUIAuthenticator(answer: true)
        let model = TracesBrowserModel(backend: backend, authenticator: auth)
        await model.image(for: frame.id)
        await model.text(for: frame.id)
        XCTAssertTrue(backend.imageFetches.isEmpty)
        XCTAssertTrue(backend.textFetches.isEmpty)
        await model.unlock()
        XCTAssertEqual(auth.reasons, [Copy.Traces.authReason])
        await model.image(for: frame.id)
        await model.image(for: frame.id)
        await model.text(for: frame.id)
        XCTAssertEqual(backend.imageFetches, ["f1"], "fetched once, after the unlock")
        XCTAssertEqual(backend.textFetches, ["f1"])
        XCTAssertNotNil(model.images["f1"])
    }

    func testAFailedUnlockFetchesNothing() async {
        let backend = TracesUIBackend()
        let model = TracesBrowserModel(backend: backend, authenticator: TracesUIAuthenticator(answer: false))
        await model.unlock()
        XCTAssertFalse(model.unlocked)
        XCTAssertTrue(model.authFailed)
        await model.image(for: frame.id)
        await model.text(for: frame.id)
        XCTAssertTrue(backend.imageFetches.isEmpty)
        XCTAssertTrue(backend.textFetches.isEmpty)
    }

    /// The rail's second click: back to the newest day, no search, no screenshot open (2026-10-19 "Say it once" (5)).
    func testReturnToRootIsTheNewestDayWithNoSearch() async {
        let backend = TracesUIBackend()
        let clock = { Date(timeIntervalSince1970: 1_792_800_000) }   // a fixed day
        let model = TracesBrowserModel(backend: backend, authenticator: TracesUIAuthenticator(answer: true), now: clock)
        var status = TraceStoreStatus()
        status.oldestDay = model.today.adding(-5).description
        model.setStatus(status)
        await model.select(model.today.adding(-3))
        model.query = "alpha"
        await model.search()
        model.selectedFrame = frame.id
        await model.returnToRoot()
        XCTAssertEqual(model.day, model.today)
        XCTAssertEqual(model.query, "")
        XCTAssertNil(model.hits)
        XCTAssertNil(model.selectedFrame)
        XCTAssertEqual(backend.timelineDays.last, model.today.description, "the newest day is read again")
    }

    func testCloseDropsEveryScreenshotFromMemory() async {
        let backend = TracesUIBackend()
        let model = TracesBrowserModel(backend: backend, authenticator: TracesUIAuthenticator(answer: true))
        await model.unlock()
        await model.image(for: frame.id)
        await model.text(for: frame.id)
        model.selectedFrame = frame.id
        model.close()
        XCTAssertFalse(model.unlocked)
        XCTAssertTrue(model.images.isEmpty)
        XCTAssertTrue(model.texts.isEmpty)
        XCTAssertNil(model.selectedFrame)
        await model.image(for: frame.id)
        XCTAssertEqual(backend.imageFetches.count, 1, "closed means locked again")
    }

    func testScreenshotsHideAgainOnTheirOwn() async throws {
        let model = TracesBrowserModel(backend: TracesUIBackend(), authenticator: TracesUIAuthenticator(answer: true),
                                       hideAfter: 0.05)
        await model.unlock()
        await model.image(for: frame.id)
        XCTAssertTrue(model.unlocked)
        try await Task.sleep(for: .milliseconds(300))
        XCTAssertFalse(model.unlocked)
        XCTAssertTrue(model.images.isEmpty)
    }

    func testTheDaysRunFromTheOldestKeptThroughToday() {
        let today = ISODay(year: 2026, month: 10, day: 23)
        XCTAssertEqual(TracesBrowserModel.days(oldest: "2026-10-21", keep: 30, today: today).map(\.description),
                       ["2026-10-23", "2026-10-22", "2026-10-21"])
        XCTAssertEqual(TracesBrowserModel.days(oldest: "2026-09-01", keep: 2, today: today).count, 2)
        XCTAssertEqual(TracesBrowserModel.days(oldest: nil, keep: 30, today: today), [today])
    }

    func testLoadReadsTheChosenDay() async {
        let backend = TracesUIBackend()
        let now = TraceClock.parse("2026-10-23T12:00:00Z")!
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC")!
        let model = TracesBrowserModel(backend: backend, authenticator: TracesUIAuthenticator(answer: false),
                                       now: { now }, calendar: calendar)
        var status = TraceStoreStatus()
        status.oldestDay = "2026-10-22"
        model.setStatus(status)
        await model.load()
        await model.select(ISODay(year: 2026, month: 10, day: 22))
        XCTAssertEqual(backend.timelineDays, ["2026-10-23", "2026-10-22"])
    }
}

// MARK: - The redesigned page (owner 2026-10-28)

final class TracesUIRedesignTests: XCTestCase {
    func testTheSettingsReadTheNewKeysAndFallBackToTheOldOnes() throws {
        let new = try JSONDecoder().decode(TraceSettings.self, from: Data(#"{"learn_from_day": true, "watch_and_read": false}"#.utf8))
        XCTAssertTrue(new.learnFromDay)
        XCTAssertFalse(new.watchAndRead)
        let old = try JSONDecoder().decode(TraceSettings.self,
                                           from: Data(#"{"learn_from_summary": true, "youtube_to_watch_history": false}"#.utf8))
        XCTAssertTrue(old.learnFromDay)
        XCTAssertFalse(old.watchAndRead)
        let notice = try JSONDecoder().decode(TraceSettings.self, from: Data(#"{"reading_notice": true}"#.utf8))
        XCTAssertTrue(notice.readingNotice)
        XCTAssertTrue(Copy.Traces.readingNotice.contains("any site") && Copy.Traces.readingNotice.contains("YouTube only"))
        let none = try JSONDecoder().decode(TraceSettings.self, from: Data("{}".utf8))
        XCTAssertFalse(none.learnFromDay, "off by default")
        XCTAssertTrue(none.watchAndRead)
    }

    func testThePreviewHidesAnEmptyPartAndKeepsTheMocksOrder() throws {
        let json = #"""
        {"day": "2026-10-27", "text": "x", "counts": {"day": "2026-10-27", "total_seconds": 9000,
         "projects": [{"id": "alpha-project", "name": "Alpha", "seconds": 3000, "apps": ["Editor"]}],
         "reading": {"seconds": 1200, "pages": 3, "sites": ["docs.example"], "site_count": 2, "apps": []},
         "watching": {"seconds": 30, "videos": 1, "platforms": ["YouTube"]},
         "calls": {"seconds": 1800, "count": 2, "apps": ["Zoom"]},
         "else": {"seconds": 2970, "apps": ["Mail"], "busiest_switches": 41}}}
        """#
        let preview = try JSONDecoder().decode(TraceDigestPreview.self, from: Data(json.utf8))
        let rows = TracesPageLogic.rows(try XCTUnwrap(preview.counts))
        XCTAssertEqual(rows.map(\.id), ["project-alpha-project", "reading", "calls", "else"], "watching under a minute")
        XCTAssertEqual(rows.first?.label, Copy.Traces.yourProjects)
        XCTAssertEqual(rows[1].title, "3 pages on 2 sites")
        XCTAssertTrue(rows.last?.detail.contains("41") ?? false)
    }

    func testALongListIsCappedWithAllN() {
        let capped = TracesPageLogic.capped(Array(1...12), limit: 8, expanded: false)
        XCTAssertEqual(capped.shown.count, 8)
        XCTAssertEqual(capped.more, 12)
        XCTAssertEqual(Copy.Traces.allCount(capped.more), "All 12")
        XCTAssertEqual(TracesPageLogic.capped(Array(1...12), limit: 8, expanded: true).more, 0)
        XCTAssertEqual(TracesPageLogic.capped(Array(1...3), limit: 8, expanded: false).more, 0)
    }

    func testAMomentOnTwoScreensStaysTogetherMainScreenFirst() {
        func frame(_ id: String, _ at: String, _ display: Int?) -> TraceFrameMeta {
            TraceFrameMeta(id: id, at: at, bundleId: "com.example.App", app: "Example", width: 640, height: 400,
                           spanId: nil, hasText: false, display: display, displays: display == nil ? nil : 2)
        }
        let moments = TracesPageLogic.moments([frame("b", "2026-10-27T10:00:00Z", 2), frame("a", "2026-10-27T10:00:00Z", 1),
                                               frame("c", "2026-10-27T10:05:00Z", nil)])
        XCTAssertEqual(moments.map { $0.map(\.id) }, [["a", "b"], ["c"]])
    }

    func testTimePerAppAndSiteTheMostFirst() {
        let spans = [TraceStoredSpan(id: "1", start: "2026-10-27T10:00:00Z", end: "2026-10-27T10:30:00Z",
                                     bundleId: "com.example.Editor", app: "Editor", title: nil, url: nil, host: nil),
                     TraceStoredSpan(id: "2", start: "2026-10-27T10:30:00Z", end: "2026-10-27T11:30:00Z",
                                     bundleId: "com.google.Chrome", app: "Chrome", title: nil, url: "https://docs.example/a",
                                     host: "docs.example")]
        XCTAssertEqual(TracesPageLogic.totals(spans) { $0.app }.map(\.name), ["Chrome", "Editor"])
        XCTAssertEqual(TracesPageLogic.totals(spans) { $0.host }.map(\.seconds), [3600])
        XCTAssertEqual(Copy.Traces.duration(7800), "2 h 10 m")
        XCTAssertEqual(Copy.Traces.duration(2400), "40 m")
    }

    func testTheNewWordsNameNoProvider() {
        for words in [Copy.Traces.learnHelp, Copy.Traces.watchAndReadHelp, Copy.Traces.removeMessage] {
            for name in ["Claude", "ChatGPT", "OpenAI", "Codex", "Ollama", "OpenRouter", "Gemini", "YouTube"] {
                XCTAssertFalse(words.contains(name), name)
            }
        }
        XCTAssertTrue(Copy.Traces.learnHelp.contains("Never the screenshots"))
    }
}

@MainActor
final class TracesUIDaysModelTests: XCTestCase {
    func testOpeningADayDeletingAnItemAndTheWholeDay() async {
        let backend = TracesUIBackend()
        backend.cards = [TraceDayCard(day: "2026-10-23", spans: 2, seconds: 600, apps: 1, sites: 0, frames: 1, screens: 2,
                                      cover: "f1")]
        let model = TracesBrowserModel(backend: backend, authenticator: TracesUIAuthenticator(answer: false))
        await model.loadCards()
        XCTAssertEqual(model.cards.map(\.day), ["2026-10-23"])
        XCTAssertNil(model.openDay)
        await model.open(ISODay(year: 2026, month: 10, day: 23))
        XCTAssertEqual(model.openDay?.description, "2026-10-23")
        XCTAssertEqual(backend.timelineDays.last, "2026-10-23")
        await model.delete(spans: ["s1"])
        XCTAssertEqual(backend.deletes.last?.spans, ["s1"])
        XCTAssertEqual(backend.deletes.last?.all, false)
        await model.deleteDay()
        XCTAssertEqual(backend.deletes.last?.all, true)
        XCTAssertNil(model.openDay, "back to the cards")
    }

    func testNoCoverIsFetchedBeforeTheUnlock() async {
        let backend = TracesUIBackend()
        let model = TracesBrowserModel(backend: backend, authenticator: TracesUIAuthenticator(answer: true))
        await model.image(for: "cover-1")
        XCTAssertTrue(backend.imageFetches.isEmpty)
        await model.unlock()
        await model.image(for: "cover-1")
        XCTAssertEqual(backend.imageFetches, ["cover-1"])
    }
}
