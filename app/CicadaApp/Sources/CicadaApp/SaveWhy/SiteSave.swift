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
/// (on X the counts, as words), the address of the page, and — when the row itself names no post — the post links of
/// the nearest enclosing block that holds any (`links`), with that block's own label (`context`, the post as the page
/// describes it).
struct SiteSaveReading: Equatable, Sendable {
    var row: [SiteSaveNode]
    var clicked: Int
    var rowLabel: String = ""
    var page: String? = nil
    var links: [String] = []
    /// How many of `links` come before the row in reading order; they are listed nearest first, then the ones after.
    var linksBefore: Int = 0
    var context: String = ""
    /// The label of the post's own link inside that block (on X its time, "5h"), which the block's label repeats.
    var linkLabel: String = ""
}

/// A post a save control belongs to.
struct SiteSaveItem: Equatable, Sendable {
    /// The site's key (`SiteSaveSite.key`, the backend's `saved_lists.PLATFORMS` key) and the origin its saves are
    /// stored under.
    var site: String
    var origin: String
    /// The post's canonical link, the spelling the backend stores.
    var url: String
    var title: String
}

/// One site Cicada can notice a save on. Everything here is structure and addresses: no word of the site's
/// interface, in any language.
struct SiteSaveSite: Sendable {
    let key: String
    let name: String
    let origin: String
    /// The site's own hosts (the page must be on one).
    let hosts: [String]
    /// A link of this site that is one post: `(pattern, canonical template, title template)`, `$1`… the captures.
    let items: [(pattern: NSRegularExpression, url: String, title: String)]
    /// A link that sits in the row beside the save control and names the post (X's views link), if the site has one.
    let rowAnchor: (pattern: NSRegularExpression, url: String, title: String)?
    /// Where the save control sits among the row's controls.
    let slot: Slot
    /// The person's own saved list on this site: a control toggled there is leaving the list, never joining it.
    let listPages: [NSRegularExpression]

    enum Slot: Sendable {
        /// The first plain button after the row's anchor link; with no anchor in the row (a post's own page), the
        /// last plain button of a row with at least `least`.
        case afterAnchorElseLast(least: Int)
        /// The last plain button of a row with at least `least` plain buttons (Instagram: like … save).
        case last(least: Int)
        /// A plain button directly followed by a menu button (GitHub: Star, then its lists menu).
        case beforeMenu
        /// The plain button directly before the row's last plain button, in a row with at least `least`
        /// (TikTok: like, comments, favourite, share).
        case beforeLast(least: Int)
    }

    func onHost(_ url: String?) -> Bool {
        guard let host = url.flatMap({ URL(string: $0)?.host?.lowercased() }) else { return false }
        return hosts.contains { host == $0 || host.hasSuffix("." + $0) }
    }

    func item(_ url: String?) -> SiteSaveItem? { Self.match(url, items).map(make) }
    func anchorItem(_ url: String?) -> SiteSaveItem? { rowAnchor.flatMap { Self.match(url, [$0]) }.map(make) }
    func isListPage(_ url: String?) -> Bool {
        guard let url else { return false }
        return listPages.contains { $0.firstMatch(in: url, range: NSRange(url.startIndex..., in: url)) != nil }
    }

    private func make(_ found: (url: String, title: String)) -> SiteSaveItem {
        SiteSaveItem(site: key, origin: origin, url: found.url, title: found.title)
    }

    private static func match(_ url: String?, _ rules: [(pattern: NSRegularExpression, url: String, title: String)])
    -> (url: String, title: String)? {
        guard let url else { return nil }
        let whole = NSRange(url.startIndex..., in: url)
        for rule in rules {
            guard let found = rule.pattern.firstMatch(in: url, range: whole) else { continue }
            return (rule.pattern.replacementString(for: found, in: url, offset: 0, template: rule.url),
                    rule.pattern.replacementString(for: found, in: url, offset: 0, template: rule.title))
        }
        return nil
    }

    private static func re(_ pattern: String) -> NSRegularExpression {
        try! NSRegularExpression(pattern: pattern, options: [.caseInsensitive])
    }

    private static let web = #"^https?://(?:[a-z0-9-]+\.)*"#
    /// GitHub's own first path segments, which are never an account.
    private static let githubOwn = "sponsors|stars|orgs|apps|topics|collections|trending|settings|marketplace|features|"
        + "explore|notifications|pulls|issues|search|login|join|about|pricing|enterprise|new|codespaces|users|site"

    static let x = SiteSaveSite(
        key: "x", name: "X", origin: "x-bookmarks", hosts: ["x.com", "twitter.com"],
        items: [(re(web + #"(?:x|twitter)\.com/([A-Za-z0-9_]{1,15})/status/([0-9]{1,20})/?(?:[?#].*)?$"#),
                 "https://x.com/$1/status/$2", "Post by @$1")],
        rowAnchor: (re(web + #"(?:x|twitter)\.com/([A-Za-z0-9_]{1,15})/status/([0-9]{1,20})/analytics/?$"#),
                    "https://x.com/$1/status/$2", "Post by @$1"),
        slot: .afterAnchorElseLast(least: 3),
        listPages: [re(web + #"(?:x|twitter)\.com/i/(?:bookmarks|history)(?:[/?#].*)?$"#)])

    static let instagram = SiteSaveSite(
        key: "instagram", name: "Instagram", origin: "instagram-saved", hosts: ["instagram.com"],
        // One post has several addresses (`/p/`, `/reel/`, `/reels/`, `/tv/`, with or without the account): they are
        // one post by its code, stored under the `/p/` spelling (the backend keeps the others as aliases).
        items: [(re(web + #"instagram\.com/(?:[A-Za-z0-9_.]+/)?(?:p|reel|reels|tv)/([A-Za-z0-9_-]{5,40})/?(?:[?#].*)?$"#),
                 "https://www.instagram.com/p/$1/", "Instagram post")],
        rowAnchor: nil, slot: .last(least: 4),
        listPages: [re(web + #"instagram\.com/[A-Za-z0-9_.]+/saved(?:[/?#].*)?$"#)])

    static let github = SiteSaveSite(
        key: "github", name: "GitHub", origin: "github-starred", hosts: ["github.com"],
        items: [(re(#"^https?://github\.com/(?!(?:"# + githubOwn + #")/)([A-Za-z0-9-]{1,39})/([A-Za-z0-9._-]{1,100})/?(?:[?#].*)?$"#),
                 "https://github.com/$1/$2", "$1/$2")],
        rowAnchor: nil, slot: .beforeMenu,
        listPages: [re(#"^https?://github\.com/stars(?:[/?#].*)?$"#),
                    re(#"^https?://github\.com/[A-Za-z0-9-]+\?(?:.*&)?tab=stars"#)])

    static let tiktok = SiteSaveSite(
        key: "tiktok", name: "TikTok", origin: "tiktok-saved", hosts: ["tiktok.com"],
        items: [(re(web + #"tiktok\.com/@([A-Za-z0-9_.]{1,40})/(video|photo)/([0-9]{5,25})/?(?:[?#].*)?$"#),
                 "https://www.tiktok.com/@$1/$2/$3", "TikTok by @$1")],
        rowAnchor: nil, slot: .beforeLast(least: 4),
        listPages: [])

    static let all: [SiteSaveSite] = [x, instagram, github, tiktok]
    static func named(_ key: String) -> SiteSaveSite? { all.first { $0.key == key } }
    /// A link that is a post of any known site (what the reader looks for around a click).
    static func isItemLink(_ url: String) -> Bool { all.contains { $0.item(url) != nil } }
}

enum SiteSaveRule {
    enum Outcome: String, Equatable, Sendable {
        /// The control changed, and the evidence says the post joined the saved list.
        case saved
        /// The control changed, and the evidence says it left.
        case unsaved
        /// The control changed and nothing says which way.
        case changed
        /// Nothing changed: the click was not a save, or the site refused it.
        case none
    }

    /// Why a click is not a save control (logged as this word, never with what was clicked).
    enum Refusal: String, Error, Equatable, Sendable {
        case notAButton, noPostLink, notTheSaveSlot, unknownSite, twoPosts
    }

    static let plainButton = "AXButton"
    static let menuButton = "AXPopUpButton"
    static let link = "AXLink"

    /// The site a reading is on: by its page's address, else by the one site its links belong to.
    static func site(of reading: SiteSaveReading) -> SiteSaveSite? {
        if let page = reading.page { return SiteSaveSite.all.first { $0.onHost(page) } }
        let urls = reading.row.compactMap(\.url) + reading.links
        return SiteSaveSite.all.first { site in urls.contains { site.anchorItem($0) != nil || site.item($0) != nil } }
    }

    private static func inSlot(_ slot: SiteSaveSite.Slot, _ reading: SiteSaveReading, anchor: Int?) -> Bool {
        let row = reading.row, clicked = reading.clicked
        let plain = row.indices.filter { row[$0].role == plainButton }
        switch slot {
        case let .afterAnchorElseLast(least):
            if let anchor { return row.indices.first { $0 > anchor && row[$0].role == plainButton } == clicked }
            return plain.count >= least && plain.last == clicked
        case let .last(least):
            return plain.count >= least && plain.last == clicked
        case .beforeMenu:
            return row.indices.contains(clicked + 1) && row[clicked + 1].role == menuButton
        case let .beforeLast(least):
            return plain.count >= least && plain.dropLast().last == clicked
        }
    }

    /// The post whose save control was clicked, or why this click is not one.
    ///
    /// The post is named, in order, by the row's own anchor link (X in a timeline), by the one post the enclosing
    /// block's links name (Instagram's time link, GitHub's repository link), or by the page itself when it is a
    /// post's own page. Two different posts in the enclosing block is no answer.
    static func item(_ reading: SiteSaveReading, sites: [SiteSaveSite] = SiteSaveSite.all) -> Result<SiteSaveItem, Refusal> {
        guard reading.row.indices.contains(reading.clicked), reading.row[reading.clicked].role == plainButton else {
            return .failure(.notAButton)
        }
        guard let site = site(of: reading), sites.contains(where: { $0.key == site.key }) else {
            return .failure(.unknownSite)
        }
        let anchors = reading.row.indices.filter { site.anchorItem(reading.row[$0].url) != nil }
        guard anchors.count <= 1 else { return .failure(.notTheSaveSlot) }
        guard inSlot(site.slot, reading, anchor: anchors.first) else { return .failure(.notTheSaveSlot) }
        if let anchor = anchors.first, let item = site.anchorItem(reading.row[anchor].url) { return .success(item) }
        func distinct(_ urls: [String]) -> [SiteSaveItem] {
            urls.compactMap { site.item($0) }.reduce(into: [SiteSaveItem]()) { if !$0.contains($1) { $0.append($1) } }
        }
        // The row's own links (GitHub's repository link beside its star): one post, or no answer.
        let inRow = distinct(reading.row.compactMap(\.url))
        if inRow.count == 1 { return .success(inRow[0]) }
        if inRow.count > 1 { return .failure(.twoPosts) }
        // The enclosing block's: a post's own link comes before its row of controls (its time, its heading), so the
        // nearest one before the row names it, whatever else the block holds (a quoted post, the next post's head).
        if let nearest = distinct(Array(reading.links.prefix(reading.linksBefore))).first { return .success(nearest) }
        if let own = site.item(reading.page) { return .success(own) }
        // Links only after the row belong to whatever follows it (measured: Instagram's stories tray above the first
        // post), never to this row.
        return .failure(reading.links.isEmpty ? .noPostLink : .twoPosts)
    }

    /// The post's own words, cut out of the block's label without knowing any of the site's words: on X the label is
    /// "name … @handle <time> <the post> <the counts>", so the words start after the handle and the time link's own
    /// label, and end before the row's label. Empty when the block is not shaped that way (then the row is titled
    /// from its link). Capped; the backend scrubs it.
    static func text(of reading: SiteSaveReading, item: SiteSaveItem) -> String {
        guard item.site == "x", !reading.context.isEmpty,
              let handle = item.title.split(separator: " ").last.map(String.init), handle.hasPrefix("@"),
              let at = reading.context.range(of: handle + " ") else { return "" }
        var words = String(reading.context[at.upperBound...])
        if !reading.linkLabel.isEmpty, words.hasPrefix(reading.linkLabel) { words.removeFirst(reading.linkLabel.count) }
        if !reading.rowLabel.isEmpty, words.hasSuffix(reading.rowLabel) { words.removeLast(reading.rowLabel.count) }
        words = words.trimmingCharacters(in: .whitespacesAndNewlines)
        return String(words.prefix(600))
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

    /// Every count a reading shows about its post: the row's own label and each control's.
    static func counts(_ reading: SiteSaveReading) -> [Int] {
        numbers(in: reading.rowLabel) + reading.row.flatMap { numbers(in: $0.label) }
    }

    /// The two labels a save control wore, before and after, or nil when it did not change.
    static func change(before: SiteSaveReading, after: SiteSaveReading) -> (was: String, now: String)? {
        guard before.row.indices.contains(before.clicked), after.row.indices.contains(after.clicked) else { return nil }
        let was = before.row[before.clicked].label, now = after.row[after.clicked].label
        return was == now ? nil : (was, now)
    }

    /// What a site's interface calls its two states on this Mac, learned from the person's own pages (never shipped,
    /// never translated): the exact labels seen on a save control when the direction was certain.
    struct Labels: Equatable, Sendable, Codable {
        var saved: Set<String> = []
        var unsaved: Set<String> = []

        func says(was: String, now: String) -> Outcome? {
            if (unsaved.contains(was) && !unsaved.contains(now)) || (saved.contains(now) && !saved.contains(was)) {
                return .saved
            }
            if (saved.contains(was) && !saved.contains(now)) || (unsaved.contains(now) && !unsaved.contains(was)) {
                return .unsaved
            }
            return nil
        }

        mutating func learn(was: String, now: String, outcome: Outcome) {
            switch outcome {
            case .saved: unsaved.insert(was); saved.insert(now)
            case .unsaved: saved.insert(was); unsaved.insert(now)
            default: break
            }
        }
    }

    /// How many OTHER plain buttons on the page wear each of the two labels, counted after the click.
    struct Census: Equatable, Sendable {
        var was: Int
        var now: Int
        /// On a page of posts the common state is "not saved": when at least `quorum` others still wear the label the
        /// control left and none wears the one it took, it joined the saved list; the mirror image is leaving it.
        /// A page where both are worn says nothing.
        static let quorum = 2
        var says: Outcome? {
            if was >= Self.quorum, now == 0 { return .saved }
            if now >= Self.quorum, was == 0 { return .unsaved }
            return nil
        }
    }

    /// Which way a changed control went. The evidence, in order of certainty: the person's own saved list (a control
    /// toggled there is leaving it); one count moving by one; the labels this Mac already learned; the page's other
    /// posts (`Census`). With none of them the change is reported as `changed` and nobody is asked.
    static func outcome(before: SiteSaveReading, after: SiteSaveReading, site: SiteSaveSite? = nil,
                        learned: Labels = Labels(), census: Census? = nil) -> Outcome {
        guard let (was, now) = change(before: before, after: after) else { return .none }
        if let site, site.isListPage(after.page ?? before.page) { return .unsaved }
        switch step(before: counts(before), after: counts(after)) {
        case .some(1): return .saved
        case .some(-1): return .unsaved
        default: break
        }
        return learned.says(was: was, now: now) ?? census?.says ?? .changed
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
            if role == SiteSaveRule.plainButton {
                // A site may nest the button the pointer is on inside the one that is the control (measured:
                // Instagram, TikTok): the outer one is the row's.
                var outer = node, above = node
                for _ in 0..<3 {
                    guard let parent = element(above, kAXParentAttribute as String) else { break }
                    above = parent
                    if string(above, kAXRoleAttribute as String) == SiteSaveRule.plainButton { outer = above }
                }
                return (outer, false)
            }
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

    static let maxFrameNodes = 500

    /// The browser's own answer was the page itself (measured: GitHub's lists, where a star button's point resolves
    /// to the whole page even on the second ask): walk down from the page by frames, into each element whose frame
    /// holds the point, to the plain button there. Only for a hit that is the page; bounded.
    private static func buttonByFrames(under hit: AXUIElement, at point: CGPoint) -> AXUIElement? {
        guard string(hit, kAXRoleAttribute as String) == "AXWebArea" else { return nil }
        var best: (button: AXUIElement, distance: CGFloat)?
        var stack = Array(children(hit).reversed()), seen = 0
        while let next = stack.popLast(), seen < maxFrameNodes {
            seen += 1
            let role = string(next, kAXRoleAttribute as String) ?? ""
            let box = frame(next)
            if role == SiteSaveRule.plainButton {
                guard let box, box.insetBy(dx: -halo, dy: -halo).contains(point) else { continue }
                let distance = hypot(box.midX - point.x, box.midY - point.y)
                if best == nil || distance < best!.distance { best = (next, distance) }
            } else if !isControl(role) {
                // An element with no frame of its own (a wrapper) is looked into; one whose frame misses the point
                // is not.
                if let box, !box.insetBy(dx: -halo, dy: -halo).contains(point) { continue }
                stack.append(contentsOf: children(next).reversed())
            }
        }
        return best?.button
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
        // Only on a site Cicada notices saves on: everywhere else the read ends here, with the page's address and
        // nothing else looked at.
        guard let address = page(above: hit), SiteSaveSite.all.contains(where: { $0.onHost(address) }) else { return nil }
        let enclosing = enclosingButton(of: hit)
        guard !enclosing.other,
              let button = enclosing.button ?? nearestButton(around: hit, to: point) ?? buttonByFrames(under: hit, at: point)
        else { return nil }
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
                var reading = SiteSaveReading(row: row, clicked: clicked, rowLabel: words, page: address)
                // A row that names no post itself: the post links of the nearest enclosing block that holds any.
                if !row.contains(where: { $0.url.map(SiteSaveSite.isItemLink) == true }) {
                    let found = postLinks(around: ancestor)
                    reading.links = found.before.reversed() + found.after
                    reading.linksBefore = found.before.count
                }
                // The post as the page describes it: the nearest labelled block above the row whose label says more
                // than the row's own (X's article), and the label of the post's own link in it, which marks where
                // the post's words begin.
                var block = labelled
                for _ in 0..<10 {
                    guard let parent = element(block, kAXParentAttribute as String),
                          string(parent, kAXRoleAttribute as String) != "AXWebArea" else { break }
                    block = parent
                    let described = label(block)
                    guard described.count > words.count, described != words else { continue }
                    reading.context = described
                    reading.linkLabel = firstPostLinkLabel(in: block)
                    break
                }
                return reading
            }
        }
        return nil
    }

    static let maxContextAncestors = 6
    static let maxContextNodes = 160

    /// The post links (`SiteSaveSite.isItemLink`) of the nearest block above `row` that holds any, in reading order
    /// and split at the row. Climbs a few levels and reads links only; a block with none is passed over.
    private static func postLinks(around row: AXUIElement) -> (before: [String], after: [String]) {
        var block = row
        for _ in 0..<maxContextAncestors {
            guard let parent = element(block, kAXParentAttribute as String),
                  string(parent, kAXRoleAttribute as String) != "AXWebArea" else { return ([], []) }
            block = parent
            var before: [String] = [], after: [String] = [], passedRow = false
            var stack = Array(children(block).reversed()), seen = 0
            while let next = stack.popLast(), seen < maxContextNodes {
                seen += 1
                if CFEqual(next, row) {
                    passedRow = true
                    continue
                }
                let role = string(next, kAXRoleAttribute as String) ?? ""
                if role == SiteSaveRule.link {
                    guard let url = string(next, kAXURLAttribute as String), SiteSaveSite.isItemLink(url) else { continue }
                    if passedRow { after.append(url) } else { before.append(url) }
                } else if !isControl(role) {
                    stack.append(contentsOf: children(next).reversed())
                }
            }
            if !before.isEmpty || !after.isEmpty { return (before, after) }
        }
        return ([], [])
    }

    /// The label of the first link in `block` that is exactly a post (its time link), read for nothing else.
    private static func firstPostLinkLabel(in block: AXUIElement) -> String {
        var stack = Array(children(block).reversed()), seen = 0
        while let next = stack.popLast(), seen < maxContextNodes {
            seen += 1
            let role = string(next, kAXRoleAttribute as String) ?? ""
            if role == SiteSaveRule.link {
                if let url = string(next, kAXURLAttribute as String), SiteSaveSite.isItemLink(url) { return label(next) }
            } else if !isControl(role) {
                stack.append(contentsOf: children(next).reversed())
            }
        }
        return ""
    }

    /// The site the front tab of the browser `pid` is on, or nil. The window's own document address is read (the
    /// browser gives it without its page tree being switched on), compared with the sites Cicada knows, and kept
    /// nowhere.
    static func frontSite(pid: pid_t) -> SiteSaveSite? {
        let app = AXUIElementCreateApplication(pid)
        AXUIElementSetMessagingTimeout(app, timeout)
        guard let window = element(app, kAXFocusedWindowAttribute as String),
              let address = string(window, kAXDocumentAttribute as String) else { return nil }
        return SiteSaveSite.all.first { $0.onHost(address) }
    }

    static let maxCensusNodes = 3000

    /// How many other plain buttons on the page under `point` wear each of two labels (`SiteSaveRule.Census`), read
    /// after a click: the clicked control itself wears `now` and is left out. Labels are compared, never kept.
    static func census(pid: pid_t, at point: CGPoint, was: String, now: String) -> SiteSaveRule.Census? {
        let app = AXUIElementCreateApplication(pid)
        AXUIElementSetMessagingTimeout(app, timeout)
        var hit: AXUIElement?
        guard AXUIElementCopyElementAtPosition(app, Float(point.x), Float(point.y), &hit) == .success, let hit,
              let area = webArea(above: hit) else { return nil }
        var wore = 0, wears = 0
        var stack = Array(children(area).reversed()), seen = 0
        while let next = stack.popLast(), seen < maxCensusNodes {
            seen += 1
            let role = string(next, kAXRoleAttribute as String) ?? ""
            if role == SiteSaveRule.plainButton {
                let words = label(next)
                if words == was { wore += 1 } else if words == now { wears += 1 }
            } else if !isControl(role) {
                stack.append(contentsOf: children(next).reversed())
            }
        }
        return SiteSaveRule.Census(was: wore, now: max(0, wears - 1))
    }

    private static func webArea(above start: AXUIElement) -> AXUIElement? {
        var node = start
        for _ in 0..<80 {
            if string(node, kAXRoleAttribute as String) == "AXWebArea" { return node }
            guard let parent = element(node, kAXParentAttribute as String) else { return nil }
            node = parent
        }
        return nil
    }

    /// The address of the page an element is on: its web area's own.
    private static func page(above start: AXUIElement) -> String? {
        webArea(above: start).flatMap { string($0, kAXURLAttribute as String) }
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

    /// The sites the person connected (none: nothing is watched).
    var sites: () -> [SiteSaveSite] = { [] }
    var prefs = SiteSavePrefs()
    var isWanted: () -> Bool = { false }
    var trusted: () -> Bool = { AXIsProcessTrusted() }
    /// Whether a site not yet connected may be offered (the notch's own switch): only then is the page's site read.
    var offers: () -> Bool = { false }
    /// The pointer rests on a page of a site the person has not connected: what the connect offer listens to. Said
    /// once per visit (again only after the pointer has been on another site or none).
    var onSite: ((SiteSaveSite, pid_t, String) -> Void)?
    private var lastSite: String?
    /// A click changed a save control: the post, which way it went, and the post's own words when the page gave them.
    var onOutcome: ((SiteSaveItem, SiteSaveRule.Outcome, String) -> Void)?

    private var observer: NSObjectProtocol?
    private var monitor: Any?
    private var armedPid: pid_t?
    private var armedBundle: String?
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

    /// A site was connected or disconnected, or the permission changed: look again at what is in front.
    func refresh() {
        frontmostChanged(NSWorkspace.shared.frontmostApplication)
        if let pid = armedPid, !sites().isEmpty {
            Task.detached(priority: .utility) { SiteSaveReader.askForWebContent(pid: pid) }
        }
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
        armedBundle = bundle
        // The browser is asked to build its page tree only once a site is connected: it costs the browser work,
        // and an offer needs only the front tab's address.
        if !sites().isEmpty { Task.detached(priority: .utility) { SiteSaveReader.askForWebContent(pid: pid) } }
        monitor = NSEvent.addGlobalMonitorForEvents(matching: [.leftMouseDown, .mouseMoved]) { [weak self] event in
            let location = NSEvent.mouseLocation, down = event.type == .leftMouseDown
            MainActor.assumeIsolated { down ? self?.clicked(atAppKit: location) : self?.moved(atAppKit: location) }
        }
    }

    private func disarm() {
        if let monitor { NSEvent.removeMonitor(monitor) }
        monitor = nil
        armedPid = nil
        armedBundle = nil
        lastSite = nil
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
            guard !Task.isCancelled, let self, self.armedPid == pid else { return }
            // The page is read only once a site is connected; before that only the front tab's address is, for the
            // offer.
            if !self.sites().isEmpty {
                let reading = await Task.detached(priority: .utility) {
                    await SiteSaveReader.settledRead(pid: pid, at: point)
                }.value
                guard !Task.isCancelled, self.armedPid == pid else { return }
                if let reading, case let .success(item) = SiteSaveRule.item(reading, sites: self.sites()) {
                    self.hovered = Hover(item: item, reading: reading, point: point, at: SaveWhyTimings.now())
                } else {
                    self.hovered = nil
                }
            }
            guard self.offers() else { return }
            let site = await Task.detached(priority: .utility) { SiteSaveReader.frontSite(pid: pid) }.value
            guard !Task.isCancelled, self.armedPid == pid else { return }
            if let site, site.key != self.lastSite, !self.sites().contains(where: { $0.key == site.key }),
               let bundle = self.armedBundle {
                self.onSite?(site, pid, bundle)
            }
            self.lastSite = site?.key
        }
    }

    /// The reading a click may lean on: a rest close to it in place and time.
    nonisolated static func usable(_ hover: Hover?, at point: CGPoint, now: TimeInterval) -> Hover? {
        guard let hover, now - hover.at <= hoverFresh,
              hypot(hover.point.x - point.x, hover.point.y - point.y) <= hoverReach else { return nil }
        return hover
    }

    private func clicked(atAppKit location: CGPoint) {
        guard let pid = armedPid, !sites().isEmpty else { return }
        let point = screenPoint(location)
        let hover = Self.usable(hovered, at: point, now: SaveWhyTimings.now())
        rest?.cancel()
        pending?.cancel()
        pending = Task { [weak self] in
            guard let self else { return }
            let found = await Self.follow(pid: pid, point: point, hover: hover, sites: self.sites(),
                                          learned: self.prefs.allLabels)
            guard !Task.isCancelled, let found else { return }
            // The control's new state is what a second click on it starts from (the pointer has not moved).
            self.hovered = Hover(item: found.item, reading: found.seen, point: point, at: SaveWhyTimings.now())
            if found.teaches {
                self.prefs.learn(found.item.site, was: found.was, now: found.now, outcome: found.outcome)
            }
            if found.outcome != .none {
                self.onOutcome?(found.item, found.outcome, SiteSaveRule.text(of: found.seen, item: found.item))
            }
        }
    }

    /// Which reading is the state before the click: the rest's when it is about the same control (or when the read
    /// at the click names none), else the read at the click itself.
    nonisolated static func before(hover: Hover?, atClick: SiteSaveReading?, sites: [SiteSaveSite] = SiteSaveSite.all)
    -> (item: SiteSaveItem, reading: SiteSaveReading)? {
        let clicked = atClick.flatMap { reading in
            (try? SiteSaveRule.item(reading, sites: sites).get()).map { ($0, reading) }
        }
        if let hover, clicked == nil || clicked?.0 == hover.item { return (hover.item, hover.reading) }
        return clicked.map { (item: $0.0, reading: $0.1) }
    }

    nonisolated static func follow(pid: pid_t, point: CGPoint, hover: Hover?, sites: [SiteSaveSite],
                                   learned: [String: SiteSaveRule.Labels])
    async -> (item: SiteSaveItem, outcome: SiteSaveRule.Outcome, seen: SiteSaveReading, teaches: Bool,
              was: String, now: String)? {
        let started = SaveWhyTimings.now()
        let atClick = await Task.detached(priority: .userInitiated) { SiteSaveReader.read(pid: pid, at: point) }.value
        guard let (item, before) = before(hover: hover, atClick: atClick, sites: sites),
              let site = SiteSaveSite.named(item.site) else { return nil }
        let known = learned[site.key] ?? SiteSaveRule.Labels()
        var outcome = SiteSaveRule.Outcome.none, seen = before
        for look in SiteSaveReader.looks {
            let wait = look - (SaveWhyTimings.now() - started)
            if wait > 0 { try? await Task.sleep(nanoseconds: UInt64(wait * 1_000_000_000)) }
            if Task.isCancelled { return nil }
            let after = await Task.detached(priority: .userInitiated) {
                await SiteSaveReader.settledRead(pid: pid, at: point)
            }.value
            // The same control must be under the point: a look that finds another, or none, is tried again.
            guard let after, case let .success(same) = SiteSaveRule.item(after, sites: sites), same == item else {
                continue
            }
            seen = after
            outcome = SiteSaveRule.outcome(before: before, after: after, site: site, learned: known)
            if outcome != .none { break }
        }
        let labels = SiteSaveRule.change(before: before, after: seen)
        // What settled the direction, and whether it is certain enough to teach this Mac the site's two labels: a
        // count moving by one and the page's other posts are; the labels already learned teach nothing new.
        var basis = "none", teaches = false
        if let labels, outcome != .none {
            let byCount = SiteSaveRule.step(before: SiteSaveRule.counts(before), after: SiteSaveRule.counts(seen)) != nil
            if site.isListPage(seen.page ?? before.page) {
                basis = "list"
            } else if byCount {
                (basis, teaches) = ("count", true)
            } else if known.says(was: labels.was, now: labels.now) != nil {
                basis = "learned"
            } else if outcome == .changed {
                let census = await Task.detached(priority: .utility) {
                    SiteSaveReader.census(pid: pid, at: point, was: labels.was, now: labels.now)
                }.value
                if let said = census?.says { (outcome, basis, teaches) = (said, "page", true) }
            }
        }
        SiteSaveReader.logger.info("""
            save control on \(item.site, privacy: .public): \(outcome.rawValue, privacy: .public) \
            by \(basis, privacy: .public) after \(SaveWhyTimings.ms(SaveWhyTimings.now() - started)) ms; \
            before from \(hover != nil && hover?.reading == before ? "rest" : "click", privacy: .public)
            """)
        return (item, outcome, seen, teaches, labels?.was ?? "", labels?.now ?? "")
    }
}

/// What this Mac has learned and been told about noticing saves on sites: which sites the person connected and each
/// site's two labels (`SiteSaveRule.Labels`). An offer turned down is the connect offer's own memory. Per Mac (`UserDefaults`), like the
/// bookmark watch's own switches: the browser it watches is this Mac's.
struct SiteSavePrefs {
    let defaults: UserDefaults
    init(defaults: UserDefaults = .standard) { self.defaults = defaults }

    static func connectedKey(_ site: String) -> String { "cicada.siteSaves.connected.\(site)" }
    static func labelsKey(_ site: String) -> String { "cicada.siteSaves.labels.\(site)" }

    func isConnected(_ site: String) -> Bool { defaults.bool(forKey: Self.connectedKey(site)) }
    func setConnected(_ site: String, _ on: Bool) { defaults.set(on, forKey: Self.connectedKey(site)) }
    var connected: [SiteSaveSite] { SiteSaveSite.all.filter { isConnected($0.key) } }

    func labels(_ site: String) -> SiteSaveRule.Labels {
        defaults.data(forKey: Self.labelsKey(site)).flatMap { try? JSONDecoder().decode(SiteSaveRule.Labels.self, from: $0) }
            ?? SiteSaveRule.Labels()
    }
    func learn(_ site: String, was: String, now: String, outcome: SiteSaveRule.Outcome) {
        var known = labels(site)
        known.learn(was: was, now: now, outcome: outcome)
        // A few labels per site (one pair per interface language the person has used); never grows without bound.
        guard known.saved.count <= 12, known.unsaved.count <= 12,
              let data = try? JSONEncoder().encode(known) else { return }
        defaults.set(data, forKey: Self.labelsKey(site))
    }
    var allLabels: [String: SiteSaveRule.Labels] {
        Dictionary(uniqueKeysWithValues: SiteSaveSite.all.map { ($0.key, labels($0.key)) })
    }
}
