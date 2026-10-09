import SwiftUI

/// The entity card's article: the page's prose as rows (`WikiArticle`), drawn lazily — only the rows on screen are laid
/// out — from `WikiArticleCache`, so a reopen or a re-render never parses again. Until the whole article is read (off
/// the main actor) the first screen is drawn, never a blank. Every line offers "Where this came from" on hover and as
/// an accessibility action (one click from any line, owner 2026-10-09).
struct WikiPageView: View {
    let key: WikiArticleCache.Key
    /// Opens a line's provenance in the Reader (`LineProvenance`); nil hides the affordance.
    var onLineSource: ((WikiRow) -> Void)? = nil

    var body: some View {
        let article = WikiArticleCache.shared.article(key)
        LazyVStack(alignment: .leading, spacing: 0) {
            ForEach(article.rows) { row in
                WikiRowView(row: row, onSource: onLineSource)
                    .padding(.top, row.id == 0 ? 0 : WikiRowView.gap(above: row, after: article.rows[row.id - 1]))
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .task(id: key) { await WikiArticleCache.shared.build(key) }
    }
}

struct WikiRowView: View {
    let row: WikiRow
    let onSource: ((WikiRow) -> Void)?
    @State private var hovering = false

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
        case .rule, .embed, .image: false
        default: onSource != nil
        }
    }

    var body: some View {
        content
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.trailing, hasSource ? CicadaTheme.scaled(28) : 0)
            .overlay(alignment: .topTrailing) {
                if hasSource, hovering, let onSource {
                    IconButton(systemName: "text.quote", help: Copy.Graph.lineSource) { onSource(row) }
                        .offset(y: -CicadaTheme.scaled(5))
                }
            }
            .onHover { hovering = $0 }
    }

    private var lineSource: LineSourceAction { LineSourceAction(enabled: hasSource) { onSource?(row) } }

    @ViewBuilder
    private var content: some View {
        switch row.kind {
        case .heading(let level):
            Text(row.text)
                .font(Self.headingFont(level))
                .foregroundStyle(CicadaTheme.textPrimary)
                .textSelection(.enabled)
                .accessibilityAddTraits(.isHeader)
                .modifier(lineSource)
        case .paragraph:
            Text(row.text)
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
                Text(row.text)
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
                Text(row.text)
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
            TranscludingMarkdownView(body: "![\(alt)](\(url))")
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
