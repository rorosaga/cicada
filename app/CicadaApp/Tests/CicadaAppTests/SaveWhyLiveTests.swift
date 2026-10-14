import AppKit
import XCTest
@testable import CicadaApp

/// G191 live (2026-10-14) — what the measurement on a real Mac found, each as a test: the panel came 18 s after the
/// save (budget 2 s), Safari's saves were never seen, "Something else…" opened with nobody choosing it, and the panel's
/// screen was `NSScreen.main`. Synthetic files in a scratch folder and placeholder sites only.
@MainActor
final class SaveWhyLiveTests: XCTestCase {
    private var dir: URL!
    private var defaults: UserDefaults!
    private var store: Store!

    override func setUp() async throws {
        dir = URL(fileURLWithPath: NSTemporaryDirectory()).appendingPathComponent("cicada-live-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defaults = UserDefaults(suiteName: "cicada.savewhy.live.\(UUID().uuidString)")
        store = Store()
    }

    override func tearDown() async throws {
        BookmarkSyncSignal.observer = nil
        BookmarkSyncSignal.early = nil
        try? FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: dir.path)
        try? FileManager.default.removeItem(at: dir)
    }

    // MARK: - Helpers

    private func eventually(_ what: String, timeout: Duration = .seconds(5), _ condition: () -> Bool) async throws {
        let deadline = ContinuousClock.now + timeout
        while ContinuousClock.now < deadline {
            if condition() { return }
            try await Task.sleep(for: .milliseconds(10))
        }
        XCTFail("timed out waiting for: \(what)")
    }

    /// A save the way Chrome makes one: a temp file beside the target, renamed over it.
    private func replaceBeside(_ target: URL, with text: String) throws {
        let tmp = target.deletingLastPathComponent().appendingPathComponent(".\(target.lastPathComponent).tmp")
        try text.write(to: tmp, atomically: false, encoding: .utf8)
        _ = try FileManager.default.replaceItemAt(target, withItemAt: tmp)
    }

    /// A save swapped in from a temp folder elsewhere — a rename the target's folder never lists as an entry change.
    private func replaceFromElsewhere(_ target: URL, with text: String) throws {
        let elsewhere = dir.deletingLastPathComponent().appendingPathComponent("cicada-live-tmp-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: elsewhere, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: elsewhere) }
        let tmp = elsewhere.appendingPathComponent(target.lastPathComponent)
        try text.write(to: tmp, atomically: false, encoding: .utf8)
        _ = try FileManager.default.replaceItemAt(target, withItemAt: tmp)
    }

    /// A save written into the same file, no rename at all.
    private func rewriteInPlace(_ target: URL, with text: String) throws {
        let handle = try FileHandle(forWritingTo: target)
        try handle.truncate(atOffset: 0)
        try handle.write(contentsOf: Data(text.utf8))
        try handle.close()
    }

    private func safariWatcher(minimumInterval: Duration = .milliseconds(1),
                               accessRecheck: Duration = .seconds(60),
                               _ onSync: @escaping @MainActor (Bool) async throws -> Void) -> BrowserWatcher {
        BrowserWatcher(defaults: defaults, channels: [("safari-bookmarks", .safariBookmarks)],
                       paths: { [dir] _ in [dir!.appendingPathComponent("Bookmarks.plist")] },
                       minimumInterval: minimumInterval, accessRecheck: accessRecheck,
                       performSync: { _, _ in try await onSync(BookmarkSyncSignal.live); return "ok" })
    }

    private var plist: URL { dir.appendingPathComponent("Bookmarks.plist") }

    // MARK: - Safari works on every change

    /// The measured Safari failure: the plist changed and nothing synced. Every way a save can land — swapped in from
    /// a temp folder elsewhere (twice), renamed from beside it, written in place — is seen, each as a live change.
    func testEverySafariSaveIsSeenHoweverTheFileIsReplaced() async throws {
        defaults.set(true, forKey: BrowserWatchPolicy.enabledKey("safari-bookmarks"))
        try "seed".write(to: plist, atomically: false, encoding: .utf8)
        var syncs: [Bool] = []
        let watcher = safariWatcher { syncs.append($0) }
        watcher.start(store: store)
        try await eventually("the catch-up sync") { syncs == [false] }

        let saves: [(String, () throws -> Void)] = [
            ("swapped in from elsewhere", { try self.replaceFromElsewhere(self.plist, with: "save one, longer") }),
            ("swapped in from elsewhere again", { try self.replaceFromElsewhere(self.plist, with: "save two, longer still") }),
            ("renamed from beside it", { try self.replaceBeside(self.plist, with: "save three") }),
            ("written in place", { try self.rewriteInPlace(self.plist, with: "save four, in place") }),
        ]
        for (i, save) in saves.enumerated() {
            try save.1()
            try await eventually("sync after a save \(save.0)") { syncs.count == i + 2 }
            XCTAssertEqual(syncs.last, true, "a save the watch saw is live: \(save.0)")
        }
        watcher.stop()
    }

    /// Armed while macOS refused the folder (Safari before Full Disk Access): once it can be read, the stream is armed
    /// again and caught up (not live — no question about what was already there), and the next save is live.
    func testAWatchArmedWhileRefusedIsArmedAgainOnceReadable() async throws {
        defaults.set(true, forKey: BrowserWatchPolicy.enabledKey("safari-bookmarks"))
        try "seed".write(to: plist, atomically: false, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o000], ofItemAtPath: dir.path)
        var syncs: [Bool] = []
        let watcher = safariWatcher { syncs.append($0) }
        watcher.start(store: store)
        try await Task.sleep(for: .milliseconds(150))
        XCTAssertEqual(watcher.state(for: "safari-bookmarks"), .blocked)
        XCTAssertTrue(syncs.isEmpty)
        XCTAssertEqual(watcher.refreshAccess(), [], "still refused: nothing re-armed")

        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: dir.path)
        XCTAssertEqual(watcher.refreshAccess(), ["safari-bookmarks"])
        try await eventually("the catch-up after access") { syncs == [false] }
        XCTAssertEqual(watcher.refreshAccess(), [], "armed readable now: never re-armed twice")

        try replaceFromElsewhere(plist, with: "the first save after access")
        try await eventually("the save after access") { syncs == [false, true] }
        watcher.stop()
    }

    /// The recheck finds the grant without the app coming to the front.
    func testTheRecheckFindsTheGrantOnItsOwn() async throws {
        defaults.set(true, forKey: BrowserWatchPolicy.enabledKey("safari-bookmarks"))
        try "seed".write(to: plist, atomically: false, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o000], ofItemAtPath: dir.path)
        var syncs: [Bool] = []
        let watcher = safariWatcher(accessRecheck: .milliseconds(100)) { syncs.append($0) }
        watcher.start(store: store)
        try await Task.sleep(for: .milliseconds(150))
        XCTAssertTrue(syncs.isEmpty)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: dir.path)
        try await eventually("the recheck's catch-up") { syncs == [false] }
        watcher.stop()
    }

    /// A save made while a sync runs is read right after it — before, it waited for the next save.
    func testASaveDuringASyncIsReadAfterIt() async throws {
        defaults.set(true, forKey: BrowserWatchPolicy.enabledKey("safari-bookmarks"))
        try "seed".write(to: plist, atomically: false, encoding: .utf8)
        var syncs: [Bool] = []
        var slow = false
        let watcher = safariWatcher { live in
            syncs.append(live)
            if slow { try await Task.sleep(for: .milliseconds(800)) }
        }
        watcher.start(store: store)
        try await eventually("the catch-up sync") { syncs.count == 1 }
        slow = true
        try replaceBeside(plist, with: "first save")
        try await eventually("the first live sync to start") { syncs.count == 2 }
        slow = false
        try replaceBeside(plist, with: "second save, during the first sync")
        try await eventually("the owed sync", timeout: .seconds(3)) { syncs.count == 3 }
        XCTAssertEqual(syncs, [false, true, true])
        watcher.stop()
    }

    func testTheStreamMatchesTheFileByNameWhateverThePathSpelling() {
        let names: Set<String> = ["Bookmarks.plist"]
        XCTAssertTrue(BrowserFileEvents.matches(["/private/var/folders/x/Bookmarks.plist"], names: names))
        XCTAssertFalse(BrowserFileEvents.matches(["/private/var/folders/x/.Bookmarks.plist.tmp"], names: names),
                       "a temp file's own writes are not the save")
        XCTAssertFalse(BrowserFileEvents.matches(["/x/History.db"], names: names))
    }

    // MARK: - Speed: the save to the panel within the budget

    /// The measured case was 18 s. This drives the real watcher (production settle and stream latency), the real
    /// center and a backend that takes as long as the measured one to save (3 s here, 6-7 s measured): the panel must
    /// be on screen within `SaveWhyPolicy.showBudget` of the browser writing its file, before the sync has finished,
    /// and an answer given before the link is saved must land once it is.
    func testTheQuestionShowsWithinTwoSecondsOfTheSaveWithoutWaitingForTheSync() async throws {
        let bookmarks = dir.appendingPathComponent("Bookmarks")
        try "{\"seed\": 1}".write(to: bookmarks, atomically: false, encoding: .utf8)
        defaults.set(true, forKey: BrowserWatchPolicy.enabledKey("chrome-bookmarks"))
        let clock = Date()
        let prefs = SaveWhyPrefs(defaults: defaults)
        prefs.enabled = true
        let api = LiveFakeAPI(now: clock)
        let presenter = TimingPresenter()
        let center = SaveWhyCenter(prefs: prefs, api: api, presenter: presenter, now: { clock })
        center.start()
        await center.refreshOptions()

        var ingested = false
        var syncs = 0
        let watcher = BrowserWatcher(
            defaults: defaults, channels: [("chrome-bookmarks", .chromeBookmarks)],
            paths: { _ in [bookmarks] }, minimumInterval: .milliseconds(1),
            performSync: { _, _ in
                // What `syncChannel` does: read, look early, then the slow sync, then its result.
                syncs += 1
                let data = try Data(contentsOf: bookmarks)
                let looked = await BookmarkSyncSignal.lookEarly(.chrome(data))
                if BookmarkSyncSignal.live { try await Task.sleep(for: .seconds(3)) }
                if BookmarkSyncSignal.live { await api.markSaved() }
                ingested = BookmarkSyncSignal.live
                BookmarkSyncSignal.post(api.synced, lookedEarly: looked)
                return "ok"
            })
        watcher.start(store: store)
        try await eventually("the catch-up sync") { syncs == 1 }
        XCTAssertEqual(presenter.shownAt, nil, "a catch-up never asks")

        try replaceBeside(bookmarks, with: "{\"seed\": 1, \"new\": \"https://alpha.example/notes\"}")
        let saved = ContinuousClock.now
        try await eventually("the panel", timeout: .seconds(4)) { presenter.shownAt != nil }
        let latency = presenter.shownAt! - saved
        print("G191 live: save → panel \(latency)")
        XCTAssertLessThanOrEqual(latency, .seconds(SaveWhyPolicy.showBudget), "save → panel took \(latency)")
        XCTAssertFalse(ingested, "the panel did not wait for the sync")
        XCTAssertEqual(center.state?.item.url, "https://alpha.example/notes")

        // Answered before the link is saved: the backend's 404 holds it, and the sync's landing sends it.
        center.send(.tapReason("design"))
        center.send(.escape)
        await center.settle()
        XCTAssertEqual(center.heldCount, 1, "a 404 before the sync lands is early, not refused")
        try await eventually("the sync to land and the answer to go", timeout: .seconds(5)) {
            ingested && center.heldCount == 0
        }
        let posts = await api.posts
        XCTAssertEqual(posts, ["https://alpha.example/notes"])
        XCTAssertEqual(presenter.shows, 1, "the sync's own result never asks a second time")
        watcher.stop()
    }

    /// The budget's parts: the settle and stream latency leave room for the read, the look and the show.
    func testTheWatchDelayLeavesRoomInTheBudget() {
        XCTAssertLessThanOrEqual(BrowserWatchPolicy.watchDelay, SaveWhyPolicy.showBudget / 4)
        XCTAssertLessThan(SaveWhyPolicy.armDelay, SaveWhyPolicy.askTimeout)
    }

    /// The early look stands aside — no request — when the switch is off, and lets the sync decide when the backend
    /// does not answer (an older one without the route).
    func testTheEarlyLookStandsAsideWhenOffOrUnanswered() async {
        let prefs = SaveWhyPrefs(defaults: defaults)
        let api = LiveFakeAPI(now: Date())
        let center = SaveWhyCenter(prefs: prefs, api: api, presenter: TimingPresenter())
        let off = await center.lookEarly(.chrome(Data()))
        XCTAssertFalse(off)
        let looks = await api.looks
        XCTAssertEqual(looks, 0, "off: not even asked")
        prefs.enabled = true
        await api.refuseLooks()
        let unanswered = await center.lookEarly(.chrome(Data()))
        XCTAssertFalse(unanswered, "no answer: the sync's own result decides")
    }

    // MARK: - No self-opening field

    /// Only a tap on "Something else…" opens the field. Every other event, in any order, never does.
    func testNothingButItsOwnTapOpensSomethingElse() {
        let item = FreshBookmark(url: "https://alpha.example/a", channel: "chrome-bookmarks")
        let others: [SaveWhyPanelState.Event] = [.tapReason("design"), .tapProject("alpha-project"),
                                                 .draftChanged("x"), .submitText, .lingerElapsed, .timeout, .escape,
                                                 .clickOutside, .dontAskForSite]
        for a in others { for b in others { for c in others {
            var state = SaveWhyPanelState(item: item, order: ["design"])
            var effects: [SaveWhyPanelState.Effect] = []
            for event in [a, b, c] { effects += state.send(event) }
            XCTAssertNotEqual(state.phase, .writing, "\([a, b, c])")
            XCTAssertFalse(effects.contains(.focusText), "\([a, b, c])")
        } } }
        var state = SaveWhyPanelState(item: item, order: ["design"])
        XCTAssertEqual(state.send(.tapOther), [.startTimer(SaveWhyPolicy.writingTimeout), .focusText])
        XCTAssertEqual(state.phase, .writing)
    }

    /// A click that lands on the panel as it appears was aimed at the page beneath: it chooses nothing and closes
    /// nothing. After `armDelay`, the same click is the person's.
    func testAClickAsThePanelAppearsChoosesNothing() async {
        let prefs = SaveWhyPrefs(defaults: defaults)
        prefs.enabled = true
        var uptime: TimeInterval = 100
        let center = SaveWhyCenter(prefs: prefs, api: LiveFakeAPI(now: Date()), presenter: TimingPresenter(),
                                   uptime: { uptime })
        await center.refreshOptions()
        var result = BookmarkSyncResult(new: 1, skipped: 0, sources: [])
        result.fresh = [FreshBookmark(url: "https://alpha.example/a", channel: "chrome-bookmarks")]
        result.freshTotal = 1
        await center.noticed(result, live: true)
        XCTAssertTrue(center.isShowing)

        uptime += SaveWhyPolicy.armDelay / 2
        for event: SaveWhyPanelState.Event in [.tapOther, .tapReason("design"), .dontAskForSite, .clickOutside] {
            center.input(event)
            XCTAssertEqual(center.lastIgnored, event)
        }
        XCTAssertEqual(center.state?.phase, .asking)
        XCTAssertTrue(center.isShowing)

        uptime += SaveWhyPolicy.armDelay
        center.input(.tapOther)
        XCTAssertEqual(center.state?.phase, .writing, "a deliberate click opens it")
    }

    /// The panel takes the keyboard only after a click inside it — so no activation or stray key can type into it.
    func testThePanelTakesTheKeyboardOnlyAfterAClickInside() throws {
        let panel = SaveWhyNSPanel(contentRect: CGRect(x: 0, y: 0, width: 100, height: 100),
                                   styleMask: [.nonactivatingPanel, .borderless], backing: .buffered, defer: true)
        XCTAssertFalse(panel.canBecomeKey)
        XCTAssertFalse(SaveWhyNSPanel.isPersonsClick(.keyDown))
        XCTAssertFalse(SaveWhyNSPanel.isPersonsClick(.mouseMoved))
        let key = try XCTUnwrap(NSEvent.keyEvent(with: .keyDown, location: .zero, modifierFlags: [], timestamp: 0,
                                                 windowNumber: panel.windowNumber, context: nil, characters: "\r",
                                                 charactersIgnoringModifiers: "\r", isARepeat: false, keyCode: 36))
        panel.sendEvent(key)
        XCTAssertFalse(panel.canBecomeKey, "a Return is not a click")
        let click = try XCTUnwrap(NSEvent.mouseEvent(with: .leftMouseDown, location: CGPoint(x: 10, y: 10),
                                                     modifierFlags: [], timestamp: 0, windowNumber: panel.windowNumber,
                                                     context: nil, eventNumber: 0, clickCount: 1, pressure: 1))
        panel.sendEvent(click)
        XCTAssertTrue(panel.canBecomeKey)
    }

    // MARK: - The screen

    /// Chrome on an external display: the panel goes there, not to the built-in screen with the notch — and on the
    /// built-in screen when the browser is there.
    func testThePanelOpensOnTheScreenOfTheBrowserWindow() {
        let builtIn = CGRect(x: 0, y: 0, width: 1512, height: 982)
        let external = CGRect(x: 1512, y: -200, width: 2560, height: 1440)
        let screens = [builtIn, external]
        let chromeOnExternal = CGRect(x: 1600, y: 100, width: 1400, height: 900)
        XCTAssertEqual(SaveWhyScreen.choose(screens: screens, candidates: [chromeOnExternal, nil], fallback: 0), 1)
        XCTAssertEqual(SaveWhyScreen.choose(screens: screens, candidates: [CGRect(x: 100, y: 100, width: 800, height: 600)],
                                            fallback: 1), 0)
        // Straddling: the screen with most of it.
        XCTAssertEqual(SaveWhyScreen.index(of: CGRect(x: 1312, y: 100, width: 1000, height: 600), in: screens), 1)
        // The browser's window unknown: the front app's; neither: the fallback (`NSScreen.main`).
        XCTAssertEqual(SaveWhyScreen.choose(screens: screens, candidates: [nil, chromeOnExternal], fallback: 0), 1)
        XCTAssertEqual(SaveWhyScreen.choose(screens: screens, candidates: [nil, nil], fallback: 0), 0)
        XCTAssertEqual(SaveWhyScreen.choose(screens: screens, candidates: [CGRect(x: -5000, y: 0, width: 10, height: 10)],
                                            fallback: 1), 1, "off every screen: the fallback")
    }

    /// The window list counts y down from the primary screen's top; AppKit counts up from its bottom.
    func testTheWindowListFrameIsFlippedToAppKit() {
        let frame = SaveWhyScreen.appKitFrame(fromWindowList: CGRect(x: 1600, y: 25, width: 1400, height: 900),
                                              primaryHeight: 982)
        XCTAssertEqual(frame, CGRect(x: 1600, y: 57, width: 1400, height: 900))
    }

    /// The notch is the chosen screen's own: a notched built-in keeps its shape, a plain external grows a sliver.
    func testTheNotchFollowsTheChosenScreen() {
        let builtIn = CGRect(x: 0, y: 0, width: 1512, height: 982)
        let notch = SaveWhyNotch.notchRect(screen: builtIn, topLeft: CGRect(x: 0, y: 950, width: 660, height: 32),
                                           topRight: CGRect(x: 852, y: 950, width: 660, height: 32), topInset: 32)
        XCTAssertEqual(notch, CGRect(x: 660, y: 950, width: 192, height: 32))
        let external = CGRect(x: 1512, y: -200, width: 2560, height: 1440)
        XCTAssertNil(SaveWhyNotch.notchRect(screen: external, topLeft: nil, topRight: nil, topInset: 0))
        let frame = SaveWhyNotch.frame(screen: external, notch: nil, size: CGSize(width: 460, height: 200))
        XCTAssertEqual(frame.midX, external.midX, accuracy: 1)
        XCTAssertEqual(frame.maxY, external.maxY)
    }
}

// MARK: - Fakes

@MainActor
private final class TimingPresenter: SaveWhyPresenting {
    var shownAt: ContinuousClock.Instant?
    var shows = 0
    func show(_ center: SaveWhyCenter) { shownAt = ContinuousClock.now; shows += 1 }
    func hide() {}
    func focusText() {}
}

/// A backend that parses in 150 ms (the early look), refuses an answer with 404 until the sync saved its link, and
/// answers options at once.
private actor LiveFakeAPI: SavedWhyAPI {
    let now: Date
    private(set) var looks = 0
    private(set) var posts: [String] = []
    private var refusing = false
    nonisolated let synced: BookmarkSyncResult

    init(now: Date) {
        self.now = now
        var r = BookmarkSyncResult(new: 1, skipped: 1, sources: [
            BookmarkSyncSourceSummary(origin: "chrome-bookmark", channel: "chrome-bookmarks", found: 2, new: 1,
                                      skipped: 1, firstSync: false),
        ])
        r.fresh = [FreshBookmark(url: "https://alpha.example/notes", title: "Alpha notes", origin: "chrome-bookmark",
                                 channel: "chrome-bookmarks", episodeId: "ep_x",
                                 addedAt: ISO8601DateFormatter().string(from: now.addingTimeInterval(-3)))]
        r.freshTotal = 1
        synced = r
    }

    func refuseLooks() { refusing = true }

    func freshBookmarks(_ bytes: BookmarkBytes) async throws -> BookmarkSyncResult {
        looks += 1
        if refusing { throw APIError.httpError(404, "Not Found") }
        try await Task.sleep(for: .milliseconds(150))
        var r = synced
        r.fresh = r.fresh.map { var f = $0; f.episodeId = ""; return f }
        return r
    }

    func savedWhyOptions() async throws -> SavedWhyOptions {
        SavedWhyOptions(reasons: [.init(key: "design", label: "The design")], projects: [], maxText: 500)
    }

    private var saved = false
    func markSaved() { saved = true }

    func saveWhy(url: String, answer: SavedWhyAnswer, at: Date) async throws {
        guard saved else { throw APIError.httpError(404, "That link isn't saved yet") }
        posts.append(url)
    }
}
