import SwiftUI

/// The Sources page (G124) in progressive columns (Direction D, DS-3c; §10). With nothing open it is Sources v2's grid —
/// packed 96 pt tiles, who wrote your memory, Advanced statistics; opening a source or an author narrows the page to a
/// list of rows and opens its detail column; a conversation's Reader is the third column. No prices, no tokens anywhere
/// (the 2026-09-03 G124 ruling); every value is a projection over `Store` snapshots, and the only on-demand fetches are
/// the per-source and per-author drill-downs.
struct SourcesPageView: View {
    /// Entity chip → the app's existing entity navigation, threaded from `ContentView` like Ask citations.
    var onSelectEntity: ((String) -> Void)?

    @Environment(Store.self) private var store
    @Environment(AppRouter.self) private var router
    @Environment(ContributorsViewModel.self) private var contributorsVM
    @Environment(ProvenanceRouter.self) private var provenance
    @AppStorage(ShellMetrics.labelledKey) private var labelledSidebar = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var columns = ListColumns<SourcesSelection>()
    /// R-S7/R-S9 — the catalog ROOT opens here, in place; `AddSourceSheet` owns its own state.
    @State private var showAddSheet = false
    @FocusState private var focus: ListFocus?

    private var rows: [SourceOverview] { SourceOverview.gridOrder(store.sourcesOverview.value ?? []) }

    var body: some View {
        let rows = self.rows
        let sections = SourceSections.group(rows)
        let segments = ContributorShare.segments(contributorsVM.contributors)
        let order = SourcesModel.order(sections: sections,
                                       authors: segments.filter { !$0.isRemainder }.map(\.author))
        let detailOpen = columns.openId.map {
            SourcesModel.present(rows: rows, contributors: contributorsVM.contributors).contains($0)
        } ?? false
        ProgressiveColumns(hasDetail: detailOpen, hasTrailing: provenance.isPresented,
                           navWidth: ShellMetrics.navWidth(labelled: labelledSidebar)) { plan in
            EyebrowRow(eyebrow: SourcesModel.eyebrow(sections: sections, open: detailOpen ? columns.openId : nil),
                       horizontalPadding: !detailOpen && !provenance.isPresented ? plan.gutter : CicadaTheme.spacingXL) {
                // R-S7 / §10 — the way in lives in the eyebrow row at all times, as a neutral button (DR-40).
                NeutralButton(title: "Add a source", systemImage: "plus", size: .compact,
                              help: Copy.Lists.addSourceHelp) { showAddSheet = true }
            }
        } list: { plan in
            if plan.listStyle == .wide {
                SourcesOverviewColumn(rows: rows, hasLoaded: store.sourcesOverview.value != nil,
                                      onOpen: { select($0) }, onSelectEntity: onSelectEntity)
            } else {
                SourcesListColumn(sections: sections, segments: segments, style: plan.listStyle,
                                  selection: columns.openId, open: { select($0) },
                                  move: { move($0, order: order) }, escape: { escape() })
                    .focused($focus, equals: .list)
            }
        } detail: { plan in
            detail(plan, rows: rows, segments: segments)
        } trailing: { _ in
            ReaderColumn().focused($focus, equals: .reader)
        }
        .background(CicadaTheme.bgBase)
        // Presented in place (R-S9): the header means the catalog root, not one staged tile, so no bounce to the Feed.
        .sheet(isPresented: $showAddSheet) {
            AddSourceSheet(initialTile: nil) { showAddSheet = false }
        }
        // Track Z §7.1 — a Sleep spine's "Open in Sources ›" lands here with the tab switch.
        .onAppear { openPendingSource() }
        .onChange(of: router.pendingSourceDetail) { _, _ in openPendingSource() }
        .onChange(of: rows.map(\.id)) { _, _ in reconcile() }
        .onChange(of: contributorsVM.contributors.map(\.author)) { _, _ in reconcile() }
    }

    @ViewBuilder
    private func detail(_ plan: ColumnPlan, rows: [SourceOverview], segments: [ContributorShare.Segment]) -> some View {
        let back = plan.listHidden ? rows.count : nil
        switch columns.openId {
        case .source(let id)?:
            if let source = rows.first(where: { $0.id == id }) {
                // G136 R-SU18 — one identity per source, so a hand-off rebuilds the conversation list.
                SourceDetailView(source: source, hiddenListCount: back, onShowList: { showList() },
                                 onClose: { close() }, onSelectEntity: onSelectEntity)
                    .id(source.id)
                    .focusable()
                    .focusEffectDisabled()
                    .onExitCommand { escape() }
                    .focused($focus, equals: .detail)
            }
        case .contributor(let author)?:
            if let contributor = contributorsVM.contributors.first(where: { $0.author == author }) {
                ContributorDetailColumn(contributor: contributor, share: SourcesModel.share(of: author, in: segments),
                                        hiddenListCount: back, onShowList: { showList() }, onClose: { close() })
                    .id(author)
                    .focusable()
                    .focusEffectDisabled()
                    .onExitCommand { escape() }
                    .focused($focus, equals: .detail)
            }
        case nil:
            EmptyView()
        }
    }

    // MARK: - Paths (R-DL8)

    /// From the grid (STATE 0 → 1) the columns open on the drawer curve; a swap is instant. The list that appears takes
    /// the keys. A Reader the old detail opened closes with it (DR-29).
    private func select(_ selection: SourcesSelection) {
        let change = {
            columns.open(selection)
            if provenance.isPresented { provenance.close() }
        }
        if columns.openId == nil {
            withAnimation(CicadaMotion.columns(reduceMotion: reduceMotion)) { change() }
        } else {
            Instant.run { change() }
        }
        DispatchQueue.main.async { focus = .list }
    }

    private func move(_ delta: Int, order: [SourcesSelection]) {
        Instant.run {
            guard let next = columns.neighbour(delta, in: order) else { return }
            columns.open(next)
            if provenance.isPresented { provenance.close() }
        }
    }

    /// DR-28 — the Reader, then the detail (back to the grid).
    private func escape() {
        Instant.run {
            switch columns.escape(readerOpen: provenance.isPresented) {
            case .closeReader: provenance.close()
            case .closeDetail: columns.close()
            case .none: break
            }
        }
    }

    private func close() {
        withAnimation(CicadaMotion.columns(reduceMotion: reduceMotion)) {
            provenance.close()
            columns.close()
        }
    }

    private func showList() {
        withAnimation(CicadaMotion.columns(reduceMotion: reduceMotion)) {
            if provenance.isPresented { provenance.close() } else { columns.close() }
        }
    }

    private func reconcile() {
        columns.reconcile(present: SourcesModel.present(rows: rows, contributors: contributorsVM.contributors))
    }

    /// Track Z §7.1 — a source id that no longer resolves leaves the grid showing rather than guessing a neighbour.
    private func openPendingSource() {
        guard let id = router.consumeSourceDetail(), rows.contains(where: { $0.id == id }) else { return }
        Instant.run { columns.open(.source(id)) }
    }
}
