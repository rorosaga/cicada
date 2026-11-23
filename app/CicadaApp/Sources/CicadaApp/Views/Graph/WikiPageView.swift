import AppKit
import SwiftUI

/// The entity card's article: the page's prose as rows (`WikiArticle`), drawn lazily — only the rows on screen are laid
/// out — from `WikiArticleCache`, so a reopen or a re-render never parses again. Until the whole article is read (off
/// the main actor) the first screen is drawn, never a blank. On an entity page (ruling 48 (16), DR-80) each cited line
/// ends with its sources' markers and keeps them in its gutter for the keys (`PageCitations`).
struct WikiPageView: View {
    let key: WikiArticleCache.Key
    /// The page the article is (owner rulings 2026-10-14): its link facts draw the link cards and its edit route
    /// takes the person's view switch. Nil: links draw from their own words and nothing can be switched.
    var entityId: String? = nil
    /// The page's citations (`PageBlocks.citations`): a row draws the markers whose line ends inside it. Nil: none.
    var citations: PageBlocks.Citations? = nil

    @Environment(Store.self) private var store: Store?

    var body: some View {
        let article = WikiArticleCache.shared.article(key)
        let index = store?.linkIndex ?? .empty
        let related = RelatedCardModel.rows(in: article, resolve: index.resolve)
        // A list's slot rule (owner 2026-10-28): the picture column stays while some card has a picture.
        let slot = RelatedCard.slotWidth(related.values.compactMap { card in
            card.target.flatMap { target in
                store.flatMap { !EntityPictureLayout.isEmpty(target.type, picture: $0.picture(for: target.id)) }
                    == true ? target.type : nil
            }
        })
        let blocks = Self.blocks(article.rows, related: related)
        LazyVStack(alignment: .leading, spacing: 0) {
            // Identified by the first row's scroll anchor, so the card can scroll a lazy block into view (`anchor`).
            ForEach(blocks, id: \.first.anchor) { block in
                Group {
                    if block.isText {
                        PageRun(rows: block.rows, entityId: entityId, citations: citations,
                                related: related, index: index)
                    } else {
                        WikiRowView(row: block.first, entityId: entityId, related: related[block.first.id],
                                    relatedSlot: slot, index: index)
                    }
                }
                .padding(.top, block.first.id == 0 ? 0 : WikiRowView.gap(above: block.first,
                                                                          after: article.rows[block.first.id - 1],
                                                                          cards: related))
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .task(id: key) { await WikiArticleCache.shared.build(key) }
        .task(id: "\(entityId ?? "")|\(key.markdown.count)") {
            // A page's link facts, only when its prose links to the web (an ETag makes an unchanged page a 304).
            guard let entityId, Self.linksTheWeb(article) else { return }
            await LinkFactsCache.shared.refresh(entityId)
        }
    }

    /// A text row's markers: the sources of the line that ends inside it (a heading, a code block or a card has none).
    static func cites(_ row: WikiRow, in citations: PageBlocks.Citations?) -> [CiteKey] {
        guard let citations, !citations.markers.isEmpty else { return [] }
        switch row.kind {
        case .paragraph, .item, .quote: return CitationMarks.keys(citations.markers(endingIn: row.source))
        default: return []
        }
    }

    /// Whether any row of the article carries a web link (a card or a preview would draw from link facts).
    static func linksTheWeb(_ article: WikiArticle) -> Bool {
        article.rows.contains { row in
            if case .image = row.kind { return true }
            return !row.links.isEmpty
        }
    }
}

extension WikiPageView {
    /// A row's scroll anchor inside the card's scroll view (a string, so it never meets another section's ids).
    static func anchor(_ rowId: Int) -> String { "wiki-row-\(rowId)" }

    /// Is ``row`` the heading of the page section titled ``title``? (`## Related` is promoted a level like every
    /// record heading; the level does not matter here.)
    static func isSection(_ row: WikiRow, _ title: String) -> Bool {
        if case .heading = row.kind {
            return String(row.text.characters).trimmingCharacters(in: .whitespaces)
                .caseInsensitiveCompare(title) == .orderedSame
        }
        return false
    }
}

extension WikiRow {
    var anchor: String { WikiPageView.anchor(id) }
}

/// One row of the article that is not a run of prose — a code block, a rule, an embed, an image, a link drawn as a block,
/// a Related card — or, drawn alone (a preview, a test), one row of text as a run of one.
struct WikiRowView: View {
    let row: WikiRow
    var entityId: String? = nil
    /// DR-80 (amended 2026-11-23) — a lone text row's sources as one cluster of marks, glued to its last word.
    var cluster: (SourceClusterModel, [CiteKey])? = nil
    /// A Related list item drawn as a card (owner 2026-11-23): the page it names, and what is said of the link.
    var related: RelatedCardModel? = nil
    /// The Related list's picture column, in units: 0 when no card draws a picture, else wide enough for the widest
    /// (a media page's 3:2 thumbnail), so every card's name starts at one edge.
    var relatedSlot: CGFloat = 0
    /// Which page a wikilink means, for the chip it becomes.
    var index: PageLinkIndex = .empty

    /// `MarkdownBody`'s rhythm: blocks `spacingSM` apart, a list's items 4 apart, a heading given room above.
    static func gap(above row: WikiRow, after previous: WikiRow, cards: [Int: RelatedCardModel] = [:]) -> CGFloat {
        switch (row.kind, previous.kind) {
        case (.item, .item): return cards[row.id] != nil && cards[previous.id] != nil ? CicadaTheme.scaled(6) : 4
        case (.heading(let level), _): return CicadaTheme.spacingSM + (level <= 2 ? CicadaTheme.spacingSM : CicadaTheme.spacingXS)
        default: return CicadaTheme.spacingSM
        }
    }

    var body: some View {
        content
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
    }

    @ViewBuilder
    private var content: some View {
        switch row.kind {
        case .heading, .paragraph, .quote:
            PageRun(rows: [row], entityId: entityId, citations: nil, related: [:], index: index,
                    lone: cluster)
        case .item(_, let indent):
            if let related {
                RelatedCard(model: related, slot: relatedSlot)
                    .padding(.leading, CGFloat(indent) * 14)
            } else {
                PageRun(rows: [row], entityId: entityId, citations: nil, related: [:], index: index,
                        lone: cluster)
            }
        case .code:
            ScrollView(.horizontal, showsIndicators: false) {
                Text(row.text)
                    .font(CicadaTheme.monoFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .textSelection(.enabled)
                    .padding(CicadaTheme.spacingSM)
            }
            .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).fill(CicadaTheme.bgFocus))
            .ringed(.resting, in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
        case .rule:
            Rectangle().fill(CicadaTheme.ring(.resting)).frame(height: 1).padding(.vertical, 2)
                .accessibilityHidden(true)
        case .embed(let ref):
            TranscludingMarkdownView(body: "![[\(ref)]]")
        case .image(let url, let alt):
            ProseImage(url: url, alt: alt, entityId: entityId)
        case .link(let ref, let note):
            LinkBlockView(ref: ref, note: note, entityId: entityId)
        }
    }
}

/// A stretch of the article the text engine draws as one text: consecutive paragraphs, headings, list items and quotes
/// (never a Related card, a code block, a rule, an image, an embed or a link drawn as a block), so a drag selects across
/// all of them. `PageBlock.maxRows` bounds one text: it is laid out whole when it is drawn, and a long list is many.
struct PageBlock {
    let rows: [WikiRow]
    let isText: Bool
    var first: WikiRow { rows[0] }

    /// The most rows in one text; also capped by `maxCharacters`, so a page of long paragraphs is not one huge layout.
    static let maxRows = 40
    static let maxCharacters = 24_000

    static func isText(_ row: WikiRow, related: [Int: RelatedCardModel]) -> Bool {
        switch row.kind {
        case .heading, .paragraph, .quote: true
        case .item: related[row.id] == nil
        default: false
        }
    }

    static func blocks(_ rows: [WikiRow], related: [Int: RelatedCardModel]) -> [PageBlock] {
        var out: [PageBlock] = []
        var run: [WikiRow] = []
        var characters = 0
        func flush() {
            if !run.isEmpty { out.append(PageBlock(rows: run, isText: true)) }
            run = []
            characters = 0
        }
        for row in rows {
            guard isText(row, related: related) else {
                flush()
                out.append(PageBlock(rows: [row], isText: false))
                continue
            }
            let size = row.text.characters.count
            if run.count >= maxRows || characters + size > maxCharacters { flush() }
            run.append(row)
            characters += size
        }
        flush()
        return out
    }
}

extension WikiPageView {
    static func blocks(_ rows: [WikiRow], related: [Int: RelatedCardModel]) -> [PageBlock] {
        PageBlock.blocks(rows, related: related)
    }
}

/// A mention's mark inside a line of text (owner 2026-10-26, research-hub's mention): the site's own icon at 15 pt with
/// the tab-icon corner (`SiteIconLayout.cornerRadius`, scaled to the side), sitting on the baseline like a glyph; a site
/// whose icon Cicada does not serve shows the tertiary globe — a `Text` cannot hold the ring monogram, and the globe
/// says "a website" without guessing a mark (G146).
enum MentionIcon {
    static let side: CGFloat = 15

    static func rounded(_ image: NSImage) -> NSImage {
        let side = CicadaTheme.scaled(Self.side)
        let radius = CicadaTheme.scaled(SiteIconLayout.cornerRadius) * Self.side / SiteIconLayout.Size.inline.points
        return NSImage(size: NSSize(width: side, height: side), flipped: false) { rect in
            NSBezierPath(roundedRect: rect, xRadius: radius, yRadius: radius).addClip()
            image.draw(in: rect)
            return true
        }
    }

    static func text(_ image: NSImage?) -> Text {
        if let image {
            return Text(Image(nsImage: image)).baselineOffset(-CicadaTheme.scaled(2.5))
        }
        return Text(Image(systemName: "globe"))
            .font(CicadaTheme.font(size: 11))
            .foregroundStyle(CicadaTheme.textTertiary)
    }
}
