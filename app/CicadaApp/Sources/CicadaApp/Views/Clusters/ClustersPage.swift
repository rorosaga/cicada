import SwiftUI

/// §10 Clusters in progressive columns (Direction D, DS-3c; F-11 since G146; DR-25…DR-31, DR-45, DR-46, DR-68): with
/// nothing open, mock A's icon-led cards — each type a card of pictures, names and one line in words; a click narrows
/// to a list of rows with pictures and opens the entity card beside it; a belief's evidence opens the Reader as the
/// third column. It replaced `TopicsView` — a pushed detail page, three filters and a
/// type rail that repeated its own rows (P2/P4, DR-38).
struct ClustersPage: View {
    @Environment(GraphViewModel.self) private var graphVM
    @Environment(AppRouter.self) private var router
    @Environment(ProvenanceRouter.self) private var provenance
    @AppStorage(ShellMetrics.labelledKey) private var labelledSidebar = false
    @AppStorage(ClustersModel.expandAllKey) private var expandAll = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    @State private var columns = ListColumns<String>()
    @State private var tab: EntityType?
    @State private var query = ""
    @State private var findOpen = false
    @State private var labels: Set<String> = []
    @State private var viewMenuOpen = false
    @State private var landingToken = 0
    @FocusState private var focus: ListFocus?

    private var typeFilter: Binding<Set<EntityType>> {
        Binding(get: { graphVM.filter.types }, set: { graphVM.filter.types = $0 })
    }

    /// DR-45 — a tab switch is instant; a tab that does not show the open card closes it (R-DL6).
    private var tabSelection: Binding<EntityType?> {
        Binding(get: { tab }, set: { newTab in
            Instant.run {
                tab = newTab
                query = ""
                findOpen = false
                if let open, let newTab, open.type != newTab { columns.close() }
            }
        })
    }

    private var open: Entity? {
        columns.openId.flatMap { id in graphVM.entities.first { $0.id == id } }
    }

    private var isFiltered: Bool {
        !labels.isEmpty || graphVM.filter.types.count < EntityType.selectableCases.count
    }

    var body: some View {
        let filtered = ClustersModel.filtered(graphVM.entities, types: graphVM.filter.types, labels: labels)
        let groups = ClustersModel.groups(filtered)
        let found = ClustersModel.matches(query: findOpen ? query : "", within: filtered) {
            graphVM.clusterSearchIndex().rank($0)
        }
        ProgressiveColumns(hasDetail: open != nil, hasTrailing: provenance.isPresented,
                           navWidth: ShellMetrics.navWidth(labelled: labelledSidebar)) { plan in
            EyebrowRow(eyebrow: ClustersModel.eyebrow(groups: groups, tab: tab, matches: found, openId: columns.openId),
                       horizontalPadding: open == nil && !provenance.isPresented ? plan.gutter : CicadaTheme.spacingXL) {
                HStack(spacing: CicadaTheme.spacingXS) {
                    AdaptiveTextTabs(tabs: ClustersModel.tabs(groups), selection: tabSelection,
                                     menuTitle: Copy.Lists.type)
                    PageFindButton(isOpen: $findOpen).padding(.leading, CicadaTheme.spacingSM)
                    TextButton(title: isFiltered ? Copy.Lists.viewFiltered : Copy.Lists.view,
                               help: Copy.Lists.viewHelp) { viewMenuOpen.toggle() }
                        .popover(isPresented: $viewMenuOpen, arrowEdge: .bottom) {
                            ClustersViewMenu(types: typeFilter, labels: $labels,
                                             labelCounts: ClustersModel.labelCounts(graphVM.entities),
                                             typeCounts: Dictionary(grouping: graphVM.entities, by: \.type)
                                                 .mapValues(\.count),
                                             expandAll: $expandAll)
                        }
                }
            }
        } list: { plan in
            let state = ClustersListState.of(hasEntities: !graphVM.entities.isEmpty, isLoading: graphVM.isLoading,
                                             groupsEmpty: groups.isEmpty, matches: found)
            if plan.listStyle == .wide, !findOpen, state == .list {
                // F-11 (R-PE12) — nothing open and find closed: A's icon-led cards. ⌘F shows the list column (its
                // find row and ranked rows) from the moment it opens, so typing never swaps the view under the field.
                ClustersGridView(groups: groups, tab: tab, expandAll: expandAll, gutter: plan.gutter,
                                 open: { openEntity($0) },
                                 showTab: { type in Instant.run { tabSelection.wrappedValue = type } },
                                 move: { delta in
                                     move(delta, visible: ClustersGrid.visible(groups, tab: tab, expandAll: expandAll))
                                 },
                                 escape: { escape() })
                    .focused($focus, equals: .list)
                    .tourAnchor(.clusters)
            } else {
                let lines = ClustersModel.lines(groups: groups, tab: tab, matches: found, expandAll: expandAll,
                                                cap: ClustersModel.cap(for: plan.listStyle))
                ClustersListColumn(
                    lines: lines, style: plan.listStyle, query: query, findOpen: $findOpen, findText: $query,
                    state: state,
                    openId: columns.openId, landingToken: landingToken,
                    open: { openEntity($0) },
                    showTab: { type in Instant.run { tabSelection.wrappedValue = type } },
                    move: { delta in move(delta, visible: lines.compactMap(\.entity)) },
                    focusDetail: { focus = .detail }, escape: { escape() },
                    showEverything: { labels = []; graphVM.filter.types = Set(EntityType.selectableCases) })
                    .focused($focus, equals: .list)
                    // G152 — this list replaces the cards whenever a card or find is open; without its own anchor
                    // the person stop would lose its hole in a real bank.
                    .tourAnchor(.clusters)
            }
        } detail: { plan in
            if let entity = open {
                ClustersCardColumn(entity: entity, gutter: plan.gutter,
                                   hiddenListCount: plan.listHidden ? (found?.count ?? filtered.count) : nil,
                                   onShowList: { showList() }, onClose: { closeCard() }, onEscape: { escape() })
                    .id(entity.id)
                    .focused($focus, equals: .detail)
                    .tourAnchor(.personCard)
            }
        } trailing: { _ in
            ReaderColumn().focused($focus, equals: .reader)
        }
        .background(CicadaTheme.bgBase)
        // DR-46 — the page opens its find row on ⌘F; once open, the field takes ⌘F itself (one publisher, R-SU10).
        // Published from a leaf, never the page: `PageFindPublisher` is an if/else, so on the page it rebuilt the whole
        // column tree on every flip of `findOpen` — the open card's trail and body, the Reader, the scroll position and
        // a landing's scroll-to all lost (DS-3c final review).
        .background { Color.clear.publishesPageFind(enabled: !findOpen) { findOpen = true } }
        .onChange(of: findOpen) { _, isOpen in if !isOpen { query = "" } }
        .onAppear { openPendingEntity(); arrive() }
        .onChange(of: router.pendingClustersEntity) { _, _ in openPendingEntity() }
        .onChange(of: graphVM.entities.map(\.id)) { _, ids in columns.reconcile(present: Set(ids)) }
    }

    // MARK: - Paths (R-DL8: a pointer path may animate, a keyboard path never does — DR-60)

    /// The pointer path: STATE 0 → 1 narrows the list on the drawer curve; a swap in place is instant (DR-61). A Reader
    /// the old card opened closes with it (DR-29: an entity cites no one conversation). The list keeps the keys.
    private func openEntity(_ entity: Entity) {
        let change = {
            columns.open(entity.id)
            if provenance.isPresented { provenance.close() }
        }
        if columns.openId == nil {
            withAnimation(CicadaMotion.columns(reduceMotion: reduceMotion)) { change() }
        } else {
            Instant.run { change() }
        }
        focus = .list
    }

    private func move(_ delta: Int, visible: [Entity]) {
        Instant.run {
            guard let next = columns.neighbour(delta, in: visible.map(\.id)) else { return }
            columns.open(next)
            if provenance.isPresented { provenance.close() }
        }
    }

    /// DR-28 — Esc closes the rightmost open thing.
    private func escape() {
        Instant.run {
            switch columns.escape(readerOpen: provenance.isPresented) {
            case .closeReader: provenance.close()
            case .closeDetail:
                columns.close()
                focus = .list
            case .none: break
            }
        }
    }

    private func closeCard() {
        withAnimation(CicadaMotion.columns(reduceMotion: reduceMotion)) {
            provenance.close()
            columns.close()
        }
        focus = .list
    }

    /// DR-27 — "‹ N entities" brings the list back by closing the Reader, else the card.
    private func showList() {
        withAnimation(CicadaMotion.columns(reduceMotion: reduceMotion)) {
            if provenance.isPresented { provenance.close() } else { columns.close() }
        }
    }

    /// G136 / R-DL12 — a palette ⌥⏎ lands on its card in its type's tab, where the row is always drawn (All's groups
    /// are capped). Read-then-clear, so `onAppear` and `onChange` open it once; an id the graph no longer holds leaves
    /// the page as it was rather than guessing a neighbour.
    private func openPendingEntity() {
        guard let id = router.consumeClustersEntity(),
              let entity = graphVM.entities.first(where: { $0.id == id }) else { return }
        Instant.run {
            findOpen = false
            query = ""
            tab = entity.type
            columns.open(id)
            landingToken &+= 1
        }
    }

    /// R-DL8 — the list takes the keys when the page appears (deferred one turn, R-DL4's reason).
    private func arrive() {
        DispatchQueue.main.async { focus = .list }
    }
}
