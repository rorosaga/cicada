import Foundation

/// ROR-15, G161 — an Apple Note as the note itself draws it: Notes' HTML walked into blocks and tied, scalar by scalar,
/// to the stored plain text, so a span's offsets (`source_spans`) wash the same words here as in the plain view. The HTML
/// is untrusted data: nothing in it is run, loaded or kept, only text, a closed set of styles and checked links. Held in
/// memory for the note on screen; never posted, never stored.
struct NoteDocument: Hashable {
    struct Style: OptionSet, Hashable {
        let rawValue: Int
        static let bold = Style(rawValue: 1)
        static let italic = Style(rawValue: 2)
        static let underline = Style(rawValue: 4)
        static let strike = Style(rawValue: 8)
        static let mono = Style(rawValue: 16)
    }

    struct Run: Hashable {
        let range: Range<Int>
        let style: Style
        let link: URL?
    }

    enum Marker: Hashable {
        case bullet, dash
        case number(Int)
        case check(done: Bool)
    }

    enum Kind: Hashable {
        case title
        /// By tag: Notes writes its Heading as `h2` and Subheading as `h3`; 3 is anything smaller.
        case heading(Int)
        case paragraph
        case item(Marker, depth: Int)
        /// A later line of a list item: under its text, no marker.
        case itemLine(depth: Int)
        case quote
        case code
        /// Each cell a range of `scalars`.
        case table([[Range<Int>]])
        case blank
    }

    struct Block: Hashable {
        var kind: Kind
        var scalars: [Unicode.Scalar]
        var runs: [Run]
        /// For each scalar, its offset in the stored text; -1 where it has none (a cell's separator, an attachment's table).
        var map: [Int] = []

        var text: String {
            var view = String.UnicodeScalarView()
            view.append(contentsOf: scalars)
            return String(view)
        }

        /// The stretches of this block that `span` (stored offsets) covers, local to `scalars`.
        func ranges(of span: Range<Int>) -> [Range<Int>] {
            var out: [Range<Int>] = []
            var start: Int?
            for (i, at) in map.enumerated() {
                if span.contains(at) {
                    if start == nil { start = i }
                } else if let s = start {
                    out.append(s..<i)
                    start = nil
                }
            }
            if let s = start { out.append(s..<map.count) }
            return out
        }
    }

    let id = UUID()
    let blocks: [Block]
    /// The note's name on the stored text's own `# name` line, and where those words start in the note's first line.
    let storedTitle: Range<Int>?
    let titleInBody: Int?

    static func == (a: NoteDocument, b: NoteDocument) -> Bool { a.id == b.id }
    func hash(into hasher: inout Hasher) { hasher.combine(id) }

    /// A span's stretches in this block; the part on the stored `# name` line lands on the same words in the first line.
    func ranges(of span: Range<Int>, in block: Block) -> [Range<Int>] {
        var out = block.ranges(of: span)
        if let storedTitle, let titleInBody, span.overlaps(storedTitle) {
            let lo = max(span.lowerBound, storedTitle.lowerBound), hi = min(span.upperBound, storedTitle.upperBound)
            let delta = titleInBody - storedTitle.lowerBound
            out += block.ranges(of: (lo + delta)..<(hi + delta))
        }
        return out
    }

    /// Whether the formatted page shows this span at all. One it cannot show (on a stored `**Folder:**` line) keeps the
    /// plain view: a citation's words are never lost to formatting.
    func draws(_ span: Range<Int>) -> Bool {
        blocks.contains { !ranges(of: span, in: $0).isEmpty }
    }

    // MARK: Building

    /// A note's pictures arrive inline in its HTML; past this a note stays in plain text rather than cost the parse.
    static let maxHTMLBytes = 40_000_000

    /// The note, or nil when its words are not the stored words. `stored` is the document's whole evidence text.
    static func build(html: String, stored: String) -> NoteDocument? {
        guard html.utf8.count <= maxHTMLBytes else { return nil }
        var blocks = NoteHTML.blocks(html)
        guard blocks.contains(where: { !$0.scalars.isEmpty }) else { return nil }
        let scalars = Array(stored.unicodeScalars)
        let head = NoteAlignment.header(scalars)
        guard NoteAlignment.align(&blocks, stored: scalars, from: head.bodyStart) else { return nil }
        var inBody: Int?
        if let title = head.title, let first = blocks.first(where: { !$0.scalars.isEmpty }),
           first.scalars.starts(with: scalars[title]), let at = first.map.first, at >= 0 {
            inBody = at
        }
        return NoteDocument(blocks: blocks, storedTitle: head.title, titleInBody: inBody)
    }
}

// MARK: - Matching the stored text

/// The same ladder as `evidence.locate`: exact, then whitespace, then case, and stop; never fuzzy. A note's lines are
/// walked in order against the stored text, so "the words are the same" is checked for the whole note, and what may
/// differ is named here: whitespace between words, an attachment's object character, a list marker at the start of a
/// list item's stored line. An attachment's table may be one object character when the stored text holds that.
enum NoteAlignment {
    static let objectCharacter: Unicode.Scalar = "\u{FFFC}"

    /// What `notes_sync._episode_body` puts above the note's text: `# name`, a blank line, the filing lines.
    static func header(_ s: [Unicode.Scalar]) -> (title: Range<Int>?, bodyStart: Int) {
        func lineEnd(_ from: Int) -> Int { s[from...].firstIndex(of: "\n") ?? s.count }
        guard s.starts(with: "# ".unicodeScalars) else { return (nil, 0) }
        let end = lineEnd(0)
        var i = min(end + 1, s.count)
        let labels = ["**Folder:**", "**Modified:**"].map { Array($0.unicodeScalars) }
        while i < s.count {
            let e = lineEnd(i)
            let line = s[i..<e]
            let blank = line.allSatisfy(\.properties.isWhitespace)
            guard blank || labels.contains(where: { line.starts(with: $0) }) else { break }
            i = min(e + 1, s.count)
        }
        return (2..<end, i)
    }

    static func align(_ blocks: inout [NoteDocument.Block], stored: [Unicode.Scalar], from start: Int) -> Bool {
        for fold in [false, true] {
            var attempt = blocks
            if walk(&attempt, stored, start, foldCase: fold) {
                blocks = attempt
                return true
            }
        }
        return false
    }

    private static func walk(_ blocks: inout [NoteDocument.Block], _ s: [Unicode.Scalar], _ start: Int,
                             foldCase: Bool) -> Bool {
        var j = start
        func space(_ c: Unicode.Scalar) -> Bool { c.properties.isWhitespace }
        func same(_ a: Unicode.Scalar, _ b: Unicode.Scalar) -> Bool {
            a == b || (foldCase && a.properties.lowercaseMapping == b.properties.lowercaseMapping)
        }
        for index in blocks.indices {
            let scalars = blocks[index].scalars
            var map = [Int](repeating: -1, count: scalars.count)
            defer { blocks[index].map = map }
            guard !scalars.isEmpty else { continue }
            while j < s.count, space(s[j]) { j += 1 }
            if case .table = blocks[index].kind, j < s.count, s[j] == objectCharacter {
                j += 1
                continue
            }
            while j < s.count, space(s[j]) || s[j] == objectCharacter { j += 1 }
            if case .item = blocks[index].kind, j < s.count, !same(s[j], scalars[0]), let after = afterMarker(s, j) {
                j = after
            }
            var i = 0
            while i < scalars.count {
                if space(scalars[i]) {
                    let before = j
                    while j < s.count, space(s[j]) || s[j] == objectCharacter { j += 1 }
                    guard j > before else { return false }
                    map[i] = before
                    i += 1
                    while i < scalars.count, space(scalars[i]) { i += 1 }
                    continue
                }
                while j < s.count, s[j] == objectCharacter { j += 1 }
                guard j < s.count, same(s[j], scalars[i]) else { return false }
                map[i] = j
                i += 1
                j += 1
            }
        }
        while j < s.count, space(s[j]) || s[j] == objectCharacter { j += 1 }
        return j == s.count
    }

    /// Past a list marker a stored line may open with: one bullet, dash or check glyph, or digits and `.`/`)`, then space.
    static func afterMarker(_ s: [Unicode.Scalar], _ at: Int) -> Int? {
        func gap(_ c: Unicode.Scalar) -> Bool { c == " " || c == "\t" || c == "\u{00A0}" }
        var j = at
        if "•◦▪‣∙·*-–—☐☑☒✓✔".unicodeScalars.contains(s[j]) {
            j += 1
        } else {
            while j < s.count, s[j].value >= 48, s[j].value <= 57, j - at < 6 { j += 1 }
            guard j > at, j < s.count, s[j] == "." || s[j] == ")" else { return nil }
            j += 1
        }
        guard j < s.count, gap(s[j]) else { return nil }
        while j < s.count, gap(s[j]) { j += 1 }
        return j
    }
}

// MARK: - Reading the HTML

/// A small, closed reader of what Notes writes. Not a browser: an element it does not know gives its text at most, and
/// these give nothing, whatever they hold.
enum NoteHTML {
    fileprivate static let dropped: Set<String> = [
        "script", "style", "head", "title", "iframe", "svg", "math", "noscript", "template", "canvas", "audio", "video",
        "applet", "select", "textarea", "button", "map", "frameset", "noembed", "noframes",
    ]
    fileprivate static let void: Set<String> = ["hr", "img", "meta", "link", "embed", "source", "area", "base", "col",
                                                "param", "track", "wbr"]
    fileprivate static let blockTags: Set<String> = [
        "div", "p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "ul", "ol", "blockquote", "pre", "table", "tr", "td", "th",
        "body", "html", "section", "article", "dl", "dt", "dd", "center", "address", "tbody", "thead", "tfoot", "caption",
        "object",
    ]
    fileprivate static let tableTags: Set<String> = ["table", "tr", "td", "th"]

    static func blocks(_ html: String) -> [NoteDocument.Block] {
        var builder = Builder()
        Tokens.walk(html) { builder.take($0) }
        return builder.finish()
    }

    enum Token {
        case text(String)
        case open(String, [String: String])
        case close(String)
    }

    private struct Inline {
        let name: String
        let style: NoteDocument.Style
        let link: URL?
        let size: Double?
    }

    private struct Piece {
        var text: String
        let style: NoteDocument.Style
        let link: URL?
    }

    private struct Builder {
        var out: [NoteDocument.Block] = []
        var pieces: [Piece] = []
        var inline: [Inline] = []
        var lists: [NoteDocument.Marker] = []
        var marker: NoteDocument.Marker?
        var heading: Int?
        var quote = 0
        var pre = 0
        var dropName: String?
        var dropDepth = 0
        var lineSize: Double = 0
        var tableDepth = 0
        var rows: [[[Piece]]] = []
        var cell: [Piece]?

        mutating func take(_ token: Token) {
            if let name = dropName {
                switch token {
                case let .open(other, _) where other == name: dropDepth += 1
                case let .close(other) where other == name:
                    dropDepth -= 1
                    if dropDepth == 0 { dropName = nil }
                default: break
                }
                return
            }
            switch token {
            case let .text(text): add(text)
            case let .open(name, attrs): open(name, attrs)
            case let .close(name): close(name)
            }
        }

        private mutating func add(_ raw: String) {
            var text = raw
            if pre == 0 {
                var view = String.UnicodeScalarView()
                var spaced = pieces.last?.text.hasSuffix(" ") ?? true
                for c in raw.unicodeScalars {
                    if c == " " || c == "\n" || c == "\r" || c == "\t" || c == "\u{0C}" {
                        if !spaced { view.append(" ") }
                        spaced = true
                    } else {
                        view.append(c)
                        spaced = false
                    }
                }
                text = String(view)
            }
            guard !text.isEmpty else { return }
            var style = NoteDocument.Style()
            var link: URL?
            for level in inline {
                style.formUnion(level.style)
                if let l = level.link { link = l }
                if let size = level.size { lineSize = max(lineSize, size) }
            }
            if let last = pieces.last, last.style == style, last.link == link {
                pieces[pieces.count - 1].text += text
            } else {
                pieces.append(Piece(text: text, style: style, link: link))
            }
        }

        private mutating func open(_ name: String, _ attrs: [String: String]) {
            if NoteHTML.dropped.contains(name) {
                dropName = name
                dropDepth = 1
            } else if name == "br" {
                if tableDepth > 0 {
                    add(" ")
                } else if pieces.isEmpty {
                    out.append(.init(kind: .blank, scalars: [], runs: []))
                } else {
                    flush()
                }
            } else if name == "input" {
                if attrs["type"]?.lowercased() == "checkbox", marker != nil { marker = .check(done: attrs["checked"] != nil) }
            } else if NoteHTML.void.contains(name) {
                return
            } else if NoteHTML.blockTags.contains(name) {
                openBlock(name, attrs)
            } else {
                inline.append(Self.inline(name, attrs))
            }
        }

        private mutating func openBlock(_ name: String, _ attrs: [String: String]) {
            if tableDepth > 0, !NoteHTML.tableTags.contains(name) {
                add(" ")
                inline.append(Self.inline(name, attrs))
                return
            }
            flush()
            // A block carries its own inline look, as `<div style="font-weight:bold">` does.
            inline.append(Self.inline(name, attrs))
            switch name {
            case "h1", "h2", "h3", "h4", "h5", "h6": heading = min(Int(String(name.dropFirst())) ?? 3, 3)
            case "blockquote": quote += 1
            case "pre": pre += 1
            case "ul": lists.append(Self.isCheck(attrs) ? .check(done: false) : Self.isDash(attrs) ? .dash : .bullet)
            case "ol": lists.append(.number(attrs["start"].flatMap(Int.init).map { min(max($0, 0), 99_999) } ?? 1))
            case "li": openItem(attrs)
            case "table":
                tableDepth += 1
                if tableDepth == 1 { rows = [] }
            case "tr":
                if tableDepth == 1 { rows.append([]) }
            case "td", "th":
                if tableDepth == 1 {
                    if rows.isEmpty { rows.append([]) }
                    cell = []
                }
            default: break
            }
        }

        private mutating func openItem(_ attrs: [String: String]) {
            var kind = lists.last ?? .bullet
            if case .number = kind, let value = attrs["value"].flatMap(Int.init) { kind = .number(min(max(value, 0), 99_999)) }
            if case let .number(n) = kind, !lists.isEmpty { lists[lists.count - 1] = .number(n + 1) }
            var isCheckItem = Self.isCheck(attrs)
            if case .check = kind { isCheckItem = true }
            marker = isCheckItem ? .check(done: Self.isDone(attrs)) : kind
        }

        private mutating func close(_ name: String) {
            if tableDepth > 0, !NoteHTML.tableTags.contains(name) {
                popInline(name)
                return
            }
            guard NoteHTML.blockTags.contains(name) else {
                popInline(name)
                return
            }
            flush()
            popInline(name)
            switch name {
            case "h1", "h2", "h3", "h4", "h5", "h6": heading = nil
            case "blockquote": quote = max(0, quote - 1)
            case "pre": pre = max(0, pre - 1)
            case "ul", "ol": if !lists.isEmpty { lists.removeLast() }
            case "li": marker = nil
            case "td", "th":
                if tableDepth == 1, let finished = cell, !rows.isEmpty {
                    rows[rows.count - 1].append(finished)
                    cell = nil
                }
            case "table":
                tableDepth = max(0, tableDepth - 1)
                if tableDepth == 0 { emitTable() }
            default: break
            }
        }

        private mutating func popInline(_ name: String) {
            if let at = inline.lastIndex(where: { $0.name == name }) { inline.remove(at: at) }
        }

        /// The current line becomes a block, or a table's cell its words.
        private mutating func flush() {
            defer { lineSize = 0 }
            trimTrailing()
            guard !pieces.isEmpty else { return }
            if tableDepth > 0 {
                cell?.append(contentsOf: pieces)
                pieces = []
                return
            }
            let (scalars, runs) = Self.linear(pieces)
            pieces = []
            let depth = max(0, lists.count - 1)
            let kind: NoteDocument.Kind
            if let marker {
                kind = .item(marker, depth: depth)
                self.marker = nil
            } else if !lists.isEmpty {
                kind = .itemLine(depth: depth)
            } else if let heading {
                kind = .heading(heading)
            } else if pre > 0 {
                kind = .code
            } else if quote > 0 {
                kind = .quote
            } else if lineSize >= 22 {
                kind = .heading(1)
            } else if lineSize >= 17 {
                kind = .heading(2)
            } else {
                kind = .paragraph
            }
            out.append(.init(kind: kind, scalars: scalars, runs: runs))
        }

        private mutating func trimTrailing() {
            guard pre == 0 else { return }
            while let last = pieces.last {
                var text = last.text
                while text.hasSuffix(" ") { text.removeLast() }
                if text.isEmpty {
                    pieces.removeLast()
                } else {
                    pieces[pieces.count - 1].text = text
                    return
                }
            }
        }

        private mutating func emitTable() {
            var scalars: [Unicode.Scalar] = []
            var runs: [NoteDocument.Run] = []
            var grid: [[Range<Int>]] = []
            for row in rows where !row.isEmpty {
                var ranges: [Range<Int>] = []
                for cellPieces in row {
                    if !scalars.isEmpty { scalars.append("\n") }
                    let start = scalars.count
                    let (cellScalars, cellRuns) = Self.linear(cellPieces)
                    scalars.append(contentsOf: cellScalars)
                    runs += cellRuns.map {
                        .init(range: ($0.range.lowerBound + start)..<($0.range.upperBound + start), style: $0.style,
                              link: $0.link)
                    }
                    ranges.append(start..<scalars.count)
                }
                grid.append(ranges)
            }
            rows = []
            if !grid.isEmpty { out.append(.init(kind: .table(grid), scalars: scalars, runs: runs)) }
        }

        private static func linear(_ pieces: [Piece]) -> ([Unicode.Scalar], [NoteDocument.Run]) {
            var scalars: [Unicode.Scalar] = []
            var runs: [NoteDocument.Run] = []
            for piece in pieces {
                let start = scalars.count
                scalars.append(contentsOf: piece.text.unicodeScalars)
                runs.append(.init(range: start..<scalars.count, style: piece.style, link: piece.link))
            }
            return (scalars, runs)
        }

        private static func inline(_ name: String, _ attrs: [String: String]) -> Inline {
            var style = NoteDocument.Style()
            var size: Double?
            switch name {
            case "b", "strong": style.insert(.bold)
            case "i", "em": style.insert(.italic)
            case "u", "ins": style.insert(.underline)
            case "s", "strike", "del": style.insert(.strike)
            case "tt", "code", "kbd", "samp", "pre": style.insert(.mono)
            default: break
            }
            for declaration in (attrs["style"] ?? "").split(separator: ";") {
                let parts = declaration.split(separator: ":", maxSplits: 1)
                guard parts.count == 2 else { continue }
                let key = parts[0].trimmingCharacters(in: .whitespaces).lowercased()
                let value = parts[1].trimmingCharacters(in: .whitespaces).lowercased()
                switch key {
                case "font-weight": if value == "bold" || (Int(value) ?? 0) >= 600 { style.insert(.bold) }
                case "font-style": if value.hasPrefix("italic") { style.insert(.italic) }
                case "text-decoration", "text-decoration-line":
                    if value.contains("underline") { style.insert(.underline) }
                    if value.contains("line-through") { style.insert(.strike) }
                case "font-size": if value.hasSuffix("px") { size = Double(value.dropLast(2)) }
                default: break
                }
            }
            let link = name == "a" ? attrs["href"].flatMap(ItemPlaceOpen.webURL) : nil
            return Inline(name: name, style: style, link: link, size: size)
        }

        private static func isDash(_ attrs: [String: String]) -> Bool {
            (attrs["class"] ?? "").lowercased().contains("dash")
        }

        private static func isCheck(_ attrs: [String: String]) -> Bool {
            let cls = (attrs["class"] ?? "").lowercased()
            return cls.contains("check") || cls.contains("todo") || attrs["data-checked"] != nil
        }

        private static func isDone(_ attrs: [String: String]) -> Bool {
            if let flag = attrs["data-checked"]?.lowercased() { return flag == "true" || flag == "1" }
            let words = (attrs["class"] ?? "").lowercased().split(whereSeparator: { !$0.isLetter && $0 != "-" })
            return words.contains { ["checked", "done", "completed", "apple-checked"].contains(String($0)) }
        }

        mutating func finish() -> [NoteDocument.Block] {
            flush()
            if tableDepth > 0 { emitTable() }
            var kept: [NoteDocument.Block] = []
            for block in out {
                if block.kind == .blank, kept.isEmpty || kept.last?.kind == .blank { continue }
                kept.append(block)
            }
            if kept.last?.kind == .blank { kept.removeLast() }
            // Notes' first line is the note's title, however it is marked.
            if let first = kept.first {
                switch first.kind {
                case .paragraph, .heading: kept[0].kind = .title
                default: break
                }
            }
            return kept
        }
    }

    // MARK: Tokens

    enum Tokens {
        /// Over UTF-8 bytes, because a note's pictures make this long: tags are ASCII, and a huge attribute value is
        /// stepped over without being copied.
        static func walk(_ html: String, _ emit: (Token) -> Void) {
            let b = Array(html.utf8)
            let gt = UInt8(ascii: ">")
            var i = 0
            var start = 0
            func text(_ r: Range<Int>) {
                guard !r.isEmpty else { return }
                let t = entities(String(decoding: b[r], as: UTF8.self))
                if !t.isEmpty { emit(.text(t)) }
            }
            while i < b.count {
                guard b[i] == UInt8(ascii: "<"), i + 1 < b.count else {
                    i += 1
                    continue
                }
                let next = b[i + 1]
                if next == UInt8(ascii: "!") || next == UInt8(ascii: "?") {
                    text(start..<i)
                    i = has(b, i, "<!--") ? (find(b, "-->", from: i + 4).map { $0 + 3 } ?? b.count)
                                          : (b[i...].firstIndex(of: gt).map { $0 + 1 } ?? b.count)
                    start = i
                } else if next == UInt8(ascii: "/") || isLetter(next) {
                    text(start..<i)
                    i = tag(b, i, emit)
                    start = i
                } else {
                    i += 1
                }
            }
            text(start..<b.count)
        }

        /// One tag from `<`; returns where the text after it starts. A `script` or `style` is skipped to its own close,
        /// so nothing inside it reads as a tag.
        private static func tag(_ b: [UInt8], _ from: Int, _ emit: (Token) -> Void) -> Int {
            let gt = UInt8(ascii: ">")
            var i = from + 1
            let closing = b[i] == UInt8(ascii: "/")
            if closing { i += 1 }
            let nameStart = i
            while i < b.count, isName(b[i]) { i += 1 }
            let name = String(decoding: b[nameStart..<i], as: UTF8.self).lowercased()
            var attrs: [String: String] = [:]
            while i < b.count, b[i] != gt {
                if isSpace(b[i]) || b[i] == UInt8(ascii: "/") {
                    i += 1
                    continue
                }
                let keyStart = i
                while i < b.count, !isSpace(b[i]), b[i] != UInt8(ascii: "="), b[i] != gt { i += 1 }
                let key = String(decoding: b[keyStart..<i], as: UTF8.self).lowercased()
                if i == keyStart { i += 1 }
                while i < b.count, isSpace(b[i]) { i += 1 }
                var value = ""
                if i < b.count, b[i] == UInt8(ascii: "=") {
                    i += 1
                    while i < b.count, isSpace(b[i]) { i += 1 }
                    let quote = i < b.count && (b[i] == 0x22 || b[i] == 0x27) ? b[i] : nil
                    if quote != nil { i += 1 }
                    let valueStart = i
                    if let quote {
                        i = b[i...].firstIndex(of: quote) ?? b.count
                    } else {
                        while i < b.count, !isSpace(b[i]), b[i] != gt { i += 1 }
                    }
                    // A picture's inline data is never read; only short values are.
                    if i - valueStart <= 8_192 { value = entities(String(decoding: b[valueStart..<i], as: UTF8.self)) }
                    if quote != nil, i < b.count { i += 1 }
                }
                if !key.isEmpty { attrs[key] = value }
            }
            if i < b.count { i += 1 }
            guard !name.isEmpty else { return i }
            if closing {
                emit(.close(name))
            } else if name == "script" || name == "style" {
                return afterClose(b, name, from: i)
            } else {
                emit(.open(name, attrs))
            }
            return i
        }

        private static func afterClose(_ b: [UInt8], _ name: String, from: Int) -> Int {
            let needle = Array("</\(name)".utf8)
            var i = from
            while i + needle.count <= b.count {
                if b[i] == needle[0], zip(b[i..<(i + needle.count)], needle).allSatisfy({ lower($0) == $1 }) {
                    return b[i...].firstIndex(of: UInt8(ascii: ">")).map { $0 + 1 } ?? b.count
                }
                i += 1
            }
            return b.count
        }

        private static func has(_ b: [UInt8], _ at: Int, _ s: String) -> Bool {
            let n = Array(s.utf8)
            return at + n.count <= b.count && b[at..<(at + n.count)].elementsEqual(n)
        }

        private static func find(_ b: [UInt8], _ s: String, from: Int) -> Int? {
            var i = from
            while i < b.count {
                if has(b, i, s) { return i }
                i += 1
            }
            return nil
        }

        private static func lower(_ c: UInt8) -> UInt8 { (65...90).contains(c) ? c + 32 : c }
        private static func isLetter(_ c: UInt8) -> Bool { (65...90).contains(c) || (97...122).contains(c) }
        private static func isName(_ c: UInt8) -> Bool { isLetter(c) || (48...57).contains(c) || c == 45 || c == 58 }
        private static func isSpace(_ c: UInt8) -> Bool { c == 32 || c == 9 || c == 10 || c == 13 || c == 12 }

        private static let named: [String: String] = [
            "amp": "&", "lt": "<", "gt": ">", "quot": "\"", "apos": "'", "nbsp": "\u{00A0}", "ndash": "–", "mdash": "—",
            "hellip": "…", "lsquo": "‘", "rsquo": "’", "ldquo": "“", "rdquo": "”", "bull": "•", "middot": "·",
        ]

        static func entities(_ text: String) -> String {
            guard text.contains("&") else { return text }
            var out = ""
            var rest = Substring(text)
            while let amp = rest.firstIndex(of: "&") {
                out += rest[..<amp]
                let after = rest[rest.index(after: amp)...]
                if let semi = after.prefix(12).firstIndex(of: ";"), let decoded = entity(String(after[..<semi])) {
                    out += decoded
                    rest = after[after.index(after: semi)...]
                } else {
                    out += "&"
                    rest = after
                }
            }
            return out + rest
        }

        private static func entity(_ name: String) -> String? {
            if name.hasPrefix("#") {
                let digits = name.dropFirst()
                let code = digits.first == "x" || digits.first == "X" ? UInt32(digits.dropFirst(), radix: 16)
                                                                      : UInt32(digits, radix: 10)
                return code.flatMap(Unicode.Scalar.init).map { String(Character($0)) }
            }
            return named[name]
        }
    }
}
