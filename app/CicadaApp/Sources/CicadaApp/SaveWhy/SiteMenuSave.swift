import AppKit
import ApplicationServices
import CryptoKit

// G221 — a save a site keeps in a menu (Reddit's post menu, YouTube's sheet of lists), noticed the same way as a save
// button (`SiteSave.swift`): the person's own click, read through Accessibility, on a site they connected.
//
// **No words are matched here either.** The menu is recognised by the page's own structure (DOM ids and class names,
// the same in every interface language) and the saving item by its place in it. A menu closes at the click, so there
// is no label to compare a moment later; which way the click went is settled, in order, by the person's own saved
// list (a click there is leaving it), by the other lists in the same sheet (most are not holding the video), by the
// labels this Mac already learned, and by what the item wore on other posts the person clicked it on (most posts are
// not saved). With none of them the click is neither stored nor asked about.
//
// **What is read:** the menu under the person's own click, and the post block that menu belongs to. On a site whose
// sheet names no post (YouTube), also which card the click that opened it was on.

/// What was read around one click on a menu item.
struct SiteMenuReading: Equatable, Sendable {
    var site: String
    /// The menu's items in order, as the page labels them (compared with each other and with later clicks, never
    /// matched against a word).
    var items: [String]
    var clicked: Int
    var page: String? = nil
    /// Every structural mark the site's rule names was found around the menu.
    var fits = true
    /// The nearest block above the menu is another kind of thing (a comment), not a post.
    var foreign = false
    /// The post block's own id, without its prefix (Reddit: the post's id), and the post links inside that block
    /// with their labels.
    var blockKey: String = ""
    var links: [String] = []
    var linkLabels: [String] = []
    /// The clicked item's frame on screen (top-left coordinates): a rest's reading is used only for a click inside it.
    var frame: CGRect = .zero
    /// The first item that carries the site's mark (`SiteSaveSite.Menu.markClass`), when the menu shows one.
    var firstMarked: Int? = nil
    /// What the post's block shows, one run of text a line, on a site whose pages name the post by no link
    /// (`SiteSaveSite.Menu.words`); read only when the item under the click is in the save's place.
    var words: String = ""
}

enum SiteMenuRule {
    typealias Outcome = SiteSaveRule.Outcome
    typealias Refusal = SiteSaveRule.Refusal

    /// Where a sheet of lists was opened from.
    enum Opener: Equatable, Sendable {
        /// The click was inside a menu: whatever opened it still stands.
        case menu
        /// A card that is one post, by its link.
        case card(String)
        /// The page's own controls: the page is the post.
        case page
        case other
    }

    private static let separators: Set<Character> = [",", "\u{060C}", "\u{3001}", "\u{FF0C}"]

    /// The parts of a list's label ("name, who sees it, in or out"), split at commas of any script.
    static func parts(_ label: String) -> [String] {
        label.split(whereSeparator: { separators.contains($0) }).map { $0.trimmingCharacters(in: .whitespaces) }
    }

    /// What an item says about its own state: the whole label of a menu's save item; for a list, its last part.
    static func state(_ label: String, lists: Bool) -> String {
        lists ? (parts(label).last ?? label) : label
    }

    /// A list's own name, when its label has the three parts measured (the name may hold commas itself).
    static func listName(_ label: String) -> String? {
        let all = parts(label)
        guard all.count >= 3 else { return nil }
        let name = all.dropLast(2).joined(separator: ", ")
        return name.isEmpty ? nil : String(name.prefix(120))
    }

    /// The post a clicked menu item saves, and the folder it is filed in when the item is one of the person's own
    /// lists, or why this click is not a save.
    /// `learned` is what this Mac has learned the site's save item is called (`SiteSavePrefs.labels`). In a menu whose
    /// layout the site's rule does not place the save in (measured 2026-11-25: Reddit's menu on the person's own post
    /// has ten items with the save third, between items no other layout has), the item that wears one of those labels
    /// is the save: the label was learned from the person's own clicks in a layout the rule does know, on this Mac,
    /// in whatever language their Reddit is in. Nothing shipped is matched.
    static func item(_ reading: SiteMenuReading, opener: Opener? = nil, sites: [SiteSaveSite] = SiteSaveSite.all,
                     learned: SiteSaveRule.Labels = .init())
    -> Result<(item: SiteSaveItem, folder: String?, text: String), Refusal> {
        guard let site = sites.first(where: { $0.key == reading.site }), let rule = site.menu else {
            return .failure(.unknownSite)
        }
        guard reading.fits, !reading.foreign, reading.items.indices.contains(reading.clicked) else {
            return .failure(.notTheSaveSlot)
        }
        let placed: Bool
        if rule.markClass != nil, let marked = reading.firstMarked {
            // The menu shows the site's mark: it places the save, whatever the menu's length.
            placed = rule.markSizes.contains(reading.items.count) && reading.clicked == marked - rule.beforeMark
        } else {
            placed = rule.sizes.contains(reading.items.count)
                && rule.fromEnd.map { reading.clicked == reading.items.count - $0 } != false
                && rule.fromStart.map { reading.clicked == $0 } != false
        }
        if !placed {
            // A layout the rule does not know: the item this Mac learned as the site's save, by its own label.
            let label = reading.items[reading.clicked]
            guard !rule.lists, reading.items.count <= Self.knownByLabelMax,
                  learned.saved.contains(label) || learned.unsaved.contains(label) else {
                return .failure(.notTheSaveSlot)
            }
        }
        if rule.lists {
            let named: SiteSaveItem?
            switch opener {
            case let .card(url): named = site.item(url)
            case .page: named = site.item(reading.page)
            default: named = nil
            }
            guard let named else { return .failure(.noPostLink) }
            // The first list is the site's own (Watch later): no folder. Every other is one the person made.
            let folder = reading.clicked > 0 ? listName(reading.items[reading.clicked]) : nil
            return .success((named, folder, ""))
        }
        if rule.words {
            // The page itself is the post (its own page), or the post is named by what its block shows: enough
            // words to tell it from another, or nothing is said.
            if let own = site.item(reading.page) { return .success((own, nil, "")) }
            guard !reading.blockKey.isEmpty, Self.names(reading.words) else { return .failure(.noPostLink) }
            return .success((SiteSaveItem(site: site.key, origin: site.origin, url: "", title: site.name + " post"),
                             nil, reading.words))
        }
        // The post is the one whose link carries the block's own id: the block's link in a feed, the page itself on
        // the post's page. Another post linked from inside the block never matches.
        guard !reading.blockKey.isEmpty else { return .failure(.noPostLink) }
        let mark = "/" + reading.blockKey + "/"
        if let index = reading.links.firstIndex(where: { ($0 + "/").contains(mark) }),
           let found = site.item(reading.links[index]) {
            return .success((found, nil, reading.linkLabels.indices.contains(index) ? reading.linkLabels[index] : ""))
        }
        if let page = reading.page, (page + "/").contains(mark), let own = site.item(page) {
            return .success((own, nil, ""))
        }
        return .failure(.noPostLink)
    }

    /// How long a menu of an unknown layout may be for a learned label to name its save.
    static let knownByLabelMax = 20

    /// How many letters and digits a block's words must hold to name a post (the backend's own floor,
    /// `site_later.MIN_HELD_FOLD`): a block that shows only a picture and a name is told from no other.
    static let namingLetters = 40

    static func names(_ words: String) -> Bool {
        words.unicodeScalars.lazy.filter { CharacterSet.alphanumerics.contains($0) }.prefix(namingLetters).count
            >= namingLetters
    }

    /// What a site's save item wore at the person's clicks, by post: the label worn on most posts is the "not saved"
    /// one. Posts are kept as short hashes, a few per label.
    struct Seen: Equatable, Sendable, Codable {
        var posts: [String: [String]] = [:]
        static let perLabel = 4
        static let labels = 6

        mutating func note(label: String, post: String) {
            var list = posts[label] ?? []
            list.removeAll { $0 == post }
            list.append(post)
            posts[label] = Array(list.suffix(Self.perLabel))
            if posts.count > Self.labels, let fewest = posts.filter({ $0.key != label }).min(by: { $0.value.count < $1.value.count }) {
                posts[fewest.key] = nil
            }
        }

        /// The labels this post was seen wearing.
        func worn(by post: String) -> [String] { posts.filter { $0.value.contains(post) }.map(\.key).sorted() }

        /// The label worn on the most posts: at least `Census.quorum` of them, and more than any other label.
        var common: String? {
            let ranked = posts.map { ($0.key, $0.value.count) }.sorted { $0.1 > $1.1 }
            guard let top = ranked.first, top.1 >= SiteSaveRule.Census.quorum else { return nil }
            if ranked.count > 1, ranked[1].1 == top.1 { return nil }
            return top.0
        }
    }

    static func postKey(_ url: String) -> String {
        SHA256.hash(data: Data(url.utf8)).prefix(6).map { String(format: "%02x", $0) }.joined()
    }

    struct Verdict: Equatable, Sendable {
        var outcome: Outcome
        /// What settled it (logged as this word).
        var basis: String
        /// Labels this click is certain enough to teach this Mac.
        var saved: String? = nil
        var unsaved: String? = nil
    }

    /// Which way a click on a menu's save item went. `seen` is what this Mac saw before this click.
    static func outcome(_ reading: SiteMenuReading, site: SiteSaveSite, post: String,
                        learned: SiteSaveRule.Labels = .init(), seen: Seen = .init()) -> Verdict {
        guard let rule = site.menu, reading.items.indices.contains(reading.clicked) else {
            return Verdict(outcome: .none, basis: "none")
        }
        let mine = state(reading.items[reading.clicked], lists: rule.lists)
        if site.isListPage(reading.page) { return Verdict(outcome: .unsaved, basis: "list", saved: mine) }
        // A site whose menu is the only word for the direction (LinkedIn: the same item, two labels, and the feed
        // names no post to compare it on): nothing here says which way, and nothing is learned from a guess. The
        // record decides (`POST /sources/site-change`, `POST /sources/site-words`).
        if rule.words { return Verdict(outcome: .changed, basis: "none") }
        if rule.lists {
            // The other lists in the same sheet: most are not holding the video.
            var others: [String: Int] = [:]
            for (index, label) in reading.items.enumerated() where index != reading.clicked {
                others[state(label, lists: true), default: 0] += 1
            }
            let ranked = others.sorted { $0.value > $1.value }
            if let top = ranked.first, top.value >= SiteSaveRule.Census.quorum,
               ranked.count == 1 || ranked[1].value < top.value {
                return top.key == mine ? Verdict(outcome: .saved, basis: "sheet", unsaved: mine)
                    : Verdict(outcome: .unsaved, basis: "sheet", saved: mine, unsaved: top.key)
            }
        }
        if learned.unsaved.contains(mine) { return Verdict(outcome: .saved, basis: "learned") }
        if learned.saved.contains(mine) { return Verdict(outcome: .unsaved, basis: "learned") }
        // The same post wore the "not saved" label at an earlier click and wears another now: it was saved since.
        if seen.worn(by: post).contains(where: { $0 != mine && learned.unsaved.contains($0) }) {
            return Verdict(outcome: .unsaved, basis: "flip", saved: mine)
        }
        var with = seen
        with.note(label: mine, post: post)
        if with.common == mine { return Verdict(outcome: .saved, basis: "seen", unsaved: mine) }
        return Verdict(outcome: .changed, basis: "none")
    }
}

extension SiteSaveReader {
    static let menuRole = "AXMenu"
    static let menuItemRole = "AXMenuItem"
    static let maxMenuItems = 200
    static let maxMenuAncestors = 18
    static let maxBlockNodes = 240

    private static func domId(_ element: AXUIElement) -> String { string(element, "AXDOMIdentifier") ?? "" }

    private static func classes(_ element: AXUIElement) -> [String] {
        var value: CFTypeRef?
        guard AXUIElementCopyAttributeValue(element, "AXDOMClassList" as CFString, &value) == .success else { return [] }
        return value as? [String] ?? []
    }

    private static func role(_ element: AXUIElement) -> String { string(element, kAXRoleAttribute as String) ?? "" }

    private static func parent(_ node: AXUIElement) -> AXUIElement? { element(node, kAXParentAttribute as String) }

    /// A menu's shown items in order (a site may wrap one in a group).
    private static func menuItems(_ menu: AXUIElement) -> [AXUIElement] {
        var out: [AXUIElement] = []
        var stack = children(menu).reversed().map { ($0, 0) }
        var seen = 0
        while let (next, depth) = stack.popLast(), seen < maxMenuItems * 2, out.count < maxMenuItems {
            seen += 1
            if role(next) == menuItemRole {
                // An item with no size is not shown (measured: Reddit keeps a hidden one at the end of a post page's
                // menu), so it is no part of the menu the person sees.
                if frame(next) != nil { out.append(next) }
            } else if depth < 3 {
                stack.append(contentsOf: children(next).reversed().map { ($0, depth + 1) })
            }
        }
        return out
    }

    private static func firstMenu(in scope: AXUIElement) -> AXUIElement? {
        var stack = Array(children(scope).reversed()), seen = 0
        while let next = stack.popLast(), seen < maxNodes {
            seen += 1
            let kind = role(next)
            if kind == menuRole { return next }
            if !isControl(kind) { stack.append(contentsOf: children(next).reversed()) }
        }
        return nil
    }

    /// The item of `menu` whose row holds the point: an item's own frame may be narrower than the row that takes
    /// the click (measured on YouTube), so the menu's frame decides sideways and the item's up and down.
    private static func item(at point: CGPoint, in menu: AXUIElement) -> AXUIElement? {
        guard let box = frame(menu), box.contains(point) else { return nil }
        return menuItems(menu).first { item in
            guard let row = frame(item) else { return false }
            return point.y >= row.minY && point.y < row.maxY
        }
    }

    private static func menuItem(under hit: AXUIElement, at point: CGPoint) -> (item: AXUIElement, menu: AXUIElement)? {
        var node = hit
        for _ in 0...4 {
            let kind = role(node)
            if kind == menuItemRole {
                var above = node
                for _ in 0..<4 {
                    guard let next = parent(above) else { return nil }
                    above = next
                    if role(above) == menuRole { return (node, above) }
                }
                return nil
            }
            if kind == menuRole { return item(at: point, in: node).map { ($0, node) } }
            guard let next = parent(node) else { break }
            node = next
        }
        var scope = hit
        for level in 0..<3 {
            if level > 0 {
                guard let next = parent(scope) else { return nil }
                scope = next
            }
            guard role(scope) != "AXWebArea" else { return nil }
            if let menu = firstMenu(in: scope), let found = item(at: point, in: menu) { return (found, menu) }
        }
        return nil
    }

    /// The post links inside a block, in reading order, with their labels. Links only; bounded.
    private static func itemLinks(in block: AXUIElement, site: SiteSaveSite) -> (urls: [String], labels: [String]) {
        var urls: [String] = [], labels: [String] = []
        var stack = Array(children(block).reversed()), seen = 0
        while let next = stack.popLast(), seen < maxBlockNodes, urls.count < 12 {
            seen += 1
            let kind = role(next)
            if kind == SiteSaveRule.link {
                if let url = string(next, kAXURLAttribute as String), site.item(url) != nil {
                    urls.append(url)
                    labels.append(label(next))
                }
            } else if kind != SiteSaveRule.plainButton, kind != menuRole {
                stack.append(contentsOf: children(next).reversed())
            }
        }
        return (urls, labels)
    }

    /// `readMenu`, asked a second time when the first answer names no menu item (`secondAsk`).
    static func settledReadMenu(pid: pid_t, at point: CGPoint, sites: [SiteSaveSite]) async -> SiteMenuReading? {
        if let first = readMenu(pid: pid, at: point, sites: sites) { return first }
        try? await Task.sleep(nanoseconds: UInt64(secondAsk * 1_000_000_000))
        return readMenu(pid: pid, at: point, sites: sites)
    }

    /// The menu item at `point` and what its site's rule needs around it, or nil when the point is on no menu item
    /// of a site in `sites` that keeps its save in a menu.
    static func readMenu(pid: pid_t, at point: CGPoint, sites: [SiteSaveSite]) -> SiteMenuReading? {
        let app = AXUIElementCreateApplication(pid)
        AXUIElementSetMessagingTimeout(app, timeout)
        var hit: AXUIElement?
        guard AXUIElementCopyElementAtPosition(app, Float(point.x), Float(point.y), &hit) == .success, let hit,
              let address = page(above: hit),
              let site = sites.first(where: { $0.menu != nil && $0.onHost(address) }), let rule = site.menu,
              let (item, menu) = menuItem(under: hit, at: point) else { return nil }
        let items = menuItems(menu)
        // The browser's first answer about a fresh point can be the item next to it (`secondAsk`): an item whose own
        // frame does not hold the point's height is not the one clicked.
        guard let clicked = items.firstIndex(where: { CFEqual($0, item) }),
              let row = frame(item), point.y >= row.minY, point.y < row.maxY else { return nil }
        var underSeen = rule.under == nil, sheetSeen = rule.sheetClass == nil
        var block: AXUIElement?, blockKey = "", foreign = false
        var node = menu
        for _ in 0..<maxMenuAncestors {
            guard let above = parent(node), role(above) != "AXWebArea" else { break }
            node = above
            let id = domId(node)
            if let under = rule.under, id == under { underSeen = true }
            if let sheet = rule.sheetClass, !sheetSeen, classes(node).contains(sheet) {
                let inside = children(node)
                let headed = rule.headerClass.map { header in inside.contains { classes($0).contains(header) } } ?? true
                sheetSeen = headed && inside.last.map { role($0) == SiteSaveRule.plainButton } == true
            }
            if block == nil, !foreign, !rule.notClasses.isEmpty, rule.notClasses.contains(where: classes(node).contains) {
                foreign = true
            }
            if block == nil, !foreign, !id.isEmpty {
                if rule.notBlock.contains(where: { id.hasPrefix($0) }) {
                    foreign = true
                } else if let prefix = rule.block, id.hasPrefix(prefix), id.count > prefix.count,
                          id.dropFirst(prefix.count).allSatisfy({
                              $0.isLetter || $0.isNumber || rule.blockMarks.contains($0)
                          }) {
                    block = node
                    blockKey = String(id.dropFirst(prefix.count))
                }
            }
        }
        let fits = (rule.menuClass.map { classes(menu).contains($0) } ?? true) && underSeen && sheetSeen
            && (rule.block == nil || block != nil || foreign)
        let found = block.map { itemLinks(in: $0, site: site) } ?? ([], [])
        let firstMarked = rule.markClass.flatMap { mark in items.firstIndex { carries(mark, in: $0) } }
        // The block's words are read only for the item in the save's place, on a site that names its posts no
        // other way, and not on the post's own page (the address names it there).
        let wanted = rule.words && fits && !foreign && rule.fromStart == clicked && site.item(address) == nil
        let shown = wanted ? block.map { words(in: $0, besides: menu) } ?? "" : ""
        return SiteMenuReading(site: site.key, items: items.map(label), clicked: clicked, page: address, fits: fits,
                               foreign: foreign, blockKey: blockKey, links: found.0, linkLabels: found.1,
                               frame: row, firstMarked: firstMarked, words: shown)
    }

    static let maxWordNodes = 500
    static let maxWordLetters = 1600

    /// What a post's block shows, in reading order: each run of text that sits side by side is one line. The menu
    /// itself and every button are left out (their labels are the site's words, not the post's). Bounded.
    private static func words(in block: AXUIElement, besides menu: AXUIElement) -> String {
        var lines: [String] = [], letters = 0, seen = 0
        var stack = [block]
        while let next = stack.popLast(), seen < maxWordNodes, letters < maxWordLetters {
            seen += 1
            var run: [String] = [], below: [AXUIElement] = []
            for child in children(next) {
                let kind = role(child)
                if kind == "AXStaticText" {
                    let text = (string(child, kAXValueAttribute as String) ?? "")
                        .split(whereSeparator: \.isWhitespace).joined(separator: " ")
                    if !text.isEmpty { run.append(text) }
                } else if kind != menuRole, kind != menuItemRole, kind != SiteSaveRule.plainButton,
                          !CFEqual(child, menu) {
                    below.append(child)
                }
            }
            if !run.isEmpty {
                let line = run.joined(separator: " ")
                lines.append(line)
                letters += line.count
            }
            stack.append(contentsOf: below.reversed())
        }
        return String(lines.joined(separator: "\n").prefix(maxWordLetters * 2))
    }

    /// Whether a menu item, or one of the few things drawn inside it (its icon), carries a class. Bounded.
    private static func carries(_ mark: String, in item: AXUIElement) -> Bool {
        var stack = [item], seen = 0
        while let next = stack.popLast(), seen < 12 {
            seen += 1
            if classes(next).contains(mark) { return true }
            stack.append(contentsOf: children(next))
        }
        return false
    }

    /// `opener`, asked a second time when the first answer places the click nowhere known (`secondAsk`).
    static func settledOpener(pid: pid_t, at point: CGPoint, site: SiteSaveSite) async -> SiteMenuRule.Opener? {
        let first = opener(pid: pid, at: point, site: site)
        guard first == nil || first == .other else { return first }
        try? await Task.sleep(nanoseconds: UInt64(secondAsk * 1_000_000_000))
        return opener(pid: pid, at: point, site: site) ?? first
    }

    /// Where a click on a page of `site` sits, for a sheet that names no post itself: inside a menu, on a card that
    /// is one post, or on the page's own controls. Class names and one link are read, climbing from the click.
    static func opener(pid: pid_t, at point: CGPoint, site: SiteSaveSite) -> SiteMenuRule.Opener? {
        guard let rule = site.menu, rule.lists else { return nil }
        let app = AXUIElementCreateApplication(pid)
        AXUIElementSetMessagingTimeout(app, timeout)
        var hit: AXUIElement?
        guard AXUIElementCopyElementAtPosition(app, Float(point.x), Float(point.y), &hit) == .success, let hit
        else { return nil }
        var node = hit
        for _ in 0..<maxMenuAncestors {
            let kind = role(node)
            if kind == "AXWebArea" { break }
            if kind == menuRole || kind == menuItemRole { return .menu }
            let marks = classes(node)
            if rule.cards.contains(where: marks.contains) {
                return itemLinks(in: node, site: site).urls.first.map { .card($0) } ?? .other
            }
            if rule.pageClasses.contains(where: marks.contains) { return .page }
            guard let above = parent(node) else { break }
            node = above
        }
        return .other
    }
}
