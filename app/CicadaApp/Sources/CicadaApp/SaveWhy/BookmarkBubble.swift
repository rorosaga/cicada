import AppKit
import CoreGraphics
import Foundation

/// G191 v3 — seeing the moment of saving in Chrome without a permission or an extension (owner 2026-10-15: "When I
/// bookmark something in Chrome, it takes quite a bit for the prompt to appear … No extension is best … Can't Cicada
/// non-intrusively monitor Chrome's window?").
///
/// **Why the file is late.** Chrome holds a bookmark change for `BookmarkStorage::kSaveDelay` = 2,500 ms
/// (chromium `components/bookmarks/browser/bookmark_storage.h`) before it writes `Bookmarks`, so no file watch can
/// show the question sooner than 2.5 s after the click — and the read, the look and the panel came on top.
///
/// **What is seen instead.** When the person bookmarks a page (⌘D or the star), Chrome opens its "Bookmark added"
/// bubble as a small window of its own, under the toolbar at the right of the browser window. The window list
/// (`CGWindowListCopyWindowInfo`) names every on-screen window's owner, layer, number and bounds without Screen
/// Recording — only a window's *title* needs that, and none is asked for. So while Chrome is the frontmost app and
/// the person has just typed or clicked, the watcher compares Chrome's windows with the ones it already knew; a new
/// one of a bubble's size, anchored under the toolbar at the right of a browser window, shows the question at once,
/// in a pending state. The link fills in when Chrome writes its file, and the answer binds to the bookmark the sync
/// confirms; if none comes within `SaveWhyPolicy.pendingBound` the panel withdraws and keeps nothing.
///
/// **Keeping false positives rare.** Chrome's other bubbles open in the same place: the password save, translate,
/// zoom, and the extensions, downloads and profile menus. Measured from Chromium's view code they share the bubble
/// width (`DISTANCE_BUBBLE_PREFERRED_WIDTH`, 320 pt, plus the frame) and only their heights differ. Four filters:
/// (1) only right after the person's own input (a key or a click in the last second — the password and translate
/// bubbles open on their own after a page loads); (2) the geometry below (permission prompts and the page-info bubble
/// open at the left of the address bar; the address bar's suggestions are as wide as the bar and start under its top;
/// a browser window narrower than `minWindowWidth` is never read, because there the two overlap); (3) a size that
/// once came with no bookmark is never shown again (`refused`); (4) once a size came with a bookmark, only that size
/// counts (`learned`) — the bookmark bubble's size is fixed per Chrome version, so the first bookmark teaches it and
/// from then on the extensions or profile menu, which are other sizes, never trigger. Both lists hold sizes only,
/// per browser, in this Mac's defaults.
struct ListedWindow: Equatable, Sendable {
    let number: Int
    let pid: pid_t
    let layer: Int
    /// Window-list coordinates: origin at the primary display's top-left, y down.
    let bounds: CGRect
}

/// A bubble's size in whole points — the key the detector learns.
struct BubbleSize: Codable, Equatable, Hashable, Sendable {
    let width: Int
    let height: Int

    init(_ rect: CGRect) {
        width = Int(rect.width.rounded())
        height = Int(rect.height.rounded())
    }

    init(width: Int, height: Int) {
        self.width = width
        self.height = height
    }

    func matches(_ other: BubbleSize, tolerance: Int = BookmarkBubblePolicy.sizeTolerance) -> Bool {
        abs(width - other.width) <= tolerance && abs(height - other.height) <= tolerance
    }
}

enum BookmarkBubblePolicy {
    /// The bubble's width: Chromium's preferred bubble width (320) plus its frame, with room either side.
    static let widthRange: ClosedRange<CGFloat> = 280...420
    /// "Bookmark added" (name, folder, three buttons) through its taller shopping variant.
    static let heightRange: ClosedRange<CGFloat> = 100...480
    /// The bubble's top below the browser window's top: under the tab strip and the toolbar (≈ 80 pt), never on them.
    static let topBand: ClosedRange<CGFloat> = 56...170
    /// The bubble's right edge lies within this of the browser window's right edge (the star sits at the address
    /// bar's right end, left of the toolbar's buttons).
    static let rightReach: CGFloat = 320
    /// And its left edge in the window's right part.
    static let leftShare: CGFloat = 0.35
    /// Narrower browser windows are not read: there a suggestion list and the bubble can look alike.
    static let minWindowWidth: CGFloat = 700
    static let minWindowHeight: CGFloat = 300
    /// Above this layer are menus, the Dock and the status bar — never a bubble.
    static let maxLayer = 20
    /// How recent the person's own key or click must be.
    static let inputWindow: TimeInterval = 1.0
    static let sizeTolerance = 4
    /// How many sizes each list keeps.
    static let learnedCap = 4
    static let refusedCap = 16
    /// The watcher's clock: a cheap input check each tick, a window-list scan only after input, at most this often.
    static let tick: Duration = .milliseconds(50)
    static let scanEvery: TimeInterval = 0.1
    /// After an input, how long the scans go on (the bubble opens within a frame or two of ⌘D).
    static let scanAfterInput: TimeInterval = 1.2

    /// Whether `window` has a bubble's size and sits where Chrome anchors its bookmark bubble on `browser`.
    static func isAnchored(_ window: CGRect, on browser: CGRect) -> Bool {
        guard widthRange.contains(window.width), heightRange.contains(window.height),
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
}

/// The pure half: which new window, if any, is the bookmark bubble. Fed the window list and the age of the person's
/// last input; keeps the windows it has already seen, and the sizes it has learned.
struct BookmarkBubbleDetector: Equatable {
    private(set) var known: Set<Int> = []
    var learned: [BubbleSize] = []
    var refused: [BubbleSize] = []

    init(learned: [BubbleSize] = [], refused: [BubbleSize] = []) {
        self.learned = learned
        self.refused = refused
    }

    /// The windows already on screen when watching starts are never new.
    mutating func baseline(_ windows: [ListedWindow]) {
        known = Set(windows.map(\.number))
    }

    /// `windows` are the browser's on-screen windows now; `inputAge` the seconds since the person's last key or click
    /// (nil when the system does not say). Returns the bubble, at most one, and remembers every window it saw.
    mutating func observe(_ windows: [ListedWindow], inputAge: TimeInterval?) -> ListedWindow? {
        let fresh = windows.filter { !known.contains($0.number) }
        known = Set(windows.map(\.number))
        if let inputAge, inputAge > BookmarkBubblePolicy.inputWindow { return nil }
        let browsers = windows.filter(BookmarkBubblePolicy.isBrowserWindow)
        for candidate in fresh where candidate.layer >= 0 && candidate.layer <= BookmarkBubblePolicy.maxLayer {
            guard browsers.contains(where: { $0.pid == candidate.pid && $0.number != candidate.number
                && BookmarkBubblePolicy.isAnchored(candidate.bounds, on: $0.bounds) }) else { continue }
            let size = BubbleSize(candidate.bounds)
            if refused.contains(where: { $0.matches(size) }) { continue }
            if !learned.isEmpty, !learned.contains(where: { $0.matches(size) }) { continue }
            return candidate
        }
        return nil
    }

    /// A bubble of `size` came with a bookmark: from now on only sizes like it count.
    mutating func confirm(_ size: BubbleSize) {
        refused.removeAll { $0.matches(size) }
        guard !learned.contains(where: { $0.matches(size) }) else { return }
        learned = Array((learned + [size]).suffix(BookmarkBubblePolicy.learnedCap))
    }

    /// A bubble of `size` came with no bookmark: never shown again — unless a bookmark already taught it.
    mutating func refuse(_ size: BubbleSize) {
        guard !learned.contains(where: { $0.matches(size) }), !refused.contains(where: { $0.matches(size) }) else {
            return
        }
        refused = Array((refused + [size]).suffix(BookmarkBubblePolicy.refusedCap))
    }
}

/// What the detector has learned, per browser, kept in this Mac's defaults: sizes only.
struct BubbleMemory: Codable, Equatable {
    var learned: [BubbleSize] = []
    var refused: [BubbleSize] = []

    static func key(_ bundleId: String) -> String { "cicada.saveWhy.bubble.\(bundleId)" }

    static func load(_ bundleId: String, defaults: UserDefaults) -> BubbleMemory {
        guard let data = defaults.data(forKey: key(bundleId)),
              let memory = try? JSONDecoder().decode(BubbleMemory.self, from: data) else { return BubbleMemory() }
        return memory
    }

    func save(_ bundleId: String, defaults: UserDefaults) {
        defaults.set(try? JSONEncoder().encode(self), forKey: Self.key(bundleId))
    }
}

/// The live half: watches only while a watched browser is the frontmost app, checks the person's input every tick
/// (`CGEventSource.secondsSinceLastEventType`, which needs no permission) and reads the window list only in the second
/// after a key or a click. Never reads a window's title or contents.
@MainActor
final class BookmarkBubbleWatcher {
    /// The browsers watched: Chrome (the bookmark bubble this was measured on).
    static let browsers: [(bundleId: String, channel: String)] = [("com.google.Chrome", "chrome-bookmarks")]

    /// Whether the question may be asked for this channel now (the switch on, the browser's watch on).
    var isWanted: (String) -> Bool = { _ in false }
    /// A bubble opened: the channel and its size (handed back through `feedback`).
    var onBubble: (String, BubbleSize) -> Void = { _, _ in }

    private let defaults: UserDefaults
    private var detector = BookmarkBubbleDetector()
    private var armed: (pid: pid_t, bundleId: String, channel: String)?
    private var loop: Task<Void, Never>?
    private var lastScan: TimeInterval = 0
    private var observer: NSObjectProtocol?

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
    }

    func start() {
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

    /// The person answered or the panel withdrew: teach the detector what this bubble size means.
    func feedback(channel: String, size: BubbleSize, bookmarked: Bool) {
        guard let entry = Self.browsers.first(where: { $0.channel == channel }) else { return }
        var memory = BubbleMemory.load(entry.bundleId, defaults: defaults)
        var learning = BookmarkBubbleDetector(learned: memory.learned, refused: memory.refused)
        if bookmarked { learning.confirm(size) } else { learning.refuse(size) }
        memory.learned = learning.learned
        memory.refused = learning.refused
        memory.save(entry.bundleId, defaults: defaults)
        if armed?.bundleId == entry.bundleId {
            detector.learned = memory.learned
            detector.refused = memory.refused
        }
    }

    private func frontmostChanged(_ app: NSRunningApplication?) {
        guard let app, let bundle = app.bundleIdentifier,
              let entry = Self.browsers.first(where: { $0.bundleId == bundle }), isWanted(entry.channel) else {
            disarm()
            return
        }
        if armed?.pid == app.processIdentifier { return }
        let memory = BubbleMemory.load(bundle, defaults: defaults)
        detector = BookmarkBubbleDetector(learned: memory.learned, refused: memory.refused)
        detector.baseline(Self.windows(of: app.processIdentifier))
        armed = (app.processIdentifier, bundle, entry.channel)
        loop?.cancel()
        loop = Task { @MainActor [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: BookmarkBubblePolicy.tick)
                self?.tick()
            }
        }
    }

    private func disarm() {
        loop?.cancel()
        loop = nil
        armed = nil
    }

    private func tick() {
        guard let armed else { return }
        let age = Self.inputAge()
        if let age, age > BookmarkBubblePolicy.scanAfterInput { return }
        let now = ProcessInfo.processInfo.systemUptime
        guard now - lastScan >= BookmarkBubblePolicy.scanEvery else { return }
        lastScan = now
        guard let bubble = detector.observe(Self.windows(of: armed.pid), inputAge: age),
              isWanted(armed.channel) else { return }
        onBubble(armed.channel, BubbleSize(bubble.bounds))
    }

    /// Seconds since the person's last key or click, system-wide; nil when the system does not say (a value past a
    /// day means it does not).
    static func inputAge() -> TimeInterval? {
        let key = CGEventSource.secondsSinceLastEventType(.combinedSessionState, eventType: .keyDown)
        let click = CGEventSource.secondsSinceLastEventType(.combinedSessionState, eventType: .leftMouseDown)
        let age = min(key, click)
        return age.isFinite && age < 86_400 ? age : nil
    }

    /// `pid`'s on-screen windows from the window list: number, layer and bounds only.
    static func windows(of pid: pid_t) -> [ListedWindow] {
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
