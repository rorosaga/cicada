import Foundation

/// One piece of a line on an entity page, as the inline flow lays it out (owner 2026-11-23, DESIGN_RULES §9: a link is a
/// chip, a passage ends in one cluster of its sources' marks). A `Text` cannot hold a view, so a line that carries a chip
/// or a cluster is cut into these — its words, each link, its sources — and laid out by `InlineFlowLayout`, which wraps
/// them like a paragraph, on one baseline. A line with neither is never cut: it stays one selectable `Text`.
enum PageInlineToken: Equatable {
    /// A run of the line's own words with its markdown styling (bold, italic, code, a link the page could not resolve).
    case word(AttributedString)
    /// A link to another page of the bank, resolved to exactly one: the chip wears the page's own name and picture.
    case entity(PageLinkTarget, url: URL)
    /// A link to the web: the chip wears the link's own words and, where the app already has one for the site, its mark.
    case external(url: URL, label: String)
    /// The passage's sources: one cluster of marks, glued to the last word.
    case cluster(SourceClusterModel, keys: [CiteKey])
}

/// A token and whether it follows the one before it with no space — a full stop after a chip, the second half of a
/// word the markdown split in two runs. A glued token never starts a line.
struct PageInlinePiece: Equatable, Identifiable {
    let id: Int
    let token: PageInlineToken
    let glued: Bool
}

enum PageInline {
    /// The plain `[text](cicada://entity/<ref>)` link a wikilink became (`MarkdownBody.linkifyWikilinks`): its ref.
    static func entityRef(_ url: URL) -> String? {
        guard url.scheme == "cicada", url.host == "entity" else { return nil }
        return MarkdownBody.wikilinkRef(from: url)
    }

    /// The chip's destination for a page: always its id, so a chip reached through an alias opens exactly the page it
    /// names and never asks which (the id answers first, `MarkdownBody.entityIDs`).
    static func pageURL(_ id: String) -> URL? { URL(string: MarkdownBody.entityLink(for: id)) }

    /// A line's pieces. `text` is one row's inline markdown as `WikiInline.attributed` made it; `resolve` answers a
    /// wikilink's ref with the one page it means (`PageLinkIndex.resolve`); `cluster` is the passage's sources,
    /// appended after the last word. Whitespace is dropped and rebuilt by the layout (one space between words that had
    /// one, none between pieces that touched).
    static func pieces(of text: AttributedString, resolve: (String) -> PageLinkTarget?,
                       cluster: (SourceClusterModel, [CiteKey])? = nil) -> [PageInlinePiece] {
        var out: [PageInlinePiece] = []
        var spaced = true   // the start of a line has nothing to be glued to

        func add(_ token: PageInlineToken) {
            out.append(PageInlinePiece(id: out.count, token: token, glued: !spaced))
            spaced = false
        }

        func plain(_ range: Range<AttributedString.Index>) {
            let slice = text[range]
            var start: AttributedString.Index?
            for index in slice.characters.indices {
                if slice.characters[index].isWhitespace {
                    if let from = start { add(.word(AttributedString(text[from..<index]))) }
                    start = nil
                    spaced = true
                } else if start == nil {
                    start = index
                }
            }
            if let from = start { add(.word(AttributedString(text[from..<range.upperBound]))) }
        }

        var runs = Array(text.runs)[...]
        while let run = runs.first {
            guard let url = run.link else {
                plain(run.range)
                runs = runs.dropFirst()
                continue
            }
            // Consecutive runs of one link are one link (bold inside a label splits it).
            var end = run.range.upperBound
            var group = [run]
            runs = runs.dropFirst()
            while let next = runs.first, next.link == url {
                group.append(next)
                end = next.range.upperBound
                runs = runs.dropFirst()
            }
            let range = run.range.lowerBound..<end
            if let ref = entityRef(url) {
                if let target = resolve(ref), let page = pageURL(target.id) {
                    add(.entity(target, url: page))
                } else {
                    plain(range)   // unresolved or ambiguous: the written words, and the click's own choice (G227)
                }
            } else if let scheme = url.scheme?.lowercased(), scheme == "http" || scheme == "https" {
                // A mention's site run ("example.com ") leads its title in the old grammar; the chip wears the mark.
                let words = group.filter { $0[WikiInline.SitePart.self] == nil }
                    .map { String(text[$0.range].characters) }.joined()
                    .trimmingCharacters(in: .whitespacesAndNewlines)
                add(.external(url: url, label: words.isEmpty ? LinkGrammar.display(url.absoluteString) : words))
            } else {
                plain(range)
            }
        }
        if let cluster, !cluster.0.isEmpty {
            spaced = false
            add(.cluster(cluster.0, keys: cluster.1))
        }
        return out
    }

    /// Whether a line needs the flow at all: it holds a chip or a cluster. Otherwise it stays one `Text`.
    static func needsFlow(_ pieces: [PageInlinePiece]) -> Bool {
        pieces.contains {
            switch $0.token {
            case .word: false
            case .entity, .external, .cluster: true
            }
        }
    }

    /// The line as plain words, for VoiceOver and Copy: a chip reads as its label.
    static func plainText(_ pieces: [PageInlinePiece]) -> String {
        var out = ""
        for piece in pieces {
            let words: String
            switch piece.token {
            case .word(let attr): words = String(attr.characters)
            case .entity(let target, _): words = target.name
            case .external(_, let label): words = label
            case .cluster: continue
            }
            out += (piece.glued || out.isEmpty ? "" : " ") + words
        }
        return out
    }
}
