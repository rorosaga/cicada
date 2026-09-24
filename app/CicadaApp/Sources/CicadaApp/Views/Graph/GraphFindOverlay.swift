import SwiftUI

/// ⌘F on the Graph (R-DG5, DR-46): find a node on the canvas, as an overlay at the canvas's top-leading corner
/// that never pushes it. It replaced `GraphSearchField`, which sat on the canvas at all times; ⌘K (the command
/// bar) is where everything else is searched, and the last row hands the words to it. The ranking is the
/// palette's (`QuickMatch`, through `graphVM.searchHits`), so the two never order one name differently.
struct GraphFindOverlay: View {
    static let width: CGFloat = 300

    /// R-SU10 — the graph stays mounted under every other tab; its field answers ⌘F only while visible.
    var isActive = true
    let close: () -> Void
    @Environment(GraphViewModel.self) private var graphVM
    @Environment(AppRouter.self) private var router
    @State private var query = ""
    @State private var highlighted = 0
    @State private var hovered: String?

    private var hits: [GraphViewModel.SearchHit] { graphVM.searchHits(query, limit: GraphFind.hitLimit) }
    private var hasQuery: Bool { !SearchAllMemoryRow.trimmed(query).isEmpty }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: CicadaTheme.spacingXS) {
                CicadaSearchField(text: $query, prompt: Copy.Graph.findOnCanvas, findEnabled: isActive,
                                  onSubmit: submit, onMove: move, onEscape: escape, autofocus: true)
                IconButton(systemName: "xmark", help: Copy.Graph.closeFind, action: close)
            }
            .padding(CicadaTheme.spacingXS)
            if hasQuery { results }
        }
        .frame(width: CicadaTheme.scaled(Self.width))
        .floatingSurface(in: CicadaTheme.shape(CicadaTheme.cornerRadius))
        .onChange(of: query) { _, _ in highlighted = 0 }
    }

    private var results: some View {
        let list = hits
        return VStack(alignment: .leading, spacing: 0) {
            ForEach(Array(list.enumerated()), id: \.element.node.id) { index, hit in row(hit, index: index) }
            if list.isEmpty {
                Text(Copy.Graph.noNodeMatches)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .padding(.horizontal, CicadaTheme.spacingSM)
                    .frame(height: CicadaTheme.scaled(28), alignment: .leading)
            }
            SearchAllMemoryRow(query: query)
                .padding(.horizontal, CicadaTheme.spacingSM)
                .frame(height: CicadaTheme.scaled(32), alignment: .leading)
        }
        .padding([.horizontal, .bottom], CicadaTheme.spacingXS)
    }

    /// DR-48 — a dot or a glyph, never both: the type's dot (a data hue), the name with the matched run
    /// bold, the type in words.
    private func row(_ hit: GraphViewModel.SearchHit, index: Int) -> some View {
        let selected = index == highlighted
        return HStack(spacing: CicadaTheme.spacingSM) {
            Circle().fill(CicadaTheme.entityColor(for: hit.node.type))
                .frame(width: CicadaTheme.scaled(7), height: CicadaTheme.scaled(7))
            Text(ExcerptText.attributed(hit.node.name, bold: hit.ranges))
                .font(CicadaTheme.font(size: 13))
                .foregroundStyle(CicadaTheme.textPrimary)
                .lineLimit(1)
            Spacer(minLength: 0)
            Text(hit.node.type.label)
                .font(CicadaTheme.metaFont)
                .foregroundStyle(selected ? CicadaTheme.textTertiaryOnFill : CicadaTheme.textTertiary)
        }
        .padding(.horizontal, CicadaTheme.spacingSM)
        .frame(height: CicadaTheme.scaled(32))
        .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall)
            .fill(selected ? CicadaTheme.bgSelected : (hovered == hit.node.id ? CicadaTheme.bgHover : Color.clear)))
        .contentShape(Rectangle())
        .onHover { inside in hovered = inside ? hit.node.id : (hovered == hit.node.id ? nil : hovered) }
        .onTapGesture { pick(index) }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(hit.node.type.label), \(hit.node.name)")
        .accessibilityAddTraits(selected ? [.isButton, .isSelected] : .isButton)
    }

    /// ⏎ — the highlighted node, or with nothing matched the palette prefilled. A keyboard path (DR-60).
    private func submit() {
        guard hasQuery else { return }
        if hits.isEmpty {
            router.requestPalette(prefill: SearchAllMemoryRow.trimmed(query))
        } else {
            Instant.run { pick(highlighted) }
        }
    }

    private func move(_ delta: Int) {
        let count = hits.count
        guard count > 0 else { return }
        highlighted = (highlighted + delta + count) % count
    }

    private func escape() {
        switch GraphFind.escape(textIsEmpty: query.isEmpty) {
        case .clear: query = ""
        case .close: Instant.run { close() }
        }
    }

    /// G123 — land on the node and open its column; the overlay's job is done.
    private func pick(_ index: Int) {
        let list = hits
        guard list.indices.contains(index) else { return }
        graphVM.revealEntity(id: list[index].node.id)
        query = ""
        highlighted = 0
        close()
    }
}
