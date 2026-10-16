import AppKit
import CoreGraphics
import Foundation

/// G191 v3/v4 — seeing the moment of saving in Chrome without a permission or an extension (owner 2026-10-15: "When I
/// bookmark something in Chrome, it takes quite a bit for the prompt to appear … No extension is best … Can't Cicada
/// non-intrusively monitor Chrome's window?").
///
/// **Why the file is late.** Chrome holds a bookmark change for `BookmarkStorage::kSaveDelay` = 2,500 ms
/// (chromium `components/bookmarks/browser/bookmark_storage.h`) before it writes `Bookmarks`, so no file watch can
/// show the question sooner than 2.5 s after the click.
///
/// **v4: the person's click is the trigger, the file the only confirmation (owner 2026-10-15: "the size check of the
/// popup seems like depending on that is not great. What about just checking when the star is clicked and
/// bookmarked? And confirm that it actually was bookmarked if added to the file. Also make sure this polling is
/// efficient and not some crazy running thread.").** v3 learned the bubble's exact size and refused sizes that came
/// with no bookmark; measured on the owner's Mac, this Chrome's bubble is 448 × 224 — outside v3's width range — and
/// its "Edit bookmark" bubble is the very same size, so size alone can never tell them apart. Now:
///
/// - a **click in the toolbar band** of the frontmost Chrome window (the star sits at the address bar's right end),
/// - followed within `inputWindow` (400 ms) by a **new window of Chrome's anchored under the toolbar** at the right of
///   that browser window (`isAnchored`) and hanging from the click (`hangsFrom`),
/// - **of a shape a bookmark confirmed** (`BubbleShapeMemory`),
///
/// opens the question at once, pending. One new bookmark in the app's own diff of the file binds the link; none within
/// `SaveWhyPolicy.pendingBound` (or a bookmark removed instead — "Edit bookmark", then Remove) withdraws it, keeping
/// nothing. A tooltip (layer 103 measured) or a menu is never one: they sit above `maxLayer`.
///
/// **v5: only a shape a bookmark confirmed (owner 2026-10-16: "when i open chrome extensions there is a popup that
/// triggers cicada popup. thats bad").** v4 took any small anchored window, and Chrome's Extensions menu — ≈ 287 × 481,
/// 102 pt under the window's top, right edge 132 pt in, taller with every extension — fits that as well as the profile
/// menu, the downloads bubble and every other toolbar bubble do; their position is the toolbar's, as the star's is, so
/// position cannot tell them apart. Their *shape* can: the bookmark bubble is a fixed 448 × 224 (Chrome's modal-dialog
/// width) whatever the page, and no other toolbar surface measured has it. So the bubble is recognised only by a shape
/// a bookmark confirmed: the measured 448 × 224 (± `shapeSlack`), plus any shape learned **positively** — an anchored
/// window of an unknown shape opens nothing, but when the file then names one new bookmark whose own instant (Chrome's
/// `date_added`, the click) fits the moment that window appeared (`confirms`), its shape is remembered. A window that
/// came with no bookmark is never remembered, so the person's own failed match (v3's flaw) can refuse nothing. A
/// Chrome update or a font change that resizes the bubble costs one slower question — that save is caught by the file
/// (≈ 2.5 s, as ⌘D is) and teaches the new shape — and the next star click is instant again.
///
/// **What runs, and when (efficiency is a hard requirement).**
/// - Chrome not frontmost: **nothing**. The watcher arms on `NSWorkspace.didActivateApplicationNotification` and
///   disarms on the next activation of any other app — no timer checks which app is in front.
/// - Chrome frontmost, no click: **nothing** but one global mouse-down monitor (an AppKit event monitor, which needs
///   no permission for mouse events and costs nothing between events). No timer, no window-list read.
/// - A click: one window-list read (`CGWindowListCopyWindowInfo`, ≈ 1–3 ms) to see whether it landed in a browser
///   window's toolbar band; if not, that is all. If it did, a burst of at most `maxScans` reads `scanEvery` apart,
///   which stops by itself at `inputWindow` or at the first bubble.
/// - ⌘D: macOS gives an app no keystroke of another without the Accessibility or Input Monitoring permission, and
///   Cicada asks for neither — so a ⌘D save is caught by the file path instead (the app's own diff ≤ 0.5 s after
///   Chrome's write), never by a steady poll of the keyboard.
///
/// Only window numbers, owners, layers and bounds are read — never a title or contents (no Screen Recording).
struct ListedWindow: Equatable, Sendable {
    let number: Int
    let pid: pid_t
    let layer: Int
    /// Window-list coordinates: origin at the primary display's top-left, y down.
    let bounds: CGRect
}

enum BookmarkBubblePolicy {
    /// A "small window": anything between a tooltip and a browser window. Generous on purpose — the shape decides
    /// (`BubbleShapeMemory`); this only keeps tooltips and second browser windows out of the shape check.
    static let smallWidth: ClosedRange<CGFloat> = 160...720
    static let smallHeight: ClosedRange<CGFloat> = 60...720
    /// The bubble's top below the browser window's top: under the tab strip and the toolbar (measured 80 pt), never on
    /// them.
    static let topBand: ClosedRange<CGFloat> = 56...170
    /// The bubble's right edge lies within this of the browser window's right edge (measured 232 pt).
    static let rightReach: CGFloat = 320
    /// And its left edge in the window's right part.
    static let leftShare: CGFloat = 0.35
    /// Narrower browser windows are not read: there a suggestion list and the bubble can look alike.
    static let minWindowWidth: CGFloat = 700
    static let minWindowHeight: CGFloat = 300
    /// Above this layer are menus, tooltips (measured: layer 103), the Dock and the status bar — never a bubble.
    static let maxLayer = 20
    /// The click's band: the tab strip and the toolbar, from the window's top.
    static let toolbarBand: CGFloat = 110
    /// How soon after the click the bubble must appear.
    static let inputWindow: TimeInterval = 0.4
    /// The burst after a toolbar click: a read this often, at most `maxScans` of them.
    static let scanEvery: Duration = .milliseconds(50)
    static let maxScans = 8

    /// G191 v5 — the shapes of Chrome's bookmark bubble a bookmark confirmed on the owner's Mac: "Bookmark added" and
    /// "Edit bookmark", both 448 × 224 pt (2026-10-15). Never a shape that came with no bookmark.
    static let measuredShapes: [BubbleShape] = [BubbleShape(width: 448, height: 224)]
    /// How far a window may differ from a confirmed shape, per side, and still be it (half-point rounding on Retina, a
    /// point of border either way). The nearest other toolbar surface measured (the Extensions menu) is 161 pt narrower.
    static let shapeSlack: CGFloat = 4
    /// The bubble hangs from the button clicked: the click's x lies within its span, or just past its right edge (the
    /// star's own width, the bubble aligned to its right). A window the click did not open sits elsewhere.
    static let hangLeft: CGFloat = 8
    static let hangRight: CGFloat = 48
    /// Learned shapes kept per browser beside the measured ones, newest first.
    static let maxLearned = 4
    /// A window of an unknown shape is remembered as the bubble only if the file names one new bookmark within this of
    /// its appearance …
    static let learnWithin: TimeInterval = 20
    /// … whose own instant (Chrome's `date_added`, the click, floored to the second) lies at most `learnLead` after and
    /// `learnLag` before the window appeared — the window came with the click that made that bookmark: the bubble shows
    /// ≤ 400 ms after the click, and flooring moves the instant back by up to 1 s. When two such windows fit one
    /// bookmark (the star, then the puzzle piece a second later) neither is learned.
    static let learnLead: TimeInterval = 0.5
    static let learnLag: TimeInterval = 1.6

    /// Whether a bookmark made at `addedAt` (the browser's own instant, floored to the second) is the one the window seen
    /// at `seenAt` came with.
    static func confirms(seenAt: Date, addedAt: Date?, now: Date) -> Bool {
        guard let addedAt, now.timeIntervalSince(seenAt) <= learnWithin else { return false }
        let lag = seenAt.timeIntervalSince(addedAt)
        return lag >= -learnLead && lag <= learnLag
    }

    /// Whether `window` hangs from a click at `point` (window-list coordinates).
    static func hangsFrom(_ window: CGRect, click point: CGPoint) -> Bool {
        point.x >= window.minX - hangLeft && point.x <= window.maxX + hangRight && point.y <= window.minY + hangLeft
    }

    /// Whether `window` is small and sits where Chrome anchors its bookmark bubble on `browser`.
    static func isAnchored(_ window: CGRect, on browser: CGRect) -> Bool {
        guard smallWidth.contains(window.width), smallHeight.contains(window.height),
              browser.width >= minWindowWidth, browser.height >= minWindowHeight else { return false }
        let top = window.minY - browser.minY
        guard topBand.contains(top) else { return false }
        guard window.maxX <= browser.maxX + 8, window.maxX >= browser.maxX - rightReach else { return false }
        return window.minX >= browser.minX + browser.width * leftShare
    }

    /// A normal browser window (layer 0, browser-sized).
    static func isBrowserWindow(_ w: ListedWindow) -> Bool {
        w.layer == 0 && w.bounds.width >= minWindowWidth && w.bounds.height >= minWindowHeight
    }

    /// Whether a click at `point` (window-list coordinates) landed in the toolbar band of `browser`.
    static func isToolbarClick(_ point: CGPoint, on browser: CGRect) -> Bool {
        browser.contains(point) && point.y - browser.minY <= toolbarBand
    }

    /// An AppKit screen point (origin bottom-left of the primary display) in window-list coordinates (y down).
    static func windowListPoint(_ appKit: CGPoint, primaryHeight: CGFloat) -> CGPoint {
        CGPoint(x: appKit.x, y: primaryHeight - appKit.y)
    }
}

/// G191 v5 — one shape of Chrome's bookmark bubble, in whole points.
struct BubbleShape: Codable, Equatable, Hashable, Sendable {
    let width: Int
    let height: Int

    init(width: Int, height: Int) {
        self.width = width
        self.height = height
    }

    init(_ size: CGSize) {
        self.init(width: Int(size.width.rounded()), height: Int(size.height.rounded()))
    }

    func matches(_ size: CGSize) -> Bool {
        abs(size.width - CGFloat(width)) <= BookmarkBubblePolicy.shapeSlack
            && abs(size.height - CGFloat(height)) <= BookmarkBubblePolicy.shapeSlack
    }
}

/// G191 v5 — the bubble shapes a bookmark confirmed, per browser: the measured ones (in code) and the learned ones
/// (`cicada.saveWhy.bubbleShapes.<bundle id>`, shapes only, newest first, at most `maxLearned`). Only ever added to
/// by a bookmark the file confirmed (`BookmarkBubbleWatcher.bookmarkNamed`); nothing here is ever a refusal.
enum BubbleShapeMemory {
    static func key(_ bundleId: String) -> String { "cicada.saveWhy.bubbleShapes.\(bundleId)" }

    static func learned(_ defaults: UserDefaults, bundleId: String) -> [BubbleShape] {
        guard let data = defaults.data(forKey: key(bundleId)),
              let shapes = try? JSONDecoder().decode([BubbleShape].self, from: data) else { return [] }
        return Array(shapes.prefix(BookmarkBubblePolicy.maxLearned))
    }

    static func shapes(_ defaults: UserDefaults, bundleId: String) -> [BubbleShape] {
        BookmarkBubblePolicy.measuredShapes + learned(defaults, bundleId: bundleId)
    }

    /// Remember `shape` (a no-op when a known shape already covers it). True when it was new.
    @discardableResult
    static func learn(_ shape: BubbleShape, _ defaults: UserDefaults, bundleId: String) -> Bool {
        let size = CGSize(width: shape.width, height: shape.height)
        guard !shapes(defaults, bundleId: bundleId).contains(where: { $0.matches(size) }) else { return false }
        let kept = Array(([shape] + learned(defaults, bundleId: bundleId)).prefix(BookmarkBubblePolicy.maxLearned))
        guard let data = try? JSONEncoder().encode(kept) else { return false }
        defaults.set(data, forKey: key(bundleId))
        return true
    }
}

/// The pure half: after a toolbar click, which new window (if any) is the bookmark bubble. Fed the window lists read
/// during the burst and the seconds since the click.
struct BookmarkBubbleDetector: Equatable {
    private(set) var known: Set<Int> = []
    /// The shapes a bookmark confirmed (`BubbleShapeMemory`); the measured ones by default.
    var shapes: [BubbleShape] = BookmarkBubblePolicy.measuredShapes
    /// The click the burst follows (window-list coordinates); nil checks no hang (the v3 tests' shortcut).
    private(set) var click: CGPoint?
    /// G191 v5 — the new anchored window this click opened whose shape no bookmark has confirmed (the Extensions menu,
    /// the profile menu, … or a resized bubble): it opens nothing, and is remembered only if the file then confirms a
    /// bookmark made with it.
    private(set) var unknown: ListedWindow?

    /// The windows on screen at the click are never new.
    mutating func baseline(_ windows: [ListedWindow], click: CGPoint? = nil) {
        known = Set(windows.map(\.number))
        self.click = click
        unknown = nil
    }

    /// The browser window whose toolbar band `point` landed in, if any.
    static func toolbarWindow(at point: CGPoint, in windows: [ListedWindow]) -> ListedWindow? {
        windows.first { BookmarkBubblePolicy.isBrowserWindow($0) && BookmarkBubblePolicy.isToolbarClick(point, on: $0.bounds) }
    }

    /// Whether a window of this size is the bookmark bubble.
    func isBubbleShape(_ size: CGSize) -> Bool { shapes.contains { $0.matches(size) } }

    /// The bubble among `windows`, at most one: a window not on screen at the click, at a bubble's layer, small and
    /// anchored under the toolbar at the right of a browser window of the same app, hanging from the click, within
    /// `inputWindow` of the click — and of a confirmed shape. An anchored new window of another shape is kept in
    /// `unknown` and is not the bubble.
    mutating func observe(_ windows: [ListedWindow], sinceClick: TimeInterval) -> ListedWindow? {
        let fresh = windows.filter { !known.contains($0.number) }
        known.formUnion(windows.map(\.number))
        guard sinceClick <= BookmarkBubblePolicy.inputWindow else { return nil }
        let browsers = windows.filter(BookmarkBubblePolicy.isBrowserWindow)
        let anchored = fresh.filter { candidate in
            candidate.layer >= 0 && candidate.layer <= BookmarkBubblePolicy.maxLayer
                && (click.map { BookmarkBubblePolicy.hangsFrom(candidate.bounds, click: $0) } ?? true)
                && browsers.contains { $0.pid == candidate.pid && $0.number != candidate.number
                    && BookmarkBubblePolicy.isAnchored(candidate.bounds, on: $0.bounds) }
        }
        if let bubble = anchored.first(where: { isBubbleShape($0.bounds.size) }) { return bubble }
        if unknown == nil { unknown = anchored.first }
        return nil
    }
}

/// The live half (see the type note above for exactly what runs when).
@MainActor
final class BookmarkBubbleWatcher {
    /// The browsers watched: Chrome (the bookmark bubble this was measured on).
    static let browsers: [(bundleId: String, channel: String)] = [("com.google.Chrome", "chrome-bookmarks")]

    /// Whether the question may be asked for this channel now (the switch on, the browser's watch on).
    var isWanted: (String) -> Bool = { _ in false }
    /// A bubble opened after the person's click: the channel.
    var onBubble: (String) -> Void = { _ in }

    private let defaults: UserDefaults
    private let windows: (pid_t) -> [ListedWindow]
    private let clock: () -> TimeInterval
    private let date: () -> Date
    /// G191 v5 — the anchored windows of an unknown shape toolbar clicks opened in the last `learnWithin`, in memory
    /// only, until a bookmark the file names confirms one: its shape, when it appeared, and where.
    private(set) var unconfirmed: [(shape: BubbleShape, seenAt: Date, bundleId: String, channel: String)] = []
    private var armed: (pid: pid_t, bundleId: String, channel: String)?
    private var monitor: Any?
    private var burst: Task<Void, Never>?
    private var observer: NSObjectProtocol?
    /// How many window-list reads this watcher made — for the efficiency test, never shown.
    private(set) var reads = 0

    init(defaults: UserDefaults = .standard,
         windows: @escaping (pid_t) -> [ListedWindow] = BookmarkBubbleWatcher.liveWindows(of:),
         clock: @escaping () -> TimeInterval = { ProcessInfo.processInfo.systemUptime },
         date: @escaping () -> Date = Date.init) {
        self.defaults = defaults
        self.windows = windows
        self.clock = clock
        self.date = date
    }

    var isArmed: Bool { armed != nil }
    var isScanning: Bool { burst != nil }

    func start() {
        Self.forgetLearnedSizes(defaults)
        guard observer == nil else { return }
        observer = NSWorkspace.shared.notificationCenter.addObserver(
            forName: NSWorkspace.didActivateApplicationNotification, object: nil, queue: .main
        ) { [weak self] note in
            let app = note.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication
            MainActor.assumeIsolated { self?.frontmostChanged(app) }
        }
        frontmostChanged(NSWorkspace.shared.frontmostApplication)
    }

    func stop() {
        if let observer { NSWorkspace.shared.notificationCenter.removeObserver(observer) }
        observer = nil
        disarm()
    }

    /// G191 v4 — v3 kept learned, refused and missed bubble sizes per browser in this Mac's defaults (refusals among
    /// them, learned from the person's own bookmarks failing to match), so they are removed (harmlessly, on every
    /// start). v5's confirmed shapes live under their own key (`BubbleShapeMemory`).
    static func forgetLearnedSizes(_ defaults: UserDefaults) {
        for entry in browsers { defaults.removeObject(forKey: "cicada.saveWhy.bubble.\(entry.bundleId)") }
    }

    private func frontmostChanged(_ app: NSRunningApplication?) {
        guard let app, let bundle = app.bundleIdentifier,
              let entry = Self.browsers.first(where: { $0.bundleId == bundle }), isWanted(entry.channel) else {
            disarm()
            return
        }
        arm(pid: app.processIdentifier, bundleId: bundle, channel: entry.channel)
    }

    /// Chrome came to the front: one global mouse-down monitor, nothing else.
    func arm(pid: pid_t, bundleId: String, channel: String) {
        if armed?.pid == pid, monitor != nil { return }
        disarm()
        armed = (pid, bundleId, channel)
        monitor = NSEvent.addGlobalMonitorForEvents(matching: [.leftMouseDown]) { [weak self] _ in
            let location = NSEvent.mouseLocation
            MainActor.assumeIsolated { self?.clicked(atAppKit: location) }
        }
    }

    /// Chrome left the front (or the watcher stopped): the monitor and any burst go.
    func disarm() {
        if let monitor { NSEvent.removeMonitor(monitor) }
        monitor = nil
        burst?.cancel()
        burst = nil
        armed = nil
    }

    func clicked(atAppKit location: CGPoint) {
        let primary = NSScreen.screens.first?.frame.height ?? 0
        clicked(at: BookmarkBubblePolicy.windowListPoint(location, primaryHeight: primary))
    }

    /// A click (window-list coordinates) while Chrome is in front: one read; a burst only for a toolbar click.
    func clicked(at point: CGPoint) {
        guard let armed, isWanted(armed.channel) else { return }
        let at = clock()
        reads += 1
        let now = windows(armed.pid)
        guard BookmarkBubbleDetector.toolbarWindow(at: point, in: now) != nil else { return }
        var detector = BookmarkBubbleDetector()
        detector.shapes = BubbleShapeMemory.shapes(defaults, bundleId: armed.bundleId)
        detector.baseline(now, click: point)
        burst?.cancel()
        burst = Task { @MainActor [weak self] in
            for _ in 0..<BookmarkBubblePolicy.maxScans {
                try? await Task.sleep(for: BookmarkBubblePolicy.scanEvery)
                guard let self, !Task.isCancelled, let armed = self.armed else { return }
                let since = self.clock() - at
                if since > BookmarkBubblePolicy.inputWindow { break }
                self.reads += 1
                if detector.observe(self.windows(armed.pid), sinceClick: since) != nil {
                    if self.isWanted(armed.channel) { self.onBubble(armed.channel) }
                    break
                }
                if let other = detector.unknown {
                    // The click opened a menu or a bubble of a shape no bookmark confirmed: nothing opens. Kept only
                    // so a bookmark made with it (a resized bookmark bubble) can teach its shape.
                    let seenAt = self.date()
                    self.unconfirmed = self.unconfirmed.filter {
                        seenAt.timeIntervalSince($0.seenAt) <= BookmarkBubblePolicy.learnWithin
                    } + [(BubbleShape(other.bounds.size), seenAt, armed.bundleId, armed.channel)]
                    break
                }
            }
            self?.burst = nil
        }
    }

    /// G191 v5 — the app's own diff of `item.channel`'s file named one new bookmark (live reads only). If an anchored
    /// window of an unknown shape appeared with the click that made it (`BookmarkBubblePolicy.confirms`), that window
    /// was the bookmark bubble: its shape is remembered, so the next star click opens the question at once. Two
    /// windows that both fit (the star, then the puzzle piece a second later) teach nothing, and anything else teaches
    /// nothing either — no shape is ever refused.
    func bookmarkNamed(_ item: FreshBookmark) {
        let now = date()
        unconfirmed = unconfirmed.filter { now.timeIntervalSince($0.seenAt) <= BookmarkBubblePolicy.learnWithin }
        let fits = unconfirmed.indices.filter { i in
            unconfirmed[i].channel == item.channel
                && BookmarkBubblePolicy.confirms(seenAt: unconfirmed[i].seenAt, addedAt: item.addedDate, now: now)
        }
        guard !fits.isEmpty else { return }
        let seen = unconfirmed[fits[0]]
        unconfirmed = unconfirmed.enumerated().filter { !fits.contains($0.offset) }.map(\.element)
        guard fits.count == 1 else { return }
        if BubbleShapeMemory.learn(seen.shape, defaults, bundleId: seen.bundleId) {
            SaveWhyTimings.logger.info(
                "save-why: bubble shape \(seen.shape.width)×\(seen.shape.height) confirmed by a bookmark")
        }
    }

    /// `pid`'s on-screen windows from the window list: number, layer and bounds only.
    nonisolated static func liveWindows(of pid: pid_t) -> [ListedWindow] {
        guard let list = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID)
            as? [[String: Any]] else { return [] }
        return list.compactMap { info in
            guard (info[kCGWindowOwnerPID as String] as? Int).map(pid_t.init) == pid,
                  let number = info[kCGWindowNumber as String] as? Int,
                  let dict = info[kCGWindowBounds as String] as? NSDictionary,
                  let bounds = CGRect(dictionaryRepresentation: dict as CFDictionary) else { return nil }
            return ListedWindow(number: number, pid: pid, layer: info[kCGWindowLayer as String] as? Int ?? 0,
                                bounds: bounds)
        }
    }
}
