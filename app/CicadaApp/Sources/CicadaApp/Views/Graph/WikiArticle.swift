import SwiftUI
import CryptoKit

// MARK: - The wiki page (owner 2026-10-09)
//
// An entity card opens on its page's prose, read as an article. The owner page of a bank imported from years of chats
// carries ~180 KB of prose (thousands of Key Facts lines). `MarkdownBody` parsed it, built an `AttributedString` per
// line and laid every line out in one `VStack` on every render — a 2.1 s main-thread stall the moment the page landed
// (`CardOpenProbeTests`). Here the prose becomes flat rows once, off the main actor, cached per text, and the card
// draws them in a `LazyVStack`: only the rows on screen are laid out.

/// One drawn line of the article: a heading, a paragraph, one list item, a code block, a quote, a rule, an embed or
/// an image. `source` is the row's range in the served prose (Unicode scalar offsets, which are Python's `str`
/// offsets), so a line can find the `/provenance` section item that describes it (`bodyRanges`).
struct WikiRow: Identifiable, Sendable, Equatable {
    enum Kind: Sendable, Equatable {
        case heading(level: Int)
        case paragraph
        case item(marker: String, indent: Int)
        case code
        case quote
        case rule
        case embed(ref: String)
        case image(url: String, alt: String)
    }

    let id: Int
    let kind: Kind
    /// The inline-rendered text (wikilinks as `cicada://entity/…` links); plain for a code block.
    let text: AttributedString
    let source: Range<Int>
}

struct WikiArticle: Sendable, Equatable {
    let rows: [WikiRow]
    /// False when the build stopped at `maxRows`: the rest is still being read.
    let complete: Bool

    static let empty = WikiArticle(rows: [], complete: true)
    var isEmpty: Bool { complete && rows.isEmpty }

    /// The sections that already have their own surface: the Summary is the header's (R-DG15), the Description a
    /// media page's card. The same pair `EntityDetailCard` used to strip before rendering.
    static let ownSurfaces: Set<String> = ["## Summary", "## Description"]

    /// `markdown` as rows, without every section in `dropping` (a `## ` header and its body, up to the next `## `)
    /// and without any ```claims block (machine data with its own surface, R-FX8). Stops after `maxRows` rows: the
    /// rows a capped build returns are exactly the full build's first rows, so a first screen can be drawn before the
    /// rest is read.
    static func build(_ markdown: String, dropping: Set<String> = ownSurfaces, maxRows: Int = .max) -> WikiArticle {
        var reader = LineReader(markdown)
        var rows: [WikiRow] = []
        var dropped = false
        func add(_ kind: WikiRow.Kind, _ text: AttributedString, _ source: Range<Int>) {
            rows.append(WikiRow(id: rows.count, kind: kind, text: text, source: source))
        }
        while rows.count < maxRows, let line = reader.peek() {
            let trimmed = line.text.trimmingCharacters(in: .whitespaces)
            if trimmed.hasPrefix("## ") || trimmed == "##" { dropped = dropping.contains(trimmed) }
            if trimmed.isEmpty {
                reader.advance()
                continue
            }
            if let lang = fenceLanguage(line.text) {
                // Everything up to the closing fence is verbatim; an unterminated fence runs to the end (R-FX8).
                reader.advance()
                var code: [String] = []
                var end = line.end
                while let next = reader.peek(), fenceLanguage(next.text) == nil {
                    code.append(next.text)
                    end = next.end
                    reader.advance()
                }
                if let close = reader.peek() { end = close.end; reader.advance() }
                if !dropped, lang.lowercased() != "claims" {
                    add(.code, AttributedString(code.joined(separator: "\n")), line.start..<end)
                }
                continue
            }
            if dropped {
                reader.advance()
                continue
            }
            if let heading = headingLevel(trimmed, line.text) {
                add(.heading(level: heading.level), WikiInline.attributed(heading.text), line.start..<line.end)
                reader.advance()
                continue
            }
            if isRule(trimmed) {
                add(.rule, AttributedString(), line.start..<line.end)
                reader.advance()
                continue
            }
            if let quote = quoteText(line.text) {
                var parts = [quote]
                var end = line.end
                reader.advance()
                while let next = reader.peek(), let more = quoteText(next.text) {
                    parts.append(more)
                    end = next.end
                    reader.advance()
                }
                add(.quote, WikiInline.attributed(parts.joined(separator: " ")), line.start..<end)
                continue
            }
            if let item = listItem(line.text) {
                emitInline(item.text, line: line) { add(.item(marker: item.marker, indent: item.indent), $0, $1) } embed: { add($0, $1, $2) }
                reader.advance()
                continue
            }
            // A paragraph: consecutive plain lines, soft-wrapped into one row.
            var parts: [String] = []
            let start = line.start
            var end = line.end
            while let next = reader.peek() {
                let t = next.text.trimmingCharacters(in: .whitespaces)
                if t.isEmpty || fenceLanguage(next.text) != nil || headingLevel(t, next.text) != nil || isRule(t)
                    || quoteText(next.text) != nil || listItem(next.text) != nil { break }
                parts.append(next.text)
                end = next.end
                reader.advance()
            }
            emitInline(parts.joined(separator: " "), line: Line(text: "", start: start, end: end)) {
                add(.paragraph, $0, $1)
            } embed: { add($0, $1, $2) }
        }
        return WikiArticle(rows: rows, complete: reader.peek() == nil || rows.count < maxRows)
    }

    /// A line's text with its `![[embed]]` and `![alt](url)` tokens split out into rows of their own, in order
    /// (`TranscludingMarkdownView`'s segments).
    private static func emitInline(_ text: String, line: Line, text emitText: (AttributedString, Range<Int>) -> Void,
                                   embed emitEmbed: (WikiRow.Kind, AttributedString, Range<Int>) -> Void) {
        guard text.contains("!["), let regex = embedPattern else {
            emitText(WikiInline.attributed(text), line.start..<line.end)
            return
        }
        let ns = text as NSString
        var last = 0
        for match in regex.matches(in: text, range: NSRange(location: 0, length: ns.length)) {
            let before = ns.substring(with: NSRange(location: last, length: match.range.location - last))
            if !before.trimmingCharacters(in: .whitespaces).isEmpty {
                emitText(WikiInline.attributed(before), line.start..<line.end)
            }
            if match.range(at: 1).location != NSNotFound {
                emitEmbed(.embed(ref: ns.substring(with: match.range(at: 1))), AttributedString(), line.start..<line.end)
            } else if match.range(at: 3).location != NSNotFound {
                let alt = match.range(at: 2).location != NSNotFound ? ns.substring(with: match.range(at: 2)) : ""
                emitEmbed(.image(url: ns.substring(with: match.range(at: 3)), alt: alt), AttributedString(),
                          line.start..<line.end)
            }
            last = match.range.location + match.range.length
        }
        let rest = ns.substring(from: last)
        if !rest.trimmingCharacters(in: .whitespaces).isEmpty {
            emitText(WikiInline.attributed(rest), line.start..<line.end)
        }
    }

    // MARK: Line grammar (`MarkdownBody`'s, so an article reads as the page always did)

    private static let embedPattern = try? NSRegularExpression(pattern: "!\\[\\[(.+?)\\]\\]|!\\[([^\\]]*)\\]\\(([^)]+)\\)")
    private static let bulletPattern = try? NSRegularExpression(pattern: "^(\\s*)[-*+]\\s+(.*)$")
    private static let orderedPattern = try? NSRegularExpression(pattern: "^(\\s*)(\\d+)\\.\\s+(.*)$")

    static func fenceLanguage(_ line: String) -> String? {
        let trimmed = line.trimmingCharacters(in: .whitespaces)
        guard trimmed.hasPrefix("```") else { return nil }
        return String(trimmed.dropFirst(3)).trimmingCharacters(in: .whitespaces)
    }

    private static func headingLevel(_ trimmed: String, _ line: String) -> (level: Int, text: String)? {
        guard line.hasPrefix("#") else { return nil }
        let hashes = line.prefix { $0 == "#" }.count
        guard (1...6).contains(hashes) else { return nil }
        let rest = line.dropFirst(hashes)
        guard let first = rest.first, first == " " || first == "\t" else { return nil }
        return (hashes, rest.trimmingCharacters(in: .whitespaces))
    }

    private static func isRule(_ trimmed: String) -> Bool {
        guard trimmed.count >= 3, let mark = trimmed.first, "-*_".contains(mark) else { return false }
        return trimmed.allSatisfy { $0 == mark }
    }

    private static func quoteText(_ line: String) -> String? {
        let lead = line.drop { $0 == " " || $0 == "\t" }
        guard lead.first == ">" else { return nil }
        var rest = lead.dropFirst()
        if rest.first == " " { rest = rest.dropFirst() }
        return String(rest)
    }

    private static func listItem(_ line: String) -> (marker: String, indent: Int, text: String)? {
        guard let first = line.first(where: { $0 != " " && $0 != "\t" }), "-*+0123456789".contains(first) else {
            return nil
        }
        let ns = line as NSString
        let range = NSRange(location: 0, length: ns.length)
        if let m = bulletPattern?.firstMatch(in: line, range: range) {
            return ("•", ns.substring(with: m.range(at: 1)).count / 2, ns.substring(with: m.range(at: 2)))
        }
        if let m = orderedPattern?.firstMatch(in: line, range: range) {
            return ("\(ns.substring(with: m.range(at: 2))).", ns.substring(with: m.range(at: 1)).count / 2,
                    ns.substring(with: m.range(at: 3)))
        }
        return nil
    }

    fileprivate struct Line {
        let text: String
        let start: Int
        let end: Int
    }

    /// The text's lines with their Unicode-scalar offsets, read one at a time (a capped build reads only what it uses).
    private struct LineReader {
        private let scalars: String.UnicodeScalarView
        private var index: String.UnicodeScalarView.Index
        private var offset = 0
        private var current: Line?

        init(_ text: String) {
            scalars = text.unicodeScalars
            index = scalars.startIndex
            current = read()
        }

        func peek() -> Line? { current }
        mutating func advance() { current = read() }

        private mutating func read() -> Line? {
            guard index < scalars.endIndex else { return nil }
            let start = offset
            var cursor = index
            var count = 0
            while cursor < scalars.endIndex, scalars[cursor] != "\n" {
                cursor = scalars.index(after: cursor)
                count += 1
            }
            var text = String(scalars[index..<cursor])
            if text.hasSuffix("\r") { text.removeLast() }
            offset = start + count
            if cursor < scalars.endIndex {
                cursor = scalars.index(after: cursor)
                offset += 1
            }
            index = cursor
            return Line(text: text, start: start, end: start + count)
        }
    }
}

/// One line's inline markdown, rendered once: bold, italic, inline code and links, with `[[wikilinks]]` as
/// `cicada://entity/…` links (`MarkdownBody.linkifyWikilinks`, the one rewrite). Links carry the accent and an
/// underline (DR-5's link use); every other run takes the `Text`'s own colour, so a cached article follows the theme.
enum WikiInline {
    static func attributed(_ raw: String) -> AttributedString {
        let prepped = MarkdownBody.linkifyWikilinks(raw)
        var attr = (try? AttributedString(
            markdown: prepped,
            options: AttributedString.MarkdownParsingOptions(interpretedSyntax: .inlineOnlyPreservingWhitespace)
        )) ?? AttributedString(prepped)
        for run in attr.runs where run.link != nil {
            attr[run.range].foregroundColor = CicadaTheme.accent
            attr[run.range].underlineStyle = .single
        }
        return attr
    }
}

// MARK: - Cache

/// Built articles by text, so a card reopened (or re-rendered by a graph push) never parses again. Not a Store domain:
/// derived from the page body the Store already holds, in memory only, a few entries (an owner-sized article is ~1 MB).
@MainActor @Observable
final class WikiArticleCache {
    static let shared = WikiArticleCache()
    static let firstScreenRows = 48

    struct Key: Hashable {
        let markdown: String
        let dropping: Set<String>
    }

    private(set) var built: [Key: WikiArticle] = [:]
    @ObservationIgnored private var order: [Key] = []
    @ObservationIgnored private var heads: [Key: WikiArticle] = [:]
    @ObservationIgnored private var inFlight: [Key: Task<Void, Never>] = [:]
    private let capacity: Int

    init(capacity: Int = 6) { self.capacity = max(1, capacity) }

    /// What to draw now: the whole article once built, else its first screen — built here, synchronously and once, so
    /// a page never draws blank while the rest is read (`build(_:)`). Writes only unobserved storage: it runs while a
    /// view is being drawn.
    func article(_ key: Key) -> WikiArticle {
        if let full = built[key] { return full }
        if let head = heads[key] { return head }
        let head = WikiArticle.build(key.markdown, dropping: key.dropping, maxRows: Self.firstScreenRows)
        if heads.count >= capacity * 4 { heads.removeAll() }
        heads[key] = head
        return head
    }

    /// Reads the whole article off the main actor, once per text; nothing to read when the first screen was all of it.
    func build(_ key: Key) async {
        if built[key] != nil || heads[key]?.complete == true { return }
        if let running = inFlight[key] { return await running.value }
        let task = Task { [weak self] in
            let article = await Task.detached(priority: .userInitiated) {
                WikiArticle.build(key.markdown, dropping: key.dropping)
            }.value
            self?.store(article, for: key)
            self?.heads[key] = nil
            self?.inFlight[key] = nil
        }
        inFlight[key] = task
        await task.value
    }

    private func store(_ article: WikiArticle, for key: Key) {
        built[key] = article
        order.removeAll { $0 == key }
        order.append(key)
        while order.count > capacity {
            let evicted = order.removeFirst()
            built[evicted] = nil
        }
    }
}

// MARK: - A line's provenance

/// "Where this line came from" — one click from any line of the article (owner 2026-10-09). `/provenance`'s section
/// items (G118) carry the ranges of the served prose they describe; a line opens the first item that covers it and
/// has evidence, in the Reader (DR-31). Nil when the served prose changed since `/provenance` was read
/// (`pageBodyHash`), or no item covers the line — the caller then opens the page's own "Where this came from".
enum LineProvenance {
    static func target(for row: WikiRow, body: String, provenance: EntityProvenance?, subjectId: String) -> ReaderTarget? {
        guard let provenance, !provenance.sections.isEmpty, provenance.pageBodyHash == bodyHash(body) else { return nil }
        for section in provenance.sections {
            for item in section.items where item.bodyRanges.contains(where: { overlaps($0, row.source) }) {
                for evidence in item.evidence {
                    let title = evidence.sourceTitle.isEmpty ? nil : evidence.sourceTitle
                    if let span = evidence.span {
                        return ReaderTarget.best(span, subjectId: subjectId, knownTitle: title)
                    }
                    if let ev = evidence.evidence,
                       let target = ReaderTarget.evidence(ev, subjectId: subjectId, knownTitle: title) {
                        return target
                    }
                }
            }
        }
        return nil
    }

    /// `evidence.body_hash`: the first 12 hex digits of the text's SHA-256.
    static func bodyHash(_ text: String) -> String {
        SHA256.hash(data: Data(text.utf8)).map { String(format: "%02x", $0) }.joined().prefix(12).description
    }

    private static func overlaps(_ range: [Int], _ row: Range<Int>) -> Bool {
        guard range.count == 2, range[1] > range[0] else { return false }
        return range[0] < row.upperBound && row.lowerBound < range[1]
    }
}
