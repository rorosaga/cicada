import SwiftUI

/// The Graph page (Direction D, DS-3a; DESIGN_RULES §10 Graph). The canvas fills the content area under the
/// command bar; its chrome is one floating group, the Legend panel, and ⌘F's find overlay. `ContentView` keeps
/// this view mounted under every other tab (opacity 0, no hit testing) so the `WKWebView` — and the zoom the
/// person left it at — survive a tab switch (owner, 2026-09-03).
///
/// A node opens its entity card as the right-hand column (`GraphColumns`, R-DG12) — no scrim; a click on empty
/// canvas or × closes it with its Reader (R-DG7).
///
/// It answers graph.js's page events (R-DG8, R-DG11) through `GraphDismiss`: Esc closes one thing per press and
/// never animates (DR-60); a click on empty canvas is a pointer path.
struct GraphPage: View {
    @Binding var selectedTab: AppTab
    @Environment(GraphViewModel.self) private var graphVM
    /// Track I T5 (R-IA27) — the empty graph takes a dropped export itself.
    @Environment(IntakeRouter.self) private var intake
    @Environment(ProvenanceRouter.self) private var provenance
    @Environment(FindPaletteModel.self) private var palette: FindPaletteModel?
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var legendOpen = false
    @State private var findOpen = false

    private var isVisible: Bool { selectedTab == .graph }

    private var dismissState: GraphDismiss.State {
        GraphDismiss.State(findOpen: findOpen, legendOpen: legendOpen,
                           readerOpen: provenance.isPresented, entityOpen: graphVM.selectedEntity != nil)
    }

    var body: some View {
        GeometryReader { geo in
            let plan = GraphColumns.plan(pageWidth: geo.size.width, scale: CGFloat(CicadaTheme.uiScale),
                                         entityOpen: graphVM.selectedEntity != nil, readerOpen: provenance.isPresented)
            HStack(spacing: 0) {
                canvas(width: plan.canvas, height: geo.size.height)
                // §5.3 — the entity card is the detail column; its evidence opens the Reader beside it (the
                // shell's trailing column, `ShellReaderHost`, which sized itself before this page).
                if let entity = graphVM.selectedEntity {
                    EntityDetailCard(entity: entity, style: .column, onClose: { close() }, onEscape: { escape() })
                        // One card identity per entity: following a wikilink must not reuse A's state under B's name.
                        .id(entity.id)
                        .frame(width: plan.entity, height: geo.size.height)
                        .transition(.opacity)
                }
            }
            .frame(width: geo.size.width, height: geo.size.height, alignment: .topLeading)
        }
        // DR-61 — opening and closing move the canvas's width on the drawer curve; a swap changes neither, so it
        // is instant (DR-29), and Esc runs inside `Instant.run`, whose transaction disables this (DR-60).
        .animation(CicadaMotion.columns(reduceMotion: reduceMotion), value: graphVM.selectedEntity == nil)
        // R-DG5 / R-SU10 — the page takes ⌘F while find is closed; the overlay's field takes it while open.
        .publishesPageFind(enabled: isVisible && !findOpen && !(palette?.isPresented ?? false)) { openFind() }
        .onChange(of: graphVM.canvasEventCount) { _, _ in handle(graphVM.canvasEvent) }
        .onChange(of: selectedTab) { _, tab in
            if tab != .graph { Instant.run { findOpen = false; legendOpen = false } }
        }
        // A node chosen — on the canvas, in find, from ⌘K — closes the floating panels (the mock's `select`).
        .onChange(of: graphVM.selectedEntity?.id) { _, _ in Instant.run { findOpen = false; legendOpen = false } }
    }

    private func canvas(width: CGFloat, height: CGFloat) -> some View {
        let scale = CGFloat(CicadaTheme.uiScale)
        let hasTabs = graphVM.hasObserverDiversity
        let group = GraphChromeLayout.group(canvasWidth: width, scale: scale, hasObserverTabs: hasTabs)
        let inset = CicadaTheme.spacingLG
        let groupHeight = CicadaTheme.scaled(GraphControlGroup.height)
        return ZStack(alignment: .topLeading) {
            GraphView()
                .frame(maxWidth: .infinity, maxHeight: .infinity)

            // G117 — a fresh bank's graph is never a literal blank canvas; `isLoading` gates on an empty cache
            // AND a fetch in flight, so this never flashes over the instant on-disk hydrate.
            if !graphVM.isLoading && graphVM.nodes.isEmpty {
                EmptyStateView(
                    title: "Nothing here yet",
                    message: Copy.emptyGraphMessage,
                    actionLabel: "Open Integrations",
                    settingsSection: .integrations,
                    onDropFiles: { intake.accept(urls: $0, from: .emptyState(.graph)) }
                )
            }

            if group != .hidden {
                GraphControlGroup(showsObserverTabs: group == .full, legendOpen: legendOpen, onToggleLegend: toggleLegend)
                    .padding(inset)
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottomLeading)
                if legendOpen {
                    GraphLegendPanel(showsObserverTabs: GraphChromeLayout.tabsInPanel(group, hasObserverTabs: hasTabs),
                                     maxHeight: max(height - groupHeight - inset * 3, 0))
                        .padding(.leading, inset)
                        .padding(.bottom, inset + groupHeight + CicadaTheme.spacingSM)
                        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottomLeading)
                }
            }

            if findOpen {
                GraphFindOverlay(isActive: isVisible, close: { findOpen = false })
                    .padding(inset)
            }
        }
        .frame(width: width, height: height)
        .clipped()
    }

    // MARK: - Paths (a pointer path may animate; a keyboard path never does — DR-60)

    /// ⌘F — a keyboard path.
    private func openFind() { Instant.run { legendOpen = false; findOpen = true } }

    /// The column's × — a pointer path: the whole detail closes on the drawer curve (R-DG7).
    private func close() {
        withAnimation(CicadaMotion.columns(reduceMotion: reduceMotion)) { apply(GraphDismiss.close(dismissState)) }
    }

    /// Esc with focus inside the column — the same order as the canvas's (DR-28), never animated.
    private func escape() { Instant.run { apply(GraphDismiss.escape(dismissState)) } }

    /// The Legend button — a pointer path; the find overlay steps aside.
    private func toggleLegend() {
        findOpen = false
        legendOpen.toggle()
    }

    private func handle(_ event: CanvasEvent?) {
        guard isVisible, let event else { return }
        switch event {
        case .escape: Instant.run { apply(GraphDismiss.escape(dismissState)) }
        case .backgroundClicked:
            withAnimation(CicadaMotion.columns(reduceMotion: reduceMotion)) { apply(GraphDismiss.backgroundClick(dismissState)) }
        }
    }

    private func apply(_ action: GraphDismiss.Action) {
        switch action {
        case .closeFind: findOpen = false
        case .closeLegend: legendOpen = false
        case .closePanels: findOpen = false; legendOpen = false
        case .closeReader: provenance.close()
        case .closeEntity: graphVM.clearSelection()
        case .closeEntityAndReader: provenance.close(); graphVM.clearSelection()
        case .none: break
        }
    }
}
