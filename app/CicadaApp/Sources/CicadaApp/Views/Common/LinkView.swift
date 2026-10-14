import Foundation

// MARK: - The link-view grammar (owner rulings 2026-10-14)
//
// How a link on a page asks to be drawn: a view word in the standard markdown link title — `[T](url "bookmark")`,
// `"screenshot 2026-10-14"` — research-hub's grammar, extended with screenshot, captures and look. The line stays a
// working link in every other markdown reader. This is `api/services/link_views.py`'s twin: both read
// `api/tests/fixtures/link_views.json` (`LinkViewTests`), the way `video_urls.json` pins `VideoRef` (R-V8: a second
// parser is how drift starts). Pure: no network, no I/O.

/// The ways a link can be drawn. The first three sit inside a sentence; the rest need a line to themselves.
enum LinkViewKind: String, CaseIterable, Sendable, Equatable, Hashable {
    case link, raw, mention, bookmark, screenshot, captures, look, embed

    static let inline: Set<LinkViewKind> = [.link, .raw, .mention]
    /// The views a date may pin.
    static let dated: Set<LinkViewKind> = [.screenshot, .look]
    /// What the person's switcher offers, in order (`raw` and `embed` are read, never offered).
    static let switcher: [LinkViewKind] = [.link, .mention, .bookmark, .screenshot, .captures, .look]

    var isBlock: Bool { !Self.inline.contains(self) }
}

/// One link in one line: what it says, where it points, and how it asks to be drawn.
struct LinkRef: Sendable, Equatable, Hashable {
    let label: String
    let url: String
    /// The view as drawn here: a block view out of place (inside a sentence) draws as `mention`.
    let view: LinkViewKind
    /// The view the markdown names (`link` for no title or a plain tooltip).
    let asked: LinkViewKind
    let day: String?
    /// Alone on its line (after a list marker, before an optional ` — note`), so a block view draws as a block.
    let block: Bool
    /// The exact token, an edit's `old`.
    let markdown: String
    /// The token's range in the line (UTF-16, for `NSString`).
    let range: NSRange

    /// The label to show: the page's own words, or the URL's short form when the label is the URL itself (the card
    /// shows the title Cicada knows instead, and never writes it back).
    var shownLabel: String { label == url || label.isEmpty ? LinkGrammar.display(url) : label }
}

enum LinkGrammar {
    struct Title: Equatable { let view: LinkViewKind; let day: String? }

    private static func regex(_ pattern: String) -> NSRegularExpression {
        // A literal pattern: a failure is a programming error caught by `LinkViewTests` on the first run.
        try! NSRegularExpression(pattern: pattern)
    }

    private static let title = regex(#"^([a-z]+)(?: (\d{4}-\d{2}-\d{2}))?$"#)
    private static let link = regex(
        #"(?<!!)\[((?:\\.|[^\[\]\\])*)\]\(\s*(?:<(https?://[^\s<>]+)>|(https?://(?:[^\s()<>]|\([^\s()<>]*\))+))(?:\s+(?:"([^"]*)"|'([^']*)'))?\s*\)"#)
    private static let autolink = regex(#"<(https?://[^\s<>]+)>"#)
    private static let bare = regex(#"(?<![\w<"'=/])(https?://[^\s<>"'`\]]+)"#)
    private static let image = regex(#"!\[[^\]]*\]\([^)]*\)"#)
    private static let item = regex(#"^\s*(?:[-*+]|\d+\.)\s+"#)
    private static let note = regex(#"^\s+[—–-]\s+"#)
    private static let code = regex("`+[^`]*`+")
    private static let bareTrail = Set(".,;:!?)'\"")

    /// The view a link title names, or nil when it is a plain tooltip (or there is none).
    static func parseTitle(_ raw: String?) -> Title? {
        guard let raw else { return nil }
        let ns = raw as NSString
        guard let m = title.firstMatch(in: raw, range: NSRange(location: 0, length: ns.length)),
              let view = LinkViewKind(rawValue: ns.substring(with: m.range(at: 1))) else { return nil }
        guard m.range(at: 2).location != NSNotFound else { return Title(view: view, day: nil) }
        let day = ns.substring(with: m.range(at: 2))
        guard LinkViewKind.dated.contains(view), validDay(day) else { return nil }
        return Title(view: view, day: day)
    }

    private static func validDay(_ day: String) -> Bool {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = TimeZone(identifier: "UTC")
        f.dateFormat = "yyyy-MM-dd"
        f.isLenient = false
        guard let date = f.date(from: day) else { return false }
        return f.string(from: date) == day
    }

    /// The link title that asks for `view` (nil for a plain link, or a date that cannot go with the view).
    static func title(for view: LinkViewKind, day: String? = nil) -> String? {
        guard view != .link else { return nil }
        if let day {
            guard LinkViewKind.dated.contains(view), validDay(day) else { return nil }
            return "\(view.rawValue) \(day)"
        }
        return view.rawValue
    }

    static func escapeLabel(_ label: String) -> String {
        var out = ""
        for ch in label {
            if ch == "[" || ch == "]" || ch == "\\" { out.append("\\") }
            out.append(ch)
        }
        return out
    }

    static func unescapeLabel(_ label: String) -> String {
        var out = ""
        var escaping = false
        for ch in label {
            if escaping {
                if ch != "[" && ch != "]" && ch != "\\" { out.append("\\") }
                out.append(ch)
                escaping = false
            } else if ch == "\\" {
                escaping = true
            } else {
                out.append(ch)
            }
        }
        if escaping { out.append("\\") }
        return out
    }

    static func escapeURL(_ url: String) -> String {
        url.replacingOccurrences(of: " ", with: "%20").replacingOccurrences(of: "\"", with: "%22")
            .replacingOccurrences(of: "<", with: "%3C").replacingOccurrences(of: ">", with: "%3E")
    }

    /// The token for `label`/`url` drawn as `view`: `[label](url)` or `[label](url "view")`.
    static func markdown(label: String, url: String, view: LinkViewKind, day: String? = nil) -> String {
        let head = "[\(escapeLabel(label))](\(escapeURL(url))"
        if let title = title(for: view, day: day) { return "\(head) \"\(title)\")" }
        return "\(head))"
    }

    /// The raw view's words: no scheme, no `www.`, no trailing slash.
    static func display(_ url: String) -> String {
        var out = url
        for scheme in ["https://", "http://"] where out.hasPrefix(scheme) { out.removeFirst(scheme.count) }
        if out.hasPrefix("www.") { out.removeFirst(4) }
        while out.hasSuffix("/") { out.removeLast() }
        return out
    }

    /// The site a mention names (the host without `www.`); nil for a URL with no host.
    static func site(_ url: String) -> String? {
        guard let host = URL(string: url)?.host?.lowercased(), !host.isEmpty else { return nil }
        return host.hasPrefix("www.") ? String(host.dropFirst(4)) : host
    }

    private static func isBlock(_ ns: NSString, _ range: NSRange) -> Bool {
        let before = ns.substring(to: range.location)
        if !before.trimmingCharacters(in: .whitespaces).isEmpty {
            let b = before as NSString
            guard let m = item.firstMatch(in: before, range: NSRange(location: 0, length: b.length)),
                  m.range.length == b.length else { return false }
        }
        let after = ns.substring(from: range.location + range.length)
        if after.trimmingCharacters(in: .whitespaces).isEmpty { return true }
        return note.firstMatch(in: after, range: NSRange(location: 0, length: (after as NSString).length)) != nil
    }

    private static func blank(_ text: inout String, _ range: NSRange) {
        let ns = text as NSString
        text = ns.replacingCharacters(in: range, with: String(repeating: " ", count: range.length))
    }

    /// A bare URL without the sentence's trailing punctuation — a closing `)` only when it closes nothing in the URL.
    static func trimBare(_ raw: String) -> String {
        var url = raw
        while let last = url.last, bareTrail.contains(last) {
            if last == ")", url.filter({ $0 == "(" }).count >= url.filter({ $0 == ")" }).count { break }
            url.removeLast()
        }
        return url
    }

    /// Every link in ONE line, in order: titled and plain markdown links, autolinks and bare URLs (`raw`). Nothing
    /// inside inline code; never an image.
    static func links(in line: String) -> [LinkRef] {
        let original = line as NSString
        var text = line
        for m in code.matches(in: line, range: NSRange(location: 0, length: original.length)) { blank(&text, m.range) }
        var found: [LinkRef] = []
        var ns = text as NSString
        for m in link.matches(in: text, range: NSRange(location: 0, length: ns.length)) {
            func group(_ i: Int) -> String? {
                m.range(at: i).location == NSNotFound ? nil : ns.substring(with: m.range(at: i))
            }
            let parsed = parseTitle(group(4) ?? group(5))
            let asked = parsed?.view ?? .link
            let block = isBlock(ns, m.range)
            let view: LinkViewKind = (LinkViewKind.inline.contains(asked) || block) ? asked : .mention
            found.append(LinkRef(label: unescapeLabel(group(1) ?? ""), url: group(2) ?? group(3) ?? "", view: view,
                                 asked: asked, day: parsed?.day, block: block,
                                 markdown: original.substring(with: m.range), range: m.range))
        }
        for ref in found { blank(&text, ref.range) }
        ns = text as NSString
        for m in image.matches(in: text, range: NSRange(location: 0, length: ns.length)) { blank(&text, m.range) }
        ns = text as NSString
        var autos: [NSRange] = []
        for m in autolink.matches(in: text, range: NSRange(location: 0, length: ns.length)) {
            let url = ns.substring(with: m.range(at: 1))
            found.append(LinkRef(label: url, url: url, view: .raw, asked: .raw, day: nil, block: isBlock(ns, m.range),
                                 markdown: original.substring(with: m.range), range: m.range))
            autos.append(m.range)
        }
        for r in autos { blank(&text, r) }
        ns = text as NSString
        for m in bare.matches(in: text, range: NSRange(location: 0, length: ns.length)) {
            var url = ns.substring(with: m.range(at: 1))
            url = trimBare(url)
            guard url.contains("://"), url.count > "https://".count else { continue }
            let range = NSRange(location: m.range.location, length: (url as NSString).length)
            found.append(LinkRef(label: url, url: url, view: .raw, asked: .raw, day: nil, block: isBlock(ns, range),
                                 markdown: url, range: range))
        }
        return found.sorted { $0.range.location < $1.range.location }
    }

    /// `text` with every view word dropped (`[T](u "bookmark")` → `[T](u)`); a real tooltip is kept. What a copy or a
    /// quote serves, so it never shows a view word.
    static func plain(_ text: String) -> String {
        guard text.contains("](") else { return text }
        let ns = text as NSString
        var out = text
        for m in link.matches(in: text, range: NSRange(location: 0, length: ns.length)).reversed() {
            let titleRange = m.range(at: 4).location != NSNotFound ? m.range(at: 4) : m.range(at: 5)
            guard titleRange.location != NSNotFound, parseTitle(ns.substring(with: titleRange)) != nil else { continue }
            let url = ns.substring(with: m.range(at: 2).location != NSNotFound ? m.range(at: 2) : m.range(at: 3))
            out = (out as NSString).replacingCharacters(in: m.range,
                                                        with: "[\(ns.substring(with: m.range(at: 1)))](\(url))")
        }
        return out
    }
}
