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

    func testNotNowWaitsLongerEachTimeAndTheOfferAfterTwoWeeksIsTheLast() {
        // Owner 2026-11-23: two hours, a day, three days, a week, two weeks.
        let hour: TimeInterval = 3600
        XCTAssertEqual(ConnectSuggestPolicy.waits, [2 * hour, day, 3 * day, 7 * day, 14 * day])
        var memory = ConnectSuggestMemory()
        var at = t0
        for wait in ConnectSuggestPolicy.waits {
            memory = ConnectSuggestPolicy.shown("whatsapp", at: at, in: memory)
            memory = ConnectSuggestPolicy.answered("whatsapp", .notNow, at: at, in: memory)
            XCTAssertEqual(decide(whatsApp, memory, context(at.addingTimeInterval(wait - 60))), .skip(.snoozed))
            at = at.addingTimeInterval(wait)
            XCTAssertEqual(decide(whatsApp, memory, context(at)), .suggest)
        }
        memory = ConnectSuggestPolicy.shown("whatsapp", at: at, in: memory)
        memory = ConnectSuggestPolicy.answered("whatsapp", .notNow, at: at, in: memory)
        XCTAssertEqual(memory.sources["whatsapp"]?.shown, ConnectSuggestPolicy.maxShows)
        XCTAssertEqual(decide(whatsApp, memory, context(at.addingTimeInterval(400 * day))), .skip(.shownEnough))
    }

    func testAShowWithNoAnswerCountsAsNotNowFromWhenItShowed() {
        // The app quit while the panel showed: counted at showing, so it is never free again at once.
        let memory = ConnectSuggestPolicy.shown("whatsapp", at: t0, in: .init())
        XCTAssertEqual(decide(whatsApp, memory, context(t0.addingTimeInterval(3600))), .skip(.snoozed))
        XCTAssertEqual(decide(whatsApp, memory, context(t0.addingTimeInterval(2 * 3600))), .suggest)
    }

    func testAtMostOneSuggestionADayBetweenDifferentSources() {
        let memory = ConnectSuggestPolicy.shown("whatsapp", at: t0, in: .init())
        XCTAssertEqual(decide(notes, memory, context(t0.addingTimeInterval(23 * 3600))), .skip(.dailyCap))
        XCTAssertEqual(decide(notes, memory, context(t0.addingTimeInterval(day))), .suggest)
    }

    func testASourcesOwnReturnIsNotHeldByTheDailyCapButAnotherSourcesOfferIs() {
        var memory = ConnectSuggestPolicy.shown("whatsapp", at: t0, in: .init())
        memory = ConnectSuggestPolicy.answered("whatsapp", .notNow, at: t0, in: memory)
        let later = t0.addingTimeInterval(2 * 3600)
        XCTAssertEqual(decide(whatsApp, memory, context(later)), .suggest)
        // Another source showed in between: the cap is back for this one.
        memory = ConnectSuggestPolicy.shown("notes", at: later, in: memory)
        XCTAssertEqual(decide(whatsApp, memory, context(later.addingTimeInterval(3600))), .skip(.dailyCap))
        XCTAssertEqual(decide(whatsApp, memory, context(later.addingTimeInterval(day))), .suggest)
    }

    func testASitesOfferIsNotHeldByAnotherSourcesOfferTheSameDay() {
        // Found live: GitHub's unanswered offer kept X, Instagram and TikTok silent for a day.
        var memory = ConnectSuggestPolicy.shown("site-save:github", at: t0, in: .init())
        memory = ConnectSuggestPolicy.answered("site-save:github", .notNow, at: t0, in: memory)
        let soon = t0.addingTimeInterval(120)
        XCTAssertEqual(decide(ConnectSuggestApps.site("x"), memory, context(soon)), .suggest)
        XCTAssertEqual(decide(ConnectSuggestApps.site("github"), memory, context(soon)), .skip(.snoozed))
        // An app's offer still waits its day after a site's.
        XCTAssertEqual(decide(notes, memory, context(soon)), .skip(.dailyCap))
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
        XCTAssertNil(state.confirmedAt, "a press inside the arm delay was aimed at what was beneath")
        XCTAssertNil(state.handle(.yes, at: u0 + (0.6)), "Yes is not an answer until what it did is known")
        XCTAssertEqual(state.confirmedAt, u0 + 0.6)
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

    func testTheAskWhyQuestionTakingTheNotchIsNotNow() {
        var state = panel()
        XCTAssertEqual(state.handle(.superseded, at: u0)?.answer, .notNow)
    }

    /// Owner 2026-11-25 — the bar the panel shows is its own timer: from the showing, gone while the pointer rests on
    /// the card, from empty again when it leaves, and gone for good once Yes is pressed.
    func testTheBarRunsFromTheShowingAndAgainFromEmptyWhenThePointerLeaves() {
        var state = panel()
        XCTAssertEqual(state.countdownFrom, u0)
        _ = state.handle(.hover(true), at: u0 + 3)
        XCTAssertNil(state.countdownFrom, "held: no bar")
        _ = state.handle(.hover(false), at: u0 + 9)
        XCTAssertEqual(state.countdownFrom, u0 + 9)
        XCTAssertNil(state.handle(.tick, at: u0 + 9 + ConnectSuggestPolicy.timeout - 0.1))
        XCTAssertEqual(state.handle(.tick, at: u0 + 9 + ConnectSuggestPolicy.timeout), .timedOut)
        var pressed = panel()
        _ = pressed.handle(.yes, at: u0 + 1)
        XCTAssertNil(pressed.countdownFrom)
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
            let reads = Copy.ConnectSuggest.reads(target)
            XCTAssertFalse(title.localizedCaseInsensitiveContains(reads), reads)
            XCTAssertFalse(reads.localizedCaseInsensitiveContains("connect"), "the title already asks: \(reads)")
            for provider in ["Claude", "ChatGPT", "OpenAI", "Gemini", "Ollama", "Anthropic"] {
                XCTAssertFalse(reads.contains(provider), reads)
            }
        }
    }

    /// Owner 2026-11-23 — "make the no, not now and yes buttons bigger, and remove the two label things, for all
    /// notifications of connect": the offer is the question, what is read and the three answers, at the row size.
    func testTheAnswersAreTheRowSizeAndNoChipsStand() throws {
        XCTAssertGreaterThanOrEqual(ConnectSuggestPanelView.answerFont, 14)
        XCTAssertGreaterThanOrEqual(ConnectSuggestPanelView.answerInsets.top, 9)
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().appendingPathComponent("Sources/CicadaApp")
        let panel = try String(contentsOf: root.appendingPathComponent("ConnectSuggest/ConnectSuggestPanel.swift"),
                               encoding: .utf8)
        XCTAssertFalse(panel.contains("SaveWhyChipRows"), "no chips of what Cicada does with it")
        XCTAssertTrue(panel.contains(".contentShape(Capsule())"), "the whole pill takes the click, not only its word")
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
        ConnectSuggestStore(defaults: TestDefaults.suite("ConnectSuggestTests.\(UUID().uuidString)")!)
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
        center.connect = { opened.append($0); return .openedPage }
        await center.enter(entering("net.whatsapp.WhatsApp", pid: whatsAppPid, launched: t0))
        XCTAssertEqual(presenter.shows, 1)
        XCTAssertEqual(center.state?.target.entryId, "whatsapp")
        XCTAssertEqual(center.store.memory.sources["whatsapp"]?.shown, 1)
        XCTAssertEqual(center.store.memory.sources["whatsapp"]?.name, "WhatsApp")
        clock.now = clock.now.addingTimeInterval(1)
        center.input(.yes)
        await center.settle()
        XCTAssertNil(center.state, "a page opened is the answer: the panel leaves at once")
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
    func testLeavingTheAppNeverClosesItOnlyAnAnswerOrTheTimeoutDoes() async {
        let clock = Clock(t0)
        var front: pid_t = whatsAppPid
        let (center, presenter) = center(clock: clock, front: { front })
        await center.enter(entering("net.whatsapp.WhatsApp", pid: whatsAppPid, launched: t0))
        XCTAssertEqual(presenter.shows, 1)
        // Owner 2026-11-25: a click into another app is not an answer. The offer stays, with nothing recorded.
        front = 77
        await center.enter(ConnectSuggestActivation(bundleId: "com.apple.finder", name: "Finder", pid: 77,
                                                    launchedAt: nil))
        XCTAssertNotNil(center.state)
        XCTAssertEqual(presenter.hides, 0)
        XCTAssertNil(center.store.memory.sources["whatsapp"]?.answer)
        clock.now = clock.now.addingTimeInterval(1)
        center.input(.notNow)
        XCTAssertNil(center.state)
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
        let prefs = SaveWhyPrefs(defaults: TestDefaults.suite("ConnectSuggestTests.\(UUID().uuidString)")!)
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

    // MARK: - A save on a site that is not connected (ruling 77b)

    private let github = ConnectSuggestApps.site("github")

    private func saveClick(_ memory: ConnectSuggestMemory, _ now: Date) -> ConnectSuggestPolicy.Decision {
        ConnectSuggestPolicy.decide(github, memory: memory, context: context(now), trigger: .saveClick)
    }

    /// Found live: a site's offer left unanswered when its page opened, and the star clicked minutes later did
    /// nothing. A save click shows the offer inside that wait, once; after an offer a save brought, the wait holds.
    func testASaveClickShowsTheOfferOnceInsideAWaitAndNoIsStillNever() {
        var memory = ConnectSuggestPolicy.shown(github.entryId, at: t0, in: .init())
        memory = ConnectSuggestPolicy.answered(github.entryId, .notNow, at: t0, in: memory)
        let soon = t0.addingTimeInterval(7 * 60)
        XCTAssertEqual(decide(github, memory, context(soon)), .skip(.snoozed), "opening the page again waits")
        XCTAssertEqual(saveClick(memory, soon), .suggest)
        XCTAssertTrue(ConnectSuggestPolicy.listens(github, memory: memory, now: soon))

        memory = ConnectSuggestPolicy.shown(github.entryId, at: soon, trigger: .saveClick, in: memory)
        memory = ConnectSuggestPolicy.answered(github.entryId, .notNow, at: soon, in: memory)
        let next = soon.addingTimeInterval(60)
        XCTAssertEqual(saveClick(memory, next), .skip(.snoozed), "the second save in the same wait is left alone")
        XCTAssertFalse(ConnectSuggestPolicy.listens(github, memory: memory, now: next), "and is not read at all")
        // The second wait is a day: after it, a save click or the page shows it again.
        let later = soon.addingTimeInterval(day + 60)
        XCTAssertEqual(saveClick(memory, later), .suggest)
        XCTAssertEqual(decide(github, memory, context(later)), .suggest)
        XCTAssertTrue(ConnectSuggestPolicy.listens(github, memory: memory, now: later))

        var declined = ConnectSuggestPolicy.shown(github.entryId, at: t0, in: .init())
        declined = ConnectSuggestPolicy.answered(github.entryId, .no, at: t0, in: declined)
        XCTAssertEqual(saveClick(declined, later), .skip(.declined))
        XCTAssertFalse(ConnectSuggestPolicy.listens(github, memory: declined, now: later), "No: the site is not read")

        var spent = ConnectSuggestMemory()
        for _ in 0..<ConnectSuggestPolicy.maxShows {
            spent = ConnectSuggestPolicy.shown(github.entryId, at: t0, in: spent)
        }
        XCTAssertFalse(ConnectSuggestPolicy.listens(github, memory: spent, now: t0.addingTimeInterval(400 * day)))
        XCTAssertTrue(ConnectSuggestPolicy.listens(github, memory: .init(), now: t0), "a site never offered listens")
    }

    func testARefusalAboutTheMomentDoesNotSpendTheVisit() {
        for skip in [ConnectSuggestPolicy.Skip.showing, .saveWhyOpen, .memoryUnknown, .noEntry, .cicadaJustLaunched,
                     .appJustLaunched] {
            XCTAssertTrue(skip.passes, skip.rawValue)
        }
        for skip in [ConnectSuggestPolicy.Skip.off, .inSetup, .demo, .setUp, .declined, .answered, .shownEnough,
                     .snoozed, .dailyCap] {
            XCTAssertFalse(skip.passes, skip.rawValue)
        }
    }

    private func candidate(_ url: String, _ outcome: SiteSaveRule.Outcome = .saved) -> SiteSaveCandidate {
        SiteSaveCandidate(item: SiteSaveItem(site: "github", origin: "github-starred", url: url, title: "alpha/beta"),
                          outcome: outcome, text: "", folder: nil,
                          lesson: .labels(was: "a", now: "b", outcome: outcome))
    }

    @MainActor
    func testASaveOnAnUnconnectedSiteOffersAndOnlyYesKeepsIt() async throws {
        let clock = Clock(t0)
        let (center, presenter) = center(clock: clock, front: { self.whatsAppPid })
        let site = try XCTUnwrap(SiteSaveSite.named("github"))
        var connected: [String] = [], kept: [[SiteSaveCandidate]] = []
        center.connect = { connected.append($0); return .turnedOn(asksWhy: true, needsAccessibility: false) }
        center.onHeld = { kept.append($0) }

        // The page's own offer leaves unanswered; the star clicked after it brings the offer back, holding the save.
        XCTAssertTrue(center.offer(site: site, connected: false, pid: 7, bundleId: "com.google.Chrome"))
        XCTAssertEqual(presenter.shows, 1)
        XCTAssertEqual(center.state?.keepsSave, false)
        clock.now = clock.now.addingTimeInterval(1)
        center.input(.notNow)
        clock.now = clock.now.addingTimeInterval(300)
        let first = candidate("https://github.com/alpha/beta")
        center.offer(saved: first, site: site, pid: 7, bundleId: "com.google.Chrome")
        XCTAssertEqual(presenter.shows, 2)
        XCTAssertEqual(center.held, [first])
        XCTAssertEqual(center.state?.keepsSave, true)
        // A second save while it shows is held too; the same post twice is one.
        let second = candidate("https://github.com/alpha/gamma")
        center.offer(saved: second, site: site, pid: 7, bundleId: "com.google.Chrome")
        center.offer(saved: first, site: site, pid: 7, bundleId: "com.google.Chrome")
        XCTAssertEqual(center.held, [second, first])
        XCTAssertEqual(presenter.shows, 2)

        // A post taken off again before the answer is let go, and an unsave alone never shows an offer.
        let third = candidate("https://github.com/alpha/delta")
        center.offer(saved: third, site: site, pid: 7, bundleId: "com.google.Chrome")
        center.offer(saved: candidate("https://github.com/alpha/delta", .unsaved), site: site, pid: 7,
                     bundleId: "com.google.Chrome")
        XCTAssertEqual(center.held, [second, first])
        XCTAssertEqual(center.state?.keepsSave, true)

        // Yes runs the connect plan; "Turned on" is said only once it has come back, and the saves follow it.
        clock.now = clock.now.addingTimeInterval(1)
        center.input(.yes)
        XCTAssertTrue(center.state?.isConnecting == true)
        await center.settle()
        XCTAssertEqual(connected, ["site-save:github"])
        XCTAssertEqual(center.state?.result, .turnedOn(asksWhy: true, needsAccessibility: false))
        XCTAssertEqual(center.store.memory.sources["site-save:github"]?.answer, .yes)
        XCTAssertEqual(kept, [[second, first]], "kept once what it turned on has returned")
        clock.now = clock.now.addingTimeInterval(ConnectSuggestPolicy.confirmShow + 0.1)
        center.input(.tick)
        XCTAssertNil(center.state)
        XCTAssertEqual(connected, ["site-save:github"], "connected once")
        XCTAssertEqual(kept.count, 1)
        XCTAssertTrue(center.held.isEmpty)
    }

    /// G245 finish — a Yes still connecting after its panel left, and a second site's offer shown meanwhile with its own
    /// held save: each press keeps only its own saves. The first never takes the second's, and the second's stays held for
    /// the second offer's answer.
    @MainActor
    func testASaveHeldForOneYesIsNeverHandedToAnotherSitesPress() async throws {
        let clock = Clock(t0)
        let (center, presenter) = center(clock: clock, front: { self.whatsAppPid })
        let github = try XCTUnwrap(SiteSaveSite.named("github"))
        let reddit = try XCTUnwrap(SiteSaveSite.named("reddit"))
        func save(_ site: String, _ origin: String, _ url: String) -> SiteSaveCandidate {
            SiteSaveCandidate(item: SiteSaveItem(site: site, origin: origin, url: url, title: "alpha/beta"),
                              outcome: .saved, text: "", folder: nil, lesson: .labels(was: "a", now: "b", outcome: .saved))
        }
        let mine = save("github", "github-starred", "https://github.com/alpha/beta")
        let theirs = save("reddit", "reddit-saved", "https://www.reddit.com/r/example/comments/abc/post/")
        var finishFirst: CheckedContinuation<Void, Never>?
        var connected: [String] = [], kept: [[SiteSaveCandidate]] = []
        center.connect = { entry in
            connected.append(entry)
            if entry == "site-save:github" { await withCheckedContinuation { finishFirst = $0 } }
            return .turnedOn(asksWhy: true, needsAccessibility: false)
        }
        center.onHeld = { kept.append($0) }

        center.offer(saved: mine, site: github, pid: 7, bundleId: "com.google.Chrome")
        XCTAssertEqual(center.held, [mine])
        clock.now = clock.now.addingTimeInterval(1)
        center.input(.yes)
        // Yes is pressed and still connecting when the ask-why question takes the notch: the press stands, its save
        // is its own.
        center.input(.superseded)
        XCTAssertNil(center.state)
        // A second site's offer shows meanwhile and holds its own save.
        clock.now = clock.now.addingTimeInterval(ConnectSuggestPolicy.confirmShow + 600)
        center.offer(saved: theirs, site: reddit, pid: 7, bundleId: "com.google.Chrome")
        XCTAssertEqual(center.state?.target, ConnectSuggestApps.site("reddit"))
        XCTAssertEqual(center.held, [theirs], "the second offer holds its own save")
        XCTAssertEqual(presenter.shows, 2)
        // The first Yes comes back now.
        while finishFirst == nil { await Task.yield() }
        finishFirst?.resume()
        await center.settle()
        XCTAssertEqual(kept, [[mine]], "the first press keeps its own save, never the second offer's")
        XCTAssertEqual(center.held, [theirs], "and the second offer still holds its save")
        XCTAssertNotNil(center.state, "the first Yes's late answer never closes the second offer")
        // The second offer's own Yes keeps the second's save.
        clock.now = clock.now.addingTimeInterval(1)
        center.input(.yes)
        await center.settle()
        XCTAssertEqual(kept, [[mine], [theirs]])
        XCTAssertEqual(connected, ["site-save:github", "site-save:reddit"])
    }

    @MainActor
    func testAHeldSaveIsDroppedByAnyAnswerButYes() async throws {
        let site = try XCTUnwrap(SiteSaveSite.named("github"))
        for answer in [ConnectSuggestPanelState.Input.notNow, .no, .superseded] {
            let clock = Clock(t0)
            let (center, _) = center(clock: clock, front: { self.whatsAppPid })
            var kept = 0
            center.onHeld = { kept += $0.count }
            center.offer(saved: candidate("https://github.com/alpha/beta"), site: site, pid: 7,
                         bundleId: "com.google.Chrome")
            XCTAssertEqual(center.held.count, 1)
            XCTAssertEqual(center.store.memory.sources["site-save:github"]?.saveShown, clock.now)
            clock.now = clock.now.addingTimeInterval(1)
            center.input(answer)
            XCTAssertNil(center.state)
            XCTAssertTrue(center.held.isEmpty)
            XCTAssertEqual(kept, 0)
            center.offer(saved: candidate("https://github.com/alpha/beta", .unsaved), site: site, pid: 7,
                         bundleId: "com.google.Chrome")
            XCTAssertNil(center.state, "an unsave never shows an offer")
            // A save right after is not offered again inside the wait, and nothing is held with no panel.
            center.offer(saved: candidate("https://github.com/alpha/gamma"), site: site, pid: 7,
                         bundleId: "com.google.Chrome")
            XCTAssertNil(center.state)
            XCTAssertTrue(center.held.isEmpty)
        }
    }

    /// A click whose direction nothing settled brings the offer but promises no save; a refusal about the moment
    /// leaves the page's own offer for the next look.
    @MainActor
    func testAnUnsettledClickPromisesNothingAndAMomentsRefusalKeepsTheVisit() async throws {
        let clock = Clock(t0)
        let (center, _) = center(clock: clock, front: { self.whatsAppPid })
        let site = try XCTUnwrap(SiteSaveSite.named("github"))
        center.memoryKnown = { false }
        XCTAssertFalse(center.offer(site: site, connected: false, pid: 7, bundleId: "com.google.Chrome"))
        XCTAssertFalse(center.listens(site: "github"), "no page is read while the offer could not show")
        center.memoryKnown = { true }
        XCTAssertTrue(center.listens(site: "github"))
        center.isDemo = { true }
        XCTAssertFalse(center.listens(site: "github"))
        center.isDemo = { false }
        center.offer(saved: candidate("https://github.com/alpha/beta", .changed), site: site, pid: 7,
                     bundleId: "com.google.Chrome")
        XCTAssertNotNil(center.state)
        XCTAssertEqual(center.state?.keepsSave, false)
        XCTAssertFalse(candidate("https://github.com/alpha/beta", .unsaved).offers)
        XCTAssertFalse(candidate("https://github.com/alpha/beta", .none).offers)
    }

    /// The question's last state stays after it closes: the offer asks whether it is showing, never whether it ever
    /// showed (found 2026-11-24: one question silenced every offer until the app was relaunched).
    func testTheOfferAsksWhetherTheQuestionIsShowingNotWhetherItEverShowed() throws {
        let text = try String(contentsOf: try XCTUnwrap(ThemeTokenTests.swiftSources().first {
            $0.path.hasSuffix("ConnectSuggest/ConnectSuggestCenter.swift") }), encoding: .utf8)
        XCTAssertTrue(text.contains("saveWhy?.isShowing == true"))
        XCTAssertFalse(text.contains("saveWhyOpen = { [weak saveWhy] in saveWhy?.state != nil }"))
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
