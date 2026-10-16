import XCTest
@testable import CicadaApp

/// G191 v5 — Chrome's toolbar menus never open the question (owner 2026-10-16: "when i open chrome extensions there is
/// a popup that triggers cicada popup. thats bad"). Only a window of a shape a bookmark confirmed is the bookmark
/// bubble: the measured 448 × 224, or a shape the file later confirmed with a bookmark made at that click. Synthetic
/// window lists (the measured geometry, window-list coordinates, y down) and placeholder sites only.
@MainActor
final class BookmarksV5Tests: XCTestCase {
    /// The browser window on an external display above the main one (as v4 recorded it): right edge at x 1686.
    private let window = ListedWindow(number: 1, pid: 77, layer: 0, bounds: CGRect(x: -234, y: -1050, width: 1920, height: 1050))
    /// "Bookmark added" / "Edit bookmark": 448 × 224, layer 0, 80 pt under the window's top, right edge 232 pt in.
    private func bubble(_ number: Int, height: CGFloat = 224) -> ListedWindow {
        ListedWindow(number: number, pid: 77, layer: 0, bounds: CGRect(x: 1006, y: -970, width: 448, height: height))
    }
    /// The star, at the address bar's right end.
    private let star = CGPoint(x: 1440, y: -990)

    /// The Extensions menu as seen in the bug: ≈ 287 × 481, 102 pt under the window's top, right edge 132 pt in —
    /// taller with every extension.
    private func extensionsMenu(_ number: Int, height: CGFloat = 481) -> ListedWindow {
        ListedWindow(number: number, pid: 77, layer: 0, bounds: CGRect(x: 1686 - 132 - 287, y: -948, width: 287, height: height))
    }
    /// The puzzle-piece button, right of the address bar.
    private let puzzle = CGPoint(x: 1540, y: -990)
    /// A profile-menu-like window under the avatar (right edge 60 pt in) and a downloads-like bubble (96 pt in).
    private let profileMenu = ListedWindow(number: 40, pid: 77, layer: 0, bounds: CGRect(x: 1306, y: -970, width: 320, height: 460))
    private let avatar = CGPoint(x: 1610, y: -990)
    private let downloads = ListedWindow(number: 41, pid: 77, layer: 0, bounds: CGRect(x: 1230, y: -970, width: 360, height: 280))
    private let downloadsButton = CGPoint(x: 1580, y: -990)
    /// A bubble of the modal width with its own height (a password-like bubble from an icon in the address bar).
    private let passwordLike = ListedWindow(number: 42, pid: 77, layer: 0, bounds: CGRect(x: 1006, y: -970, width: 448, height: 318))
    private let keyIcon = CGPoint(x: 1400, y: -990)
    private let tooltip = ListedWindow(number: 9, pid: 77, layer: 103, bounds: CGRect(x: 1520, y: -1002, width: 149, height: 18))

    private func detector(click: CGPoint, shapes: [BubbleShape] = BookmarkBubblePolicy.measuredShapes) -> BookmarkBubbleDetector {
        var d = BookmarkBubbleDetector()
        d.shapes = shapes
        d.baseline([window], click: click)
        return d
    }

    // MARK: - The pure detector

    func testTheMeasuredBubblePasses() {
        var d = detector(click: star)
        XCTAssertEqual(d.observe([window, bubble(2), tooltip], sinceClick: 0.1), bubble(2))
        XCTAssertNil(d.unknown)
        // A half point either way (Retina rounding) is still the bubble.
        var half = detector(click: star)
        let rounded = ListedWindow(number: 3, pid: 77, layer: 0, bounds: CGRect(x: 1006.5, y: -970, width: 447.5, height: 224.5))
        XCTAssertEqual(half.observe([window, rounded], sinceClick: 0.1), rounded)
    }

    func testTheExtensionsMenuNeverPasses() {
        var d = detector(click: puzzle)
        XCTAssertNil(d.observe([window, extensionsMenu(20)], sinceClick: 0.1), "the measured Extensions menu")
        XCTAssertEqual(d.unknown, extensionsMenu(20), "kept as unknown, only so a bookmark could ever confirm it")
        var taller = detector(click: puzzle)
        XCTAssertNil(taller.observe([window, extensionsMenu(21, height: 700)], sinceClick: 0.1), "more extensions")
        var shorter = detector(click: puzzle)
        XCTAssertNil(shorter.observe([window, extensionsMenu(22, height: 224)], sinceClick: 0.1),
                     "even exactly as tall as the bubble: the width differs by 161 pt")
    }

    func testOtherToolbarMenusAndBubblesNeverPass() {
        var profile = detector(click: avatar)
        XCTAssertNil(profile.observe([window, profileMenu], sinceClick: 0.1), "a profile-menu-like window")
        var dl = detector(click: downloadsButton)
        XCTAssertNil(dl.observe([window, downloads], sinceClick: 0.1), "a downloads-like bubble")
        var key = detector(click: keyIcon)
        XCTAssertNil(key.observe([window, passwordLike], sinceClick: 0.1), "the modal width with another height")
        let permission = ListedWindow(number: 43, pid: 77, layer: 0, bounds: CGRect(x: -100, y: -970, width: 448, height: 224))
        var site = detector(click: CGPoint(x: -150, y: -990))
        XCTAssertNil(site.observe([window, permission], sinceClick: 0.1), "a site bubble at the address bar's left")
        var tip = detector(click: star)
        XCTAssertNil(tip.observe([window, tooltip], sinceClick: 0.05), "a tooltip stays refused")
        XCTAssertNil(tip.unknown, "and is not even a candidate")
    }

    /// A window of the bubble's shape the click did not open (it opened by itself during the burst, or hangs from
    /// another button) is not the bubble.
    func testTheBubbleMustHangFromTheClick() {
        var tab = detector(click: CGPoint(x: 200, y: -1035))
        XCTAssertNil(tab.observe([window, bubble(2)], sinceClick: 0.1), "a click on a tab, far left of it")
    }

    // MARK: - The confirmed-shape memory

    func testMemoryKeepsOnlyConfirmedShapesAndNeverARefusal() throws {
        let defaults = UserDefaults(suiteName: "cicada.v5.\(UUID().uuidString)")!
        let bundle = "com.google.Chrome"
        XCTAssertEqual(BubbleShapeMemory.shapes(defaults, bundleId: bundle), BookmarkBubblePolicy.measuredShapes)
        XCTAssertFalse(BubbleShapeMemory.learn(BubbleShape(width: 450, height: 222), defaults, bundleId: bundle),
                       "covered by the measured shape")
        for h in [260, 270, 280, 290, 300] {
            XCTAssertTrue(BubbleShapeMemory.learn(BubbleShape(width: 448, height: h), defaults, bundleId: bundle))
        }
        let learned = BubbleShapeMemory.learned(defaults, bundleId: bundle)
        XCTAssertEqual(learned.map(\.height), [300, 290, 280, 270], "newest first, at most four")
        XCTAssertEqual(BubbleShapeMemory.shapes(defaults, bundleId: bundle).first, BubbleShape(width: 448, height: 224),
                       "the measured shape is always kept")
    }

    func testABookmarkConfirmsOnlyTheWindowItCameWith() {
        let click = Date(timeIntervalSince1970: 1_800_000_000.95)
        let seen = click.addingTimeInterval(0.2)
        let later = seen.addingTimeInterval(3)
        // Chrome makes the bookmark between the click and the bubble — across a second boundary, too.
        XCTAssertTrue(BookmarkBubblePolicy.confirms(clickAt: click, seenAt: seen, addedAt: click.addingTimeInterval(0.1),
                                                    now: later))
        XCTAssertTrue(BookmarkBubblePolicy.confirms(clickAt: click, seenAt: seen, addedAt: click.addingTimeInterval(-0.3),
                                                    now: later), "the monitor's delivery lag")
        XCTAssertFalse(BookmarkBubblePolicy.confirms(clickAt: click, seenAt: seen, addedAt: seen.addingTimeInterval(0.3),
                                                     now: later),
                       "a ⌘D 0.3 s after the menu was seen is not that window's bookmark (the floored instant allowed it)")
        XCTAssertFalse(BookmarkBubblePolicy.confirms(clickAt: click, seenAt: seen, addedAt: click.addingTimeInterval(-60),
                                                     now: later),
                       "an older bookmark (a sync from another device) is not either")
        XCTAssertFalse(BookmarkBubblePolicy.confirms(clickAt: click, seenAt: seen, addedAt: nil, now: later))
        XCTAssertFalse(BookmarkBubblePolicy.confirms(clickAt: click, seenAt: seen, addedAt: click,
                                                     now: seen.addingTimeInterval(30)), "too long after")
    }

    /// Chromium's `date_added` is microseconds since 1601-01-01 UTC, kept to the microsecond for the teacher and
    /// floored to the second for the backend's `addedAt`.
    func testChromiumInstantIsExactAndTheWireValueFloored() {
        let entry = BookmarkEntry(url: "https://alpha.example/", title: "", addedMicros: 13_355_526_400_750_000)
        XCTAssertEqual(entry.addedAt, "2024-03-21T20:26:40Z")
        let exact = BookmarkEntry.instant(micros: 13_355_526_400_750_000)!
        XCTAssertEqual(exact.timeIntervalSince1970, 1_711_052_800.75, accuracy: 0.000_01)
        XCTAssertNil(BookmarkEntry.instant(micros: 0))
        let fresh = FreshBookmark(url: entry.url, addedAt: entry.addedAt, addedMicros: entry.addedMicros)
        XCTAssertEqual(fresh.addedInstant!.timeIntervalSince1970, 1_711_052_800.75, accuracy: 0.000_01)
        XCTAssertNil(FreshBookmark(url: entry.url, addedAt: entry.addedAt).addedInstant,
                     "the backend's floored instant teaches nothing")
    }

    // MARK: - The watcher, end to end on synthetic window lists

    private func eventually(_ what: String, timeout: Duration = .seconds(2), _ condition: () -> Bool) async throws {
        let deadline = ContinuousClock.now + timeout
        while ContinuousClock.now < deadline {
            if condition() { return }
            try await Task.sleep(for: .milliseconds(5))
        }
        XCTFail("timed out waiting for: \(what)")
    }

    private func iso(_ date: Date) -> String {
        ISO8601DateFormatter().string(from: Date(timeIntervalSince1970: date.timeIntervalSince1970.rounded(.down)))
    }

    private func named(_ url: String, at date: Date, channel: String = "chrome-bookmarks") -> FreshBookmark {
        FreshBookmark(url: url, origin: "chrome-bookmark", channel: channel, addedAt: iso(date),
                      addedMicros: Int64(((date.timeIntervalSince1970 + 11_644_473_600) * 1_000_000).rounded()))
    }

    /// The bug: the puzzle piece opens the Extensions menu — again and again, then a ⌘D a few seconds later — and the
    /// question never opens, nothing is learned, and the real bubble still opens it at once.
    func testTheExtensionsMenuNeverOpensTheQuestionAndTeachesNothing() async throws {
        let defaults = UserDefaults(suiteName: "cicada.v5.\(UUID().uuidString)")!
        var shown: [ListedWindow] = [window]
        var bubbles: [String] = []
        var now = Date(timeIntervalSince1970: 1_800_000_000.2)
        let watcher = BookmarkBubbleWatcher(defaults: defaults, windows: { _ in shown }, date: { now })
        watcher.isWanted = { _ in true }
        watcher.onBubble = { bubbles.append($0) }
        watcher.arm(pid: 77, bundleId: "com.google.Chrome", channel: "chrome-bookmarks")

        for n in 0..<3 {
            shown = [window]
            watcher.clicked(at: puzzle)
            shown = [window, extensionsMenu(100 + n, height: 481 + CGFloat(n) * 40), tooltip]
            try await eventually("the burst to end at the menu") { !watcher.isScanning }
            XCTAssertEqual(bubbles, [], "the Extensions menu never opens the question, not even pending")
            XCTAssertEqual(watcher.unconfirmed.count, n + 1)
        }
        // A ⌘D three seconds after the menu: Chrome's instant is the keystroke's, not the menu's.
        now = now.addingTimeInterval(5.5)
        watcher.bookmarkNamed(named("https://alpha.example/a", at: now.addingTimeInterval(-2.5)))
        // Review 2026-10-16: a ⌘D (or an extension saving from the menu) one second after the menu was seen — inside
        // the old floored window — teaches nothing either: Chrome's instant is after the window.
        shown = [window]
        watcher.clicked(at: puzzle)
        shown = [window, extensionsMenu(110)]
        try await eventually("the burst to end at the menu") { !watcher.isScanning }
        watcher.bookmarkNamed(named("https://alpha.example/b", at: now.addingTimeInterval(1.0)))
        XCTAssertEqual(BubbleShapeMemory.learned(defaults, bundleId: "com.google.Chrome"), [], "nothing learned")
        XCTAssertNil(defaults.object(forKey: BubbleShapeMemory.key("com.google.Chrome")))

        // The star still opens it at once.
        shown = [window]
        watcher.clicked(at: star)
        shown = [window, bubble(200)]
        try await eventually("the bubble") { bubbles == ["chrome-bookmarks"] }
        watcher.disarm()
    }

    /// A Chrome update makes the bubble 448 × 260. The first star click opens nothing at once (the file asks, as for
    /// ⌘D); the bookmark it made confirms the shape; the next click is instant again. Other toolbar menus still never
    /// open it, and another browser's bookmark teaches nothing.
    func testAResizedBubbleIsLearnedFromTheBookmarkItMade() async throws {
        let defaults = UserDefaults(suiteName: "cicada.v5.\(UUID().uuidString)")!
        var shown: [ListedWindow] = [window]
        var bubbles: [String] = []
        var now = Date(timeIntervalSince1970: 1_800_000_000.25)
        let watcher = BookmarkBubbleWatcher(defaults: defaults, windows: { _ in shown }, date: { now })
        watcher.isWanted = { _ in true }
        watcher.onBubble = { bubbles.append($0) }
        watcher.arm(pid: 77, bundleId: "com.google.Chrome", channel: "chrome-bookmarks")

        watcher.clicked(at: star)
        let clickAt = now.addingTimeInterval(0.1)   // Chrome makes the bookmark, then shows its bubble
        now = now.addingTimeInterval(0.2)
        shown = [window, bubble(300, height: 260)]
        try await eventually("the burst to end") { !watcher.isScanning }
        XCTAssertEqual(bubbles, [], "an unconfirmed shape opens nothing")
        // Another browser's bookmark is not this window's.
        watcher.bookmarkNamed(named("https://beta.example/b", at: clickAt, channel: "brave-bookmarks"))
        XCTAssertEqual(watcher.unconfirmed.count, 1)
        // Chrome writes its file 2.5 s later; the app's diff names the bookmark made at the click.
        now = now.addingTimeInterval(2.6)
        watcher.bookmarkNamed(named("https://alpha.example/a", at: clickAt))
        XCTAssertEqual(BubbleShapeMemory.learned(defaults, bundleId: "com.google.Chrome"),
                       [BubbleShape(width: 448, height: 260)])

        shown = [window]
        watcher.clicked(at: star)
        shown = [window, bubble(301, height: 260)]
        try await eventually("the learned bubble opens it at once") { bubbles == ["chrome-bookmarks"] }

        shown = [window]
        watcher.clicked(at: puzzle)
        shown = [window, extensionsMenu(302)]
        try await eventually("the burst to end") { !watcher.isScanning }
        XCTAssertEqual(bubbles.count, 1, "the Extensions menu still never does")
        watcher.disarm()
    }

    /// The star opens a resized bubble, and 0.3 s later the puzzle piece opens the Extensions menu, the bookmark's
    /// instant falling where both windows could have come with it: neither shape is learned. A bookmark made before
    /// the second click is the first window's alone.
    func testTwoWindowsThatFitOneBookmarkTeachNothing() async throws {
        let defaults = UserDefaults(suiteName: "cicada.v5.\(UUID().uuidString)")!
        var shown: [ListedWindow] = [window]
        let start = Date(timeIntervalSince1970: 1_800_000_000.25)
        var now = start
        let watcher = BookmarkBubbleWatcher(defaults: defaults, windows: { _ in shown }, date: { now })
        watcher.isWanted = { _ in true }
        watcher.arm(pid: 77, bundleId: "com.google.Chrome", channel: "chrome-bookmarks")
        func twoWindows() async throws {
            now = start
            shown = [window]
            watcher.clicked(at: star)
            now = start.addingTimeInterval(0.2)
            shown = [window, bubble(400, height: 260)]
            try await eventually("the burst to end") { !watcher.isScanning }
            now = start.addingTimeInterval(0.3)
            shown = [window]
            watcher.clicked(at: puzzle)
            now = start.addingTimeInterval(0.4)
            shown = [window, extensionsMenu(401)]
            try await eventually("the burst to end") { !watcher.isScanning }
            XCTAssertEqual(watcher.unconfirmed.count, 2)
            now = start.addingTimeInterval(3)
        }
        try await twoWindows()
        watcher.bookmarkNamed(named("https://alpha.example/a", at: start.addingTimeInterval(0.15)))
        XCTAssertEqual(BubbleShapeMemory.learned(defaults, bundleId: "com.google.Chrome"), [])
        XCTAssertEqual(watcher.unconfirmed.count, 0)

        // The puzzle piece a second after the star instead: the bookmark (made with the star) fits only the bubble.
        now = start
        shown = [window]
        watcher.clicked(at: star)
        now = start.addingTimeInterval(0.2)
        shown = [window, bubble(402, height: 260)]
        try await eventually("the burst to end") { !watcher.isScanning }
        now = start.addingTimeInterval(1.2)
        shown = [window]
        watcher.clicked(at: puzzle)
        now = start.addingTimeInterval(1.3)
        shown = [window, extensionsMenu(403)]
        try await eventually("the burst to end") { !watcher.isScanning }
        now = start.addingTimeInterval(3)
        watcher.bookmarkNamed(named("https://alpha.example/b", at: start.addingTimeInterval(0.1)))
        XCTAssertEqual(BubbleShapeMemory.learned(defaults, bundleId: "com.google.Chrome"),
                       [BubbleShape(width: 448, height: 260)], "the bubble's shape, never the menu's")
        watcher.disarm()
    }

    /// A menu of an unknown shape, then the star's measured bubble: the bookmark that follows is the bubble's, so the
    /// held menu is dropped and can never claim it.
    func testAMeasuredBubbleDropsTheHeldWindows() async throws {
        let defaults = UserDefaults(suiteName: "cicada.v5.\(UUID().uuidString)")!
        var shown: [ListedWindow] = [window]
        var bubbles: [String] = []
        let start = Date(timeIntervalSince1970: 1_800_000_000.25)
        var now = start
        let watcher = BookmarkBubbleWatcher(defaults: defaults, windows: { _ in shown }, date: { now })
        watcher.isWanted = { _ in true }
        watcher.onBubble = { bubbles.append($0) }
        watcher.arm(pid: 77, bundleId: "com.google.Chrome", channel: "chrome-bookmarks")
        watcher.clicked(at: puzzle)
        now = start.addingTimeInterval(0.3)
        shown = [window, extensionsMenu(500)]
        try await eventually("the burst to end") { !watcher.isScanning }
        XCTAssertEqual(watcher.unconfirmed.count, 1)
        now = start.addingTimeInterval(0.35)
        shown = [window]
        watcher.clicked(at: star)
        shown = [window, bubble(501)]
        try await eventually("the bubble") { bubbles == ["chrome-bookmarks"] }
        XCTAssertEqual(watcher.unconfirmed.count, 0)
        now = start.addingTimeInterval(3)
        watcher.bookmarkNamed(named("https://alpha.example/a", at: start.addingTimeInterval(0.2)))
        XCTAssertNil(defaults.object(forKey: BubbleShapeMemory.key("com.google.Chrome")))
        watcher.disarm()
    }

    /// The center hands every bookmark its diff names to the watcher's teacher, whatever it decides to ask.
    func testTheCenterHandsEveryNamedBookmarkToTheTeacher() {
        let defaults = UserDefaults(suiteName: "cicada.v5.\(UUID().uuidString)")!
        let prefs = SaveWhyPrefs(defaults: defaults)
        prefs.enabled = true
        prefs.mutedHosts = ["alpha.example"]
        let center = SaveWhyCenter(prefs: prefs, api: APIClient.shared)
        var taught: [String] = []
        center.onNamed = { taught.append($0.url) }
        center.candidate(named("https://alpha.example/a", at: Date()))
        XCTAssertEqual(taught, ["https://alpha.example/a"], "a muted site still confirms the bubble's shape")
        XCTAssertFalse(center.isShowing)
    }
}
