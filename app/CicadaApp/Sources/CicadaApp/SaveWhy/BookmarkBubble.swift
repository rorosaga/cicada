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
/// - followed within `inputWindow` (400 ms) by **any new small window** of Chrome's, anchored under the toolbar at the
///   right of that browser window (`isAnchored`: no exact size, nothing learned, nothing refused),
///
/// opens the question at once, pending. One new bookmark in the app's own diff of the file binds the link; none within
/// `SaveWhyPolicy.pendingBound` (or a bookmark removed instead — "Edit bookmark", then Remove) withdraws it, keeping
/// nothing. A tooltip (layer 103 measured) or a menu is never one: they sit above `maxLayer`.
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
    /// A "small window": anything between a tooltip and a browser window. Generous on purpose — the position decides.
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

/// The pure half: after a toolbar click, which new window (if any) is the bookmark bubble. Fed the window lists read
/// during the burst and the seconds since the click.
struct BookmarkBubbleDetector: Equatable {
    private(set) var known: Set<Int> = []

    /// The windows on screen at the click are never new.
    mutating func baseline(_ windows: [ListedWindow]) {
        known = Set(windows.map(\.number))
    }

    /// The browser window whose toolbar band `point` landed in, if any.
    static func toolbarWindow(at point: CGPoint, in windows: [ListedWindow]) -> ListedWindow? {
        windows.first { BookmarkBubblePolicy.isBrowserWindow($0) && BookmarkBubblePolicy.isToolbarClick(point, on: $0.bounds) }
    }

    /// The bubble among `windows`, at most one: a window not on screen at the click, at a bubble's layer, small and
    /// anchored under the toolbar at the right of a browser window of the same app, within `inputWindow` of the click.
    mutating func observe(_ windows: [ListedWindow], sinceClick: TimeInterval) -> ListedWindow? {
        let fresh = windows.filter { !known.contains($0.number) }
        known.formUnion(windows.map(\.number))
        guard sinceClick <= BookmarkBubblePolicy.inputWindow else { return nil }
        let browsers = windows.filter(BookmarkBubblePolicy.isBrowserWindow)
        return fresh.first { candidate in
            candidate.layer >= 0 && candidate.layer <= BookmarkBubblePolicy.maxLayer
                && browsers.contains { $0.pid == candidate.pid && $0.number != candidate.number
                    && BookmarkBubblePolicy.isAnchored(candidate.bounds, on: $0.bounds) }
        }
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
    private var armed: (pid: pid_t, bundleId: String, channel: String)?
    private var monitor: Any?
    private var burst: Task<Void, Never>?
    private var observer: NSObjectProtocol?
    /// How many window-list reads this watcher made — for the efficiency test, never shown.
    private(set) var reads = 0

    init(defaults: UserDefaults = .standard,
         windows: @escaping (pid_t) -> [ListedWindow] = BookmarkBubbleWatcher.liveWindows(of:),
         clock: @escaping () -> TimeInterval = { ProcessInfo.processInfo.systemUptime }) {
        self.defaults = defaults
        self.windows = windows
        self.clock = clock
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

    /// G191 v4 — v3 kept learned, refused and missed bubble sizes per browser in this Mac's defaults; v4 learns
    /// nothing, so they are removed (once, harmlessly, on every start).
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
        detector.baseline(now)
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
            }
            self?.burst = nil
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
