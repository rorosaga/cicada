import SwiftUI

/// Owner 2026-11-25 (G246, ruling 81a) — Media's lists of saved things in Clusters: what is open, and the three things a
/// list line can ask the page for. The page owns the state (per viewer, never stored); the views only draw it.
struct ClusterListActions {
    /// The lists opened, and the ones whose "Show all N" was pressed.
    var open: Set<String> = []
    var full: Set<String> = []
    var toggle: (String) -> Void = { _ in }
    var showAll: (String) -> Void = { _ in }
    /// The list's own page as the card, when it has one the graph holds.
    var openPage: (String) -> Void = { _ in }

    static let none = ClusterListActions()
}

/// One list of saved things as one collapsed line (DR-34 one height, DR-48 hover fill, DR-52 the source's own mark): a
/// chevron, the mark, the list's name and "N videos". The whole line opens or closes it; the list's own page, when it
/// has one, opens from the arrow at the trailing edge. A keyboard toggle never animates — the chevron is swapped, not
/// turned (DR-60).
struct ClusterListLine: View {
    let list: ClustersModel.ListFold
    let isOpen: Bool
    let toggle: () -> Void
    /// nil when the list has no page of its own.
    let openPage: (() -> Void)?

    @State private var hovering = false

    private var mark: String? {
        guard let m = list.bubble.mark, !m.isEmpty, m != "unknown" else { return nil }
        return m
    }

    var body: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            Button(action: toggle) {
                HStack(spacing: CicadaTheme.spacingSM) {
                    DisclosureChevron(isOpen: isOpen)
                        .frame(width: CicadaTheme.scaled(12))
                    if let mark { OriginMark(origin: mark, size: CicadaTheme.scaled(18)) }
                    Text(list.name)
                        .font(CicadaTheme.rowFont)
                        .foregroundStyle(CicadaTheme.textPrimary)
                        .lineLimit(1)
                    Text(Copy.Lists.listCount(list.count, noun: list.bubble.kindNoun))
                        .font(CicadaTheme.metaFont)
                        .monospacedDigit()
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .lineLimit(1)
                    Spacer(minLength: 0)
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.cicadaPlain)
            .accessibilityLabel(Copy.Lists.listLine(name: list.name, count: list.count, noun: list.bubble.kindNoun,
                                                    open: isOpen))
            .accessibilityAddTraits(.isButton)
            if let openPage {
                IconButton(systemName: "arrow.up.right", help: Copy.Lists.openSavedListPage, action: openPage)
            }
        }
        .padding(.horizontal, CicadaTheme.scaled(8))
        .frame(maxWidth: .infinity, minHeight: CicadaTheme.scaled(RowMetrics.titleOnly),
               maxHeight: CicadaTheme.scaled(RowMetrics.titleOnly), alignment: .leading)
        .rowHover($hovering)
        .contentShape(Rectangle())
    }
}

/// The lists of a grid card or section, each line with its members under it when opened: lazy, the first
/// `ClustersModel.memberCap` and then "Show all N". `member` draws one page the way the surrounding section does.
struct ClusterListBlocks<Member: View>: View {
    let lists: [ClustersModel.ListFold]
    let actions: ClusterListActions
    let columns: Int
    @ViewBuilder let member: (Entity) -> Member

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ForEach(lists) { list in
                ClusterListLine(list: list, isOpen: actions.open.contains(list.id),
                                toggle: { Instant.run { actions.toggle(list.id) } },
                                openPage: list.pageId.map { id in { actions.openPage(id) } })
                    .id("list:" + list.id)
                if actions.open.contains(list.id) {
                    let all = actions.full.contains(list.id)
                    let shown = all ? list.members : Array(list.members.prefix(ClustersModel.memberCap))
                    LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: CicadaTheme.spacingSM,
                                                                 alignment: .topLeading), count: max(columns, 1)),
                              alignment: .leading, spacing: CicadaTheme.scaled(4)) {
                        ForEach(shown) { entity in member(entity).id(entity.id) }
                    }
                    .padding(.leading, CicadaTheme.scaled(20))
                    if shown.count < list.members.count {
                        TextButton(title: Copy.Lists.showAll(list.members.count)) { actions.showAll(list.id) }
                            .padding(.leading, CicadaTheme.scaled(28))
                            .padding(.vertical, CicadaTheme.spacingXS)
                    }
                }
            }
        }
    }
}
