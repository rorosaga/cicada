import AppKit
import SwiftUI

// MARK: - The article as one text (owner 2026-11-23, "ok rebuild"; DESIGN_RULES §9)
//
// The entity page's article is drawn by one text engine, so it selects like text in a Mac reading app: a run of
// consecutive text rows (headings, paragraphs, list items, quotes) is ONE `NSAttributedString` in one `NSTextView`
// (`PageTextView`), and a drag crosses words, chips, quiet links and the cluster, and runs from one paragraph into the
// next. A chip and the cluster are text attachments (`PageInlineAttachment`) whose views are the same SwiftUI views the
// page always drew (`PageLinkChip`, `SourceCluster`); a quiet link is text carrying a link. What a copy yields is the
// prose: every piece of the string that is not its own words carries what it stands for (`PageText.plainKey`) — a chip
// its page's name, the cluster and the joiners nothing, a bullet "- ".

/// One paragraph of a run: a row of the article, cut into the pieces `PageInline` made.
struct PageTextParagraph: Equatable {
    enum Style: Equatable {
        case body
        case heading(level: Int)
        case item(marker: String, indent: Int)
        case quote
    }

    /// The row's id (`WikiRow.id`); a belief paragraph's is its own.
    let id: Int
    let style: Style
    let pieces: [PageInlinePiece]
    /// The space above it (`WikiRowView.gap`); a run's first paragraph has none, the stack spaces the run.
    var gapBefore: CGFloat = 0
    /// The 🔗 button's column is kept free at the trailing edge (a line that carries web links).
    var gutter = false
}

/// A thing in the text the keyboard can land on, in reading order: a chip, a quiet link (all its words), the cluster.
/// A quiet link's hover fill and its focus are one drawing (`PageTextView`), a chip's and the cluster's their own views'.
struct PageStop: Equatable {
    enum Kind: Equatable { case chip, quiet, cluster }
    let kind: Kind
    /// A chip's or cluster's stop number (its attachment's), or a quiet link's group.
    let id: Int
    /// The characters it covers (a quiet link: from its first word to its last).
    let range: NSRange
    /// What ⏎ opens; the cluster opens its own popover.
    let url: URL?
}

/// A run, built: the text and where each row sits in it.
struct PageTextDocument {
    let text: NSAttributedString
    /// The keyboard's stops, in order.
    var stops: [PageStop] = []
    /// Each paragraph's id and its range in `text` (the line break after it excluded), in order.
    let rows: [(id: Int, range: NSRange)]
    /// The characters of each quiet link, by group, so the words of one link light together.
    let groups: [Int: [NSRange]]

    /// What a copy of `range` yields (`PageText.plainKey`).
    func plain(_ range: NSRange) -> String { PageText.plain(text, range) }

    /// The row that holds the character at `index`.
    func row(at index: Int) -> Int? {
        var low = 0
        var high = rows.count - 1
        while low <= high {
            let mid = (low + high) / 2
            let range = rows[mid].range
            if index < range.location { high = mid - 1 } else if index > range.location + range.length { low = mid + 1 } else {
                return rows[mid].id
            }
        }
        return nil
    }
}

/// A word of an edited passage in a past sleep's page change (owner 2026-11-24: "the words that changed inline"): added
/// words wear a quiet wash of the added colour, removed words are struck through in tertiary ink. Carried on the words'
/// own `AttributedString` runs, so the one article engine draws it and nothing else about the article differs.
enum ProseMark: AttributedStringKey {
    typealias Value = Kind
    static let name = "cicada.proseMark"

    enum Kind: Hashable, Sendable { case added, removed }

    /// The look of a marked word, merged into the run's text attributes.
    static func attributes(_ kind: Kind) -> [NSAttributedString.Key: Any] {
        switch kind {
        case .added:
            return [.backgroundColor: NSColor(CicadaTheme.success).withAlphaComponent(0.22)]
        case .removed:
            return [.strikethroughStyle: NSUnderlineStyle.single.rawValue,
                    .strikethroughColor: NSColor(CicadaTheme.textTertiary),
                    .foregroundColor: NSColor(CicadaTheme.textTertiary)]
        }
    }
}

enum PageText {
    /// What a range of the text stands for in a copy (a String), where it is not its own words.
    static let plainKey = NSAttributedString.Key("cicada.plain")
    /// The group of a quiet link's characters (an Int).
    static let groupKey = NSAttributedString.Key("cicada.group")
    /// A quote's paragraph, which draws its rule at the leading edge (a Bool).
    static let quoteKey = NSAttributedString.Key("cicada.quote")

    /// U+2060: forbids a break on either side, so a full stop never starts a line and the cluster is never alone on one.
    static let joiner = "\u{2060}"

    /// The marker column of a list item, as the old layout drew it: 16 pt, then 6 before the words, 14 per level.
    static var markerColumn: CGFloat { CicadaTheme.scaled(16) }
    static var markerGap: CGFloat { CicadaTheme.scaled(6) }
    static var indentStep: CGFloat { CicadaTheme.scaled(14) }
    static var quoteInset: CGFloat { 3 + CicadaTheme.spacingSM }
    /// The room a line with web links keeps for its 🔗 button (the old row's trailing padding).
    static var gutterWidth: CGFloat { CicadaTheme.scaled(28) }

    // MARK: Type

    static func size(_ style: PageTextParagraph.Style) -> CGFloat {
        switch style {
        case .heading(let level):
            switch level {
            case 1: CicadaTheme.scaled(20)
            case 2: CicadaTheme.scaled(17)
            case 3: CicadaTheme.scaled(14)
            default: CicadaTheme.scaled(12)
            }
        default: CicadaTheme.scaled(14)
        }
    }

    static func baseFont(_ style: PageTextParagraph.Style) -> NSFont {
        if case .heading(let level) = style {
            return NSFont.systemFont(ofSize: size(style), weight: level <= 3 ? .semibold : .semibold)
        }
        return NSFont.systemFont(ofSize: size(style))
    }

    static func font(_ base: NSFont, intent: InlinePresentationIntent?, italic: Bool) -> NSFont {
        var font = base
        if let intent, intent.contains(.code) {
            font = NSFont.monospacedSystemFont(ofSize: base.pointSize, weight: .regular)
        }
        var traits: NSFontDescriptor.SymbolicTraits = []
        if intent?.contains(.stronglyEmphasized) == true { traits.insert(.bold) }
        if intent?.contains(.emphasized) == true || italic { traits.insert(.italic) }
        if !traits.isEmpty {
            let descriptor = font.fontDescriptor.withSymbolicTraits(font.fontDescriptor.symbolicTraits.union(traits))
            font = NSFont(descriptor: descriptor, size: base.pointSize) ?? font
        }
        return font
    }

    static func ink(_ style: PageTextParagraph.Style) -> NSColor {
        style == .quote ? NSColor(CicadaTheme.textSecondary) : NSColor(CicadaTheme.textPrimary)
    }

    static func paragraphStyle(_ paragraph: PageTextParagraph) -> NSParagraphStyle {
        let style = NSMutableParagraphStyle()
        style.lineSpacing = CicadaTheme.scaled(2)
        // TextKit adds the line spacing under a paragraph's last line too; the stack's gaps are measured without it.
        style.paragraphSpacingBefore = max(paragraph.gapBefore - style.lineSpacing, 0)
        style.lineBreakMode = .byWordWrapping
        switch paragraph.style {
        case .item(_, let indent):
            let lead = CGFloat(indent) * indentStep
            style.firstLineHeadIndent = lead
            style.headIndent = lead + markerColumn + markerGap
            style.tabStops = [NSTextTab(textAlignment: .right, location: lead + markerColumn),
                              NSTextTab(textAlignment: .left, location: lead + markerColumn + markerGap)]
        case .quote:
            style.firstLineHeadIndent = quoteInset
            style.headIndent = quoteInset
        default: break
        }
        if paragraph.gutter { style.tailIndent = -gutterWidth }
        return style
    }

    // MARK: Building

    /// `paragraphs` as one text. `context` is what the attachments' views need to be drawn (`PageAttachmentContext`).
    static func build(_ paragraphs: [PageTextParagraph], context: PageAttachmentContext) -> PageTextDocument {
        let out = NSMutableAttributedString()
        var rows: [(id: Int, range: NSRange)] = []
        var groups: [Int: [NSRange]] = [:]
        var stops: [PageStop] = []
        for (n, paragraph) in paragraphs.enumerated() {
            let start = out.length
            append(paragraph, to: out, groups: &groups, stops: &stops, groupBase: n * 10_000, context: context)
            let end = out.length
            rows.append((paragraph.id, NSRange(location: start, length: end - start)))
            let separator = n == paragraphs.count - 1 ? "" : "\n"
            out.append(NSAttributedString(string: separator, attributes: [:]))
            out.addAttribute(.paragraphStyle, value: paragraphStyle(paragraph),
                             range: NSRange(location: start, length: out.length - start))
            if paragraph.style == .quote {
                out.addAttribute(quoteKey, value: true, range: NSRange(location: start, length: out.length - start))
            }
        }
        return PageTextDocument(text: out, stops: stops, rows: rows, groups: groups)
    }

    private static func append(_ paragraph: PageTextParagraph, to out: NSMutableAttributedString,
                               groups: inout [Int: [NSRange]], stops: inout [PageStop], groupBase: Int,
                               context: PageAttachmentContext) {
        let base = baseFont(paragraph.style)
        let color = ink(paragraph.style)
        let italic = paragraph.style == .quote
        let isHeading: Bool = { if case .heading = paragraph.style { return true } else { return false } }()

        func plainAttrs(_ font: NSFont, _ plain: String? = nil) -> [NSAttributedString.Key: Any] {
            var attrs: [NSAttributedString.Key: Any] = [.font: font, .foregroundColor: color]
            if let plain { attrs[plainKey] = plain }
            return attrs
        }

        if case .item(let marker, _) = paragraph.style {
            let tertiary = NSColor(CicadaTheme.textTertiary)
            let said = marker == "•" ? "- " : marker + " "
            out.append(NSAttributedString(string: "\t", attributes: plainAttrs(base, "")))
            out.append(NSAttributedString(string: marker, attributes: [.font: base, .foregroundColor: tertiary, plainKey: said]))
            out.append(NSAttributedString(string: "\t", attributes: plainAttrs(base, "")))
        }

        /// A quiet link's words: the page's name or the words as written, in the line's ink, carrying the link.
        func quiet(_ text: String, intent: InlinePresentationIntent?, url: URL, group: Int, mark: ProseMark.Kind? = nil) {
            var attrs = plainAttrs(font(base, intent: intent, italic: italic))
            if let mark { attrs.merge(ProseMark.attributes(mark)) { $1 } }
            attrs[.link] = url
            attrs[groupKey] = group
            let at = out.length
            out.append(NSAttributedString(string: text, attributes: attrs))
            let range = NSRange(location: at, length: (text as NSString).length)
            groups[group, default: []].append(range)
            if let last = stops.last, last.kind == .quiet, last.id == group {
                stops[stops.count - 1] = PageStop(kind: .quiet, id: group, range: NSUnionRange(last.range, range), url: url)
            } else {
                stops.append(PageStop(kind: .quiet, id: group, range: range, url: url))
            }
        }

        /// The edit mark a piece's words carry, when they carry one (the first run decides: a word is marked whole).
        func mark(of piece: PageInlinePiece?) -> ProseMark.Kind? {
            switch piece?.token {
            case .word(let words)?: return words.runs.first?[ProseMark.self]
            case .quiet(let word)?: return word.text.runs.first?[ProseMark.self]
            default: return nil
            }
        }

        var previous: PageInlinePiece?
        for piece in paragraph.pieces {
            let isObject: Bool = {
                switch piece.token {
                case .entity, .external, .cluster: return !isHeading
                default: return false
                }
            }()
            let previousObject: Bool = {
                guard let previous else { return false }
                switch previous.token {
                case .entity, .external, .cluster: return !isHeading
                default: return false
                }
            }()
            if previous != nil {
                if !piece.glued {
                    // One space between words that had one; a quiet link's own words share its link.
                    if case .quiet(let word) = piece.token, case .quiet(let before)? = previous?.token, word.group == before.group {
                        quiet(" ", intent: nil, url: word.url, group: groupBase + word.group, mark: mark(of: piece))
                    } else {
                        // A wash runs unbroken across the spaces between two words of one added (or removed) stretch.
                        var attrs = plainAttrs(base)
                        if let kind = mark(of: piece), kind == mark(of: previous) { attrs.merge(ProseMark.attributes(kind)) { $1 } }
                        out.append(NSAttributedString(string: " ", attributes: attrs))
                    }
                } else if isObject || previousObject {
                    out.append(NSAttributedString(string: joiner, attributes: plainAttrs(base, "")))
                }
            }
            switch piece.token {
            case .word(let words):
                for run in words.runs {
                    let text = String(words[run.range].characters)
                    var attrs = plainAttrs(font(base, intent: run.inlinePresentationIntent, italic: italic))
                    if let kind = run[ProseMark.self] { attrs.merge(ProseMark.attributes(kind)) { $1 } }
                    out.append(NSAttributedString(string: text, attributes: attrs))
                }
            case .quiet(let word):
                for run in word.text.runs {
                    quiet(String(word.text[run.range].characters), intent: run.inlinePresentationIntent, url: word.url,
                          group: groupBase + word.group, mark: run[ProseMark.self])
                }
            case .entity(let target, let url):
                if isHeading {
                    quiet(target.name, intent: nil, url: url, group: -1 - out.length)
                } else {
                    attach(.chip(.page(target), url), to: out, stops: &stops, plain: target.name, font: base, color: color, context: context)
                }
            case .external(let url, let label):
                if isHeading {
                    quiet(label, intent: nil, url: url, group: -1 - out.length)
                } else {
                    attach(.chip(.web(label: label), url), to: out, stops: &stops, plain: label, font: base, color: color, context: context)
                }
            case .cluster(let model, let keys):
                attach(.cluster(model, keys), to: out, stops: &stops, plain: "", font: base, color: color, context: context)
            }
            previous = piece
        }
    }

    private static func attach(_ content: PageAttachmentContent, to out: NSMutableAttributedString,
                               stops: inout [PageStop], plain: String, font: NSFont, color: NSColor,
                               context: PageAttachmentContext) {
        let attachment = PageInlineAttachment(content: content, font: font, context: context, stop: stops.count)
        switch content {
        case .chip(_, let url):
            stops.append(PageStop(kind: .chip, id: stops.count, range: NSRange(location: out.length, length: 1), url: url))
        case .cluster:
            stops.append(PageStop(kind: .cluster, id: stops.count, range: NSRange(location: out.length, length: 1), url: nil))
        }
        let string = NSMutableAttributedString(attachment: attachment)
        string.addAttributes([.font: font, .foregroundColor: color, plainKey: plain],
                             range: NSRange(location: 0, length: string.length))
        out.append(string)
    }

    // MARK: Plain text

    /// `range` of `text` as prose: each piece that stands for something else says so (`plainKey`).
    static func plain(_ text: NSAttributedString, _ range: NSRange) -> String {
        guard range.length > 0 else { return "" }
        var out = ""
        let ns = text.string as NSString
        text.enumerateAttribute(plainKey, in: range, options: []) { value, run, _ in
            out += (value as? String) ?? ns.substring(with: run)
        }
        return out
    }
}
