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

    private var rows: [SourceOverview] { SourceOverview.gridOrder(store.sourcesOverview.value ?? []) }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            switch route {
            case .grid:
                PageHeader(title: Copy.sources, subtitle: Copy.sourcesSubtitle) {
                    Toggle("Advanced", isOn: Binding(
                        get: { usageVM.mode == .advanced },
                        set: { usageVM.mode = $0 ? .advanced : .minimal }
                    ))
                    .toggleStyle(.switch).controlSize(.small)
                    .accessibilityLabel("Show advanced read and write statistics")
                }
                ScrollView {
                    VStack(alignment: .leading, spacing: CicadaTheme.spacingXL) {
                        SourceCardGrid(rows: rows, hasLoaded: store.sourcesOverview.value != nil,
                                       isRefreshing: store.sourcesOverview.isRefreshing) { route = .detail($0) }
                        sectionHeader("Contributors")
                        ContributorsSection()
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
    }

    private func sectionHeader(_ title: String) -> some View {
        Text(title)
            .font(CicadaTheme.headingFont)
            .foregroundStyle(CicadaTheme.textPrimary)
            .padding(.horizontal, CicadaTheme.spacingXL)
    }
}
