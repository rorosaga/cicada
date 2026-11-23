import AppKit
import ApplicationServices
import OSLog

// G221 (B, owner 2026-11-23: "if accessibility solves all this, it should be the one we implement, but also important
// to have it work on different languages") — noticing the person's own save inside a site, from the control they
// clicked. Three parts: a pure rule (`SiteSaveRule`), the one reader that asks macOS about the click
// (`SiteSaveReader`), and the watcher that ties them to a click in a browser (`SiteSaveWatcher`).
//
// **No words are matched, in any language.** A save control is recognised by where it sits (the post's own link
// beside it, its place among the row's buttons) and a save by what changes after the click (the control's label, the
// row's counts). A layout this does not know reads as nothing: no question, never a wrong one.
//
// **What is read:** the control under the person's own click and the row of controls it sits in, in the front
// browser only. Never the feed, another post, a message, or anything the person did not click.

/// One thing in the row around a click: its role (`AXButton`, `AXPopUpButton`, `AXLink` …), its label as the page
/// gives it (never matched, only compared with itself a moment later), and its link when it is one.
struct SiteSaveNode: Equatable, Sendable {
    var role: String
    var label: String = ""
    var url: String? = nil
}

/// What was read around one click: the row in reading order, which of its nodes was clicked, the row's own label
/// (on X the counts, as words), and the address of the page it is on.
struct SiteSaveReading: Equatable, Sendable {
    var row: [SiteSaveNode]
    var clicked: Int
    var rowLabel: String = ""
    var page: String? = nil
}

/// A post a save control belongs to.
struct SiteSaveItem: Equatable, Sendable {
    /// The site's key in `saved_lists.PLATFORMS` and the origin its saves are stored under.
    var site: String
    var origin: String
    /// The post's canonical link, the spelling `saved_lists.canonical` stores.
    var url: String
    var title: String
}

enum SiteSaveRule {
    enum Outcome: String, Equatable, Sendable {
        /// The control changed and the row's counts went up by one.
        case saved
        /// The control changed and the counts went down by one.
        case unsaved
        /// The control changed and the counts say nothing (they are rounded, or did not move yet).
        case changed
        /// Nothing changed: the click was not a save, or the site refused it.
        case none
    }

    /// Why a click is not a save control (logged as this word, never with what was clicked).
    enum Refusal: String, Error, Equatable, Sendable {
        case notAButton, noPostLink, notTheSaveSlot, unknownSite
    }

    static let plainButton = "AXButton"
    static let link = "AXLink"

    // X: a post's row is reply, repost, like, the views link, bookmark, share. Repost and share open menus (pop-up
    // buttons); reply, like and bookmark are plain buttons. The views link is the post's own link + `/analytics`.
    private static let xHost = #"https?://(?:www\.|mobile\.)?(?:x|twitter)\.com"#
    private static let xViews = try! NSRegularExpression(
        pattern: "^\(xHost)/([A-Za-z0-9_]{1,15})/status/([0-9]{1,20})/analytics/?$", options: [.caseInsensitive])
    private static let xPost = try! NSRegularExpression(
        pattern: "^\(xHost)/([A-Za-z0-9_]{1,15})/status/([0-9]{1,20})/?(?:[?#].*)?$", options: [.caseInsensitive])

    private static func xItem(_ url: String?, _ pattern: NSRegularExpression) -> SiteSaveItem? {
        guard let url, let found = pattern.firstMatch(in: url, range: NSRange(url.startIndex..., in: url)),
              let user = Range(found.range(at: 1), in: url), let id = Range(found.range(at: 2), in: url) else {
            return nil
        }
        return SiteSaveItem(site: "x", origin: "x-bookmarks", url: "https://x.com/\(url[user])/status/\(url[id])",
                            title: "Post by @\(url[user])")
    }

    /// The post whose save control was clicked, or why this click is not one.
    ///
    /// On X two layouts are known. **In a timeline** the row holds the post's views link, and the save control is the
    /// first plain button after it. **On a post's own page** the open post's row has no views link: there the save
    /// control is the last plain button of a row with at least three, and the post is the page itself.
    static func item(_ reading: SiteSaveReading) -> Result<SiteSaveItem, Refusal> {
        guard reading.row.indices.contains(reading.clicked), reading.row[reading.clicked].role == plainButton else {
            return .failure(.notAButton)
        }
        let views = reading.row.indices.filter { reading.row[$0].role == link && xItem(reading.row[$0].url, xViews) != nil }
        if let anchor = views.last(where: { $0 < reading.clicked }), views.count == 1,
           let item = xItem(reading.row[anchor].url, xViews) {
            let next = reading.row.indices.first { $0 > anchor && reading.row[$0].role == plainButton }
            return next == reading.clicked ? .success(item) : .failure(.notTheSaveSlot)
        }
        guard views.isEmpty else { return .failure(.notTheSaveSlot) }
        guard let page = reading.page, page.range(of: "^\(xHost)/", options: [.regularExpression, .caseInsensitive]) != nil
        else { return .failure(.unknownSite) }
        guard let item = xItem(page, xPost) else { return .failure(.noPostLink) }
        let plain = reading.row.indices.filter { reading.row[$0].role == plainButton }
        return plain.count >= 3 && plain.last == reading.clicked ? .success(item) : .failure(.notTheSaveSlot)
    }

    /// The whole numbers a label holds, in order ("20 replies, 1,204 likes" → [20, 1204]). A digit group separator
    /// between digits is part of the number; a rounded count ("1.2K") is read as it is written and simply never
    /// moves by one.
    static func numbers(in label: String) -> [Int] {
        var out: [Int] = [], current: [Int] = [], pendingSeparator = false
        func flush() {
            // A count too long to be one is not a count (an id in a label): dropped, never an overflow.
            if !current.isEmpty, current.count <= 15 { out.append(current.reduce(0) { $0 * 10 + $1 }) }
            current = []
            pendingSeparator = false
        }
        for ch in label {
            if let digit = ch.wholeNumberValue, (0...9).contains(digit) {   // any script's digits, not only 0-9
                current.append(digit)
                pendingSeparator = false
            } else if !current.isEmpty, !pendingSeparator, ",.\u{00A0}\u{202F}\u{066C}'".contains(ch) {
                pendingSeparator = true          // kept only if a digit follows
            } else {
                flush()
            }
        }
        flush()
        return out
    }

    /// +1 when exactly one count went up by one (or a new count of 1 appeared, a zero count being left out of the
    /// label), −1 for the reverse, nil when the counts say nothing.
    static func step(before: [Int], after: [Int]) -> Int? {
        if before.count == after.count {
            let moved = zip(before, after).filter { $0 != $1 }
            guard moved.count == 1, let (was, now) = moved.first, abs(now - was) == 1 else { return nil }
            return now - was
        }
        func without(_ list: [Int], oneFrom other: [Int]) -> Bool {
            guard list.count == other.count + 1 else { return false }
            return list.indices.contains { index in
                list[index] == 1 && Array(list[..<index] + list[(index + 1)...]) == other
            }
        }
        if without(after, oneFrom: before) { return 1 }
        if without(before, oneFrom: after) { return -1 }
        return nil
    }

    /// What the click did, from the same row read before it and a moment after.
    static func outcome(before: SiteSaveReading, after: SiteSaveReading) -> Outcome {
        guard before.row.indices.contains(before.clicked), after.row.indices.contains(after.clicked),
              before.row[before.clicked].label != after.row[after.clicked].label else { return .none }
        switch step(before: numbers(in: before.rowLabel), after: numbers(in: after.rowLabel)) {
        case .some(1): return .saved
        case .some(-1): return .unsaved
        default: return .changed
        }
    }
}

/// The one place that asks macOS about another app's interface for a save. Blocking calls with a short timeout, so
/// every read runs off the main thread.
enum SiteSaveReader {
    static let timeout: Float = 0.25
    static let logger = Logger(subsystem: "com.cicada.app", category: "site-save")
    /// When the row is read again after a click: once the page has answered, and twice more for a slow one.
    static let looks: [TimeInterval] = [0.6, 1.2, 2.0]
    /// Measured 2026-11-23 on Chrome: the first answer about a point nobody asked about before is often a nearby
    /// element, and the same question a moment later is answered exactly (the browser works the true answer out in
    /// the background). So a read that finds no save control is asked once more after this long.
    static let secondAsk: TimeInterval = 0.05

    /// `read`, asked a second time when the first answer names no save control.
    static func settledRead(pid: pid_t, at point: CGPoint) async -> SiteSaveReading? {
        let first = read(pid: pid, at: point)
        if let first, case .success = SiteSaveRule.item(first) { return first }
        try? await Task.sleep(nanoseconds: UInt64(secondAsk * 1_000_000_000))
        return read(pid: pid, at: point) ?? first
    }
    /// How far up from the click the row may be, and how many nodes of it are read.
    static let maxAncestors = 6
    static let maxNodes = 80

    private static func string(_ element: AXUIElement, _ attribute: String) -> String? {
        var value: CFTypeRef?
        guard AXUIElementCopyAttributeValue(element, attribute as CFString, &value) == .success else { return nil }
        if let text = value as? String { return text }
        if let url = value as? URL { return url.absoluteString }
        return nil
    }

    private static func element(_ element: AXUIElement, _ attribute: String) -> AXUIElement? {
        var value: CFTypeRef?
        guard AXUIElementCopyAttributeValue(element, attribute as CFString, &value) == .success, let value,
              CFGetTypeID(value) == AXUIElementGetTypeID() else { return nil }
        return (value as! AXUIElement)
    }

    private static func children(_ element: AXUIElement) -> [AXUIElement] {
        var value: CFTypeRef?
        guard AXUIElementCopyAttributeValue(element, kAXChildrenAttribute as CFString, &value) == .success else {
            return []
        }
        return value as? [AXUIElement] ?? []
    }

    private static func label(_ element: AXUIElement) -> String {
        let described = string(element, kAXDescriptionAttribute as String) ?? ""
        return described.isEmpty ? (string(element, kAXTitleAttribute as String) ?? "") : described
    }

    /// How far outside a button's own frame a click still belongs to it.
    static let halo: CGFloat = 14

    private static func frame(_ element: AXUIElement) -> CGRect? {
        var position: CFTypeRef?, size: CFTypeRef?
        guard AXUIElementCopyAttributeValue(element, kAXPositionAttribute as CFString, &position) == .success,
              AXUIElementCopyAttributeValue(element, kAXSizeAttribute as CFString, &size) == .success,
              let position, let size, CFGetTypeID(position) == AXValueGetTypeID(),
              CFGetTypeID(size) == AXValueGetTypeID() else { return nil }
        var origin = CGPoint.zero, extent = CGSize.zero
        guard AXValueGetValue(position as! AXValue, .cgPoint, &origin),
              AXValueGetValue(size as! AXValue, .cgSize, &extent), extent.width > 0, extent.height > 0 else { return nil }
        return CGRect(origin: origin, size: extent)
    }

    /// The button the hit element is, or sits inside; `other` when it sits inside a link or a menu button instead
    /// (a click on the neighbouring control is never handed to the save control beside it).
    private static func enclosingButton(of hit: AXUIElement) -> (button: AXUIElement?, other: Bool) {
        var node = hit
        for _ in 0...4 {
            let role = string(node, kAXRoleAttribute as String) ?? ""
            if role == SiteSaveRule.plainButton { return (node, false) }
            if isControl(role) { return (nil, true) }
            guard let parent = element(node, kAXParentAttribute as String) else { break }
            node = parent
        }
        return (nil, false)
    }

    /// The plain button whose frame, widened by `halo`, holds the point: looked for under the element that was hit,
    /// then under its parent and grandparent, never across the whole page.
    private static func nearestButton(around hit: AXUIElement, to point: CGPoint) -> AXUIElement? {
        var scope = hit
        for level in 0..<3 {
            if level > 0 {
                guard let parent = element(scope, kAXParentAttribute as String) else { return nil }
                scope = parent
            }
            guard string(scope, kAXRoleAttribute as String) != "AXWebArea" else { return nil }
            var best: (button: AXUIElement, distance: CGFloat)?
            var stack = Array(children(scope).reversed()), seen = 0
            while let next = stack.popLast(), seen < maxNodes {
                seen += 1
                let role = string(next, kAXRoleAttribute as String) ?? ""
                if role == SiteSaveRule.plainButton {
                    guard let box = frame(next), box.insetBy(dx: -halo, dy: -halo).contains(point) else { continue }
                    let distance = hypot(box.midX - point.x, box.midY - point.y)
                    if best == nil || distance < best!.distance { best = (next, distance) }
                } else if !isControl(role) {
                    stack.append(contentsOf: children(next).reversed())
                }
            }
            if let best { return best.button }
        }
        return nil
    }

    private static func isControl(_ role: String) -> Bool {
        role == SiteSaveRule.plainButton || role == "AXPopUpButton" || role == SiteSaveRule.link
    }

    /// Chromium builds a page's accessibility tree only for an app that asks. Asked once per browser process, when
    /// it comes to the front; a browser that does not know the attribute ignores it (Safari needs nothing).
    static func askForWebContent(pid: pid_t) {
        let app = AXUIElementCreateApplication(pid)
        AXUIElementSetMessagingTimeout(app, timeout)
        AXUIElementSetAttributeValue(app, "AXManualAccessibility" as CFString, kCFBooleanTrue)
    }

    /// The row around the control at `point` (top-left screen coordinates) in the app `pid`, or nil when the click
    /// landed on no button, or on one that sits in no row of controls.
    static func read(pid: pid_t, at point: CGPoint) -> SiteSaveReading? {
        let app = AXUIElementCreateApplication(pid)
        AXUIElementSetMessagingTimeout(app, timeout)
        var hit: AXUIElement?
        guard AXUIElementCopyElementAtPosition(app, Float(point.x), Float(point.y), &hit) == .success, let hit
        else { return nil }
        // The click lands on the icon inside the button (climb to it), or beside it: a site's control can be far
        // smaller to macOS than the round area that takes the click (measured on X: 17 × 19 pt inside a ~35 pt
        // circle, so a click a little left or right of the icon is on no button at all).
        let enclosing = enclosingButton(of: hit)
        guard !enclosing.other, let button = enclosing.button ?? nearestButton(around: hit, to: point) else {
            return nil
        }
        // The row: the nearest ancestor that holds at least three controls (the button and its neighbours).
        var ancestor = button
        for _ in 0..<maxAncestors {
            guard let parent = element(ancestor, kAXParentAttribute as String) else { return nil }
            ancestor = parent
            guard string(ancestor, kAXRoleAttribute as String) != "AXWebArea" else { return nil }
            var row: [SiteSaveNode] = [], clicked: Int?
            var stack = Array(children(ancestor).reversed()), seen = 0
            while let next = stack.popLast(), seen < maxNodes {
                seen += 1
                let role = string(next, kAXRoleAttribute as String) ?? ""
                if isControl(role) {
                    if CFEqual(next, button) { clicked = row.count }
                    row.append(SiteSaveNode(role: role, label: label(next),
                                            url: role == SiteSaveRule.link ? string(next, kAXURLAttribute as String) : nil))
                } else {
                    stack.append(contentsOf: children(next).reversed())
                }
            }
            if let clicked, row.count >= 3 {
                // The counts are the label of the row's own group, which may sit a wrapper or two above.
                var labelled = ancestor, words = label(ancestor)
                for _ in 0..<2 where words.isEmpty {
                    guard let parent = element(labelled, kAXParentAttribute as String),
                          string(parent, kAXRoleAttribute as String) != "AXWebArea" else { break }
                    labelled = parent
                    words = label(parent)
                }
                // The page's address is needed only when the row names no post itself (a walk to the top).
                let namesAPost = row.contains { $0.role == SiteSaveRule.link && $0.url != nil }
                return SiteSaveReading(row: row, clicked: clicked, rowLabel: words,
                                       page: namesAPost ? nil : page(above: ancestor))
            }
        }
        return nil
    }

    /// The address of the page an element is on: its web area's own.
    private static func page(above start: AXUIElement) -> String? {
        var node = start
        for _ in 0..<80 {
            if string(node, kAXRoleAttribute as String) == "AXWebArea" { return string(node, kAXURLAttribute as String) }
            guard let parent = element(node, kAXParentAttribute as String) else { return nil }
            node = parent
        }
        return nil
    }
}

/// Developer-only for now (`defaults write com.rorosaga.cicada cicada.debug.siteSaveObserve -bool YES`, a developer
/// build, Accessibility already granted — never asked for here): a save noticed on X shows the question for that
/// post through the notch's write-nothing preview. Nothing is saved, posted or remembered. It exists to measure the
/// rule on real pages (other languages, a post's own page, a rounded count) before anything is built on it.
enum SiteSaveObserve {
    static let defaultsKey = "cicada.debug.siteSaveObserve"

    static func isAvailable(defaults: UserDefaults = .standard, runtime: CicadaRuntime = .current) -> Bool {
        defaults.bool(forKey: defaultsKey) && runtime.distribution == .developer
    }
}

/// Watches the pointer and the person's clicks in the front browser and reports a save. One global monitor while a
/// browser is in front (mouse moves and mouse-downs; the same permission-free kind the bookmark bubble uses); the
/// reads need the Accessibility grant, and without it nothing is armed.
///
/// **The state before the click is read when the pointer comes to rest on a save control, not at the click.** Two
/// measured reasons (2026-11-23): the browser's first answer about a fresh point is often wrong (`secondAsk`), and
/// a tap is over before any read could finish. So a rest of `restDelay` on a control reads its row and keeps it in
/// memory (never stored; replaced by the next rest, dropped when the browser leaves the front); a click near it
/// then compares that with the row a moment later. A rest on anything else keeps nothing.
@MainActor
final class SiteSaveWatcher {
    /// The browsers whose pages are read (`BrowserInventory`'s supported ones).
    static let browsers: Set<String> = Set(BrowserInventory.catalog.filter(\.supported).map(\.bundleId))
    /// How long the pointer is still before the control under it is read.
    static let restDelay: TimeInterval = 0.07
    /// How long a rest's reading stays usable, and how far from it a click may land.
    nonisolated static let hoverFresh: TimeInterval = 60
    nonisolated static let hoverReach: CGFloat = 24

    struct Hover: Equatable, Sendable {
        var item: SiteSaveItem
        var reading: SiteSaveReading
        var point: CGPoint
        var at: TimeInterval
    }

    var isWanted: () -> Bool = { false }
    var trusted: () -> Bool = { AXIsProcessTrusted() }
    /// A click changed a save control: the post, and what the counts say about the direction.
    var onOutcome: ((SiteSaveItem, SiteSaveRule.Outcome) -> Void)?

    private var observer: NSObjectProtocol?
    private var monitor: Any?
    private var armedPid: pid_t?
    private var pending: Task<Void, Never>?
    private var rest: Task<Void, Never>?
    private(set) var hovered: Hover?

    func start() {
        guard observer == nil else { return }
        observer = NSWorkspace.shared.notificationCenter.addObserver(
            forName: NSWorkspace.didActivateApplicationNotification, object: nil, queue: .main) { [weak self] note in
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

    private func frontmostChanged(_ app: NSRunningApplication?) {
        guard let app, let bundle = app.bundleIdentifier, Self.browsers.contains(bundle), isWanted() else {
            disarm()
            return
        }
        guard trusted() else {
            SiteSaveReader.logger.info("a browser is in front; Accessibility is not granted, so nothing is watched")
            disarm()
            return
        }
        SiteSaveReader.logger.info("watching the front browser")
        let pid = app.processIdentifier
        if armedPid == pid, monitor != nil { return }
        disarm()
        armedPid = pid
        Task.detached(priority: .utility) { SiteSaveReader.askForWebContent(pid: pid) }
        monitor = NSEvent.addGlobalMonitorForEvents(matching: [.leftMouseDown, .mouseMoved]) { [weak self] event in
            let location = NSEvent.mouseLocation, down = event.type == .leftMouseDown
            MainActor.assumeIsolated { down ? self?.clicked(atAppKit: location) : self?.moved(atAppKit: location) }
        }
    }

    private func disarm() {
        if let monitor { NSEvent.removeMonitor(monitor) }
        monitor = nil
        armedPid = nil
        pending?.cancel()
        pending = nil
        rest?.cancel()
        rest = nil
        hovered = nil
    }

    private func screenPoint(_ appKit: CGPoint) -> CGPoint {
        BookmarkBubblePolicy.windowListPoint(appKit, primaryHeight: NSScreen.screens.first?.frame.height ?? 0)
    }

    /// The pointer moved: once it has been still for `restDelay`, read what it rests on.
    private func moved(atAppKit location: CGPoint) {
        guard let pid = armedPid else { return }
        let point = screenPoint(location)
        rest?.cancel()
        rest = Task { [weak self] in
            try? await Task.sleep(nanoseconds: UInt64(Self.restDelay * 1_000_000_000))
            guard !Task.isCancelled else { return }
            let reading = await Task.detached(priority: .utility) {
                await SiteSaveReader.settledRead(pid: pid, at: point)
            }.value
            guard !Task.isCancelled, let self, self.armedPid == pid else { return }
            if let reading, case let .success(item) = SiteSaveRule.item(reading) {
                self.hovered = Hover(item: item, reading: reading, point: point, at: SaveWhyTimings.now())
            } else {
                self.hovered = nil
            }
        }
    }

    /// The reading a click may lean on: a rest close to it in place and time.
    nonisolated static func usable(_ hover: Hover?, at point: CGPoint, now: TimeInterval) -> Hover? {
        guard let hover, now - hover.at <= hoverFresh,
              hypot(hover.point.x - point.x, hover.point.y - point.y) <= hoverReach else { return nil }
        return hover
    }

    private func clicked(atAppKit location: CGPoint) {
        guard let pid = armedPid else { return }
        let point = screenPoint(location)
        let hover = Self.usable(hovered, at: point, now: SaveWhyTimings.now())
        rest?.cancel()
        pending?.cancel()
        pending = Task { [weak self] in
            let found = await Self.follow(pid: pid, point: point, hover: hover)
            guard !Task.isCancelled, let found else { return }
            // The control's new state is what a second click on it starts from (the pointer has not moved).
            self?.hovered = Hover(item: found.item, reading: found.seen, point: point, at: SaveWhyTimings.now())
            if found.outcome != .none { self?.onOutcome?(found.item, found.outcome) }
        }
    }

    /// Which reading is the state before the click: the rest's when it is about the same control (or when the read
    /// at the click names none), else the read at the click itself.
    nonisolated static func before(hover: Hover?, atClick: SiteSaveReading?)
    -> (item: SiteSaveItem, reading: SiteSaveReading)? {
        let clicked = atClick.flatMap { reading in (try? SiteSaveRule.item(reading).get()).map { ($0, reading) } }
        if let hover, clicked == nil || clicked?.0 == hover.item { return (hover.item, hover.reading) }
        return clicked.map { (item: $0.0, reading: $0.1) }
    }

    nonisolated static func follow(pid: pid_t, point: CGPoint, hover: Hover?)
    async -> (item: SiteSaveItem, outcome: SiteSaveRule.Outcome, seen: SiteSaveReading)? {
        let started = SaveWhyTimings.now()
        let atClick = await Task.detached(priority: .userInitiated) { SiteSaveReader.read(pid: pid, at: point) }.value
        guard let (item, before) = before(hover: hover, atClick: atClick) else { return nil }
        var outcome = SiteSaveRule.Outcome.none, seen = before
        for look in SiteSaveReader.looks {
            let wait = look - (SaveWhyTimings.now() - started)
            if wait > 0 { try? await Task.sleep(nanoseconds: UInt64(wait * 1_000_000_000)) }
            if Task.isCancelled { return nil }
            let after = await Task.detached(priority: .userInitiated) {
                await SiteSaveReader.settledRead(pid: pid, at: point)
            }.value
            // The same control must be under the point: a look that finds another, or none, is tried again.
            guard let after, case let .success(same) = SiteSaveRule.item(after), same == item else { continue }
            seen = after
            outcome = SiteSaveRule.outcome(before: before, after: after)
            if outcome != .none { break }
        }
        SiteSaveReader.logger.info("""
            save control on \(item.site, privacy: .public): \(outcome.rawValue, privacy: .public) \
            after \(SaveWhyTimings.ms(SaveWhyTimings.now() - started)) ms; \
            before from \(hover != nil && hover?.reading == before ? "rest" : "click", privacy: .public), \
            label length \(before.row[before.clicked].label.count) → \(seen.row[seen.clicked].label.count), \
            counts \(SiteSaveRule.numbers(in: before.rowLabel).count) → \(SiteSaveRule.numbers(in: seen.rowLabel).count)
            """)
        return (item, outcome, seen)
    }
}
