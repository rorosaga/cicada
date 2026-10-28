import XCTest
@testable import CicadaApp

/// G218 — the recorder on fakes only: no NSWorkspace, Accessibility, Apple Events, ScreenCaptureKit, Vision or
/// LocalAuthentication is touched, and no permission prompt can appear. Synthetic apps and titles only.
@MainActor
final class TraceRecorderTests: XCTestCase {
    // MARK: Fakes

    final class Backend: TraceBackend, @unchecked Sendable {
        private let lock = NSLock()
        var answer: TraceSettingsAnswer
        private(set) var spans: [TraceSpan] = []
        private(set) var frames: [TraceFramePost] = []
        private(set) var calls: [String] = []
        var failSync = false

        init(settings: TraceSettings) {
            var lists = TracePolicyLists()
            lists.neverApps = ["com.example.Vault"]
            lists.titleOffApps = ["com.apple.MobileSMS", "com.example.Chat"]
            lists.urlBrowsers = ["chrome": ["com.google.Chrome"]]
            lists.contentKeys = ["youtube.com": ["v"]]
            answer = TraceSettingsAnswer(settings: settings, status: TraceStoreStatus(), policy: lists, consentVersion: 1)
        }

        private func note(_ call: String) { lock.lock(); calls.append(call); lock.unlock() }
        func traceSettings() async throws -> TraceSettingsAnswer { note("settings"); return answer }
        private(set) var displayedVersions: [Int] = []
        func traceTurnOn(consentVersion: Int, displayedVersion: Int) async throws -> TraceSettingsAnswer {
            note("on"); displayedVersions.append(displayedVersion); answer.settings.enabled = true; return answer
        }
        func traceTurnOff() async throws -> TraceSettingsAnswer { note("off"); answer.settings.enabled = false; return answer }
        func traceUpdate(_ patch: [String: TracePatchValue]) async throws -> TraceSettingsAnswer { note("update"); return answer }
        func tracePause(until: String?) async throws -> TraceSettingsAnswer {
            note("pause")
            answer.settings.pausedSince = until == nil ? nil : "2026-10-23T15:00:00Z"
            answer.settings.pausedUntil = until
            return answer
        }
        func traceSync(_ spans: [TraceSpan]) async throws -> TraceSyncResult {
            note("sync")
            if failSync { throw APIError.serverUnreachable }
            lock.lock(); self.spans += spans; lock.unlock()
            return TraceSyncResult(received: spans.count, kept: spans.count)
        }
        func traceAddFrame(_ frame: TraceFramePost) async throws { note("frame"); lock.lock(); frames.append(frame); lock.unlock() }
        func traceTimeline(day: String) async throws -> TraceTimeline { TraceTimeline(day: day, spans: [], frames: [], unreadable: 0) }
        func traceSearch(_ query: String) async throws -> [TraceSearchHit] { [] }
        func traceFrameImage(id: String) async throws -> Data { Data() }
        func traceFrameText(id: String) async throws -> TraceFrameText { TraceFrameText(id: id, at: "", app: nil, text: "") }
        func traceForget(minutes: Int) async throws { note("forget") }
        func traceWipe() async throws -> TraceSettingsAnswer { note("wipe"); answer.settings = TraceSettings(); return answer }
        func traceDayCards() async throws -> [TraceDayCard] { [] }
        func traceDelete(day: String, spans: [String], frames: [String], all: Bool) async throws -> TraceDeleted {
            TraceDeleted(spans: 0, frames: 0)
        }
        func tracePreview(day: String?) async throws -> TraceDigestPreview { TraceDigestPreview(day: "") }
        func traceAdded() async throws -> TraceAdded { TraceAdded() }
        func traceRemoveFromMemory() async throws -> TraceRemoval { TraceRemoval(removalId: nil, removed: 0) }
        func traceUndoRemoval(id: String) async throws -> Int { 0 }
    }

    final class Workspace: TraceWorkspace {
        var front: TraceFrontApp?
        func frontmost() -> TraceFrontApp? { front }
        func onActivation(_ handler: @escaping @MainActor () -> Void) -> AnyObject { NSObject() }
    }

    final class Idle: TraceIdleProbe, @unchecked Sendable {
        var idleFor: TimeInterval = 0
        var locked = false
        var secure = false
        func secondsSinceInput() -> TimeInterval { idleFor }
        func screenLocked() -> Bool { locked }
        func secureInput() -> Bool { secure }
    }

    final class Titles: TraceWindowTitles, @unchecked Sendable {
        var title: String? = "alpha-project plan"
        var isTrusted = true
        private(set) var reads = 0
        func trusted() -> Bool { isTrusted }
        func focusedTitle(pid: Int32) -> String? { reads += 1; return title }
    }

    final class Tabs: TraceBrowserTabs, @unchecked Sendable {
        var tab: TraceBrowserTab? = TraceBrowserTab(url: "https://www.youtube.com/watch?v=aaaaaaaaaaa&t=9",
                                                    title: "Bridge design", isPrivate: false)
        var isGranted = true
        private(set) var reads = 0
        func granted(bundleId: String) -> Bool { isGranted }
        func frontTab(bundleId: String) async -> TraceBrowserTab? { reads += 1; return tab }
    }

    final class Capture: TraceScreenCapture, @unchecked Sendable {
        var access = true
        private(set) var captures = 0
        private(set) var accessChecks = 0
        private(set) var screenCaptures = 0
        /// What each all-screens capture was told to show and keep.
        private(set) var shownAsked: [(keepFront: Bool, shown: @Sendable (String) -> Bool)] = []
        var screens = 2
        var onCapture: (@MainActor () -> Void)?
        func hasAccess() -> Bool { accessChecks += 1; return access }
        func captureFrontWindow(pid: Int32, maxSide: Int) async throws -> TraceCapturedFrame {
            captures += 1
            if let onCapture { await onCapture() }
            return TraceCapturedFrame(jpeg: Data([0xFF, 0xD8, 0xFF, 0xE0]), width: 640, height: 400)
        }
        func captureScreens(frontPid: Int32, keepFrontWindow: Bool, maxSide: Int,
                            shown: @escaping @Sendable (String) -> Bool) async throws -> [TraceCapturedFrame] {
            screenCaptures += 1
            shownAsked.append((keepFrontWindow, shown))
            return (1...screens).map {
                TraceCapturedFrame(jpeg: Data([0xFF, 0xD8, 0xFF, 0xE0]), width: 640, height: 400, display: $0,
                                   displays: screens)
            }
        }
    }

    struct Recognizer: TraceTextRecognizer {
        func recognize(jpeg: Data) async -> String { "recognized words" }
    }

    final class Registry: TraceBrowserRegistry, @unchecked Sendable {
        var webApps: Set<String> = []
        func opensWebLinks(_ bundleId: String) -> Bool { webApps.contains(bundleId) }
    }

    // MARK: Harness

    var clock = Date(timeIntervalSince1970: 1_792_768_800)   // 2026-10-23 (synthetic)
    var backend: Backend!
    var workspace: Workspace!
    var idle: Idle!
    var titles: Titles!
    var tabs: Tabs!
    var capture: Capture!
    var registry: Registry!
    var connection = ServerConnection(mode: .thisMac, source: .none)

    static let editor = TraceFrontApp(bundleId: "com.example.Editor", name: "Editor", pid: 101)
    static let chrome = TraceFrontApp(bundleId: "com.google.Chrome", name: "Chrome", pid: 102)

    func makeRecorder(_ configure: (inout TraceSettings) -> Void = { _ in }) -> TraceRecorder {
        var settings = TraceSettings()
        settings.enabled = true
        settings.browsers = ["chrome"]
        configure(&settings)
        backend = Backend(settings: settings)
        workspace = Workspace()
        idle = Idle()
        titles = Titles()
        tabs = Tabs()
        capture = Capture()
        registry = Registry()
        // A ticker that never fires on its own: the test drives every tick.
        return TraceRecorder(backend: backend, workspace: workspace, idle: idle, titles: titles, tabs: tabs,
                             capture: capture, recognizer: Recognizer(), registry: registry, connection: { [unowned self] in connection },
                             now: { [unowned self] in clock }, ownBundleId: "com.rorosaga.cicada.test",
                             tickInterval: .seconds(3600))
    }

    func advance(_ seconds: TimeInterval) { clock = clock.addingTimeInterval(seconds) }

    /// Ticks at `every` seconds for `seconds`.
    func run(_ recorder: TraceRecorder, for seconds: TimeInterval, every: TimeInterval = 5) async {
        var elapsed: TimeInterval = 0
        while elapsed < seconds {
            await recorder.tick()
            advance(every)
            elapsed += every
        }
    }

    func settle() async {
        for _ in 0..<20 { await Task.yield() }
        try? await Task.sleep(for: .milliseconds(30))
    }

    // MARK: Off, on, this Mac

    func testOffByDefaultNothingIsReadOrPosted() async {
        let recorder = makeRecorder { $0.enabled = false }
        await recorder.start()
        workspace.front = Self.editor
        await run(recorder, for: 120)
        await recorder.flush(force: true)
        XCTAssertEqual(recorder.state, .off)
        XCTAssertEqual(titles.reads, 0)
        XCTAssertEqual(capture.captures, 0)
        XCTAssertTrue(backend.spans.isEmpty)
        XCTAssertFalse(backend.calls.contains("sync"))
    }

    func testOnAServerConnectionNothingIsRecordedOrSent() async {
        let recorder = makeRecorder()
        connection = ServerConnection(mode: .server(URL(string: "https://home-server.example")!), source: .file)
        await recorder.start()
        workspace.front = Self.editor
        await run(recorder, for: 120)
        await recorder.flush(force: true)
        XCTAssertEqual(recorder.state, .notThisMac)
        XCTAssertTrue(backend.calls.isEmpty, "not even the settings are asked of a server")
        XCTAssertFalse(TraceBackendGate.allows(connection))
    }

    func testARecordedSpanCarriesTheAppTheTitleAndZonedTimes() async throws {
        let recorder = makeRecorder()
        await recorder.start()
        workspace.front = Self.editor
        await run(recorder, for: 30)
        workspace.front = Self.chrome
        await run(recorder, for: 30)
        await recorder.flush(force: true)
        XCTAssertEqual(recorder.state, .recording)
        XCTAssertEqual(backend.spans.count, 1)
        let span = try XCTUnwrap(backend.spans.first)
        XCTAssertEqual(span.bundleId, "com.example.Editor")
        XCTAssertEqual(span.title, "alpha-project plan")
        XCTAssertNil(span.url)
        XCTAssertTrue(span.start.hasSuffix("Z") && span.end.hasSuffix("Z"))
        XCTAssertNotNil(TraceClock.parse(span.end))
    }

    // MARK: Exclusions

    func testAnExcludedAppRecordsNothingNotEvenATitleOrAScreenshot() async {
        let recorder = makeRecorder { $0.excludedApps = ["com.example.Bank"] }
        await recorder.start()
        workspace.front = TraceFrontApp(bundleId: "com.example.Bank", name: "Bank", pid: 7)
        await run(recorder, for: 600)
        await recorder.flush(force: true)
        XCTAssertTrue(backend.spans.isEmpty)
        XCTAssertEqual(titles.reads, 0, "an excluded app's window is never read")
        XCTAssertEqual(capture.captures, 0)
    }

    func testPasswordManagersTheBackendsListAndCicadaItselfAreNeverRecorded() async {
        let recorder = makeRecorder()
        await recorder.start()
        for app in ["com.1password.1password", "com.apple.Passwords", "com.example.Vault", "com.rorosaga.cicada",
                    "com.rorosaga.cicada.test"] {
            workspace.front = TraceFrontApp(bundleId: app, name: "x", pid: 9)
            await run(recorder, for: 30)
        }
        await recorder.flush(force: true)
        XCTAssertTrue(backend.spans.isEmpty)
        XCTAssertEqual(titles.reads, 0)
        XCTAssertEqual(capture.captures, 0)
    }

    func testAPrivateWindowRecordsNothing() async {
        let recorder = makeRecorder()
        await recorder.start()
        tabs.tab = TraceBrowserTab(url: "https://docs.example/a", title: "Secret", isPrivate: true)
        workspace.front = Self.chrome
        await run(recorder, for: 120)
        await recorder.flush(force: true)
        XCTAssertTrue(backend.spans.isEmpty)
        XCTAssertEqual(capture.captures, 0)
    }

    func testAnExcludedSiteDropsTheWholeMoment() async {
        let recorder = makeRecorder { $0.excludedSites = ["bank.example"] }
        await recorder.start()
        tabs.tab = TraceBrowserTab(url: "https://my.bank.example/account", title: "Balance", isPrivate: false)
        workspace.front = Self.chrome
        await run(recorder, for: 120)
        await recorder.flush(force: true)
        XCTAssertTrue(backend.spans.isEmpty)
        XCTAssertEqual(capture.captures, 0)
    }

    func testAnAllowedBrowserKeepsTheCleanedAddressAndTheTabTitle() async throws {
        let recorder = makeRecorder()
        await recorder.start()
        workspace.front = Self.chrome
        await run(recorder, for: 30)
        XCTAssertEqual(titles.reads, 0, "a browser's title comes from its verified tab, never the window")
        workspace.front = Self.editor
        await run(recorder, for: 10)
        await recorder.flush(force: true)
        let span = try XCTUnwrap(backend.spans.first)
        XCTAssertEqual(span.url, "https://www.youtube.com/watch?v=aaaaaaaaaaa")
        XCTAssertEqual(span.title, "Bridge design")
    }

    func testABrowserWhoseTabCannotBeVerifiedKeepsOnlyTheAppAndTimes() async throws {
        let recorder = makeRecorder()
        await recorder.start()
        workspace.front = TraceFrontApp(bundleId: "com.apple.Safari", name: "Safari", pid: 103)
        await run(recorder, for: 400)
        await settle()
        let (reads, captures) = (titles.reads, capture.captures)
        workspace.front = Self.editor
        await run(recorder, for: 10)
        await recorder.flush(force: true)
        let span = try XCTUnwrap(backend.spans.first)
        XCTAssertEqual(span.bundleId, "com.apple.Safari")
        XCTAssertNil(span.title)
        XCTAssertNil(span.url)
        XCTAssertEqual(tabs.reads, 0, "only an allowed Chromium browser is asked for its tab")
        XCTAssertEqual(reads, 0)
        XCTAssertEqual(captures, 0, "a window that may be private is never captured")
    }

    func testABrowserNotAllowedOrNotGrantedIsNeverAsked() async {
        let recorder = makeRecorder { $0.browsers = [] }
        await recorder.start()
        workspace.front = Self.chrome
        await run(recorder, for: 30)
        XCTAssertEqual(tabs.reads, 0)
        let granted = makeRecorder()
        tabs.isGranted = false
        await granted.start()
        workspace.front = Self.chrome
        await run(granted, for: 30)
        XCTAssertEqual(tabs.reads, 0, "an undecided Automation grant is never pushed to a prompt")
    }

    func testChatAndMailKeepTheAppNeverTheTitleOrAScreenshot() async throws {
        let recorder = makeRecorder()
        await recorder.start()
        workspace.front = TraceFrontApp(bundleId: "com.apple.MobileSMS", name: "Messages", pid: 104)
        await run(recorder, for: 400)
        await settle()
        XCTAssertEqual(titles.reads, 0)
        XCTAssertEqual(capture.captures, 0)
        workspace.front = Self.editor
        await run(recorder, for: 10)
        await recorder.flush(force: true)
        let span = try XCTUnwrap(backend.spans.first)
        XCTAssertNil(span.title)
    }

    // MARK: Review of #456

    /// B3: an app macOS registers for https: links is a browser even when no list names it.
    func testAnUnlistedBrowserIsNeverDescribedNorCaptured() async throws {
        let recorder = makeRecorder()
        registry.webApps = ["org.example.NewBrowser"]
        await recorder.start()
        workspace.front = TraceFrontApp(bundleId: "org.example.NewBrowser", name: "New", pid: 120)
        await run(recorder, for: 400)
        await settle()
        XCTAssertEqual(titles.reads, 0, "its window title (a private window's, maybe) is never read")
        XCTAssertEqual(capture.captures, 0)
        workspace.front = Self.editor
        await run(recorder, for: 10)
        await recorder.flush(force: true)
        let span = try XCTUnwrap(backend.spans.first)
        XCTAssertNil(span.title)
        XCTAssertEqual(span.browser, true, "the flag tells the backend to refuse its title and frames too")
    }

    /// B2: a frame is kept only if what was vetted is still in front when it was taken.
    func testAFrameTakenAfterTheTabTurnedPrivateIsDropped() async {
        let recorder = makeRecorder()
        await recorder.start()
        workspace.front = Self.chrome
        capture.onCapture = { [unowned self] in
            self.tabs.tab = TraceBrowserTab(url: "https://docs.example/secret", title: "Secret", isPrivate: true)
        }
        await recorder.tick()
        await settle()
        XCTAssertEqual(capture.captures, 1)
        XCTAssertTrue(backend.frames.isEmpty, "the incognito window came forward: its frame is never posted")
    }

    func testAFrameTakenAfterAnotherAppCameForwardIsDropped() async {
        let recorder = makeRecorder()
        await recorder.start()
        workspace.front = Self.editor
        capture.onCapture = { [unowned self] in
            self.workspace.front = TraceFrontApp(bundleId: "com.example.Other", name: "Other", pid: 999)
        }
        await recorder.tick()
        await settle()
        XCTAssertEqual(capture.captures, 1)
        XCTAssertTrue(backend.frames.isEmpty)
    }

    func testAnUnchangedBrowserFrameIsKeptAndMarkedAsABrowser() async {
        let recorder = makeRecorder()
        await recorder.start()
        workspace.front = Self.chrome
        await recorder.tick()
        await settle()
        XCTAssertEqual(backend.frames.count, 1)
        XCTAssertEqual(backend.frames.first?.browser, true)
        XCTAssertEqual(backend.frames.first?.host, "www.youtube.com")
    }

    /// B2: the front window is the window server's first normal-layer window of the app, never ScreenCaptureKit's.
    func testTheFrontWindowIsTheFirstNormalWindowInTheFrontToBackList() {
        let entries: [[String: Any]] = [
            ["kCGWindowOwnerPID": 50, "kCGWindowLayer": 0, "kCGWindowNumber": 1],            // another app on top
            ["kCGWindowOwnerPID": 102, "kCGWindowLayer": 25, "kCGWindowNumber": 2],           // the app's menu-bar item
            ["kCGWindowOwnerPID": 102, "kCGWindowLayer": 0, "kCGWindowNumber": 3,
             "kCGWindowBounds": ["Width": 20.0, "Height": 20.0]],                               // a tiny helper window
            ["kCGWindowOwnerPID": 102, "kCGWindowLayer": 0, "kCGWindowNumber": 4],            // its front window
            ["kCGWindowOwnerPID": 102, "kCGWindowLayer": 0, "kCGWindowNumber": 5],            // a covered (incognito?) one
        ]
        XCTAssertEqual(TraceWindowPick.frontWindowID(in: entries, pid: 102), 4)
        XCTAssertNil(TraceWindowPick.frontWindowID(in: entries, pid: 7))
    }

    // MARK: Pause, lock, secure input, idle

    func testPausedNothingIsCapturedNotEvenATitle() async {
        let recorder = makeRecorder()
        await recorder.start()
        workspace.front = Self.editor
        await run(recorder, for: 20)
        await settle()
        let readsBefore = titles.reads
        let capturesBefore = capture.captures
        await recorder.pause(.untilResumed)
        XCTAssertEqual(recorder.state, .paused)
        workspace.front = Self.chrome
        await run(recorder, for: 600)
        await settle()
        XCTAssertEqual(titles.reads, readsBefore)
        XCTAssertEqual(tabs.reads, 0)
        XCTAssertEqual(capture.captures, capturesBefore)
        let posted = backend.spans
        XCTAssertEqual(posted.count, 1, "only the span before the pause, closed at the pause")
        await recorder.resume()
        await run(recorder, for: 30)
        XCTAssertGreaterThan(tabs.reads, 0)
    }

    func testAnHourPauseEndsByItself() async {
        let recorder = makeRecorder()
        await recorder.start()
        await recorder.pause(.hour)
        workspace.front = Self.editor
        await run(recorder, for: 600)
        XCTAssertEqual(titles.reads, 0)
        backend.answer.settings.pausedSince = nil
        backend.answer.settings.pausedUntil = nil
        advance(3600)
        await run(recorder, for: 20)
        XCTAssertGreaterThan(titles.reads, 0)
        XCTAssertEqual(recorder.state, .recording)
    }

    func testTheLockedScreenAndAPasswordFieldRecordNothing() async {
        let recorder = makeRecorder()
        await recorder.start()
        workspace.front = Self.editor
        idle.locked = true
        await run(recorder, for: 60)
        idle.locked = false
        idle.secure = true
        await run(recorder, for: 60)
        await recorder.flush(force: true)
        XCTAssertTrue(backend.spans.isEmpty)
        XCTAssertEqual(titles.reads, 0)
        XCTAssertEqual(capture.captures, 0)
    }

    func testIdleEndsTheSpanWhereInputStoppedAndTakesNoScreenshot() async throws {
        let recorder = makeRecorder()
        await recorder.start()
        workspace.front = Self.editor
        await run(recorder, for: 300)
        await settle()
        let capturesBefore = capture.captures
        idle.idleFor = 200
        await run(recorder, for: 600)
        await recorder.flush(force: true)
        await settle()
        XCTAssertEqual(capture.captures, capturesBefore)
        let span = try XCTUnwrap(backend.spans.first)
        let end = try XCTUnwrap(TraceClock.parse(span.end))
        let start = try XCTUnwrap(TraceClock.parse(span.start))
        XCTAssertLessThanOrEqual(end.timeIntervalSince(start), 105, "the idle stretch is not counted")
        XCTAssertGreaterThanOrEqual(end.timeIntervalSince(start), 95)
    }

    // MARK: Screenshots

    /// Owner 2026-10-28, "a low screenshot frequency": on change at most every five minutes, every fifteen otherwise.
    func testScreenshotsComeOnChangeAtMostEveryFiveMinutesAndEveryFifteenOtherwise() async {
        let recorder = makeRecorder()
        await recorder.start()
        workspace.front = Self.editor
        await recorder.tick()
        await settle()
        XCTAssertEqual(capture.captures, 1, "a new span gets a frame")
        // A burst of switches inside five minutes costs nothing more.
        for i in 0..<30 {
            advance(5)
            titles.title = "window \(i)"
            await recorder.tick()
        }
        await settle()
        XCTAssertEqual(capture.captures, 1)
        titles.title = "steady"
        advance(151)
        await recorder.tick()
        await settle()
        XCTAssertEqual(capture.captures, 2, "the span that had none gets one once five minutes passed")
        await run(recorder, for: 890)
        await settle()
        XCTAssertEqual(capture.captures, 2)
        await run(recorder, for: 20)
        await settle()
        XCTAssertEqual(capture.captures, 3)
        XCTAssertEqual(backend.frames.count, 3)
        XCTAssertEqual(backend.frames.first?.text, "recognized words")
        XCTAssertEqual(backend.frames.first?.spanId.isEmpty, false)
    }

    /// The Screen Recording preflight is a TCC lookup (~7 ms on the main actor, measured 2026-10-28): asked only when a
    /// frame is due, never on every tick.
    func testTheScreenRecordingPreflightIsAskedOnlyWhenAFrameIsDue() async {
        let recorder = makeRecorder()
        await recorder.start()
        workspace.front = Self.editor
        await run(recorder, for: 1200)
        await settle()
        XCTAssertEqual(capture.accessChecks, capture.captures)
        XCTAssertLessThanOrEqual(capture.accessChecks, 3, "20 minutes of five-second ticks")
    }

    /// Every connected screen only under the sheet that says so (consent 2); the older sheet keeps the front window.
    func testEveryScreenIsCapturedOnlyAfterTheNewerSheet() async {
        let older = makeRecorder { $0.consentVersion = 1 }
        backend.answer.allScreensConsent = 2
        await older.start()
        XCTAssertTrue(older.offersAllScreens)
        workspace.front = Self.editor
        await older.tick()
        await settle()
        XCTAssertEqual([capture.captures, capture.screenCaptures], [1, 0])

        let newer = makeRecorder { $0.consentVersion = 2 }
        backend.answer.allScreensConsent = 2
        await newer.start()
        XCTAssertFalse(newer.offersAllScreens)
        workspace.front = Self.editor
        await newer.tick()
        await settle()
        XCTAssertEqual([capture.captures, capture.screenCaptures], [0, 1])
        XCTAssertEqual(backend.frames.map(\.display), [1, 2])
        XCTAssertEqual(backend.frames.map(\.displays), [2, 2])
        XCTAssertEqual(Set(backend.frames.map(\.at)).count, 1, "one moment, one frame per screen")
        let asked = try? XCTUnwrap(capture.shownAsked.first)
        XCTAssertEqual(asked?.keepFront, false, "an editor in front: no browser window to keep")
        let shown = asked?.shown ?? { _ in true }
        XCTAssertTrue(shown("com.example.Editor"))
        XCTAssertFalse(shown("com.google.Chrome"), "a browser appears only through its vetted front window")
        XCTAssertFalse(shown("com.example.Chat"), "a chat app whose titles stay off")
        XCTAssertFalse(shown("com.example.Vault"), "an app never recorded")
        XCTAssertFalse(shown("com.apple.notificationcenterui"), "banners show other apps' words")
        XCTAssertFalse(shown("com.rorosaga.cicada.test"), "Cicada itself")
    }

    /// Review of #508, must-fix 6: the sheet this app showed is what is sent, never the version the backend serves.
    func testTurnOnSendsTheSheetThisAppShowed() async throws {
        let recorder = makeRecorder { $0.enabled = false }
        backend.answer = TraceSettingsAnswer(settings: backend.answer.settings, status: backend.answer.status,
                                             policy: backend.answer.policy, consentVersion: 7)
        await recorder.start()
        try await recorder.turnOn()
        XCTAssertEqual(backend.displayedVersions, [TraceRecorder.sheetVersion])
    }

    /// Review of #508, B1: the every-screen picture is an allow-list — unknown, new and helper windows are not drawn.
    func testOnlyListedWindowsOfAppsThatMayBeDescribedAreDrawn() async {
        func w(_ id: UInt32, _ bundle: String, pid: Int32, layer: Int = 0, here: Bool = true) -> TraceScreenWindow {
            TraceScreenWindow(id: id, bundleId: bundle, pid: pid, layer: layer, onScreen: true, onThisScreen: here)
        }
        let recorder = makeRecorder()
        await recorder.start()   // the backend's lists: chat apps keep no titles
        let shown = TraceScreens.shown(recorder.policy) { _ in false }
        let regular: (Int32) -> Bool = { $0 < 100 }   // fixtures: pids under 100 are Dock apps
        let windows = [
            w(1, "com.example.Editor", pid: 10),
            w(2, "com.google.Chrome", pid: 11),                         // a browser window, not the vetted one
            w(3, "com.google.Chrome", pid: 11),                         // the vetted front window
            w(4, "com.apple.quicklook.QuickLookUIService", pid: 500),  // a Mail attachment's preview
            w(5, "com.apple.appkit.xpc.openAndSavePanelService", pid: 501),
            w(6, "com.example.Helper", pid: 502),                       // an unknown helper, not a Dock app
            w(7, "com.example.Chat", pid: 12),                          // a chat app, titles off
            w(8, "com.example.Editor", pid: 10, layer: 3),              // a floating panel
            w(9, "com.example.Editor", pid: 10, here: false),           // on another screen
            w(10, "", pid: 13),
        ]
        let allowed = TraceScreenPick.allowed(windows, frontWindowID: 3, frontPid: 11, shown: shown, regular: regular)
        XCTAssertEqual(allowed, [1, 3])
        XCTAssertEqual(TraceScreenPick.allowed(windows, frontWindowID: nil, frontPid: 11, shown: shown,
                                               regular: regular), [1])
    }

    func testAnOlderBackendNeverTurnsEveryScreenOn() async {
        let recorder = makeRecorder { $0.consentVersion = 9 }
        await recorder.start()   // no all_screens_consent in the answer
        XCTAssertFalse(recorder.capturesAllScreens)
        XCTAssertFalse(recorder.offersAllScreens)
    }

    func testScreenshotsOffOrNoScreenRecordingTakesNone() async {
        let off = makeRecorder { $0.screenshots = false }
        await off.start()
        workspace.front = Self.editor
        await run(off, for: 600)
        await settle()
        XCTAssertEqual(capture.captures, 0)
        let noAccess = makeRecorder()
        capture.access = false
        await noAccess.start()
        workspace.front = Self.editor
        await run(noAccess, for: 600)
        await settle()
        XCTAssertEqual(capture.captures, 0)
    }

    // MARK: Memory only, forget, wipe

    func testWithTheBackendAwaySpansWaitInMemoryCappedNeverOnDisk() async {
        let recorder = makeRecorder()
        await recorder.start()
        backend.failSync = true
        for i in 0..<(TraceRecorder.pendingCap + 40) {
            workspace.front = TraceFrontApp(bundleId: "com.example.App\(i % 2)", name: "App", pid: 5)
            titles.title = "t\(i)"
            await recorder.tick()
            advance(5)
        }
        XCTAssertLessThanOrEqual(recorder.pendingCount, TraceRecorder.pendingCap)
        backend.failSync = false
        await recorder.flush(force: true)
        XCTAssertEqual(recorder.pendingCount, 0)
        XCTAssertLessThanOrEqual(backend.spans.count, TraceRecorder.pendingCap)
    }

    func testForgetDropsWhatWaitsHereAndAsksTheBackendToo() async {
        let recorder = makeRecorder()
        await recorder.start()
        backend.failSync = true
        workspace.front = Self.editor
        await run(recorder, for: 30)
        workspace.front = Self.chrome
        await run(recorder, for: 30)
        XCTAssertGreaterThan(recorder.pendingCount, 0)
        try? await recorder.forget(minutes: 15)
        XCTAssertEqual(recorder.pendingCount, 0)
        XCTAssertTrue(backend.calls.contains("forget"))
    }

    func testWipeTurnsTracesOff() async throws {
        let recorder = makeRecorder()
        await recorder.start()
        try await recorder.wipe()
        XCTAssertEqual(recorder.state, .off)
        workspace.front = Self.editor
        await run(recorder, for: 60)
        XCTAssertEqual(titles.reads, 0)
    }

    // MARK: The policy

    func testTheURLKeepsSchemeHostPathAndOnlyContentKeys() {
        var lists = TracePolicyLists()
        lists.contentKeys = ["youtube.com": ["v"]]
        let policy = TracePolicy(settings: TraceSettings(), lists: lists, ownBundleId: nil)
        XCTAssertEqual(policy.cleanURL("https://www.youtube.com/watch?v=abc&list=x#t=1")?.url,
                       "https://www.youtube.com/watch?v=abc")
        XCTAssertEqual(policy.cleanURL("https://user:pw@example.com:8443/reset?token=s")?.url,
                       "https://example.com/reset")
        XCTAssertNil(policy.cleanURL("chrome://settings"))
        XCTAssertNil(policy.cleanURL("file:///Users/x"))
    }

    func testTheCadenceNumbersAreTheOnesTheDocsName() {
        let cadence = TraceFrameCadence()
        XCTAssertEqual(cadence.minGap, 300)
        XCTAssertEqual(cadence.steadyInterval, 900)
        XCTAssertEqual(cadence.maxSide, 1280)
        XCTAssertEqual(TraceRecorder.idleThreshold, 120)
    }
}

/// G218 — the no-network guarantee, read from the source: the traces code path builds no request of its own and never
/// writes to disk; its one way out is `APIClient`'s gated `trace…` methods to This Mac's backend, and the offline
/// outbox never holds a trace.
final class TraceNoNetworkTests: XCTestCase {
    static var tracesDir: URL {
        URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("Sources/CicadaApp/Services/Traces")
    }

    func sources() throws -> [(String, String)] {
        let files = try FileManager.default.contentsOfDirectory(at: Self.tracesDir, includingPropertiesForKeys: nil)
            .filter { $0.pathExtension == "swift" }
        XCTAssertGreaterThanOrEqual(files.count, 5)
        return try files.map { ($0.lastPathComponent, try String(contentsOf: $0, encoding: .utf8)) }
    }

    func testTheTracesPathHasNoURLSessionNoSocketAndNoWebAddress() throws {
        let forbidden = ["URLSession", "URLRequest", "NWConnection", "NWPathMonitor", "import Network", "CFStream",
                         "http://", "https://", "WKWebView", "dataTask", "Socket("]
        for (name, text) in try sources() {
            for word in forbidden {
                XCTAssertFalse(text.contains(word), "\(name) contains \(word)")
            }
        }
    }

    func testTheTracesPathWritesNothingToDisk() throws {
        let forbidden = [".write(to", "createFile(", "FileHandle(forWriting", "UserDefaults", "@AppStorage",
                         "NSKeyedArchiver", "fopen("]
        for (name, text) in try sources() {
            for word in forbidden {
                XCTAssertFalse(text.contains(word), "\(name) contains \(word)")
            }
        }
    }

    func testNoPromptingPermissionCallAnywhereOnThePath() throws {
        let prompting = ["CGRequestScreenCaptureAccess", "AXIsProcessTrustedWithOptions", "kAXTrustedCheckOptionPrompt"]
        for (name, text) in try sources() {
            for word in prompting {
                XCTAssertFalse(text.contains(word), "\(name) contains \(word)")
            }
        }
    }

    func testEveryAPIClientTraceCallIsGatedToThisMac() throws {
        let client = Self.tracesDir.deletingLastPathComponent().appendingPathComponent("APIClient.swift")
        let text = try String(contentsOf: client, encoding: .utf8)
        let section = try XCTUnwrap(text.range(of: "// MARK: - Activity traces (G218)"))
        let end = try XCTUnwrap(text.range(of: "// MARK: - Messages (G179)"))
        let body = String(text[section.upperBound..<end.lowerBound])
        let funcs = body.components(separatedBy: "    func trace").dropFirst()
        XCTAssertEqual(funcs.count, 19)   // 13, plus the page's six (2026-10-28)
        for f in funcs { XCTAssertTrue(f.contains("try traceGate()"), "ungated: func trace\(f.prefix(30))") }
    }

    func testTheOfflineOutboxNeverHoldsATrace() {
        for path in ["/sources/traces/sync", "/sources/traces/frames", "/sources/traces/settings"] {
            XCTAssertFalse(ReaderOutbox.queues(path), path)
        }
    }
}
