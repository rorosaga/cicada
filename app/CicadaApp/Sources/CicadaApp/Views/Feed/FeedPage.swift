import SwiftUI

/// §10 Feed in progressive columns (Direction D, DS-3c; DR-25, DR-31, DR-45, DR-46, DR-68). With nothing open, every
/// saved item at full width under the Connected strip; a click opens the item beside a triage column; the Reader, if
/// open, is the third column. It replaced `FeedView`, whose non-scrolling stack of bands — a page header, the strips,
/// the search row and a count line, over a centring layer with a floating `+` — drew its own header under the titlebar
/// on the demo bank (R-DL17). The eyebrow is now the only fixed band. (`FeedLayoutPinTests` greps this file: keep the
/// words it refuses out of comments too.)
struct FeedPage: View {
    @Environment(FeedViewModel.self) private var viewModel
    /// G126 R9 — Settings → Integrations' "Import in Feed →" hand-off, and the palette's saved item (R-DL16).
    @Environment(AppRouter.self) private var router
    @Environment(ProvenanceRouter.self) private var provenance
    @AppStorage(ShellMetrics.labelledKey) private var labelledSidebar = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var showAddSheet = false
    @State private var sheetTile: AddSourceTile?
    @State private var findOpen = false
    @State private var landingToken = 0
    @FocusState private var focus: ListFocus?

    private var searching: Bool { findOpen && !QuickMatch.tokens(viewModel.searchText).isEmpty }

    private var kindSelection: Binding<FeedKind?> {
        Binding(get: { viewModel.kind }, set: { newKind in
            Instant.run {
                viewModel.setKind(newKind)
                findOpen = false
            }
        })
    }

    var body: some View {
        ProgressiveColumns(hasDetail: viewModel.openItem != nil, hasTrailing: provenance.isPresented,
                           navWidth: ShellMetrics.navWidth(labelled: labelledSidebar)) { plan in
            EyebrowRow(eyebrow: viewModel.eyebrow(searching: searching),
                       horizontalPadding: viewModel.openItem == nil && !provenance.isPresented
                           ? plan.gutter : CicadaTheme.spacingXL) {
                HStack(spacing: CicadaTheme.spacingXS) {
                    // R-DL13 — one sort is always on: re-tapping the active one keeps it.
                    TextTabs(tabs: [TextTab(id: FeedViewModel.SortMode.relevance, label: Copy.Lists.relevance),
                                    TextTab(id: FeedViewModel.SortMode.recent, label: Copy.Lists.recent)],
                             selection: Binding(get: { viewModel.sort }, set: { viewModel.sort = $0 ?? viewModel.sort }))
                        .accessibilityLabel(Copy.Lists.sortFeed)
                    AdaptiveTextTabs(tabs: viewModel.kindTabs, selection: kindSelection, menuTitle: Copy.Lists.kind)
                        .padding(.leading, CicadaTheme.scaled(14))
                    PageFindButton(isOpen: $findOpen).padding(.leading, CicadaTheme.spacingSM)
                    // R-DL14 — the one-shot import's door (G126), a plain icon in the eyebrow, and ⌘N's only home.
                    IconButton(systemName: "plus", help: Copy.Lists.addSourceShortcut,
                               accessibilityLabel: Copy.addASource,
                               shortcut: KeyboardShortcut("n", modifiers: .command)) { openSheet(nil) }
                }
            }
        } list: { plan in
            FeedListColumn(style: plan.listStyle, findOpen: $findOpen, searching: searching, landingToken: landingToken,
                           open: { open($0) }, move: { move($0) }, focusDetail: { focus = .detail },
                           escape: { escape() }, openSheet: { openSheet($0) })
                .focused($focus, equals: .list)
        } detail: { plan in
            if let item = viewModel.openItem {
                ScrollView {
                    FeedItemDetail(item: item, padding: plan.cardPadding,
                                   hiddenListCount: plan.listHidden ? viewModel.visible.count : nil,
                                   onShowList: { showList() }, onClose: { closeItem() })
                        .frame(maxWidth: .infinity)
                        .padding(.horizontal, plan.gutter)
                        .padding(.bottom, CicadaTheme.scaled(72))
                }
                .id(item.id)
                .focusable()
                .focusEffectDisabled()
                .onExitCommand { escape() }
                .focused($focus, equals: .detail)
            }
        } trailing: { _ in
            ReaderColumn().focused($focus, equals: .reader)
        }
        .background(CicadaTheme.bgBase)
        .publishesPageFind(enabled: !findOpen) { findOpen = true }
        .onChange(of: findOpen) { _, isOpen in if !isOpen { viewModel.searchText = "" } }
        .sheet(isPresented: $showAddSheet) {
            AddSourceSheet(initialTile: sheetTile) { showAddSheet = false }
        }
        // A hand-off can arrive while the Feed is on screen (`onChange`) or as it appears (`onAppear`); each consumer
        // reads then clears, so a second firing is a no-op.
        .onAppear { consumePendingAddSource(); consumeLanding(); viewModel.reconcile(); arrive() }
        .onChange(of: router.pendingAddSource) { _, _ in consumePendingAddSource() }
        .onChange(of: router.pendingFeedItem) { _, _ in consumeLanding() }
        .onChange(of: viewModel.items.map(\.id)) { _, _ in viewModel.reconcile() }
    }

    // MARK: - Paths (R-DL8)

    private func open(_ item: MediaFeedItem) {
        let change = {
            viewModel.columns.open(item.id)
            if provenance.isPresented { provenance.close() }
        }
        if viewModel.columns.openId == nil {
            withAnimation(CicadaMotion.columns(reduceMotion: reduceMotion)) { change() }
        } else {
            Instant.run { change() }
        }
        focus = .list
    }

    private func move(_ delta: Int) {
        Instant.run {
            guard let next = viewModel.columns.neighbour(delta, in: viewModel.visible.map(\.id)) else { return }
            viewModel.columns.open(next)
            if provenance.isPresented { provenance.close() }
        }
    }

    private func escape() {
        Instant.run {
            switch viewModel.columns.escape(readerOpen: provenance.isPresented) {
            case .closeReader: provenance.close()
            case .closeDetail:
                viewModel.columns.close()
                focus = .list
            case .none: break
            }
        }
    }

    private func closeItem() {
        withAnimation(CicadaMotion.columns(reduceMotion: reduceMotion)) {
            provenance.close()
            viewModel.columns.close()
        }
        focus = .list
    }

    private func showList() {
        withAnimation(CicadaMotion.columns(reduceMotion: reduceMotion)) {
            if provenance.isPresented { provenance.close() } else { viewModel.columns.close() }
        }
    }

    private func openSheet(_ tile: AddSourceTile?) {
        sheetTile = tile
        showAddSheet = true
    }

    private func consumePendingAddSource() {
        guard let tile = router.consumeAddSource() else { return }
        openSheet(tile)
    }

    /// R-DL16 / DR-30 — a landed item opens in All, scrolled into view; a keyboard-free path, so it never animates.
    private func consumeLanding() {
        guard let id = router.consumeFeedItem() else { return }
        Instant.run {
            findOpen = false
            if viewModel.land(mediaEntityId: id) { landingToken &+= 1 }
        }
    }

    private func arrive() {
        DispatchQueue.main.async { focus = .list }
    }
}
