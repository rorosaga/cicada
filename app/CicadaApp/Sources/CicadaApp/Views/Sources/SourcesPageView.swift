import SwiftUI

/// Where the page is: the grid, or one source's page. `@State`, not
/// `@AppStorage` — a relaunch lands on the grid (R15). Cross-page history is
/// G108's decision, not built here.
enum SourcesRoute: Hashable {
    case grid
    case detail(SourceOverview)
}

/// The Sources page (G124) — Activity's successor. Opens on *where memory
/// comes from*: a grid of clickable source cards, then Contributors, then
/// (behind the persisted Advanced toggle, R8 — the same `cicada.usageMode`
/// key the old Mode picker wrote) counts-only stats. No prices, no tokens
/// anywhere on this page — the 2026-09-03 ruling on the G124 row.
/// Every value is a projection over `Store` snapshots; the only on-demand
/// fetches are the per-source drill-downs.
struct SourcesPageView: View {
    /// Entity chip → the app's existing entity navigation (select in the
    /// graph, switch to it), threaded from `ContentView` like Ask citations.
    var onSelectEntity: ((String) -> Void)?

    @Environment(Store.self) private var store
    @Environment(UsageViewModel.self) private var usageVM
    @State private var route: SourcesRoute = .grid
    /// R-S7/R-S9 — the catalog opens HERE. `AddSourceSheet` owns its own state
    /// and reads `Store` from the environment, so a second presenter of it is
    /// not a conflict with the Feed's.
    @State private var showAddSheet = false

    private var rows: [SourceOverview] { SourceOverview.gridOrder(store.sourcesOverview.value ?? []) }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            switch route {
            case .grid:
                PageHeader(title: Copy.sources, subtitle: Copy.sourcesSubtitle) {
                    // R-S7 — the way in lives in the header at ALL times. It
                    // used to exist only inside the empty state, so the moment
                    // one source existed the page that is *about* where memory
                    // comes from offered no way to add another (critique F2).
                    // The Advanced toggle stays beside it for now; rehoming it
                    // is a later slice.
                    HStack(spacing: CicadaTheme.spacingMD) {
                        addSourceButton
                        Toggle("Advanced", isOn: Binding(
                            get: { usageVM.mode == .advanced },
                            set: { usageVM.mode = $0 ? .advanced : .minimal }
                        ))
                        .toggleStyle(.switch).controlSize(.small)
                        .accessibilityLabel("Show advanced read and write statistics")
                    }
                }
                ScrollView {
                    VStack(alignment: .leading, spacing: CicadaTheme.spacingXL) {
                        // R-S10: no `isRefreshing`. The grid never blanks —
                        // it shows last-known-good through a refresh — so a
                        // line that blinked on every SSE version bump was
                        // motion nobody asked for.
                        SourceCardGrid(rows: rows,
                                       hasLoaded: store.sourcesOverview.value != nil) { route = .detail($0) }
                        // R-S6 — the strip carries its own "WHO WROTE YOUR
                        // MEMORY" header, so the page's separate
                        // `sectionHeader("Contributors")` would be the same
                        // label twice, eighteen points apart.
                        ContributorsStrip()
                        if usageVM.mode == .advanced {
                            sectionHeader("Advanced")
                            AdvancedStatsView(onSelectEntity: onSelectEntity)
                        }
                    }
                    .padding(.bottom, CicadaTheme.spacingXL)
                }
            case .detail(let source):
                SourceDetailView(source: source, onBack: { route = .grid }, onSelectEntity: onSelectEntity)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(CicadaTheme.background)
        // R-S9: presented in place, never routed through `AppRouter`'s Feed
        // hand-off — that path stages ONE specific tile (its parameter is a
        // non-optional `AddSourceTile`), where "Add a source" from this page
        // means the catalog root. Bouncing to another tab to show a sheet that
        // works fine here would be a worse answer than presenting it. The name
        // of the rejected method is deliberately absent: the pin in
        // `SourcesV2Tests` greps this file for it, and a comment that mentions
        // it would make the pin unfalsifiable.
        .sheet(isPresented: $showAddSheet) {
            AddSourceSheet(initialTile: nil) { showAddSheet = false }
        }
    }

    private var addSourceButton: some View {
        Button { showAddSheet = true } label: {
            Label("Add a source", systemImage: "plus").labelStyle(.titleAndIcon)
        }
        .buttonStyle(.cicadaGlass(cornerRadius: CicadaTheme.cornerRadiusSmall))
        .help("Add another source of memory")
        .accessibilityLabel("Add a source")
    }

    private func sectionHeader(_ title: String) -> some View {
        Text(title)
            .font(CicadaTheme.headingFont)
            .foregroundStyle(CicadaTheme.textPrimary)
            .padding(.horizontal, CicadaTheme.spacingXL)
    }
}
