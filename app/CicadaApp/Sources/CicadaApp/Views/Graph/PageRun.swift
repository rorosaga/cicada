import AppKit
import SwiftUI

// MARK: - A run of the article (owner 2026-11-23, DESIGN_RULES §9)

/// A stretch of consecutive text rows drawn as one selectable text (`PageTextRunView`), with what a row used to carry
/// beside its words: the 🔗 button of a line that links to the web (hover, keyboard focus, or its popover open), and the
/// line a view switch says ("Saving…", "Saved · shown as a bookmark"). A right-click on a line with web links offers the
/// same view choices as the button.
struct PageRun: View {
    let rows: [WikiRow]
    let entityId: String?
    let citations: PageBlocks.Citations?
    /// Which list items are Related cards (they set the gap above an item).
    let related: [Int: RelatedCardModel]
    let index: PageLinkIndex
    /// A row drawn alone, with its own cluster (`WikiRowView`).
    var lone: (SourceClusterModel, [CiteKey])? = nil

    @Environment(GraphViewModel.self) private var graphVM: GraphViewModel?
    @State private var frames: [Int: CGRect] = [:]
    @State private var hovered: Int?
    @State private var buttonHovered: Int?
    @State private var popover: Int?
    @State private var status: String?
    @FocusState private var focused: Int?

    var body: some View {
        // Reading the tokens here makes the run follow the theme and the type scale.
        let look = "\(CicadaTheme.mode)|\(CicadaTheme.uiScale)"
        let paragraphs = Self.paragraphs(rows, entityId: entityId, citations: citations, lone: lone, related: related,
                                         index: index)
        let linked = paragraphs.filter(\.gutter).map(\.id)
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            PageTextRunView(paragraphs: paragraphs, look: look, entityId: entityId, watched: Set(linked),
                            onRowFrames: { frames = $0 },
                            onHoverRow: { hovered = $0 },
                            onMenu: { menu(for: $0) })
                .overlay(alignment: .topTrailing) {
                    ZStack(alignment: .topTrailing) {
                        ForEach(linked, id: \.self) { id in button(id) }
                    }
                }
            if let status {
                Text(status)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    // MARK: Paragraphs

    /// The rows as paragraphs: each row's words and links cut into pieces, a cited passage ending in its cluster.
    static func paragraphs(_ rows: [WikiRow], entityId: String?, citations: PageBlocks.Citations?,
                           lone: (SourceClusterModel, [CiteKey])?, related: [Int: RelatedCardModel],
                           index: PageLinkIndex) -> [PageTextParagraph] {
        var out: [PageTextParagraph] = []
        for (n, row) in rows.enumerated() {
            let style: PageTextParagraph.Style
            switch row.kind {
            case .heading(let level): style = .heading(level: level)
            case .item(let marker, let indent): style = .item(marker: marker, indent: indent)
            case .quote: style = .quote
            default: style = .body
            }
            var cluster = lone
            if entityId != nil, cluster == nil {
                cluster = CitationMarks.cluster(WikiPageView.cites(row, in: citations), in: citations)
            }
            if entityId == nil { cluster = nil }
            let pieces = PageInline.pieces(of: row.text, resolve: index.resolve, cluster: cluster)
            let gap = n == 0 ? 0 : WikiRowView.gap(above: row, after: rows[n - 1], cards: related)
            out.append(PageTextParagraph(id: row.id, style: style, pieces: pieces, gapBefore: gap,
                                         gutter: !row.links.isEmpty))
        }
        return out
    }

    // MARK: The 🔗 button

    @ViewBuilder
    private func button(_ id: Int) -> some View {
        if let row = rows.first(where: { $0.id == id }) {
            let shown = hovered == id || buttonHovered == id || popover == id || focused == id
            IconButton(systemName: "link", help: Copy.Links.linksOnLine) { popover = id }
                .focused($focused, equals: id)
                .onHover { buttonHovered = $0 ? id : (buttonHovered == id ? nil : buttonHovered) }
                .opacity(shown ? 1 : 0)
                .popover(isPresented: Binding(get: { popover == id }, set: { if !$0, popover == id { popover = nil } }),
                         arrowEdge: .trailing) {
                    LinkLinePopover(refs: row.links, entityId: entityId)
                }
                .offset(y: (frames[id]?.minY ?? 0) - CicadaTheme.scaled(5))
        }
    }

    // MARK: A right-click on a line with links

    private func menu(for id: Int) -> NSMenu? {
        guard let entityId, let row = rows.first(where: { $0.id == id }) else { return nil }
        let switchable = row.links.filter { $0.markdown.hasPrefix("[") }
        guard !switchable.isEmpty else { return nil }
        let menu = NSMenu()
        let graph = graphVM
        for ref in switchable {
            if switchable.count > 1 {
                let title = NSMenuItem(title: ref.shownLabel, action: nil, keyEquivalent: "")
                title.isEnabled = false
                menu.addItem(title)
            }
            let current = LinkCardModel.current(ref)
            let fact = LinkFactsCache.shared.fact(ref.url, on: entityId)
            for view in LinkCardModel.offered(ref, fact: fact) {
                menu.addItem(PageMenuItem(title: Copy.Links.menuName(view, url: ref.url), checked: view == current) {
                    guard view != current else { return }
                    status = Copy.Links.saving
                    Task {
                        status = await LinkViewChange.apply(ref, view, entityId: entityId) {
                            await graph?.reloadEntity(id: entityId)
                        }
                    }
                })
            }
            menu.addItem(.separator())
            menu.addItem(PageMenuItem(title: Copy.Links.openInBrowser) { LinkOpen.browserOpen(ref.url) })
            menu.addItem(PageMenuItem(title: Copy.Links.copyLink) { AppPasteboard.copy(ref.url) })
        }
        return menu
    }
}

/// A menu item that runs a closure.
final class PageMenuItem: NSMenuItem {
    private let handler: () -> Void

    init(title: String, checked: Bool = false, handler: @escaping () -> Void) {
        self.handler = handler
        super.init(title: title, action: #selector(fire), keyEquivalent: "")
        target = self
        state = checked ? .on : .off
    }

    required init(coder: NSCoder) { fatalError("PageMenuItem is never decoded") }

    @objc private func fire() { handler() }
}
