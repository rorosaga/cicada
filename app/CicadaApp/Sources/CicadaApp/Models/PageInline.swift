import Foundation

/// One piece of a line on an entity page (owner 2026-11-23, DESIGN_RULES §9: a link is a chip, a passage ends in one
/// cluster of its sources' marks): its words, each link, its sources. `PageText` lays the pieces of a run of rows out as
/// one text, a chip and the cluster as attachments, so the run selects like any Mac text.
enum PageInlineToken: Equatable {
    /// A run of the line's own words with its markdown styling (bold, italic, code, a link the page could not resolve).
    case word(AttributedString)
    /// A link to another page of the bank, resolved to exactly one: the chip wears the page's own name and picture.
    case entity(PageLinkTarget, url: URL)
    /// A link to the web: the chip wears the link's own words and, where the app already has one for the site, its mark.
    case external(url: URL, label: String)
    /// A link drawn as a quiet link: its words in body ink with no picture and no fill (a hover fill and the same click).
    /// One token per word, so a name wraps like plain text; the words of one link share a `group` (they light together).
    /// A later mention of a page in the same passage, and every ref that resolved to no single page, is this.
    case quiet(PageQuietWord)
    /// The passage's sources: one cluster of marks, glued to the last word.
    case cluster(SourceClusterModel, keys: [CiteKey])
}

/// One word of a quiet link (`PageInlineToken.quiet`).
struct PageQuietWord: Equatable {
    let text: AttributedString
    /// Where the click goes: the page's id link, or the ref as written (the click then asks which page, G227).
    let url: URL
    let group: Int
    /// The link's first word carries its accessibility label and focus; the rest are the same control.
    let first: Bool
    /// The whole link's words, for VoiceOver.
    let label: String
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
    ///
    /// **One chip per page per passage (owner 2026-11-23):** the first mention of a page in `text` is the chip with its
    /// picture; later mentions of the same page are quiet links, as an encyclopedia links a name once. `text` is one
    /// passage (a paragraph, a bullet), so each is counted afresh. A ref that resolved to no single page is a quiet link
    /// too, in its written words, so no link on the page is blue and underlined.
    static func pieces(of text: AttributedString, resolve: (String) -> PageLinkTarget?,
                       cluster: (SourceClusterModel, [CiteKey])? = nil) -> [PageInlinePiece] {
        var out: [PageInlinePiece] = []
        var spaced = true   // the start of a line has nothing to be glued to
        var chipped = Set<String>()
        var groups = 0

        func add(_ token: PageInlineToken) {
            out.append(PageInlinePiece(id: out.count, token: token, glued: !spaced))
            spaced = false
        }

        /// A run's words, split at whitespace; `emit` makes each a token.
        func words(_ range: Range<AttributedString.Index>, _ emit: (AttributedString) -> Void) {
            let slice = text[range]
            var start: AttributedString.Index?
            for index in slice.characters.indices {
                if slice.characters[index].isWhitespace {
                    if let from = start { emit(AttributedString(text[from..<index])) }
                    start = nil
                    spaced = true
                } else if start == nil {
                    start = index
                }
            }
            if let from = start { emit(AttributedString(text[from..<range.upperBound])) }
        }

        func plain(_ range: Range<AttributedString.Index>) { words(range) { add(.word($0)) } }

        /// A quiet link over `range`'s own words, or over `name`'s when a page's name is shown instead.
        func quiet(_ range: Range<AttributedString.Index>, url: URL, name: String? = nil) {
            let group = groups
            groups += 1
            let label = name ?? String(text[range].characters).trimmingCharacters(in: .whitespacesAndNewlines)
            var first = true
            func emit(_ word: AttributedString) {
                var word = word
                word.link = nil
                word.underlineStyle = nil
                word.foregroundColor = nil
                add(.quiet(PageQuietWord(text: word, url: url, group: group, first: first, label: label)))
                first = false
            }
            if let name {
                for (i, word) in name.split(whereSeparator: \.isWhitespace).enumerated() {
                    if i > 0 { spaced = true }
                    emit(AttributedString(String(word)))
                }
            } else {
                words(range, emit)
            }
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
                    if chipped.insert(target.id).inserted {
                        add(.entity(target, url: page))
                    } else {
                        quiet(range, url: page, name: target.name)
                    }
                } else {
                    quiet(range, url: url)   // unresolved or ambiguous: the written words, and the click's own choice (G227)
                }
            } else if let scheme = url.scheme?.lowercased(), scheme == "http" || scheme == "https" {
                // A mention's site run ("example.com ") leads its title in the old grammar; the chip wears the mark.
                let label = group.filter { $0[WikiInline.SitePart.self] == nil }
                    .map { String(text[$0.range].characters) }.joined()
                    .trimmingCharacters(in: .whitespacesAndNewlines)
                add(.external(url: url, label: label.isEmpty ? LinkGrammar.display(url.absoluteString) : label))
            } else {
                quiet(range, url: url)
            }
        }
        if let cluster, !cluster.0.isEmpty {
            spaced = false
            add(.cluster(cluster.0, keys: cluster.1))
        }
        return out
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
            case .quiet(let word): words = String(word.text.characters)
            case .cluster: continue
            }
            out += (piece.glued || out.isEmpty ? "" : " ") + words
        }
        return out
    }
}
