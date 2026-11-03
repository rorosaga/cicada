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

    /// The panel's own clock is uptime seconds, never the wall clock.
    private let u0: TimeInterval = 5_000

    private func panel() -> ConnectSuggestPanelState {
        ConnectSuggestPanelState(target: whatsApp, appName: "WhatsApp", bundleId: "net.whatsapp.WhatsApp", shownAt: u0)
    }

    func testAButtonInTheArmDelayIsIgnored() {
        var state = panel()
        XCTAssertNil(state.handle(.yes, at: u0 + (0.2)))
        XCTAssertEqual(state.handle(.yes, at: u0 + (0.6)), .yes)
        state = panel()
        XCTAssertEqual(state.handle(.no, at: u0 + (1)), .no)
        state = panel()
        XCTAssertEqual(state.handle(.notNow, at: u0 + (1)), .notNow)
    }

    func testUntouchedItLeavesAfterTheTimeoutAsNotNow() {
        var state = panel()
        XCTAssertNil(state.handle(.tick, at: u0 + (ConnectSuggestPolicy.timeout - 0.1)))
        let outcome = state.handle(.tick, at: u0 + (ConnectSuggestPolicy.timeout))
        XCTAssertEqual(outcome, .timedOut)
        XCTAssertEqual(outcome?.answer, .notNow)
    }

    func testThePointerOnItHoldsItAndLeavingStartsItsPatienceAgain() {
        var state = panel()
        XCTAssertNil(state.handle(.hover(true), at: u0 + (5)))
        XCTAssertNil(state.handle(.tick, at: u0 + (60)))
        XCTAssertNil(state.handle(.hover(false), at: u0 + (60)))
        XCTAssertNil(state.handle(.tick, at: u0 + (60 + ConnectSuggestPolicy.timeout - 0.1)))
        XCTAssertEqual(state.handle(.tick, at: u0 + (60 + ConnectSuggestPolicy.timeout)), .timedOut)
    }

    func testLeavingTheAppOrTheAskWhyQuestionIsNotNow() {
        var state = panel()
        XCTAssertEqual(state.handle(.appChanged, at: u0)?.answer, .notNow)
        state = panel()
        XCTAssertEqual(state.handle(.superseded, at: u0)?.answer, .notNow)
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

    func testYesLandsOnTheMissingPermissionFirstElseTheSource() {
        for id in ["imessage", "whatsapp", "browser:safari"] {
            XCTAssertEqual(ConnectSuggestApps.landing(entryId: id, permissionGranted: { _ in false }),
                           .permission(.fullDiskAccess), id)
            XCTAssertEqual(ConnectSuggestApps.landing(entryId: id, permissionGranted: { _ in true }), .source(id), id)
        }
        // A source whose own Connect asks macOS's prompt goes straight to its page.
        for id in ["notes", "calendar-local", "reminders-local", "contacts-local", "browser:chrome", "telegram-chats"] {
            XCTAssertEqual(ConnectSuggestApps.landing(entryId: id, permissionGranted: { _ in false }), .source(id), id)
        }
    }

    func testEveryFixedTargetIsAnEntryOfTheCatalogue() {
        let ids = Set(SourceCatalog.entries(browsers: BrowserInventory.catalog.filter(\.supported), wisprPresent: true,
                                            hexPresent: true, overview: []).map(\.id))
        for target in ConnectSuggestApps.fixed.values {
            XCTAssertTrue(ids.contains(target.entryId), target.entryId)
        }
    }

    /// #579 — Hex in front is offered while no Hex meeting folder is connected, and never once one is.
    func testHexIsOfferedUntilItsMeetingFolderIsConnected() {
        XCTAssertEqual(ConnectSuggestApps.status(of: "hex", channels: [], overview: [], localReaders: [:]), .off)
        let folder = FolderRegistration(id: "hex-1", label: "Meetings", path: "/tmp/hex-meetings",
                                        include: ["**/*.md"], kind: FolderRegistration.meetingsKind,
                                        recorder: SourceCatalog.hexId)
        let connected = [SourceChannel(id: folder.channelId, label: "Hex", connected: true)]
        XCTAssertEqual(ConnectSuggestApps.status(of: "hex", channels: connected, overview: [], localReaders: [:],
                                                 meetingFolders: [folder]), .connected)
        // Another recorder's folder is the Transcripts entry's, never Hex's.
        let other = FolderRegistration(id: "otter-1", label: "Transcripts", path: "/tmp/otter",
                                       include: ["**/*.vtt"], kind: FolderRegistration.meetingsKind, recorder: nil)
        let otherOn = [SourceChannel(id: other.channelId, label: "Transcripts", connected: true)]
        XCTAssertEqual(ConnectSuggestApps.status(of: "hex", channels: otherOn, overview: [], localReaders: [:],
                                                 meetingFolders: [other]), .off)
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
        let browsers = ["chrome", "safari", "brave"].map {
            ConnectSuggestApps.Target(entryId: SourceCatalog.browserPrefix + $0, kind: .browser)
        }
        let targets = ConnectSuggestApps.Kind.allCases.filter { $0 != .browser }
            .map { ConnectSuggestApps.Target(entryId: "x", kind: $0) } + browsers
        for target in targets {
            let kind = target.kind
            let uses = Copy.ConnectSuggest.uses(kind)
            XCTAssertTrue((2...3).contains(uses.count), "\(kind)")
            XCTAssertEqual(Set(uses).count, uses.count, "\(kind)")
            let reads = Copy.ConnectSuggest.reads(target)
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

    /// Review of #585 — a browser's line says what its own entry reads: Chrome's extra switches, Safari's Reading
    /// List and its iCloud tabs import, every other browser bookmarks only.
    func testEachBrowserSaysWhatItsOwnEntryReads() {
        func line(_ id: String) -> String {
            Copy.ConnectSuggest.reads(ConnectSuggestApps.Target(entryId: SourceCatalog.browserPrefix + id, kind: .browser))
        }
        XCTAssertTrue(line("chrome").contains("tab groups") && line("chrome").contains("watched videos"))
        XCTAssertTrue(line("safari").contains("Reading List") && line("safari").contains("iCloud tabs"))
        XCTAssertEqual(line("brave"), "Only your bookmarks are read.")
        XCTAssertEqual(Set(["chrome", "safari", "brave"].map(line)).count, 3)
        // Only Chrome has the tab-groups switch and the watch history; only Safari has a Reading List.
        XCTAssertEqual(BrowserInventory.catalog.filter { $0.reads.contains(.tabGroups) }.map(\.id), ["chrome"])
        XCTAssertEqual(WatchHistoryWatcher.browser, "chrome")
        XCTAssertEqual(BrowserInventory.catalog.filter { $0.reads.contains(.readingList) }.map(\.id), ["safari"])
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
        var onHide: () -> Void = {}
        func show(_ center: ConnectSuggestCenter) { shows += 1 }
        func hide() { hides += 1; onHide() }
    }

    /// The ask-why panel's presenter, standing in for the `NSPanel` (no window anywhere).
    @MainActor
    private final class QuestionPresenter: SaveWhyPresenting {
        var shown = 0
        let onShow: () -> Void
        init(onShow: @escaping () -> Void) { self.onShow = onShow }
        func show(_ center: SaveWhyCenter) { shown += 1; onShow() }
        func hide() {}
        func focusText() {}
    }

    private actor QuietSavedWhyAPI: SavedWhyAPI {
        func freshBookmarks(_ bytes: BookmarkBytes) async throws -> BookmarkSyncResult {
            BookmarkSyncResult(new: 0, skipped: 0, sources: [])
        }
        func savedWhyOptions() async throws -> SavedWhyOptions { SavedWhyOptions.basic }
        func saveWhy(url: String, answer: SavedWhyAnswer, at: Date, addedAt: String?) async throws {}
    }

    @MainActor
    private final class Clock {
        var now: Date
        init(_ now: Date) { self.now = now }
    }

    private let whatsAppPid: pid_t = 4242

    @MainActor
    private func center(clock: Clock, front: @escaping () -> pid_t?) -> (ConnectSuggestCenter, Presenter) {
        let center = ConnectSuggestCenter(store: store(), now: { clock.now },
                                          uptime: { clock.now.timeIntervalSince1970 }, wait: { _ in }, ticks: false)
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
    func testTheAskWhyQuestionTakesTheNotchThroughItsOwnCenterWithNoWindow() async {
        // Review of #585: the offer used to step aside only through an `.onChange` on the main window's view, which a
        // closed window takes down, while the ask-why panel still opens from a sync. This drives the app's own wiring
        // (`yields(to:)`, called by `CicadaApp.startConnectSuggest`) and the question's real path, with no window.
        let clock = Clock(t0)
        let (offer, offerPanel) = center(clock: clock, front: { self.whatsAppPid })
        var order: [String] = []
        offerPanel.onHide = { order.append("offer hides") }
        let prefs = SaveWhyPrefs(defaults: UserDefaults(suiteName: "ConnectSuggestTests.\(UUID().uuidString)")!)
        prefs.enabled = true
        let questionPanel = QuestionPresenter { order.append("question shows") }
        let question = SaveWhyCenter(prefs: prefs, api: QuietSavedWhyAPI(), presenter: questionPanel,
                                     now: { clock.now })
        offer.yields(to: question)

        await offer.enter(entering("net.whatsapp.WhatsApp", pid: whatsAppPid, launched: t0))
        XCTAssertNotNil(offer.state)
        // A bookmark made a moment ago, synced live — the path a sync from another device takes with no window open.
        let fresh = FreshBookmark(url: "https://www.alpha.example/post", title: "Alpha post", origin: "chrome-bookmark",
                                  channel: "chrome-bookmarks", episodeId: "ep_2027-01-15_001",
                                  addedAt: ISO8601DateFormatter().string(from: clock.now.addingTimeInterval(-30)))
        var result = BookmarkSyncResult(new: 1, skipped: 0, sources: [
            BookmarkSyncSourceSummary(origin: "chrome-bookmark", channel: "chrome-bookmarks", found: 1, new: 1,
                                      skipped: 0, firstSync: false),
        ])
        result.fresh = [fresh]
        result.freshTotal = 1
        await question.noticed(result, live: true)

        XCTAssertEqual(questionPanel.shown, 1)
        XCTAssertNil(offer.state, "the offer never stays under the question")
        XCTAssertEqual(offer.lastOutcome, .superseded)
        XCTAssertEqual(order, ["offer hides", "question shows"], "the offer leaves before the question shows")
        XCTAssertEqual(offer.store.memory.sources["whatsapp"]?.answer, .notNow)

        // And while the question shows, no offer starts.
        clock.now = clock.now.addingTimeInterval(20 * day)
        await offer.enter(ConnectSuggestActivation(bundleId: "com.apple.Notes", name: "Notes", pid: whatsAppPid,
                                                   launchedAt: t0))
        XCTAssertEqual(offer.lastDecision, .skip(.saveWhyOpen))
    }

    func testTheAppWiresTheYieldWhereTheAppLivesNotOnTheWindow() throws {
        let app = try String(contentsOf: try XCTUnwrap(ThemeTokenTests.swiftSources().first {
            $0.path.hasSuffix("Sources/CicadaApp/CicadaApp.swift") }), encoding: .utf8)
        let start = try XCTUnwrap(app.range(of: "private func startConnectSuggest()"))
        let body = app[start.upperBound...].prefix(2_000)
        XCTAssertTrue(body.contains("connectSuggest.yields(to: saveWhy)"))
        XCTAssertFalse(app.contains("onChange(of: saveWhy.state"), "a window-level hook dies with the window")
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
