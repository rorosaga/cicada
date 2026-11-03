import XCTest
@testable import CicadaApp

/// G231 — the notch's connect suggestion: the respect rules (pure, an injected clock), the panel's own clock, the
/// apps it knows, the copy, and the center end to end against a fake presenter and a fake front app.
final class ConnectSuggestTests: XCTestCase {
    private let t0 = Date(timeIntervalSince1970: 1_800_000_000)
    private let whatsApp = ConnectSuggestApps.Target(entryId: "whatsapp", kind: .chats)
    private let notes = ConnectSuggestApps.Target(entryId: "notes", kind: .notes)
    private let day: TimeInterval = 24 * 3600

    /// A context in which everything allows a suggestion: Cicada and the app both launched an hour ago.
    private func context(_ now: Date, status: SourceCatalogStatus? = .off) -> ConnectSuggestPolicy.Context {
        ConnectSuggestPolicy.Context(now: now, enabled: true, memoryKnown: true, setUp: true, isDemo: false,
                                     status: status,
                                     appLaunchedAt: now.addingTimeInterval(-3600),
                                     cicadaLaunchedAt: now.addingTimeInterval(-3600), saveWhyOpen: false,
                                     showing: false)
    }

    private func decide(_ target: ConnectSuggestApps.Target, _ memory: ConnectSuggestMemory,
                        _ c: ConnectSuggestPolicy.Context) -> ConnectSuggestPolicy.Decision {
        ConnectSuggestPolicy.decide(target, memory: memory, context: c)
    }

    private func decide(_ target: ConnectSuggestApps.Target,
                        _ c: ConnectSuggestPolicy.Context) -> ConnectSuggestPolicy.Decision {
        decide(target, .init(), c)
    }

    // MARK: - The respect rules

    func testAFreshSourceNotConnectedIsSuggested() {
        XCTAssertEqual(decide(whatsApp, context(t0)), .suggest)
    }

    func testTheSwitchTheDemoTheMemoryAndTheOtherPanelEachRefuse() {
        var c = context(t0)
        c.enabled = false
        XCTAssertEqual(decide(whatsApp, c), .skip(.off))
        c = context(t0); c.isDemo = true
        XCTAssertEqual(decide(whatsApp, c), .skip(.demo))
        c = context(t0); c.memoryKnown = false
        XCTAssertEqual(decide(whatsApp, c), .skip(.memoryUnknown))
        c = context(t0); c.setUp = false
        XCTAssertEqual(decide(whatsApp, c), .skip(.inSetup))
        c = context(t0); c.saveWhyOpen = true
        XCTAssertEqual(decide(whatsApp, c), .skip(.saveWhyOpen))
        c = context(t0); c.showing = true
        XCTAssertEqual(decide(whatsApp, c), .skip(.showing))
    }

    func testOnlyASourceThatIsOffIsSuggested() {
        XCTAssertEqual(decide(whatsApp, context(t0, status: nil)), .skip(.noEntry))
        for status in [SourceCatalogStatus.connected, .needsSignIn, .waitingForAgent] {
            XCTAssertEqual(decide(whatsApp, context(t0, status: status)), .skip(.setUp), "\(status)")
        }
    }

    func testNoIsNeverAgainUntilSettingsUndoesIt() {
        var memory = ConnectSuggestPolicy.shown("whatsapp", name: "WhatsApp", at: t0, in: .init())
        memory = ConnectSuggestPolicy.answered("whatsapp", .no, at: t0, in: memory)
        XCTAssertEqual(decide(whatsApp, memory, context(t0.addingTimeInterval(400 * day))), .skip(.declined))
        XCTAssertEqual(memory.declined, ["whatsapp"])
        memory = ConnectSuggestPolicy.undoDecline("whatsapp", in: memory)
        XCTAssertEqual(memory.declined, [])
        XCTAssertEqual(decide(whatsApp, memory, context(t0.addingTimeInterval(2 * day))), .suggest)
    }

    func testYesIsNeverSuggestedAgain() {
        var memory = ConnectSuggestPolicy.shown("whatsapp", at: t0, in: .init())
        memory = ConnectSuggestPolicy.answered("whatsapp", .yes, at: t0, in: memory)
        XCTAssertEqual(decide(whatsApp, memory, context(t0.addingTimeInterval(400 * day))), .skip(.answered))
    }

    func testNotNowWaitsFourteenDaysThenOnceMoreAndThatIsTheLast() {
        var memory = ConnectSuggestPolicy.shown("whatsapp", at: t0, in: .init())
        memory = ConnectSuggestPolicy.answered("whatsapp", .notNow, at: t0, in: memory)
        XCTAssertEqual(decide(whatsApp, memory, context(t0.addingTimeInterval(13 * day))), .skip(.snoozed))
        let second = t0.addingTimeInterval(14 * day)
        XCTAssertEqual(decide(whatsApp, memory, context(second)), .suggest)
        memory = ConnectSuggestPolicy.shown("whatsapp", at: second, in: memory)
        memory = ConnectSuggestPolicy.answered("whatsapp", .notNow, at: second, in: memory)
        XCTAssertEqual(decide(whatsApp, memory, context(second.addingTimeInterval(400 * day))), .skip(.shownEnough))
    }

    func testAShowWithNoAnswerCountsAsNotNowFromWhenItShowed() {
        // The app quit while the panel showed: counted at showing, so it never comes back the next day.
        let memory = ConnectSuggestPolicy.shown("whatsapp", at: t0, in: .init())
        XCTAssertEqual(decide(whatsApp, memory, context(t0.addingTimeInterval(2 * day))), .skip(.snoozed))
        XCTAssertEqual(decide(whatsApp, memory, context(t0.addingTimeInterval(14 * day))), .suggest)
    }

    func testAtMostOneSuggestionADayAcrossSources() {
        let memory = ConnectSuggestPolicy.shown("whatsapp", at: t0, in: .init())
        XCTAssertEqual(decide(notes, memory, context(t0.addingTimeInterval(23 * 3600))), .skip(.dailyCap))
        XCTAssertEqual(decide(notes, memory, context(t0.addingTimeInterval(day))), .suggest)
    }

    func testNeverInTheFirstMinuteAfterTheAppOrCicadaLaunched() {
        var c = context(t0)
        c.appLaunchedAt = t0.addingTimeInterval(-59)
        XCTAssertEqual(decide(whatsApp, c), .skip(.appJustLaunched))
        c.appLaunchedAt = t0.addingTimeInterval(-60)
        XCTAssertEqual(decide(whatsApp, c), .suggest)
        c.appLaunchedAt = nil   // launched outside Launch Services: Cicada's own minute still holds
        c.cicadaLaunchedAt = t0.addingTimeInterval(-30)
        XCTAssertEqual(decide(whatsApp, c), .skip(.cicadaJustLaunched))
    }

    // MARK: - The panel's clock

    private func panel() -> ConnectSuggestPanelState {
        ConnectSuggestPanelState(target: whatsApp, appName: "WhatsApp", bundleId: "net.whatsapp.WhatsApp", shownAt: t0)
    }

    func testAButtonInTheArmDelayIsIgnored() {
        var state = panel()
        XCTAssertNil(state.handle(.yes, at: t0.addingTimeInterval(0.2)))
        XCTAssertEqual(state.handle(.yes, at: t0.addingTimeInterval(0.6)), .yes)
        state = panel()
        XCTAssertEqual(state.handle(.no, at: t0.addingTimeInterval(1)), .no)
        state = panel()
        XCTAssertEqual(state.handle(.notNow, at: t0.addingTimeInterval(1)), .notNow)
    }

    func testUntouchedItLeavesAfterTheTimeoutAsNotNow() {
        var state = panel()
        XCTAssertNil(state.handle(.tick, at: t0.addingTimeInterval(ConnectSuggestPolicy.timeout - 0.1)))
        let outcome = state.handle(.tick, at: t0.addingTimeInterval(ConnectSuggestPolicy.timeout))
        XCTAssertEqual(outcome, .timedOut)
        XCTAssertEqual(outcome?.answer, .notNow)
    }

    func testThePointerOnItHoldsItAndLeavingStartsItsPatienceAgain() {
        var state = panel()
        XCTAssertNil(state.handle(.hover(true), at: t0.addingTimeInterval(5)))
        XCTAssertNil(state.handle(.tick, at: t0.addingTimeInterval(60)))
        XCTAssertNil(state.handle(.hover(false), at: t0.addingTimeInterval(60)))
        XCTAssertNil(state.handle(.tick, at: t0.addingTimeInterval(60 + ConnectSuggestPolicy.timeout - 0.1)))
        XCTAssertEqual(state.handle(.tick, at: t0.addingTimeInterval(60 + ConnectSuggestPolicy.timeout)), .timedOut)
    }

    func testLeavingTheAppOrTheAskWhyQuestionIsNotNow() {
        var state = panel()
        XCTAssertEqual(state.handle(.appChanged, at: t0)?.answer, .notNow)
        state = panel()
        XCTAssertEqual(state.handle(.superseded, at: t0)?.answer, .notNow)
    }

    // MARK: - The apps

    func testTheSupportedApps() {
        let expect: [String: String] = [
            "net.whatsapp.WhatsApp": "whatsapp", "ru.keepcoder.Telegram": "telegram-chats",
            "org.telegram.desktop": "telegram-chats", "com.apple.MobileSMS": "imessage", "com.apple.Notes": "notes",
            "com.apple.iCal": "calendar-local", "com.apple.reminders": "reminders-local",
            "com.apple.AddressBook": "contacts-local", "com.google.Chrome": "browser:chrome",
            "com.apple.Safari": "browser:safari", "anomaly.hex": "hex", "notion.id": "notion",
        ]
        for (bundle, entry) in expect {
            XCTAssertEqual(ConnectSuggestApps.target(bundleId: bundle)?.entryId, entry, bundle)
        }
        // A browser Cicada does not read, an app with no source, and Readwise (gone from Sources) are never suggested.
        for bundle in ["company.thebrowser.Browser", "org.mozilla.firefox", "com.apple.finder", "com.readwise.app"] {
            XCTAssertNil(ConnectSuggestApps.target(bundleId: bundle), bundle)
        }
        XCTAssertNil(ConnectSuggestApps.target(bundleId: nil))
    }

    func testEveryFixedTargetIsAnEntryOfTheCatalogueOrWaitsForOne() {
        let ids = Set(SourceCatalog.entries(browsers: BrowserInventory.catalog.filter(\.supported), wisprPresent: true,
                                            overview: []).map(\.id))
        for target in ConnectSuggestApps.fixed.values where target.entryId != "hex" {
            XCTAssertTrue(ids.contains(target.entryId), target.entryId)
        }
    }

    func testTheStatusIsTheCatalogueRowsOwn() {
        let on = [SourceChannel(id: "whatsapp", label: "WhatsApp", connected: true)]
        XCTAssertEqual(ConnectSuggestApps.status(of: "whatsapp", channels: on, overview: [], localReaders: [:]),
                       .connected)
        XCTAssertEqual(ConnectSuggestApps.status(of: "whatsapp", channels: [], overview: [], localReaders: [:]), .off)
        // A browser whose bookmarks synced once but whose watch is off here reads Off, as its row does.
        let chrome = [SourceChannel(id: "chrome-bookmarks", label: "Chrome", connected: true)]
        XCTAssertEqual(ConnectSuggestApps.status(of: "browser:chrome", channels: chrome, overview: [],
                                                 localReaders: ["chrome-bookmarks": false]), .off)
        XCTAssertNil(ConnectSuggestApps.status(of: "no-such-entry", channels: [], overview: [], localReaders: [:]))
    }

    // MARK: - The copy

    func testTheCopySaysEachThingOnceAndNamesNoProvider() {
        let title = Copy.ConnectSuggest.title("WhatsApp")
        for kind in ConnectSuggestApps.Kind.allCases {
            let uses = Copy.ConnectSuggest.uses(kind)
            XCTAssertTrue((2...3).contains(uses.count), "\(kind)")
            XCTAssertEqual(Set(uses).count, uses.count, "\(kind)")
            let reads = Copy.ConnectSuggest.reads(kind)
            for line in uses + [reads] {
                XCTAssertFalse(title.localizedCaseInsensitiveContains(line), line)
                XCTAssertFalse(line.localizedCaseInsensitiveContains("connect"), "the title already asks: \(line)")
                for provider in ["Claude", "ChatGPT", "OpenAI", "Gemini", "Ollama", "Anthropic"] {
                    XCTAssertFalse(line.contains(provider), line)
                }
            }
            XCTAssertFalse(uses.contains(reads))
        }
    }

    // MARK: - The store and the center

    private func store() -> ConnectSuggestStore {
        ConnectSuggestStore(defaults: UserDefaults(suiteName: "ConnectSuggestTests.\(UUID().uuidString)")!)
    }

    func testTheSwitchIsOnByDefaultAndTheMemoryRoundTrips() {
        let store = store()
        XCTAssertTrue(store.enabled)
        let memory = ConnectSuggestPolicy.shown("notes", name: "Notes", at: t0, in: .init())
        store.memory = memory
        XCTAssertEqual(store.memory, memory)
        store.enabled = false
        XCTAssertFalse(store.enabled)
    }

    @MainActor
    private final class Presenter: ConnectSuggestPresenting {
        var shows = 0
        var hides = 0
        func show(_ center: ConnectSuggestCenter) { shows += 1 }
        func hide() { hides += 1 }
    }

    @MainActor
    private final class Clock {
        var now: Date
        init(_ now: Date) { self.now = now }
    }

    private let whatsAppPid: pid_t = 4242

    @MainActor
    private func center(clock: Clock, front: @escaping () -> pid_t?) -> (ConnectSuggestCenter, Presenter) {
        let center = ConnectSuggestCenter(store: store(), now: { clock.now }, wait: { _ in }, ticks: false)
        // Cicada launched an hour before the test's clock starts moving.
        clock.now = clock.now.addingTimeInterval(3600)
        let presenter = Presenter()
        center.attach(presenter: presenter)
        center.memoryKnown = { true }
        center.setUp = { true }
        center.isDemo = { false }
        center.status = { _ in .off }
        center.frontmostPid = front
        center.iconFor = { _ in nil }
        return (center, presenter)
    }

    private func entering(_ bundle: String, pid: pid_t, launched: Date?) -> ConnectSuggestActivation {
        ConnectSuggestActivation(bundleId: bundle, name: "WhatsApp", pid: pid, launchedAt: launched)
    }

    @MainActor
    func testEnteringShowsOnceAndYesOpensTheSourcesPage() async {
        let clock = Clock(t0)
        let (center, presenter) = center(clock: clock, front: { self.whatsAppPid })
        var opened: [String] = []
        center.onYes = { opened.append($0) }
        await center.enter(entering("net.whatsapp.WhatsApp", pid: whatsAppPid, launched: t0))
        XCTAssertEqual(presenter.shows, 1)
        XCTAssertEqual(center.state?.target.entryId, "whatsapp")
        XCTAssertEqual(center.store.memory.sources["whatsapp"]?.shown, 1)
        XCTAssertEqual(center.store.memory.sources["whatsapp"]?.name, "WhatsApp")
        clock.now = clock.now.addingTimeInterval(1)
        center.input(.yes)
        XCTAssertNil(center.state)
        XCTAssertEqual(presenter.hides, 1)
        XCTAssertEqual(opened, ["whatsapp"])
        XCTAssertEqual(center.store.memory.sources["whatsapp"]?.answer, .yes)
        // The next day, entering WhatsApp again shows nothing.
        clock.now = clock.now.addingTimeInterval(2 * day)
        await center.enter(entering("net.whatsapp.WhatsApp", pid: whatsAppPid, launched: t0))
        XCTAssertEqual(presenter.shows, 1)
        XCTAssertEqual(center.lastDecision, .skip(.answered))
    }

    @MainActor
    func testAnAppPassedThroughDuringTheDwellIsNotEntered() async {
        let clock = Clock(t0)
        let (center, presenter) = center(clock: clock, front: { 1 })   // something else is in front after the dwell
        await center.enter(entering("net.whatsapp.WhatsApp", pid: whatsAppPid, launched: t0))
        XCTAssertEqual(presenter.shows, 0)
        XCTAssertNil(center.lastDecision)
    }

    @MainActor
    func testLeavingTheAppClosesItAsNotNowAndTheTimeoutDoesToo() async {
        let clock = Clock(t0)
        var front: pid_t = whatsAppPid
        let (center, presenter) = center(clock: clock, front: { front })
        await center.enter(entering("net.whatsapp.WhatsApp", pid: whatsAppPid, launched: t0))
        XCTAssertEqual(presenter.shows, 1)
        front = 77
        await center.enter(ConnectSuggestActivation(bundleId: "com.apple.finder", name: "Finder", pid: 77,
                                                    launchedAt: nil))
        XCTAssertNil(center.state)
        XCTAssertEqual(center.lastOutcome, .leftApp)
        XCTAssertEqual(center.store.memory.sources["whatsapp"]?.answer, .notNow)

        // Fifteen days on, Notes: shown, then untouched past the timeout.
        clock.now = clock.now.addingTimeInterval(15 * day)
        front = 88
        await center.enter(ConnectSuggestActivation(bundleId: "com.apple.Notes", name: "Notes", pid: 88,
                                                    launchedAt: t0))
        XCTAssertEqual(center.state?.target.entryId, "notes")
        clock.now = clock.now.addingTimeInterval(ConnectSuggestPolicy.timeout)
        center.input(.tick)
        XCTAssertEqual(center.lastOutcome, .timedOut)
        XCTAssertEqual(center.store.memory.sources["notes"]?.answer, .notNow)
    }

    @MainActor
    func testTheAskWhyQuestionTakesTheNotch() async {
        let clock = Clock(t0)
        let (center, presenter) = center(clock: clock, front: { self.whatsAppPid })
        await center.enter(entering("net.whatsapp.WhatsApp", pid: whatsAppPid, launched: t0))
        center.yield()
        XCTAssertEqual(presenter.hides, 1)
        XCTAssertEqual(center.lastOutcome, .superseded)
    }

    @MainActor
    func testNoIsListedForSettingsAndSuggestAgainClearsIt() async {
        let clock = Clock(t0)
        let (center, _) = center(clock: clock, front: { self.whatsAppPid })
        await center.enter(entering("net.whatsapp.WhatsApp", pid: whatsAppPid, launched: t0))
        clock.now = clock.now.addingTimeInterval(1)
        center.input(.no)
        XCTAssertEqual(center.declined.map(\.name), ["WhatsApp"])
        center.undoDecline("whatsapp")
        XCTAssertTrue(center.declined.isEmpty)
    }

    @MainActor
    func testTurningTheSwitchOffClosesAnOpenSuggestionWithoutAnAnswer() async {
        let clock = Clock(t0)
        let (center, presenter) = center(clock: clock, front: { self.whatsAppPid })
        await center.enter(entering("net.whatsapp.WhatsApp", pid: whatsAppPid, launched: t0))
        center.enabled = false
        XCTAssertEqual(presenter.hides, 1)
        XCTAssertNil(center.store.memory.sources["whatsapp"]?.answer)
    }

    // MARK: - Source guards

    func testThePanelNeverTakesTheKeyboardAndAsksNoPermission() throws {
        let sources = try ThemeTokenTests.swiftSources().filter { $0.path.contains("/ConnectSuggest/") }
        XCTAssertEqual(sources.count, 3)
        let text = try sources.map { try String(contentsOf: $0, encoding: .utf8) }.joined()
        XCTAssertTrue(text.contains("override var canBecomeKey: Bool { false }"))
        XCTAssertTrue(text.contains("orderFrontRegardless()"))
        for forbidden in ["makeKey", "activate(ignoringOtherApps", "AEDeterminePermissionToAutomateTarget",
                          "CGWindowListCreateImage", "NSAppleScript", "AXIsProcessTrusted"] {
            XCTAssertFalse(text.contains(forbidden), forbidden)
        }
    }
}
