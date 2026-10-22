import XCTest
@testable import CicadaApp

/// G191 v4 — bookmarks, round 4 (owner 2026-10-15): a few basic reasons and no project chips; "no longer in Chrome"
/// shown where a bookmark shows; the file write → panel path that waits on nothing but the browser's own file; and
/// Chrome's bookmark bubble as measured on the owner's Mac (448 × 224, layer 0). Synthetic files, synthetic window
/// lists and placeholder sites only — no real browser is read.
@MainActor
final class BookmarksV4Tests: XCTestCase {
    private var dirs: [URL] = []

    override func tearDown() async throws {
        BookmarkSyncSignal.observer = nil
        BookmarkSyncSignal.early = nil
        BookmarkSyncSignal.numberLook = nil
        BookmarkSyncSignal.offer = nil
        BookmarkSyncSignal.removed = nil
        BookmarkSyncSignal.eventAt = [:]
        for dir in dirs {
            try? FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: dir.path)
            try? FileManager.default.removeItem(at: dir)
        }
    }

    private func scratch() throws -> URL {
        let dir = URL(fileURLWithPath: NSTemporaryDirectory()).appendingPathComponent("cicada-v4-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        dirs.append(dir)
        return dir
    }

    private func eventually(_ what: String, timeout: Duration = .seconds(5), _ condition: () -> Bool) async throws {
        let deadline = ContinuousClock.now + timeout
        while ContinuousClock.now < deadline {
            if condition() { return }
            try await Task.sleep(for: .milliseconds(5))
        }
        XCTFail("timed out waiting for: \(what)")
    }

    // MARK: - A few basic reasons

    func testThePanelOffersFourBasicReasonsAndNoProject() {
        let basic = SavedWhyOptions.basic
        // The backend's `saved_why.REASONS`, keys and words alike (api/tests/test_bookmarks_v4.py pins its side).
        XCTAssertEqual(basic.reasons.map(\.key), ["design", "product", "read_later", "someday"])
        XCTAssertEqual(basic.reasons.map(\.label), ["The design", "The product", "To read later", "Useful someday"])
        XCTAssertTrue(basic.projects.isEmpty)
        XCTAssertEqual(Copy.SaveWhy.placeholder, "Something else…")
        XCTAssertEqual(SaveWhyPreview.sampleOptions, basic, "the preview shows what a real question shows")

        var s = SaveWhyPanelState(item: FreshBookmark(url: "https://alpha.example/a", channel: "chrome-bookmarks"),
                                  order: basic.reasons.map(\.key))
        _ = s.send(.tapReason("someday"))
        _ = s.send(.draftChanged("for a later idea"))
        XCTAssertEqual(s.selection, SavedWhyAnswer(reasons: ["someday"], project: nil, text: "for a later idea"),
                       "the panel never answers with a project")
    }

    func testAnOldAnswerStillShowsItsRetiredReasonAndItsProject() throws {
        let json: [String: Any] = [
            "mediaEntityId": "media-x", "url": "https://alpha.example/a", "title": "Alpha", "mediaType": "url",
            "savedAt": "2026-10-01T10:00:00Z", "origin": "chrome-bookmark",
            "savedWhy": ["reasons": ["technique", "design"], "labels": ["A technique to reuse", "The design"],
                         "project": "alpha-project", "text": "the sync trick", "at": "2026-10-10T10:00:00Z"],
        ]
        let item = try JSONDecoder().decode(MediaFeedItem.self, from: JSONSerialization.data(withJSONObject: json))
        let row = BookmarkHistory.row(item, projectNames: ["alpha-project": "Alpha project"])
        XCTAssertEqual(row.reasons, ["A technique to reuse", "The design", "For Alpha project"])
        XCTAssertEqual(Copy.Bookmarks.secondLine(row), "A technique to reuse · The design · For Alpha project · “the sync trick”")
    }

    // MARK: - No longer in the browser

    func testNoLongerInChromeReadsOnTheItemTheHistoryAndSources() throws {
        var utc = Calendar(identifier: .gregorian)
        utc.timeZone = TimeZone(identifier: "UTC")!
        let left = [BookmarkLeft(browser: "Chrome", channel: "chrome-bookmarks", since: "2026-10-15T08:00:00.123456+00:00")]
        // The locale is pinned, never the runner's: a Mac in Spain reads "15 Oct", and so does en_GB here.
        XCTAssertEqual(Copy.Bookmarks.noLongerIn(left, calendar: utc, locale: Locale(identifier: "en_US")),
                       "No longer in Chrome since Oct 15")
        XCTAssertEqual(Copy.Bookmarks.noLongerIn(left, calendar: utc, locale: Locale(identifier: "en_GB")),
                       "No longer in Chrome since 15 Oct")
        XCTAssertNil(Copy.Bookmarks.noLongerIn([]))

        let json: [String: Any] = [
            "mediaEntityId": "media-x", "url": "https://alpha.example/a", "title": "Alpha", "mediaType": "url",
            "savedAt": "2026-10-01T10:00:00Z", "origin": "chrome-bookmark",
            "leftBrowser": [["browser": "Chrome", "channel": "chrome-bookmarks", "since": "2026-10-15T08:00:00+00:00"]],
        ]
        let item = try JSONDecoder().decode(MediaFeedItem.self, from: JSONSerialization.data(withJSONObject: json))
        XCTAssertEqual(item.leftBrowser.map(\.browser), ["Chrome"])
        XCTAssertNotNil(BookmarkHistory.row(item).leftLine, "the ⌘B row is dimmed and marked")
        let roundTrip = try JSONDecoder().decode(MediaFeedItem.self, from: JSONEncoder().encode(item))
        XCTAssertEqual(roundTrip.leftBrowser, item.leftBrowser, "the Store's disk snapshot keeps the status")

        var present = json
        present["leftBrowser"] = nil
        let still = try JSONDecoder().decode(MediaFeedItem.self, from: JSONSerialization.data(withJSONObject: present))
        XCTAssertNil(BookmarkHistory.row(still).leftLine)

        let rowJSON: [String: Any] = ["kind": "media", "id": "media-x", "title": "Alpha", "day": "2026-10-01",
                                      "left": "2026-10-15T08:00:00+00:00"]
        let channelItem = try JSONDecoder().decode(ChannelItem.self,
                                                   from: JSONSerialization.data(withJSONObject: rowJSON))
        XCTAssertEqual(CapturedItems.leftLine(channelItem, channel: "chrome-bookmarks")?.hasPrefix("No longer in Chrome since"), true)
        XCTAssertNil(CapturedItems.leftLine(ChannelItem(kind: .media, id: "m", title: "T"), channel: "chrome-bookmarks"))

        var result = BookmarkSyncResult(new: 0, skipped: 3, sources: [])
        result.leftMarked = 1
        XCTAssertEqual(BrowserImportSummary.bookmarks(result), "Nothing new · 3 already saved · 1 no longer in the browser")
    }

    // MARK: - File write → panel, waiting on nothing else

    private static func chromeJSON(_ links: [(url: String, added: Date)]) -> String {
        let children = links.enumerated().map { i, link -> [String: Any] in
            let micros = Int64((link.added.timeIntervalSince1970 + 11_644_473_600) * 1_000_000)
            return ["type": "url", "id": "\(i + 10)", "name": "Site \(i)", "url": link.url, "date_added": "\(micros)"]
        }
        let tree: [String: Any] = ["version": 1, "roots": [
            "bookmark_bar": ["type": "folder", "id": "1", "name": "Bookmarks bar", "children": children],
            "other": ["type": "folder", "id": "2", "name": "Other bookmarks", "children": []],
        ]]
        return String(decoding: try! JSONSerialization.data(withJSONObject: tree), as: UTF8.self)
    }

    /// The coordinator's live case (2026-10-15): Chrome with 354 bookmarks, Safari turned on but refused (no Full Disk
    /// Access yet). Here everything else that could hold the question is held on purpose: Safari refused with its
    /// recheck armed and its sync hung, Chrome's own sync hung (busy, inside its 5 s floor), the backend's look never
    /// answering and no options fetched. Chrome writes its file (a rename, as Chrome does) and the panel must be on
    /// screen within 0.5 s of the write — from the app's own read and diff alone.
    func testAChromeSaveShowsWithinHalfASecondWhateverElseIsWaiting() async throws {
        let chromeDir = try scratch()
        let safariDir = try scratch()
        let bookmarks = chromeDir.appendingPathComponent("Bookmarks")
        let plist = safariDir.appendingPathComponent("Bookmarks.plist")
        let now = Date()
        var links = (0..<354).map { (url: "https://site\($0).example/page", added: now.addingTimeInterval(-86_400 - Double($0))) }
        try Self.chromeJSON(links).write(to: bookmarks, atomically: false, encoding: .utf8)
        try "refused".write(to: plist, atomically: false, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o000], ofItemAtPath: safariDir.path)

        let defaults = UserDefaults(suiteName: "cicada.v4.\(UUID().uuidString)")!
        defaults.set(true, forKey: BrowserWatchPolicy.enabledKey("chrome-bookmarks"))
        defaults.set(true, forKey: BrowserWatchPolicy.enabledKey("safari-bookmarks"))
        let prefs = SaveWhyPrefs(defaults: defaults)
        prefs.enabled = true
        let api = SilentAPI()
        let presenter = ClockPresenter()
        let center = SaveWhyCenter(prefs: prefs, api: api, presenter: presenter)
        center.start()
        XCTAssertNil(center.cachedOptions, "no options in hand: the panel must not wait for them")

        let diff = BookmarkFileDiff()
        var syncsStarted: [String] = []
        let watcher = BrowserWatcher(
            defaults: defaults,
            channels: [("chrome-bookmarks", .chromeBookmarks), ("safari-bookmarks", .safariBookmarks)],
            paths: { file in file == .safariBookmarks ? [plist] : [bookmarks] },
            accessRecheck: .milliseconds(100),
            performSync: { channel, _ in
                syncsStarted.append(channel)
                try await Task.sleep(for: .seconds(30))   // every sync hangs: none may hold the question
                return "ok"
            },
            peek: { _ in try? await Task.sleep(for: .seconds(30)) },
            diff: diff)
        watcher.start(store: Store())
        try await eventually("Chrome's baseline") { diff.hasBaseline("chrome-bookmarks") }
        try await eventually("Chrome's catch-up sync to start (and hang)") { syncsStarted == ["chrome-bookmarks"] }
        XCTAssertEqual(watcher.state(for: "safari-bookmarks"), .blocked)
        try await Task.sleep(for: .milliseconds(250))   // Safari's recheck has run at least twice meanwhile
        XCTAssertNil(presenter.shownAt, "nothing is asked about bookmarks already there")

        // The save: one more bookmark, written the way Chrome writes (a temp file renamed over the old one).
        links.append((url: "https://alpha.example/notes", added: now))
        let tmp = chromeDir.appendingPathComponent(".org.chromium.tmp")
        try Self.chromeJSON(links).write(to: tmp, atomically: false, encoding: .utf8)
        let written = SaveWhyTimings.now()
        _ = try FileManager.default.replaceItemAt(bookmarks, withItemAt: tmp)
        try await eventually("the panel", timeout: .seconds(3)) { presenter.shownAt != nil }

        let shown = try XCTUnwrap(presenter.shownAt)
        let look = try XCTUnwrap(watcher.lookTimings["chrome-bookmarks"])
        let stages = "write → event \(SaveWhyTimings.ms(look.event - written)) ms, read \(SaveWhyTimings.ms((look.read ?? 0) - look.event)) ms, "
            + "diff \(SaveWhyTimings.ms((look.diffed ?? 0) - (look.read ?? 0))) ms, panel \(SaveWhyTimings.ms(shown - written)) ms"
        print("G191 v4 stage timings (354 bookmarks): \(stages)")
        XCTAssertLessThanOrEqual(shown - written, 0.5, stages)
        XCTAssertEqual(center.state?.item?.url, "https://alpha.example/notes")
        XCTAssertFalse(center.confirmed, "shown at once, confirmed by the backend in the background")
        XCTAssertEqual(center.state?.order, SavedWhyOptions.basic.reasons.map(\.key))
        XCTAssertEqual(syncsStarted, ["chrome-bookmarks"], "the busy sync did not start a second one inside its floor")

        watcher.cancel("chrome-bookmarks")
        watcher.stop()
    }

    /// The diff never moves its baseline back: a read caught mid-write (nothing parsed) is ignored, so the next good
    /// read still names the one bookmark; and a read that finished after a newer one recorded nothing.
    func testTheDiffIgnoresAHalfWrittenReadAndAStaleOne() async {
        let diff = BookmarkFileDiff()
        let now = Date()
        let base = (0..<5).map { (url: "https://site\($0).example/", added: now.addingTimeInterval(-86_400)) }
        _ = await diff.observe(channel: "chrome-bookmarks", data: Data(Self.chromeJSON(base).utf8), live: false)
        let half = await diff.observe(channel: "chrome-bookmarks", data: Data("{\"roots\": {".utf8), live: true)
        XCTAssertNil(half)
        XCTAssertEqual(diff.baselines["chrome-bookmarks"]?.urls.count, 5, "the baseline survived the half-written read")
        let named = await diff.observe(channel: "chrome-bookmarks",
                                       data: Data(Self.chromeJSON(base + [(url: "https://alpha.example/n", added: now)]).utf8),
                                       live: true)
        XCTAssertEqual(named?.url, "https://alpha.example/n")
    }

    // MARK: - Chrome's bubble: the person's click is the trigger, the file the only confirmation

    /// The recorded window list (window-list coordinates, y down; the browser on an external display above the main
    /// one): the browser window, the "Edit bookmark" bubble, the "Bookmark added" bubble 2.2 s later — both 448 × 224,
    /// layer 0, 80 pt under the window's top, their right edge 232 pt in — and a 149 × 18 tooltip at layer 103.
    private let window = ListedWindow(number: 1, pid: 77, layer: 0, bounds: CGRect(x: -234, y: -1050, width: 1920, height: 1050))
    private func bubble(_ number: Int) -> ListedWindow {
        ListedWindow(number: number, pid: 77, layer: 0, bounds: CGRect(x: 1006, y: -970, width: 448, height: 224))
    }
    private let tooltip = ListedWindow(number: 9, pid: 77, layer: 103, bounds: CGRect(x: 1520, y: -1002, width: 149, height: 18))
    /// The star, at the address bar's right end (about 60 pt under the window's top), and a click in the page.
    private let star = CGPoint(x: 1440, y: -1050 + 60)
    private let page = CGPoint(x: 600, y: -500)

    func testTheRecordedBubblesFollowAToolbarClickAndTheTooltipNeverCounts() {
        XCTAssertNotNil(BookmarkBubbleDetector.toolbarWindow(at: star, in: [window]))
        XCTAssertNil(BookmarkBubbleDetector.toolbarWindow(at: page, in: [window]), "a click in the page starts nothing")

        var edit = BookmarkBubbleDetector()
        edit.baseline([window])
        XCTAssertEqual(edit.observe([window, bubble(2)], sinceClick: 0.1), bubble(2), "the Edit bookmark bubble")
        var added = BookmarkBubbleDetector()
        added.baseline([window])
        XCTAssertEqual(added.observe([window, bubble(3), tooltip], sinceClick: 0.12), bubble(3),
                       "the Bookmark added bubble: the measured shape")
        XCTAssertNil(added.observe([window, bubble(3), tooltip], sinceClick: 0.2), "the same window is seen once")
        var tip = BookmarkBubbleDetector()
        tip.baseline([window])
        XCTAssertNil(tip.observe([window, tooltip], sinceClick: 0.05), "a tooltip never counts")
        var late = BookmarkBubbleDetector()
        late.baseline([window])
        XCTAssertNil(late.observe([window, bubble(4)], sinceClick: 0.45), "only within 400 ms of the click")
        var other = BookmarkBubbleDetector()
        other.baseline([window])
        let elsewhere = ListedWindow(number: 5, pid: 78, layer: 0, bounds: bubble(5).bounds)
        XCTAssertNil(other.observe([window, elsewhere], sinceClick: 0.05), "only Chrome's own window counts")
    }

    /// What runs when: nothing until a click; one read for a click in the page; for a toolbar click a burst that ends
    /// at the bubble, or by itself within 400 ms; nothing after Chrome leaves the front.
    func testTheWatcherReadsTheWindowListOnlyInTheBurstAfterAToolbarClick() async throws {
        var shown: [ListedWindow] = [window]
        var bubbles: [String] = []
        let watcher = BookmarkBubbleWatcher(defaults: UserDefaults(suiteName: "cicada.v4.\(UUID().uuidString)")!,
                                            windows: { _ in shown })
        watcher.isWanted = { _ in true }
        watcher.onBubble = { bubbles.append($0) }
        watcher.arm(pid: 77, bundleId: "com.google.Chrome", channel: "chrome-bookmarks")
        try await Task.sleep(for: .milliseconds(300))
        XCTAssertEqual(watcher.reads, 0, "armed, no click: no read")

        watcher.clicked(at: page)
        XCTAssertEqual(watcher.reads, 1)
        XCTAssertFalse(watcher.isScanning, "a click in the page: one read and nothing more")

        watcher.clicked(at: star)
        XCTAssertTrue(watcher.isScanning)
        shown = [window, bubble(3), tooltip]
        try await eventually("the bubble", timeout: .seconds(1)) { bubbles == ["chrome-bookmarks"] }
        try await eventually("the burst to stop at the bubble", timeout: .seconds(1)) { !watcher.isScanning }
        let afterBubble = watcher.reads
        XCTAssertLessThanOrEqual(afterBubble, 4)

        shown = [window, bubble(3)]
        let started = ContinuousClock.now
        watcher.clicked(at: star)   // a toolbar click that opens nothing new
        try await eventually("the burst to stop by itself", timeout: .seconds(1)) { !watcher.isScanning }
        XCTAssertLessThanOrEqual(ContinuousClock.now - started, .milliseconds(600))
        XCTAssertLessThanOrEqual(watcher.reads - afterBubble, 1 + BookmarkBubblePolicy.maxScans)
        XCTAssertEqual(bubbles.count, 1)

        watcher.disarm()
        XCTAssertFalse(watcher.isArmed)
        let reads = watcher.reads
        watcher.clicked(at: star)
        XCTAssertEqual(watcher.reads, reads, "Chrome not in front: nothing runs")
    }

    /// Idle cost with Chrome in front: a global mouse-down monitor and nothing else. Measured over
    /// `CICADA_IDLE_SECONDS` (default 2 s; the report's run used 60 s) as this process's CPU time.
    func testIdleWithChromeInFrontCostsNothing() async throws {
        let seconds = Double(ProcessInfo.processInfo.environment["CICADA_IDLE_SECONDS"] ?? "") ?? 2
        let watcher = BookmarkBubbleWatcher(defaults: UserDefaults(suiteName: "cicada.v4.\(UUID().uuidString)")!,
                                            windows: { _ in [] })
        watcher.isWanted = { _ in true }
        watcher.arm(pid: 77, bundleId: "com.google.Chrome", channel: "chrome-bookmarks")
        func cpu() -> Double {
            var usage = rusage()
            getrusage(RUSAGE_SELF, &usage)
            return Double(usage.ru_utime.tv_sec + usage.ru_stime.tv_sec)
                + Double(usage.ru_utime.tv_usec + usage.ru_stime.tv_usec) / 1e6
        }
        let before = cpu()
        try await Task.sleep(for: .seconds(seconds))
        let used = cpu() - before
        print("G191 v4 idle with Chrome in front: \(seconds) s wall, \(String(format: "%.4f", used)) s CPU "
              + "(\(String(format: "%.3f", used / seconds * 100)) %), \(watcher.reads) window-list reads")
        XCTAssertEqual(watcher.reads, 0)
        XCTAssertLessThan(used / seconds, 0.01, "under 1 % of one core, whole test process")
        watcher.disarm()
    }

    func testTheLearnedSizesOfV3AreForgotten() {
        let defaults = UserDefaults(suiteName: "cicada.v4.\(UUID().uuidString)")!
        defaults.set(Data("{}".utf8), forKey: "cicada.saveWhy.bubble.com.google.Chrome")
        BookmarkBubbleWatcher.forgetLearnedSizes(defaults)
        XCTAssertNil(defaults.object(forKey: "cicada.saveWhy.bubble.com.google.Chrome"))
    }

    private func center() -> (SaveWhyCenter, ClockPresenter, SilentAPI) {
        let defaults = UserDefaults(suiteName: "cicada.v4.\(UUID().uuidString)")!
        let prefs = SaveWhyPrefs(defaults: defaults)
        prefs.enabled = true
        let presenter = ClockPresenter()
        let api = SilentAPI()
        return (SaveWhyCenter(prefs: prefs, api: api, presenter: presenter), presenter, api)
    }

    /// "Bookmark added" opens the panel at once, pending; the re-save's bookmark (a newer node for a link Chrome had,
    /// named by the diff) binds it, and the backend's look confirms it.
    func testTheAddedBubbleOpensAtOnceAndTheResaveConfirmsIt() async {
        let (center, presenter, api) = center()
        center.bubbleSeen(channel: "chrome-bookmarks")
        XCTAssertEqual(presenter.shows, 1)
        XCTAssertEqual(center.state?.isPending, true)
        center.send(.tapReason("design"))

        let again = FreshBookmark(url: "https://alpha.example/a", title: "Alpha", origin: "chrome-bookmark",
                                  channel: "chrome-bookmarks", addedAt: ISO8601DateFormatter().string(from: Date()),
                                  resave: true)
        center.candidate(again)
        XCTAssertEqual(center.state?.item?.url, again.url)
        XCTAssertFalse(center.confirmed)
        var result = BookmarkSyncResult(new: 0, skipped: 1, sources: [
            BookmarkSyncSourceSummary(origin: "chrome-bookmark", channel: "chrome-bookmarks", found: 1, new: 0,
                                      skipped: 1, firstSync: false)])
        result.fresh = [again]
        result.freshTotal = 1
        await center.noticed(result, live: true, early: 1)
        XCTAssertTrue(center.confirmed)
        XCTAssertEqual(presenter.shows, 1, "confirmed in place, never shown twice")
        center.send(.escape)
        await center.settle()
        let posts = await api.posts
        XCTAssertEqual(posts, [again.url])
    }

    /// "Edit bookmark", then Remove: Chrome writes the file with the bookmark gone and none new, and the pending panel
    /// withdraws at once, keeping nothing. A second bubble while one is pending keeps the one panel.
    func testEditThenRemoveWithdrawsKeepingNothing() async {
        let (center, presenter, api) = center()
        center.bubbleSeen(channel: "chrome-bookmarks")
        center.bubbleSeen(channel: "chrome-bookmarks")   // the next bubble while this one waits
        XCTAssertEqual(presenter.shows, 1)
        center.send(.tapReason("product"))
        center.bookmarkRemoved(on: "chrome-bookmarks")
        XCTAssertFalse(center.isShowing)
        XCTAssertEqual(center.lastOutcome, .withdrawn)
        await center.settle()
        let posts = await api.posts
        XCTAssertTrue(posts.isEmpty, "a withdrawn panel keeps nothing")
    }

    private func look(_ item: FreshBookmark) -> BookmarkSyncResult {
        var result = BookmarkSyncResult(new: 0, skipped: 1, sources: [
            BookmarkSyncSourceSummary(origin: "chrome-bookmark", channel: "chrome-bookmarks", found: 2, new: 0,
                                      skipped: 1, firstSync: false)])
        result.fresh = [item]
        result.freshTotal = 1
        return result
    }

    private func saved(_ url: String) -> FreshBookmark {
        FreshBookmark(url: url, title: "Placeholder", origin: "chrome-bookmark", channel: "chrome-bookmarks",
                      addedAt: ISO8601DateFormatter().string(from: Date()))
    }

    /// Review 2026-10-15: the backend agreeing about another link never takes over the answer given about the link the
    /// diff named. Review 2026-10-19: and never drops it either — an answer bound to its own link waits for that
    /// link's sync; an untouched panel withdraws.
    func testTheBackendsLinkMustBeTheOneTheDiffNamed() async {
        let (untouched, _, _) = center()
        untouched.candidate(saved("https://alpha.example/a"))
        await untouched.noticed(look(saved("https://beta.example/b")), live: true, early: 1)
        XCTAssertEqual(untouched.lastOutcome, .withdrawn)

        let (first, _, api) = center()
        first.candidate(saved("https://alpha.example/a"))
        first.send(.tapReason("design"))
        await first.noticed(look(saved("https://beta.example/b")), live: true, early: 1)
        XCTAssertTrue(first.isShowing, "a touched panel stays")
        XCTAssertFalse(first.confirmed)

        // The panel left with an answer before the backend spoke: another link never takes it, nor drops it.
        let (held, _, heldAPI) = center()
        held.candidate(saved("https://alpha.example/a"))
        held.send(.tapReason("product"))
        held.send(.escape)
        XCTAssertEqual(held.unconfirmedAnswer?.url, "https://alpha.example/a")
        await held.noticed(look(saved("https://beta.example/b")), live: true, early: 1)
        XCTAssertNil(held.unconfirmedAnswer)
        await held.settle()
        var heldPosts = await heldAPI.posts
        XCTAssertTrue(heldPosts.isEmpty, "never posted against another link")
        XCTAssertEqual(held.heldCount, 1, "kept for its own link")
        await held.syncLanded(look(saved("https://alpha.example/a")))
        heldPosts = await heldAPI.posts
        XCTAssertEqual(heldPosts, ["https://alpha.example/a"], "posted to its own link once its sync lands")

        // The same link binds and posts.
        let (same, _, sameAPI) = center()
        same.candidate(saved("https://alpha.example/a"))
        same.send(.tapReason("product"))
        same.send(.escape)
        await same.noticed(look(saved("https://alpha.example/a")), live: true, early: 1)
        await same.settle()
        let samePosts = await sameAPI.posts
        XCTAssertEqual(samePosts, ["https://alpha.example/a"])
        await first.settle()
        let posts = await api.posts
        XCTAssertTrue(posts.isEmpty)
    }

    /// The instant look reports a removal-only change, which is what withdraws the Edit-then-Remove panel.
    func testTheDiffCountsARemovalOnALiveRead() async {
        let diff = BookmarkFileDiff()
        let now = Date()
        let two = [(url: "https://a.example/", added: now), (url: "https://b.example/", added: now)]
        _ = await diff.observe(channel: "chrome-bookmarks", data: Data(Self.chromeJSON(two).utf8), live: false)
        let named = await diff.observe(channel: "chrome-bookmarks", data: Data(Self.chromeJSON([two[0]]).utf8), live: true)
        XCTAssertNil(named)
        XCTAssertEqual(diff.removedOnLastRead["chrome-bookmarks"], 1)
    }
}

// MARK: - Fakes

@MainActor
private final class ClockPresenter: SaveWhyPresenting {
    var shownAt: TimeInterval?
    var shows = 0
    func show(_ center: SaveWhyCenter) {
        if shownAt == nil { shownAt = SaveWhyTimings.now() }
        shows += 1
    }
    func hide() {}
    func focusText() {}
}

/// A backend that never answers a look or an options fetch (each waits until cancelled), and records answers.
private actor SilentAPI: SavedWhyAPI {
    private(set) var posts: [String] = []

    func freshBookmarks(_ bytes: BookmarkBytes) async throws -> BookmarkSyncResult {
        try await Task.sleep(for: .seconds(60))
        throw CancellationError()
    }

    func savedWhyOptions() async throws -> SavedWhyOptions {
        try await Task.sleep(for: .seconds(60))
        throw CancellationError()
    }

    func saveWhy(url: String, answer: SavedWhyAnswer, at: Date, addedAt: String?) async throws {
        posts.append(url)
    }
}
