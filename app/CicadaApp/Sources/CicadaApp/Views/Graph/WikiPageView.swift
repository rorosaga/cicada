import AppKit
import SwiftUI

/// The entity card's article: the page's prose as rows (`WikiArticle`), drawn lazily — only the rows on screen are laid
/// out — from `WikiArticleCache`, so a reopen or a re-render never parses again. Until the whole article is read (off
/// the main actor) the first screen is drawn, never a blank. Every line offers "Where this came from" on hover and as
/// an accessibility action (one click from any line, owner 2026-10-09).
struct WikiPageView: View {
    let key: WikiArticleCache.Key
    /// Opens a line's provenance in the Reader (`LineProvenance`); nil hides the affordance.
    var onLineSource: ((WikiRow) -> Void)? = nil
    /// The page the article is (owner rulings 2026-10-14): its link facts draw the link cards and its edit route
    /// takes the person's view switch. Nil: links draw from their own words and nothing can be switched.
    var entityId: String? = nil

    var body: some View {
        let article = WikiArticleCache.shared.article(key)
        LazyVStack(alignment: .leading, spacing: 0) {
            // Identified by its scroll anchor, so the card can scroll a lazy row into view (`anchor`).
            ForEach(article.rows, id: \.anchor) { row in
                WikiRowView(row: row, onSource: onLineSource, entityId: entityId)
                    .padding(.top, row.id == 0 ? 0 : WikiRowView.gap(above: row, after: article.rows[row.id - 1]))
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

struct WikiRowView: View {
    let row: WikiRow
    let onSource: ((WikiRow) -> Void)?
    var entityId: String? = nil
    @Environment(Store.self) private var store: Store?
    @State private var hovering = false
    @State private var showLinks = false
    @FocusState private var linksFocused: Bool
    /// The site icons of the row's mentions, by link URL (`MentionIcon`), loaded once the page's link facts say the
    /// icon route serves them.
    @State private var icons: [String: NSImage] = [:]
    /// What the last view change from this line's right-click menu said ("Saving…", "Saved · shown as a bookmark").
    @State private var status: String?

    /// `MarkdownBody`'s rhythm: blocks `spacingSM` apart, a list's items 4 apart, a heading given room above.
    static func gap(above row: WikiRow, after previous: WikiRow) -> CGFloat {
        switch (row.kind, previous.kind) {
        case (.item, .item): return 4
        case (.heading(let level), _): return CicadaTheme.spacingSM + (level <= 2 ? CicadaTheme.spacingSM : CicadaTheme.spacingXS)
        default: return CicadaTheme.spacingSM
        }
    }

    private var hasSource: Bool {
        switch row.kind {
        case .rule, .embed, .image, .link: false
        default: onSource != nil
        }
    }

    /// The line's web links have a 🔗 in the gutter: their previews and, on the page's own card, each link's view menu.
    /// It shows on hover and while it holds keyboard focus (it stays in the focus order, owner 2026-10-26: never only
    /// on hover); a right-click on the line opens the same choices.
    private var hasLinks: Bool { !row.links.isEmpty }

    /// The links on a text line the person can switch (a block row's card carries its own menu).
    private var switchable: [LinkRef] {
        guard entityId != nil else { return [] }
        if case .link = row.kind { return [] }
        return row.links.filter { $0.markdown.hasPrefix("[") }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            content
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)
            if let status {
                Text(status)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
        }
        .padding(.trailing, CicadaTheme.scaled(28) * CGFloat((hasSource ? 1 : 0) + (hasLinks ? 1 : 0)))
        .overlay(alignment: .topTrailing) {
            HStack(spacing: 0) {
                if hasLinks {
                    IconButton(systemName: "link", help: Copy.Links.linksOnLine) { showLinks = true }
                        .focused($linksFocused)
                        .opacity(hovering || showLinks || linksFocused ? 1 : 0)
                        .popover(isPresented: $showLinks, arrowEdge: .trailing) {
                            LinkLinePopover(refs: row.links, entityId: entityId)
                        }
                }
                if hasSource, hovering, let onSource {
                    IconButton(systemName: "text.quote", help: Copy.Graph.lineSource) { onSource(row) }
                }
            }
            .offset(y: -CicadaTheme.scaled(5))
        }
        .onHover { hovering = $0 }
        .modifier(LineLinksAction(enabled: hasLinks) { showLinks = true })
        .contextMenu {
            if let entityId, !switchable.isEmpty {
                ForEach(Array(switchable.enumerated()), id: \.offset) { _, ref in
                    LinkViewMenuItems(ref: ref, fact: LinkFactsCache.shared.fact(ref.url, on: entityId),
                                      entityId: entityId, status: $status, titled: switchable.count > 1)
                }
            }
        }
        .task(id: iconKey) { await loadIcons() }
    }

    private var lineSource: LineSourceAction { LineSourceAction(enabled: hasSource) { onSource?(row) } }

    // MARK: Mentions

    /// The row's mentions whose site icon the page's icon route serves (`LinkFact.icon`), as the task's key: it reruns
    /// when the link facts arrive or the bank changes.
    private var iconKey: String {
        guard let entityId, WikiInline.hasSitePart(row.text) else { return "" }
        let served = WikiInline.mentionURLs(row.text).filter { LinkFactsCache.shared.fact($0, on: entityId).icon }
        return served.isEmpty ? "" : "\(store?.bank ?? "")|\(entityId)|\(served.joined(separator: " "))"
    }

    private func loadIcons() async {
        guard !iconKey.isEmpty, let entityId, let bank = store?.bank else { return }
        for url in WikiInline.mentionURLs(row.text) where icons[url] == nil {
            let fact = LinkFactsCache.shared.fact(url, on: entityId)
            guard fact.icon, let site = fact.site ?? LinkGrammar.site(url),
                  let image = await SiteIconStore.shared.image(site: site, bank: bank, entity: entityId, saved: nil)
            else { continue }
            icons[url] = MentionIcon.rounded(image)
        }
    }

    /// The row's text in the current theme, each mention led by its site's icon (`WikiInline.composed`).
    private func text(_ font: Font) -> Text {
        guard !row.links.isEmpty, WikiInline.hasSitePart(row.text) else { return Text(row.text) }
        return WikiInline.composed(WikiInline.themed(row.text, font: font)) { url in
            MentionIcon.text(icons[url])
        }
    }

    @ViewBuilder
    private var content: some View {
        switch row.kind {
        case .heading(let level):
            text(Self.headingFont(level))
                .font(Self.headingFont(level))
                .foregroundStyle(CicadaTheme.textPrimary)
                .textSelection(.enabled)
                .accessibilityAddTraits(.isHeader)
                .modifier(lineSource)
        case .paragraph:
            text(CicadaTheme.bodyFont)
                .font(CicadaTheme.bodyFont)
                .lineSpacing(CicadaTheme.scaled(2))
                .foregroundStyle(CicadaTheme.textPrimary)
                .textSelection(.enabled)
                .modifier(lineSource)
        case .item(let marker, let indent):
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Text(marker)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .frame(minWidth: 16, alignment: .trailing)
                    .accessibilityHidden(true)
                text(CicadaTheme.bodyFont)
                    .font(CicadaTheme.bodyFont)
                    .lineSpacing(CicadaTheme.scaled(2))
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .textSelection(.enabled)
                    .modifier(lineSource)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .padding(.leading, CGFloat(indent) * 14)
        case .code:
            ScrollView(.horizontal, showsIndicators: false) {
                Text(row.text)
                    .font(CicadaTheme.monoFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .textSelection(.enabled)
                    .modifier(lineSource)
                    .padding(CicadaTheme.spacingSM)
            }
            .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).fill(CicadaTheme.bgFocus))
            .ringed(.resting, in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
        case .quote:
            HStack(alignment: .top, spacing: 0) {
                Rectangle().fill(CicadaTheme.ring(.strong)).frame(width: 3)
                text(CicadaTheme.bodyFont)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .italic()
                    .textSelection(.enabled)
                    .modifier(lineSource)
                    .padding(.leading, CicadaTheme.spacingSM)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
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

    private static func headingFont(_ level: Int) -> Font {
        switch level {
        case 1: CicadaTheme.titleFont
        case 2: CicadaTheme.headingFont
        case 3: CicadaTheme.bodyFont.weight(.semibold)
        default: CicadaTheme.captionFont.weight(.semibold)
        }
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
/// VoiceOver reaches a line's links without hovering: the same popover the 🔗 opens.
struct LineLinksAction: ViewModifier {
    let enabled: Bool
    let action: () -> Void

    func body(content: Content) -> some View {
        if enabled {
            content.accessibilityAction(named: Copy.Links.linksOnLine, action)
        } else {
            content
        }
    }
}

/// VoiceOver reaches a line's source without hovering: an action on the line's own text, which keeps its links.
struct LineSourceAction: ViewModifier {
    let enabled: Bool
    let action: () -> Void

    func body(content: Content) -> some View {
        if enabled {
            content.accessibilityAction(named: Copy.Graph.lineSource, action)
        } else {
            content
        }
    }
}
